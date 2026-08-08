"""Golden-file eval for the two reasoning-adjacent nodes (investigate_root_cause,
generate_fix), per the design doc's Test Review decision: a minimal,
assertion-based eval (not semantic scoring) that catches a prompt/logic
regression before a demo, not a full graded-rubric framework.

Each scenario runs the real nodes against the real fixture data with a fake
LLM (deterministic, not a real API call — the SQL transform itself is
deterministic per app/agents/sql_fix.py; only the explanation text is
LLM-authored, and these scenarios assert facts about *structure*, not prose
quality, so a canned fake is the right tool here) and asserts the exact
file/column/branch the design doc calls out as the regression risk worth
protecting.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_graph_e2e import FakeGitHubService, fake_llm_generate  # noqa: E402

from app.agents.nodes import Nodes
from app.config import settings
from app.datahub.client import CachingDataHubClient
from app.datahub.mock import MockDataHubClient
from app.incidents.state import IncidentStatus

ANALYTICS_CUSTOMERS = "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customers,PROD)"


@pytest.fixture
def nodes() -> Nodes:
    datahub = CachingDataHubClient(MockDataHubClient(settings.fixture_dir))
    github = FakeGitHubService(settings.fixture_dir)
    return Nodes(datahub=datahub, github=github, llm_generate=fake_llm_generate)


async def _investigated_state(nodes: Nodes) -> dict:
    """Runs the real chain up through investigate_root_cause — every
    scenario needs this as a starting point since root cause depends on
    lineage already being traced."""
    state: dict = {
        "incident_id": "golden-eval",
        "dataset_urn": ANALYTICS_CUSTOMERS,
        "incident_type": "column_deleted",
        "incident_description": "customer_email deleted",
        "affected_column": "customer_email",
    }
    state.update(await nodes.detect_incident(state))
    state.update(await nodes.fetch_context(state))
    state.update(await nodes.trace_lineage(state))
    state.update(await nodes.analyze_blast_radius(state))
    state.update(await nodes.identify_owners(state))
    state.update(await nodes.investigate_root_cause(state))
    return state


@pytest.mark.parametrize(
    "expected_file",
    ["customer_metrics.sql", "customer_segmentation.sql", "customer_features.sql"],
)
async def test_golden_each_downstream_file_flagged_and_fixed(nodes: Nodes, expected_file: str):
    """Golden scenario: each of the 3 real downstream files that reference
    customer_email is (a) flagged by investigate_root_cause and (b) fixed
    by generate_fix with the column fully removed and branch_taken=removal."""
    state = await _investigated_state(nodes)
    assert state["status"] == IncidentStatus.INVESTIGATED.value
    assert expected_file in state["root_cause"]["affected_files"]
    assert expected_file in state["affected_files"]

    state.update(await nodes.generate_fix(state))
    assert state["proposed_fix"]["branch_taken"] == "removal"
    assert expected_file in state["proposed_fix"]["files"]
    assert "customer_email" not in state["proposed_fix"]["files"][expected_file]

    state.update(await nodes.validate_fix(state))
    assert state["validation_result"]["passed"] is True


async def test_golden_upstream_files_never_flagged_as_affected(nodes: Nodes):
    """Regression test: raw_customers.sql and staging_customers.sql both
    contain the literal text "customer_email" (they're upstream of the
    incident, not broken by it) — a naive text search over the whole repo
    would wrongly flag them. investigate_root_cause must cross-reference
    against the known downstream lineage and exclude them."""
    state = await _investigated_state(nodes)
    assert "raw_customers.sql" not in state["affected_files"]
    assert "staging_customers.sql" not in state["affected_files"]
    assert "analytics_customers.sql" not in state["affected_files"]


async def test_golden_confidence_is_high_when_files_found(nodes: Nodes):
    state = await _investigated_state(nodes)
    assert state["root_cause"]["confidence"] >= 0.9


async def test_golden_nonexistent_column_produces_no_fix_needed(nodes: Nodes):
    """Golden scenario: a column that appears nowhere downstream should
    produce zero affected files and generate_fix's no_fix_needed branch —
    not a fabricated fix for a file that was never actually broken."""
    state: dict = {
        "incident_id": "golden-eval-no-match",
        "dataset_urn": ANALYTICS_CUSTOMERS,
        "incident_type": "column_deleted",
        "incident_description": "a column that doesn't exist anywhere was deleted",
        "affected_column": "totally_nonexistent_column_xyz",
    }
    state.update(await nodes.detect_incident(state))
    state.update(await nodes.fetch_context(state))
    state.update(await nodes.trace_lineage(state))
    state.update(await nodes.analyze_blast_radius(state))
    state.update(await nodes.identify_owners(state))
    state.update(await nodes.investigate_root_cause(state))

    assert state["affected_files"] == []
    assert state["root_cause"]["confidence"] < 0.5

    state.update(await nodes.generate_fix(state))
    assert state["proposed_fix"]["branch_taken"] == "no_fix_needed"
    assert state["proposed_fix"]["files"] == {}
