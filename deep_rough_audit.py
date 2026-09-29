#!/usr/bin/env python3
"""
Deep Rough & Comprehensive Stress Audit for Quantitative Market Terminal.
Tests:
1. Live Frontend HTML & Component Wiring
2. Multi-Market & Multi-Timeframe Quant Confluence Engine (US, India, Gold, Crypto, Forex)
3. Edge-Case Resilience (Invalid tickers, slashes, boundary allocations, rapid parallel bursts)
4. End-to-End Real Live Trade Execution (Buy, Multi-currency FX, Sell, Realized P&L, Audit)
5. AlphaQuant AI Copilot & 24/7 Signals Stream
"""
import sys
import time
import json
import urllib.request
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "http://127.0.0.1:5000"

failures = []
passes = []

def record_pass(test_name: str, detail: str = ""):
    passes.append(test_name)
    print(f"  [✓ PASS] {test_name}" + (f" -> {detail}" if detail else ""))

def record_fail(test_name: str, detail: str):
    failures.append((test_name, detail))
    print(f"  [✗ FAIL] {test_name} -> {detail}")

def http_get(path: str, timeout: float = 12.0) -> tuple:
    url = f"{BASE_URL}{path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DeepAudit/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(data)
            except Exception:
                return resp.status, data
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(err_body)
        except Exception:
            return e.code, err_body
    except Exception as e:
        return 0, str(e)

def http_post(path: str, payload: dict, timeout: float = 15.0) -> tuple:
    url = f"{BASE_URL}{path}"
    data_bytes = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json", "User-Agent": "DeepAudit/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(data)
            except Exception:
                return resp.status, data
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(err_body)
        except Exception:
            return e.code, err_body
    except Exception as e:
        return 0, str(e)

print("\n" + "=" * 70)
print("🔥 RUNNING HARD, ROUGH STRESS TEST & DEEP THOROUGH AUDIT")
print("=" * 70)

# -------------------------------------------------------------
# 1. FRONTEND HTML & COMPONENT INTEGRITY AUDIT
# -------------------------------------------------------------
print("\n--- 1. Testing Frontend HTML & Component Wiring ---")
status, html = http_get("/")
if status == 200 and isinstance(html, str):
    record_pass("Root Terminal HTML 200 OK")
    
    ui_elements = [
        ("TradingView iframe container", 'id="tradingview_iframe"'),
        ("Timeframe selector [1m]", 'id="tfBtn_1m"'),
        ("Timeframe selector [5m]", 'id="tfBtn_5m"'),
        ("Timeframe selector [15m]", 'id="tfBtn_15m"'),
        ("Timeframe selector [30m]", 'id="tfBtn_30m"'),
        ("Timeframe selector [1h]", 'id="tfBtn_1h"'),
        ("Timeframe selector [1d]", 'id="tfBtn_1d"'),
        ("Timeframe selector [1w]", 'id="tfBtn_1w"'),
        ("Special TV map & slash fix", 'SPECIAL_TV_MAP'),
        ("Persistent currentChartSymbol tracking", 'currentChartSymbol'),
        ("TradingView top toolbar enabled", 'hide_top_toolbar=0'),
        ("Practice Sandbox Tab", 'id="tabPractice"'),
        ("Practice Order Console Input", 'id="pracInputSymbol"'),
        ("Practice Order Console Buy Button", '🛒 Buy Stock'),
        ("Practice Order Console Sell Button", '🔴 Sell / Close'),
        ("Practice Position Table Sell Button", '🔴 Sell / Exit'),
        ("Dynamic Holdings Chips Container", 'id="pracHoldingsChips"'),
        ("AI Market Chatbot Tab", 'id="tabAI"'),
        ("24/7 Signals Feed Container", 'id="signalsFeedBody"'),
        ("Signals Count Badge", 'id="signalsFeedCount"'),
    ]
    for label, needle in ui_elements:
        if needle in html:
            record_pass(f"UI Element: {label}")
        else:
            record_fail(f"UI Element: {label}", f"Missing '{needle}' in HTML")
else:
    record_fail("Root Terminal HTML 200 OK", f"Status: {status}")

# -------------------------------------------------------------
# 2. MULTI-ASSET & MULTI-TIMEFRAME QUANT ANALYSIS ENGINE
# -------------------------------------------------------------
print("\n--- 2. Testing Multi-Asset & Multi-Timeframe Quant Engine ---")
matrix = [
    ("NVDA", "1m", "US Equity Intraday 1m"),
    ("NVDA", "30m", "US Equity Swing 30m"),
    ("AAPL", "1d", "US Equity Daily 1d"),
    ("RELIANCE.NS", "15m", "Indian NSE Intraday 15m"),
    ("TCS.NS", "1d", "Indian NSE Daily 1d"),
    ("XAU/USD", "1m", "Commodity Gold Intraday 1m"),
    ("XAU/USD", "30m", "Commodity Gold Intraday 30m"),
    ("BTC/USD", "15m", "Crypto Bitcoin Intraday 15m"),
    ("ETH/USD", "1h", "Crypto Ethereum Intraday 1h"),
    ("EUR/USD", "1d", "Forex EUR/USD Daily"),
    ("USD/INR", "1d", "Forex USD/INR Daily"),
]

for sym, tf, desc in matrix:
    path = f"/api/analyze?ticker={urllib.parse.quote(sym)}&timeframe={tf}"
    s, data = http_get(path, timeout=15.0)
    if s == 200 and isinstance(data, dict) and data.get("symbol"):
        price = data.get("current_price", 0)
        score = data.get("score", 0)
        signal = data.get("signal", "HOLD")
        levels = data.get("execution", {})
        entry = levels.get("entry_zone", "N/A")
        sl = levels.get("stop_loss", "N/A")
        record_pass(f"{desc} ({sym} [{tf}])", f"Price={price}, Score={score}/100, Signal={signal}, Entry={entry}, SL={sl}")
    else:
        record_fail(f"{desc} ({sym} [{tf}])", f"Status={s}, Data={data}")

# -------------------------------------------------------------
# 3. ROUGH BOUNDARY & MALICIOUS INPUT TESTING
# -------------------------------------------------------------
print("\n--- 3. Testing Rough & Boundary Edge Cases ---")

# A. Non-existent ticker
s, res = http_get("/api/analyze?ticker=INVALID_ZZZ_999&timeframe=1d")
if s in (200, 404) and isinstance(res, dict) and "error" in res:
    record_pass("Non-Existent Ticker Handled Cleanly", res.get("error"))
else:
    record_fail("Non-Existent Ticker Handled Cleanly", f"s={s}, res={res}")

# B. Empty query
s, res = http_get("/api/analyze?ticker=&timeframe=1d")
if s in (200, 400, 404) and isinstance(res, dict):
    record_pass("Empty Ticker Handled Safely", "No server crash")
else:
    record_fail("Empty Ticker Handled Safely", f"s={s}, res={res}")

# C. Arbitrary slash pair (XMA/USD)
s, res = http_get("/api/analyze?ticker=XMA/USD&timeframe=30m")
if s in (200, 404) and isinstance(res, dict):
    record_pass("Arbitrary Slash Pair (XMA/USD) Safe", "Graceful response without 500 error")
else:
    record_fail("Arbitrary Slash Pair (XMA/USD) Safe", f"s={s}, res={res}")

# D. Route Aliases
s1, r1 = http_get("/api/practice")
s2, r2 = http_get("/api/practice/portfolio")
if s1 == 200 and s2 == 200 and isinstance(r1, dict) and isinstance(r2, dict):
    record_pass("Practice Route Aliases", "/api/practice & /api/practice/portfolio both 200 OK")
else:
    record_fail("Practice Route Aliases", f"s1={s1}, s2={s2}")

s_sig1, _ = http_get("/api/signals-feed")
s_sig2, _ = http_get("/api/signals")
if s_sig1 == 200 and s_sig2 == 200:
    record_pass("Signals Route Aliases", "/api/signals-feed & /api/signals both 200 OK")
else:
    record_fail("Signals Route Aliases", f"s_sig1={s_sig1}, s_sig2={s_sig2}")

# E. High Concurrency Burst (6 Simultaneous Parallel Workers)
print("  Burst testing: 6 simultaneous parallel worker requests...")
burst_symbols = ["NVDA", "AAPL", "MSFT", "RELIANCE.NS", "XAU/USD", "BTC/USD"]
with ThreadPoolExecutor(max_workers=6) as executor:
    futures = {
        executor.submit(http_get, f"/api/analyze?ticker={urllib.parse.quote(sym)}&timeframe=15m"): sym
        for sym in burst_symbols
    }
    burst_ok = 0
    for future in as_completed(futures):
        sym = futures[future]
        st, d = future.result()
        if st == 200 and isinstance(d, dict) and d.get("symbol"):
            burst_ok += 1
    if burst_ok >= 5:
        record_pass("Rapid Concurrency Burst", f"{burst_ok}/{len(burst_symbols)} parallel requests succeeded simultaneously")
    else:
        record_fail("Rapid Concurrency Burst", f"Only {burst_ok}/{len(burst_symbols)} succeeded")

# -------------------------------------------------------------
# 4. END-TO-END REAL PRACTICE TRADE EXECUTION (BUY + SELL)
# -------------------------------------------------------------
print("\n--- 4. Executing Real End-to-End Live Trade ---")

# Step 4.1: Reset Practice Sandbox
s, reset_data = http_post("/api/practice/reset", {})
if s == 200 and isinstance(reset_data, dict) and reset_data.get("cash") == 1000.0:
    record_pass("Practice Sandbox Reset", f"Cash reset to ${reset_data['cash']:.2f}")
else:
    record_fail("Practice Sandbox Reset", f"s={s}, data={reset_data}")

# Step 4.2: Boundary rejection tests on orders
# A. Empty symbol order
s, empty_res = http_post("/api/practice/buy", {"symbol": "", "allocation": 100.0})
if s == 400 or (isinstance(empty_res, dict) and not empty_res.get("success")):
    record_pass("Blank Symbol Order Blocked", "Rejected cleanly")
else:
    record_fail("Blank Symbol Order Blocked", f"Accepted blank order: s={s}")

# B. Selling unowned asset
s, unowned_sell = http_post("/api/practice/sell", {"symbol": "NONEXISTENT_XYZ", "price": 100.0})
if s == 400 or (isinstance(unowned_sell, dict) and not unowned_sell.get("success")):
    record_pass("Unowned Asset Sell Blocked", "Rejected cleanly")
else:
    record_fail("Unowned Asset Sell Blocked", f"Allowed phantom sell: s={s}")

# Step 4.3: Real Live BUY Trade: US Stock (NVDA)
# Fetch live quote for NVDA
_, nvda_res = http_get("/api/analyze?ticker=NVDA&timeframe=15m")
live_nvda_price = nvda_res.get("current_price", 230.0) if isinstance(nvda_res, dict) else 230.0
nvda_alloc = 250.0 # Deploy $250
nvda_sl = round(live_nvda_price * 0.95, 2)
nvda_tp = round(live_nvda_price * 1.05, 2)

s, nvda_buy_res = http_post("/api/practice/buy", {
    "symbol": "NVDA",
    "price": live_nvda_price,
    "allocation": nvda_alloc,
    "stop_loss": nvda_sl,
    "take_profit_1": nvda_tp
})

if s == 200 and nvda_buy_res.get("success"):
    sh = nvda_buy_res.get("shares")
    pr = nvda_buy_res.get("price")
    inv = nvda_buy_res.get("invested", 0.0)
    record_pass("Execute Live BUY Trade (NVDA)", f"Bought {sh} shares @ ${pr} (Invested: ${inv:.2f}, SL=${nvda_sl}, TP=${nvda_tp})")
else:
    record_fail("Execute Live BUY Trade (NVDA)", f"s={s}, res={nvda_buy_res}")

# Step 4.4: Real Live BUY Trade: Indian Stock (RELIANCE.NS) with Auto-FX
_, rel_res = http_get("/api/analyze?ticker=RELIANCE.NS&timeframe=15m")
live_rel_price = rel_res.get("current_price", 1180.0) if isinstance(rel_res, dict) else 1180.0
rel_alloc = 250.0 # Deploy $250 USD
rel_sl = round(live_rel_price * 0.95, 2)
rel_tp = round(live_rel_price * 1.05, 2)

s, rel_buy_res = http_post("/api/practice/buy", {
    "symbol": "RELIANCE.NS",
    "price": live_rel_price,
    "allocation": rel_alloc,
    "stop_loss": rel_sl,
    "take_profit_1": rel_tp,
    "currency": "INR"
})

if s == 200 and rel_buy_res.get("success"):
    sh_rel = rel_buy_res.get("shares")
    pr_rel = rel_buy_res.get("price")
    fx_rel = rel_buy_res.get("fx_rate")
    inv_rel = rel_buy_res.get("invested", 0.0)
    record_pass("Execute Live BUY Trade (RELIANCE.NS INR)", f"Bought {sh_rel} shares @ ₹{pr_rel} (FX rate={fx_rel}, Invested: ${inv_rel:.2f} USD)")
else:
    record_fail("Execute Live BUY Trade (RELIANCE.NS INR)", f"s={s}, res={rel_buy_res}")

# Step 4.5: Verify Portfolio State After Buys
s, port_state = http_get("/api/practice")
positions = port_state.get("positions", [])
if isinstance(positions, dict):
    pos_symbols = list(positions.keys())
    open_count = len(positions)
else:
    pos_symbols = [p.get("symbol") for p in positions]
    open_count = len(positions)

cash_after_buys = port_state.get("cash", 0.0)
if open_count == 2 and "NVDA" in pos_symbols and "RELIANCE.NS" in pos_symbols and cash_after_buys <= 510.0:
    record_pass("Holdings & Cash Verification", f"2 Active Positions: {pos_symbols}, Cash Available: ${cash_after_buys:.2f}")
else:
    record_fail("Holdings & Cash Verification", f"Count={open_count}, Symbols={pos_symbols}, Cash=${cash_after_buys}")

# Step 4.6: Real Live SELL / EXIT Trade: NVDA (Liquidate with Profit)
# Simulate winning exit at +3% above entry price
nvda_exit_price = round(live_nvda_price * 1.03, 2)
s, sell_res = http_post("/api/practice/sell", {
    "symbol": "NVDA",
    "price": nvda_exit_price,
    "reason": "TARGET_PROFIT_TEST"
})

if s == 200 and sell_res.get("success"):
    realized_dollar = sell_res.get("pnl", 0.0)
    realized_pct = sell_res.get("pnl_pct", 0.0)
    outcome = sell_res.get("result", "WIN")
    record_pass("Execute Live SELL / EXIT Trade (NVDA)", f"Sold NVDA @ ${nvda_exit_price:.2f} -> Outcome={outcome}, Realized P&L=+${realized_dollar:.2f} (+{realized_pct:.2f}%)")
else:
    record_fail("Execute Live SELL / EXIT Trade (NVDA)", f"s={s}, res={sell_res}")

# Step 4.7: Verify Closed Trade Statistics & Cash Return
s, port_after_sell = http_get("/api/practice")
history = port_after_sell.get("trade_history", [])
total_trades = port_after_sell.get("total_trades", len(history))
realized_pnl = port_after_sell.get("realized_pnl", 0.0)
win_rate = port_after_sell.get("win_rate_pct", 0.0)
cash_final = port_after_sell.get("cash", 0.0)

if total_trades >= 1 and realized_pnl > 0 and win_rate == 100.0 and cash_final > cash_after_buys:
    record_pass("Trade Lifecycle Recorded & Verified", f"Closed Trades={total_trades}, Win Rate={win_rate}%, Realized P&L=+${realized_pnl:.2f}, Cash Restored to ${cash_final:.2f}")
else:
    record_fail("Trade Lifecycle Recorded & Verified", f"Trades={total_trades}, PnL={realized_pnl}, WinRate={win_rate}%, Cash=${cash_final}")

# -------------------------------------------------------------
# 5. AI COPILOT, MARKET OVERVIEW & SIGNALS FEED
# -------------------------------------------------------------
print("\n--- 5. Testing AlphaQuant AI Copilot & Signals Feed ---")

# Chat Query
s, chat_res = http_post("/api/chat", {
    "message": "Give me a quick tactical assessment of Gold (XAU/USD) and NVDA based on current indicators."
}, timeout=25.0)

if s == 200 and chat_res.get("reply"):
    snippet = chat_res["reply"][:95].replace("\n", " ") + "..."
    record_pass("AlphaQuant AI Chatbot", f"'{snippet}'")
else:
    record_fail("AlphaQuant AI Chatbot", f"s={s}, res={chat_res}")

# Signals feed
s, sigs = http_get("/api/signals")
if s == 200 and isinstance(sigs, list):
    record_pass("24/7 Signals Stream Active", f"{len(sigs)} recent signals logged in feed")
else:
    record_fail("24/7 Signals Stream Active", f"s={s}, sigs={sigs}")

# AI Portfolio Fund
s, ai_port = http_get("/api/portfolio")
if s == 200 and isinstance(ai_port, dict) and "total_equity" in ai_port:
    record_pass("AI Autonomous Fund", f"Equity=${ai_port['total_equity']:.2f}, Realized P&L=${ai_port.get('realized_pnl', 0.0):.2f}, Win Rate={ai_port.get('win_rate_pct', 0.0)}%")
else:
    record_fail("AI Autonomous Fund", f"s={s}, data={ai_port}")

# US Market Overview
s, us_ov = http_get("/api/market-overview?market=US")
if s == 200 and isinstance(us_ov, dict) and "indices" in us_ov:
    record_pass("US Market Regime Overview", f"Regime: {us_ov.get('regime')}, VIX: {us_ov.get('vix_score')}")
else:
    record_fail("US Market Regime Overview", f"s={s}, data={us_ov}")

# Indian Market Overview
s, in_ov = http_get("/api/market-overview?market=IN")
if s == 200 and isinstance(in_ov, dict) and "indices" in in_ov:
    record_pass("Indian Market Regime Overview", f"Regime: {in_ov.get('regime')}")
else:
    record_fail("Indian Market Regime Overview", f"s={s}, data={in_ov}")

# -------------------------------------------------------------
# FINAL SCORECARD
# -------------------------------------------------------------
print("\n" + "=" * 70)
print("📊 FINAL AUDIT SCORECARD & BENCHMARK RESULTS")
print("=" * 70)
print(f"Total Checks Executed : {len(passes) + len(failures)}")
print(f"Passed Checks         : {len(passes)}  ✅")
print(f"Failed Checks         : {len(failures)}  {'❌' if failures else '✨'}")

if failures:
    print("\nFailure Details:")
    for name, det in failures:
        print(f"  • {name}: {det}")
    sys.exit(1)
else:
    print("\n🎉 100% PERFECT SCORE! All components, UI controls, quant engines, edge cases, and end-to-end live trades PASSED!")
    sys.exit(0)
