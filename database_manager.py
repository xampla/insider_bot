"""
Database Manager for Insider Trading Bot
Handles SQLite database operations for storing insider filings, market data, and trade history.
"""

import sqlite3
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

@dataclass
class InsiderFiling:
    """Data class for insider filing information"""
    filing_id: str
    company_symbol: str
    company_name: str
    company_cik: str
    insider_name: str
    insider_title: str
    transaction_date: str
    transaction_code: str  # 'P' for purchase, 'S' for sale
    shares_traded: float
    price_per_share: float
    total_value: float
    ownership_type: str  # 'D' for direct, 'I' for indirect
    shares_owned_after: float
    filing_date: str
    is_first_time_purchase: bool
    raw_filing_data: str  # JSON string of raw data
    created_at: str = ""  # Database timestamp (auto-generated)

@dataclass
class MarketData:
    """Data class for market data"""
    symbol: str
    date: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    atr_14: float  # 14-day ATR
    avg_volume_30: float  # 30-day average volume

@dataclass
class StrategyScore:
    """Data class for strategy scoring"""
    filing_id: str
    symbol: str
    total_score: int
    insider_role_score: int
    ownership_type_score: int
    transaction_size_score: int
    volume_filter_passed: bool
    atr_filter_passed: bool
    spy_filter_passed: bool
    earnings_season_bonus: int
    multi_insider_bonus: int
    decision: str  # 'BUY', 'PASS', 'SKIP'
    confidence_level: str  # 'HIGH', 'MEDIUM', 'LOW'
    analysis_date: str

@dataclass
class TradeRecord:
    """Data class for trade records"""
    trade_id: str
    filing_id: str
    symbol: str
    entry_date: str
    entry_price: float
    shares: int
    position_value: float
    stop_loss_price: float
    take_profit_price: Optional[float]
    exit_date: Optional[str]
    exit_price: Optional[float]
    exit_reason: Optional[str]  # 'STOP_LOSS', 'TAKE_PROFIT', 'END_OF_DAY', 'MANUAL'
    pnl: Optional[float]
    pnl_percent: Optional[float]
    strategy_score: int

class DatabaseManager:
    """Manages SQLite database operations for the insider trading bot"""

    def __init__(self, db_path: str = "insider_trading_bot.db"):
        """
        Initialize database manager

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._init_database()

    def _init_database(self) -> None:
        """Initialize database with required tables"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Insider filings table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS insider_filings (
                        filing_id TEXT PRIMARY KEY,
                        company_symbol TEXT NOT NULL,
                        company_name TEXT NOT NULL,
                        company_cik TEXT NOT NULL,
                        insider_name TEXT NOT NULL,
                        insider_title TEXT NOT NULL,
                        transaction_date TEXT NOT NULL,
                        transaction_code TEXT NOT NULL,
                        shares_traded REAL NOT NULL,
                        price_per_share REAL NOT NULL,
                        total_value REAL NOT NULL,
                        ownership_type TEXT NOT NULL,
                        shares_owned_after REAL NOT NULL,
                        filing_date TEXT NOT NULL,
                        is_first_time_purchase BOOLEAN NOT NULL,
                        raw_filing_data TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Create indexes separately
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_company_symbol ON insider_filings(company_symbol)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_filing_date ON insider_filings(filing_date)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_transaction_date ON insider_filings(transaction_date)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_insider_name ON insider_filings(insider_name)")

                # Market data table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS market_data (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        date TEXT NOT NULL,
                        open_price REAL NOT NULL,
                        high_price REAL NOT NULL,
                        low_price REAL NOT NULL,
                        close_price REAL NOT NULL,
                        volume REAL NOT NULL,
                        atr_14 REAL NOT NULL,
                        avg_volume_30 REAL NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(symbol, date)
                    )
                """)

                # Create indexes for market data
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_market_symbol ON market_data(symbol)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_market_date ON market_data(date)")

                # Strategy scores table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS strategy_scores (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        filing_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        total_score INTEGER NOT NULL,
                        insider_role_score INTEGER NOT NULL,
                        ownership_type_score INTEGER NOT NULL,
                        transaction_size_score INTEGER NOT NULL,
                        volume_filter_passed BOOLEAN NOT NULL,
                        atr_filter_passed BOOLEAN NOT NULL,
                        spy_filter_passed BOOLEAN NOT NULL,
                        earnings_season_bonus INTEGER NOT NULL,
                        multi_insider_bonus INTEGER NOT NULL,
                        decision TEXT NOT NULL,
                        confidence_level TEXT NOT NULL,
                        analysis_date TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (filing_id) REFERENCES insider_filings(filing_id)
                    )
                """)

                # Create indexes for strategy scores
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_scores_filing_id ON strategy_scores(filing_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_scores_symbol ON strategy_scores(symbol)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_scores_decision ON strategy_scores(decision)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_scores_analysis_date ON strategy_scores(analysis_date)")

                # Trade records table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trade_records (
                        trade_id TEXT PRIMARY KEY,
                        filing_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        entry_date TEXT NOT NULL,
                        entry_price REAL NOT NULL,
                        shares INTEGER NOT NULL,
                        position_value REAL NOT NULL,
                        stop_loss_price REAL NOT NULL,
                        take_profit_price REAL,
                        exit_date TEXT,
                        exit_price REAL,
                        exit_reason TEXT,
                        pnl REAL,
                        pnl_percent REAL,
                        strategy_score INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (filing_id) REFERENCES insider_filings(filing_id)
                    )
                """)

                # Create indexes for trade records
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trade_records(symbol)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry_date ON trade_records(entry_date)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_exit_date ON trade_records(exit_date)")

                # SPY market condition tracking
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS spy_conditions (
                        date TEXT PRIMARY KEY,
                        open_price REAL NOT NULL,
                        previous_close REAL NOT NULL,
                        gap_percent REAL NOT NULL,
                        trading_allowed BOOLEAN NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Processed document URLs cache table (prevents re-parsing same URLs)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS processed_document_urls (
                        url TEXT PRIMARY KEY,
                        company_symbol TEXT NOT NULL,
                        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        result_type TEXT NOT NULL,  -- 'transactions_found', 'no_transactions', 'parse_error'
                        transaction_count INTEGER DEFAULT 0
                    )
                """)

                conn.commit()
                self.logger.info("Database initialized successfully")

        except sqlite3.Error as e:
            self.logger.error(f"Database initialization error: {e}")
            raise

    def store_insider_filing(self, filing: InsiderFiling) -> bool:
        """
        Store insider filing data

        Args:
            filing: InsiderFiling object

        Returns:
            bool: True if stored successfully, False if already exists
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO insider_filings (
                        filing_id, company_symbol, company_name, company_cik,
                        insider_name, insider_title, transaction_date, transaction_code,
                        shares_traded, price_per_share, total_value, ownership_type,
                        shares_owned_after, filing_date, is_first_time_purchase, raw_filing_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    filing.filing_id, filing.company_symbol, filing.company_name, filing.company_cik,
                    filing.insider_name, filing.insider_title, filing.transaction_date,
                    filing.transaction_code, filing.shares_traded, filing.price_per_share,
                    filing.total_value, filing.ownership_type, filing.shares_owned_after,
                    filing.filing_date, filing.is_first_time_purchase, filing.raw_filing_data
                ))
                return cursor.rowcount > 0

        except sqlite3.Error as e:
            self.logger.error(f"Error storing insider filing: {e}")
            return False

    def store_market_data(self, market_data: MarketData) -> bool:
        """Store market data"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO market_data (
                        symbol, date, open_price, high_price, low_price, close_price,
                        volume, atr_14, avg_volume_30
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    market_data.symbol, market_data.date, market_data.open_price,
                    market_data.high_price, market_data.low_price, market_data.close_price,
                    market_data.volume, market_data.atr_14, market_data.avg_volume_30
                ))
                return True

        except sqlite3.Error as e:
            self.logger.error(f"Error storing market data: {e}")
            return False

    def get_market_data(self, symbol: str, date: str) -> Optional[MarketData]:
        """Retrieve market data for specific symbol and date"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT symbol, date, open_price, high_price, low_price, close_price,
                           volume, atr_14, avg_volume_30
                    FROM market_data
                    WHERE symbol = ? AND date = ?
                """, (symbol, date))

                row = cursor.fetchone()
                if row:
                    return MarketData(
                        symbol=row[0],
                        date=row[1],
                        open_price=row[2],
                        high_price=row[3],
                        low_price=row[4],
                        close_price=row[5],
                        volume=row[6],
                        atr_14=row[7],
                        avg_volume_30=row[8]
                    )
                return None

        except sqlite3.Error as e:
            self.logger.error(f"Error retrieving market data: {e}")
            return None

    def store_strategy_score(self, score: StrategyScore) -> bool:
        """Store strategy scoring results"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO strategy_scores (
                        filing_id, symbol, total_score, insider_role_score, ownership_type_score,
                        transaction_size_score, volume_filter_passed, atr_filter_passed,
                        spy_filter_passed, earnings_season_bonus, multi_insider_bonus,
                        decision, confidence_level, analysis_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    score.filing_id, score.symbol, score.total_score, score.insider_role_score,
                    score.ownership_type_score, score.transaction_size_score, score.volume_filter_passed,
                    score.atr_filter_passed, score.spy_filter_passed, score.earnings_season_bonus,
                    score.multi_insider_bonus, score.decision, score.confidence_level, score.analysis_date
                ))
                return True

        except sqlite3.Error as e:
            self.logger.error(f"Error storing strategy score: {e}")
            return False

    def store_trade_record(self, trade: TradeRecord) -> bool:
        """Store trade execution record"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO trade_records (
                        trade_id, filing_id, symbol, entry_date, entry_price, shares,
                        position_value, stop_loss_price, take_profit_price, exit_date,
                        exit_price, exit_reason, pnl, pnl_percent, strategy_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade.trade_id, trade.filing_id, trade.symbol, trade.entry_date,
                    trade.entry_price, trade.shares, trade.position_value, trade.stop_loss_price,
                    trade.take_profit_price, trade.exit_date, trade.exit_price, trade.exit_reason,
                    trade.pnl, trade.pnl_percent, trade.strategy_score
                ))
                return True

        except sqlite3.Error as e:
            self.logger.error(f"Error storing trade record: {e}")
            return False

    def get_recent_insider_purchases(self, symbol: str, days: int = 30) -> List[Dict]:
        """Get recent insider purchases for a symbol"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM insider_filings
                    WHERE company_symbol = ?
                    AND transaction_code = 'P'
                    AND transaction_date >= date('now', '-{} days')
                    ORDER BY transaction_date DESC
                """.format(days), (symbol,))

                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

        except sqlite3.Error as e:
            self.logger.error(f"Error retrieving insider purchases: {e}")
            return []

    def check_insider_repeat_purchase(self, insider_name: str, symbol: str, days: int = 30) -> bool:
        """Check if insider has made purchases in the last N days"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM insider_filings
                    WHERE insider_name = ?
                    AND company_symbol = ?
                    AND transaction_code = 'P'
                    AND transaction_date >= date('now', '-{} days')
                """.format(days), (insider_name, symbol))

                count = cursor.fetchone()[0]
                return count > 0

        except sqlite3.Error as e:
            self.logger.error(f"Error checking repeat purchases: {e}")
            return False

    def get_unprocessed_filings(self) -> List[Dict]:
        """Get insider filings that haven't been scored yet"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT f.* FROM insider_filings f
                    LEFT JOIN strategy_scores s ON f.filing_id = s.filing_id
                    WHERE s.filing_id IS NULL
                    AND f.transaction_code = 'P'
                    ORDER BY f.filing_date DESC
                """)

                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

        except sqlite3.Error as e:
            self.logger.error(f"Error retrieving unprocessed filings: {e}")
            return []

    def get_filing_by_id(self, filing_id: str) -> Optional[InsiderFiling]:
        """Get insider filing by filing ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM insider_filings WHERE filing_id = ?", (filing_id,))
                row = cursor.fetchone()

                if row:
                    return InsiderFiling(
                        filing_id=row[0], company_symbol=row[1], company_name=row[2], company_cik=row[3],
                        insider_name=row[4], insider_title=row[5], transaction_date=row[6], transaction_code=row[7],
                        shares_traded=row[8], price_per_share=row[9], total_value=row[10], ownership_type=row[11],
                        shares_owned_after=row[12], filing_date=row[13], is_first_time_purchase=row[14], raw_filing_data=row[15]
                    )
                return None
        except sqlite3.Error as e:
            self.logger.error(f"Error retrieving filing by ID: {e}")
            return None

    def get_buy_signals(self, date: str = None) -> List[Dict]:
        """Get filings that generated BUY signals"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT s.*, f.company_symbol, f.insider_name, f.total_value
                    FROM strategy_scores s
                    JOIN insider_filings f ON s.filing_id = f.filing_id
                    WHERE s.decision = 'BUY'
                    AND s.analysis_date = ?
                    ORDER BY s.total_score DESC
                """, (date,))

                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

        except sqlite3.Error as e:
            self.logger.error(f"Error retrieving buy signals: {e}")
            return []

    def get_open_positions(self) -> List[Dict]:
        """Get currently open trade positions"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM trade_records
                    WHERE exit_date IS NULL
                    ORDER BY entry_date
                """)

                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

        except sqlite3.Error as e:
            self.logger.error(f"Error retrieving open positions: {e}")
            return []

    def update_spy_condition(self, date: str, open_price: float, previous_close: float) -> bool:
        """Update SPY market condition for the day"""
        gap_percent = ((open_price - previous_close) / previous_close) * 100
        trading_allowed = abs(gap_percent) <= 0.5  # Allow trading if gap <= 0.5%

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO spy_conditions
                    (date, open_price, previous_close, gap_percent, trading_allowed)
                    VALUES (?, ?, ?, ?, ?)
                """, (date, open_price, previous_close, gap_percent, trading_allowed))
                return True

        except sqlite3.Error as e:
            self.logger.error(f"Error updating SPY condition: {e}")
            return False

    def is_trading_allowed_today(self, date: str = None) -> bool:
        """Check if trading is allowed based on SPY gap filter"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT trading_allowed FROM spy_conditions
                    WHERE date = ?
                """, (date,))

                result = cursor.fetchone()
                return result[0] if result else True  # Default to allow if no data

        except sqlite3.Error as e:
            self.logger.error(f"Error checking trading allowance: {e}")
            return True  # Default to allow trading on error

    def get_performance_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get trading performance summary for last N days"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Get trade statistics
                cursor.execute("""
                    SELECT
                        COUNT(*) as total_trades,
                        COUNT(CASE WHEN pnl > 0 THEN 1 END) as winning_trades,
                        COUNT(CASE WHEN pnl < 0 THEN 1 END) as losing_trades,
                        AVG(pnl) as avg_pnl,
                        SUM(pnl) as total_pnl,
                        AVG(pnl_percent) as avg_pnl_percent,
                        MAX(pnl) as max_win,
                        MIN(pnl) as max_loss
                    FROM trade_records
                    WHERE entry_date >= date('now', '-{} days')
                    AND pnl IS NOT NULL
                """.format(days))

                stats = cursor.fetchone()

                return {
                    'total_trades': stats[0] or 0,
                    'winning_trades': stats[1] or 0,
                    'losing_trades': stats[2] or 0,
                    'win_rate': (stats[1] / stats[0] * 100) if stats[0] > 0 else 0,
                    'avg_pnl': stats[3] or 0,
                    'total_pnl': stats[4] or 0,
                    'avg_pnl_percent': stats[5] or 0,
                    'max_win': stats[6] or 0,
                    'max_loss': stats[7] or 0
                }

        except sqlite3.Error as e:
            self.logger.error(f"Error getting performance summary: {e}")
            return {}

    def _get_connection(self):
        """Get database connection (for analysis module)"""
        return sqlite3.connect(self.db_path)

    def clean_database(self) -> Dict[str, int]:
        """
        Clean all data from the database for fresh start

        Returns:
            Dictionary with counts of deleted records by table
        """
        try:
            self.logger.info("🧹 Cleaning database...")

            # Get current state before cleaning
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Get counts before deletion
                cursor.execute("SELECT COUNT(*) FROM insider_filings")
                filings_count = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM strategy_scores")
                scores_count = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM market_data")
                market_count = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM spy_conditions")
                spy_count = cursor.fetchone()[0]

            self.logger.info(f"   Current state: {filings_count} filings, {scores_count} scores, {market_count} market data, {spy_count} SPY conditions")

            # Clean all filing data but preserve schema
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Clean insider filings (main data)
                cursor.execute("DELETE FROM insider_filings")
                filings_deleted = cursor.rowcount

                # Clean associated data that depends on filings
                cursor.execute("DELETE FROM strategy_scores")
                scores_deleted = cursor.rowcount

                # Optionally clean trade records (keeping for audit trail by default)
                # cursor.execute("DELETE FROM trade_records")

                # Clean market data cache (will be rebuilt)
                cursor.execute("DELETE FROM market_data")
                market_deleted = cursor.rowcount

                # Clean SPY conditions cache (will be rebuilt)
                cursor.execute("DELETE FROM spy_conditions")
                spy_deleted = cursor.rowcount

            # Optimize database (VACUUM must be outside transaction)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("VACUUM")

            results = {
                'filings_deleted': filings_deleted,
                'scores_deleted': scores_deleted,
                'market_deleted': market_deleted,
                'spy_deleted': spy_deleted
            }

            self.logger.info(f"✅ Database cleaned successfully:")
            self.logger.info(f"   📊 Filings deleted: {filings_deleted}")
            self.logger.info(f"   🎯 Strategy scores deleted: {scores_deleted}")
            self.logger.info(f"   📈 Market data deleted: {market_deleted}")
            self.logger.info(f"   🔍 SPY conditions deleted: {spy_deleted}")
            self.logger.info(f"   💾 Database optimized with VACUUM")

            return results

        except sqlite3.Error as e:
            self.logger.error(f"Error cleaning database: {e}")
            raise

    def is_document_url_processed(self, url: str) -> bool:
        """Check if a document URL has already been processed"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM processed_document_urls WHERE url = ?", (url,))
                return cursor.fetchone() is not None
        except sqlite3.Error as e:
            self.logger.error(f"Error checking processed URL: {e}")
            return False

    def cache_processed_document_url(self, url: str, company_symbol: str,
                                   result_type: str, transaction_count: int = 0):
        """Cache a processed document URL to avoid re-processing"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO processed_document_urls
                    (url, company_symbol, result_type, transaction_count)
                    VALUES (?, ?, ?, ?)
                """, (url, company_symbol, result_type, transaction_count))
                conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Error caching processed URL: {e}")

    def close(self):
        """Close database connections (if any persistent connections)"""
        # SQLite doesn't require explicit connection closing in our context manager approach
        pass