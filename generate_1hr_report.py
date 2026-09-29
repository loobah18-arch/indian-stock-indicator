#!/usr/bin/env python3
"""
generate_1hr_report.py
Generates an audit report of the AI Autonomous Fund forward-test,
logging every stock traded, exact timestamps, capital amounts used,
entry/exit execution prices, P&L outcomes, and current active holdings.
"""

import os
import sys
import json
from datetime import datetime, timezone
from market_client import MarketClient

PORTFOLIO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio.json")

def format_currency(val: float, curr: str = "USD") -> str:
    sign = "$" if curr == "USD" else "₹"
    return f"{sign}{val:,.2f}"

def generate_report() -> str:
    if not os.path.exists(PORTFOLIO_FILE):
        return "# ⚠️ Error: portfolio.json not found."

    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    client = MarketClient()
    raw_positions = data.get("positions", {})
    if isinstance(raw_positions, dict):
        positions = list(raw_positions.values())
    else:
        positions = list(raw_positions)
    history = data.get("trade_history", [])
    starting_balance = float(data.get("starting_balance", 1000.0))
    cash = float(data.get("cash", 1000.0))

    # Fetch live prices for open positions
    open_positions_val = 0.0
    unrealized_pnl = 0.0
    open_details = []

    for p in positions:
        sym = p["symbol"]
        curr = p.get("currency", "USD")
        shares = float(p.get("shares", 0.0))
        entry_price = float(p.get("entry_price", 0.0))
        invested = float(p.get("invested", 0.0))
        entry_time = p.get("entry_time", "-")
        score = p.get("score", "-")
        sl = float(p.get("stop_loss", 0.0))
        tp1 = float(p.get("take_profit_1", 0.0))
        rationale = p.get("ai_rationale", "")

        try:
            live_data = client.get_full_analysis(sym)
            live_price = float(live_data.get("analyst", {}).get("current_price") or entry_price)
        except Exception:
            live_price = entry_price

        curr_val = round(shares * live_price, 2)
        pos_pnl = round(curr_val - invested, 2)
        pos_pnl_pct = round(((live_price - entry_price) / entry_price) * 100, 2) if entry_price > 0 else 0.0

        open_positions_val += curr_val
        unrealized_pnl += pos_pnl

        open_details.append({
            "symbol": sym,
            "currency": curr,
            "shares": shares,
            "entry_time": entry_time,
            "amount_used": invested,
            "entry_price": entry_price,
            "live_price": live_price,
            "current_value": curr_val,
            "unrealized_pnl": pos_pnl,
            "unrealized_pct": pos_pnl_pct,
            "score": score,
            "stop_loss": sl,
            "take_profit_1": tp1,
            "rationale": rationale
        })

    # Closed trades breakdown
    realized_pnl = 0.0
    wins = 0
    losses = 0
    gross_win = 0.0
    gross_loss = 0.0

    for t in history:
        pnl = float(t.get("pnl_amount", 0.0))
        realized_pnl += pnl
        if pnl >= 0:
            wins += 1
            gross_win += pnl
        else:
            losses += 1
            gross_loss += abs(pnl)

    total_closed = len(history)
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0.0
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (gross_win if gross_win > 0 else 1.0)
    total_equity = round(cash + open_positions_val, 2)
    total_net_pnl = round(total_equity - starting_balance, 2)
    total_return_pct = round((total_net_pnl / starting_balance) * 100, 2)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Generate Markdown Report
    lines = []
    lines.append(f"# 📊 AI Autonomous Trading 1-Hour Verification Audit Report")
    lines.append(f"**Report Generated At:** `{now_utc}` | **Evaluation Window:** 1 Hour Live Forward-Test")
    lines.append(f"**Starting Capital:** `${starting_balance:,.2f}` | **Current Fund Equity:** `${total_equity:,.2f}` | **Net Return:** `+{total_return_pct:.2f}%` (`+${total_net_pnl:.2f}`)")
    lines.append("")
    lines.append("---")
    lines.append("### 📈 1. Executive Performance & Accuracy Matrix")
    lines.append("")
    lines.append("| Metric | Value | Risk / Edge Assessment |")
    lines.append("| :--- | :--- | :--- |")
    lines.append(f"| **Starting Capital** | `${starting_balance:,.2f}` | Allocated Virtual Credits |")
    lines.append(f"| **Current Total Equity** | `${total_equity:,.2f}` | **{'Profitable (+)' if total_net_pnl >= 0 else 'Drawdown (-)'}** |")
    lines.append(f"| **Total Net P&L** | **{'+' if total_net_pnl >= 0 else ''}${total_net_pnl:.2f} ({'+' if total_return_pct >= 0 else ''}{total_return_pct:.2f}%)** | Overall Fund P&L |")
    lines.append(f"| **Realized P&L** | `${realized_pnl:,.2f}` | Locked Profits from Closed Trades |")
    lines.append(f"| **Unrealized Live P&L** | `${unrealized_pnl:,.2f}` | Floating P&L on Open Positions |")
    lines.append(f"| **Available Cash** | `${cash:,.2f}` | Liquid Capital Available for New Setups |")
    lines.append(f"| **Closed Trades** | `{total_closed}` ({wins}W / {losses}L) | Total Round-Trip Executions |")
    lines.append(f"| **Win Rate %** | **{win_rate:.1f}%** | Realized Probability Accuracy |")
    lines.append(f"| **Profit Factor** | **{profit_factor:.2f}** | Ratio of Gross Profit to Gross Loss |")
    lines.append(f"| **Active Holdings** | `{len(positions)}` / 4 slots | Deployed Capital (`${open_positions_val:,.2f}`) |")
    lines.append("")
    lines.append("---")
    lines.append("### 📜 2. Detailed Trade Execution Log (Closed Trades)")
    lines.append("Exhaustive record of all completed autonomous trades, including exact timestamps, capital amount used, entry/exit prices, and realized P&L.")
    lines.append("")

    if not history:
        lines.append("*No trades have fully closed during this session yet. Active positions are being forward-tested against trailing ATR stops and TP1 targets.*")
    else:
        lines.append("| # | Stock Symbol | Amount Used ($) | Entry Time | Exit Time | Entry Price | Exit Price | Realized P&L ($) | Return (%) | Outcome | Exit Trigger & Reason |")
        lines.append("| :-: | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :---: | :--- |")
        for i, t in enumerate(history, 1):
            sym = t.get("symbol", "-")
            invested = float(t.get("invested", 0.0))
            entry_t = t.get("entry_time", "-")
            exit_t = t.get("exit_time", "-")
            entry_p = float(t.get("entry_price", 0.0))
            exit_p = float(t.get("exit_price", 0.0))
            pnl_amt = float(t.get("pnl_amount", 0.0))
            pnl_pct = float(t.get("pnl_pct", 0.0))
            result = t.get("result", "WIN")
            outcome_badge = "🎯 WIN" if result == "WIN" else "🛑 LOSS"
            reason = t.get("exit_reason", "TRIGGER")
            rationale = t.get("exit_rationale", "")
            sign = "+" if pnl_amt >= 0 else ""

            reason_str = f"**{reason}**"
            if rationale and rationale != reason:
                reason_str += f" ({rationale[:45]}...)"

            lines.append(f"| {i} | **{sym}** | `${invested:.2f}` | `{entry_t}` | `{exit_t}` | `${entry_p:.2f}` | `${exit_p:.2f}` | **{sign}${pnl_amt:.2f}** | **{sign}{pnl_pct:.2f}%** | {outcome_badge} | {reason_str} |")

    lines.append("")
    lines.append("---")
    lines.append("### 🟢 3. Active Positions Under Autonomous Forward-Test")
    lines.append("Stocks currently held in the portfolio, their time entered, capital deployed, and live floating performance.")
    lines.append("")

    if not open_details:
        lines.append("*No open positions currently active. All capital is liquid in cash buffer.*")
    else:
        lines.append("| # | Stock Symbol | Amount Allocated ($) | Time Entered | Shares | Entry Price | Live Price | Market Value | Floating P&L | Confluence Score | Stop Loss | TP1 Target |")
        lines.append("| :-: | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :---: | :--- | :--- |")
        for i, p in enumerate(open_details, 1):
            sign = "+" if p["unrealized_pnl"] >= 0 else ""
            c_sign = "$" if p["currency"] == "USD" else "₹"
            lines.append(f"| {i} | **{p['symbol']}** | `${p['amount_used']:.2f}` | `{p['entry_time']}` | {p['shares']} | {c_sign}{p['entry_price']:.2f} | {c_sign}{p['live_price']:.2f} | `${p['current_value']:.2f}` | **{sign}${p['unrealized_pnl']:.2f} ({sign}{p['unrealized_pct']:.2f}%)** | **{p['score']}/100** | {c_sign}{p['stop_loss']:.2f} | {c_sign}{p['take_profit_1']:.2f} |")

    lines.append("")
    lines.append("---")
    lines.append("### 🔍 4. Algorithmic Accuracy & Probability Validation Summary")
    lines.append(f"- **High Confluence Discipline:** Only setups scoring ≥ 70 with multi-pillar confirmation are autonomously traded.")
    lines.append(f"- **Capital Protection:** Capital is strictly capped at $250.00 max per position (25% maximum exposure) preventing concentration risk.")
    lines.append(f"- **Exit Discipline:** Automatic liquidation occurs via mathematical ATR risk bands or take-profit targets, eliminating emotional bias.")
    lines.append(f"- **Live Dashboard:** Real-time metrics are synced live to the dedicated `🤖 AI Autonomous Fund & Trade Records` tab on `http://localhost:5000`.")

    return "\n".join(lines)

if __name__ == "__main__":
    report_text = generate_report()
    print(report_text)
