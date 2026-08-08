-- dataset: revenue_dashboard
-- depends_on: customer_metrics
-- urn: urn:li:chart:(looker,revenue_dashboard)
--
-- Not directly broken by the schema change, but stops refreshing once
-- customer_metrics stops producing rows.

SELECT
    DATE_TRUNC('week', last_order_ts) AS week,
    SUM(total_spend) AS revenue,
    COUNT(DISTINCT customer_id) AS active_customers
FROM customer_metrics
GROUP BY 1;
