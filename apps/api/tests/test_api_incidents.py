"""API-level tests: exercise the FastAPI routes (status guards, 404s, 409s)
against the real graph, with the same fixture-backed fakes used in
test_graph_e2e.py standing in for GitHub/LLM so no network or API key is
required."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.agents.graph import compile_graph, sqlite_checkpointer
from app.api.deps import AppState
from app.api.incidents import router as incidents_router
from app.config import settings
from app.datahub.client import CachingDataHubClient
from app.datahub.mock import MockDataHubClient
from tests.test_graph_e2e import FakeGitHubService, fake_llm_generate


@pytest.fixture
async def client(tmp_path):
    app = FastAPI()
    app.include_router(incidents_router)

    db_path = str(tmp_path / "api-checkpoints.db")
    async with sqlite_checkpointer(db_path) as checkpointer:
        datahub = CachingDataHubClient(MockDataHubClient(settings.fixture_dir))
        github = FakeGitHubService(settings.fixture_dir)
        graph = compile_graph(datahub, github, fake_llm_generate, checkpointer)
        app.state.firefighter = AppState(datahub=datahub, github=github, graph=graph)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def test_demo_incident_creates_and_returns_detected_state(client):
    resp = await client.post("/api/incidents/demo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "detected"
    assert body["dataset_urn"].endswith("analytics.customers,PROD)")


async def test_get_unknown_incident_404s(client):
    resp = await client.get("/api/incidents/does-not-exist")
    assert resp.status_code == 404


async def test_remediate_before_investigate_409s(client):
    demo = await client.post("/api/incidents/demo")
    incident_id = demo.json()["incident_id"]

    resp = await client.post(f"/api/incidents/{incident_id}/remediate")
    assert resp.status_code == 409


async def test_create_pr_before_remediate_409s(client):
    demo = await client.post("/api/incidents/demo")
    incident_id = demo.json()["incident_id"]
    await client.post(f"/api/incidents/{incident_id}/investigate")

    resp = await client.post(f"/api/incidents/{incident_id}/create-pr")
    assert resp.status_code == 409


async def test_full_flow_through_api_resolves_incident(client):
    demo = await client.post("/api/incidents/demo")
    incident_id = demo.json()["incident_id"]

    investigate = await client.post(f"/api/incidents/{incident_id}/investigate")
    assert investigate.status_code == 200
    assert investigate.json()["status"] == "investigated"
    assert investigate.json()["blast_radius"]["total_count"] == 6

    remediate = await client.post(f"/api/incidents/{incident_id}/remediate")
    assert remediate.status_code == 200
    assert remediate.json()["status"] == "remediated"

    create_pr = await client.post(f"/api/incidents/{incident_id}/create-pr")
    assert create_pr.status_code == 200
    assert create_pr.json()["status"] == "resolved"
    assert create_pr.json()["github_pr_url"] is not None

    final = await client.get(f"/api/incidents/{incident_id}")
    assert final.json()["status"] == "resolved"

    lineage = await client.get(f"/api/incidents/{incident_id}/lineage")
    assert lineage.status_code == 200
    assert len(lineage.json()["downstream_assets"]) == 6


async def test_non_column_deleted_incident_type_rejected(client):
    resp = await client.post("/api/incidents", json={"incident_type": "column_renamed"})
    assert resp.status_code == 400
