#!/usr/bin/env python3
import sys
import inspect
import typing
from notifier import get_alert_history, Notifier
from market_client import MarketClient
from paper_trading import PracticePortfolio, get_usd_inr_rate

print("============================================================")
print("🧪 TESTING BUG FIXES & EDGE CASE RESILIENCE")
print("============================================================")

# 1. Test Notifier type annotations
hints = typing.get_type_hints(get_alert_history)
assert "return" in hints, "Failed to resolve type hints for get_alert_history"
print("[✓ PASS] Notifier type annotations inspect cleanly without NameError")

# 2. Test Market Client timeframe ranges
client = MarketClient()
tf_1m = client.get_technical_data("NVDA", "1m")
assert tf_1m is not None, "1m technical data failed"
assert tf_1m["rsi_14"] is not None, "1m RSI is None"
assert tf_1m["ema_9"] is not None, "1m EMA9 is None"
assert tf_1m["bb_pct_b"] is not None, "1m BB %B is None"
print(f"[✓ PASS] 1m technicals calculated with 5d range: close=${tf_1m['latest_close']}, RSI={tf_1m['rsi_14']}")

# 3. Test PaperTrading multi-currency position averaging
test_pf = PracticePortfolio(file_path="test_temp_portfolio.json")
test_pf.reset(1000.0)

# Buy 1: 18.42 shares of ICICIBANK.NS @ ₹1302.50 ($13.57 USD) -> $250 USD
res1 = test_pf.buy("ICICIBANK.NS", price=1302.50, allocation=250.0, currency="INR")
assert res1["success"] is True, f"Buy 1 failed: {res1}"
pos1 = test_pf.positions["ICICIBANK.NS"]
assert 1200 <= pos1["entry_price"] <= 1400, f"Entry price should be native INR (~1302), got {pos1['entry_price']}"
assert 10 <= pos1["entry_price_usd"] <= 16, f"Entry price USD should be ~$13.57, got {pos1['entry_price_usd']}"
print(f"[✓ PASS] Initial Indian asset buy: {pos1['shares']} shares @ ₹{pos1['entry_price']} (${pos1['entry_price_usd']} USD)")

# Buy 2 (Averaging in): Buy another $250 of ICICIBANK.NS @ ₹1350.00
res2 = test_pf.buy("ICICIBANK.NS", price=1350.00, allocation=250.0, currency="INR")
assert res2["success"] is True, f"Buy 2 failed: {res2}"
pos2 = test_pf.positions["ICICIBANK.NS"]
assert 1200 <= pos2["entry_price"] <= 1400, f"Averaged entry price should remain native INR (~1326), got {pos2['entry_price']}"
assert 10 <= pos2["entry_price_usd"] <= 16, f"Averaged entry price USD should remain ~$13.8, got {pos2['entry_price_usd']}"
assert abs(pos2["invested"] - 500.0) < 1.0, f"Invested should be ~$500, got {pos2['invested']}"
print(f"[✓ PASS] Averaged in Indian asset: {pos2['shares']} shares @ ₹{pos2['entry_price']} (${pos2['entry_price_usd']} USD), Invested=${pos2['invested']}")

# Sell half @ ₹1400
sell_res = test_pf.sell("ICICIBANK.NS", price=1400.00, shares_to_sell=pos2["shares"] / 2)
assert sell_res["success"] is True, f"Sell failed: {sell_res}"
assert sell_res["pnl"] > 0, f"Expected profit, got {sell_res['pnl']}"
assert 0 < sell_res["pnl_pct"] < 20, f"Expected reasonable P&L % (~5-6%), got {sell_res['pnl_pct']}%"
print(f"[✓ PASS] Liquidated half position: P&L=+${sell_res['pnl']} (+{sell_res['pnl_pct']}%)")

# Cleanup temp file
import os
if os.path.exists("test_temp_portfolio.json"):
    os.remove("test_temp_portfolio.json")

print("============================================================")
print("🎉 ALL REGRESSION TESTS PASSED CLEANLY!")
print("============================================================")
