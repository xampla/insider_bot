"""
Alpaca Trader for Insider Trading Bot
Handles portfolio management, market data, and trade execution via Alpaca API.
"""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest, GetPortfolioHistoryRequest
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

        # Enhanced PDF-compliant scaling mechanism with 3-month rolling windows
        self.scaling_config = {
            'base_risk_percent': 0.01,        # Start with 1% risk per trade
            'max_risk_percent': 0.02,         # Never exceed 2% per trade (PDF limit)
            'monthly_growth_rate': 0.10,      # 10% monthly growth per PDF
            'evaluation_period_days': 90,     # 3-month rolling evaluation (enhanced)
            'monthly_evaluation_days': 30,    # Individual month evaluation
            'min_win_rate_for_scaling': 0.60, # 60% win rate required for scaling
            'min_trades_for_evaluation': 30,  # Minimum trades needed for 3-month evaluation
            'min_trades_per_month': 10,       # Minimum trades per month for robustness
            'scale_down_loss_threshold': -0.15, # Scale down if monthly loss > 15%
            'required_profitable_months': 3   # Must be profitable for all 3 months
        }

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
                'day_trade_count': getattr(account, 'day_trade_count', 0),  # Default to 0 if not available
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
                    'qty': float(pos.qty),  # Handle fractional shares
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

    def get_market_data(self, symbol: str, target_date: str = None,
                       timeframe: TimeFrame = TimeFrame.Day, limit: int = 100) -> Optional[MarketData]:
        """
        Get market data for a symbol including price and volume
        Supports both current and historical data retrieval

        Args:
            symbol: Stock symbol
            target_date: Specific date for historical data (YYYY-MM-DD), None for current
            timeframe: Data timeframe (TimeFrame.Day, TimeFrame.Hour, etc.)
            limit: Number of bars to retrieve for calculations

        Returns:
            MarketData object with market information for the target date
        """
        try:
            # Create request for historical data
            if target_date:
                # For historical data, get range around target date for calculations
                target_dt = datetime.strptime(target_date, '%Y-%m-%d')
                start_time = target_dt - timedelta(days=limit)
                end_time = target_dt + timedelta(days=1)  # Include target date

                request = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=timeframe,
                    start=start_time,
                    end=end_time
                )
            else:
                # For current data, get recent bars
                request = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=timeframe,
                    limit=limit
                )

            # Get historical bars using correct API
            bars = self.data_client.get_stock_bars(request).df

            if bars.empty:
                self.logger.warning(f"No market data found for {symbol}")
                return None

            # Handle MultiIndex (symbol, timestamp) - select for our symbol
            if isinstance(bars.index, pd.MultiIndex):
                bars = bars.loc[symbol] if symbol in bars.index.get_level_values(0) else bars.iloc[:, :]
                bars.index = pd.to_datetime(bars.index)

            # Find the target bar
            if target_date:
                # For historical data, find the specific date or closest available
                target_date_str = target_date
                date_strings = bars.index.strftime('%Y-%m-%d')
                matching_mask = date_strings == target_date_str
                matching_bars = bars[matching_mask]

                if matching_bars.empty:
                    # Use closest available date
                    self.logger.warning(f"No data for exact date {target_date}, using closest available")
                    target_bar = bars.iloc[-1]
                    actual_date = bars.index[-1].strftime('%Y-%m-%d')
                    self.logger.info(f"Using data from {actual_date} for {symbol}")
                else:
                    target_bar = matching_bars.iloc[-1]
                    actual_date = target_date
            else:
                # For current data, use latest bar
                target_bar = bars.iloc[-1]
                actual_date = bars.index[-1].strftime('%Y-%m-%d')

            # Calculate ATR (14-period) using available data
            atr_14 = self._calculate_atr(bars, period=14)

            # Calculate 30-day average volume using available data
            avg_volume_30 = bars['volume'].tail(30).mean()

            return MarketData(
                symbol=symbol,
                date=actual_date,
                open_price=float(target_bar['open']),
                high_price=float(target_bar['high']),
                low_price=float(target_bar['low']),
                close_price=float(target_bar['close']),
                volume=float(target_bar['volume']),
                atr_14=float(atr_14),
                avg_volume_30=float(avg_volume_30)
            )

        except Exception as e:
            self.logger.error(f"Error getting market data for {symbol} on {target_date or 'current'}: {e}")
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

    def _get_spy_gap_data(self) -> Dict[str, Any]:
        """
        Get SPY data for gap calculation using hybrid approach:
        - AlphaVantage for reliable historical close data
        - Alpaca for today's open (when available)

        Returns:
            Dict with success status, current_open, previous_close, and reason
        """
        import requests
        import json
        from datetime import datetime

        try:
            # Get AlphaVantage API key from environment
            alpha_key = os.getenv('ALPHAVANTAGE_API_KEY', 'WDABSJY7AQU6IJF1')

            # 1. Get historical data from AlphaVantage (reliable for yesterday's close)
            av_url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=SPY&apikey={alpha_key}"

            response = requests.get(av_url, timeout=10)
            response.raise_for_status()

            av_data = response.json()

            if "Error Message" in av_data:
                raise Exception(f"AlphaVantage error: {av_data['Error Message']}")

            if "Note" in av_data:
                # API call frequency limit
                self.logger.warning(f"AlphaVantage rate limit: {av_data['Note']}")
                return self._fallback_to_alpaca_only()

            time_series = av_data.get("Time Series (Daily)", {})
            if not time_series:
                raise Exception("No time series data from AlphaVantage")

            # Get sorted dates (most recent first)
            dates = sorted(time_series.keys(), reverse=True)

            if len(dates) < 1:
                raise Exception("Insufficient AlphaVantage data")

            # Get yesterday's close from AlphaVantage
            latest_date = dates[0]
            previous_close = float(time_series[latest_date]['4. close'])

            self.logger.info(f"📊 AlphaVantage: Previous close ({latest_date}): ${previous_close:.2f}")

            # 2. Try to get today's open from Alpaca (real-time when market is open)
            try:
                request = StockBarsRequest(
                    symbol_or_symbols='SPY',
                    timeframe=TimeFrame.Day,
                    limit=1
                )
                spy_bars = self.data_client.get_stock_bars(request).df

                if spy_bars is not None and len(spy_bars) > 0:
                    current_open = spy_bars.iloc[-1]['open']
                    today_date = spy_bars.index.get_level_values('timestamp')[-1].date()
                    self.logger.info(f"📊 Alpaca: Current open ({today_date}): ${current_open:.2f}")

                    return {
                        'success': True,
                        'current_open': float(current_open),
                        'previous_close': previous_close,
                        'data_source': 'AlphaVantage(historical) + Alpaca(today)',
                        'reason': 'Hybrid data source successful'
                    }

            except Exception as alpaca_error:
                self.logger.info(f"Alpaca current data unavailable: {alpaca_error}")

            # 3. Fallback: Use AlphaVantage for both yesterday and today
            if len(dates) >= 2:
                today_data = time_series[dates[0]]
                current_open = float(today_data['1. open'])

                # Use second-most recent date for yesterday's close
                yesterday_date = dates[1]
                previous_close = float(time_series[yesterday_date]['4. close'])

                self.logger.info(f"📊 AlphaVantage fallback: Using {dates[0]} open vs {yesterday_date} close")

                return {
                    'success': True,
                    'current_open': current_open,
                    'previous_close': previous_close,
                    'data_source': 'AlphaVantage(both)',
                    'reason': 'AlphaVantage fallback successful'
                }
            else:
                return {
                    'success': False,
                    'current_open': 0.0,
                    'previous_close': 0.0,
                    'data_source': 'None',
                    'reason': 'Insufficient AlphaVantage historical data'
                }

        except requests.RequestException as e:
            self.logger.warning(f"AlphaVantage network error: {e}")
            return self._fallback_to_alpaca_only()
        except Exception as e:
            self.logger.warning(f"AlphaVantage data error: {e}")
            return self._fallback_to_alpaca_only()

    def _fallback_to_alpaca_only(self) -> Dict[str, Any]:
        """Fallback to original Alpaca-only approach when AlphaVantage fails"""
        try:
            request = StockBarsRequest(
                symbol_or_symbols='SPY',
                timeframe=TimeFrame.Day,
                limit=2
            )
            spy_bars = self.data_client.get_stock_bars(request).df

            if spy_bars is not None and len(spy_bars) >= 2:
                current_open = spy_bars.iloc[-1]['open']
                previous_close = spy_bars.iloc[-2]['close']

                return {
                    'success': True,
                    'current_open': float(current_open),
                    'previous_close': float(previous_close),
                    'data_source': 'Alpaca(fallback)',
                    'reason': 'Alpaca fallback successful'
                }
            else:
                return {
                    'success': False,
                    'current_open': 0.0,
                    'previous_close': 0.0,
                    'data_source': 'None',
                    'reason': 'Both AlphaVantage and Alpaca failed'
                }
        except Exception as e:
            return {
                'success': False,
                'current_open': 0.0,
                'previous_close': 0.0,
                'data_source': 'None',
                'reason': f'All data sources failed: {e}'
            }

    def get_enhanced_spy_condition(self, symbol: str = None,
                                  has_insider_cluster: bool = False) -> Dict[str, Any]:
        """
        Enhanced SPY market filter with tier-based exceptions

        Rules:
        - Skip Tier 1 & 2 trades if SPY gap > ±0.5%
        - Allow Tier 3 & 4 trades if insider cluster buy (≥2 insiders same day)
        - Prevents macro-driven days from distorting insider signals

        Args:
            symbol: Company symbol to check tier classification
            has_insider_cluster: Whether there's a multi-insider buy signal

        Returns:
            Dict with trading decision and reasoning
        """
        try:
            # Get SPY gap data using hybrid approach (AlphaVantage + Alpaca)
            spy_data = self._get_spy_gap_data()

            if not spy_data['success']:
                self.logger.warning(f"SPY data unavailable: {spy_data['reason']}")
                return {
                    'trading_allowed': True,
                    'gap_percent': 0.0,
                    'reason': f"SPY data unavailable - allowing trades with caution ({spy_data['reason']})",
                    'filter_applied': False,
                    'risk_multiplier': 1.0
                }

            current_open = spy_data['current_open']
            previous_close = spy_data['previous_close']
            self.logger.info(f"📊 SPY Gap Data: {spy_data['data_source']} - Open: ${current_open:.2f}, Close: ${previous_close:.2f}")

            # Robust validation for SPY data
            import numpy as np
            if (previous_close == 0 or current_open == 0 or
                pd.isna(previous_close) or pd.isna(current_open) or
                not np.isfinite(previous_close) or not np.isfinite(current_open)):
                self.logger.warning(f"Invalid SPY data: current_open={current_open}, previous_close={previous_close}")
                return {
                    'trading_allowed': True,
                    'gap_percent': 0.0,
                    'reason': 'Invalid SPY data - allowing trades with caution',
                    'filter_applied': False,
                    'risk_multiplier': 1.0
                }

            try:
                gap_percent = ((current_open - previous_close) / previous_close) * 100
            except (ZeroDivisionError, ValueError, ArithmeticError) as e:
                self.logger.warning(f"SPY gap calculation failed: {e} (current: {current_open}, previous: {previous_close})")
                return {
                    'trading_allowed': True,
                    'gap_percent': 0.0,
                    'reason': 'SPY calculation error - allowing trades with caution',
                    'filter_applied': False,
                    'risk_multiplier': 1.0
                }

            # GRANULAR SPY MARKET FILTER with graduated risk adjustments
            abs_gap = abs(gap_percent)

            # Define graduated thresholds
            if abs_gap < 0.5:
                # Normal market conditions - no filter adjustment
                return {
                    'trading_allowed': True,
                    'risk_multiplier': 1.0,
                    'gap_percent': gap_percent,
                    'reason': f'Normal market conditions (SPY gap: {gap_percent:.2f}%)',
                    'filter_applied': False
                }

            # Graduated filtering based on gap size and tier
            if symbol:
                tier = self._get_symbol_tier(symbol)

                if abs_gap < 1.0:
                    # Medium gap (0.5-1.0%): Graduated response
                    if tier in [1, 2]:
                        # Tier 1 & 2: Trade at 50% risk
                        return {
                            'trading_allowed': True,
                            'risk_multiplier': 0.5,
                            'gap_percent': gap_percent,
                            'reason': f'Medium SPY gap: {gap_percent:.2f}% → 50% risk (Tier {tier})',
                            'filter_applied': True,
                            'tier': tier
                        }
                    elif tier in [3, 4]:
                        # Tier 3 & 4: Cluster exception → normal risk, single buys → 50% risk
                        if has_insider_cluster:
                            return {
                                'trading_allowed': True,
                                'risk_multiplier': 1.0,
                                'gap_percent': gap_percent,
                                'reason': f'Tier {tier} cluster exception: Normal risk despite {gap_percent:.2f}% gap',
                                'filter_applied': True,
                                'tier': tier,
                                'exception_applied': True
                            }
                        else:
                            return {
                                'trading_allowed': True,
                                'risk_multiplier': 0.5,
                                'gap_percent': gap_percent,
                                'reason': f'Medium SPY gap: {gap_percent:.2f}% → 50% risk (Tier {tier}, single buy)',
                                'filter_applied': True,
                                'tier': tier
                            }
                else:
                    # Large gap (>1.0%): More restrictive
                    if tier in [1, 2]:
                        # Tier 1 & 2: Skip completely
                        return {
                            'trading_allowed': False,
                            'risk_multiplier': 0.0,
                            'gap_percent': gap_percent,
                            'reason': f'Large SPY gap: {gap_percent:.2f}% > 1.0% → Skip (Tier {tier})',
                            'filter_applied': True,
                            'tier': tier
                        }
                    elif tier == 3:
                        # Tier 3: Cluster exception → 25% risk for very rare but powerful signals
                        if has_insider_cluster:
                            return {
                                'trading_allowed': True,
                                'risk_multiplier': 0.25,
                                'gap_percent': gap_percent,
                                'reason': f'Tier 3 cluster exception: 25% risk for rare powerful signal ({gap_percent:.2f}%)',
                                'filter_applied': True,
                                'tier': tier,
                                'exception_applied': True
                            }
                        else:
                            return {
                                'trading_allowed': False,
                                'risk_multiplier': 0.0,
                                'gap_percent': gap_percent,
                                'reason': f'Large SPY gap: {gap_percent:.2f}% > 1.0% → Skip (Tier {tier}, no cluster)',
                                'filter_applied': True,
                                'tier': tier
                            }
                    elif tier == 4:
                        # Tier 4: Cluster exception → 25% risk (maintained for high-risk small caps)
                        if has_insider_cluster:
                            return {
                                'trading_allowed': True,
                                'risk_multiplier': 0.25,
                                'gap_percent': gap_percent,
                                'reason': f'Tier 4 cluster exception: 25% risk despite large gap ({gap_percent:.2f}%)',
                                'filter_applied': True,
                                'tier': tier,
                                'exception_applied': True
                            }
                        else:
                            return {
                                'trading_allowed': False,
                                'risk_multiplier': 0.0,
                                'gap_percent': gap_percent,
                                'reason': f'Large SPY gap: {gap_percent:.2f}% → Skip (Tier {tier}, no cluster)',
                                'filter_applied': True,
                                'tier': tier
                            }

                # Unknown tier - default to conservative
                return {
                    'trading_allowed': False,
                    'risk_multiplier': 0.0,
                    'gap_percent': gap_percent,
                    'reason': f'SPY gap filter: {gap_percent:.2f}% (Unknown tier)',
                    'filter_applied': True
                }
            else:
                # No symbol provided - basic graduated filter
                if abs_gap < 1.0:
                    return {
                        'trading_allowed': True,
                        'risk_multiplier': 0.5,
                        'gap_percent': gap_percent,
                        'reason': f'Medium SPY gap: {gap_percent:.2f}% → 50% risk',
                        'filter_applied': True
                    }
                else:
                    return {
                        'trading_allowed': False,
                        'risk_multiplier': 0.0,
                        'gap_percent': gap_percent,
                        'reason': f'Large SPY gap: {gap_percent:.2f}% → Skip',
                        'filter_applied': True
                    }

        except Exception as e:
            self.logger.error(f"Error in enhanced SPY condition check: {e}")
            return {
                'trading_allowed': True,
                'gap_percent': 0.0,
                'reason': f'SPY filter error - allowing trades with caution: {e}',
                'filter_applied': False,
                'risk_multiplier': 1.0
            }

    def calculate_insider_role_adjustment(self, filing_data: Dict) -> int:
        """
        Calculate strategy score adjustment based on insider role(s)

        Academic research shows CFO trades predict future returns better than CEO
        Makes Strategy Score more "information sensitive"

        Role Weighting:
        - CFO/COO: +2 (strongest predictive power - financial insiders)
        - CEO/President: +1 (good signal, but more PR-driven)
        - Director only: -1 (weakest signal, often symbolic buys)
        - Multiple roles: Add all adjustments

        Args:
            filing_data: Dictionary containing insider information

        Returns:
            Score adjustment (can be negative)
        """
        try:
            # Extract insider role information from filing data
            insider_name = filing_data.get('insider_name', '').upper()
            insider_title = filing_data.get('insider_title', '').upper()

            # Combine name and title for comprehensive role detection
            combined_text = f"{insider_name} {insider_title}".upper()

            total_adjustment = 0
            roles_detected = []

            # CFO/COO Detection (Highest priority - financial insiders)
            cfo_indicators = ['CFO', 'CHIEF FINANCIAL OFFICER', 'CHIEF FINANCE OFFICER']
            coo_indicators = ['COO', 'CHIEF OPERATING OFFICER', 'CHIEF OPERATIONS OFFICER']

            if any(indicator in combined_text for indicator in cfo_indicators):
                total_adjustment += 2
                roles_detected.append('CFO (+2)')

            if any(indicator in combined_text for indicator in coo_indicators):
                total_adjustment += 2
                roles_detected.append('COO (+2)')

            # CEO/President Detection (Medium priority)
            ceo_indicators = ['CEO', 'CHIEF EXECUTIVE OFFICER', 'CHIEF EXEC OFFICER']
            president_indicators = ['PRESIDENT', 'PRES ', ' PRES']

            if any(indicator in combined_text for indicator in ceo_indicators):
                total_adjustment += 1
                roles_detected.append('CEO (+1)')

            if any(indicator in combined_text for indicator in president_indicators):
                # Avoid double-counting if already detected as CEO
                if not any('CEO' in role for role in roles_detected):
                    total_adjustment += 1
                    roles_detected.append('President (+1)')

            # Director-only Detection (Lowest priority - often symbolic)
            director_indicators = ['DIRECTOR', 'DIR ', ' DIR', 'BOARD MEMBER']

            # Only apply director penalty if no executive roles detected
            if (any(indicator in combined_text for indicator in director_indicators) and
                not roles_detected):  # No executive roles found
                total_adjustment -= 1
                roles_detected.append('Director Only (-1)')

            # Additional high-value roles (use word boundaries to avoid false matches)
            cto_indicators = [' CTO', 'CTO ', 'CHIEF TECHNOLOGY OFFICER', 'CHIEF TECH OFFICER']
            if any(indicator in combined_text for indicator in cto_indicators):
                total_adjustment += 2
                roles_detected.append('CTO (+2)')

            # Cap role boost at +2 total to prevent over-inflation
            # Prevents weak base scores from jumping to high conviction instantly
            capped_adjustment = max(-2, min(2, total_adjustment))  # Cap between -2 and +2

            # Log the role analysis for transparency
            if roles_detected:
                self.logger.info(f"🧑‍💼 Insider Role Analysis for {insider_name}:")
                self.logger.info(f"   Detected roles: {', '.join(roles_detected)}")
                if capped_adjustment != total_adjustment:
                    self.logger.info(f"   Raw adjustment: {total_adjustment:+d} → Capped: {capped_adjustment:+d}")
                else:
                    self.logger.info(f"   Total adjustment: {capped_adjustment:+d}")
            else:
                self.logger.info(f"🧑‍💼 No specific roles detected for {insider_name}, no adjustment")

            return capped_adjustment

        except Exception as e:
            self.logger.error(f"Error calculating insider role adjustment: {e}")
            return 0  # Default to no adjustment on error

    def apply_insider_role_weighting(self, base_strategy_score: int,
                                   filing_data: Dict) -> int:
        """
        Apply insider role weighting to enhance strategy score

        Args:
            base_strategy_score: Original strategy score
            filing_data: Insider filing information

        Returns:
            Adjusted strategy score with role weighting applied
        """
        try:
            role_adjustment = self.calculate_insider_role_adjustment(filing_data)
            adjusted_score = base_strategy_score + role_adjustment

            # Ensure score stays within reasonable bounds (0-10 range typically)
            adjusted_score = max(0, min(10, adjusted_score))

            if role_adjustment != 0:
                self.logger.info(f"📊 Strategy Score Enhancement:")
                self.logger.info(f"   Base score: {base_strategy_score}")
                self.logger.info(f"   Role adjustment: {role_adjustment:+d}")
                self.logger.info(f"   Final score: {adjusted_score}")

            return adjusted_score

        except Exception as e:
            self.logger.error(f"Error applying insider role weighting: {e}")
            return base_strategy_score  # Return original score on error

    def should_exclude_director_only_signal(self, signal_data: Dict) -> bool:
        """
        Check if signal should be excluded due to director-only + small size criteria

        Excludes trades where:
        1. ALL insiders are directors only (no executives)
        2. Transaction size < $100k (weak signal strength)

        Args:
            signal_data: Signal data with filing information

        Returns:
            True if signal should be excluded
        """
        try:
            symbol = signal_data.get('symbol', 'Unknown')

            # Check if this is a director-only signal
            insider_title = signal_data.get('insider_title', '').upper()
            insider_name = signal_data.get('insider_name', '').upper()
            combined_text = f"{insider_name} {insider_title}".upper()

            # Check for executive roles (if any present, not director-only)
            executive_indicators = [
                'CFO', 'CHIEF FINANCIAL OFFICER', 'CHIEF FINANCE OFFICER',
                'CEO', 'CHIEF EXECUTIVE OFFICER', 'CHIEF EXEC OFFICER',
                'COO', 'CHIEF OPERATING OFFICER', 'CHIEF OPERATIONS OFFICER',
                'PRESIDENT', 'PRES ', ' PRES',
                ' CTO', 'CTO ', 'CHIEF TECHNOLOGY OFFICER', 'CHIEF TECH OFFICER'
            ]

            has_executive_role = any(indicator in combined_text for indicator in executive_indicators)

            if has_executive_role:
                # Has executive role, not director-only
                return False

            # Check for director indicators
            director_indicators = ['DIRECTOR', 'DIR ', ' DIR', 'BOARD MEMBER']
            is_director = any(indicator in combined_text for indicator in director_indicators)

            if not is_director:
                # Not identified as director either, allow trade
                return False

            # This is a director-only signal, check transaction size
            shares = signal_data.get('shares', 0)
            price_per_share = signal_data.get('price_per_share', 0)
            transaction_value = shares * price_per_share

            min_transaction_threshold = 100000  # $100k

            if transaction_value < min_transaction_threshold:
                self.logger.info(f"🚫 Excluding director-only signal for {symbol}:")
                self.logger.info(f"   Insider: {signal_data.get('insider_name', 'Unknown')}")
                self.logger.info(f"   Title: {signal_data.get('insider_title', 'Unknown')}")
                self.logger.info(f"   Transaction value: ${transaction_value:,.0f} < ${min_transaction_threshold:,.0f}")
                self.logger.info(f"   Reason: Director-only signal with small transaction size")
                return True

            return False

        except Exception as e:
            self.logger.error(f"Error evaluating director-only exclusion: {e}")
            return False  # Don't exclude on error

    def check_sector_concentration_limits(self, symbol: str, strategy_score: int) -> bool:
        """
        Check if adding this high conviction trade would violate sector concentration limits

        Risk Control: Max 1 high conviction position per sector to avoid sector concentration risk

        Args:
            symbol: Company symbol
            strategy_score: Strategy score to determine if high conviction

        Returns:
            True if trade is allowed, False if would violate sector concentration
        """
        try:
            # Only apply to high conviction trades (score >= 7)
            if strategy_score < 7:
                return True  # Allow non-high conviction trades

            current_sector = self._get_company_sector(symbol)
            if not current_sector:
                # If we can't determine sector, allow trade (conservative approach)
                return True

            # Get current open positions
            open_positions = self.get_current_positions()

            # Check for existing high conviction positions in same sector
            for position in open_positions:
                position_symbol = position.get('symbol', '')
                position_score = position.get('strategy_score', 0)

                # Check if this is a high conviction position in the same sector
                if position_score >= 7:  # High conviction
                    position_sector = self._get_company_sector(position_symbol)
                    if position_sector == current_sector:
                        self.logger.info(f"🚫 Blocked new {symbol} trade: {current_sector} sector already has {position_symbol} (High Conviction)")
                        return False

            return True

        except Exception as e:
            self.logger.error(f"Error checking sector concentration for {symbol}: {e}")
            return True  # Allow trade on error (conservative)

    def _get_company_sector(self, symbol: str) -> str:
        """
        Get sector classification for a company symbol

        Returns sector string or empty string if unknown

        Args:
            symbol: Company symbol

        Returns:
            Sector name (e.g., "Technology", "Healthcare", etc.)
        """
        try:
            # Basic sector mapping for major companies
            # In production, this would use a real sector data provider
            sector_mapping = {
                # Technology
                'AAPL': 'Technology',
                'MSFT': 'Technology',
                'NVDA': 'Technology',
                'GOOGL': 'Technology',
                'META': 'Technology',
                'CRM': 'Technology',
                'ADBE': 'Technology',
                'SNOW': 'Technology',
                'ZM': 'Technology',
                'DOCU': 'Technology',
                'TWLO': 'Technology',
                'PLTR': 'Technology',
                'RBLX': 'Technology',

                # E-commerce / Consumer
                'AMZN': 'Consumer',
                'TSLA': 'Consumer',
                'NFLX': 'Consumer',
                'DIS': 'Consumer',
                'ROKU': 'Consumer',
                'SPOT': 'Consumer',

                # Financial
                'V': 'Financial',
                'MA': 'Financial',
                'SQ': 'Financial',
                'SOFI': 'Financial',
                'COIN': 'Financial',
                'HOOD': 'Financial',

                # Healthcare
                'UNH': 'Healthcare',

                # Real Estate
                'OPEN': 'Real Estate',

                # Streaming/Entertainment
                'FUBO': 'Entertainment',
                'LCID': 'Automotive'
            }

            return sector_mapping.get(symbol, '')

        except Exception as e:
            self.logger.error(f"Error getting sector for {symbol}: {e}")
            return ''

    def _get_symbol_tier(self, symbol: str) -> int:
        """
        Get tier classification for a symbol
        This should eventually be injected via backfill_manager, but for now we'll hardcode
        """
        # TIER 1: Mega-caps
        tier1 = ['AAPL', 'NVDA', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA']

        # TIER 2: Large-caps
        tier2 = ['JPM', 'JNJ', 'V', 'PG', 'UNH', 'HD', 'MA', 'DIS', 'NFLX', 'CRM']

        # TIER 3: Mid-caps + Quality
        tier3 = ['DDOG', 'ZS', 'CRWD', 'TEAM', 'ALGN', 'ROKU', 'ADBE', 'PFE', 'KO', 'TMO', 'ABT']

        # TIER 4: Small-caps
        tier4 = ['PLTR', 'RBLX', 'FUBO', 'SOFI', 'OPEN', 'COIN', 'HOOD', 'LCID']

        if symbol in tier1:
            return 1
        elif symbol in tier2:
            return 2
        elif symbol in tier3:
            return 3
        elif symbol in tier4:
            return 4
        else:
            return 0  # Unknown

    def get_spy_condition(self) -> Tuple[bool, float]:
        """
        Legacy SPY condition method - maintained for backward compatibility
        """
        result = self.get_enhanced_spy_condition()
        return result['trading_allowed'], result['gap_percent']

    def calculate_position_size(self, symbol: str, strategy_score: int,
                              current_price: float, market_data: MarketData = None,
                              stop_variant: int = 1, cluster_details: dict = None) -> float:
        """
        Calculate position size using enhanced risk-first approach

        Risk-first methodology:
        1. Determine base risk per trade (1-2% of account)
        2. Apply cluster buy multiplier (+0.5% if multiple insiders)
        3. Calculate stop-loss distance based on ATR
        4. Position size = Risk Amount / Stop Distance

        Args:
            symbol: Stock symbol
            strategy_score: Strategy confidence score (affects risk allocation)
            current_price: Current stock price
            market_data: Market data containing ATR
            stop_variant: 1 for 50% ATR stop, 2 for 150% ATR stop
            has_insider_cluster: True if ≥2 insiders buying same day

        Returns:
            Number of shares to buy
        """
        try:
            account = self.trading_client.get_account()
            portfolio_value = float(account.portfolio_value)
            buying_power = float(account.buying_power)

            # Get market data if not provided
            if not market_data:
                market_data = self.get_market_data(symbol)
                if not market_data:
                    self.logger.error(f"Cannot get market data for position sizing: {symbol}")
                    return 1

            # RISK-FIRST APPROACH per PDF with scaling mechanism
            # Base risk allocation based on strategy confidence
            if strategy_score >= 8:
                base_risk_percent = 0.02  # 2% for high conviction (max recommended)
            elif strategy_score >= 6:
                base_risk_percent = 0.015  # 1.5% for medium conviction
            else:
                base_risk_percent = 0.01  # 1% for low conviction (conservative)

            # Apply scaling factor based on performance (PDF: "~10% growth per month of success")
            scaling_factor = self.get_scaling_factor()
            risk_percent = base_risk_percent * scaling_factor

            # 👥 CLUSTER BUY MULTIPLIER: Boost risk for exceptional signals with diminishing returns
            # Multiple insiders buying same day = exceptionally strong signal
            cluster_boost = 0.0
            if cluster_details and cluster_details.get('is_cluster', False):
                cluster_boost = self._calculate_cluster_risk_boost(cluster_details)
                risk_percent += cluster_boost
                insider_count = cluster_details.get('insider_count', 0)
                self.logger.info(f"🎯 Cluster Buy Detected: {insider_count} insiders, boosting risk by +{cluster_boost*100:.2f}% for {symbol}")

            # Ensure we never exceed PDF maximum of 2%
            risk_percent = min(risk_percent, self.scaling_config['max_risk_percent'])

            # Log risk calculation details
            if cluster_boost > 0:
                self.logger.info(f"📊 Risk Calculation Breakdown for {symbol}:")
                self.logger.info(f"   Base risk: {base_risk_percent*100:.1f}%")
                self.logger.info(f"   Scaling factor: {scaling_factor:.2f}")
                self.logger.info(f"   Cluster boost: +{cluster_boost*100:.2f}%")
                self.logger.info(f"   Final risk: {risk_percent*100:.1f}% (capped at 2.0%)")

            # Calculate dollar risk amount
            risk_amount = portfolio_value * risk_percent

            # Calculate stop-loss distance using ATR variants per PDF
            is_earnings_season = self._is_earnings_season()

            if stop_variant == 1:
                # Variant 1: 50% ATR stop (tighter)
                atr_multiplier = 0.5
            else:
                # Variant 2: 150% ATR stop (wider buffer)
                atr_multiplier = 1.5

            # Adjust for earnings season (PDF uses different multipliers)
            if is_earnings_season:
                # Earnings season: use tighter stops
                atr_multiplier = min(atr_multiplier, 0.5)

            stop_distance = market_data.atr_14 * atr_multiplier
            stop_loss_price = current_price - stop_distance

            # Calculate position size: Risk Amount / Stop Distance
            if stop_distance > 0:
                target_position_value = risk_amount / (stop_distance / current_price)
            else:
                # Fallback to conservative sizing if ATR is invalid
                target_position_value = risk_amount / 0.024  # Assume 2.4% stop (PDF average)

            # Calculate shares with fractional precision (Alpaca supports up to 6 decimals)
            shares = round(target_position_value / current_price, 6)

            # Safety checks
            # Ensure we don't exceed buying power with fractional precision
            actual_cost = shares * current_price
            if actual_cost > buying_power * 0.95:  # Leave 5% buffer
                shares = round((buying_power * 0.95) / current_price, 6)
                actual_cost = shares * current_price

            # Ensure minimum position (at least $2 for meaningful trades)
            if actual_cost < 2:
                shares = max(round(2 / current_price, 6), 0.000001)  # Alpaca minimum
                actual_cost = shares * current_price

            # Ensure we can afford the position with fractional precision
            if actual_cost > buying_power:
                shares = round(buying_power / current_price, 6)
                actual_cost = shares * current_price

            # Calculate actual risk percentage
            actual_risk_amount = stop_distance * shares if stop_distance > 0 else actual_cost * 0.024
            actual_risk_percent = (actual_risk_amount / portfolio_value) * 100

            self.logger.info(f"Risk-first position sizing for {symbol}:")
            self.logger.info(f"  Base risk: {base_risk_percent*100:.1f}% → Scaled: {risk_percent*100:.1f}% (factor: {scaling_factor:.2f})")
            self.logger.info(f"  Target risk: ${risk_amount:.2f}")
            self.logger.info(f"  Stop distance: ${stop_distance:.2f} (ATR: ${market_data.atr_14:.2f})")
            self.logger.info(f"  Position: {shares} shares @ ${current_price:.2f} = ${actual_cost:.2f}")
            self.logger.info(f"  Actual risk: ${actual_risk_amount:.2f} ({actual_risk_percent:.2f}%)")
            self.logger.info(f"  Stop loss: ${stop_loss_price:.2f}")

            return max(0.000001, shares)  # At least Alpaca minimum fractional

        except Exception as e:
            self.logger.error(f"Error calculating risk-first position size: {e}")
            # Fallback to conservative position
            return max(0.000001, round(1000 / current_price, 6))  # $1000 fallback with fractional

    def optimize_capital_allocation(self, signal_list: list, telegram_notifier=None) -> dict:
        """
        Optimize capital allocation when multiple signals exceed available buying power

        Args:
            signal_list: List of trading signals with position sizes
            telegram_notifier: Telegram notifier for user alerts

        Returns:
            dict: Allocation results with optimized positions and notifications
        """
        try:
            account = self.trading_client.get_account()
            available_capital = float(account.buying_power) * 0.95  # 5% buffer

            # Calculate total requested capital
            total_requested = sum(signal['shares'] * signal['current_price'] for signal in signal_list)

            if total_requested <= available_capital:
                # No allocation conflict
                return {
                    'allocation_needed': False,
                    'optimized_signals': signal_list,
                    'message': f"All {len(signal_list)} signals fit within ${available_capital:,.0f} buying power"
                }

            # Allocation needed - prioritize by strategy_score and optimize fractional usage
            sorted_signals = sorted(signal_list, key=lambda x: x['strategy_score'], reverse=True)
            optimized_signals = []
            remaining_capital = available_capital
            skipped_signals = []

            self.logger.warning(f"⚠️ Capital allocation needed: ${total_requested:,.0f} requested > ${available_capital:,.0f} available")

            for signal in sorted_signals:
                signal_cost = signal['shares'] * signal['current_price']

                if signal_cost <= remaining_capital:
                    # Signal fits - take it as-is
                    optimized_signals.append(signal)
                    remaining_capital -= signal_cost
                    self.logger.info(f"✅ Allocated: {signal['symbol']} - {signal['shares']:.6f} shares @ ${signal['current_price']:.2f} = ${signal_cost:.2f}")

                elif remaining_capital >= 2:  # Minimum $2 position
                    # Partial allocation with fractional shares
                    fractional_shares = round(remaining_capital / signal['current_price'], 6)
                    if fractional_shares >= 0.000001:  # Alpaca minimum
                        optimized_signal = signal.copy()
                        optimized_signal['shares'] = fractional_shares
                        optimized_signal['original_shares'] = signal['shares']
                        optimized_signal['allocation_type'] = 'partial'

                        optimized_signals.append(optimized_signal)
                        actual_cost = fractional_shares * signal['current_price']
                        remaining_capital -= actual_cost

                        self.logger.info(f"📉 Partial allocation: {signal['symbol']} - {fractional_shares:.6f}/{signal['shares']:.6f} shares = ${actual_cost:.2f}")
                    else:
                        skipped_signals.append(signal)
                else:
                    # Skip signal - insufficient capital
                    skipped_signals.append(signal)
                    self.logger.warning(f"❌ Skipped: {signal['symbol']} - insufficient capital (${remaining_capital:.2f} remaining)")

            # Send Telegram notification
            if telegram_notifier and telegram_notifier.enabled:
                allocated_count = len(optimized_signals)
                skipped_count = len(skipped_signals)
                capital_used = available_capital - remaining_capital

                notification = (
                    f"🚨 CAPITAL ALLOCATION ALERT\n"
                    f"📊 {len(signal_list)} signals detected, ${total_requested:,.0f} requested\n"
                    f"💰 Available: ${available_capital:,.0f}\n"
                    f"✅ Allocated: {allocated_count} positions (${capital_used:,.0f})\n"
                    f"❌ Skipped: {skipped_count} positions\n"
                    f"💵 Remaining: ${remaining_capital:,.0f}"
                )

                if any(s.get('allocation_type') == 'partial' for s in optimized_signals):
                    notification += f"\n⚠️ Some positions reduced to fit budget"

                telegram_notifier.notify_system_status("capital_allocation", notification)

            return {
                'allocation_needed': True,
                'optimized_signals': optimized_signals,
                'skipped_signals': skipped_signals,
                'capital_utilization': ((available_capital - remaining_capital) / available_capital) * 100,
                'message': f"Optimized {len(optimized_signals)}/{len(signal_list)} signals within budget"
            }

        except Exception as e:
            self.logger.error(f"Error optimizing capital allocation: {e}")
            return {
                'allocation_needed': False,
                'optimized_signals': signal_list,
                'error': str(e)
            }

    def place_buy_order(self, symbol: str, shares: float, strategy_score: int,
                       filing_id: str, stop_variant: int = 1,
                       take_profit_variant: int = 1) -> Optional[TradeRecord]:
        """
        Place a buy order with PDF-compliant stop-loss and take-profit strategy

        Stop-Loss Variants (per PDF):
        - Variant 1: 50% ATR below entry (tighter stops)
        - Variant 2: 150% ATR below entry (wider buffer)

        Take-Profit Variants (per PDF):
        - Variant 1: Fixed take-profit at 100-150% ATR above entry
        - Variant 2: No fixed take-profit, exit on stop-loss or EOD

        Args:
            symbol: Stock symbol
            shares: Number of shares to buy
            strategy_score: Strategy confidence score
            filing_id: Related insider filing ID
            stop_variant: 1 for 50% ATR stop, 2 for 150% ATR stop
            take_profit_variant: 1 for fixed TP, 2 for EOD-only exit

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

            # Trust the position size calculated in main.py with fractional precision
            # (Removed redundant recalculation to streamline workflow)

            position_value = shares * current_price

            # PDF-COMPLIANT STOP-LOSS VARIANTS
            is_earnings_season = self._is_earnings_season()

            if stop_variant == 1:
                # Variant 1: 50% ATR below entry (tighter stops)
                atr_multiplier = 0.5
                stop_description = "50% ATR (Variant 1)"
            else:
                # Variant 2: 150% ATR below entry (wider buffer)
                atr_multiplier = 1.5
                stop_description = "150% ATR (Variant 2)"

            # Adjust for earnings season (PDF recommends tighter stops)
            if is_earnings_season:
                # Earnings season: use 50% ATR regardless of variant
                atr_multiplier = 0.5
                stop_description += " - Earnings Season"

            stop_loss_price = current_price - (market_data.atr_14 * atr_multiplier)

            # UNIFIED TAKE-PROFIT STRATEGY (fixed inconsistency)
            # High conviction (≥7): 50% ATR stop, no TP, EOD exit
            # Medium conviction (6-7): 50% ATR stop, 150% ATR TP
            # Low conviction (<6): 150% ATR stop, 100% ATR TP
            take_profit_price = None
            take_profit_description = "EOD Exit Only"

            if strategy_score >= 7:
                # HIGH CONVICTION: No fixed TP, let big winners run until EOD
                take_profit_price = None
                take_profit_description = "High Conviction - EOD Exit Only (No TP)"
                self.logger.info(f"🔥 High conviction trade: Letting {symbol} run until EOD")

            elif strategy_score >= 6:
                # MEDIUM CONVICTION: TP at 150% ATR
                tp_multiplier = 1.5
                take_profit_price = current_price + (market_data.atr_14 * tp_multiplier)
                take_profit_description = f"Medium Conviction - 150% ATR Take-Profit"

            else:
                # LOW CONVICTION: TP at 100% ATR (conservative)
                tp_multiplier = 1.0
                take_profit_price = current_price + (market_data.atr_14 * tp_multiplier)
                take_profit_description = f"Low Conviction - 100% ATR Take-Profit"

            # Earnings season adjustment (if using fixed TP)
            if is_earnings_season and take_profit_price is not None and strategy_score < 7:
                # During earnings, be more aggressive with TP (only applies to medium/low conviction)
                if strategy_score >= 6:
                    tp_multiplier = 1.0  # Reduce 150% to 100% ATR for earnings
                else:
                    tp_multiplier = 0.75  # Reduce 100% to 75% ATR for earnings

                take_profit_price = current_price + (market_data.atr_14 * tp_multiplier)
                take_profit_description += f" (Earnings Adjusted: {tp_multiplier*100:.0f}% ATR)"

            # Place market buy order using proper MarketOrderRequest
            market_order_data = MarketOrderRequest(
                symbol=symbol,
                qty=shares,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY
            )
            order = self.trading_client.submit_order(order_data=market_order_data)

            # Create enhanced trade record with PDF strategy details
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

            # Enhanced logging per PDF requirements
            risk_amount = (current_price - stop_loss_price) * shares
            self.logger.info(f"")
            self.logger.info(f"🎯 PDF-COMPLIANT BUY ORDER PLACED:")
            self.logger.info(f"   Symbol: {symbol}")
            self.logger.info(f"   Shares: {shares} @ ${current_price:.2f} = ${position_value:.2f}")
            self.logger.info(f"   Stop-Loss: ${stop_loss_price:.2f} ({stop_description})")
            self.logger.info(f"   Take-Profit: {take_profit_description}")
            if take_profit_price:
                self.logger.info(f"                ${take_profit_price:.2f}")
            self.logger.info(f"   Risk Amount: ${risk_amount:.2f}")
            self.logger.info(f"   ATR: ${market_data.atr_14:.2f}")
            self.logger.info(f"   Earnings Season: {is_earnings_season}")
            self.logger.info(f"")

            return trade_record

        except Exception as e:
            self.logger.error(f"Error placing PDF-compliant buy order for {symbol}: {e}")
            return None

    def place_sell_order(self, symbol: str, shares: float, reason: str = "MANUAL") -> bool:
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
            # Place market sell order using proper MarketOrderRequest
            market_order_data = MarketOrderRequest(
                symbol=symbol,
                qty=shares,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            order = self.trading_client.submit_order(order_data=market_order_data)

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

                # Get current price - use our market data method
                try:
                    market_data = self.get_market_data(symbol)
                    if market_data:
                        current_price = market_data.close_price
                    else:
                        continue
                except:
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
            positions = self.trading_client.get_all_positions()

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

    def get_scaling_factor(self) -> float:
        """
        Calculate current risk scaling factor based on performance
        PDF Strategy: "grow exposure slowly: start smaller and increase size by ~10% per month of success"

        Returns:
            Scaling factor to apply to base risk percentage (1.0 = no scaling)
        """
        try:
            from database_manager import DatabaseManager
            # Note: This would typically be injected, but for now we'll access it
            # In a production system, pass DatabaseManager in the constructor

            # Get performance for last 30 days
            performance = self.get_portfolio_performance()
            if not performance or performance.get('days_tracked', 0) < self.scaling_config['evaluation_period_days']:
                self.logger.info("Insufficient data for scaling evaluation, using base risk")
                return 1.0

            # Get trade statistics (would need to pass db_manager for this)
            # For now, use portfolio performance as proxy
            total_return = performance.get('total_return_percent', 0)
            sharpe_ratio = performance.get('sharpe_ratio', 0)

            # Scaling logic per PDF guidelines
            scaling_factor = 1.0

            if total_return > 0 and sharpe_ratio > 0.5:
                # Positive performance: scale up gradually
                # 10% growth per month of success
                months_of_success = min(total_return / 5, 12)  # Cap at 12 months equivalent
                scaling_factor = 1.0 + (self.scaling_config['monthly_growth_rate'] * months_of_success)

            elif total_return < self.scaling_config['scale_down_loss_threshold']:
                # Significant losses: scale down
                scaling_factor = 0.8  # Reduce risk by 20%

            # Cap scaling factor
            max_scaling = self.scaling_config['max_risk_percent'] / self.scaling_config['base_risk_percent']
            scaling_factor = min(scaling_factor, max_scaling)
            scaling_factor = max(scaling_factor, 0.5)  # Never scale below 50%

            self.logger.info(f"📊 Risk Scaling Analysis:")
            self.logger.info(f"   30-day return: {total_return:.2f}%")
            self.logger.info(f"   Sharpe ratio: {sharpe_ratio:.2f}")
            self.logger.info(f"   Scaling factor: {scaling_factor:.2f}")
            self.logger.info(f"   Effective risk: {self.scaling_config['base_risk_percent'] * scaling_factor * 100:.2f}%")

            return scaling_factor

        except Exception as e:
            self.logger.error(f"Error calculating scaling factor: {e}")
            return 1.0  # Default to no scaling on error

    def _calculate_cluster_risk_boost(self, cluster_details: dict) -> float:
        """
        Calculate cluster risk boost with diminishing returns

        Prevents mega-clusters (CFO+COO+CEO) from always hitting 2% cap
        Uses diminishing returns for sophisticated risk management

        Enhanced Granularity (v2024.9.2):
        - 2 insiders: +0.5% (base cluster boost)
        - 3 insiders: +0.5% + 0.25% = +0.75%
        - 4+ insiders: +0.5% + 0.25% + 0.25% = +1.0% (improved from +0.85%)

        Args:
            cluster_details: Dict with cluster information including insider_count

        Returns:
            Risk boost percentage (e.g., 0.005 = 0.5%)
        """
        try:
            if not cluster_details or not cluster_details.get('is_cluster', False):
                return 0.0

            insider_count = cluster_details.get('insider_count', 0)
            symbol = cluster_details.get('symbol', 'Unknown')

            # Diminishing returns calculation
            if insider_count == 2:
                cluster_boost = 0.005  # +0.5%
                boost_description = "2 insiders: +0.5%"
            elif insider_count == 3:
                cluster_boost = 0.0075  # +0.75% (0.5% + 0.25%)
                boost_description = "3 insiders: +0.75%"
            elif insider_count >= 4:
                cluster_boost = 0.010  # +1.0% (0.5% + 0.25% + 0.25%)
                boost_description = f"{insider_count} insiders: +1.0%"
            else:
                cluster_boost = 0.0  # Shouldn't happen if is_cluster is True
                boost_description = f"{insider_count} insiders: no boost"

            self.logger.info(f"🎯 Cluster boost calculation: {boost_description}")
            return cluster_boost

        except Exception as e:
            self.logger.error(f"Error calculating cluster risk boost: {e}")
            return 0.005  # Default to base cluster boost

    def evaluate_scaling_performance(self, db_manager) -> Dict[str, Any]:
        """
        Enhanced scaling evaluation with 3-month rolling window analysis
        Prevents "hot streaks" from leading to premature risk increases

        Requires:
        - ≥60% win rate + profitable across 3 rolling months
        - Consistent performance (no monthly drawdown >15%)
        - Minimum trade activity per month

        Args:
            db_manager: DatabaseManager instance for trade data

        Returns:
            Performance evaluation with scaling recommendations
        """
        try:
            # Get 3-month rolling performance data
            performance_3m = db_manager.get_performance_summary(self.scaling_config['evaluation_period_days'])

            if not performance_3m or performance_3m.get('total_trades', 0) < self.scaling_config['min_trades_for_evaluation']:
                return {
                    'scaling_recommendation': 'HOLD',
                    'reason': f'Insufficient trades for 3-month evaluation (need {self.scaling_config["min_trades_for_evaluation"]}, have {performance_3m.get("total_trades", 0)})',
                    'current_scaling': 1.0,
                    'performance_3m': performance_3m
                }

            # Analyze month-by-month performance for consistency
            monthly_analysis = self._analyze_monthly_consistency(db_manager)

            if not monthly_analysis['sufficient_data']:
                return {
                    'scaling_recommendation': 'HOLD',
                    'reason': monthly_analysis['reason'],
                    'current_scaling': 1.0,
                    'monthly_analysis': monthly_analysis
                }

            # Overall 3-month metrics
            total_trades_3m = performance_3m.get('total_trades', 0)
            win_rate_3m = performance_3m.get('win_rate', 0) / 100  # Convert to decimal
            total_pnl_3m = performance_3m.get('total_pnl', 0)
            avg_pnl_percent_3m = performance_3m.get('avg_pnl_percent', 0)

            # ENHANCED SCALING CRITERIA (3-month rolling)
            meets_win_rate = win_rate_3m >= self.scaling_config['min_win_rate_for_scaling']
            is_profitable = total_pnl_3m > 0
            avg_loss_acceptable = avg_pnl_percent_3m > -2.4  # PDF notes average loss ~2.4%
            months_profitable = monthly_analysis['profitable_months']
            required_months = self.scaling_config['required_profitable_months']
            max_monthly_drawdown = monthly_analysis['max_monthly_drawdown']
            consistent_activity = monthly_analysis['consistent_activity']

            # Decision logic with enhanced criteria
            if (meets_win_rate and is_profitable and avg_loss_acceptable and
                months_profitable >= required_months and
                max_monthly_drawdown <= 0.15 and  # No month with >15% loss
                consistent_activity):

                recommendation = 'SCALE_UP'
                scaling_adjustment = 1.0 + self.scaling_config['monthly_growth_rate']
                reason = (f"Sustained excellence: {win_rate_3m:.1%} win rate over 3 months, "
                         f"{months_profitable}/{required_months} profitable months, "
                         f"max drawdown {max_monthly_drawdown:.1%}")

            elif max_monthly_drawdown > 0.15:  # Any month with >15% loss
                recommendation = 'SCALE_DOWN'
                scaling_adjustment = 0.8
                reason = f"High monthly drawdown detected: {max_monthly_drawdown:.1%} > 15% threshold"

            elif total_pnl_3m < 0:  # Overall unprofitable
                recommendation = 'SCALE_DOWN'
                scaling_adjustment = 0.8
                reason = f"3-month unprofitability: ${total_pnl_3m:.2f} total P&L"

            elif months_profitable < required_months:
                recommendation = 'HOLD'
                scaling_adjustment = 1.0
                reason = (f"Inconsistent profitability: only {months_profitable}/{required_months} "
                         f"profitable months")

            else:
                recommendation = 'HOLD'
                scaling_adjustment = 1.0
                reason = "Good performance but not meeting all scaling criteria"

            return {
                'scaling_recommendation': recommendation,
                'scaling_adjustment': scaling_adjustment,
                'reason': reason,
                'performance_metrics_3m': {
                    'total_trades': total_trades_3m,
                    'win_rate': f"{win_rate_3m:.1%}",
                    'total_pnl': total_pnl_3m,
                    'avg_pnl_percent': avg_pnl_percent_3m,
                    'profitable_months': f"{months_profitable}/{required_months}",
                    'max_monthly_drawdown': f"{max_monthly_drawdown:.1%}",
                    'consistent_activity': consistent_activity,
                    'meets_all_criteria': {
                        'win_rate': meets_win_rate,
                        'profitable': is_profitable,
                        'loss_acceptable': avg_loss_acceptable,
                        'sufficient_profitable_months': months_profitable >= required_months,
                        'acceptable_drawdowns': max_monthly_drawdown <= 0.15,
                        'consistent_activity': consistent_activity
                    }
                },
                'monthly_breakdown': monthly_analysis['monthly_details']
            }

        except Exception as e:
            self.logger.error(f"Error evaluating 3-month scaling performance: {e}")
            return {
                'scaling_recommendation': 'HOLD',
                'reason': f'Evaluation error: {e}',
                'current_scaling': 1.0
            }

    def _analyze_monthly_consistency(self, db_manager) -> Dict[str, Any]:
        """
        Analyze month-by-month performance consistency
        Required for robust 3-month scaling evaluation

        Args:
            db_manager: DatabaseManager instance

        Returns:
            Dictionary with monthly consistency analysis
        """
        try:
            from datetime import datetime, timedelta

            # Analyze last 3 months individually
            monthly_details = []
            profitable_months = 0
            max_monthly_drawdown = 0.0
            consistent_activity = True

            for month_offset in range(3):
                # Calculate date range for this month (30-day periods)
                end_date = datetime.now() - timedelta(days=month_offset * 30)
                start_date = end_date - timedelta(days=30)

                # This would require a more sophisticated database query
                # For now, we'll use the existing method with different time windows
                if month_offset == 0:
                    month_perf = db_manager.get_performance_summary(30)
                elif month_offset == 1:
                    month_perf = db_manager.get_performance_summary(60)  # Days 30-60
                    # Subtract month 0 performance to get month 1 only
                    month_0_perf = db_manager.get_performance_summary(30)
                    if month_perf and month_0_perf:
                        month_perf = {
                            'total_trades': month_perf.get('total_trades', 0) - month_0_perf.get('total_trades', 0),
                            'total_pnl': month_perf.get('total_pnl', 0) - month_0_perf.get('total_pnl', 0),
                            'win_rate': month_perf.get('win_rate', 0)  # Approximation
                        }
                else:  # month_offset == 2
                    month_perf = db_manager.get_performance_summary(90)  # Days 60-90
                    month_60_perf = db_manager.get_performance_summary(60)
                    if month_perf and month_60_perf:
                        month_perf = {
                            'total_trades': month_perf.get('total_trades', 0) - month_60_perf.get('total_trades', 0),
                            'total_pnl': month_perf.get('total_pnl', 0) - month_60_perf.get('total_pnl', 0),
                            'win_rate': month_perf.get('win_rate', 0)  # Approximation
                        }

                if not month_perf:
                    month_details = {
                        'month': f"Month-{month_offset + 1}",
                        'trades': 0,
                        'pnl': 0,
                        'profitable': False,
                        'sufficient_activity': False
                    }
                else:
                    trades = month_perf.get('total_trades', 0)
                    pnl = month_perf.get('total_pnl', 0)
                    is_profitable = pnl > 0

                    month_details = {
                        'month': f"Month-{month_offset + 1}",
                        'trades': trades,
                        'pnl': pnl,
                        'profitable': is_profitable,
                        'sufficient_activity': trades >= self.scaling_config['min_trades_per_month']
                    }

                    if is_profitable:
                        profitable_months += 1

                    # Track maximum monthly loss
                    if pnl < 0:
                        # Estimate monthly drawdown (simplified)
                        monthly_loss_percent = abs(pnl) / 10000  # Rough approximation
                        max_monthly_drawdown = max(max_monthly_drawdown, monthly_loss_percent)

                    if not month_details['sufficient_activity']:
                        consistent_activity = False

                monthly_details.append(month_details)

            # Determine if we have sufficient data for evaluation
            total_months_with_data = sum(1 for month in monthly_details if month['trades'] > 0)
            sufficient_data = total_months_with_data >= 2  # Need at least 2 months of data

            if not sufficient_data:
                reason = f"Insufficient monthly data: only {total_months_with_data}/3 months have trades"
            elif not consistent_activity:
                reason = f"Inconsistent activity: need ≥{self.scaling_config['min_trades_per_month']} trades/month"
            else:
                reason = "Sufficient data for evaluation"

            return {
                'sufficient_data': sufficient_data,
                'reason': reason,
                'profitable_months': profitable_months,
                'max_monthly_drawdown': max_monthly_drawdown,
                'consistent_activity': consistent_activity,
                'monthly_details': monthly_details,
                'total_months_analyzed': len(monthly_details)
            }

        except Exception as e:
            self.logger.error(f"Error analyzing monthly consistency: {e}")
            return {
                'sufficient_data': False,
                'reason': f'Error in monthly analysis: {e}',
                'profitable_months': 0,
                'max_monthly_drawdown': 1.0,  # Conservative assumption
                'consistent_activity': False,
                'monthly_details': []
            }

    def get_order_history(self, status: str = None, limit: int = 100) -> List[Dict]:
        """Get order history"""
        try:
            orders = self.trading_client.get_orders(
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
            # Get portfolio history using proper request pattern
            history_request = GetPortfolioHistoryRequest(
                period='1M',  # 1 month
                timeframe='1D'  # Daily
            )
            portfolio_history = self.trading_client.get_portfolio_history(history_request)

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
            clock = self.trading_client.get_clock()
            return {
                'is_open': clock.is_open,
                'next_open': clock.next_open.isoformat(),
                'next_close': clock.next_close.isoformat(),
                'timezone': str(clock.timezone)
            }
        except Exception as e:
            self.logger.error(f"Error getting market hours: {e}")
            return {
                'is_open': False,
                'next_open': None,
                'next_close': None,
                'timezone': 'US/Eastern'
            }

    def get_trading_window_status(self) -> Dict[str, Any]:
        """
        Enhanced market timing analysis for WSV strategy

        WSV Strategy Rules:
        - Enter at market open the day after detection
        - Don't chase in after-hours/premarket (thin liquidity, high spreads)
        - Queue trades for next open if detected outside regular hours
        - Exit same day by market close

        Returns:
            Dict with detailed trading window information
        """
        try:
            from datetime import datetime
            import pytz

            # Get current market status
            clock = self.trading_client.get_clock()

            # Convert to Eastern Time (market timezone) and local timezone
            et_tz = pytz.timezone('US/Eastern')
            current_time = datetime.now(et_tz)

            # Also get current time in Spain (CET/CEST) for user reference
            spain_tz = pytz.timezone('Europe/Madrid')
            spain_time = datetime.now(spain_tz)

            # Parse market open/close times
            next_open = clock.next_open.astimezone(et_tz)
            next_close = clock.next_close.astimezone(et_tz)

            # Determine current trading window
            is_market_open = clock.is_open

            # Define trading windows (all times in ET)
            regular_hours_start = current_time.replace(hour=9, minute=30, second=0, microsecond=0)
            regular_hours_end = current_time.replace(hour=16, minute=0, second=0, microsecond=0)
            after_hours_end = current_time.replace(hour=20, minute=0, second=0, microsecond=0)
            premarket_start = current_time.replace(hour=4, minute=0, second=0, microsecond=0)

            # Determine current window
            if is_market_open and regular_hours_start <= current_time <= regular_hours_end:
                window = "REGULAR_HOURS"
                action = "TRADE_NOW"
                reason = "Market is open - execute trades immediately"

            elif regular_hours_end < current_time <= after_hours_end:
                window = "AFTER_HOURS"
                action = "QUEUE_FOR_NEXT_OPEN"
                reason = "After-hours detected - queue for next market open (WSV strategy)"

            elif after_hours_end < current_time or current_time < premarket_start:
                window = "OVERNIGHT"
                action = "QUEUE_FOR_NEXT_OPEN"
                reason = "Overnight period - queue for next market open"

            elif premarket_start <= current_time < regular_hours_start:
                window = "PREMARKET"
                action = "QUEUE_FOR_NEXT_OPEN"
                reason = "Premarket detected - wait for official open (avoid thin liquidity)"

            else:
                window = "UNKNOWN"
                action = "QUEUE_FOR_NEXT_OPEN"
                reason = "Unknown trading window - default to queue"

            # Calculate minutes until next action
            if action == "TRADE_NOW":
                minutes_until_action = 0
                next_action_time = current_time
            else:
                minutes_until_action = int((next_open - current_time).total_seconds() / 60)
                next_action_time = next_open

            # Calculate minutes until market close (for same-day exit rule)
            if is_market_open:
                minutes_until_close = int((next_close - current_time).total_seconds() / 60)
            else:
                # If market is closed, next close is tomorrow's close
                tomorrow_close = next_close
                minutes_until_close = int((tomorrow_close - current_time).total_seconds() / 60)

            result = {
                'current_window': window,
                'recommended_action': action,
                'reason': reason,
                'is_market_open': is_market_open,
                'current_time_et': current_time.strftime('%Y-%m-%d %H:%M:%S %Z'),
                'current_time_spain': spain_time.strftime('%Y-%m-%d %H:%M:%S %Z'),
                'next_open': next_open.strftime('%Y-%m-%d %H:%M:%S %Z'),
                'next_open_spain': next_open.astimezone(spain_tz).strftime('%Y-%m-%d %H:%M:%S %Z'),
                'next_close': next_close.strftime('%Y-%m-%d %H:%M:%S %Z'),
                'next_close_spain': next_close.astimezone(spain_tz).strftime('%Y-%m-%d %H:%M:%S %Z'),
                'minutes_until_action': minutes_until_action,
                'minutes_until_close': minutes_until_close,
                'next_action_time': next_action_time.strftime('%Y-%m-%d %H:%M:%S %Z'),
                'next_action_time_spain': next_action_time.astimezone(spain_tz).strftime('%Y-%m-%d %H:%M:%S %Z'),
                'wsv_compliant': True  # Always true when using this method
            }

            self.logger.info(f"🕒 Trading Window Analysis:")
            self.logger.info(f"   Current window: {window}")
            self.logger.info(f"   Recommended action: {action}")
            self.logger.info(f"   Reason: {reason}")
            self.logger.info(f"   Current time: {current_time.strftime('%H:%M %Z')} / {spain_time.strftime('%H:%M %Z')} (Spain)")
            self.logger.info(f"   Next action in: {minutes_until_action} minutes")
            if action == "QUEUE_FOR_NEXT_OPEN":
                next_open_spain = next_open.astimezone(spain_tz)
                self.logger.info(f"   Next market open: {next_open.strftime('%H:%M %Z')} / {next_open_spain.strftime('%H:%M %Z')} (Spain)")

            return result

        except Exception as e:
            self.logger.error(f"Error analyzing trading window: {e}")
            # Conservative fallback
            return {
                'current_window': 'UNKNOWN',
                'recommended_action': 'QUEUE_FOR_NEXT_OPEN',
                'reason': f'Error in window analysis: {e}',
                'is_market_open': False,
                'minutes_until_action': 0,
                'minutes_until_close': 0,
                'wsv_compliant': False
            }

    def should_execute_trade_now(self) -> bool:
        """
        Simple boolean check if trades should execute immediately
        Based on WSV strategy timing rules

        Returns:
            True if in regular trading hours, False if should queue
        """
        try:
            window_status = self.get_trading_window_status()
            return window_status['recommended_action'] == 'TRADE_NOW'
        except Exception as e:
            self.logger.error(f"Error checking trade execution timing: {e}")
            return False  # Conservative: don't execute on error

    def queue_trade_for_next_open(self, signal_data: Dict, enhanced_strategy_score: int,
                                 has_insider_cluster: bool) -> bool:
        """
        Queue a trade for execution at next market open (WSV strategy)

        WSV Rule: "Enter at market open the day after detection"
        - Queues trade with all signal data preserved
        - Will execute when market opens using standard risk/stop/TP rules
        - Maintains same-day exit rule even if entry was delayed

        Args:
            signal_data: Original signal data from strategy engine
            enhanced_strategy_score: Score after role weighting applied
            has_insider_cluster: Whether this is a cluster buy signal

        Returns:
            True if successfully queued
        """
        try:
            from datetime import datetime

            # Get next market open time
            window_status = self.get_trading_window_status()
            next_open_time = window_status.get('next_action_time', 'Unknown')

            # Create queued trade record
            queued_trade = {
                'queue_id': f"queue_{signal_data['symbol']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                'symbol': signal_data['symbol'],
                'filing_id': signal_data['filing_id'],
                'original_strategy_score': signal_data['total_score'],
                'enhanced_strategy_score': enhanced_strategy_score,
                'has_insider_cluster': has_insider_cluster,
                'signal_data': signal_data,
                'queue_timestamp': datetime.now().isoformat(),
                'scheduled_execution': next_open_time,
                'queue_reason': window_status.get('reason', 'Outside regular hours'),
                'current_window': window_status.get('current_window', 'UNKNOWN'),
                'status': 'QUEUED',
                'wsv_compliant': True
            }

            # Store in database (would need to extend database schema)
            # For now, store in trader instance for immediate implementation
            if not hasattr(self, 'queued_trades'):
                self.queued_trades = []

            self.queued_trades.append(queued_trade)

            self.logger.info(f"📋 Trade Queued for Next Open:")
            self.logger.info(f"   Symbol: {signal_data['symbol']}")
            self.logger.info(f"   Enhanced Score: {enhanced_strategy_score} (orig: {signal_data['total_score']})")
            self.logger.info(f"   Cluster Buy: {has_insider_cluster}")
            self.logger.info(f"   Scheduled for: {next_open_time}")
            self.logger.info(f"   Queue Reason: {window_status.get('reason')}")
            self.logger.info(f"   Queue ID: {queued_trade['queue_id']}")

            return True

        except Exception as e:
            self.logger.error(f"Error queuing trade for {signal_data.get('symbol', 'unknown')}: {e}")
            return False

    def execute_queued_trades(self) -> Dict[str, Any]:
        """
        Execute trades queued for market open (WSV strategy implementation)

        Called at market open to process all queued trades
        Applies all standard rules: SPY filter, tier limits, risk sizing, etc.

        Returns:
            Dict with execution results
        """
        try:
            # Check if we should execute now
            if not self.should_execute_trade_now():
                return {
                    'trades_executed': 0,
                    'reason': 'Market not open for execution',
                    'queued_count': len(getattr(self, 'queued_trades', []))
                }

            # Get queued trades
            queued_trades = getattr(self, 'queued_trades', [])
            if not queued_trades:
                return {
                    'trades_executed': 0,
                    'reason': 'No trades in queue',
                    'queued_count': 0
                }

            executed_count = 0
            failed_count = 0
            skipped_count = 0
            execution_results = []

            self.logger.info(f"🚀 Executing {len(queued_trades)} queued trades at market open")

            for queued_trade in queued_trades.copy():  # Copy to allow modification during iteration
                try:
                    symbol = queued_trade['symbol']
                    signal_data = queued_trade['signal_data']
                    enhanced_score = queued_trade['enhanced_strategy_score']
                    has_cluster = queued_trade['has_insider_cluster']

                    self.logger.info(f"🎯 Processing queued trade: {symbol}")

                    # Apply all standard trade execution logic
                    # (This would call the same execution path as immediate trades)

                    # 1. SPY filter check
                    spy_condition = self.get_enhanced_spy_condition(
                        symbol=symbol,
                        has_insider_cluster=has_cluster
                    )

                    if not spy_condition['trading_allowed']:
                        self.logger.info(f"❌ SPY Filter blocked queued trade: {symbol} - {spy_condition['reason']}")
                        skipped_count += 1
                        execution_results.append({
                            'symbol': symbol,
                            'status': 'SKIPPED',
                            'reason': f"SPY filter: {spy_condition['reason']}"
                        })
                        continue

                    # 2. Get market data
                    market_data = self.get_market_data(symbol)
                    if not market_data:
                        self.logger.warning(f"No market data for queued trade: {symbol}")
                        failed_count += 1
                        execution_results.append({
                            'symbol': symbol,
                            'status': 'FAILED',
                            'reason': 'No market data available'
                        })
                        continue

                    # 3. Calculate position size with all enhancements
                    # UNIFIED STOP VARIANT LOGIC (fixed inconsistency)
                    if enhanced_score >= 6:
                        stop_variant = 1  # 50% ATR stop (for both high and medium conviction)
                    else:
                        stop_variant = 2  # 150% ATR stop (for low conviction only)

                    # 🔴 TIER 4 ATR OVERRIDE: Force wide stops for small cap volatility
                    tier_risk_multiplier = self._get_tier_risk_multiplier_for_queued(symbol)
                    if tier_risk_multiplier < 1.0:  # Tier 4 detected
                        if stop_variant == 1:
                            stop_variant = 2
                            self.logger.info(f"🔴 Tier 4 Override: Forcing queued {symbol} to use Variant 2 (150% ATR) for volatility buffer")

                    # Reconstruct cluster details for queued trade (needed for enhanced cluster boost)
                    if has_cluster:
                        # For queued trades, we need to reconstruct cluster details
                        # This is a limitation of the current queued trade storage format
                        cluster_details = {
                            'is_cluster': True,
                            'insider_count': 2,  # Conservative default for queued trades
                            'insiders_list': [],
                            'analysis_date': signal_data.get('analysis_date', '')
                        }
                    else:
                        cluster_details = None

                    shares = self.calculate_position_size(
                        symbol, enhanced_score, market_data.close_price, market_data, stop_variant, cluster_details
                    )

                    # 4. Apply risk multipliers (SPY + Tier 4)
                    spy_risk_multiplier = spy_condition.get('risk_multiplier', 1.0)
                    combined_multiplier = spy_risk_multiplier * tier_risk_multiplier

                    if combined_multiplier < 1.0:
                        shares = int(shares * combined_multiplier)

                    if shares <= 0:
                        failed_count += 1
                        execution_results.append({
                            'symbol': symbol,
                            'status': 'FAILED',
                            'reason': 'Invalid position size'
                        })
                        continue

                    # 5. Sector concentration check
                    if not self.check_sector_concentration_limits(symbol, enhanced_score):
                        skipped_count += 1
                        execution_results.append({
                            'symbol': symbol,
                            'status': 'SKIPPED',
                            'reason': 'Sector concentration limit (max 1 high conviction per sector)'
                        })
                        continue

                    # 6. Execute the trade
                    trade_record = self.place_buy_order(
                        symbol, shares, enhanced_score, signal_data['filing_id'], stop_variant
                    )

                    if trade_record:
                        executed_count += 1
                        execution_results.append({
                            'symbol': symbol,
                            'status': 'EXECUTED',
                            'shares': shares,
                            'trade_id': trade_record.trade_id
                        })
                        self.logger.info(f"✅ Queued trade executed: {symbol} - {shares} shares")
                    else:
                        failed_count += 1
                        execution_results.append({
                            'symbol': symbol,
                            'status': 'FAILED',
                            'reason': 'Order placement failed'
                        })

                except Exception as e:
                    self.logger.error(f"Error executing queued trade for {queued_trade.get('symbol', 'unknown')}: {e}")
                    failed_count += 1
                    execution_results.append({
                        'symbol': queued_trade.get('symbol', 'unknown'),
                        'status': 'FAILED',
                        'reason': f'Execution error: {e}'
                    })

            # Clear executed/processed trades from queue
            self.queued_trades = []

            result = {
                'trades_executed': executed_count,
                'trades_failed': failed_count,
                'trades_skipped': skipped_count,
                'total_processed': len(queued_trades),
                'execution_results': execution_results,
                'execution_time': datetime.now().isoformat()
            }

            self.logger.info(f"📊 Queued Trade Execution Summary:")
            self.logger.info(f"   ✅ Executed: {executed_count}")
            self.logger.info(f"   ❌ Failed: {failed_count}")
            self.logger.info(f"   ⏭️ Skipped: {skipped_count}")
            self.logger.info(f"   📋 Total: {len(queued_trades)}")

            return result

        except Exception as e:
            self.logger.error(f"Error executing queued trades: {e}")
            return {
                'trades_executed': 0,
                'trades_failed': 0,
                'trades_skipped': 0,
                'error': str(e)
            }

    def get_queued_trades_count(self) -> int:
        """Get number of trades currently queued"""
        return len(getattr(self, 'queued_trades', []))

    def clear_expired_queued_trades(self) -> int:
        """
        Clear queued trades that missed their intended market open (next open only)

        WSV Strategy: Alpha decays after first trading day. If a trade was queued for
        a market open that has already passed, drop it rather than executing late.

        Returns:
            Number of trades cleared
        """
        try:
            from datetime import datetime

            if not hasattr(self, 'queued_trades'):
                return 0

            if len(self.queued_trades) == 0:
                return 0

            # Get current market status
            window_status = self.get_trading_window_status()
            current_market_open = window_status.get('next_open')  # Next market open timestamp
            original_count = len(self.queued_trades)

            # Filter out trades that missed their scheduled execution window
            valid_trades = []

            for trade in self.queued_trades:
                scheduled_execution = trade.get('scheduled_execution', 'Unknown')

                # If this trade was scheduled for a previous market open, it's expired
                # Compare scheduled execution with current next open - if different, trade is stale
                if scheduled_execution != current_market_open and scheduled_execution != 'Unknown':
                    # This trade was for a previous market session - drop it
                    symbol = trade.get('symbol', 'Unknown')
                    self.logger.info(f"🗑️ Dropping expired queued trade: {symbol} (was scheduled for {scheduled_execution}, current open: {current_market_open})")
                else:
                    # Trade is still valid for current/next open
                    valid_trades.append(trade)

            self.queued_trades = valid_trades
            cleared_count = original_count - len(self.queued_trades)

            if cleared_count > 0:
                self.logger.info(f"🧹 Cleared {cleared_count} expired queued trades (missed execution window)")

            return cleared_count

        except Exception as e:
            self.logger.error(f"Error clearing expired queued trades: {e}")
            return 0