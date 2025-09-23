# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains documentation and strategy guides for an **Insider Trading Bot** project that implements automated trading based on SEC Form 4 insider purchase filings. The project focuses on momentum trading strategies triggered by insider buy signals.

## Repository Structure

Currently, this is a documentation/research repository containing:

- **Insider-Buy Momentum Strategy_ Key Criteria.pdf**: Comprehensive trading strategy documentation detailing:
  - Entry triggers (Form 4 purchase filings)
  - Filtering criteria (volume, liquidity, ATR, market conditions)
  - Risk management rules (stop losses, take profits)
  - Scoring framework for trade evaluation

- **WSV Trading Mastery Draft.pdf**: Additional trading methodology documentation

## Key Strategy Components

Based on the strategy documentation, any future implementation should include:

### Core Trading Logic
- **Trigger**: Buy at market open following insider Form 4 purchase filings reported after previous market close
- **Volume Filter**: Target $30M-$100M daily volume for earnings season, $30M-$10B for year-round
- **Volatility Filter**: Require ATR ≥3.5% (earnings season) or 7-20% (year-round)
- **Market Filter**: Skip trades when SPY gaps >±0.5%

### Signal Quality Filters
- Only first-time buys (exclude repeat purchases within 30 days)
- Open-market purchases only (Form 4 code "P")
- Prioritize CFO/COO purchases over CEO purchases
- Weight indirect ownership (trusts) higher than direct purchases
- Multi-insider events (≥2 insiders same day) are high-conviction signals

### Risk Management
- **Earnings Season**: -50% ATR stop loss, +100% ATR take profit
- **Year-round**: -150% ATR stop loss, exit at market close
- Execute trades within first few minutes of session
- Always exit before market close to avoid overnight risk

## Development Notes

This appears to be a strategy research repository. Future development would likely involve:

1. **Data Pipeline**: SEC EDGAR Form 4 filing parser and monitor
2. **Market Data Integration**: Real-time price, volume, and ATR calculations
3. **Filtering Engine**: Implementation of all strategy criteria
4. **Scoring System**: Automated trade evaluation based on documented framework
5. **Execution Engine**: Automated trade placement and risk management
6. **Backtesting Framework**: Historical strategy validation

## Important Considerations

- This strategy involves securities trading and requires proper regulatory compliance
- Implementation should include comprehensive risk controls and position sizing
- Market data feeds and broker API integrations would be required
- Extensive backtesting and paper trading recommended before live deployment