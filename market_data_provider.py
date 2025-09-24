#!/usr/bin/env python3
"""
Market Data Provider for Insider Trading Bot
Retrieves historical and current market data using Finnhub API.
Date-agnostic implementation supporting both current and historical data.
"""

import logging
import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from dataclasses import asdict

from database_manager import MarketData, DatabaseManager


class MarketDataProvider:
    """
    Provides market data using Finnhub API
    Supports both historical and current data retrieval
    """

    def __init__(self, api_key: str = None, db_manager: DatabaseManager = None):
        """
        Initialize market data provider

        Args:
            api_key: Finnhub API key (will read from env if not provided)
            db_manager: Database manager for caching data
        """
        self.logger = logging.getLogger(__name__)

        # API configuration
        self.api_key = api_key or os.getenv('FINNHUB_API_KEY')
        if not self.api_key:
            raise ValueError("Finnhub API key required. Set FINNHUB_API_KEY environment variable.")

        self.base_url = "https://finnhub.io/api/v1"
        self.request_delay = 0.1  # Rate limiting

        # Database for caching
        self.db_manager = db_manager

        self.logger.info("MarketDataProvider initialized with Finnhub API")

    def get_market_data(self, symbol: str, date: str, force_refresh: bool = False) -> Optional[MarketData]:
        """
        Get comprehensive market data for a symbol on a specific date

        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            date: Date in YYYY-MM-DD format
            force_refresh: Force API call even if cached data exists

        Returns:
            MarketData object with all required fields
        """
        try:
            self.logger.info(f"Getting market data for {symbol} on {date}")

            # Check cache first (unless force refresh)
            if not force_refresh and self.db_manager:
                cached_data = self.db_manager.get_market_data(symbol, date)
                if cached_data:
                    self.logger.info(f"Using cached market data for {symbol} on {date}")
                    return cached_data

            # Determine if this is current or historical data
            target_date = datetime.strptime(date, '%Y-%m-%d').date()
            today = datetime.now().date()
            is_historical = target_date < today

            if is_historical:
                market_data = self._get_historical_market_data(symbol, date)
            else:
                market_data = self._get_current_market_data(symbol, date)

            # Store in database cache
            if market_data and self.db_manager:
                self.db_manager.store_market_data(market_data)
                self.logger.info(f"Cached market data for {symbol} on {date}")

            return market_data

        except Exception as e:
            self.logger.error(f"Error getting market data for {symbol} on {date}: {e}")
            return None

    def _get_historical_market_data(self, symbol: str, target_date: str) -> Optional[MarketData]:
        """Get historical market data for a specific date"""
        try:
            target_dt = datetime.strptime(target_date, '%Y-%m-%d')

            # Get data range: 45 days before target date to calculate ATR and avg volume
            end_date = target_dt
            start_date = target_dt - timedelta(days=45)

            # Convert to Unix timestamps
            start_ts = int(start_date.timestamp())
            end_ts = int(end_date.timestamp())

            # Get candlestick data
            candles_data = self._fetch_candlestick_data(symbol, start_ts, end_ts, 'D')

            if not candles_data:
                self.logger.warning(f"No candlestick data available for {symbol} on {target_date}")
                return None

            # Convert to DataFrame for calculations
            df = pd.DataFrame(candles_data)
            df['date'] = pd.to_datetime(df['t'], unit='s')
            df = df.sort_values('date')

            # Find the exact target date data
            target_date_str = target_dt.strftime('%Y-%m-%d')
            target_row = df[df['date'].dt.strftime('%Y-%m-%d') == target_date_str]

            if target_row.empty:
                self.logger.warning(f"No data available for exact date {target_date}")
                # Use the closest available date
                closest_idx = (df['date'] - target_dt).abs().idxmin()
                target_row = df.loc[[closest_idx]]
                actual_date = target_row.iloc[0]['date'].strftime('%Y-%m-%d')
                self.logger.info(f"Using closest available date: {actual_date}")

            target_data = target_row.iloc[0]

            # Calculate technical indicators
            atr_14 = self._calculate_atr(df, 14)
            avg_volume_30 = self._calculate_avg_volume(df, 30)

            # Get the ATR value for target date (last calculated value)
            target_atr = atr_14.iloc[-1] if len(atr_14) > 0 else 0.0
            target_avg_volume = avg_volume_30.iloc[-1] if len(avg_volume_30) > 0 else float(target_data['v'])

            return MarketData(
                symbol=symbol,
                date=target_date,
                open_price=float(target_data['o']),
                high_price=float(target_data['h']),
                low_price=float(target_data['l']),
                close_price=float(target_data['c']),
                volume=float(target_data['v']),
                atr_14=float(target_atr),
                avg_volume_30=float(target_avg_volume)
            )

        except Exception as e:
            self.logger.error(f"Error getting historical data for {symbol}: {e}")
            return None

    def _get_current_market_data(self, symbol: str, date: str) -> Optional[MarketData]:
        """Get current market data (for today's date)"""
        try:
            # For current data, we still need historical data to calculate ATR and avg volume
            end_date = datetime.now()
            start_date = end_date - timedelta(days=45)

            # Get historical candlestick data
            start_ts = int(start_date.timestamp())
            end_ts = int(end_date.timestamp())

            candles_data = self._fetch_candlestick_data(symbol, start_ts, end_ts, 'D')

            if not candles_data:
                self.logger.warning(f"No historical data available for {symbol}")
                return None

            # Get current quote
            current_quote = self._fetch_current_quote(symbol)
            if not current_quote:
                self.logger.warning(f"No current quote available for {symbol}")
                return None

            # Convert candlestick data to DataFrame
            df = pd.DataFrame(candles_data)
            df['date'] = pd.to_datetime(df['t'], unit='s')
            df = df.sort_values('date')

            # Calculate technical indicators from historical data
            atr_14 = self._calculate_atr(df, 14)
            avg_volume_30 = self._calculate_avg_volume(df, 30)

            # Use current quote for today's prices
            current_price = current_quote.get('c', 0)  # Current price

            return MarketData(
                symbol=symbol,
                date=date,
                open_price=current_quote.get('o', current_price),
                high_price=current_quote.get('h', current_price),
                low_price=current_quote.get('l', current_price),
                close_price=current_price,
                volume=0.0,  # Current volume not available in basic quote
                atr_14=float(atr_14.iloc[-1]) if len(atr_14) > 0 else 0.0,
                avg_volume_30=float(avg_volume_30.iloc[-1]) if len(avg_volume_30) > 0 else 0.0
            )

        except Exception as e:
            self.logger.error(f"Error getting current data for {symbol}: {e}")
            return None

    def _fetch_candlestick_data(self, symbol: str, start_ts: int, end_ts: int, resolution: str = 'D') -> Optional[Dict]:
        """Fetch candlestick data from Finnhub API"""
        try:
            url = f"{self.base_url}/stock/candle"
            params = {
                'symbol': symbol,
                'resolution': resolution,
                'from': start_ts,
                'to': end_ts,
                'token': self.api_key
            }

            time.sleep(self.request_delay)  # Rate limiting
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            if data.get('s') == 'ok' and data.get('c'):
                return {
                    't': data['t'],  # timestamps
                    'o': data['o'],  # open
                    'h': data['h'],  # high
                    'l': data['l'],  # low
                    'c': data['c'],  # close
                    'v': data['v']   # volume
                }
            else:
                self.logger.warning(f"No candlestick data returned for {symbol}: {data.get('s', 'unknown status')}")
                return None

        except Exception as e:
            self.logger.error(f"Error fetching candlestick data for {symbol}: {e}")
            return None

    def _fetch_current_quote(self, symbol: str) -> Optional[Dict]:
        """Fetch current quote from Finnhub API"""
        try:
            url = f"{self.base_url}/quote"
            params = {
                'symbol': symbol,
                'token': self.api_key
            }

            time.sleep(self.request_delay)  # Rate limiting
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            return response.json()

        except Exception as e:
            self.logger.error(f"Error fetching current quote for {symbol}: {e}")
            return None

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Calculate Average True Range (ATR)

        Args:
            df: DataFrame with OHLC data
            period: ATR period (default 14)

        Returns:
            Series with ATR values
        """
        try:
            if len(df) < period + 1:
                return pd.Series([0.0])

            # Calculate True Range components
            hl = df['h'] - df['l']  # High - Low
            hc = abs(df['h'] - df['c'].shift(1))  # High - Previous Close
            lc = abs(df['l'] - df['c'].shift(1))  # Low - Previous Close

            # True Range is the maximum of the three
            tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)

            # ATR is the moving average of True Range
            atr = tr.rolling(window=period).mean()

            return atr

        except Exception as e:
            self.logger.error(f"Error calculating ATR: {e}")
            return pd.Series([0.0])

    def _calculate_avg_volume(self, df: pd.DataFrame, period: int = 30) -> pd.Series:
        """
        Calculate average volume over specified period

        Args:
            df: DataFrame with volume data
            period: Period for average (default 30)

        Returns:
            Series with average volume values
        """
        try:
            if len(df) < period:
                return pd.Series([df['v'].mean() if len(df) > 0 else 0.0])

            return df['v'].rolling(window=period).mean()

        except Exception as e:
            self.logger.error(f"Error calculating average volume: {e}")
            return pd.Series([0.0])

    def bulk_update_market_data(self, symbols: List[str], date: str, force_refresh: bool = False) -> Dict[str, bool]:
        """
        Update market data for multiple symbols at once

        Args:
            symbols: List of stock symbols
            date: Date in YYYY-MM-DD format
            force_refresh: Force API calls even if cached data exists

        Returns:
            Dictionary mapping symbol -> success status
        """
        results = {}

        self.logger.info(f"Bulk updating market data for {len(symbols)} symbols on {date}")

        for symbol in symbols:
            try:
                market_data = self.get_market_data(symbol, date, force_refresh)
                results[symbol] = market_data is not None

                if market_data:
                    self.logger.info(f"✅ {symbol}: Updated successfully")
                else:
                    self.logger.warning(f"❌ {symbol}: Failed to update")

            except Exception as e:
                self.logger.error(f"❌ {symbol}: Error during update: {e}")
                results[symbol] = False

        success_count = sum(results.values())
        self.logger.info(f"Bulk update completed: {success_count}/{len(symbols)} successful")

        return results


def main():
    """Test the market data provider"""
    from dotenv import load_dotenv

    load_dotenv()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("🧪 Testing Market Data Provider...")

    # Initialize components
    try:
        db_manager = DatabaseManager()
        provider = MarketDataProvider(db_manager=db_manager)

        # Test with recent date
        test_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        test_symbol = 'AAPL'

        print(f"\n📊 Testing market data retrieval for {test_symbol} on {test_date}")

        market_data = provider.get_market_data(test_symbol, test_date)

        if market_data:
            print(f"✅ Market data retrieved successfully:")
            print(f"   Close Price: ${market_data.close_price:.2f}")
            print(f"   Volume: {market_data.volume:,.0f}")
            print(f"   ATR (14): ${market_data.atr_14:.2f}")
            print(f"   Avg Volume (30): {market_data.avg_volume_30:,.0f}")
        else:
            print("❌ Failed to retrieve market data")

        # Test bulk update
        print(f"\n📈 Testing bulk update for multiple symbols...")
        symbols = ['AAPL', 'NVDA', 'TSLA']
        results = provider.bulk_update_market_data(symbols, test_date)

        for symbol, success in results.items():
            status = "✅" if success else "❌"
            print(f"   {status} {symbol}")

    except Exception as e:
        print(f"❌ Test failed: {e}")


if __name__ == "__main__":
    main()