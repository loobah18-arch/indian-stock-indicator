import unittest
from market_client import normalize_symbol, MarketClient
from strategy import IndicatorStrategy
from notifier import Notifier

class TestIndianStockIndicator(unittest.TestCase):

    def test_normalize_symbol(self):
        self.assertEqual(normalize_symbol("RELIANCE"), "RELIANCE.NS")
        self.assertEqual(normalize_symbol("tcs"), "TCS.NS")
        self.assertEqual(normalize_symbol("INFY.NS"), "INFY.NS")
        self.assertEqual(normalize_symbol("TMCV.BO"), "TMCV.BO")
        self.assertEqual(normalize_symbol("^NSEI"), "^NSEI")

    def test_rsi_calculation(self):
        client = MarketClient()
        prices = [100.0] * 20
        self.assertEqual(client._calc_rsi(prices), 100.0)

        increasing = [float(i) for i in range(1, 30)]
        self.assertEqual(client._calc_rsi(increasing), 100.0)

        alternating = [100.0, 105.0, 100.0, 105.0] * 6
        rsi = client._calc_rsi(alternating)
        self.assertIsNotNone(rsi)
        self.assertTrue(40.0 <= rsi <= 60.0)

    def test_strategy_precision_scoring(self):
        strategy = IndicatorStrategy(min_upside_pct=5.0, rsi_overbought=72.0)

        # Bullish setup with strong confluence
        data_strong_buy = {
            "symbol": "RELIANCE.NS",
            "analyst": {
                "name": "Reliance Industries",
                "current_price": 1200.0,
                "target_mean_price": 1600.0,
                "upside_pct": 33.33,
                "recommendation_key": "strong_buy",
                "recommendation_mean": 1.3,
                "analyst_count": 26,
                "breakdown": {"strongBuy": 10, "buy": 15, "hold": 1, "sell": 0, "strongSell": 0}
            },
            "technical": {
                "latest_close": 1200.0,
                "rsi_14": 52.0,
                "trend_above_ema200": True,
                "trend_above_ema21": True,
                "trend_above_ema9": True,
                "ema_alignment_bullish": True,
                "macd_bullish": True,
                "macd_expanding": True,
                "bb_pct_b": 0.45,
                "bb_bandwidth": 8.0,
                "atr_14": 20.0,
                "rvol": 1.4
            }
        }
        res_sb = strategy.analyze(data_strong_buy)
        self.assertEqual(res_sb["signal"], "STRONG BUY")
        self.assertGreaterEqual(res_sb["score"], 80)
        self.assertIn("execution", res_sb)
        self.assertGreater(res_sb["execution"]["take_profit_1"], 1200.0)
        self.assertLess(res_sb["execution"]["stop_loss"], 1200.0)

        # Overbought condition should turn into HOLD (WAIT FOR PULLBACK)
        data_overbought = dict(data_strong_buy)
        data_overbought["technical"] = dict(data_strong_buy["technical"])
        data_overbought["technical"]["rsi_14"] = 82.0
        res_ob = strategy.analyze(data_overbought)
        self.assertEqual(res_ob["signal"], "HOLD")
        self.assertIn("PULLBACK", res_ob["action_verb"])

        # Bearish breakdown
        data_sell = {
            "symbol": "BEARISH.NS",
            "analyst": {
                "name": "Bearish Corp",
                "current_price": 500.0,
                "target_mean_price": 400.0,
                "upside_pct": -20.0,
                "recommendation_key": "underperform",
                "recommendation_mean": 4.2,
                "analyst_count": 15,
                "breakdown": {"strongBuy": 0, "buy": 1, "hold": 3, "sell": 8, "strongSell": 5}
            },
            "technical": {
                "latest_close": 500.0,
                "rsi_14": 28.0,
                "trend_above_ema200": False,
                "trend_above_ema21": False,
                "trend_above_ema9": False,
                "ema_alignment_bullish": False,
                "macd_bullish": False,
                "macd_expanding": False,
                "bb_pct_b": 0.05,
                "bb_bandwidth": 15.0,
                "atr_14": 15.0,
                "rvol": 0.5
            }
        }
        res_sell = strategy.analyze(data_sell)
        self.assertIn(res_sell["signal"], ["SELL", "STRONG SELL"])
        self.assertLessEqual(res_sell["score"], 45)

    def test_buy_and_sell_triggers(self):
        strategy = IndicatorStrategy()
        data_buy = {
            "symbol": "NVDA",
            "analyst": {"current_price": 200.0, "target_mean_price": 280.0, "upside_pct": 40.0, "currency": "USD"},
            "technical": {
                "latest_close": 200.0, "rsi_14": 55.0, "trend_above_ema200": True,
                "trend_above_ema21": True, "trend_above_ema9": True, "ema_alignment_bullish": True,
                "macd_bullish": True, "macd_expanding": True, "atr_14": 6.0, "rvol": 1.5
            }
        }
        res = strategy.analyze(data_buy)
        self.assertIn("triggers", res)
        triggers = res["triggers"]
        self.assertIn("buy", triggers)
        self.assertIn("sell", triggers)
        self.assertTrue(triggers["buy"]["triggered"])
        self.assertIn("WHEN TO BUY", triggers["buy"]["instruction"])
        self.assertIn("WHEN TO SELL", triggers["sell"]["instruction"])

    def test_market_overview_structure(self):
        client = MarketClient()
        overview = client.get_market_overview("US")
        self.assertIn("regime", overview)
        self.assertIn("bias", overview)
        self.assertIn("guidance", overview)
        self.assertIn("indices", overview)
        self.assertGreater(len(overview["indices"]), 0)

if __name__ == "__main__":
    unittest.main()
