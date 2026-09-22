# Olist 电商经营与支付绩效分析

本项目使用 Olist 公开电商交易数据，将订单、商品、支付、评价、客户和卖家数据合并，分析经营规模、支付方式、配送体验和客户再次购买情况。

## 核心结论

- 2017 年 1 月至 2018 年 8 月的已送达订单样本有 96,211 笔订单、93,104 名客户，GMV 为 R$13.18M，客单价为 R$137.00。GMV 不含运费，也不等于收入或利润。
- 晚到率为 8.13%。晚到订单平均评分为 2.57，差评率为 53.98%；准时订单分别为 4.30 和 9.17%。这说明两者存在明显差异，但不能据此直接判断配送延迟一定造成差评。
- 按每笔订单中金额最大的支付记录计算，信用卡订单占 75.48%，对应支付金额占 78.46%，平均分期 3.55 期。这一口径用于订单分析，不代表实际支付流水的完整份额。
- 首次购买客户在 90 天内再次购买的比例为 2.28%；整个观察期内有过再次购买的客户占 3.00%。
- 圣保罗州贡献 38.36% 的 GMV，前 10 个品类贡献 62.47%，531 个卖家累计贡献 80% 的 GMV。

## 项目结构

```text
data/raw/                 Olist 原始 CSV（不上传，按说明下载）
data/processed/           清洗后的事实表与维表（本地生成）
src/                      Python 数据准备与分析流水线
sql/                      SQLite 分析查询
powerbi/                  DAX 指标与 Power BI 构建指南
outputs/metrics/          可复算聚合指标
outputs/run/              证据、角色复核、claims 与 HTML 报告
outputs/                   Excel、PPT、SQLite、HTML 成品
docs/                     完整项目报告与简历表述
build/                    Excel/PPT 生成脚本与预览
```

## 运行方式

```powershell
conda env create -f environment.yml
conda activate olist-analysis
python src/prepare_data.py
python src/analysis_pipeline.py
```

`analysis_pipeline.py` 会生成指标 CSV、`analysis_summary.json`、`evidence.json` 和 SQLite 数据库。Power BI 可按 `powerbi/POWER_BI_BUILD_GUIDE.md` 导入数据库或聚合 CSV。

## 主要交付物

- `outputs/Olist电商经营与支付分析看板.xlsx`：6 张工作表、16 个原生可编辑图表。
- `outputs/Olist电商经营与支付绩效汇报.pptx`：15 页、19 个原生可编辑图表。
- `outputs/Olist电商经营与支付绩效分析报告.html`：六段式可审计业务报告。
- `outputs/olist_ecommerce_finance.db`：SQLite 分析数据库。
- `docs/PROJECT_REPORT.md`：完整分析过程与业务建议。
- `docs/RESUME_PROJECT.md`：简历版本与面试话术。

## 数据与口径边界

数据来自 Olist 公开电商数据集。订单、GMV 和支付金额已完成对账，但数据没有退款、退货、商品成本、平台费、营销流量、实验分组、实际物流成本和更长的再次购买观察期。因此项目不计算净收入、毛利和 ROI；配送与评价的比较只作为关联分析，支付方式也只按订单口径统计。
