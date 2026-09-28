#!/usr/bin/env python3
import os
import sys
import json
import time
import argparse
from typing import List, Dict, Any, Optional

from market_client import MarketClient, normalize_symbol
from strategy import IndicatorStrategy
from notifier import Notifier

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config() -> Dict[str, Any]:
    default_config = {
        "discord_webhook_url": "",
        "enable_termux_notification": True,
        "min_upside_for_buy_pct": 5.0,
        "rsi_overbought": 72.0,
        "rsi_oversold": 30.0,
        "notify_on": ["STRONG BUY", "BUY", "STRONG SELL", "SELL"],
        "watchlist": [
            "RELIANCE.NS",
            "TCS.NS",
            "HDFCBANK.NS",
            "INFY.NS",
            "ICICIBANK.NS",
            "BHARTIARTL.NS",
            "SBIN.NS",
            "LT.NS",
            "ITC.NS",
            "AXISBANK.NS",
            "SUNPHARMA.NS",
            "MARUTI.NS"
        ]
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_config.update(saved)
        except Exception:
            pass
    return default_config

def save_config(cfg: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

# ANSI terminal colors
GREEN = "\033[92m"
BRIGHT_GREEN = "\033[1;92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BRIGHT_RED = "\033[1;91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def color_signal(signal: str) -> str:
    if signal == "STRONG BUY":
        return f"{BRIGHT_GREEN}🟢 {signal}{RESET}"
    elif signal == "BUY":
        return f"{GREEN}🟢 {signal}{RESET}"
    elif signal == "HOLD":
        return f"{YELLOW}🟡 {signal}{RESET}"
    elif signal == "SELL":
        return f"{RED}🔴 {signal}{RESET}"
    elif signal == "STRONG SELL":
        return f"{BRIGHT_RED}🔴 {signal}{RESET}"
    return signal

def analyze_and_notify(
    symbols: List[str],
    client: MarketClient,
    strategy: IndicatorStrategy,
    notifier: Notifier,
    notify_signals: List[str],
    send_all_signals: bool = False
) -> List[Dict[str, Any]]:
    results = []
    print(f"\n{BOLD}{CYAN}=== Dalal Street Quantitative Precision Market Scanner ==={RESET}")
    print(f"{'Symbol':<14} {'Price (₹)':<11} {'Score':<8} {'Upside':<9} {'RSI':<7} {'R:R':<6} {'Stop Loss':<12} {'TP1 (Swing)':<12} {'Signal':<16}")
    print("-" * 98)

    for sym in symbols:
        raw_data = client.get_full_analysis(sym)
        if not raw_data or not raw_data.get("analyst"):
            print(f"{normalize_symbol(sym):<14} {'[Data Unavailable / Not Found]':<70}")
            continue

        result = strategy.analyze(raw_data)
        results.append(result)

        symbol_name = result["symbol"]
        price = result["current_price"]
        score = result.get("score", 50)
        upside = result.get("upside_pct", 0.0)
        tech = result.get("technicals", {})
        rsi = tech.get("rsi_14")
        exec_plan = result.get("execution", {})
        sl = exec_plan.get("stop_loss", 0.0)
        tp1 = exec_plan.get("take_profit_1", 0.0)
        rr = exec_plan.get("risk_reward_tp1", 0.0)
        signal = result["signal"]

        price_str = f"₹{price:,.2f}" if price else "N/A"
        upside_str = f"{'+' if upside > 0 else ''}{upside:.1f}%"
        rsi_str = f"{rsi:.1f}" if rsi is not None else "-"
        sl_str = f"₹{sl:,.1f}" if sl else "-"
        tp1_str = f"₹{tp1:,.1f}" if tp1 else "-"
        score_str = f"{score}/100"
        rr_str = f"1:{rr:.1f}"

        print(f"{symbol_name:<14} {price_str:<11} {score_str:<8} {upside_str:<9} {rsi_str:<7} {rr_str:<6} {sl_str:<12} {tp1_str:<12} {color_signal(signal):<16}")

        should_notify = send_all_signals or (signal in notify_signals)
        if should_notify:
            status = notifier.notify(result)
            notes = []
            if status["discord"]:
                notes.append("Discord sent")
            if status["termux"]:
                notes.append("Termux push sent")
            if notes:
                print(f"  └─ Notification: {', '.join(notes)}")

    print("-" * 98)
    return results

def main():
    parser = argparse.ArgumentParser(
        description="Dalal Street Quantitative AI Indicator — 5-Pillar Confluence Engine & Localhost Web Dashboard."
    )
    parser.add_argument(
        "-t", "--ticker",
        nargs="+",
        help="One or more Indian stock tickers (e.g. RELIANCE, TCS, INFY, HDFCBANK)"
    )
    parser.add_argument(
        "--web", "--serve",
        action="store_true",
        help="Launch the live interactive web dashboard on localhost"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for the web dashboard (default: 8080)"
    )
    parser.add_argument(
        "--set-webhook",
        type=str,
        help="Set and save your Discord Webhook URL"
    )
    parser.add_argument(
        "--test-webhook",
        action="store_true",
        help="Send a test message to your configured Discord webhook"
    )
    parser.add_argument(
        "-w", "--watch",
        action="store_true",
        help="Run continuously in watch/monitoring mode"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Interval in seconds for watch mode (default: 300s / 5 mins)"
    )
    parser.add_argument(
        "--all-signals",
        action="store_true",
        help="Send notifications for all signals (including HOLD)"
    )
    parser.add_argument(
        "--no-termux",
        action="store_true",
        help="Disable native Termux Android notifications"
    )

    args = parser.parse_args()
    config = load_config()

    if args.web or args.serve:
        from web_server import run_server
        run_server(args.port)
        return

    if args.set_webhook:
        config["discord_webhook_url"] = args.set_webhook.strip()
        save_config(config)
        print(f"{GREEN}✓ Discord Webhook URL saved successfully to config.json!{RESET}")
        notifier = Notifier(discord_webhook_url=config["discord_webhook_url"])
        print("Sending test ping to Discord...")
        if notifier.test_discord_connection():
            print(f"{GREEN}✓ Test ping delivered to Discord!{RESET}")
        else:
            print(f"{RED}✗ Failed to send test ping. Please check your Webhook URL.{RESET}")
        return

    webhook_url = config.get("discord_webhook_url") or os.environ.get("DISCORD_WEBHOOK_URL", "")
    enable_termux = config.get("enable_termux_notification", True) and not args.no_termux

    notifier = Notifier(discord_webhook_url=webhook_url, enable_termux=enable_termux)

    if args.test_webhook:
        if not webhook_url:
            print(f"{RED}Error: Discord webhook is not set. Use --set-webhook <URL> to configure.{RESET}")
            sys.exit(1)
        print("Sending test ping to Discord...")
        if notifier.test_discord_connection():
            print(f"{GREEN}✓ Test ping delivered to Discord!{RESET}")
        else:
            print(f"{RED}✗ Failed to deliver test ping to Discord.{RESET}")
        return

    if not webhook_url:
        print(f"{YELLOW}[Notice] Discord Webhook URL is not configured yet.{RESET}")
        print(f"You can set it anytime with: {BOLD}python indicator.py --set-webhook <YOUR_DISCORD_WEBHOOK_URL>{RESET}")
        print(f"Android status bar notifications ({'enabled' if enable_termux else 'disabled'}) will still deliver directly to your phone.\n")

    client = MarketClient()
    strategy = IndicatorStrategy(
        min_upside_pct=config.get("min_upside_for_buy_pct", 5.0),
        rsi_overbought=config.get("rsi_overbought", 72.0),
        rsi_oversold=config.get("rsi_oversold", 30.0),
    )

    symbols = args.ticker if args.ticker else config.get("watchlist", [])

    if args.watch:
        print(f"{CYAN}Starting continuous monitoring mode every {args.interval} seconds. Press Ctrl+C to stop.{RESET}")
        try:
            while True:
                analyze_and_notify(
                    symbols,
                    client,
                    strategy,
                    notifier,
                    config.get("notify_on", ["STRONG BUY", "BUY", "STRONG SELL", "SELL"]),
                    send_all_signals=args.all_signals
                )
                print(f"\nSleeping for {args.interval}s until next check...")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print(f"\n{YELLOW}Monitoring stopped.{RESET}")
    else:
        results = analyze_and_notify(
            symbols,
            client,
            strategy,
            notifier,
            config.get("notify_on", ["STRONG BUY", "BUY", "STRONG SELL", "SELL"]),
            send_all_signals=args.all_signals
        )
        buys = [r for r in results if "BUY" in r.get("signal", "")]
        if buys:
            best_buy = max(buys, key=lambda x: x.get("score", 0))
            ex = best_buy.get("execution", {})
            print(f"\n{BRIGHT_GREEN}★ TOP HIGH-PRECISION PICK: {best_buy['symbol']} ({best_buy['name']}){RESET}")
            print(f"  Precision Score: {best_buy['score']}/100 ({best_buy['conviction']})")
            print(f"  Current Price: ₹{best_buy['current_price']:,.2f} | Entry Zone: {ex.get('entry_zone')}")
            print(f"  Stop Loss: ₹{ex.get('stop_loss', 0):,.2f} (-{ex.get('sl_risk_pct')}%) | TP1: ₹{ex.get('take_profit_1', 0):,.2f} (+{ex.get('tp1_gain_pct')}%)")
            print(f"  Target 2 (Analyst Mean): ₹{best_buy.get('target_price', 0):,.2f} (+{best_buy['upside_pct']}%) | Risk-Reward: 1 : {ex.get('risk_reward_tp1')}")
            print(f"  Rationale: {best_buy['rationale']}\n")

if __name__ == "__main__":
    main()
