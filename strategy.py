from typing import Dict, Any, List, Optional

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
        }
