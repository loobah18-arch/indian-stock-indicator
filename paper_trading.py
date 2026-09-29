#!/usr/bin/env python3
import os
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

PORTFOLIO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio.json")
PRACTICE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "practice_portfolio.json")

_cached_fx: Dict[str, Any] = {"rate": 95.98, "time": 0.0}

def get_usd_inr_rate() -> float:
    """Returns live USD/INR exchange rate with 10-minute caching for accurate multi-currency accounting."""
    now = time.time()
    if now - _cached_fx["time"] < 600 and _cached_fx["rate"] > 0:
        return _cached_fx["rate"]
    try:
        from market_client import MarketClient
        mc = MarketClient()
        raw = mc.get_full_analysis("USDINR=X")
        if raw and raw.get("analyst", {}).get("current_price"):
            val = float(raw["analyst"]["current_price"])
            if val > 50:
                _cached_fx["rate"] = val
                _cached_fx["time"] = now
                return val
    except Exception:
        pass
    return _cached_fx["rate"]

class PaperPortfolio:
    """Manages $1,000 virtual credit fund for forward testing and probability audit."""

    def __init__(self, file_path: str = PORTFOLIO_FILE, initial_balance: float = 1000.0):
        self.file_path = file_path
        self.initial_balance = initial_balance
        self.starting_balance = initial_balance
        self.cash = initial_balance
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.trade_history: List[Dict[str, Any]] = []
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.load()

    def load(self) -> None:
        """Loads portfolio state from disk."""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.starting_balance = float(data.get("starting_balance", self.initial_balance))
                    self.cash = float(data.get("cash", self.initial_balance))
                    self.positions = data.get("positions", {})
                    self.trade_history = data.get("trade_history", [])
                    self.created_at = data.get("created_at", self.created_at)
                    return
            except Exception:
                pass
        self.save()

    def save(self) -> None:
        """Saves current portfolio state to disk."""
        data = {
            "starting_balance": self.starting_balance,
            "cash": round(self.cash, 2),
            "created_at": self.created_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "positions": self.positions,
            "trade_history": self.trade_history,
        }
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def reset(self, balance: float = 1000.0) -> Dict[str, Any]:
        """Resets virtual portfolio back to $1,000."""
        self.starting_balance = balance
        self.cash = balance
        self.positions = {}
        self.trade_history = []
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.save()
        return self.get_summary()

    def buy(
        self,
        symbol: str,
        price: float,
        allocation: float = 250.0,
        stop_loss: float = 0.0,
        take_profit_1: float = 0.0,
        take_profit_2: float = 0.0,
        score: int = 50,
        signal: str = "BUY",
        currency: str = "USD",
        conviction: str = "HIGH",
        ai_rationale: str = ""
    ) -> Dict[str, Any]:
        """Executes simulated paper buy order using virtual funds."""
        if price <= 0:
            return {"success": False, "error": "Invalid price"}

        if self.cash < 10.0:
            return {"success": False, "error": f"Insufficient virtual cash (${self.cash:.2f} available)"}

        is_inr = currency == "INR" or symbol.endswith((".NS", ".BO"))
        fx_rate = get_usd_inr_rate() if is_inr else 1.0
        price_usd = round(price / fx_rate, 4) if is_inr else price

        # Position sizing in USD fund: up to allocation or remaining cash
        invest_amount = min(allocation, self.cash)
        shares = round(invest_amount / price_usd, 4)
        actual_invested = round(shares * price_usd, 2)

        self.cash = round(self.cash - actual_invested, 2)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        position_data = {
            "symbol": symbol,
            "entry_price": price,              # Native exchange price (e.g. ₹1302.50)
            "entry_price_usd": price_usd,      # USD price (e.g. $13.57)
            "fx_rate": fx_rate,
            "shares": shares,
            "invested": actual_invested,       # USD amount (e.g. $250.00)
            "entry_time": now_str,
            "stop_loss": stop_loss or round(price * 0.95, 2),
            "take_profit_1": take_profit_1 or round(price * 1.05, 2),
            "take_profit_2": take_profit_2 or round(price * 1.15, 2),
            "score": score,
            "signal": signal,
            "conviction": conviction,
            "ai_rationale": ai_rationale,
            "currency": currency,
        }

        # If already holding, average in
        if symbol in self.positions:
            old = self.positions[symbol]
            tot_shares = old["shares"] + shares
            tot_invested = old["invested"] + actual_invested
            avg_price_usd = round(tot_invested / tot_shares, 4) if tot_shares > 0 else price_usd
            avg_price_native = round(avg_price_usd * fx_rate, 2) if is_inr else avg_price_usd
            old["shares"] = round(tot_shares, 4)
            old["invested"] = round(tot_invested, 2)
            old["entry_price"] = avg_price_native
            old["entry_price_usd"] = avg_price_usd
            old["fx_rate"] = fx_rate
            old["stop_loss"] = stop_loss or old["stop_loss"]
            old["take_profit_1"] = take_profit_1 or old["take_profit_1"]
            old["take_profit_2"] = take_profit_2 or old["take_profit_2"]
            old["ai_rationale"] = ai_rationale or old.get("ai_rationale", "")
            self.positions[symbol] = old
        else:
            self.positions[symbol] = position_data

        self.save()
        return {
            "success": True,
            "action": "BUY",
            "symbol": symbol,
            "shares": shares,
            "price": price,
            "price_usd": price_usd,
            "fx_rate": fx_rate,
            "invested": actual_invested,
            "score": score,
            "signal": signal,
            "conviction": conviction,
            "ai_rationale": ai_rationale,
            "remaining_cash": self.cash,
        }

    def sell(
        self,
        symbol: str,
        price: float,
        exit_reason: str = "MANUAL",
        shares_to_sell: Optional[float] = None,
        ai_rationale: str = ""
    ) -> Dict[str, Any]:
        """Liquidates paper position and books realized profit/loss."""
        if symbol not in self.positions:
            return {"success": False, "error": f"No active position for {symbol}"}

        pos = self.positions[symbol]
        curr_shares = pos["shares"]
        shares = min(shares_to_sell or curr_shares, curr_shares)

        fraction = shares / curr_shares
        portion_invested = round(pos["invested"] * fraction, 2)

        is_inr = pos.get("currency") == "INR" or symbol.endswith((".NS", ".BO"))
        fx_rate = pos.get("fx_rate") or (get_usd_inr_rate() if is_inr else 1.0)
        price_usd = round(price / fx_rate, 4) if is_inr else price

        gross_proceeds = round(shares * price_usd, 2)
        pnl = round(gross_proceeds - portion_invested, 2)
        pnl_pct = round(((price - pos["entry_price"]) / pos["entry_price"]) * 100, 2) if pos.get("entry_price") else 0.0

        self.cash = round(self.cash + gross_proceeds, 2)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        trade_record = {
            "id": f"trade_{symbol}_{int(time.time())}",
            "symbol": symbol,
            "entry_price": pos["entry_price"],
            "entry_price_usd": pos.get("entry_price_usd", round(pos["entry_price"] / fx_rate, 4) if is_inr else pos["entry_price"]),
            "exit_price": price,
            "exit_price_usd": price_usd,
            "fx_rate": fx_rate,
            "shares": shares,
            "invested": portion_invested,
            "proceeds": gross_proceeds,
            "pnl_amount": pnl,
            "pnl_pct": pnl_pct,
            "result": "WIN" if pnl >= 0 else "LOSS",
            "score": pos.get("score", 50),
            "signal": pos.get("signal", "BUY"),
            "conviction": pos.get("conviction", "HIGH"),
            "buy_rationale": pos.get("ai_rationale", ""),
            "exit_reason": exit_reason,
            "exit_rationale": ai_rationale or exit_reason,
            "entry_time": pos["entry_time"],
            "exit_time": now_str,
            "currency": pos.get("currency", "USD"),
        }

        self.trade_history.append(trade_record)

        if shares >= curr_shares:
            del self.positions[symbol]
        else:
            pos["shares"] = round(curr_shares - shares, 4)
            pos["invested"] = round(pos["invested"] - portion_invested, 2)
            self.positions[symbol] = pos

        self.save()
        return {
            "success": True,
            "action": "SELL",
            "symbol": symbol,
            "shares": shares,
            "exit_price": price,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "result": "WIN" if pnl >= 0 else "LOSS",
            "score": pos.get("score", 50),
            "exit_reason": exit_reason,
            "exit_rationale": ai_rationale or exit_reason,
            "remaining_cash": self.cash,
        }

    def process_autonomous_signals(
        self,
        analyzed_stocks: List[Dict[str, Any]],
        max_positions: int = 4,
        min_buy_score: int = 70
    ) -> Dict[str, Any]:
        """Autonomous AI trading loop: evaluates open positions for exits and deploys available credits into top buy setups."""
        latest_prices = {s["symbol"]: s.get("current_price", 0.0) for s in analyzed_stocks if s.get("current_price")}
        sells_executed = []
        buys_executed = []

        # 1. Check exits on active positions
        for sym, pos in list(self.positions.items()):
            curr_price = latest_prices.get(sym)
            if not curr_price or curr_price <= 0:
                continue

            sl = pos.get("stop_loss", 0.0)
            tp1 = pos.get("take_profit_1", 0.0)
            tp2 = pos.get("take_profit_2", 0.0)
            c_sym = "₹" if (pos.get("currency") == "INR" or sym.endswith((".NS", ".BO"))) else "$"

            # Find matching stock analysis for sell triggers
            stock_data = next((s for s in analyzed_stocks if s.get("symbol") == sym), None)
            triggers = stock_data.get("triggers", {}) if stock_data else {}
            sell_t = triggers.get("sell", {})

            # Exit rule 1: Stop-loss breached
            if sl > 0 and curr_price <= sl:
                res = self.sell(
                    sym,
                    curr_price,
                    exit_reason="STOP_LOSS_HIT",
                    ai_rationale=f"ATR Stop Loss hit at {c_sym}{curr_price:.2f} (SL level: {c_sym}{sl:.2f}). Capital protected."
                )
                sells_executed.append(res)
            # Exit rule 2: TP2 target reached
            elif tp2 > 0 and curr_price >= tp2:
                res = self.sell(
                    sym,
                    curr_price,
                    exit_reason="TAKE_PROFIT_2",
                    ai_rationale=f"Take-Profit 2 reached at {c_sym}{curr_price:.2f} (Analyst Target was {c_sym}{tp2:.2f}). Full target captured."
                )
                sells_executed.append(res)
            # Exit rule 3: TP1 target reached
            elif tp1 > 0 and curr_price >= tp1:
                res = self.sell(
                    sym,
                    curr_price,
                    exit_reason="TAKE_PROFIT_1",
                    ai_rationale=f"Take-Profit 1 reached at {c_sym}{curr_price:.2f} (Target was {c_sym}{tp1:.2f}). Profit booked."
                )
                sells_executed.append(res)
            # Exit rule 4: Severe Bearish breakdown or Overbought Trim trigger
            elif sell_t.get("triggered") and sell_t.get("type") in ["BEARISH_BREAKDOWN", "OVERBOUGHT_TRIM"]:
                res = self.sell(
                    sym,
                    curr_price,
                    exit_reason=sell_t.get("type"),
                    ai_rationale=sell_t.get("instruction") or f"AI Sell Signal triggered ({sell_t.get('type')})."
                )
                sells_executed.append(res)

        # 2. Check buys if capacity and cash available
        available_slots = max(0, max_positions - len(self.positions))
        if available_slots > 0 and self.cash >= 20.0:
            target_allocation = round(min(250.0, self.cash / available_slots), 2)
            # Filter and sort by confluence score descending
            candidates = [
                s for s in analyzed_stocks
                if s.get("score", 0) >= min_buy_score
                and "BUY" in s.get("signal", "")
                and s.get("symbol") not in self.positions
                and s.get("current_price", 0) > 0
            ]
            candidates.sort(key=lambda x: x.get("score", 0), reverse=True)

            for c in candidates:
                if self.cash < 20.0 or len(self.positions) >= max_positions:
                    break

                sym = c["symbol"]
                price = c["current_price"]
                ex = c.get("execution", {})
                sl = ex.get("stop_loss") or round(price * 0.95, 2)
                tp1 = ex.get("take_profit_1") or round(price * 1.05, 2)
                tp2 = ex.get("take_profit_2") or round(price * 1.15, 2)
                triggers = c.get("triggers", {})
                buy_t = triggers.get("buy", {})

                rationale = buy_t.get("instruction") or (
                    f"AI Confluence Score {c.get('score')}/100 ({c.get('conviction', 'HIGH')}). "
                    f"Entry: {ex.get('entry_zone', str(price))}, SL: ${sl:.2f}, TP1: ${tp1:.2f}, R:R: 1:{ex.get('risk_reward_tp1', 1.5)}"
                )

                res = self.buy(
                    symbol=sym,
                    price=price,
                    allocation=target_allocation,
                    stop_loss=sl,
                    take_profit_1=tp1,
                    take_profit_2=tp2,
                    score=c.get("score", 70),
                    signal=c.get("signal", "BUY"),
                    currency=c.get("currency", "USD"),
                    conviction=c.get("conviction", "HIGH"),
                    ai_rationale=rationale
                )
                if res.get("success"):
                    buys_executed.append(res)

        return {
            "buys_executed": buys_executed,
            "sells_executed": sells_executed,
            "total_open_positions": len(self.positions),
            "cash": self.cash,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def evaluate_live_stops(self, latest_prices: Dict[str, float]) -> List[Dict[str, Any]]:
        """Evaluates open positions against live prices and executes automatic Stop-Loss or TP exits."""
        executed_exits = []
        for sym, pos in list(self.positions.items()):
            curr_price = latest_prices.get(sym)
            if not curr_price or curr_price <= 0:
                continue

            sl = pos.get("stop_loss", 0.0)
            tp1 = pos.get("take_profit_1", 0.0)
            tp2 = pos.get("take_profit_2", 0.0)
            c_sym = "₹" if (pos.get("currency") == "INR" or sym.endswith((".NS", ".BO"))) else "$"

            # Condition 1: Stop-loss breached
            if sl > 0 and curr_price <= sl:
                res = self.sell(sym, curr_price, exit_reason="STOP_LOSS_HIT", ai_rationale=f"ATR Stop Loss hit at {c_sym}{curr_price:.2f} (SL was {c_sym}{sl:.2f})")
                executed_exits.append(res)
            # Condition 2: TP2 secondary target reached
            elif tp2 > 0 and curr_price >= tp2:
                res = self.sell(sym, curr_price, exit_reason="TAKE_PROFIT_2", ai_rationale=f"Take Profit 2 target hit at {c_sym}{curr_price:.2f}")
                executed_exits.append(res)
            # Condition 3: TP1 swing target reached
            elif tp1 > 0 and curr_price >= tp1:
                res = self.sell(sym, curr_price, exit_reason="TAKE_PROFIT_1", ai_rationale=f"Take Profit 1 target hit at {c_sym}{curr_price:.2f}")
                executed_exits.append(res)

        return executed_exits

    def auto_invest_top_picks(self, analyzed_stocks: List[Dict[str, Any]], max_positions: int = 4) -> List[Dict[str, Any]]:
        """Automatically deploys virtual funds into top high-confluence BUY candidates."""
        res = self.process_autonomous_signals(analyzed_stocks, max_positions=max_positions)
        return res.get("buys_executed", [])

    def get_summary(self, live_prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Calculates comprehensive portfolio metrics, unrealized P&L, and win rates."""
        live_prices = live_prices or {}
        open_positions_list = []
        total_open_value = 0.0

        for sym, pos in self.positions.items():
            curr_price = live_prices.get(sym, pos["entry_price"])
            shares = pos["shares"]
            is_inr = pos.get("currency") == "INR" or sym.endswith((".NS", ".BO"))
            fx_rate = pos.get("fx_rate") or (get_usd_inr_rate() if is_inr else 1.0)

            curr_price_usd = round(curr_price / fx_rate, 4) if is_inr else curr_price
            entry_price_usd = pos.get("entry_price_usd", round(pos["entry_price"] / fx_rate, 4) if is_inr else pos["entry_price"])

            curr_val = round(shares * curr_price_usd, 2)
            invested = pos["invested"]
            unrealized_pnl = round(curr_val - invested, 2)
            unrealized_pct = round(((curr_price - pos["entry_price"]) / pos["entry_price"]) * 100, 2) if pos["entry_price"] else 0.0

            total_open_value += curr_val
            open_positions_list.append({
                "symbol": sym,
                "shares": shares,
                "entry_price": pos["entry_price"],
                "entry_price_usd": entry_price_usd,
                "current_price": curr_price,
                "current_price_usd": curr_price_usd,
                "fx_rate": fx_rate,
                "invested": invested,
                "current_value": curr_val,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pct": unrealized_pct,
                "stop_loss": pos.get("stop_loss"),
                "take_profit_1": pos.get("take_profit_1"),
                "take_profit_2": pos.get("take_profit_2"),
                "entry_time": pos.get("entry_time"),
                "score": pos.get("score"),
                "currency": pos.get("currency", "USD"),
            })

        total_equity = round(self.cash + total_open_value, 2)
        total_pnl = round(total_equity - self.starting_balance, 2)
        total_pnl_pct = round((total_pnl / self.starting_balance) * 100, 2) if self.starting_balance else 0.0

        wins = sum(1 for t in self.trade_history if t.get("result") == "WIN")
        losses = sum(1 for t in self.trade_history if t.get("result") == "LOSS")
        total_closed = len(self.trade_history)
        win_rate = round((wins / total_closed) * 100, 1) if total_closed > 0 else 0.0

        gross_profit = sum(t["pnl_amount"] for t in self.trade_history if t["pnl_amount"] > 0)
        gross_loss = abs(sum(t["pnl_amount"] for t in self.trade_history if t["pnl_amount"] < 0))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 1.0)
        realized_pnl = round(sum(t.get("pnl_amount", 0.0) for t in self.trade_history), 2)
        unrealized_total = round(sum(p["unrealized_pnl"] for p in open_positions_list), 2)

        return {
            "starting_balance": self.starting_balance,
            "cash": round(self.cash, 2),
            "open_positions_value": round(total_open_value, 2),
            "total_equity": total_equity,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_total,
            "total_trades": total_closed,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "open_positions_count": len(open_positions_list),
            "positions": open_positions_list,
            "trade_history": list(reversed(self.trade_history[-50:])),
        }

class PracticePortfolio(PaperPortfolio):
    """Manages user's manual sandbox trading account ($1,000 credits) to test AI guidance."""
    def __init__(self, file_path: str = PRACTICE_FILE, initial_balance: float = 1000.0):
        super().__init__(file_path=file_path, initial_balance=initial_balance)
