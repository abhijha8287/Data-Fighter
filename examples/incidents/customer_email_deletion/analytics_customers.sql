-- dataset: analytics.customers
-- depends_on: staging.customers
-- urn: urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customers,PROD)
--
-- INCIDENT: customer_email was removed from this SELECT during an upstream
-- schema cleanup. Downstream consumers that still reference
-- analytics.customers.customer_email are now broken:
--   customer_metrics.sql, customer_segmentation.sql, customer_features.sql

SELECT
    customer_id,
    first_name,
    last_name,
    signup_ts,
    country_code
FROM staging.customers;
