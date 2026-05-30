"""
GH #25 Phase 5: Intraday QC Implementation — Minute Bars + Tenkan Confirmation + Stop Market

This module extends the BCT minimal algorithm with intraday execution capabilities:
- Stop market orders for immediate exit execution
- Tenkan confirmation for entry timing
- Mid-day rebalance for stop updates and deferred entries

Integration: Import and inherit from BCTMinimalAlgorithmIntraday instead of BCTMinimalAlgorithm
"""

from __future__ import annotations
from datetime import timedelta
from typing import Optional

from AlgorithmImports import *
from QuantConnect.Indicators import AverageTrueRange, MovingAverageType

# Import the base algorithm - will be at bottom of main.py
# from main import BCTMinimalAlgorithm


class BCTIntradayMixin:
    """
    Mixin class adding intraday execution features to BCTMinimalAlgorithm.
    
    Features:
    1. Stop market orders for exits (immediate execution vs next open)
    2. Tenkan confirmation for entry timing (intraday momentum check)
    3. Mid-day rebalance (11:00 AM) for stop updates
    """
    
    # GH #25: Intraday parameters
    INTRADAY_ENABLED: bool = True  # Master switch for intraday features
    TENKAN_CONFIRMATION: bool = True  # Require Tenkan confirmation for entries
    TENKAN_TOLERANCE_PCT: float = 0.005  # 0.5% tolerance above Tenkan
    MID_DAY_REBALANCE_HOUR: int = 11  # 11:00 AM ET
    MID_DAY_REBALANCE_MIN: int = 0
    MAX_DEFERRED_ENTRIES: int = 5  # Max symbols waiting for Tenkan confirmation
    
    def _initialize_intraday(self) -> None:
        """Initialize intraday-specific settings. Called from Initialize()."""
        if not self.INTRADAY_ENABLED:
            return
        
        # Track deferred entries (waiting for Tenkan confirmation)
        self._deferred_entries: dict[Symbol, dict] = {}  # symbol -> entry_params
        
        # Track stop market orders
        # Already in _position_meta: stop_market_order_id
        
        # Subscribe to minute data for active symbols (positions + top candidates)
        # This is done dynamically in _rebalance() to avoid over-subscription
        
        # Add mid-day rebalance schedule
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(self.MID_DAY_REBALANCE_HOUR, self.MID_DAY_REBALANCE_MIN),
            self._intraday_rebalance,
        )
        
        self.log(f"INTRADAY_INIT|enabled={self.INTRADAY_ENABLED}|tenkan={self.TENKAN_CONFIRMATION}")
    
    def _tenkan_confirmed(self, symbol: Symbol) -> bool:
        """
        Intraday confirmation: current price > minute Tenkan-sen (9-period midpoint).
        
        Per GH #25 design spec: Wait for price above Tenkan before entering.
        This provides intraday momentum confirmation beyond daily signals.
        
        Args:
            symbol: Symbol to check
            
        Returns:
            True if confirmed (price > Tenkan or data insufficient - permissive)
            False if price below Tenkan (defer entry)
        """
        if not self.TENKAN_CONFIRMATION:
            return True  # Bypass if disabled
        
        try:
            # Fetch 10 minutes of 1-min bars (enough for 9-period Tenkan)
            hist = self.history(symbol, 10, Resolution.MINUTE)
            if hist is None or len(hist) < 9:
                return True  # Permissive if insufficient data
            
            if isinstance(hist.index, pd.MultiIndex):
                hist = hist.droplevel(0)
            
            # Calculate 9-period Tenkan-sen: (highest high + lowest low) / 2
            highs = hist['high'].values if 'high' in hist.columns else hist['High'].values
            lows = hist['low'].values if 'low' in hist.columns else hist['Low'].values
            
            tenkan_1m = (max(highs[-9:]) + min(lows[-9:])) / 2.0
            current_price = float(self.securities[symbol].price)
            
            # Allow small tolerance above Tenkan
            threshold = tenkan_1m * (1.0 + self.TENKAN_TOLERANCE_PCT)
            confirmed = current_price > threshold
            
            if not confirmed:
                self.log(f"TENKAN_DEFER|{symbol.value}|price={current_price:.2f}|tenkan={tenkan_1m:.2f}|threshold={threshold:.2f}")
            
            return confirmed
            
        except Exception as e:
            # Log error but be permissive to avoid blocking entries on data issues
            self.log(f"TENKAN_ERROR|{symbol.value}|error={str(e)}")
            return True
    
    def _place_stop_market_exit(self, symbol: Symbol, quantity: int, stop_price: float) -> Optional[int]:
        """
        Place a stop market order for exit (sell when price hits stop level).
        
        Args:
            symbol: Symbol to exit
            quantity: Quantity to sell (negative for short, positive for long exit)
            stop_price: Stop price level
            
        Returns:
            Order ID if placed successfully, None otherwise
        """
        try:
            # Cancel any existing stop market order for this symbol
            self._cancel_existing_stop_order(symbol)
            
            # Place new stop market order
            # For long positions, we want to sell when price <= stop_price
            ticket = self.stop_market_order(symbol, -quantity, stop_price)
            
            if ticket and ticket.order_id:
                # Track in position meta
                if symbol in self._position_meta:
                    self._position_meta[symbol]["stop_market_order_id"] = ticket.order_id
                    self._position_meta[symbol]["stop_price"] = stop_price
                
                self.log(f"STOP_MARKET_EXIT|{symbol.value}|qty={quantity}|stop={stop_price:.2f}|order_id={ticket.order_id}")
                return ticket.order_id
            
            return None
            
        except Exception as e:
            self.log(f"STOP_MARKET_ERROR|{symbol.value}|error={str(e)}")
            return None
    
    def _cancel_existing_stop_order(self, symbol: Symbol) -> None:
        """Cancel existing stop market order for symbol if present."""
        if symbol not in self._position_meta:
            return
        
        existing_order_id = self._position_meta[symbol].get("stop_market_order_id")
        if existing_order_id:
            try:
                self.transactions.cancel_order(existing_order_id)
                self.log(f"STOP_CANCEL|{symbol.value}|old_order_id={existing_order_id}")
            except Exception:
                pass  # Order may have already filled or been cancelled
            
            self._position_meta[symbol]["stop_market_order_id"] = None
    
    def _update_stop_market_order(self, symbol: Symbol, new_stop_price: float) -> None:
        """
        Update stop market order to new price level.
        Cancels existing and places new order.
        """
        if symbol not in self._position_meta:
            return
        
        holding = self.portfolio[symbol]
        if not holding.invested:
            return
        
        current_stop = self._position_meta[symbol].get("stop_price")
        
        # Only update if stop has moved up (ratchet behavior)
        if current_stop and new_stop_price <= current_stop:
            return
        
        # Place new stop market order
        self._place_stop_market_exit(symbol, holding.quantity, new_stop_price)
    
    def _intraday_rebalance(self) -> None:
        """
        Mid-day rebalance (11:00 AM ET per schedule).
        
        Responsibilities:
        1. Update stop market orders to current ATR/Kijun levels
        2. Check Tenkan confirmation for deferred entries
        3. Process any intraday earnings surprises (if data available)
        """
        if self.is_warming_up:
            return
        
        date_str = self.time.strftime("%Y-%m-%d %H:%M")
        self.log(f"INTRADAY_REBALANCE|{date_str}")
        
        # 1. Update stop market orders for all positions
        for symbol, holding in self.portfolio.items():
            if not holding.invested:
                continue
            
            # Get current stop price
            stop_price = self._get_position_stop_price(symbol)
            if stop_price:
                self._update_stop_market_order(symbol, stop_price)
        
        # 2. Process deferred entries (waiting for Tenkan confirmation)
        if self._deferred_entries:
            confirmed_entries = []
            
            for symbol, entry_params in list(self._deferred_entries.items()):
                if self._tenkan_confirmed(symbol):
                    confirmed_entries.append((symbol, entry_params))
                else:
                    # Check if deferred too long (max 1 day)
                    deferred_time = entry_params.get("deferred_at")
                    if deferred_time and (self.time - deferred_time).days >= 1:
                        self.log(f"DEFERRED_EXPIRED|{symbol.value}|deferred_at={deferred_time}")
                        confirmed_entries.append((symbol, entry_params))  # Enter anyway
            
            # Execute confirmed entries
            for symbol, entry_params in confirmed_entries:
                self._execute_deferred_entry(symbol, entry_params)
                del self._deferred_entries[symbol]
        
        self.log(f"INTRADAY_REBALANCE_DONE|{date_str}|deferred_remaining={len(self._deferred_entries)}")
    
    def _defer_entry(self, symbol: Symbol, entry_params: dict) -> None:
        """
        Defer entry until Tenkan confirmation.
        
        Args:
            symbol: Symbol to enter
            entry_params: Dict with entry parameters (score, quantity, etc.)
        """
        if len(self._deferred_entries) >= self.MAX_DEFERRED_ENTRIES:
            # Remove oldest deferred entry
            oldest = min(self._deferred_entries.items(), key=lambda x: x[1].get("deferred_at", self.time))
            del self._deferred_entries[oldest[0]]
            self.log(f"DEFERRED_EVICTION|{oldest[0].value}|for={symbol.value}")
        
        entry_params["deferred_at"] = self.time
        self._deferred_entries[symbol] = entry_params
        
        self.log(f"ENTRY_DEFERRED|{symbol.value}|score={entry_params.get('score')}|qty={entry_params.get('quantity')}")
    
    def _execute_deferred_entry(self, symbol: Symbol, entry_params: dict) -> None:
        """Execute a deferred entry order."""
        quantity = entry_params.get("quantity", 0)
        score = entry_params.get("score", 0)
        
        if quantity <= 0:
            return
        
        # Use stop market order for entry (buy stop at close + 0.75%)
        price = float(self.securities[symbol].price)
        stop_price = price * (1.0 + self.buy_stop_pct)
        
        ticket = self.stop_market_order(symbol, quantity, stop_price)
        
        if ticket:
            # Track position
            self._position_meta[symbol] = {
                "entry_date": self.time,
                "entry_price": price,
                "initial_quantity": quantity,
                "add_count": 0,
                "previous_stop": None,
                "ladder_trims": set(),
                "stop_market_order_id": None,  # Will be set after fill
            }
            
            # Immediately place stop market exit
            exit_stop = self._get_position_stop_price(symbol)
            if exit_stop:
                self._place_stop_market_exit(symbol, quantity, exit_stop)
            
            date_str = self.time.strftime("%Y-%m-%d")
            self.log(f"ENTRY_DEFERRED_EXEC|{date_str}|{symbol.value}|score={score}/8|qty={quantity}|deferred_for={(self.time - entry_params.get('deferred_at', self.time)).total_seconds()/60:.0f}min")


class BCTMinimalAlgorithmIntraday(QCAlgorithm):
    """
    Intraday-enabled BCT algorithm combining base features with intraday execution.
    
    This is a wrapper that combines the base BCTMinimalAlgorithm with intraday mixin.
    For actual implementation, the intraday methods would be merged into main.py.
    """
    pass  # Placeholder - actual implementation merges methods into main BCTMinimalAlgorithm
