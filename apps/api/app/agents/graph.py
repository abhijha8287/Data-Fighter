"""Builds the 11-node LangGraph state machine.

detect_incident -> fetch_context -> trace_lineage -> analyze_blast_radius ->
identify_owners -> investigate_root_cause -> generate_fix -> validate_fix ->
create_pull_request -> write_incident_report -> write_back_to_datahub

Cross-request state persistence: the graph does not run end-to-end in one
call. It pauses at three checkpoints so the FastAPI layer can map them onto
separate HTTP endpoints (see app/api/incidents.py):

  detect_incident         <-- POST /incidents, /incidents/demo
  ... investigate chain ... <-- POST /incidents/{id}/investigate
  investigate_root_cause  <-- pauses here
  generate_fix, validate_fix <-- POST /incidents/{id}/remediate
  validate_fix             <-- pauses here
  create_pull_request, write_incident_report, write_back_to_datahub
                            <-- POST /incidents/{id}/create-pr

Each endpoint calls graph.ainvoke(..., config={"configurable": {"thread_id":
incident_id}}); the checkpointer (AsyncSqliteSaver, not the in-memory
MemorySaver — see the design doc's outside-voice revision) resumes from the
last pause automatically when the input is None.

Any node in the investigation/remediation/validation chain that sets
status=FAILED routes straight to END instead of continuing — a DataHub or
GitHub failure must not silently keep running. create_pull_request failing
is the one exception: it still flows into write_incident_report and
write_back_to_datahub (see the finalization chain below), since a failed
PR still has real investigation and remediation data worth reporting.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph

from app.agents.llm import LLMGenerate
from app.agents.nodes import Nodes
from app.datahub.client import DataHubClient
from app.github.service import GitHubService
from app.incidents.state import IncidentState, IncidentStatus


def _route_on_status(state: IncidentState) -> str:
    return END if state.get("status") == IncidentStatus.FAILED.value else "__continue__"


def build_graph(datahub: DataHubClient, github: GitHubService, llm_generate: LLMGenerate):
    nodes = Nodes(datahub=datahub, github=github, llm_generate=llm_generate)

    builder = StateGraph(IncidentState)
    builder.add_node("detect_incident", nodes.detect_incident)
    builder.add_node("fetch_context", nodes.fetch_context)
    builder.add_node("trace_lineage", nodes.trace_lineage)
    builder.add_node("analyze_blast_radius", nodes.analyze_blast_radius)
    builder.add_node("identify_owners", nodes.identify_owners)
    builder.add_node("investigate_root_cause", nodes.investigate_root_cause)
    builder.add_node("generate_fix", nodes.generate_fix)
    builder.add_node("validate_fix", nodes.validate_fix)
    builder.add_node("create_pull_request", nodes.create_pull_request)
    builder.add_node("write_incident_report", nodes.write_incident_report)
    builder.add_node("write_back_to_datahub", nodes.write_back_to_datahub)

    builder.set_entry_point("detect_incident")

    # Investigation/remediation/validation chain: a failure here means we
    # don't have trustworthy data to act on or report, so it short-circuits
    # straight to END.
    investigation_chain = [
        "detect_incident",
        "fetch_context",
        "trace_lineage",
        "analyze_blast_radius",
        "identify_owners",
        "investigate_root_cause",
        "generate_fix",
        "validate_fix",
    ]
    for current, nxt in zip(investigation_chain, investigation_chain[1:]):
        builder.add_conditional_edges(current, _route_on_status, {"__continue__": nxt, END: END})
    builder.add_conditional_edges(
        "validate_fix", _route_on_status, {"__continue__": "create_pull_request", END: END}
    )

    # Finalization chain: create_pull_request can itself fail (per the
    # design doc's failure mode — "fix generated, PR creation failed —
    # retry"), but that must still produce an incident report and attempt
    # a write-back, not silently stop. Unconditional edges — no routing on
    # status here.
    builder.add_edge("create_pull_request", "write_incident_report")
    builder.add_edge("write_incident_report", "write_back_to_datahub")
    builder.add_edge("write_back_to_datahub", END)

    return builder


def compile_graph(
    datahub: DataHubClient,
    github: GitHubService,
    llm_generate: LLMGenerate,
    checkpointer,
):
    builder = build_graph(datahub, github, llm_generate)
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_after=["detect_incident", "investigate_root_cause", "validate_fix"],
    )


@asynccontextmanager
async def sqlite_checkpointer(db_path: str) -> AsyncIterator[AsyncSqliteSaver]:
    """Async context manager wrapping AsyncSqliteSaver.from_conn_string —
    used for both the long-lived app (see app/api/deps.py) and short-lived
    test/eval runs. Every node in this graph is async, so the checkpointer
    must be too — the sync SqliteSaver raises NotImplementedError from
    ainvoke()."""
    async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
        yield saver
