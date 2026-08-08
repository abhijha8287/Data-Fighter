"""App-lifespan-scoped dependencies: the compiled graph (with its
checkpointer), DataHubClient, and GitHubService are built once at startup
and reused across requests — not rebuilt per-request."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.agents.graph import compile_graph
from app.agents.llm import generate as llm_generate
from app.config import settings
from app.datahub.client import DataHubClient
from app.datahub.factory import build_datahub_client
from app.github.service import GitHubService


@dataclass
class AppState:
    datahub: DataHubClient
    github: GitHubService | None
    graph: object  # CompiledStateGraph — left untyped to avoid a hard
                    # langgraph import here; see app/agents/graph.py


def build_app_state(checkpointer) -> AppState:
    datahub = build_datahub_client()
    github = (
        GitHubService(settings.github_token, settings.github_demo_repo)
        if settings.github_token and settings.github_demo_repo
        else None
    )
    graph = compile_graph(datahub, github, llm_generate, checkpointer)
    return AppState(datahub=datahub, github=github, graph=graph)


def get_app_state(request: Request) -> AppState:
    return request.app.state.firefighter


def get_graph(request: Request):
    state: AppState = get_app_state(request)
    if state.github is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "GITHUB_TOKEN and GITHUB_DEMO_REPO must be set to run an incident "
                "(the agent needs a repo to search and open a PR against)."
            ),
        )
    return state.graph
