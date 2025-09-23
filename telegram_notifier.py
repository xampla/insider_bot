#!/usr/bin/env python3
"""
Telegram Notification System for Insider Trading Bot
Sends notifications when BUY decisions are made by the strategy.
"""

import logging
import json
import os
from typing import Dict, Any, Optional
import requests
from dataclasses import asdict

from database_manager import InsiderFiling, StrategyScore


class TelegramNotifier:
    """Handles Telegram notifications for trading decisions"""

    def __init__(self, bot_token: str = None, chat_id: str = None):
        """
        Initialize Telegram notifier

        Args:
            bot_token: Telegram bot token
            chat_id: Chat ID to send messages to
        """
        self.logger = logging.getLogger(__name__)

        # Get credentials from environment or parameters
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')

        if not self.bot_token or not self.chat_id:
            self.logger.warning("⚠️ Telegram credentials not configured - notifications disabled")
            self.enabled = False
        else:
            self.enabled = True
            self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
            self.logger.info("✅ Telegram notifier initialized")

    def notify_buy_decision(self, filing: InsiderFiling, strategy_score: StrategyScore,
                           market_data: Dict = None) -> bool:
        """
        Send notification when strategy decides to BUY

        Args:
            filing: Insider filing that triggered the decision
            strategy_score: Strategy analysis results
            market_data: Additional market context

        Returns:
            True if notification sent successfully
        """
        if not self.enabled:
            return False

        try:
            # Create formatted message
            message = self._format_buy_notification(filing, strategy_score, market_data)

            # Send message
            return self._send_message(message)

        except Exception as e:
            self.logger.error(f"Failed to send Telegram notification: {e}")
            return False

    def notify_system_status(self, status: str, details: str = None) -> bool:
        """
        Send system status notifications

        Args:
            status: Status type (started, error, etc.)
            details: Additional details

        Returns:
            True if notification sent successfully
        """
        if not self.enabled:
            return False

        try:
            if status == "started":
                message = "🚀 **Insider Trading Bot Started**\n\n"
                message += "✅ Real SEC API connected\n"
                message += "✅ Alpaca trader initialized\n"
                message += "✅ Strategy engine ready\n"
                message += "✅ Monitoring for insider trades..."

            elif status == "error":
                message = f"❌ **System Error**\n\n{details}"

            elif status == "stopped":
                message = "⏹️ **Insider Trading Bot Stopped**\n\n"
                message += f"Details: {details}" if details else ""

            else:
                message = f"ℹ️ **System Status: {status}**\n\n{details}"

            return self._send_message(message)

        except Exception as e:
            self.logger.error(f"Failed to send status notification: {e}")
            return False

    def _format_buy_notification(self, filing: InsiderFiling, strategy_score: StrategyScore,
                                market_data: Dict = None) -> str:
        """Format BUY decision notification message"""

        # Header with eye-catching emoji
        message = "🚨 **INSIDER BUY SIGNAL** 🚨\n\n"

        # Company and insider info
        message += f"📈 **{filing.company_symbol}** - {filing.company_name}\n"
        message += f"👤 **Insider**: {filing.insider_name}\n"
        message += f"🏢 **Title**: {filing.insider_title}\n\n"

        # Transaction details
        message += f"💰 **Transaction Details**:\n"
        message += f"• **Type**: {'Purchase' if filing.transaction_code == 'P' else 'Sale'} ({filing.transaction_code})\n"
        message += f"• **Shares**: {filing.shares_traded:,.0f}\n"
        message += f"• **Price**: ${filing.price_per_share:.2f}\n"
        message += f"• **Total Value**: ${filing.total_value:,.0f}\n"
        message += f"• **Date**: {filing.transaction_date}\n\n"

        # Strategy analysis
        message += f"🎯 **Strategy Analysis**:\n"
        message += f"• **Total Score**: {strategy_score.total_score}/10\n"
        message += f"• **Confidence**: {strategy_score.confidence_level}\n"
        message += f"• **Decision**: {strategy_score.decision}\n\n"

        # Score breakdown
        message += f"📊 **Score Breakdown**:\n"
        message += f"• **Insider Role**: {strategy_score.insider_role_score} pts\n"
        message += f"• **Transaction Size**: {strategy_score.transaction_size_score} pts\n"
        message += f"• **Ownership Type**: {strategy_score.ownership_type_score} pts\n"

        if strategy_score.earnings_season_bonus > 0:
            message += f"• **Earnings Bonus**: +{strategy_score.earnings_season_bonus} pts\n"
        if strategy_score.multi_insider_bonus > 0:
            message += f"• **Multi-Insider Bonus**: +{strategy_score.multi_insider_bonus} pts\n"

        # Risk filters
        message += f"\n🛡️ **Risk Filters**:\n"
        message += f"• **Volume Filter**: {'✅ PASS' if strategy_score.volume_filter_passed else '❌ FAIL'}\n"
        message += f"• **ATR Filter**: {'✅ PASS' if strategy_score.atr_filter_passed else '❌ FAIL'}\n"
        message += f"• **SPY Filter**: {'✅ PASS' if strategy_score.spy_filter_passed else '❌ FAIL'}\n\n"

        # Market context if available
        if market_data:
            message += f"📈 **Market Context**:\n"
            message += f"• **Current Price**: ${market_data.get('current_price', filing.price_per_share):.2f}\n"
            message += f"• **Volume**: {market_data.get('volume', 'N/A')}\n"
            message += f"• **ATR**: {market_data.get('atr_14', 'N/A')}\n\n"

        # Call to action
        message += f"⚡ **Action**: Consider reviewing this opportunity for manual evaluation.\n"
        message += f"🕐 **Time**: {strategy_score.analysis_date}\n"
        message += f"🤖 **Source**: WSV Insider Trading Bot"

        return message

    def _send_message(self, message: str) -> bool:
        """Send message via Telegram API"""
        try:
            url = f"{self.base_url}/sendMessage"

            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'Markdown',  # Enable markdown formatting
                'disable_web_page_preview': True
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()

            result = response.json()
            if result.get('ok'):
                self.logger.info("✅ Telegram notification sent successfully")
                return True
            else:
                self.logger.error(f"Telegram API error: {result}")
                return False

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error sending Telegram message: {e}")
            return False

    def test_connection(self) -> bool:
        """Test Telegram bot connection"""
        if not self.enabled:
            self.logger.warning("Telegram not configured")
            return False

        try:
            test_message = "🧪 **Test Message**\n\nInsider Trading Bot connection test successful! ✅"
            return self._send_message(test_message)

        except Exception as e:
            self.logger.error(f"Telegram connection test failed: {e}")
            return False


def main():
    """Test the Telegram notifier"""
    import os
    from dotenv import load_dotenv
    from datetime import datetime

    load_dotenv()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Initialize notifier
    notifier = TelegramNotifier()

    print("🧪 Testing Telegram notifier...")

    # Test connection
    if notifier.test_connection():
        print("✅ Telegram connection test successful!")

        # Test system status notification
        notifier.notify_system_status("started")
        print("✅ System status notification sent!")

    else:
        print("❌ Telegram connection test failed!")


if __name__ == "__main__":
    main()