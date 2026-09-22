"""Build an auditable e-commerce operating and payment-performance analysis."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
OUT = ROOT / "outputs"
METRICS = OUT / "metrics"
DB = OUT / "olist_ecommerce_finance.db"


def save(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(METRICS / f"{name}.csv", index=False, encoding="utf-8-sig")


def scalar(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    METRICS.mkdir(parents=True, exist_ok=True)

    orders = pd.read_csv(
        DATA / "orders_enriched.csv",
        parse_dates=[
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
        low_memory=False,
    )
    items = pd.read_csv(
        DATA / "order_items_enriched.csv",
        parse_dates=["order_purchase_timestamp"],
        low_memory=False,
    )
    payments = pd.read_csv(DATA / "fact_payments.csv", low_memory=False)
    reviews = pd.read_csv(DATA / "fact_reviews.csv", low_memory=False)

    delivered = orders.loc[orders["order_status"].eq("delivered")].copy()
    delivered_items = items.loc[items["order_status"].eq("delivered")].copy()
    delivered["purchase_month"] = delivered["order_purchase_timestamp"].dt.to_period("M").astype(str)
    delivered["purchase_year"] = delivered["order_purchase_timestamp"].dt.year
    delivered["payment_gap"] = delivered["payment_value"] - delivered["order_value"]
    delivered["payment_gap_abs"] = delivered["payment_gap"].abs()

    analysis_orders = delivered.loc[
        delivered["purchase_month"].between("2017-01", "2018-08")
    ].copy()
    analysis_items = delivered_items.loc[
        delivered_items["purchase_month"].between("2017-01", "2018-08")
    ].copy()

    monthly = (
        analysis_orders.groupby("purchase_month", as_index=False)
        .agg(
            gmv=("gmv", "sum"),
            orders=("order_id", "nunique"),
            freight=("freight_value", "sum"),
            payment_value=("payment_value", "sum"),
            late_rate=("is_late", "mean"),
            review_score=("review_score", "mean"),
            bad_review_rate=("is_bad_review", "mean"),
        )
        .sort_values("purchase_month")
    )
    monthly["aov"] = monthly["gmv"] / monthly["orders"]
    monthly["freight_share"] = monthly["freight"] / (monthly["gmv"] + monthly["freight"])
    monthly["gmv_mom"] = monthly["gmv"].pct_change()
    save(monthly, "monthly_performance")

    payment_type = (
        analysis_orders.groupby("primary_payment_type", as_index=False)
        .agg(
            orders=("order_id", "nunique"),
            gmv=("gmv", "sum"),
            payment_value=("payment_value", "sum"),
            avg_installments=("max_installments", "mean"),
        )
        .sort_values("payment_value", ascending=False)
    )
    payment_type["order_share"] = payment_type["orders"] / payment_type["orders"].sum()
    payment_type["payment_share"] = payment_type["payment_value"] / payment_type["payment_value"].sum()
    payment_type["aov"] = payment_type["gmv"] / payment_type["orders"]
    save(payment_type, "payment_type_performance")

    credit = analysis_orders.loc[analysis_orders["primary_payment_type"].eq("credit_card")].copy()
    credit["installment_band"] = pd.cut(
        credit["max_installments"].fillna(0),
        bins=[-np.inf, 1, 3, 5, 9, np.inf],
        labels=["1", "2-3", "4-5", "6-9", "10+"],
    )
    installments = (
        credit.groupby("installment_band", observed=False, as_index=False)
        .agg(orders=("order_id", "nunique"), gmv=("gmv", "sum"), payment_value=("payment_value", "sum"))
    )
    installments["aov"] = installments["gmv"] / installments["orders"]
    installments["order_share"] = installments["orders"] / installments["orders"].sum()
    save(installments, "installment_performance")

    category = (
        analysis_items.groupby("product_category", as_index=False)
        .agg(
            gmv=("price", "sum"),
            orders=("order_id", "nunique"),
            freight=("freight_value", "sum"),
            late_rate=("is_late", "mean"),
            review_score=("review_score", "mean"),
            bad_review_rate=("is_bad_review", "mean"),
        )
        .sort_values("gmv", ascending=False)
    )
    category["aov"] = category["gmv"] / category["orders"]
    category["freight_share"] = category["freight"] / (category["gmv"] + category["freight"])
    category["gmv_share"] = category["gmv"] / category["gmv"].sum()
    category["cumulative_gmv_share"] = category["gmv_share"].cumsum()
    save(category, "category_performance")

    state = (
        analysis_orders.groupby("customer_state", as_index=False)
        .agg(
            gmv=("gmv", "sum"),
            orders=("order_id", "nunique"),
            freight=("freight_value", "sum"),
            delivery_days=("delivery_days", "mean"),
            late_rate=("is_late", "mean"),
            review_score=("review_score", "mean"),
            bad_review_rate=("is_bad_review", "mean"),
        )
        .sort_values("gmv", ascending=False)
    )
    state["aov"] = state["gmv"] / state["orders"]
    state["freight_share"] = state["freight"] / (state["gmv"] + state["freight"])
    state["gmv_share"] = state["gmv"] / state["gmv"].sum()
    save(state, "state_performance")

    delivery_group = (
        analysis_orders.dropna(subset=["is_late"])
        .assign(delivery_group=lambda x: np.where(x["is_late"].eq(1), "晚到", "准时"))
        .groupby("delivery_group", as_index=False)
        .agg(
            orders=("order_id", "nunique"),
            gmv=("gmv", "sum"),
            delivery_days=("delivery_days", "mean"),
            review_score=("review_score", "mean"),
            bad_review_rate=("is_bad_review", "mean"),
        )
    )
    save(delivery_group, "delivery_group_performance")

    delivery_bands = (
        analysis_orders.dropna(subset=["delivery_days", "review_score"])
        .assign(
            delivery_band=lambda x: pd.cut(
                x["delivery_days"],
                bins=[-np.inf, 7, 14, 21, 30, np.inf],
                labels=["0-7", "8-14", "15-21", "22-30", "31+"],
            )
        )
        .groupby("delivery_band", observed=False, as_index=False)
        .agg(orders=("order_id", "nunique"), review_score=("review_score", "mean"), bad_review_rate=("is_bad_review", "mean"))
    )
    save(delivery_bands, "delivery_band_performance")

    review_dist = (
        analysis_orders.dropna(subset=["review_score"])
        .assign(review_score=lambda x: x["review_score"].round().astype(int))
        .groupby("review_score", as_index=False)
        .agg(orders=("order_id", "nunique"), gmv=("gmv", "sum"))
        .sort_values("review_score")
    )
    review_dist["order_share"] = review_dist["orders"] / review_dist["orders"].sum()
    save(review_dist, "review_distribution")

    customer_orders = analysis_orders[["customer_unique_id", "order_id", "order_purchase_timestamp", "gmv"]].dropna().copy()
    customer_orders = customer_orders.sort_values(["customer_unique_id", "order_purchase_timestamp"])
    customer_orders["order_number"] = customer_orders.groupby("customer_unique_id").cumcount() + 1
    firsts = customer_orders.groupby("customer_unique_id", as_index=False).agg(
        first_purchase=("order_purchase_timestamp", "min"),
        last_purchase=("order_purchase_timestamp", "max"),
        orders=("order_id", "nunique"),
        lifetime_gmv=("gmv", "sum"),
    )
    second = customer_orders.loc[customer_orders["order_number"].eq(2), ["customer_unique_id", "order_purchase_timestamp"]].rename(columns={"order_purchase_timestamp": "second_purchase"})
    firsts = firsts.merge(second, on="customer_unique_id", how="left")
    firsts["days_to_second"] = (firsts["second_purchase"] - firsts["first_purchase"]).dt.days
    firsts["cohort_month"] = firsts["first_purchase"].dt.to_period("M").astype(str)
    firsts["is_repeat"] = firsts["orders"].ge(2).astype(int)
    for days in [30, 60, 90]:
        firsts[f"repeat_{days}d"] = firsts["days_to_second"].le(days).fillna(False).astype(int)
    customer_summary = firsts.copy()
    save(customer_summary, "customer_summary")

    eligible_cohorts = firsts.loc[firsts["first_purchase"] <= analysis_orders["order_purchase_timestamp"].max() - pd.Timedelta(days=90)].copy()
    cohort = (
        eligible_cohorts.groupby("cohort_month", as_index=False)
        .agg(
            customers=("customer_unique_id", "nunique"),
            repeat_30d=("repeat_30d", "mean"),
            repeat_60d=("repeat_60d", "mean"),
            repeat_90d=("repeat_90d", "mean"),
            avg_lifetime_gmv=("lifetime_gmv", "mean"),
        )
        .sort_values("cohort_month")
    )
    save(cohort, "cohort_repeat")

    seller_order = (
        analysis_items.groupby(["seller_id", "order_id"], as_index=False)
        .agg(gmv=("price", "sum"), is_late=("is_late", "first"), review_score=("review_score", "first"))
    )
    seller = (
        seller_order.groupby("seller_id", as_index=False)
        .agg(gmv=("gmv", "sum"), orders=("order_id", "nunique"), late_rate=("is_late", "mean"), review_score=("review_score", "mean"))
        .sort_values("gmv", ascending=False)
    )
    seller["gmv_share"] = seller["gmv"] / seller["gmv"].sum()
    seller["cumulative_gmv_share"] = seller["gmv_share"].cumsum()
    save(seller, "seller_performance")

    total_gmv = analysis_orders["gmv"].sum()
    total_orders = analysis_orders["order_id"].nunique()
    total_customers = analysis_orders["customer_unique_id"].nunique()
    total_payment = analysis_orders["payment_value"].sum()
    freight_total = analysis_orders["freight_value"].sum()
    payment_gap_abs = analysis_orders["payment_gap_abs"].sum()
    payment_gap_rate = payment_gap_abs / total_payment
    late = delivery_group.set_index("delivery_group").loc["晚到"]
    on_time = delivery_group.set_index("delivery_group").loc["准时"]
    repeat_rate = firsts["is_repeat"].mean()
    repeat_90_rate = eligible_cohorts["repeat_90d"].mean()
    credit_row = payment_type.set_index("primary_payment_type").loc["credit_card"]
    top_state = state.iloc[0]
    top10_category_share = category.head(10)["gmv"].sum() / category["gmv"].sum()
    sellers_for_80 = int((seller["cumulative_gmv_share"] < 0.8).sum() + 1)
    high_freight = category.loc[category["orders"].ge(500)].sort_values("freight_share", ascending=False).iloc[0]

    summary = {
        "window": "2017-01..2018-08",
        "orders": int(total_orders),
        "customers": int(total_customers),
        "gmv": float(total_gmv),
        "payment_value": float(total_payment),
        "aov": float(total_gmv / total_orders),
        "freight_total": float(freight_total),
        "freight_share": float(freight_total / (total_gmv + freight_total)),
        "late_rate": float(analysis_orders["is_late"].mean()),
        "review_score": float(analysis_orders["review_score"].mean()),
        "bad_review_rate": float(analysis_orders["is_bad_review"].mean()),
        "late_review_score": float(late["review_score"]),
        "on_time_review_score": float(on_time["review_score"]),
        "late_bad_review_rate": float(late["bad_review_rate"]),
        "on_time_bad_review_rate": float(on_time["bad_review_rate"]),
        "late_gmv": float(late["gmv"]),
        "repeat_customer_rate": float(repeat_rate),
        "repeat_90d_rate": float(repeat_90_rate),
        "credit_card_order_share": float(credit_row["order_share"]),
        "credit_card_payment_share": float(credit_row["payment_share"]),
        "credit_card_avg_installments": float(credit_row["avg_installments"]),
        "payment_reconciliation_abs_gap": float(payment_gap_abs),
        "payment_reconciliation_gap_rate": float(payment_gap_rate),
        "top_state": str(top_state["customer_state"]),
        "top_state_gmv_share": float(top_state["gmv_share"]),
        "top10_category_gmv_share": float(top10_category_share),
        "sellers_for_80pct_gmv": sellers_for_80,
        "high_freight_category": str(high_freight["product_category"]),
        "high_freight_category_share": float(high_freight["freight_share"]),
    }
    (OUT / "analysis_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    evidence = [
        {"id": "E001", "metric": "scope", "values": {k: summary[k] for k in ["window", "orders", "customers", "gmv", "payment_value", "aov"]}, "source": "orders_enriched.csv", "formula": "2017-01 to 2018-08 delivered orders; GMV=sum(item price)", "filters": "order_status=delivered"},
        {"id": "E002", "metric": "freight", "values": {k: summary[k] for k in ["freight_total", "freight_share", "high_freight_category", "high_freight_category_share"]}, "source": "orders_enriched.csv + order_items_enriched.csv", "formula": "freight/(gmv+freight); high-volume category requires >=500 orders", "filters": "analysis window, delivered"},
        {"id": "E003", "metric": "delivery_experience", "values": {k: summary[k] for k in ["late_rate", "late_review_score", "on_time_review_score", "late_bad_review_rate", "on_time_bad_review_rate", "late_gmv"]}, "source": "delivery_group_performance.csv", "formula": "late if delivered date exceeds estimated date; bad review <=2", "filters": "analysis window, delivered, non-null dates"},
        {"id": "E004", "metric": "payments", "values": {k: summary[k] for k in ["credit_card_order_share", "credit_card_payment_share", "credit_card_avg_installments", "payment_reconciliation_abs_gap", "payment_reconciliation_gap_rate"]}, "source": "payment_type_performance.csv + orders_enriched.csv", "formula": "primary payment type is largest payment record per order; gap=sum(abs(payment-order value))/sum(payment)", "filters": "analysis window, delivered"},
        {"id": "E005", "metric": "customer_repeat", "values": {k: summary[k] for k in ["repeat_customer_rate", "repeat_90d_rate"]}, "source": "customer_summary.csv + cohort_repeat.csv", "formula": "repeat=second order in analysis window; 90d denominator excludes acquisitions without 90 days follow-up", "filters": "2017-01..2018-08 delivered"},
        {"id": "E006", "metric": "concentration", "values": {k: summary[k] for k in ["top_state", "top_state_gmv_share", "top10_category_gmv_share", "sellers_for_80pct_gmv"]}, "source": "state/category/seller performance CSVs", "formula": "share of total GMV and cumulative seller GMV", "filters": "analysis window, delivered"},
    ]
    (OUT / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    quality = {
        "status": "review",
        "raw_orders": int(len(orders)),
        "delivered_analysis_orders": int(total_orders),
        "missing_review_orders": int(analysis_orders["review_score"].isna().sum()),
        "missing_delivery_days": int(analysis_orders["delivery_days"].isna().sum()),
        "duplicate_order_ids": int(orders["order_id"].duplicated().sum()),
        "payment_gap_rate": float(payment_gap_rate),
        "limitations": ["2016 and 2018-09 onward are excluded from trend window because boundary months are incomplete or sparse", "no product cost, platform fee, refund, traffic, inventory, campaign exposure or experiment assignment", "repeat rate is bounded by the observation window"],
    }
    (OUT / "quality_summary.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")

    if DB.exists():
        DB.unlink()
    with sqlite3.connect(DB) as conn:
        for name, frame in {
            "orders_analysis": analysis_orders,
            "monthly_performance": monthly,
            "payment_type_performance": payment_type,
            "installment_performance": installments,
            "category_performance": category,
            "state_performance": state,
            "delivery_group_performance": delivery_group,
            "delivery_band_performance": delivery_bands,
            "review_distribution": review_dist,
            "customer_summary": customer_summary,
            "cohort_repeat": cohort,
            "seller_performance": seller,
        }.items():
            frame.to_sql(name, conn, index=False)
        conn.execute("CREATE INDEX idx_orders_month ON orders_analysis(purchase_month)")
        conn.execute("CREATE INDEX idx_orders_state ON orders_analysis(customer_state)")
        conn.execute("CREATE INDEX idx_orders_payment ON orders_analysis(primary_payment_type)")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
