export const meta = {
  name: 'sector-regime-batch',
  description: 'Implement + FY-BT #155 per-stock sector regime and #156 sector RS gate on champion 3b1c244',
  phases: [
    { title: 'Implement+FY-BT', detail: 'one agent per experiment: subscribe 11 SPDR ETFs, gate per-stock by sector, run FY2025 BT' },
    { title: 'Window-validate', detail: 'W1-W6 for FY > 0.778 survivors' },
  ],
}

const CHAMP = 0.778
const ROOT = '/Users/falk/projects'
const SPDRS = 'XLB,XLC,XLY,XLP,XLV,XLI,XLRE,XLF,XLE,XLK,XLU'

const HOWTO = (id, marker, gateLog) => `
WORKTREE: ${ROOT}/kumo-qc-${id} (created from champion 3b1c244, flat-10% e40c base).
Has: data/ symlink, scripts/lean-bt.sh, algorithm/performance_bct/ticker_sector_map.json (ticker -> {sector, etf}, 246/326 mapped; tickers ABSENT from the map must SKIP the sector filter, never reject).
Do ALL work in that worktree; edit algorithm/performance_bct/main.py there.

LOAD THE SECTOR MAP: reuse the exact file-resolution pattern of _load_polygon_universe() already in main.py (it tries candidate paths next to the project). Load ticker_sector_map.json the same way into a dict at initialize(). Look up sector ETF by symbol.value.upper(); missing key => skip filter for that symbol.

SUBSCRIBE the 11 SPDR sector ETFs + a 50-day SMA each, in initialize() (near the QQQ sub ~line 265):
  self._sector_sma50 = {}
  for etf in "${SPDRS}".split(","):
      self.add_equity(etf, Resolution.DAILY)
      self._sector_sma50[etf] = self.sma(etf, 50)

MANDATORY MARKERS (data-integrity — no fabrication):
1. initialize():  self.log("VERSION_MARKER|${marker}")
2. emit a runtime log line containing ${gateLog} wherever your gate decision fires.

RUN FY2025 (champion defaults, flat-10%):
  cd ${ROOT}/kumo-qc-${id}
  LEAN_LOCK=1 MARKER=${marker} bash scripts/lean-bt.sh algorithm/performance_bct 2>&1 | tail -30

VERIFY (all must hold or report implemented=false):
- wrapper prints VERSION_MARKER OK ('${marker}')
- latest backtest runtime log contains ${gateLog} >=1×:  d=$(ls -td algorithm/performance_bct/backtests/*/ | head -1); grep -c "${gateLog}" "$d"*log* 2>/dev/null
- Sharpe/Ret/DD/orders from summary json:
    sj=$(ls "$d"*-summary.json|head -1); python3 -c "import json;s=json.load(open('$sj'))['statistics'];print(s['Sharpe Ratio'],s['Net Profit'],s['Drawdown'],s['Total Orders'])"

COMMIT: git add -A && git commit -q -m "feat(${id}): <one-line> (#<ticket>)"
RETURN structured result with fy_sharpe/fy_return_pct/fy_dd_pct/fy_orders from the ARTIFACT only.`

const SPECS = [
  {
    id: 'me155', ticket: 155, marker: 'me155_sector_regime_v1', gateLog: 'SECTOR_REGIME',
    title: 'V16 per-stock sector regime — enter only if the stock\'s sector ETF > 50MA',
    body: `EXPERIMENT #155 (V16): gate each candidate by ITS OWN sector ETF's 50MA. Enter a stock only when its mapped SPDR sector ETF trades above its 50-day MA (strong sector).
INSERTION: candidate qualification loop in _rebalance(), after the score passes (~line 528).
  etf = sector_map.get(symbol.value.upper(), {}).get("etf")
  if etf is None: pass  # not in map → skip filter (allow)
  else:
      ind = self._sector_sma50.get(etf)
      if ind is not None and ind.is_ready:
          etf_price = float(self.securities[etf].price)
          etf_ma = float(ind.current.value)
          if etf_price < etf_ma:
              self.log(f"SECTOR_REGIME|{date_str}|{symbol.value}|{etf}|price={etf_price:.2f}<ma50={etf_ma:.2f}|SKIP")
              continue   # weak sector → reject
          else:
              self.log(f"SECTOR_REGIME|{date_str}|{symbol.value}|{etf}|OK")
Champion=${CHAMP}.`,
  },
  {
    id: 'me156', ticket: 156, marker: 'me156_sector_rs_v1', gateLog: 'SECTOR_RS',
    title: 'V17 sector RS gate — sector ETF > 50MA AND sector 20d-return > SPY 20d-return',
    body: `EXPERIMENT #156 (V17): enter a stock only if its sector ETF is BOTH above its 50MA AND outperforming SPY over the trailing 20 days.
SETUP: also ensure SPY is subscribed (add_equity("SPY") — idempotent; it may be the benchmark).
20d return helper: ret20(sym) = from self.history(sym, 21, Resolution.DAILY): close.iloc[-1]/close.iloc[0]-1 (handle MultiIndex; return None if <21 bars). Cache SPY's ret20 once per rebalance.
INSERTION: candidate loop after score pass (~line 528).
  etf = sector_map.get(symbol.value.upper(), {}).get("etf")
  if etf is None: pass  # skip filter
  else:
      ind = self._sector_sma50.get(etf)
      above_ma = ind is not None and ind.is_ready and float(self.securities[etf].price) >= float(ind.current.value)
      etf_r = ret20(etf); spy_r = spy_ret20
      rs_ok = etf_r is not None and spy_r is not None and etf_r > spy_r
      if not (above_ma and rs_ok):
          self.log(f"SECTOR_RS|{date_str}|{symbol.value}|{etf}|above_ma={above_ma}|etf_r={etf_r}|spy_r={spy_r}|SKIP")
          continue
      self.log(f"SECTOR_RS|{date_str}|{symbol.value}|{etf}|OK|etf_r={etf_r:.3f}>spy_r={spy_r:.3f}")
Champion=${CHAMP}.`,
  },
]

const S1 = {
  type: 'object', additionalProperties: false,
  required: ['id', 'ticket', 'implemented', 'marker_ok', 'gate_fired', 'fy_sharpe', 'fy_return_pct', 'fy_dd_pct', 'fy_orders', 'bt_dir', 'commit', 'notes'],
  properties: {
    id: { type: 'string' }, ticket: { type: 'number' },
    implemented: { type: 'boolean' }, marker_ok: { type: 'boolean' }, gate_fired: { type: 'boolean' },
    fy_sharpe: { type: ['number', 'null'] }, fy_return_pct: { type: ['number', 'null'] },
    fy_dd_pct: { type: ['number', 'null'] }, fy_orders: { type: ['number', 'null'] },
    bt_dir: { type: ['string', 'null'] }, commit: { type: ['string', 'null'] }, notes: { type: 'string' },
  },
}
const S2 = {
  type: 'object', additionalProperties: false,
  required: ['id', 'windows', 'windows_passed', 'notes'],
  properties: {
    id: { type: 'string' },
    windows: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['window', 'sharpe', 'return_pct', 'dd_pct', 'orders'], properties: { window: { type: 'string' }, sharpe: { type: ['number', 'null'] }, return_pct: { type: ['number', 'null'] }, dd_pct: { type: ['number', 'null'] }, orders: { type: ['number', 'null'] } } } },
    windows_passed: { type: 'number' }, notes: { type: 'string' },
  },
}

phase('Implement+FY-BT')
log(`Sector batch: ${SPECS.length} experiments on champion ${CHAMP}, BT-serialized.`)

const results = await pipeline(
  SPECS,
  (spec) => agent(
    `Implement ONE QuantConnect LEAN sector-regime experiment and backtest it. Be precise; never fabricate numbers.\n\n=== ${spec.title} ===\n${spec.body}\n\n${HOWTO(spec.id, spec.marker, spec.gateLog)}\n\nReturn id=${spec.id}, ticket=${spec.ticket}, verified artifact-backed result (include fy_return_pct and fy_dd_pct).`,
    { label: `impl:${spec.id}`, phase: 'Implement+FY-BT', schema: S1 }
  ),
  (r, spec) => {
    if (!r || !r.implemented || !r.marker_ok || !r.gate_fired || r.fy_sharpe == null || r.fy_sharpe <= CHAMP) {
      return { id: spec.id, windows: [], windows_passed: 0, notes: 'skipped windows — did not beat champion or unverified' }
    }
    return agent(
      `Experiment ${spec.id} (#${spec.ticket}) beat champion on FY2025 (${r.fy_sharpe} > ${CHAMP}). Validate 6 windows in ${ROOT}/kumo-qc-${spec.id}. For each: LEAN_LOCK=1 MARKER=${spec.marker} bash scripts/lean-bt.sh algorithm/performance_bct --parameter start_year 2025 --parameter start_month M1 --parameter start_day D1 --parameter end_year 2025 --parameter end_month M2 --parameter end_day D2. Windows: W1 1/1-3/31, W2 3/1-5/31, W3 5/1-7/31, W4 7/1-9/30, W5 9/1-11/30, W6 10/1-12/31. Extract Sharpe/Net Profit/Drawdown/orders per window from summary json. windows_passed=count Sharpe>0.`,
      { label: `win:${spec.id}`, phase: 'Window-validate', schema: S2 }
    )
  }
)

return { champion: CHAMP, count: results.length, results }
