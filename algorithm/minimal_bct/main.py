from __future__ import annotations
"""
Minimal BCT backtest — hardcoded universe, no Morningstar/fundamental data.

Purpose: local + QC cloud parity baseline that bypasses has_fundamental_data=True
blocker (GH #14/#16). Proves the BCT scoring and execution logic works end-to-end
without the coarse/fine universe filter.

Universe: 545 tickers (S&P 500 + BCT DEFAULT_TICKERS, merged + deduped).
Signal: same 8-condition BCT Blue Flag checklist as performance_bct.
Entry Gates: SPY 4-day confirm, 3% from 52w high, Kijun extension check,
      chikou confirm, min $3 price, $500K volume, VIX tier (50% if >90th pct 2yr).
Exits: ATR trailing stop (22-period, 2.5x initial, 3.0x floor) + Kijun trail +
      ladder trim [20%,40%] + reversal_profit_exit (6% gain, 10% Tenkan ext) +
      earnings exits (adaptive 9d / hard 3d) + optional cloud breach + weekly Kijun.
Sizing: Fixed-risk $200 per position with ATR-based position sizing.
Adds: Cloud top break triggers (50% of original, max 1 add).
Rotation: score_ratio ≥ 2.0, profit veto at +5%.
Parameters: warmup_days (default 750), cloud_exit (default false),
      weekly_kijun_exit (default false), atr_period (default 22).
"""

import csv
import io
from datetime import timedelta, datetime
from pathlib import Path

from AlgorithmImports import *  # noqa: F401,F403
from QuantConnect.Indicators import AverageTrueRange, MovingAverageType

from bct_signal import score_symbol


class BCTMinimalAlgorithm(QCAlgorithm):

    MAX_POSITIONS: int = 10
    POSITION_PCT: float = 0.10
    MIN_SCORE: int = 6

    # Rotation engine parameters (Item 2: sT10e+R-B-v3)
    SCORE_RATIO_THRESHOLD: float = 2.0
    MIN_HOLD_DAYS: int = 1
    MIN_PNL_PCT: float = 0.0
    PROFIT_VETO_PCT: float = 0.05
    MAX_CORR: float = 0.75  # GH #22: skip rotation if correlation > 0.75
    PROFIT_ALPHA: float = 0.0  # GH #22: 0.0 = use binary veto, >0 = continuous multiplier

    # Buy-stop fill parameter (Item 3: sT10e+R-B-v3)
    BUY_STOP_PCT: float = 0.0075  # 0.75% above close

    # Entry gates (Item 4: sT10e champion)
    RESISTANCE_PROXIMITY_PCT: float = 0.03  # 3% from 52-week high
    KIJUN_EXTENSION_MULT: float = 1.5  # 1.5× kijun above cloud
    MIN_PRICE: float = 3.0
    SKIP_IF_EARNINGS_DAYS: int = 5
    SPY_GATE_CONFIRM_DAYS: int = 4
    VIX_PERCENTILE_THRESHOLD: float = 90.0  # GH #28: reduce size above 90th pct
    VIX_SIZE_MULTIPLIER: float = 0.50  # 50% size when VIX > 90th pct of 2yr dist

    # 607 tickers (kumo-trader curated sim list)
    UNIVERSE: list[str] = [
        "A", "AAPL", "ABBV", "ABNB", "ABT", "ACGL", "ACN", "ADBE", "ADI", "ADM",
        "ADP", "ADSK", "AEE", "AEP", "AES", "AFL", "AIG", "AIZ", "AJG", "AKAM",
        "ALB", "ALGN", "ALL", "ALLE", "ALNY", "AMAT", "AMCR", "AMD", "AME", "AMGN",
        "AMP", "AMT", "AMZN", "ANET", "AON", "AOS", "APA", "APD", "APH", "APO",
        "APP", "APTV", "ARE", "ARES", "ARM", "ASML", "ATO", "AVB", "AVGO", "AVY",
        "AWK", "AXON", "AXP", "AZO", "BA", "BAC", "BALL", "BAX", "BBY", "BDX",
        "BEN", "BF-B", "BG", "BIIB", "BK", "BKNG", "BKR", "BLDR", "BLK", "BMY",
        "BR", "BRK-B", "BRO", "BSX", "BX", "BXP", "C", "CAG", "CAH", "CARR",
        "CASY", "CAT", "CB", "CBOE", "CBRE", "CCEP", "CCI", "CCL", "CDNS", "CDW",
        "CEG", "CF", "CFG", "CHD", "CHRW", "CHTR", "CI", "CIEN", "CINF", "CL",
        "CLX", "CMCSA", "CME", "CMG", "CMI", "CMS", "CNC", "CNP", "COF", "COHR",
        "COIN", "COO", "COP", "COR", "COST", "CPAY", "CPB", "CPRT", "CPT", "CRH",
        "CRL", "CRM", "CRWD", "CSCO", "CSGP", "CSX", "CTAS", "CTSH", "CTVA", "CVNA",
        "CVS", "CVX", "D", "DAL", "DASH", "DD", "DDOG", "DE", "DECK", "DELL",
        "DG", "DGX", "DHI", "DHR", "DIS", "DLR", "DLTR", "DOC", "DOV", "DOW",
        "DPZ", "DRI", "DTE", "DUK", "DVA", "DVN", "DXCM", "EA", "EBAY", "ECL",
        "ED", "EFX", "EG", "EIX", "EL", "ELV", "EME", "EMR", "EOG", "EPAM",
        "EQIX", "EQR", "EQT", "ERIE", "ES", "ESS", "ETN", "ETR", "EVRG", "EW",
        "EXC", "EXE", "EXPD", "EXPE", "EXR", "F", "FANG", "FAST", "FCX", "FDS",
        "FDX", "FE", "FER", "FFIV", "FICO", "FIS", "FISV", "FITB", "FIX", "FOX",
        "FOXA", "FRT", "FSLR", "FTNT", "FTV", "GD", "GDDY", "GE", "GEHC", "GEN",
        "GEV", "GILD", "GIS", "GL", "GLW", "GM", "GNRC", "GOOG", "GOOGL", "GPC",
        "GPN", "GRMN", "GS", "GWW", "HAL", "HAS", "HBAN", "HCA", "HD", "HIG",
        "HII", "HLT", "HON", "HOOD", "HPE", "HPQ", "HRL", "HSIC", "HST", "HSY",
        "HUBB", "HUM", "HWM", "IBKR", "IBM", "ICE", "IDXX", "IEX", "IFF", "INCY",
        "INSM", "INTC", "INTU", "INVH", "IP", "IQV", "IR", "IRM", "ISRG", "IT",
        "ITW", "IVZ", "J", "JBHT", "JBL", "JCI", "JKHY", "JNJ", "JPM", "KDP",
        "KEY", "KEYS", "KHC", "KIM", "KKR", "KLAC", "KMB", "KMI", "KO", "KR",
        "KVUE", "L", "LDOS", "LEN", "LH", "LHX", "LII", "LIN", "LITE", "LLY",
        "LMT", "LNT", "LOW", "LRCX", "LULU", "LUV", "LVS", "LYB", "LYV", "MA",
        "MAA", "MAR", "MAS", "MCD", "MCHP", "MCK", "MCO", "MDLZ", "MDT", "MELI",
        "MET", "META", "MGM", "MKC", "MLM", "MMM", "MNST", "MO", "MOS", "MPC",
        "MPWR", "MRK", "MRNA", "MRSH", "MRVL", "MS", "MSCI", "MSFT", "MSI", "MSTR",
        "MTB", "MTD", "MU", "NCLH", "NDAQ", "NDSN", "NEE", "NEM", "NFLX", "NI",
        "NKE", "NOC", "NOW", "NRG", "NSC", "NTAP", "NTRS", "NUE", "NVDA", "NVR",
        "NWS", "NWSA", "NXPI", "O", "ODFL", "OKE", "OMC", "ON", "ORCL", "ORLY",
        "OTIS", "OXY", "PANW", "PAYX", "PCAR", "PCG", "PDD", "PEG", "PEP", "PFE",
        "PFG", "PG", "PGR", "PH", "PHM", "PKG", "PLD", "PLTR", "PM", "PNC",
        "PNR", "PNW", "PODD", "POOL", "PPG", "PPL", "PRU", "PSA", "PSKY", "PSX",
        "PTC", "PWR", "PYPL", "Q", "QCOM", "RCL", "REG", "REGN", "RF", "RJF",
        "RL", "RMD", "ROK", "ROL", "ROP", "ROST", "RSG", "RTX", "RVTY", "SATS",
        "SBAC", "SBUX", "SCHW", "SHOP", "SHW", "SJM", "SLB", "SMCI", "SNA", "SNDK",
        "SNPS", "SO", "SOLV", "SPG", "SPGI", "SRE", "STE", "STLD", "STT", "STX",
        "STZ", "SW", "SWK", "SWKS", "SYF", "SYK", "SYY", "T", "TAP", "TDG",
        "TDY", "TECH", "TEL", "TER", "TFC", "TGT", "TJX", "TKO", "TMO", "TMUS",
        "TPL", "TPR", "TRGP", "TRI", "TRMB", "TROW", "TRV", "TSCO", "TSLA", "TSN",
        "TT", "TTD", "TTWO", "TXN", "TXT", "TYL", "UAL", "UBER", "UDR", "UHS",
        "ULTA", "UNH", "UNP", "UPS", "URI", "USB", "V", "VEEV", "VICI", "VLO",
        "VLTO", "VMC", "VRSK", "VRSN", "VRT", "VRTX", "VST", "VTR", "VTRS", "VZ",
        "WAB", "WAT", "WBD", "WDAY", "WDC", "WEC", "WELL", "WFC", "WM", "WMB",
        "WMT", "WRB", "WSM", "WST", "WTW", "WY", "WYNN", "XEL", "XOM", "XYL",
        "XYZ", "YUM", "ZBH", "ZBRA", "ZS", "ZTS", "SPY", "QQQ", "DIA", "IWM",
        "VTI", "VOO", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE",
        "XLU", "XLV", "XLY", "SMH", "SOXX", "SOXL", "BOTZ", "ARKQ", "ARKK", "ARKG",
        "AIQ", "ROBO", "IRBO", "ROBT", "CIBR", "HACK", "BUG", "ITA", "XAR", "GRID",
        "ICLN", "URNM", "TAN", "OIH", "IBB", "XBI", "GDX", "GDXJ", "COPX", "XME",
        "IBIT", "GBTC", "VNQ", "IYR", "VXX", "EWJ", "EWG", "EWU", "EWZ", "EWY",
        "INDA", "EWT", "EWA", "EWC", "EWL", "FXI", "KWEB", "MCHI", "VEA", "VWO",
        "EEM", "ASML", "SAP", "NVO", "SHEL", "BP", "TTE", "AZN", "UBS", "DEO",
        "BTI", "TSM", "BABA", "JD", "BIDU", "SE", "ARM", "TM", "SONY", "HMC",
        "GRAB", "MELI", "NU", "SHOP", "TD", "RY", "PBR",
    ]

    @staticmethod
    def _find_local_data_dir() -> Path | None:
        """Return first existing local equity daily data directory, or None.

        LEAN CLI mounts the project data/ folder to /Lean/Data inside Docker.
        We check both the Docker mount and the native relative path so the
        same code works in lean backtest (Docker) and bare Python unit tests.
        """
        candidates = [
            Path("/Lean/Data/equity/usa/daily"),                     # LEAN Docker mount
            Path("/Data/equity/usa/daily"),                          # alternative mount
            Path(__file__).parent.parent.parent / "data/equity/usa/daily",  # native dev
        ]
        return next((d for d in candidates if d.exists()), None)

    def _load_universe(self) -> list[str]:
        """Scan local equity daily dir for .zip files → ticker list.
        Falls back to hardcoded 545-ticker UNIVERSE if no local dir found.
        Result cached in self._universe_cache to avoid repeated disk scans."""
        if hasattr(self, '_universe_cache'):
            return self._universe_cache
        data_dir = self._find_local_data_dir()
        if data_dir is not None:
            tickers = [p.stem.upper() for p in data_dir.glob("*.zip")]
            if tickers:
                self._universe_cache = tickers
                return tickers
        self._universe_cache = list(self.UNIVERSE)
        return self._universe_cache

    # ── Dynamic Universe (replaces 545 static add_equity() calls) ──────────────
    # B2-8 node cap = 500 assets. Static 545 add_equity() exceeded cap by 45 —
    # only 83/545 tickers received data (silent gaps). Dynamic universe covers
    # ~8,000 US equities; BCT score still narrows to ≤10 open slots.
    def _universe_filter(self, fundamental: List[Fundamental]) -> List[Symbol]:
        filtered = [
            f for f in fundamental
            if f.price >= self.min_price
            and f.dollar_volume >= 1_000_000
            and f.has_fundamental_data
        ]
        top500 = sorted(filtered, key=lambda f: f.dollar_volume, reverse=True)[:500]
        return [f.symbol for f in top500]

    def on_securities_changed(self, changes: SecurityChanges) -> None:
        for s in changes.added_securities:
            sym = s.symbol
            if sym not in self._indicators:
                self._register_indicators(sym)
        for s in changes.removed_securities:
            sym = s.symbol
            if sym in self._indicators:
                ind = self._indicators.pop(sym)
                try:
                    self.subscription_manager.remove_consolidator(sym, ind["consolidator"])
                except Exception:
                    pass
            if sym in self._position_meta:
                del self._position_meta[sym]

    def initialize(self) -> None:
        self.set_time_zone("America/New_York")
        sy = int(self.get_parameter("start_year",  "2025"))
        sm = int(self.get_parameter("start_month", "1"))
        sd = int(self.get_parameter("start_day",   "1"))
        ey = int(self.get_parameter("end_year",    "2025"))
        em = int(self.get_parameter("end_month",   "12"))
        ed = int(self.get_parameter("end_day",     "31"))
        self.set_start_date(sy, sm, sd)
        self.set_end_date(ey, em, ed)
        self.set_cash(100_000)
        self.set_benchmark("SPY")

        warmup_days = int(self.get_parameter("warmup_days", "750"))
        MIN_WARMUP_DAYS = 750  # ~107 weekly bars needed for Ichimoku readiness
        if warmup_days < MIN_WARMUP_DAYS:
            self.log(f"WARMUP_OVERRIDE|requested={warmup_days}|enforced={MIN_WARMUP_DAYS}")
            warmup_days = MIN_WARMUP_DAYS
        self.set_warmup(timedelta(days=warmup_days))
        self.warmup_days = warmup_days

        # Exit condition parameters (default: disabled for reference baseline)
        self.cloud_exit_enabled = self.get_parameter("cloud_exit", "false").lower() == "true"
        self.weekly_kijun_exit_enabled = self.get_parameter("weekly_kijun_exit", "false").lower() == "true"

        # Rotation engine parameters (Item 2: sT10e+R-B-v3)
        self.score_ratio_threshold = float(self.get_parameter("score_ratio_threshold", str(self.SCORE_RATIO_THRESHOLD)))
        self.min_hold_days = int(self.get_parameter("min_hold_days", str(self.MIN_HOLD_DAYS)))
        self.min_pnl_pct = float(self.get_parameter("min_pnl_pct", str(self.MIN_PNL_PCT)))
        self.profit_veto_pct = float(self.get_parameter("profit_veto_pct", str(self.PROFIT_VETO_PCT)))
        self.max_corr = float(self.get_parameter("max_corr", str(self.MAX_CORR)))  # GH #22
        self.profit_alpha = float(self.get_parameter("profit_alpha", str(self.PROFIT_ALPHA)))  # GH #22

        # Buy-stop fill parameter (Item 3: sT10e+R-B-v3)
        self.buy_stop_pct = float(self.get_parameter("buy_stop_pct", str(self.BUY_STOP_PCT)))

        # Entry gates parameters (Item 4: sT10e champion)
        self.resistance_proximity_pct = float(self.get_parameter("resistance_proximity_pct", str(self.RESISTANCE_PROXIMITY_PCT)))
        self.kijun_extension_mult = float(self.get_parameter("kijun_extension_mult", str(self.KIJUN_EXTENSION_MULT)))
        self.min_price = float(self.get_parameter("min_price", str(self.MIN_PRICE)))
        self.skip_if_earnings_days = int(self.get_parameter("skip_if_earnings_days", str(self.SKIP_IF_EARNINGS_DAYS)))
        self.spy_gate_confirm_days = int(self.get_parameter("spy_gate_confirm_days", str(self.SPY_GATE_CONFIRM_DAYS)))
        self.vix_percentile_threshold = float(self.get_parameter("vix_percentile_threshold", str(self.VIX_PERCENTILE_THRESHOLD)))
        self.vix_size_multiplier = float(self.get_parameter("vix_size_multiplier", str(self.VIX_SIZE_MULTIPLIER)))

        # Earnings avoidance parameters (Item 6: disabled via stub)
        self.adaptive_earnings_enabled = False
        self.adaptive_earnings_gain_threshold = 0.12
        self.adaptive_earnings_exit_days = 9
        self.earnings_exit_days_before = 3  # Hard exit 3 days before earnings

        # Ladder trim parameters (Item 5)
        self.ladder_rungs_pct = [20.0, 40.0]  # Trim at +20%, +40%
        self.ladder_trim_fraction = 0.50  # Trim 50% of position

        # Reversal profit exit parameters (Item 5)
        self.reversal_profit_enabled = True
        self.reversal_profit_min_gain_pct = 0.06  # 6% gain required
        self.reversal_profit_extension_pct = 0.10  # 10% above Tenkan

        # Track SPY gate state (4-day confirmation)
        self._spy_above_cloud_days: int = 0
        self._spy_gate_open: bool = False
        self._vix_size_mult: float = 1.0  # GH #28: cached VIX percentile multiplier
        self._vix_cache_date: object = None  # GH #42: date of last VIX history fetch
        self._vix_cached_closes: list[float] = []  # GH #42: cached VIX closes array

        self.universe_settings.resolution = Resolution.DAILY
        self._indicators: dict = {}
        self._position_meta: dict = {}  # Track entry date, avg price per position
        self.add_equity("SPY", Resolution.DAILY)  # needed for benchmark + SPY gate
        self.add_index("VIX", Resolution.DAILY)  # GH #28: VIX percentile gate
        
        # Register SPY ATR indicators for atr_adaptive_score (GH #21)
        spy_sym = self.symbol("SPY")
        self._spy_atr_14 = AverageTrueRange(14, MovingAverageType.Wilders)
        self.register_indicator(spy_sym, self._spy_atr_14, Resolution.DAILY)
        self._spy_atr_252 = AverageTrueRange(252, MovingAverageType.Wilders)
        self.register_indicator(spy_sym, self._spy_atr_252, Resolution.DAILY)
        
        # ── GH #19: Load earnings dates from Object Store ──────────────────
        try:
            obj = self.object_store.read("earnings_dates.csv")
            self._earnings_dict: dict[str, list[str]] = {}
            for row in csv.DictReader(io.StringIO(obj)):
                self._earnings_dict.setdefault(row["ticker"], []).append(row["report_date"])
        except Exception:
            self._earnings_dict = {}  # fallback: no earnings avoidance
        
        local_tickers = self._load_universe()
        if self._find_local_data_dir() is not None:
            # Local LEAN data present — static load, no asset cap
            for ticker in local_tickers:
                try:
                    sym = self.add_equity(ticker, Resolution.DAILY).symbol
                    self._register_indicators(sym)
                except Exception:
                    pass
        else:
            # Cloud — dynamic universe (cap 300, fundamental filter)
            self.universe_settings.asynchronous = True
            self.add_universe(self._universe_filter)

        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(16, 5),
            self._rebalance,
        )

    def _register_indicators(self, sym) -> None:
        d_ichi = self.ichimoku(sym, 9, 26, 26, 52, 26, 26)
        sma200 = self.sma(sym, 200)
        adx = self.adx(sym, 9)
        plus_di = adx.PositiveDirectionalIndex
        minus_di = adx.NegativeDirectionalIndex
        atr = AverageTrueRange(14, MovingAverageType.Wilders)
        self.register_indicator(sym, atr, Resolution.DAILY)

        w_ichi = IchimokuKinkoHyo(9, 26, 26, 52, 26, 26)
        w_close = RollingWindow[float](28)

        consolidator = TradeBarConsolidator(Calendar.WEEKLY)

        def _on_weekly(_, bar: TradeBar) -> None:
            w_ichi.update(bar)
            w_close.add(bar.close)

        consolidator.data_consolidated += _on_weekly
        self.subscription_manager.add_consolidator(sym, consolidator)

        if not self.is_warming_up:
            self._seed_weekly(sym, w_ichi, w_close)

        self._indicators[sym] = {
            "d_ichi": d_ichi,
            "w_ichi": w_ichi,
            "w_close": w_close,
            "sma200": sma200,
            "adx": adx,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "atr": atr,
            "consolidator": consolidator,
        }

    def _seed_weekly(self, sym, w_ichi, w_close) -> None:
        # Guard: with warmup >= 750 days, the weekly consolidator receives sufficient
        # bars automatically. Manual history pull is redundant and skipped during warmup.
        if self.is_warming_up:
            return
        hist = self.history(sym, 750, Resolution.DAILY)
        if hist is None or hist.empty:
            return
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.droplevel(0)
        hist.columns = [c.lower() for c in hist.columns]
        if not {"open", "high", "low", "close", "volume"}.issubset(hist.columns):
            return
        weekly = hist.resample("W-FRI").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna(subset=["close"])
        for time, row in weekly.iterrows():
            bar = TradeBar(
                time, sym,
                float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]),
                int(row["volume"]), timedelta(weeks=1),
            )
            w_ichi.update(bar)
            w_close.add(float(row["close"]))

    def _has_open_orders(self, symbol) -> bool:
        return bool(self.transactions.get_open_orders(symbol))

    def _get_position_pnl_pct(self, symbol) -> float:
        """Calculate position P&L percentage."""
        holding = self.portfolio[symbol]
        if not holding.invested or holding.average_price == 0:
            return 0.0
        current_price = float(self.securities[symbol].price)
        return (current_price - holding.average_price) / holding.average_price

    def _get_hold_days(self, symbol) -> int:
        """Get number of days position has been held."""
        if symbol not in self._position_meta:
            return 0
        entry_date = self._position_meta[symbol].get("entry_date")
        if entry_date is None:
            return 0
        return (self.time - entry_date).days

    def _update_returns_cache(self) -> None:
        """Pre-compute daily returns for all active symbols once per OnData (GH #22 performance fix).
        Stores in self._returns_cache to avoid N×M history() calls per rotation.
        """
        if self.is_warming_up:
            return
        self._returns_cache: dict[Symbol, np.ndarray] = {}
        for symbol in list(self._indicators.keys()):
            try:
                hist = self.history(symbol, 61, Resolution.DAILY)  # 61 bars for 60 returns
                if hist is None or hist.empty or len(hist) < 2:
                    continue
                if isinstance(hist.index, pd.MultiIndex):
                    hist = hist.droplevel(0)
                closes = hist['close'].values if 'close' in hist.columns else hist['Close'].values
                if len(closes) < 2:
                    continue
                returns = np.diff(closes) / closes[:-1]
                self._returns_cache[symbol] = returns
            except Exception:
                continue

    def _get_correlation(self, symbol1: Symbol, symbol2: Symbol) -> float:
        """Calculate rolling correlation between two symbols from pre-computed cache (GH #22).
        Falls back to 0.0 if either symbol not in cache.
        """
        ret1 = self._returns_cache.get(symbol1)
        ret2 = self._returns_cache.get(symbol2)
        if ret1 is None or ret2 is None or len(ret1) < 2 or len(ret2) < 2:
            return 0.0
        # Align to minimum length
        min_len = min(len(ret1), len(ret2))
        if min_len < 2:
            return 0.0
        try:
            corr = np.corrcoef(ret1[-min_len:], ret2[-min_len:])[0, 1]
            return corr if not np.isnan(corr) else 0.0
        except Exception:
            return 0.0

    def _should_rotate(self, symbol: Symbol, current_score: int, best_score: int, candidate_symbol: Symbol = None) -> bool:
        """
        Rotation engine: determine if we should rotate out of current position.
        Returns True if rotation criteria met.
        Implements atr_adaptive_score (GH #21): effective_ratio scales up to 2x in high vol.
        Implements max_corr (GH #22): skip if correlation > 0.75.
        Implements profit_alpha (GH #22): continuous multiplier when > 0.
        """
        # Check minimum hold period
        hold_days = self._get_hold_days(symbol)
        if hold_days < self.min_hold_days:
            return False

        # Score ratio threshold: only rotate if significantly better opportunity
        if best_score <= 0 or current_score <= 0:
            return False
        score_ratio = best_score / current_score if current_score > 0 else float('inf')
        
        # ATR-adaptive score ratio (GH #21): scale up in high volatility periods
        # effective_ratio = score_ratio * (1.0 + scale) where scale = min(max(atr_14/atr_252 - 1.0, 0.0), 1.0)
        # Max 2x multiplier when SPY ATR-14 is 2x ATR-252 (extreme volatility)
        effective_ratio = score_ratio
        if hasattr(self, '_spy_atr_14') and hasattr(self, '_spy_atr_252'):
            if self._spy_atr_14.is_ready and self._spy_atr_252.is_ready:
                atr_14 = float(self._spy_atr_14.current.value)
                atr_252 = float(self._spy_atr_252.current.value)
                if atr_252 > 0:
                    atr_ratio = atr_14 / atr_252
                    scale = min(max(atr_ratio - 1.0, 0.0), 1.0)
                    effective_ratio = score_ratio * (1.0 + scale)
        
        # GH #22: profit_alpha logic - continuous multiplier when > 0, otherwise binary veto
        pnl_pct = self._get_position_pnl_pct(symbol)
        if self.profit_alpha > 0.0:
            # Continuous threshold: higher profit = harder to evict
            effective_threshold = max(1.0, 1.0 + self.profit_alpha * pnl_pct)
            if effective_ratio < effective_threshold * self.score_ratio_threshold:
                return False
        else:
            # Binary veto (original logic)
            if effective_ratio < self.score_ratio_threshold:
                return False
            if pnl_pct > self.profit_veto_pct:
                return False

        # GH #22: max_corr check - skip rotation if candidate correlation with any held position > max_corr
        if candidate_symbol is not None and self.max_corr < 1.0:
            corr = self._get_correlation(candidate_symbol, symbol)
            if abs(corr) > self.max_corr:
                return False

        # Minimum PnL check: only rotate losers or small gains
        if pnl_pct < self.min_pnl_pct:
            return True

        return True

    def _daily_close_and_kijun_and_cloud_top(self, symbol) -> tuple[float, float, float] | None:
        """Fetch daily close, Kijun-sen, and cloud top for exit logic."""
        if symbol not in self._indicators:
            return None
        d_ichi = self._indicators[symbol]["d_ichi"]
        if not d_ichi.is_ready:
            return None
        
        close = float(self.securities[symbol].price)
        kijun = d_ichi.kijun.current.value
        
        senkou_a = d_ichi.senkou_a.current.value
        senkou_b = d_ichi.senkou_b.current.value
        cloud_top = max(senkou_a, senkou_b)
        
        return close, kijun, cloud_top

    def _check_resistance_proximity(self, symbol: Symbol) -> bool:
        """Check if price is within 3% of 52-week high (resistance proximity block)."""
        # Get 252-day (52-week) high
        hist = self.history(symbol, 252, Resolution.DAILY)
        if hist is None or hist.empty:
            return True  # Block if data unavailable
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.droplevel(0)
        if "close" not in [c.lower() for c in hist.columns]:
            return True
        hist.columns = [c.lower() for c in hist.columns]
        high_52w = hist["high"].max() if "high" in hist.columns else hist["close"].max()
        current_price = float(self.securities[symbol].price)
        # Block if within 3% of 52-week high
        return (high_52w - current_price) / high_52w < self.resistance_proximity_pct

    def _check_kijun_extension(self, symbol: Symbol) -> bool:
        """Check if price is extended above Kijun (kijun_extension_block)."""
        if symbol not in self._indicators:
            return True  # Block if no indicators
        d_ichi = self._indicators[symbol]["d_ichi"]
        if not d_ichi.is_ready:
            return True
        price = float(self.securities[symbol].price)
        kijun = d_ichi.kijun.current.value
        cloud_top = max(d_ichi.senkou_a.current.value, d_ichi.senkou_b.current.value)
        # Block if price > 1.5× kijun above cloud (extended)
        kijun_above_cloud = kijun > cloud_top
        if kijun_above_cloud:
            extension = (price - kijun) / kijun if kijun > 0 else 0
            return extension > (self.kijun_extension_mult - 1)  # > 0.5 = 50% above
        return False

    def _check_chikou(self, symbol: Symbol) -> bool:
        """Check daily chikou > price 26 bars ago."""
        hist = self.history(symbol, 30, Resolution.DAILY)
        if hist is None or hist.empty or len(hist) < 27:
            return False
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.droplevel(0)
        hist.columns = [c.lower() for c in hist.columns]
        if "close" not in hist.columns:
            return False
        current_price = hist["close"].iloc[-1]
        price_26_ago = hist["close"].iloc[-27]
        # Chikou check: current price > price 26 bars ago
        return current_price > price_26_ago

    def _check_min_price(self, symbol: Symbol) -> bool:
        """Check minimum price requirement only."""
        price = float(self.securities[symbol].price)
        return price >= self.min_price

    def _check_earnings(self, symbol: Symbol) -> bool:
        """Check if earnings within skip window (placeholder - requires fundamental data)."""
        # In QC Python, fundamental data access is limited
        # For now, this is a placeholder that always passes
        # TODO: Implement if fundamental data available
        return True

    def _update_spy_gate(self):
        """Update SPY gate: 4 consecutive days above weekly cloud required."""
        spy_symbol = self.symbol("SPY")
        ind = self._indicators.get(spy_symbol)
        if ind is None:
            return
        w_ichi = ind.get("w_ichi")
        if w_ichi is None or not w_ichi.is_ready:
            return
        senkou_a = float(w_ichi.senkou_a.current.value)
        senkou_b = float(w_ichi.senkou_b.current.value)
        cloud_top = max(senkou_a, senkou_b)
        spy_close = float(self.securities[spy_symbol].price)
        # Check if SPY above weekly cloud
        above_cloud = spy_close > cloud_top
        if above_cloud:
            self._spy_above_cloud_days += 1
        else:
            self._spy_above_cloud_days = 0
        # Gate opens after 4 consecutive days
        self._spy_gate_open = self._spy_above_cloud_days >= self.spy_gate_confirm_days

    def _update_vix_percentile(self) -> None:
        """GH #28 + #42: Update cached VIX size multiplier using 2-year percentile rank.

        Fetches 504-day VIX history at most once per week (GH #42 perf fix).
        Caches the closes array and refetch date. If current VIX is above the 90th
        percentile of that distribution, sets _vix_size_mult to 0.5 (half-size).
        Falls back to 1.0 (full size) on any data error.
        """
        try:
            vix_sym = self.symbol("VIX")
            today = self.time.date()

            # GH #42: only refetch 504-day history if cache is empty or > 7 days old
            if (self._vix_cache_date is None or
                (today - self._vix_cache_date).days > 7 or
                len(self._vix_cached_closes) < 10):
                hist = self.history(vix_sym, 504, Resolution.DAILY)
                if hist is None or hist.empty:
                    return
                if isinstance(hist.index, pd.MultiIndex):
                    hist = hist.droplevel(0)
                closes = hist["close"].dropna().values
                if len(closes) < 10:
                    return
                self._vix_cached_closes = closes.tolist()
                self._vix_cache_date = today

            current = float(self.securities[vix_sym].price)
            if current <= 0:
                return
            import numpy as np  # noqa: PLC0415
            pct_rank = float(np.sum(np.array(self._vix_cached_closes) < current)) / len(self._vix_cached_closes) * 100
            self._vix_size_mult = (
                self.vix_size_multiplier if pct_rank >= self.vix_percentile_threshold else 1.0
            )
        except Exception:
            self._vix_size_mult = 1.0

    def _get_vix_size_multiplier(self) -> float:
        """Return cached VIX size multiplier (updated daily in _rebalance)."""
        return self._vix_size_mult

    def _check_chikou_weekly(self, symbol: Symbol) -> bool:
        """Weekly chikou: current week close > close 26 weeks ago."""
        ind = self._indicators.get(symbol)
        if ind is None:
            return False
        w_close = ind["w_close"]
        if w_close.count < 27:
            return False
        return w_close[0] > w_close[26]

    def _check_all_entry_gates(self, symbol: Symbol) -> tuple[bool, str]:
        """Check all entry gates. Returns (passed, reason_if_failed)."""
        # Gate: kijun extension
        if self._check_kijun_extension(symbol):
            return False, "KIJUN_EXTENSION"
        # Gate: resistance proximity (within 3% of 52w high)
        if self._check_resistance_proximity(symbol):
            return False, "RESISTANCE_PROXIMITY"
        # Gate: weekly chikou (current week close > 26 weeks ago)
        if not self._check_chikou_weekly(symbol):
            return False, "CHIKOU_WEEKLY"
        # Gate: SPY 4-day close above weekly cloud
        if not self._spy_gate_open:
            return False, "SPY_GATE_CLOSED"
        # Gate: DI positive + min ADX 20
        ind = self._indicators.get(symbol)
        if ind:
            adx_ind = ind.get("adx")
            plus_di = ind.get("plus_di")
            minus_di = ind.get("minus_di")
            if adx_ind and adx_ind.is_ready and plus_di and minus_di:
                adx_val = float(adx_ind.current.value)
                if adx_val < 20:
                    return False, "ADX_TOO_LOW"
                if float(plus_di.current.value) <= float(minus_di.current.value):
                    return False, "DI_NOT_POSITIVE"
        # Gate: earnings avoidance (skip entry if within 5 days)
        if self._days_to_next_earnings(symbol) < 5:
            return False, "EARNINGS_SKIP"
        return True, ""

    def _get_atr(self, symbol: Symbol) -> float | None:
        """Get ATR14 value for symbol."""
        ind = self._indicators.get(symbol)
        if ind is None:
            return None
        atr = ind.get("atr")
        if atr is None or not atr.is_ready:
            return None
        return float(atr.current.value)

    def _get_position_stop_price(self, symbol: Symbol) -> float | None:
        """Get current stop price for position (daily ATR or Kijun trail)."""
        if symbol not in self._position_meta:
            return None
        meta = self._position_meta[symbol]
        entry_price = meta.get("entry_price", 0.0)
        if entry_price <= 0:
            return None

        atr = self._get_atr(symbol)
        initial_stop = (entry_price - 2.5 * atr) if atr and atr > 0 else entry_price * 0.95

        # Kijun trail: ratchet UP only, never below ATR stop
        vals = self._daily_close_and_kijun_and_cloud_top(symbol)
        if vals:
            _, kijun, _ = vals
            return max(initial_stop, kijun)
        return initial_stop

    def _update_and_check_stop(self, symbol: Symbol, holding) -> tuple[bool, str]:
        """Update trailing stop and check if stop triggered. Returns (should_exit, reason)."""
        # ATR initial stop with Kijun trail
        stop_price = self._get_position_stop_price(symbol)
        if stop_price is None:
            return False, ""
        
        close = float(self.securities[symbol].price)
        if close < stop_price:
            vals = self._daily_close_and_kijun_and_cloud_top(symbol)
            kijun = vals[1] if vals else 0
            return True, f"ATR_STOP|stop={stop_price:.2f}|close={close:.2f}|kijun={kijun:.2f}"
        return False, ""

    # ── Item 5: Ladder trim + reversal profit exit ────────────────────────────

    def _check_ladder_trims(self, symbol: Symbol, holding) -> list[dict]:
        """Check if any ladder rungs have been hit and return trim actions.

        Mirrors kumo-trader decision_engine.py:231-248.
        Returns list of trim dicts: {rung_key, qty}. Empty if nothing to trim.
        """
        if symbol not in self._position_meta:
            return []
        meta = self._position_meta[symbol]
        entry_price = meta.get("entry_price", 0.0)
        if entry_price <= 0:
            return []
        fired = meta.get("ladder_trims", set())
        close = float(self.securities[symbol].price)
        trims = []
        for rung_pct in self.ladder_rungs_pct:
            rung_key = f"{int(rung_pct)}pct"
            if rung_key in fired:
                continue
            target = entry_price * (1.0 + rung_pct / 100.0)
            if close >= target:
                trim_qty = max(1, int(holding.quantity * self.ladder_trim_fraction))
                trims.append({"rung_key": rung_key, "qty": trim_qty, "target": target})
        return trims

    def _check_reversal_profit_exit(self, symbol: Symbol, holding) -> bool:
        """Return True if reversal-profit exit should fire.

        Conditions (mirrors kumo-trader decision_engine.py:251-272):
          1. Current gain >= reversal_profit_min_gain_pct (6%)
          2. Price extended >= reversal_profit_extension_pct (10%) above Tenkan
          3. Today's candle is a reversal: upper shadow >= 2x body AND
             close in the bottom 30% of the day's high-low range
        """
        date_str = self.time.strftime("%Y-%m-%d")
        
        if not self.reversal_profit_enabled:
            return False
        if symbol not in self._position_meta:
            return False
        meta = self._position_meta[symbol]
        entry_price = meta.get("entry_price", 0.0)
        if entry_price <= 0:
            return False

        close = float(self.securities[symbol].price)
        gain = (close - entry_price) / entry_price
        if gain < self.reversal_profit_min_gain_pct:
            self.log(f"REVERSAL_CHECK|{date_str}|{symbol.value}|FAIL=gain|gain={gain:.3f}|min={self.reversal_profit_min_gain_pct:.3f}")
            return False

        # Check Tenkan extension
        ind = self._indicators.get(symbol)
        if ind is None:
            self.log(f"REVERSAL_CHECK|{date_str}|{symbol.value}|FAIL=no_indicators")
            return False
        d_ichi = ind.get("d_ichi")
        if d_ichi is None or not d_ichi.is_ready:
            self.log(f"REVERSAL_CHECK|{date_str}|{symbol.value}|FAIL=ichi_not_ready")
            return False
        # Tenkan extension check (primary)
        tenkan = d_ichi.tenkan.current.value
        extension = (close - tenkan) / tenkan if tenkan > 0 else 0
        tenkan_ext = extension
        
        # If Tenkan extension fails, try Kijun fallback (champion behavior)
        if extension < self.reversal_profit_extension_pct:
            kijun = d_ichi.kijun.current.value
            if kijun > 0:
                extension = (close - kijun) / kijun
        
        if extension < self.reversal_profit_extension_pct:
            self.log(f"REVERSAL_CHECK|{date_str}|{symbol.value}|FAIL=extension|gain={gain:.3f}|tenkan_ext={tenkan_ext:.3f}|kijun_ext={extension:.3f}|min_ext={self.reversal_profit_extension_pct:.3f}")
            return False

        # Check reversal candle using last 2 daily bars
        hist = self.history(symbol, 2, Resolution.DAILY)
        if hist is None or hist.empty or len(hist) < 1:
            self.log(f"REVERSAL_CHECK|{date_str}|{symbol.value}|FAIL=no_history")
            return False
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.droplevel(0)
        hist.columns = [c.lower() for c in hist.columns]
        required = {"open", "high", "low", "close"}
        if not required.issubset(hist.columns):
            self.log(f"REVERSAL_CHECK|{date_str}|{symbol.value}|FAIL=missing_ohlc")
            return False
        today_bar = hist.iloc[-1]
        prev_bar = hist.iloc[-2] if len(hist) > 1 else None
        o, h, lo, c = float(today_bar["open"]), float(today_bar["high"]), float(today_bar["low"]), float(today_bar["close"])
        body = abs(c - o)
        candle_range = h - lo
        if candle_range <= 0:
            self.log(f"REVERSAL_CHECK|{date_str}|{symbol.value}|FAIL=zero_range|gain={gain:.3f}|ext={extension:.3f}")
            return False
        
        # Champion reversal candle check: spinning top OR bearish engulfing
        body_ratio = 0.35
        is_spinning_top = body < body_ratio * candle_range
        
        # Bearish engulfing pattern
        is_bearish_engulfing = False
        if prev_bar is not None:
            prev_o = float(prev_bar["open"])
            prev_c = float(prev_bar["close"])
            is_bearish_engulfing = (c < o) and (o >= prev_c) and (c <= prev_o)
        
        is_reversal = is_spinning_top or is_bearish_engulfing
        
        if not is_reversal:
            self.log(f"REVERSAL_CHECK|{date_str}|{symbol.value}|FAIL=candle|gain={gain:.3f}|ext={extension:.3f}|spinning={is_spinning_top}|engulf={is_bearish_engulfing}")
        else:
            self.log(f"REVERSAL_CHECK|{date_str}|{symbol.value}|PASS|gain={gain:.3f}|ext={extension:.3f}|spinning={is_spinning_top}|engulf={is_bearish_engulfing}")
        
        return is_reversal

    # ── Item 6: Earnings avoidance ────────────────────────────────────────────

    def _days_to_next_earnings(self, symbol: Symbol) -> int | None:
        """Return days until next earnings report, or None if unknown/unavailable."""
        try:
            ticker = symbol.value
            dates = self._earnings_dict.get(ticker, [])
            if not dates:
                return 999
            today = self.time.strftime("%Y-%m-%d")
            future = [d for d in dates if d >= today]
            if not future:
                return 999
            next_date = min(future)
            delta = (datetime.strptime(next_date, "%Y-%m-%d") - self.time).days
            return max(delta, 0)
        except Exception:
            return 999

    def _rebalance(self) -> None:
        if self.is_warming_up:
            return
        date_str = self.time.strftime("%Y-%m-%d")

        # Update SPY gate state (Item 4: sT10e champion)
        self._update_spy_gate()
        # Update VIX percentile size multiplier (GH #28)
        self._update_vix_percentile()

        # Process position exits and adds
        for symbol, holding in list(self.portfolio.items()):
            if not holding.invested or self._has_open_orders(symbol):
                continue
            
            # ── Item 6: Earnings exits (run before ATR stop) ──────────────
            days_out = self._days_to_next_earnings(symbol)
            if days_out is not None:
                pnl_pct = self._get_position_pnl_pct(symbol)
                # Adaptive: profitable positions exit earlier (9 days out)
                if (self.adaptive_earnings_enabled
                        and pnl_pct >= self.adaptive_earnings_gain_threshold
                        and days_out <= self.adaptive_earnings_exit_days):
                    self.market_on_open_order(symbol, -holding.quantity)
                    self.log(
                        f"ADAPTIVE_EARNINGS_EXIT|{date_str}|{symbol.value}"
                        f"|days_out={days_out}|pnl={pnl_pct:.1%}|gain_thresh={self.adaptive_earnings_gain_threshold:.0%}"
                    )
                    if symbol in self._position_meta:
                        del self._position_meta[symbol]
                    continue
                # Hard: always exit 3 days before earnings
                elif days_out <= self.earnings_exit_days_before:
                    self.market_on_open_order(symbol, -holding.quantity)
                    self.log(
                        f"EARNINGS_EXIT|{date_str}|{symbol.value}"
                        f"|days_out={days_out}|pnl={pnl_pct:.1%}"
                    )
                    if symbol in self._position_meta:
                        del self._position_meta[symbol]
                    continue

            # ── Item 5: Reversal profit exit (before ladder — full exit) ──
            if self._check_reversal_profit_exit(symbol, holding):
                self.market_on_open_order(symbol, -holding.quantity)
                pnl_pct = self._get_position_pnl_pct(symbol)
                self.log(
                    f"REVERSAL_PROFIT_EXIT|{date_str}|{symbol.value}"
                    f"|pnl={pnl_pct:.1%}"
                )
                if symbol in self._position_meta:
                    del self._position_meta[symbol]
                continue

            # ── Item 5: Ladder trims (partial — do not skip to next position) ──
            trims = self._check_ladder_trims(symbol, holding)
            for trim in trims:
                rung_key = trim["rung_key"]
                trim_qty = trim["qty"]
                # Do not trim more than we hold
                trim_qty = min(trim_qty, holding.quantity)
                if trim_qty > 0:
                    self.market_on_open_order(symbol, -trim_qty)
                    self.log(
                        f"TRIM|{date_str}|{symbol.value}"
                        f"|rung={rung_key}|qty={trim_qty}|target={trim['target']:.2f}"
                    )
                    if symbol in self._position_meta:
                        self._position_meta[symbol]["ladder_trims"].add(rung_key)

            # Update trailing stop and check exit
            should_exit, exit_reason = self._update_and_check_stop(symbol, holding)
            if should_exit:
                self.market_on_open_order(symbol, -holding.quantity)
                self.log(f"EXIT|{date_str}|{symbol.value}|{exit_reason}")
                # Clear position metadata
                if symbol in self._position_meta:
                    del self._position_meta[symbol]
                continue
            
            # Legacy exit checks (optional, controlled by parameters)
            vals = self._daily_close_and_kijun_and_cloud_top(symbol)
            if vals:
                close, kijun, cloud_top = vals
                w_ichi = self._indicators[symbol]["w_ichi"]
                w_kijun = w_ichi.kijun.current.value if w_ichi.is_ready else None
                
                if self.cloud_exit_enabled and close < cloud_top:
                    self.market_on_open_order(symbol, -holding.quantity)
                    self.log(f"CLOUD_EXIT|{date_str}|{symbol.value}|close={close:.2f}|cloud_top={cloud_top:.2f}")
                    if symbol in self._position_meta:
                        del self._position_meta[symbol]
                elif self.weekly_kijun_exit_enabled and w_kijun is not None and close < w_kijun:
                    self.market_on_open_order(symbol, -holding.quantity)
                    self.log(f"WEEKLY_KIJUN_STOP|{date_str}|{symbol.value}|close={close:.2f}|w_kijun={w_kijun:.2f}")
                    if symbol in self._position_meta:
                        del self._position_meta[symbol]

        exiting = {
            o.symbol
            for o in self.transactions.get_open_orders()
            if o.quantity < 0
        }
        open_count = sum(
            1 for sym, h in self.portfolio.items()
            if h.invested and sym not in exiting
        )
        slots = max(0, self.MAX_POSITIONS - open_count)

        # Entry funnel counters (single DEBUG line per rebalance cycle)
        funnel_total_candidates = 0
        funnel_prefilter_pass = 0
        funnel_score_pass = 0
        funnel_slot_pass = 0
        funnel_reach_sizing = 0
        funnel_orders_submitted = 0

        # GH #22: Pre-compute returns cache for correlation checks (performance optimization)
        # Avoids N×M history() calls during rotation
        if self.max_corr < 1.0:
            self._update_returns_cache()
        
        # Score all symbols for rotation decisions
        all_scores: dict[Symbol, int] = {}
        for symbol in list(self._indicators.keys()):
            funnel_total_candidates += 1
            if not self.securities.contains_key(symbol):
                continue

            # Stage 2: pre-filter (price >= min_price only)
            if not self._check_min_price(symbol):
                continue
            funnel_prefilter_pass += 1
            
            # === PRE-FILTER: skip symbols that cannot reach MIN_SCORE ===
            ind = self._indicators.get(symbol)
            if ind is not None:
                sma200_ind = ind.get("sma200")
                d_ichi_ind = ind.get("d_ichi")
                if (sma200_ind and sma200_ind.is_ready and 
                    d_ichi_ind and d_ichi_ind.is_ready):
                    price = float(self.securities[symbol].price)
                    if price <= 0:
                        continue
                    # Condition 8: price > SMA200
                    if price < sma200_ind.current.value:
                        continue
                    # Condition 5: price > daily cloud top
                    cloud_top = max(d_ichi_ind.senkou_a.current.value, 
                                   d_ichi_ind.senkou_b.current.value)
                    if price < cloud_top:
                        continue
            # === END PRE-FILTER ===
            
            result = score_symbol(self, symbol, ind)
            if result is None or result["score"] < self.MIN_SCORE:
                continue
            all_scores[symbol] = result["score"]
            funnel_score_pass += 1

        # Rotation engine: check for positions to rotate out
        if len(all_scores) > 0:
            best_score = max(all_scores.values())
            for symbol, holding in list(self.portfolio.items()):
                if not holding.invested:
                    continue
                current_score = all_scores.get(symbol, 0)
                if self._should_rotate(symbol, current_score, best_score):
                    self.market_on_open_order(symbol, -holding.quantity)
                    self.log(f"ROTATE|{date_str}|{symbol.value}|score={current_score}|best={best_score}|pnl={self._get_position_pnl_pct(symbol):.2%}")
                    # Clear position metadata
                    if symbol in self._position_meta:
                        del self._position_meta[symbol]

        # Build candidates list from non-invested symbols
        candidates: list[tuple[Symbol, int]] = [
            (symbol, score) for symbol, score in all_scores.items()
            if not self.portfolio[symbol].invested and symbol not in exiting
        ]
        candidates.sort(key=lambda x: x[1], reverse=True)
        funnel_slot_pass = min(len(candidates), slots)

        for symbol, score in candidates[:slots]:
            price = float(self.securities[symbol].price)
            if price <= 0:
                continue
            
            # GH #22: max_corr check - skip candidate if correlation with any held position > max_corr
            if self.max_corr < 1.0:
                held_positions = [s for s, h in self.portfolio.items() if h.invested]
                if held_positions:
                    max_correlation = max(abs(self._get_correlation(symbol, held_sym)) for held_sym in held_positions)
                    if max_correlation > self.max_corr:
                        self.log(f"GATE_BLOCK|{date_str}|{symbol.value}|reason=CORR_TOO_HIGH|corr={max_correlation:.2f}|max={self.max_corr}")
                        continue
            
            # ── Item 6: Earnings entry gate ────────────────────────────────
            days_out = self._days_to_next_earnings(symbol)
            if days_out is not None and days_out <= self.skip_if_earnings_days:
                self.log(
                    f"GATE_BLOCK|{date_str}|{symbol.value}"
                    f"|reason=EARNINGS_WITHIN_{days_out}d|score={score}"
                )
                continue

            # Check entry gates (Item 4: sT10e champion)
            gates_passed, gate_reason = self._check_all_entry_gates(symbol)
            if not gates_passed:
                self.log(f"GATE_BLOCK|{date_str}|{symbol.value}|reason={gate_reason}|score={score}")
                continue
            
            # Fixed-risk sizing: $200 risk per position / (2.5 * ATR14)
            funnel_reach_sizing += 1
            atr = self._get_atr(symbol)
            if atr and atr > 0:
                # 2% floor: reject if ATR stop < 2% below entry
                stop_pct = (2.5 * atr) / price
                if stop_pct < 0.02:
                    self.log(f"GATE_BLOCK|{date_str}|{symbol.value}|reason=ATR_FLOOR_2PCT|atr_pct={stop_pct:.3f}")
                    continue
                # Position size = $200 / (2.5 * ATR)
                risk_per_share = 2.5 * atr
                shares = int(200.0 / risk_per_share * self._get_vix_size_multiplier())
                target_value = shares * price
                # Cap at max position size (10% of portfolio)
                max_value = self.portfolio.total_portfolio_value * self.POSITION_PCT
                if target_value > max_value:
                    target_value = max_value
                    shares = int(target_value / price)
                quantity = shares
            else:
                # Fallback: flat 10% sizing if ATR unavailable
                target_value = self.portfolio.total_portfolio_value * self.POSITION_PCT
                quantity = int(target_value / price * self._get_vix_size_multiplier())
            if quantity <= 0:
                continue

            # Entry: market-on-open at current price
            self.market_on_open_order(symbol, quantity)
            funnel_orders_submitted += 1

            # Track position entry metadata
            self._position_meta[symbol] = {
                "entry_date": self.time,
                "entry_price": price,
                "original_quantity": quantity,
                "ladder_trims": set(),
            }

            self.log(f"ENTRY|{date_str}|{symbol.value}|score={score}/8|qty={quantity}|mark={price:.2f}")

        self.log(f"REBALANCE|{date_str}|open={open_count}|new_entries={min(len(candidates), slots)}")
        self.debug(
            f"FUNNEL|{date_str}"
            f"|total={funnel_total_candidates}"
            f"|prefilter_pass={funnel_prefilter_pass}"
            f"|score_gte_{self.MIN_SCORE}={funnel_score_pass}"
            f"|slot_pass={funnel_slot_pass}"
            f"|reach_sizing={funnel_reach_sizing}"
            f"|order_submitted={funnel_orders_submitted}"
        )
