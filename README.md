# 📊 NSE Intraday Confluence Scanner & Paper-Trading Bot

Automated Python equity screener and paper-trading engine for NSE F&O stocks using **5-Minute Candlestick Patterns**, **VWAP & 20/200 EMA Confluence**, **15-Minute Opening Range Breakouts (ORB)**, and **1% Risk Position Sizing**.

## ⚡ Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env
python nse_intraday_scanner.py
```

## 🛠️ Features
- **Stage A (Night-Before EOD Scan):** Identifies NR7, Inside Bar, RVOL > 1.5x, PDH / PDL levels, and EMA trend confluence.
- **Stage B (Live 5-Min Intraday Scanner):** Real-time candlestick pattern recognition (Engulfing, Hammer, Shooting Star, Marubozu), 15m ORB breakout/breakdown, and VWAP / 20 EMA confluence.
- **SQLite Paper-Trading Engine:** Automatically records trade setups with 1% risk position sizing and evaluates outcomes at 3:15 PM IST.
- **Telegram Bot & Scheduler:** Integrated polling / push notifications with command controls (`/start`, `/eod`, `/orb`, `/pnl`, `/size`).
- **GitHub Actions Automation:** Free cloud execution on Indian market schedules.
