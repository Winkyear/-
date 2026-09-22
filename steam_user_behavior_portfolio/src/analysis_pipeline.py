"""Steam 用户行为与内容运营分析主流程。

在 PyCharm 或 Anaconda Prompt 中运行：
    python src/analysis_pipeline.py

输入：
    data/raw/steam_200k.csv
    data/raw/steam_store.csv

输出：
    data/processed/*.csv
    outputs/steam_analysis.db
    outputs/analysis_summary.json
    outputs/evidence.json
    outputs/charts/*.png
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "outputs"
CHART_DIR = OUTPUT_DIR / "charts"


def normalize_name(value: object) -> str:
    """保守标准化游戏名，只做大小写、空白和商标符号处理，不做模糊匹配。"""
    text = str(value).casefold().strip()
    text = re.sub(r"[™®©]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def parse_owner_midpoint(value: object) -> float:
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(value))
    if not match:
        return np.nan
    return (float(match.group(1)) + float(match.group(2))) / 2


def ensure_dirs() -> None:
    for path in (PROCESSED_DIR, OUTPUT_DIR, CHART_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_and_clean() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    raw_behavior = pd.read_csv(
        RAW_DIR / "steam_200k.csv",
        header=None,
        names=["user_id", "game_name", "behavior", "value", "aux"],
    )
    raw_store = pd.read_csv(RAW_DIR / "steam_store.csv")

    quality = {
        "behavior_rows_raw": int(len(raw_behavior)),
        "store_rows_raw": int(len(raw_store)),
        "behavior_exact_duplicates": int(raw_behavior.duplicated().sum()),
        "store_duplicate_appid": int(raw_store["appid"].duplicated().sum()),
        "store_duplicate_name_normalized": 0,
        "invalid_behavior_values": int((~raw_behavior["behavior"].isin(["purchase", "play"])).sum()),
        "nonpositive_play_rows": int(
            ((raw_behavior["behavior"] == "play") & (raw_behavior["value"] <= 0)).sum()
        ),
        "nonunit_purchase_rows": int(
            ((raw_behavior["behavior"] == "purchase") & (raw_behavior["value"] != 1)).sum()
        ),
        "aux_nonzero_rows": int((raw_behavior["aux"] != 0).sum()),
    }

    behavior = raw_behavior.drop_duplicates().copy()
    behavior["user_id"] = pd.to_numeric(behavior["user_id"], errors="coerce").astype("Int64")
    behavior["game_name"] = behavior["game_name"].astype("string").str.strip()
    behavior["behavior"] = behavior["behavior"].astype("string").str.strip().str.lower()
    behavior["value"] = pd.to_numeric(behavior["value"], errors="coerce")
    behavior = behavior[
        behavior["user_id"].notna()
        & behavior["game_name"].notna()
        & behavior["behavior"].isin(["purchase", "play"])
        & behavior["value"].notna()
    ].copy()
    behavior["name_key"] = behavior["game_name"].map(normalize_name)

    store = raw_store.drop_duplicates(subset=["appid"]).copy()
    store["name_key"] = store["name"].map(normalize_name)
    quality["store_duplicate_name_normalized"] = int(store["name_key"].duplicated().sum())
    store = store.sort_values("appid").drop_duplicates(subset=["name_key"], keep="first")
    store["release_date"] = pd.to_datetime(store["release_date"], errors="coerce")
    store["release_year"] = store["release_date"].dt.year.astype("Int64")
    store["primary_genre"] = (
        store["genres"].fillna("Unknown").astype(str).str.split(";").str[0].replace("", "Unknown")
    )
    store["rating_count"] = store["positive_ratings"] + store["negative_ratings"]
    store["positive_rate"] = np.where(
        store["rating_count"] > 0,
        store["positive_ratings"] / store["rating_count"],
        np.nan,
    )
    store["owner_midpoint"] = store["owners"].map(parse_owner_midpoint)
    store["is_free"] = (store["price"] == 0).astype(int)
    store["price_band"] = pd.cut(
        store["price"],
        bins=[-0.01, 0, 5, 10, 20, np.inf],
        labels=["免费", "£0-5", "£5-10", "£10-20", "£20+"],
        include_lowest=True,
    ).astype("string")

    quality["behavior_rows_clean"] = int(len(behavior))
    quality["store_rows_clean"] = int(len(store))
    quality["behavior_missing_after_parse"] = int(
        behavior[["user_id", "game_name", "behavior", "value"]].isna().any(axis=1).sum()
    )
    quality["store_missing_release_date"] = int(store["release_date"].isna().sum())
    quality["store_missing_genres"] = int(store["genres"].isna().sum())
    return behavior, store, quality


def build_models(
    behavior: pd.DataFrame, store: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    purchase = (
        behavior.loc[behavior["behavior"] == "purchase", ["user_id", "name_key", "game_name"]]
        .drop_duplicates(["user_id", "name_key"])
        .assign(purchased=1)
    )
    play = (
        behavior.loc[behavior["behavior"] == "play"]
        .groupby(["user_id", "name_key"], as_index=False)
        .agg(play_hours=("value", "sum"))
    )
    fact = purchase.merge(play, on=["user_id", "name_key"], how="outer")
    fact["purchased"] = fact["purchased"].fillna(0).astype(int)
    fact["play_hours"] = fact["play_hours"].fillna(0.0)
    fact["played"] = (fact["play_hours"] > 0).astype(int)
    fact["game_name"] = fact["game_name"].fillna(fact["name_key"])

    store_cols = [
        "appid", "name_key", "name", "release_date", "release_year", "developer", "publisher",
        "platforms", "categories", "genres", "primary_genre", "steamspy_tags", "positive_ratings",
        "negative_ratings", "rating_count", "positive_rate", "average_playtime", "median_playtime",
        "owners", "owner_midpoint", "price", "price_band", "is_free",
    ]
    fact = fact.merge(store[store_cols], on="name_key", how="left", validate="many_to_one")
    fact["store_matched"] = fact["appid"].notna().astype(int)
    # 原始数据把 DLC、地图包等“拥有但不可单独启动”的内容也记为 purchase。
    # 若某个名称在全样本从未出现 play，则不把它计入可行动的购买后启动率分母。
    fact["observed_playable"] = fact.groupby("name_key")["played"].transform("max").astype(int)
    fact["playable_purchase"] = fact["purchased"] * fact["observed_playable"]

    users = (
        fact.groupby("user_id", as_index=False)
        .agg(
            library_size_all=("purchased", "sum"),
            playable_library_size=("playable_purchase", "sum"),
            played_games=("played", "sum"),
            total_play_hours=("play_hours", "sum"),
            matched_games=("store_matched", "sum"),
            nonplayable_owned=("observed_playable", lambda x: int((x == 0).sum())),
            distinct_genres=("primary_genre", lambda x: x.dropna().nunique()),
        )
    )
    users["library_size"] = users["playable_library_size"]
    users["activation_rate"] = np.where(
        users["playable_library_size"] > 0,
        users["played_games"] / users["playable_library_size"],
        np.nan,
    )
    users["avg_hours_per_played_game"] = np.where(
        users["played_games"] > 0, users["total_play_hours"] / users["played_games"], 0
    )
    q = {
        "library_q25": float(users["library_size"].quantile(0.25)),
        "library_q75": float(users["library_size"].quantile(0.75)),
        "hours_q25": float(users["total_play_hours"].quantile(0.25)),
        "hours_q75": float(users["total_play_hours"].quantile(0.75)),
        "activation_median": float(users["activation_rate"].median()),
    }
    conditions = [
        (users["library_size"] >= q["library_q75"])
        & (users["activation_rate"] < q["activation_median"]),
        (users["total_play_hours"] >= q["hours_q75"])
        & (users["activation_rate"] >= q["activation_median"]),
        (users["library_size"] <= q["library_q25"])
        & (users["total_play_hours"] <= q["hours_q25"]),
    ]
    users["segment"] = np.select(
        conditions,
        ["大库低启动", "深度活跃", "轻量用户"],
        default="常规玩家",
    )

    games = (
        fact.groupby(["name_key", "game_name"], as_index=False)
        .agg(
            purchase_users=("purchased", "sum"),
            played_users=("played", "sum"),
            total_play_hours=("play_hours", "sum"),
            appid=("appid", "first"),
            publisher=("publisher", "first"),
            primary_genre=("primary_genre", "first"),
            release_year=("release_year", "first"),
            price=("price", "first"),
            price_band=("price_band", "first"),
            positive_rate=("positive_rate", "first"),
            rating_count=("rating_count", "first"),
            owner_midpoint=("owner_midpoint", "first"),
            store_matched=("store_matched", "max"),
            observed_playable=("observed_playable", "max"),
        )
    )
    games["activation_rate"] = np.where(
        games["purchase_users"] > 0, games["played_users"] / games["purchase_users"], np.nan
    )
    games["avg_hours_per_player"] = np.where(
        games["played_users"] > 0, games["total_play_hours"] / games["played_users"], 0
    )
    eligible = games[(games["purchase_users"] >= 20) & (games["observed_playable"] == 1)]
    purchase_median = float(eligible["purchase_users"].median())
    activation_median = float(eligible["activation_rate"].median())
    games["content_quadrant"] = np.select(
        [
            (games["purchase_users"] >= purchase_median) & (games["activation_rate"] >= activation_median),
            (games["purchase_users"] >= purchase_median) & (games["activation_rate"] < activation_median),
            (games["purchase_users"] < purchase_median) & (games["activation_rate"] >= activation_median),
        ],
        ["高规模高激活", "高规模低激活", "低规模高激活"],
        default="低规模低激活",
    )
    games.loc[games["purchase_users"] < 20, "content_quadrant"] = "样本不足"
    games.loc[games["observed_playable"] == 0, "content_quadrant"] = "非独立游玩候选"

    matched_fact = fact[fact["store_matched"] == 1].copy()
    genres = (
        matched_fact.groupby("primary_genre", as_index=False)
        .agg(
            purchase_pairs=("purchased", "sum"),
            played_pairs=("played", "sum"),
            total_play_hours=("play_hours", "sum"),
            unique_users=("user_id", "nunique"),
            unique_games=("name_key", "nunique"),
        )
    )
    genres["activation_rate"] = genres["played_pairs"] / genres["purchase_pairs"]
    genres["play_hours_share"] = genres["total_play_hours"] / genres["total_play_hours"].sum()

    segments = (
        users.groupby("segment", as_index=False)
        .agg(
            users=("user_id", "nunique"),
            avg_library_size=("library_size", "mean"),
            avg_played_games=("played_games", "mean"),
            avg_activation_rate=("activation_rate", "mean"),
            avg_total_play_hours=("total_play_hours", "mean"),
            median_total_play_hours=("total_play_hours", "median"),
        )
    )
    segments["user_share"] = segments["users"] / segments["users"].sum()

    summary = calculate_summary(fact, users, games, genres, segments, q)
    return fact, users, games, genres, segments, summary


def calculate_summary(
    fact: pd.DataFrame,
    users: pd.DataFrame,
    games: pd.DataFrame,
    genres: pd.DataFrame,
    segments: pd.DataFrame,
    thresholds: dict,
) -> dict:
    purchases = int(fact["purchased"].sum())
    played = int(fact["played"].sum())
    playable_purchases = int(fact["playable_purchase"].sum())
    total_hours = float(fact["play_hours"].sum())
    games_sorted_purchase = games.sort_values("purchase_users", ascending=False)
    games_sorted_hours = games.sort_values("total_play_hours", ascending=False)
    n_top_1pct = max(1, int(np.ceil(len(games) * 0.01)))

    top10_purchase_share = float(games_sorted_purchase.head(10)["purchase_users"].sum() / purchases)
    top10_hours_share = float(games_sorted_hours.head(10)["total_play_hours"].sum() / total_hours)
    top1pct_purchase_share = float(
        games_sorted_purchase.head(n_top_1pct)["purchase_users"].sum() / purchases
    )
    top1pct_hours_share = float(
        games_sorted_hours.head(n_top_1pct)["total_play_hours"].sum() / total_hours
    )
    matched = fact["store_matched"] == 1
    matched_purchase_share = float(fact.loc[matched, "purchased"].sum() / purchases)
    matched_game_share = float(games["store_matched"].mean())
    one_purchase_game_share = float((games["purchase_users"] == 1).mean())

    segment_map = segments.set_index("segment").to_dict("index")
    top_genres = (
        genres.sort_values("total_play_hours", ascending=False)
        .head(8)
        .round({"activation_rate": 6, "play_hours_share": 6})
        .to_dict("records")
    )
    top_purchase_games = (
        games_sorted_purchase.head(10)[
            ["game_name", "purchase_users", "played_users", "activation_rate", "total_play_hours"]
        ]
        .round({"activation_rate": 6, "total_play_hours": 2})
        .to_dict("records")
    )
    top_hours_games = (
        games_sorted_hours.head(10)[
            ["game_name", "purchase_users", "played_users", "activation_rate", "total_play_hours"]
        ]
        .round({"activation_rate": 6, "total_play_hours": 2})
        .to_dict("records")
    )
    return {
        "row_grain": "user-game aggregate",
        "users": int(users["user_id"].nunique()),
        "games": int(games["name_key"].nunique()),
        "purchase_pairs": purchases,
        "played_pairs": played,
        "unplayed_purchase_pairs": purchases - played,
        "overall_activation_rate": played / purchases,
        "playable_purchase_pairs": playable_purchases,
        "actionable_unplayed_purchase_pairs": playable_purchases - played,
        "playable_activation_rate": played / playable_purchases,
        "never_played_game_count": int((games["observed_playable"] == 0).sum()),
        "never_played_game_purchase_share": float(
            games.loc[games["observed_playable"] == 0, "purchase_users"].sum() / purchases
        ),
        "total_play_hours": total_hours,
        "median_user_library": float(users["library_size"].median()),
        "median_user_play_hours": float(users["total_play_hours"].median()),
        "top10_purchase_share": top10_purchase_share,
        "top10_hours_share": top10_hours_share,
        "top1pct_purchase_share": top1pct_purchase_share,
        "top1pct_hours_share": top1pct_hours_share,
        "one_purchase_game_share": one_purchase_game_share,
        "matched_purchase_share": matched_purchase_share,
        "matched_game_share": matched_game_share,
        "segment_thresholds": thresholds,
        "segments": segment_map,
        "top_genres": top_genres,
        "top_purchase_games": top_purchase_games,
        "top_hours_games": top_hours_games,
    }


def save_models(
    fact: pd.DataFrame,
    users: pd.DataFrame,
    games: pd.DataFrame,
    genres: pd.DataFrame,
    segments: pd.DataFrame,
    quality: dict,
    summary: dict,
) -> None:
    exports = {
        "fact_user_game.csv": fact,
        "dim_user_segments.csv": users,
        "dim_game_metrics.csv": games,
        "agg_genre_metrics.csv": genres,
        "agg_segment_metrics.csv": segments,
    }
    for filename, frame in exports.items():
        frame.to_csv(PROCESSED_DIR / filename, index=False, encoding="utf-8-sig")

    db_path = OUTPUT_DIR / "steam_analysis.db"
    with sqlite3.connect(db_path) as conn:
        fact.to_sql("fact_user_game", conn, if_exists="replace", index=False)
        users.to_sql("dim_user_segments", conn, if_exists="replace", index=False)
        games.to_sql("dim_game_metrics", conn, if_exists="replace", index=False)
        genres.to_sql("agg_genre_metrics", conn, if_exists="replace", index=False)
        segments.to_sql("agg_segment_metrics", conn, if_exists="replace", index=False)
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_fact_user ON fact_user_game(user_id);
            CREATE INDEX IF NOT EXISTS idx_fact_game ON fact_user_game(name_key);
            CREATE INDEX IF NOT EXISTS idx_game_quadrant ON dim_game_metrics(content_quadrant);
            """
        )

    (OUTPUT_DIR / "quality_summary.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "analysis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def create_charts(users: pd.DataFrame, games: pd.DataFrame, genres: pd.DataFrame) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False
    color = "#2F6BFF"

    genre_plot = genres.nlargest(10, "total_play_hours").sort_values("total_play_hours")
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(genre_plot["primary_genre"], genre_plot["total_play_hours"], color=color)
    ax.set_title("Top 10 主类型总游玩时长")
    ax.set_xlabel("小时")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(CHART_DIR / "genre_play_hours.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    plot_games = games[games["purchase_users"] >= 20].copy()
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.scatter(
        plot_games["purchase_users"],
        plot_games["activation_rate"],
        s=np.clip(np.sqrt(plot_games["total_play_hours"]) * 2, 10, 300),
        alpha=0.45,
        color=color,
        edgecolors="none",
    )
    ax.set_xscale("log")
    ax.set_title("游戏购买规模与启动率")
    ax.set_xlabel("购买用户数（对数刻度）")
    ax.set_ylabel("购买后启动率")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(CHART_DIR / "game_scale_activation.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    capped = users["total_play_hours"].clip(upper=users["total_play_hours"].quantile(0.99))
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.hist(capped, bins=40, color=color, alpha=0.85)
    ax.set_title("用户累计游玩时长分布（截尾至 P99）")
    ax.set_xlabel("小时")
    ax.set_ylabel("用户数")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(CHART_DIR / "user_playtime_distribution.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def build_evidence(summary: dict, quality: dict, segments: pd.DataFrame, genres: pd.DataFrame) -> list[dict]:
    seg_records = segments.round(6).to_dict("records")
    genre_records = genres.sort_values("total_play_hours", ascending=False).head(10).round(6).to_dict("records")
    return [
        {
            "id": "E001",
            "metric": "data_scope",
            "values": {
                "behavior_rows": quality["behavior_rows_raw"],
                "users": summary["users"],
                "games": summary["games"],
                "purchase_pairs": summary["purchase_pairs"],
                "played_pairs": summary["played_pairs"],
            },
            "source": "data/raw/steam_200k.csv",
            "formula": "去重 user_id-game_name 后统计 purchase 与 play 记录",
            "filters": "behavior in {purchase, play}",
        },
        {
            "id": "E002",
            "metric": "purchase_activation",
            "values": {
                "purchase_pairs": summary["purchase_pairs"],
                "played_pairs": summary["played_pairs"],
                "unplayed_purchase_pairs": summary["unplayed_purchase_pairs"],
                "overall_activation_rate": summary["overall_activation_rate"],
                "playable_purchase_pairs": summary["playable_purchase_pairs"],
                "actionable_unplayed_purchase_pairs": summary["actionable_unplayed_purchase_pairs"],
                "playable_activation_rate": summary["playable_activation_rate"],
                "never_played_game_count": summary["never_played_game_count"],
                "never_played_game_purchase_share": summary["never_played_game_purchase_share"],
            },
            "source": "data/processed/fact_user_game.csv",
            "formula": "原始口径为 played_pairs / purchase_pairs；可行动口径排除全样本从未出现 play 的内容名",
            "filters": "user-game 粒度；play_hours > 0 记为已启动；DLC 等非独立游玩内容通过 observed_playable=0 单独披露",
        },
        {
            "id": "E003",
            "metric": "content_concentration",
            "values": {
                "top10_purchase_share": summary["top10_purchase_share"],
                "top10_hours_share": summary["top10_hours_share"],
                "top1pct_purchase_share": summary["top1pct_purchase_share"],
                "top1pct_hours_share": summary["top1pct_hours_share"],
                "one_purchase_game_share": summary["one_purchase_game_share"],
            },
            "source": "data/processed/dim_game_metrics.csv",
            "formula": "按游戏聚合后排序，头部总量 / 全量总量",
            "filters": "全部可识别游戏名",
        },
        {
            "id": "E004",
            "metric": "user_segments",
            "values": seg_records,
            "source": "data/processed/agg_segment_metrics.csv",
            "formula": "基于游戏库规模、购买后启动率、总游玩时长的分位数规则分层",
            "filters": "全部用户；互斥且完备",
        },
        {
            "id": "E005",
            "metric": "genre_structure",
            "values": genre_records,
            "source": "data/processed/agg_genre_metrics.csv",
            "formula": "按主类型（genres 第一项）互斥聚合",
            "filters": "仅精确名称匹配到 Steam 商店元数据的记录",
        },
        {
            "id": "E006",
            "metric": "join_quality",
            "values": {
                "matched_purchase_share": summary["matched_purchase_share"],
                "matched_game_share": summary["matched_game_share"],
                "store_duplicate_name_normalized": quality["store_duplicate_name_normalized"],
            },
            "source": "steam_200k.csv + steam_store.csv",
            "formula": "标准化名称精确匹配，不使用模糊匹配",
            "filters": "商标符号移除、大小写折叠、空白压缩",
        },
    ]


def main() -> None:
    ensure_dirs()
    behavior, store, quality = load_and_clean()
    fact, users, games, genres, segments, summary = build_models(behavior, store)
    save_models(fact, users, games, genres, segments, quality, summary)
    create_charts(users, games, genres)
    evidence = build_evidence(summary, quality, segments, genres)
    (OUTPUT_DIR / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
