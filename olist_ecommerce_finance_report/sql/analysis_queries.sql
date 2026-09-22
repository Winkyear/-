-- Olist e-commerce operating and payment analysis (SQLite)

-- 1. Monthly GMV, orders, AOV and freight share
SELECT purchase_month,
       ROUND(SUM(gmv), 2) AS gmv,
       COUNT(DISTINCT order_id) AS orders,
       ROUND(SUM(gmv) / COUNT(DISTINCT order_id), 2) AS aov,
       ROUND(SUM(freight_value) / SUM(gmv + freight_value), 4) AS freight_share
FROM orders_analysis
GROUP BY purchase_month
ORDER BY purchase_month;

-- 2. Payment structure
SELECT primary_payment_type,
       COUNT(DISTINCT order_id) AS orders,
       ROUND(SUM(payment_value), 2) AS payment_value,
       ROUND(AVG(max_installments), 2) AS avg_installments,
       ROUND(AVG(gmv), 2) AS aov
FROM orders_analysis
GROUP BY primary_payment_type
ORDER BY payment_value DESC;

-- 3. Payment reconciliation by month
SELECT purchase_month,
       ROUND(SUM(payment_value), 2) AS payment_value,
       ROUND(SUM(order_value), 2) AS order_value,
       ROUND(SUM(ABS(payment_value - order_value)), 2) AS absolute_gap,
       ROUND(SUM(ABS(payment_value - order_value)) / SUM(payment_value), 6) AS gap_rate
FROM orders_analysis
GROUP BY purchase_month
ORDER BY purchase_month;

-- 4. Delivery and customer experience
SELECT CASE WHEN is_late = 1 THEN '晚到' ELSE '准时' END AS delivery_group,
       COUNT(DISTINCT order_id) AS orders,
       ROUND(SUM(gmv), 2) AS gmv,
       ROUND(AVG(delivery_days), 2) AS avg_delivery_days,
       ROUND(AVG(review_score), 3) AS avg_review_score,
       ROUND(AVG(is_bad_review), 4) AS bad_review_rate
FROM orders_analysis
WHERE is_late IS NOT NULL
GROUP BY delivery_group;

-- 5. Category GMV and freight burden
SELECT product_category,
       ROUND(gmv, 2) AS gmv,
       orders,
       ROUND(freight_share, 4) AS freight_share,
       ROUND(review_score, 3) AS review_score,
       ROUND(late_rate, 4) AS late_rate
FROM category_performance
WHERE orders >= 500
ORDER BY gmv DESC;

-- 6. State scale and service level
SELECT customer_state,
       ROUND(gmv, 2) AS gmv,
       orders,
       ROUND(late_rate, 4) AS late_rate,
       ROUND(review_score, 3) AS review_score,
       ROUND(freight_share, 4) AS freight_share
FROM state_performance
ORDER BY gmv DESC;

-- 7. Mature cohort 90-day repeat rate
SELECT cohort_month,
       customers,
       ROUND(repeat_30d, 4) AS repeat_30d,
       ROUND(repeat_60d, 4) AS repeat_60d,
       ROUND(repeat_90d, 4) AS repeat_90d
FROM cohort_repeat
ORDER BY cohort_month;

-- 8. Seller concentration checkpoints
WITH ranked AS (
    SELECT seller_id, gmv,
           ROW_NUMBER() OVER (ORDER BY gmv DESC) AS seller_rank,
           SUM(gmv) OVER (ORDER BY gmv DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
             / SUM(gmv) OVER () AS cumulative_gmv_share
    FROM seller_performance
)
SELECT seller_rank, seller_id, ROUND(gmv, 2) AS gmv,
       ROUND(cumulative_gmv_share, 4) AS cumulative_gmv_share
FROM ranked
WHERE seller_rank IN (1, 10, 50, 100, 200, 531, 1000, 2000)
ORDER BY seller_rank;
