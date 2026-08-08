-- dataset: raw.customers
-- depends_on:
-- urn: urn:li:dataset:(urn:li:dataPlatform:snowflake,raw.customers,PROD)
--
-- Raw ingestion from the source CRM system. No transformation.

SELECT
    id AS customer_id,
    email AS customer_email,
    first_name,
    last_name,
    signup_ts,
    country_code
FROM crm_source.customers;
