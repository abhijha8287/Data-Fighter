-- dataset: customer_features
-- depends_on: analytics.customers
-- urn: urn:li:dataset:(urn:li:dataPlatform:snowflake,customer_features,PROD)
--
-- BROKEN: derives an ML feature (email domain, used as a weak signal for
-- account type) from analytics.customers.customer_email.

SELECT
    customer_id,
    SPLIT_PART(customer_email, '@', 2) AS email_domain_feature,
    DATEDIFF('day', signup_ts, CURRENT_DATE()) AS tenure_days,
    country_code
FROM analytics.customers;
