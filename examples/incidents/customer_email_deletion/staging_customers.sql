-- dataset: staging.customers
-- depends_on: raw.customers
-- urn: urn:li:dataset:(urn:li:dataPlatform:snowflake,staging.customers,PROD)
--
-- Light cleanup: dedupe, normalize email casing, drop test accounts.

SELECT
    customer_id,
    LOWER(TRIM(customer_email)) AS customer_email,
    first_name,
    last_name,
    signup_ts,
    country_code
FROM raw.customers
WHERE customer_email NOT LIKE '%@test.internal'
QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY signup_ts DESC) = 1;
