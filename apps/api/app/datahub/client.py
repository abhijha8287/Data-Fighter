"""DataHubClient abstraction.

Two implementations share this interface:
- MockDataHubClient (app/datahub/mock.py) — fixture-backed, always available.
- RealDataHubClient (app/datahub/real.py) — real MCP/REST calls against
  DATAHUB_GMS_URL. Stretch goal (T8); not required for the mock-mode demo.

Selected via DATAHUB_MODE=mock|real (app/datahub/factory.py). Swapping modes
must never require touching any code outside this module and its two
implementations — that boundary is the actual point of the project.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.incidents.state import SchemaField


class DataHubUnavailableError(Exception):
    """Raised when a DataHub read fails (unreachable, timeout, not found).

    Per the design doc: nodes that hit this must fail the incident with a
    clear error state, never silently fall back to mock data.
    """


class DataHubClient(ABC):
    @abstractmethod
    async def get_dataset(self, urn: str) -> dict:
        """Entity-level metadata: name, platform, entity_type, description, owner."""

    @abstractmethod
    async def get_schema(self, urn: str, *, before_incident: bool = False) -> list[SchemaField]:
        """Current schema fields, or the pre-incident schema if before_incident=True."""

    @abstractmethod
    async def get_lineage(self, urn: str, direction: str = "DOWNSTREAM", hops: int = 5) -> dict:
        """Returns {"assets": [urn, ...]} reachable in `direction` within `hops`."""

    @abstractmethod
    async def get_lineage_paths_between(self, source_urn: str, dest_urn: str) -> dict:
        """Returns {"paths": [[urn, urn, ...], ...]} between two assets."""

    @abstractmethod
    async def get_owners(self, urn: str) -> list[dict]:
        """Returns [{"team": str, "contact": str}, ...]."""

    @abstractmethod
    async def search_datasets(self, query: str) -> list[dict]:
        """Keyword search over dataset entities."""

    @abstractmethod
    async def get_dataset_queries(self, urn: str) -> list[str]:
        """Real SQL query text referencing this dataset (query-log metadata)."""

    @abstractmethod
    async def add_incident_note(self, urn: str, note: str) -> bool:
        """Write-back. Returns False (and logs what WOULD have been written)
        unless both DATAHUB_MUTATION_ENABLED (app-side) and the DataHub MCP
        server's own TOOLS_IS_MUTATION_ENABLED are true. Never raises —
        write-back failure must never block incident resolution."""


class CachingDataHubClient(DataHubClient):
    """Per-incident memoization wrapper.

    Several nodes (trace_lineage, analyze_blast_radius, identify_owners,
    investigate_root_cause) request overlapping entity/lineage data. Caches
    by (method, args) for the lifetime of one incident run — in real mode
    this avoids redundant network round trips that add visible latency to
    a live demo; in mock mode it costs nothing either way.
    """

    def __init__(self, inner: DataHubClient) -> None:
        self._inner = inner
        self._cache: dict[tuple, object] = {}

    async def _memoize(self, key: tuple, coro):
        if key not in self._cache:
            self._cache[key] = await coro
        return self._cache[key]

    async def get_dataset(self, urn: str) -> dict:
        return await self._memoize(("get_dataset", urn), self._inner.get_dataset(urn))

    async def get_schema(self, urn: str, *, before_incident: bool = False) -> list[SchemaField]:
        return await self._memoize(
            ("get_schema", urn, before_incident),
            self._inner.get_schema(urn, before_incident=before_incident),
        )

    async def get_lineage(self, urn: str, direction: str = "DOWNSTREAM", hops: int = 5) -> dict:
        return await self._memoize(
            ("get_lineage", urn, direction, hops),
            self._inner.get_lineage(urn, direction=direction, hops=hops),
        )

    async def get_lineage_paths_between(self, source_urn: str, dest_urn: str) -> dict:
        return await self._memoize(
            ("get_lineage_paths_between", source_urn, dest_urn),
            self._inner.get_lineage_paths_between(source_urn, dest_urn),
        )

    async def get_owners(self, urn: str) -> list[dict]:
        return await self._memoize(("get_owners", urn), self._inner.get_owners(urn))

    async def search_datasets(self, query: str) -> list[dict]:
        return await self._memoize(("search_datasets", query), self._inner.search_datasets(query))

    async def get_dataset_queries(self, urn: str) -> list[str]:
        return await self._memoize(
            ("get_dataset_queries", urn), self._inner.get_dataset_queries(urn)
        )

    async def add_incident_note(self, urn: str, note: str) -> bool:
        # Never cached — a write must always actually attempt to run.
        return await self._inner.add_incident_note(urn, note)
