-- dataset: customer_dashboard
-- depends_on: customer_segmentation
-- urn: urn:li:chart:(looker,customer_dashboard)
--
-- Ops-facing segment view. Not directly broken by the schema change, but
-- stops refreshing once customer_segmentation stops producing rows.

SELECT
    email_domain,
    country_code,
    COUNT(*) AS customer_count
FROM customer_segmentation
GROUP BY 1, 2;
