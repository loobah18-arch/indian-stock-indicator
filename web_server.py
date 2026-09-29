#!/usr/bin/env python3
import os
import sys
import json
import time
import threading
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Optional, List

from market_client import MarketClient
from strategy import IndicatorStrategy
from notifier import Notifier, get_alert_history
from ai_assistant import AIAssistant
from paper_trading import PaperPortfolio

PORT = 5000
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config() -> Dict[str, Any]:
    default_cfg = {
        "discord_webhook_url": "",
        "enable_termux_notification": True,
        "auto_monitor_enabled": True,
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

cached_results: Dict[str, Any] = {}
auto_monitor_enabled = config.get("auto_monitor_enabled", True)
alerted_triggers = set()

def background_market_monitor_loop():
    """Background daemon that periodically scans watchlists, checks portfolio stop losses, and dispatches Buy and Sell alerts."""
    while True:
        try:
            if auto_monitor_enabled:
                notifier = Notifier(discord_webhook_url=config.get("discord_webhook_url"))
                all_syms = config.get("watchlist_us", []) + config.get("watchlist_india", [])
                for s in all_syms:
                    if not auto_monitor_enabled:
                        break
                    try:
                        resolved = client.resolve_symbol(s)
                        raw = client.get_full_analysis(resolved)
                        if raw and raw.get("analyst"):
                            res = strategy.analyze(raw)
                            cached_results[res["symbol"]] = res
                            triggers = res.get("triggers", {})
                            buy_t = triggers.get("buy", {})
                            sell_t = triggers.get("sell", {})

                            if buy_t.get("triggered"):
                                key = (res["symbol"], "BUY")
                                if key not in alerted_triggers:
                                    notifier.send_trade_alert(res, "BUY")
                                    alerted_triggers.add(key)
                            else:
                                alerted_triggers.discard((res["symbol"], "BUY"))

                            if sell_t.get("triggered"):
                                key = (res["symbol"], sell_t.get("type", "SELL"))
                                if key not in alerted_triggers:
                                    notifier.send_trade_alert(res, "SELL")
                                    alerted_triggers.add(key)
                            else:
                                for st in ["TAKE_PROFIT_1", "TAKE_PROFIT_2", "STOP_LOSS_HIT", "OVERBOUGHT_TRIM", "BEARISH_BREAKDOWN"]:
                                    alerted_triggers.discard((res["symbol"], st))
                    except Exception:
                        pass

                # Check active virtual portfolio positions against live prices for TP / SL hits
                if portfolio.positions:
                    live_prices = {sym: r.get("current_price", 0.0) for sym, r in cached_results.items() if r.get("current_price")}
                    portfolio.evaluate_live_stops(live_prices)
        except Exception:
            pass
        time.sleep(180)

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

    <!-- Market Selector Tabs -->
    <div class="market-tabs">
      <div class="market-tab active" id="tabUS" onclick="switchMarket('US')">
        <span>🇺🇸 US Market (NASDAQ / NYSE)</span>
      </div>
      <div class="market-tab" id="tabIN" onclick="switchMarket('IN')">
        <span>🇮🇳 Indian Market (NSE / BSE)</span>
      </div>
    </div>

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
      <div class="card-title">
        <span>TradingView Real-Time Candlestick Chart (RSI, MACD, EMAs)</span>
        <span id="tvSymbolLabel" style="font-family: var(--font-mono); font-weight: 600; color: var(--blue);">NASDAQ:NVDA</span>
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

    <!-- VIRTUAL $1,000 AI PORTFOLIO & PROBABILITY AUDIT SECTION -->
    <div class="card" style="margin-top: 20px;" id="portfolioSection">
      <div class="card-title" style="flex-wrap: wrap; gap: 8px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 14px; font-weight: 700; color: #fff;">💼 Virtual $1,000 AI Paper Portfolio</span>
          <span class="ai-model-badge" style="background: rgba(59, 130, 246, 0.15); color: #60a5fa; border-color: rgba(59, 130, 246, 0.3);">Signal Verification Mode</span>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
          <button class="primary" onclick="autoInvestTopPicks()" style="background: #10b981; border-color: #10b981; font-weight: 600;" title="Deploy virtual credits into top scoring confluence setups">
            🤖 Auto-Invest $1,000 in Top AI Picks
          </button>
          <button class="primary" onclick="openAIReportModal()" style="background: #8b5cf6; border-color: #8b5cf6; font-weight: 600;" title="Generate institutional AI P&L and probability verification report">
            📊 Generate AI P&L Report
          </button>
          <button onclick="resetPortfolioCredits()" style="border-color: #475569;" title="Reset virtual credits back to $1,000.00">
            ↺ Reset ($1,000)
          </button>
        </div>
      </div>

      <!-- Stat Cards Grid -->
      <div class="portfolio-stats-grid">
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
          <div class="exec-label">Win Rate & Factor</div>
          <div class="stat-big-val" id="portWinRate">0.0%</div>
          <div class="stat-sub-val" id="portProfitFactor">Profit Factor: 1.00</div>
        </div>
      </div>

      <!-- Subgrid: Active Positions & Closed History -->
      <div style="display: grid; grid-template-columns: 1fr; gap: 16px; margin-top: 14px;">
        <!-- Active Positions Table -->
        <div>
          <div class="card-title" style="margin-bottom: 8px;">
            <span>🟢 Active Positions Under Forward Test</span>
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
                  <th>Action</th>
                </tr>
              </thead>
              <tbody id="portOpenTableBody">
                <tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 18px;">No active positions. Click "🤖 Auto-Invest $1,000 in Top AI Picks" or buy with virtual credits above.</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Trade History Table -->
        <div>
          <div class="card-title" style="margin-bottom: 8px;">
            <span>📜 Closed Trade History & Realized P&L</span>
            <span id="portTradeHistoryMeta" style="font-family: var(--font-mono); font-size: 11px;">0 trades</span>
          </div>
          <div class="table-container">
            <table>
              <thead>
                <tr>
                  <th>Asset</th>
                  <th>Entry ➔ Exit</th>
                  <th>Invested</th>
                  <th>Proceeds</th>
                  <th>Realized P&L</th>
                  <th>Result</th>
                  <th>Exit Reason</th>
                  <th>Exit Time</th>
                </tr>
              </thead>
              <tbody id="portHistoryTableBody">
                <tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 18px;">No closed trades yet. Stop-Loss and Take-Profit automated triggers will log executions here.</td></tr>
              </tbody>
            </table>
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
        <span>🤖 AlphaQuant AI</span>
        <span class="ai-model-badge">Free 120B / MoE</span>
      </div>
      <button onclick="toggleChatDrawer()" style="background: none; border: none; color: #94a3b8; font-size: 16px; padding: 0 4px; cursor: pointer;">✕</button>
    </div>

    <div class="ai-context-chip" id="aiContextChip">
      <span>🎯 Target:</span>
      <strong id="aiActiveSym" style="color: #60a5fa;">NVDA</strong>
      <span id="aiActivePrice">($229.35)</span>
    </div>

    <div class="ai-quick-prompts">
      <div class="quick-chip" onclick="askQuickPrompt('Analyze the current setup for this stock: entry, risk, and technical bias.')">⚡ Full Analysis</div>
      <div class="quick-chip" onclick="askQuickPrompt('Explain the Stop Loss level and maximum drawdown risk.')">🛑 Stop Loss Audit</div>
      <div class="quick-chip" onclick="askQuickPrompt('Compare the institutional analyst price targets vs the current technical momentum.')">🎯 Price Target vs RSI</div>
      <div class="quick-chip" onclick="askQuickPrompt('Is this in an accumulation or distribution phase based on RVOL and EMAs?')">📊 Volume & Phase</div>
    </div>

    <div class="ai-chat-messages" id="aiChatMessages">
      <div class="chat-bubble assistant">
        Hello! I'm <strong>AlphaQuant AI</strong>. I have real-time access to live quantitative indicators, institutional consensus, and exact Stop-Loss / Take-Profit calculations for both US and Indian equities.<br><br>
        Ask me anything about the active stock or overall market structure!
      </div>
    </div>

    <div class="ai-chat-footer">
      <input type="text" id="aiChatInput" placeholder="Ask about this stock..." onkeydown="if(event.key==='Enter') sendChatMessage()">
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
    let activeResult = null;
    let chatHistory = [];

    const US_PILLS = ['NVDA', 'AAPL', 'MSFT', 'TSLA', 'AMZN', 'META', 'AMD', 'SPY', 'QQQ'];
    const IN_PILLS = ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS', 'TATAMOTORS.NS', 'SBIN.NS'];

    const US_EXCHANGE_MAP = {
      'SPY': 'AMEX', 'DIA': 'AMEX', 'IWM': 'AMEX',
      'BABA': 'NYSE', 'DIS': 'NYSE', 'BA': 'NYSE', 'JPM': 'NYSE', 'V': 'NYSE', 'WMT': 'NYSE', 'ORCL': 'NYSE', 'CRM': 'NYSE', 'NKE': 'NYSE', 'UBER': 'NYSE',
      'NVDA': 'NASDAQ', 'AAPL': 'NASDAQ', 'MSFT': 'NASDAQ', 'TSLA': 'NASDAQ', 'AMZN': 'NASDAQ', 'GOOGL': 'NASDAQ', 'GOOG': 'NASDAQ', 'META': 'NASDAQ', 'AMD': 'NASDAQ', 'QQQ': 'NASDAQ', 'NFLX': 'NASDAQ', 'INTC': 'NASDAQ', 'AVGO': 'NASDAQ', 'COIN': 'NASDAQ', 'PLTR': 'NASDAQ', 'SMCI': 'NASDAQ', 'ARM': 'NASDAQ'
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

    function updateTradingViewChart(symbol) {
      const tvSym = toTradingViewSymbol(symbol);
      document.getElementById('tvSymbolLabel').innerText = tvSym;
      
      const iframe = document.getElementById('tradingview_iframe');
      const targetSrc = "https://s.tradingview.com/widgetembed/?symbol=" + encodeURIComponent(tvSym) +
        "&interval=D&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=131722&studies=RSI%40tv-basicstudies%1BMACD%40tv-basicstudies%1BMASimple%40tv-basicstudies&theme=dark&style=1&timezone=exchange&withdateranges=1&showpopupbutton=1";
      
      if (iframe.src !== targetSrc) {
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

    function switchMarket(market) {
      currentMarket = market;
      document.getElementById('tabUS').className = 'market-tab' + (market === 'US' ? ' active' : '');
      document.getElementById('tabIN').className = 'market-tab' + (market === 'IN' ? ' active' : '');
      document.getElementById('tickerInput').placeholder = market === 'US' 
        ? 'Search any US stock (e.g. NVDA, AAPL, TSLA, MSFT, SPY)' 
        : 'Search any Indian stock (e.g. RELIANCE, TCS, HDFCBANK, INFY)';
      updatePills();
      fetchMarketOverview(false);
      const defaultTicker = market === 'US' ? 'NVDA' : 'RELIANCE.NS';
      analyzeSpecific(defaultTicker);
      scanMarketWatchlist(false);
    }

    async function analyzeSpecific(sym) {
      showToast('Analyzing ' + sym + '...');
      updateTradingViewChart(sym);

      try {
        const res = await fetch('/api/analyze?ticker=' + encodeURIComponent(sym));
        const data = await res.json();
        if (data && data.symbol) {
          renderActiveTicker(data);
        } else {
          showToast('Failed to fetch data for: ' + sym);
        }
      } catch (e) {
        showToast('Error analyzing ' + sym + ': ' + e);
      }
    }

    async function searchTicker() {
      const val = document.getElementById('tickerInput').value.trim();
      if (!val) return;
      analyzeSpecific(val);
    }

    function renderActiveTicker(data) {
      activeResult = data;
      document.getElementById('updateTime').innerText = 'Live • ' + new Date().toLocaleTimeString();
      document.getElementById('heroSymbol').innerText = data.symbol;
      document.getElementById('heroName').innerText = data.name || data.symbol;

      const curr = data.currency || (data.symbol.includes('.NS') ? 'INR' : 'USD');
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
            symbol: activeResult ? activeResult.symbol : 'NVDA',
            history: chatHistory
          })
        });
        const data = await res.json();
        typingBubble.remove();

        const replyBubble = document.createElement('div');
        replyBubble.className = 'chat-bubble assistant';
        replyBubble.innerHTML = formatMarkdown(data.reply || 'No response.');
        chatBox.appendChild(replyBubble);
        chatBox.scrollTop = chatBox.scrollHeight;

        chatHistory.push({role: 'assistant', content: data.reply || ''});
      } catch (e) {
        typingBubble.innerHTML = '<span style="color:#ef4444;">Error getting response: ' + e + '</span>';
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
      const winRateEl = document.getElementById('portWinRate');
      const factorEl = document.getElementById('portProfitFactor');

      if (equityEl) equityEl.innerText = '$' + data.total_equity.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
      if (returnEl) {
        const sign = data.total_pnl >= 0 ? '+' : '';
        returnEl.innerText = `${sign}$${data.total_pnl.toFixed(2)} (${sign}${data.total_pnl_pct.toFixed(2)}%) Overall`;
        returnEl.style.color = data.total_pnl >= 0 ? 'var(--green)' : 'var(--red)';
      }
      if (cashEl) cashEl.innerText = '$' + data.cash.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
      
      if (realizedEl) {
        const sign = data.realized_pnl >= 0 ? '+' : '';
        realizedEl.innerText = `${sign}$${data.realized_pnl.toFixed(2)}`;
        realizedEl.style.color = data.realized_pnl >= 0 ? 'var(--green)' : 'var(--red)';
      }
      if (closedTradesEl) closedTradesEl.innerText = `${data.total_trades} Closed Trades (${data.wins}W / ${data.losses}L)`;

      if (unrealizedEl) {
        const sign = data.unrealized_pnl >= 0 ? '+' : '';
        unrealizedEl.innerText = `${sign}$${data.unrealized_pnl.toFixed(2)}`;
        unrealizedEl.style.color = data.unrealized_pnl >= 0 ? 'var(--green)' : 'var(--red)';
      }
      if (openCountEl) openCountEl.innerText = `${data.open_positions_count} Active Holdings`;

      if (winRateEl) {
        winRateEl.innerText = `${data.win_rate_pct.toFixed(1)}%`;
        winRateEl.style.color = data.win_rate_pct >= 50 ? 'var(--green)' : (data.total_trades === 0 ? 'inherit' : 'var(--red)');
      }
      if (factorEl) factorEl.innerText = `Profit Factor: ${data.profit_factor.toFixed(2)}`;

      // Render Open Positions Table
      const openTbody = document.getElementById('portOpenTableBody');
      const openMeta = document.getElementById('portOpenPositionsMeta');
      if (openMeta) openMeta.innerText = `${data.positions.length} active positions`;

      if (openTbody) {
        if (!data.positions || data.positions.length === 0) {
          openTbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 18px;">No active positions. Click "🤖 Auto-Invest $1,000 in Top AI Picks" or buy with virtual credits above.</td></tr>';
        } else {
          openTbody.innerHTML = '';
          data.positions.forEach(p => {
            const tr = document.createElement('tr');
            const sign = p.unrealized_pnl >= 0 ? '+' : '';
            const colorClass = p.unrealized_pnl >= 0 ? 'color: var(--green);' : 'color: var(--red);';
            const currSymbol = p.currency === 'INR' ? '₹' : '$';
            tr.innerHTML = `
              <td><strong style="color: #60a5fa; cursor: pointer;" onclick="loadSingleStock('${p.symbol}')">${p.symbol}</strong></td>
              <td style="font-family: var(--font-mono);">${p.shares}</td>
              <td style="font-family: var(--font-mono);">${currSymbol}${p.entry_price.toFixed(2)}</td>
              <td style="font-family: var(--font-mono);">${currSymbol}${p.current_price.toFixed(2)}</td>
              <td style="font-family: var(--font-mono);">$${p.invested.toFixed(2)}</td>
              <td style="font-family: var(--font-mono); font-weight: 600;">$${p.current_value.toFixed(2)}</td>
              <td style="font-family: var(--font-mono); font-weight: 700; ${colorClass}">${sign}$${p.unrealized_pnl.toFixed(2)} (${sign}${p.unrealized_pct.toFixed(2)}%)</td>
              <td style="font-family: var(--font-mono); color: var(--red);">${p.stop_loss ? currSymbol + p.stop_loss.toFixed(2) : '-'}</td>
              <td style="font-family: var(--font-mono); color: var(--green);">${p.take_profit_1 ? currSymbol + p.take_profit_1.toFixed(2) : '-'}</td>
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

      // Render Closed Trades Table
      const histTbody = document.getElementById('portHistoryTableBody');
      const histMeta = document.getElementById('portTradeHistoryMeta');
      if (histMeta) histMeta.innerText = `${data.trade_history.length} trades recorded`;

      if (histTbody) {
        if (!data.trade_history || data.trade_history.length === 0) {
          histTbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 18px;">No closed trades yet. Automated Stop-Loss and Take-Profit rules will log executions here.</td></tr>';
        } else {
          histTbody.innerHTML = '';
          data.trade_history.forEach(t => {
            const tr = document.createElement('tr');
            const sign = t.pnl_amount >= 0 ? '+' : '';
            const colorClass = t.pnl_amount >= 0 ? 'color: var(--green);' : 'color: var(--red);';
            const currSymbol = t.currency === 'INR' ? '₹' : '$';
            const resultBadge = t.result === 'WIN' 
              ? '<span class="status-pill strong-buy">WIN</span>' 
              : '<span class="status-pill sell">LOSS</span>';
            tr.innerHTML = `
              <td><strong>${t.symbol}</strong></td>
              <td style="font-family: var(--font-mono);">${currSymbol}${t.entry_price.toFixed(2)} ➔ ${currSymbol}${t.exit_price.toFixed(2)}</td>
              <td style="font-family: var(--font-mono);">$${t.invested.toFixed(2)}</td>
              <td style="font-family: var(--font-mono);">$${t.proceeds.toFixed(2)}</td>
              <td style="font-family: var(--font-mono); font-weight: 700; ${colorClass}">${sign}$${t.pnl_amount.toFixed(2)} (${sign}${t.pnl_pct.toFixed(2)}%)</td>
              <td>${resultBadge}</td>
              <td style="font-size: 11px; font-family: var(--font-mono); color: #94a3b8;">${t.exit_reason}</td>
              <td style="font-size: 11px; color: var(--text-muted);">${t.exit_time || '-'}</td>
            `;
            histTbody.appendChild(tr);
          });
        }
      }
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

    // Startup
    loadConfig();
    switchMarket('US');
    fetchMarketOverview(false);
    fetchAlertsHistory();
    fetchPortfolio();
    setInterval(fetchPortfolio, 10000);
    setInterval(fetchAlertsHistory, 15000);
    setInterval(() => fetchMarketOverview(false), 60000);
  </script>
</body>
</html>
"""

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

        elif path == "/api/analyze":
            ticker = query.get("ticker", [""])[0]
            if not ticker:
                self.send_json({"error": "Missing ticker parameter"}, 400)
                return
            resolved = client.resolve_symbol(ticker)
            raw = client.get_full_analysis(resolved)
            if not raw or not raw.get("analyst"):
                self.send_json({"error": f"Failed to fetch data for {resolved}"}, 404)
                return
            result = strategy.analyze(raw)
            cached_results[result["symbol"]] = result
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

        elif path == "/api/market-overview":
            market = query.get("market", ["US"])[0].upper()
            overview = client.get_market_overview(market)
            self.send_json(overview)

        elif path == "/api/alerts":
            limit = int(query.get("limit", [50])[0])
            self.send_json(get_alert_history(limit))

        elif path == "/api/portfolio":
            live_prices = {sym: res.get("current_price", 0.0) for sym, res in cached_results.items() if res.get("current_price")}
            self.send_json(portfolio.get_summary(live_prices))

        elif path == "/api/portfolio/report":
            live_prices = {sym: res.get("current_price", 0.0) for sym, res in cached_results.items() if res.get("current_price")}
            summary = portfolio.get_summary(live_prices)
            report = ai_assistant.generate_portfolio_report(summary)
            self.send_json(report)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
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
            price = float(payload.get("price", 0.0))
            allocation = float(payload.get("allocation", 250.0))
            sl = float(payload.get("stop_loss", 0.0))
            tp1 = float(payload.get("take_profit_1", 0.0))
            tp2 = float(payload.get("take_profit_2", 0.0))
            score = int(payload.get("score", 50))
            signal = payload.get("signal", "BUY")
            curr = payload.get("currency", "USD")
            res = portfolio.buy(sym, price, allocation, sl, tp1, tp2, score, signal, curr)
            self.send_json(res)

        elif path == "/api/portfolio/sell":
            sym = payload.get("symbol", "").upper().strip()
            price = float(payload.get("price", 0.0))
            reason = payload.get("reason", "MANUAL")
            res = portfolio.sell(sym, price, exit_reason=reason)
            self.send_json(res)

        elif path == "/api/portfolio/auto-invest":
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
            executed = portfolio.auto_invest_top_picks(stocks, max_positions=4)
            live_prices = {s: r.get("current_price", 0.0) for s, r in cached_results.items() if r.get("current_price")}
            self.send_json({"executed": executed, "summary": portfolio.get_summary(live_prices)})

        elif path == "/api/portfolio/reset":
            summary = portfolio.reset()
            self.send_json(summary)

        elif path == "/api/portfolio/report":
            live_prices = {sym: res.get("current_price", 0.0) for sym, res in cached_results.items() if res.get("current_price")}
            summary = portfolio.get_summary(live_prices)
            report = ai_assistant.generate_portfolio_report(summary)
            self.send_json(report)

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

            res = ai_assistant.chat(message, stock_context=stock_ctx, history=history)
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
