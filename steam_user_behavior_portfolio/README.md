# Steam 用户行为与内容运营分析

本项目用 Steam 用户行为数据区分“拥有游戏”和“实际玩过游戏”，分析可做用户召回的对象和更值得推荐的内容。项目包含数据清洗、指标计算、SQL 查询、Excel/Power BI 看板和业务汇报。

## 快速复现

### Anaconda

```bash
conda env create -f environment.yml
conda activate steam-user-behavior
python src/analysis_pipeline.py
```

也可以在 PyCharm 中把项目根目录设为工作目录，选择上述 Conda 环境后运行 `src/analysis_pipeline.py`。

### SQL

```bash
sqlite3 outputs/steam_analysis.db < sql/analysis_queries.sql
```

## 核心结果

- 数据包含 12,393 名用户、5,153 款游戏和 128,801 条拥有记录。
- 其中有 70,474 条记录带有实际游玩时间。按当前样本口径，有 47,018 条“拥有但未游玩”的记录可作为后续核验对象。
- 3,044 名用户拥有较多游戏但实际启动较少，占用户总数的 24.56%，可作为召回候选。
- 游玩时长前 10 的游戏贡献 58.18% 的总游玩时长；该指标容易受个别超长游玩记录影响，因此只用于判断内容集中度。
- 长尾游戏中启动情况较好的内容可作为小范围推荐测试候选，是否有效仍需补充曝光和对照数据验证。

## 目录

```text
data/raw/                    原始数据（不上传）
data/processed/              Power BI/Excel 可直接导入的清洗结果（本地生成）
src/analysis_pipeline.py     Python 主流程
sql/analysis_queries.sql     SQLite 分析查询
powerbi/                     DAX 与 Power BI Desktop 搭建说明
docs/PROJECT_REPORT.md       完整项目报告
docs/RESUME_PROJECT.md       简历与面试表达
outputs/steam_analysis.db    SQLite 数据库
outputs/portfolio_run/       data-analysis skill 证据与 HTML 报告
```

## 口径说明

原始记录没有时间、金额和推荐曝光，因此项目不计算 DAU、留存、流失、收入或 LTV。没有游玩记录的内容可能是 DLC、工具类内容，也可能是真正未启动的游戏；`observed_playable` 只是样本内的辅助标记，不是官方分类。商店元数据只按游戏名称精确匹配，具体限制见正式报告。
