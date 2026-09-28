import os
import requests
from typing import Dict, Any, List, Optional

FREE_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/free",
    "qwen/qwen3.8-27b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-31b-it:free",
]

def find_api_key() -> str:
    """Finds OPENROUTER_API_KEY from environment variables or .env files."""
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"].strip()

    search_paths = [
        "/data/data/com.termux/files/home/.env",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.expanduser("~/.env"),
        "/data/data/com.termux/files/home/antigravity/auto-clipper-shorts/.env",
    ]

    for p in search_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("OPENROUTER_API_KEY="):
                            val = line.split("=", 1)[1].strip().strip("\"' ")
                            if val:
                                return val
            except Exception:
                pass
    return ""

class AIAssistant:
    """Quantitative Financial Market Chatbot powered by free, high-precision reasoning models."""

    def __init__(self):
        self.api_key = find_api_key()

    def build_system_prompt(self, stock_context: Optional[Dict[str, Any]] = None) -> str:
        prompt = (
            "You are 'AlphaQuant AI', an institutional quantitative market strategist and technical analyst assistant "
            "specializing in both US Markets (NASDAQ/NYSE/S&P500) and Indian Markets (NSE/BSE).\n"
            "You provide precise, data-driven, objective answers. Always cite specific numbers, price levels, "
            "and risk-to-reward ratios when discussing setups. Avoid generic disclaimers and boilerplate fluff.\n"
        )

        if stock_context:
            sym = stock_context.get("symbol", "")
            name = stock_context.get("name", sym)
            price = stock_context.get("current_price", 0.0)
            curr = stock_context.get("currency", "USD")
            csign = "$" if curr == "USD" else "₹"
            score = stock_context.get("score", 50)
            signal = stock_context.get("signal", "HOLD")
            conviction = stock_context.get("conviction", "")

            ex = stock_context.get("execution", {})
            entry = ex.get("entry_zone", "N/A")
            sl = ex.get("stop_loss", 0.0)
            sl_pct = ex.get("sl_risk_pct", 0.0)
            tp1 = ex.get("take_profit_1", 0.0)
            tp1_pct = ex.get("tp1_gain_pct", 0.0)
            tp2 = ex.get("take_profit_2", 0.0)
            tp2_pct = ex.get("tp2_gain_pct", 0.0)
            rr = ex.get("risk_reward_tp1", 0.0)

            tech = stock_context.get("technicals", {})
            rsi = tech.get("rsi_14", "N/A")
            macd_h = tech.get("macd_hist", "N/A")
            rvol = tech.get("rvol", 1.0)
            above_200 = tech.get("above_ema200", False)
            ema9 = tech.get("ema_9", "N/A")
            ema21 = tech.get("ema_21", "N/A")
            ema50 = tech.get("ema_50", "N/A")
            ema200 = tech.get("ema_200", "N/A")

            b = stock_context.get("breakdown", {})
            total_a = sum(b.values()) if b else stock_context.get("analyst_count", 0)
            buy_a = (b.get("strongBuy", 0) + b.get("buy", 0)) if b else 0

            prompt += (
                f"\n--- ACTIVE STOCK REAL-TIME DATA ---\n"
                f"Asset: {sym} ({name})\n"
                f"Current Price: {csign}{price:,.2f} {curr}\n"
                f"Quantitative Score: {score}/100 | Signal: {signal} ({conviction})\n"
                f"Recommended Entry Zone: {entry}\n"
                f"Stop-Loss (ATR Sized): {csign}{sl:,.2f} (-{sl_pct}% risk)\n"
                f"Take-Profit 1 (Swing): {csign}{tp1:,.2f} (+{tp1_pct}%)\n"
                f"Take-Profit 2 (Analyst Target): {csign}{tp2:,.2f} (+{tp2_pct}%)\n"
                f"Risk-to-Reward Ratio: 1 : {rr}\n"
                f"Technicals: RSI(14)={rsi}, MACD Hist={macd_h}, RVOL={rvol}x, Above 200 EMA={above_200}\n"
                f"Key EMAs: 9 EMA={ema9}, 21 EMA={ema21}, 50 EMA={ema50}, 200 EMA={ema200}\n"
                f"Institutional Analysts: {buy_a}/{total_a} Recommend Buy\n"
                f"------------------------------------\n"
                f"When answering, directly reference these live levels if the user asks about this asset.\n"
            )

        return prompt

    def chat(self, user_message: str, stock_context: Optional[Dict[str, Any]] = None, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        """Sends chat request to OpenRouter free models with automatic multi-model fallback."""
        if not self.api_key:
            self.api_key = find_api_key()

        if not self.api_key:
            return {
                "reply": "API Key Error: Could not find OPENROUTER_API_KEY in .env or environment. Please add it to ~/.env.",
                "model": "none",
                "error": True
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5000",
            "X-Title": "Quantitative Market Terminal"
        }

        messages = [{"role": "system", "content": self.build_system_prompt(stock_context)}]
        if history:
            # Keep up to last 6 conversational turns to manage context window
            for h in history[-6:]:
                if h.get("role") in ["user", "assistant"] and h.get("content"):
                    messages.append({"role": h["role"], "content": h["content"]})

        messages.append({"role": "user", "content": user_message})

        last_error = ""
        for model in FREE_MODELS:
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": 500,
                "temperature": 0.4
            }
            try:
                resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=14)
                if resp.status_code == 200:
                    data = resp.json()
                    reply = data["choices"][0]["message"]["content"].strip()
                    return {
                        "reply": reply,
                        "model": model,
                        "error": False
                    }
                else:
                    last_error = f"Model {model} returned status {resp.status_code}: {resp.text[:100]}"
            except Exception as e:
                last_error = str(e)
                continue

        return {
            "reply": f"AI service temporarily unavailable across free models. Error: {last_error}",
            "model": "failed",
            "error": True
        }
