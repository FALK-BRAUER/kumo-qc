#!/usr/bin/env python3
"""
fetch_community_strategies.py — Download QC community strategy leaderboard.

Public endpoint (no auth required):
  https://www.quantconnect.com/api/v2/strategies/list

Saves:
  - qc/community/<rank>-<slug>.json   one file per strategy
  - qc/community/INDEX.md             summary table sorted by leaderboard rank

Usage:
  python3 scripts/fetch_community_strategies.py [--max 100] [--out qc/community]

Notes:
  - The endpoint paginates via 'start' param (default page size appears to be 10).
  - We page until we have 'max' strategies or no more results.
  - No credentials needed; the leaderboard is public.
"""

import argparse
import json
import re
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

BASE_URL = "https://www.quantconnect.com/api/v2/strategies/list"
DEFAULT_MAX = 100
DEFAULT_OUT = Path(__file__).parent.parent / "qc" / "community"
PAGE_SIZE = 10
SLEEP_BETWEEN_PAGES = 1.0  # seconds — be polite


def slugify(name: str) -> str:
    """Convert strategy name to safe filename slug."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:60]  # cap length


def fetch_page(start: int, count: int = PAGE_SIZE) -> dict:
    """Fetch one page of strategies from the public leaderboard.

    The endpoint uses start + end (inclusive range), not start + count.
    """
    end = start + count  # end is exclusive upper index
    url = f"{BASE_URL}?start={start}&end={end}"
    req = Request(url, headers={"User-Agent": "kumo-qc/1.0 research-bot"})
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except (URLError, HTTPError) as e:
        print(f"  ERROR fetching page start={start}: {e}")
        return {}


def extract_strategy_summary(s: dict, rank: int) -> dict:
    """Extract clean summary fields from raw strategy object."""
    stats = s.get("statistics", {})
    author = s.get("author", {})
    return {
        "rank": rank,
        "leaderboard_position": s.get("leaderboard"),
        "id": s.get("id"),
        "name": s.get("name"),
        "author": author.get("name"),
        "author_public_id": author.get("publicId"),
        "organization": author.get("organizationName"),
        "description": s.get("description", "")[:500],  # truncate for index
        "description_full": s.get("description", ""),
        "tags": s.get("tags", []),
        "asset_classes": s.get("assetClasses", []),
        "language": "Python",  # QC community default
        "version": s.get("version"),
        "score": s.get("score"),
        "sharpe_1y": stats.get("1y sharpe"),
        "return_3m": stats.get("3m return"),
        "return_oos_1y": stats.get("oos 1y return"),
        "sharpe_oos_1y": stats.get("oos 1y sharpe"),
        "cagr_5y": stats.get("5y cagr"),
        "drawdown_5y": stats.get("5y drawdown"),
        "psr_5y": stats.get("5y psr"),
        "watchers": s.get("followersCount", 0),
        "clones": s.get("clones", 0),
        "clone_project_id": s.get("cloneProjectId"),
        "backtest_id": s.get("backtestId"),
        "discussion_id": s.get("discussionId"),
        "published_ts": s.get("published"),
        "hot": s.get("hot", False),
        "top_author": author.get("topAuthor", False),
    }


def write_strategy_file(summary: dict, raw: dict, out_dir: Path) -> Path:
    """Write per-strategy JSON file."""
    rank = summary["rank"]
    slug = slugify(summary["name"] or f"strategy-{summary['id']}")
    filename = f"{rank:03d}-{slug}.json"
    filepath = out_dir / filename
    payload = {"summary": summary, "raw": raw}
    filepath.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return filepath


def write_index(strategies: list[dict], out_dir: Path) -> Path:
    """Write INDEX.md summary table."""
    index_path = out_dir / "INDEX.md"
    lines = [
        "# QC Community Strategy Leaderboard",
        "",
        f"Fetched: {time.strftime('%Y-%m-%d')}  |  Count: {len(strategies)}",
        "",
        "Source: `https://www.quantconnect.com/api/v2/strategies/list` (public, no auth)",
        "",
        "| # | Name | Author | Score | 1Y Sharpe | 3M Return | CAGR 5Y | DD 5Y | Watchers | Clones | Tags |",
        "|---|------|--------|-------|-----------|-----------|---------|-------|----------|--------|------|",
    ]
    for s in strategies:
        name = (s["name"] or "")[:40]
        author = (s["author"] or "")[:20]
        score = f"{s['score']:.2f}" if s["score"] is not None else "—"
        sharpe = f"{s['sharpe_1y']:.2f}" if s["sharpe_1y"] is not None else "—"
        ret3m = f"{s['return_3m']:.1f}%" if s["return_3m"] is not None else "—"
        cagr = f"{s['cagr_5y']:.1f}%" if s["cagr_5y"] is not None else "—"
        dd = f"{s['drawdown_5y']:.0f}%" if s["drawdown_5y"] is not None else "—"
        tags = ", ".join(s["tags"][:3]) if s["tags"] else "—"
        rank = s["rank"]
        lines.append(
            f"| {rank} | {name} | {author} | {score} | {sharpe} | {ret3m} | {cagr} | {dd} | {s['watchers']} | {s['clones']} | {tags} |"
        )
    lines += [
        "",
        "## Notes",
        "- **Score** = 1Y Sharpe with penalty for < 1Y out-of-sample history",
        "- **3M Return** = out-of-sample 3-month return (daily live backtesting)",
        "- **CAGR 5Y** = 5-year compound annual growth rate (in-sample)",
        "- Per-strategy JSON files: `<rank>-<slug>.json`",
        "- Clone URL: `https://www.quantconnect.com/terminal/#open/<cloneProjectId>`",
    ]
    index_path.write_text("\n".join(lines))
    return index_path


def main():
    parser = argparse.ArgumentParser(description="Fetch QC community strategies leaderboard")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX, help="Max strategies to fetch")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching up to {args.max} strategies → {out_dir}")

    all_summaries = []
    start = 0
    rank = 1

    while rank <= args.max:
        count = min(PAGE_SIZE, args.max - (rank - 1))
        print(f"  Page start={start} count={count} ...", end=" ", flush=True)
        data = fetch_page(start, count)

        # The endpoint returns {"strategies": [...]} without a "success" key
        if not data or "strategies" not in data:
            print(f"STOP (no success or empty response)")
            break

        strategies = data.get("strategies", [])
        if not strategies:
            print("STOP (no more strategies)")
            break

        print(f"got {len(strategies)}")

        for raw in strategies:
            if rank > args.max:
                break
            summary = extract_strategy_summary(raw, rank)
            write_strategy_file(summary, raw, out_dir)
            all_summaries.append(summary)
            rank += 1

        start += len(strategies)
        if len(strategies) < count:
            # Fewer results than requested — end of list
            break

        time.sleep(SLEEP_BETWEEN_PAGES)

    # Sort by leaderboard position for index
    all_summaries.sort(key=lambda s: (s["leaderboard_position"] or 9999, s["rank"]))
    for i, s in enumerate(all_summaries, 1):
        s["rank"] = i

    index_path = write_index(all_summaries, out_dir)
    print(f"\nDone. {len(all_summaries)} strategies saved.")
    print(f"  Index: {index_path}")
    print(f"  Files: {out_dir}/<rank>-<slug>.json")


if __name__ == "__main__":
    main()
