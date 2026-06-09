"""Offline George/BCT top-K scanner validation harness.

This module is research-only. Runtime strategy code must not import it. It evaluates explicit
George label files against an explicit denominator/candidate panel and reports pool coverage,
gate quality, and rank@K quality for scanner-alignment work.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import math
import pandas as pd

from sweeps.archive import candidates as C
from sweeps.archive import george_coverage_audit as coverage


DEFAULT_KS: tuple[int, ...] = (5, 10, 20, 50, 100)
DEFAULT_TOP_N: int = 3000
DEFAULT_MIN_SCORE: int = 6

DENOMINATOR_USECOLS: tuple[str, ...] = (
    "date",
    "symbol",
    "in_candidate_denominator",
    "adv20_rank_price10",
    "day_dv_rank_price10",
    "bct_score",
    "gap_pct",
    "day_return_pct",
    "intraday_return_pct",
    "range_pct",
    "daily_structure_score",
    "d_price_above_cloud",
    "d_price_above_tenkan",
    "d_price_above_kijun",
    "d_tenkan_extension_pct",
    "d_kijun_extension_pct",
    "d_cloud_distance_pct",
    "d_near_prior20_high_within3",
    "d_near_prior50_high_within5",
    "d_near_prior252_high_within5",
    "d_breakout20_volume_confirmed",
    "d_breakout50_volume_confirmed",
    "d_breakout252_volume_confirmed",
    "d_no_chase_risk",
    "d_bearish_reversal_candle",
    "d_shooting_star_like",
    "rel_volume20",
    "w_price_above_cloud",
)


@dataclass(frozen=True, slots=True)
class AuditConfig:
    """Top-K audit settings."""

    top_n: int = DEFAULT_TOP_N
    min_score: int = DEFAULT_MIN_SCORE
    ks: tuple[int, ...] = DEFAULT_KS


@dataclass(frozen=True, slots=True)
class TopKAuditResult:
    """In-memory result tables from a George top-K audit."""

    base_summary: pd.DataFrame
    gate_summary: pd.DataFrame
    rank_summary: pd.DataFrame
    failure_examples: pd.DataFrame


def _bool_col(df: pd.DataFrame, col: str, *, default: bool = False) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=bool)
    series = df[col]
    if series.dtype == bool:
        return series.fillna(default).astype(bool)
    return series.astype(str).str.lower().isin(("true", "1", "yes"))


def _num_col(df: pd.DataFrame, col: str, *, default: float = math.nan) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce")


def _normalize_denominator(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = out["date"].astype(str)
    out["symbol"] = out["symbol"].astype(str).str.upper()
    out["key"] = out["date"] + "|" + out["symbol"]
    return out


def load_denominator(path: Path) -> pd.DataFrame:
    """Load only the denominator columns this audit needs."""
    return pd.read_csv(path, usecols=list(DENOMINATOR_USECOLS), low_memory=False)


def covered_dates_from_coarse(year: int, coarse_dir: Path) -> set[str]:
    """Return QC coarse-covered dates for `year`, failing loudly when the cache is empty."""
    _universe, coarse_metrics = C.build_coarse_universe(year, coarse_dir=coarse_dir)
    dates = set(coarse_metrics.keys())
    if not dates:
        raise ValueError(
            f"no coarse dates found for {year} under {coarse_dir}; pass the populated QC data cache"
        )
    return dates


def load_covered_labels(labels_path: Path, *, covered_dates: set[str]) -> list[tuple[str, str]]:
    """Load George labels and keep only dates covered by the audit substrate."""
    labels = coverage.load_george_labels(labels_path)
    return [(date, symbol) for date, symbol in labels if date in covered_dates]


def build_score6_panel(
    denominator: pd.DataFrame,
    labels: Sequence[tuple[str, str]],
    *,
    covered_dates: set[str],
    config: AuditConfig = AuditConfig(),
) -> pd.DataFrame:
    """Build the broad score-6 candidate panel and stamp `is_george` labels."""
    label_keys = {f"{date}|{symbol.upper()}" for date, symbol in labels}
    df = _normalize_denominator(denominator)
    mask = (
        _bool_col(df, "in_candidate_denominator")
        & df["date"].isin(covered_dates)
        & (_num_col(df, "adv20_rank_price10") <= config.top_n)
        & (_num_col(df, "bct_score") >= config.min_score)
    )
    panel = df.loc[mask].copy()
    panel["is_george"] = panel["key"].isin(label_keys)
    return panel


def summarize_base_panel(panel: pd.DataFrame, *, label_count: int) -> pd.DataFrame:
    """Return one-row coverage summary for the score-6 base panel."""
    hits = int(_bool_col(panel, "is_george").sum())
    daily_counts = panel.groupby("date").size()
    return pd.DataFrame(
        [
            {
                "rows": int(len(panel)),
                "dates": int(panel["date"].nunique()) if "date" in panel else 0,
                "median_daily": float(daily_counts.median()) if not daily_counts.empty else 0.0,
                "hits": hits,
                "label_count": int(label_count),
                "recall_pct": round(100.0 * hits / label_count, 2) if label_count else 0.0,
                "precision_pct": round(100.0 * hits / len(panel), 3) if len(panel) else 0.0,
            }
        ]
    )


def default_gates(panel: pd.DataFrame) -> dict[str, pd.Series]:
    """Reusable clean gates from the score-6 selector audit."""
    bct = _num_col(panel, "bct_score")
    adv_rank = _num_col(panel, "adv20_rank_price10")
    day_dv_rank = _num_col(panel, "day_dv_rank_price10")
    tenkan_ext = _num_col(panel, "d_tenkan_extension_pct")
    gap = _num_col(panel, "gap_pct")
    day_return = _num_col(panel, "day_return_pct")

    gates: dict[str, pd.Series] = {
        "bct_score_ge7": bct >= 7,
        "bct_score_eq6": bct == 6,
        "adv_top2000": adv_rank <= 2000,
        "adv_top1500": adv_rank <= 1500,
        "daydv_top1000": day_dv_rank <= 1000,
        "daydv_top500": day_dv_rank <= 500,
        "day_green": day_return > 0,
        "day_quiet_any_m2_4": day_return.between(-2, 4, inclusive="both"),
        "gap_0_3": gap.between(0, 3, inclusive="both"),
        "tenkan_ext_0_6": tenkan_ext.between(0, 6, inclusive="both"),
        "tenkan_ext_m1_6": tenkan_ext.between(-1, 6, inclusive="both"),
        "above_daily_cloud": _bool_col(panel, "d_price_above_cloud"),
        "above_daily_tenkan": _bool_col(panel, "d_price_above_tenkan"),
        "above_daily_kijun": _bool_col(panel, "d_price_above_kijun"),
        "no_nochase": ~_bool_col(panel, "d_no_chase_risk"),
        "no_bearish_reversal": ~_bool_col(panel, "d_bearish_reversal_candle"),
        "no_shooting_star": ~_bool_col(panel, "d_shooting_star_like"),
        "relvol20_07_18": _num_col(panel, "rel_volume20").between(0.7, 1.8, inclusive="both"),
        "weekly_above_cloud": _bool_col(panel, "w_price_above_cloud"),
    }
    gates["clean_daily_base"] = (
        gates["above_daily_cloud"]
        & gates["above_daily_tenkan"]
        & gates["above_daily_kijun"]
        & gates["no_nochase"]
    )
    gates["pullback_like"] = (
        gates["tenkan_ext_m1_6"]
        & gates["above_daily_kijun"]
        & gates["above_daily_cloud"]
        & gates["day_quiet_any_m2_4"]
        & gates["no_nochase"]
    )
    gates["prior_high_clean"] = (
        (
            _bool_col(panel, "d_near_prior20_high_within3")
            | _bool_col(panel, "d_near_prior50_high_within5")
            | _bool_col(panel, "d_near_prior252_high_within5")
        )
        & gates["no_bearish_reversal"]
        & gates["no_nochase"]
    )
    gates["breakout_any_vol_clean"] = (
        (
            _bool_col(panel, "d_breakout20_volume_confirmed")
            | _bool_col(panel, "d_breakout50_volume_confirmed")
            | _bool_col(panel, "d_breakout252_volume_confirmed")
        )
        & gates["no_nochase"]
    )
    gates["clean_top2000"] = gates["adv_top2000"] & gates["clean_daily_base"]
    gates["pullback_top2000"] = gates["adv_top2000"] & gates["pullback_like"]
    gates["score6_clean_all"] = (
        gates["bct_score_eq6"]
        & gates["clean_daily_base"]
        & gates["tenkan_ext_0_6"]
        & gates["no_bearish_reversal"]
    )
    gates["score7_or_clean6"] = gates["bct_score_ge7"] | (
        gates["bct_score_eq6"] & gates["clean_daily_base"] & gates["tenkan_ext_0_6"]
    )
    return gates


def summarize_gates(
    panel: pd.DataFrame,
    gates: Mapping[str, pd.Series],
    *,
    label_count: int,
) -> pd.DataFrame:
    """Summarize each gate by pool size, recall, precision, and lift."""
    base_hits = int(_bool_col(panel, "is_george").sum())
    base_rate = base_hits / len(panel) if len(panel) else 0.0
    rows: list[dict[str, Any]] = []
    for name, mask in gates.items():
        selected = panel.loc[mask.fillna(False).astype(bool)]
        hits = int(_bool_col(selected, "is_george").sum())
        daily_counts = selected.groupby("date").size()
        precision = hits / len(selected) if len(selected) else 0.0
        rows.append(
            {
                "name": name,
                "rows": int(len(selected)),
                "median_daily": round(float(daily_counts.median()), 2) if not daily_counts.empty else 0.0,
                "avg_daily": round(float(daily_counts.mean()), 2) if not daily_counts.empty else 0.0,
                "hits": hits,
                "recall_pct": round(100.0 * hits / label_count, 2) if label_count else 0.0,
                "within_base_recall_pct": round(100.0 * hits / base_hits, 2) if base_hits else 0.0,
                "precision_pct": round(100.0 * precision, 3),
                "lift": round(precision / base_rate, 2) if base_rate else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values(["recall_pct", "precision_pct"], ascending=False).reset_index(drop=True)


def _percentile_rank(series: pd.Series, panel: pd.DataFrame, *, ascending: bool) -> pd.Series:
    return series.groupby(panel["date"]).rank(pct=True, ascending=ascending).fillna(0.5)


def default_rank_variants(panel: pd.DataFrame, gates: Mapping[str, pd.Series]) -> dict[str, tuple[pd.Series, pd.Series]]:
    """Return deterministic rank variants used as top-K baselines."""
    all_rows = pd.Series(True, index=panel.index, dtype=bool)
    bct = _num_col(panel, "bct_score").astype(float)
    daily_structure = _num_col(panel, "daily_structure_score").fillna(0.0)
    adv_rank = _num_col(panel, "adv20_rank_price10")
    adv_bonus = 1.0 - _percentile_rank(adv_rank, panel, ascending=True)
    qc_fixed_proxy = (
        bct
        + (bct >= 8).astype(float)
        + ((bct >= 7) & (bct < 8)).astype(float) * 0.5
        + _bool_col(panel, "d_price_above_tenkan").astype(float) * 0.45
        + _bool_col(panel, "d_price_above_kijun").astype(float) * 0.45
        + _bool_col(panel, "d_price_above_cloud").astype(float) * 0.35
        + _num_col(panel, "d_tenkan_extension_pct").between(0, 5, inclusive="both").astype(float) * 0.75
        + _num_col(panel, "d_kijun_extension_pct").between(0, 10, inclusive="both").astype(float) * 0.35
        + _num_col(panel, "d_cloud_distance_pct").between(0, 10, inclusive="both").astype(float) * 0.30
        + gates.get("prior_high_clean", all_rows & False).astype(float)
        + gates.get("breakout_any_vol_clean", all_rows & False).astype(float)
        - _bool_col(panel, "d_no_chase_risk").astype(float) * 2.0
        - _bool_col(panel, "d_bearish_reversal_candle").astype(float)
    )
    clean_chart_simple = (
        bct
        + daily_structure * 0.30
        + gates.get("tenkan_ext_0_6", all_rows & False).astype(float) * 1.2
        + gates.get("day_quiet_any_m2_4", all_rows & False).astype(float) * 0.8
        + gates.get("gap_0_3", all_rows & False).astype(float) * 0.6
        + gates.get("prior_high_clean", all_rows & False).astype(float) * 0.8
        + gates.get("relvol20_07_18", all_rows & False).astype(float) * 0.4
        + gates.get("weekly_above_cloud", all_rows & False).astype(float) * 0.5
        + adv_bonus * 0.2
        - _bool_col(panel, "d_no_chase_risk").astype(float) * 1.7
        - _bool_col(panel, "d_bearish_reversal_candle").astype(float) * 0.8
        - _bool_col(panel, "d_shooting_star_like").astype(float) * 0.5
    )
    variants: dict[str, tuple[pd.Series, pd.Series]] = {
        "base__daily_structure_rank": (all_rows, daily_structure),
        "base__qc_fixed_proxy": (all_rows, qc_fixed_proxy),
        "base__clean_chart_simple": (all_rows, clean_chart_simple),
    }
    for gate_name in ("clean_top2000", "pullback_top2000", "score7_or_clean6"):
        gate = gates.get(gate_name)
        if gate is not None:
            variants[f"{gate_name}__daily_structure_rank"] = (gate, daily_structure)
            variants[f"{gate_name}__clean_chart_simple"] = (gate, clean_chart_simple)
    return variants


def _average_precision(relevance: Sequence[bool]) -> float:
    relevant_total = int(sum(1 for item in relevance if item))
    if relevant_total == 0:
        return math.nan
    hits = 0
    precision_sum = 0.0
    for rank, relevant in enumerate(relevance, start=1):
        if not relevant:
            continue
        hits += 1
        precision_sum += hits / rank
    return precision_sum / relevant_total


def _ndcg_at_k(relevance: Sequence[bool], *, k: int) -> float:
    relevant_total = int(sum(1 for item in relevance if item))
    if relevant_total == 0:
        return math.nan
    discounts = [1.0 / math.log2(rank + 1) for rank in range(1, min(k, len(relevance)) + 1)]
    dcg = sum(discount for discount, relevant in zip(discounts, relevance[:k]) if relevant)
    ideal_len = min(k, relevant_total)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_len + 1))
    return dcg / ideal if ideal else math.nan


def _mean_ranking_metric(
    selected: pd.DataFrame,
    *,
    metric: str,
    k: int | None = None,
) -> float:
    values: list[float] = []
    for _date, group in selected.groupby("date", sort=False):
        relevance = group["_is_george"].astype(bool).tolist()
        value = _average_precision(relevance) if metric == "ap" else _ndcg_at_k(relevance, k=k or 10)
        if not math.isnan(value):
            values.append(value)
    return round(100.0 * sum(values) / len(values), 2) if values else 0.0


def _ranked_variant_frame(
    panel: pd.DataFrame,
    gate: pd.Series,
    score: pd.Series,
) -> pd.DataFrame:
    is_george = _bool_col(panel, "is_george")
    adv_rank = _num_col(panel, "adv20_rank_price10", default=math.inf)
    selected = panel.loc[gate.fillna(False).astype(bool), ["date", "symbol"]].copy()
    selected["_score"] = score.loc[selected.index].fillna(float("-inf"))
    selected["_adv_rank"] = adv_rank.loc[selected.index].fillna(math.inf)
    selected["_is_george"] = is_george.loc[selected.index]
    selected = selected.sort_values(
        ["date", "_score", "_adv_rank", "symbol"],
        ascending=[True, False, True, True],
    )
    selected["rank"] = selected.groupby("date").cumcount() + 1
    return selected


def evaluate_rank_variants(
    panel: pd.DataFrame,
    variants: Mapping[str, tuple[pd.Series, pd.Series]],
    *,
    label_count: int,
    ks: Sequence[int] = DEFAULT_KS,
) -> pd.DataFrame:
    """Evaluate rank@K for each deterministic variant."""
    rows: list[dict[str, Any]] = []
    for name, (gate, score) in variants.items():
        selected = _ranked_variant_frame(panel, gate, score)
        george_rows = selected[selected["_is_george"]]
        row: dict[str, Any] = {
            "variant": name,
            "rows": int(len(selected)),
            "median_daily": (
                round(float(selected.groupby("date").size().median()), 2) if len(selected) else 0.0
            ),
            "seen_hits": int(len(george_rows)),
            "seen_recall_pct": round(100.0 * len(george_rows) / label_count, 2) if label_count else 0.0,
            "median_george_rank": (
                round(float(george_rows["rank"].median()), 2) if len(george_rows) else math.nan
            ),
            "map_seen_pct": _mean_ranking_metric(selected, metric="ap"),
        }
        for k in ks:
            top = selected[selected["rank"] <= k]
            hits = int(top["_is_george"].sum())
            row[f"hits{k}"] = hits
            row[f"recall{k}_pct"] = round(100.0 * hits / label_count, 2) if label_count else 0.0
            row[f"precision{k}_pct"] = round(100.0 * hits / len(top), 2) if len(top) else 0.0
            row[f"ndcg{k}_seen_pct"] = _mean_ranking_metric(selected, metric="ndcg", k=k)
        rows.append(row)
    sort_cols = [f"recall{ks[1] if len(ks) > 1 else ks[0]}_pct", f"recall{ks[0]}_pct"]
    return pd.DataFrame(rows).sort_values(sort_cols, ascending=False).reset_index(drop=True)


def rank_failure_examples(
    panel: pd.DataFrame,
    variants: Mapping[str, tuple[pd.Series, pd.Series]],
    *,
    k: int = 10,
    limit_per_variant: int = 5,
) -> pd.DataFrame:
    """Return per-date examples where seen George rows miss the top-K list."""
    rows: list[dict[str, Any]] = []
    for name, (gate, score) in variants.items():
        selected = _ranked_variant_frame(panel, gate, score)
        variant_rows: list[dict[str, Any]] = []
        for date, group in selected.groupby("date", sort=False):
            george_rows = group[group["_is_george"]]
            if george_rows.empty:
                continue
            top = group[group["rank"] <= k]
            if bool(top["_is_george"].any()):
                continue
            variant_rows.append(
                {
                    "variant": name,
                    "date": str(date),
                    "k": int(k),
                    "seen_george_count": int(len(george_rows)),
                    "best_george_rank": int(george_rows["rank"].min()),
                    "george_symbols": ";".join(
                        f"{row.symbol}@{int(row.rank)}" for row in george_rows.itertuples()
                    ),
                    "top_symbols": ";".join(str(symbol) for symbol in top["symbol"].tolist()),
                }
            )
        rows.extend(sorted(variant_rows, key=lambda row: row["best_george_rank"], reverse=True)[:limit_per_variant])
    return pd.DataFrame(
        rows,
        columns=[
            "variant",
            "date",
            "k",
            "seen_george_count",
            "best_george_rank",
            "george_symbols",
            "top_symbols",
        ],
    )


def run_topk_audit(
    denominator: pd.DataFrame,
    labels: Sequence[tuple[str, str]],
    *,
    covered_dates: set[str],
    config: AuditConfig = AuditConfig(),
) -> TopKAuditResult:
    """Run the reusable in-memory score-6 top-K audit."""
    panel = build_score6_panel(denominator, labels, covered_dates=covered_dates, config=config)
    gates = default_gates(panel)
    variants = default_rank_variants(panel, gates)
    return TopKAuditResult(
        base_summary=summarize_base_panel(panel, label_count=len(labels)),
        gate_summary=summarize_gates(panel, gates, label_count=len(labels)),
        rank_summary=evaluate_rank_variants(
            panel,
            variants,
            label_count=len(labels),
            ks=config.ks,
        ),
        failure_examples=rank_failure_examples(panel, variants, k=10),
    )


def write_result(result: TopKAuditResult, output_dir: Path) -> None:
    """Write audit result tables as CSVs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result.base_summary.to_csv(output_dir / "base_summary.csv", index=False)
    result.gate_summary.to_csv(output_dir / "gate_summary.csv", index=False)
    result.rank_summary.to_csv(output_dir / "rank_summary.csv", index=False)
    result.failure_examples.to_csv(output_dir / "failure_examples.csv", index=False)


def _print_result(result: TopKAuditResult) -> None:
    print("\nBASE")
    print(result.base_summary.to_string(index=False))
    print("\nTOP GATES BY RECALL")
    print(result.gate_summary.head(20).to_string(index=False))
    print("\nRANK VARIANTS")
    print(result.rank_summary.head(20).to_string(index=False))
    print("\nFAILURE EXAMPLES")
    print(result.failure_examples.head(20).to_string(index=False))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-csv", required=True, type=Path)
    parser.add_argument("--denominator-csv", required=True, type=Path)
    parser.add_argument("--coarse-dir", required=True, type=Path)
    parser.add_argument("--year", default=2026, type=int)
    parser.add_argument("--top-n", default=DEFAULT_TOP_N, type=int)
    parser.add_argument("--min-score", default=DEFAULT_MIN_SCORE, type=int)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    covered_dates = covered_dates_from_coarse(args.year, args.coarse_dir)
    labels = load_covered_labels(args.labels_csv, covered_dates=covered_dates)
    if not labels:
        raise ValueError("no George labels remain after covered-date filtering")
    result = run_topk_audit(
        load_denominator(args.denominator_csv),
        labels,
        covered_dates=covered_dates,
        config=AuditConfig(top_n=args.top_n, min_score=args.min_score),
    )
    _print_result(result)
    if args.output_dir is not None:
        write_result(result, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
