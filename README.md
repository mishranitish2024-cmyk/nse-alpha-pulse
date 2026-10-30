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
- **FastAPI Backend (Render + cron-job.org):** Sub-second precise triggers eliminating GitHub Actions queue delays.
- **Telegram Bot & Scheduler:** Integrated polling / push notifications with command controls (`/start`, `/eod`, `/orb`, `/pnl`, `/size`).
- **GitHub Actions Automation:** Free cloud execution on Indian market schedules.

## 🚀 Deploy to Render + cron-job.org (Zero-Delay Triggers)

### 1. Render Setup
1. Create a free **Web Service** on [Render.com](https://render.com) linked to your repo.
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Set Environment Variables:
   - `TELEGRAM_BOT_TOKEN`: Your Telegram bot token
   - `TELEGRAM_CHAT_ID`: Your chat ID
   - `TRADING_CAPITAL`: `50000`
   - `CRON_SECRET`: *(Optional)* Secret token to protect your endpoints

### 2. cron-job.org Setup (Indian Market Times)
Set up scheduled jobs on [cron-job.org](https://cron-job.org):

| Job Name | Schedule (IST) | Days | URL |
| :--- | :--- | :--- | :--- |
| **Keep-Alive Ping** | Every 10 mins (9:00 AM - 4:30 PM) | Mon-Fri | `https://your-app.onrender.com/health` |
| **Morning ORB Scan** | 9:30 AM IST | Mon-Fri | `https://your-app.onrender.com/scan/orb` |
| **VWAP Pullback Scan** | 10:15 AM IST | Mon-Fri | `https://your-app.onrender.com/scan/orb` |
| **3:15 PM Square-Off** | 3:15 PM IST | Mon-Fri | `https://your-app.onrender.com/scan/pnl` |
| **EOD Watchlist Scan** | 4:10 PM IST | Mon-Fri | `https://your-app.onrender.com/scan/eod` |

*(If `CRON_SECRET` is set, append `?secret=YOUR_SECRET` to the URLs or pass `X-Cron-Secret` header).*
