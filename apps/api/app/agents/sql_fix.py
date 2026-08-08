"""Deterministic SQL transformation and validation helpers used by the
generate_fix and validate_fix nodes.

The SQL dialect is pinned to generic ANSI (sqlglot's `read=None` default) —
the demo's SQL is fully within our control (the seeded fixture files), so
there's no real dialect ambiguity to resolve, per the design doc.

generate_fix's actual column removal is deterministic (AST transform), not
LLM-generated — a live demo depending on an LLM to hand-write correct SQL
is a real hallucination risk; the LLM's role here is limited to producing
the natural-language explanation grounded in this deterministic transform,
not the SQL itself. This is a judgment call within the design's stated
"choose the simplest option consistent with the design" guidance for
ambiguous details — the design doc didn't pin down HOW the SQL gets
rewritten, only that it must be correct and explainable.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from app.incidents.state import SchemaField


class SqlParseError(Exception):
    pass


def _strip_fixture_header_comments(sql: str) -> str:
    """The seeded fixture files carry leading `-- dataset:`/`-- depends_on:`
    metadata comments for the seed script and README to parse. Those are
    authoring metadata, not part of the query — and one of them literally
    says "BROKEN: ..." which would read as a stale, confusing artifact in
    a PR diff that just fixed the query. Strip leading comment lines
    before parsing so the fix output is clean, production SQL."""
    lines = sql.splitlines()
    idx = 0
    while idx < len(lines) and (lines[idx].strip().startswith("--") or not lines[idx].strip()):
        idx += 1
    return "\n".join(lines[idx:])


def remove_column_references(sql: str, column: str) -> str:
    """Removes every top-level SELECT projection that references `column`,
    including derived expressions (e.g. SPLIT_PART(customer_email, '@', 2)
    AS email_domain) — since there is no replacement column, the correct
    fix removes the field AND anything computed from it, not just a bare
    reference."""
    sql = _strip_fixture_header_comments(sql)
    try:
        tree = sqlglot.parse_one(sql, read=None)
    except Exception as exc:  # sqlglot raises its own ParseError subclasses
        raise SqlParseError(str(exc)) from exc

    column_lower = column.lower()
    for select in tree.find_all(exp.Select):
        kept = [
            projection
            for projection in select.expressions
            if column_lower not in projection.sql(dialect=None).lower()
        ]
        select.set("expressions", kept)
    return tree.sql(dialect=None, pretty=True) + ";\n"


def check_sql_parses(sql: str) -> tuple[bool, str | None]:
    try:
        sqlglot.parse_one(sql, read=None)
        return True, None
    except Exception as exc:
        return False, str(exc)


def check_deleted_column_absent(sql: str, deleted_column: str) -> tuple[bool, list[str]]:
    """Confirms the fixed SQL no longer references the deleted column
    anywhere (SELECT list, WHERE, JOIN condition, etc.).

    Deliberately scoped to this one check — full multi-table schema
    resolution (validating every remaining column against every joined
    table's schema) is out of scope: DataHub only has schema metadata for
    the datasets in this fixture graph, not arbitrary joined tables like
    order_facts. This check targets the actual regression risk the design
    doc calls out: the fix silently leaving the deleted column in place.
    """
    try:
        tree = sqlglot.parse_one(sql, read=None)
    except Exception as exc:
        raise SqlParseError(str(exc)) from exc
    matches = [c.name for c in tree.find_all(exp.Column) if c.name.lower() == deleted_column.lower()]
    errors = [f"query still references deleted column '{m}'" for m in matches]
    return len(matches) == 0, errors


def schema_has_field(schema: list[SchemaField], field_name: str) -> bool:
    return any(f["field_path"].lower() == field_name.lower() for f in schema)
