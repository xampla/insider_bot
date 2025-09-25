#!/usr/bin/env python3
"""
Debug script to test service environment
Run this to see what environment the service has access to
"""

import os
import sys
import logging
from pathlib import Path

# Setup logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('service_debug.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def debug_environment():
    """Debug the service environment"""
    logger.info("🔍 SERVICE ENVIRONMENT DEBUG")
    logger.info("=" * 50)

    # Working directory
    logger.info(f"📁 Current directory: {os.getcwd()}")
    logger.info(f"📂 Script directory: {Path(__file__).parent}")

    # Python environment
    logger.info(f"🐍 Python executable: {sys.executable}")
    logger.info(f"🐍 Python version: {sys.version}")
    logger.info(f"🐍 Python path: {sys.path}")

    # Environment variables
    logger.info("🔧 Environment variables:")
    key_env_vars = ['PATH', 'VIRTUAL_ENV', 'HOME', 'USER', 'PWD']
    for var in key_env_vars:
        value = os.getenv(var, 'NOT SET')
        logger.info(f"   {var}: {value}")

    # File checks
    logger.info("📋 File existence check:")
    files_to_check = [
        'main.py',
        '.env',
        'insider_bot_env/bin/python',
        'insider_bot_env/pyvenv.cfg',
        'insider_trading_bot.db'
    ]

    for file_path in files_to_check:
        exists = "✅" if os.path.exists(file_path) else "❌"
        logger.info(f"   {exists} {file_path}")

    # Import tests
    logger.info("📦 Import tests:")
    import_tests = [
        'os',
        'sys',
        'logging',
        'dotenv',
        'requests',
        'sqlite3',
        'pandas'
    ]

    for module in import_tests:
        try:
            __import__(module)
            logger.info(f"   ✅ {module}")
        except ImportError as e:
            logger.info(f"   ❌ {module}: {e}")

    # Alpaca test
    logger.info("🦙 Alpaca import test:")
    try:
        from alpaca.trading.client import TradingClient
        logger.info("   ✅ alpaca.trading.client.TradingClient")
    except ImportError as e:
        logger.info(f"   ❌ alpaca.trading.client.TradingClient: {e}")

    # .env test
    logger.info("🔐 Environment file test:")
    try:
        from dotenv import load_dotenv
        load_dotenv()

        # Check critical env vars (without showing values)
        env_checks = {
            'ALPACA_API_KEY': os.getenv('ALPACA_API_KEY'),
            'ALPACA_SECRET_KEY': os.getenv('ALPACA_SECRET_KEY'),
            'SEC_USER_AGENT': os.getenv('SEC_USER_AGENT')
        }

        for key, value in env_checks.items():
            status = "✅ SET" if value else "❌ MISSING"
            logger.info(f"   {status} {key}")

    except Exception as e:
        logger.info(f"   ❌ .env loading failed: {e}")

    logger.info("🎯 Debug complete - check service_debug.log for full output")

if __name__ == "__main__":
    debug_environment()