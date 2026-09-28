# Quantitative AI Market Terminal 📈🇺🇸🇮🇳

An automated, institutional-grade stock market indicator and interactive terminal supporting both **US Markets (NASDAQ / NYSE / S&P 500)** and **Indian Markets (NSE / BSE)**.

It pairs **official TradingView real-time candlestick charts** with a proprietary **5-Pillar Confluence Engine** (Wall Street & Dalal Street analyst targets, 9/21/50/200 EMA trend stack, Wilder RSI, MACD, Bollinger Bands, and Smart Money Volume Flow), computing exact **Stop-Loss**, **Take-Profit 1/2**, and **Risk-to-Reward levels**.

---

## 🌟 Key Features

1. **Interactive Real-Time TradingView Charts**:
   - Official TradingView candlestick chart embedded directly in the dashboard.
   - Pre-loaded with top technical indicators: RSI (14), MACD, and Exponential Moving Averages (EMA 20/50).
   - Real-time live updating candlesticks from exchange WebSocket feeds for both US and Indian tickers.

2. **Dual-Market Support**:
   - 🇺🇸 **US Equities**: NVDA, AAPL, MSFT, TSLA, AMZN, GOOGL, META, AMD, SPY, QQQ (Prices in `$ USD`).
   - 🇮🇳 **Indian Equities**: RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK, TATAMOTORS, SBIN, etc. (Prices in `₹ INR`).
   - Smart resolution: Type any ticker without extensions; the engine automatically resolves exchange and currency.

3. **5-Pillar Quantitative Precision Model (0–100 Score)**:
   - **Pillar 1: Institutional Analyst & Valuation (25 pts)**: Wall St / Dalal St consensus rating, price target upside, coverage depth.
   - **Pillar 2: Market Trend & Regime (25 pts)**: EMA 9, 21, 50, and 200 EMA macro bull/bear alignment.
   - **Pillar 3: Momentum & Oscillators (20 pts)**: Wilder RSI(14) + MACD line, signal, and histogram momentum.
   - **Pillar 4: Volatility & Extremes (15 pts)**: Bollinger Bands %B & volatility squeeze detection.
   - **Pillar 5: Volume & Smart Money Flow (15 pts)**: Relative Volume (RVOL vs 20-day average).

4. **Exact Calculated Execution Plan**:
   - **Entry Zone**: Optimal limit entry range calculated with ATR equilibrium buffers.
   - **Stop-Loss (SL)**: Mathematically sized via ATR volatility buffer with exact downside risk percentage.
   - **Take-Profit 1 (TP1 - Swing)**: Technical swing resistance level.
   - **Take-Profit 2 (TP2 - Analyst Target)**: Institutional consensus target.
   - **Risk-to-Reward Ratio**: Exact asymmetric payoff profile (`1 : R:R`).

5. **Multi-Channel Alerts**:
   - Rich color-coded **Discord Webhook** embed cards.
   - Native **Android Status Bar** push notifications via `termux-notification`.

---

## 🚀 Live Dashboard on Localhost

Open your browser to:
👉 **[http://localhost:5000](http://localhost:5000)**

### Terminal Commands:

```bash
cd ~/antigravity/indian-stock-indicator

# Launch the live web terminal on port 5000:
python3 web_server.py 5000

# Run terminal scan on US stocks:
python3 indicator.py -t NVDA AAPL TSLA MSFT

# Run terminal scan on Indian stocks:
python3 indicator.py -t RELIANCE TCS HDFCBANK INFY

# Continuous background monitor mode (every 5 mins):
python3 indicator.py --watch --interval 300
```
