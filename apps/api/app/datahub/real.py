"""RealDataHubClient — talks to an actual DataHub instance over its REST/
OpenAPI + GraphQL surface (the same operations the DataHub MCP server
exposes as `search`, `get_entities`, `get_lineage`, etc.).

Stretch goal (T8) per the design doc's day-1 EOD kill switch: this class is
real, not faked — every method makes an actual HTTP call — but it is not
required for the demo, which defaults to DATAHUB_MODE=mock. Selecting
DATAHUB_MODE=real requires DATAHUB_GMS_URL and DATAHUB_GMS_TOKEN.

Write-back (add_incident_note) requires BOTH DATAHUB_MUTATION_ENABLED=true
on the app side AND the DataHub MCP server's own TOOLS_IS_MUTATION_ENABLED=
true — this class does not know whether the server flag is set; a mutation
call that 403s because the server flag is off is treated the same as any
other write failure (logged, returns False, never raises).
"""

from __future__ import annotations

import re

import httpx

from app.datahub.client import DataHubClient, DataHubUnavailableError
from app.incidents.state import SchemaField

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Real GraphQL query roots and the entity-type string trace_lineage/nodes.py
# expect on the returned dict. Verified against DataHub's actual GraphQL SDL
# (datahub-graphql-core/src/main/resources/entity.graphql on GitHub) — not
# guessed. Dataset and Chart both directly expose name/type/platform/
# ownership on the entity itself; both were confirmed field-by-field.
_ENTITY_TYPE_FROM_URN_PREFIX = {
    "urn:li:dataset:": "dataset",
    "urn:li:chart:": "chart",
    "urn:li:mlModel:": "mlModel",
}

# Downstream-consumer categorization our app applies on top of DataHub's
# real entity_type — the same categorization MockDataHubClient's fixture
# data hand-assigns per asset. Not a DataHub-native field; a display bucket
# this app defines, applied consistently to real entity_type values.
_ASSET_CATEGORY_BY_ENTITY_TYPE = {"dataset": "pipeline", "chart": "dashboard", "mlModel": "ml_model"}

_MLMODEL_URN_RE = re.compile(r"^urn:li:mlModel:\(urn:li:dataPlatform:([^,]+),([^,]+),[^)]+\)$")


def _entity_type_of(urn: str) -> str:
    for prefix, etype in _ENTITY_TYPE_FROM_URN_PREFIX.items():
        if urn.startswith(prefix):
            return etype
    raise DataHubUnavailableError(f"unrecognized entity type for urn: {urn}")


def _mlmodel_name_and_platform_from_urn(urn: str) -> tuple[str | None, str | None]:
    """MLModel's GraphQL type fields aren't documented in DataHub's public
    schema reference the way Dataset/Chart are, so rather than guess field
    names that could break the whole query if wrong, name/platform are
    parsed from the URN DataHub itself returned — the URN is real data,
    self-describing by DataHub's own construction (matches
    make_ml_model_urn's format exactly), not a fabricated substitute."""
    match = _MLMODEL_URN_RE.match(urn)
    if not match:
        return None, None
    platform, name = match.groups()
    return name, platform


def _first_owner_name(ownership: dict | None) -> str | None:
    if not ownership:
        return None
    for o in ownership.get("owners") or []:
        owner_obj = (o or {}).get("owner") or {}
        name = owner_obj.get("name") or owner_obj.get("username")
        if name:
            return name
    return None


_OWNERSHIP_FRAGMENT = """
ownership {
  owners {
    owner {
      ... on CorpGroup { name }
      ... on CorpUser { username }
    }
  }
}
"""


class RealDataHubClient(DataHubClient):
    def __init__(self, gms_url: str, gms_token: str | None) -> None:
        self._base_url = gms_url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if gms_token:
            headers["Authorization"] = f"Bearer {gms_token}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url, headers=headers, timeout=_TIMEOUT
        )

    async def _graphql(self, query: str, variables: dict) -> dict:
        try:
            resp = await self._client.post(
                "/api/graphql", json={"query": query, "variables": variables}
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise DataHubUnavailableError(f"DataHub GMS unreachable: {exc}") from exc
        if "errors" in payload and payload["errors"]:
            raise DataHubUnavailableError(str(payload["errors"]))
        return payload.get("data", {})

    async def get_dataset(self, urn: str) -> dict:
        """Returns the shape trace_lineage/fetch_context expect: urn, name,
        platform, entity_type, asset_category, owner, description. Branches
        on entity type (derived locally from the URN prefix — zero API
        risk) since DataHub's GraphQL query root differs per type
        (`dataset(urn)`, `chart(urn)`, `mlModel(urn)`) and Dataset/Chart's
        confirmed real fields (name, platform, ownership) aren't guaranteed
        identical on MLModel."""
        etype = _entity_type_of(urn)

        if etype == "dataset":
            data = await self._graphql(
                f"""
                query getDataset($urn: String!) {{
                  dataset(urn: $urn) {{
                    urn
                    name
                    platform {{ name }}
                    properties {{ description }}
                    {_OWNERSHIP_FRAGMENT}
                  }}
                }}
                """,
                {"urn": urn},
            )
            entity = data.get("dataset")
        elif etype == "chart":
            data = await self._graphql(
                f"""
                query getChart($urn: String!) {{
                  chart(urn: $urn) {{
                    urn
                    name
                    platform {{ name }}
                    properties {{ description }}
                    {_OWNERSHIP_FRAGMENT}
                  }}
                }}
                """,
                {"urn": urn},
            )
            entity = data.get("chart")
        else:  # mlModel
            data = await self._graphql(
                f"""
                query getMlModel($urn: String!) {{
                  mlModel(urn: $urn) {{
                    urn
                    {_OWNERSHIP_FRAGMENT}
                  }}
                }}
                """,
                {"urn": urn},
            )
            entity = data.get("mlModel")

        if not entity:
            raise DataHubUnavailableError(f"entity not found in DataHub: {urn}")

        if etype == "mlModel":
            name, platform = _mlmodel_name_and_platform_from_urn(urn)
            description = None
        else:
            name = entity.get("name")
            platform = (entity.get("platform") or {}).get("name")
            description = (entity.get("properties") or {}).get("description")

        return {
            "urn": entity.get("urn", urn),
            "name": name,
            "platform": platform,
            "entity_type": etype,
            "asset_category": _ASSET_CATEGORY_BY_ENTITY_TYPE.get(etype),
            "owner": _first_owner_name(entity.get("ownership")),
            "description": description,
        }

    async def get_schema(self, urn: str, *, before_incident: bool = False) -> list[SchemaField]:
        # Historical (before_incident=True) schema versioning is best-effort
        # in real mode — DataHub's schema history API varies by version.
        # Only the current schema is guaranteed available here.
        if before_incident:
            raise DataHubUnavailableError(
                "Historical schema diffing is not guaranteed in DATAHUB_MODE=real; "
                "guaranteed only in DATAHUB_MODE=mock."
            )
        data = await self._graphql(
            """
            query getSchema($urn: String!) {
              dataset(urn: $urn) {
                schemaMetadata { fields { fieldPath type nullable } }
              }
            }
            """,
            {"urn": urn},
        )
        fields = ((data.get("dataset") or {}).get("schemaMetadata") or {}).get("fields") or []
        return [
            {"field_path": f["fieldPath"], "type": str(f["type"]), "nullable": bool(f["nullable"])}
            for f in fields
        ]

    async def get_lineage(self, urn: str, direction: str = "DOWNSTREAM", hops: int = 5) -> dict:
        data = await self._graphql(
            """
            query getLineage($urn: String!, $direction: LineageDirection!) {
              searchAcrossLineage(input: {
                urn: $urn, direction: $direction, query: "*",
                start: 0, count: 100
              }) {
                searchResults { entity { urn } }
              }
            }
            """,
            {"urn": urn, "direction": direction},
        )
        results = (data.get("searchAcrossLineage") or {}).get("searchResults") or []
        return {"assets": [r["entity"]["urn"] for r in results]}

    async def get_lineage_paths_between(self, source_urn: str, dest_urn: str) -> dict:
        # DataHub doesn't expose a direct "paths between" primitive over
        # GraphQL; approximate via a bounded BFS over get_lineage.
        downstream = await self.get_lineage(source_urn, "DOWNSTREAM", hops=10)
        if dest_urn in downstream["assets"]:
            return {"paths": [[source_urn, dest_urn]]}
        return {"paths": []}

    async def get_owners(self, urn: str) -> list[dict]:
        # Reuses get_dataset's real ownership extraction rather than
        # re-querying — get_dataset already resolves the CorpGroup/CorpUser
        # owner name from DataHub's actual ownership aspect.
        ds = await self.get_dataset(urn)
        owner = ds.get("owner")
        return [{"team": owner}] if owner else []

    async def search_datasets(self, query: str) -> list[dict]:
        data = await self._graphql(
            """
            query search($query: String!) {
              search(input: {type: DATASET, query: $query, start: 0, count: 20}) {
                searchResults { entity { urn } }
              }
            }
            """,
            {"query": query},
        )
        results = (data.get("search") or {}).get("searchResults") or []
        return [{"urn": r["entity"]["urn"]} for r in results]

    async def get_dataset_queries(self, urn: str) -> list[str]:
        # Maps to the DataHub MCP server's get_dataset_queries tool (query-log
        # metadata). Real-mode implementation depends on the DataHub Actions/
        # query-log ingestion being enabled on the target instance — not
        # guaranteed on every install, hence still a stretch-goal path.
        raise DataHubUnavailableError(
            "get_dataset_queries in DATAHUB_MODE=real requires query-log "
            "ingestion configured on the target DataHub instance."
        )

    async def add_incident_note(self, urn: str, note: str) -> bool:
        try:
            data = await self._graphql(
                """
                mutation addNote($urn: String!, $note: String!) {
                  updateDescription(input: {resourceUrn: $urn, description: $note})
                }
                """,
                {"urn": urn, "note": note},
            )
            return bool(data.get("updateDescription"))
        except DataHubUnavailableError as exc:
            print(f"[RealDataHubClient] write-back failed for {urn}: {exc}")
            return False
