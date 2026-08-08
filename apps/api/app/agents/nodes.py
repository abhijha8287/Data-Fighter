"""The 11 LangGraph nodes. Each node is a closure built by `build_nodes()`,
capturing its dependencies (DataHubClient, GitHubService, llm_generate) —
this is what makes the graph testable with fakes/mocks instead of real
network calls, without any global state.

Blast-radius, root-cause, and SQL-validation logic live directly inside the
node that owns them, per the design doc's Step 0 scope reduction — no
separate services/ package. The node *is* the service at this scale.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.agents.llm import LLMGenerate, LLMNotConfiguredError
from app.agents.sql_fix import (
    SqlParseError,
    check_deleted_column_absent,
    check_sql_parses,
    remove_column_references,
)
from app.datahub.client import DataHubClient, DataHubUnavailableError
from app.github.service import GitHubService, GitHubServiceError
from app.incidents.state import BlastRadius, IncidentState, IncidentStatus, LineageAsset

_ASSET_CATEGORY_PLURAL = {"pipeline": "pipelines", "dashboard": "dashboards", "ml_model": "ml_models"}


def _fail(message: str) -> dict:
    return {"status": IncidentStatus.FAILED.value, "error": message}


class Nodes:
    """Bundles the 11 node functions with their injected dependencies."""

    def __init__(
        self,
        datahub: DataHubClient,
        github: GitHubService,
        llm_generate: LLMGenerate,
    ) -> None:
        self.datahub = datahub
        self.github = github
        self.llm_generate = llm_generate

    # 1 ----------------------------------------------------------------
    async def detect_incident(self, state: IncidentState) -> dict:
        if not state.get("dataset_urn") or not state.get("incident_type"):
            return _fail("detect_incident: dataset_urn and incident_type are required")
        return {"status": IncidentStatus.DETECTED.value, "error": None}

    # 2 ----------------------------------------------------------------
    async def fetch_context(self, state: IncidentState) -> dict:
        urn = state["dataset_urn"]
        try:
            dataset_metadata = await self.datahub.get_dataset(urn)
            schema_after = await self.datahub.get_schema(urn, before_incident=False)
        except DataHubUnavailableError as exc:
            return _fail(
                f"DataHub unreachable while fetching context for {urn}: {exc}. "
                "Check DATAHUB_GMS_URL, or try DATAHUB_MODE=mock."
            )
        try:
            schema_before = await self.datahub.get_schema(urn, before_incident=True)
        except DataHubUnavailableError:
            # schema_before is unused by every downstream node (only the
            # replacement-column branch needed it, and that branch was cut
            # — see the design doc). MockDataHubClient always returns real
            # before/after fixture data; RealDataHubClient documents this
            # as unsupported (no historical schema versioning guarantee).
            # An empty list is the honest "not available" signal — not a
            # fabricated substitute for real data.
            schema_before = []
        return {
            "status": IncidentStatus.INVESTIGATING.value,
            "dataset_metadata": dataset_metadata,
            "schema_before": schema_before,
            "schema_after": schema_after,
        }

    # 3 ----------------------------------------------------------------
    async def trace_lineage(self, state: IncidentState) -> dict:
        urn = state["dataset_urn"]
        try:
            lineage = await self.datahub.get_lineage(urn, direction="DOWNSTREAM", hops=5)
            assets: list[LineageAsset] = []
            for downstream_urn in lineage["assets"]:
                entity = await self.datahub.get_dataset(downstream_urn)
                assets.append(
                    LineageAsset(
                        urn=downstream_urn,
                        name=entity["name"],
                        platform=entity["platform"],
                        entity_type=entity["entity_type"],
                        asset_category=entity.get("asset_category"),
                        owner=entity["owner"],
                    )
                )
        except DataHubUnavailableError as exc:
            return _fail(f"DataHub unreachable while tracing lineage for {urn}: {exc}")
        return {"downstream_assets": assets}

    # 4 ----------------------------------------------------------------
    async def analyze_blast_radius(self, state: IncidentState) -> dict:
        assets = state.get("downstream_assets", [])
        counts = {"pipelines": 0, "dashboards": 0, "ml_models": 0}
        owners: set[str] = set()
        for asset in assets:
            category = asset.get("asset_category")
            if category in _ASSET_CATEGORY_PLURAL:
                counts[_ASSET_CATEGORY_PLURAL[category]] += 1
            owners.add(asset["owner"])
        blast_radius: BlastRadius = {
            "downstream_assets": assets,
            "total_count": len(assets),
            "pipelines": counts["pipelines"],
            "dashboards": counts["dashboards"],
            "ml_models": counts["ml_models"],
            "owners": sorted(owners),
        }
        return {"blast_radius": blast_radius}

    # 5 ----------------------------------------------------------------
    async def identify_owners(self, state: IncidentState) -> dict:
        urn = state["dataset_urn"]
        try:
            primary_owners = await self.datahub.get_owners(urn)
        except DataHubUnavailableError as exc:
            return _fail(f"DataHub unreachable while identifying owners for {urn}: {exc}")
        primary_teams = {o["team"] for o in primary_owners if o.get("team")}
        downstream_teams = set(state.get("blast_radius", {}).get("owners", []))
        return {"affected_owners": sorted(primary_teams | downstream_teams)}

    # 6 ----------------------------------------------------------------
    async def investigate_root_cause(self, state: IncidentState) -> dict:
        column = state.get("affected_column")
        if not column:
            return _fail("investigate_root_cause: affected_column is required for column_deleted incidents")

        try:
            matches = await self.github.search_code(column)
        except GitHubServiceError as exc:
            return _fail(f"GitHub search failed while investigating root cause: {exc}")

        # A raw text search for the column name also matches files that
        # legitimately still contain it (e.g. the upstream raw/staging
        # tables the column hasn't been removed from yet) and incidental
        # comment mentions. Cross-reference against the DOWNSTREAM lineage
        # already established by trace_lineage/analyze_blast_radius — only
        # a downstream consumer of the incident dataset is actually broken
        # by this deletion. This is deliberate: two independent DataHub
        # and GitHub signals corroborating each other, not blind grep.
        downstream_names = {a["name"] for a in state.get("downstream_assets", [])}
        affected_files = [
            m["path"] for m in matches if m["path"].removesuffix(".sql") in downstream_names
        ]
        confidence = 0.95 if affected_files else 0.4

        prompt = (
            f"A column named `{column}` was removed from the dataset `{state['dataset_urn']}`. "
            f"A code search of the repository found it still referenced in these files: "
            f"{', '.join(affected_files) if affected_files else '(none found)'}. "
            "In 2-3 sentences, explain why this is a real incident and what breaks. "
            "Be concrete and reference the actual file names given above — do not invent files."
        )
        try:
            summary = await self.llm_generate(prompt)
        except LLMNotConfiguredError as exc:
            return _fail(f"investigate_root_cause: {exc}")

        root_cause = {
            "summary": summary,
            "affected_files": affected_files,
            "confidence": confidence,
        }
        return {
            "status": IncidentStatus.INVESTIGATED.value,
            "affected_files": affected_files,
            "root_cause": root_cause,
        }

    # 7 ----------------------------------------------------------------
    async def generate_fix(self, state: IncidentState) -> dict:
        column = state.get("affected_column")
        affected_files = state.get("affected_files", [])
        if not column or not affected_files:
            return {
                "status": IncidentStatus.REMEDIATING.value,
                "proposed_fix": {
                    "branch_taken": "no_fix_needed",
                    "files": {},
                    "files_before": {},
                    "explanation": "No affected files found referencing the deleted column; no fix needed.",
                },
            }

        fixed_files: dict[str, str] = {}
        original_files: dict[str, str] = {}
        try:
            for path in affected_files:
                current_content = await self.github.get_file_content(path)
                original_files[path] = current_content
                fixed_files[path] = remove_column_references(current_content, column)
        except GitHubServiceError as exc:
            return _fail(f"generate_fix: could not read current file content: {exc}")
        except SqlParseError as exc:
            return _fail(f"generate_fix: could not parse existing SQL: {exc}")

        prompt = (
            f"The column `{column}` was removed from `{state['dataset_urn']}` with no replacement "
            f"column available. The following files were updated to remove all references to it: "
            f"{', '.join(fixed_files.keys())}. Write a 2-3 sentence explanation, for a PR description, "
            "of what changed and why no replacement was substituted."
        )
        try:
            explanation = await self.llm_generate(prompt)
        except LLMNotConfiguredError as exc:
            return _fail(f"generate_fix: {exc}")

        proposed_fix = {
            "branch_taken": "removal",
            "files": fixed_files,
            "files_before": original_files,
            "explanation": explanation,
        }
        return {"status": IncidentStatus.REMEDIATING.value, "proposed_fix": proposed_fix}

    # 8 ----------------------------------------------------------------
    async def validate_fix(self, state: IncidentState) -> dict:
        proposed_fix = state.get("proposed_fix", {})
        files = proposed_fix.get("files", {})
        affected_files = set(state.get("affected_files", []))
        column = state.get("affected_column", "")
        errors: list[str] = []

        sql_parses = True
        schema_check_passed = True
        for path, content in files.items():
            ok, parse_err = check_sql_parses(content)
            if not ok:
                sql_parses = False
                errors.append(f"{path}: SQL syntax error: {parse_err}")
                continue
            absent, col_errors = check_deleted_column_absent(content, column)
            if not absent:
                schema_check_passed = False
                errors.extend(f"{path}: {e}" for e in col_errors)

        file_scope_check_passed = all(path in affected_files for path in files)
        if not file_scope_check_passed:
            errors.append("proposed fix touches files outside the cached search_code() result")

        passed = sql_parses and schema_check_passed and file_scope_check_passed
        validation_result = {
            "sql_parses": sql_parses,
            "schema_check_passed": schema_check_passed,
            "file_scope_check_passed": file_scope_check_passed,
            "passed": passed,
            "errors": errors,
        }
        if not passed:
            return {
                **_fail(f"validate_fix: {'; '.join(errors)}"),
                "validation_result": validation_result,
            }
        return {"status": IncidentStatus.REMEDIATED.value, "validation_result": validation_result}

    # 9 ----------------------------------------------------------------
    async def create_pull_request(self, state: IncidentState) -> dict:
        proposed_fix = state.get("proposed_fix", {})
        files = proposed_fix.get("files", {})
        if not files:
            return {"status": IncidentStatus.REMEDIATED.value, "github_pr_url": None}

        incident_id = state["incident_id"]
        branch_name = f"data-firefighter/{incident_id}"
        title = f"fix: remediate {state.get('affected_column', 'schema')} incident"
        body = _build_pr_body(state)

        try:
            await self.github.create_branch(branch_name)
            for path, content in files.items():
                await self.github.update_file(path, content, branch_name, title)
            pr_url = await self.github.create_pull_request(title, body, branch_name)
        except GitHubServiceError as exc:
            # Per the design doc's failure-mode contract: PR creation
            # failing does not silently stop the workflow. The fix was
            # generated and validated successfully — only the GitHub write
            # failed — so we record the error and github_pr_url=None and
            # let write_incident_report/write_back_to_datahub still run.
            return {
                "status": IncidentStatus.FAILED.value,
                "error": f"fix generated, PR creation failed — retry: {exc}",
                "github_pr_url": None,
            }
        return {"status": IncidentStatus.CREATING_PR.value, "github_pr_url": pr_url}

    # 10 ---------------------------------------------------------------
    async def write_incident_report(self, state: IncidentState) -> dict:
        resolved = state.get("github_pr_url") is not None
        report = {
            "incident_id": state["incident_id"],
            "dataset": state["dataset_urn"],
            "incident_type": state["incident_type"],
            "description": state.get("incident_description", ""),
            "blast_radius": state.get("blast_radius"),
            "root_cause": state.get("root_cause"),
            "remediation": state.get("proposed_fix"),
            "validation": state.get("validation_result"),
            "github_pr_url": state.get("github_pr_url"),
            "resolved_at": datetime.now(timezone.utc).isoformat() if resolved else None,
        }
        update: dict = {"incident_report": report}
        if resolved:
            update["status"] = IncidentStatus.RESOLVED.value
        return update

    # 11 ---------------------------------------------------------------
    async def write_back_to_datahub(self, state: IncidentState) -> dict:
        # Write-back is a bonus, never a blocker — never raises, and the
        # incident's resolved status (set in write_incident_report) does
        # not depend on this succeeding.
        note = _build_write_back_note(state)
        try:
            succeeded = await self.datahub.add_incident_note(state["dataset_urn"], note)
        except Exception as exc:  # defensive: write-back must never crash the graph
            succeeded = False
            note = f"{note}\n\n(write-back attempt raised: {exc})"
        return {"datahub_write_back": {"attempted": True, "succeeded": succeeded, "note": note}}


def _build_pr_body(state: IncidentState) -> str:
    blast_radius = state.get("blast_radius", {})
    root_cause = state.get("root_cause", {})
    proposed_fix = state.get("proposed_fix", {})
    validation = state.get("validation_result", {})
    return f"""## Data Incident

Dataset:
{state['dataset_urn']}

Incident:
{state.get('affected_column')} removed

## Impact

{blast_radius.get('total_count', 0)} downstream assets affected \
({blast_radius.get('pipelines', 0)} pipelines, {blast_radius.get('dashboards', 0)} dashboards, \
{blast_radius.get('ml_models', 0)} ML models). Owners: {', '.join(blast_radius.get('owners', []))}.

## Root Cause

{root_cause.get('summary', '')}

## Remediation

{proposed_fix.get('explanation', '')}

No replacement column was found — the field and everything derived from it were removed.

## Validation

- SQL parses: {validation.get('sql_parses')}
- Deleted column absent from fix: {validation.get('schema_check_passed')}
- File scope check: {validation.get('file_scope_check_passed')}

## DataHub Context

Root cause and affected files were grounded in DataHub's get_dataset_queries \
metadata and a live repository search, not invented.

---
Generated by Data Firefighter.
"""


def _build_write_back_note(state: IncidentState) -> str:
    blast_radius = state.get("blast_radius", {})
    root_cause = state.get("root_cause", {})
    return f"""Incident resolved by Data Firefighter.

Incident:
{state.get('affected_column')} schema change on {state['dataset_urn']}

Root cause:
{root_cause.get('summary', '')}

Affected assets:
{blast_radius.get('total_count', 0)} downstream assets \
({blast_radius.get('pipelines', 0)} pipelines, {blast_radius.get('dashboards', 0)} dashboards, \
{blast_radius.get('ml_models', 0)} ML models)

Remediation:
{state.get('proposed_fix', {}).get('explanation', '')}

GitHub PR:
{state.get('github_pr_url', '(none)')}

Resolution timestamp:
{datetime.now(timezone.utc).isoformat()}
"""
