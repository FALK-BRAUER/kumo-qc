from __future__ import annotations
"""
BCT performance backtest — parameterized date range.

Replicates live_bct.py trading logic for historical performance measurement:
≥7/8 BCT signal entry, 10% position sizing, Kijun stop exit, max 10 positions.

Date range set via QC parameters (start_year/month/day, end_year/month/day).
Defaults: 2025-01-01 to 2025-12-31 (FY2025).
Use scripts/run_windows.py to launch all 6-window + FY2025 backtests.

Uses QC native IchimokuKinkoHyo: daily registered via self.ichimoku(),
weekly via TradeBarConsolidator(Calendar.WEEKLY). Custom Wilder period-9
ADX retained in score_symbol_native() — QC native ADX is period 14.

Local mode: when LEAN data dir is detected, loads polygon_universe_equity200_fy2025.json
(326 unique tickers, top-200 S&P equity by dollar volume) instead of Morningstar CoarseFundamental filter.
"""

import json
from datetime import timedelta
from pathlib import Path

from AlgorithmImports import *  # noqa: F401,F403

from bct_signal import score_symbol_native
from universe_filter import BCTUniverseFilter


class BCTPerformanceAlgorithm(QCAlgorithm):

    MAX_POSITIONS: int = 10
    POSITION_PCT: float = 0.10
    MIN_SCORE: int = 7
    # Exit condition flags — False = reference bct‑perf‑2020‑2026 (daily Kijun only)
    ENABLE_CLOUD_BREACH_EXIT: bool = False
    ENABLE_WEEKLY_KIJUN_EXIT: bool = False

    BLOCKED_SECTORS: frozenset[str] = frozenset({"Financial Services"})
    # Sector map sourced from kumo-market.db universe table (317/326 equity-200 tickers covered)
    SECTOR_MAP: dict[str, str] = {
        "AAL": "Industrials",
        "AAPL": "Technology",
        "ABBV": "Healthcare",
        "ABNB": "Consumer Cyclical",
        "ABT": "Healthcare",
        "ACN": "Technology",
        "ADBE": "Technology",
        "ADI": "Technology",
        "ADP": "Technology",
        "ADSK": "Technology",
        "AEP": "Utilities",
        "AIG": "Financial Services",
        "AJG": "Financial Services",
        "ALB": "Basic Materials",
        "ALL": "Financial Services",
        "AMAT": "Technology",
        "AMCR": "Consumer Cyclical",
        "AMD": "Technology",
        "AMGN": "Healthcare",
        "AMT": "Real Estate",
        "AMZN": "Consumer Cyclical",
        "ANET": "Technology",
        "AON": "Financial Services",
        "APD": "Basic Materials",
        "APH": "Technology",
        "APO": "Financial Services",
        "APP": "Communication Services",
        "ARES": "Financial Services",
        "AVGO": "Technology",
        "AXON": "Industrials",
        "AXP": "Financial Services",
        "AZO": "Consumer Cyclical",
        "BA": "Industrials",
        "BAC": "Financial Services",
        "BDX": "Healthcare",
        "BK": "Financial Services",
        "BKNG": "Consumer Cyclical",
        "BKR": "Energy",
        "BLK": "Financial Services",
        "BMY": "Healthcare",
        "BRO": "Financial Services",
        "BSX": "Healthcare",
        "BX": "Financial Services",
        "C": "Financial Services",
        "CAH": "Healthcare",
        "CARR": "Industrials",
        "CAT": "Industrials",
        "CAVA": "Consumer Cyclical",
        "CB": "Financial Services",
        "CCI": "Real Estate",
        "CCL": "Consumer Cyclical",
        "CDNS": "Technology",
        "CEG": "Utilities",
        "CELH": "Consumer Defensive",
        "CHTR": "Communication Services",
        "CHWY": "Consumer Cyclical",
        "CI": "Healthcare",
        "CIEN": "Technology",
        "CL": "Consumer Defensive",
        "CLF": "Basic Materials",
        "CMCSA": "Communication Services",
        "CME": "Financial Services",
        "CMG": "Consumer Cyclical",
        "CMI": "Industrials",
        "CNC": "Healthcare",
        "COF": "Financial Services",
        "COHR": "Technology",
        "COIN": "Financial Services",
        "COP": "Energy",
        "COR": "Healthcare",
        "COST": "Consumer Defensive",
        "CPRT": "Industrials",
        "CRH": "Basic Materials",
        "CRM": "Technology",
        "CRWD": "Technology",
        "CSCO": "Technology",
        "CSX": "Industrials",
        "CTAS": "Industrials",
        "CVNA": "Consumer Cyclical",
        "CVS": "Healthcare",
        "CVX": "Energy",
        "DAL": "Industrials",
        "DASH": "Consumer Cyclical",
        "DDOG": "Technology",
        "DE": "Industrials",
        "DECK": "Consumer Cyclical",
        "DELL": "Technology",
        "DG": "Consumer Defensive",
        "DHI": "Consumer Cyclical",
        "DHR": "Healthcare",
        "DIS": "Communication Services",
        "DKS": "Consumer Cyclical",
        "DLR": "Real Estate",
        "DLTR": "Consumer Defensive",
        "DOCU": "Technology",
        "DOW": "Basic Materials",
        "DUK": "Utilities",
        "DUOL": "Technology",
        "DVN": "Energy",
        "DXCM": "Healthcare",
        "EA": "Communication Services",
        "EBAY": "Consumer Cyclical",
        "EIX": "Utilities",
        "ELV": "Healthcare",
        "EME": "Industrials",
        "EMR": "Industrials",
        "ENPH": "Technology",
        "EOG": "Energy",
        "EQIX": "Real Estate",
        "EQT": "Energy",
        "ETN": "Industrials",
        "ETR": "Utilities",
        "ETSY": "Consumer Cyclical",
        "EW": "Healthcare",
        "EXC": "Utilities",
        "EXE": "Energy",
        "EXPE": "Consumer Cyclical",
        "F": "Consumer Cyclical",
        "FANG": "Energy",
        "FCX": "Basic Materials",
        "FDX": "Industrials",
        "FICO": "Technology",
        "FITB": "Financial Services",
        "FIX": "Industrials",
        "FLEX": "Technology",
        "FSLR": "Technology",
        "FTNT": "Technology",
        "GD": "Industrials",
        "GE": "Industrials",
        "GEHC": "Healthcare",
        "GEV": "Industrials",
        "GILD": "Healthcare",
        "GIS": "Consumer Defensive",
        "GLW": "Technology",
        "GM": "Consumer Cyclical",
        "GME": "Consumer Cyclical",
        "GOOG": "Communication Services",
        "GOOGL": "Communication Services",
        "GS": "Financial Services",
        "HBAN": "Financial Services",
        "HCA": "Healthcare",
        "HD": "Consumer Cyclical",
        "HLT": "Consumer Cyclical",
        "HON": "Industrials",
        "HOOD": "Financial Services",
        "HPE": "Technology",
        "HSY": "Consumer Defensive",
        "HUM": "Healthcare",
        "HWM": "Industrials",
        "IBKR": "Financial Services",
        "IBM": "Technology",
        "ICE": "Financial Services",
        "IDXX": "Healthcare",
        "INTC": "Technology",
        "INTU": "Technology",
        "IP": "Consumer Cyclical",
        "IQV": "Healthcare",
        "ISRG": "Healthcare",
        "IT": "Technology",
        "JBL": "Technology",
        "JCI": "Industrials",
        "JNJ": "Healthcare",
        "JPM": "Financial Services",
        "KDP": "Consumer Defensive",
        "KEY": "Financial Services",
        "KHC": "Consumer Defensive",
        "KKR": "Financial Services",
        "KLAC": "Technology",
        "KMB": "Consumer Defensive",
        "KMI": "Energy",
        "KO": "Consumer Defensive",
        "KR": "Consumer Defensive",
        "KVUE": "Consumer Defensive",
        "LEN": "Consumer Cyclical",
        "LHX": "Industrials",
        "LII": "Industrials",
        "LIN": "Basic Materials",
        "LITE": "Technology",
        "LLY": "Healthcare",
        "LMT": "Industrials",
        "LOW": "Consumer Cyclical",
        "LRCX": "Technology",
        "LULU": "Consumer Cyclical",
        "LUV": "Industrials",
        "LYFT": "Technology",
        "LYV": "Communication Services",
        "MA": "Financial Services",
        "MAR": "Consumer Cyclical",
        "MCD": "Consumer Cyclical",
        "MCHP": "Technology",
        "MCK": "Healthcare",
        "MCO": "Financial Services",
        "MDLZ": "Consumer Defensive",
        "MDT": "Healthcare",
        "META": "Communication Services",
        "MMM": "Industrials",
        "MO": "Consumer Defensive",
        "MOH": "Healthcare",
        "MP": "Basic Materials",
        "MPC": "Energy",
        "MPWR": "Technology",
        "MRK": "Healthcare",
        "MRNA": "Healthcare",
        "MS": "Financial Services",
        "MSCI": "Financial Services",
        "MSFT": "Technology",
        "MSI": "Technology",
        "MU": "Technology",
        "NCLH": "Consumer Cyclical",
        "NEE": "Utilities",
        "NEM": "Basic Materials",
        "NFLX": "Communication Services",
        "NKE": "Consumer Cyclical",
        "NOC": "Industrials",
        "NOW": "Technology",
        "NRG": "Utilities",
        "NSC": "Industrials",
        "NTNX": "Technology",
        "NUE": "Basic Materials",
        "NVDA": "Technology",
        "NXPI": "Technology",
        "OKE": "Energy",
        "OKTA": "Technology",
        "OMC": "Communication Services",
        "ON": "Technology",
        "ORCL": "Technology",
        "ORLY": "Consumer Cyclical",
        "OXY": "Energy",
        "PANW": "Technology",
        "PATH": "Technology",
        "PAYX": "Technology",
        "PCG": "Utilities",
        "PEP": "Consumer Defensive",
        "PFE": "Healthcare",
        "PG": "Consumer Defensive",
        "PGR": "Financial Services",
        "PH": "Industrials",
        "PINS": "Communication Services",
        "PLD": "Real Estate",
        "PLTR": "Technology",
        "PM": "Consumer Defensive",
        "PNC": "Financial Services",
        "PSX": "Energy",
        "PWR": "Industrials",
        "PYPL": "Financial Services",
        "QCOM": "Technology",
        "RCL": "Consumer Cyclical",
        "REGN": "Healthcare",
        "RF": "Financial Services",
        "RH": "Consumer Cyclical",
        "ROK": "Industrials",
        "ROP": "Technology",
        "ROST": "Consumer Cyclical",
        "RTX": "Industrials",
        "SATS": "Communication Services",
        "SBUX": "Consumer Cyclical",
        "SCHW": "Financial Services",
        "SFM": "Consumer Defensive",
        "SHW": "Basic Materials",
        "SLB": "Energy",
        "SMCI": "Technology",
        "SNDK": "Technology",
        "SNPS": "Technology",
        "SO": "Utilities",
        "SPGI": "Financial Services",
        "SRE": "Utilities",
        "STX": "Technology",
        "STZ": "Consumer Defensive",
        "SYK": "Healthcare",
        "T": "Communication Services",
        "TDG": "Industrials",
        "TEL": "Technology",
        "TER": "Technology",
        "TFC": "Financial Services",
        "TGT": "Consumer Defensive",
        "TJX": "Consumer Cyclical",
        "TLN": "Utilities",
        "TMO": "Healthcare",
        "TMUS": "Communication Services",
        "TPR": "Consumer Cyclical",
        "TRGP": "Energy",
        "TRU": "Financial Services",
        "TRV": "Financial Services",
        "TSLA": "Consumer Cyclical",
        "TT": "Industrials",
        "TTD": "Communication Services",
        "TTWO": "Communication Services",
        "TWLO": "Technology",
        "TXN": "Technology",
        "UAL": "Industrials",
        "UBER": "Technology",
        "ULTA": "Consumer Cyclical",
        "UNH": "Healthcare",
        "UNP": "Industrials",
        "UPS": "Industrials",
        "URI": "Industrials",
        "USB": "Financial Services",
        "V": "Financial Services",
        "VEEV": "Healthcare",
        "VLO": "Energy",
        "VRT": "Industrials",
        "VRTX": "Healthcare",
        "VST": "Utilities",
        "VZ": "Communication Services",
        "WBD": "Communication Services",
        "WDAY": "Technology",
        "WDC": "Technology",
        "WELL": "Real Estate",
        "WFC": "Financial Services",
        "WM": "Industrials",
        "WMB": "Energy",
        "WMT": "Consumer Defensive",
        "WSM": "Consumer Cyclical",
        "XEL": "Utilities",
        "XOM": "Energy",
        "XYZ": "Technology",
        "ZTS": "Healthcare",
    }

    @staticmethod
    def _find_local_data_dir() -> Path | None:
        candidates = [
            Path("/Lean/Data/equity/usa/daily"),
            Path("/Data/equity/usa/daily"),
            Path(__file__).parent.parent.parent / "data/equity/usa/daily",
        ]
        return next((d for d in candidates if d.exists()), None)

    @staticmethod
    def _load_polygon_universe() -> dict | None:
        candidates = [
            Path(__file__).parent / "polygon_universe_equity200_fy2025.json",
            Path("/Lean/Data/polygon_universe_equity200_fy2025.json"),
        ]
        for p in candidates:
            if p.exists():
                with open(p) as f:
                    return json.load(f)
        return None

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

        # Exit condition parameter overrides
        self.cloud_exit_enabled = self.get_parameter("cloud_exit", str(self.ENABLE_CLOUD_BREACH_EXIT)).lower() == "true"
        self.weekly_kijun_exit_enabled = self.get_parameter("weekly_kijun_exit", str(self.ENABLE_WEEKLY_KIJUN_EXIT)).lower() == "true"
        self.sector_filter_enabled = self.get_parameter("sector_filter_enabled", "false").lower() == "true"

        self.universe_settings.resolution = Resolution.DAILY
        self._active: set = set()
        self._indicators: dict = {}
        self._polygon_universe: dict | None = None

        if self._find_local_data_dir() is not None:
            # Local: static universe from Polygon daily snapshot (867 unique tickers, FY2025)
            poly = self._load_polygon_universe()
            if poly is not None:
                self._polygon_universe = poly
                all_tickers: set[str] = set()
                for tickers in poly.values():
                    all_tickers.update(tickers)
                self.log(f"LOCAL_UNIVERSE|polygon_equity|unique_tickers={len(all_tickers)}")
                for ticker in sorted(all_tickers):
                    try:
                        self.add_equity(ticker, Resolution.DAILY)
                    except Exception:
                        pass
            else:
                # Fallback: ETFs only (no polygon JSON found)
                self.log("LOCAL_UNIVERSE|fallback_etf_only|polygon_json_not_found")
                etfs = ["QQQ", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC", "SPY"]
                for etf in etfs:
                    self.add_equity(etf, Resolution.DAILY)
        else:
            # Cloud: dynamic universe via Morningstar CoarseFundamental + ETFs
            etfs = ["QQQ", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]
            for etf in etfs:
                self.add_equity(etf, Resolution.DAILY)
            self._filter = BCTUniverseFilter()
            self.add_universe(
                self._filter.coarse_selection,
                self._filter.fine_selection,
            )

        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(16, 5),
            self._rebalance,
        )

    def on_securities_changed(self, changes: SecurityChanges) -> None:
        for s in changes.added_securities:
            sym = s.symbol
            self._active.add(sym)
            if sym not in self._indicators:
                self._register_indicators(sym)
        for s in changes.removed_securities:
            sym = s.symbol
            self._active.discard(sym)
            if sym in self._indicators:
                self.subscription_manager.remove_consolidator(
                    sym, self._indicators[sym]["consolidator"]
                )
                del self._indicators[sym]

    def _register_indicators(self, sym) -> None:
        d_ichi = self.ichimoku(sym, 9, 26, 26, 52, 26, 26)
        sma200 = self.sma(sym, 200)

        w_ichi = IchimokuKinkoHyo(9, 26, 26, 52, 26, 26)
        w_close = RollingWindow[float](28)

        consolidator = TradeBarConsolidator(Calendar.WEEKLY)

        def _on_weekly(_, bar: TradeBar) -> None:
            w_ichi.update(bar)
            w_close.add(bar.close)

        consolidator.data_consolidated += _on_weekly
        self.subscription_manager.add_consolidator(sym, consolidator)

        # With 750-day warmup, consolidator receives sufficient weekly bars automatically.
        # Skip manual seed during warmup to avoid 326× history() calls at init time.
        if not self.is_warming_up:
            self._seed_weekly(sym, w_ichi, w_close)

        # === Experiment D: Volume surge confirmation ===
        # 20-day SMA of volume for entry-day surge check
        vol_sma = SimpleMovingAverage(20)
        self.register_indicator(sym, vol_sma, Resolution.DAILY, Field.Volume)
        # === END Experiment D ===

        self._indicators[sym] = {
            "d_ichi": d_ichi,
            "w_ichi": w_ichi,
            "w_close": w_close,
            "sma200": sma200,
            "consolidator": consolidator,
            "vol_sma": vol_sma,
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

    def _daily_close_and_kijun_and_cloud_top(self, symbol) -> tuple[float, float, float] | None:
        if symbol not in self._indicators:
            return None
        d_ichi = self._indicators[symbol]["d_ichi"]
        if not d_ichi.is_ready:
            return None
        
        close = float(self.securities[symbol].price)
        kijun = d_ichi.kijun.current.value
        
        # Access the displaced Senkou Span A/B values directly
        senkou_a = d_ichi.senkou_a.current.value
        senkou_b = d_ichi.senkou_b.current.value
        
        cloud_top = max(senkou_a, senkou_b)
        
        return close, kijun, cloud_top

    def _has_open_orders(self, symbol) -> bool:
        return bool(self.transactions.get_open_orders(symbol))

    def _rebalance(self) -> None:
        if self.is_warming_up:
            return
        date_str = self.time.strftime("%Y-%m-%d")

        for symbol, holding in list(self.portfolio.items()):
            if not holding.invested or self._has_open_orders(symbol):
                continue
            vals = self._daily_close_and_kijun_and_cloud_top(symbol)
            if vals is None:
                continue
            close, kijun, cloud_top = vals
            
            w_ichi = self._indicators[symbol]["w_ichi"]
            w_kijun = w_ichi.kijun.current.value if w_ichi.is_ready else None

            if close < kijun:
                self.market_on_open_order(symbol, -holding.quantity)
                self.log(f"STOP|{date_str}|{symbol.value}|close={close:.2f}|kijun={kijun:.2f}")
            elif self.cloud_exit_enabled and close < cloud_top:
                self.market_on_open_order(symbol, -holding.quantity)
                self.log(f"CLOUD_EXIT|{date_str}|{symbol.value}|close={close:.2f}|cloud_top={cloud_top:.2f}")
            elif self.weekly_kijun_exit_enabled and w_kijun is not None and close < w_kijun:
                self.market_on_open_order(symbol, -holding.quantity)
                self.log(f"WEEKLY_KIJUN_STOP|{date_str}|{symbol.value}|close={close:.2f}|w_kijun={w_kijun:.2f}")

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

        # When running locally with polygon universe, restrict candidates to today's snapshot
        today_poly: set[str] | None = None
        if self._polygon_universe is not None:
            today_poly = set(self._polygon_universe.get(date_str, []))

        candidates: list[tuple] = []
        for symbol in sorted(self._active):
            if today_poly is not None and symbol.value not in today_poly:
                continue
            if self.portfolio[symbol].invested:
                continue
            ind = self._indicators.get(symbol)
            if ind is None:
                continue
            # === PRE-FILTER: skip symbols that cannot reach MIN_SCORE=7 ===
            sma200_ind = ind.get("sma200")
            d_ichi_ind = ind.get("d_ichi")
            if (sma200_ind and sma200_ind.is_ready and d_ichi_ind and d_ichi_ind.is_ready):
                price = float(self.securities[symbol].price)
                if price <= 0:
                    continue
                # If below SMA200, condition 8 fails → max score 6 → skip (MIN_SCORE=7)
                if price < sma200_ind.current.value:
                    continue
                # If below daily cloud, condition 5 fails → max score 6 → skip
                cloud_top = max(d_ichi_ind.senkou_a.current.value, d_ichi_ind.senkou_b.current.value)
                if price < cloud_top:
                    continue
            # === END PRE-FILTER ===
            result = score_symbol_native(self, symbol, ind)
            if result is None or result["score"] < self.MIN_SCORE:
                continue
            if self.sector_filter_enabled:
                sector = self.SECTOR_MAP.get(symbol.value)
                if sector in self.BLOCKED_SECTORS:
                    self.log(f"SECTOR_BLOCK|{date_str}|{symbol.value}|sector={sector}")
                    continue
            # === Experiment C: Cloud thickness gate (1.5% minimum) ===
            # Thin clouds indicate weak trend conviction — skip entry
            price = float(self.securities[symbol].price)
            if price > 0 and d_ichi_ind and d_ichi_ind.is_ready:
                senkou_a = d_ichi_ind.senkou_a.current.value
                senkou_b = d_ichi_ind.senkou_b.current.value
                cloud_thickness = abs(senkou_a - senkou_b) / price
                if cloud_thickness < 0.015:  # 1.5% minimum thickness
                    self.log(f"THIN_CLOUD|{date_str}|{symbol.value}|thickness={cloud_thickness:.3f}|price={price:.2f}")
                    continue  # Skip thin cloud candidates
            # === END CLOUD THICKNESS GATE ===
            # === Experiment D: Volume surge confirmation ===
            # Require entry-day volume >= 1.2x 20-day average volume
            vol_sma = ind.get("vol_sma")
            if vol_sma is not None and vol_sma.is_ready:
                current_volume = float(self.securities[symbol].volume)
                avg_volume = float(vol_sma.current.value)
                if avg_volume > 0 and current_volume < avg_volume * 1.2:
                    self.log(f"LOW_VOLUME|{date_str}|{symbol.value}|vol={current_volume:,.0f}|avg20={avg_volume:,.0f}|ratio={current_volume/avg_volume:.2f}")
                    continue  # Skip low-volume candidates
            # === END Experiment D ===
            candidates.append((symbol, result["score"]))

        candidates.sort(key=lambda x: x[1], reverse=True)
        for symbol, score in candidates[:slots]:
            price = self.securities[symbol].price
            if price <= 0:
                continue
            target_value = self.portfolio.total_portfolio_value * self.POSITION_PCT
            quantity = int(target_value / price)
            if quantity <= 0:
                continue
            self.market_on_open_order(symbol, quantity)
            self.log(f"ENTRY|{date_str}|{symbol.value}|score={score}/8|qty={quantity}|price~{price:.2f}")

        self.log(f"REBALANCE|{date_str}|open={open_count}|new_entries={min(len(candidates), slots)}")
