# Exit Logic Evolution — Reference vs Current
*2026‑05‑24*

## Comparison Table

| Aspect | Reference (`bct‑perf‑2020‑2026`) | Current (`performance_bct/main.py`) |
|---|---|---|
| **Entry conditions** | ≥7/8 BCT checklist, 10% position, max 10 positions | Same |
| **Universe filter** | ETF addition duplicated (lines 44‑48 + 51‑55), candidate sorting unsorted | ETF list once, sorted iteration |
| **Exit conditions** | **Daily Kijun only** (`close < kijun`) | **Daily Kijun** + **Daily cloud breach** + **Weekly Kijun trail** |
| **Cloud breach exit** | No | `close < max(senkou_a, senkou_b)` |
| **Weekly Kijun trail exit** | No | `close < weekly_kijun` if weekly indicator ready |
| **Sharpe (2020‑2026)** | **0.393** | Unknown (3‑exit stricter) |
| **Trades** | 1807 | Likely fewer (more exits) |
| **Win rate** | 42% | Likely lower (more early exits) |

## Expected Impact of Each Added Exit

| Exit | Effect | Expected Metric Change |
|---|---|---|
| **Daily cloud breach** (`close < cloud_top`) | Additional exit trigger; many Kijun‑above‑cloud entries would exit earlier at cloud breach | → Lower Sharpe (more exits), fewer trades, lower win rate |
| **Weekly Kijun trail** (`close < weekly_kijun`) | Weekly Kijun rises slower than daily → additional trailing exit | → Lower Sharpe, fewer trades, lower win rate |
| **Combined (3 exits)** | Up to 3 exit triggers per position → positions exit earlier, sooner | → Significant deviation from reference Sharpe 0.393 |

## Recommendation

**Option A:** Run reproduction with current 3‑exit code, accept different metrics.
- ✅ Quick path
- ✅ Reflects latest BCT logic
- ❌ Cannot validate parity with reference Sharpe 0.393

**Option B:** Create a "reference‑compatible" mode with only Kijun stop.
- ✅ Exact reproduction of reference Sharpe 0.393
- ✅ Validation of universe/entry logic parity
- ✅ Parameter study of exit impact
- ⏳ Extra implementation

**Decision:** Use reference‑compatible mode first (Option B). Validate that the core universe filter and entry logic produce the same 1807 trades, 42% win rate with Kijun‑only exit. Then add cloud breach and weekly Kijun one‑by‑one to quantify their impact on Sharpe.

## Implementation Steps

1. Add parameter `EXIT_MODE` (options: `KIJUN_ONLY`, `KIJUN_CLOUD`, `KIJUN_CLOUD_WEEKLY`)
2. In `_rebalance`, switch exit logic based on `EXIT_MODE`
3. Run reproduction backtests for each mode
4. Compare metrics to reference 0.393

## Key Files
- `qc/01_bct‑perf‑2020‑2026/algorithm.py` (reference)
- `algorithm/performance_bct/main.py` (current)
- `algorithm/live_bct.py` (live)
- `algorithm/live_bct/main.py` (live)

**Commit:** 262d2f4, 4a8aeaa, 3be20d6, 1110b41, a91bb36