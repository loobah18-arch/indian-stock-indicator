#!/usr/bin/env python3
import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta
import threading
import urllib.parse

IST = timezone(timedelta(hours=5, minutes=30))
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from typing import Dict, Any, Optional, List

from market_client import MarketClient
from strategy import IndicatorStrategy
from notifier import Notifier, get_alert_history
from ai_assistant import AIAssistant
from paper_trading import PaperPortfolio, PracticePortfolio, get_usd_inr_rate

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

PORT = 5000
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
SIGNALS_FEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signals_feed.json")

def load_config() -> Dict[str, Any]:
    default_cfg = {
        "discord_webhook_url": "",
        "enable_termux_notification": True,
        "auto_monitor_enabled": True,
        "ai_auto_trading_enabled": True,
        "min_upside_for_buy_pct": 5.0,
        "rsi_overbought": 72.0,
        "rsi_oversold": 30.0,
        "watchlist_india": [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
            "BHARTIARTL.NS", "SBIN.NS", "LT.NS", "ITC.NS", "AXISBANK.NS",
            "SUNPHARMA.NS", "MARUTI.NS"
        ],
        "watchlist_us": [
            "NVDA", "AAPL", "MSFT", "TSLA", "AMZN",
            "GOOGL", "META", "AMD", "SPY", "QQQ"
        ]
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_cfg.update(saved)
        except Exception:
            pass
    return default_cfg

def save_config(cfg: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

client = MarketClient()
config = load_config()
strategy = IndicatorStrategy(
    min_upside_pct=config.get("min_upside_for_buy_pct", 5.0),
    rsi_overbought=config.get("rsi_overbought", 72.0),
    rsi_oversold=config.get("rsi_oversold", 30.0),
)
ai_assistant = AIAssistant()
portfolio = PaperPortfolio()
practice_portfolio = PracticePortfolio()

signals_feed: List[Dict[str, Any]] = []

def load_signals_feed() -> List[Dict[str, Any]]:
    global signals_feed
    if os.path.exists(SIGNALS_FEED_FILE):
        try:
            with open(SIGNALS_FEED_FILE, "r", encoding="utf-8") as f:
                signals_feed = json.load(f)
        except Exception:
            signals_feed = []
    return signals_feed

def save_signals_feed():
    try:
        with open(SIGNALS_FEED_FILE, "w", encoding="utf-8") as f:
            json.dump(signals_feed[-50:], f, indent=2)
    except Exception:
        pass

load_signals_feed()

cached_results: Dict[str, Any] = {}
auto_monitor_enabled = config.get("auto_monitor_enabled", True)
ai_auto_trading_enabled = config.get("ai_auto_trading_enabled", True)
ai_trade_symbols = config.get("ai_trade_symbols", [
    "NVDA", "AAPL", "MSFT", "TSLA", "RELIANCE.NS", "TCS.NS", "ICICIBANK.NS", "BTC/USD", "XAU/USD"
])
alerted_triggers = set()

def background_market_monitor_loop():
    """Background daemon that periodically scans watchlists, checks portfolio stop losses, executes autonomous trades, and dispatches alerts."""
    while True:
        try:
            if auto_monitor_enabled:
                notifier = Notifier(discord_webhook_url=config.get("discord_webhook_url"))
                all_syms = list(dict.fromkeys(config.get("watchlist_us", []) + config.get("watchlist_india", []) + ai_trade_symbols + ["XAU/USD", "BTC/USD", "ETH/USD"]))

                with ThreadPoolExecutor(max_workers=8) as executor:
                    future_to_sym = {executor.submit(client.get_full_analysis, client.resolve_symbol(s)): s for s in all_syms}
                    for future in as_completed(future_to_sym):
                        try:
                            raw = future.result()
                            if raw and raw.get("analyst"):
                                res = strategy.analyze(raw)
                                cached_results[res["symbol"]] = res
                                triggers = res.get("triggers", {})
                                buy_t = triggers.get("buy", {})
                                sell_t = triggers.get("sell", {})

                                now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
                                if buy_t.get("triggered"):
                                    key = (res["symbol"], "BUY")
                                    sig_item = {
                                        "id": f"sig_{res['symbol']}_{int(time.time())}",
                                        "symbol": res["symbol"],
                                        "name": res.get("name", res["symbol"]),
                                        "action": "BUY",
                                        "signal": res.get("signal", "BUY"),
                                        "price": res.get("current_price", 0.0),
                                        "score": res.get("score", 70),
                                        "conviction": res.get("conviction", "High"),
                                        "timestamp": now_str,
                                        "entry_zone": res.get("execution", {}).get("entry_zone", f"${res.get('current_price', 0.0):.2f}"),
                                        "stop_loss": res.get("execution", {}).get("stop_loss", 0.0),
                                        "take_profit_1": res.get("execution", {}).get("take_profit_1", 0.0),
                                        "take_profit_2": res.get("execution", {}).get("take_profit_2", 0.0),
                                        "risk_reward": res.get("execution", {}).get("risk_reward_tp1", 1.5),
                                        "instruction": buy_t.get("instruction") or f"Recommended BUY: Enter between {res.get('execution', {}).get('entry_zone')}. SL: {res.get('execution', {}).get('stop_loss')}. TP1: {res.get('execution', {}).get('take_profit_1')}.",
                                        "currency": res.get("currency", "USD"),
                                        "time_epoch": time.time()
                                    }
                                    if not any(s["symbol"] == res["symbol"] and s["action"] == "BUY" and (time.time() - float(s.get("time_epoch", 0))) < 300 for s in signals_feed):
                                        signals_feed.append(sig_item)
                                        save_signals_feed()

                                    if key not in alerted_triggers:
                                        notifier.send_trade_alert(res, "BUY")
                                        alerted_triggers.add(key)
                                else:
                                    alerted_triggers.discard((res["symbol"], "BUY"))

                                if sell_t.get("triggered"):
                                    key = (res["symbol"], sell_t.get("type", "SELL"))
                                    sig_item = {
                                        "id": f"sig_{res['symbol']}_{int(time.time())}",
                                        "symbol": res["symbol"],
                                        "name": res.get("name", res["symbol"]),
                                        "action": "SELL",
                                        "signal": sell_t.get("type", "SELL"),
                                        "price": res.get("current_price", 0.0),
                                        "score": res.get("score", 40),
                                        "conviction": res.get("conviction", "Defensive"),
                                        "timestamp": now_str,
                                        "instruction": sell_t.get("instruction") or f"Recommended SELL/TRIM: {sell_t.get('type')} at {res.get('current_price', 0.0)}.",
                                        "currency": res.get("currency", "USD"),
                                        "time_epoch": time.time()
                                    }
                                    if not any(s["symbol"] == res["symbol"] and s["action"] == "SELL" and (time.time() - float(s.get("time_epoch", 0))) < 300 for s in signals_feed):
                                        signals_feed.append(sig_item)
                                        save_signals_feed()

                                    if key not in alerted_triggers:
                                        notifier.send_trade_alert(res, "SELL")
                                        alerted_triggers.add(key)
                                else:
                                    for st in ["TAKE_PROFIT_1", "TAKE_PROFIT_2", "STOP_LOSS_HIT", "OVERBOUGHT_TRIM", "BEARISH_BREAKDOWN"]:
                                        alerted_triggers.discard((res["symbol"], st))
                        except Exception:
                            pass

                # Live prices map for evaluation
                live_prices = {sym: r.get("current_price", 0.0) for sym, r in cached_results.items() if r.get("current_price")}

                # Autonomous AI Trading: deploy virtual credits into top confluence setups & execute TP/SL exits
                if ai_auto_trading_enabled and cached_results:
                    try:
                        if ai_trade_symbols and "ALL" not in ai_trade_symbols:
                            eligible_stocks = [
                                r for sym, r in cached_results.items()
                                if sym in ai_trade_symbols or sym.replace('/', '') in ai_trade_symbols or any(s == sym for s in ai_trade_symbols)
                            ]
                        else:
                            eligible_stocks = list(cached_results.values())
                        trade_res = portfolio.process_autonomous_signals(eligible_stocks, max_positions=4)
                        now_ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
                        for b in trade_res.get("buys_executed", []):
                            print(f"[{now_ts}] [AI AUTONOMOUS TRADER] BUY: {b['symbol']} | ${b['invested']} invested ({b['shares']} shares @ ${b['price']}) | Score: {b.get('score')}/100 | Cash Left: ${b.get('remaining_cash')}")
                        for s in trade_res.get("sells_executed", []):
                            sign = '+' if s.get('pnl', 0) >= 0 else ''
                            print(f"[{now_ts}] [AI AUTONOMOUS TRADER] SELL: {s['symbol']} @ ${s['exit_price']} | P&L: {sign}${s.get('pnl')} ({s.get('result')}) | Reason: {s.get('exit_reason')}")
                    except Exception as e:
                        print(f"[AI AUTO TRADER ERROR] {e}")
                elif portfolio.positions and live_prices:
                    portfolio.evaluate_live_stops(live_prices)

                # Practice Sandbox: evaluate live stops for manual practice positions
                if practice_portfolio.positions and live_prices:
                    try:
                        practice_portfolio.evaluate_live_stops(live_prices)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[BACKGROUND MONITOR ERROR] {e}")
        time.sleep(60)

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Quantitative AI Market Terminal | TradingView & AI Chatbot</title>
  <style>
    :root {
      --bg: #0b0e14;
      --surface: #131722;
      --surface-elevated: #1a202c;
      --border: #242b3d;
      --border-accent: #2e384f;
      --text: #e2e8f0;
      --text-muted: #8492a6;
      --green: #10b981;
      --green-bg: rgba(16, 185, 129, 0.12);
      --red: #ef4444;
      --red-bg: rgba(239, 68, 68, 0.12);
      --yellow: #f59e0b;
      --yellow-bg: rgba(245, 158, 11, 0.12);
      --blue: #3b82f6;
      --blue-bg: rgba(59, 130, 246, 0.12);
      --font-mono: 'Geist Mono', 'SF Mono', Consolas, monospace;
      --font-sans: 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      line-height: 1.5;
      padding: 12px;
      -webkit-font-smoothing: antialiased;
    }

    .container {
      max-width: 1400px;
      margin: 0 auto;
    }

    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 16px;
      flex-wrap: wrap;
      gap: 12px;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .badge-market {
      font-family: var(--font-mono);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      background: #1e293b;
      color: #94a3b8;
      padding: 4px 8px;
      border-radius: 4px;
      border: 1px solid #334155;
    }

    h1 {
      font-size: 18px;
      font-weight: 600;
      letter-spacing: -0.02em;
    }

    .header-actions {
      display: flex;
      gap: 8px;
      align-items: center;
    }

    /* Market Selector Tabs */
    .market-tabs {
      display: flex;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 3px;
      margin-bottom: 14px;
      gap: 4px;
    }

    .market-tab {
      flex: 1;
      text-align: center;
      padding: 8px 12px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      border-radius: 4px;
      color: var(--text-muted);
      transition: all 0.15s ease;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      user-select: none;
    }

    .market-tab.active {
      background: var(--surface-elevated);
      color: #ffffff;
      border: 1px solid var(--border-accent);
    }

    button {
      background: var(--surface-elevated);
      color: var(--text);
      border: 1px solid var(--border);
      padding: 7px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
      font-family: var(--font-sans);
    }

    button:hover {
      background: #252b3b;
      border-color: var(--border-accent);
    }

    button.primary {
      background: var(--blue);
      border-color: var(--blue);
      color: #ffffff;
    }
    button.primary:hover {
      background: #2563eb;
    }

    /* Macro Market Regime Section */
    .macro-section {
      margin-bottom: 16px;
    }
    .macro-banner {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px 16px;
    }
    .macro-regime-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
      flex-wrap: wrap;
      gap: 8px;
    }
    .macro-regime-badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.03em;
    }
    .macro-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--yellow);
      display: inline-block;
      box-shadow: 0 0 8px currentColor;
    }
    .macro-meta-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .macro-guidance {
      font-size: 12px;
      color: #94a3b8;
      line-height: 1.5;
      margin-bottom: 12px;
      padding-bottom: 10px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .macro-indices {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 8px;
    }
    .macro-idx-chip {
      background: var(--surface-elevated);
      border: 1px solid var(--border);
      padding: 8px 10px;
      border-radius: 6px;
    }
    .macro-idx-name {
      font-size: 10px;
      color: var(--text-muted);
      text-transform: uppercase;
      margin-bottom: 2px;
      display: flex;
      justify-content: space-between;
    }
    .macro-idx-val {
      font-family: var(--font-mono);
      font-size: 13px;
      font-weight: 600;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    /* Actionable Buy / Sell Trigger Cards */
    .triggers-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 16px;
    }
    @media (max-width: 768px) {
      .triggers-grid { grid-template-columns: 1fr; }
    }
    .trigger-card {
      background: #0d111b;
      border-radius: 8px;
      padding: 12px 14px;
      border: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .trigger-card.buy-card {
      border-left: 4px solid var(--green);
      background: linear-gradient(180deg, rgba(16,185,129,0.05) 0%, rgba(13,17,27,1) 100%);
    }
    .trigger-card.sell-card {
      border-left: 4px solid var(--red);
      background: linear-gradient(180deg, rgba(239,68,68,0.05) 0%, rgba(13,17,27,1) 100%);
    }
    .trigger-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    .trigger-badge {
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .trigger-badge.buy { color: var(--green); }
    .trigger-badge.sell { color: var(--red); }
    .trigger-status {
      font-family: var(--font-mono);
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 4px;
      background: rgba(255,255,255,0.08);
      font-weight: 600;
    }
    .trigger-content {
      font-size: 12px;
      line-height: 1.5;
      color: #e2e8f0;
      margin-bottom: 10px;
    }
    .trigger-meta {
      font-size: 11px;
      font-family: var(--font-mono);
      color: var(--text-muted);
      display: flex;
      justify-content: space-between;
      margin-bottom: 10px;
      padding-top: 6px;
      border-top: 1px solid rgba(255,255,255,0.05);
    }
    .trigger-action-btn {
      width: 100%;
      padding: 7px;
      font-size: 11px;
      font-weight: 600;
      border-radius: 4px;
      cursor: pointer;
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 6px;
      border: 1px solid transparent;
      font-family: var(--font-sans);
    }
    .trigger-action-btn.buy-btn {
      background: rgba(16,185,129,0.15);
      color: var(--green);
      border-color: rgba(16,185,129,0.3);
    }
    .trigger-action-btn.buy-btn:hover {
      background: rgba(16,185,129,0.25);
    }
    .trigger-action-btn.sell-btn {
      background: rgba(239,68,68,0.15);
      color: var(--red);
      border-color: rgba(239,68,68,0.3);
    }
    .trigger-action-btn.sell-btn:hover {
      background: rgba(239,68,68,0.25);
    }

    /* Virtual $1,000 Portfolio & Report Modal */
    .portfolio-stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin-top: 10px;
      margin-bottom: 14px;
    }
    .portfolio-stat-box {
      background: var(--surface-elevated);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px 14px;
    }
    .stat-big-val {
      font-family: var(--font-mono);
      font-size: 19px;
      font-weight: 700;
      margin: 4px 0 2px 0;
    }
    .stat-sub-val {
      font-size: 11px;
      color: var(--text-muted);
    }
    .modal-overlay {
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(4px);
      z-index: 1002;
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 16px;
    }
    .modal-box {
      background: #10141f;
      border: 1px solid #2d3748;
      border-radius: 10px;
      width: 820px;
      max-width: 100%;
      max-height: 88vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 16px 40px rgba(0,0,0,0.8);
    }
    .modal-header {
      background: #161b2a;
      padding: 14px 18px;
      border-bottom: 1px solid #242c3f;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .modal-body {
      padding: 20px;
      overflow-y: auto;
      font-size: 13px;
      line-height: 1.6;
      color: #e2e8f0;
    }
    .modal-body h3 {
      margin: 16px 0 8px 0;
      color: #60a5fa;
      font-size: 14px;
      border-bottom: 1px solid #1e293b;
      padding-bottom: 4px;
    }
    .modal-body ul {
      margin-left: 18px;
      margin-bottom: 12px;
    }
    .modal-body li {
      margin-bottom: 4px;
    }
    .modal-body strong {
      color: #f8fafc;
    }

    /* AI Autonomous Trader Tab Styling */
    .ai-live-banner {
      background: linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(59, 130, 246, 0.06) 100%);
      border: 1px solid rgba(16, 185, 129, 0.25);
      border-radius: 8px;
      padding: 14px 18px;
      margin-bottom: 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
    }
    .ai-live-status {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .pulsing-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 10px var(--green);
      animation: pulseDot 2s infinite ease-in-out;
    }
    @keyframes pulseDot {
      0%, 100% { transform: scale(1); opacity: 1; }
      50% { transform: scale(1.35); opacity: 0.55; }
    }
    .action-chip {
      display: inline-block;
      padding: 2px 7px;
      border-radius: 4px;
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      font-family: var(--font-mono);
    }
    .action-chip.buy { background: rgba(16, 185, 129, 0.18); color: var(--green); border: 1px solid rgba(16, 185, 129, 0.35); }
    .action-chip.sell { background: rgba(239, 68, 68, 0.18); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.35); }
    .accuracy-matrix {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .accuracy-card {
      background: #141926;
      border: 1px solid #242f44;
      border-radius: 6px;
      padding: 12px 14px;
    }

    /* Alerts Drawer */
    .alerts-drawer {
      position: fixed;
      top: 60px;
      right: 20px;
      width: 360px;
      max-width: calc(100vw - 32px);
      max-height: 500px;
      background: #111522;
      border: 1px solid #2d3748;
      border-radius: 8px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.7);
      z-index: 1000;
      display: none;
      flex-direction: column;
      overflow: hidden;
    }
    .alerts-header {
      background: #181e2f;
      padding: 10px 14px;
      border-bottom: 1px solid #242c3f;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .alerts-list {
      flex: 1;
      overflow-y: auto;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .alert-card-item {
      background: #181d2a;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 8px 10px;
      font-size: 11px;
    }
    .alert-card-item.buy { border-left: 3px solid var(--green); }
    .alert-card-item.sell { border-left: 3px solid var(--red); }
    .alert-item-top {
      display: flex;
      justify-content: space-between;
      font-weight: 700;
      margin-bottom: 3px;
    }
    .alert-item-time {
      font-family: var(--font-mono);
      font-size: 10px;
      color: var(--text-muted);
    }

    /* AI Trading Universe Chips */
    .universe-chip {
      background: var(--surface-elevated);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 6px 10px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: space-between;
      transition: all 0.15s ease;
      user-select: none;
    }
    .universe-chip:hover {
      border-color: #3b82f6;
      background: rgba(59, 130, 246, 0.1);
    }
    .universe-chip.selected {
      background: rgba(16, 185, 129, 0.12);
      border-color: #10b981;
      box-shadow: 0 0 10px rgba(16, 185, 129, 0.15);
    }
    .universe-chip .chip-symbol {
      font-weight: 800;
      font-size: 12px;
      color: #fff;
      font-family: var(--font-mono);
    }
    .universe-chip.selected .chip-symbol {
      color: #10b981;
    }
    .universe-chip .chip-check {
      font-size: 11px;
      color: var(--text-muted);
    }
    .universe-chip.selected .chip-check {
      color: #10b981;
      font-weight: 800;
    }

    /* Chat Action Card */
    .chat-action-card {
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid #10b981;
      border-radius: 6px;
      padding: 8px 12px;
      margin-top: 8px;
      font-size: 12px;
      color: #e2e8f0;
      box-shadow: 0 2px 8px rgba(16, 185, 129, 0.15);
    }
    .chat-action-card .action-header {
      display: flex;
      align-items: center;
      gap: 6px;
      font-weight: 800;
      color: #10b981;
      margin-bottom: 4px;
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 0.05em;
    }

    /* Search Box & Quick Pills */
    .search-section {
      margin-bottom: 16px;
    }

    .search-box {
      display: flex;
      gap: 8px;
      margin-bottom: 8px;
    }

    .search-box input {
      flex: 1;
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 9px 12px;
      border-radius: 6px;
      font-size: 14px;
      font-family: var(--font-mono);
      outline: none;
    }
    .search-box input:focus {
      border-color: var(--blue);
    }

    .quick-pills {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      padding-bottom: 4px;
      -webkit-overflow-scrolling: touch;
    }

    .pill-btn {
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text-muted);
      font-family: var(--font-mono);
      font-size: 11px;
      padding: 4px 10px;
      border-radius: 4px;
      cursor: pointer;
      white-space: nowrap;
    }
    .pill-btn:hover, .pill-btn.active {
      color: #fff;
      border-color: var(--blue);
      background: var(--blue-bg);
    }

    /* TradingView Container */
    .chart-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 16px;
    }

    .tradingview-container {
      width: 100%;
      height: 480px;
      border-radius: 6px;
      overflow: hidden;
      border: 1px solid var(--border);
      background: #131722;
    }

    @media (max-width: 768px) {
      .tradingview-container { height: 380px; }
    }

    iframe#tradingview_iframe {
      width: 100%;
      height: 100%;
      border: 0;
      display: block;
    }

    /* Layout */
    .main-grid {
      display: grid;
      grid-template-columns: 1fr 340px;
      gap: 16px;
      margin-bottom: 20px;
    }

    @media (max-width: 1024px) {
      .main-grid { grid-template-columns: 1fr; }
    }

    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }

    .card-title {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text-muted);
      margin-bottom: 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    /* Hero Ticker & Signal Banner */
    .hero-ticker {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 14px;
      flex-wrap: wrap;
      gap: 10px;
    }

    .ticker-symbol {
      font-size: 24px;
      font-weight: 700;
      letter-spacing: -0.02em;
    }

    .ticker-name {
      font-size: 12px;
      color: var(--text-muted);
    }

    .price-box {
      text-align: right;
    }

    .price-val {
      font-size: 24px;
      font-weight: 700;
      font-family: var(--font-mono);
    }

    .price-change {
      font-size: 12px;
      font-family: var(--font-mono);
    }

    .signal-banner {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 16px;
      border-radius: 6px;
      margin-bottom: 16px;
      border: 1px solid transparent;
    }

    .signal-banner.strong-buy, .signal-banner.buy {
      background: var(--green-bg);
      border-color: rgba(16, 185, 129, 0.3);
      color: var(--green);
    }
    .signal-banner.sell, .signal-banner.strong-sell {
      background: var(--red-bg);
      border-color: rgba(239, 68, 68, 0.3);
      color: var(--red);
    }
    .signal-banner.hold {
      background: var(--yellow-bg);
      border-color: rgba(245, 158, 11, 0.3);
      color: var(--yellow);
    }

    .signal-badge {
      font-size: 16px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }
    .action-badge {
      font-family: var(--font-mono);
      font-size: 11px;
      text-transform: uppercase;
      padding: 3px 7px;
      border-radius: 4px;
      background: rgba(0,0,0,0.25);
    }

    /* Pillars */
    .pillars-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: 8px;
      margin-bottom: 16px;
    }

    .pillar-box {
      background: var(--surface-elevated);
      padding: 10px;
      border-radius: 6px;
      border: 1px solid var(--border);
    }

    .pillar-label {
      font-size: 10px;
      color: var(--text-muted);
      margin-bottom: 3px;
    }

    .pillar-val {
      font-size: 15px;
      font-weight: 600;
      font-family: var(--font-mono);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .pillar-bar {
      height: 4px;
      background: #283042;
      border-radius: 2px;
      margin-top: 5px;
      overflow: hidden;
    }

    .pillar-fill {
      height: 100%;
      background: var(--blue);
      border-radius: 2px;
      transition: width 0.3s ease;
    }

    /* Execution Plan */
    .execution-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 10px;
      background: #0d1017;
      padding: 12px;
      border-radius: 6px;
      border: 1px solid var(--border);
      margin-bottom: 14px;
    }

    .exec-item .exec-label {
      font-size: 10px;
      color: var(--text-muted);
      margin-bottom: 2px;
    }

    .exec-item .exec-val {
      font-family: var(--font-mono);
      font-size: 14px;
      font-weight: 600;
    }

    .positive { color: var(--green); }
    .negative { color: var(--red); }

    /* Gauge */
    .gauge-circle {
      width: 130px;
      height: 130px;
      border-radius: 50%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      border: 7px solid var(--border);
      margin: 14px auto;
      transition: border-color 0.3s ease;
    }

    .gauge-score {
      font-size: 36px;
      font-weight: 800;
      font-family: var(--font-mono);
      line-height: 1;
    }

    .gauge-max {
      font-size: 11px;
      color: var(--text-muted);
      font-family: var(--font-mono);
    }

    .gauge-verdict {
      text-align: center;
      font-size: 14px;
      font-weight: 700;
      margin-top: 4px;
    }

    /* Watchlist Table */
    .table-container {
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }

    th {
      text-align: left;
      padding: 8px 10px;
      color: var(--text-muted);
      font-weight: 500;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border-bottom: 1px solid var(--border);
    }

    td {
      padding: 10px;
      border-bottom: 1px solid #1a202c;
      font-family: var(--font-mono);
      white-space: nowrap;
    }

    tr:hover td {
      background: rgba(255,255,255,0.03);
      cursor: pointer;
    }

    .status-pill {
      display: inline-block;
      padding: 2px 7px;
      border-radius: 4px;
      font-size: 10px;
      font-weight: 600;
    }
    .status-pill.strong-buy, .status-pill.buy { background: var(--green-bg); color: var(--green); }
    .status-pill.hold { background: var(--yellow-bg); color: var(--yellow); }
    .status-pill.sell, .status-pill.strong-sell { background: var(--red-bg); color: var(--red); }

    /* =======================================
       AI CHATBOT FLOATING DRAWER & WIDGET
       ======================================= */
    .ai-chat-btn {
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: #2563eb;
      color: #fff;
      border: 1px solid #3b82f6;
      border-radius: 30px;
      padding: 10px 18px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      box-shadow: 0 4px 18px rgba(37, 99, 235, 0.4);
      z-index: 998;
      transition: transform 0.2s, background 0.2s;
    }
    .ai-chat-btn:hover {
      background: #1d4ed8;
      transform: translateY(-2px);
    }

    .ai-chat-drawer {
      position: fixed;
      bottom: 74px;
      right: 20px;
      width: 410px;
      max-width: calc(100vw - 32px);
      height: 560px;
      max-height: calc(100vh - 100px);
      background: #10141f;
      border: 1px solid #2d3748;
      border-radius: 12px;
      display: flex;
      flex-direction: column;
      box-shadow: 0 10px 30px rgba(0,0,0,0.6);
      z-index: 999;
      display: none;
      overflow: hidden;
    }

    .ai-chat-header {
      background: #161b2a;
      padding: 12px 16px;
      border-bottom: 1px solid #242c3f;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .ai-chat-title {
      font-size: 13px;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .ai-model-badge {
      font-size: 10px;
      color: #10b981;
      font-family: var(--font-mono);
      background: rgba(16, 185, 129, 0.1);
      padding: 2px 6px;
      border-radius: 4px;
      border: 1px solid rgba(16, 185, 129, 0.2);
    }

    .ai-context-chip {
      background: #1a2234;
      padding: 6px 14px;
      font-size: 11px;
      color: #94a3b8;
      border-bottom: 1px solid #242c3f;
      display: flex;
      align-items: center;
      gap: 6px;
      font-family: var(--font-mono);
    }

    .ai-quick-prompts {
      display: flex;
      gap: 6px;
      padding: 8px 12px;
      overflow-x: auto;
      border-bottom: 1px solid #1e2638;
      background: #121724;
      -webkit-overflow-scrolling: touch;
    }

    .quick-chip {
      font-size: 11px;
      background: #1c2333;
      border: 1px solid #2d3748;
      color: #cbd5e1;
      padding: 4px 10px;
      border-radius: 12px;
      cursor: pointer;
      white-space: nowrap;
    }
    .quick-chip:hover {
      background: #2b354c;
      color: #fff;
    }

    .ai-chat-messages {
      flex: 1;
      padding: 14px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
      font-size: 13px;
      line-height: 1.5;
    }

    .chat-bubble {
      max-width: 88%;
      padding: 10px 14px;
      border-radius: 10px;
      word-break: break-word;
    }

    .chat-bubble.user {
      align-self: flex-end;
      background: #2563eb;
      color: #fff;
      border-bottom-right-radius: 2px;
    }

    .chat-bubble.assistant {
      align-self: flex-start;
      background: #1a2233;
      border: 1px solid #2a354c;
      color: #e2e8f0;
      border-bottom-left-radius: 2px;
    }

    .chat-bubble.assistant p {
      margin-bottom: 6px;
    }
    .chat-bubble.assistant p:last-child {
      margin-bottom: 0;
    }

    .ai-chat-footer {
      padding: 10px 12px;
      background: #131826;
      border-top: 1px solid #242c3f;
      display: flex;
      gap: 8px;
    }

    .ai-chat-footer input {
      flex: 1;
      background: #1a202c;
      border: 1px solid #2d3748;
      color: #fff;
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 13px;
      outline: none;
    }
    .ai-chat-footer input:focus {
      border-color: var(--blue);
    }

    .toast {
      position: fixed;
      bottom: 20px;
      left: 20px;
      background: #1e293b;
      color: #fff;
      padding: 10px 16px;
      border-radius: 6px;
      border: 1px solid #334155;
      font-size: 12px;
      display: none;
      z-index: 1001;
      box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    }

    /* ============================================== */
    /* BINOMO STYLE PRACTICE TRADING DESK STYLES       */
    /* ============================================== */
    .binomo-top-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 14px;
      margin-bottom: 12px;
    }
    .binomo-assets-scroll {
      display: flex;
      align-items: center;
      gap: 6px;
      overflow-x: auto;
      max-width: 100%;
      padding-bottom: 2px;
    }
    .binomo-asset-chip {
      background: var(--surface-elevated);
      border: 1px solid var(--border);
      color: #cbd5e1;
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 11px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
      transition: all 0.15s;
    }
    .binomo-asset-chip:hover, .binomo-asset-chip.active {
      border-color: #60a5fa;
      background: rgba(59,130,246,0.18);
      color: #fff;
    }
    .binomo-asset-chip .chip-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      display: inline-block;
    }
    .binomo-asset-chip .chip-rate {
      font-size: 10px;
      color: #10b981;
      font-family: var(--font-mono);
      font-weight: 700;
    }
    .binomo-account-card {
      display: flex;
      align-items: center;
      gap: 12px;
      background: rgba(15,23,42,0.85);
      border: 1px solid rgba(245,158,11,0.3);
      padding: 6px 12px;
      border-radius: 6px;
    }
    .binomo-demo-badge {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 10px;
      font-weight: 800;
      color: #f59e0b;
      letter-spacing: 0.05em;
    }
    .binomo-balance-group {
      text-align: right;
    }
    .binomo-cash-val {
      font-family: var(--font-mono);
      font-weight: 800;
      font-size: 17px;
      color: #fff;
      line-height: 1.1;
    }
    .binomo-equity-sub {
      font-size: 10px;
      color: #94a3b8;
    }
    .binomo-recharge-btn {
      background: rgba(245,158,11,0.15);
      border: 1px solid rgba(245,158,11,0.4);
      color: #fbbf24;
      font-size: 11px;
      font-weight: 700;
      padding: 5px 9px;
      border-radius: 5px;
      cursor: pointer;
    }
    .binomo-recharge-btn:hover {
      background: rgba(245,158,11,0.25);
    }
    .binomo-stats-ribbon {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 14px;
      margin-bottom: 12px;
    }
    .binomo-stat-item {
      display: flex;
      flex-direction: column;
      border-right: 1px solid rgba(255,255,255,0.06);
      padding-right: 8px;
    }
    .binomo-stat-label {
      font-size: 10px;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 700;
      margin-bottom: 2px;
    }
    .binomo-stat-val {
      font-size: 16px;
      font-weight: 800;
      font-family: var(--font-mono);
      color: #fff;
    }
    .binomo-stat-sub {
      font-size: 10px;
      color: #64748b;
    }
    .binomo-terminal-grid {
      display: grid;
      grid-template-columns: 1fr 340px;
      gap: 14px;
    }
    @media (max-width: 960px) {
      .binomo-terminal-grid {
        grid-template-columns: 1fr;
      }
    }
    .binomo-chart-section {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      display: flex;
      flex-direction: column;
    }
    .binomo-chart-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }
    .binomo-tf-bar {
      display: flex;
      align-items: center;
      gap: 3px;
      background: rgba(15,23,42,0.7);
      padding: 3px 6px;
      border-radius: 6px;
      border: 1px solid var(--border);
    }
    .binomo-chart-wrapper {
      width: 100%;
      height: 480px;
      border-radius: 6px;
      overflow: hidden;
      border: 1px solid var(--border);
      background: #131722;
    }
    @media (max-width: 768px) {
      .binomo-chart-wrapper { height: 360px; }
    }
    iframe#practice_tv_iframe {
      width: 100%;
      height: 100%;
      border: 0;
      display: block;
    }
    .binomo-trade-dock {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .binomo-dock-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      padding-bottom: 10px;
    }
    .binomo-live-price {
      font-size: 20px;
      font-weight: 800;
      font-family: var(--font-mono);
      color: #fff;
    }
    .binomo-time-presets {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 4px;
    }
    .binomo-time-btn {
      background: var(--surface-elevated);
      border: 1px solid var(--border);
      color: var(--text-muted);
      font-size: 11px;
      font-weight: 700;
      padding: 6px 2px;
      border-radius: 4px;
      cursor: pointer;
      text-align: center;
    }
    .binomo-time-btn:hover, .binomo-time-btn.active {
      border-color: #3b82f6;
      background: rgba(59,130,246,0.2);
      color: #60a5fa;
    }
    .binomo-amount-stepper {
      display: flex;
      align-items: center;
      background: var(--surface-elevated);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
    }
    .stepper-btn {
      width: 42px;
      height: 40px;
      background: rgba(255,255,255,0.04);
      border: none;
      color: #cbd5e1;
      font-size: 18px;
      font-weight: 700;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .stepper-btn:hover {
      background: rgba(255,255,255,0.09);
      color: #fff;
    }
    .binomo-amount-chips {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 4px;
      margin-top: 6px;
    }
    .binomo-amount-chips button {
      background: rgba(255,255,255,0.03);
      border: 1px solid var(--border);
      color: var(--text-muted);
      font-size: 10px;
      font-weight: 600;
      padding: 4px;
      border-radius: 4px;
      cursor: pointer;
    }
    .binomo-amount-chips button:hover {
      border-color: #60a5fa;
      color: #fff;
    }
    .binomo-payout-card {
      background: linear-gradient(135deg, rgba(16,185,129,0.08) 0%, rgba(15,23,42,0.4) 100%);
      border: 1px solid rgba(16,185,129,0.25);
      border-radius: 6px;
      padding: 10px 12px;
    }
    .binomo-btn-up {
      width: 100%;
      background: linear-gradient(135deg, #10b981 0%, #059669 100%);
      color: #fff;
      border: none;
      border-radius: 8px;
      padding: 12px 16px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: space-between;
      transition: all 0.15s;
      box-shadow: 0 4px 12px rgba(16,185,129,0.3);
    }
    .binomo-btn-up:hover {
      transform: translateY(-1px);
      box-shadow: 0 6px 18px rgba(16,185,129,0.45);
    }
    .binomo-btn-down {
      width: 100%;
      background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
      color: #fff;
      border: none;
      border-radius: 8px;
      padding: 12px 16px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: space-between;
      transition: all 0.15s;
      box-shadow: 0 4px 12px rgba(239,68,68,0.3);
    }
    .binomo-btn-down:hover {
      transform: translateY(-1px);
      box-shadow: 0 6px 18px rgba(239,68,68,0.45);
    }
    .binomo-drawer {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
    }
    .binomo-drawer-tabs {
      display: flex;
      gap: 6px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      padding-bottom: 10px;
      margin-bottom: 14px;
    }
    .drawer-tab {
      background: transparent;
      border: 1px solid transparent;
      color: var(--text-muted);
      font-size: 12px;
      font-weight: 700;
      padding: 6px 12px;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.15s;
    }
    .drawer-tab:hover, .drawer-tab.active {
      background: var(--surface-elevated);
      border-color: var(--border);
      color: #fff;
    }
    .pulse-indicator-yellow {
      width: 8px;
      height: 8px;
      background: #f59e0b;
      border-radius: 50%;
      display: inline-block;
      box-shadow: 0 0 8px #f59e0b;
      animation: pulse 1.8s infinite;
    }
    .pulse-indicator-green {
      width: 7px;
      height: 7px;
      background: #10b981;
      border-radius: 50%;
      display: inline-block;
      box-shadow: 0 0 6px #10b981;
      animation: pulse 1.5s infinite;
    }
    /* Binomo Chart Timing & Confluence Radar */
    .binomo-timing-banner {
      background: linear-gradient(135deg, rgba(15, 23, 42, 0.95), rgba(30, 41, 59, 0.9));
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 14px;
      margin-bottom: 10px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.3);
      transition: border-color 0.3s ease, box-shadow 0.3s ease;
    }
    .timing-col-left {
      display: flex;
      flex-direction: column;
      gap: 4px;
      flex: 1;
      min-width: 250px;
    }
    .timing-col-right {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .timing-action-badge {
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.03em;
      padding: 4px 10px;
      border-radius: 5px;
      text-transform: uppercase;
      font-family: var(--font-mono);
      background: rgba(16, 185, 129, 0.2);
      color: #10b981;
      border: 1px solid #10b981;
      box-shadow: 0 0 10px rgba(16, 185, 129, 0.25);
    }
    .timing-action-badge.sell {
      background: rgba(239, 68, 68, 0.2);
      color: #ef4444;
      border: 1px solid #ef4444;
      box-shadow: 0 0 10px rgba(239, 68, 68, 0.25);
    }
    .timing-action-badge.wait {
      background: rgba(96, 165, 250, 0.2);
      color: #60a5fa;
      border: 1px solid #60a5fa;
      box-shadow: 0 0 10px rgba(96, 165, 250, 0.2);
    }
    .timing-score-pill {
      font-size: 11px;
      font-weight: 700;
      color: #cbd5e1;
      background: rgba(255, 255, 255, 0.06);
      padding: 3px 8px;
      border-radius: 4px;
      border: 1px solid rgba(255, 255, 255, 0.1);
      font-family: var(--font-mono);
    }
    .timing-type-pill {
      font-size: 10px;
      color: #94a3b8;
      background: rgba(255, 255, 255, 0.04);
      padding: 3px 6px;
      border-radius: 4px;
      text-transform: uppercase;
      font-weight: 600;
    }
    .timing-reason-text {
      font-size: 12px;
      color: #e2e8f0;
      font-weight: 500;
      line-height: 1.4;
    }
    .timing-time-box {
      background: rgba(0, 0, 0, 0.35);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 6px;
      padding: 5px 8px;
      display: flex;
      flex-direction: column;
      min-width: 90px;
    }
    .timing-time-box.highlight {
      border-color: rgba(96, 165, 250, 0.4);
      background: rgba(15, 23, 42, 0.7);
    }
    .timing-box-label {
      font-size: 9px;
      color: #94a3b8;
      text-transform: uppercase;
      font-weight: 700;
      margin-bottom: 2px;
    }
    .timing-box-val {
      font-size: 11px;
      font-family: var(--font-mono);
      font-weight: 700;
      color: #fff;
    }
    .timing-countdown-badge {
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 800;
      color: #60a5fa;
      background: rgba(96, 165, 250, 0.2);
      padding: 2px 5px;
      border-radius: 3px;
      border: 1px solid rgba(96, 165, 250, 0.4);
      letter-spacing: 0.02em;
    }
    .timing-apply-btn {
      background: linear-gradient(135deg, #2563eb, #1d4ed8);
      color: #fff;
      border: none;
      padding: 7px 12px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 700;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 4px;
      transition: all 0.2s;
    }
    .timing-apply-btn:hover {
      background: linear-gradient(135deg, #3b82f6, #2563eb);
      transform: translateY(-1px);
    }
    .timing-refresh-btn {
      background: var(--surface-elevated);
      color: #94a3b8;
      border: 1px solid var(--border);
      width: 28px;
      height: 28px;
      border-radius: 6px;
      font-size: 14px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: color 0.2s;
    }
    .timing-refresh-btn:hover {
      color: #fff;
      border-color: #60a5fa;
    }
    .pulse-highlight {
      animation: pulseHighlight 0.6s 3 alternate ease-in-out;
    }
    @keyframes pulseHighlight {
      0% { transform: scale(1); filter: drop-shadow(0 0 0px #fff); }
      100% { transform: scale(1.03); filter: drop-shadow(0 0 12px #fff); }
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="brand">
        <span class="badge-market" id="headerMarketBadge">🇺🇸 US & 🇮🇳 INDIA</span>
        <h1>Quantitative AI Market Terminal</h1>
      </div>
      <div class="header-actions">
        <button onclick="scanAndNotifyAll()" class="primary" style="background: #10b981; border-color: #10b981;" title="Scan market now and send Buy/Sell alerts">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          ⚡ Scan & Send Buy/Sell Alerts
        </button>
        <button onclick="toggleAutoMonitor()" id="btnAutoMonitor" style="border-color: #334155;">
          🔔 Auto-Alerts: ON
        </button>
        <button onclick="toggleAlertsDrawer()" id="btnAlertsBell" style="position: relative;">
          🔔 Alert Log
          <span id="alertBellBadge" style="display:none; background:#ef4444; color:#fff; border-radius:10px; font-size:10px; padding:1px 5px; font-weight:700; margin-left:4px;">0</span>
        </button>
        <button onclick="rescanActiveMarket()">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
          Rescan
        </button>
      </div>
    </header>

    <!-- Main Market & Fund Navigation Tabs -->
    <div class="market-tabs">
      <div class="market-tab active" id="tabUS" onclick="switchView('US')">
        <span>🇺🇸 US Stocks</span>
      </div>
      <div class="market-tab" id="tabIN" onclick="switchView('IN')">
        <span>🇮🇳 India Stocks</span>
      </div>
      <div class="market-tab" id="tabAI" onclick="switchView('AI')">
        <span>🤖 AI Auto-Trader ($1,000)</span>
        <span id="aiTabLivePill" style="background: rgba(16,185,129,0.2); color: #10b981; border: 1px solid rgba(16,185,129,0.4); font-size: 10px; padding: 2px 7px; border-radius: 10px; font-weight: 700; margin-left: 5px;">ACTIVE</span>
      </div>
      <div class="market-tab" id="tabPractice" onclick="switchView('Practice')">
        <span>🎮 Practice Sandbox ($1,000)</span>
        <span style="background: rgba(99,102,241,0.2); color: #818cf8; border: 1px solid rgba(99,102,241,0.4); font-size: 10px; padding: 2px 7px; border-radius: 10px; font-weight: 700; margin-left: 5px;">TEST LAB</span>
      </div>
    </div>

    <!-- ============================================== -->
    <!-- VIEW 1: LIVE MARKET ANALYSIS (US & INDIA)      -->
    <!-- ============================================== -->
    <div id="marketView">
      <!-- Macro Market Regime & Broad Market Analysis -->
      <div class="macro-section" id="macroSection">
      <div class="macro-banner" id="macroBanner">
        <div class="macro-regime-row">
          <div class="macro-regime-badge" id="macroRegimeBadge">
            <span class="macro-dot" id="macroDot"></span>
            <span id="macroRegimeText">ANALYZING CURRENT MARKET REGIME...</span>
          </div>
          <div class="macro-meta-actions">
            <span id="macroUpdateTime" style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">Scanning...</span>
            <button class="macro-btn" onclick="fetchMarketOverview(true)" style="padding: 3px 8px; font-size: 11px;">↻ Refresh Market</button>
          </div>
        </div>

        <p class="macro-guidance" id="macroGuidance">Evaluating market-wide breadth, index trend lines, and volatility index...</p>

        <div class="macro-indices" id="macroIndices">
          <!-- Populated by JS -->
        </div>
      </div>
    </div>

    <!-- Search bar & Quick Picks -->
    <div class="search-section">
      <div class="search-box">
        <input type="text" id="tickerInput" placeholder="Search any US or Indian ticker (e.g. NVDA, TSLA, AAPL, RELIANCE, TCS)" onkeydown="if(event.key==='Enter') searchTicker()">
        <button onclick="searchTicker()" class="primary">Analyze</button>
      </div>
      <div class="quick-pills" id="quickPills"></div>
    </div>

    <!-- Real-Time TradingView Candlestick Chart (Direct Embed Iframe) -->
    <div class="chart-card">
      <div class="card-title" style="flex-direction: column; gap: 8px; align-items: stretch;">
        <!-- Row 1: Symbol Badge + Timeframe Bar -->
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-weight: 700;">📊 Candlestick Chart</span>
            <span id="tvSymbolLabel" style="font-family: var(--font-mono); font-weight: 700; color: #60a5fa; background: rgba(59,130,246,0.15); padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(59,130,246,0.3);">NASDAQ:NVDA • [1D]</span>
          </div>
          <!-- Timeframe selector -->
          <div style="display: flex; align-items: center; gap: 3px; background: rgba(15,23,42,0.7); padding: 3px 6px; border-radius: 6px; border: 1px solid var(--border);">
            <span style="font-size: 10px; color: var(--text-muted); font-weight: 600; margin-right: 3px; text-transform: uppercase;">TF:</span>
            <button class="macro-btn tf-btn" id="tfBtn_1m" onclick="setChartTimeframe('1m', '1')" style="padding: 2px 7px; font-size: 11px;">1m</button>
            <button class="macro-btn tf-btn" id="tfBtn_5m" onclick="setChartTimeframe('5m', '5')" style="padding: 2px 7px; font-size: 11px;">5m</button>
            <button class="macro-btn tf-btn" id="tfBtn_15m" onclick="setChartTimeframe('15m', '15')" style="padding: 2px 7px; font-size: 11px;">15m</button>
            <button class="macro-btn tf-btn" id="tfBtn_30m" onclick="setChartTimeframe('30m', '30')" style="padding: 2px 7px; font-size: 11px;">30m</button>
            <button class="macro-btn tf-btn" id="tfBtn_1h" onclick="setChartTimeframe('1h', '60')" style="padding: 2px 7px; font-size: 11px;">1H</button>
            <button class="macro-btn tf-btn active" id="tfBtn_1d" onclick="setChartTimeframe('1d', 'D')" style="padding: 2px 7px; font-size: 11px; background: rgba(59,130,246,0.25); color: #60a5fa; border-color: #3b82f6;">1D</button>
            <button class="macro-btn tf-btn" id="tfBtn_1w" onclick="setChartTimeframe('1w', 'W')" style="padding: 2px 7px; font-size: 11px;">1W</button>
          </div>
        </div>
        <!-- Row 2: Indicator Presets + Fullscreen Link -->
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.06);">
          <div style="display: flex; align-items: center; gap: 5px; flex-wrap: wrap;">
            <span style="font-size: 10px; color: var(--text-muted); font-weight: 600; text-transform: uppercase;">Indicators:</span>
            <button class="macro-btn" id="tvPresetAll" onclick="setTradingViewPreset('all')" style="padding: 2px 8px; font-size: 11px; background: rgba(59,130,246,0.25); color: #60a5fa; border-color: #3b82f6;">🔥 All Indicators</button>
            <button class="macro-btn" id="tvPresetMomentum" onclick="setTradingViewPreset('momentum')" style="padding: 2px 8px; font-size: 11px;">⚡ Momentum (RSI/MACD)</button>
            <button class="macro-btn" id="tvPresetTrend" onclick="setTradingViewPreset('trend')" style="padding: 2px 8px; font-size: 11px;">📈 Trend (EMAs/BB)</button>
            <button class="macro-btn" id="tvPresetVol" onclick="setTradingViewPreset('vol')" style="padding: 2px 8px; font-size: 11px;">🌊 Volume & ATR</button>
          </div>
          <button class="macro-btn" onclick="openFullTradingViewTab()" style="padding: 2px 8px; font-size: 11px; background: rgba(16,185,129,0.15); color: #10b981; border-color: rgba(16,185,129,0.4);">↗ Full TradingView</button>
        </div>
      </div>
      <div class="tradingview-container">
        <iframe
          id="tradingview_iframe"
          src="about:blank"
          allowtransparency="true"
          scrolling="no"
          allowfullscreen>
        </iframe>
      </div>
    </div>

    <!-- Quantitative Confluence Analysis Grid -->
    <div class="main-grid">
      <div class="card">
        <div class="card-title">
          <span>5-Pillar Confluence Diagnosis</span>
          <span id="updateTime" style="font-family: var(--font-mono); font-size: 11px;">Initializing...</span>
        </div>

        <div class="hero-ticker">
          <div>
            <div class="ticker-symbol" id="heroSymbol">Loading...</div>
            <div class="ticker-name" id="heroName">Fetching real-time market data...</div>
          </div>
          <div class="price-box">
            <div class="price-val" id="heroPrice">-</div>
            <div class="price-change" id="heroChange">-</div>
          </div>
        </div>

        <div class="signal-banner hold" id="signalBanner">
          <div>
            <div class="signal-badge" id="signalTitle">🟡 EVALUATING</div>
            <div style="font-size: 12px; margin-top: 2px;" id="signalConviction">Calculating technical indicators...</div>
          </div>
          <div class="action-badge" id="actionBadge">PLEASE WAIT</div>
        </div>

        <!-- 5 Pillars Progress -->
        <div class="pillars-grid">
          <div class="pillar-box">
            <div class="pillar-label">1. Analyst Valuation</div>
            <div class="pillar-val"><span id="p1Val">0</span><small>/25</small></div>
            <div class="pillar-bar"><div class="pillar-fill" id="p1Fill" style="width: 0%;"></div></div>
          </div>
          <div class="pillar-box">
            <div class="pillar-label">2. Trend Regime</div>
            <div class="pillar-val"><span id="p2Val">0</span><small>/25</small></div>
            <div class="pillar-bar"><div class="pillar-fill" id="p2Fill" style="width: 0%;"></div></div>
          </div>
          <div class="pillar-box">
            <div class="pillar-label">3. Momentum (RSI/MACD)</div>
            <div class="pillar-val"><span id="p3Val">0</span><small>/20</small></div>
            <div class="pillar-bar"><div class="pillar-fill" id="p3Fill" style="width: 0%;"></div></div>
          </div>
          <div class="pillar-box">
            <div class="pillar-label">4. Volatility/BB</div>
            <div class="pillar-val"><span id="p4Val">0</span><small>/15</small></div>
            <div class="pillar-bar"><div class="pillar-fill" id="p4Fill" style="width: 0%;"></div></div>
          </div>
          <div class="pillar-box">
            <div class="pillar-label">5. Smart Volume</div>
            <div class="pillar-val"><span id="p5Val">0</span><small>/15</small></div>
            <div class="pillar-bar"><div class="pillar-fill" id="p5Fill" style="width: 0%;"></div></div>
          </div>
        </div>

        <!-- Execution Plan -->
        <div class="card-title"><span>Calculated Execution Plan</span></div>
        <div class="execution-grid">
          <div class="exec-item">
            <div class="exec-label">Recommended Entry</div>
            <div class="exec-val" id="execEntry">-</div>
          </div>
          <div class="exec-item">
            <div class="exec-label">Stop-Loss (SL)</div>
            <div class="exec-val negative" id="execSL">-</div>
          </div>
          <div class="exec-item">
            <div class="exec-label">Take Profit 1 (Swing)</div>
            <div class="exec-val positive" id="execTP1">-</div>
          </div>
          <div class="exec-item">
            <div class="exec-label">TP2 (Analyst Target)</div>
            <div class="exec-val positive" id="execTP2">-</div>
          </div>
          <div class="exec-item">
            <div class="exec-label">Risk / Reward (TP1)</div>
            <div class="exec-val" id="execRR">-</div>
          </div>
          <div class="exec-item">
            <div class="exec-label">14-Day ATR</div>
            <div class="exec-val" id="execATR">-</div>
          </div>
        </div>

        <!-- Actionable Buy & Sell Execution Rules -->
        <div class="card-title"><span>Actionable Buy & Sell Execution Rules</span></div>
        <div class="triggers-grid">
          <div class="trigger-card buy-card" id="triggerBuyCard">
            <div class="trigger-top">
              <span class="trigger-badge buy">🟢 WHEN TO BUY</span>
              <span class="trigger-status" id="triggerBuyAction">ACCUMULATE ON DIP</span>
            </div>
            <div class="trigger-content" id="triggerBuyInstruction">
              Enter between $226.04–$229.66. Stop-Loss at $219.41 (-3.96%). Target TP1: $241.72 (+5.81%).
            </div>
            <div class="trigger-meta" id="triggerBuyMeta">
              <span>Risk:Reward: <strong id="triggerBuyRR">1:1.5</strong></span>
              <span>Confluence: <strong id="triggerBuyScore">92/100</strong></span>
            </div>
            <button class="trigger-action-btn buy-btn" onclick="dispatchDirectTradeAlert('BUY')">
              ⚡ Send Buy Alert to Phone & Discord
            </button>
            <button class="trigger-action-btn buy-btn" onclick="buyActiveStockInPortfolio()" style="margin-top: 6px; background: rgba(59,130,246,0.15); color: #60a5fa; border-color: rgba(59,130,246,0.3);">
              💼 Buy with Virtual $250 Credits
            </button>
          </div>

          <div class="trigger-card sell-card" id="triggerSellCard">
            <div class="trigger-top">
              <span class="trigger-badge sell">🔴 WHEN TO SELL</span>
              <span class="trigger-status" id="triggerSellAction">HOLD FOR TARGET</span>
            </div>
            <div class="trigger-content" id="triggerSellInstruction">
              Sell 50% at TP1 to lock gains. Hold remainder for TP2. Immediate exit if price drops to Stop Loss.
            </div>
            <div class="trigger-meta" id="triggerSellMeta">
              <span>TP1 Target: <strong id="triggerSellTP1">-</strong></span>
              <span>SL Cutoff: <strong id="triggerSellSL">-</strong></span>
            </div>
            <button class="trigger-action-btn sell-btn" onclick="dispatchDirectTradeAlert('SELL')">
              ⚡ Send Sell Alert to Phone & Discord
            </button>
          </div>
        </div>

        <p id="rationaleText" style="font-size: 12px; color: var(--text-muted); line-height: 1.6; margin-top: 10px;"></p>
      </div>

      <!-- Right Column: Gauge & Actions -->
      <div class="card" style="text-align: center;">
        <div class="card-title" style="width: 100%;"><span>Quantitative Score</span></div>
        <div class="gauge-circle" id="gaugeCircle">
          <div class="gauge-score" id="gaugeScore">-</div>
          <div class="gauge-max">/ 100</div>
        </div>
        <div class="gauge-verdict" id="gaugeVerdict" style="color: var(--yellow);">CALCULATING</div>
        <div style="font-size: 11px; color: var(--text-muted); margin-top: 6px;" id="analystSummary">Analyst & Technical Confluence</div>

        <div style="margin-top: 20px;">
          <button style="width: 100%; justify-content: center; margin-bottom: 8px;" onclick="triggerDiscordForActive()">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/></svg>
            Send Alert to Discord
          </button>
          <button style="width: 100%; justify-content: center; background: #2563eb; color: #fff; border-color: #3b82f6;" onclick="toggleChatDrawer()">
            💬 Ask AI About This Stock
          </button>
        </div>

        <!-- Webhook Quick Config -->
        <div style="margin-top: 16px; text-align: left; border-top: 1px solid var(--border); padding-top: 12px;">
          <div class="exec-label" style="margin-bottom: 5px; font-size: 10px; color: var(--text-muted);">Discord Webhook URL</div>
          <input type="text" id="webhookInput" style="width: 100%; background: var(--surface-elevated); border: 1px solid var(--border); color: #fff; padding: 6px 8px; border-radius: 4px; font-size: 11px; font-family: var(--font-mono); margin-bottom: 6px;" placeholder="https://discord.com/api/webhooks/...">
          <button style="width: 100%; font-size: 11px; padding: 5px;" onclick="saveWebhook()">Save & Test Webhook</button>
        </div>
      </div>
    </div>

    <!-- Watchlist Table -->
    <div class="card">
      <div class="card-title">
        <span id="watchlistTableTitle">Watchlist Overview</span>
        <span id="watchlistCount" style="font-family: var(--font-mono); font-size: 11px;">Loading...</span>
      </div>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Price</th>
              <th>Analyst Target</th>
              <th>Upside</th>
              <th>Score</th>
              <th>RSI(14)</th>
              <th>200 EMA</th>
              <th>Signal</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="watchlistBody">
            <tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 20px;">Loading watchlist...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 24/7 Continuous AI Market Signals & Timestamps Stream -->
    <div class="card" style="margin-top: 18px;">
      <div class="card-title" style="flex-wrap: wrap; gap: 8px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span class="pulsing-dot" style="background: #10b981;"></span>
          <span style="font-weight: 700;">📡 24/7 Live AI Market Signals & Timestamps Stream</span>
          <span class="ai-model-badge" style="background: rgba(59,130,246,0.2); color: #60a5fa; border-color: rgba(59,130,246,0.4);">ALWAYS ACTIVE</span>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span id="signalsFeedCount" style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">0 signals logged</span>
          <button class="macro-btn" onclick="fetchSignalsFeed()" style="padding: 2px 8px; font-size: 11px;">↻ Refresh</button>
        </div>
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 12px;">
        <div style="font-size: 12px; color: var(--text-muted);">
          Scans live markets 24/7 and records exact Buy/Sell triggers, entry zones, and risk boundaries.
        </div>
        <div style="display: flex; gap: 4px;">
          <button class="macro-btn" id="sigFilterAll" onclick="filterSignalsFeed('ALL')" style="padding: 2px 8px; font-size: 11px; background: rgba(59,130,246,0.25); color: #60a5fa; border-color: #3b82f6;">All Signals</button>
          <button class="macro-btn" id="sigFilterBuy" onclick="filterSignalsFeed('BUY')" style="padding: 2px 8px; font-size: 11px;">🟢 BUY Triggers</button>
          <button class="macro-btn" id="sigFilterSell" onclick="filterSignalsFeed('SELL')" style="padding: 2px 8px; font-size: 11px;">🔴 SELL Triggers</button>
        </div>
      </div>
      <div class="table-container" style="max-height: 340px; overflow-y: auto;">
        <table>
          <thead>
            <tr>
              <th>Timestamp (IST)</th>
              <th>Asset</th>
              <th>Action</th>
              <th>Signal Type</th>
              <th>Trigger Price</th>
              <th>Score</th>
              <th>AI Instruction & Strategy</th>
              <th>Quick Action</th>
            </tr>
          </thead>
          <tbody id="signalsFeedBody">
            <tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 22px;">Monitoring market... Triggers with exact timestamps will stream here automatically.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div> <!-- end #marketView -->

  <!-- ============================================== -->
  <!-- VIEW 2: DEDICATED AI AUTONOMOUS TRADER VIEW    -->
  <!-- ============================================== -->
  <div id="aiTraderView" style="display: none; margin-top: 15px;">
    <!-- AI Autonomous Status & Control Banner -->
    <div class="ai-live-banner">
      <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
        <div class="pulsing-dot" id="aiEngineDot"></div>
        <div>
          <div style="font-size: 16px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 8px;">
            <span>🤖 AI Autonomous Fund Engine ($1,000 Portfolio)</span>
            <span id="aiAutoBadge" class="ai-model-badge" style="background: rgba(16, 185, 129, 0.2); color: #10b981; border-color: rgba(16, 185, 129, 0.4);">AUTONOMOUS: ACTIVE</span>
          </div>
          <div style="font-size: 12px; color: #94a3b8; margin-top: 2px;" id="aiEngineSubtitle">
            Continuous background forward-testing · Buying high-confluence setups (Score ≥ 70) · Auto-exiting on ATR SL & TP1/TP2
          </div>
        </div>
      </div>
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <button class="primary" onclick="triggerAutoTradeNow()" style="background: #10b981; border-color: #10b981; font-weight: 600;" title="Run AI forward scan immediately to execute buy/sell decisions">
          ⚡ Run AI Scan Now
        </button>
        <button onclick="toggleAutoTradingMode()" id="aiToggleBtn" style="background: #1e293b; border-color: #475569; font-weight: 600;" title="Toggle AI Autonomous Execution on/off">
          ⏸️ Pause Engine
        </button>
        <button class="primary" onclick="openAIReportModal()" style="background: #8b5cf6; border-color: #8b5cf6; font-weight: 600;" title="Generate institutional AI P&L and probability verification report">
          📊 AI P&L Report
        </button>
        <button onclick="resetPortfolioCredits()" style="border-color: #475569;" title="Reset virtual credits back to $1,000.00">
          ↺ Reset ($1,000)
        </button>
      </div>
    </div>

    <!-- Friendly Guidance Callout -->
    <div style="background: rgba(59, 130, 246, 0.08); border: 1px solid rgba(59, 130, 246, 0.25); border-radius: 8px; padding: 10px 14px; margin-top: 12px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
      <div style="font-size: 12px; color: #93c5fd; display: flex; align-items: center; gap: 8px;">
        <span style="font-size: 16px;">🤖</span>
        <span><strong>Autonomous AI Fund:</strong> The AI trades this $1,000 portfolio on its own 24/7 to audit predictive accuracy. Want to place your own trades with virtual cash? Use the <strong>Practice Sandbox</strong> tab.</span>
      </div>
      <button class="macro-btn" onclick="switchView('Practice')" style="padding: 4px 10px; font-size: 11px; background: rgba(99,102,241,0.25); color: #c7d2fe; border-color: rgba(99,102,241,0.5);">
        Open Practice Sandbox ➔
      </button>
    </div>

    <!-- 🎯 AI TRADING UNIVERSE & ASSET SELECTOR -->
    <div class="card" style="margin-top: 14px; border: 1px solid rgba(59,130,246,0.4); background: linear-gradient(180deg, rgba(30,41,59,0.5) 0%, rgba(15,23,42,0.7) 100%);">
      <div class="card-title" style="margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 16px;">🎯</span>
          <span style="font-size: 14px; font-weight: 800; color: #fff;">AI Auto-Trader Universe & Stock Selector</span>
          <span id="aiUniverseCountBadge" class="ai-model-badge" style="background: rgba(16,185,129,0.2); color: #10b981; border-color: rgba(16,185,129,0.4);">
            Loading Universe...
          </span>
        </div>
        <div style="display: flex; gap: 6px; flex-wrap: wrap;">
          <button type="button" class="macro-btn" onclick="selectUniversePreset('ALL')">⚡ All Assets</button>
          <button type="button" class="macro-btn" onclick="selectUniversePreset('US')">🇺🇸 US Mega-Caps</button>
          <button type="button" class="macro-btn" onclick="selectUniversePreset('IN')">🇮🇳 Nifty India</button>
          <button type="button" class="macro-btn" onclick="selectUniversePreset('CRYPTO_COMMODITY')">🪙 Crypto & Gold</button>
          <button type="button" class="macro-btn" onclick="selectUniversePreset('NONE')" style="color: #ef4444;">❌ Clear All</button>
        </div>
      </div>

      <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 12px; line-height: 1.4;">
        Choose which stocks the autonomous AI engine is permitted to trade with its $1,000 capital. Click any chip to toggle on/off, or command the chatbot directly: <em>"Set AI to trade only NVDA and BTC"</em>.
      </div>

      <!-- Scrollable Asset Selector Chips Grid -->
      <div id="aiUniverseChipsGrid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 8px; max-height: 220px; overflow-y: auto; padding: 4px;">
        <div style="color: var(--text-muted); font-size: 12px; padding: 10px; text-align: center; grid-column: 1 / -1;">
          Loading trading universe assets...
        </div>
      </div>

      <!-- Custom Asset Input & Action Bar -->
      <div style="margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); display: flex; gap: 8px; align-items: center; justify-content: space-between; flex-wrap: wrap;">
        <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
          <span style="font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase;">Add Custom Ticker:</span>
          <input type="text" id="aiUniverseCustomInput" placeholder="e.g. PLTR, INFY.NS, SOL/USD" style="width: 170px; background: var(--surface-elevated); border: 1px solid var(--border); color: #fff; padding: 6px 10px; border-radius: 4px; font-family: var(--font-mono); font-size: 12px; font-weight: 700;">
          <button type="button" class="primary" onclick="addCustomToAIUniverse()" style="padding: 6px 12px; font-size: 11px; font-weight: 700;">+ Add Ticker</button>
        </div>
        <button type="button" onclick="saveAIUniverseSelection()" style="padding: 6px 16px; background: #10b981; border: 1px solid #10b981; color: #fff; border-radius: 6px; font-size: 12px; font-weight: 800; cursor: pointer; display: flex; align-items: center; gap: 6px;">
          <span>💾</span> Save Active Universe
        </button>
      </div>
    </div>

    <!-- Probability & Accuracy Verification Matrix -->
    <div class="accuracy-matrix">
      <div class="accuracy-card">
        <div class="acc-title">🎯 AI Accuracy / Win Rate</div>
        <div class="acc-val" id="accWinRate">0.0%</div>
        <div class="acc-sub" id="accWinLossRatio">0 Wins / 0 Losses</div>
      </div>
      <div class="accuracy-card">
        <div class="acc-title">📈 Profit Factor</div>
        <div class="acc-val" id="accProfitFactor">1.00</div>
        <div class="acc-sub" id="accGrossPnl">Gross Win: $0.00 | Loss: $0.00</div>
      </div>
      <div class="accuracy-card">
        <div class="acc-title">💰 Total Portfolio Return</div>
        <div class="acc-val" id="accTotalReturn">+0.00%</div>
        <div class="acc-sub" id="accEquitySub">Equity: $1,000.00 / $1,000.00</div>
      </div>
      <div class="accuracy-card">
        <div class="acc-title">🛡️ Risk-Reward Ratio (RR)</div>
        <div class="acc-val" id="accAvgRR">2.3 : 1</div>
        <div class="acc-sub">ATR Trailing Stop / TP Rules</div>
      </div>
    </div>

    <!-- Stat Cards Grid -->
    <div class="portfolio-stats-grid" style="margin-top: 16px;">
      <div class="portfolio-stat-box">
        <div class="exec-label">Total Portfolio Equity</div>
        <div class="stat-big-val" id="portTotalEquity">$1,000.00</div>
        <div class="stat-sub-val" id="portTotalReturn">+0.00% Overall</div>
      </div>
      <div class="portfolio-stat-box">
        <div class="exec-label">Available Cash</div>
        <div class="stat-big-val" id="portCash">$1,000.00</div>
        <div class="stat-sub-val">Virtual Buying Power</div>
      </div>
      <div class="portfolio-stat-box">
        <div class="exec-label">Realized Net P&L</div>
        <div class="stat-big-val" id="portRealizedPnl">$0.00</div>
        <div class="stat-sub-val" id="portClosedTrades">0 Closed Trades</div>
      </div>
      <div class="portfolio-stat-box">
        <div class="exec-label">Unrealized Live P&L</div>
        <div class="stat-big-val" id="portUnrealizedPnl">$0.00</div>
        <div class="stat-sub-val" id="portOpenCount">0 Active Holdings</div>
      </div>
      <div class="portfolio-stat-box">
        <div class="exec-label">Active Capital Deployed</div>
        <div class="stat-big-val" id="portInvestedVal">$0.00</div>
        <div class="stat-sub-val" id="portMaxPositions">Max 4 concurrent ($250/ea)</div>
      </div>
    </div>

    <!-- Active Forward-Test Positions -->
    <div class="card" style="margin-top: 18px;">
      <div class="card-title" style="margin-bottom: 10px;">
        <span>🟢 Open Positions Autonomously Managed by AI</span>
        <span id="portOpenPositionsMeta" style="font-family: var(--font-mono); font-size: 11px;">0 open positions</span>
      </div>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Shares</th>
              <th>Entry Price</th>
              <th>Live Price</th>
              <th>Invested</th>
              <th>Current Value</th>
              <th>Unrealized P&L</th>
              <th>Stop Loss</th>
              <th>TP1 Target</th>
              <th>AI Score & Bias</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="portOpenTableBody">
            <tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 22px;">No active positions. The AI autonomous engine buys when a stock achieves ≥ 70 Confluence Score.</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Dedicated AI Trade Records Table (Audit of Accuracy) -->
    <div class="card" style="margin-top: 18px;">
      <div class="card-title" style="margin-bottom: 10px; flex-wrap: wrap; gap: 8px;">
        <div>
          <span style="font-size: 14px; font-weight: 700;">📜 AI Autonomous Trade Records & Accuracy Audit Log</span>
          <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">All autonomous executions with entry/exit timestamps, P&L, probability score, and exit triggers.</div>
        </div>
        <span id="portTradeHistoryMeta" style="font-family: var(--font-mono); font-size: 11px;">0 recorded trades</span>
      </div>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Asset</th>
              <th>Action Flow</th>
              <th>Score</th>
              <th>Entry Price</th>
              <th>Exit Price</th>
              <th>Invested</th>
              <th>Proceeds</th>
              <th>Realized P&L</th>
              <th>Outcome</th>
              <th>Trigger / Reason</th>
              <th>Exit Time</th>
            </tr>
          </thead>
          <tbody id="portHistoryTableBody">
            <tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 22px;">No trade records yet. The autonomous engine records all executions here as positions close via Stop-Loss or Take-Profit.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ======================================================= -->
  <!-- VIEW 3: PRACTICE SANDBOX & TEST AI GUIDANCE ($1,000)    -->
  <!-- ======================================================= -->
  <div id="practiceView" style="display: none; margin-top: 15px;">
    
    <!-- Binomo Top Navigation & Asset Selector Bar -->
    <div class="binomo-top-bar">
      <!-- Left: Asset Switcher -->
      <div class="binomo-assets-scroll">
        <span style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; margin-right: 4px;">Assets:</span>
        <button type="button" class="binomo-asset-chip active" data-sym="NVDA" onclick="selectPracticeAsset('NVDA')">
          <span class="chip-dot" style="background: #10b981;"></span>
          <strong>NVDA</strong> <span class="chip-rate">+43%</span>
        </button>
        <button type="button" class="binomo-asset-chip" data-sym="XAU/USD" onclick="selectPracticeAsset('XAU/USD')">
          <span class="chip-dot" style="background: #f59e0b;"></span>
          <strong>GOLD (XAU/USD)</strong> <span class="chip-rate">+15%</span>
        </button>
        <button type="button" class="binomo-asset-chip" data-sym="BTC/USD" onclick="selectPracticeAsset('BTC/USD')">
          <span class="chip-dot" style="background: #f59e0b;"></span>
          <strong>BTC/USD</strong> <span class="chip-rate">+25%</span>
        </button>
        <button type="button" class="binomo-asset-chip" data-sym="ETH/USD" onclick="selectPracticeAsset('ETH/USD')">
          <span class="chip-dot" style="background: #60a5fa;"></span>
          <strong>ETH/USD</strong> <span class="chip-rate">+20%</span>
        </button>
        <button type="button" class="binomo-asset-chip" data-sym="RELIANCE.NS" onclick="selectPracticeAsset('RELIANCE.NS')">
          <span class="chip-dot" style="background: #f59e0b;"></span>
          <strong>RELIANCE.NS</strong> <span class="chip-rate">₹ INR</span>
        </button>
        <button type="button" class="binomo-asset-chip" data-sym="ICICIBANK.NS" onclick="selectPracticeAsset('ICICIBANK.NS')">
          <span class="chip-dot" style="background: #10b981;"></span>
          <strong>ICICIBANK.NS</strong> <span class="chip-rate">₹ INR</span>
        </button>
        <button type="button" class="binomo-asset-chip" data-sym="AAPL" onclick="selectPracticeAsset('AAPL')">
          <span class="chip-dot" style="background: #94a3b8;"></span>
          <strong>AAPL</strong> <span class="chip-rate">+18%</span>
        </button>
        <button type="button" class="binomo-asset-chip" data-sym="TSLA" onclick="selectPracticeAsset('TSLA')">
          <span class="chip-dot" style="background: #ef4444;"></span>
          <strong>TSLA</strong> <span class="chip-rate">+35%</span>
        </button>
        <button type="button" class="binomo-asset-chip" data-sym="EUR/USD" onclick="selectPracticeAsset('EUR/USD')">
          <span class="chip-dot" style="background: #60a5fa;"></span>
          <strong>EUR/USD</strong> <span class="chip-rate">Forex</span>
        </button>
      </div>

      <!-- Right: Binomo Account Pill -->
      <div class="binomo-account-card">
        <div class="binomo-demo-badge">
          <span class="pulse-indicator-yellow"></span>
          <span>DEMO ACCOUNT</span>
        </div>
        <div class="binomo-balance-group">
          <div class="binomo-cash-val" id="pracCash">$1,000.00</div>
          <div class="binomo-equity-sub" id="pracEquitySub">Equity: $1,000.00</div>
        </div>
        <button onclick="resetPracticeCredits()" class="binomo-recharge-btn" title="Reset practice virtual credits back to $1,000.00">
          ↺ Refill ($1,000)
        </button>
      </div>
    </div>

    <!-- Binomo Quick Stats Ribbon -->
    <div class="binomo-stats-ribbon">
      <div class="binomo-stat-item">
        <span class="binomo-stat-label">🎯 Win Rate</span>
        <span class="binomo-stat-val" id="pracWinRate" style="color: #10b981;">0.0%</span>
        <span class="binomo-stat-sub" id="pracWinLossRatio">0 Wins / 0 Losses</span>
      </div>
      <div class="binomo-stat-item">
        <span class="binomo-stat-label">💰 Total Return</span>
        <span class="binomo-stat-val" id="pracTotalReturn">+0.00%</span>
        <span class="binomo-stat-sub">Virtual P&L</span>
      </div>
      <div class="binomo-stat-item">
        <span class="binomo-stat-label">📈 Realized Net P&L</span>
        <span class="binomo-stat-val" id="pracRealizedPnl">$0.00</span>
        <span class="binomo-stat-sub" id="pracClosedTrades">0 Closed Trades</span>
      </div>
      <div class="binomo-stat-item" style="border: none;">
        <span class="binomo-stat-label">⚡ AI Mode</span>
        <span class="binomo-stat-val" style="color: #60a5fa;">QUANT RADAR</span>
        <span class="binomo-stat-sub">5-Pillar Confluence</span>
      </div>
    </div>

    <!-- Binomo Main Trading Arena (Chart Left + Dock Right) -->
    <div class="binomo-terminal-grid">
      
      <!-- LEFT: Live Candlestick Chart Area -->
      <div class="binomo-chart-section">
        <div class="binomo-chart-header">
          <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
            <span id="pracTvSymbolLabel" style="font-family: var(--font-mono); font-weight: 700; color: #60a5fa; background: rgba(59,130,246,0.15); padding: 4px 10px; border-radius: 4px; border: 1px solid rgba(59,130,246,0.3); font-size: 13px;">NASDAQ:NVDA • [1m]</span>
            <span id="binomoSignalBadge" style="font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px; border: 1px solid #10b981; background: rgba(16,185,129,0.15); color: #10b981;">
              AI: STRONG BUY (85/100)
            </span>
          </div>
          <!-- Timeframe selector -->
          <div class="binomo-tf-bar">
            <span style="font-size: 10px; color: var(--text-muted); font-weight: 700; text-transform: uppercase;">TF:</span>
            <button class="macro-btn tf-btn active" id="pracTfBtn_1m" onclick="setPracticeTimeframe('1m', '1')">1m</button>
            <button class="macro-btn tf-btn" id="pracTfBtn_5m" onclick="setPracticeTimeframe('5m', '5')">5m</button>
            <button class="macro-btn tf-btn" id="pracTfBtn_15m" onclick="setPracticeTimeframe('15m', '15')">15m</button>
            <button class="macro-btn tf-btn" id="pracTfBtn_30m" onclick="setPracticeTimeframe('30m', '30')">30m</button>
            <button class="macro-btn tf-btn" id="pracTfBtn_1h" onclick="setPracticeTimeframe('1h', '60')">1H</button>
            <button class="macro-btn tf-btn" id="pracTfBtn_1d" onclick="setPracticeTimeframe('1d', 'D')">1D</button>
          </div>
        </div>

        <!-- Real-Time AI Chart Timing & Confluence Radar -->
        <div id="pracTimingRadar" class="binomo-timing-banner">
          <div class="timing-col-left">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span id="timingActionBadge" class="timing-action-badge">▲ PERFECT TIME TO BUY</span>
              <span id="timingScorePill" class="timing-score-pill">85/100 Score</span>
              <span id="timingTypePill" class="timing-type-pill">CONFLUENCE</span>
            </div>
            <div id="timingReasonText" class="timing-reason-text">
              Analyzing chart for optimal execution timestamp...
            </div>
          </div>
          
          <div class="timing-col-right">
            <div class="timing-time-box">
              <span class="timing-box-label">🎯 Signal Timestamp</span>
              <span id="timingTriggerTime" class="timing-box-val">--:--:-- IST</span>
            </div>
            <div class="timing-time-box">
              <span class="timing-box-label">⏱️ Entry Window</span>
              <span id="timingWindowVal" class="timing-box-val">--:-- – --:--</span>
            </div>
            <div class="timing-time-box highlight">
              <span class="timing-box-label">⏳ Next Candle Close</span>
              <div style="display: flex; align-items: center; gap: 6px;">
                <span id="timingNextBarTime" class="timing-box-val" style="font-weight: 700;">--:--:--</span>
                <span id="timingCountdownBadge" class="timing-countdown-badge">00:00s</span>
              </div>
            </div>
            <button type="button" id="timingApplyBtn" onclick="applyTimingToConsole()" class="timing-apply-btn" title="Pre-fill console with this optimal setup">
              ⚡ Apply Setup
            </button>
            <button type="button" onclick="analyzeCurrentChartTiming(true)" class="timing-refresh-btn" title="Re-analyze chart timing">
              ↻
            </button>
          </div>
        </div>

        <!-- Embedded Live TradingView Chart Frame -->
        <div class="binomo-chart-wrapper">
          <iframe
            id="practice_tv_iframe"
            src="about:blank"
            allowtransparency="true"
            scrolling="no"
            allowfullscreen>
          </iframe>
        </div>

        <!-- Live Holdings Quick-Exit Strip Below Chart -->
        <div style="margin-top: 10px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
          <div id="pracHoldingsChips" style="display: flex; align-items: center; flex-wrap: wrap; gap: 6px; font-size: 11px;"></div>
          <div style="font-size: 11px; color: var(--text-muted);">
            Available Cash: <span id="pracConsoleCash" style="color: #10b981; font-weight: 700;">$1,000.00</span>
          </div>
        </div>
      </div>

      <!-- RIGHT: Binomo Trading Dock -->
      <div class="binomo-trade-dock">
        
        <!-- Asset Header & Live Pulsing Price -->
        <div class="binomo-dock-header">
          <div>
            <div id="binomoAssetTitle" style="font-size: 16px; font-weight: 800; color: #fff; letter-spacing: -0.02em;">NVDA</div>
            <div id="binomoPriceChange" class="price-change positive" style="font-size: 11px;">+43.2% Target Upside</div>
          </div>
          <div style="text-align: right;">
            <div id="binomoLivePrice" class="binomo-live-price">$231.62</div>
            <div style="font-size: 10px; color: #10b981; display: flex; align-items: center; justify-content: flex-end; gap: 4px;">
              <span class="pulse-indicator-green"></span> LIVE QUOTE
            </div>
          </div>
        </div>

        <!-- Custom Symbol Input (for any other ticker) -->
        <div style="margin-top: 4px;">
          <label style="font-size: 10px; color: var(--text-muted); text-transform: uppercase; font-weight: 700; display: block; margin-bottom: 4px;">Asset Ticker</label>
          <div style="display: flex; gap: 6px;">
            <input type="text" id="pracInputSymbol" value="NVDA" placeholder="e.g. NVDA, RELIANCE.NS, XAU/USD" onchange="selectPracticeAsset(this.value)" style="flex: 1; background: var(--surface-elevated); border: 1px solid var(--border); color: #fff; padding: 7px 10px; border-radius: 6px; font-family: var(--font-mono); font-size: 13px; font-weight: 700;">
            <button type="button" onclick="selectPracticeAsset(document.getElementById('pracInputSymbol').value)" style="padding: 7px 12px; background: var(--surface-elevated); border: 1px solid var(--border); color: #60a5fa; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer;">Load</button>
          </div>
        </div>

        <!-- Expiration / Duration Selector -->
        <div>
          <label style="font-size: 10px; color: var(--text-muted); text-transform: uppercase; font-weight: 700; display: block; margin-bottom: 6px;">Timeframe / Expiry</label>
          <div class="binomo-time-presets">
            <button type="button" class="binomo-time-btn active" id="btnExp_1m" onclick="setPracticeTimeframe('1m', '1')">1 min</button>
            <button type="button" class="binomo-time-btn" id="btnExp_5m" onclick="setPracticeTimeframe('5m', '5')">5 min</button>
            <button type="button" class="binomo-time-btn" id="btnExp_15m" onclick="setPracticeTimeframe('15m', '15')">15 min</button>
            <button type="button" class="binomo-time-btn" id="btnExp_30m" onclick="setPracticeTimeframe('30m', '30')">30 min</button>
            <button type="button" class="binomo-time-btn" id="btnExp_1h" onclick="setPracticeTimeframe('1h', '60')">1 hr</button>
          </div>
        </div>

        <!-- Investment Amount Section with Steppers -->
        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <label style="font-size: 10px; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">Investment ($ USD)</label>
            <span onclick="setPracticeAmountMax()" style="font-size: 10px; color: #60a5fa; cursor: pointer; font-weight: 700; text-decoration: underline;">Max All</span>
          </div>
          
          <div class="binomo-amount-stepper">
            <button type="button" onclick="adjustPracticeAmount(-50)" class="stepper-btn">−</button>
            <input type="number" id="pracInputAmount" value="250" min="10" max="1000" oninput="updateBinomoPayout()" style="flex: 1; text-align: center; background: transparent; border: none; color: #fff; font-family: var(--font-mono); font-size: 18px; font-weight: 800;">
            <button type="button" onclick="adjustPracticeAmount(50)" class="stepper-btn">+</button>
          </div>

          <!-- Quick Amount Chips -->
          <div class="binomo-amount-chips">
            <button type="button" onclick="setPracticeAmountPreset(50)">$50</button>
            <button type="button" onclick="setPracticeAmountPreset(100)">$100</button>
            <button type="button" onclick="setPracticeAmountPreset(250)">$250</button>
            <button type="button" onclick="setPracticeAmountPreset(500)">$500</button>
          </div>
        </div>

        <!-- Dynamic Payout & Projected Profit Box (Binomo Signature) -->
        <div class="binomo-payout-card">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <span style="font-size: 11px; color: #94a3b8; font-weight: 600;">Expected Target Payout:</span>
            <span id="binomoExpectedProfit" style="font-family: var(--font-mono); font-weight: 800; color: #10b981; font-size: 13px;">+$12.50 (+5.0%)</span>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-size: 11px; color: #64748b;">Total Capital Returned:</span>
            <span id="binomoTotalPayout" style="font-family: var(--font-mono); font-weight: 700; color: #fff; font-size: 14px;">$262.50</span>
          </div>
        </div>

        <!-- Risk Protection: SL & TP -->
        <div style="background: rgba(15,23,42,0.6); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-size: 10px; color: var(--text-muted); font-weight: 700; text-transform: uppercase;">🛡️ Risk Protection</span>
            <span style="font-size: 10px; color: #818cf8;">Auto-Bracket</span>
          </div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
            <div>
              <span style="font-size: 10px; color: #ef4444; display: block; margin-bottom: 2px;">Stop Loss</span>
              <input type="number" id="pracInputSL" placeholder="Auto -5%" step="0.01" style="width: 100%; background: var(--surface-elevated); border: 1px solid var(--border); color: #fff; padding: 4px 6px; border-radius: 4px; font-family: var(--font-mono); font-size: 11px;">
            </div>
            <div>
              <span style="font-size: 10px; color: #10b981; display: block; margin-bottom: 2px;">Take Profit</span>
              <input type="number" id="pracInputTP" placeholder="Auto +5%" step="0.01" style="width: 100%; background: var(--surface-elevated); border: 1px solid var(--border); color: #fff; padding: 4px 6px; border-radius: 4px; font-family: var(--font-mono); font-size: 11px;">
            </div>
          </div>
        </div>

        <!-- Live Timing Status Notice in Trade Dock -->
        <div id="dockTimingNotice" style="background: rgba(16,185,129,0.12); border: 1px solid #10b981; border-radius: 6px; padding: 8px 10px; font-size: 11px; margin-top: 4px; display: flex; align-items: center; justify-content: space-between; transition: all 0.3s ease;">
          <div>
            <div id="dockTimingHeader" style="font-weight: 800; color: #10b981; font-size: 11px; letter-spacing: 0.02em;">▲ OPTIMAL BUY WINDOW ACTIVE</div>
            <div id="dockTimingSub" style="color: #cbd5e1; font-size: 10px; margin-top: 1px;">Trigger: --:--:-- IST • Next Bar Close</div>
          </div>
          <span id="dockCountdownPill" style="font-family: var(--font-mono); font-weight: 800; color: #10b981; background: rgba(16,185,129,0.2); padding: 3px 6px; border-radius: 4px; font-size: 11px; border: 1px solid rgba(16,185,129,0.3);">00:00s</span>
        </div>

        <!-- THE ICONIC BINOMO ACTION BUTTONS: UP (BUY) and DOWN (SELL) -->
        <div style="display: flex; flex-direction: column; gap: 10px; margin-top: 4px;">
          
          <!-- UP / CALL BUTTON -->
          <button type="button" onclick="submitPracticeOrder('BUY')" class="binomo-btn-up" title="Open Long / Buy Position with Virtual Credits">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span style="font-size: 22px; line-height: 1;">▲</span>
              <div style="text-align: left;">
                <div style="font-size: 15px; font-weight: 800; letter-spacing: 0.02em;">▲ UP / BUY</div>
                <div style="font-size: 10px; opacity: 0.85; font-weight: 600;">🛒 Buy Stock • Follow Bullish Setup</div>
              </div>
            </div>
            <div style="text-align: right; font-family: var(--font-mono); font-size: 12px; font-weight: 800;">
              +5.0%
            </div>
          </button>

          <!-- DOWN / PUT BUTTON -->
          <button type="button" onclick="submitPracticeOrder('SELL')" class="binomo-btn-down" title="Exit / Close Position or Sell">
            <div style="display: flex; align-items: center; gap: 10px;">
              <span style="font-size: 22px; line-height: 1;">▼</span>
              <div style="text-align: left;">
                <div style="font-size: 15px; font-weight: 800; letter-spacing: 0.02em;">▼ DOWN / SELL</div>
                <div style="font-size: 10px; opacity: 0.85; font-weight: 600;">🔴 Sell / Close • Lock Gains or Exit</div>
              </div>
            </div>
            <div style="text-align: right; font-family: var(--font-mono); font-size: 12px; font-weight: 800;">
              EXIT
            </div>
          </button>

        </div>

        <div style="font-size: 10px; color: var(--text-muted); text-align: center; margin-top: 4px;">
          Practice Mode • 100% Risk Free • Zero Real Money Involved
        </div>

      </div>
    </div>

    <!-- Binomo Bottom Drawer (Active Positions, History, AI Signals) -->
    <div class="binomo-drawer" style="margin-top: 20px;">
      <!-- Tab Controls -->
      <div class="binomo-drawer-tabs">
        <button type="button" class="drawer-tab active" id="tabDrawerOpen" onclick="switchPracticeDrawer('open')">
          🟢 Active Positions (<span id="pracDrawerOpenCount">0</span>)
        </button>
        <button type="button" class="drawer-tab" id="tabDrawerHistory" onclick="switchPracticeDrawer('history')">
          📜 Closed History (<span id="pracDrawerHistCount">0</span>)
        </button>
        <button type="button" class="drawer-tab" id="tabDrawerAI" onclick="switchPracticeDrawer('ai')">
          💡 AI Top Opportunities
        </button>
      </div>

      <!-- Drawer Content 1: Active Positions -->
      <div id="drawerContentOpen" class="drawer-content active">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <span style="font-size: 12px; font-weight: 700; color: #fff;">Currently Held Practice Assets</span>
          <span id="pracOpenMeta" style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">0 active positions</span>
        </div>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Shares</th>
                <th>Entry Price</th>
                <th>Live Price</th>
                <th>Invested</th>
                <th>Current Value</th>
                <th>Unrealized P&L</th>
                <th>Stop Loss</th>
                <th>Take Profit</th>
                <th>AI Score</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody id="pracOpenTbody">
              <tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 22px;">No active practice positions. Click "▲ UP / BUY" to open your first trade!</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Drawer Content 2: Closed History -->
      <div id="drawerContentHistory" class="drawer-content" style="display: none;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <span style="font-size: 12px; font-weight: 700; color: #fff;">Past Realized Trades Log</span>
          <span id="pracHistoryMeta" style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">0 recorded trades</span>
        </div>
        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Asset</th>
                <th>Action</th>
                <th>Score</th>
                <th>Entry Price</th>
                <th>Exit Price</th>
                <th>Invested</th>
                <th>Proceeds</th>
                <th>Realized P&L</th>
                <th>Outcome</th>
                <th>Exit Reason</th>
                <th>Exit Time</th>
              </tr>
            </thead>
            <tbody id="pracHistoryTbody">
              <tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 22px;">No closed practice trades yet.</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Drawer Content 3: AI Radar Guidance -->
      <div id="drawerContentAI" class="drawer-content" style="display: none;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <span style="font-size: 12px; font-weight: 700; color: #fff;">💡 Top High-Confluence AI Setups</span>
          <button class="macro-btn" onclick="fetchAIGuidance()" style="padding: 2px 8px; font-size: 11px;">↻ Refresh Setups</button>
        </div>
        <div id="aiGuidanceGrid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px;">
          <div style="color: var(--text-muted); font-size: 12px; padding: 15px; text-align: center; grid-column: 1 / -1;">
            Loading AI recommendations...
          </div>
        </div>
      </div>

    </div>

  </div>
  </div>

  <!-- FLOATING AI CHATBOT BUTTON & DRAWER -->
  <button class="ai-chat-btn" onclick="toggleChatDrawer()">
    <span>💬</span>
    <span>Ask AlphaQuant AI</span>
  </button>

  <div class="ai-chat-drawer" id="aiChatDrawer">
    <div class="ai-chat-header">
      <div class="ai-chat-title">
        <span>🤖 AlphaQuant AI Copilot</span>
        <span class="ai-model-badge" style="background: rgba(16,185,129,0.2); color: #10b981; border-color: rgba(16,185,129,0.4);">⚡ Full Execution Access</span>
      </div>
      <button onclick="toggleChatDrawer()" style="background: none; border: none; color: #94a3b8; font-size: 16px; padding: 0 4px; cursor: pointer;">✕</button>
    </div>

    <div class="ai-context-chip" id="aiContextChip">
      <span>🎯 Target:</span>
      <strong id="aiActiveSym" style="color: #60a5fa;">NVDA</strong>
      <span id="aiActivePrice">($229.35)</span>
      <span style="margin-left: auto; font-size: 10px; color: #10b981; font-weight: 700;">🟢 EXECUTION READY</span>
    </div>

    <div class="ai-quick-prompts">
      <div class="quick-chip" onclick="askQuickPrompt('Buy $250 of active stock in Practice sandbox')">🛒 Buy $250 Target</div>
      <div class="quick-chip" onclick="askQuickPrompt('Close / exit my position for the active stock')">🔴 Exit Target</div>
      <div class="quick-chip" onclick="askQuickPrompt('Set AI to trade only NVDA, TSLA, and BTC')">🎯 Focus AI Universe</div>
      <div class="quick-chip" onclick="askQuickPrompt('Reset my practice balance back to $1,000')">↺ Reset Demo</div>
      <div class="quick-chip" onclick="askQuickPrompt('Analyze the current setup for this stock: entry, risk, and technical bias.')">⚡ Full Analysis</div>
    </div>

    <div class="ai-chat-messages" id="aiChatMessages">
      <div class="chat-bubble assistant">
        Hello! I'm <strong>AlphaQuant AI Copilot</strong>. I have <strong>full autonomous execution privileges</strong> across this platform.<br><br>
        You can talk to me or command me directly:
        <ul style="margin: 6px 0 6px 18px; padding: 0; line-height: 1.5; font-size: 11px;">
          <li><strong>Trade Execution:</strong> <em>"Buy $200 NVDA"</em> or <em>"Sell my Apple position"</em></li>
          <li><strong>AI Universe Selection:</strong> <em>"Set AI to trade only NVDA, TSLA, and BTC"</em></li>
          <li><strong>Controls:</strong> <em>"Pause auto trading"</em> or <em>"Reset demo balance"</em></li>
          <li><strong>Quant Analysis:</strong> <em>"Analyze NVDA RSI, EMAs, and Stop Loss"</em></li>
        </ul>
        Whatever you tell me to do, I execute it directly on the platform!
      </div>
    </div>

    <div class="ai-chat-footer">
      <input type="text" id="aiChatInput" placeholder="Command AI: 'Buy $200 NVDA', 'Sell AAPL', 'Set AI to trade BTC'..." onkeydown="if(event.key==='Enter') sendChatMessage()">
      <button class="primary" onclick="sendChatMessage()" style="padding: 8px 14px;">Send</button>
    </div>
  </div>

  <div class="toast" id="toastMsg">Notification dispatched!</div>

  <!-- ALERT HISTORY MODAL / DRAWER -->
  <div class="alerts-drawer" id="alertsDrawer">
    <div class="alerts-header">
      <div style="font-weight: 700; font-size: 13px; display: flex; align-items: center; gap: 6px;">
        <span>🔔 Recent Buy & Sell Alerts</span>
      </div>
      <button onclick="toggleAlertsDrawer()" style="background: none; border: none; color: #94a3b8; font-size: 16px; cursor: pointer;">✕</button>
    </div>
    <div class="alerts-list" id="alertsList">
      <div style="text-align: center; color: var(--text-muted); padding: 20px; font-size: 12px;">No alerts recorded yet. Click "⚡ Scan & Send Buy/Sell Alerts" to scan the market.</div>
    </div>
  </div>

  <!-- AI PORTFOLIO & PROBABILITY AUDIT REPORT MODAL -->
  <div class="modal-overlay" id="reportModal" style="display: none;">
    <div class="modal-box">
      <div class="modal-header">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 15px; font-weight: 700;">📊 AI Quantitative P&L & Probability Audit</span>
          <span class="ai-model-badge" id="reportModelBadge">Nemotron-120B / Free MoE</span>
        </div>
        <button onclick="closeAIReportModal()" style="background: none; border: none; color: #94a3b8; font-size: 18px; cursor: pointer;">✕</button>
      </div>
      <div class="modal-body" id="reportBody">
        <div style="text-align: center; padding: 40px; color: var(--text-muted);">
          <div style="font-size: 24px; margin-bottom: 8px;">⏳</div>
          <div>Auditing $1,000 virtual portfolio P&L and computing probability accuracy...</div>
        </div>
      </div>
      <div class="modal-footer" style="padding: 12px 18px; background: #131826; border-top: 1px solid #242c3f; display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 11px; color: var(--text-muted);" id="reportTimestamp">-</span>
        <button class="primary" onclick="generateAIReport()" style="padding: 6px 12px;">↻ Re-run Audit</button>
      </div>
    </div>
  </div>

  <script>
    let currentMarket = 'US';
    let currentChartSymbol = 'NVDA';
    let activeResult = null;
    let chatHistory = [];

    const US_PILLS = ['NVDA', 'AAPL', 'MSFT', 'TSLA', 'AMZN', 'META', 'AMD', 'SPY', 'QQQ'];
    const IN_PILLS = ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS', 'TATAMOTORS.NS', 'SBIN.NS'];

    const US_EXCHANGE_MAP = {
      'SPY': 'AMEX', 'DIA': 'AMEX', 'IWM': 'AMEX',
      'BABA': 'NYSE', 'DIS': 'NYSE', 'BA': 'NYSE', 'JPM': 'NYSE', 'V': 'NYSE', 'WMT': 'NYSE', 'ORCL': 'NYSE', 'CRM': 'NYSE', 'NKE': 'NYSE', 'UBER': 'NYSE',
      'NVDA': 'NASDAQ', 'AAPL': 'NASDAQ', 'MSFT': 'NASDAQ', 'TSLA': 'NASDAQ', 'AMZN': 'NASDAQ', 'GOOGL': 'NASDAQ', 'GOOG': 'NASDAQ', 'META': 'NASDAQ', 'AMD': 'NASDAQ', 'QQQ': 'NASDAQ', 'NFLX': 'NASDAQ', 'INTC': 'NASDAQ', 'AVGO': 'NASDAQ', 'COIN': 'NASDAQ', 'PLTR': 'NASDAQ', 'SMCI': 'NASDAQ', 'ARM': 'NASDAQ'
    };

    const SPECIAL_TV_MAP = {
      'XAUUSD': 'OANDA:XAUUSD',
      'GOLD': 'OANDA:XAUUSD',
      'GC=F': 'COMEX:GC1!',
      'XAGUSD': 'OANDA:XAGUSD',
      'SILVER': 'OANDA:XAGUSD',
      'SI=F': 'COMEX:SI1!',
      'BTCUSD': 'BINANCE:BTCUSDT',
      'BTCUSDT': 'BINANCE:BTCUSDT',
      'ETHUSD': 'BINANCE:ETHUSDT',
      'ETHUSDT': 'BINANCE:ETHUSDT',
      'SOLUSD': 'BINANCE:SOLUSDT',
      'SOLUSDT': 'BINANCE:SOLUSDT',
      'XMRUSD': 'BINANCE:XMRUSDT',
      'XMRUSDT': 'BINANCE:XMRUSDT',
      'XRPUSD': 'BINANCE:XRPUSDT',
      'XRPUSDT': 'BINANCE:XRPUSDT',
      'DOGEUSD': 'BINANCE:DOGEUSDT',
      'EURUSD': 'FX:EURUSD',
      'GBPUSD': 'FX:GBPUSD',
      'USDINR': 'FX_IDC:USDINR'
    };

    function showToast(msg) {
      const t = document.getElementById('toastMsg');
      t.innerText = msg;
      t.style.display = 'block';
      setTimeout(() => { t.style.display = 'none'; }, 3000);
    }

    function toTradingViewSymbol(sym) {
      if (!sym) return 'NASDAQ:NVDA';
      sym = sym.toUpperCase().trim();

      if (SPECIAL_TV_MAP[sym]) {
        return SPECIAL_TV_MAP[sym];
      }

      // If symbol contains a slash (e.g. XAU/USD, XMA/USD, BTC/USD),
      // strip the slash so TradingView treats it as a single market instrument
      // rather than a mathematical ratio formula (which locks to 1D only!).
      if (sym.includes('/')) {
        const clean = sym.split('/').join('');
        if (SPECIAL_TV_MAP[clean]) {
          return SPECIAL_TV_MAP[clean];
        }
        return clean;
      }

      if (sym.includes('-')) {
        const clean = sym.replace(/-/g, '');
        if (SPECIAL_TV_MAP[clean]) {
          return SPECIAL_TV_MAP[clean];
        }
      }

      if (sym.endsWith('.NS')) {
        return 'NSE:' + sym.replace('.NS', '');
      }
      if (sym.endsWith('.BO')) {
        return 'BSE:' + sym.replace('.BO', '');
      }
      if (US_EXCHANGE_MAP[sym]) {
        return US_EXCHANGE_MAP[sym] + ':' + sym;
      }
      return sym;
    }

    let currentTradingViewPreset = 'all';
    const TV_STUDIES = {
      'all': 'RSI%40tv-basicstudies%1BMACD%40tv-basicstudies%1BMASimple%40tv-basicstudies%1BMAExp%40tv-basicstudies%1BBB%40tv-basicstudies%1BVolume%40tv-basicstudies%1BATR%40tv-basicstudies%1BStochasticRSI%40tv-basicstudies',
      'momentum': 'RSI%40tv-basicstudies%1BMACD%40tv-basicstudies%1BStochasticRSI%40tv-basicstudies',
      'trend': 'MASimple%40tv-basicstudies%1BMAExp%40tv-basicstudies%1BBB%40tv-basicstudies',
      'vol': 'Volume%40tv-basicstudies%1BATR%40tv-basicstudies%1BBB%40tv-basicstudies'
    };

    function setTradingViewPreset(preset) {
      currentTradingViewPreset = preset;
      ['tvPresetAll', 'tvPresetMomentum', 'tvPresetTrend', 'tvPresetVol'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
          el.style.background = '';
          el.style.color = '';
          el.style.borderColor = '';
        }
      });
      const activeBtnMap = {
        'all': 'tvPresetAll',
        'momentum': 'tvPresetMomentum',
        'trend': 'tvPresetTrend',
        'vol': 'tvPresetVol'
      };
      const activeEl = document.getElementById(activeBtnMap[preset]);
      if (activeEl) {
        activeEl.style.background = 'rgba(59,130,246,0.25)';
        activeEl.style.color = '#60a5fa';
        activeEl.style.borderColor = '#3b82f6';
      }
      const inputVal = document.getElementById('tickerInput')?.value.trim();
      const currentSym = currentChartSymbol || (activeResult ? activeResult.symbol : (inputVal || (currentMarket === 'US' ? 'NVDA' : 'RELIANCE.NS')));
      updateTradingViewChart(currentSym, preset);
    }

    function openFullTradingViewTab() {
      const inputVal = document.getElementById('tickerInput')?.value.trim();
      const sym = currentChartSymbol || (activeResult ? activeResult.symbol : (inputVal || (currentMarket === 'US' ? 'NVDA' : 'RELIANCE.NS')));
      const tvSym = toTradingViewSymbol(sym);
      window.open('https://www.tradingview.com/chart/?symbol=' + encodeURIComponent(tvSym), '_blank');
    }

    let currentChartTimeframe = 'D'; // TradingView interval: '1', '5', '15', '30', '60', 'D', 'W'
    let currentAnalysisTimeframe = '1d'; // '1m', '5m', '15m', '30m', '1h', '1d', '1w'

    function setChartTimeframe(analysisTf, tvInterval) {
      currentChartTimeframe = tvInterval;
      currentAnalysisTimeframe = analysisTf;

      ['1m', '5m', '15m', '30m', '1h', '1d', '1w'].forEach(t => {
        const el = document.getElementById('tfBtn_' + t);
        if (el) {
          el.style.background = '';
          el.style.color = '';
          el.style.borderColor = '';
        }
      });
      const activeEl = document.getElementById('tfBtn_' + analysisTf);
      if (activeEl) {
        activeEl.style.background = 'rgba(59,130,246,0.25)';
        activeEl.style.color = '#60a5fa';
        activeEl.style.borderColor = '#3b82f6';
      }

      const inputVal = document.getElementById('tickerInput')?.value.trim();
      const currentSym = currentChartSymbol || (activeResult ? activeResult.symbol : (inputVal || (currentMarket === 'US' ? 'NVDA' : 'RELIANCE.NS')));
      updateTradingViewChart(currentSym);
      analyzeSpecific(currentSym, analysisTf);
    }

    function updateTradingViewChart(symbol, preset = null) {
      if (!symbol) return;
      currentChartSymbol = symbol;
      if (preset) currentTradingViewPreset = preset;
      const tvSym = toTradingViewSymbol(symbol);
      const tfLabel = currentChartTimeframe === 'D' ? '1D' : (currentChartTimeframe === 'W' ? '1W' : (currentChartTimeframe === '60' ? '1H' : currentChartTimeframe + 'm'));
      const labelEl = document.getElementById('tvSymbolLabel');
      if (labelEl) labelEl.innerText = `${tvSym} • [${tfLabel}]`;
      
      const studies = TV_STUDIES[currentTradingViewPreset] || TV_STUDIES['all'];
      const iframe = document.getElementById('tradingview_iframe');
      const targetSrc = "https://s.tradingview.com/widgetembed/?symbol=" + encodeURIComponent(tvSym) +
        "&interval=" + encodeURIComponent(currentChartTimeframe) +
        "&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=131722&studies=" + studies +
        "&theme=dark&style=1&timezone=exchange&withdateranges=1&showpopupbutton=1&hide_top_toolbar=0";
      
      if (iframe && iframe.src !== targetSrc) {
        iframe.src = targetSrc;
      }
    }

    function updatePills() {
      const container = document.getElementById('quickPills');
      container.innerHTML = '';
      const list = currentMarket === 'US' ? US_PILLS : IN_PILLS;
      list.forEach(item => {
        const btn = document.createElement('button');
        btn.className = 'pill-btn' + (activeResult && activeResult.symbol === item ? ' active' : '');
        btn.innerText = item;
        btn.onclick = () => analyzeSpecific(item);
        container.appendChild(btn);
      });
    }

    function switchView(tabKey) {
      const tabUS = document.getElementById('tabUS');
      const tabIN = document.getElementById('tabIN');
      const tabAI = document.getElementById('tabAI');
      const tabPractice = document.getElementById('tabPractice');
      const marketView = document.getElementById('marketView');
      const aiTraderView = document.getElementById('aiTraderView');
      const practiceView = document.getElementById('practiceView');

      if (tabKey === 'Practice') {
        if (tabUS) tabUS.className = 'market-tab';
        if (tabIN) tabIN.className = 'market-tab';
        if (tabAI) tabAI.className = 'market-tab';
        if (tabPractice) tabPractice.className = 'market-tab active';
        if (marketView) marketView.style.display = 'none';
        if (aiTraderView) aiTraderView.style.display = 'none';
        if (practiceView) practiceView.style.display = 'block';
        fetchPracticePortfolio();
        fetchAIGuidance();
        updatePracticeChart();
        fetchPracticeLiveQuote(currentPracticeSymbol || 'NVDA');
        analyzeCurrentChartTiming();
      } else if (tabKey === 'AI') {
        if (tabUS) tabUS.className = 'market-tab';
        if (tabIN) tabIN.className = 'market-tab';
        if (tabPractice) tabPractice.className = 'market-tab';
        if (tabAI) tabAI.className = 'market-tab active';
        if (marketView) marketView.style.display = 'none';
        if (practiceView) practiceView.style.display = 'none';
        if (aiTraderView) aiTraderView.style.display = 'block';
        fetchPortfolio();
        fetchAIUniverseSymbols();
      } else {
        if (tabAI) tabAI.className = 'market-tab';
        if (tabPractice) tabPractice.className = 'market-tab';
        if (aiTraderView) aiTraderView.style.display = 'none';
        if (practiceView) practiceView.style.display = 'none';
        if (marketView) marketView.style.display = 'block';
        switchMarket(tabKey);
      }
    }

    function switchMarket(market) {
      currentMarket = market;
      const tabUS = document.getElementById('tabUS');
      const tabIN = document.getElementById('tabIN');
      const tabAI = document.getElementById('tabAI');
      const tabPractice = document.getElementById('tabPractice');
      if (tabUS) tabUS.className = 'market-tab' + (market === 'US' ? ' active' : '');
      if (tabIN) tabIN.className = 'market-tab' + (market === 'IN' ? ' active' : '');
      if (tabAI) tabAI.className = 'market-tab';
      if (tabPractice) tabPractice.className = 'market-tab';
      
      const marketView = document.getElementById('marketView');
      const aiTraderView = document.getElementById('aiTraderView');
      const practiceView = document.getElementById('practiceView');
      if (marketView) marketView.style.display = 'block';
      if (aiTraderView) aiTraderView.style.display = 'none';
      if (practiceView) practiceView.style.display = 'none';

      document.getElementById('tickerInput').placeholder = market === 'US' 
        ? 'Search any US stock (e.g. NVDA, AAPL, TSLA, MSFT, SPY)' 
        : 'Search any Indian stock (e.g. RELIANCE, TCS, HDFCBANK, INFY)';
      updatePills();
      fetchMarketOverview(false);
      const defaultTicker = market === 'US' ? 'NVDA' : 'RELIANCE.NS';
      analyzeSpecific(defaultTicker);
      scanMarketWatchlist(false);
    }

    async function analyzeSpecific(sym, tf = null) {
      if (!sym) return;
      currentChartSymbol = sym;
      const inputEl = document.getElementById('tickerInput');
      if (inputEl && inputEl.value !== sym) inputEl.value = sym;
      const activeTf = tf || currentAnalysisTimeframe || '1d';
      showToast(`Analyzing ${sym} [${activeTf.toUpperCase()}]...`);
      updateTradingViewChart(sym);

      try {
        const res = await fetch('/api/analyze?ticker=' + encodeURIComponent(sym) + '&timeframe=' + encodeURIComponent(activeTf));
        const data = await res.json();
        if (data && data.symbol) {
          renderActiveTicker(data);
        } else {
          showToast(`Live chart active for ${sym} (Quant metrics unavailable)`);
        }
      } catch (e) {
        showToast('Live chart active for ' + sym);
      }
    }

    async function searchTicker() {
      const val = document.getElementById('tickerInput').value.trim();
      if (!val) return;
      analyzeSpecific(val);
    }

    function renderActiveTicker(data) {
      activeResult = data;
      if (data && data.symbol) currentChartSymbol = data.symbol;
      const tfText = (data.timeframe || currentAnalysisTimeframe || '1D').toUpperCase();
      document.getElementById('updateTime').innerText = `Live • [${tfText}] • ` + new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' }) + ' IST';
      document.getElementById('heroSymbol').innerText = data.symbol;
      document.getElementById('heroName').innerText = data.name || data.symbol;

      const curr = data.currency || (data.symbol.includes('.NS') || data.symbol.includes('.BO') ? 'INR' : 'USD');
      const cSign = curr === 'USD' ? '$' : '₹';

      const price = data.current_price || 0;
      document.getElementById('heroPrice').innerText = cSign + price.toLocaleString('en-US', {minimumFractionDigits: 2});

      const upside = data.upside_pct || 0;
      const heroChange = document.getElementById('heroChange');
      heroChange.innerText = (upside >= 0 ? '+' : '') + upside.toFixed(1) + '% Target Upside';
      heroChange.className = 'price-change ' + (upside >= 0 ? 'positive' : 'negative');

      // Banner
      const banner = document.getElementById('signalBanner');
      const sig = data.signal || 'HOLD';
      banner.className = 'signal-banner ' + sig.toLowerCase().replace(' ', '-');
      document.getElementById('signalTitle').innerText = (sig.includes('BUY') ? '🟢 ' : (sig.includes('SELL') ? '🔴 ' : '🟡 ')) + sig;
      document.getElementById('signalConviction').innerText = (data.conviction || 'Moderate') + ' (Score ' + data.score + '/100)';
      document.getElementById('actionBadge').innerText = data.action_verb || sig;

      // Pillars
      const p = data.pillar_scores || {};
      document.getElementById('p1Val').innerText = p.expert_valuation || 0;
      document.getElementById('p1Fill').style.width = ((p.expert_valuation || 0) / 25 * 100) + '%';
      document.getElementById('p2Val').innerText = p.trend_regime || 0;
      document.getElementById('p2Fill').style.width = ((p.trend_regime || 0) / 25 * 100) + '%';
      document.getElementById('p3Val').innerText = p.momentum_oscillator || 0;
      document.getElementById('p3Fill').style.width = ((p.momentum_oscillator || 0) / 20 * 100) + '%';
      document.getElementById('p4Val').innerText = p.volatility_extremes || 0;
      document.getElementById('p4Fill').style.width = ((p.volatility_extremes || 0) / 15 * 100) + '%';
      document.getElementById('p5Val').innerText = p.volume_flow || 0;
      document.getElementById('p5Fill').style.width = ((p.volume_flow || 0) / 15 * 100) + '%';

      // Execution
      const ex = data.execution || {};
      document.getElementById('execEntry').innerText = ex.entry_zone || 'N/A';
      document.getElementById('execSL').innerText = cSign + (ex.stop_loss || 0).toLocaleString('en-US', {minimumFractionDigits: 2}) + ' (-' + (ex.sl_risk_pct || 0) + '%)';
      document.getElementById('execTP1').innerText = cSign + (ex.take_profit_1 || 0).toLocaleString('en-US', {minimumFractionDigits: 2}) + ' (+' + (ex.tp1_gain_pct || 0) + '%)';
      document.getElementById('execTP2').innerText = cSign + (ex.take_profit_2 || 0).toLocaleString('en-US', {minimumFractionDigits: 2}) + ' (+' + (ex.tp2_gain_pct || 0) + '%)';
      document.getElementById('execRR').innerText = '1 : ' + (ex.risk_reward_tp1 || 0);
      document.getElementById('execATR').innerText = cSign + (ex.atr || 0).toFixed(2);

      document.getElementById('rationaleText').innerText = data.rationale || '';

      // Actionable Buy & Sell Triggers
      const trigs = data.triggers || {};
      const buyT = trigs.buy || {};
      const sellT = trigs.sell || {};

      document.getElementById('triggerBuyAction').innerText = buyT.action || 'ACCUMULATE ON DIP';
      document.getElementById('triggerBuyInstruction').innerText = buyT.instruction || 'Wait for setup confirmation.';
      document.getElementById('triggerBuyRR').innerText = '1 : ' + (ex.risk_reward_tp1 || 0);
      document.getElementById('triggerBuyScore').innerText = (data.score || 0) + '/100';

      document.getElementById('triggerSellAction').innerText = sellT.action || 'HOLD';
      document.getElementById('triggerSellInstruction').innerText = sellT.instruction || 'Follow exit targets.';
      document.getElementById('triggerSellTP1').innerText = cSign + (ex.take_profit_1 || 0).toLocaleString('en-US', {minimumFractionDigits: 2});
      document.getElementById('triggerSellSL').innerText = cSign + (ex.stop_loss || 0).toLocaleString('en-US', {minimumFractionDigits: 2});

      // Gauge
      const score = data.score || 50;
      document.getElementById('gaugeScore').innerText = score;
      const gVerdict = document.getElementById('gaugeVerdict');
      gVerdict.innerText = sig;
      gVerdict.style.color = sig.includes('BUY') ? 'var(--green)' : (sig.includes('SELL') ? 'var(--red)' : 'var(--yellow)');

      const circle = document.getElementById('gaugeCircle');
      circle.style.borderColor = sig.includes('BUY') ? 'var(--green)' : (sig.includes('SELL') ? 'var(--red)' : 'var(--yellow)');

      const b = data.breakdown || {};
      const totalA = (b.strongBuy || 0) + (b.buy || 0) + (b.hold || 0) + (b.sell || 0) + (b.strongSell || 0);
      document.getElementById('analystSummary').innerText = totalA > 0 ? `${(b.strongBuy || 0) + (b.buy || 0)}/${totalA} Analysts Recommend Buy` : 'Wall St / Dalal St Consensus';

      // AI Chatbot Context
      document.getElementById('aiActiveSym').innerText = data.symbol;
      document.getElementById('aiActivePrice').innerText = `(${cSign}${price.toFixed(2)})`;

      updateTradingViewChart(data.symbol);
      updatePills();
    }

    async function scanMarketWatchlist(force = false) {
      const title = currentMarket === 'US' ? 'US S&P/NASDAQ Watchlist' : 'Indian Nifty Watchlist';
      document.getElementById('watchlistTableTitle').innerText = title;
      if (force) showToast('Scanning ' + title + ' in parallel...');

      try {
        const res = await fetch('/api/scan?market=' + currentMarket + (force ? '&force=1' : ''));
        const list = await res.json();
        const tbody = document.getElementById('watchlistBody');
        tbody.innerHTML = '';

        if (!list || list.length === 0) {
          tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 20px;">No tickers found.</td></tr>';
          return;
        }

        document.getElementById('watchlistCount').innerText = list.length + ' Tickers';

        list.forEach((item, index) => {
          const tr = document.createElement('tr');
          const sig = item.signal || 'HOLD';
          const sigClass = sig.toLowerCase().replace(' ', '-');
          const upside = item.upside_pct || 0;
          const rsi = item.technicals ? item.technicals.rsi_14 : null;
          const ema200 = item.technicals ? item.technicals.above_ema200 : null;
          const cSign = (item.currency === 'USD') ? '$' : '₹';

          tr.innerHTML = `
            <td style="font-weight: 600;">${item.symbol}</td>
            <td>${cSign}${(item.current_price || 0).toLocaleString('en-US', {minimumFractionDigits: 2})}</td>
            <td>${cSign}${(item.target_price || 0).toLocaleString('en-US', {minimumFractionDigits: 2})}</td>
            <td class="${upside >= 0 ? 'positive' : 'negative'}">${upside >= 0 ? '+' : ''}${upside.toFixed(1)}%</td>
            <td style="font-weight: 600;">${item.score}/100</td>
            <td>${rsi ? rsi.toFixed(1) : '-'}</td>
            <td>${ema200 === true ? 'Bull' : (ema200 === false ? 'Bear' : '-')}</td>
            <td><span class="status-pill ${sigClass}">${sig}</span></td>
            <td>${item.action_verb || sig}</td>
          `;
          tr.onclick = () => renderActiveTicker(item);
          tbody.appendChild(tr);
        });

        if (force) showToast(title + ' scan finished!');
      } catch (e) {
        showToast('Scan error: ' + e);
      }
    }

    function rescanActiveMarket() {
      scanMarketWatchlist(true);
    }

    async function triggerDiscordForActive() {
      if (!activeResult) return;
      showToast('Sending alert for ' + activeResult.symbol + ' to Discord...');
      const res = await fetch('/api/notify', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({symbol: activeResult.symbol})
      });
      const data = await res.json();
      if (data.discord) {
        showToast('Delivered to Discord channel successfully!');
      } else {
        showToast('Discord webhook returned failure or not configured.');
      }
    }

    async function sendPhonePush() {
      if (!activeResult) return;
      await fetch('/api/notify', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({symbol: activeResult.symbol, only_phone: true})
      });
      showToast('Notification sent to Android device status bar!');
    }

    /* AUDIO & WEB PUSH NOTIFICATIONS */
    function playNotificationSound() {
      try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) return;
        const ctx = new AudioCtx();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(587.33, ctx.currentTime);
        osc.frequency.setValueAtTime(880.00, ctx.currentTime + 0.12);
        gain.gain.setValueAtTime(0.2, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.4);
      } catch (e) {}
    }

    function requestNotificationPermission() {
      if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
      }
    }

    function triggerWebNotification(title, body) {
      playNotificationSound();
      if ('Notification' in window && Notification.permission === 'granted') {
        try {
          new Notification(title, {
            body: body,
            icon: 'https://img.icons8.com/color/512/bullish.png',
            tag: 'stock_signal'
          });
        } catch (e) {}
      }
    }

    /* MACRO MARKET REGIME FUNCTIONS */
    async function fetchMarketOverview(force = false) {
      if (force) showToast('Analyzing broad market regime...');
      try {
        const res = await fetch('/api/market-overview?market=' + currentMarket);
        const data = await res.json();
        if (data && data.regime) {
          renderMarketOverview(data);
          if (force) showToast('Market regime analysis updated!');
        }
      } catch (e) {
        console.error('Market overview error:', e);
      }
    }

    function renderMarketOverview(data) {
      document.getElementById('macroRegimeText').innerText = data.regime;
      const dot = document.getElementById('macroDot');
      dot.style.background = data.color || '#f59e0b';
      dot.style.boxShadow = '0 0 10px ' + (data.color || '#f59e0b');
      document.getElementById('macroGuidance').innerText = data.guidance;
      document.getElementById('macroUpdateTime').innerText = 'Live ' + data.updated_at;

      const container = document.getElementById('macroIndices');
      container.innerHTML = '';
      (data.indices || []).forEach(idx => {
        const chip = document.createElement('div');
        chip.className = 'macro-idx-chip';
        const cSign = idx.currency === 'USD' ? '$' : (idx.currency === 'INR' ? '₹' : '');
        const chg = idx.change_pct || 0;
        const chgClass = chg >= 0 ? 'positive' : 'negative';
        chip.innerHTML = `
          <div class="macro-idx-name">
            <span>${idx.name}</span>
            <span style="color:${idx.status === 'Bullish' ? 'var(--green)' : (idx.status === 'Bearish' ? 'var(--red)' : 'var(--yellow)')}; font-weight:600;">${idx.status}</span>
          </div>
          <div class="macro-idx-val">
            <span>${cSign}${(idx.price || 0).toLocaleString('en-US', {minimumFractionDigits: 2})}</span>
            <span class="${chgClass}" style="font-size:11px;">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span>
          </div>
        `;
        container.appendChild(chip);
      });
    }

    /* TRADE ALERT & DISPATCH FUNCTIONS */
    async function scanAndNotifyAll() {
      requestNotificationPermission();
      showToast('Scanning all ' + currentMarket + ' stocks for active Buy/Sell triggers...');
      try {
        const res = await fetch('/api/scan-and-notify', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({market: currentMarket})
        });
        const data = await res.json();
        const count = data.alerts_count || 0;
        if (count > 0) {
          showToast(`⚡ ${count} Buy/Sell alert(s) triggered & delivered to Phone/Discord!`);
          triggerWebNotification('🚨 Actionable Trade Alert', `${count} stock(s) triggered Buy or Sell conditions!`);
          fetchAlertsHistory();
        } else {
          showToast(`Scan complete. All tickers in consolidation/hold range.`);
        }
      } catch (e) {
        showToast('Scan error: ' + e);
      }
    }

    async function dispatchDirectTradeAlert(type) {
      if (!activeResult) return;
      requestNotificationPermission();
      showToast(`Dispatching ${type} alert for ${activeResult.symbol}...`);
      try {
        const res = await fetch('/api/trade-alert', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({symbol: activeResult.symbol, type: type})
        });
        const data = await res.json();
        if (data.success) {
          showToast(`✓ ${type} alert dispatched to Phone & Discord!`);
          triggerWebNotification(`🚨 [${type} ALERT] ${activeResult.symbol}`, data.alert ? data.alert.content : `${type} alert executed.`);
          fetchAlertsHistory();
        } else {
          showToast('Failed to dispatch alert.');
        }
      } catch (e) {
        showToast('Error: ' + e);
      }
    }

    let autoMonitorState = true;
    async function toggleAutoMonitor() {
      autoMonitorState = !autoMonitorState;
      const btn = document.getElementById('btnAutoMonitor');
      btn.innerText = '🔔 Auto-Alerts: ' + (autoMonitorState ? 'ON' : 'OFF');
      btn.style.color = autoMonitorState ? '#10b981' : '#94a3b8';
      await fetch('/api/auto-monitor', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled: autoMonitorState})
      });
      showToast('Auto-Monitor ' + (autoMonitorState ? 'Enabled (Every 3 mins)' : 'Disabled'));
    }

    function toggleAlertsDrawer() {
      const drawer = document.getElementById('alertsDrawer');
      if (drawer.style.display === 'flex') {
        drawer.style.display = 'none';
      } else {
        drawer.style.display = 'flex';
        fetchAlertsHistory();
      }
    }

    async function fetchAlertsHistory() {
      try {
        const res = await fetch('/api/alerts?limit=25');
        const list = await res.json();
        const container = document.getElementById('alertsList');
        const badge = document.getElementById('alertBellBadge');

        if (!list || list.length === 0) {
          container.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 20px; font-size: 12px;">No alerts recorded yet. Click "⚡ Scan & Send Buy/Sell Alerts" to scan the market.</div>';
          badge.style.display = 'none';
          return;
        }

        badge.innerText = list.length;
        badge.style.display = 'inline-block';
        container.innerHTML = '';

        list.forEach(a => {
          const item = document.createElement('div');
          item.className = 'alert-card-item ' + (a.type || 'buy').toLowerCase();
          item.innerHTML = `
            <div class="alert-item-top">
              <span style="color: ${a.type === 'BUY' ? 'var(--green)' : (a.type === 'SELL' ? 'var(--red)' : 'var(--yellow)')};">${a.title}</span>
              <span class="alert-item-time">${a.timestamp}</span>
            </div>
            <div style="font-size: 11px; color: #cbd5e1; line-height: 1.4;">${a.content}</div>
          `;
          container.appendChild(item);
        });
      } catch (e) {}
    }

    async function loadConfig() {
      try {
        const res = await fetch('/api/config');
        const data = await res.json();
        if (data.discord_webhook_url) {
          document.getElementById('webhookInput').value = data.discord_webhook_url;
        }
      } catch (e) {}
    }

    async function saveWebhook() {
      const url = document.getElementById('webhookInput').value.trim();
      const res = await fetch('/api/webhook', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({webhook_url: url})
      });
      const data = await res.json();
      if (data.success) {
        showToast('Discord webhook saved & test ping delivered!');
      } else {
        showToast('Webhook saved! (Check Discord URL if ping failed)');
      }
    }

    /* AI CHATBOT FUNCTIONS */
    function toggleChatDrawer() {
      const drawer = document.getElementById('aiChatDrawer');
      if (drawer.style.display === 'flex') {
        drawer.style.display = 'none';
      } else {
        drawer.style.display = 'flex';
        document.getElementById('aiChatInput').focus();
      }
    }

    function askQuickPrompt(text) {
      document.getElementById('aiChatInput').value = text;
      sendChatMessage();
    }

    function formatMarkdown(text) {
      let html = text
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>')
        .replace(/\\*(.*?)\\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code style="background:#222a3d;padding:2px 4px;border-radius:3px;font-family:var(--font-mono);">$1</code>')
        .replace(/\\n/g, '<br>');
      return html;
    }

    async function sendChatMessage() {
      const input = document.getElementById('aiChatInput');
      const msg = input.value.trim();
      if (!msg) return;

      input.value = '';
      const chatBox = document.getElementById('aiChatMessages');

      // Append User Bubble
      const userBubble = document.createElement('div');
      userBubble.className = 'chat-bubble user';
      userBubble.innerText = msg;
      chatBox.appendChild(userBubble);

      // Append Typing Placeholder
      const typingBubble = document.createElement('div');
      typingBubble.className = 'chat-bubble assistant';
      typingBubble.id = 'aiTyping';
      typingBubble.innerHTML = '<span style="color:#94a3b8;">Thinking & analyzing real-time confluence data...</span>';
      chatBox.appendChild(typingBubble);
      chatBox.scrollTop = chatBox.scrollHeight;

      chatHistory.push({role: 'user', content: msg});

      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            message: msg,
            symbol: (currentPracticeSymbol || (activeResult ? activeResult.symbol : 'NVDA')),
            active_symbol: (currentPracticeSymbol || (activeResult ? activeResult.symbol : 'NVDA')),
            timeframe: (currentPracticeTfLabel || '1m'),
            history: chatHistory
          })
        });
        const data = await res.json();
        typingBubble.remove();

        const replyBubble = document.createElement('div');
        replyBubble.className = 'chat-bubble assistant';
        replyBubble.innerHTML = formatMarkdown(data.reply || 'No response.');

        if (data.action_executed) {
          const act = data.action_executed;
          const actCard = document.createElement('div');
          actCard.className = 'chat-action-card';
          actCard.innerHTML = `
            <div class="action-header">⚡ SYSTEM ACTION EXECUTED: ${act.type || 'EXECUTE'}</div>
            <div style="font-family: var(--font-mono); font-size: 11px;">${act.summary || 'Command processed successfully.'}</div>
          `;
          replyBubble.appendChild(actCard);

          if (act.refresh_practice) fetchPracticePortfolio();
          if (act.refresh_portfolio) fetchPortfolio();
          if (act.refresh_universe) fetchAIUniverseSymbols();
          if (act.switch_symbol) {
            selectPracticeAsset(act.switch_symbol);
          }
        }

        chatBox.appendChild(replyBubble);
        chatBox.scrollTop = chatBox.scrollHeight;

        chatHistory.push({role: 'assistant', content: data.reply || ''});
      } catch (e) {
        typingBubble.innerHTML = '<span style="color:#ef4444;">Error getting response: ' + e + '</span>';
      }
    }

    /* ========================================================= */
    /* AI TRADING UNIVERSE & ASSET SELECTOR JAVASCRIPT LOGIC     */
    /* ========================================================= */
    let allAvailableUniverseSymbols = [];
    let currentSelectedUniverseSymbols = [];

    async function fetchAIUniverseSymbols() {
      try {
        const res = await fetch('/api/ai-trader/symbols');
        const data = await res.json();
        if (!data) return;

        allAvailableUniverseSymbols = data.all_available || [];
        currentSelectedUniverseSymbols = data.selected || [];
        renderAIUniverseChips();
      } catch (e) {
        console.error('Error fetching AI universe symbols:', e);
      }
    }

    function renderAIUniverseChips() {
      const grid = document.getElementById('aiUniverseChipsGrid');
      const badge = document.getElementById('aiUniverseCountBadge');
      if (badge) {
        badge.innerText = `${currentSelectedUniverseSymbols.length} Allowed Assets`;
        badge.style.color = currentSelectedUniverseSymbols.length > 0 ? '#10b981' : '#ef4444';
      }
      if (!grid) return;

      if (!allAvailableUniverseSymbols || allAvailableUniverseSymbols.length === 0) {
        grid.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; padding: 10px; text-align: center; grid-column: 1 / -1;">No symbols available.</div>';
        return;
      }

      grid.innerHTML = '';
      allAvailableUniverseSymbols.forEach(item => {
        const sym = item.symbol;
        const isSelected = currentSelectedUniverseSymbols.includes(sym);
        const chip = document.createElement('div');
        chip.className = 'universe-chip' + (isSelected ? ' selected' : '');
        chip.onclick = () => toggleAIUniverseSymbol(sym);

        const marketBadge = item.market === 'IN' ? '🇮🇳' : (item.market === 'US' ? '🇺🇸' : '🪙');
        chip.innerHTML = `
          <div>
            <span style="font-size: 10px; margin-right: 4px;">${marketBadge}</span>
            <span class="chip-symbol">${sym}</span>
          </div>
          <span class="chip-check">${isSelected ? '✓ ON' : '○ OFF'}</span>
        `;
        grid.appendChild(chip);
      });
    }

    function toggleAIUniverseSymbol(sym) {
      sym = sym.toUpperCase().trim();
      const idx = currentSelectedUniverseSymbols.indexOf(sym);
      if (idx >= 0) {
        currentSelectedUniverseSymbols.splice(idx, 1);
      } else {
        currentSelectedUniverseSymbols.push(sym);
      }
      renderAIUniverseChips();
    }

    function selectUniversePreset(preset) {
      if (preset === 'ALL') {
        currentSelectedUniverseSymbols = allAvailableUniverseSymbols.map(s => s.symbol);
      } else if (preset === 'NONE') {
        currentSelectedUniverseSymbols = [];
      } else if (preset === 'US') {
        currentSelectedUniverseSymbols = allAvailableUniverseSymbols.filter(s => s.market === 'US').map(s => s.symbol);
      } else if (preset === 'IN') {
        currentSelectedUniverseSymbols = allAvailableUniverseSymbols.filter(s => s.market === 'IN').map(s => s.symbol);
      } else if (preset === 'CRYPTO_COMMODITY') {
        currentSelectedUniverseSymbols = allAvailableUniverseSymbols.filter(s => s.market === 'CRYPTO_COMMODITY').map(s => s.symbol);
      }
      renderAIUniverseChips();
      saveAIUniverseSelection();
    }

    function addCustomToAIUniverse() {
      const input = document.getElementById('aiUniverseCustomInput');
      if (!input) return;
      const val = input.value.trim().toUpperCase();
      if (!val) {
        showToast('Please enter a ticker symbol to add.');
        return;
      }

      if (!currentSelectedUniverseSymbols.includes(val)) {
        currentSelectedUniverseSymbols.push(val);
      }
      if (!allAvailableUniverseSymbols.some(s => s.symbol === val)) {
        allAvailableUniverseSymbols.push({symbol: val, name: val, market: 'CUSTOM'});
      }
      input.value = '';
      renderAIUniverseChips();
      saveAIUniverseSelection();
    }

    async function saveAIUniverseSelection() {
      try {
        const res = await fetch('/api/ai-trader/symbols', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            symbols: currentSelectedUniverseSymbols,
            enabled: true
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(`✓ AI Universe Saved: ${data.count} assets active for autonomous trading`);
        } else {
          showToast('Failed to save universe selection.');
        }
      } catch (e) {
        showToast('Error saving universe: ' + e);
      }
    }

    /* VIRTUAL $1,000 PORTFOLIO FUNCTIONS */
    async function fetchPortfolio() {
      try {
        const res = await fetch('/api/portfolio');
        const data = await res.json();
        updatePortfolioUI(data);
      } catch (e) {
        console.error('Error fetching portfolio:', e);
      }
    }

    function updatePortfolioUI(data) {
      if (!data) return;
      
      const equityEl = document.getElementById('portTotalEquity');
      const returnEl = document.getElementById('portTotalReturn');
      const cashEl = document.getElementById('portCash');
      const realizedEl = document.getElementById('portRealizedPnl');
      const unrealizedEl = document.getElementById('portUnrealizedPnl');
      const closedTradesEl = document.getElementById('portClosedTrades');
      const openCountEl = document.getElementById('portOpenCount');
      const investedEl = document.getElementById('portInvestedVal');
      const maxPositionsEl = document.getElementById('portMaxPositions');

      // Accuracy Matrix elements
      const accWinRate = document.getElementById('accWinRate');
      const accWinLossRatio = document.getElementById('accWinLossRatio');
      const accProfitFactor = document.getElementById('accProfitFactor');
      const accGrossPnl = document.getElementById('accGrossPnl');
      const accTotalReturn = document.getElementById('accTotalReturn');
      const accEquitySub = document.getElementById('accEquitySub');

      const sign = (data.total_pnl || 0) >= 0 ? '+' : '';

      if (equityEl) equityEl.innerText = '$' + (data.total_equity || 1000).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
      if (returnEl) {
        returnEl.innerText = `${sign}$${(data.total_pnl || 0).toFixed(2)} (${sign}${(data.total_pnl_pct || 0).toFixed(2)}%) Overall`;
        returnEl.style.color = (data.total_pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)';
      }
      if (cashEl) cashEl.innerText = '$' + (data.cash || 1000).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
      
      if (realizedEl) {
        const rSign = (data.realized_pnl || 0) >= 0 ? '+' : '';
        realizedEl.innerText = `${rSign}$${(data.realized_pnl || 0).toFixed(2)}`;
        realizedEl.style.color = (data.realized_pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)';
      }
      if (closedTradesEl) closedTradesEl.innerText = `${data.total_trades || 0} Closed Trades (${data.wins || 0}W / ${data.losses || 0}L)`;

      if (unrealizedEl) {
        const uSign = (data.unrealized_pnl || 0) >= 0 ? '+' : '';
        unrealizedEl.innerText = `${uSign}$${(data.unrealized_pnl || 0).toFixed(2)}`;
        unrealizedEl.style.color = (data.unrealized_pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)';
      }
      if (openCountEl) openCountEl.innerText = `${data.open_positions_count || 0} Active Holdings`;
      if (investedEl) investedEl.innerText = '$' + (data.total_invested || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
      if (maxPositionsEl) maxPositionsEl.innerText = `${data.open_positions_count || 0} of 4 slots deployed ($250/ea)`;

      // Accuracy Matrix
      if (accWinRate) {
        accWinRate.innerText = `${(data.win_rate_pct || 0).toFixed(1)}%`;
        accWinRate.style.color = (data.win_rate_pct || 0) >= 50 ? 'var(--green)' : (data.total_trades === 0 ? 'inherit' : 'var(--red)');
      }
      if (accWinLossRatio) {
        accWinLossRatio.innerText = `${data.wins || 0} Wins / ${data.losses || 0} Losses (${data.total_trades || 0} Closed)`;
      }
      if (accProfitFactor) {
        accProfitFactor.innerText = (data.profit_factor || 1.0).toFixed(2);
      }
      if (accGrossPnl) {
        accGrossPnl.innerText = `Gross Win: $${(data.gross_profit || 0).toFixed(2)} | Loss: $${(data.gross_loss || 0).toFixed(2)}`;
      }
      if (accTotalReturn) {
        accTotalReturn.innerText = `${sign}${(data.total_pnl_pct || 0).toFixed(2)}%`;
        accTotalReturn.style.color = (data.total_pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)';
      }
      if (accEquitySub) {
        accEquitySub.innerText = `Equity: $${(data.total_equity || 1000).toFixed(2)} / $1,000.00`;
      }

      // Render Open Positions Table (11 columns)
      const openTbody = document.getElementById('portOpenTableBody');
      const openMeta = document.getElementById('portOpenPositionsMeta');
      if (openMeta) openMeta.innerText = `${data.positions ? data.positions.length : 0} active positions`;

      if (openTbody) {
        if (!data.positions || data.positions.length === 0) {
          openTbody.innerHTML = '<tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 22px;">No active positions. The AI autonomous engine buys when a stock achieves ≥ 70 Confluence Score.</td></tr>';
        } else {
          openTbody.innerHTML = '';
          data.positions.forEach(p => {
            const tr = document.createElement('tr');
            const pSign = p.unrealized_pnl >= 0 ? '+' : '';
            const colorClass = p.unrealized_pnl >= 0 ? 'color: var(--green);' : 'color: var(--red);';
            const currSymbol = p.currency === 'INR' ? '₹' : '$';
            const isINR = p.currency === 'INR' || (p.symbol && (p.symbol.endsWith('.NS') || p.symbol.endsWith('.BO')));

            const entryDisplay = isINR && p.entry_price_usd 
              ? `$${p.entry_price_usd.toFixed(2)} <span style="font-size: 10px; color: var(--text-muted);">(₹${p.entry_price.toFixed(2)})</span>` 
              : `${currSymbol}${p.entry_price.toFixed(2)}`;
            const currDisplay = isINR && p.current_price_usd 
              ? `$${p.current_price_usd.toFixed(2)} <span style="font-size: 10px; color: var(--text-muted);">(₹${p.current_price.toFixed(2)})</span>` 
              : `${currSymbol}${p.current_price.toFixed(2)}`;

            tr.innerHTML = `
              <td><strong style="color: #60a5fa; cursor: pointer;" onclick="loadSingleStock('${p.symbol}')" title="Click to open chart and 5-pillar breakdown">${p.symbol}</strong></td>
              <td style="font-family: var(--font-mono);">${p.shares}</td>
              <td style="font-family: var(--font-mono);">${entryDisplay}</td>
              <td style="font-family: var(--font-mono);">${currDisplay}</td>
              <td style="font-family: var(--font-mono);">$${p.invested.toFixed(2)}</td>
              <td style="font-family: var(--font-mono); font-weight: 600;">$${p.current_value.toFixed(2)}</td>
              <td style="font-family: var(--font-mono); font-weight: 700; ${colorClass}">${pSign}$${p.unrealized_pnl.toFixed(2)} (${pSign}${p.unrealized_pct.toFixed(2)}%)</td>
              <td style="font-family: var(--font-mono); color: var(--red);">${p.stop_loss ? currSymbol + p.stop_loss.toFixed(2) : '-'}</td>
              <td style="font-family: var(--font-mono); color: var(--green);">${p.take_profit_1 ? currSymbol + p.take_profit_1.toFixed(2) : '-'}</td>
              <td>
                <span style="font-weight: 700; color: #60a5fa;">${p.score || 70}/100</span>
                <span style="font-size: 10px; color: #10b981; font-weight: 600;">(${p.conviction || 'HIGH'})</span>
                ${p.ai_rationale ? `<div style="font-size: 10px; color: #94a3b8; max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${p.ai_rationale}">${p.ai_rationale}</div>` : ''}
              </td>
              <td>
                <button onclick="liquidatePosition('${p.symbol}', ${p.current_price})" style="padding: 3px 8px; font-size: 11px; background: rgba(239,68,68,0.15); color: var(--red); border-color: rgba(239,68,68,0.3);">
                  Liquidate
                </button>
              </td>
            `;
            openTbody.appendChild(tr);
          });
        }
      }

      // Render Dedicated AI Trade Records Audit Table (11 columns)
      const histTbody = document.getElementById('portHistoryTableBody');
      const histMeta = document.getElementById('portTradeHistoryMeta');
      if (histMeta) histMeta.innerText = `${data.trade_history ? data.trade_history.length : 0} recorded trades`;

      if (histTbody) {
        if (!data.trade_history || data.trade_history.length === 0) {
          histTbody.innerHTML = '<tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 22px;">No trade records yet. The autonomous engine records all executions here as positions close via Stop-Loss or Take-Profit.</td></tr>';
        } else {
          histTbody.innerHTML = '';
          data.trade_history.forEach(t => {
            const tr = document.createElement('tr');
            const tSign = t.pnl_amount >= 0 ? '+' : '';
            const colorClass = t.pnl_amount >= 0 ? 'color: var(--green);' : 'color: var(--red);';
            const currSymbol = t.currency === 'INR' ? '₹' : '$';
            const isINR = t.currency === 'INR' || (t.symbol && (t.symbol.endsWith('.NS') || t.symbol.endsWith('.BO')));
            const resultBadge = t.result === 'WIN' 
              ? '<span class="status-pill strong-buy" style="font-size: 11px; padding: 2px 7px;">🎯 WIN</span>' 
              : '<span class="status-pill sell" style="font-size: 11px; padding: 2px 7px;">🛑 LOSS</span>';

            const entryDisplay = isINR && t.entry_price_usd 
              ? `$${t.entry_price_usd.toFixed(2)} <span style="font-size: 10px; color: var(--text-muted);">(₹${t.entry_price.toFixed(2)})</span>` 
              : `${currSymbol}${t.entry_price.toFixed(2)}`;
            const exitDisplay = isINR && t.exit_price_usd 
              ? `$${t.exit_price_usd.toFixed(2)} <span style="font-size: 10px; color: var(--text-muted);">(₹${t.exit_price.toFixed(2)})</span>` 
              : `${currSymbol}${t.exit_price.toFixed(2)}`;

            tr.innerHTML = `
              <td><strong style="color: #fff;">${t.symbol}</strong></td>
              <td><span class="action-chip buy">BUY</span> ➔ <span class="action-chip sell">SELL</span></td>
              <td style="font-family: var(--font-mono);"><span style="color: #60a5fa; font-weight: 700;">${t.score || '-'}</span><small style="color: #64748b;">/100</small></td>
              <td style="font-family: var(--font-mono);">${entryDisplay}</td>
              <td style="font-family: var(--font-mono);">${exitDisplay}</td>
              <td style="font-family: var(--font-mono);">$${t.invested.toFixed(2)}</td>
              <td style="font-family: var(--font-mono);">$${t.proceeds.toFixed(2)}</td>
              <td style="font-family: var(--font-mono); font-weight: 700; ${colorClass}">${tSign}$${t.pnl_amount.toFixed(2)} (${tSign}${t.pnl_pct.toFixed(2)}%)</td>
              <td>${resultBadge}</td>
              <td style="font-size: 11px; color: #cbd5e1;">
                <strong>${t.exit_reason || 'TRIGGER'}</strong>
                ${t.exit_rationale ? `<div style="font-size: 10px; color: #94a3b8; max-width: 220px; line-height: 1.3; margin-top: 2px;">${t.exit_rationale}</div>` : ''}
              </td>
              <td style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono);">${t.exit_time || '-'}</td>
            `;
            histTbody.appendChild(tr);
          });
        }
      }
    }

    let autoTradeRunning = false;
    async function triggerAutoTradeNow() {
      if (autoTradeRunning) return;
      autoTradeRunning = true;
      showToast('🤖 AI scanning live market to execute autonomous buy/sell decisions...');
      try {
        const res = await fetch('/api/portfolio/auto-trade-now', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({market: currentMarket})
        });
        const data = await res.json();
        if (data.success) {
          const buys = data.bought ? data.bought.length : 0;
          const sells = data.sold ? data.sold.length : 0;
          if (buys > 0 || sells > 0) {
            showToast(`✓ AI executed ${buys} buys and ${sells} sells!`);
          } else {
            showToast(`✓ AI scan completed: Evaluated ${data.analyzed_count || 0} setups. No criteria breached.`);
          }
          if (data.portfolio) {
            updatePortfolioUI(data.portfolio);
          } else {
            fetchPortfolio();
          }
        } else {
          showToast(`AI execution error: ${data.error || 'Failed'}`);
        }
      } catch (e) {
        showToast('Error during auto-trade: ' + e);
      } finally {
        autoTradeRunning = false;
      }
    }

    let isAutoTradeEngineActive = true;
    async function toggleAutoTradingMode() {
      isAutoTradeEngineActive = !isAutoTradeEngineActive;
      const toggleBtn = document.getElementById('aiToggleBtn');
      const badge = document.getElementById('aiAutoBadge');
      const tabPill = document.getElementById('aiTabLivePill');
      const dot = document.getElementById('aiEngineDot');

      if (isAutoTradeEngineActive) {
        if (toggleBtn) toggleBtn.innerText = '⏸️ Pause Engine';
        if (badge) {
          badge.innerText = 'AUTONOMOUS: ACTIVE';
          badge.style.background = 'rgba(16, 185, 129, 0.2)';
          badge.style.color = '#10b981';
          badge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
        }
        if (tabPill) {
          tabPill.innerText = 'AUTO: ON';
          tabPill.style.background = 'rgba(16,185,129,0.2)';
          tabPill.style.color = '#10b981';
        }
        if (dot) dot.style.background = '#10b981';
      } else {
        if (toggleBtn) toggleBtn.innerText = '▶️ Resume Engine';
        if (badge) {
          badge.innerText = 'AUTONOMOUS: PAUSED';
          badge.style.background = 'rgba(239, 68, 68, 0.2)';
          badge.style.color = '#ef4444';
          badge.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        }
        if (tabPill) {
          tabPill.innerText = 'AUTO: OFF';
          tabPill.style.background = 'rgba(239,68,68,0.2)';
          tabPill.style.color = '#ef4444';
        }
        if (dot) dot.style.background = '#ef4444';
      }

      try {
        await fetch('/api/portfolio/toggle-auto-trade', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({enabled: isAutoTradeEngineActive})
        });
        showToast('Autonomous AI Engine ' + (isAutoTradeEngineActive ? 'Resumed (Scanning every 3m)' : 'Paused'));
      } catch (e) {
        showToast('Error syncing engine state: ' + e);
      }
    }

    function loadSingleStock(sym) {
      switchView(sym.includes('.NS') || sym.includes('.BO') ? 'IN' : 'US');
      analyzeSpecific(sym);
    }

    async function autoInvestTopPicks() {
      showToast('🤖 AI scanning top confluence setups and deploying $1,000 credits...');
      try {
        const res = await fetch('/api/portfolio/auto-invest', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({market: currentMarket})
        });
        const data = await res.json();
        if (data.executed && data.executed.length > 0) {
          const syms = data.executed.map(e => e.symbol).join(', ');
          showToast(`✓ Auto-invested in ${data.executed.length} setups: ${syms}`);
        } else {
          showToast('No new BUY confluence setups found or all slots full.');
        }
        if (data.summary) {
          updatePortfolioUI(data.summary);
        } else {
          fetchPortfolio();
        }
      } catch (e) {
        showToast('Error auto-investing: ' + e);
      }
    }

    async function buyActiveStockInPortfolio() {
      if (!activeResult) return;
      showToast(`Buying $250 of ${activeResult.symbol} with virtual credits...`);
      try {
        const ex = activeResult.execution || {};
        const res = await fetch('/api/portfolio/buy', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            symbol: activeResult.symbol,
            price: activeResult.current_price,
            allocation: 250.0,
            stop_loss: ex.stop_loss || 0,
            take_profit_1: ex.take_profit_1 || 0,
            take_profit_2: ex.take_profit_2 || 0,
            score: activeResult.score || 50,
            signal: activeResult.signal || 'BUY',
            currency: activeResult.currency || 'USD'
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(`✓ Bought ${data.shares} shares of ${data.symbol} for $${data.invested}!`);
          fetchPortfolio();
        } else {
          showToast(`Buy failed: ${data.error || 'Unknown error'}`);
        }
      } catch (e) {
        showToast('Error: ' + e);
      }
    }

    async function liquidatePosition(symbol, price) {
      if (!confirm(`Liquidate active position for ${symbol} at $${price}?`)) return;
      try {
        const res = await fetch('/api/portfolio/sell', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({symbol: symbol, price: price, reason: 'MANUAL_LIQUIDATE'})
        });
        const data = await res.json();
        if (data.success) {
          const sign = data.pnl >= 0 ? '+' : '';
          showToast(`✓ Sold ${symbol}: Realized P&L ${sign}$${data.pnl} (${sign}${data.pnl_pct}%)`);
          fetchPortfolio();
        } else {
          showToast(`Sell failed: ${data.error || 'Unknown error'}`);
        }
      } catch (e) {
        showToast('Error liquidating: ' + e);
      }
    }

    async function resetPortfolioCredits() {
      if (!confirm('Reset virtual portfolio back to $1,000.00 virtual credits?')) return;
      try {
        const res = await fetch('/api/portfolio/reset', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'}
        });
        const data = await res.json();
        updatePortfolioUI(data);
        showToast('✓ Virtual portfolio reset to $1,000.00 cash.');
      } catch (e) {
        showToast('Error resetting: ' + e);
      }
    }

    /* AI P&L REPORT MODAL FUNCTIONS */
    function openAIReportModal() {
      const modal = document.getElementById('reportModal');
      modal.style.display = 'flex';
      generateAIReport();
    }

    function closeAIReportModal() {
      const modal = document.getElementById('reportModal');
      modal.style.display = 'none';
    }

    async function generateAIReport() {
      const bodyEl = document.getElementById('reportBody');
      const badgeEl = document.getElementById('reportModelBadge');
      const timeEl = document.getElementById('reportTimestamp');

      bodyEl.innerHTML = `
        <div style="text-align: center; padding: 40px; color: var(--text-muted);">
          <div style="font-size: 28px; margin-bottom: 12px; animation: pulse 1.5s infinite;">⚡</div>
          <div style="font-size: 14px; font-weight: 600; color: #e2e8f0; margin-bottom: 6px;">Chief Quantitative Risk Officer Audit in Progress</div>
          <div style="font-size: 12px;">Auditing $1,000 forward testing data, win rate, risk-reward skew, and probability validity...</div>
        </div>
      `;

      try {
        const res = await fetch('/api/portfolio/report', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'}
        });
        const data = await res.json();
        if (badgeEl) badgeEl.innerText = data.model || 'Nemotron-120B / Free';
        if (timeEl) timeEl.innerText = 'Generated: ' + (data.generated_at || new Date().toISOString());

        if (data.report) {
          bodyEl.innerHTML = formatMarkdown(data.report);
        } else {
          bodyEl.innerHTML = '<div style="color: var(--red); padding: 20px;">Failed to generate AI report.</div>';
        }
      } catch (e) {
        bodyEl.innerHTML = `<div style="color: var(--red); padding: 20px;">Error generating report: ${e}</div>`;
      }
    }

    /* 24/7 LIVE AI SIGNALS FEED FUNCTIONS */
    let currentSignalsFeed = [];
    let currentSignalsFilter = 'ALL';

    function renderSignalsFeed(signals) {
      const tbody = document.getElementById('signalsFeedBody');
      const countEl = document.getElementById('signalsFeedCount');
      if (countEl) countEl.innerText = `${signals ? signals.length : 0} signals logged`;

      if (!tbody) return;
      if (!signals || signals.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 22px;">No signals matching filter. Triggers with exact timestamps will stream here automatically.</td></tr>';
        return;
      }

      tbody.innerHTML = '';
      signals.forEach(s => {
        const tr = document.createElement('tr');
        const isBuy = s.action === 'BUY';
        const actionBadge = isBuy
          ? '<span class="status-pill strong-buy" style="font-size: 11px; padding: 2px 7px;">🟢 BUY</span>'
          : '<span class="status-pill sell" style="font-size: 11px; padding: 2px 7px;">🔴 SELL</span>';
        const currSign = s.currency === 'INR' ? '₹' : '$';
        const priceDisplay = s.price ? `${currSign}${s.price.toFixed(2)}` : '-';

        tr.innerHTML = `
          <td style="font-family: var(--font-mono); font-size: 11px; color: #94a3b8; white-space: nowrap;">${s.timestamp || '-'}</td>
          <td><strong style="color: #60a5fa; cursor: pointer;" onclick="loadSingleStock('${s.symbol}')">${s.symbol}</strong></td>
          <td>${actionBadge}</td>
          <td style="font-family: var(--font-mono); font-size: 11px; color: ${isBuy ? '#10b981' : '#f87171'};">${s.signal || s.action}</td>
          <td style="font-family: var(--font-mono); font-weight: 600;">${priceDisplay}</td>
          <td style="font-family: var(--font-mono);"><span style="color: #60a5fa; font-weight: 700;">${s.score || '-'}</span><small style="color: #64748b;">/100</small></td>
          <td style="font-size: 11px; color: #cbd5e1; max-width: 280px; line-height: 1.4;">${s.instruction || '-'}</td>
          <td>
            ${isBuy 
              ? `<button class="primary" onclick="quickBuyGuidance('${s.symbol}', ${s.price}, ${s.score || 70}, '${s.signal || 'BUY'}')" style="padding: 2px 8px; font-size: 11px; background: #10b981; border-color: #10b981; cursor: pointer;">Test in Practice</button>`
              : `<button onclick="loadSingleStock('${s.symbol}')" style="padding: 2px 8px; font-size: 11px; cursor: pointer;">Inspect Chart</button>`
            }
          </td>
        `;
        tbody.appendChild(tr);
      });
    }

    function filterSignalsFeed(filter) {
      currentSignalsFilter = filter;
      ['sigFilterAll', 'sigFilterBuy', 'sigFilterSell'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
          el.style.background = '';
          el.style.color = '';
          el.style.borderColor = '';
        }
      });
      const activeEl = document.getElementById(filter === 'ALL' ? 'sigFilterAll' : (filter === 'BUY' ? 'sigFilterBuy' : 'sigFilterSell'));
      if (activeEl) {
        activeEl.style.background = filter === 'BUY' ? 'rgba(16,185,129,0.25)' : (filter === 'SELL' ? 'rgba(239,68,68,0.25)' : 'rgba(59,130,246,0.25)');
        activeEl.style.color = filter === 'BUY' ? '#10b981' : (filter === 'SELL' ? '#f87171' : '#60a5fa');
        activeEl.style.borderColor = filter === 'BUY' ? '#10b981' : (filter === 'SELL' ? '#ef4444' : '#3b82f6');
      }

      let filtered = currentSignalsFeed;
      if (filter === 'BUY') {
        filtered = currentSignalsFeed.filter(s => s.action === 'BUY');
      } else if (filter === 'SELL') {
        filtered = currentSignalsFeed.filter(s => s.action === 'SELL');
      }
      renderSignalsFeed(filtered);
    }

    async function fetchSignalsFeed() {
      try {
        const res = await fetch('/api/signals-feed');
        const signals = await res.json();
        currentSignalsFeed = signals || [];
        filterSignalsFeed(currentSignalsFilter);
      } catch (e) {
        console.error('Error fetching signals feed:', e);
      }
    }

    /* PRACTICE SANDBOX & AI GUIDANCE FUNCTIONS */
    async function fetchAIGuidance() {
      const container = document.getElementById('aiGuidanceGrid');
      if (container) container.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; padding: 15px; text-align: center; grid-column: 1 / -1;">Evaluating live high-confluence setups...</div>';
      try {
        const res = await fetch('/api/guidance');
        const picks = await res.json();
        if (!container) return;

        if (!picks || picks.length === 0) {
          container.innerHTML = '<div style="color: var(--text-muted); font-size: 12px; padding: 15px; text-align: center; grid-column: 1 / -1;">No high-confluence (Score ≥ 60) stocks identified right now. Check back as market scans.</div>';
          return;
        }

        container.innerHTML = '';
        picks.forEach(p => {
          const card = document.createElement('div');
          card.style.cssText = 'background: var(--surface-elevated); border: 1px solid var(--border); border-radius: 6px; padding: 12px; display: flex; flex-direction: column; justify-content: space-between;';
          const isINR = p.currency === 'INR' || (p.symbol && p.symbol.endsWith('.NS'));
          const currSign = isINR ? '₹' : '$';
          const ex = p.execution || {};
          const sl = ex.stop_loss ? `${currSign}${ex.stop_loss.toFixed(2)}` : 'Auto 5%';
          const tp1 = ex.take_profit_1 ? `${currSign}${ex.take_profit_1.toFixed(2)}` : 'Auto 5%';
          const entryZone = ex.entry_zone || `${currSign}${p.current_price.toFixed(2)}`;

          card.innerHTML = `
            <div>
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
                <div>
                  <strong style="font-size: 15px; color: #fff; cursor: pointer;" onclick="loadSingleStock('${p.symbol}')">${p.symbol}</strong>
                  <div style="font-size: 11px; color: var(--text-muted);">${p.name || p.symbol}</div>
                </div>
                <div style="text-align: right;">
                  <span style="font-size: 14px; font-weight: 700; color: #60a5fa; font-family: var(--font-mono);">${p.score}/100</span>
                  <div style="font-size: 10px; color: #10b981; font-weight: 600;">${p.conviction || 'BUY'}</div>
                </div>
              </div>
              <div style="display: flex; justify-content: space-between; font-size: 12px; margin: 8px 0; padding: 6px 8px; background: var(--surface); border-radius: 4px;">
                <span>Price: <strong>${currSign}${p.current_price.toFixed(2)}</strong></span>
                <span style="color: var(--green);">Upside: +${(p.upside_pct || 0).toFixed(1)}%</span>
              </div>
              <div style="font-size: 11px; color: #cbd5e1; margin-bottom: 8px;">
                <div>🎯 <strong>Entry:</strong> ${entryZone}</div>
                <div style="display: flex; gap: 10px; margin-top: 3px;">
                  <span style="color: var(--red);">🛑 SL: ${sl}</span>
                  <span style="color: var(--green);">🎯 TP1: ${tp1}</span>
                </div>
              </div>
              <div style="font-size: 10px; color: var(--text-muted); line-height: 1.3; margin-bottom: 10px; max-height: 40px; overflow: hidden;">
                ${p.rationale || 'High confluence alignment across trend regime, momentum RSI, and institutional valuation.'}
              </div>
            </div>
            <button class="primary" onclick="quickBuyGuidance('${p.symbol}', ${p.current_price}, ${p.score}, '${p.signal || 'BUY'}', ${ex.stop_loss || 0}, ${ex.take_profit_1 || 0})" style="width: 100%; padding: 6px; font-size: 12px; background: #6366f1; border-color: #6366f1;">
              ⚡ Follow AI: Buy $250
            </button>
          `;
          container.appendChild(card);
        });
      } catch (e) {
        console.error('Error fetching AI guidance:', e);
      }
    }

    async function quickBuyGuidance(symbol, price, score, signal, sl = 0, tp1 = 0) {
      showToast(`Executing Practice Buy for ${symbol}...`);
      try {
        const res = await fetch('/api/practice/buy', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            symbol: symbol,
            price: price,
            allocation: 250.0,
            stop_loss: sl,
            take_profit_1: tp1,
            score: score || 70,
            signal: signal || 'BUY',
            currency: symbol.endsWith('.NS') || symbol.endsWith('.BO') ? 'INR' : 'USD'
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(`✓ Practice Order Filled: ${data.shares} shares of ${data.symbol} for $${data.invested}!`);
          switchView('Practice');
          fetchPracticePortfolio();
        } else {
          showToast(`Practice Buy Failed: ${data.error || 'Error'}`);
        }
      } catch (e) {
        showToast('Error: ' + e);
      }
    }

    /* ========================================================= */
    /* BINOMO-STYLE PRACTICE SANDBOX JAVASCRIPT LOGIC           */
    /* ========================================================= */
    let currentPracticeSymbol = 'NVDA';
    let currentPracticeTf = '1';
    let currentPracticeTfLabel = '1m';

    function selectPracticeAsset(sym) {
      if (!sym) return;
      sym = sym.toUpperCase().trim();
      currentPracticeSymbol = sym;

      const symInput = document.getElementById('pracInputSymbol');
      if (symInput) symInput.value = sym;

      const titleEl = document.getElementById('binomoAssetTitle');
      if (titleEl) titleEl.innerText = sym;

      // Update active asset chip in the top ribbon
      const chips = document.querySelectorAll('.binomo-asset-chip');
      chips.forEach(chip => {
        if (chip.getAttribute('data-sym') === sym) {
          chip.classList.add('active');
        } else {
          chip.classList.remove('active');
        }
      });

      updatePracticeChart(sym);
      fetchPracticeLiveQuote(sym);
      analyzeCurrentChartTiming(sym);
    }

    function quickFillPracticeTicker(sym) {
      selectPracticeAsset(sym);
    }

    function quickFillPracticeAmount(amt) {
      setPracticeAmountPreset(amt);
    }

    function updatePracticeChart(sym) {
      sym = sym || currentPracticeSymbol || 'NVDA';
      const tvSym = toTradingViewSymbol(sym);
      const labelEl = document.getElementById('pracTvSymbolLabel');
      if (labelEl) {
        labelEl.innerText = `${tvSym} • [${currentPracticeTfLabel}]`;
      }
      const iframe = document.getElementById('practice_tv_iframe');
      if (iframe) {
        const newSrc = `https://s.tradingview.com/widgetembed/?frameElementId=practice_tv_iframe&symbol=${encodeURIComponent(tvSym)}&interval=${currentPracticeTf}&hidesidetoolbar=1&symboledit=1&saveimage=0&toolbarbg=0a0e17&studies=[]&theme=dark&style=1&timezone=Asia%2FKolkata&studies_overrides={}&overrides={}&enabled_features=[]&disabled_features=[]&locale=en&utm_source=localhost`;
        if (iframe.src !== newSrc) {
          iframe.src = newSrc;
        }
      }
    }

    function setPracticeTimeframe(tfLabel, tfCode) {
      currentPracticeTfLabel = tfLabel;
      currentPracticeTf = tfCode;

      // Update chart header buttons
      const tfButtons = document.querySelectorAll('.binomo-tf-bar .tf-btn');
      tfButtons.forEach(btn => btn.classList.remove('active'));
      const activeBtn = document.getElementById(`pracTfBtn_${tfLabel}`);
      if (activeBtn) activeBtn.classList.add('active');

      // Update dock buttons
      const dockTfButtons = document.querySelectorAll('.binomo-time-presets .binomo-time-btn');
      dockTfButtons.forEach(btn => btn.classList.remove('active'));
      const activeDockBtn = document.getElementById(`btnExp_${tfLabel}`);
      if (activeDockBtn) activeDockBtn.classList.add('active');

      updatePracticeChart(currentPracticeSymbol);
      fetchPracticeLiveQuote(currentPracticeSymbol);
      analyzeCurrentChartTiming(currentPracticeSymbol);
    }

    async function fetchPracticeLiveQuote(sym) {
      sym = sym || currentPracticeSymbol || 'NVDA';
      try {
        const res = await fetch(`/api/analyze?symbol=${encodeURIComponent(sym)}`);
        const data = await res.json();
        if (!data || data.error) return;

        const isINR = data.currency === 'INR' || sym.endsWith('.NS') || sym.endsWith('.BO');
        const currSign = isINR ? '₹' : '$';
        const price = data.current_price || 0;

        const livePriceEl = document.getElementById('binomoLivePrice');
        if (livePriceEl && price > 0) {
          livePriceEl.innerText = `${currSign}${price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
        }

        const priceChangeEl = document.getElementById('binomoPriceChange');
        if (priceChangeEl) {
          const upside = data.upside_pct || 0;
          const uSign = upside >= 0 ? '+' : '';
          priceChangeEl.innerText = `${uSign}${upside.toFixed(1)}% Target Upside`;
          priceChangeEl.className = 'price-change ' + (upside >= 0 ? 'positive' : 'negative');
        }

        const badgeEl = document.getElementById('binomoSignalBadge');
        if (badgeEl) {
          const sig = data.signal || 'HOLD';
          const score = data.score || 50;
          let badgeColor = '#60a5fa';
          let badgeBg = 'rgba(96,165,250,0.15)';
          if (sig.includes('BUY')) {
            badgeColor = '#10b981';
            badgeBg = 'rgba(16,185,129,0.15)';
          } else if (sig.includes('SELL')) {
            badgeColor = '#ef4444';
            badgeBg = 'rgba(239,68,68,0.15)';
          }
          badgeEl.style.borderColor = badgeColor;
          badgeEl.style.background = badgeBg;
          badgeEl.style.color = badgeColor;
          badgeEl.innerText = `AI: ${sig} (${score}/100)`;
        }

        const slInput = document.getElementById('pracInputSL');
        const tpInput = document.getElementById('pracInputTP');
        if (price > 0) {
          const ex = data.execution || {};
          const slVal = ex.stop_loss ? ex.stop_loss.toFixed(2) : (price * 0.95).toFixed(2);
          const tpVal = ex.take_profit_1 ? ex.take_profit_1.toFixed(2) : (price * 1.05).toFixed(2);
          if (slInput) slInput.placeholder = `${currSign}${slVal} (-5%)`;
          if (tpInput) tpInput.placeholder = `${currSign}${tpVal} (+5%)`;
        }

        updateBinomoPayout();
      } catch (e) {
        console.error('Error fetching live quote for ' + sym, e);
      }
    }

    let currentTimingData = null;
    let timingCountdownInterval = null;
    let timingSecondsRemaining = 60;

    async function analyzeCurrentChartTiming(force = false) {
      const sym = currentPracticeSymbol || 'NVDA';
      const tf = currentPracticeTfLabel || '1m';
      try {
        const res = await fetch(`/api/chart-timing?symbol=${encodeURIComponent(sym)}&timeframe=${encodeURIComponent(tf)}`);
        const data = await res.json();
        if (!data || data.error) return;

        currentTimingData = data;
        const t = data.timing || {};
        const ex = data.execution || {};

        // 1. Action Badge & Styles
        const badge = document.getElementById('timingActionBadge');
        const radar = document.getElementById('pracTimingRadar');
        const dockNotice = document.getElementById('dockTimingNotice');
        const dockHeader = document.getElementById('dockTimingHeader');
        const dockSub = document.getElementById('dockTimingSub');

        const act = (t.action || 'WAIT').toUpperCase();
        let badgeClass = 'timing-action-badge';
        let accentColor = '#60a5fa';

        if (act === 'BUY') {
          badgeClass = 'timing-action-badge';
          accentColor = '#10b981';
          if (dockHeader) dockHeader.innerText = '▲ OPTIMAL BUY WINDOW ACTIVE';
        } else if (act === 'SELL') {
          badgeClass = 'timing-action-badge sell';
          accentColor = '#ef4444';
          if (dockHeader) dockHeader.innerText = '▼ OPTIMAL SELL WINDOW ACTIVE';
        } else {
          badgeClass = 'timing-action-badge wait';
          accentColor = '#60a5fa';
          if (dockHeader) dockHeader.innerText = '⏳ MONITORING CONSOLIDATION';
        }

        if (badge) {
          badge.className = badgeClass;
          badge.innerText = t.action_label || `${act} WINDOW`;
        }
        if (radar) {
          radar.style.borderColor = accentColor;
        }
        if (dockNotice) {
          dockNotice.style.borderColor = accentColor;
          dockNotice.style.background = `${accentColor}18`;
        }

        // 2. Score & Type Pills
        const scorePill = document.getElementById('timingScorePill');
        if (scorePill) scorePill.innerText = `${data.score || 50}/100 Score`;

        const typePill = document.getElementById('timingTypePill');
        if (typePill) typePill.innerText = t.trigger_type ? t.trigger_type.replace(/_/g, ' ') : 'CONFLUENCE';

        // 3. Reason Text
        const reasonEl = document.getElementById('timingReasonText');
        if (reasonEl) {
          reasonEl.innerText = t.trigger_reason || t.instruction || 'Analyzing confluence signals across moving averages...';
        }

        // 4. Timestamps
        const trigEl = document.getElementById('timingTriggerTime');
        if (trigEl) trigEl.innerText = t.trigger_time_short || '--:--:--';

        const winEl = document.getElementById('timingWindowVal');
        if (winEl) winEl.innerText = t.optimal_window || '--:-- – --:--';

        const nextBarEl = document.getElementById('timingNextBarTime');
        if (nextBarEl) nextBarEl.innerText = t.next_candle_time_short || '--:--:--';

        if (dockSub) {
          dockSub.innerText = `Trigger: ${t.trigger_time_short || '--:--'} • TF: ${t.timeframe || tf} • Score: ${data.score}/100`;
        }

        // 5. Countdown timer setup
        timingSecondsRemaining = t.seconds_to_next_bar !== undefined ? t.seconds_to_next_bar : 60;
        updateTimingCountdownDisplay();

        if (timingCountdownInterval) clearInterval(timingCountdownInterval);
        timingCountdownInterval = setInterval(() => {
          timingSecondsRemaining--;
          if (timingSecondsRemaining <= 0) {
            timingSecondsRemaining = t.interval_seconds || 60;
            analyzeCurrentChartTiming();
          }
          updateTimingCountdownDisplay();
        }, 1000);

      } catch (err) {
        console.error('Error fetching chart timing:', err);
      }
    }

    function updateTimingCountdownDisplay() {
      const mins = Math.floor(timingSecondsRemaining / 60);
      const secs = timingSecondsRemaining % 60;
      const str = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}s`;

      const badge = document.getElementById('timingCountdownBadge');
      if (badge) badge.innerText = str;

      const dockPill = document.getElementById('dockCountdownPill');
      if (dockPill) dockPill.innerText = str;
    }

    function applyTimingToConsole() {
      if (!currentTimingData) return;
      const t = currentTimingData.timing || {};
      const ex = currentTimingData.execution || {};

      const slInput = document.getElementById('pracInputSL');
      const tpInput = document.getElementById('pracInputTP');
      if (ex.stop_loss && slInput) slInput.value = ex.stop_loss;
      if (ex.take_profit_1 && tpInput) tpInput.value = ex.take_profit_1;

      const act = (t.action || 'BUY').toUpperCase();
      if (act === 'BUY') {
        const btnUp = document.querySelector('.binomo-btn-up');
        if (btnUp) {
          btnUp.classList.add('pulse-highlight');
          setTimeout(() => btnUp.classList.remove('pulse-highlight'), 2000);
        }
      } else if (act === 'SELL') {
        const btnDown = document.querySelector('.binomo-btn-down');
        if (btnDown) {
          btnDown.classList.add('pulse-highlight');
          setTimeout(() => btnDown.classList.remove('pulse-highlight'), 2000);
        }
      }
      showToast(`⚡ Perfect timing setup applied for ${currentTimingData.symbol}! Target: ${act}`);
    }

    function updateBinomoPayout() {
      const amtInput = document.getElementById('pracInputAmount');
      const amount = amtInput ? parseFloat(amtInput.value) || 0 : 0;
      const profitRate = 0.05; // 5% target profit
      const expectedProfit = amount * profitRate;
      const totalReturn = amount + expectedProfit;

      const profitEl = document.getElementById('binomoExpectedProfit');
      if (profitEl) {
        profitEl.innerText = `+$${expectedProfit.toFixed(2)} (+5.0%)`;
      }
      const totalEl = document.getElementById('binomoTotalPayout');
      if (totalEl) {
        totalEl.innerText = `$${totalReturn.toFixed(2)}`;
      }
    }

    function adjustPracticeAmount(delta) {
      const input = document.getElementById('pracInputAmount');
      if (!input) return;
      let val = (parseFloat(input.value) || 0) + delta;
      if (val < 10) val = 10;
      if (val > 1000) val = 1000;
      input.value = val;
      updateBinomoPayout();
    }

    function setPracticeAmountPreset(amt) {
      const input = document.getElementById('pracInputAmount');
      if (!input) return;
      input.value = amt;
      updateBinomoPayout();
    }

    function setPracticeAmountMax() {
      const input = document.getElementById('pracInputAmount');
      const cashEl = document.getElementById('pracCash');
      let maxVal = 1000;
      if (cashEl) {
        const raw = cashEl.innerText.replace(/[^0-9.]/g, '');
        const parsed = parseFloat(raw);
        if (!isNaN(parsed) && parsed > 0) maxVal = Math.min(1000, parsed);
      }
      if (input) {
        input.value = Math.max(10, Math.floor(maxVal));
        updateBinomoPayout();
      }
    }

    function switchPracticeDrawer(tab) {
      const tabOpen = document.getElementById('tabDrawerOpen');
      const tabHist = document.getElementById('tabDrawerHistory');
      const tabAI = document.getElementById('tabDrawerAI');
      const contentOpen = document.getElementById('drawerContentOpen');
      const contentHist = document.getElementById('drawerContentHistory');
      const contentAI = document.getElementById('drawerContentAI');

      if (tabOpen) tabOpen.className = 'drawer-tab' + (tab === 'open' ? ' active' : '');
      if (tabHist) tabHist.className = 'drawer-tab' + (tab === 'history' ? ' active' : '');
      if (tabAI) tabAI.className = 'drawer-tab' + (tab === 'ai' ? ' active' : '');

      if (contentOpen) contentOpen.style.display = (tab === 'open' ? 'block' : 'none');
      if (contentHist) contentHist.style.display = (tab === 'history' ? 'block' : 'none');
      if (contentAI) contentAI.style.display = (tab === 'ai' ? 'block' : 'none');

      if (tab === 'ai') {
        fetchAIGuidance();
      }
    }

    async function submitPracticeOrder(action = 'BUY', specificSym = null) {
      const symInput = document.getElementById('pracInputSymbol');
      const amtInput = document.getElementById('pracInputAmount');
      const slInput = document.getElementById('pracInputSL');
      const tpInput = document.getElementById('pracInputTP');

      const symbol = (specificSym || (symInput ? symInput.value : '') || currentPracticeSymbol || 'NVDA').trim().toUpperCase();
      if (!symbol) {
        showToast('Please enter or select a stock ticker to ' + (action === 'SELL' ? 'sell' : 'buy'));
        return;
      }

      if (action === 'SELL') {
        showToast(`Submitting Practice Sell for ${symbol}...`);
        try {
          const res = await fetch('/api/practice/sell', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              symbol: symbol,
              reason: 'MANUAL_PRACTICE_SELL'
            })
          });
          const data = await res.json();
          if (data.success) {
            const sign = (data.pnl || 0) >= 0 ? '+' : '';
            showToast(`✓ Sold ${data.symbol}: Realized P&L ${sign}$${data.pnl} (${sign}${data.pnl_pct}%)!`);
            fetchPracticePortfolio();
          } else {
            showToast(`Practice Sell failed: ${data.error || 'Check position'}`);
          }
        } catch (e) {
          showToast('Error selling: ' + e);
        }
        return;
      }

      const amount = amtInput ? parseFloat(amtInput.value) || 250 : 250;
      const sl = slInput ? parseFloat(slInput.value) || 0 : 0;
      const tp1 = tpInput ? parseFloat(tpInput.value) || 0 : 0;

      showToast(`Submitting Practice Buy for ${symbol}...`);
      try {
        const res = await fetch('/api/practice/buy', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            symbol: symbol,
            allocation: amount,
            stop_loss: sl,
            take_profit_1: tp1,
            score: 75,
            signal: 'MANUAL_TEST'
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(`✓ Practice Buy executed: ${data.shares} shares of ${data.symbol} for $${data.invested}!`);
          fetchPracticePortfolio();
        } else {
          showToast(`Practice Buy failed: ${data.error || 'Unknown error'}`);
        }
      } catch (e) {
        showToast('Error: ' + e);
      }
    }

    async function fetchPracticePortfolio() {
      try {
        const res = await fetch('/api/practice');
        const data = await res.json();
        updatePracticeUI(data);
      } catch (e) {
        console.error('Error fetching practice portfolio:', e);
      }
    }

    function updatePracticeUI(data) {
      if (!data) return;
      const winRateEl = document.getElementById('pracWinRate');
      const winLossEl = document.getElementById('pracWinLossRatio');
      const returnEl = document.getElementById('pracTotalReturn');
      const equityEl = document.getElementById('pracEquitySub');
      const cashEl = document.getElementById('pracCash');
      const realizedEl = document.getElementById('pracRealizedPnl');
      const closedTradesEl = document.getElementById('pracClosedTrades');
      const openMeta = document.getElementById('pracOpenMeta');
      const openTbody = document.getElementById('pracOpenTbody');
      const histMeta = document.getElementById('pracHistoryMeta');
      const histTbody = document.getElementById('pracHistoryTbody');

      const sign = (data.total_pnl || 0) >= 0 ? '+' : '';
      if (winRateEl) {
        winRateEl.innerText = `${(data.win_rate_pct || 0).toFixed(1)}%`;
        winRateEl.style.color = (data.win_rate_pct || 0) >= 50 ? 'var(--green)' : (data.total_trades === 0 ? '#818cf8' : 'var(--red)');
      }
      if (winLossEl) winLossEl.innerText = `${data.wins || 0} Wins / ${data.losses || 0} Losses (${data.total_trades || 0} Closed)`;
      if (returnEl) {
        returnEl.innerText = `${sign}${(data.total_pnl_pct || 0).toFixed(2)}%`;
        returnEl.style.color = (data.total_pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)';
      }
      if (equityEl) equityEl.innerText = `Equity: $${(data.total_equity || 1000).toFixed(2)} / $1,000.00`;
      if (cashEl) cashEl.innerText = '$' + (data.cash || 1000).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
      const consoleCashEl = document.getElementById('pracConsoleCash');
      if (consoleCashEl) consoleCashEl.innerText = '$' + (data.cash || 1000).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
      if (realizedEl) realizedEl.innerText = `${sign}$${(data.realized_pnl || 0).toFixed(2)}`;
      if (closedTradesEl) closedTradesEl.innerText = `${data.total_trades || 0} Closed Trades`;

      // Drawer count badges
      const drawerOpenCount = document.getElementById('pracDrawerOpenCount');
      if (drawerOpenCount) drawerOpenCount.innerText = data.positions ? data.positions.length : 0;
      const drawerHistCount = document.getElementById('pracDrawerHistCount');
      if (drawerHistCount) drawerHistCount.innerText = data.trade_history ? data.trade_history.length : 0;

      // Holdings chips for quick sell in console
      const holdingsContainer = document.getElementById('pracHoldingsChips');
      if (holdingsContainer) {
        if (data.positions && data.positions.length > 0) {
          holdingsContainer.innerHTML = '<span style="color: var(--border); margin: 0 2px;">|</span><span style="color: #f87171; font-weight: 600;">Holdings to Sell:</span>' + 
            data.positions.map(p => `<button type="button" class="macro-btn" onclick="selectPracticeAsset('${p.symbol}')" style="padding: 2px 7px; font-size: 11px; color: #f87171; border-color: rgba(239,68,68,0.4); background: rgba(239,68,68,0.1);">🔴 ${p.symbol} (${p.shares})</button>`).join(' ');
        } else {
          holdingsContainer.innerHTML = '';
        }
      }

      // Open Positions Table
      if (openMeta) openMeta.innerText = `${data.positions ? data.positions.length : 0} active positions`;
      if (openTbody) {
        if (!data.positions || data.positions.length === 0) {
          openTbody.innerHTML = '<tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 22px;">No active practice positions. Buy a stock or follow AI guidance above to test!</td></tr>';
        } else {
          openTbody.innerHTML = '';
          data.positions.forEach(p => {
            const tr = document.createElement('tr');
            const pSign = p.unrealized_pnl >= 0 ? '+' : '';
            const colorClass = p.unrealized_pnl >= 0 ? 'color: var(--green);' : 'color: var(--red);';
            const currSymbol = p.currency === 'INR' ? '₹' : '$';
            const isINR = p.currency === 'INR' || (p.symbol && (p.symbol.endsWith('.NS') || p.symbol.endsWith('.BO')));

            const entryDisplay = isINR && p.entry_price_usd 
              ? `$${p.entry_price_usd.toFixed(2)} <span style="font-size: 10px; color: var(--text-muted);">(₹${p.entry_price.toFixed(2)})</span>` 
              : `${currSymbol}${p.entry_price.toFixed(2)}`;
            const currDisplay = isINR && p.current_price_usd 
              ? `$${p.current_price_usd.toFixed(2)} <span style="font-size: 10px; color: var(--text-muted);">(₹${p.current_price.toFixed(2)})</span>` 
              : `${currSymbol}${p.current_price.toFixed(2)}`;

            tr.innerHTML = `
              <td><strong style="color: #60a5fa; cursor: pointer;" onclick="selectPracticeAsset('${p.symbol}')" title="Click to view chart in Practice">${p.symbol}</strong></td>
              <td style="font-family: var(--font-mono);">${p.shares}</td>
              <td style="font-family: var(--font-mono);">${entryDisplay}</td>
              <td style="font-family: var(--font-mono);">${currDisplay}</td>
              <td style="font-family: var(--font-mono);">$${p.invested.toFixed(2)}</td>
              <td style="font-family: var(--font-mono); font-weight: 600;">$${p.current_value.toFixed(2)}</td>
              <td style="font-family: var(--font-mono); font-weight: 700; ${colorClass}">${pSign}$${p.unrealized_pnl.toFixed(2)} (${pSign}${p.unrealized_pct.toFixed(2)}%)</td>
              <td style="font-family: var(--font-mono); color: var(--red);">${p.stop_loss ? currSymbol + p.stop_loss.toFixed(2) : '-'}</td>
              <td style="font-family: var(--font-mono); color: var(--green);">${p.take_profit_1 ? currSymbol + p.take_profit_1.toFixed(2) : '-'}</td>
              <td><span style="color: #60a5fa; font-weight: 700;">${p.score || 70}/100</span></td>
              <td>
                <button onclick="submitPracticeOrder('SELL', '${p.symbol}')" style="padding: 4px 10px; font-size: 11px; background: rgba(239,68,68,0.2); color: #f87171; border: 1px solid #ef4444; border-radius: 4px; font-weight: 700; cursor: pointer;">
                  🔴 Sell / Exit
                </button>
              </td>
            `;
            openTbody.appendChild(tr);
          });
        }
      }

      // History Table
      if (histMeta) histMeta.innerText = `${data.trade_history ? data.trade_history.length : 0} recorded trades`;
      if (histTbody) {
        if (!data.trade_history || data.trade_history.length === 0) {
          histTbody.innerHTML = '<tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 22px;">No closed practice trades yet.</td></tr>';
        } else {
          histTbody.innerHTML = '';
          data.trade_history.forEach(t => {
            const tr = document.createElement('tr');
            const tSign = t.pnl_amount >= 0 ? '+' : '';
            const colorClass = t.pnl_amount >= 0 ? 'color: var(--green);' : 'color: var(--red);';
            const currSymbol = t.currency === 'INR' ? '₹' : '$';
            const isINR = t.currency === 'INR' || (t.symbol && (t.symbol.endsWith('.NS') || t.symbol.endsWith('.BO')));
            const resultBadge = t.result === 'WIN' 
              ? '<span class="status-pill strong-buy" style="font-size: 11px; padding: 2px 7px;">🎯 WIN</span>' 
              : '<span class="status-pill sell" style="font-size: 11px; padding: 2px 7px;">🛑 LOSS</span>';

            const entryDisplay = isINR && t.entry_price_usd 
              ? `$${t.entry_price_usd.toFixed(2)} (₹${t.entry_price.toFixed(2)})` 
              : `${currSymbol}${t.entry_price.toFixed(2)}`;
            const exitDisplay = isINR && t.exit_price_usd 
              ? `$${t.exit_price_usd.toFixed(2)} (₹${t.exit_price.toFixed(2)})` 
              : `${currSymbol}${t.exit_price.toFixed(2)}`;

            tr.innerHTML = `
              <td><strong style="color: #fff;">${t.symbol}</strong></td>
              <td><span class="action-chip buy">BUY</span> ➔ <span class="action-chip sell">SELL</span></td>
              <td style="font-family: var(--font-mono);">${t.score || '-'}</td>
              <td style="font-family: var(--font-mono);">${entryDisplay}</td>
              <td style="font-family: var(--font-mono);">${exitDisplay}</td>
              <td style="font-family: var(--font-mono);">$${t.invested.toFixed(2)}</td>
              <td style="font-family: var(--font-mono);">$${t.proceeds.toFixed(2)}</td>
              <td style="font-family: var(--font-mono); font-weight: 700; ${colorClass}">${tSign}$${t.pnl_amount.toFixed(2)} (${tSign}${t.pnl_pct.toFixed(2)}%)</td>
              <td>${resultBadge}</td>
              <td style="font-size: 11px; color: #cbd5e1;">${t.exit_reason || 'MANUAL'}</td>
              <td style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono);">${t.exit_time || '-'}</td>
            `;
            histTbody.appendChild(tr);
          });
        }
      }
    }

    async function liquidatePracticePosition(symbol, price) {
      if (!confirm(`Liquidate practice position for ${symbol}?`)) return;
      try {
        const res = await fetch('/api/practice/sell', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({symbol: symbol, price: price, reason: 'MANUAL_PRACTICE_EXIT'})
        });
        const data = await res.json();
        if (data.success) {
          const sign = data.pnl >= 0 ? '+' : '';
          showToast(`✓ Sold ${symbol}: Realized P&L ${sign}$${data.pnl} (${sign}${data.pnl_pct}%)`);
          fetchPracticePortfolio();
        } else {
          showToast(`Sell failed: ${data.error || 'Error'}`);
        }
      } catch (e) {
        showToast('Error: ' + e);
      }
    }

    async function resetPracticeCredits() {
      if (!confirm('Reset Practice Sandbox back to $1,000.00 virtual credits?')) return;
      try {
        const res = await fetch('/api/practice/reset', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'}
        });
        const data = await res.json();
        updatePracticeUI(data);
        showToast('✓ Practice sandbox reset to $1,000.00 virtual credits.');
      } catch (e) {
        showToast('Error resetting: ' + e);
      }
    }

    // Startup
    loadConfig();
    switchMarket('US');
    fetchMarketOverview(false);
    fetchAlertsHistory();
    fetchPortfolio();
    fetchPracticePortfolio();
    fetchSignalsFeed();
    updateBinomoPayout();
    fetchAIUniverseSymbols();
    analyzeCurrentChartTiming();
    setInterval(fetchPortfolio, 10000);
    setInterval(fetchPracticePortfolio, 10000);
    setInterval(fetchSignalsFeed, 10000);
    setInterval(fetchAlertsHistory, 15000);
    setInterval(() => fetchMarketOverview(false), 60000);
  </script>
</body>
</html>
"""

def execute_action_dict(act: Dict[str, Any], active_symbol: str = "NVDA") -> Optional[Dict[str, Any]]:
    """Executes a structured action dictionary on the platform."""
    global ai_auto_trading_enabled, ai_trade_symbols
    act_type = str(act.get("type", "")).upper()
    
    if act_type == "BUY":
        sym = (act.get("symbol") or active_symbol or "NVDA").upper().strip()
        amt = float(act.get("amount") or act.get("allocation") or 250.0)
        curr_price = 0.0
        currency = "INR" if sym.endswith((".NS", ".BO")) else "USD"
        res_analysis = None
        if sym in cached_results:
            res_analysis = cached_results[sym]
        else:
            resolved = client.resolve_symbol(sym)
            raw = client.get_full_analysis(resolved)
            if raw and raw.get("analyst"):
                res_analysis = strategy.analyze(raw)
                cached_results[resolved] = res_analysis
        if res_analysis:
            curr_price = res_analysis.get("current_price", 0.0)
            score = res_analysis.get("score", 75)
            ex = res_analysis.get("execution", {})
            sl = ex.get("stop_loss", round(curr_price * 0.95, 2))
            tp1 = ex.get("take_profit_1", round(curr_price * 1.05, 2))
        else:
            curr_price = 100.0
            score = 70
            sl = round(curr_price * 0.95, 2)
            tp1 = round(curr_price * 1.05, 2)
        buy_res = practice_portfolio.buy(sym, curr_price, amt, sl, tp1, score=score, signal="AI_AGENTIC_BUY", currency=currency)
        if buy_res.get("success"):
            c_sign = "₹" if currency == "INR" else "$"
            return {
                "type": "BUY",
                "symbol": sym,
                "shares": buy_res["shares"],
                "invested": buy_res["invested"],
                "price": curr_price,
                "summary": f"Executed BUY order: {buy_res['shares']} shares of {sym} for ${buy_res['invested']:.2f} at {c_sign}{curr_price:,.2f} (SL: {c_sign}{sl:,.2f}, TP1: {c_sign}{tp1:,.2f}).",
                "refresh_practice": True,
                "refresh_portfolio": True,
                "switch_symbol": sym
            }
        return {"type": "BUY_FAILED", "summary": f"Buy failed: {buy_res.get('error')}"}

    elif act_type == "SELL":
        sym = (act.get("symbol") or active_symbol).upper().strip()
        if sym in practice_portfolio.positions:
            pos = practice_portfolio.positions[sym]
            live_p = pos.get("current_price") or pos.get("entry_price") or 100.0
            sell_res = practice_portfolio.sell(sym, price=live_p, exit_reason="AI_AGENTIC_SELL")
            sign = '+' if sell_res.get("pnl", 0) >= 0 else ''
            return {
                "type": "SELL",
                "symbol": sym,
                "summary": f"Closed position in {sym} @ {live_p}: Realized P&L {sign}${sell_res.get('pnl', 0):.2f} ({sign}{sell_res.get('pnl_pct', 0):.2f}%).",
                "pnl": sell_res.get("pnl"),
                "refresh_practice": True,
                "refresh_portfolio": True
            }
        return {"type": "SELL_FAILED", "summary": f"No active position found for {sym} to sell."}

    elif act_type == "LIQUIDATE_ALL":
        sold = []
        for sym, pos in list(practice_portfolio.positions.items()):
            live_p = pos.get("current_price") or pos.get("entry_price") or 100.0
            r = practice_portfolio.sell(sym, price=live_p, exit_reason="AI_COMMAND_LIQUIDATE_ALL")
            sold.append(r)
        return {
            "type": "LIQUIDATE_ALL",
            "summary": f"Liquidated all {len(sold)} practice positions.",
            "refresh_practice": True,
            "refresh_portfolio": True
        }

    elif act_type == "RESET_PRACTICE":
        res = practice_portfolio.reset()
        return {
            "type": "RESET_PRACTICE",
            "summary": "Restored Practice Sandbox to $1,000.00 virtual credits.",
            "refresh_practice": True,
            "refresh_portfolio": True
        }

    elif act_type == "SET_AI_SYMBOLS":
        syms = act.get("symbols", [])
        if syms:
            ai_trade_symbols = [s.strip().upper() for s in syms if s.strip()]
            config["ai_trade_symbols"] = ai_trade_symbols
            save_config(config)
            return {
                "type": "SET_AI_SYMBOLS",
                "summary": f"Updated AI Trading Universe to {len(ai_trade_symbols)} assets: {', '.join(ai_trade_symbols)}",
                "symbols": ai_trade_symbols,
                "refresh_universe": True
            }

    elif act_type == "TOGGLE_AUTO_TRADING":
        enabled = bool(act.get("enabled", True))
        ai_auto_trading_enabled = enabled
        config["ai_auto_trading_enabled"] = enabled
        save_config(config)
        return {
            "type": "TOGGLE_AUTO_TRADING",
            "summary": f"AI Autonomous Trading Engine {'activated' if enabled else 'paused'}.",
            "enabled": enabled,
            "refresh_portfolio": True
        }

    elif act_type == "RUN_AI_SCAN":
        eligible = [
            r for sym, r in cached_results.items()
            if not ai_trade_symbols or sym in ai_trade_symbols or any(s == sym for s in ai_trade_symbols)
        ]
        trade_res = portfolio.process_autonomous_signals(eligible, max_positions=4)
        buys = len(trade_res.get("buys_executed", []))
        sells = len(trade_res.get("sells_executed", []))
        return {
            "type": "RUN_AI_SCAN",
            "summary": f"AI Autonomous scan executed: {buys} buys, {sells} exits processed.",
            "refresh_portfolio": True
        }

    return None

def execute_agentic_system_command(message: str, active_symbol: str = "NVDA") -> Optional[Dict[str, Any]]:
    """Deterministic agentic action dispatcher: parses user natural language commands and executes them on the live platform."""
    global ai_auto_trading_enabled, ai_trade_symbols
    msg = message.strip()
    msg_lower = msg.lower()

    # 1. RESET / REFILL PRACTICE SANDBOX
    if any(k in msg_lower for k in ["reset practice", "reset demo", "reset balance", "refill credits", "refill practice", "refill demo", "reset sandbox", "reset virtual"]):
        res = practice_portfolio.reset()
        return {
            "type": "RESET_PRACTICE",
            "summary": "Restored Practice Sandbox to $1,000.00 virtual credits.",
            "details": res,
            "refresh_practice": True,
            "refresh_portfolio": True
        }

    # 2. LIQUIDATE ALL POSITIONS
    if any(k in msg_lower for k in ["liquidate all", "sell all", "close all positions", "close all trades", "exit all", "sell everything"]):
        sold = []
        for sym, pos in list(practice_portfolio.positions.items()):
            live_p = pos.get("current_price") or pos.get("entry_price") or 100.0
            r = practice_portfolio.sell(sym, price=live_p, exit_reason="AI_COMMAND_LIQUIDATE_ALL")
            sold.append(r)
        return {
            "type": "LIQUIDATE_ALL",
            "summary": f"Liquidated all {len(sold)} practice positions.",
            "details": sold,
            "refresh_practice": True,
            "refresh_portfolio": True
        }

    # 3. SET AI TRADING UNIVERSE / ALLOWED STOCKS
    if ("ai" in msg_lower or "universe" in msg_lower or "trader" in msg_lower) and any(k in msg_lower for k in ["trade", "universe", "stocks", "assets"]):
        if any(w in msg_lower for w in ["set", "make", "configure", "allow", "choose", "select", "restrict", "only", "add", "remove"]):
            name_map = {
                "apple": "AAPL", "nvidia": "NVDA", "gold": "XAU/USD", "bitcoin": "BTC/USD", "btc": "BTC/USD",
                "ethereum": "ETH/USD", "eth": "ETH/USD", "reliance": "RELIANCE.NS", "tesla": "TSLA",
                "microsoft": "MSFT", "google": "GOOGL", "amazon": "AMZN", "meta": "META",
                "tcs": "TCS.NS", "hdfc": "HDFCBANK.NS", "icici": "ICICIBANK.NS", "infosys": "INFY.NS"
            }
            tokens = re.findall(r'[A-Za-z0-9_./-]+', msg)
            found_symbols = []
            for t in tokens:
                tl = t.lower()
                tu = t.upper()
                if tl in name_map:
                    found_symbols.append(name_map[tl])
                elif tu in ["NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "META", "AMD", "SPY", "QQQ", "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "BHARTIARTL.NS", "SBIN.NS", "LT.NS", "ITC.NS", "AXISBANK.NS", "SUNPHARMA.NS", "MARUTI.NS", "BTC/USD", "ETH/USD", "XAU/USD", "EUR/USD", "USD/INR"] or "/" in tu or tu.endswith((".NS", ".BO")):
                    found_symbols.append(tu)

            found_symbols = list(dict.fromkeys(found_symbols))
            if found_symbols:
                if "add" in msg_lower:
                    for s in found_symbols:
                        if s not in ai_trade_symbols:
                            ai_trade_symbols.append(s)
                elif "remove" in msg_lower or "delete" in msg_lower:
                    ai_trade_symbols = [s for s in ai_trade_symbols if s not in found_symbols]
                else:
                    ai_trade_symbols = found_symbols

                config["ai_trade_symbols"] = ai_trade_symbols
                save_config(config)
                return {
                    "type": "SET_AI_SYMBOLS",
                    "summary": f"Updated AI Trading Universe to {len(ai_trade_symbols)} assets: {', '.join(ai_trade_symbols)}",
                    "symbols": ai_trade_symbols,
                    "refresh_universe": True
                }

    # 4. TOGGLE AUTO TRADING
    if any(k in msg_lower for k in ["pause auto", "pause ai", "stop auto", "stop ai", "disable auto", "disable ai trader"]):
        ai_auto_trading_enabled = False
        config["ai_auto_trading_enabled"] = False
        save_config(config)
        return {
            "type": "TOGGLE_AUTO_TRADING",
            "summary": "AI Autonomous Trading Engine paused.",
            "enabled": False,
            "refresh_portfolio": True
        }
    if any(k in msg_lower for k in ["resume auto", "start auto", "enable auto", "turn on auto", "activate auto"]):
        ai_auto_trading_enabled = True
        config["ai_auto_trading_enabled"] = True
        save_config(config)
        return {
            "type": "TOGGLE_AUTO_TRADING",
            "summary": "AI Autonomous Trading Engine activated.",
            "enabled": True,
            "refresh_portfolio": True
        }

    # 5. RUN AI SCAN
    if any(k in msg_lower for k in ["run scan", "run ai scan", "scan now", "execute auto trade", "trigger auto trade"]):
        eligible = [
            r for sym, r in cached_results.items()
            if not ai_trade_symbols or sym in ai_trade_symbols or any(s == sym for s in ai_trade_symbols)
        ]
        trade_res = portfolio.process_autonomous_signals(eligible, max_positions=4)
        buys = len(trade_res.get("buys_executed", []))
        sells = len(trade_res.get("sells_executed", []))
        return {
            "type": "RUN_AI_SCAN",
            "summary": f"AI Autonomous scan executed: {buys} buys, {sells} exits processed.",
            "details": trade_res,
            "refresh_portfolio": True
        }

    # 6. BUY / LONG
    buy_match = re.search(r'\b(buy|purchase|long|enter|open long)\b', msg_lower)
    if buy_match:
        target_sym = None
        name_map = {
            "apple": "AAPL", "nvidia": "NVDA", "gold": "XAU/USD", "bitcoin": "BTC/USD", "btc": "BTC/USD",
            "ethereum": "ETH/USD", "eth": "ETH/USD", "reliance": "RELIANCE.NS", "tesla": "TSLA",
            "microsoft": "MSFT", "google": "GOOGL", "amazon": "AMZN", "meta": "META"
        }
        for word in re.findall(r'[A-Za-z0-9_./-]+', msg):
            wl = word.lower()
            wu = word.upper()
            if wl in name_map:
                target_sym = name_map[wl]
                break
            if wu in ["NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "META", "AMD", "SPY", "QQQ", "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "BHARTIARTL.NS", "SBIN.NS", "BTC/USD", "ETH/USD", "XAU/USD", "EUR/USD", "USD/INR"] or "/" in wu or wu.endswith((".NS", ".BO")):
                target_sym = wu
                break

        if not target_sym:
            target_sym = active_symbol or "NVDA"

        amt_match = re.search(r'\$?([0-9]+(?:\.[0-9]+)?)\s*(?:dollars|\$|usd)?', msg)
        amount = 250.0
        if amt_match:
            try:
                parsed_amt = float(amt_match.group(1))
                if 10.0 <= parsed_amt <= 1000.0:
                    amount = parsed_amt
            except Exception:
                pass

        curr_price = 0.0
        currency = "INR" if target_sym.endswith((".NS", ".BO")) else "USD"
        res_analysis = None
        if target_sym in cached_results:
            res_analysis = cached_results[target_sym]
        else:
            resolved = client.resolve_symbol(target_sym)
            raw = client.get_full_analysis(resolved)
            if raw and raw.get("analyst"):
                res_analysis = strategy.analyze(raw)
                cached_results[resolved] = res_analysis

        if res_analysis:
            curr_price = res_analysis.get("current_price", 0.0)
            score = res_analysis.get("score", 75)
            ex = res_analysis.get("execution", {})
            sl = ex.get("stop_loss", round(curr_price * 0.95, 2))
            tp1 = ex.get("take_profit_1", round(curr_price * 1.05, 2))
        else:
            curr_price = 100.0
            score = 70
            sl = round(curr_price * 0.95, 2)
            tp1 = round(curr_price * 1.05, 2)

        buy_res = practice_portfolio.buy(
            symbol=target_sym,
            price=curr_price,
            allocation=amount,
            stop_loss=sl,
            take_profit_1=tp1,
            score=score,
            signal="AI_AGENTIC_BUY",
            currency=currency
        )

        if buy_res.get("success"):
            c_sign = "₹" if currency == "INR" else "$"
            summary_msg = f"Executed BUY order: {buy_res['shares']} shares of {target_sym} for ${buy_res['invested']:.2f} at {c_sign}{curr_price:,.2f} (SL: {c_sign}{sl:,.2f}, TP1: {c_sign}{tp1:,.2f})."
            return {
                "type": "BUY",
                "symbol": target_sym,
                "shares": buy_res["shares"],
                "invested": buy_res["invested"],
                "price": curr_price,
                "summary": summary_msg,
                "refresh_practice": True,
                "refresh_portfolio": True,
                "switch_symbol": target_sym
            }
        else:
            return {
                "type": "BUY_FAILED",
                "symbol": target_sym,
                "summary": f"Could not execute BUY for {target_sym}: {buy_res.get('error', 'Unknown error')}",
                "error": buy_res.get("error")
            }

    # 7. SELL / EXIT SPECIFIC SYMBOL
    sell_match = re.search(r'\b(sell|exit|close|liquidate)\b', msg_lower)
    if sell_match:
        target_sym = None
        name_map = {
            "apple": "AAPL", "nvidia": "NVDA", "gold": "XAU/USD", "bitcoin": "BTC/USD", "btc": "BTC/USD",
            "ethereum": "ETH/USD", "eth": "ETH/USD", "reliance": "RELIANCE.NS", "tesla": "TSLA",
            "microsoft": "MSFT", "google": "GOOGL", "amazon": "AMZN", "meta": "META"
        }
        for word in re.findall(r'[A-Za-z0-9_./-]+', msg):
            wl = word.lower()
            wu = word.upper()
            if wl in name_map:
                target_sym = name_map[wl]
                break
            if wu in practice_portfolio.positions or wu in cached_results:
                target_sym = wu
                break

        if not target_sym:
            target_sym = active_symbol

        if target_sym in practice_portfolio.positions:
            pos = practice_portfolio.positions[target_sym]
            live_p = pos.get("current_price") or pos.get("entry_price") or 100.0
            sell_res = practice_portfolio.sell(target_sym, price=live_p, exit_reason="AI_COMMAND_EXIT")
            if sell_res.get("success"):
                sign = '+' if sell_res.get("pnl", 0) >= 0 else ''
                summary_msg = f"Closed position in {target_sym} @ {live_p}: Realized P&L {sign}${sell_res.get('pnl', 0):.2f} ({sign}{sell_res.get('pnl_pct', 0):.2f}%)."
                return {
                    "type": "SELL",
                    "symbol": target_sym,
                    "summary": summary_msg,
                    "pnl": sell_res.get("pnl"),
                    "refresh_practice": True,
                    "refresh_portfolio": True
                }
            else:
                return {
                    "type": "SELL_FAILED",
                    "symbol": target_sym,
                    "summary": f"Could not sell {target_sym}: {sell_res.get('error')}"
                }
        else:
            return {
                "type": "SELL_FAILED",
                "symbol": target_sym,
                "summary": f"No active practice position found for {target_sym} to sell."
            }

    return None

class DashboardHandler(BaseHTTPRequestHandler):
    """Handles REST API and serves the dashboard HTML."""

    def log_message(self, format, *args):
        pass

    def send_json(self, data: Any, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ["/", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))

        elif path == "/api/config":
            self.send_json(config)

        elif path in ["/api/analyze", "/api/chart-timing", "/api/timing"]:
            ticker = query.get("ticker", query.get("symbol", [""]))[0]
            tf = query.get("timeframe", query.get("tf", ["1d"]))[0].lower()
            if not ticker:
                self.send_json({"error": "Missing ticker or symbol parameter"}, 400)
                return
            resolved = client.resolve_symbol(ticker)
            raw = client.get_full_analysis(resolved, timeframe=tf)
            if not raw or (not raw.get("analyst") and not raw.get("technical")):
                self.send_json({"error": f"Failed to fetch data for {resolved}"}, 404)
                return
            result = strategy.analyze(raw)
            result["timeframe"] = tf
            cached_results[result["symbol"]] = result
            if path in ["/api/chart-timing", "/api/timing"]:
                self.send_json({
                    "symbol": result["symbol"],
                    "name": result.get("name", result["symbol"]),
                    "current_price": result.get("current_price", 0.0),
                    "currency": result.get("currency", "USD"),
                    "timeframe": tf,
                    "score": result.get("score", 50),
                    "signal": result.get("signal", "HOLD"),
                    "timing": result.get("timing", {}),
                    "execution": result.get("execution", {})
                })
            else:
                self.send_json(result)

        elif path == "/api/scan":
            force = "force" in query
            market = query.get("market", ["US"])[0].upper()
            symbols = config.get("watchlist_us", []) if market == "US" else config.get("watchlist_india", [])
            
            results = []
            needed_symbols = []
            for s in symbols:
                resolved = client.resolve_symbol(s)
                if not force and resolved in cached_results:
                    results.append(cached_results[resolved])
                else:
                    needed_symbols.append(resolved)

            if needed_symbols:
                with ThreadPoolExecutor(max_workers=8) as executor:
                    future_to_sym = {executor.submit(client.get_full_analysis, sym): sym for sym in needed_symbols}
                    for future in as_completed(future_to_sym):
                        try:
                            raw = future.result()
                            if raw and raw.get("analyst"):
                                res = strategy.analyze(raw)
                                cached_results[res["symbol"]] = res
                                results.append(res)
                        except Exception:
                            pass

            results.sort(key=lambda x: x.get("score", 0), reverse=True)
            self.send_json(results)

        elif path in ["/api/market-overview", "/api/overview"]:
            market = query.get("market", ["US"])[0].upper()
            overview = client.get_market_overview(market)
            self.send_json(overview)

        elif path == "/api/alerts":
            limit = int(query.get("limit", [50])[0])
            self.send_json(get_alert_history(limit))

        elif path == "/api/portfolio":
            live_prices = {sym: res.get("current_price", 0.0) for sym, res in cached_results.items() if res.get("current_price")}
            self.send_json(portfolio.get_summary(live_prices))

        elif path in ("/api/signals-feed", "/api/signals"):
            self.send_json(list(reversed(signals_feed[-50:])))

        elif path in ("/api/practice", "/api/practice/portfolio"):
            live_prices = {sym: res.get("current_price", 0.0) for sym, res in cached_results.items() if res.get("current_price")}
            self.send_json(practice_portfolio.get_summary(live_prices))

        elif path == "/api/guidance":
            top_guidance = [
                r for r in cached_results.values()
                if r.get("score", 0) >= 60 and r.get("current_price", 0) > 0
            ]
            top_guidance.sort(key=lambda x: x.get("score", 0), reverse=True)
            self.send_json(top_guidance[:6])

        elif path == "/api/portfolio/report":
            live_prices = {sym: res.get("current_price", 0.0) for sym, res in cached_results.items() if res.get("current_price")}
            summary = portfolio.get_summary(live_prices)
            report = ai_assistant.generate_portfolio_report(summary)
            self.send_json(report)

        elif path == "/api/ai-trader/symbols":
            available_list = []
            seen = set()
            us_stocks = config.get("watchlist_us", ["NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "META", "AMD", "SPY", "QQQ"])
            for s in us_stocks:
                if s not in seen:
                    available_list.append({"symbol": s, "name": s, "market": "US", "price": cached_results.get(s, {}).get("current_price", 0.0)})
                    seen.add(s)

            in_stocks = config.get("watchlist_india", ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "BHARTIARTL.NS", "SBIN.NS", "LT.NS", "ITC.NS", "AXISBANK.NS", "SUNPHARMA.NS", "MARUTI.NS"])
            for s in in_stocks:
                if s not in seen:
                    available_list.append({"symbol": s, "name": s, "market": "IN", "price": cached_results.get(s, {}).get("current_price", 0.0)})
                    seen.add(s)

            commodities_crypto = ["XAU/USD", "BTC/USD", "ETH/USD", "EUR/USD", "USD/INR"]
            for s in commodities_crypto:
                if s not in seen:
                    available_list.append({"symbol": s, "name": s, "market": "CRYPTO_COMMODITY", "price": cached_results.get(s, {}).get("current_price", 0.0)})
                    seen.add(s)

            for s in ai_trade_symbols:
                if s not in seen:
                    available_list.append({"symbol": s, "name": s, "market": "CUSTOM", "price": cached_results.get(s, {}).get("current_price", 0.0)})
                    seen.add(s)

            self.send_json({
                "selected": ai_trade_symbols,
                "all_available": available_list,
                "enabled": ai_auto_trading_enabled
            })

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global ai_trade_symbols, ai_auto_trading_enabled
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if path == "/api/portfolio/buy":
            sym = payload.get("symbol", "").upper().strip()
            if not sym:
                self.send_json({"success": False, "error": "Missing symbol"}, 400)
                return
            sym = client.resolve_symbol(sym)
            price = float(payload.get("price", 0.0))
            if price <= 0 and sym in cached_results:
                price = float(cached_results[sym].get("current_price", 0.0))
            if price <= 0:
                raw = client.get_full_analysis(sym)
                if raw and raw.get("analyst"):
                    price = float(raw["analyst"].get("current_price", 0.0))
                    cached_results[sym] = strategy.analyze(raw)
            if price <= 0:
                self.send_json({"success": False, "error": f"Could not fetch live price for {sym}"}, 400)
                return
            allocation = float(payload.get("allocation", 250.0))
            sl = float(payload.get("stop_loss", 0.0))
            tp1 = float(payload.get("take_profit_1", 0.0))
            tp2 = float(payload.get("take_profit_2", 0.0))
            score = int(payload.get("score", 50))
            signal = payload.get("signal", "BUY")
            curr = payload.get("currency") or ("INR" if sym.endswith((".NS", ".BO")) else "USD")
            res = portfolio.buy(sym, price, allocation, sl, tp1, tp2, score, signal, curr)
            self.send_json(res)

        elif path == "/api/portfolio/sell":
            sym = payload.get("symbol", "").upper().strip()
            resolved = client.resolve_symbol(sym)
            target_sym = sym if sym in portfolio.positions else resolved
            price = float(payload.get("price", 0.0))
            if price <= 0 and target_sym in cached_results:
                price = float(cached_results[target_sym].get("current_price", 0.0))
            if price <= 0:
                raw = client.get_full_analysis(target_sym)
                if raw and raw.get("analyst"):
                    price = float(raw["analyst"].get("current_price", 0.0))
            reason = payload.get("reason", "MANUAL")
            res = portfolio.sell(target_sym, price, exit_reason=reason)
            self.send_json(res)

        elif path == "/api/practice/buy":
            sym = payload.get("symbol", "").upper().strip()
            if not sym:
                self.send_json({"success": False, "error": "Missing symbol"}, 400)
                return
            sym = client.resolve_symbol(sym)
            price = float(payload.get("price", 0.0))
            if price <= 0 and sym in cached_results:
                price = float(cached_results[sym].get("current_price", 0.0))
            if price <= 0:
                raw = client.get_full_analysis(sym)
                if raw and raw.get("analyst"):
                    price = float(raw["analyst"].get("current_price", 0.0))
                    cached_results[sym] = strategy.analyze(raw)
            if price <= 0:
                self.send_json({"success": False, "error": f"Could not fetch live price for {sym}"}, 400)
                return
            allocation = float(payload.get("allocation", 250.0))
            sl = float(payload.get("stop_loss", 0.0))
            tp1 = float(payload.get("take_profit_1", 0.0))
            tp2 = float(payload.get("take_profit_2", 0.0))
            score = int(payload.get("score", 50))
            signal = payload.get("signal", "BUY")
            curr = payload.get("currency") or ("INR" if sym.endswith((".NS", ".BO")) else "USD")
            res = practice_portfolio.buy(sym, price, allocation, sl, tp1, tp2, score, signal, curr)
            self.send_json(res)

        elif path == "/api/practice/sell":
            sym = payload.get("symbol", "").upper().strip()
            resolved = client.resolve_symbol(sym)
            target_sym = sym if sym in practice_portfolio.positions else resolved
            price = float(payload.get("price", 0.0))
            if price <= 0 and target_sym in cached_results:
                price = float(cached_results[target_sym].get("current_price", 0.0))
            if price <= 0:
                raw = client.get_full_analysis(target_sym)
                if raw and raw.get("analyst"):
                    price = float(raw["analyst"].get("current_price", 0.0))
            reason = payload.get("reason", "MANUAL_PRACTICE")
            res = practice_portfolio.sell(target_sym, price, exit_reason=reason)
            self.send_json(res)

        elif path == "/api/practice/reset":
            summary = practice_portfolio.reset()
            self.send_json(summary)

        elif path == "/api/portfolio/auto-invest" or path == "/api/portfolio/auto-trade-now":
            market = payload.get("market", "US").upper()
            stocks = list(cached_results.values())
            if len(stocks) < 3:
                syms = config.get("watchlist_us", [])[:6] if market == "US" else config.get("watchlist_india", [])[:6]
                for s in syms:
                    try:
                        raw = client.get_full_analysis(client.resolve_symbol(s))
                        if raw and raw.get("analyst"):
                            res = strategy.analyze(raw)
                            cached_results[res["symbol"]] = res
                            stocks.append(res)
                    except Exception:
                        pass
            trade_res = portfolio.process_autonomous_signals(stocks, max_positions=4)
            live_prices = {s: r.get("current_price", 0.0) for s, r in cached_results.items() if r.get("current_price")}
            trade_res["summary"] = portfolio.get_summary(live_prices)
            self.send_json(trade_res)

        elif path == "/api/portfolio/toggle-auto-trade":
            global ai_auto_trading_enabled
            enabled = payload.get("enabled")
            if enabled is None:
                ai_auto_trading_enabled = not ai_auto_trading_enabled
            else:
                ai_auto_trading_enabled = bool(enabled)
            config["ai_auto_trading_enabled"] = ai_auto_trading_enabled
            save_config(config)
            self.send_json({"ai_auto_trading_enabled": ai_auto_trading_enabled})

        elif path == "/api/portfolio/reset":
            summary = portfolio.reset()
            self.send_json(summary)

        elif path == "/api/portfolio/report":
            live_prices = {sym: res.get("current_price", 0.0) for sym, res in cached_results.items() if res.get("current_price")}
            summary = portfolio.get_summary(live_prices)
            report = ai_assistant.generate_portfolio_report(summary)
            self.send_json(report)

        elif path == "/api/ai-trader/symbols":
            symbols = payload.get("symbols", [])
            enabled = payload.get("enabled", ai_auto_trading_enabled)
            cleaned_syms = list(dict.fromkeys([s.strip().upper() for s in symbols if s.strip()]))
            ai_trade_symbols = cleaned_syms
            ai_auto_trading_enabled = bool(enabled)
            config["ai_trade_symbols"] = ai_trade_symbols
            config["ai_auto_trading_enabled"] = ai_auto_trading_enabled
            save_config(config)
            self.send_json({
                "success": True,
                "selected": ai_trade_symbols,
                "enabled": ai_auto_trading_enabled,
                "count": len(ai_trade_symbols)
            })

        elif path == "/api/chat":
            message = payload.get("message", "").strip()
            symbol = payload.get("symbol", "")
            history = payload.get("history", [])

            if not message:
                self.send_json({"error": "Empty message"}, 400)
                return

            stock_ctx = None
            if symbol:
                if symbol in cached_results:
                    stock_ctx = cached_results[symbol]
                else:
                    resolved = client.resolve_symbol(symbol)
                    if resolved in cached_results:
                        stock_ctx = cached_results[resolved]
                    else:
                        raw = client.get_full_analysis(resolved)
                        if raw and raw.get("analyst"):
                            stock_ctx = strategy.analyze(raw)
                            cached_results[resolved] = stock_ctx

            # 1. Deterministic System Action Execution
            action_executed = execute_agentic_system_command(message, active_symbol=symbol or "NVDA")
            action_receipt = action_executed.get("summary") if action_executed else None

            # Build real-time live system state for AI full awareness
            live_prices = {k: v.get("current_price", 0.0) for k, v in cached_results.items() if v.get("current_price")}
            active_viewed_sym = payload.get("active_symbol") or symbol or "NVDA"
            active_tf = payload.get("timeframe", "1m").lower()

            chart_timing = None
            if stock_ctx and stock_ctx.get("timing"):
                chart_timing = stock_ctx.get("timing")
            else:
                resolved_viewed = client.resolve_symbol(active_viewed_sym)
                if resolved_viewed in cached_results and cached_results[resolved_viewed].get("timing") and cached_results[resolved_viewed].get("timeframe") == active_tf:
                    chart_timing = cached_results[resolved_viewed].get("timing")
                else:
                    raw_viewed = client.get_full_analysis(resolved_viewed, timeframe=active_tf)
                    if raw_viewed:
                        analyzed_viewed = strategy.analyze(raw_viewed)
                        analyzed_viewed["timeframe"] = active_tf
                        cached_results[resolved_viewed] = analyzed_viewed
                        chart_timing = analyzed_viewed.get("timing")
                        if not stock_ctx:
                            stock_ctx = analyzed_viewed

            system_state = {
                "practice_portfolio": practice_portfolio.get_summary(live_prices),
                "ai_fund": portfolio.get_summary(),
                "ai_trade_symbols": ai_trade_symbols,
                "ai_auto_trading_enabled": ai_auto_trading_enabled,
                "current_chart_symbol": active_viewed_sym,
                "chart_timing": chart_timing
            }

            # 2. Call AI Assistant with action receipt and system state
            res = ai_assistant.chat(message, stock_context=stock_ctx, history=history, action_receipt=action_receipt, system_state=system_state)

            # 3. If no deterministic action executed yet, check if LLM produced [ACTION: ...]
            if not action_executed and res.get("reply"):
                raw_reply = res["reply"]
                action_match = re.search(r'\[ACTION:\s*(\{.*?\})\]', raw_reply, re.DOTALL)
                if action_match:
                    try:
                        act_dict = json.loads(action_match.group(1))
                        action_executed = execute_action_dict(act_dict, active_symbol=symbol or "NVDA")
                        res["reply"] = raw_reply.replace(action_match.group(0), "").strip()
                    except Exception as e:
                        print(f"[ACTION PARSE ERROR] {e}")

            if action_executed:
                res["action_executed"] = action_executed
                clean_reply = re.sub(r'\[ACTION:\s*\{.*?\}\]', '', res.get("reply", ""), flags=re.DOTALL).strip()
                clean_reply = re.sub(r'<think>.*?</think>', '', clean_reply, flags=re.DOTALL).strip()
                if not clean_reply or res.get("error") or len(clean_reply) < 15 or clean_reply.lower().startswith("we need to") or clean_reply.lower().startswith("i need to"):
                    res["reply"] = f"⚡ **System Action Executed:** {action_executed.get('summary')}"
                else:
                    res["reply"] = clean_reply
                res["error"] = False

            self.send_json(res)

        elif path == "/api/webhook":
            webhook_url = payload.get("webhook_url", "").strip()
            config["discord_webhook_url"] = webhook_url
            save_config(config)
            notifier = Notifier(discord_webhook_url=webhook_url)
            ok = notifier.test_discord_connection()
            self.send_json({"success": ok, "webhook_url": webhook_url})

        elif path == "/api/notify":
            symbol = payload.get("symbol")
            if not symbol or symbol not in cached_results:
                resolved = client.resolve_symbol(symbol)
                raw = client.get_full_analysis(resolved)
                if raw and raw.get("analyst"):
                    cached_results[resolved] = strategy.analyze(raw)
                    symbol = resolved

            if symbol in cached_results:
                res = cached_results[symbol]
                only_phone = payload.get("only_phone", False)
                notifier = Notifier(
                    discord_webhook_url="" if only_phone else config.get("discord_webhook_url"),
                    enable_termux=True
                )
                status = notifier.notify(res)
                self.send_json(status)
            else:
                self.send_json({"error": "Symbol not analyzed yet"}, 400)

        elif path == "/api/trade-alert":
            symbol = payload.get("symbol", "")
            alert_type = payload.get("type", "BUY").upper()
            if not symbol or symbol not in cached_results:
                resolved = client.resolve_symbol(symbol)
                raw = client.get_full_analysis(resolved)
                if raw and raw.get("analyst"):
                    cached_results[resolved] = strategy.analyze(raw)
                    symbol = resolved
            if symbol in cached_results:
                notifier = Notifier(discord_webhook_url=config.get("discord_webhook_url"))
                res = notifier.send_trade_alert(cached_results[symbol], alert_type)
                self.send_json(res)
            else:
                self.send_json({"error": "Symbol not analyzed yet"}, 400)

        elif path == "/api/scan-and-notify":
            market = payload.get("market", "US").upper()
            symbols = config.get("watchlist_us", []) if market == "US" else config.get("watchlist_india", [])
            notifier = Notifier(discord_webhook_url=config.get("discord_webhook_url"))
            alerts_triggered = []

            with ThreadPoolExecutor(max_workers=8) as executor:
                future_to_sym = {executor.submit(client.get_full_analysis, s): s for s in symbols}
                for future in as_completed(future_to_sym):
                    try:
                        raw = future.result()
                        if raw and raw.get("analyst"):
                            res = strategy.analyze(raw)
                            cached_results[res["symbol"]] = res
                            triggers = res.get("triggers", {})
                            buy_t = triggers.get("buy", {})
                            sell_t = triggers.get("sell", {})

                            if buy_t.get("triggered"):
                                out = notifier.send_trade_alert(res, "BUY")
                                if out.get("alert"):
                                    alerts_triggered.append(out["alert"])
                            elif sell_t.get("triggered"):
                                out = notifier.send_trade_alert(res, "SELL")
                                if out.get("alert"):
                                    alerts_triggered.append(out["alert"])
                    except Exception:
                        pass

            self.send_json({
                "market": market,
                "scanned_count": len(symbols),
                "alerts_count": len(alerts_triggered),
                "alerts": alerts_triggered
            })

        elif path == "/api/auto-monitor":
            global auto_monitor_enabled
            enabled = payload.get("enabled", True)
            auto_monitor_enabled = enabled
            config["auto_monitor_enabled"] = enabled
            save_config(config)
            self.send_json({"auto_monitor_enabled": auto_monitor_enabled})

        else:
            self.send_response(404)
            self.end_headers()

def run_server(port: int = PORT):
    # Start background market monitor daemon thread
    monitor_thread = threading.Thread(target=background_market_monitor_loop, daemon=True)
    monitor_thread.start()

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"\n=======================================================")
    print(f"🚀 AI Market Terminal & Chatbot Live on Localhost!")
    print(f"👉 Real-Time TradingView & AI Chat: http://localhost:{port}")
    print(f"=======================================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web dashboard server.")
        server.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run_server(port)
