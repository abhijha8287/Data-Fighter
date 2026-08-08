"""Seeds a REAL running DataHub instance with the customer_email_deletion
demo scenario, using examples/incidents/customer_email_deletion/lineage.json
as the single source of truth (the same file MockDataHubClient reads).

This does NOT touch the application's mock adapter — it emits real
MetadataChangeProposal (MCP) events over DataHub's REST emitter to a live
GMS instance, so the application's RealDataHubClient reads this data back
from DataHub itself, not from a fixture file.

Usage:
    uv run --with acryl-datahub python3 scripts/seed_datahub.py \
        --gms-url http://localhost:8080

Idempotent: re-running overwrites the same URNs with the same data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "examples" / "incidents" / "customer_email_deletion"

ENTITY_TYPE_FROM_URN_PREFIX = {
    "urn:li:dataset:": "dataset",
    "urn:li:chart:": "chart",
    "urn:li:mlModel:": "mlModel",
}


def entity_type_of(urn: str) -> str:
    for prefix, etype in ENTITY_TYPE_FROM_URN_PREFIX.items():
        if urn.startswith(prefix):
            return etype
    raise ValueError(f"Unrecognized URN type: {urn}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gms-url", default="http://localhost:8080")
    parser.add_argument("--token", default=None, help="DataHub personal access token, if auth is enabled")
    args = parser.parse_args()

    # Local imports so this script's own --help works without the SDK installed.
    from datahub.emitter.mce_builder import make_group_urn
    from datahub.emitter.mcp import MetadataChangeProposalWrapper
    from datahub.emitter.rest_emitter import DatahubRestEmitter
    from datahub.metadata.schema_classes import (
        ChangeAuditStampsClass,
        ChartInfoClass,
        CorpGroupInfoClass,
        DatasetLineageTypeClass,
        DatasetPropertiesClass,
        MLModelPropertiesClass,
        OtherSchemaClass,
        OwnerClass,
        OwnershipClass,
        OwnershipTypeClass,
        SchemaFieldClass,
        SchemaFieldDataTypeClass,
        SchemaMetadataClass,
        StringTypeClass,
        UpstreamClass,
        UpstreamLineageClass,
    )

    with (FIXTURE_DIR / "lineage.json").open() as f:
        data = json.load(f)

    entities: dict = data["entities"]
    edges: list[list[str]] = data["lineage_edges"]
    schema_after: dict = data["schema_after"]
    owners_meta: dict = data["owners"]

    emitter = DatahubRestEmitter(gms_server=args.gms_url, token=args.token)
    emitter.test_connection()
    print(f"Connected to DataHub GMS at {args.gms_url}")

    def emit(urn: str, aspect) -> None:
        mcp = MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect)
        emitter.emit(mcp)

    # 1. CorpGroup entities for the 3 real owning teams.
    team_to_group_urn: dict[str, str] = {}
    for team_name in owners_meta:
        group_urn = make_group_urn(team_name)
        team_to_group_urn[team_name] = group_urn
        emit(
            group_urn,
            CorpGroupInfoClass(
                displayName=team_name,
                email=owners_meta[team_name].get("contact", ""),
                admins=[],
                members=[],
                groups=[],
                description=f"{team_name} — Data Firefighter demo scenario",
            ),
        )
    print(f"Emitted {len(team_to_group_urn)} CorpGroup entities: {list(team_to_group_urn)}")

    # 2. Downstream edges, grouped by source, for UpstreamLineage/inputs.
    downstream_of: dict[str, list[str]] = {}
    for src, dst in edges:
        downstream_of.setdefault(src, []).append(dst)
    upstream_of: dict[str, list[str]] = {}
    for src, dst in edges:
        upstream_of.setdefault(dst, []).append(src)

    # 3. Per-entity properties, schema (datasets only), ownership, lineage.
    for urn, entity in entities.items():
        etype = entity_type_of(urn)
        owner_group_urn = team_to_group_urn[entity["owner"]]

        if etype == "dataset":
            emit(
                urn,
                DatasetPropertiesClass(
                    name=entity["name"],
                    description=entity["description"],
                    customProperties={"platform": entity["platform"]},
                ),
            )
            if urn in schema_after:
                fields = [
                    SchemaFieldClass(
                        fieldPath=f["field_path"],
                        type=SchemaFieldDataTypeClass(type=StringTypeClass()),
                        nativeDataType=f["type"],
                        nullable=f["nullable"],
                    )
                    for f in schema_after[urn]
                ]
                emit(
                    urn,
                    SchemaMetadataClass(
                        schemaName=entity["name"],
                        platform=f"urn:li:dataPlatform:{entity['platform']}",
                        version=0,
                        hash="",
                        platformSchema=OtherSchemaClass(rawSchema=""),
                        fields=fields,
                    ),
                )
            ups = upstream_of.get(urn, [])
            if ups:
                emit(
                    urn,
                    UpstreamLineageClass(
                        upstreams=[
                            UpstreamClass(dataset=u, type=DatasetLineageTypeClass.TRANSFORMED)
                            for u in ups
                        ]
                    ),
                )

        elif etype == "chart":
            ups = upstream_of.get(urn, [])
            emit(
                urn,
                ChartInfoClass(
                    title=entity["name"],
                    description=entity["description"],
                    lastModified=ChangeAuditStampsClass(),
                    inputs=ups,
                ),
            )

        elif etype == "mlModel":
            emit(
                urn,
                MLModelPropertiesClass(
                    name=entity["name"],
                    description=entity["description"],
                ),
            )
            ups = upstream_of.get(urn, [])
            if ups:
                # Generic upstreamLineage aspect — DataHub 1.x supports this
                # for mlModel entities in addition to datasets.
                emit(
                    urn,
                    UpstreamLineageClass(
                        upstreams=[
                            UpstreamClass(dataset=u, type=DatasetLineageTypeClass.TRANSFORMED)
                            for u in ups
                        ]
                    ),
                )

        emit(
            urn,
            OwnershipClass(
                owners=[OwnerClass(owner=owner_group_urn, type=OwnershipTypeClass.DATAOWNER)]
            ),
        )
        print(f"Seeded {etype}: {entity['name']} ({urn})")

    print("\nDone. Verify at", f"{args.gms_url.replace('8080', '9002')}" if "8080" in args.gms_url else args.gms_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
