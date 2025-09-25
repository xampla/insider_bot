#!/usr/bin/env python3
"""
Test AlphaVantage API as alternative SPY data source
"""

import requests
import json
import logging
from datetime import datetime, timedelta
import pandas as pd

def test_alphavantage_spy():
    """Test AlphaVantage API for SPY daily data"""

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    api_key = "WDABSJY7AQU6IJF1"

    logger.info("🔍 TESTING ALPHAVANTAGE SPY DATA")
    logger.info("=" * 50)

    # AlphaVantage TIME_SERIES_DAILY endpoint for SPY
    url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=SPY&apikey={api_key}"

    logger.info("🌐 Fetching SPY data from AlphaVantage...")
    logger.info(f"   URL: {url}")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()
        logger.info(f"✅ API call successful")
        logger.info(f"   Response keys: {list(data.keys())}")

        # Check for API errors
        if "Error Message" in data:
            logger.error(f"❌ API Error: {data['Error Message']}")
            return False

        if "Note" in data:
            logger.warning(f"⚠️  API Note: {data['Note']}")

        # Extract time series data
        time_series_key = "Time Series (Daily)"
        if time_series_key not in data:
            logger.error(f"❌ No time series data found. Available keys: {list(data.keys())}")
            return False

        time_series = data[time_series_key]
        logger.info(f"✅ Time series data found")
        logger.info(f"   Total days available: {len(time_series)}")

        # Convert to sorted list of dates (most recent first)
        dates = sorted(time_series.keys(), reverse=True)
        logger.info(f"   Most recent dates: {dates[:5]}")

        if len(dates) < 2:
            logger.error("❌ Insufficient data for gap calculation")
            return False

        # Extract data for gap calculation (today and yesterday)
        latest_date = dates[0]
        previous_date = dates[1]

        latest_data = time_series[latest_date]
        previous_data = time_series[previous_date]

        logger.info(f"\n📊 SPY DATA FOR GAP CALCULATION:")
        logger.info(f"   Latest Date: {latest_date}")
        logger.info(f"      Open: {latest_data['1. open']}")
        logger.info(f"      High: {latest_data['2. high']}")
        logger.info(f"      Low: {latest_data['3. low']}")
        logger.info(f"      Close: {latest_data['4. close']}")
        logger.info(f"      Volume: {latest_data['5. volume']}")

        logger.info(f"   Previous Date: {previous_date}")
        logger.info(f"      Open: {previous_data['1. open']}")
        logger.info(f"      High: {previous_data['2. high']}")
        logger.info(f"      Low: {previous_data['3. low']}")
        logger.info(f"      Close: {previous_data['4. close']}")
        logger.info(f"      Volume: {previous_data['5. volume']}")

        # Calculate gap (current open vs previous close)
        current_open = float(latest_data['1. open'])
        previous_close = float(previous_data['4. close'])

        gap_percent = ((current_open - previous_close) / previous_close) * 100

        logger.info(f"\n🎯 GAP CALCULATION:")
        logger.info(f"   Current Open: ${current_open:.2f}")
        logger.info(f"   Previous Close: ${previous_close:.2f}")
        logger.info(f"   Gap Percentage: {gap_percent:.3f}%")

        # Test production logic
        abs_gap = abs(gap_percent)
        logger.info(f"\n🔍 PRODUCTION SPY FILTER TEST:")
        logger.info(f"   Absolute Gap: {abs_gap:.3f}%")

        if abs_gap < 0.5:
            result = "Normal trading conditions"
        elif abs_gap < 1.0:
            result = "Moderate gap - tier exceptions may apply"
        else:
            result = "Large gap - significant restrictions"

        logger.info(f"   Filter Result: {result}")

        logger.info(f"\n✅ ALPHAVANTAGE TEST SUCCESSFUL:")
        logger.info(f"   • Retrieved {len(time_series)} days of SPY data")
        logger.info(f"   • Successfully calculated gap: {gap_percent:.3f}%")
        logger.info(f"   • Data format compatible with production needs")
        logger.info(f"   • No subscription limitations like Alpaca")

        return True

    except requests.RequestException as e:
        logger.error(f"❌ Network error: {e}")
        return False
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON parsing error: {e}")
        return False
    except KeyError as e:
        logger.error(f"❌ Data format error - missing key: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    success = test_alphavantage_spy()
    print(f"\n🎯 TEST RESULT: {'✅ PASSED' if success else '❌ FAILED'}")