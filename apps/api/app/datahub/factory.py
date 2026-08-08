"""Builds the configured DataHubClient. This is the ONLY place DATAHUB_MODE
is read outside of app/config.py — every other module depends on the
DataHubClient interface, never on mock/real directly."""

from __future__ import annotations

from app.config import settings
from app.datahub.client import CachingDataHubClient, DataHubClient
from app.datahub.mock import MockDataHubClient


def build_datahub_client() -> DataHubClient:
    if settings.datahub_mode == "real":
        if not settings.datahub_gms_url:
            raise RuntimeError("DATAHUB_MODE=real requires DATAHUB_GMS_URL to be set")
        from app.datahub.real import RealDataHubClient  # local import: httpx client is lazy

        inner = RealDataHubClient(settings.datahub_gms_url, settings.datahub_gms_token)
    else:
        inner = MockDataHubClient(settings.fixture_dir)
    return CachingDataHubClient(inner)
