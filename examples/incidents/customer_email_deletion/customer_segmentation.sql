-- dataset: customer_segmentation
-- depends_on: analytics.customers
-- urn: urn:li:dataset:(urn:li:dataPlatform:snowflake,customer_segmentation,PROD)
--
-- BROKEN: segments customers by email domain (e.g. corporate vs. free
-- webmail), which requires analytics.customers.customer_email.

SELECT
    customer_id,
    customer_email,
    SPLIT_PART(customer_email, '@', 2) AS email_domain,
    country_code
FROM analytics.customers;
