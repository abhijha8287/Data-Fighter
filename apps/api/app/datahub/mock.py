"""MockDataHubClient — fixture-backed implementation of DataHubClient.

Loads examples/incidents/customer_email_deletion/lineage.json for entities,
lineage edges, schema before/after, and owners. get_dataset_queries() reads
the *actual* .sql files in that same directory rather than duplicating query
text in the JSON — this is the single source of truth the design review
required: the same files this client serves are the files seeded into the
throwaway GitHub demo repo (see scripts/seed_demo_repo.py), so a root-cause
claim grounded in get_dataset_queries() output is provably true against the
real PR, not invented prose.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.datahub.client import DataHubClient
from app.incidents.state import SchemaField


class MockDataHubClient(DataHubClient):
    def __init__(self, fixture_dir: Path) -> None:
        self._dir = fixture_dir
        with (fixture_dir / "lineage.json").open() as f:
            self._data = json.load(f)
        self._entities: dict = self._data["entities"]
        self._edges: list[list[str]] = self._data["lineage_edges"]

    def _downstream_of(self, urn: str) -> list[str]:
        return [dst for src, dst in self._edges if src == urn]

    def _upstream_of(self, urn: str) -> list[str]:
        return [src for src, dst in self._edges if dst == urn]

    async def get_dataset(self, urn: str) -> dict:
        entity = self._entities.get(urn)
        if entity is None:
            raise KeyError(f"Unknown URN in mock fixture: {urn}")
        return {"urn": urn, **entity}

    async def get_schema(self, urn: str, *, before_incident: bool = False) -> list[SchemaField]:
        key = "schema_before" if before_incident else "schema_after"
        return self._data.get(key, {}).get(urn, [])

    async def get_lineage(self, urn: str, direction: str = "DOWNSTREAM", hops: int = 5) -> dict:
        seen: set[str] = set()
        frontier = [urn]
        for _ in range(hops):
            next_frontier: list[str] = []
            for node in frontier:
                neighbors = (
                    self._downstream_of(node)
                    if direction == "DOWNSTREAM"
                    else self._upstream_of(node)
                )
                for n in neighbors:
                    if n not in seen and n != urn:
                        seen.add(n)
                        next_frontier.append(n)
            if not next_frontier:
                break
            frontier = next_frontier
        return {"assets": sorted(seen)}

    async def get_lineage_paths_between(self, source_urn: str, dest_urn: str) -> dict:
        paths: list[list[str]] = []

        def dfs(node: str, target: str, path: list[str]) -> None:
            if node == target:
                paths.append(path[:])
                return
            for nxt in self._downstream_of(node):
                if nxt not in path:
                    dfs(nxt, target, path + [nxt])

        dfs(source_urn, dest_urn, [source_urn])
        return {"paths": paths}

    async def get_owners(self, urn: str) -> list[dict]:
        entity = self._entities.get(urn)
        if entity is None:
            return []
        team = entity.get("owner")
        owner_info = self._data.get("owners", {}).get(team, {"team": team})
        return [owner_info]

    async def search_datasets(self, query: str) -> list[dict]:
        q = query.lower()
        return [
            {"urn": urn, **entity}
            for urn, entity in self._entities.items()
            if q in entity["name"].lower()
        ]

    async def get_dataset_queries(self, urn: str) -> list[str]:
        entity = self._entities.get(urn)
        if entity is None or "sql_file" not in entity:
            return []
        sql_path = self._dir / entity["sql_file"]
        if not sql_path.exists():
            return []
        return [sql_path.read_text()]

    async def add_incident_note(self, urn: str, note: str) -> bool:
        # Mock mode never performs a real write — mirrors the real client's
        # "both flags must be true" gate by always logging what would have
        # been written and returning False. Never fake success.
        print(f"[MockDataHubClient] would write incident note to {urn}:\n{note}")
        return False
