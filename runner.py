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

def get_india_vix() -> dict:
    """Fetches real-time India VIX via yfinance with MultiIndex safety."""
    try:
        vix_df = yf.download("^INDIAVIX", period="5d", interval="1d", progress=False)
        if not vix_df.empty:
            if isinstance(vix_df.columns, pd.MultiIndex):
                try:
                    close_col = vix_df["Close"]["^INDIAVIX"].dropna()
                except KeyError:
                    close_col = vix_df[("^INDIAVIX", "Close")].dropna()
            else:
                close_col = vix_df["Close"].dropna()

            if not close_col.empty:
                latest_vix = float(close_col.iloc[-1])
                prev_vix = float(close_col.iloc[-2]) if len(close_col) > 1 else latest_vix
                pct_change = ((latest_vix - prev_vix) / prev_vix) * 100 if prev_vix > 0 else 0.0
                regime = "VOLATILE (>15)" if latest_vix > 15.0 else "STABLE (<15)"
                return {
                    "value": round(latest_vix, 2),
                    "change_pct": round(pct_change, 2),
                    "regime": regime,
                    "is_volatile": latest_vix > 15.0,
                }
    except Exception as e:
        print(f"[!] Error fetching India VIX: {e}")
    return {"value": 15.0, "change_pct": 0.0, "regime": "STABLE (<15)", "is_volatile": False}


def get_gift_nifty_live() -> dict:
    """
    Scrapes live GIFT Nifty level from Moneycontrol with BeautifulSoup.
    Includes yfinance Nifty 50 proxy as fallback.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    # Primary Source: Moneycontrol GIFT Nifty Widget
    try:
        url = "https://www.moneycontrol.com/indian-indices/gift-nifty-44.html"
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            price_div = soup.find("div", {"id": "in_val"}) or soup.find("span", {"class": "lastprice"})
            change_span = soup.find("div", {"id": "in_chg"}) or soup.find("span", {"class": "change"})

            if price_div and price_div.text.strip():
                price = float(price_div.text.strip().replace(",", ""))
                change_pct = 0.0
                if change_span and change_span.text.strip():
                    raw_chg = change_span.text.strip().replace("%", "").replace("+", "")
                    if "(" in raw_chg:
                        raw_chg = raw_chg.split("(")[-1].replace(")", "")
                    try:
                        change_pct = float(raw_chg)
                    except ValueError:
                        change_pct = 0.0

                sentiment = "GREEN / GAP-UP" if change_pct >= 0 else "RED / GAP-DOWN"
                return {
                    "price": price,
                    "change_pct": change_pct,
                    "sentiment": sentiment,
                    "is_green": change_pct >= 0,
                }
    except Exception as e:
        print(f"[!] Moneycontrol GIFT Nifty scrape failed: {e}. Trying fallback...")

    # Fallback Proxy using yfinance Nifty 50 Index (^NSEI)
    try:
        nifty_fut = yf.download("^NSEI", period="5d", interval="1d", progress=False)
        if not nifty_fut.empty:
            close_col = nifty_fut["Close"].dropna()
            latest = float(close_col.iloc[-1])
            prev = float(close_col.iloc[-2]) if len(close_col) > 1 else latest
            chg = ((latest - prev) / prev) * 100 if prev > 0 else 0.0
            sentiment = "GREEN / GAP-UP" if chg >= 0 else "RED / GAP-DOWN"
            return {
                "price": round(latest, 2),
                "change_pct": round(chg, 2),
                "sentiment": sentiment,
                "is_green": chg >= 0,
            }
    except Exception as fb_err:
        print(f"[!] Fallback proxy error: {fb_err}")

    return {"price": 0.0, "change_pct": 0.0, "sentiment": "NEUTRAL", "is_green": True}


def get_us_markets() -> dict:
    """Fetches NASDAQ & Dow Jones performance via yfinance."""
    nasdaq_change, dji_change = 0.0, 0.0
    sentiment = "NEUTRAL"
    status_label = "⚠️ Data Unavailable"
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
            status_label = "🟩 GREEN (Bullish)"
            sentiment = "BULLISH"
        elif nasdaq_change < 0 and dji_change < 0:
            status_label = "🟥 RED (Bearish)"
            sentiment = "BEARISH"
        else:
            status_label = "🟨 MIXED (Sideways)"
            sentiment = "MIXED"
    except Exception as e:
        print(f"[!] US Markets fetch warning: {e}")

    return {
        "nasdaq_change": round(nasdaq_change, 2),
        "dji_change": round(dji_change, 2),
        "status": status_label,
        "sentiment": sentiment,
    }


def get_nse_market_breadth() -> dict:
    """Checks NSE Pre-Open Advances vs Declines."""
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
            return {"status": breadth_status, "advances": advances, "declines": declines}
    except Exception:
        pass
    return {"status": "📊 Pending Pre-Open Settlement (09:08 AM)", "advances": 0, "declines": 0}


def run_pre_market_analysis() -> dict:
    """
    Executes 4 Pre-Market Checks at 09:00 AM IST:
    1. US Markets (Investing.com proxy via yfinance: NASDAQ & DJI)
    2. India VIX (Volatile > 15 vs Stable < 15 via yfinance)
    3. GIFT Nifty Live Scrape (Moneycontrol + BeautifulSoup with proxy fallback)
    4. Market Breadth (NSE Advances vs Declines)
    """
    global MARKET_BIAS
    now_str = datetime.now(IST).strftime("%d-%b-%Y | %H:%M IST")
    print("\n==================================================")
    print(f"🌅 RUNNING PRE-MARKET ANALYSIS ({now_str})")
    print("==================================================")

    us = get_us_markets()
    vix = get_india_vix()
    gift = get_gift_nifty_live()
    breadth = get_nse_market_breadth()

    MARKET_BIAS["us_sentiment"] = us["sentiment"]
    MARKET_BIAS["vix_regime"] = "VOLATILE" if vix["is_volatile"] else "STABLE"
    MARKET_BIAS["gift_nifty_sentiment"] = "GREEN" if gift["is_green"] else "RED"

    # Determine Directional Filters based on Combined Confluence
    if us["sentiment"] == "BULLISH" and gift["is_green"]:
        overall_bias = "🚀 BULLISH (Longs Only)"
        MARKET_BIAS["allow_longs"] = True
        MARKET_BIAS["allow_shorts"] = False  # Blocks counter-trend shorting on strong green days!
    elif us["sentiment"] == "BEARISH" and not gift["is_green"]:
        overall_bias = "🩸 BEARISH (Shorts Only)"
        MARKET_BIAS["allow_longs"] = False  # Blocks buying on high-risk crash days!
        MARKET_BIAS["allow_shorts"] = True
    else:
        overall_bias = "⚖️ NEUTRAL / SIDEWAYS (Both Allowed with Strict Filters)"
        MARKET_BIAS["allow_longs"] = True
        MARKET_BIAS["allow_shorts"] = True

    MARKET_BIAS["bias"] = overall_bias

    vix_icon = "🔥" if vix["is_volatile"] else "🛡️"
    gift_icon = "🟩" if gift["is_green"] else "🟥"

    # Dispatch Telegram Report
    msg = (
        f"🌅 <b>NSE PRE-MARKET ANALYSIS (09:00 AM IST)</b>\n"
        f"<i>Date: {datetime.now(IST).strftime('%d-%b-%Y')}</i>\n\n"
        f"1️⃣ <b>US Markets:</b> {us['status']}\n"
        f"   • NASDAQ: <code>{us['nasdaq_change']:+.2f}%</code> | DJI: <code>{us['dji_change']:+.2f}%</code>\n\n"
        f"2️⃣ <b>India VIX:</b> {vix_icon} <b>{vix['value']}</b> (<code>{vix['change_pct']:+.2f}%</code>) — {vix['regime']}\n\n"
        f"3️⃣ <b>GIFT Nifty:</b> {gift_icon} <b>{gift['price']}</b> (<code>{gift['change_pct']:+.2f}%</code>) — {gift['sentiment']}\n\n"
        f"4️⃣ <b>NSE Market Breadth:</b> {breadth['status']}\n\n"
        f"🎯 <b>DAY MARKET BIAS:</b> <b>{overall_bias}</b>\n\n"
        f"🛡️ <i>Filtering: Longs Allowed = {MARKET_BIAS['allow_longs']} | Shorts Allowed = {MARKET_BIAS['allow_shorts']}</i>"
    )

    send_telegram_alert(msg)
    print(f"1️⃣ India VIX: {vix['value']} ({vix['change_pct']:+.2f}%) -> {vix['regime']}")
    print(f"2️⃣ GIFT Nifty: {gift['price']} ({gift['change_pct']:+.2f}%) -> {gift['sentiment']}")
    print(f"3️⃣ US Markets: NASDAQ ({us['nasdaq_change']:+.2f}%), DJI ({us['dji_change']:+.2f}%)")
    print(f"4️⃣ Market Bias: {overall_bias}")
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

def sleep_until_next_5m_boundary(buffer_seconds: int = 3) -> None:
    """Sleeps precisely until the next 5-minute interval plus buffer seconds (e.g. XX:X0:03)."""
    now = datetime.now(IST)
    minute = now.minute
    second = now.second
    next_minute = ((minute // 5) + 1) * 5
    if next_minute == 60:
        sleep_secs = (60 - minute - 1) * 60 + (60 - second) + buffer_seconds
    else:
        sleep_secs = (next_minute - minute - 1) * 60 + (60 - second) + buffer_seconds
    time.sleep(max(3, sleep_secs))


def main_trading_loop():
    print("🚀 Single Continuous Intraday Runner Initialized (09:15 AM - 03:20 PM IST)")
    pre_market_executed = False

    while True:
        now_ist = datetime.now(IST)
        current_time = now_ist.time()

        # Skip weekends
        if now_ist.weekday() >= 5:
            print("Weekend. No market session. Exiting runner.")
            break

        # Task A: Execute Pre-Market Analysis ONCE between 09:00 AM and 09:15 AM IST
        if dtime(9, 0) <= current_time < dtime(9, 15) and not pre_market_executed:
            run_pre_market_analysis()
            pre_market_executed = True
            time.sleep(10)
            continue

        # Task B: Pre-Market Wait Window (09:15 AM - 09:20 AM: Wait for first 5m bar to complete)
        if dtime(9, 15) <= current_time < dtime(9, 20):
            print(f"[{now_ist.strftime('%H:%M:%S')}] Waiting for first 5-min candle (09:15-09:20) to settle...")
            sleep_until_next_5m_boundary(buffer_seconds=3)
            continue

        # Task C: Active Intraday Window (09:20 AM - 03:15 PM IST)
        if dtime(9, 20) <= current_time < dtime(15, 15):
            print(f"[{now_ist.strftime('%H:%M:%S')}] Running Intraday Confluence Scan...")
            try:
                raw_df = run_intraday_preopen_and_orb_scan(WATCHLIST)
                if not raw_df.empty:
                    # Filter setups through 09:00 AM Market Bias Gates
                    filtered_rows = []
                    for _, row in raw_df.iterrows():
                        direction = "LONG" if "BUY" in str(row["Signal"]) else "SHORT"
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
                print(f"[!] Intraday Scan Error: {e}")

            # Sleep precisely until next 5-minute candle closes (e.g. at XX:X0:03 or XX:X5:03)
            sleep_until_next_5m_boundary(buffer_seconds=3)
            continue

        # Task D: Closing Window (03:15 PM IST Auto Square-Off & Daily Report)
        if current_time >= dtime(15, 15):
            print("🔔 03:15 PM Reached. Squaring off open trades via Two-Stage Exit Engine...")
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
            print("🏁 Trading day complete. Exiting runner cleanly.")
            break


if __name__ == "__main__":
    main_trading_loop()

