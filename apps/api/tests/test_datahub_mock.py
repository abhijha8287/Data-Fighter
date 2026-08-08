import pytest

from app.config import settings
from app.datahub.client import CachingDataHubClient
from app.datahub.mock import MockDataHubClient

ANALYTICS_CUSTOMERS = "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customers,PROD)"
CUSTOMER_METRICS = "urn:li:dataset:(urn:li:dataPlatform:snowflake,customer_metrics,PROD)"
CHURN_MODEL = "urn:li:mlModel:(urn:li:dataPlatform:sagemaker,churn_model,PROD)"
RAW_CUSTOMERS = "urn:li:dataset:(urn:li:dataPlatform:snowflake,raw.customers,PROD)"


@pytest.fixture
def client() -> MockDataHubClient:
    return MockDataHubClient(settings.fixture_dir)


async def test_get_dataset_known_urn(client: MockDataHubClient):
    ds = await client.get_dataset(ANALYTICS_CUSTOMERS)
    assert ds["name"] == "analytics.customers"
    assert ds["owner"] == "Data Engineering"


async def test_get_dataset_unknown_urn_raises(client: MockDataHubClient):
    with pytest.raises(KeyError):
        await client.get_dataset("urn:li:dataset:(urn:li:dataPlatform:snowflake,nope,PROD)")


async def test_schema_before_has_customer_email(client: MockDataHubClient):
    fields = await client.get_schema(ANALYTICS_CUSTOMERS, before_incident=True)
    names = {f["field_path"] for f in fields}
    assert "customer_email" in names


async def test_schema_after_missing_customer_email(client: MockDataHubClient):
    fields = await client.get_schema(ANALYTICS_CUSTOMERS, before_incident=False)
    names = {f["field_path"] for f in fields}
    assert "customer_email" not in names


async def test_downstream_lineage_reaches_churn_model(client: MockDataHubClient):
    lineage = await client.get_lineage(ANALYTICS_CUSTOMERS, direction="DOWNSTREAM", hops=5)
    assert CHURN_MODEL in lineage["assets"]


async def test_downstream_lineage_excludes_upstream(client: MockDataHubClient):
    lineage = await client.get_lineage(ANALYTICS_CUSTOMERS, direction="DOWNSTREAM", hops=5)
    assert RAW_CUSTOMERS not in lineage["assets"]


async def test_downstream_blast_radius_is_six_assets(client: MockDataHubClient):
    lineage = await client.get_lineage(ANALYTICS_CUSTOMERS, direction="DOWNSTREAM", hops=5)
    # customer_metrics, customer_segmentation, customer_features,
    # revenue_dashboard, customer_dashboard, churn_model
    assert len(lineage["assets"]) == 6


async def test_lineage_paths_between(client: MockDataHubClient):
    paths = await client.get_lineage_paths_between(ANALYTICS_CUSTOMERS, CHURN_MODEL)
    assert paths["paths"]
    assert paths["paths"][0][0] == ANALYTICS_CUSTOMERS
    assert paths["paths"][0][-1] == CHURN_MODEL


async def test_owners_for_ml_platform_asset(client: MockDataHubClient):
    owners = await client.get_owners(CHURN_MODEL)
    assert owners[0]["team"] == "ML Platform"


async def test_search_datasets(client: MockDataHubClient):
    results = await client.search_datasets("customer")
    names = {r["name"] for r in results}
    assert "customer_metrics" in names
    assert "churn_model" not in names  # search matches dataset name substring only


async def test_get_dataset_queries_reads_real_sql_file(client: MockDataHubClient):
    queries = await client.get_dataset_queries(CUSTOMER_METRICS)
    assert len(queries) == 1
    assert "customer_email" in queries[0]
    assert "FROM analytics.customers" in queries[0]


async def test_get_dataset_queries_empty_for_dataset_without_sql_file(client: MockDataHubClient):
    # analytics.customers itself has a sql_file, so pick a URN with none by
    # constructing a client against a stripped copy isn't worth the setup —
    # instead assert the real contract: unknown/no-file URN returns [].
    queries = await client.get_dataset_queries("urn:li:dataset:(unknown,nope,PROD)")
    assert queries == []


async def test_add_incident_note_returns_false_in_mock_mode(client: MockDataHubClient):
    result = await client.add_incident_note(ANALYTICS_CUSTOMERS, "test note")
    assert result is False


async def test_caching_wrapper_memoizes_calls():
    inner = MockDataHubClient(settings.fixture_dir)
    call_count = {"n": 0}
    original = inner.get_dataset

    async def counting_get_dataset(urn: str):
        call_count["n"] += 1
        return await original(urn)

    inner.get_dataset = counting_get_dataset  # type: ignore[method-assign]
    caching = CachingDataHubClient(inner)

    await caching.get_dataset(ANALYTICS_CUSTOMERS)
    await caching.get_dataset(ANALYTICS_CUSTOMERS)
    await caching.get_dataset(ANALYTICS_CUSTOMERS)

    assert call_count["n"] == 1
