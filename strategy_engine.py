"""
Strategy Engine for Insider Trading Bot
Implements the validated scoring and decision logic based on academic research and WSV strategy.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd

from database_manager import DatabaseManager, InsiderFiling, MarketData, StrategyScore
from alpaca_trader import AlpacaTrader

class StrategyEngine:
    """
    Implements insider trading momentum strategy with validated scoring criteria

    Based on:
    - WSV Trading Mastery Strategy
    - Academic research on CFO vs CEO purchase predictive power
    - ATR-based risk management research
    - Volume and liquidity filters
    """

    def __init__(self, db_manager: DatabaseManager, trader: AlpacaTrader):
        """
        Initialize strategy engine

        Args:
            db_manager: Database manager instance
            trader: Alpaca trader instance
        """
        self.db_manager = db_manager
        self.trader = trader
        self.logger = logging.getLogger(__name__)

        # Strategy configuration based on PDF and research
        self.config = {
            # Volume filters (daily average volume in USD)
            'earnings_season_volume_min': 30_000_000,   # $30M min
            'earnings_season_volume_max': 100_000_000,  # $100M max
            'year_round_volume_min': 30_000_000,        # $30M min
            'year_round_volume_max': 10_000_000_000,    # $10B max

            # ATR filters (percentage of price)
            'earnings_season_atr_min': 3.5,  # 3.5% minimum
            'year_round_atr_min': 7.0,       # 7% minimum
            'year_round_atr_max': 20.0,      # 20% maximum

            # Transaction size filters
            'min_transaction_value': 50_000,   # $50k minimum
            'large_transaction_value': 100_000, # $100k for bonus

            # Multi-insider detection window
            'multi_insider_window_hours': 24,  # Same day = 24 hours

            # Repeat purchase detection
            'repeat_purchase_window_days': 30,

            # Scoring thresholds
            'buy_threshold': 5,     # Minimum score for BUY decision
            'high_conviction_threshold': 7,  # High conviction threshold

            # SPY gap filter
            'spy_gap_threshold': 0.5,  # ±0.5% gap threshold
        }

    def analyze_insider_filing(self, filing: InsiderFiling, market_data: MarketData) -> StrategyScore:
        """
        Analyze an insider filing and generate strategy score

        Args:
            filing: Insider filing data
            market_data: Current market data for the stock

        Returns:
            StrategyScore with detailed analysis
        """
        try:
            self.logger.info(f"Analyzing filing: {filing.filing_id}")

            # Initialize scoring components
            insider_role_score = self._score_insider_role(filing.insider_title)
            ownership_type_score = self._score_ownership_type(filing.ownership_type)
            transaction_size_score = self._score_transaction_size(filing.total_value)

            # Filter checks
            volume_filter_passed = self._check_volume_filter(market_data)
            atr_filter_passed = self._check_atr_filter(market_data)
            spy_filter_passed = self._check_spy_filter()

            # Bonus scoring
            earnings_season_bonus = self._get_earnings_season_bonus()
            multi_insider_bonus = self._get_multi_insider_bonus(filing)

            # Check for repeat purchases
            is_repeat_purchase = self._is_repeat_purchase(filing)

            # Calculate total score
            total_score = (
                insider_role_score +
                ownership_type_score +
                transaction_size_score +
                earnings_season_bonus +
                multi_insider_bonus
            )

            # Make decision
            decision, confidence_level = self._make_trading_decision(
                total_score, volume_filter_passed, atr_filter_passed,
                spy_filter_passed, is_repeat_purchase
            )

            # Create strategy score object
            strategy_score = StrategyScore(
                filing_id=filing.filing_id,
                symbol=filing.company_symbol,
                total_score=total_score,
                insider_role_score=insider_role_score,
                ownership_type_score=ownership_type_score,
                transaction_size_score=transaction_size_score,
                volume_filter_passed=volume_filter_passed,
                atr_filter_passed=atr_filter_passed,
                spy_filter_passed=spy_filter_passed,
                earnings_season_bonus=earnings_season_bonus,
                multi_insider_bonus=multi_insider_bonus,
                decision=decision,
                confidence_level=confidence_level,
                analysis_date=datetime.now().strftime('%Y-%m-%d')
            )

            self._log_analysis_results(filing, strategy_score, market_data)

            # Send Telegram notification for BUY decisions
            if hasattr(self, 'telegram_notifier') and self.telegram_notifier and strategy_score.decision == 'BUY':
                try:
                    market_context = {
                        'current_price': market_data.close_price,
                        'volume': market_data.volume,
                        'atr_14': market_data.atr_14
                    }
                    self.telegram_notifier.notify_buy_decision(filing, strategy_score, market_context)
                    self.logger.info("📱 Telegram BUY notification sent")
                except Exception as e:
                    self.logger.error(f"Failed to send Telegram notification: {e}")

            return strategy_score

        except Exception as e:
            self.logger.error(f"Error analyzing filing {filing.filing_id}: {e}")
            # Return default SKIP decision on error
            return StrategyScore(
                filing_id=filing.filing_id,
                symbol=filing.company_symbol,
                total_score=0,
                insider_role_score=0,
                ownership_type_score=0,
                transaction_size_score=0,
                volume_filter_passed=False,
                atr_filter_passed=False,
                spy_filter_passed=False,
                earnings_season_bonus=0,
                multi_insider_bonus=0,
                decision='SKIP',
                confidence_level='LOW',
                analysis_date=datetime.now().strftime('%Y-%m-%d')
            )

    def _score_insider_role(self, insider_title: str) -> int:
        """
        Score based on insider role (research shows CFO > CEO > others)

        Args:
            insider_title: Insider's title/role

        Returns:
            Score (0-3)
        """
        title_lower = insider_title.lower()

        # CFO/COO get highest score (research validated)
        if any(role in title_lower for role in ['cfo', 'chief financial', 'coo', 'chief operating']):
            return 3

        # CEO/President get medium score
        if any(role in title_lower for role in ['ceo', 'chief executive', 'president']):
            return 2

        # Directors get low score
        if 'director' in title_lower:
            return 1

        # 10% owners, trustees, other officers
        if any(role in title_lower for role in ['10%', 'owner', 'trustee', 'officer', 'vice']):
            return 1

        return 0

    def _score_ownership_type(self, ownership_type: str) -> int:
        """
        Score based on ownership type (research shows indirect > direct)

        Args:
            ownership_type: 'D' for direct, 'I' for indirect

        Returns:
            Score (0-1)
        """
        # Research shows indirect purchases (trusts, family accounts) are more predictive
        return 1 if ownership_type == 'I' else 0

    def _score_transaction_size(self, total_value: float) -> int:
        """
        Score based on transaction size

        Args:
            total_value: Total transaction value in USD

        Returns:
            Score (0-2)
        """
        if total_value >= self.config['large_transaction_value']:
            return 2  # Large transactions show strong conviction
        elif total_value >= self.config['min_transaction_value']:
            return 1  # Medium transactions
        else:
            return 0  # Small transactions (should be filtered out earlier)

    def _check_volume_filter(self, market_data: MarketData) -> bool:
        """Check if stock meets volume requirements"""
        is_earnings_season = self._is_earnings_season()
        daily_volume_usd = market_data.avg_volume_30 * market_data.close_price

        if is_earnings_season:
            return (self.config['earnings_season_volume_min'] <=
                   daily_volume_usd <=
                   self.config['earnings_season_volume_max'])
        else:
            return (self.config['year_round_volume_min'] <=
                   daily_volume_usd <=
                   self.config['year_round_volume_max'])

    def _check_atr_filter(self, market_data: MarketData) -> bool:
        """Check if stock meets ATR (volatility) requirements"""
        atr_percent = (market_data.atr_14 / market_data.close_price) * 100
        is_earnings_season = self._is_earnings_season()

        if is_earnings_season:
            return atr_percent >= self.config['earnings_season_atr_min']
        else:
            return (self.config['year_round_atr_min'] <=
                   atr_percent <=
                   self.config['year_round_atr_max'])

    def _check_spy_filter(self) -> bool:
        """Check SPY gap filter"""
        try:
            trading_allowed, gap_percent = self.trader.get_spy_condition()

            # Update database with SPY condition
            self.db_manager.update_spy_condition(
                datetime.now().strftime('%Y-%m-%d'),
                0,  # Will be filled by trader
                0   # Will be filled by trader
            )

            return trading_allowed

        except Exception as e:
            self.logger.error(f"Error checking SPY filter: {e}")
            return True  # Default to allow trading

    def _get_earnings_season_bonus(self) -> int:
        """Get bonus points for earnings season"""
        return 1 if self._is_earnings_season() else 0

    def _get_multi_insider_bonus(self, filing: InsiderFiling) -> int:
        """
        Check for multiple insider purchases on the same day (high conviction signal)

        Args:
            filing: Current insider filing

        Returns:
            Bonus points (0-2)
        """
        try:
            # Look for other insider purchases on the same day
            same_day_purchases = self.db_manager.get_recent_insider_purchases(
                filing.company_symbol, days=1
            )

            # Filter for same transaction date
            filing_date = filing.transaction_date
            same_day_count = sum(
                1 for purchase in same_day_purchases
                if (purchase['transaction_date'] == filing_date and
                    purchase['insider_name'] != filing.insider_name)
            )

            if same_day_count >= 2:
                return 2  # 3+ insiders same day = very high conviction
            elif same_day_count >= 1:
                return 1  # 2 insiders same day = high conviction
            else:
                return 0

        except Exception as e:
            self.logger.error(f"Error checking multi-insider bonus: {e}")
            return 0

    def _is_repeat_purchase(self, filing: InsiderFiling) -> bool:
        """Check if this is a repeat purchase (should be filtered out)"""
        try:
            return self.db_manager.check_insider_repeat_purchase(
                filing.insider_name,
                filing.company_symbol,
                self.config['repeat_purchase_window_days']
            )
        except Exception as e:
            self.logger.error(f"Error checking repeat purchase: {e}")
            return False

    def _make_trading_decision(self, total_score: int, volume_filter: bool,
                             atr_filter: bool, spy_filter: bool,
                             is_repeat: bool) -> Tuple[str, str]:
        """
        Make final trading decision based on all criteria

        Args:
            total_score: Calculated strategy score
            volume_filter: Volume filter passed
            atr_filter: ATR filter passed
            spy_filter: SPY filter passed
            is_repeat: Is repeat purchase

        Returns:
            Tuple of (decision, confidence_level)
        """
        # Immediate disqualifiers
        if is_repeat:
            return 'SKIP', 'LOW'  # Never trade repeat purchases

        if not spy_filter:
            return 'SKIP', 'LOW'  # Skip on large SPY gaps

        # Must pass both volume and ATR filters
        if not (volume_filter and atr_filter):
            return 'PASS', 'LOW'

        # Score-based decisions
        if total_score >= self.config['high_conviction_threshold']:
            return 'BUY', 'HIGH'
        elif total_score >= self.config['buy_threshold']:
            return 'BUY', 'MEDIUM'
        else:
            return 'PASS', 'LOW'

    def _is_earnings_season(self) -> bool:
        """Check if current month is in earnings season"""
        current_month = datetime.now().month
        # Earnings seasons: February (2), May (5), August (8), November (11)
        return current_month in [2, 5, 8, 11]

    def _log_analysis_results(self, filing: InsiderFiling, score: StrategyScore,
                            market_data: MarketData) -> None:
        """Log detailed analysis results"""
        self.logger.info(f"=== Analysis Results for {filing.company_symbol} ===")
        self.logger.info(f"Insider: {filing.insider_name} ({filing.insider_title})")
        self.logger.info(f"Transaction: ${filing.total_value:,.0f} ({filing.shares_traded:,.0f} shares)")
        self.logger.info(f"Ownership Type: {'Indirect' if filing.ownership_type == 'I' else 'Direct'}")

        self.logger.info(f"Market Data:")
        self.logger.info(f"  Price: ${market_data.close_price:.2f}")
        self.logger.info(f"  ATR: ${market_data.atr_14:.2f} ({(market_data.atr_14/market_data.close_price)*100:.1f}%)")
        self.logger.info(f"  Volume: ${market_data.avg_volume_30 * market_data.close_price:,.0f} avg daily")

        self.logger.info(f"Scoring:")
        self.logger.info(f"  Insider Role: {score.insider_role_score}")
        self.logger.info(f"  Ownership Type: {score.ownership_type_score}")
        self.logger.info(f"  Transaction Size: {score.transaction_size_score}")
        self.logger.info(f"  Earnings Season Bonus: {score.earnings_season_bonus}")
        self.logger.info(f"  Multi-Insider Bonus: {score.multi_insider_bonus}")
        self.logger.info(f"  Total Score: {score.total_score}")

        self.logger.info(f"Filters:")
        self.logger.info(f"  Volume: {'PASS' if score.volume_filter_passed else 'FAIL'}")
        self.logger.info(f"  ATR: {'PASS' if score.atr_filter_passed else 'FAIL'}")
        self.logger.info(f"  SPY: {'PASS' if score.spy_filter_passed else 'FAIL'}")

        self.logger.info(f"DECISION: {score.decision} ({score.confidence_level} confidence)")
        self.logger.info("=" * 50)

    def process_unscored_filings(self) -> List[StrategyScore]:
        """
        Process all unscored filings in the database

        Returns:
            List of strategy scores for new filings
        """
        scores = []

        try:
            # Get unprocessed filings
            unprocessed = self.db_manager.get_unprocessed_filings()
            self.logger.info(f"Processing {len(unprocessed)} unscored filings")

            for filing_data in unprocessed:
                # Convert dict to InsiderFiling object
                filing = InsiderFiling(**filing_data)

                # Get market data for the filing date (or current if filing is recent)
                filing_date = filing.filing_date  # Use filing date for historical accuracy
                market_data = self.trader.get_market_data(filing.company_symbol, target_date=filing_date)
                if not market_data:
                    self.logger.warning(f"No market data for {filing.company_symbol} on {filing_date}, skipping")
                    continue

                # Analyze filing
                score = self.analyze_insider_filing(filing, market_data)

                # Store score
                if self.db_manager.store_strategy_score(score):
                    scores.append(score)
                    self.logger.info(f"Stored strategy score for {filing.filing_id}")

        except Exception as e:
            self.logger.error(f"Error processing unscored filings: {e}")

        return scores

    def get_buy_signals(self, date: str = None) -> List[Dict]:
        """
        Get buy signals for a specific date

        Args:
            date: Date to get signals for (default: today)

        Returns:
            List of buy signals with filing and scoring details
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        return self.db_manager.get_buy_signals(date)

    def validate_strategy_criteria(self, filing: InsiderFiling, market_data: MarketData) -> Dict[str, Any]:
        """
        Validate that a filing meets all documented strategy criteria
        Used for testing and validation

        Args:
            filing: Insider filing to validate
            market_data: Market data for the stock

        Returns:
            Dictionary with validation results
        """
        validation = {
            'filing_id': filing.filing_id,
            'symbol': filing.company_symbol,
            'validation_date': datetime.now().isoformat(),
            'criteria': {}
        }

        # 1. Form 4 Purchase (Transaction Code P)
        validation['criteria']['form_4_purchase'] = filing.transaction_code == 'P'

        # 2. Volume Filter
        is_earnings = self._is_earnings_season()
        daily_volume_usd = market_data.avg_volume_30 * market_data.close_price
        validation['criteria']['volume_filter'] = self._check_volume_filter(market_data)
        validation['criteria']['daily_volume_usd'] = daily_volume_usd

        # 3. ATR Filter
        atr_percent = (market_data.atr_14 / market_data.close_price) * 100
        validation['criteria']['atr_filter'] = self._check_atr_filter(market_data)
        validation['criteria']['atr_percent'] = atr_percent

        # 4. Transaction Size
        validation['criteria']['min_transaction_size'] = (
            filing.total_value >= self.config['min_transaction_value']
        )

        # 5. Not Repeat Purchase
        validation['criteria']['not_repeat_purchase'] = not self._is_repeat_purchase(filing)

        # 6. SPY Filter
        validation['criteria']['spy_filter'] = self._check_spy_filter()

        # 7. Insider Role Scoring
        validation['criteria']['insider_role_score'] = self._score_insider_role(filing.insider_title)

        # 8. Ownership Type
        validation['criteria']['indirect_ownership'] = filing.ownership_type == 'I'

        # Overall validation
        validation['passes_all_filters'] = all([
            validation['criteria']['form_4_purchase'],
            validation['criteria']['volume_filter'],
            validation['criteria']['atr_filter'],
            validation['criteria']['min_transaction_size'],
            validation['criteria']['not_repeat_purchase'],
            validation['criteria']['spy_filter']
        ])

        return validation

    def get_strategy_performance_metrics(self, days: int = 30) -> Dict[str, Any]:
        """
        Get strategy performance metrics

        Args:
            days: Number of days to analyze

        Returns:
            Dictionary with performance metrics
        """
        try:
            # Get trade performance from database
            performance = self.db_manager.get_performance_summary(days)

            # Get strategy decision statistics
            # This would require additional database queries to analyze
            # decision accuracy, score distributions, etc.

            return {
                'trading_performance': performance,
                'analysis_period_days': days,
                'strategy_config': self.config
            }

        except Exception as e:
            self.logger.error(f"Error getting strategy performance: {e}")
            return {}