from __future__ import annotations
"""
IRPrecisionFalcon — ML-based QQQ-relative strategy.

Universe: MAG8 (AAPL, AMZN, GOOGL, META, MSFT, NVDA, TSLA, AMD) + QQQ default.
Signal: RandomForest on 2 features (10d return, 10d active return vs QQQ).
Label: stock beats QQQ over next 5 days.
Gate: prob > 0.70 → 98% in predicted winner; else hold QQQ.
Retrain: monthly on 500d history.
"""

from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from AlgorithmImports import *  # noqa: F401,F403


class IRPrecisionFalcon(QCAlgorithm):

    TICKERS = ["AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA", "TSLA", "AMD"]
    POSITION_PCT: float = 0.98
    PROB_GATE: float = 0.70
    TRAIN_DAYS: int = 500
    FEATURE_WIN: int = 10
    LABEL_HOR: int = 5

    def initialize(self) -> None:
        self.set_time_zone("America/New_York")
        sy = int(self.get_parameter("start_year", "2025"))
        sm = int(self.get_parameter("start_month", "1"))
        sd = int(self.get_parameter("start_day", "1"))
        ey = int(self.get_parameter("end_year", "2025"))
        em = int(self.get_parameter("end_month", "12"))
        ed = int(self.get_parameter("end_day", "31"))
        self.set_start_date(sy, sm, sd)
        self.set_end_date(ey, em, ed)
        self.set_cash(100_000)
        self.set_benchmark("QQQ")

        warmup_days = self.TRAIN_DAYS + self.LABEL_HOR + 20
        self.set_warmup(timedelta(days=warmup_days))

        self.universe_settings.resolution = Resolution.DAILY
        self._securities: dict = {}
        self._qqq = self.add_equity("QQQ", Resolution.DAILY).symbol
        for t in self.TICKERS:
            sym = self.add_equity(t, Resolution.DAILY).symbol
            self._securities[t] = sym

        self._model: RandomForestClassifier | None = None
        self._current_target: str = "QQQ"

        self.schedule.on(
            self.date_rules.month_start(1),
            self.time_rules.after_market_open("QQQ", 30),
            self._monthly_retrain,
        )
        self.schedule.on(
            self.date_rules.every_day("QQQ"),
            self.time_rules.after_market_open("QQQ", 60),
            self._rebalance,
        )

    def _fetch_history(self, lookback: int) -> pd.DataFrame | None:
        all_syms = [self._qqq] + list(self._securities.values())
        hist = self.history(all_syms, lookback, Resolution.DAILY)
        if hist is None or hist.empty:
            return None
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist["close"].unstack(level=0)
        else:
            hist = hist[["close"]]
        hist.columns = [str(c).split(" ")[0].upper() if " " in str(c) else str(c).upper() for c in hist.columns]
        return hist.dropna()

    def _build_features_labels(self, closes: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, list[str]]:
        tickers = [t for t in self.TICKERS if t in closes.columns]
        X_rows, y_rows = [], []
        dates = closes.index

        for i in range(self.FEATURE_WIN, len(closes) - self.LABEL_HOR):
            qqq_10d = closes["QQQ"].iloc[i] / closes["QQQ"].iloc[i - self.FEATURE_WIN] - 1
            qqq_fwd = closes["QQQ"].iloc[i + self.LABEL_HOR] / closes["QQQ"].iloc[i] - 1
            row_X, row_y = [], []
            for t in tickers:
                ret_10d = closes[t].iloc[i] / closes[t].iloc[i - self.FEATURE_WIN] - 1
                active_10d = ret_10d - qqq_10d
                row_X.extend([ret_10d, active_10d])
                fwd = closes[t].iloc[i + self.LABEL_HOR] / closes[t].iloc[i] - 1
                row_y.append(1 if fwd > qqq_fwd else 0)
            X_rows.append(row_X)
            y_rows.append(row_y)

        feature_names = [f"{t}_{f}" for t in tickers for f in ["ret10d", "active10d"]]
        return np.array(X_rows), np.array(y_rows), tickers

    def _monthly_retrain(self) -> None:
        if self.is_warming_up:
            return
        closes = self._fetch_history(self.TRAIN_DAYS + self.LABEL_HOR + 5)
        if closes is None or len(closes) < self.TRAIN_DAYS // 2:
            self.log("RETRAIN|SKIP|insufficient_history")
            return

        X, Y, tickers = self._build_features_labels(closes)
        if len(X) < 50:
            self.log("RETRAIN|SKIP|insufficient_rows")
            return

        self._models: dict[str, RandomForestClassifier] = {}
        for i, ticker in enumerate(tickers):
            y_col = Y[:, i]
            if y_col.sum() < 5 or (len(y_col) - y_col.sum()) < 5:
                continue
            clf = RandomForestClassifier(n_estimators=100, max_depth=4, random_state=42, n_jobs=1)
            clf.fit(X, y_col)
            self._models[ticker] = clf

        self.log(f"RETRAIN|{self.time.strftime('%Y-%m-%d')}|rows={len(X)}|models={len(self._models)}")

    def _get_signal(self) -> str:
        if not hasattr(self, "_models") or not self._models:
            return "QQQ"
        closes = self._fetch_history(self.FEATURE_WIN + 5)
        if closes is None or len(closes) < self.FEATURE_WIN + 1:
            return "QQQ"

        qqq_10d = closes["QQQ"].iloc[-1] / closes["QQQ"].iloc[-1 - self.FEATURE_WIN] - 1
        best_ticker, best_prob = "QQQ", 0.0

        for ticker, clf in self._models.items():
            if ticker not in closes.columns:
                continue
            ret_10d = closes[ticker].iloc[-1] / closes[ticker].iloc[-1 - self.FEATURE_WIN] - 1
            active_10d = ret_10d - qqq_10d

            # Build full feature vector (one row, all tickers)
            tickers_ordered = list(self._models.keys())
            features = []
            for t in tickers_ordered:
                if t in closes.columns:
                    r = closes[t].iloc[-1] / closes[t].iloc[-1 - self.FEATURE_WIN] - 1
                    a = r - qqq_10d
                else:
                    r, a = 0.0, 0.0
                features.extend([r, a])

            try:
                prob = clf.predict_proba([features])[0][1]
            except Exception:
                continue
            if prob > best_prob:
                best_prob, best_ticker = prob, ticker

        if best_prob >= self.PROB_GATE:
            self.log(f"SIGNAL|{self.time.strftime('%Y-%m-%d')}|winner={best_ticker}|prob={best_prob:.3f}")
            return best_ticker
        return "QQQ"

    def _rebalance(self) -> None:
        if self.is_warming_up:
            return
        target = self._get_signal()
        date_str = self.time.strftime("%Y-%m-%d")
        target_sym = self._qqq if target == "QQQ" else self._securities.get(target)
        if target_sym is None:
            return

        current_holdings = {
            str(sym).split(" ")[0].upper(): h
            for sym, h in self.portfolio.items()
            if h.invested
        }

        if self._current_target == target and target in current_holdings:
            return

        for sym in list(self.portfolio.keys()):
            if self.portfolio[sym].invested:
                self.set_holdings(sym, 0)

        self.set_holdings(target_sym, self.POSITION_PCT)
        self._current_target = target
        self.log(f"HOLD|{date_str}|{target}|prob_gate={self.PROB_GATE}")
