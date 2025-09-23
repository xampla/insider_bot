# Insider Trading Bot - System Architecture

## Overview
A modular Python system that monitors SEC Form 4 filings, analyzes insider trading patterns, and executes trades based on validated momentum strategies.

## System Components

### 1. SECDataReader (`sec_data_reader.py`)
**Purpose**: Fetch and parse SEC Form 4 insider trading filings
**Key Functions**:
- Monitor SEC EDGAR API for new Form 4 filings
- Parse XML/JSON filing data
- Extract insider information (name, title, transaction details)
- Filter for open-market purchases (transaction code "P")
- Detect multi-insider events (same-day purchases)

### 2. AlpacaTrader (`alpaca_trader.py`)
**Purpose**: Handle portfolio management and trade execution
**Key Functions**:
- Connect to Alpaca API for trading
- Get account balance and buying power
- Fetch real-time market data (price, volume, ATR)
- Execute buy/sell orders with position sizing
- Monitor SPY for market condition filtering
- Implement risk management (stop-loss, take-profit)

### 3. StrategyEngine (`strategy_engine.py`)
**Purpose**: Implement the scoring and decision logic
**Key Functions**:
- Calculate ATR and volume filters
- Score insider trades based on documented criteria:
  - Insider role (CFO > CEO > Director)
  - Direct vs indirect ownership
  - Transaction size and timing
  - First-time vs repeat purchases
  - Market conditions (SPY filter)
  - Earnings season detection
- Make go/no-go trading decisions
- Determine position sizing based on conviction score

### 4. DatabaseManager (`database_manager.py`)
**Purpose**: Handle data persistence and retrieval
**Key Functions**:
- Manage SQLite database connections
- Store insider filings, market data, strategy scores
- Track trade history and performance
- Prevent duplicate processing
- Generate performance reports

### 5. Main Orchestrator (`main.py`)
**Purpose**: Coordinate all system components
**Key Functions**:
- Schedule periodic SEC data fetching
- Run strategy evaluation pipeline
- Execute trades based on strategy signals
- Handle error logging and recovery
- Provide status reporting

## Data Flow

1. **Data Ingestion**: SECDataReader fetches new Form 4 filings
2. **Market Data**: AlpacaTrader gets current market data for relevant stocks
3. **Strategy Analysis**: StrategyEngine scores each insider trade
4. **Decision Making**: High-scoring trades trigger buy orders
5. **Execution**: AlpacaTrader executes trades with risk management
6. **Persistence**: DatabaseManager stores all data and results

## Configuration

Environment variables required:
- `ALPACA_API_KEY`: Alpaca trading API key
- `ALPACA_SECRET_KEY`: Alpaca secret key
- `ALPACA_BASE_URL`: Alpaca API endpoint (paper/live)
- `DATABASE_PATH`: SQLite database file path

## Risk Management

- Position sizing based on strategy conviction score
- ATR-based stop losses (-50% earnings season, -150% year-round)
- Take profits at +100% ATR (earnings season only)
- SPY gap filter (skip trades when SPY gaps >±0.5%)
- Maximum position limits per trade
- Exit all positions before market close

## Monitoring & Logging

- Real-time trade logging
- Performance tracking
- Error handling and recovery
- Strategy effectiveness metrics