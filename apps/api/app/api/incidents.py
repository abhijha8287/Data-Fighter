"""The 7 incident endpoints. Each one advances the LangGraph state machine
to its next checkpoint via graph.ainvoke(..., thread_id=incident_id) and
returns the resulting IncidentState — see app/agents/graph.py's module
docstring for the full endpoint-to-node mapping.

Demo Mode: POST /incidents/demo hardcodes the column-deletion scenario
against the seeded fixture data (Approach A's flagship, only-wired incident
type — see the design doc's Scope correction). Other incident types are
intentionally not exposed here; the frontend's demo selector disables them
rather than routing to dead logic.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_graph
from app.incidents.state import IncidentStatus

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

ANALYTICS_CUSTOMERS_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customers,PROD)"


def _thread_config(incident_id: str) -> dict:
    return {"configurable": {"thread_id": incident_id}}


async def _current_state(graph, incident_id: str) -> dict:
    snapshot = await graph.aget_state(_thread_config(incident_id))
    if not snapshot.values:
        raise HTTPException(status_code=404, detail=f"incident {incident_id} not found")
    return dict(snapshot.values)


@router.post("/demo")
async def create_demo_incident(graph=Depends(get_graph)):
    """The only incident type wired to real logic in this build: a column
    deletion on analytics.customers. See the design doc's "Scope correction"
    — the other 3 incident types are UI-only, not exposed here."""
    incident_id = str(uuid.uuid4())
    initial_state = {
        "incident_id": incident_id,
        "dataset_urn": ANALYTICS_CUSTOMERS_URN,
        "incident_type": "column_deleted",
        "incident_description": "customer_email was removed from analytics.customers",
        "affected_column": "customer_email",
    }
    state = await graph.ainvoke(initial_state, config=_thread_config(incident_id))
    return state


@router.post("")
async def create_incident(incident: dict, graph=Depends(get_graph)):
    """General incident intake. Requires dataset_urn, incident_type, and
    (for column_deleted incidents) affected_column — the only incident_type
    with real node logic in this build."""
    if incident.get("incident_type") != "column_deleted":
        raise HTTPException(
            status_code=400,
            detail="Only incident_type='column_deleted' is wired to real logic in this build.",
        )
    incident_id = str(uuid.uuid4())
    initial_state = {
        "incident_id": incident_id,
        "dataset_urn": incident.get("dataset_urn"),
        "incident_type": incident.get("incident_type"),
        "incident_description": incident.get("incident_description", ""),
        "affected_column": incident.get("affected_column"),
    }
    state = await graph.ainvoke(initial_state, config=_thread_config(incident_id))
    return state


@router.get("/{incident_id}")
async def get_incident(incident_id: str, graph=Depends(get_graph)):
    return await _current_state(graph, incident_id)


@router.post("/{incident_id}/investigate")
async def investigate_incident(incident_id: str, graph=Depends(get_graph)):
    """Runs fetch_context -> trace_lineage -> analyze_blast_radius ->
    identify_owners -> investigate_root_cause, then pauses."""
    await _current_state(graph, incident_id)  # 404s cleanly if unknown
    state = await graph.ainvoke(None, config=_thread_config(incident_id))
    return state


@router.post("/{incident_id}/remediate")
async def remediate_incident(incident_id: str, graph=Depends(get_graph)):
    """Runs generate_fix -> validate_fix, then pauses. Does NOT touch
    GitHub yet — this is the review-before-acting checkpoint."""
    current = await _current_state(graph, incident_id)
    if current.get("status") != IncidentStatus.INVESTIGATED.value:
        raise HTTPException(
            status_code=409,
            detail=f"incident is in status={current.get('status')!r}; call /investigate first",
        )
    state = await graph.ainvoke(None, config=_thread_config(incident_id))
    return state


@router.post("/{incident_id}/create-pr")
async def create_pr_for_incident(incident_id: str, graph=Depends(get_graph)):
    """Runs create_pull_request -> write_incident_report ->
    write_back_to_datahub. This is the human-approval checkpoint: nothing
    touches GitHub until this endpoint is explicitly called."""
    current = await _current_state(graph, incident_id)
    if current.get("status") != IncidentStatus.REMEDIATED.value:
        raise HTTPException(
            status_code=409,
            detail=f"incident is in status={current.get('status')!r}; call /remediate first",
        )
    state = await graph.ainvoke(None, config=_thread_config(incident_id))
    return state


@router.get("/{incident_id}/lineage")
async def get_incident_lineage(incident_id: str, graph=Depends(get_graph)):
    state = await _current_state(graph, incident_id)
    return {
        "dataset_urn": state.get("dataset_urn"),
        "downstream_assets": state.get("downstream_assets", []),
        "blast_radius": state.get("blast_radius"),
    }
