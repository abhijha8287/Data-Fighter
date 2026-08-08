-- dataset: churn_model
-- depends_on: customer_features
-- urn: urn:li:mlModel:(urn:li:dataPlatform:sagemaker,churn_model,PROD)
--
-- ML training query. Not directly broken by the schema change, but the
-- next scheduled retrain will silently train on stale/incomplete features
-- once customer_features stops refreshing.

SELECT
    customer_id,
    email_domain_feature,
    tenure_days,
    country_code,
    churned_within_90d AS label
FROM customer_features
JOIN churn_labels USING (customer_id);
