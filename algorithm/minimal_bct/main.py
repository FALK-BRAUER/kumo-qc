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
      optional cloud breach + weekly Kijun.
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
    ATR_ADAPTIVE_SCORE: bool = True
    MIN_PNL_PCT: float = 0.0
    PROFIT_VETO_PCT: float = 0.05

    # Buy-stop fill parameter (Item 3: sT10e+R-B-v3)
    BUY_STOP_PCT: float = 0.0075  # 0.75% above close

    # ATR stop + sizing parameters (Item 7: sT10e champion)
    ATR_PERIOD: int = 22
    ATR_STOP_MULT_INITIAL: float = 2.5
    ATR_STOP_MULT_FLOOR: float = 3.0
    FIXED_RISK_DOLLARS: float = 200.0  # $200 max risk per position
    MAX_POSITION_PCT: float = 0.10  # 10% max position size
    TRAIL_TO_TENKAN_FIRST: bool = True
    NEVER_LOWER_STOP: bool = True
    STOP_ON_CLOSE_ONLY: bool = True
    ADD_AT_CLOUD_BREAK_PCT: float = 0.50  # 50% of original position
    MAX_ADDS: int = 1
    PYRAMID_PCT: float = 0.50  # 50% of original

    # Entry gates (Item 4: sT10e champion)
    RESISTANCE_PROXIMITY_PCT: float = 0.03  # 3% from 52-week high
    KIJUN_EXTENSION_MULT: float = 1.5  # 1.5× kijun above cloud
    MIN_PRICE: float = 3.0
    MIN_DOLLAR_VOLUME: float = 500000.0
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
        self.atr_adaptive_score = self.get_parameter("atr_adaptive_score", str(self.ATR_ADAPTIVE_SCORE)).lower() == "true"
        self.min_pnl_pct = float(self.get_parameter("min_pnl_pct", str(self.MIN_PNL_PCT)))
        self.profit_veto_pct = float(self.get_parameter("profit_veto_pct", str(self.PROFIT_VETO_PCT)))

        # Buy-stop fill parameter (Item 3: sT10e+R-B-v3)
        self.buy_stop_pct = float(self.get_parameter("buy_stop_pct", str(self.BUY_STOP_PCT)))

        # ATR stop + sizing parameters (Item 7: sT10e champion)
        self.atr_period = int(self.get_parameter("atr_period", str(self.ATR_PERIOD)))
        self.atr_stop_mult_initial = float(self.get_parameter("atr_stop_mult_initial", str(self.ATR_STOP_MULT_INITIAL)))
        self.atr_stop_mult_floor = float(self.get_parameter("atr_stop_mult_floor", str(self.ATR_STOP_MULT_FLOOR)))
        self.fixed_risk_dollars = float(self.get_parameter("fixed_risk_dollars", str(self.FIXED_RISK_DOLLARS)))
        self.trail_to_tenkan_first = self.get_parameter("trail_to_tenkan_first", str(self.TRAIL_TO_TENKAN_FIRST)).lower() == "true"
        self.never_lower_stop = self.get_parameter("never_lower_stop", str(self.NEVER_LOWER_STOP)).lower() == "true"
        self.stop_on_close_only = self.get_parameter("stop_on_close_only", str(self.STOP_ON_CLOSE_ONLY)).lower() == "true"
        self.add_at_cloud_break_pct = float(self.get_parameter("add_at_cloud_break_pct", str(self.ADD_AT_CLOUD_BREAK_PCT)))
        self.max_adds = int(self.get_parameter("max_adds", str(self.MAX_ADDS)))
        self.pyramid_pct = float(self.get_parameter("pyramid_pct", str(self.PYRAMID_PCT)))

        # Entry gates parameters (Item 4: sT10e champion)
        self.resistance_proximity_pct = float(self.get_parameter("resistance_proximity_pct", str(self.RESISTANCE_PROXIMITY_PCT)))
        self.kijun_extension_mult = float(self.get_parameter("kijun_extension_mult", str(self.KIJUN_EXTENSION_MULT)))
        self.min_price = float(self.get_parameter("min_price", str(self.MIN_PRICE)))
        self.min_dollar_volume = float(self.get_parameter("min_dollar_volume", str(self.MIN_DOLLAR_VOLUME)))
        self.skip_if_earnings_days = int(self.get_parameter("skip_if_earnings_days", str(self.SKIP_IF_EARNINGS_DAYS)))
        self.spy_gate_confirm_days = int(self.get_parameter("spy_gate_confirm_days", str(self.SPY_GATE_CONFIRM_DAYS)))
        self.vix_threshold = float(self.get_parameter("vix_threshold", str(self.VIX_THRESHOLD)))
        self.vix_size_multiplier = float(self.get_parameter("vix_size_multiplier", str(self.VIX_SIZE_MULTIPLIER)))

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
        # ATR for stop loss calculation (Item 7)
        atr = self.atr(sym, self.atr_period, MovingAverageType.Wilders)

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
            "atr": atr,
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

    def _get_atr(self, symbol) -> float:
        """Get current ATR value for a symbol."""
        if symbol not in self._indicators:
            return 0.0
        atr = self._indicators[symbol].get("atr")
        if atr is None or not atr.is_ready:
            return 0.0
        return float(atr.current.value)

    def _calculate_initial_stop(self, symbol: Symbol, entry_price: float) -> float:
        """Calculate initial stop price: entry - (ATR × 2.5)."""
        atr = self._get_atr(symbol)
        if atr == 0:
            # Fallback to 10% stop if ATR not ready
            return entry_price * 0.90
        return entry_price - (atr * self.atr_stop_mult_initial)

    def _calculate_trailing_stop(self, symbol: Symbol, current_stop: float) -> float:
        """Calculate trailing stop: max of Kijun-sen and (ATR × 3.0 floor)."""
        if symbol not in self._indicators:
            return current_stop
        
        d_ichi = self._indicators[symbol]["d_ichi"]
        if not d_ichi.is_ready:
            return current_stop
        
        # Get Kijun-sen (26-period mid-price)
        kijun = d_ichi.kijun.current.value
        
        # Get ATR floor
        atr = self._get_atr(symbol)
        price = float(self.securities[symbol].price)
        atr_floor = price - (atr * self.atr_stop_mult_floor) if atr > 0 else price * 0.97
        
        # Trail to higher of Kijun or ATR floor
        new_stop = max(kijun, atr_floor)
        
        # Never lower stop if enabled
        if self.never_lower_stop:
            return max(current_stop, new_stop)
        return new_stop

    def _get_position_size_fixed_risk(self, symbol: Symbol, entry_price: float) -> int:
        """Calculate position size based on $200 fixed risk."""
        atr = self._get_atr(symbol)
        if atr == 0:
            # Default sizing if ATR not available
            target_value = self.portfolio.total_portfolio_value * self.POSITION_PCT
            return int(target_value / entry_price)
        
        # Risk per share = ATR × 2.5 (initial stop distance)
        risk_per_share = atr * self.atr_stop_mult_initial
        if risk_per_share <= 0:
            return 0
        
        # Number of shares = fixed risk / risk per share
        shares = int(self.fixed_risk_dollars / risk_per_share)
        
        # Cap at max position size (10% of portfolio)
        max_position_value = self.portfolio.total_portfolio_value * self.MAX_POSITION_PCT
        max_shares = int(max_position_value / entry_price)
        
        return min(shares, max_shares)

    def _check_cloud_top_break(self, symbol: Symbol) -> bool:
        """Check if price has broken above cloud top for add trigger."""
        vals = self._daily_close_and_kijun_and_cloud_top(symbol)
        if vals is None:
            return False
        close, _, cloud_top = vals
        # Cloud top break = close > cloud_top (strong momentum)
        return close > cloud_top and close > cloud_top * 1.02  # 2% buffer

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

    def _check_min_price_volume(self, symbol: Symbol) -> bool:
        """Check minimum price and dollar volume requirements."""
        price = float(self.securities[symbol].price)
        if price < self.min_price:
            return False
        # Check dollar volume (price × volume)
        # Get today's volume
        hist = self.history(symbol, 1, Resolution.DAILY)
        if hist is not None and not hist.empty:
            if isinstance(hist.index, pd.MultiIndex):
                hist = hist.droplevel(0)
            hist.columns = [c.lower() for c in hist.columns]
            if "volume" in hist.columns:
                volume = hist["volume"].iloc[-1]
                dollar_volume = price * volume
                if dollar_volume < self.min_dollar_volume:
                    return False
        return True

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
        try:
            vix_symbol = self.symbol("VIX")
            vix_price = float(self.securities[vix_symbol].price)
            if vix_price > self.vix_threshold:
                return self.vix_size_multiplier  # 50% size
        except:
            pass
        return 1.0  # Normal size

    def _check_all_entry_gates(self, symbol: Symbol) -> tuple[bool, str]:
        """Check all entry gates. Returns (passed, reason_if_failed)."""
        # SPY gate must be open
        if not self._spy_gate_open:
            return False, "SPY_GATE_CLOSED"
        # Resistance proximity
        if self._check_resistance_proximity(symbol):
            return False, "RESISTANCE_PROXIMITY"
        # Kijun extension
        if self._check_kijun_extension(symbol):
            return False, "KIJUN_EXTENSION"
        # Chikou check
        if not self._check_chikou(symbol):
            return False, "CHIKOU_FAIL"
        # Min price/volume
        if not self._check_min_price_volume(symbol):
            return False, "MIN_PRICE_VOLUME"
        # Earnings skip
        if not self._check_earnings(symbol):
            return False, "EARNINGS_SKIP"
        return True, ""

    def _update_and_check_stop(self, symbol: Symbol, holding) -> tuple[bool, str]:
        """Update trailing stop and check if stop triggered. Returns (should_exit, reason)."""
        if symbol not in self._position_meta:
            return False, ""
        
        meta = self._position_meta[symbol]
        current_stop = meta.get("stop_price", 0)
        if current_stop == 0:
            return False, ""
        
        close = float(self.securities[symbol].price)
        
        # Update trailing stop (if price moved in our favor)
        new_stop = self._calculate_trailing_stop(symbol, current_stop)
        if new_stop > current_stop:
            self._position_meta[symbol]["stop_price"] = new_stop
        
        # Check if stop triggered
        if close < current_stop:
            return True, f"ATR_STOP|stop={current_stop:.2f}|close={close:.2f}"
        
        # Check cloud break add opportunity
        if self._check_cloud_top_break(symbol):
            adds_count = meta.get("adds_count", 0)
            if adds_count < self.max_adds:
                return False, "ADD_TRIGGER"
        
        return False, ""

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
            
            # Update trailing stop and check exit
            should_exit, exit_reason = self._update_and_check_stop(symbol, holding)
            if should_exit:
                self.market_on_open_order(symbol, -holding.quantity)
                self.log(f"EXIT|{date_str}|{symbol.value}|{exit_reason}")
                # Clear position metadata
                if symbol in self._position_meta:
                    del self._position_meta[symbol]
                continue
            
            # Check for cloud top break add
            if exit_reason == "ADD_TRIGGER":
                meta = self._position_meta[symbol]
                original_qty = meta.get("original_quantity", holding.quantity)
                add_qty = int(original_qty * self.add_at_cloud_break_pct)
                if add_qty > 0:
                    self.market_on_open_order(symbol, add_qty)
                    self._position_meta[symbol]["adds_count"] = meta.get("adds_count", 0) + 1
                    self.log(f"ADD|{date_str}|{symbol.value}|qty={add_qty}|cloud_break")
            
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
        slots = self.MAX_POSITIONS - open_count
        if slots <= 0:
            return

        # Score all symbols for rotation decisions
        all_scores: dict[Symbol, int] = {}
        for ticker in self.UNIVERSE:
            symbol = self.symbol(ticker)
            
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
            
            result = score_symbol(self, symbol)
            if result is None or result["score"] < self.MIN_SCORE:
                continue
            all_scores[symbol] = result["score"]

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

        for symbol, score in candidates[:slots]:
            price = float(self.securities[symbol].price)
            if price <= 0:
                continue
            
            # Check entry gates (Item 4: sT10e champion)
            gates_passed, gate_reason = self._check_all_entry_gates(symbol)
            if not gates_passed:
                self.log(f"GATE_BLOCK|{date_str}|{symbol.value}|reason={gate_reason}|score={score}")
                continue
            
            # Calculate position size using fixed risk (Item 7)
            quantity = self._get_position_size_fixed_risk(symbol, price)
            if quantity <= 0:
                continue
            
            # Apply VIX size multiplier (Item 4: sT10e champion)
            vix_multiplier = self._get_vix_size_multiplier()
            quantity = int(quantity * vix_multiplier)
            if quantity <= 0:
                continue
            
            # Calculate initial ATR stop (Item 7)
            initial_stop = self._calculate_initial_stop(symbol, price)
            
            # Buy-stop fill: place stop order 0.75% above close (Item 3)
            entry_stop = price * (1 + self.buy_stop_pct)
            self.stop_market_order(symbol, quantity, entry_stop)
            
            # Track position entry metadata with ATR stop info (Item 7)
            self._position_meta[symbol] = {
                "entry_date": self.time,
                "entry_price": price,
                "stop_price": initial_stop,
                "original_quantity": quantity,
                "adds_count": 0,
                "highest_price": price,  # For trailing stop calculation
            }
            
            atr_val = self._get_atr(symbol)
            vix_tag = f"|vix_mult={vix_multiplier:.2f}" if vix_multiplier < 1.0 else ""
            self.log(f"ENTRY|{date_str}|{symbol.value}|score={score}/8|qty={quantity}|stop={entry_stop:.2f}|mark={price:.2f}|atr={atr_val:.2f}|init_stop={initial_stop:.2f}{vix_tag}")

        self.log(f"REBALANCE|{date_str}|open={open_count}|new_entries={min(len(candidates), slots)}")
