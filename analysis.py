#!/usr/bin/env python3
"""
Analysis Module for Insider Trading Bot
Provides historical analysis and decision tracking capabilities.
"""

import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple
import pandas as pd
from collections import Counter, defaultdict

from database_manager import DatabaseManager

class StrategyAnalyzer:
    """Analyzes historical strategy performance and decision patterns"""

    def __init__(self, db_path: str = "insider_trading_bot.db"):
        """Initialize analyzer"""
        self.db_manager = DatabaseManager(db_path)
        self.logger = logging.getLogger(__name__)

    def get_decision_distribution(self, days: int = 30) -> Dict[str, Any]:
        """Get distribution of strategy decisions"""
        try:
            # Get all strategy scores from last N days
            with self.db_manager._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT decision, confidence_level, COUNT(*) as count,
                           AVG(total_score) as avg_score
                    FROM strategy_scores
                    WHERE analysis_date >= date('now', '-{} days')
                    GROUP BY decision, confidence_level
                    ORDER BY decision, confidence_level
                """.format(days))

                results = cursor.fetchall()

            distribution = {}
            for row in results:
                decision, confidence, count, avg_score = row
                if decision not in distribution:
                    distribution[decision] = {}
                distribution[decision][confidence] = {
                    'count': count,
                    'avg_score': avg_score
                }

            return distribution

        except Exception as e:
            self.logger.error(f"Error getting decision distribution: {e}")
            return {}

    def get_insider_role_performance(self, days: int = 30) -> Dict[str, Any]:
        """Analyze performance by insider role"""
        try:
            with self.db_manager._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT f.insider_title, s.decision, COUNT(*) as count,
                           AVG(s.total_score) as avg_score,
                           AVG(s.insider_role_score) as avg_role_score
                    FROM strategy_scores s
                    JOIN insider_filings f ON s.filing_id = f.filing_id
                    WHERE s.analysis_date >= date('now', '-{} days')
                    GROUP BY f.insider_title, s.decision
                    ORDER BY avg_score DESC
                """.format(days))

                results = cursor.fetchall()

            role_performance = defaultdict(lambda: defaultdict(dict))
            for row in results:
                title, decision, count, avg_score, avg_role_score = row
                role_performance[title][decision] = {
                    'count': count,
                    'avg_total_score': avg_score,
                    'avg_role_score': avg_role_score
                }

            return dict(role_performance)

        except Exception as e:
            self.logger.error(f"Error analyzing insider role performance: {e}")
            return {}

    def get_filter_effectiveness(self, days: int = 30) -> Dict[str, Any]:
        """Analyze how often each filter passes/fails"""
        try:
            with self.db_manager._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT
                        COUNT(*) as total_analyzed,
                        SUM(CASE WHEN volume_filter_passed = 1 THEN 1 ELSE 0 END) as volume_pass,
                        SUM(CASE WHEN atr_filter_passed = 1 THEN 1 ELSE 0 END) as atr_pass,
                        SUM(CASE WHEN spy_filter_passed = 1 THEN 1 ELSE 0 END) as spy_pass,
                        SUM(CASE WHEN volume_filter_passed = 1 AND atr_filter_passed = 1
                                    AND spy_filter_passed = 1 THEN 1 ELSE 0 END) as all_filters_pass
                    FROM strategy_scores
                    WHERE analysis_date >= date('now', '-{} days')
                """.format(days))

                result = cursor.fetchone()

            if result:
                total, volume_pass, atr_pass, spy_pass, all_pass = result
                return {
                    'total_analyzed': total,
                    'volume_filter': {
                        'pass_count': volume_pass,
                        'pass_rate': (volume_pass / total * 100) if total > 0 else 0
                    },
                    'atr_filter': {
                        'pass_count': atr_pass,
                        'pass_rate': (atr_pass / total * 100) if total > 0 else 0
                    },
                    'spy_filter': {
                        'pass_count': spy_pass,
                        'pass_rate': (spy_pass / total * 100) if total > 0 else 0
                    },
                    'all_filters': {
                        'pass_count': all_pass,
                        'pass_rate': (all_pass / total * 100) if total > 0 else 0
                    }
                }

            return {}

        except Exception as e:
            self.logger.error(f"Error analyzing filter effectiveness: {e}")
            return {}

    def get_scoring_patterns(self, days: int = 30) -> Dict[str, Any]:
        """Analyze scoring patterns and thresholds"""
        try:
            with self.db_manager._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT
                        total_score,
                        decision,
                        COUNT(*) as count,
                        AVG(insider_role_score) as avg_role,
                        AVG(ownership_type_score) as avg_ownership,
                        AVG(transaction_size_score) as avg_size,
                        AVG(earnings_season_bonus) as avg_earnings,
                        AVG(multi_insider_bonus) as avg_multi
                    FROM strategy_scores
                    WHERE analysis_date >= date('now', '-{} days')
                    GROUP BY total_score, decision
                    ORDER BY total_score DESC
                """.format(days))

                results = cursor.fetchall()

            scoring_patterns = []
            for row in results:
                score, decision, count, avg_role, avg_ownership, avg_size, avg_earnings, avg_multi = row
                scoring_patterns.append({
                    'total_score': score,
                    'decision': decision,
                    'count': count,
                    'avg_components': {
                        'role': avg_role,
                        'ownership': avg_ownership,
                        'size': avg_size,
                        'earnings': avg_earnings,
                        'multi_insider': avg_multi
                    }
                })

            return {'patterns': scoring_patterns}

        except Exception as e:
            self.logger.error(f"Error analyzing scoring patterns: {e}")
            return {}

    def get_symbol_analysis(self, days: int = 30) -> Dict[str, Any]:
        """Analyze performance by stock symbol"""
        try:
            with self.db_manager._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT
                        s.symbol,
                        COUNT(*) as filing_count,
                        SUM(CASE WHEN s.decision = 'BUY' THEN 1 ELSE 0 END) as buy_signals,
                        AVG(s.total_score) as avg_score,
                        AVG(f.total_value) as avg_transaction_value
                    FROM strategy_scores s
                    JOIN insider_filings f ON s.filing_id = f.filing_id
                    WHERE s.analysis_date >= date('now', '-{} days')
                    GROUP BY s.symbol
                    HAVING filing_count > 0
                    ORDER BY buy_signals DESC, avg_score DESC
                """.format(days))

                results = cursor.fetchall()

            symbol_analysis = []
            for row in results:
                symbol, count, buy_signals, avg_score, avg_value = row
                symbol_analysis.append({
                    'symbol': symbol,
                    'filing_count': count,
                    'buy_signals': buy_signals,
                    'buy_rate': (buy_signals / count * 100) if count > 0 else 0,
                    'avg_score': avg_score,
                    'avg_transaction_value': avg_value
                })

            return {'symbols': symbol_analysis}

        except Exception as e:
            self.logger.error(f"Error analyzing symbols: {e}")
            return {}

    def generate_comprehensive_report(self, days: int = 30) -> Dict[str, Any]:
        """Generate comprehensive analysis report"""
        self.logger.info(f"Generating comprehensive analysis report for last {days} days...")

        report = {
            'analysis_period': f"Last {days} days",
            'generated_at': datetime.now().isoformat(),
            'decision_distribution': self.get_decision_distribution(days),
            'insider_role_performance': self.get_insider_role_performance(days),
            'filter_effectiveness': self.get_filter_effectiveness(days),
            'scoring_patterns': self.get_scoring_patterns(days),
            'symbol_analysis': self.get_symbol_analysis(days)
        }

        return report

    def print_summary_report(self, days: int = 30):
        """Print a human-readable summary report"""
        report = self.generate_comprehensive_report(days)

        print(f"\n{'='*80}")
        print(f"INSIDER TRADING BOT - ANALYSIS REPORT")
        print(f"{'='*80}")
        print(f"Analysis Period: {report['analysis_period']}")
        print(f"Generated: {report['generated_at'][:19]}")
        print(f"{'='*80}")

        # Decision Distribution
        decisions = report['decision_distribution']
        if decisions:
            print(f"\n📊 DECISION DISTRIBUTION:")
            for decision, confidence_levels in decisions.items():
                total_count = sum(cl['count'] for cl in confidence_levels.values())
                print(f"  {decision}: {total_count} total")
                for confidence, data in confidence_levels.items():
                    print(f"    └─ {confidence}: {data['count']} (avg score: {data['avg_score']:.1f})")

        # Filter Effectiveness
        filters = report['filter_effectiveness']
        if filters and filters.get('total_analyzed', 0) > 0:
            print(f"\n🔍 FILTER EFFECTIVENESS:")
            print(f"  Total Filings Analyzed: {filters['total_analyzed']}")
            print(f"  Volume Filter Pass Rate: {filters['volume_filter']['pass_rate']:.1f}%")
            print(f"  ATR Filter Pass Rate: {filters['atr_filter']['pass_rate']:.1f}%")
            print(f"  SPY Filter Pass Rate: {filters['spy_filter']['pass_rate']:.1f}%")
            print(f"  All Filters Pass Rate: {filters['all_filters']['pass_rate']:.1f}%")

        # Top Symbols
        symbols = report['symbol_analysis'].get('symbols', [])
        if symbols:
            print(f"\n🏢 TOP PERFORMING SYMBOLS:")
            for i, symbol_data in enumerate(symbols[:5]):
                print(f"  {i+1}. {symbol_data['symbol']}: {symbol_data['buy_signals']} BUY signals "
                      f"({symbol_data['buy_rate']:.1f}% rate, avg score: {symbol_data['avg_score']:.1f})")

        # Insider Role Performance
        roles = report['insider_role_performance']
        if roles:
            print(f"\n👥 INSIDER ROLE PERFORMANCE:")
            role_totals = {}
            for role, decisions in roles.items():
                total_decisions = sum(d['count'] for d in decisions.values())
                buy_count = decisions.get('BUY', {}).get('count', 0)
                buy_rate = (buy_count / total_decisions * 100) if total_decisions > 0 else 0
                role_totals[role] = {'total': total_decisions, 'buy_rate': buy_rate, 'buy_count': buy_count}

            # Sort by buy rate
            sorted_roles = sorted(role_totals.items(), key=lambda x: x[1]['buy_rate'], reverse=True)
            for role, data in sorted_roles[:5]:
                print(f"  {role}: {data['buy_count']}/{data['total']} BUY signals ({data['buy_rate']:.1f}%)")

        print(f"\n{'='*80}")

def main():
    """Main analysis function"""
    import argparse

    parser = argparse.ArgumentParser(description='Analyze insider trading bot performance')
    parser.add_argument('--days', type=int, default=30, help='Days to analyze')
    parser.add_argument('--db-path', default='insider_trading_bot.db', help='Database path')
    parser.add_argument('--export', help='Export report to JSON file')

    args = parser.parse_args()

    analyzer = StrategyAnalyzer(args.db_path)

    # Print summary report
    analyzer.print_summary_report(args.days)

    # Export if requested
    if args.export:
        import json
        report = analyzer.generate_comprehensive_report(args.days)
        with open(args.export, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\n📄 Full report exported to: {args.export}")

if __name__ == "__main__":
    main()