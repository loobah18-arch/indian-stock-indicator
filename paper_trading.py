#!/usr/bin/env python3
import os
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

PORTFOLIO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio.json")

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
        currency: str = "USD"
    ) -> Dict[str, Any]:
        """Executes simulated paper buy order using virtual funds."""
        if price <= 0:
            return {"success": False, "error": "Invalid price"}

        if self.cash < 10.0:
            return {"success": False, "error": f"Insufficient virtual cash (${self.cash:.2f} available)"}

        # Position sizing: up to allocation or remaining cash
        invest_amount = min(allocation, self.cash)
        shares = round(invest_amount / price, 4)
        actual_invested = round(shares * price, 2)

        self.cash = round(self.cash - actual_invested, 2)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        position_data = {
            "symbol": symbol,
            "entry_price": price,
            "shares": shares,
            "invested": actual_invested,
            "entry_time": now_str,
            "stop_loss": stop_loss or round(price * 0.95, 2),
            "take_profit_1": take_profit_1 or round(price * 1.05, 2),
            "take_profit_2": take_profit_2 or round(price * 1.15, 2),
            "score": score,
            "signal": signal,
            "currency": currency,
        }

        # If already holding, average in
        if symbol in self.positions:
            old = self.positions[symbol]
            tot_shares = old["shares"] + shares
            tot_invested = old["invested"] + actual_invested
            avg_price = round(tot_invested / tot_shares, 2)
            old["shares"] = round(tot_shares, 4)
            old["invested"] = round(tot_invested, 2)
            old["entry_price"] = avg_price
            old["stop_loss"] = stop_loss or old["stop_loss"]
            old["take_profit_1"] = take_profit_1 or old["take_profit_1"]
            old["take_profit_2"] = take_profit_2 or old["take_profit_2"]
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
            "invested": actual_invested,
            "remaining_cash": self.cash,
        }

    def sell(self, symbol: str, price: float, exit_reason: str = "MANUAL", shares_to_sell: Optional[float] = None) -> Dict[str, Any]:
        """Liquidates paper position and books realized profit/loss."""
        if symbol not in self.positions:
            return {"success": False, "error": f"No active position for {symbol}"}

        pos = self.positions[symbol]
        curr_shares = pos["shares"]
        shares = min(shares_to_sell or curr_shares, curr_shares)

        fraction = shares / curr_shares
        portion_invested = round(pos["invested"] * fraction, 2)
        gross_proceeds = round(shares * price, 2)
        pnl = round(gross_proceeds - portion_invested, 2)
        pnl_pct = round(((price - pos["entry_price"]) / pos["entry_price"]) * 100, 2)

        self.cash = round(self.cash + gross_proceeds, 2)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        trade_record = {
            "id": f"trade_{symbol}_{int(time.time())}",
            "symbol": symbol,
            "entry_price": pos["entry_price"],
            "exit_price": price,
            "shares": shares,
            "invested": portion_invested,
            "proceeds": gross_proceeds,
            "pnl_amount": pnl,
            "pnl_pct": pnl_pct,
            "result": "WIN" if pnl >= 0 else "LOSS",
            "entry_time": pos["entry_time"],
            "exit_time": now_str,
            "exit_reason": exit_reason,
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
            "exit_reason": exit_reason,
            "remaining_cash": self.cash,
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

            # Condition 1: Stop-loss breached
            if sl > 0 and curr_price <= sl:
                res = self.sell(sym, curr_price, exit_reason="STOP_LOSS_HIT")
                executed_exits.append(res)
            # Condition 2: TP2 secondary target reached
            elif tp2 > 0 and curr_price >= tp2:
                res = self.sell(sym, curr_price, exit_reason="TAKE_PROFIT_2")
                executed_exits.append(res)
            # Condition 3: TP1 swing target reached
            elif tp1 > 0 and curr_price >= tp1:
                res = self.sell(sym, curr_price, exit_reason="TAKE_PROFIT_1")
                executed_exits.append(res)

        return executed_exits

    def auto_invest_top_picks(self, analyzed_stocks: List[Dict[str, Any]], max_positions: int = 4) -> List[Dict[str, Any]]:
        """Automatically deploys virtual funds into top high-confluence BUY candidates."""
        # Filter for BUY / STRONG BUY candidates
        buys = [
            s for s in analyzed_stocks
            if "BUY" in s.get("signal", "") and s.get("score", 0) >= 70 and s.get("current_price", 0) > 0
        ]
        buys.sort(key=lambda x: x.get("score", 0), reverse=True)

        executed = []
        if not buys or self.cash < 20.0:
            return executed

        # Target allocation per position (e.g. up to $250 for 4 slots)
        available_slots = max(1, max_positions - len(self.positions))
        target_allocation = round(min(250.0, self.cash / available_slots), 2)

        for stock in buys:
            sym = stock["symbol"]
            if sym in self.positions:
                continue
            if self.cash < 20.0:
                break

            price = stock["current_price"]
            ex = stock.get("execution", {})
            sl = ex.get("stop_loss") or round(price * 0.95, 2)
            tp1 = ex.get("take_profit_1") or round(price * 1.05, 2)
            tp2 = ex.get("take_profit_2") or round(price * 1.15, 2)

            res = self.buy(
                symbol=sym,
                price=price,
                allocation=target_allocation,
                stop_loss=sl,
                take_profit_1=tp1,
                take_profit_2=tp2,
                score=stock.get("score", 70),
                signal=stock.get("signal", "BUY"),
                currency=stock.get("currency", "USD")
            )
            if res.get("success"):
                executed.append(res)

        return executed

    def get_summary(self, live_prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Calculates comprehensive portfolio metrics, unrealized P&L, and win rates."""
        live_prices = live_prices or {}
        open_positions_list = []
        total_open_value = 0.0

        for sym, pos in self.positions.items():
            curr_price = live_prices.get(sym, pos["entry_price"])
            shares = pos["shares"]
            curr_val = round(shares * curr_price, 2)
            invested = pos["invested"]
            unrealized_pnl = round(curr_val - invested, 2)
            unrealized_pct = round(((curr_price - pos["entry_price"]) / pos["entry_price"]) * 100, 2) if pos["entry_price"] else 0.0

            total_open_value += curr_val
            open_positions_list.append({
                "symbol": sym,
                "shares": shares,
                "entry_price": pos["entry_price"],
                "current_price": curr_price,
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
