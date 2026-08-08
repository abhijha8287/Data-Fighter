"""Unit tests for RealDataHubClient against mocked GraphQL responses —
no live DataHub instance required. Response shapes match DataHub's actual
GraphQL SDL (datahub-graphql-core/src/main/resources/entity.graphql on
GitHub), verified during the real-mode bug fixes: Dataset and Chart expose
name/type/platform/ownership directly on the entity; MLModel's exact GraphQL
fields aren't publicly documented, so its name/platform are derived from the
URN instead (see _mlmodel_name_and_platform_from_urn).
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.datahub.client import DataHubUnavailableError
from app.datahub.real import RealDataHubClient

DATASET_URN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customers,PROD)"
CHART_URN = "urn:li:chart:(looker,revenue_dashboard)"
MLMODEL_URN = "urn:li:mlModel:(urn:li:dataPlatform:sagemaker,churn_model,PROD)"


def _client_with_handler(handler) -> RealDataHubClient:
    client = RealDataHubClient("http://fake-gms:8080", "fake-token")
    client._client = httpx.AsyncClient(
        base_url="http://fake-gms:8080", transport=httpx.MockTransport(handler)
    )
    return client


def _gql_response(data: dict, errors: list | None = None) -> httpx.Response:
    body = {"data": data}
    if errors:
        body["errors"] = errors
    return httpx.Response(200, json=body)


async def test_get_dataset_extracts_name_platform_owner_from_corpgroup():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "dataset(urn: $urn)" in request.content.decode()
        return _gql_response(
            {
                "dataset": {
                    "urn": DATASET_URN,
                    "name": "analytics.customers",
                    "platform": {"name": "snowflake"},
                    "properties": {"description": "Canonical customer dimension"},
                    "ownership": {
                        "owners": [{"owner": {"name": "Data Engineering"}}]
                    },
                }
            }
        )

    client = _client_with_handler(handler)
    result = await client.get_dataset(DATASET_URN)

    assert result["name"] == "analytics.customers"
    assert result["platform"] == "snowflake"
    assert result["entity_type"] == "dataset"
    assert result["asset_category"] == "pipeline"
    assert result["owner"] == "Data Engineering"
    assert result["description"] == "Canonical customer dimension"


async def test_get_dataset_owner_from_corpuser_username():
    def handler(request: httpx.Request) -> httpx.Response:
        return _gql_response(
            {
                "dataset": {
                    "urn": DATASET_URN,
                    "name": "analytics.customers",
                    "platform": {"name": "snowflake"},
                    "properties": {"description": None},
                    "ownership": {"owners": [{"owner": {"username": "jane.doe"}}]},
                }
            }
        )

    client = _client_with_handler(handler)
    result = await client.get_dataset(DATASET_URN)
    assert result["owner"] == "jane.doe"


async def test_get_dataset_chart_uses_chart_query_root():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert "chart(urn: $urn)" in body
        assert "dataset(urn:" not in body
        return _gql_response(
            {
                "chart": {
                    "urn": CHART_URN,
                    "name": "revenue_dashboard",
                    "platform": {"name": "looker"},
                    "properties": {"description": "Weekly revenue dashboard"},
                    "ownership": {"owners": [{"owner": {"name": "Analytics Engineering"}}]},
                }
            }
        )

    client = _client_with_handler(handler)
    result = await client.get_dataset(CHART_URN)

    assert result["name"] == "revenue_dashboard"
    assert result["platform"] == "looker"
    assert result["entity_type"] == "chart"
    assert result["asset_category"] == "dashboard"
    assert result["owner"] == "Analytics Engineering"


async def test_get_dataset_mlmodel_uses_mlmodel_query_root_and_urn_derived_name():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert "mlModel(urn: $urn)" in body
        # MLModel's exact GraphQL fields aren't publicly documented (unlike
        # Dataset/Chart, verified against the real schema), so the query
        # must NOT guess a `name` or `platform` field on the type itself —
        # only the interface-guaranteed `urn` plus `ownership`, which docs
        # confirm is present on "most data assets including ML models".
        # Everything requested on the mlModel entity BEFORE the ownership
        # fragment starts — this is where a guessed `name`/`platform`
        # field would appear if the query were wrong. The ownership
        # fragment's own `... on CorpGroup { name }` legitimately contains
        # "name" but that's a different, needed field (the owner's name).
        pre_ownership = body.split("mlModel(urn: $urn) {", 1)[1].split("ownership", 1)[0]
        assert "name" not in pre_ownership
        assert "platform" not in pre_ownership
        assert "ownership" in body.split("mlModel(urn: $urn) {", 1)[1]
        return _gql_response(
            {
                "mlModel": {
                    "urn": MLMODEL_URN,
                    "ownership": {"owners": [{"owner": {"name": "ML Platform"}}]},
                }
            }
        )

    client = _client_with_handler(handler)
    result = await client.get_dataset(MLMODEL_URN)

    assert result["name"] == "churn_model"  # derived from the URN, not a GraphQL field
    assert result["platform"] == "sagemaker"  # derived from the URN
    assert result["entity_type"] == "mlModel"
    assert result["asset_category"] == "ml_model"
    assert result["owner"] == "ML Platform"


async def test_get_dataset_raises_when_entity_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return _gql_response({"dataset": None})

    client = _client_with_handler(handler)
    with pytest.raises(DataHubUnavailableError):
        await client.get_dataset(DATASET_URN)


async def test_get_dataset_raises_on_unrecognized_urn_type():
    client = _client_with_handler(lambda r: _gql_response({}))
    with pytest.raises(DataHubUnavailableError):
        await client.get_dataset("urn:li:corpGroup:Data Engineering")


async def test_get_owners_returns_real_team_not_dataset_name():
    """Regression test for the original bug: get_owners used to return
    [{"team": dataset_name}] — the dataset's OWN name, not real ownership."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _gql_response(
            {
                "dataset": {
                    "urn": DATASET_URN,
                    "name": "analytics.customers",
                    "platform": {"name": "snowflake"},
                    "properties": {"description": None},
                    "ownership": {"owners": [{"owner": {"name": "Data Engineering"}}]},
                }
            }
        )

    client = _client_with_handler(handler)
    owners = await client.get_owners(DATASET_URN)

    assert owners == [{"team": "Data Engineering"}]
    assert owners[0]["team"] != "analytics.customers"


async def test_get_owners_returns_empty_list_when_no_owners():
    def handler(request: httpx.Request) -> httpx.Response:
        return _gql_response(
            {
                "dataset": {
                    "urn": DATASET_URN,
                    "name": "analytics.customers",
                    "platform": {"name": "snowflake"},
                    "properties": {"description": None},
                    "ownership": {"owners": []},
                }
            }
        )

    client = _client_with_handler(handler)
    assert await client.get_owners(DATASET_URN) == []


async def test_get_schema_after_incident_returns_real_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        return _gql_response(
            {
                "dataset": {
                    "schemaMetadata": {
                        "fields": [
                            {"fieldPath": "customer_id", "type": "STRING", "nullable": False},
                        ]
                    }
                }
            }
        )

    client = _client_with_handler(handler)
    fields = await client.get_schema(DATASET_URN, before_incident=False)
    assert fields == [{"field_path": "customer_id", "type": "STRING", "nullable": False}]


async def test_get_schema_before_incident_raises_documented_limitation():
    """Real mode doesn't guarantee historical schema versioning — this must
    raise, not silently return the current schema or fabricated data."""
    client = _client_with_handler(lambda r: _gql_response({}))
    with pytest.raises(DataHubUnavailableError):
        await client.get_schema(DATASET_URN, before_incident=True)


async def test_graphql_errors_array_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return _gql_response({}, errors=[{"message": "field not found on type Dataset"}])

    client = _client_with_handler(handler)
    with pytest.raises(DataHubUnavailableError):
        await client.get_dataset(DATASET_URN)


async def test_graphql_http_error_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    client = _client_with_handler(handler)
    with pytest.raises(DataHubUnavailableError):
        await client.get_dataset(DATASET_URN)


async def test_mlmodel_urn_parsing_helper_matches_real_urn_format():
    from app.datahub.real import _mlmodel_name_and_platform_from_urn

    name, platform = _mlmodel_name_and_platform_from_urn(MLMODEL_URN)
    assert name == "churn_model"
    assert platform == "sagemaker"


async def test_mlmodel_urn_parsing_helper_returns_none_on_malformed_urn():
    from app.datahub.real import _mlmodel_name_and_platform_from_urn

    name, platform = _mlmodel_name_and_platform_from_urn("not-a-real-urn")
    assert name is None
    assert platform is None


async def test_fetch_context_node_degrades_gracefully_when_schema_before_unavailable():
    """Integration test: fetch_context must NOT fail the whole incident just
    because RealDataHubClient.get_schema(before_incident=True) raises — that
    field is unused downstream (see nodes.py). The current schema and
    dataset metadata, which ARE real and required, must still come through."""
    from app.agents.nodes import Nodes
    from app.incidents.state import IncidentStatus

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "schemaMetadata" in body:
            return _gql_response(
                {
                    "dataset": {
                        "schemaMetadata": {
                            "fields": [
                                {"fieldPath": "customer_id", "type": "STRING", "nullable": False}
                            ]
                        }
                    }
                }
            )
        return _gql_response(
            {
                "dataset": {
                    "urn": DATASET_URN,
                    "name": "analytics.customers",
                    "platform": {"name": "snowflake"},
                    "properties": {"description": "Canonical customer dimension"},
                    "ownership": {"owners": [{"owner": {"name": "Data Engineering"}}]},
                }
            }
        )

    real_client = _client_with_handler(handler)
    nodes = Nodes(datahub=real_client, github=None, llm_generate=None)  # type: ignore[arg-type]

    result = await nodes.fetch_context({"dataset_urn": DATASET_URN})

    assert result["status"] == IncidentStatus.INVESTIGATING.value
    assert result["schema_before"] == []  # honest "not available", not fabricated
    assert result["schema_after"] == [{"field_path": "customer_id", "type": "STRING", "nullable": False}]
    assert result["dataset_metadata"]["name"] == "analytics.customers"
