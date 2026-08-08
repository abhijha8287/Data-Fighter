import pytest

from app.agents.sql_fix import (
    SqlParseError,
    check_deleted_column_absent,
    check_sql_parses,
    remove_column_references,
    schema_has_field,
)


def test_remove_column_references_strips_bare_column():
    sql = "SELECT customer_id, customer_email, total_spend FROM analytics.customers;"
    fixed = remove_column_references(sql, "customer_email")
    assert "customer_email" not in fixed
    assert "customer_id" in fixed
    assert "total_spend" in fixed


def test_remove_column_references_strips_derived_expression():
    sql = "SELECT customer_id, SPLIT_PART(customer_email, '@', 2) AS email_domain FROM t;"
    fixed = remove_column_references(sql, "customer_email")
    assert "customer_email" not in fixed
    assert "email_domain" not in fixed  # the derived expression is dropped entirely
    assert "customer_id" in fixed


def test_remove_column_references_strips_leading_fixture_comments():
    sql = (
        "-- dataset: customer_metrics\n"
        "-- BROKEN: references customer_email\n"
        "SELECT customer_id, customer_email FROM t;"
    )
    fixed = remove_column_references(sql, "customer_email")
    assert "BROKEN" not in fixed
    assert "-- dataset" not in fixed


def test_remove_column_references_raises_on_invalid_sql():
    with pytest.raises(SqlParseError):
        remove_column_references("SELECT FROM WHERE (((", "customer_email")


def test_check_sql_parses_valid():
    ok, err = check_sql_parses("SELECT 1;")
    assert ok is True
    assert err is None


def test_check_sql_parses_invalid():
    ok, err = check_sql_parses("SELEC 1 FRUM x")
    assert ok is False
    assert err is not None


def test_check_deleted_column_absent_true_when_removed():
    absent, errors = check_deleted_column_absent("SELECT customer_id FROM t;", "customer_email")
    assert absent is True
    assert errors == []


def test_check_deleted_column_absent_false_when_still_present():
    absent, errors = check_deleted_column_absent(
        "SELECT customer_id, customer_email FROM t;", "customer_email"
    )
    assert absent is False
    assert len(errors) == 1
    assert "customer_email" in errors[0]


def test_check_deleted_column_absent_raises_on_invalid_sql():
    with pytest.raises(SqlParseError):
        check_deleted_column_absent("NOT VALID SQL (((", "customer_email")


def test_schema_has_field_case_insensitive():
    schema = [{"field_path": "Customer_ID", "type": "STRING", "nullable": False}]
    assert schema_has_field(schema, "customer_id") is True
    assert schema_has_field(schema, "nonexistent") is False
