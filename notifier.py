import os
import json
import subprocess
import requests
from datetime import datetime, timezone
from typing import Dict, Any, Optional

class Notifier:
    """Delivers market alerts to Discord Webhook and native Android (Termux) notifications for US & Indian markets."""

    def __init__(self, discord_webhook_url: Optional[str] = None, enable_termux: bool = True):
        self.webhook_url = discord_webhook_url or os.environ.get("DISCORD_WEBHOOK_URL") or ""
        self.enable_termux = enable_termux

    def send_discord_alert(self, result: Dict[str, Any]) -> bool:
        """Sends a rich Discord embed card for a BUY/SELL/HOLD signal with exact execution levels."""
        if not self.webhook_url:
            return False

        sym = result["symbol"]
        name = result.get("name", sym)
        signal = result["signal"]
        action = result.get("action_verb", signal)
        score = result.get("score", 50)
        conviction = result.get("conviction", "Moderate")
        price = result.get("current_price", 0.0)
        currency = result.get("currency", "INR")
        curr_sym = "$" if currency == "USD" else "₹"
        market_label = "US Equities (NASDAQ/NYSE)" if currency == "USD" else "NSE India (National Stock Exchange)"

        target = result.get("target_price")
        upside = result.get("upside_pct", 0.0)
        breakdown = result.get("breakdown", {})
        rationale = result.get("rationale", "")
        color = result.get("color", 0x3498DB)

        execution = result.get("execution", {})
        sl = execution.get("stop_loss", 0.0)
        sl_pct = execution.get("sl_risk_pct", 0.0)
        tp1 = execution.get("take_profit_1", 0.0)
        tp1_pct = execution.get("tp1_gain_pct", 0.0)
        tp2 = execution.get("take_profit_2", target or 0.0)
        tp2_pct = execution.get("tp2_gain_pct", upside)
        rr = execution.get("risk_reward_tp1", 0.0)
        entry_zone = execution.get("entry_zone", f"{curr_sym}{price:,.2f}")

        tech = result.get("technicals", {})
        rsi = tech.get("rsi_14")
        rvol = tech.get("rvol", 1.0)
        above_200 = tech.get("above_ema200")

        emoji = "🟢" if "BUY" in signal else ("🔴" if "SELL" in signal else "🟡")
        rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
        
        strong_b = breakdown.get("strongBuy", 0)
        b = breakdown.get("buy", 0)
        h = breakdown.get("hold", 0)
        s = breakdown.get("sell", 0)
        strong_s = breakdown.get("strongSell", 0)
        consensus_str = f"{strong_b + b} Buy | {h} Hold | {s + strong_s} Sell"

        embed = {
            "title": f"{emoji} [{signal}] {sym} — {name}",
            "description": f"**Action:** `{action}` | **Precision Score:** `{score}/100` ({conviction})\n\n**Strategy Analysis:**\n{rationale}",
            "color": color,
            "fields": [
                {
                    "name": "💰 Current Price",
                    "value": f"{curr_sym}{price:,.2f}",
                    "inline": True,
                },
                {
                    "name": "🎯 TP1 (Swing)",
                    "value": f"{curr_sym}{tp1:,.2f} (+{tp1_pct:.1f}%)",
                    "inline": True,
                },
                {
                    "name": "🛑 Stop Loss",
                    "value": f"{curr_sym}{sl:,.2f} (-{sl_pct:.1f}%)",
                    "inline": True,
                },
                {
                    "name": "🎯 TP2 (Analyst Target)",
                    "value": f"{curr_sym}{tp2:,.2f} (+{tp2_pct:.1f}%)" if tp2 else "N/A",
                    "inline": True,
                },
                {
                    "name": "⚖️ Risk / Reward",
                    "value": f"1 : {rr:.1f}",
                    "inline": True,
                },
                {
                    "name": "📍 Entry Zone",
                    "value": entry_zone,
                    "inline": True,
                },
                {
                    "name": "👥 Expert Breakdown",
                    "value": consensus_str,
                    "inline": True,
                },
                {
                    "name": "📊 Momentum & Volume",
                    "value": f"RSI: {rsi_str} | RVOL: {rvol:.2f}x",
                    "inline": True,
                },
                {
                    "name": "🏛️ Market",
                    "value": market_label,
                    "inline": True,
                },
            ],
            "footer": {
                "text": "Quantitative AI Market Indicator • Wall Street & Dalal Street Confluence",
                "icon_url": "https://img.icons8.com/color/512/bullish.png"
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        payload = {
            "username": "Stock Market AI Indicator",
            "avatar_url": "https://img.icons8.com/color/512/bullish.png",
            "embeds": [embed]
        }

        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code in [200, 204]
        except Exception:
            return False

    def send_termux_notification(self, result: Dict[str, Any]) -> bool:
        """Sends native Android notification via termux-notification CLI."""
        if not self.enable_termux:
            return False

        sym = result["symbol"]
        signal = result["signal"]
        action = result.get("action_verb", signal)
        score = result.get("score", 50)
        price = result.get("current_price", 0.0)
        currency = result.get("currency", "INR")
        curr_sym = "$" if currency == "USD" else "₹"
        execution = result.get("execution", {})
        sl = execution.get("stop_loss", 0.0)
        tp1 = execution.get("take_profit_1", 0.0)
        target = result.get("target_price")
        upside = result.get("upside_pct", 0.0)

        title = f"[{signal}] {sym} (Score: {score}/100) @ {curr_sym}{price:,.2f}"
        content = f"Action: {action}\nEntry: {execution.get('entry_zone', '')} | SL: {curr_sym}{sl:,.1f} | TP1: {curr_sym}{tp1:,.1f}\nTarget: {curr_sym}{target:,.1f} (+{upside:.1f}%)" if target else f"Action: {action}\nSL: {curr_sym}{sl:,.1f} | TP1: {curr_sym}{tp1:,.1f}"

        try:
            cmd = [
                "termux-notification",
                "--title", title,
                "--content", content,
                "--priority", "high",
                "--vibrate", "200,200",
                "--id", f"stock_{sym.replace('.', '_')}"
            ]
            subprocess.run(cmd, capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    def notify(self, result: Dict[str, Any]) -> Dict[str, bool]:
        """Dispatches notification to both Discord and Termux."""
        discord_ok = self.send_discord_alert(result)
        termux_ok = self.send_termux_notification(result)
        return {"discord": discord_ok, "termux": termux_ok}

    def test_discord_connection(self) -> bool:
        """Sends a test ping embed to Discord."""
        if not self.webhook_url:
            return False

        payload = {
            "username": "Stock Market AI Indicator",
            "avatar_url": "https://img.icons8.com/color/512/bullish.png",
            "embeds": [
                {
                    "title": "✅ Discord Webhook Connected Successfully!",
                    "description": "The Multi-Market Quantitative Indicator is active and ready to deliver real-time signals for both US & Indian equities.",
                    "color": 0x2ECC71,
                    "fields": [
                        {"name": "Status", "value": "Online & Watching", "inline": True},
                        {"name": "Markets", "value": "🇺🇸 US (NASDAQ/NYSE) & 🇮🇳 India (NSE/BSE)", "inline": True},
                        {"name": "Precision Engine", "value": "5-Pillar Confluence (EMAs, MACD, RSI, BB, ATR)", "inline": True},
                    ],
                    "footer": {"text": "AI Indicator Setup Verification"},
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            ]
        }
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code in [200, 204]
        except Exception:
            return False
