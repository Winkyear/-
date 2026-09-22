# Power BI Desktop 搭建说明

本项目没有交付 `.pbix`，因为 Power BI Desktop 文件需要在本机图形界面中保存。项目已提供可直接导入的星型模型 CSV、DAX 度量值和页面设计，按下面步骤约 20–30 分钟可复现。

## 1. 导入数据

在 Power BI Desktop 中选择“获取数据 → 文本/CSV”，导入：

- `data/processed/fact_user_game.csv`
- `data/processed/dim_user_segments.csv`
- `data/processed/dim_game_metrics.csv`
- `data/processed/agg_genre_metrics.csv`
- `data/processed/agg_segment_metrics.csv`

在 Power Query 中确认：

- `user_id`、`appid` 为整数。
- `play_hours`、`activation_rate`、`positive_rate` 为小数。
- `release_date` 为日期。
- `purchased`、`played`、`playable_purchase`、`store_matched` 为整数或布尔标记。

## 2. 建立模型

使用单向筛选：

- `dim_user_segments[user_id]` 一对多连接 `fact_user_game[user_id]`。
- `dim_game_metrics[name_key]` 一对多连接 `fact_user_game[name_key]`。

两个聚合表用于独立汇报，不要再与事实表连接，避免重复汇总。

## 3. 创建度量值

新建一个名为 `Measures` 的空表，将 `dax_measures.dax` 中的度量值逐项粘贴。重点检查：

- 可行动启动率应约为 60.0%。
- 原始启动率应约为 54.7%。
- 总游玩时长应约为 345 万小时。
- Top10 游玩时长占比应约为 58.2%。

## 4. 页面设计

### 页面一：经营总览

- KPI：用户数、游戏数、可行动启动率、待激活关系数、总游玩时长。
- 横向条形图：用户分层的用户数与平均启动率。
- 条形图：Top 10 游戏总游玩时长。
- 筛选器：用户分层、主类型、内容象限。

### 页面二：用户激活

- 散点图：X 为可独立游玩游戏库规模，Y 为用户启动率，气泡大小为累计游玩时长，图例为用户分层。
- 矩阵：用户分层、用户数、平均游戏库、平均启动率、平均总游玩时长。
- 明细表：大库低启动用户，按游戏库规模降序，用于生成召回样本。

### 页面三：内容组合

- 散点图：X 为购买用户数（建议对数轴），Y 为游戏启动率，气泡大小为总游玩时长，图例为内容象限。
- 条形图：主类型总游玩时长。
- 明细表：高规模低激活内容。排除 `content_quadrant = 非独立游玩候选`，避免把 DLC 当作未启动游戏。

## 5. 页面说明与限制

在每页底部放置短注：

> 数据没有事件日期、金额、曝光与推荐日志。启动率是横截面行为口径；全样本从未出现 play 的内容可能包括 DLC/地图包，已从可行动启动率分母排除。类型与价格分析仅覆盖精确名称匹配样本。

## 6. 建议的交互

- 点击用户分层联动游戏与类型图表。
- 内容页默认过滤 `purchase_users >= 20`，减少小样本噪声。
- 工具提示显示购买用户数、已启动用户数、启动率、总游玩时长和元数据匹配状态。
- 书签保留“全量”和“仅可独立游玩内容”两个视图，避免口径混淆。
