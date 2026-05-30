export const meta = {
  name: 'rs-multietf-batch',
  description: 'Implement + FY-BT 8 R/S and multi-ETF experiments on champion 3b1c244, window-validate survivors',
  phases: [
    { title: 'Implement+FY-BT', detail: 'one agent per experiment: edit main.py, run FY2025 BT, verify gate fired' },
    { title: 'Window-validate', detail: 'W1-W6 for FY > 0.778 survivors' },
  ],
}

const CHAMP = 0.778
const ROOT = '/Users/falk/projects'

// Shared boilerplate: how every agent must run + verify + report.
const HOWTO = (id, marker, gateLog) => `
WORKTREE: ${ROOT}/kumo-qc-${id}  (already created from champion commit 3b1c244, flat-10% e40c base).
It has: data/ symlink, scripts/lean-bt.sh, algorithm/resistance_support.py (the #146 R/S module).
Do ALL work inside that worktree. Edit algorithm/performance_bct/main.py there.

MANDATORY MARKERS (data-integrity — no fabrication allowed):
1. In initialize(), add exactly:  self.log("VERSION_MARKER|${marker}")
2. Where your gate/logic actually fires at runtime, emit a log line containing the token ${gateLog}
   (e.g. self.log(f"${gateLog}|{date_str}|...")). This proves your code executed.

RUN the FY2025 backtest (champion defaults = flat-10%, FY2025, no extra params):
  cd ${ROOT}/kumo-qc-${id}
  LEAN_LOCK=1 MARKER=${marker} bash scripts/lean-bt.sh algorithm/performance_bct 2>&1 | tail -30
(LEAN_LOCK=1 is REQUIRED — serializes the docker lean step machine-wide to avoid OOM. Other agents share the lock; your run may wait for the lock, that is expected.)

VERIFY (all three must hold or report implemented=false):
- wrapper prints "VERSION_MARKER OK ('${marker}')" → marker_ok=true
- the latest backtest log contains your ${gateLog} token at least once → gate_fired=true. Check:
    d=$(ls -td algorithm/performance_bct/backtests/*/ | head -1)
    grep -c "${gateLog}" "$d"*log* 2>/dev/null ; grep -c "${gateLog}" "$d"*/main.py 2>/dev/null
  (the runtime log file, not the code, is the proof it FIRED — search the *.txt/log in the backtest dir)
- extract Sharpe + orders from the summary json:
    sj=$(ls "$d"*-summary.json | head -1)
    python3 -c "import json;s=json.load(open('$sj'))['statistics'];print(s['Sharpe Ratio'],s['Total Orders'])"

COMPARE vs champion ${CHAMP}. If your BT errors or produces 0 orders / 0.67s runtime → data/build problem, report implemented=false with the error.

COMMIT your change in the worktree:
  git add -A && git commit -q -m "feat(${id}): <one-line> (#<ticket>)"

RETURN the structured result. fy_sharpe/fy_orders from the ARTIFACT only — never invent. If gate never fired, say so honestly (gate_fired=false) even if a number printed.
`

const SPECS = [
  {
    id: 'rs147', ticket: 147, marker: 'rs147_struct_stop_v1', gateLog: 'STRUCT_STOP',
    title: 'Structural stop = max(Kijun, support + ATR×0.5)',
    body: `EXPERIMENT #147: replace the daily Kijun stop with a structural stop = max(kijun, nearest_support + 0.5*ATR14).
INSERTION: the exit/stop logic in _rebalance(), the held-position loop. In champion 3b1c244 main.py the Kijun stop is:
    if close < kijun:
        self.market_on_open_order(symbol, -holding.quantity) ...  (around line 450)
Change the stop THRESHOLD from \`kijun\` to \`structural_stop\` where:
    daily df = self.history(symbol, 252, Resolution.DAILY) → build OHLCV DataFrame (droplevel if MultiIndex; columns open/high/low/close/volume).
    from resistance_support import compute_levels
    lv = compute_levels(df, ref_price=close, senkou_a=cloud_top, senkou_b=cloud_bottom)
    support = lv.nearest_support if lv.nearest_support is not None else kijun
    atr = average true range over 14 daily bars from df (TR = max(h-l, abs(h-prevclose), abs(l-prevclose)); ATR=TR.rolling(14).mean().iloc[-1])
    structural_stop = max(kijun, support + 0.5*atr)
Exit when close < structural_stop. Emit STRUCT_STOP log on exit with close, kijun, support, atr, structural_stop.
Hypothesis: support-anchored stop cuts whipsaw losers. Caveat from V7/V12: loosening exits collapsed the year — this is a DIFFERENT (tighter, structural) stop, distinct test. Keep phase3/cloud/weekly-kijun exits intact; only change the base Kijun stop threshold.`,
  },
  {
    id: 'rs148', ticket: 148, marker: 'rs148_prebreakout_v1', gateLog: 'PREBREAKOUT',
    title: 'Pre-breakout zone filter — enter only 2-10% below resistance',
    body: `EXPERIMENT #148: filter entries — only enter a candidate when price is 2% to 10% below its nearest resistance (defined upside, not at the ceiling).
INSERTION: the candidate qualification loop in _rebalance(), right AFTER the score passes (after \`if result is None or result["score"] < self.MIN_SCORE: continue\`, ~line 528).
    price = float(self.securities[symbol].price)
    df = self.history(symbol, 252, Resolution.DAILY) → OHLCV DataFrame
    lv = compute_levels(df, ref_price=price)
    r = lv.nearest_resistance
    if r is None: skip (continue) — no clean resistance.
    gap = r/price - 1
    keep ONLY if 0.02 <= gap <= 0.10, else continue (skip).
Emit PREBREAKOUT log: PREBREAKOUT_OK on keep (with gap) and/or PREBREAKOUT_SKIP on reject. Champion=${CHAMP}.`,
  },
  {
    id: 'rs149', ticket: 149, marker: 'rs149_buystop_v1', gateLog: 'BUYSTOP',
    title: 'Post-breakout buy-stop entry above resistance',
    body: `EXPERIMENT #149: replace market-on-open entry with a BUY-STOP above nearest resistance (confirmed-strength entry — only fills if price breaks out).
INSERTION: the order-placement loop (~line 567-580, where market_on_open_order(symbol, quantity) places the entry).
    Compute nearest_resistance via compute_levels on 252d daily history. If None, skip candidate.
    Place a stop-market BUY at trigger = nearest_resistance * 1.001 instead of market_on_open_order:
        self.stop_market_order(symbol, quantity, trigger_price)
    "confirmation" = only arm the buy-stop when price is within 5% below resistance (0 <= r/price-1 <= 0.05); else skip.
    Keep position_meta bookkeeping on fill (use on_order_event or set meta at placement; simplest: set meta at placement).
Emit BUYSTOP log with symbol, trigger, price. NOTE: expect FEWER orders than champion (many stops never trigger). That is the point — report honestly.`,
  },
  {
    id: 'rs150', ticket: 150, marker: 'rs150_rr2_v1', gateLog: 'RR',
    title: 'R/R 2:1 entry filter',
    body: `EXPERIMENT #150: skip entries whose reward:risk < 2:1, measured structurally.
INSERTION: candidate qualification loop, after score pass (~line 528).
    price = security price; df=252d history; lv=compute_levels(df, ref_price=price)
    r = lv.nearest_resistance; s = lv.nearest_support
    if r is None or s is None: skip (continue) — no clean R/S.
    reward = r - price ; risk = price - s
    keep ONLY if risk > 0 and reward >= 2.0 * risk ; else continue (skip).
Emit RR log: RR_OK (with reward,risk,ratio) on keep, RR_SKIP on reject. Champion=${CHAMP}.`,
  },
  {
    id: 'rs151', ticket: 151, marker: 'rs151_polarity_v1', gateLog: 'POLARITY_TRAIL',
    title: 'Structural trailing — polarity-flip (broken resistance → support)',
    body: `EXPERIMENT #151: replace the Kijun stop with a polarity-flip structural trail. When price breaks ABOVE a prior resistance, that level flips to support and becomes the trailing stop; exit when close falls below the highest such flipped level.
INSERTION: exit/stop logic in _rebalance() held-position loop (~line 450), AND track flipped levels in self._position_meta per symbol.
    On each rebalance for a held symbol: df=252d history; lv=compute_levels(df, ref_price=close).
    flipped = max( [lvl for lvl in lv.support if lvl < close] , default=None )  # resistance now below price = flipped support
    Maintain meta[symbol]['trail'] = max(existing trail, flipped) (ratchet up only, never down).
    Exit (market_on_open_order -qty) when close < meta['trail'] (if trail set), ELSE fall back to kijun stop.
NOTE from V7/V12: the Kijun trail is PROTECTIVE — a structural trail must BEAT it, not just differ. Keep phase3 cloud-bottom exit intact.
Emit POLARITY_TRAIL log on exit with close, trail. Champion=${CHAMP}.`,
  },
  {
    id: 'me153', ticket: 153, marker: 'me153_qqq_and_spy_v1', gateLog: 'REGIME_AND',
    title: 'V14 Multi-ETF AND — QQQ>50MA AND SPY>50MA',
    body: `EXPERIMENT #153 (V14): tighten the regime gate to require BOTH QQQ>50MA AND SPY>50MA to allow entries.
SETUP (initialize, near the QQQ sub ~line 265): add SPY 50MA:
    self.spy_sym = self.add_equity("SPY", Resolution.DAILY).symbol   # SPY may already be benchmark; add_equity is idempotent
    self.spy_sma50 = self.sma("SPY", 50)
GATE (the QQQ regime-block in _rebalance, ~lines 475-481): currently blocks when QQQ<50MA. Change to block UNLESS (qqq>qqq_ma50 AND spy>spy_ma50):
    if qqq_sma50.is_ready and spy_sma50.is_ready:
        block = (qqq_price < qqq_ma50) or (spy_price < spy_ma50)
        if block: log REGIME_AND with both prices/MAs and return
Emit REGIME_AND log when blocking. Champion=${CHAMP} (single QQQ gate). Expect FEWER entries.`,
  },
  {
    id: 'me154', ticket: 154, marker: 'me154_qqq_or_iwm_v1', gateLog: 'REGIME_OR',
    title: 'V15 Multi-ETF OR — QQQ>50MA OR IWM>50MA',
    body: `EXPERIMENT #154 (V15): loosen the regime gate — allow entries if QQQ>50MA OR IWM>50MA.
SETUP (initialize, near QQQ sub): add IWM 50MA:
    self.iwm_sym = self.add_equity("IWM", Resolution.DAILY).symbol
    self.iwm_sma50 = self.sma("IWM", 50)
GATE (QQQ regime-block ~475-481): block ONLY when BOTH below their 50MA:
    if qqq_sma50.is_ready and iwm_sma50.is_ready:
        block = (qqq_price < qqq_ma50) and (iwm_price < iwm_ma50)
        if block: log REGIME_OR and return
Emit REGIME_OR log when blocking. Champion=${CHAMP}. Expect MORE entries (looser gate).`,
  },
  {
    id: 'me157', ticket: 157, marker: 'me157_breadth_v1', gateLog: 'BREADTH',
    title: 'V18 Market breadth gate — % universe >200MA > 50%',
    body: `EXPERIMENT #157 (V18): block entries when fewer than 50% of the active universe trades above its own 200-day MA (weak breadth).
GATE (in _rebalance, alongside the QQQ regime-block ~475-481): each active symbol already has a per-symbol sma200 indicator in self._indicators[symbol]["sma200"] (champion builds it). Compute breadth:
    ready=0; above=0
    for sym in self._active:
        ind=self._indicators.get(sym); s200=ind and ind.get("sma200")
        if s200 and s200.is_ready:
            ready+=1
            if float(self.securities[sym].price) > float(s200.current.value): above+=1
    if ready>0:
        breadth = above/ready
        log BREADTH with breadth, above, ready
        if breadth < 0.50: return   # block entries this rebalance
Emit BREADTH log every rebalance (value) and block when <0.50. Champion=${CHAMP}.`,
  },
]

const STAGE1_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['id', 'ticket', 'implemented', 'marker_ok', 'gate_fired', 'fy_sharpe', 'fy_orders', 'bt_dir', 'commit', 'notes'],
  properties: {
    id: { type: 'string' },
    ticket: { type: 'number' },
    implemented: { type: 'boolean' },
    marker_ok: { type: 'boolean' },
    gate_fired: { type: 'boolean' },
    fy_sharpe: { type: ['number', 'null'] },
    fy_orders: { type: ['number', 'null'] },
    bt_dir: { type: ['string', 'null'] },
    commit: { type: ['string', 'null'] },
    notes: { type: 'string' },
  },
}

const WINDOW_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['id', 'windows', 'windows_passed', 'notes'],
  properties: {
    id: { type: 'string' },
    windows: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['window', 'sharpe', 'orders'],
        properties: { window: { type: 'string' }, sharpe: { type: ['number', 'null'] }, orders: { type: ['number', 'null'] } },
      },
    },
    windows_passed: { type: 'number' },
    notes: { type: 'string' },
  },
}

phase('Implement+FY-BT')
log(`Spawning ${SPECS.length} experiment agents (BT-serialized via LEAN_LOCK). Champion=${CHAMP}.`)

const results = await pipeline(
  SPECS,
  (spec) => agent(
    `You are implementing ONE QuantConnect LEAN strategy experiment and backtesting it. Be precise; do not fabricate numbers.\n\n` +
    `=== ${spec.title} ===\n${spec.body}\n\n${HOWTO(spec.id, spec.marker, spec.gateLog)}\n\n` +
    `Return: id=${spec.id}, ticket=${spec.ticket}, and the verified artifact-backed result.`,
    { label: `impl:${spec.id}`, phase: 'Implement+FY-BT', schema: STAGE1_SCHEMA }
  ),
  // stage 2: window-validate only true survivors (gate fired, marker ok, FY beats champion)
  (r, spec) => {
    if (!r || !r.implemented || !r.marker_ok || !r.gate_fired || r.fy_sharpe == null || r.fy_sharpe <= CHAMP) {
      return { id: spec.id, windows: [], windows_passed: 0, notes: 'skipped windows — did not beat champion or unverified' }
    }
    return agent(
      `Experiment ${spec.id} (#${spec.ticket}) BEAT the champion on FY2025 (Sharpe ${r.fy_sharpe} > ${CHAMP}). Now validate across 6 windows in worktree ${ROOT}/kumo-qc-${spec.id}.\n` +
      `For each window run the BT with start/end params, LEAN_LOCK=1 MARKER=${spec.marker}, and extract Sharpe+orders from the summary json. Windows (YYYY-MM-DD):\n` +
      `  W1 2025-01-01..2025-03-31, W2 2025-03-01..2025-05-31, W3 2025-05-01..2025-07-31, W4 2025-07-01..2025-09-30, W5 2025-09-01..2025-11-30, W6 2025-10-01..2025-12-31.\n` +
      `Run e.g.: LEAN_LOCK=1 MARKER=${spec.marker} bash scripts/lean-bt.sh algorithm/performance_bct --parameter start_year 2025 --parameter start_month 1 --parameter start_day 1 --parameter end_year 2025 --parameter end_month 3 --parameter end_day 31\n` +
      `windows_passed = count of windows with Sharpe > 0. Report each window's sharpe/orders from artifacts only.`,
      { label: `win:${spec.id}`, phase: 'Window-validate', schema: WINDOW_SCHEMA }
    )
  }
)

return { champion: CHAMP, count: results.length, results }
