"""
Alpaca Trader for Insider Trading Bot
Handles portfolio management, market data, and trade execution via Alpaca API.
"""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd
import numpy as np
from dataclasses import asdict

from database_manager import MarketData, TradeRecord

class AlpacaTrader:
    """Handles trading operations through Alpaca API"""

    def __init__(self, api_key: str = None, secret_key: str = None, paper: bool = True):
        """
        Initialize Alpaca trader

        Args:
            api_key: Alpaca API key (defaults to environment variable)
            secret_key: Alpaca secret key (defaults to environment variable)
            paper: Use paper trading (default True)
        """
        self.api_key = api_key or os.getenv('ALPACA_API_KEY')
        self.secret_key = secret_key or os.getenv('ALPACA_SECRET_KEY')
        self.paper = paper if paper is not None else os.getenv('ALPACA_BASE_URL', '').find('paper') != -1

        if not self.api_key or not self.secret_key:
            raise ValueError("Alpaca API credentials not provided")

        # Initialize trading client
        self.trading_client = TradingClient(
            api_key=self.api_key,
            secret_key=self.secret_key,
            paper=self.paper
        )

        # Initialize data client
        self.data_client = StockHistoricalDataClient(
            api_key=self.api_key,
            secret_key=self.secret_key
        )

        self.logger = logging.getLogger(__name__)

        # Trading configuration
        self.max_position_size = 0.05  # Max 5% of portfolio per position
        self.max_daily_trades = 10     # Max trades per day
        self.min_position_value = 1000 # Minimum position size

        try:
            # Verify API connection
            account = self.trading_client.get_account()
            self.logger.info(f"Connected to Alpaca account: {account.id}")
            self.logger.info(f"Account status: {account.status}")
            self.logger.info(f"Trading blocked: {account.trading_blocked}")
            self.logger.info(f"Portfolio value: ${float(account.portfolio_value):,.2f}")

        except Exception as e:
            self.logger.error(f"Failed to connect to Alpaca API: {e}")
            raise

    def get_account_info(self) -> Dict[str, Any]:
        """Get account information and buying power"""
        try:
            account = self.trading_client.get_account()
            return {
                'portfolio_value': float(account.portfolio_value),
                'buying_power': float(account.buying_power),
                'cash': float(account.cash),
                'equity': float(account.equity),
                'long_market_value': float(account.long_market_value),
                'short_market_value': float(account.short_market_value),
                'day_trade_count': int(account.day_trade_count),
                'pattern_day_trader': account.pattern_day_trader,
                'trading_blocked': account.trading_blocked,
                'status': account.status
            }
        except Exception as e:
            self.logger.error(f"Error getting account info: {e}")
            return {}

    def get_current_positions(self) -> List[Dict[str, Any]]:
        """Get current open positions"""
        try:
            positions = self.trading_client.get_all_positions()
            return [
                {
                    'symbol': pos.symbol,
                    'qty': int(pos.qty),
                    'market_value': float(pos.market_value),
                    'cost_basis': float(pos.cost_basis),
                    'unrealized_pl': float(pos.unrealized_pl),
                    'unrealized_plpc': float(pos.unrealized_plpc),
                    'current_price': float(pos.current_price),
                    'avg_entry_price': float(pos.avg_entry_price),
                    'side': pos.side
                }
                for pos in positions
            ]
        except Exception as e:
            self.logger.error(f"Error getting positions: {e}")
            return []

    def get_market_data(self, symbol: str, timeframe: str = '1Day',
                       limit: int = 100) -> Optional[MarketData]:
        """
        Get market data for a symbol including price and volume

        Args:
            symbol: Stock symbol
            timeframe: Data timeframe ('1Day', '1Hour', etc.)
            limit: Number of bars to retrieve

        Returns:
            MarketData object with current market information
        """
        try:
            # Get historical bars
            bars = self.api.get_bars(
                symbol,
                timeframe,
                limit=limit,
                adjustment='raw'
            ).df

            if bars.empty:
                self.logger.warning(f"No market data found for {symbol}")
                return None

            # Get latest bar
            latest_bar = bars.iloc[-1]
            latest_date = bars.index[-1].strftime('%Y-%m-%d')

            # Calculate ATR (14-period)
            atr_14 = self._calculate_atr(bars, period=14)

            # Calculate 30-day average volume
            avg_volume_30 = bars['volume'].tail(30).mean()

            return MarketData(
                symbol=symbol,
                date=latest_date,
                open_price=latest_bar['open'],
                high_price=latest_bar['high'],
                low_price=latest_bar['low'],
                close_price=latest_bar['close'],
                volume=latest_bar['volume'],
                atr_14=atr_14,
                avg_volume_30=avg_volume_30
            )

        except Exception as e:
            self.logger.error(f"Error getting market data for {symbol}: {e}")
            return None

    def _calculate_atr(self, bars: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range"""
        try:
            # Calculate True Range
            high_low = bars['high'] - bars['low']
            high_close = np.abs(bars['high'] - bars['close'].shift())
            low_close = np.abs(bars['low'] - bars['close'].shift())

            true_range = np.maximum(high_low, np.maximum(high_close, low_close))
            atr = true_range.rolling(window=period).mean().iloc[-1]

            return float(atr) if not np.isnan(atr) else 0.0

        except Exception as e:
            self.logger.error(f"Error calculating ATR: {e}")
            return 0.0

    def get_spy_condition(self) -> Tuple[bool, float]:
        """
        Get SPY market condition for gap filter

        Returns:
            Tuple of (trading_allowed, gap_percent)
        """
        try:
            # Get SPY current and previous close using correct data client
            request = StockBarsRequest(
                symbol_or_symbols='SPY',
                timeframe=TimeFrame.Day,
                limit=2
            )
            spy_bars = self.data_client.get_stock_bars(request).df

            if len(spy_bars) < 2:
                self.logger.warning("Insufficient SPY data for gap calculation")
                return True, 0.0  # Default to allow trading

            current_open = spy_bars.iloc[-1]['open']
            previous_close = spy_bars.iloc[-2]['close']

            # Prevent division by zero
            if previous_close == 0:
                self.logger.warning("Previous close is zero, skipping gap calculation")
                return True, 0.0

            gap_percent = ((current_open - previous_close) / previous_close) * 100

            # Allow trading if gap is <= 0.5%
            trading_allowed = abs(gap_percent) <= 0.5

            self.logger.info(f"SPY gap: {gap_percent:.2f}%, Trading allowed: {trading_allowed}")

            return trading_allowed, gap_percent

        except Exception as e:
            self.logger.error(f"Error checking SPY condition: {e}")
            return True, 0.0  # Default to allow trading on error

    def calculate_position_size(self, symbol: str, strategy_score: int,
                              current_price: float) -> int:
        """
        Calculate position size based on strategy score and risk management

        Args:
            symbol: Stock symbol
            strategy_score: Strategy confidence score
            current_price: Current stock price

        Returns:
            Number of shares to buy
        """
        try:
            account = self.api.get_account()
            portfolio_value = float(account.portfolio_value)
            buying_power = float(account.buying_power)

            # Base position size as percentage of portfolio
            # Higher scores get larger allocations
            if strategy_score >= 8:
                base_allocation = 0.05  # 5% for high conviction
            elif strategy_score >= 6:
                base_allocation = 0.03  # 3% for medium conviction
            else:
                base_allocation = 0.02  # 2% for low conviction

            # Calculate target position value
            target_value = portfolio_value * base_allocation

            # Ensure we don't exceed buying power
            target_value = min(target_value, buying_power * 0.95)  # Leave 5% buffer

            # Ensure minimum position size
            target_value = max(target_value, self.min_position_value)

            # Calculate shares
            shares = int(target_value / current_price)

            # Ensure we can afford the position
            actual_cost = shares * current_price
            if actual_cost > buying_power:
                shares = int(buying_power / current_price)

            self.logger.info(f"Position sizing for {symbol}: {shares} shares (${actual_cost:.2f})")

            return max(1, shares)  # At least 1 share

        except Exception as e:
            self.logger.error(f"Error calculating position size: {e}")
            return 1

    def place_buy_order(self, symbol: str, shares: int, strategy_score: int,
                       filing_id: str) -> Optional[TradeRecord]:
        """
        Place a buy order for a stock

        Args:
            symbol: Stock symbol
            shares: Number of shares to buy
            strategy_score: Strategy confidence score
            filing_id: Related insider filing ID

        Returns:
            TradeRecord if successful, None otherwise
        """
        try:
            # Get current market data
            market_data = self.get_market_data(symbol)
            if not market_data:
                self.logger.error(f"Cannot get market data for {symbol}")
                return None

            current_price = market_data.close_price
            position_value = shares * current_price

            # Calculate stop loss based on ATR and strategy
            # Earnings season: -50% ATR, Year-round: -150% ATR
            is_earnings_season = self._is_earnings_season()
            atr_multiplier = 0.5 if is_earnings_season else 1.5
            stop_loss_price = current_price - (market_data.atr_14 * atr_multiplier)

            # Calculate take profit (only for earnings season)
            take_profit_price = None
            if is_earnings_season:
                take_profit_price = current_price + (market_data.atr_14 * 1.0)  # +100% ATR

            # Place market buy order
            order = self.api.submit_order(
                symbol=symbol,
                qty=shares,
                side='buy',
                type='market',
                time_in_force='day'
            )

            # Create trade record
            trade_id = f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            trade_record = TradeRecord(
                trade_id=trade_id,
                filing_id=filing_id,
                symbol=symbol,
                entry_date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                entry_price=current_price,
                shares=shares,
                position_value=position_value,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                exit_date=None,
                exit_price=None,
                exit_reason=None,
                pnl=None,
                pnl_percent=None,
                strategy_score=strategy_score
            )

            self.logger.info(f"Buy order placed for {symbol}: {shares} shares at ~${current_price:.2f}")
            self.logger.info(f"Stop loss: ${stop_loss_price:.2f}, Take profit: ${take_profit_price:.2f if take_profit_price else 'EOD'}")

            return trade_record

        except Exception as e:
            self.logger.error(f"Error placing buy order for {symbol}: {e}")
            return None

    def place_sell_order(self, symbol: str, shares: int, reason: str = "MANUAL") -> bool:
        """
        Place a sell order to close a position

        Args:
            symbol: Stock symbol
            shares: Number of shares to sell
            reason: Reason for selling

        Returns:
            True if order placed successfully
        """
        try:
            order = self.api.submit_order(
                symbol=symbol,
                qty=shares,
                side='sell',
                type='market',
                time_in_force='day'
            )

            self.logger.info(f"Sell order placed for {symbol}: {shares} shares - {reason}")
            return True

        except Exception as e:
            self.logger.error(f"Error placing sell order for {symbol}: {e}")
            return False

    def check_stop_losses(self, open_trades: List[Dict]) -> List[Dict]:
        """
        Check if any open positions should be closed due to stop losses

        Args:
            open_trades: List of open trade records

        Returns:
            List of trades that should be closed
        """
        trades_to_close = []

        try:
            for trade in open_trades:
                symbol = trade['symbol']
                stop_loss_price = trade['stop_loss_price']
                take_profit_price = trade.get('take_profit_price')

                # Get current price
                try:
                    latest_trade = self.api.get_latest_trade(symbol)
                    current_price = float(latest_trade.price)
                except:
                    # Fallback to last bar close
                    bars = self.api.get_bars(symbol, '1Min', limit=1).df
                    if not bars.empty:
                        current_price = bars.iloc[-1]['close']
                    else:
                        continue

                # Check stop loss
                if current_price <= stop_loss_price:
                    trade['exit_reason'] = 'STOP_LOSS'
                    trade['current_price'] = current_price
                    trades_to_close.append(trade)
                    self.logger.info(f"Stop loss triggered for {symbol}: ${current_price:.2f} <= ${stop_loss_price:.2f}")

                # Check take profit (if set)
                elif take_profit_price and current_price >= take_profit_price:
                    trade['exit_reason'] = 'TAKE_PROFIT'
                    trade['current_price'] = current_price
                    trades_to_close.append(trade)
                    self.logger.info(f"Take profit triggered for {symbol}: ${current_price:.2f} >= ${take_profit_price:.2f}")

        except Exception as e:
            self.logger.error(f"Error checking stop losses: {e}")

        return trades_to_close

    def close_all_positions(self, reason: str = "END_OF_DAY") -> bool:
        """
        Close all open positions (used at end of trading day)

        Args:
            reason: Reason for closing positions

        Returns:
            True if all positions closed successfully
        """
        try:
            positions = self.api.list_positions()

            for position in positions:
                symbol = position.symbol
                qty = abs(int(position.qty))

                if qty > 0:
                    self.place_sell_order(symbol, qty, reason)

            self.logger.info(f"Closed all positions - {reason}")
            return True

        except Exception as e:
            self.logger.error(f"Error closing all positions: {e}")
            return False

    def _is_earnings_season(self) -> bool:
        """Check if current date is in earnings season"""
        current_month = datetime.now().month
        # Earnings seasons: February (2), May (5), August (8), November (11)
        return current_month in [2, 5, 8, 11]

    def get_order_history(self, status: str = None, limit: int = 100) -> List[Dict]:
        """Get order history"""
        try:
            orders = self.api.list_orders(
                status=status or 'all',
                limit=limit,
                direction='desc'
            )

            return [
                {
                    'id': order.id,
                    'symbol': order.symbol,
                    'qty': int(order.qty),
                    'side': order.side,
                    'order_type': order.order_type,
                    'status': order.status,
                    'submitted_at': order.submitted_at,
                    'filled_at': order.filled_at,
                    'filled_avg_price': float(order.filled_avg_price) if order.filled_avg_price else None,
                    'filled_qty': int(order.filled_qty) if order.filled_qty else 0
                }
                for order in orders
            ]

        except Exception as e:
            self.logger.error(f"Error getting order history: {e}")
            return []

    def get_portfolio_performance(self) -> Dict[str, Any]:
        """Get portfolio performance metrics"""
        try:
            # Get portfolio history
            portfolio_history = self.api.get_portfolio_history(
                period='1M',  # 1 month
                timeframe='1D'  # Daily
            )

            if not portfolio_history.equity:
                return {}

            # Calculate performance metrics
            equity_values = [float(e) for e in portfolio_history.equity]

            if len(equity_values) < 2:
                return {}

            start_value = equity_values[0]
            current_value = equity_values[-1]
            total_return = ((current_value - start_value) / start_value) * 100

            # Calculate daily returns
            daily_returns = []
            for i in range(1, len(equity_values)):
                daily_return = ((equity_values[i] - equity_values[i-1]) / equity_values[i-1]) * 100
                daily_returns.append(daily_return)

            avg_daily_return = np.mean(daily_returns) if daily_returns else 0
            volatility = np.std(daily_returns) if daily_returns else 0
            sharpe_ratio = (avg_daily_return / volatility) * np.sqrt(252) if volatility > 0 else 0

            return {
                'total_return_percent': total_return,
                'current_value': current_value,
                'start_value': start_value,
                'avg_daily_return': avg_daily_return,
                'volatility': volatility,
                'sharpe_ratio': sharpe_ratio,
                'days_tracked': len(equity_values)
            }

        except Exception as e:
            self.logger.error(f"Error getting portfolio performance: {e}")
            return {}

    def is_market_open(self) -> bool:
        """Check if market is currently open"""
        try:
            clock = self.trading_client.get_clock()
            return clock.is_open
        except Exception as e:
            self.logger.error(f"Error checking market status: {e}")
            return False

    def get_market_hours(self) -> Dict[str, Any]:
        """Get market hours information"""
        try:
            clock = self.api.get_clock()
            return {
                'is_open': clock.is_open,
                'next_open': clock.next_open.isoformat(),
                'next_close': clock.next_close.isoformat(),
                'timezone': str(clock.timezone)
            }
        except Exception as e:
            self.logger.error(f"Error getting market hours: {e}")
            return {}