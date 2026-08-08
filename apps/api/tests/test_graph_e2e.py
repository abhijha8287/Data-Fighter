"""End-to-end test of the 11-node graph against the real fixture data,
exercising the checkpoint/resume boundary the FastAPI endpoints rely on.

Uses the real MockDataHubClient (fixture-backed) and the real sql_fix
transform/validation logic. Only the GitHub network calls and the LLM call
are faked — this validates that everything in between (blast radius calc,
root-cause grounding, SQL transform, validation) works against real data,
which is the thing most worth protecting with a test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.graph import compile_graph, sqlite_checkpointer
from app.config import settings
from app.datahub.client import CachingDataHubClient, DataHubUnavailableError
from app.datahub.mock import MockDataHubClient
from app.incidents.state import IncidentStatus

ANALYTICS_CUSTOMERS = "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customers,PROD)"


class FakeGitHubService:
    """Reads real content from the fixture directory (so search_code and
    get_file_content exercise real file I/O against real SQL), but never
    hits the network for branch/commit/PR creation."""

    def __init__(self, fixture_dir: Path) -> None:
        self._dir = fixture_dir
        self.created_branches: list[str] = []
        self.updated_files: dict[str, str] = {}
        self.pr_created = False

    async def search_code(self, query: str) -> list[dict]:
        matches = []
        for sql_file in sorted(self._dir.glob("*.sql")):
            content = sql_file.read_text()
            if query in content:
                for line in content.splitlines():
                    if query in line:
                        matches.append({"path": sql_file.name, "matched_line": line.strip()})
                        break
        return matches

    async def get_file_content(self, path: str, ref: str | None = None) -> str:
        return (self._dir / path).read_text()

    async def create_branch(self, name: str, base: str | None = None) -> str:
        self.created_branches.append(name)
        return name

    async def update_file(self, path: str, content: str, branch: str, message: str) -> dict:
        self.updated_files[path] = content
        return {"path": path, "commit_sha": "fakesha"}

    async def create_pull_request(self, title: str, body: str, head: str, base: str | None = None) -> str:
        self.pr_created = True
        self._pr_body = body
        return "https://github.com/acme/demo-repo/pull/1"


class FailingGitHubService(FakeGitHubService):
    async def create_pull_request(self, title: str, body: str, head: str, base: str | None = None) -> str:
        from app.github.service import GitHubServiceError

        raise GitHubServiceError("simulated rate limit")


async def fake_llm_generate(prompt: str) -> str:
    return "The customer_email column was removed and is still referenced downstream."


def _thread_config(incident_id: str) -> dict:
    return {"configurable": {"thread_id": incident_id}}


@pytest.fixture
def datahub():
    return CachingDataHubClient(MockDataHubClient(settings.fixture_dir))


@pytest.fixture
def github():
    return FakeGitHubService(settings.fixture_dir)


async def test_full_happy_path_resolves_incident(datahub, github, tmp_path):
    db_path = str(tmp_path / "checkpoints.db")
    async with sqlite_checkpointer(db_path) as checkpointer:
        graph = compile_graph(datahub, github, fake_llm_generate, checkpointer)
        incident_id = "test-incident-1"
        config = _thread_config(incident_id)

        initial_state = {
            "incident_id": incident_id,
            "dataset_urn": ANALYTICS_CUSTOMERS,
            "incident_type": "column_deleted",
            "incident_description": "customer_email deleted",
            "affected_column": "customer_email",
        }

        # /incidents/demo — runs detect_incident, pauses.
        state = await graph.ainvoke(initial_state, config=config)
        assert state["status"] == IncidentStatus.DETECTED

        # /investigate — resumes, runs fetch_context..investigate_root_cause, pauses.
        state = await graph.ainvoke(None, config=config)
        assert state["status"] == IncidentStatus.INVESTIGATED
        assert state["blast_radius"]["total_count"] == 6
        assert state["blast_radius"]["pipelines"] == 3
        assert state["blast_radius"]["dashboards"] == 2
        assert state["blast_radius"]["ml_models"] == 1
        assert set(state["affected_owners"]) == {"Data Engineering", "Analytics Engineering", "ML Platform"}
        assert set(state["affected_files"]) == {
            "customer_metrics.sql",
            "customer_segmentation.sql",
            "customer_features.sql",
        }

        # /remediate — resumes, runs generate_fix..validate_fix, pauses.
        state = await graph.ainvoke(None, config=config)
        assert state["status"] == IncidentStatus.REMEDIATED
        assert state["validation_result"]["passed"] is True
        assert set(state["proposed_fix"]["files"].keys()) == set(state["affected_files"])
        for content in state["proposed_fix"]["files"].values():
            assert "customer_email" not in content

        # /create-pr — resumes, runs create_pull_request..write_back_to_datahub, graph ends.
        state = await graph.ainvoke(None, config=config)
        assert state["status"] == IncidentStatus.RESOLVED
        assert state["github_pr_url"] == "https://github.com/acme/demo-repo/pull/1"
        assert state["incident_report"]["resolved_at"] is not None
        assert state["datahub_write_back"]["attempted"] is True
        # Mock DataHub write-back always returns False (DATAHUB_MUTATION_ENABLED
        # defaults to false) — resolution must not depend on it succeeding.
        assert state["datahub_write_back"]["succeeded"] is False

        assert github.created_branches == [f"data-firefighter/{incident_id}"]
        assert set(github.updated_files.keys()) == set(state["affected_files"])
        assert github.pr_created is True


async def test_pr_creation_failure_does_not_crash_graph(datahub, tmp_path):
    github = FailingGitHubService(settings.fixture_dir)
    db_path = str(tmp_path / "checkpoints.db")
    async with sqlite_checkpointer(db_path) as checkpointer:
        graph = compile_graph(datahub, github, fake_llm_generate, checkpointer)
        incident_id = "test-incident-fail-pr"
        config = _thread_config(incident_id)
        initial_state = {
            "incident_id": incident_id,
            "dataset_urn": ANALYTICS_CUSTOMERS,
            "incident_type": "column_deleted",
            "incident_description": "customer_email deleted",
            "affected_column": "customer_email",
        }

        await graph.ainvoke(initial_state, config=config)
        await graph.ainvoke(None, config=config)  # investigate
        await graph.ainvoke(None, config=config)  # remediate
        state = await graph.ainvoke(None, config=config)  # create-pr (fails)

        assert state["status"] == IncidentStatus.FAILED
        assert state["github_pr_url"] is None
        assert "PR creation failed" in state["error"]
        # The workflow did not silently stop — it still produced a report.
        assert state["incident_report"] is not None
        assert state["incident_report"]["resolved_at"] is None


class UnreachableDataHubClient:
    """Simulates DATAHUB_MODE=real with the GMS unreachable — every read
    raises, per the design doc's Architecture decision #2."""

    async def get_dataset(self, urn: str) -> dict:
        raise DataHubUnavailableError("connection refused")

    async def get_schema(self, urn: str, *, before_incident: bool = False):
        raise DataHubUnavailableError("connection refused")

    async def get_lineage(self, urn: str, direction: str = "DOWNSTREAM", hops: int = 5):
        raise DataHubUnavailableError("connection refused")

    async def get_lineage_paths_between(self, source_urn: str, dest_urn: str):
        raise DataHubUnavailableError("connection refused")

    async def get_owners(self, urn: str):
        raise DataHubUnavailableError("connection refused")

    async def search_datasets(self, query: str):
        raise DataHubUnavailableError("connection refused")

    async def get_dataset_queries(self, urn: str):
        raise DataHubUnavailableError("connection refused")

    async def add_incident_note(self, urn: str, note: str) -> bool:
        return False


async def test_datahub_unreachable_fails_cleanly_no_silent_mock_fallback(github, tmp_path):
    db_path = str(tmp_path / "checkpoints.db")
    async with sqlite_checkpointer(db_path) as checkpointer:
        graph = compile_graph(UnreachableDataHubClient(), github, fake_llm_generate, checkpointer)
        incident_id = "test-incident-datahub-down"
        config = _thread_config(incident_id)
        initial_state = {
            "incident_id": incident_id,
            "dataset_urn": ANALYTICS_CUSTOMERS,
            "incident_type": "column_deleted",
            "incident_description": "customer_email deleted",
            "affected_column": "customer_email",
        }

        await graph.ainvoke(initial_state, config=config)  # detect_incident, pauses
        state = await graph.ainvoke(None, config=config)  # fetch_context fails

        assert state["status"] == IncidentStatus.FAILED
        assert "DataHub unreachable" in state["error"]
        # No blast radius / lineage should have been silently fabricated.
        assert state.get("blast_radius") is None
        assert state.get("downstream_assets") is None


async def test_empty_blast_radius_still_produces_report(github, tmp_path):
    """A dataset with no downstream lineage should still produce a report
    stating so, not error out — per the design doc's failure-mode contract."""
    from app.datahub.mock import MockDataHubClient as _Mock

    class NoDownstreamDataHubClient(_Mock):
        async def get_lineage(self, urn: str, direction: str = "DOWNSTREAM", hops: int = 5):
            return {"assets": []}

    datahub = NoDownstreamDataHubClient(settings.fixture_dir)
    db_path = str(tmp_path / "checkpoints.db")
    async with sqlite_checkpointer(db_path) as checkpointer:
        graph = compile_graph(datahub, github, fake_llm_generate, checkpointer)
        incident_id = "test-incident-empty-blast"
        config = _thread_config(incident_id)
        initial_state = {
            "incident_id": incident_id,
            "dataset_urn": ANALYTICS_CUSTOMERS,
            "incident_type": "column_deleted",
            "incident_description": "customer_email deleted",
            "affected_column": "customer_email",
        }

        await graph.ainvoke(initial_state, config=config)
        state = await graph.ainvoke(None, config=config)

        assert state["status"] == IncidentStatus.INVESTIGATED
        assert state["blast_radius"]["total_count"] == 0
        assert state["blast_radius"]["owners"] == []
