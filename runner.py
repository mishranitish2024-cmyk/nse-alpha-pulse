import os
import time
from datetime import datetime, time as dtime
import pytz
import sqlite3
import pandas as pd
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from dotenv import load_dotenv

from nse_intraday_scanner import (
    NSE_FO_WATCHLIST,
    run_intraday_preopen_and_orb_scan,
)
from paper_trade_logger import log_paper_trades, evaluate_open_paper_trades
from telegram_trading_bot import send_telegram_message

load_dotenv()

IST = pytz.timezone("Asia/Kolkata")
DB_PATH = "paper_trades.db"

# 150-Stock Watchlist Array
WATCHLIST = NSE_FO_WATCHLIST

# Global Market State (Populated strictly at 09:00 AM IST)
MARKET_BIAS = {
    "us_sentiment": "NEUTRAL",
    "vix_regime": "STABLE",
    "gift_nifty_sentiment": "NEUTRAL",
    "bias": "NEUTRAL",
    "allow_longs": True,
    "allow_shorts": True,
}


def send_telegram_alert(message: str) -> None:
    """Dispatches HTML-formatted alerts to Telegram using our resilient sender."""
    send_telegram_message(message)


# ==============================================================================
# 1. PRE-MARKET ANALYSIS ENGINE (RUNS AT 09:00 AM IST)
# ==============================================================================

def run_pre_market_analysis() -> dict:
    """
    Executes 4 Pre-Market Checks at 09:00 AM IST:
    1. US Markets (Investing.com proxy via yfinance: NASDAQ & DJI)
    2. India VIX (Volatile > 15 vs Stable < 15)
    3. Market Breadth (NSE Advances vs Declines)
    4. GIFT Nifty Opening Expectation
    """
    global MARKET_BIAS
    now_str = datetime.now(IST).strftime("%d-%b-%Y | %H:%M IST")
    print("\n==================================================")
    print(f"🌅 RUNNING PRE-MARKET ANALYSIS ({now_str})")
    print("==================================================")

    # Check 1: US Markets (NASDAQ & Dow Jones)
    nasdaq_change, dji_change = 0.0, 0.0
    try:
        us_data = yf.download(["^IXIC", "^DJI"], period="5d", interval="1d", progress=False, group_by="ticker")
        if "^IXIC" in us_data and "^DJI" in us_data:
            nasdaq_close = us_data["^IXIC"]["Close"].dropna()
            dji_close = us_data["^DJI"]["Close"].dropna()
        else:
            nasdaq_close = us_data["Close"]["^IXIC"].dropna()
            dji_close = us_data["Close"]["^DJI"].dropna()

        if len(nasdaq_close) >= 2 and len(dji_close) >= 2:
            nasdaq_change = ((nasdaq_close.iloc[-1] - nasdaq_close.iloc[-2]) / nasdaq_close.iloc[-2]) * 100
            dji_change = ((dji_close.iloc[-1] - dji_close.iloc[-2]) / dji_close.iloc[-2]) * 100

        if nasdaq_change > 0 and dji_change > 0:
            us_status = "🟩 GREEN (Bullish)"
            MARKET_BIAS["us_sentiment"] = "BULLISH"
        elif nasdaq_change < 0 and dji_change < 0:
            us_status = "🟥 RED (Bearish)"
            MARKET_BIAS["us_sentiment"] = "BEARISH"
        else:
            us_status = "🟨 MIXED (Sideways)"
            MARKET_BIAS["us_sentiment"] = "MIXED"
    except Exception as e:
        print(f"[!] US Markets fetch warning: {e}")
        us_status = "⚠️ DATA UNAVAILABLE"
        MARKET_BIAS["us_sentiment"] = "NEUTRAL"

    # Check 2: India VIX Check
    try:
        vix_df = yf.download("^INDIAVIX", period="5d", interval="1d", progress=False)
        vix_close = vix_df["Close"].dropna()
        latest_vix = float(vix_close.iloc[-1]) if not vix_close.empty else 15.0
        if latest_vix > 15.0:
            vix_status = f"🔥 {latest_vix:.2f} (Volatile > 15)"
            MARKET_BIAS["vix_regime"] = "VOLATILE"
        else:
            vix_status = f"🛡️ {latest_vix:.2f} (Stable < 15)"
            MARKET_BIAS["vix_regime"] = "STABLE"
    except Exception as e:
        print(f"[!] India VIX fetch warning: {e}")
        latest_vix = 15.0
        vix_status = "⚠️ 15.0 (Default)"
        MARKET_BIAS["vix_regime"] = "STABLE"

    # Check 3: Market Breadth Check (NSE Advances vs Declines)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        sess = requests.Session()
        sess.get("https://www.nseindia.com", headers=headers, timeout=5)
        res = sess.get("https://www.nseindia.com/api/market-data-pre-open", headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            advances = data.get("advances", 0)
            declines = data.get("declines", 0)
            breadth_status = f"📈 Advances ({advances}) > Declines ({declines})" if advances >= declines else f"📉 Advances ({advances}) < Declines ({declines})"
        else:
            breadth_status = "📊 Pending Pre-Open Session (09:00-09:08 AM)"
    except Exception:
        breadth_status = "📊 Pending Pre-Open Settlement (09:08 AM)"

    # Check 4: GIFT Nifty Live Scrape / Sentiment
    try:
        res = requests.get("https://www.moneycontrol.com/indian-indices/gift-nifty-44.html", headers=headers, timeout=5)
        if res.status_code == 200 and "in_chg" in res.text:
            if "green" in res.text.lower() or "+" in res.text:
                gift_status = "🟩 Green Open Expected (GIFT Nifty)"
                MARKET_BIAS["gift_nifty_sentiment"] = "GREEN"
            else:
                gift_status = "🟥 Red Open Expected (GIFT Nifty)"
                MARKET_BIAS["gift_nifty_sentiment"] = "RED"
        else:
            gift_status = "🟩 Green Open Expected" if MARKET_BIAS["us_sentiment"] == "BULLISH" else "🟥 Red Open Expected"
            MARKET_BIAS["gift_nifty_sentiment"] = "GREEN" if MARKET_BIAS["us_sentiment"] == "BULLISH" else "RED"
    except Exception:
        gift_status = "➡️ Neutral Open Expected"
        MARKET_BIAS["gift_nifty_sentiment"] = "NEUTRAL"

    # Determine Directional Filters based on Combined Confluence
    if MARKET_BIAS["us_sentiment"] == "BULLISH" and MARKET_BIAS["gift_nifty_sentiment"] == "GREEN":
        overall_bias = "🚀 BULLISH (Longs Only)"
        MARKET_BIAS["allow_longs"] = True
        MARKET_BIAS["allow_shorts"] = False  # Blocks counter-trend shorting on strong green days!
    elif MARKET_BIAS["us_sentiment"] == "BEARISH" and MARKET_BIAS["gift_nifty_sentiment"] == "RED":
        overall_bias = "🩸 BEARISH (Shorts Only)"
        MARKET_BIAS["allow_longs"] = False  # Blocks buying on high-risk crash days!
        MARKET_BIAS["allow_shorts"] = True
    else:
        overall_bias = "⚖️ NEUTRAL / SIDEWAYS (Both Allowed with Tight Filters)"
        MARKET_BIAS["allow_longs"] = True
        MARKET_BIAS["allow_shorts"] = True

    MARKET_BIAS["bias"] = overall_bias

    # Dispatch Telegram Report
    msg = (
        f"🌅 <b>NSE PRE-MARKET ANALYSIS (09:00 AM IST)</b>\n"
        f"<i>Date: {datetime.now(IST).strftime('%d-%b-%Y')}</i>\n\n"
        f"1️⃣ <b>US Markets:</b> {us_status}\n"
        f"   • NASDAQ: <code>{nasdaq_change:+.2f}%</code> | DJI: <code>{dji_change:+.2f}%</code>\n\n"
        f"2️⃣ <b>India VIX:</b> {vix_status}\n\n"
        f"3️⃣ <b>NSE Market Breadth:</b> {breadth_status}\n\n"
        f"4️⃣ <b>GIFT Nifty Open:</b> {gift_status}\n\n"
        f"🎯 <b>DAY MARKET BIAS:</b> <b>{overall_bias}</b>\n\n"
        f"🛡️ <i>Filtering: Longs Allowed = {MARKET_BIAS['allow_longs']} | Shorts Allowed = {MARKET_BIAS['allow_shorts']}</i>"
    )

    send_telegram_alert(msg)
    print("✅ Pre-market analysis completed & dispatch sent.")
    return MARKET_BIAS


# ==============================================================================
# 2. INTRADAY EVALUATOR USING PRE-MARKET BIAS
# ==============================================================================

def evaluate_setup_with_bias(ticker: str, direction: str, rvol: float) -> bool:
    """
    Evaluates whether a trade setup aligns with today's 09:00 AM Market Bias.
    """
    # 1. Enforce Pre-Market Directional Gate
    if direction == "LONG" and not MARKET_BIAS["allow_longs"]:
        print(f"[{ticker}] Skipped LONG: Blocked by 09:00 AM Bearish Market Bias.")
        return False

    if direction == "SHORT" and not MARKET_BIAS["allow_shorts"]:
        print(f"[{ticker}] Skipped SHORT: Blocked by 09:00 AM Bullish Market Bias.")
        return False

    # 2. Enforce India VIX Threshold Adjustment
    if MARKET_BIAS["vix_regime"] == "VOLATILE" and rvol < 2.5:
        print(f"[{ticker}] Skipped: VIX > 15 requires at least 2.5x RVOL (Got {rvol:.1f}x).")
        return False

    return True


# ==============================================================================
# 3. CONTINUOUS ALL-DAY TRADING LOOP
# ==============================================================================

def main_trading_loop():
    print("🚀 Intraday Paper Trading Engine Running")
    pre_market_executed = False

    while True:
        now_ist = datetime.now(IST)
        current_time = now_ist.time()

        # Skip weekends
        if now_ist.weekday() >= 5:
            print("Weekend. Sleeping for 1 hour...")
            time.sleep(3600)
            continue

        # Task A: Execute Pre-Market Analysis ONCE between 09:00 AM and 09:14 AM IST
        if dtime(9, 0) <= current_time < dtime(9, 15) and not pre_market_executed:
            run_pre_market_analysis()
            pre_market_executed = True
            time.sleep(10)
            continue

        # Task B: Pre-Market Wait Window (09:15 AM - 09:30 AM)
        if dtime(9, 15) <= current_time < dtime(9, 30):
            time.sleep(15)
            continue

        # Task C: Active Intraday Window (09:30 AM - 03:15 PM IST)
        if dtime(9, 30) <= current_time < dtime(15, 15):
            print(f"[{now_ist.strftime('%H:%M:%S')}] Running Intraday Confluence Scan...")
            try:
                raw_df = run_intraday_preopen_and_orb_scan(WATCHLIST)
                if not raw_df.empty:
                    # Filter setups through 09:00 AM Market Bias Gates
                    filtered_rows = []
                    for _, row in raw_df.iterrows():
                        direction = "LONG" if "BUY" in str(row["Signal"]) else "SHORT"
                        # Extract numeric rvol from '5m Vol' string (e.g. '3.2x' -> 3.2)
                        try:
                            rvol_val = float(str(row["5m Vol"]).replace("x", ""))
                        except Exception:
                            rvol_val = 1.0

                        if evaluate_setup_with_bias(row["Stock"], direction, rvol_val):
                            filtered_rows.append(row)

                    filtered_df = pd.DataFrame(filtered_rows)
                    if not filtered_df.empty:
                        logged = log_paper_trades(filtered_df)
                        if logged > 0:
                            print(f"[+] Logged {logged} new paper trade(s) aligned with market bias.")
            except Exception as e:
                print(f"[!] Loop Data Download / Scan Error: {e}")

            time.sleep(60)
            continue

        # Task D: Closing Window (03:15 PM IST Auto Square-Off)
        if current_time >= dtime(15, 15):
            print("🔔 03:15 PM Reached. Squaring off open trades...")
            try:
                report = evaluate_open_paper_trades()
                send_telegram_alert(report)
                try:
                    from chart_generator import generate_equity_curve_chart
                    generate_equity_curve_chart()
                except Exception as chart_e:
                    print(f"[!] Chart generation error: {chart_e}")
            except Exception as e:
                print(f"[!] Error during 3:15 PM evaluation: {e}")
            pre_market_executed = False  # Reset flag for next trading session
            print("💤 Session closed. Sleeping until tomorrow morning...")
            time.sleep(3600)


if __name__ == "__main__":
    main_trading_loop()

