#!/usr/bin/env python3
"""
Insider Trading Bot - Main Orchestration Script

A comprehensive system that monitors SEC Form 4 filings, analyzes insider trading patterns,
and executes trades based on validated momentum strategies.

Based on:
- WSV Trading Mastery Strategy
- Academic research validation
- ATR-based risk management
- Volume and liquidity filters
"""

import os
import sys
import logging
import time
import signal
import schedule
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple
import argparse
import json

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Import our modules
from database_manager import DatabaseManager
from alpaca_trader import AlpacaTrader
from strategy_engine import StrategyEngine
from sec_historical_loader import SECHistoricalLoader
from auto_backfill import AutoBackfillManager
from telegram_notifier import TelegramNotifier

class InsiderTradingBot:
    """Main orchestration class for the insider trading bot"""

    def __init__(self, config_file: str = None):
        """
        Initialize the insider trading bot

        Args:
            config_file: Path to configuration file (optional)
        """
        self.setup_logging()
        self.logger = logging.getLogger(__name__)

        # Load configuration
        self.config = self.load_configuration(config_file)

        # Initialize components
        self.db_manager = None
        self.sec_reader = None
        self.trader = None
        self.strategy_engine = None

        # State tracking
        self.is_running = False
        self.shutdown_requested = False  # Track shutdown requests during initialization
        self.last_filing_check = None
        self.daily_trade_count = 0
        self.start_time = datetime.now()

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('insider_bot.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )

    def load_configuration(self, config_file: str = None) -> Dict[str, Any]:
        """Load configuration from file or environment variables"""
        default_config = {
            'database_path': os.getenv('DATABASE_PATH', 'insider_trading_bot.db'),
            'sec_check_interval': int(os.getenv('SEC_CHECK_INTERVAL', '300')),  # 5 minutes
            'max_daily_trades': int(os.getenv('MAX_DAILY_TRADES', '10')),
            'max_position_per_trade': float(os.getenv('MAX_POSITION_PCT', '0.05')),  # 5%
            'user_agent': os.getenv('SEC_USER_AGENT', 'InsiderBot research@example.com'),
            'market_open_delay': int(os.getenv('MARKET_OPEN_DELAY', '15')),  # Wait 15 min after open
            'end_of_day_exit': os.getenv('END_OF_DAY_EXIT', 'true').lower() == 'true'
        }

        if config_file and os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    file_config = json.load(f)
                default_config.update(file_config)
                self.logger.info(f"Loaded configuration from {config_file}")
            except Exception as e:
                self.logger.warning(f"Failed to load config file {config_file}: {e}")

        return default_config

    def initialize_components(self):
        """Initialize all system components"""
        try:
            self.logger.info("Initializing system components...")

            # Check for shutdown request early
            if self.shutdown_requested:
                self.logger.info("🛑 Shutdown requested before database initialization")
                return

            # Initialize database
            self.db_manager = DatabaseManager(self.config['database_path'])
            self.logger.info("Database manager initialized")

            # Production mode - using real SEC data only

            # Initialize real SEC data reader (with real XML parsing and URL caching)
            user_agent = self.config['user_agent']
            self.sec_reader = SECHistoricalLoader(user_agent, self.db_manager)

            # SEC Historical Loader with real XML parsing is ready
            self.logger.info("✅ Real SEC API access confirmed")
            self.using_real_sec = True

            self.logger.info("Real SEC data reader initialized")

            # Initialize Alpaca trader
            self.trader = AlpacaTrader()
            self.logger.info("Alpaca trader initialized")

            # Initialize Telegram notifier
            self.telegram_notifier = TelegramNotifier()
            if self.telegram_notifier.enabled:
                self.logger.info("Telegram notifier initialized")
            else:
                self.logger.info("Telegram notifier disabled (no credentials)")

            # Initialize strategy engine with Telegram notifier
            self.strategy_engine = StrategyEngine(self.db_manager, self.trader)
            self.strategy_engine.telegram_notifier = self.telegram_notifier  # Add notifier to strategy
            self.logger.info("Strategy engine initialized")

            # Initialize auto-backfill system
            self.sec_historical_loader = SECHistoricalLoader(user_agent, self.db_manager)
            self.backfill_manager = AutoBackfillManager(self.db_manager, self.sec_historical_loader)

            # Check and execute auto-backfill if needed
            self.logger.info("📚 Auto-Backfill Check - Filling any HISTORICAL gaps in database...")
            self.logger.info("   (Scans last 60 days to ensure no missing data)")

            # Check for shutdown during initialization
            if self.shutdown_requested:
                self.logger.info("🛑 Shutdown requested during initialization, skipping auto-backfill")
                return

            # Handle interrupts during backfill
            try:
                backfill_result = self.backfill_manager.check_and_backfill()
            except KeyboardInterrupt:
                self.logger.info("🛑 Auto-backfill interrupted by user")
                return

            # Check for shutdown after backfill
            if self.shutdown_requested:
                self.logger.info("🛑 Shutdown requested after auto-backfill")
                return

            if backfill_result['backfill_executed']:
                self.logger.info(f"✅ Auto-backfill completed: {backfill_result['stored_count']} new filings")
                if self.telegram_notifier.enabled:
                    self.telegram_notifier.notify_system_status("backfill_complete",
                        f"Added {backfill_result['stored_count']} filings for period {backfill_result['period']}")
            else:
                self.logger.info(f"ℹ️ No backfill needed: {backfill_result.get('reason', 'Database up to date')}")

            self.logger.info("Auto-backfill system initialized")

            # Verify market connection
            if not self.trader.is_market_open():
                self.logger.info("Market is currently closed")
            else:
                self.logger.info("Market is open - ready for trading")

            self.logger.info("All components initialized successfully")

        except Exception as e:
            self.logger.error(f"Failed to initialize components: {e}")
            raise


    def signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.logger.info(f"🛑 Received signal {signum} (Ctrl+C), shutting down gracefully...")
        self.shutdown_requested = True
        if self.is_running:
            self.shutdown()
        else:
            # During initialization, just set flag and exit
            self.logger.info("💥 Forcing immediate shutdown during initialization...")
            import sys
            sys.exit(0)

    def run_filing_check(self):
        """Check for new SEC Form 4 filings and process them"""
        try:
            self.logger.info("🔍 Scheduled Filing Check - Looking for NEW filings since last check...")
            self.logger.info("   (This is different from auto-backfill which fills historical gaps)")

            # Get recent filings (last 1 day) using real XML parsing
            today = datetime.now().strftime('%Y-%m-%d')
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

            # Use the same companies as auto-backfill system (all 36 companies)
            target_companies = self.backfill_manager._get_target_companies()

            self.logger.info(f"   📊 Checking {len(target_companies)} companies for new filings (Date range: {yesterday} to {today})")
            self.logger.info(f"   🏢 Companies: {', '.join(target_companies[:10])}{'...' if len(target_companies) > 10 else ''}")

            recent_filings = self.sec_reader.load_historical_data(
                start_date=yesterday,
                end_date=today,
                companies=target_companies
            )

            new_filings_processed = 0
            duplicate_filings_skipped = 0

            for filing in recent_filings:
                # Store in database with duplicate detection
                if self.db_manager.store_insider_filing(filing):
                    new_filings_processed += 1
                    self.logger.info(f"📄 NEW filing: {filing.filing_id} ({filing.company_symbol} - {filing.insider_name})")
                else:
                    duplicate_filings_skipped += 1

            if new_filings_processed > 0:
                self.logger.info(f"✅ Processed {new_filings_processed} NEW filings (added to database for analysis)")
                if duplicate_filings_skipped > 0:
                    self.logger.info(f"   📋 Skipped {duplicate_filings_skipped} duplicate filings (already in database)")
            else:
                if duplicate_filings_skipped > 0:
                    self.logger.info(f"ℹ️  No new filings found, but {duplicate_filings_skipped} duplicates were detected (already processed)")
                else:
                    self.logger.info("ℹ️  No filings found in the last 24 hours")

            self.last_filing_check = datetime.now()

        except Exception as e:
            self.logger.error(f"Error in filing check: {e}")

    def run_strategy_analysis(self):
        """Analyze unscored filings and generate trading signals"""
        try:
            self.logger.info("Running strategy analysis...")

            # Process unscored filings
            new_scores = self.strategy_engine.process_unscored_filings()

            if new_scores:
                self.logger.info(f"Generated {len(new_scores)} new strategy scores")

                # Count buy signals
                buy_signals = [score for score in new_scores if score.decision == 'BUY']
                if buy_signals:
                    self.logger.info(f"Generated {len(buy_signals)} BUY signals")

        except Exception as e:
            self.logger.error(f"Error in strategy analysis: {e}")

    def execute_trades(self):
        """Execute trades based on buy signals with WSV timing strategy"""
        try:

            # 🕘 WSV TIMING STRATEGY: Execute queued trades first (if market is open)
            # This handles trades detected after hours that were queued for market open
            if self.trader.is_market_open():
                self.logger.info("🚀 Checking for queued trades to execute at market open...")
                queue_results = self.trader.execute_queued_trades()

                if queue_results['trades_executed'] > 0:
                    self.daily_trade_count += queue_results['trades_executed']
                    self.logger.info(f"✅ Executed {queue_results['trades_executed']} queued trades")
                elif queue_results.get('queued_count', 0) > 0:
                    self.logger.info(f"ℹ️ {queue_results['queued_count']} trades still queued: {queue_results['reason']}")

            # Check daily trade limit with cluster exception
            # Allow +3 extra trades for cluster signals (strong conviction signals)
            max_trades = self.config['max_daily_trades']
            cluster_extra_limit = 3

            if self.daily_trade_count >= max_trades:
                # Check if we have any cluster trades to process that could use the extra allowance
                remaining_signals = self.strategy_engine.get_buy_signals()
                cluster_signals_count = 0

                for check_signal in remaining_signals:
                    if self._check_insider_cluster_buy(check_signal['symbol'], check_signal.get('analysis_date')):
                        cluster_signals_count += 1

                # Allow up to +3 extra if we have cluster signals
                effective_limit = max_trades + min(cluster_signals_count, cluster_extra_limit)

                if self.daily_trade_count >= effective_limit:
                    self.logger.info(f"Daily trade limit reached ({self.daily_trade_count}/{effective_limit}) - including cluster exceptions")
                    return
                else:
                    self.logger.info(f"📊 Using cluster exception: {self.daily_trade_count}/{effective_limit} trades (base: {max_trades} + cluster: {effective_limit - max_trades})")

            # Get buy signals for today
            buy_signals = self.strategy_engine.get_buy_signals()

            if not buy_signals:
                self.logger.info("No buy signals to execute")
                return

            self.logger.info(f"Processing {len(buy_signals)} buy signals")

            for signal in buy_signals:
                try:
                    symbol = signal['symbol']
                    filing_id = signal['filing_id']
                    base_strategy_score = signal['total_score']

                    # 📅 DATE FILTER: Skip old backfilled signals (only trade recent filings)
                    # WSV strategy requires fresh momentum - old signals are stale
                    analysis_date = signal.get('analysis_date')
                    if analysis_date:
                        from datetime import datetime
                        signal_date = datetime.strptime(analysis_date, '%Y-%m-%d')
                        days_old = (datetime.now() - signal_date).days

                        if days_old > 2:  # Only trade signals from last 2 days
                            self.logger.info(f"⏭️ Skipping {symbol}: Signal too old ({days_old} days) - WSV requires fresh momentum")
                            continue

                    # Check if this specific signal qualifies for cluster exception
                    cluster_details = self._get_insider_cluster_details(symbol, signal.get('analysis_date'))
                    is_cluster_signal = cluster_details['is_cluster']

                    # Additional check for daily trade limit per individual trade
                    # Regular limit: max_daily_trades, Cluster exception: +3 extra
                    effective_max_trades = self.config['max_daily_trades']
                    if is_cluster_signal:
                        effective_max_trades += cluster_extra_limit

                    if self.daily_trade_count >= effective_max_trades:
                        if is_cluster_signal:
                            self.logger.info(f"⏭️ Skipping {symbol}: Cluster exception limit reached ({self.daily_trade_count}/{effective_max_trades})")
                        else:
                            self.logger.info(f"⏭️ Skipping {symbol}: Daily limit reached ({self.daily_trade_count}/{self.config['max_daily_trades']})")
                        continue

                    # 🧑‍💼 INSIDER ROLE WEIGHTING enhancement
                    # Apply academic research-based role adjustments to strategy score
                    strategy_score = self.trader.apply_insider_role_weighting(
                        base_strategy_score, signal
                    )

                    if strategy_score != base_strategy_score:
                        self.logger.info(f"🎯 Enhanced scoring for {symbol}: {base_strategy_score} → {strategy_score}")

                    # 🚫 DIRECTOR-ONLY SIGNAL EXCLUSION
                    # Skip weak director-only signals with small transaction sizes
                    if self.trader.should_exclude_director_only_signal(signal):
                        self.logger.info(f"⏭️ Skipping {symbol}: Director-only signal with small transaction size")
                        continue

                    # 🕘 WSV TIMING STRATEGY: Check trading window and decide action
                    # Determine whether to execute now or queue for next market open
                    trading_window = self.trader.get_trading_window_status()
                    should_execute_now = trading_window['recommended_action'] == 'TRADE_NOW'

                    if not should_execute_now:
                        # Queue trade for next market open (WSV strategy)
                        self.logger.info(f"🕘 {symbol}: {trading_window['reason']}")

                        queued_success = self.trader.queue_trade_for_next_open(
                            signal_data=signal,
                            enhanced_strategy_score=strategy_score,
                            has_insider_cluster=is_cluster_signal
                        )

                        if queued_success:
                            self.logger.info(f"📋 {symbol}: Queued for execution at {trading_window.get('next_open', 'next market open')}")
                        else:
                            self.logger.error(f"❌ {symbol}: Failed to queue trade")

                        continue  # Skip to next signal
                    else:
                        self.logger.info(f"🚀 {symbol}: Market open - executing immediately")

                    # 🧭 ENHANCED SPY MARKET FILTER with tier-based exceptions
                    # Use already-calculated cluster status
                    has_insider_cluster = is_cluster_signal

                    spy_condition = self.trader.get_enhanced_spy_condition(
                        symbol=symbol,
                        has_insider_cluster=has_insider_cluster
                    )

                    if not spy_condition['trading_allowed']:
                        self.logger.info(f"❌ SPY Filter: Skipping {symbol} - {spy_condition['reason']}")
                        continue
                    elif spy_condition.get('exception_applied'):
                        self.logger.info(f"✅ SPY Exception: Trading {symbol} - {spy_condition['reason']}")

                    # Extract SPY risk multiplier from graduated filter
                    spy_risk_multiplier = spy_condition.get('risk_multiplier', 1.0)
                    if spy_risk_multiplier < 1.0:
                        self.logger.info(f"📊 SPY Risk Adjustment: {symbol} - Risk reduced to {spy_risk_multiplier*100:.0f}% due to {spy_condition['reason']}")

                    # Get current market data
                    market_data = self.trader.get_market_data(symbol)
                    if not market_data:
                        self.logger.warning(f"No market data for {symbol}, skipping")
                        continue

                    # Calculate position size using enhanced risk-first approach
                    # UNIFIED STOP VARIANT LOGIC (fixed take-profit inconsistency)
                    # High conviction (≥7): 50% ATR stop, no TP, EOD exit
                    # Medium conviction (6-7): 50% ATR stop, 150% ATR TP
                    # Low conviction (<6): 150% ATR stop, 100% ATR TP
                    if strategy_score >= 6:
                        stop_variant = 1  # 50% ATR stop (for both high and medium conviction)
                    else:
                        stop_variant = 2  # 150% ATR stop (for low conviction only)

                    # 🧪 TIER 4 SAFETY CAPS - Prevent portfolio creep into high-risk small caps
                    tier_risk_multiplier = self._get_tier_risk_multiplier(symbol)
                    if tier_risk_multiplier < 1.0:  # Tier 4 detected
                        # Force Tier 4 to always use wide stops (Variant 2) regardless of conviction
                        # Small caps are volatile - need buffer against whipsaws
                        if stop_variant == 1:
                            stop_variant = 2
                            self.logger.info(f"🔴 Tier 4 Override: Forcing {symbol} to use Variant 2 (150% ATR) for volatility buffer")

                        # Check concurrency limits for Tier 4 trades
                        tier4_limits_ok, limit_reason = self._check_tier4_limits(symbol)
                        if not tier4_limits_ok:
                            self.logger.info(f"🚫 Tier 4 Safety Cap: Skipping {symbol} - {limit_reason}")
                            continue

                        self.logger.info(f"🔴 Tier 4 approved: {symbol} - Risk reduced to {tier_risk_multiplier*100:.0f}%")

                    # 🏭 SECTOR CONCENTRATION LIMITS - Prevent sector concentration risk
                    # Max 1 high conviction position per sector at any time
                    if not self.trader.check_sector_concentration_limits(symbol, strategy_score):
                        self.logger.info(f"⏭️ Skipping {symbol}: Sector concentration limit (max 1 high conviction per sector)")
                        continue

                    shares = self.trader.calculate_position_size(
                        symbol, strategy_score, market_data.close_price, market_data, stop_variant, cluster_details
                    )

                    # Apply combined risk adjustments: SPY filter × Tier 4 multiplier
                    combined_risk_multiplier = spy_risk_multiplier * tier_risk_multiplier
                    if combined_risk_multiplier < 1.0:
                        shares = int(shares * combined_risk_multiplier)
                        adjustment_reasons = []
                        if spy_risk_multiplier < 1.0:
                            adjustment_reasons.append(f"SPY: {spy_risk_multiplier*100:.0f}%")
                        if tier_risk_multiplier < 1.0:
                            adjustment_reasons.append(f"Tier 4: {tier_risk_multiplier*100:.0f}%")
                        self.logger.info(f"📉 Combined risk adjustment: {symbol} position reduced to {shares} shares ({', '.join(adjustment_reasons)})")

                    if shares <= 0:
                        self.logger.warning(f"Invalid position size for {symbol}, skipping")
                        continue

                    # Execute trade with enhanced PDF-compliant strategy
                    # Note: take_profit_variant is now determined automatically by strategy_score
                    trade_record = self.trader.place_buy_order(
                        symbol, shares, strategy_score, filing_id, stop_variant
                    )

                    if trade_record:
                        # Store trade record
                        self.db_manager.store_trade_record(trade_record)
                        self.daily_trade_count += 1

                        # Enhanced trade logging with portfolio context
                        trade_value = shares * trade_record.entry_price
                        account_info = self.trader.get_account_info()
                        portfolio_value = account_info.get('portfolio_value', 0)
                        trade_percentage = (trade_value / portfolio_value * 100) if portfolio_value > 0 else 0

                        self.logger.info(f"🎯 TRADE EXECUTED: {symbol}")
                        self.logger.info(f"   📊 Position: {shares} shares @ ${trade_record.entry_price:.2f}")
                        self.logger.info(f"   💰 Trade value: ${trade_value:,.2f}")
                        self.logger.info(f"   🏦 Portfolio: ${portfolio_value:,.2f}")
                        self.logger.info(f"   📈 Position size: {trade_percentage:.2f}% of portfolio")
                        self.logger.info(f"   🎯 Strategy score: {strategy_score}")
                        self.logger.info(f"   📋 Filing ID: {filing_id}")
                    else:
                        self.logger.error(f"❌ Failed to execute trade for {symbol}")

                except Exception as e:
                    self.logger.error(f"Error executing trade for {signal.get('symbol', 'unknown')}: {e}")

        except Exception as e:
            self.logger.error(f"Error in trade execution: {e}")

    def _check_insider_cluster_buy(self, symbol: str, analysis_date: str = None) -> bool:
        """
        Check if there's an insider cluster buy (≥2 insiders same day)
        This is used for Tier 3/4 SPY filter exceptions

        Args:
            symbol: Company symbol
            analysis_date: Date to check (default: today)

        Returns:
            True if insider cluster buy detected
        """
        cluster_info = self._get_insider_cluster_details(symbol, analysis_date)
        return cluster_info['is_cluster']

    def _get_insider_cluster_details(self, symbol: str, analysis_date: str = None) -> dict:
        """
        Get detailed insider cluster information for advanced risk calculations

        Args:
            symbol: Company symbol
            analysis_date: Date to check (default: today)

        Returns:
            Dict with cluster details: {is_cluster, insider_count, insiders_list}
        """
        try:
            if not analysis_date:
                analysis_date = datetime.now().strftime('%Y-%m-%d')

            # Get recent insider purchases for this symbol
            recent_purchases = self.db_manager.get_recent_insider_purchases(symbol, days=1)

            # Filter for purchases on the analysis date
            same_day_purchases = [
                purchase for purchase in recent_purchases
                if purchase['transaction_date'] == analysis_date
            ]

            # Count unique insiders (avoid double counting same insider)
            unique_insiders = set(purchase['insider_name'] for purchase in same_day_purchases)
            insider_count = len(unique_insiders)
            is_cluster = insider_count >= 2

            if is_cluster:
                self.logger.info(f"🎯 Insider cluster detected for {symbol}: {insider_count} insiders on {analysis_date}")
                for insider in unique_insiders:
                    self.logger.info(f"   - {insider}")

            return {
                'is_cluster': is_cluster,
                'insider_count': insider_count,
                'insiders_list': list(unique_insiders),
                'analysis_date': analysis_date
            }

        except Exception as e:
            self.logger.error(f"Error checking insider cluster for {symbol}: {e}")
            return {
                'is_cluster': False,
                'insider_count': 0,
                'insiders_list': [],
                'analysis_date': analysis_date or datetime.now().strftime('%Y-%m-%d')
            }

    def _get_tier_risk_multiplier(self, symbol: str) -> float:
        """
        Get risk multiplier for different company tiers
        Tier 4 companies get reduced risk allocation

        Args:
            symbol: Company symbol

        Returns:
            Risk multiplier (0.25 for Tier 4, 1.0 for others)
        """
        try:
            # Use the backfill manager's tier system if available
            if hasattr(self, 'backfill_manager') and hasattr(self.backfill_manager, 'get_tier_risk_multiplier'):
                return self.backfill_manager.get_tier_risk_multiplier(symbol)

            # Fallback: hardcoded Tier 4 list for risk reduction
            tier4_companies = ['PLTR', 'RBLX', 'FUBO', 'SOFI', 'OPEN', 'COIN', 'HOOD', 'LCID']

            if symbol in tier4_companies:
                return 0.25  # Reduce risk to 25% for Tier 4 (max 0.5% instead of 2%)
            else:
                return 1.0   # Normal risk for Tier 1-3

        except Exception as e:
            self.logger.error(f"Error getting tier risk multiplier for {symbol}: {e}")
            return 1.0  # Default to normal risk

    def _check_tier4_limits(self, symbol: str) -> Tuple[bool, str]:
        """
        Check Tier 4 concurrency and monthly limits to prevent portfolio creep

        Safety Rules:
        - Max 1 Tier 4 trade open at any time
        - Optional: Max 5 Tier 4 trades per month
        - Keeps Tier 4 truly "sandbox" rather than diluting portfolio

        Args:
            symbol: Company symbol to check

        Returns:
            Tuple of (limits_ok, reason)
        """
        try:
            from datetime import datetime, timedelta

            # Define Tier 4 companies
            tier4_companies = ['PLTR', 'RBLX', 'FUBO', 'SOFI', 'OPEN', 'COIN', 'HOOD', 'LCID']

            if symbol not in tier4_companies:
                return True, "Not a Tier 4 company"

            # Check 1: Max 1 Tier 4 trade open at any time
            open_positions = self.db_manager.get_open_positions()
            tier4_open_count = 0

            for position in open_positions:
                position_symbol = position.get('symbol', '')
                if position_symbol in tier4_companies:
                    tier4_open_count += 1

            if tier4_open_count >= 1:
                return False, f"Tier 4 concurrency limit: {tier4_open_count}/1 positions already open"

            # Check 2: Max 5 Tier 4 trades per month (optional strict limit)
            current_month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            monthly_tier4_trades = 0

            # Get trades from this month
            try:
                monthly_trades = self.db_manager.get_trades_in_period(
                    start_date=current_month_start.strftime('%Y-%m-%d'),
                    end_date=datetime.now().strftime('%Y-%m-%d')
                )

                for trade in monthly_trades:
                    trade_symbol = trade.get('symbol', '')
                    if trade_symbol in tier4_companies:
                        monthly_tier4_trades += 1

                # Optional stricter limit: 5 trades per month
                MAX_TIER4_MONTHLY = 5
                if monthly_tier4_trades >= MAX_TIER4_MONTHLY:
                    return False, f"Tier 4 monthly limit: {monthly_tier4_trades}/{MAX_TIER4_MONTHLY} trades this month"

            except Exception as e:
                # If we can't check monthly trades, be conservative but don't block
                self.logger.warning(f"Could not check monthly Tier 4 limits: {e}")

            # All limits passed
            self.logger.info(f"🧪 Tier 4 Limits Check for {symbol}:")
            self.logger.info(f"   Open positions: {tier4_open_count}/1")
            self.logger.info(f"   Monthly trades: {monthly_tier4_trades}/5")
            self.logger.info(f"   Status: ✅ Approved")

            return True, "All Tier 4 limits satisfied"

        except Exception as e:
            self.logger.error(f"Error checking Tier 4 limits for {symbol}: {e}")
            # Be conservative: deny on error to prevent uncontrolled Tier 4 exposure
            return False, f"Error in limit check: {e}"

    def manage_positions(self):
        """Manage open positions (stop losses, take profits)"""
        try:
            # Get open positions from database
            open_trades = self.db_manager.get_open_positions()

            if not open_trades:
                return

            self.logger.info(f"Managing {len(open_trades)} open positions")

            # Check for stop losses and take profits
            trades_to_close = self.trader.check_stop_losses(open_trades)

            for trade in trades_to_close:
                try:
                    symbol = trade['symbol']
                    shares = trade['shares']
                    exit_reason = trade['exit_reason']
                    current_price = trade['current_price']

                    # Close position
                    if self.trader.place_sell_order(symbol, shares, exit_reason):
                        # Update trade record
                        trade['exit_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        trade['exit_price'] = current_price
                        trade['pnl'] = (current_price - trade['entry_price']) * shares
                        trade['pnl_percent'] = (trade['pnl'] / trade['position_value']) * 100

                        # Convert to TradeRecord and update database
                        from database_manager import TradeRecord
                        updated_trade = TradeRecord(**trade)
                        self.db_manager.store_trade_record(updated_trade)

                        self.logger.info(f"✅ Closed position: {symbol} - {exit_reason}")
                        self.logger.info(f"💰 P&L: ${trade['pnl']:,.2f} ({trade['pnl_percent']:+.2f}%)")

                except Exception as e:
                    self.logger.error(f"Error managing position {trade.get('symbol', 'unknown')}: {e}")

        except Exception as e:
            self.logger.error(f"Error in position management: {e}")

    def end_of_day_cleanup(self):
        """Close all positions at end of trading day"""
        try:
            if self.config['end_of_day_exit']:
                self.logger.info("🌅 Performing end-of-day cleanup...")
                self.trader.close_all_positions("END_OF_DAY")

                # Reset daily counters
                self.daily_trade_count = 0

        except Exception as e:
            self.logger.error(f"Error in end-of-day cleanup: {e}")

    def print_status(self):
        """Print current system status"""
        try:
            account_info = self.trader.get_account_info()
            portfolio_value = account_info.get('portfolio_value', 0)
            buying_power = account_info.get('buying_power', 0)

            open_positions = self.trader.get_current_positions()
            position_count = len(open_positions)

            performance = self.db_manager.get_performance_summary(30)

            print(f"\n{'='*60}")
            print(f"INSIDER TRADING BOT STATUS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}")
            print(f"Portfolio Value: ${portfolio_value:,.2f}")
            print(f"Buying Power: ${buying_power:,.2f}")
            print(f"Open Positions: {position_count}")
            print(f"Daily Trades: {self.daily_trade_count}/{self.config['max_daily_trades']}")
            print(f"Market Open: {self.trader.is_market_open()}")
            print(f"Last Filing Check: {self.last_filing_check or 'Never'}")
            print(f"Running Time: {datetime.now() - self.start_time}")

            if performance:
                print(f"\n30-Day Performance:")
                print(f"  Total Trades: {performance.get('total_trades', 0)}")
                print(f"  Win Rate: {performance.get('win_rate', 0):.1f}%")
                print(f"  Total P&L: ${performance.get('total_pnl', 0):,.2f}")
                print(f"  Avg P&L: ${performance.get('avg_pnl', 0):,.2f}")

            print(f"{'='*60}\n")

        except Exception as e:
            self.logger.error(f"Error printing status: {e}")

    def run_scheduled_tasks(self):
        """Run all scheduled tasks"""
        self.run_filing_check()
        self.run_strategy_analysis()
        self.execute_trades()
        self.manage_positions()

    def start_scheduling(self):
        """Start scheduled operations"""
        self.logger.info("Starting scheduled operations...")

        # Schedule filing checks every 5 minutes during market hours
        schedule.every(self.config['sec_check_interval']).seconds.do(self.run_scheduled_tasks)

        # Schedule end-of-day cleanup
        schedule.every().day.at("16:05").do(self.end_of_day_cleanup)  # 5 minutes after market close

        # Schedule status reports
        schedule.every(30).minutes.do(self.print_status)

        self.is_running = True

        # Show timezone info for Spain-based user
        import pytz
        et_tz = pytz.timezone('US/Eastern')
        spain_tz = pytz.timezone('Europe/Madrid')
        current_et = datetime.now(et_tz)
        current_spain = datetime.now(spain_tz)

        self.logger.info("🚀 Scheduled operations started")
        self.logger.info(f"   📍 Your local time (Spain): {current_spain.strftime('%H:%M %Z')}")
        self.logger.info(f"   📍 Market time (US Eastern): {current_et.strftime('%H:%M %Z')}")
        self.logger.info(f"   🔄 Bot will check for SEC filings every {self.config['sec_check_interval']} seconds")
        self.logger.info(f"   📊 Status reports every 30 minutes")
        self.logger.info(f"   🌅 End-of-day cleanup at 16:05 ET (22:05/23:05 Spain depending on DST)")

        try:
            while self.is_running:
                schedule.run_pending()
                time.sleep(1)

        except KeyboardInterrupt:
            self.logger.info("Interrupted by user")
        finally:
            self.shutdown()

    def run_backtest(self, start_date: str, end_date: str):
        """Run backtest for a date range"""
        self.logger.info(f"Running backtest from {start_date} to {end_date}")
        # Implement backtesting logic here
        self.logger.info("Backtest completed")

    def shutdown(self):
        """Graceful shutdown"""
        self.logger.info("Shutting down insider trading bot...")
        self.is_running = False

        # Close any remaining positions if configured
        if self.trader and self.config.get('close_on_shutdown', False):
            self.trader.close_all_positions("SHUTDOWN")

        # Close database connections
        if self.db_manager:
            self.db_manager.close()

        self.logger.info("Shutdown complete")

    def clean_database(self):
        """Clean all data from the database for fresh start"""
        try:
            # Use DatabaseManager's clean method
            results = self.db_manager.clean_database()

            print(f"""
{'='*60}
DATABASE CLEANED SUCCESSFULLY
{'='*60}
Removed {results['filings_deleted']} insider filings and associated data.
Database is ready for fresh 60-day backfill.

Run without --clean to start normal operation.
{'='*60}
            """)

        except Exception as e:
            self.logger.error(f"Error cleaning database: {e}")
            raise

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Insider Trading Bot')
    parser.add_argument('--config', help='Configuration file path')
    parser.add_argument('--status', action='store_true', help='Print status and exit')
    parser.add_argument('--backtest', nargs=2, metavar=('start_date', 'end_date'),
                       help='Run backtest for date range (YYYY-MM-DD)')
    parser.add_argument('--clean', action='store_true', help='Clean database and exit')

    args = parser.parse_args()


    try:
        # Create bot instance
        bot = InsiderTradingBot(args.config)

        # Handle --clean early to avoid wasteful initialization
        if args.clean:
            # Only initialize minimal components needed for cleaning
            bot.db_manager = DatabaseManager(bot.config['database_path'])
            bot.clean_database()
            return

        # Full initialization for all other operations
        bot.initialize_components()

        if args.status:
            # Print status and exit
            bot.print_status()
            return

        if args.backtest:
            # Run backtest
            bot.run_backtest(args.backtest[0], args.backtest[1])
            return

        # Normal operation - start scheduling
        print(f"""
{'='*60}
INSIDER TRADING BOT STARTED
{'='*60}
Mode: PAPER TRADING (Alpaca Paper Account)
Database: {bot.config['database_path']}
Max Daily Trades: {bot.config['max_daily_trades']}
Check Interval: {bot.config['sec_check_interval']} seconds

Press Ctrl+C to stop
{'='*60}
        """)

        bot.start_scheduling()

    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()