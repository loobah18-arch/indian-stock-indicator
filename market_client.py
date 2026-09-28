import time
import math
import requests
from typing import Dict, Any, Optional, List, Tuple

# Common US tickers for fast direct routing
US_CORE_TICKERS = {
    "NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "GOOG", "META",
    "AMD", "SPY", "QQQ", "DIA", "IWM", "NFLX", "INTC", "AVGO",
    "PLTR", "COIN", "SMCI", "BABA", "ARM", "UBER", "DIS", "BA",
    "JPM", "V", "WMT", "ORCL", "CRM", "NKE", "PYPL"
}

_default_client: Optional['MarketClient'] = None

def normalize_symbol(symbol: str) -> str:
    """Module-level helper to resolve tickers for US and Indian markets."""
    global _default_client
    if _default_client is None:
        _default_client = MarketClient()
    return _default_client.resolve_symbol(symbol)

class MarketClient:
    """High-precision market data client supporting Indian (NSE/BSE) and US (NASDAQ/NYSE) markets."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.crumb: Optional[str] = None
        self._crumb_timestamp: float = 0.0

    def _ensure_crumb(self, force: bool = False) -> Optional[str]:
        """Fetch and cache Yahoo Finance crumb using cookie session."""
        now = time.time()
        if not force and self.crumb and (now - self._crumb_timestamp < 1800):
            return self.crumb

        try:
            self.session.get("https://fc.yahoo.com", timeout=10)
            resp = self.session.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
            if resp.status_code == 200 and resp.text.strip():
                self.crumb = resp.text.strip()
                self._crumb_timestamp = now
                return self.crumb
        except Exception:
            pass
        return None

    def resolve_symbol(self, symbol: str) -> str:
        """Intelligently resolves bare tickers to either US (NVDA) or Indian (RELIANCE.NS) symbols."""
        sym = symbol.strip().upper()
        if not sym:
            return sym
        if "." in sym or sym.startswith("^"):
            return sym

        if sym in US_CORE_TICKERS:
            return sym

        crumb = self._ensure_crumb()
        # Test as-is
        try:
            url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}?crumb={crumb or ''}&modules=price"
            r = self.session.get(url, timeout=6)
            if r.status_code == 200:
                res = r.json().get("quoteSummary", {}).get("result")
                if res and res[0].get("price", {}).get("regularMarketPrice", {}).get("raw") is not None:
                    return sym
        except Exception:
            pass

        # Fallback to Indian NSE
        try:
            url_ns = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}.NS?crumb={crumb or ''}&modules=price"
            r_ns = self.session.get(url_ns, timeout=6)
            if r_ns.status_code == 200:
                res = r_ns.json().get("quoteSummary", {}).get("result")
                if res and res[0].get("price", {}).get("regularMarketPrice", {}).get("raw") is not None:
                    return f"{sym}.NS"
        except Exception:
            pass

        # Fallback to Indian BSE
        try:
            url_bo = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}.BO?crumb={crumb or ''}&modules=price"
            r_bo = self.session.get(url_bo, timeout=6)
            if r_bo.status_code == 200:
                res = r_bo.json().get("quoteSummary", {}).get("result")
                if res and res[0].get("price", {}).get("regularMarketPrice", {}).get("raw") is not None:
                    return f"{sym}.BO"
        except Exception:
            pass

        return sym

    def get_analyst_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch analyst ratings, price targets, consensus, and currency for US or Indian stocks."""
        sym = self.resolve_symbol(symbol)
        crumb = self._ensure_crumb()
        if not crumb:
            crumb = self._ensure_crumb(force=True)

        url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
        params = {
            "modules": "financialData,recommendationTrend,price,defaultKeyStatistics",
            "crumb": crumb or ""
        }

        try:
            resp = self.session.get(url, params=params, timeout=12)
            if resp.status_code == 401:
                crumb = self._ensure_crumb(force=True)
                params["crumb"] = crumb or ""
                resp = self.session.get(url, params=params, timeout=12)

            if resp.status_code != 200:
                return None

            data = resp.json()
            results = data.get("quoteSummary", {}).get("result", [])
            if not results:
                return None

            item = results[0]
            price_info = item.get("price", {})
            fin_info = item.get("financialData", {})
            rec_trend = item.get("recommendationTrend", {})

            current_price = fin_info.get("currentPrice", {}).get("raw") or price_info.get("regularMarketPrice", {}).get("raw")
            target_mean = fin_info.get("targetMeanPrice", {}).get("raw")
            target_high = fin_info.get("targetHighPrice", {}).get("raw")
            target_low = fin_info.get("targetLowPrice", {}).get("raw")
            rec_key = fin_info.get("recommendationKey", "hold")
            rec_mean = fin_info.get("recommendationMean", {}).get("raw")
            analysts_count = fin_info.get("numberOfAnalystOpinions", {}).get("raw", 0)

            # Currency detection: USD vs INR
            currency = fin_info.get("financialCurrency") or price_info.get("currency")
            if not currency:
                currency = "INR" if (".NS" in sym or ".BO" in sym) else "USD"

            # Market detection
            if ".NS" in sym:
                market_name = "NSE (India)"
            elif ".BO" in sym:
                market_name = "BSE (India)"
            else:
                market_name = price_info.get("exchangeName", "US Market")

            breakdown = {"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0}
            trends = rec_trend.get("trend", [])
            if trends:
                curr_period = trends[0]
                breakdown = {
                    "strongBuy": curr_period.get("strongBuy", 0),
                    "buy": curr_period.get("buy", 0),
                    "hold": curr_period.get("hold", 0),
                    "sell": curr_period.get("sell", 0),
                    "strongSell": curr_period.get("strongSell", 0),
                }

            upside_pct = 0.0
            if current_price and target_mean:
                upside_pct = round(((target_mean - current_price) / current_price) * 100, 2)

            return {
                "symbol": sym,
                "name": price_info.get("shortName") or price_info.get("longName") or sym,
                "current_price": current_price,
                "currency": currency,
                "market": market_name,
                "day_change": price_info.get("regularMarketChange", {}).get("raw", 0.0),
                "day_change_pct": (price_info.get("regularMarketChangePercent", {}).get("raw", 0.0) or 0.0) * 100,
                "target_mean_price": target_mean,
                "target_high_price": target_high,
                "target_low_price": target_low,
                "upside_pct": upside_pct,
                "recommendation_key": rec_key,
                "recommendation_mean": rec_mean,
                "analyst_count": analysts_count,
                "breakdown": breakdown,
            }
        except Exception:
            return None

    def _calc_ema_series(self, values: List[float], period: int) -> List[float]:
        """Calculates Exponential Moving Average series."""
        if len(values) < period:
            return [values[-1]] * len(values)
        multiplier = 2.0 / (period + 1.0)
        ema = [sum(values[:period]) / period]
        for val in values[period:]:
            ema.append((val * multiplier) + (ema[-1] * (1.0 - multiplier)))
        pad = [ema[0]] * (len(values) - len(ema))
        return pad + ema

    def _calc_rsi(self, prices: List[float], period: int = 14) -> Optional[float]:
        """Calculates 14-period Wilder-smoothed RSI."""
        if len(prices) < period + 1:
            return None

        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0.0 for d in deltas]
        losses = [-d if d < 0 else 0.0 for d in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0.0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100.0 - (100.0 / (1.0 + rs)), 2)

    def _calc_atr(self, highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Calculates Average True Range."""
        if len(closes) < period + 1:
            return 0.0
        tr = []
        for i in range(1, len(closes)):
            h, l, prev_c = highs[i], lows[i], closes[i - 1]
            tr.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
        if len(tr) < period:
            return sum(tr) / max(len(tr), 1)
        atr = sum(tr[:period]) / period
        for i in range(period, len(tr)):
            atr = (atr * (period - 1) + tr[i]) / period
        return round(atr, 2)

    def get_technical_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch 1-year daily chart history and compute technicals (EMAs, MACD, RSI, BB, ATR, RVOL)."""
        sym = self.resolve_symbol(symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1y"

        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code != 200:
                return None

            data = resp.json()
            result = data.get("chart", {}).get("result", [])
            if not result:
                return None

            indicators = result[0].get("indicators", {})
            quote = indicators.get("quote", [{}])[0]

            raw_closes = quote.get("close", [])
            raw_highs = quote.get("high", [])
            raw_lows = quote.get("low", [])
            raw_volumes = quote.get("volume", [])

            records = []
            for i in range(len(raw_closes)):
                c = raw_closes[i]
                h = raw_highs[i] if i < len(raw_highs) else None
                l = raw_lows[i] if i < len(raw_lows) else None
                v = raw_volumes[i] if i < len(raw_volumes) else 0
                if c is not None and h is not None and l is not None:
                    records.append({"close": c, "high": h, "low": l, "volume": v or 0})

            if len(records) < 30:
                return None

            closes = [r["close"] for r in records]
            highs = [r["high"] for r in records]
            lows = [r["low"] for r in records]
            volumes = [r["volume"] for r in records]

            current_close = closes[-1]
            prev_close = closes[-2] if len(closes) >= 2 else current_close

            # EMAs: 9, 21, 50, 200
            ema9_series = self._calc_ema_series(closes, 9)
            ema21_series = self._calc_ema_series(closes, 21)
            ema50_series = self._calc_ema_series(closes, 50)
            ema200_series = self._calc_ema_series(closes, 200)

            ema9 = round(ema9_series[-1], 2)
            ema21 = round(ema21_series[-1], 2)
            ema50 = round(ema50_series[-1], 2)
            ema200 = round(ema200_series[-1], 2) if len(closes) >= 150 else None

            # MACD (12, 26, 9)
            ema12_series = self._calc_ema_series(closes, 12)
            ema26_series = self._calc_ema_series(closes, 26)
            macd_series = [ema12_series[i] - ema26_series[i] for i in range(len(closes))]
            signal_series = self._calc_ema_series(macd_series, 9)

            macd_line = round(macd_series[-1], 2)
            macd_signal = round(signal_series[-1], 2)
            macd_hist = round(macd_line - macd_signal, 2)
            prev_hist = round(macd_series[-2] - signal_series[-2], 2) if len(macd_series) >= 2 else macd_hist
            macd_expanding = macd_hist > prev_hist

            # RSI 14
            rsi_14 = self._calc_rsi(closes, period=14)

            # Bollinger Bands (20 periods, 2 std)
            slice20 = closes[-20:]
            sma20 = sum(slice20) / 20.0
            variance = sum((x - sma20) ** 2 for x in slice20) / 20.0
            std20 = math.sqrt(variance)
            upper_bb = round(sma20 + (2.0 * std20), 2)
            lower_bb = round(sma20 - (2.0 * std20), 2)
            mid_bb = round(sma20, 2)
            pct_b = round((current_close - lower_bb) / (upper_bb - lower_bb), 3) if upper_bb != lower_bb else 0.5
            bandwidth = round(((upper_bb - lower_bb) / mid_bb) * 100, 2) if mid_bb else 0.0

            # ATR 14
            atr_14 = self._calc_atr(highs, lows, closes, 14)
            atr_pct = round((atr_14 / current_close) * 100, 2) if current_close else 0.0

            # Volume & RVOL
            vol_slice = volumes[-20:]
            avg_vol_20 = sum(vol_slice) / len(vol_slice) if vol_slice else 1.0
            latest_vol = volumes[-1]
            rvol = round(latest_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 1.0

            # 52-Week High & Low
            high_52w = round(max(highs[-250:]), 2) if highs else current_close
            low_52w = round(min(lows[-250:]), 2) if lows else current_close
            dist_from_52w_high_pct = round(((high_52w - current_close) / high_52w) * 100, 2) if high_52w else 0.0

            sparkline = [round(c, 2) for c in closes[-30:]]

            return {
                "symbol": sym,
                "latest_close": round(current_close, 2),
                "prev_close": round(prev_close, 2),
                "ema_9": ema9,
                "ema_21": ema21,
                "ema_50": ema50,
                "ema_200": ema200,
                "trend_above_ema9": current_close >= ema9,
                "trend_above_ema21": current_close >= ema21,
                "trend_above_ema50": current_close >= ema50,
                "trend_above_ema200": (current_close >= ema200) if ema200 else None,
                "golden_cross": (ema50 >= ema200) if (ema50 and ema200) else None,
                "ema_alignment_bullish": (ema9 > ema21 > ema50),
                "rsi_14": rsi_14,
                "macd_line": macd_line,
                "macd_signal": macd_signal,
                "macd_hist": macd_hist,
                "macd_expanding": macd_expanding,
                "macd_bullish": macd_line > macd_signal,
                "bb_upper": upper_bb,
                "bb_middle": mid_bb,
                "bb_lower": lower_bb,
                "bb_pct_b": pct_b,
                "bb_bandwidth": bandwidth,
                "atr_14": atr_14,
                "atr_pct": atr_pct,
                "volume": latest_vol,
                "avg_volume_20": int(avg_vol_20),
                "rvol": rvol,
                "high_52w": high_52w,
                "low_52w": low_52w,
                "dist_from_52w_high_pct": dist_from_52w_high_pct,
                "sparkline": sparkline,
            }
        except Exception:
            return None

    def get_full_analysis(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Combine institutional analyst consensus and deep quantitative technicals for US or Indian ticker."""
        resolved = self.resolve_symbol(symbol)
        analyst = self.get_analyst_data(resolved)
        technical = self.get_technical_data(resolved)

        if not analyst and not technical:
            return None

        return {
            "symbol": resolved,
            "analyst": analyst,
            "technical": technical,
        }

    def get_market_overview(self, market: str = "US") -> Dict[str, Any]:
        """Analyzes broad market regime, index trends, and volatility gauge for US or Indian market."""
        market = market.upper()
        if not hasattr(self, "_market_cache"):
            self._market_cache = {}

        now = time.time()
        cached = self._market_cache.get(market)
        if cached and (now - cached["timestamp"] < 60):
            return cached["data"]

        if market == "IN":
            index_symbols = [
                {"symbol": "^NSEI", "name": "NIFTY 50", "currency": "INR"},
                {"symbol": "^BSESN", "name": "BSE SENSEX", "currency": "INR"},
                {"symbol": "^INDIAVIX", "name": "INDIA VIX", "currency": ""},
            ]
        else:
            index_symbols = [
                {"symbol": "^GSPC", "name": "S&P 500", "currency": "USD"},
                {"symbol": "^IXIC", "name": "NASDAQ Composite", "currency": "USD"},
                {"symbol": "^VIX", "name": "CBOE Volatility (VIX)", "currency": ""},
            ]

        indices = []
        bullish_count = 0
        total_eval = 0
        vix_val = None

        for item in index_symbols:
            sym = item["symbol"]
            tech = self.get_technical_data(sym)
            analyst = self.get_analyst_data(sym)
            
            price = None
            change_pct = 0.0
            if analyst and analyst.get("current_price"):
                price = analyst["current_price"]
                change_pct = analyst.get("day_change_pct", 0.0)
            elif tech and tech.get("latest_close"):
                price = tech["latest_close"]
                prev = tech.get("prev_close") or price
                change_pct = round(((price - prev) / prev) * 100, 2) if prev else 0.0

            above_200 = tech.get("trend_above_ema200") if tech else None
            above_21 = tech.get("trend_above_ema21") if tech else None
            rsi = tech.get("rsi_14") if tech else None

            if "VIX" in sym:
                vix_val = price or 16.0
                status_label = "Low Volatility" if vix_val < 18 else ("Moderate" if vix_val < 25 else "High Fear")
            else:
                total_eval += 1
                if above_200:
                    bullish_count += 1
                status_label = "Bullish" if above_200 and above_21 else ("Neutral" if above_200 else "Bearish")

            indices.append({
                "symbol": sym,
                "name": item["name"],
                "price": price,
                "change_pct": change_pct,
                "above_200": above_200,
                "above_21": above_21,
                "rsi": rsi,
                "status": status_label,
                "currency": item["currency"]
            })

        # Market Regime Classification
        vix_score = vix_val or 18.0
        if bullish_count == total_eval and vix_score < 22:
            regime = "BULLISH ACCUMULATION REGIME"
            bias = "BULLISH"
            color = "#10b981"
            guidance = "Market breadth is strong with major indices holding above their 200 EMAs. Favorable environment for high-confluence BUY signals and breakout follow-through."
        elif bullish_count > 0 and vix_score <= 26:
            regime = "CHOPPY CONSOLIDATION REGIME"
            bias = "NEUTRAL"
            color = "#f59e0b"
            guidance = "Market is in a rangebound consolidation phase. Be selective: buy only in defined entry zones, protect capital with tight stop-losses, and lock profits at TP1."
        else:
            regime = "BEARISH RISK-OFF REGIME"
            bias = "BEARISH"
            color = "#ef4444"
            guidance = "Macro indices are under distribution or breaking key moving averages. Volatility is elevated. Avoid aggressive new buys; trim laggards and honor stop-loss exits."

        overview = {
            "market": market,
            "regime": regime,
            "bias": bias,
            "color": color,
            "vix": vix_score,
            "bullish_ratio": f"{bullish_count}/{total_eval}",
            "guidance": guidance,
            "indices": indices,
            "updated_at": time.strftime("%H:%M:%S UTC", time.gmtime(now))
        }

        self._market_cache[market] = {"data": overview, "timestamp": now}
        return overview
