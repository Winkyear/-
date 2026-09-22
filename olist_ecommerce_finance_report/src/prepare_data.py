"""Download, clean, model, and quality-check the public Olist dataset."""

from __future__ import annotations

import sqlite3
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIR = PROJECT_ROOT / "output"
DATABASE_PATH = PROJECT_ROOT / "olist_analysis.sqlite"

BASE_URL = "https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets/"
FILES = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}


def download_files() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for filename in FILES.values():
        target = RAW_DIR / filename
        if target.exists() and target.stat().st_size > 0:
            print(f"Using existing raw file: {filename}")
            continue
        print(f"Downloading: {filename}")
        urllib.request.urlretrieve(BASE_URL + filename, target)


def load_tables() -> dict[str, pd.DataFrame]:
    return {
        name: pd.read_csv(RAW_DIR / filename, low_memory=False)
        for name, filename in FILES.items()
    }


def parse_dates(frame: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        frame[column] = pd.to_datetime(frame[column], errors="coerce")


def export_csv(frame: pd.DataFrame, name: str) -> None:
    destination = PROCESSED_DIR / f"{name}.csv"
    frame.to_csv(destination, index=False, encoding="utf-8-sig")
    print(f"Wrote {destination.relative_to(PROJECT_ROOT)}: {len(frame):,} rows")


def main() -> None:
    download_files()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tables = load_tables()
    customers = tables["customers"]
    orders = tables["orders"]
    items = tables["items"]
    payments = tables["payments"]
    products = tables["products"]
    sellers = tables["sellers"]
    reviews = tables["reviews"]
    translation = tables["category_translation"]

    parse_dates(
        orders,
        [
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
    )
    parse_dates(items, ["shipping_limit_date"])
    parse_dates(reviews, ["review_creation_date", "review_answer_timestamp"])

    products = products.merge(translation, on="product_category_name", how="left")
    products = products.rename(
        columns={"product_category_name_english": "product_category"}
    )
    products["product_category"] = products["product_category"].fillna("unknown")

    item_summary = (
        items.groupby("order_id", as_index=False)
        .agg(
            item_count=("order_item_id", "count"),
            seller_count=("seller_id", "nunique"),
            gmv=("price", "sum"),
            freight_value=("freight_value", "sum"),
        )
    )
    item_summary["order_value"] = item_summary["gmv"] + item_summary["freight_value"]

    payment_summary = (
        payments.sort_values(["order_id", "payment_value"], ascending=[True, False])
        .groupby("order_id", as_index=False)
        .agg(
            payment_value=("payment_value", "sum"),
            payment_records=("payment_sequential", "count"),
            max_installments=("payment_installments", "max"),
            primary_payment_type=("payment_type", "first"),
        )
    )

    review_summary = (
        reviews.groupby("order_id", as_index=False)
        .agg(
            review_score=("review_score", "mean"),
            review_records=("review_id", "count"),
            review_creation_date=("review_creation_date", "min"),
        )
    )

    orders_enriched = (
        orders.merge(customers, on="customer_id", how="left", validate="many_to_one")
        .merge(item_summary, on="order_id", how="left", validate="one_to_one")
        .merge(payment_summary, on="order_id", how="left", validate="one_to_one")
        .merge(review_summary, on="order_id", how="left", validate="one_to_one")
    )
    orders_enriched["purchase_date"] = orders_enriched[
        "order_purchase_timestamp"
    ].dt.date
    orders_enriched["purchase_month"] = orders_enriched[
        "order_purchase_timestamp"
    ].dt.to_period("M").astype(str)
    orders_enriched["delivery_days"] = (
        orders_enriched["order_delivered_customer_date"]
        - orders_enriched["order_purchase_timestamp"]
    ).dt.total_seconds() / 86400
    orders_enriched["late_days"] = (
        orders_enriched["order_delivered_customer_date"]
        - orders_enriched["order_estimated_delivery_date"]
    ).dt.total_seconds() / 86400
    orders_enriched["is_late"] = np.where(
        orders_enriched["order_delivered_customer_date"].notna()
        & orders_enriched["order_estimated_delivery_date"].notna(),
        (orders_enriched["late_days"] > 0).astype(int),
        np.nan,
    )
    orders_enriched["is_bad_review"] = np.where(
        orders_enriched["review_score"].notna(),
        (orders_enriched["review_score"] <= 2).astype(int),
        np.nan,
    )
    orders_enriched["is_delivered"] = (
        orders_enriched["order_status"] == "delivered"
    ).astype(int)
    orders_enriched["freight_share"] = orders_enriched["freight_value"] / orders_enriched[
        "order_value"
    ]

    items_enriched = (
        items.merge(
            products[["product_id", "product_category", "product_weight_g"]],
            on="product_id",
            how="left",
            validate="many_to_one",
        )
        .merge(sellers, on="seller_id", how="left", validate="many_to_one")
        .merge(
            orders_enriched[
                [
                    "order_id",
                    "order_status",
                    "order_purchase_timestamp",
                    "purchase_month",
                    "customer_unique_id",
                    "customer_city",
                    "customer_state",
                    "delivery_days",
                    "late_days",
                    "is_late",
                    "review_score",
                    "is_bad_review",
                ]
            ],
            on="order_id",
            how="left",
            validate="many_to_one",
        )
    )
    items_enriched["item_value"] = items_enriched["price"] + items_enriched[
        "freight_value"
    ]
    items_enriched["item_freight_share"] = items_enriched["freight_value"] / items_enriched[
        "item_value"
    ]

    customer_summary = (
        orders_enriched.groupby("customer_unique_id", as_index=False)
        .agg(
            order_count=("order_id", "nunique"),
            delivered_order_count=("is_delivered", "sum"),
            first_purchase=("order_purchase_timestamp", "min"),
            last_purchase=("order_purchase_timestamp", "max"),
            lifetime_gmv=("gmv", "sum"),
            customer_state=("customer_state", "first"),
        )
    )
    customer_summary["is_repeat_customer"] = (
        customer_summary["order_count"] >= 2
    ).astype(int)

    quality_rows = [
        ("orders", "row_count", len(orders)),
        ("orders", "duplicate_order_id", int(orders["order_id"].duplicated().sum())),
        ("orders", "missing_customer_id", int(orders["customer_id"].isna().sum())),
        ("orders", "missing_delivered_date", int(orders["order_delivered_customer_date"].isna().sum())),
        ("items", "row_count", len(items)),
        ("items", "duplicate_order_item_key", int(items.duplicated(["order_id", "order_item_id"]).sum())),
        ("items", "missing_product_id", int(items["product_id"].isna().sum())),
        ("products", "unknown_category", int((products["product_category"] == "unknown").sum())),
        ("reviews", "orders_without_review", int(orders_enriched["review_score"].isna().sum())),
        ("joins", "items_without_order", int(items_enriched["order_status"].isna().sum())),
    ]
    quality_report = pd.DataFrame(
        quality_rows, columns=["table_name", "check_name", "check_value"]
    )

    export_csv(orders_enriched, "orders_enriched")
    export_csv(items_enriched, "order_items_enriched")
    export_csv(customer_summary, "customer_summary")
    export_csv(customers, "dim_customers")
    export_csv(products, "dim_products")
    export_csv(sellers, "dim_sellers")
    export_csv(payments, "fact_payments")
    export_csv(reviews, "fact_reviews")
    quality_report.to_csv(
        OUTPUT_DIR / "data_quality_report.csv", index=False, encoding="utf-8-sig"
    )

    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    with sqlite3.connect(DATABASE_PATH) as connection:
        orders_enriched.to_sql("orders_enriched", connection, index=False)
        items_enriched.to_sql("order_items_enriched", connection, index=False)
        customer_summary.to_sql("customer_summary", connection, index=False)
        quality_report.to_sql("data_quality_report", connection, index=False)
        connection.execute("CREATE INDEX idx_orders_month ON orders_enriched(purchase_month)")
        connection.execute("CREATE INDEX idx_orders_state ON orders_enriched(customer_state)")
        connection.execute("CREATE INDEX idx_items_category ON order_items_enriched(product_category)")
        connection.execute("CREATE INDEX idx_items_seller ON order_items_enriched(seller_id)")

    print(f"SQLite database: {DATABASE_PATH}")


if __name__ == "__main__":
    main()
