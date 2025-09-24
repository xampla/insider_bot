# Tier-Based Trading Rules Matrix
## Comprehensive Strategy Reference for Insider Trading Bot

*Version: 2024.9.2 - Advanced Refinements Implementation*

---

## 🕘 TIMING RULES (WSV Strategy)

### Core Principle: "Enter at Market Open After Detection"

| Trading Window | Time (ET) | Action | Rationale |
|----------------|-----------|--------|-----------|
| **Regular Hours** | 9:30 AM - 4:00 PM | `TRADE_NOW` | Market is open - execute immediately |
| **After Hours** | 4:00 PM - 8:00 PM | `QUEUE_FOR_NEXT_OPEN` | Thin liquidity, high spreads - wait for official open |
| **Overnight** | 8:00 PM - 4:00 AM | `QUEUE_FOR_NEXT_OPEN` | Market closed - queue for momentum at open |
| **Premarket** | 4:00 AM - 9:30 AM | `QUEUE_FOR_NEXT_OPEN` | Avoid premarket volatility and thin liquidity |

### Execution Rules
- **Immediate Execution**: Market open → Execute with all standard filters (SPY, tier, role weighting)
- **Queued Execution**: Market closed → Queue trade for next open with preserved signal data
- **Same-Day Exit**: All trades (immediate or queued) must exit by market close (≈3:55-4:00 PM ET)
- **No Overnight Holds**: WSV strategy requires day-trading discipline regardless of entry timing

### Queue Management
- Trades queued outside regular hours preserve all signal metadata
- At market open: Execute queued trades first, then process new signals
- Apply same filtering logic to queued trades: SPY filter, tier limits, risk sizing
- **Refined Expiration**: Drop trades that missed their intended market open (not 24h time-based)
  - If trade was queued for a previous market session, drop it rather than execute late
  - Alpha decay principle: First trading day carries most momentum, late execution is ineffective

---

## 🏢 COMPANY TIER CLASSIFICATION

### Tier 1: Large Cap Leaders (Market Cap >$500B)
- **Companies**: AAPL, NVDA, MSFT, GOOGL, AMZN, META, TSLA
- **Risk Multiplier**: 1.0x (full position sizing)
- **SPY Filter Sensitivity**: High (strict 0.5% gap limits)
- **Max Position**: 2% of portfolio per trade

### Tier 2: Established Growth (Market Cap $100B-$500B)
- **Companies**: CRM, ADBE, NFLX, DIS, V, MA, UNH
- **Risk Multiplier**: 1.0x (full position sizing)
- **SPY Filter Sensitivity**: High (strict 0.5% gap limits)
- **Max Position**: 2% of portfolio per trade

### Tier 3: Mid-Cap Focus (Market Cap $10B-$100B)
- **Companies**: SNOW, ZM, DOCU, SQ, ROKU, SPOT, TWLO
- **Risk Multiplier**: 1.0x (full position sizing)
- **SPY Filter Sensitivity**: Medium (exceptions for insider clusters)
- **Max Position**: 2% of portfolio per trade
- **Exception**: Can trade with 0.5x risk during moderate SPY gaps (0.5-1.0%)

### Tier 4: Small Cap Sandbox (Market Cap <$10B)
- **Companies**: PLTR, RBLX, FUBO, SOFI, OPEN, COIN, HOOD, LCID
- **Risk Multiplier**: 0.25x (reduced position sizing for risk control)
- **SPY Filter Sensitivity**: Low (exceptions for insider clusters)
- **Max Position**: 0.5% of portfolio per trade (25% of normal tier)
- **Concurrency Limit**: Maximum 1 Tier 4 trade open at any time
- **Monthly Limit**: Maximum 5 Tier 4 trades per month
- **Exception**: Can trade with 0.25x risk during any SPY gap if insider cluster detected

---

## 🧭 SPY MARKET FILTER (Graduated Risk System)

### Filter Logic: "Risk Reduction vs. Complete Avoidance"

| SPY Gap | Tier 1-2 Action | Tier 3 Action | Tier 4 Action | Risk Multiplier |
|---------|------------------|---------------|---------------|-----------------|
| **<0.5%** | Trade Normal | Trade Normal | Trade Normal | 1.0x |
| **0.5-1.0%** | No Trade | 0.5x Risk if Cluster | 0.25x Risk if Cluster | 0.5x / 0.25x |
| **>1.0%** | No Trade | **0.25x Risk if Cluster** | 0.25x Risk if Cluster | 0.25x |

### Exception Rules
- **Insider Cluster Override**: ≥2 insiders buying same day → Lower tier exceptions apply
- **Tier-Based Flexibility**: Higher risk tolerance for smaller, more volatile companies
- **Risk Graduation**: Reduce position size rather than skip entirely when possible

---

## 🧑‍💼 INSIDER ROLE WEIGHTING (Academic Research-Based)

### Role Scoring Adjustments
| Insider Role | Score Adjustment | Rationale |
|--------------|------------------|-----------|
| **CFO** | +2 points | Strongest predictor of positive alpha (financial oversight) |
| **CEO** | +1 point | High signal strength but some ego/timing bias |
| **COO/President** | +1 point | Operational insight, moderate predictive power |
| **Director** | -1 point | Often routine/schedule-based purchases |
| **Other Officers** | 0 points | Neutral baseline |

### Implementation Notes
- Applied after base strategy scoring but before execution
- Text pattern matching on insider titles for classification
- **Stacking Cap**: Total role adjustment capped at +2 to prevent over-inflation
  - Prevents weak base scores (e.g., 5) from jumping to high conviction instantly
  - Multiple roles (e.g., CFO+CEO = +3) are capped at +2 maximum
- Logging shows score transitions: "Base: 6.5 → Enhanced: 8.5" or "Raw: +3 → Capped: +2"

---

## 🎯 CLUSTER BUY DETECTION

### Definition: ≥2 Unique Insiders Buying Same Day

### Scoring Benefits
- **Score Boost**: +0.5 points to enhanced strategy score
- **Risk Boost**: Diminishing returns cluster boost (prevents always hitting 2% cap)
  - 2 insiders: +0.5% base boost
  - 3 insiders: +0.5% + 0.25% = +0.75%
  - 4+ insiders: +0.5% + 0.25% + 0.1% = +0.85% (capped)
- **SPY Exception Power**: Enables trading during moderate/high volatility periods
- **High Conviction Signal**: Multiple insiders indicate strong internal optimism

### Detection Logic
- Check for same-day purchases by different insiders (avoid double-counting)
- Apply boost to position sizing calculation
- Log cluster participants for transparency

---

## 🚫 SIGNAL QUALITY FILTERS

### Director-Only Signal Exclusion

| Condition | Threshold | Action |
|-----------|-----------|--------|
| **Director-Only Signal** | No executives present | Apply size filter |
| **Small Transaction** | < $100k transaction value | **EXCLUDE** trade |
| **Large Transaction** | ≥ $100k transaction value | Allow trade (standard scoring) |

### Exclusion Logic
- Check if ALL insiders are directors (no CFO, CEO, COO, CTO, President)
- Calculate transaction value: `shares × price_per_share`
- Exclude if director-only AND transaction < $100k
- **Rationale**: Director trades are often routine/schedule-based, small ones are weak signals

---

## 🏭 SECTOR CONCENTRATION LIMITS

### Risk Control: Prevent Sector Over-Exposure

| Conviction Level | Sector Limit | Rationale |
|------------------|--------------|-----------|
| **High Conviction (≥7)** | Max 1 position per sector | Avoid sector concentration risk |
| **Medium/Low (<7)** | No sector limits | Lower conviction trades don't concentrate risk |

### Sector Classifications
- **Technology**: AAPL, MSFT, NVDA, GOOGL, META, CRM, ADBE, SNOW, ZM, DOCU, TWLO, PLTR, RBLX
- **Consumer**: AMZN, TSLA, NFLX, DIS, ROKU, SPOT
- **Financial**: V, MA, SQ, SOFI, COIN, HOOD
- **Healthcare**: UNH
- **Real Estate**: OPEN
- **Entertainment**: FUBO
- **Automotive**: LCID

### Implementation
- Only applies to high conviction trades (strategy score ≥ 7)
- Checks existing open positions for same-sector high conviction trades
- Blocks new high conviction trade if sector already has one
- **Conservative approach**: Unknown sectors are allowed (don't block on missing data)

---

## 🛡️ STOP-LOSS VARIANTS (ATR-Based)

### Unified Variant Selection (Fixed Inconsistency)

| Strategy Score | Stop Variant | ATR Multiplier | Take-Profit Rule |
|----------------|--------------|----------------|------------------|
| **≥7 (High Conviction)** | Variant 1* | 50% ATR | **No TP** - EOD exit only |
| **6-7 (Medium Conviction)** | Variant 1* | 50% ATR | **150% ATR TP** |
| **<6 (Low Conviction)** | Variant 2 | 150% ATR | **100% ATR TP** |

*\*Tier 4 Override: All Tier 4 companies use Variant 2 (150% ATR) regardless of conviction*

### Special Rules
- **Tier 4 Volatility Override**: Small caps always use Variant 2 (150% ATR stops)
  - Applies to all Tier 4 companies regardless of strategy score
  - **Rationale**: Small caps are volatile, need buffer against whipsaws
  - Overrides normal conviction-based variant selection

### Exit Rules
- **High Conviction**: Tight stops, no take-profit target, let winners run until EOD
- **Medium Conviction**: Tight stops with moderate take-profit at 150% ATR
- **Low Conviction**: Wide stops with conservative take-profit at 100% ATR
- **Tier 4 Exception**: Always wide stops for volatility protection
- **End-of-Day**: Always exit by 3:55 PM ET regardless of P&L
- **Stop Loss**: Immediate exit if price hits stop level

---

## 📏 POSITION SIZING (Risk-First Methodology)

### Core Formula
```
Position Size = (Risk Amount) / (Stop Distance)
Risk Amount = (Portfolio Value × Risk %) × Scaling Factor × Tier Multiplier × SPY Multiplier
```

### Risk Allocation by Score
| Strategy Score | Base Risk % | Scaling Factor |
|----------------|-------------|----------------|
| **9-10** | 2.0% | 1.0x |
| **7-8** | 1.5% | 0.9x |
| **5-6** | 1.0% | 0.8x |
| **<5** | 0.5% | 0.7x |

### Combined Multipliers
- **SPY Risk Reduction**: 0.5x or 0.25x during market gaps
- **Tier 4 Risk Control**: 0.25x for small cap exposure limits
- **Cluster Boost**: +0.5 strategy points + 0.5% additional base risk
- **Performance Scaling**: Explicit multipliers based on 3-month rolling evaluation

---

## 🎯 TRADING EXECUTION FLOW

### Signal Processing Priority
1. **Execute Queued Trades** (if market open)
2. **Check Trading Window** (immediate vs. queue decision)
3. **Apply Insider Role Weighting** (enhance scoring)
4. **SPY Market Filter** (risk adjustment or skip)
5. **Tier Risk Assessment** (multiplier and limits)
6. **Position Sizing** (combined risk factors)
7. **Execute or Queue** (based on window status)

### Quality Controls
- **Daily trade limits**: Max 10 trades/day (standard)
- **Cluster exception**: +3 extra trades for insider cluster signals (max 13/day)
- **Tier 4 concurrency limits**: Max 1 position, 5/month
- **Performance-based scaling adjustments**: 3-month rolling evaluation
- **Real-time risk monitoring and stops**: ATR-based exit discipline

---

## 📊 PERFORMANCE TRACKING

### Key Metrics
- **Win Rate**: Target >65% (academic research baseline)
- **Risk-Adjusted Returns**: Sharpe ratio optimization
- **Tier Performance**: Track relative alpha by company tier
- **Timing Effectiveness**: Compare immediate vs. queued trade performance

### Scaling Rules (Explicit Multipliers)

| Performance Condition | Scaling Multiplier | Criteria |
|----------------------|-------------------|----------|
| **Scale Up** | **1.1x** (+10% monthly growth) | >60% win rate, 3 profitable months, <15% max drawdown |
| **Normal** | **1.0x** (baseline) | Standard performance |
| **Scale Down** | **0.8x** (-20% risk reduction) | <60% win rate, >15% monthly loss, or negative 3-month P&L |
| **Minimum Floor** | **0.5x** (safety floor) | Never scale below 50% regardless of performance |

### Implementation Notes
- **Evaluation Period**: 3-month rolling window
- **Minimum Activity**: Requires ≥30 trades for evaluation validity
- **Monthly Requirements**: ≥10 trades per month for robustness
- **Automatic Adjustment**: Risk allocation automatically adjusts based on performance metrics

---

## ⚠️ RISK CONTROLS

### Hard Limits
- No single position >2% of portfolio (0.5% for Tier 4)
- **Daily trade limits**: 10 standard + 3 cluster exception (max 13/day)
- No overnight positions (WSV day-trading rule)
- No trading during extreme market gaps (>1.0% SPY for Tier 1-2)
- **Role weighting cap**: Maximum +2 adjustment to prevent score inflation

### Soft Controls
- Graduated risk reduction vs. complete avoidance
- Tier-based flexibility for volatility tolerance
- Performance-linked scaling adjustments
- Real-time stop-loss monitoring

---

## 🔧 REFINEMENT PACK (Version 2024.9.2)

### Foundation Pack (v2024.9.1)

1. **Queue Expiration Logic**: Changed from 24-hour time-based to "next open only"
2. **Take-Profit Consistency**: Unified stop/take-profit variant selection
3. **Role Weighting Cap**: Total adjustment capped at +2 maximum
4. **Cluster Trade Exception**: +3 extra daily trades for insider clusters
5. **Enhanced Cluster Benefits**: Dual scoring and risk boosts
6. **Extended Tier 3 Exceptions**: 0.25x risk even at >1.0% SPY gaps for clusters
7. **Explicit Performance Scaling**: Clear multiplier transparency (1.1x, 1.0x, 0.8x, 0.5x)

### Advanced Pack (v2024.9.2)

8. **Cluster Boost Diminishing Returns**: Sophisticated risk management for mega-clusters
   - Prevents CFO+COO+CEO clusters from always hitting 2% cap
   - 2 insiders: +0.5% | 3 insiders: +0.75% | 4+ insiders: +0.85% (capped)
   - More nuanced than flat +0.5% boost

9. **Director-Only Signal Exclusion**: Quality-based signal filtering
   - Excludes director-only trades with transaction value < $100k
   - **Rationale**: Director trades are often routine, small ones are weak signals
   - Executive presence (CFO, CEO, etc.) overrides exclusion

10. **Tier 4 ATR Override**: Volatility protection for small caps
    - All Tier 4 companies forced to use Variant 2 (150% ATR) regardless of conviction
    - **Rationale**: Small caps whip around, need buffer against false stops
    - Overrides normal score-based variant selection

11. **Sector Concentration Limits**: Portfolio risk diversification
    - Max 1 high conviction position (≥7 score) per sector at any time
    - Prevents over-concentration in Technology, Financial, Consumer, etc.
    - **Conservative approach**: Unknown sectors allowed (don't block on missing data)

12. **Performance Monitoring Notes**:
    - Track Tier 2 responsiveness over 90 days
    - Consider replacing low-alpha large caps (DIS, UNH) with growth names if underperforming
    - Focus on companies where insider signals generate measurable momentum

---

*This matrix serves as the definitive reference for all trading decisions. All code implementations should align with these rules.*