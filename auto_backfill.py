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
        self.max_gap_days = 7  # Max gap before triggering backfill
        self.max_backfill_days = 30  # Max days to backfill in one session
        self.target_companies = ['AAPL', 'NVDA', 'MSFT', 'TSLA', 'GOOGL', 'AMZN', 'META']

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
                    # New database - backfill last 7 days
                    backfill_days = 7
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