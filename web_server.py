#!/usr/bin/env python3
import os
import sys
import json
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Optional, List

from market_client import MarketClient
from strategy import IndicatorStrategy
from notifier import Notifier
from ai_assistant import AIAssistant

PORT = 5000
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config() -> Dict[str, Any]:
    default_cfg = {
        "discord_webhook_url": "",
        "enable_termux_notification": True,
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

cached_results: Dict[str, Any] = {}

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
        <button onclick="rescanActiveMarket()" class="primary">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
          Rescan Watchlist
        </button>
        <button onclick="sendPhonePush()">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>
          Phone Alert
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

        <p id="rationaleText" style="font-size: 12px; color: var(--text-muted); line-height: 1.6;"></p>
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

    // Startup
    loadConfig();
    switchMarket('US');
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

        if path == "/api/chat":
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

        else:
            self.send_response(404)
            self.end_headers()

def run_server(port: int = PORT):
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
