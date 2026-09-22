-- Steam 用户行为分析（SQLite 兼容）
-- 数据表由 src/analysis_pipeline.py 写入 outputs/steam_analysis.db。

-- 1. 核心规模与购买后启动率
SELECT
    COUNT(DISTINCT user_id) AS users,
    COUNT(DISTINCT name_key) AS games,
    SUM(purchased) AS purchase_pairs,
    SUM(played) AS played_pairs,
    ROUND(1.0 * SUM(played) / NULLIF(SUM(purchased), 0), 4) AS activation_rate,
    ROUND(SUM(play_hours), 1) AS total_play_hours
FROM fact_user_game;

-- 2. 用户分层画像
SELECT
    segment,
    COUNT(*) AS users,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS user_share_pct,
    ROUND(AVG(library_size), 2) AS avg_library_size,
    ROUND(AVG(activation_rate), 4) AS avg_activation_rate,
    ROUND(AVG(total_play_hours), 2) AS avg_total_play_hours
FROM dim_user_segments
GROUP BY segment
ORDER BY users DESC;

-- 3. 高规模低激活内容，作为召回与推荐优化候选
SELECT
    game_name,
    purchase_users,
    played_users,
    ROUND(activation_rate, 4) AS activation_rate,
    ROUND(total_play_hours, 1) AS total_play_hours,
    primary_genre,
    publisher
FROM dim_game_metrics
WHERE content_quadrant = '高规模低激活'
ORDER BY purchase_users DESC
LIMIT 20;

-- 4. 主类型结构，使用互斥的 primary_genre 避免重复计数
SELECT
    primary_genre,
    purchase_pairs,
    played_pairs,
    ROUND(activation_rate, 4) AS activation_rate,
    ROUND(total_play_hours, 1) AS total_play_hours,
    ROUND(100.0 * play_hours_share, 2) AS play_hours_share_pct
FROM agg_genre_metrics
ORDER BY total_play_hours DESC;

-- 5. 内容长尾：按购买人数分组
SELECT
    CASE
        WHEN purchase_users = 1 THEN '1'
        WHEN purchase_users BETWEEN 2 AND 5 THEN '2-5'
        WHEN purchase_users BETWEEN 6 AND 20 THEN '6-20'
        WHEN purchase_users BETWEEN 21 AND 100 THEN '21-100'
        ELSE '100+'
    END AS purchase_user_band,
    COUNT(*) AS games,
    SUM(purchase_users) AS purchase_pairs,
    ROUND(SUM(total_play_hours), 1) AS total_play_hours
FROM dim_game_metrics
GROUP BY purchase_user_band
ORDER BY MIN(purchase_users);

-- 6. 价格带与启动表现。价格为 2019 年快照，仅作相关性描述。
SELECT
    price_band,
    COUNT(*) AS games,
    SUM(purchase_users) AS purchase_pairs,
    SUM(played_users) AS played_pairs,
    ROUND(1.0 * SUM(played_users) / NULLIF(SUM(purchase_users), 0), 4) AS weighted_activation_rate,
    ROUND(SUM(total_play_hours), 1) AS total_play_hours
FROM dim_game_metrics
WHERE store_matched = 1 AND price_band IS NOT NULL
GROUP BY price_band
ORDER BY CASE price_band
    WHEN '免费' THEN 1 WHEN '£0-5' THEN 2 WHEN '£5-10' THEN 3
    WHEN '£10-20' THEN 4 WHEN '£20+' THEN 5 END;

-- 7. 质量对账：事实表购买与游戏表购买应相等
SELECT
    (SELECT SUM(purchased) FROM fact_user_game) AS fact_purchase_pairs,
    (SELECT SUM(purchase_users) FROM dim_game_metrics) AS game_purchase_pairs,
    (SELECT SUM(purchased) FROM fact_user_game)
      - (SELECT SUM(purchase_users) FROM dim_game_metrics) AS residual;
