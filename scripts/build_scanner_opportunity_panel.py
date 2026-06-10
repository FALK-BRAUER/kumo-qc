"""Build the canonical scanner opportunity panel for #463.

The panel is intentionally label-free. It preserves source/provenance flags for Kumo/Falk
scanner candidates and George scanner/watchlist/video evidence, but it does not include future
returns, MFE/MAE, PnL, or path outcomes.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COMPARE_DIR = Path("/Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare")
DEFAULT_GEORGE_CANDIDATES = COMPARE_DIR / "george_scanner_candidates_raw.csv"
DEFAULT_KUMO_CANDIDATES = COMPARE_DIR / "falk_scanner_candidates_enriched.csv"
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "scanner_opportunity_panel_463"
DEFAULT_KUMO_TOP_N = 100

KUMO_USECOLS = [
    "date",
    "symbol",
    "falk_close",
    "falk_volume",
    "falk_dollar_vol",
    "falk_score",
    "falk_gap_pct",
    "falk_vol_ratio_20d",
    "falk_rank_by_score",
    "falk_scanner_source_scope",
    "falk_scanner_source_basis",
    "falk_scanner_price_adjustment",
    "falk_scanner_source_path",
    "falk_scanner_score_df_source",
    "falk_scanner_score_df_commit",
    "falk_scanner_full_rank_available",
    "falk_scanner_targeted_only",
    "in_falk_kumo_scanner",
    "in_falk_kumo_scanner_full_universe",
    "falk_phase2_qualifies_7",
    "falk_phase2_qualifies_6",
    "company_sector",
    "company_industry",
    "sector_category",
    "sector_etf_proxy",
    "sector_profile_ok",
    "source_role",
]

GEORGE_USECOLS = [
    "date",
    "symbol",
    "george_candidate_source",
    "george_source_kind",
    "george_source_confidence_observed",
    "george_rank",
    "george_watchlist_rank",
    "george_watchlist_type",
    "george_pct_change_text",
    "post_id",
    "post_markdown_path",
    "source_path",
    "source_detail",
    "video_id",
    "george_source_family",
    "george_source_role",
    "source_role",
    "george_source_confidence",
    "in_george_scanner",
    "ocr_status",
]

OUTPUT_COLUMNS = [
    "scan_date",
    "symbol",
    "kumo_scanner",
    "kumo_top_n",
    "kumo_full_universe",
    "kumo_targeted_only",
    "george_scanner_ocr",
    "george_scanner_manual",
    "george_scanner_positive",
    "george_watchlist",
    "george_video_mention",
    "kumo_rank_by_score",
    "kumo_score",
    "kumo_close",
    "kumo_volume",
    "kumo_dollar_vol",
    "kumo_gap_pct",
    "kumo_vol_ratio_20d",
    "george_rank",
    "george_watchlist_rank",
    "company_sector",
    "company_industry",
    "sector_category",
    "sector_etf_proxy",
    "source_tags",
    "source_count",
    "kumo_source_scope",
    "kumo_source_basis",
    "kumo_price_adjustment",
    "kumo_source_path",
    "kumo_score_df_source",
    "kumo_score_df_commit",
    "george_candidate_source",
    "george_source_kind",
    "george_source_role",
    "george_source_confidence",
    "george_watchlist_type",
    "george_post_ids",
    "george_video_ids",
    "george_source_paths",
    "george_source_detail",
]

FUTURE_LABEL_TOKENS = (
    "fwd_",
    "mfe",
    "mae",
    "pnl",
    "drawdown",
    "days_to_peak",
    "exit_",
    "sell_",
    "actual_",
    "estimated_",
    "counterfactual_",
)


@dataclass(frozen=True)
class BuildConfig:
    george_candidates: str
    kumo_candidates: str
    output_dir: str
    kumo_top_n: int


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--george-candidates", type=Path, default=DEFAULT_GEORGE_CANDIDATES)
    parser.add_argument("--kumo-candidates", type=Path, default=DEFAULT_KUMO_CANDIDATES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--kumo-top-n", type=int, default=DEFAULT_KUMO_TOP_N)
    return parser.parse_args()


def _read_csv(path: Path, *, usecols: list[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    available = [column for column in usecols if column in set(header)]
    return pd.read_csv(path, usecols=available, low_memory=False)


def _clean_symbol(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def _clean_date(value: Any) -> str:
    if pd.isna(value):
        return ""
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.strftime("%Y-%m-%d")


def _bool_series(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype=bool)
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _text(frame: pd.DataFrame, columns: Iterable[str]) -> pd.Series:
    parts: list[pd.Series] = []
    for column in columns:
        if column in frame.columns:
            parts.append(frame[column].fillna("").astype(str))
    if not parts:
        return pd.Series([""] * len(frame), index=frame.index)
    out = parts[0].copy()
    for part in parts[1:]:
        out = out.str.cat(part, sep=";")
    return out.str.lower()


def _contains_any(text: pd.Series, needles: Iterable[str]) -> pd.Series:
    escaped = "|".join(needles)
    return text.str.contains(escaped, case=False, regex=True, na=False)


def _join_unique(values: Iterable[Any]) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if pd.isna(value):
            continue
        text = str(value).strip()
        if not text or text.lower() == "nan":
            continue
        for part in text.split(";"):
            cleaned = part.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                out.append(cleaned)
    return ";".join(out)


def _min_numeric(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.min())


def _max_numeric(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.max())


def _first_non_empty(values: Iterable[Any]) -> str:
    for value in values:
        if pd.isna(value):
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            return text
    return ""


def normalize_kumo_candidates(path: Path, *, kumo_top_n: int) -> pd.DataFrame:
    frame = _read_csv(path, usecols=KUMO_USECOLS)
    frame["scan_date"] = frame["date"].map(_clean_date)
    frame["symbol"] = frame["symbol"].map(_clean_symbol)
    frame = frame[(frame["scan_date"] != "") & (frame["symbol"] != "")].copy()

    rank = pd.to_numeric(frame.get("falk_rank_by_score"), errors="coerce")
    full_universe = _bool_series(frame.get("in_falk_kumo_scanner_full_universe"))
    scanner_flag = _bool_series(frame.get("in_falk_kumo_scanner"))
    source_scope = frame.get("falk_scanner_source_scope", pd.Series("", index=frame.index)).fillna("").astype(str)
    frame["kumo_scanner"] = scanner_flag | source_scope.ne("")
    frame["kumo_full_universe"] = full_universe | source_scope.eq("phase2_full_universe")
    frame["kumo_targeted_only"] = _bool_series(frame.get("falk_scanner_targeted_only")) | source_scope.eq(
        "targeted_raw_gap_score"
    )
    frame["kumo_top_n"] = frame["kumo_full_universe"] & rank.le(kumo_top_n)
    frame["source_tags"] = "kumo_scanner"
    frame.loc[frame["kumo_top_n"], "source_tags"] = "kumo_scanner;kumo_top_n"

    rename = {
        "falk_rank_by_score": "kumo_rank_by_score",
        "falk_score": "kumo_score",
        "falk_close": "kumo_close",
        "falk_volume": "kumo_volume",
        "falk_dollar_vol": "kumo_dollar_vol",
        "falk_gap_pct": "kumo_gap_pct",
        "falk_vol_ratio_20d": "kumo_vol_ratio_20d",
        "falk_scanner_source_scope": "kumo_source_scope",
        "falk_scanner_source_basis": "kumo_source_basis",
        "falk_scanner_price_adjustment": "kumo_price_adjustment",
        "falk_scanner_source_path": "kumo_source_path",
        "falk_scanner_score_df_source": "kumo_score_df_source",
        "falk_scanner_score_df_commit": "kumo_score_df_commit",
    }
    frame = frame.rename(columns=rename)
    for column in OUTPUT_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[OUTPUT_COLUMNS]


def normalize_george_candidates(path: Path) -> pd.DataFrame:
    frame = _read_csv(path, usecols=GEORGE_USECOLS)
    frame["scan_date"] = frame["date"].map(_clean_date)
    frame["symbol"] = frame["symbol"].map(_clean_symbol)
    frame = frame[(frame["scan_date"] != "") & (frame["symbol"] != "")].copy()

    combined = _text(
        frame,
        [
            "george_candidate_source",
            "george_source_kind",
            "george_source_role",
            "source_role",
            "george_watchlist_type",
        ],
    )
    scanner_ocr = _contains_any(combined, ["scanner_candidate_ocr", "ocr_community_scanner_image", "post_image_ocr"])
    scanner_manual = _contains_any(
        combined,
        [
            "scanner_candidate_manual_markdown",
            "scanner_candidate_legacy_csv",
            "manual_markdown_scanner_table",
            "manual_markdown_top_results",
            "legacy_scanner_csv",
        ],
    )
    watchlist = _contains_any(combined, ["watchlist", "post_text_watchlist", "george_watchlist_text"])
    video = _contains_any(combined, ["video_discussed", "video_analysis", "video_markdown", "video_covered_universe"])
    frame["george_scanner_ocr"] = scanner_ocr
    frame["george_scanner_manual"] = scanner_manual
    frame["george_scanner_positive"] = scanner_ocr | scanner_manual
    frame["george_watchlist"] = watchlist
    frame["george_video_mention"] = video
    frame["source_tags"] = frame.apply(_george_source_tags, axis=1)
    frame["george_post_ids"] = frame.get("post_id", "")
    frame["george_video_ids"] = frame.get("video_id", "")
    frame["george_source_paths"] = frame.get("source_path", "")
    frame["george_source_detail"] = frame.get("source_detail", "")

    for column in OUTPUT_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[OUTPUT_COLUMNS]


def _george_source_tags(row: pd.Series) -> str:
    tags: list[str] = []
    if bool(row.get("george_scanner_ocr")):
        tags.append("george_scanner_ocr")
    if bool(row.get("george_scanner_manual")):
        tags.append("george_scanner_manual")
    if bool(row.get("george_watchlist")):
        tags.append("george_watchlist")
    if bool(row.get("george_video_mention")):
        tags.append("george_video_mention")
    return ";".join(tags) or "george_context"


def build_panel(kumo: pd.DataFrame, george: pd.DataFrame) -> pd.DataFrame:
    combined = pd.concat([kumo, george], ignore_index=True)
    bool_columns = [
        "kumo_scanner",
        "kumo_top_n",
        "kumo_full_universe",
        "kumo_targeted_only",
        "george_scanner_ocr",
        "george_scanner_manual",
        "george_scanner_positive",
        "george_watchlist",
        "george_video_mention",
    ]
    for column in bool_columns:
        combined[column] = _bool_series(combined[column])

    grouped = combined.groupby(["scan_date", "symbol"], sort=True, dropna=False)
    rows: list[dict[str, Any]] = []
    for (scan_date, symbol), group in grouped:
        row: dict[str, Any] = {"scan_date": scan_date, "symbol": symbol}
        for column in bool_columns:
            row[column] = bool(group[column].any())
        row["kumo_rank_by_score"] = _min_numeric(group["kumo_rank_by_score"])
        row["kumo_score"] = _max_numeric(group["kumo_score"])
        row["kumo_close"] = _first_non_empty(group["kumo_close"])
        row["kumo_volume"] = _first_non_empty(group["kumo_volume"])
        row["kumo_dollar_vol"] = _first_non_empty(group["kumo_dollar_vol"])
        row["kumo_gap_pct"] = _first_non_empty(group["kumo_gap_pct"])
        row["kumo_vol_ratio_20d"] = _first_non_empty(group["kumo_vol_ratio_20d"])
        row["george_rank"] = _min_numeric(group["george_rank"])
        row["george_watchlist_rank"] = _min_numeric(group["george_watchlist_rank"])
        for column in [
            "company_sector",
            "company_industry",
            "sector_category",
            "sector_etf_proxy",
            "kumo_source_scope",
            "kumo_source_basis",
            "kumo_price_adjustment",
            "kumo_source_path",
            "kumo_score_df_source",
            "kumo_score_df_commit",
            "george_candidate_source",
            "george_source_kind",
            "george_source_role",
            "george_source_confidence",
            "george_watchlist_type",
            "george_post_ids",
            "george_video_ids",
            "george_source_paths",
            "george_source_detail",
        ]:
            row[column] = _join_unique(group[column])
        row["source_tags"] = _source_tags(row)
        row["source_count"] = len(row["source_tags"].split(";")) if row["source_tags"] else 0
        rows.append(row)

    panel = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    _assert_no_future_labels(panel)
    return panel.sort_values(["scan_date", "symbol"]).reset_index(drop=True)


def _source_tags(row: dict[str, Any]) -> str:
    tags: list[str] = []
    for column in [
        "kumo_scanner",
        "kumo_top_n",
        "george_scanner_ocr",
        "george_scanner_manual",
        "george_watchlist",
        "george_video_mention",
    ]:
        if bool(row.get(column)):
            tags.append(column)
    return ";".join(tags)


def _assert_no_future_labels(panel: pd.DataFrame) -> None:
    bad = [
        column
        for column in panel.columns
        if any(token in column.lower() for token in FUTURE_LABEL_TOKENS)
        and column not in {"kumo_source_path", "george_source_paths"}
    ]
    if bad:
        raise ValueError(f"future/path label columns are not allowed in #463 panel: {bad}")


def source_summary(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    total = len(panel)
    for flag in [
        "kumo_scanner",
        "kumo_top_n",
        "kumo_full_universe",
        "kumo_targeted_only",
        "george_scanner_ocr",
        "george_scanner_manual",
        "george_scanner_positive",
        "george_watchlist",
        "george_video_mention",
    ]:
        count = int(panel[flag].sum())
        rows.append(
            {
                "source_flag": flag,
                "opportunities": count,
                "pct_of_panel": round(100.0 * count / total, 3) if total else 0.0,
                "date_count": int(panel.loc[panel[flag], "scan_date"].nunique()),
                "symbol_count": int(panel.loc[panel[flag], "symbol"].nunique()),
            }
        )
    overlap_masks = {
        "george_scanner_or_watchlist": panel["george_scanner_positive"] | panel["george_watchlist"],
        "kumo_and_george_any": panel["kumo_scanner"]
        & (
            panel["george_scanner_positive"]
            | panel["george_watchlist"]
            | panel["george_video_mention"]
        ),
        "kumo_and_george_scanner_positive": panel["kumo_scanner"] & panel["george_scanner_positive"],
        "george_any_only_no_kumo": (~panel["kumo_scanner"])
        & (
            panel["george_scanner_positive"]
            | panel["george_watchlist"]
            | panel["george_video_mention"]
        ),
        "video_only_context": panel["george_video_mention"]
        & ~panel["george_scanner_positive"]
        & ~panel["george_watchlist"],
    }
    for name, mask in overlap_masks.items():
        count = int(mask.sum())
        rows.append(
            {
                "source_flag": name,
                "opportunities": count,
                "pct_of_panel": round(100.0 * count / total, 3) if total else 0.0,
                "date_count": int(panel.loc[mask, "scan_date"].nunique()),
                "symbol_count": int(panel.loc[mask, "symbol"].nunique()),
            }
        )
    return pd.DataFrame(rows)


def date_summary(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scan_date, group in panel.groupby("scan_date", sort=True):
        rows.append(
            {
                "scan_date": scan_date,
                "opportunities": int(len(group)),
                "kumo_scanner": int(group["kumo_scanner"].sum()),
                "kumo_top_n": int(group["kumo_top_n"].sum()),
                "george_scanner_positive": int(group["george_scanner_positive"].sum()),
                "george_watchlist": int(group["george_watchlist"].sum()),
                "george_video_mention": int(group["george_video_mention"].sum()),
                "video_only_context": int(
                    (
                        group["george_video_mention"]
                        & ~group["george_scanner_positive"]
                        & ~group["george_watchlist"]
                    ).sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def _markdown_table(frame: pd.DataFrame, columns: list[str], *, limit: int | None = None) -> str:
    subset = frame.loc[:, columns]
    if limit is not None:
        subset = subset.head(limit)
    if subset.empty:
        return "_No rows._"
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in subset.iterrows():
        lines.append("| " + " | ".join(str(row[col]) for col in columns) + " |")
    return "\n".join(lines)


def write_report(
    *,
    output_dir: Path,
    panel: pd.DataFrame,
    sources: pd.DataFrame,
    dates: pd.DataFrame,
    config: BuildConfig,
) -> None:
    first_date = panel["scan_date"].min() if len(panel) else ""
    last_date = panel["scan_date"].max() if len(panel) else ""
    lines = [
        "# Scanner Opportunity Panel #463",
        "",
        "This report builds the label-free scanner opportunity surface. It intentionally does not",
        "include future returns, MFE/MAE, PnL, exits, or path labels; those belong to #464.",
        "",
        "## Inputs",
        "",
        f"- George candidates: `{config.george_candidates}`",
        f"- Kumo candidates: `{config.kumo_candidates}`",
        f"- Kumo top-N threshold: `{config.kumo_top_n}`",
        "",
        "## Panel",
        "",
        f"- Opportunities: `{len(panel)}`",
        f"- Date range: `{first_date}` to `{last_date}`",
        f"- Dates: `{panel['scan_date'].nunique()}`",
        f"- Symbols: `{panel['symbol'].nunique()}`",
        "",
        "## Source Summary",
        "",
        _markdown_table(sources, ["source_flag", "opportunities", "pct_of_panel", "date_count", "symbol_count"]),
        "",
        "## Date Sample",
        "",
        _markdown_table(
            dates,
            [
                "scan_date",
                "opportunities",
                "kumo_scanner",
                "kumo_top_n",
                "george_scanner_positive",
                "george_watchlist",
                "george_video_mention",
                "video_only_context",
            ],
            limit=20,
        ),
        "",
        "## Source Semantics",
        "",
        "- `kumo_scanner` means the row came from the Kumo/Falk candidate surface.",
        "- `kumo_top_n` means the full-universe Kumo rank was within the configured top-N threshold.",
        "- `george_scanner_ocr` means OCR/post-image scanner evidence was present.",
        "- `george_scanner_manual` means manual/legacy scanner table evidence was present.",
        "- `george_scanner_positive` is scanner OCR or manual/legacy scanner evidence.",
        "- `george_watchlist` means explicit watchlist/post-text evidence was present.",
        "- `george_video_mention` is context evidence only; video-only rows are not scanner positives.",
        "",
    ]
    (output_dir / "opportunity_panel_report.md").write_text("\n".join(lines), encoding="utf-8")


def write_outputs(
    *,
    panel: pd.DataFrame,
    config: BuildConfig,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    readme = output_dir / "README.md"
    readme.write_text(
        "# scanner_opportunity_panel_463/\n\n"
        "Label-free scanner opportunity panel for issue #463. Keep slim canonical CSVs and summaries "
        "here; do not store raw enriched source files or future-path labels.\n",
        encoding="utf-8",
    )
    panel_path = output_dir / "opportunity_panel.csv.gz"
    with panel_path.open("wb") as raw_fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_fh, mtime=0) as gzip_fh:
            with io.TextIOWrapper(gzip_fh, encoding="utf-8", newline="") as text_fh:
                panel.to_csv(text_fh, index=False)
    sources = source_summary(panel)
    dates = date_summary(panel)
    sources.to_csv(output_dir / "source_summary.csv", index=False)
    dates.to_csv(output_dir / "date_summary.csv", index=False)
    write_report(output_dir=output_dir, panel=panel, sources=sources, dates=dates, config=config)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue": "https://github.com/FALK-BRAUER/kumo-qc/issues/463",
        "config": asdict(config),
        "outputs": {
            "opportunity_panel.csv.gz": {"rows": int(len(panel)), "columns": list(panel.columns)},
            "source_summary.csv": {"rows": int(len(sources))},
            "date_summary.csv": {"rows": int(len(dates))},
            "opportunity_panel_report.md": {},
        },
        "label_free": True,
        "forbidden_label_tokens": FUTURE_LABEL_TOKENS,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "panel": panel_path,
        "source_summary": output_dir / "source_summary.csv",
        "date_summary": output_dir / "date_summary.csv",
        "report": output_dir / "opportunity_panel_report.md",
        "manifest": output_dir / "manifest.json",
    }


def run(
    *,
    george_candidates: Path = DEFAULT_GEORGE_CANDIDATES,
    kumo_candidates: Path = DEFAULT_KUMO_CANDIDATES,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    kumo_top_n: int = DEFAULT_KUMO_TOP_N,
) -> dict[str, Path]:
    config = BuildConfig(
        george_candidates=str(george_candidates),
        kumo_candidates=str(kumo_candidates),
        output_dir=str(output_dir),
        kumo_top_n=kumo_top_n,
    )
    kumo = normalize_kumo_candidates(kumo_candidates, kumo_top_n=kumo_top_n)
    george = normalize_george_candidates(george_candidates)
    panel = build_panel(kumo, george)
    return write_outputs(panel=panel, config=config, output_dir=output_dir)


def main() -> None:
    args = _args()
    outputs = run(
        george_candidates=args.george_candidates,
        kumo_candidates=args.kumo_candidates,
        output_dir=args.output_dir,
        kumo_top_n=args.kumo_top_n,
    )
    for label, path in outputs.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
