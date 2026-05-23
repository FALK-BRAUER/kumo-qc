# CLAUDE.md — kumo-qc

## What This Is
QuantConnect-based trading engine implementing George's Blue Cloud Trading (BCT) Ichimoku methodology at scale.
Replaces the brittle kumo-trader agent/ monolith with QC's managed infrastructure.

QC handles: engine, universe (6,000 names), IBKR connection, data, scheduling, VPS.
We own: BCT signal logic (~400 lines Python), cockpit adapter (Next.js reading QC REST API).

## Architecture
- **Strategy code:** Python, QuantConnect LEAN algorithm framework
- **Universe:** Coarse filter (6k → ~200 by liquidity/price) → BCT fine scoring (→ 5-10 signals)
- **Execution:** QC live trading node → IBKR paper (DUK434934) or live (U18777181 — manual approval gate)
- **Cockpit:** Next.js UI reads QC REST API (positions, orders, P&L) — adapts kumo-trader UI patterns
- **Credentials:** QC User ID + API Token via macOS keychain (never hardcoded)

## IBKR Accounts
| Account | ID | Purpose | Who touches it |
|---|---|---|---|
| **Live** | U18777181 | Falk's manual trades only | Falk via TWS/app |
| **Paper** | DUK434934 | Automated QC paper loop only | QC live node (port 4002) |

Rules:
- Automated QC algorithms → NEVER target U18777181. Paper loop = DUK434934.
- Falk placing manual orders → U18777181 is correct and expected.

## BCT Signal Stack
8-condition Blue Flag checklist:
1. Weekly price above cloud (Span A)
2. Weekly Tenkan > Kijun
3. Weekly Chikou > price 26 bars ago
4. Weekly cloud GREEN (Span A > Span B)
5. Daily price above cloud
6. Daily price above Tenkan
7. ADX rising + +DI > -DI + ADX ≥ 20 (period 9, Wilder's EWM)
8. Price above 200-day MA

Rating: +++ = 8/8, ++ = 6-7/8, + = 4-5/8

## QC Tier
Researcher ($84/month) — sufficient for solo live trading with up to 2 live nodes.
API credentials: User ID + API Token from QC account settings → macOS keychain.

## Key Rules
- Never commit API keys, account numbers, or passwords
- QC API token → keychain only, never in code or config files
- Conventional Commits format
- Strategy logic in algorithm/ directory
- Cockpit adapter in ui/ directory (Next.js, same stack as kumo-trader)

## Project Phases
| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ | QC account setup + API credentials + local LEAN CLI |
| 2 | ✅ | BCT signal port — 8-condition checklist in QC Python (bct_signal.py) |
| 3 | ✅ | Universe filter — coarse (6k→200) + fine (BCT score ≥7 → 5-10) |
| 4 | ✅ | Backtest validation — 74.2% recall / 100% precision vs scanner; ADX 71% match (data feed delta, not bug) |
| 5 | 🔲 | Paper live trading — gate.py unlock → deploy.py → DUK434934 (Falk decision) |
| 6 | ✅ | Cockpit adapter — Next.js reads QC REST API (server-only auth, 4 route handlers) |
| 7 | ✅ | Live trading gate — gate.py + live-gate QC parameter + DU account prefix check |

## QC Project IDs
| Project | ID | Purpose |
|---------|----|---------|
| backtest_bct | 32033824 | Signal audit only (no orders) |
| performance_bct | 32034565 | Full return simulation |
| live_bct | not deployed | Awaiting Falk gate.py unlock |

## Credentials (keychain only)
```
security find-generic-password -s "qc-user-id" -a "kumo-qc" -w     → QC user ID
security find-generic-password -s "qc-api-token" -a "kumo-qc" -w   → QC API token
security find-generic-password -s "kumo-qc" -a "qc-live-gate" -w   → UNLOCKED or absent
```

UI credentials: set in `ui/.env.local` (gitignored):
```
QC_USER_ID=...
QC_API_TOKEN=...
QC_PROJECT_ID=32033824
```

## Commit Policy
- Conventional Commits: feat|fix|chore|refactor(scope): description
- Never commit: .env*, secrets, API tokens, account numbers
- Always commit: algorithm/, ui/, scripts/, CLAUDE.md
