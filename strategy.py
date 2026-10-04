import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

IST = timezone(timedelta(hours=5, minutes=30))

def fmt_ist(ts: float, fmt: str = "%H:%M:%S IST") -> str:
    return datetime.fromtimestamp(ts, tz=IST).strftime(fmt)

def fmt_ist_full(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=IST).strftime("%Y-%m-%d %H:%M:%S IST")

class IndicatorStrategy:
    """Quantitative 5-Pillar Confluence Engine for high-precision stock signals."""

    def __init__(self, min_upside_pct: float = 5.0, rsi_overbought: float = 72.0, rsi_oversold: float = 30.0):
        self.min_upside_pct = min_upside_pct
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates 0-100 Precision Confluence Score and computes exact Entry, SL, and TP levels."""
        analyst = data.get("analyst") or {}
        tech = data.get("technical") or {}

        symbol = data.get("symbol", "")
        name = analyst.get("name") or symbol
        current_price = analyst.get("current_price") or tech.get("latest_close") or 0.0
        currency = analyst.get("currency", "INR")
        target_price = analyst.get("target_mean_price")
        target_high = analyst.get("target_high_price")
        target_low = analyst.get("target_low_price")
        upside_pct = analyst.get("upside_pct", 0.0)
        rec_mean = analyst.get("recommendation_mean")
        rec_key = (analyst.get("recommendation_key") or "hold").lower()
        analyst_count = analyst.get("analyst_count", 0)
        breakdown = analyst.get("breakdown", {})

        total_opinions = sum(breakdown.values()) or analyst_count or 1
        bullish_count = breakdown.get("strongBuy", 0) + breakdown.get("buy", 0)
        bearish_count = breakdown.get("sell", 0) + breakdown.get("strongSell", 0)
        hold_count = breakdown.get("hold", 0)

        # Technical Metrics
        rsi = tech.get("rsi_14")
        ema9 = tech.get("ema_9")
        ema21 = tech.get("ema_21")
        ema50 = tech.get("ema_50")
        ema200 = tech.get("ema_200")
        above_ema9 = tech.get("trend_above_ema9", False)
        above_ema21 = tech.get("trend_above_ema21", False)
        above_ema50 = tech.get("trend_above_ema50", False)
        above_ema200 = tech.get("trend_above_ema200", False)
        golden_cross = tech.get("golden_cross", False)
        ema_aligned = tech.get("ema_alignment_bullish", False)
        macd_line = tech.get("macd_line")
        macd_signal = tech.get("macd_signal")
        macd_hist = tech.get("macd_hist", 0.0)
        macd_bullish = tech.get("macd_bullish", False)
        macd_expanding = tech.get("macd_expanding", False)
        bb_pct_b = tech.get("bb_pct_b", 0.5)
        bb_bandwidth = tech.get("bb_bandwidth", 0.0)
        atr = tech.get("atr_14", current_price * 0.02)
        rvol = tech.get("rvol", 1.0)
        sparkline = tech.get("sparkline", [])

        # ==========================================
        # 5-PILLAR PRECISION CONFLUENCE SCORING (0 - 100)
        # ==========================================
        pillar_scores = {
            "expert_valuation": 0,    # Max 25
            "trend_regime": 0,        # Max 25
            "momentum_oscillator": 0, # Max 20
            "volatility_extremes": 0, # Max 15
            "volume_flow": 0          # Max 15
        }

        # Pillar 1: Institutional Analyst & Valuation (25 pts)
        is_etf = (symbol in ["SPY", "QQQ", "DIA", "IWM", "^NSEI", "^BSESN"]) or (analyst_count == 0 and rec_mean is None)
        if is_etf:
            if above_ema200:
                pillar_scores["expert_valuation"] = 18 if above_ema21 else 14
            else:
                pillar_scores["expert_valuation"] = 8
        else:
            if rec_mean is not None:
                if rec_mean <= 1.5:
                    pillar_scores["expert_valuation"] += 12
                elif rec_mean <= 1.9:
                    pillar_scores["expert_valuation"] += 10
                elif rec_mean <= 2.3:
                    pillar_scores["expert_valuation"] += 7
                elif rec_mean <= 2.8:
                    pillar_scores["expert_valuation"] += 4
                elif rec_mean >= 3.6:
                    pillar_scores["expert_valuation"] -= 8

            if upside_pct >= 30.0:
                pillar_scores["expert_valuation"] += 8
            elif upside_pct >= 18.0:
                pillar_scores["expert_valuation"] += 6
            elif upside_pct >= 8.0:
                pillar_scores["expert_valuation"] += 4
            elif upside_pct <= -5.0:
                pillar_scores["expert_valuation"] -= 6

            if analyst_count >= 20:
                pillar_scores["expert_valuation"] += 5
            elif analyst_count >= 8:
                pillar_scores["expert_valuation"] += 3

        pillar_scores["expert_valuation"] = max(0, min(25, pillar_scores["expert_valuation"]))

        # Pillar 2: Trend & Moving Average Regime (25 pts)
        if above_ema200:
            pillar_scores["trend_regime"] += 8
        if ema_aligned:
            pillar_scores["trend_regime"] += 8
        elif above_ema21:
            pillar_scores["trend_regime"] += 5
        if above_ema9:
            pillar_scores["trend_regime"] += 5
        if golden_cross:
            pillar_scores["trend_regime"] += 4

        pillar_scores["trend_regime"] = max(0, min(25, pillar_scores["trend_regime"]))

        # Pillar 3: Momentum & Oscillators (20 pts)
        if rsi is not None:
            if 42.0 <= rsi <= 64.0:
                pillar_scores["momentum_oscillator"] += 10
            elif 30.0 <= rsi < 42.0:
                pillar_scores["momentum_oscillator"] += 8
            elif 64.0 < rsi <= 70.0:
                pillar_scores["momentum_oscillator"] += 5
            elif rsi < 30.0:
                pillar_scores["momentum_oscillator"] += 6
            elif rsi > self.rsi_overbought:
                pillar_scores["momentum_oscillator"] += 1  # Penalty for overbought

        if macd_bullish:
            pillar_scores["momentum_oscillator"] += 5
        if macd_expanding:
            pillar_scores["momentum_oscillator"] += 5

        pillar_scores["momentum_oscillator"] = max(0, min(20, pillar_scores["momentum_oscillator"]))

        # Pillar 4: Volatility & Bollinger Bands (15 pts)
        if bb_pct_b is not None:
            if 0.15 <= bb_pct_b <= 0.60:
                pillar_scores["volatility_extremes"] += 10
            elif 0.60 < bb_pct_b <= 0.85:
                pillar_scores["volatility_extremes"] += 7
            elif bb_pct_b > 0.95:
                pillar_scores["volatility_extremes"] += 2
            else:
                pillar_scores["volatility_extremes"] += 4

        if bb_bandwidth > 0 and bb_bandwidth < 12.0:
            pillar_scores["volatility_extremes"] += 5  # Volatility Squeeze setup

        pillar_scores["volatility_extremes"] = max(0, min(15, pillar_scores["volatility_extremes"]))

        # Pillar 5: Volume Flow (15 pts)
        if rvol >= 1.3:
            pillar_scores["volume_flow"] += 15
        elif rvol >= 1.0:
            pillar_scores["volume_flow"] += 10
        elif rvol >= 0.7:
            pillar_scores["volume_flow"] += 6
        else:
            pillar_scores["volume_flow"] += 3

        pillar_scores["volume_flow"] = max(0, min(15, pillar_scores["volume_flow"]))

        # Aggregate Precision Score (0 - 100)
        total_score = sum(pillar_scores.values())

        # ==========================================
        # SIGNAL CLASSIFICATION & ACTION
        # ==========================================
        is_overbought = (rsi is not None and rsi >= self.rsi_overbought)
        
        if total_score >= 80:
            if is_overbought:
                signal = "HOLD"
                action_verb = "WAIT FOR PULLBACK"
                conviction = "High (Overbought Entry Blocked)"
            else:
                signal = "STRONG BUY"
                action_verb = "AGGRESSIVE BUY"
                conviction = "Ultra High Conviction"
        elif total_score >= 65:
            if is_overbought:
                signal = "HOLD"
                action_verb = "WAIT FOR PULLBACK"
                conviction = "Moderate (Overbought)"
            else:
                signal = "BUY"
                action_verb = "ACCUMULATE ON DIP"
                conviction = "High Conviction"
        elif total_score <= 30:
            signal = "STRONG SELL"
            action_verb = "EXIT ALL / SHORT"
            conviction = "High Bearish Conviction"
        elif total_score <= 45:
            signal = "SELL"
            action_verb = "TRIM POSITIONS"
            conviction = "Moderate Bearish"
        else:
            signal = "HOLD"
            action_verb = "NEUTRAL / WAIT"
            conviction = "Neutral / Low Edge"

        # ==========================================
        # PRECISE EXECUTION LEVELS (SL, TP1, TP2, R:R)
        # ==========================================
        volatility_buffer = max(atr * 1.5, current_price * 0.02)
        stop_loss = round(max(current_price - volatility_buffer, current_price * 0.85), 2)
        sl_risk_pct = round(((current_price - stop_loss) / current_price) * 100, 2) if current_price else 0.0

        tp1_buffer = max(atr * 2.2, current_price * 0.035)
        take_profit_1 = round(current_price + tp1_buffer, 2)
        tp1_gain_pct = round(((take_profit_1 - current_price) / current_price) * 100, 2) if current_price else 0.0

        take_profit_2 = target_price if (target_price and target_price > current_price) else round(current_price + (tp1_buffer * 2.0), 2)
        tp2_gain_pct = round(((take_profit_2 - current_price) / current_price) * 100, 2) if current_price else 0.0

        risk_reward_tp1 = round(tp1_gain_pct / max(sl_risk_pct, 0.1), 2)
        risk_reward_tp2 = round(tp2_gain_pct / max(sl_risk_pct, 0.1), 2)

        entry_low = round(current_price - (atr * 0.4), 2)
        entry_high = round(current_price + (atr * 0.2), 2)
        curr_sym = "$" if currency == "USD" else "₹"
        entry_zone = f"{curr_sym}{entry_low:,.2f} – {curr_sym}{entry_high:,.2f}"

        # Actionable Buy / Sell Triggers
        buy_active = (signal in ["STRONG BUY", "BUY"]) and (not is_overbought) and (current_price <= entry_high * 1.015)
        buy_trigger = {
            "triggered": bool(buy_active),
            "type": "BUY" if buy_active else "NONE",
            "action": "BUY IN ZONE" if (entry_low <= current_price <= entry_high) else ("ACCUMULATE ON DIP" if buy_active else "WAIT FOR SETUP"),
            "entry_range": entry_zone,
            "stop_loss": f"{curr_sym}{stop_loss:,.2f} (-{sl_risk_pct}%)",
            "take_profit_1": f"{curr_sym}{take_profit_1:,.2f} (+{tp1_gain_pct}%)",
            "take_profit_2": f"{curr_sym}{take_profit_2:,.2f} (+{tp2_gain_pct}%)",
            "instruction": f"🟢 WHEN TO BUY: Enter between {curr_sym}{entry_low:,.2f}–{curr_sym}{entry_high:,.2f}. SL at {curr_sym}{stop_loss:,.2f} (-{sl_risk_pct}%). Target TP1: {curr_sym}{take_profit_1:,.2f} (+{tp1_gain_pct}%)." if buy_active else "Wait for confluence score >= 65 and entry zone retest before opening new long."
        }

        sell_reason = None
        sell_action = "HOLD"
        sell_type = "NONE"
        if current_price >= take_profit_2 and take_profit_2 > 0:
            sell_type = "TAKE_PROFIT_2"
            sell_action = "SELL ALL (TP2 TARGET HIT)"
            sell_reason = f"Price reached secondary analyst target of {curr_sym}{take_profit_2:,.2f} (+{tp2_gain_pct}%). Secure full profits."
        elif current_price >= take_profit_1 and take_profit_1 > 0:
            sell_type = "TAKE_PROFIT_1"
            sell_action = "SELL 50% (TP1 SWING HIT)"
            sell_reason = f"Price reached swing target {curr_sym}{take_profit_1:,.2f} (+{tp1_gain_pct}%). Trim 50% profits and move SL to breakeven."
        elif current_price <= stop_loss and stop_loss > 0:
            sell_type = "STOP_LOSS_HIT"
            sell_action = "EXIT ALL (STOP LOSS BREACHED)"
            sell_reason = f"Price dropped below stop loss {curr_sym}{stop_loss:,.2f} (-{sl_risk_pct}%). Exit immediately to preserve capital."
        elif rsi and rsi >= 75.0:
            sell_type = "OVERBOUGHT_TRIM"
            sell_action = "TRIM PROFITS (EXTREME OVERBOUGHT)"
            sell_reason = f"Wilder RSI reached {rsi:.1f} (overbought). Take partial profits or tighten trailing stop."
        elif signal in ["SELL", "STRONG SELL"]:
            sell_type = "BEARISH_BREAKDOWN"
            sell_action = "EXIT / AVOID"
            sell_reason = f"Technical confluence breakdown with score of {total_score}/100. Trend is hostile."

        sell_trigger = {
            "triggered": sell_type != "NONE",
            "type": sell_type,
            "action": sell_action,
            "reason": sell_reason,
            "instruction": f"🔴 WHEN TO SELL: {sell_reason}" if sell_reason else f"🔴 WHEN TO SELL: Exit at {curr_sym}{take_profit_1:,.2f} (TP1: +{tp1_gain_pct}%) to lock gains, or cut at {curr_sym}{stop_loss:,.2f} (SL: -{sl_risk_pct}%) if price reverses."
        }

        # Analytical Rationale
        notes = []
        if total_score >= 65:
            notes.append(f"Precision Score: {total_score}/100. High institutional alignment with {bullish_count}/{total_opinions} Buy consensus and +{upside_pct}% target.")
            if above_ema200:
                notes.append("Confirmed above 200 EMA macro bull regime.")
            if rsi:
                notes.append(f"RSI({rsi:.1f}) provides comfortable entry runway.")
            if rvol >= 1.2:
                notes.append(f"Volume is elevated ({rvol:.2f}x RVOL) confirming smart money participation.")
        elif total_score <= 45:
            notes.append(f"Precision Score: {total_score}/100. Weak institutional sponsorship or breakdown below EMA trendlines.")
        else:
            notes.append(f"Precision Score: {total_score}/100. Mixed indicators. Consolidation phase.")

        color_map = {
            "STRONG BUY": 0x00E676,
            "BUY": 0x2ECC71,
            "HOLD": 0xF1C40F,
            "SELL": 0xE67E22,
            "STRONG SELL": 0xE74C3C,
        }

        return {
            "symbol": symbol,
            "name": name,
            "current_price": current_price,
            "currency": currency,
            "signal": signal,
            "action_verb": action_verb,
            "conviction": conviction,
            "score": total_score,
            "pillar_scores": pillar_scores,
            "color": color_map.get(signal, 0x95A5A6),
            "target_price": target_price,
            "upside_pct": upside_pct,
            "recommendation_mean": rec_mean,
            "recommendation_key": rec_key,
            "analyst_count": analyst_count,
            "breakdown": breakdown,
            "triggers": {
                "buy": buy_trigger,
                "sell": sell_trigger,
            },
            "execution": {
                "entry_zone": entry_zone,
                "current_price": current_price,
                "stop_loss": stop_loss,
                "sl_risk_pct": sl_risk_pct,
                "take_profit_1": take_profit_1,
                "tp1_gain_pct": tp1_gain_pct,
                "take_profit_2": take_profit_2,
                "tp2_gain_pct": tp2_gain_pct,
                "risk_reward_tp1": risk_reward_tp1,
                "risk_reward_tp2": risk_reward_tp2,
                "atr": atr,
            },
            "technicals": {
                "rsi_14": rsi,
                "ema_9": ema9,
                "ema_21": ema21,
                "ema_50": ema50,
                "ema_200": ema200,
                "above_ema200": above_ema200,
                "above_ema21": above_ema21,
                "golden_cross": golden_cross,
                "macd_line": macd_line,
                "macd_signal": macd_signal,
                "macd_hist": macd_hist,
                "macd_bullish": macd_bullish,
                "bb_pct_b": bb_pct_b,
                "bb_bandwidth": bb_bandwidth,
                "rvol": rvol,
                "sparkline": sparkline,
            },
            "rationale": " ".join(notes),
            "timing": self.compute_chart_timing(
                tech=tech,
                signal=signal,
                score=total_score,
                current_price=current_price,
                timeframe=data.get("timeframe", tech.get("timeframe", "1d")),
                currency=currency
            )
        }

    def compute_chart_timing(
        self,
        tech: Dict[str, Any],
        signal: str,
        score: int,
        current_price: float,
        timeframe: str = "1d",
        currency: str = "USD"
    ) -> Dict[str, Any]:
        """Pinpoints the exact candle trigger timestamp, execution window, and seconds countdown to next bar."""
        now = int(time.time())
        timestamps = tech.get("timestamps", [])
        candle_sec = tech.get("candle_interval_sec") or {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1h": 3600, "1d": 86400, "1w": 604800}.get(timeframe.lower(), 60)
        latest_ts = tech.get("latest_timestamp") or (timestamps[-1] if timestamps else now)
        next_candle_ts = latest_ts + candle_sec

        if abs(now - latest_ts) <= candle_sec * 3:
            seconds_remaining = max(0, next_candle_ts - now)
        else:
            live_boundary = (now // candle_sec) * candle_sec
            seconds_remaining = max(0, (live_boundary + candle_sec) - now)

        recent_closes = tech.get("recent_closes", [])
        recent_ema9 = tech.get("recent_ema9", [])
        recent_ema21 = tech.get("recent_ema21", [])
        recent_macd = tech.get("recent_macd", [])
        recent_macd_sig = tech.get("recent_macd_sig", [])

        trigger_ts = latest_ts
        trigger_reason = ""
        trigger_type = "TREND_CONTINUATION"

        n = min(len(recent_closes), len(recent_ema9), len(recent_ema21), len(timestamps))
        found_event = False

        if n >= 2:
            if "BUY" in signal:
                for idx in range(n - 1, 0, -1):
                    ts_bar = timestamps[idx]
                    if recent_ema9[idx] >= recent_ema21[idx] and recent_ema9[idx-1] < recent_ema21[idx-1]:
                        trigger_ts = ts_bar
                        trigger_reason = f"Bullish Crossover: 9 EMA crossed above 21 EMA at {fmt_ist(ts_bar)} (Price: {recent_closes[idx]})"
                        trigger_type = "EMA_BULLISH_CROSS"
                        found_event = True
                        break
                    elif len(recent_macd) > idx and len(recent_macd_sig) > idx:
                        if recent_macd[idx] >= recent_macd_sig[idx] and recent_macd[idx-1] < recent_macd_sig[idx-1]:
                            trigger_ts = ts_bar
                            trigger_reason = f"MACD Bullish Cross: Momentum flipped positive at {fmt_ist(ts_bar)}"
                            trigger_type = "MACD_BULLISH_CROSS"
                            found_event = True
                            break
                if not found_event:
                    trigger_reason = f"Bullish Accumulation: Price holding firmly above 9 EMA with high confluence score ({score}/100)"
                    trigger_type = "BULLISH_MOMENTUM"

            elif "SELL" in signal:
                for idx in range(n - 1, 0, -1):
                    ts_bar = timestamps[idx]
                    if recent_ema9[idx] <= recent_ema21[idx] and recent_ema9[idx-1] > recent_ema21[idx-1]:
                        trigger_ts = ts_bar
                        trigger_reason = f"Bearish Breakdown: 9 EMA fell below 21 EMA at {fmt_ist(ts_bar)} (Price: {recent_closes[idx]})"
                        trigger_type = "EMA_BEARISH_CROSS"
                        found_event = True
                        break
                    elif len(recent_macd) > idx and len(recent_macd_sig) > idx:
                        if recent_macd[idx] <= recent_macd_sig[idx] and recent_macd[idx-1] > recent_macd_sig[idx-1]:
                            trigger_ts = ts_bar
                            trigger_reason = f"MACD Bearish Cross: Momentum turned negative at {fmt_ist(ts_bar)}"
                            trigger_type = "MACD_BEARISH_CROSS"
                            found_event = True
                            break
                if not found_event:
                    trigger_reason = f"Bearish Pressure: Downward momentum dominant with low confluence score ({score}/100)"
                    trigger_type = "BEARISH_MOMENTUM"

            else:
                trigger_reason = f"Consolidation / Rangebound: Score {score}/100. Price compressing between EMAs. Awaiting breakout."
                trigger_type = "CONSOLIDATION"
        else:
            if "BUY" in signal:
                trigger_reason = f"Bullish setup: Confluence Score {score}/100"
                trigger_type = "BULLISH_MOMENTUM"
            elif "SELL" in signal:
                trigger_reason = f"Bearish setup: Confluence Score {score}/100"
                trigger_type = "BEARISH_MOMENTUM"
            else:
                trigger_reason = f"Consolidation: Confluence Score {score}/100"
                trigger_type = "CONSOLIDATION"

        is_buy = "BUY" in signal
        is_sell = "SELL" in signal

        if is_buy:
            action = "BUY"
            action_label = "▲ PERFECT TIME TO BUY (UP)"
            action_color = "#10b981"
            timing_status = "CONFIRMED_BUY_WINDOW"
            confidence_pct = min(98, max(65, score + 10))
            instruction = f"🟢 Confirmed BUY signal at {fmt_ist(trigger_ts)}. Open UP trade now or on the next candle open."
        elif is_sell:
            action = "SELL"
            action_label = "▼ PERFECT TIME TO SELL (DOWN)"
            action_color = "#ef4444"
            timing_status = "CONFIRMED_SELL_WINDOW"
            confidence_pct = min(95, max(60, 100 - score + 5))
            instruction = f"🔴 Confirmed SELL signal at {fmt_ist(trigger_ts)}. Open DOWN trade or exit long to preserve gains."
        else:
            action = "WAIT"
            action_label = "⏳ MONITORING (WAIT FOR SETUP)"
            action_color = "#60a5fa"
            timing_status = "MONITORING_CONSOLIDATION"
            confidence_pct = 50
            instruction = f"⏳ Neutral consolidation. Do not open positions prematurely. Monitor next candle close."

        trigger_time_ist = fmt_ist_full(trigger_ts)
        trigger_time_short = fmt_ist(trigger_ts)
        next_candle_time_ist = fmt_ist_full(next_candle_ts)
        next_candle_time_short = fmt_ist(next_candle_ts)

        # Retain UTC strings for backward compatibility
        trigger_time_utc = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(trigger_ts))
        next_candle_time_utc = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(next_candle_ts))

        window_end_ts = trigger_ts + (candle_sec * 3)
        optimal_window_str = f"{trigger_time_short} – {fmt_ist(window_end_ts)}"

        return {
            "action": action,
            "action_label": action_label,
            "action_color": action_color,
            "timing_status": timing_status,
            "timeframe": timeframe,
            "interval_seconds": candle_sec,
            "trigger_timestamp": trigger_ts,
            "trigger_time": trigger_time_ist,
            "trigger_time_ist": trigger_time_ist,
            "trigger_time_short": trigger_time_short,
            "trigger_time_utc": trigger_time_utc,
            "next_candle_timestamp": next_candle_ts,
            "next_candle_time": next_candle_time_ist,
            "next_candle_time_ist": next_candle_time_ist,
            "next_candle_time_short": next_candle_time_short,
            "next_candle_time_utc": next_candle_time_utc,
            "seconds_to_next_bar": seconds_remaining,
            "optimal_window": optimal_window_str,
            "confidence_pct": confidence_pct,
            "trigger_type": trigger_type,
            "trigger_reason": trigger_reason,
            "instruction": instruction,
            "confluence_score": score,
            "suggested_duration": timeframe,
        }
