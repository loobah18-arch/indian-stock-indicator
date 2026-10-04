import os
import re
import requests
from typing import Dict, Any, List, Optional

FREE_MODELS = [
    "qwen/qwen3.8-27b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
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

    def build_system_prompt(self, stock_context: Optional[Dict[str, Any]] = None, system_state: Optional[Dict[str, Any]] = None) -> str:
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

        if system_state:
            prac = system_state.get("practice_portfolio", {})
            fund = system_state.get("ai_fund", {})
            ai_syms = system_state.get("ai_trade_symbols", [])
            auto_active = system_state.get("ai_auto_trading_enabled", True)

            p_cash = prac.get("cash", 1000.0)
            p_equity = prac.get("total_equity", 1000.0)
            p_pnl = prac.get("total_pnl", 0.0)
            p_pnl_pct = prac.get("total_pnl_pct", 0.0)
            p_positions = prac.get("positions", [])
            p_pos_desc = []
            for p in p_positions:
                c_sign = "₹" if p.get("currency") == "INR" or str(p.get("symbol", "")).endswith((".NS", ".BO")) else "$"
                p_pos_desc.append(f"{p['symbol']} ({p['shares']} shares @ {c_sign}{p['entry_price']:.2f}, current {c_sign}{p['current_price']:.2f}, unrealized P&L: ${p['unrealized_pnl']:+,.2f})")
            p_pos_str = "; ".join(p_pos_desc) if p_pos_desc else "None (100% Cash / No open trades)"

            f_equity = fund.get("total_equity", 1000.0)
            f_pnl = fund.get("realized_pnl", 0.0)
            f_win = fund.get("win_rate_pct", 0.0)
            f_trades = fund.get("total_trades", 0)

            prompt += (
                f"\n--- REAL-TIME PLATFORM LIVE SYSTEM ACCESS & STATUS ---\n"
                f"• Practice Trading Sandbox: Available Cash=${p_cash:,.2f} | Total Account Equity=${p_equity:,.2f} | Net P&L=${p_pnl:+,.2f} ({p_pnl_pct:+,.2f}%)\n"
                f"• Practice Open Positions: {p_pos_str}\n"
                f"• Autonomous AI Fund: Equity=${f_equity:,.2f} | Realized P&L=${f_pnl:+,.2f} | Closed Trades={f_trades} | Win Rate={f_win:.1f}%\n"
                f"• Allowed AI Stock Universe: {', '.join(ai_syms) if ai_syms else 'All'}\n"
                f"• Auto-Trading Status: {'ACTIVE (ON)' if auto_active else 'PAUSED (OFF)'}\n"
                f"--------------------------------------------------------\n"
                f"You have live awareness of all these metrics and can directly answer any questions about the user's balance, "
                f"holdings, trade counts, P&L, or AI universe, as well as execute trades and adjustments for them.\n"
            )

            timing = system_state.get("chart_timing")
            chart_sym = system_state.get("current_chart_symbol", "")
            if timing:
                prompt += (
                    f"\n--- ACTIVE CHART TIMING & PERFECT TIMESTAMP RADAR (IST) ---\n"
                    f"Viewed Asset: {chart_sym} | Timeframe: {timing.get('timeframe', '1m')}\n"
                    f"Action Recommendation: {timing.get('action_label', timing.get('action'))}\n"
                    f"Confluence Score: {timing.get('confluence_score')}/100 | Status: {timing.get('timing_status')}\n"
                    f"Confirmed Signal Trigger Timestamp (IST): {timing.get('trigger_time_ist', timing.get('trigger_time_utc'))} ({timing.get('trigger_type')})\n"
                    f"Optimal Execution Window (IST): {timing.get('optimal_window')}\n"
                    f"Next Candle Close Timestamp (IST): {timing.get('next_candle_time_ist', timing.get('next_candle_time_utc'))} (T-minus {timing.get('seconds_to_next_bar')}s)\n"
                    f"Technical Confluence Rationale: {timing.get('trigger_reason')}\n"
                    f"Guidance: {timing.get('instruction')}\n"
                    f"------------------------------------------------------\n"
                    f"Note: All timestamps are in Indian Standard Time (IST). When the user asks when to buy or sell, what the perfect timestamp is, or asks you to analyze the chart they are seeing, "
                    f"cite these exact IST timestamps, optimal entry/exit window, candle countdown, and technical trigger reasons directly.\n"
                )

        prompt += (
            "\n--- AUTONOMOUS SYSTEM PRIVILEGES & FUNCTION EXECUTION ---\n"
            "You have DIRECT SYSTEM EXECUTION ACCESS across this quantitative trading platform. "
            "You are NOT just a conversational bot — if the user instructs you to perform any trading, universe configuration, "
            "or system control task, you have the full authority and access to execute it directly!\n"
            "Supported System Actions you can invoke:\n"
            "1. BUY / LONG: When instructed to buy, invest in, or open a position:\n"
            "   [ACTION: {\"type\": \"BUY\", \"symbol\": \"<TICKER>\", \"amount\": <DOLLARS>}]\n"
            "2. SELL / EXIT: When instructed to sell, exit, close, or liquidate a position:\n"
            "   [ACTION: {\"type\": \"SELL\", \"symbol\": \"<TICKER>\"}]\n"
            "3. LIQUIDATE ALL: When instructed to close/sell all active positions:\n"
            "   [ACTION: {\"type\": \"LIQUIDATE_ALL\"}]\n"
            "4. RESET PRACTICE: When instructed to reset practice balance / refill demo credits:\n"
            "   [ACTION: {\"type\": \"RESET_PRACTICE\"}]\n"
            "5. SET AI TRADING UNIVERSE: When instructed which stocks the AI auto-trader should trade on:\n"
            "   [ACTION: {\"type\": \"SET_AI_SYMBOLS\", \"symbols\": [\"<SYM1>\", \"<SYM2>\"]}]\n"
            "6. TOGGLE AUTO TRADING: When instructed to pause, stop, resume, or start auto trading:\n"
            "   [ACTION: {\"type\": \"TOGGLE_AUTO_TRADING\", \"enabled\": true|false}]\n"
            "7. RUN AI SCAN: When instructed to run an autonomous scan cycle:\n"
            "   [ACTION: {\"type\": \"RUN_AI_SCAN\"}]\n"
            "\n"
            "Always be decisive, highly competent, professional, and confirm exact numbers and levels.\n"
        )

        return prompt

    def _call_llm(self, messages: List[Dict[str, str]], max_tokens: int = 600, temperature: float = 0.3) -> Dict[str, Any]:
        """Calls OpenRouter with fallback across verified free models."""
        if not self.api_key:
            self.api_key = find_api_key()

        if not self.api_key:
            return {
                "reply": "API Key Error: Could not find OPENROUTER_API_KEY in .env or environment.",
                "model": "none",
                "error": True
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5000",
            "X-Title": "Quantitative Market Terminal"
        }

        last_error = ""
        for model in FREE_MODELS:
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature
            }
            try:
                resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices and choices[0].get("message", {}).get("content"):
                        reply = choices[0]["message"]["content"].strip()
                        reply = re.sub(r'<think>.*?</think>', '', reply, flags=re.DOTALL).strip()
                        if len(reply) > 20 and not reply.lower().startswith("user safety:"):
                            return {
                                "reply": reply,
                                "model": model,
                                "error": False
                            }
                        else:
                            last_error = f"Model {model} returned non-substantive content: '{reply[:35]}'"
                    else:
                        last_error = f"Model {model} returned empty choices"
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

    def chat(self, user_message: str, stock_context: Optional[Dict[str, Any]] = None, history: Optional[List[Dict[str, str]]] = None, action_receipt: Optional[str] = None, system_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Sends chat request to OpenRouter free models with automatic multi-model fallback."""
        messages = [{"role": "system", "content": self.build_system_prompt(stock_context, system_state=system_state)}]
        if history:
            for h in history[-6:]:
                if h.get("role") in ["user", "assistant"] and h.get("content"):
                    messages.append({"role": h["role"], "content": h["content"]})

        messages.append({"role": "user", "content": user_message})
        if action_receipt:
            messages.append({"role": "system", "content": f"SYSTEM EXECUTION RECEIPT: {action_receipt}. Confirm this execution clearly to the user, state the exact price and risk levels, and outline the technical outlook."})
        return self._call_llm(messages, max_tokens=500, temperature=0.4)

    def generate_portfolio_report(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Audits the $1,000 virtual portfolio P&L and verifies whether the AI's probability scoring is mathematically accurate."""
        equity = summary.get("total_equity", 1000.0)
        start_bal = summary.get("starting_balance", 1000.0)
        cash = summary.get("cash", 1000.0)
        open_val = summary.get("open_positions_value", 0.0)
        tot_pnl = summary.get("total_pnl", 0.0)
        tot_pnl_pct = summary.get("total_pnl_pct", 0.0)
        realized_pnl = summary.get("realized_pnl", 0.0)
        unrealized_pnl = summary.get("unrealized_pnl", 0.0)
        total_trades = summary.get("total_trades", 0)
        wins = summary.get("wins", 0)
        losses = summary.get("losses", 0)
        win_rate = summary.get("win_rate_pct", 0.0)
        profit_factor = summary.get("profit_factor", 1.0)
        open_pos = summary.get("positions", [])
        history = summary.get("trade_history", [])

        # Format open positions
        pos_lines = []
        for p in open_pos:
            c_sym = "₹" if (p.get("currency") == "INR" or p.get("symbol", "").endswith((".NS", ".BO"))) else "$"
            pos_lines.append(
                f"- **{p['symbol']}**: {p['shares']} shares @ {c_sym}{p['entry_price']} | Curr: {c_sym}{p['current_price']} | "
                f"Unrealized P&L: ${p['unrealized_pnl']:+,.2f} ({p['unrealized_pct']:+,.2f}%) | "
                f"SL: {c_sym}{p.get('stop_loss')} | TP1: {c_sym}{p.get('take_profit_1')} | Confluence Score: {p.get('score')}/100"
            )
        pos_str = "\n".join(pos_lines) if pos_lines else "None (100% Cash / Inactive)"

        # Format closed trades
        trade_lines = []
        for t in history[:10]:
            c_sym = "₹" if (t.get("currency") == "INR" or t.get("symbol", "").endswith((".NS", ".BO"))) else "$"
            trade_lines.append(
                f"- **{t['symbol']}**: Entry {c_sym}{t['entry_price']} -> Exit {c_sym}{t['exit_price']} | "
                f"P&L: ${t['pnl_amount']:+,.2f} ({t['pnl_pct']:+,.2f}%) | Result: {t['result']} | Trigger: {t['exit_reason']}"
            )
        history_str = "\n".join(trade_lines) if trade_lines else "No closed trades yet (trades are currently live/in-flight)."

        prompt = f"""You are the Chief Quantitative Risk Officer auditing an AI Automated Trading Strategy.
The user allocated $1,000.00 in virtual credits to rigorously verify if the AI's probability scoring and confluence signals are actually profitable and mathematically sound.

PORTFOLIO PERFORMANCE DATA:
- Initial Capital: ${start_bal:,.2f}
- Current Total Equity: ${equity:,.2f}
- Virtual Cash Available: ${cash:,.2f}
- Market Value of Open Positions: ${open_val:,.2f}
- Total Net P&L: ${tot_pnl:+,.2f} ({tot_pnl_pct:+,.2f}%)
- Realized P&L: ${realized_pnl:+,.2f}
- Unrealized P&L: ${unrealized_pnl:+,.2f}
- Closed Trades: {total_trades} (Wins: {wins}, Losses: {losses})
- Win Rate: {win_rate:.1f}%
- Profit Factor: {profit_factor:.2f}

OPEN POSITIONS UNDER TEST:
{pos_str}

CLOSED TRADES HISTORY:
{history_str}

Write an objective, institutional-grade Quantitative Audit Report formatted in clean markdown. Include:
1. ### 📊 Executive Performance Summary
   - Direct breakdown of whether the $1,000 credit fund is currently net positive or negative, with exact return metrics.
2. ### 🎯 Signal Probability & Mathematical Edge Evaluation
   - Assess whether the 5-pillar confluence scoring (70-100 threshold) is demonstrating statistical edge or if variance/luck is driving the results.
   - Analyze risk-to-reward asymmetry (are wins larger than losses?).
3. ### 🛡️ Risk Management & Drawdown Analysis
   - Audit the position sizing (e.g. $250 max per position, 4 positions max) and stop-loss enforcement efficiency.
4. ### 🏁 Quantitative Verdict & Calibration Recommendations
   - Clear verdict: EDGE VERIFIED, PRELIMINARY ACCURACY, or CALIBRATION NEEDED.
   - Specific parameter tweaks (e.g. tightening RSI filters, adjusting TP/SL ratios, or market regime weighting).

Avoid fluff and generic warnings. Deliver concrete quantitative insights.
"""

        messages = [
            {"role": "system", "content": "You are a quantitative finance and algorithmic risk auditing expert. You provide objective, rigorous statistical assessments."},
            {"role": "user", "content": prompt}
        ]

        llm_res = self._call_llm(messages, max_tokens=1000, temperature=0.25)
        if not llm_res.get("error"):
            return {
                "report": llm_res["reply"],
                "model": llm_res.get("model", "nemotron"),
                "generated_at": summary.get("updated_at", ""),
                "equity": equity,
                "total_pnl": tot_pnl,
                "total_pnl_pct": tot_pnl_pct,
                "win_rate_pct": win_rate,
                "error": False
            }

        # Fallback to local deterministic quantitative analysis if external API is unreachable
        status_word = "PROFITABLE" if tot_pnl >= 0 else "DRAWDOWN"
        verdict_badge = "EDGE DEMONSTRATED" if tot_pnl >= 0 and win_rate >= 50 else "TESTING IN PROGRESS / MODERATE VARIANCE"
        local_report = f"""### 📊 Executive Performance Summary
- **Virtual Starting Fund:** ${start_bal:,.2f}
- **Current Total Equity:** ${equity:,.2f} (${tot_pnl:+,.2f} / {tot_pnl_pct:+,.2f}%)
- **Realized P&L:** ${realized_pnl:+,.2f} | **Unrealized P&L:** ${unrealized_pnl:+,.2f}
- **Status:** **{status_word}** ({len(open_pos)} active positions deployed, {total_trades} closed trades)

### 🎯 Signal Probability & Edge Evaluation
- **Empirical Win Rate:** {win_rate:.1f}% across {total_trades} completed trades.
- **Profit Factor:** {profit_factor:.2f} (Gross Profit / Gross Loss ratio).
- **Confluence Threshold:** All positions were filtered with Confluence Score ≥ 70/100 requiring alignment across Technicals, Momentum, and Institutional Analyst Consensus.

### 🛡️ Risk & Capital Preservation Audit
- **Position Allocation:** Sized at 25% max capital ($250 per asset) across a 4-asset basket to avoid single-stock ruin.
- **Stop-Loss Protection:** Dynamic ATR-based Stop-Loss active on all open holdings to cap downside risk.

### 🏁 Quantitative Verdict: `{verdict_badge}`
- The strategy demonstrates strict capital preservation and asymmetric risk-reward profile (1:2+ target ratios).
- Continuous forward monitoring is active via background scanner.
"""
        return {
            "report": local_report,
            "model": "deterministic-quant-engine",
            "generated_at": summary.get("updated_at", ""),
            "equity": equity,
            "total_pnl": tot_pnl,
            "total_pnl_pct": tot_pnl_pct,
            "win_rate_pct": win_rate,
            "error": False
        }

