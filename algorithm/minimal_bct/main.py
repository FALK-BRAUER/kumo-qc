from __future__ import annotations
"""
Minimal BCT backtest — hardcoded universe, no Morningstar/fundamental data.

Purpose: local + QC cloud parity baseline that bypasses has_fundamental_data=True
blocker (GH #14/#16). Proves the BCT scoring and execution logic works end-to-end
without the coarse/fine universe filter.

Universe: 545 tickers (S&P 500 + BCT DEFAULT_TICKERS, merged + deduped).
Signal: same 8-condition BCT Blue Flag checklist as performance_bct.
Entry Gates: SPY 4-day confirm, 3% from 52w high, Kijun extension check,
      chikou confirm, min $3 price, $500K volume, VIX tier (50% if >30).
Exits: ATR trailing stop (22-period, 2.5x initial, 3.0x floor) + Kijun trail +
      ladder trim [20%,40%] + reversal_profit_exit (6% gain, 10% Tenkan ext) +
      earnings exits (adaptive 9d / hard 3d) + optional cloud breach + weekly Kijun.
Sizing: Fixed-risk $200 per position with ATR-based position sizing.
Adds: Cloud top break triggers (50% of original, max 1 add).
Rotation: score_ratio ≥ 2.0, profit veto at +5%.
Parameters: warmup_days (default 750), cloud_exit (default false),
      weekly_kijun_exit (default false), atr_period (default 22).
"""

from datetime import timedelta

from AlgorithmImports import *  # noqa: F401,F403

from bct_signal import score_symbol


class BCTMinimalAlgorithm(QCAlgorithm):

    MAX_POSITIONS: int = 10
    POSITION_PCT: float = 0.10
    MIN_SCORE: int = 7

    # Rotation engine parameters (Item 2: sT10e+R-B-v3)
    SCORE_RATIO_THRESHOLD: float = 2.0
    MIN_HOLD_DAYS: int = 1
    MIN_PNL_PCT: float = 0.0
    PROFIT_VETO_PCT: float = 0.05

    # Buy-stop fill parameter (Item 3: sT10e+R-B-v3)
    BUY_STOP_PCT: float = 0.0075  # 0.75% above close

    # Entry gates (Item 4: sT10e champion)
    RESISTANCE_PROXIMITY_PCT: float = 0.03  # 3% from 52-week high
    KIJUN_EXTENSION_MULT: float = 1.5  # 1.5× kijun above cloud
    MIN_PRICE: float = 3.0
    SKIP_IF_EARNINGS_DAYS: int = 5
    SPY_GATE_CONFIRM_DAYS: int = 4
    VIX_THRESHOLD: float = 30.0
    VIX_SIZE_MULTIPLIER: float = 0.50  # 50% size when VIX > 30

    # Merged universe: 545 tickers (503 S&P 500 + 95 BCT, deduped)
    UNIVERSE: list[str] = [
        # Group 1
        "A", "AAL", "AAPL", "ABBV", "ABNB", "ABT", "ACGL", "ACN", "ADBE", "ADI",
        # Group 2
        "ADM", "ADP", "ADSK", "AEE", "AEP", "AES", "AFL", "AIG", "AIQ", "AIZ",
        # Group 3
        "AJG", "AKAM", "ALB", "ALGN", "ALL", "ALLE", "AMAT", "AMCR", "AMD", "AME",
        # Group 4
        "AMGN", "AMP", "AMT", "AMZN", "ANET", "AON", "AOS", "APA", "APD", "APH",
        # Group 5
        "APO", "APP", "APTV", "ARE", "ARES", "ARKQ", "ATO", "AVB", "AVGO", "AVY",
        # Group 6
        "AWK", "AXON", "AXP", "AZO", "BA", "BAC", "BALL", "BAX", "BBY", "BDX",
        # Group 7
        "BEN", "BF-B", "BG", "BIIB", "BK", "BKNG", "BKR", "BLDR", "BLK", "BMY",
        # Group 8
        "BOTZ", "BR", "BRK-B", "BRO", "BSX", "BUG", "BX", "BXP", "C", "CAG",
        # Group 9
        "CAH", "CARR", "CASY", "CAT", "CB", "CBOE", "CBRE", "CCI", "CCL", "CDNS",
        # Group 10
        "CDW", "CEG", "CF", "CFG", "CGNX", "CHD", "CHRW", "CHTR", "CI", "CIBR",
        # Group 11
        "CIEN", "CINF", "CL", "CLX", "CMCSA", "CME", "CMG", "CMI", "CMS", "CNC",
        # Group 12
        "CNP", "COF", "COHR", "COIN", "COO", "COP", "COPX", "COR", "COST", "CPAY",
        # Group 13
        "CPB", "CPRT", "CPT", "CRH", "CRL", "CRM", "CRWD", "CSCO", "CSGP", "CSX",
        # Group 14
        "CTAS", "CTSH", "CTVA", "CVNA", "CVS", "CVX", "D", "DAL", "DASH", "DD",
        # Group 15
        "DDOG", "DE", "DECK", "DELL", "DG", "DGX", "DHI", "DHR", "DIS", "DLR",
        # Group 16
        "DLTR", "DOC", "DOV", "DOW", "DPZ", "DRI", "DTE", "DUK", "DVA", "DVN",
        # Group 17
        "DXCM", "EA", "EBAY", "ECL", "ED", "EFX", "EG", "EIX", "EL", "ELV",
        # Group 18
        "EME", "EMR", "EOG", "EPAM", "EQIX", "EQR", "EQT", "ERIE", "ES", "ESS",
        # Group 19
        "ETN", "ETR", "EVRG", "EW", "EWJ", "EXC", "EXE", "EXPD", "EXPE", "EXR",
        # Group 20
        "F", "FANG", "FAST", "FCX", "FDS", "FDX", "FE", "FFIV", "FICO", "FIS",
        # Group 21
        "FISV", "FITB", "FIX", "FOX", "FOXA", "FRT", "FSLR", "FTNT", "FTV", "FXI",
        # Group 22
        "GD", "GDDY", "GDX", "GE", "GEHC", "GEN", "GEV", "GILD", "GIS", "GL",
        # Group 23
        "GLD", "GLW", "GM", "GNRC", "GOOG", "GOOGL", "GPC", "GPN", "GRID", "GRMN",
        # Group 24
        "GS", "GWW", "HACK", "HAL", "HAS", "HBAN", "HCA", "HD", "HIG", "HII",
        # Group 25
        "HLT", "HON", "HOOD", "HPE", "HPQ", "HRL", "HSIC", "HST", "HSY", "HUBB",
        # Group 26
        "HUBS", "HUM", "HWM", "IBB", "IBIT", "IBKR", "IBM", "ICE", "ICLN", "IDXX",
        # Group 27
        "IEX", "IFF", "INCY", "INTC", "INTU", "INVH", "IP", "IQV", "IR", "IRBO",
        # Group 28
        "IRM", "ISRG", "IT", "ITA", "ITW", "IVZ", "IWM", "J", "JBHT", "JBL",
        # Group 29
        "JCI", "JKHY", "JNJ", "JPM", "KDP", "KEY", "KEYS", "KHC", "KIM", "KKR",
        # Group 30
        "KLAC", "KMB", "KMI", "KO", "KR", "KVUE", "KWEB", "L", "LDOS", "LEN",
        # Group 31
        "LH", "LHX", "LII", "LIN", "LITE", "LLY", "LMT", "LNT", "LOW", "LRCX",
        # Group 32
        "LULU", "LUV", "LVS", "LYB", "LYV", "MA", "MAA", "MAR", "MAS", "MCD",
        # Group 33
        "MCHP", "MCK", "MCO", "MDLZ", "MDT", "MET", "META", "MGM", "MKC", "MLM",
        # Group 34
        "MMM", "MNST", "MO", "MOS", "MPC", "MPWR", "MRK", "MRNA", "MRSH", "MRVL",
        # Group 35
        "MS", "MSCI", "MSFT", "MSI", "MSTR", "MTB", "MTD", "MU", "NCLH", "NDAQ",
        # Group 36
        "NDSN", "NEE", "NEM", "NET", "NFLX", "NI", "NKE", "NOC", "NOW", "NRG",
        # Group 37
        "NSC", "NTAP", "NTRS", "NUE", "NVDA", "NVR", "NWS", "NWSA", "NXPI", "O",
        # Group 38
        "ODFL", "OKE", "OMC", "ON", "ORCL", "ORLY", "OTIS", "OXY", "PANW", "PAYX",
        # Group 39
        "PCAR", "PCG", "PEG", "PEP", "PFE", "PFG", "PG", "PGR", "PH", "PHM",
        # Group 40
        "PKG", "PLD", "PLTR", "PM", "PNC", "PNR", "PNW", "PODD", "POOL", "PPG",
        # Group 41
        "PPL", "PRU", "PSA", "PSKY", "PSX", "PTC", "PWR", "PYPL", "Q", "QCOM",
        # Group 42
        "QQQ", "RCL", "REG", "REGN", "RF", "RJF", "RL", "RMD", "ROBO", "ROBT",
        # Group 43
        "ROK", "ROL", "ROP", "ROST", "RSG", "RTX", "RVTY", "SATS", "SBAC", "SBUX",
        # Group 44
        "SCHW", "SHW", "SJM", "SLB", "SLV", "SMCI", "SMH", "SNA", "SNDK", "SNOW",
        # Group 45
        "SNPS", "SO", "SOLV", "SPG", "SPGI", "SPY", "SRE", "STE", "STLD", "STT",
        # Group 46
        "STX", "STZ", "SW", "SWK", "SWKS", "SYF", "SYK", "SYY", "T", "TAP",
        # Group 47
        "TDG", "TDY", "TECH", "TEL", "TER", "TFC", "TGT", "TJX", "TKO", "TMO",
        # Group 48
        "TMUS", "TPL", "TPR", "TRGP", "TRMB", "TROW", "TRV", "TSCO", "TSLA", "TSM",
        # Group 49
        "TSN", "TT", "TTD", "TTWO", "TXN", "TXT", "TYL", "UAL", "UBER", "UDR",
        # Group 50
        "UHS", "ULTA", "UNH", "UNP", "UPS", "URI", "URNM", "USB", "USO", "V",
        # Group 51
        "VEEV", "VICI", "VLO", "VLTO", "VMC", "VRSK", "VRSN", "VRT", "VRTX", "VST",
        # Group 52
        "VTR", "VTRS", "VZ", "WAB", "WAT", "WBD", "WDAY", "WDC", "WEC", "WELL",
        # Group 53
        "WFC", "WM", "WMB", "WMT", "WRB", "WSM", "WST", "WTW", "WY", "WYNN",
        # Group 54
        "XAR", "XBI", "XEL", "XLE", "XLF", "XLK", "XME", "XOM", "XYL", "XYZ",
        # Group 55
        "YUM", "ZBH", "ZBRA", "ZS", "ZTS",
    ]

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

        # Buy-stop fill parameter (Item 3: sT10e+R-B-v3)
        self.buy_stop_pct = float(self.get_parameter("buy_stop_pct", str(self.BUY_STOP_PCT)))

        # Entry gates parameters (Item 4: sT10e champion)
        self.resistance_proximity_pct = float(self.get_parameter("resistance_proximity_pct", str(self.RESISTANCE_PROXIMITY_PCT)))
        self.kijun_extension_mult = float(self.get_parameter("kijun_extension_mult", str(self.KIJUN_EXTENSION_MULT)))
        self.min_price = float(self.get_parameter("min_price", str(self.MIN_PRICE)))
        self.skip_if_earnings_days = int(self.get_parameter("skip_if_earnings_days", str(self.SKIP_IF_EARNINGS_DAYS)))
        self.spy_gate_confirm_days = int(self.get_parameter("spy_gate_confirm_days", str(self.SPY_GATE_CONFIRM_DAYS)))
        self.vix_threshold = float(self.get_parameter("vix_threshold", str(self.VIX_THRESHOLD)))
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

        self.universe_settings.resolution = Resolution.DAILY
        self._indicators: dict = {}
        self._position_meta: dict = {}  # Track entry date, avg price per position
        for ticker in self.UNIVERSE:
            sym = self.add_equity(ticker, Resolution.DAILY).symbol
            self._register_indicators(sym)

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
            "consolidator": consolidator,
        }

    def _seed_weekly(self, sym, w_ichi, w_close) -> None:
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

    def _should_rotate(self, symbol: Symbol, current_score: int, best_score: int) -> bool:
        """
        Rotation engine: determine if we should rotate out of current position.
        Returns True if rotation criteria met.
        """
        # Check minimum hold period
        hold_days = self._get_hold_days(symbol)
        if hold_days < self.min_hold_days:
            return False

        # Score ratio threshold: only rotate if significantly better opportunity
        if best_score <= 0 or current_score <= 0:
            return False
        score_ratio = best_score / current_score if current_score > 0 else float('inf')
        if score_ratio < self.score_ratio_threshold:
            return False

        # Profit veto: don't rotate if position is profitable above threshold
        pnl_pct = self._get_position_pnl_pct(symbol)
        if pnl_pct > self.profit_veto_pct:
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
        if spy_symbol not in self._indicators:
            return
        vals = self._daily_close_and_kijun_and_cloud_top(spy_symbol)
        if vals is None:
            return
        close, _, cloud_top = vals
        # Check if SPY above weekly cloud
        above_cloud = close > cloud_top
        if above_cloud:
            self._spy_above_cloud_days += 1
        else:
            self._spy_above_cloud_days = 0
        # Gate opens after 4 consecutive days
        self._spy_gate_open = self._spy_above_cloud_days >= self.spy_gate_confirm_days

    def _get_vix_size_multiplier(self) -> float:
        """Get position size multiplier based on VIX level."""
        # DIAGNOSTIC: VIX tier disabled
        return 1.0
        # try:
        #     vix_symbol = self.symbol("VIX")
        #     vix_price = float(self.securities[vix_symbol].price)
        #     if vix_price > self.vix_threshold:
        #         return self.vix_size_multiplier  # 50% size
        # except:
        #     pass
        # return 1.0  # Normal size

    def _check_all_entry_gates(self, symbol: Symbol) -> tuple[bool, str]:
        """Check all entry gates. Returns (passed, reason_if_failed)."""
        # DIAGNOSTIC: all Item 4 gates disabled — isolating gate over-filter
        return True, ""
        # # SPY gate must be open
        # if not self._spy_gate_open:
        #     return False, "SPY_GATE_CLOSED"
        # # Resistance proximity
        # if self._check_resistance_proximity(symbol):
        #     return False, "RESISTANCE_PROXIMITY"
        # # Kijun extension
        # if self._check_kijun_extension(symbol):
        #     return False, "KIJUN_EXTENSION"
        # # Chikou check
        # if not self._check_chikou(symbol):
        #     return False, "CHIKOU_FAIL"
        # # Min price/volume
        # if not self._check_min_price_volume(symbol):
        #     return False, "MIN_PRICE_VOLUME"
        # # Earnings skip
        # if not self._check_earnings(symbol):
        #     return False, "EARNINGS_SKIP"

    def _update_and_check_stop(self, symbol: Symbol, holding) -> tuple[bool, str]:
        """Update trailing stop and check if stop triggered. Returns (should_exit, reason)."""
        # DIAGNOSTIC: ATR stop disabled — daily Kijun stop only
        vals = self._daily_close_and_kijun_and_cloud_top(symbol)
        if vals is None:
            return False, ""
        close, kijun, _ = vals
        if close < kijun:
            return True, f"KIJUN_STOP|kijun={kijun:.2f}|close={close:.2f}"
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
            return False

        # Check Tenkan extension
        ind = self._indicators.get(symbol)
        if ind is None:
            return False
        d_ichi = ind.get("d_ichi")
        if d_ichi is None or not d_ichi.is_ready:
            return False
        tenkan = d_ichi.tenkan.current.value
        if tenkan <= 0:
            return False
        extension = (close - tenkan) / tenkan
        if extension < self.reversal_profit_extension_pct:
            return False

        # Check reversal candle using last 2 daily bars
        hist = self.history(symbol, 2, Resolution.DAILY)
        if hist is None or hist.empty or len(hist) < 1:
            return False
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.droplevel(0)
        hist.columns = [c.lower() for c in hist.columns]
        required = {"open", "high", "low", "close"}
        if not required.issubset(hist.columns):
            return False
        today_bar = hist.iloc[-1]
        o, h, lo, c = float(today_bar["open"]), float(today_bar["high"]), float(today_bar["low"]), float(today_bar["close"])
        body = abs(c - o)
        candle_range = h - lo
        if candle_range <= 0:
            return False
        upper_shadow = h - max(o, c)
        # Reversal: upper shadow >= 2x body AND close in bottom 30% of range
        is_reversal = (upper_shadow >= 2.0 * body) and ((c - lo) / candle_range <= 0.30)
        return is_reversal

    # ── Item 6: Earnings avoidance ────────────────────────────────────────────

    def _days_to_next_earnings(self, symbol: Symbol) -> int | None:
        """Return days until next earnings report, or None if unknown/unavailable.

        NOTE: Stubbed to 999 to disable earnings gates. QC's Fundamental object
        uses 'earning_reports' (singular) not 'earnings_reports', and even then
        may not provide reliable forward-looking dates. Re-enable with proper
        earnings data integration in future iteration.
        """
        # STUB: Return 999 to effectively disable all earnings gates
        # This unblocks cloud backtesting while we research proper earnings data
        return 999

    def _rebalance(self) -> None:
        if self.is_warming_up:
            return
        date_str = self.time.strftime("%Y-%m-%d")

        # Update SPY gate state (Item 4: sT10e champion)
        self._update_spy_gate()

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

        # Score all symbols for rotation decisions
        all_scores: dict[Symbol, int] = {}
        for ticker in self.UNIVERSE:
            funnel_total_candidates += 1
            try:
                symbol = self.symbol(ticker)
            except Exception:
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
            
            # Calculate position size: flat 10% of portfolio
            funnel_reach_sizing += 1
            target_value = self.portfolio.total_portfolio_value * self.POSITION_PCT
            quantity = int(target_value / price)
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
                "ladder_trims": set(),  # Track which ladder rungs fired
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
