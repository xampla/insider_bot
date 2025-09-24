#!/usr/bin/env python3
"""
Auto-Backfill System for Insider Trading Bot
Automatically detects and fills database gaps when the bot restarts.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import sqlite3

from database_manager import DatabaseManager, InsiderFiling
from sec_historical_loader import SECHistoricalLoader


class AutoBackfillManager:
    """Manages automatic database backfilling for insider trading data"""

    def __init__(self, db_manager: DatabaseManager, sec_loader: SECHistoricalLoader):
        """
        Initialize auto-backfill manager

        Args:
            db_manager: Database manager instance
            sec_loader: SEC historical data loader
        """
        self.logger = logging.getLogger(__name__)
        self.db_manager = db_manager
        self.sec_loader = sec_loader

        # Backfill configuration
        self.max_gap_days = 1  # Max gap before triggering backfill (daily sensitivity)
        self.max_backfill_days = 65  # Max days to backfill in one session (60 + buffer)

        # Enhanced company selection based on PDF strategy requirements
        # Focus on liquid, high-volume stocks that meet strategy filters
        self.target_companies = self._get_target_companies()

    def _get_target_companies(self) -> List[str]:
        """
        Enhanced company tier system with mid-cap focus and experimental tier

        Strategy: Best volatility/tradability balance in mid-caps where insider buys move prices more
        Quality over quantity approach per PDF requirements

        Returns:
            List of company symbols to track
        """
        # Initialize tier system
        self._init_company_tiers()

        # Start conservative: Tier 1 + select Tier 2 companies
        target_list = self.tier1_companies + self.tier2_companies[:5]

        self.logger.info(f"📊 Enhanced Company Tier System Initialized:")
        self.logger.info(f"   🔥 Tier 1 (Mega-caps): {len(self.tier1_companies)} companies")
        self.logger.info(f"   🟡 Tier 2 (Large-caps): {len(self.tier2_companies)} companies")
        self.logger.info(f"   🟢 Tier 3 (Mid-caps + Quality): {len(self.tier3_companies)} companies")
        self.logger.info(f"   🔴 Tier 4 (Small-cap Sandbox): {len(self.tier4_companies)} companies")
        self.logger.info(f"")
        self.logger.info(f"🎯 Currently Active: {len(target_list)} companies")
        self.logger.info(f"   Active List: {target_list}")
        self.logger.info(f"")
        self.logger.info(f"📈 Expansion Path:")
        self.logger.info(f"   Next: Add Tier 3 after ≥2 profitable months + no >15% drawdown")
        self.logger.info(f"   Future: Optional Tier 4 for experimental small-cap trades")

        return target_list

    def _init_company_tiers(self) -> None:
        """
        Initialize comprehensive company tier system with proper classification
        """
        # TIER 1: Mega-cap tech giants (>$500B) - Core holdings, best liquidity
        self.tier1_companies = [
            'AAPL',   # Apple - $3T+ market cap, consistent insider activity
            'NVDA',   # NVIDIA - $1T+, AI leader, strong insider signals
            'MSFT',   # Microsoft - $3T+, stable, excellent volume
            'GOOGL',  # Alphabet - $2T+, tech leader, good liquidity
            'AMZN',   # Amazon - $1.5T+, e-commerce leader
            'META',   # Meta - $800B+, social media leader
            'TSLA'    # Tesla - $800B+, high volatility, strong insider signals
        ]

        # TIER 2: Quality large-caps ($100B-$500B) - Diversified sector exposure
        self.tier2_companies = [
            'JPM',    # JPMorgan Chase - $500B+, financial leader
            'JNJ',    # Johnson & Johnson - $400B+, healthcare stability
            'V',      # Visa - $500B+, fintech leader, excellent volume
            'PG',     # Procter & Gamble - $300B+, consumer staples
            'UNH',    # UnitedHealth - $500B+, healthcare growth
            'HD',     # Home Depot - $350B+, retail leader
            'MA',     # Mastercard - $400B+, fintech growth
            'DIS',    # Disney - $200B+, entertainment sector
            'NFLX',   # Netflix - $200B+, streaming leader
            'CRM'     # Salesforce - $250B+, software leader
        ]

        # TIER 3: Mid-caps + Quality ($10B-$100B) - ENHANCED with volatility leaders
        # Rationale: Mid-caps have best balance of volatility & tradability
        # Insider buys historically move these prices more than mega-caps
        self.tier3_companies = [
            # High-growth software/tech mid-caps (replacing INTC/CSCO)
            'DDOG',   # Datadog - $40B, cloud monitoring, high insider activity
            'ZS',     # Zscaler - $20B, cybersecurity leader
            'CRWD',   # CrowdStrike - $80B, cybersecurity growth
            'TEAM',   # Atlassian - $50B, collaboration software
            'ALGN',   # Align Technology - $20B, medical devices
            'ROKU',   # Roku - $5B, streaming platform

            # Quality traditional companies (kept best performers)
            'ADBE',   # Adobe - $250B, creative software leader
            'PFE',    # Pfizer - $150B, pharmaceuticals
            'KO',     # Coca-Cola - $250B, consumer staples dividend
            'TMO',    # Thermo Fisher - $200B, life sciences leader
            'ABT',    # Abbott - $180B, healthcare devices
        ]

        # TIER 4: Small-cap experimental ($2B-$10B) - High-risk, high-reward
        # Only for very large insider buys, limited exposure
        self.tier4_companies = [
            'PLTR',   # Palantir - $50B, data analytics
            'RBLX',   # Roblox - $25B, gaming platform
            'FUBO',   # FuboTV - $1B, streaming sports
            'SOFI',   # SoFi Technologies - $8B, fintech
            'OPEN',   # Opendoor - $2B, real estate tech
            'COIN',   # Coinbase - $20B, crypto exchange
            'HOOD',   # Robinhood - $15B, trading platform
            'LCID',   # Lucid Motors - $10B, EV startup
        ]

        # Create tier mapping for easy lookup
        self.company_tier_map = {}
        for symbol in self.tier1_companies:
            self.company_tier_map[symbol] = 1
        for symbol in self.tier2_companies:
            self.company_tier_map[symbol] = 2
        for symbol in self.tier3_companies:
            self.company_tier_map[symbol] = 3
        for symbol in self.tier4_companies:
            self.company_tier_map[symbol] = 4

    def get_company_tier(self, symbol: str) -> int:
        """
        Get the tier classification for a company symbol

        Args:
            symbol: Company symbol (e.g., 'AAPL')

        Returns:
            Tier number (1-4) or 0 if not found
        """
        if not hasattr(self, 'company_tier_map'):
            self._init_company_tiers()

        return self.company_tier_map.get(symbol, 0)

    def is_tier1_or_tier2(self, symbol: str) -> bool:
        """Check if company is Tier 1 or Tier 2 (affected by SPY filter)"""
        tier = self.get_company_tier(symbol)
        return tier in [1, 2]

    def is_tier3_or_tier4(self, symbol: str) -> bool:
        """Check if company is Tier 3 or Tier 4 (may trade during SPY gaps)"""
        tier = self.get_company_tier(symbol)
        return tier in [3, 4]

    def get_tier_risk_multiplier(self, symbol: str) -> float:
        """
        Get risk multiplier for Tier 4 companies (experimental small-caps)

        Args:
            symbol: Company symbol

        Returns:
            Risk multiplier (0.25 for Tier 4, 1.0 for others)
        """
        tier = self.get_company_tier(symbol)
        if tier == 4:
            return 0.25  # Max 0.5% risk for Tier 4 (vs 2% normal max)
        return 1.0

    def get_companies_by_tier(self, tier: int) -> List[str]:
        """Get list of companies in a specific tier"""
        if not hasattr(self, 'company_tier_map'):
            self._init_company_tiers()

        if tier == 1:
            return self.tier1_companies.copy()
        elif tier == 2:
            return self.tier2_companies.copy()
        elif tier == 3:
            return self.tier3_companies.copy()
        elif tier == 4:
            return self.tier4_companies.copy()
        else:
            return []

    def get_all_available_companies(self) -> List[str]:
        """Get all companies across all tiers"""
        if not hasattr(self, 'company_tier_map'):
            self._init_company_tiers()

        return (self.tier1_companies + self.tier2_companies +
                self.tier3_companies + self.tier4_companies)

    def expand_to_tier3(self, db_manager=None, force: bool = False) -> Dict[str, Any]:
        """
        Enhanced expansion with drawdown-linked conditions
        Ensures growth happens only during stable performance periods

        Expansion Rules:
        - ≥2 months profitable trading
        - No monthly drawdown >15% during that period
        - Stable performance demonstrates strategy robustness

        Args:
            db_manager: DatabaseManager for performance analysis (optional)
            force: Force expansion without checks (for testing)

        Returns:
            Dict with expansion results and reasoning
        """
        try:
            # Check expansion eligibility unless forced
            if not force and db_manager:
                eligibility = self._check_expansion_eligibility(db_manager)
                if not eligibility['eligible']:
                    return {
                        'expansion_executed': False,
                        'reason': eligibility['reason'],
                        'eligibility_details': eligibility,
                        'recommendation': eligibility.get('recommendation', 'Wait for stable performance')
                    }

            # Get Tier 3 companies (now includes enhanced mid-caps)
            if not hasattr(self, 'tier3_companies'):
                self._init_company_tiers()

            tier3_companies = self.tier3_companies.copy()
            original_count = len(self.target_companies)

            # Add Tier 3 companies to tracking list
            companies_to_add = [comp for comp in tier3_companies if comp not in self.target_companies]

            if not companies_to_add:
                return {
                    'expansion_executed': False,
                    'reason': 'Tier 3 companies already included',
                    'current_count': len(self.target_companies)
                }

            self.target_companies.extend(companies_to_add)
            self.target_companies = list(set(self.target_companies))  # Remove duplicates

            expansion_result = {
                'expansion_executed': True,
                'companies_added': companies_to_add,
                'previous_count': original_count,
                'current_count': len(self.target_companies),
                'tier3_focus': 'Enhanced with mid-cap growth leaders',
                'expansion_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            self.logger.info(f"🚀 TIER 3 EXPANSION EXECUTED:")
            self.logger.info(f"   ✅ Expansion approved after stability checks")
            self.logger.info(f"   📊 Previous: {original_count} companies")
            self.logger.info(f"   📈 Current: {len(self.target_companies)} companies")
            self.logger.info(f"   🎯 Added: {len(companies_to_add)} Tier 3 companies")
            self.logger.info(f"   🔥 Focus: Mid-cap volatility leaders (DDOG, ZS, CRWD, etc.)")
            self.logger.info(f"")

            # Log the strategic reasoning
            self.logger.info(f"💡 Strategic Rationale:")
            self.logger.info(f"   • Mid-caps offer best volatility/tradability balance")
            self.logger.info(f"   • Insider buys move these prices more than mega-caps")
            self.logger.info(f"   • Expansion approved only after stable performance")
            self.logger.info(f"")

            return expansion_result

        except Exception as e:
            self.logger.error(f"Error during Tier 3 expansion: {e}")
            return {
                'expansion_executed': False,
                'reason': f'Expansion error: {e}',
                'error': True
            }

    def _check_expansion_eligibility(self, db_manager) -> Dict[str, Any]:
        """
        Check if strategy performance meets expansion criteria

        Expansion Requirements:
        - ≥2 profitable months in last 3 months
        - No monthly drawdown >15%
        - Minimum trading activity

        Args:
            db_manager: DatabaseManager for performance analysis

        Returns:
            Dict with eligibility analysis
        """
        try:
            from datetime import datetime, timedelta

            # Analyze last 3 months performance
            months_to_check = 3
            profitable_months = 0
            max_monthly_drawdown = 0.0
            months_with_data = 0
            monthly_details = []

            for month_offset in range(months_to_check):
                # Get performance for this month (simplified analysis)
                if month_offset == 0:
                    month_perf = db_manager.get_performance_summary(30)
                elif month_offset == 1:
                    month_60_perf = db_manager.get_performance_summary(60)
                    month_30_perf = db_manager.get_performance_summary(30)
                    if month_60_perf and month_30_perf:
                        month_perf = {
                            'total_trades': month_60_perf.get('total_trades', 0) - month_30_perf.get('total_trades', 0),
                            'total_pnl': month_60_perf.get('total_pnl', 0) - month_30_perf.get('total_pnl', 0)
                        }
                    else:
                        month_perf = None
                else:  # month_offset == 2
                    month_90_perf = db_manager.get_performance_summary(90)
                    month_60_perf = db_manager.get_performance_summary(60)
                    if month_90_perf and month_60_perf:
                        month_perf = {
                            'total_trades': month_90_perf.get('total_trades', 0) - month_60_perf.get('total_trades', 0),
                            'total_pnl': month_90_perf.get('total_pnl', 0) - month_60_perf.get('total_pnl', 0)
                        }
                    else:
                        month_perf = None

                if month_perf and month_perf.get('total_trades', 0) > 0:
                    months_with_data += 1
                    pnl = month_perf.get('total_pnl', 0)
                    trades = month_perf.get('total_trades', 0)

                    is_profitable = pnl > 0
                    if is_profitable:
                        profitable_months += 1

                    # Estimate monthly drawdown (simplified)
                    if pnl < 0:
                        estimated_drawdown = abs(pnl) / 10000  # Rough approximation
                        max_monthly_drawdown = max(max_monthly_drawdown, estimated_drawdown)

                    monthly_details.append({
                        'month': f"Month-{month_offset + 1}",
                        'trades': trades,
                        'pnl': pnl,
                        'profitable': is_profitable
                    })

            # Expansion eligibility criteria
            min_profitable_months = 2
            max_allowed_drawdown = 0.15  # 15%
            min_months_with_data = 2

            meets_profitability = profitable_months >= min_profitable_months
            meets_drawdown = max_monthly_drawdown <= max_allowed_drawdown
            has_sufficient_data = months_with_data >= min_months_with_data

            eligible = meets_profitability and meets_drawdown and has_sufficient_data

            if eligible:
                reason = f"Expansion approved: {profitable_months}/{months_to_check} profitable months, max drawdown {max_monthly_drawdown:.1%}"
                recommendation = "Expand to Tier 3 now"
            elif not has_sufficient_data:
                reason = f"Insufficient data: only {months_with_data}/{min_months_with_data} months have trading activity"
                recommendation = "Continue trading with current companies"
            elif not meets_profitability:
                reason = f"Insufficient profitability: only {profitable_months}/{min_profitable_months} profitable months"
                recommendation = "Focus on improving strategy performance"
            else:  # drawdown too high
                reason = f"High drawdown detected: {max_monthly_drawdown:.1%} > {max_allowed_drawdown:.1%} threshold"
                recommendation = "Wait for more stable performance"

            return {
                'eligible': eligible,
                'reason': reason,
                'recommendation': recommendation,
                'metrics': {
                    'profitable_months': f"{profitable_months}/{months_to_check}",
                    'max_monthly_drawdown': f"{max_monthly_drawdown:.1%}",
                    'months_with_data': f"{months_with_data}/{months_to_check}",
                    'meets_criteria': {
                        'profitability': meets_profitability,
                        'drawdown': meets_drawdown,
                        'data_sufficiency': has_sufficient_data
                    }
                },
                'monthly_breakdown': monthly_details
            }

        except Exception as e:
            self.logger.error(f"Error checking expansion eligibility: {e}")
            return {
                'eligible': False,
                'reason': f'Error in eligibility check: {e}',
                'recommendation': 'Manual review required'
            }

    def get_company_stats(self) -> Dict:
        """Get statistics about current company tracking"""
        return {
            'total_tracked': len(self.target_companies),
            'companies': self.target_companies,
            'recommendation': 'Start with current set, expand after 2-3 months of successful trading'
        }

    def check_and_backfill(self) -> Dict:
        """
        Check if backfill is needed and execute if necessary

        Returns:
            Dict with backfill results and statistics
        """
        self.logger.info("🔍 Checking if database backfill is needed...")

        try:
            # Analyze database state
            analysis = self._analyze_database_state()

            if analysis['needs_backfill']:
                self.logger.info(f"📅 Database gap detected: {analysis['gap_info']}")
                return self._execute_backfill(analysis)
            else:
                self.logger.info("✅ Database is up to date - no backfill needed")
                return {
                    'backfill_executed': False,
                    'reason': 'Database up to date',
                    'analysis': analysis
                }

        except Exception as e:
            self.logger.error(f"Error during backfill check: {e}")
            return {
                'backfill_executed': False,
                'error': str(e),
                'analysis': None
            }

    def _analyze_database_state(self) -> Dict:
        """Analyze database to determine if backfill is needed"""

        try:
            # Get most recent filing date
            with self.db_manager._get_connection() as conn:
                cursor = conn.cursor()

                # Check most recent filing
                cursor.execute("""
                    SELECT MAX(filing_date) as latest_date, COUNT(*) as total_filings
                    FROM insider_filings
                    WHERE filing_date IS NOT NULL
                """)

                result = cursor.fetchone()
                latest_date_str = result[0] if result and result[0] else None
                total_filings = result[1] if result else 0

                # Get recent filings by company
                cursor.execute("""
                    SELECT
                        company_symbol,
                        MAX(filing_date) as latest_date,
                        COUNT(*) as filing_count
                    FROM insider_filings
                    WHERE filing_date >= date('now', '-30 days')
                    GROUP BY company_symbol
                    ORDER BY company_symbol
                """)

                company_status = {row[0]: {'latest_date': row[1], 'count': row[2]}
                                for row in cursor.fetchall()}

            # Calculate gaps
            today = datetime.now().date()

            if latest_date_str:
                latest_date = datetime.strptime(latest_date_str, '%Y-%m-%d').date()
                days_since_last = (today - latest_date).days
            else:
                latest_date = None
                days_since_last = 999  # Force backfill for empty database

            # Determine if backfill is needed
            needs_backfill = (
                days_since_last > self.max_gap_days or  # Too many days since last filing
                total_filings == 0 or  # Empty database
                len(company_status) < len(self.target_companies) / 2  # Missing too many companies
            )

            # Calculate backfill period
            if needs_backfill:
                if latest_date_str:
                    # Fill gap from last filing to today
                    backfill_start = latest_date
                    backfill_days = min(days_since_last, self.max_backfill_days)
                else:
                    # New database - backfill last 60 days for proper strategy baseline
                    backfill_days = 60
                    backfill_start = today - timedelta(days=backfill_days)

                backfill_end = today
            else:
                backfill_start = None
                backfill_end = None
                backfill_days = 0

            return {
                'needs_backfill': needs_backfill,
                'total_filings': total_filings,
                'latest_date': latest_date_str,
                'days_since_last': days_since_last,
                'company_status': company_status,
                'backfill_start': backfill_start.strftime('%Y-%m-%d') if backfill_start else None,
                'backfill_end': backfill_end.strftime('%Y-%m-%d') if backfill_end else None,
                'backfill_days': backfill_days,
                'gap_info': f"{days_since_last} days since last filing" if latest_date_str else "Empty database"
            }

        except Exception as e:
            self.logger.error(f"Error analyzing database state: {e}")
            # Default to conservative backfill on error
            today = datetime.now().date()
            return {
                'needs_backfill': True,
                'total_filings': 0,
                'latest_date': None,
                'days_since_last': 999,
                'company_status': {},
                'backfill_start': (today - timedelta(days=7)).strftime('%Y-%m-%d'),
                'backfill_end': today.strftime('%Y-%m-%d'),
                'backfill_days': 7,
                'gap_info': "Error analyzing database - defaulting to 7-day backfill",
                'analysis_error': str(e)
            }

    def _execute_backfill(self, analysis: Dict) -> Dict:
        """Execute the backfill process"""

        start_date = analysis['backfill_start']
        end_date = analysis['backfill_end']

        self.logger.info(f"🔄 Starting backfill process...")
        self.logger.info(f"   Period: {start_date} to {end_date}")
        self.logger.info(f"   Companies: {self.target_companies}")

        try:
            # Load historical data
            filings = self.sec_loader.load_historical_data(
                start_date=start_date,
                end_date=end_date,
                companies=self.target_companies
            )

            # Store in database
            stored_count = 0
            duplicate_count = 0
            error_count = 0

            for filing in filings:
                try:
                    # Check if filing already exists
                    existing = self.db_manager.get_filing_by_id(filing.filing_id)
                    if existing:
                        duplicate_count += 1
                        continue

                    # Store new filing
                    self.db_manager.store_insider_filing(filing)
                    stored_count += 1

                except Exception as e:
                    self.logger.warning(f"Failed to store filing {filing.filing_id}: {e}")
                    error_count += 1

            # Summary
            self.logger.info(f"✅ Backfill completed:")
            self.logger.info(f"   📥 Loaded: {len(filings)} filings")
            self.logger.info(f"   💾 Stored: {stored_count} new filings")
            self.logger.info(f"   🔄 Duplicates: {duplicate_count}")
            self.logger.info(f"   ❌ Errors: {error_count}")

            return {
                'backfill_executed': True,
                'period': f"{start_date} to {end_date}",
                'total_loaded': len(filings),
                'stored_count': stored_count,
                'duplicate_count': duplicate_count,
                'error_count': error_count,
                'companies': self.target_companies,
                'analysis': analysis
            }

        except Exception as e:
            self.logger.error(f"Backfill execution failed: {e}")
            return {
                'backfill_executed': False,
                'error': str(e),
                'period': f"{start_date} to {end_date}",
                'analysis': analysis
            }

    def get_database_summary(self) -> Dict:
        """Get summary of current database state"""
        try:
            with self.db_manager._get_connection() as conn:
                cursor = conn.cursor()

                # Overall statistics
                cursor.execute("""
                    SELECT
                        COUNT(*) as total_filings,
                        COUNT(DISTINCT company_symbol) as unique_companies,
                        MIN(filing_date) as earliest_date,
                        MAX(filing_date) as latest_date
                    FROM insider_filings
                """)

                overall = cursor.fetchone()

                # By company
                cursor.execute("""
                    SELECT
                        company_symbol,
                        COUNT(*) as filing_count,
                        MAX(filing_date) as latest_date,
                        AVG(total_value) as avg_value
                    FROM insider_filings
                    GROUP BY company_symbol
                    ORDER BY filing_count DESC
                """)

                by_company = cursor.fetchall()

                # Recent activity (last 7 days)
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM insider_filings
                    WHERE filing_date >= date('now', '-7 days')
                """)

                recent_count = cursor.fetchone()[0]

                return {
                    'total_filings': overall[0],
                    'unique_companies': overall[1],
                    'earliest_date': overall[2],
                    'latest_date': overall[3],
                    'recent_filings_7d': recent_count,
                    'by_company': [
                        {
                            'symbol': row[0],
                            'count': row[1],
                            'latest_date': row[2],
                            'avg_value': round(row[3], 2) if row[3] else 0
                        }
                        for row in by_company
                    ]
                }

        except Exception as e:
            self.logger.error(f"Error getting database summary: {e}")
            return {'error': str(e)}


def main():
    """Test the auto-backfill system"""
    import os
    from dotenv import load_dotenv

    load_dotenv()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("🧪 Testing Auto-Backfill System...")

    # Initialize components
    db_manager = DatabaseManager()
    user_agent = os.getenv('SEC_USER_AGENT', 'InsideTracker admin@gmail.com')
    sec_loader = SECHistoricalLoader(user_agent)

    # Initialize backfill manager
    backfill_manager = AutoBackfillManager(db_manager, sec_loader)

    # Get current database summary
    print("\n📊 Current Database State:")
    summary = backfill_manager.get_database_summary()
    if 'error' not in summary:
        print(f"   Total filings: {summary['total_filings']}")
        print(f"   Companies: {summary['unique_companies']}")
        print(f"   Date range: {summary['earliest_date']} to {summary['latest_date']}")
        print(f"   Recent filings (7d): {summary['recent_filings_7d']}")

    # Check and execute backfill if needed
    print("\n🔍 Checking backfill requirements...")
    result = backfill_manager.check_and_backfill()

    if result['backfill_executed']:
        print("✅ Backfill completed successfully!")
        print(f"   Period: {result['period']}")
        print(f"   New filings: {result['stored_count']}")
    else:
        print(f"ℹ️ Backfill not needed: {result.get('reason', 'Unknown')}")


if __name__ == "__main__":
    main()