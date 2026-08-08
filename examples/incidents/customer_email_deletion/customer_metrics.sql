-- dataset: customer_metrics
-- depends_on: analytics.customers
-- urn: urn:li:dataset:(urn:li:dataPlatform:snowflake,customer_metrics,PROD)
--
-- BROKEN: references analytics.customers.customer_email, which no longer
-- exists after the upstream incident.

SELECT
    customer_id,
    customer_email,
    total_spend,
    order_count,
    last_order_ts
FROM analytics.customers
JOIN order_facts USING (customer_id);
