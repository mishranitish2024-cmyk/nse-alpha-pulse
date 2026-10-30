import os
import time
import requests
import pytz
from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

from nse_intraday_scanner import (
    NSE_FO_WATCHLIST,
    run_eod_watchlist_scan,
    run_intraday_preopen_and_orb_scan,
)
from paper_trade_logger import log_paper_trades, evaluate_open_paper_trades

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TRADING_CAPITAL = float(os.getenv("TRADING_CAPITAL", "50000"))
IST = pytz.timezone("Asia/Kolkata")


def send_telegram_message(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print(text)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for i in range(0, len(text), 3900):
        payload = {
            "chat_id": CHAT_ID,
            "text": text[i : i + 3900],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            requests.post(url, json=payload, timeout=10).raise_for_status()
        except Exception as e:
            print(f"[!] Telegram send error: {e}")


def job_evening_watchlist() -> None:
    now_str = datetime.now(IST).strftime("%d %b %Y | %I:%M %p IST")
    df = run_eod_watchlist_scan(NSE_FO_WATCHLIST)
    if df.empty:
        send_telegram_message(f"<b>🌙 EOD Structural Scan ({now_str})</b>\nNo stocks met NR7/RVOL criteria today.")
        return

    lines = [f"<b>🌙 NIGHT-BEFORE WATCHLIST ({now_str})</b>\n"]
    for _, row in df.head(10).iterrows():
        lines.append(
            f"📌 <b>{row['Stock']}</b> | Close: ₹{row['Close (₹)']}\n"
            f"   • <b>Buy > PDH:</b> ₹{row['PDH (Buy >)']} | <b>Short < PDL:</b> ₹{row['PDL (Short <)']}\n"
            f"   • <b>RVOL:</b> {row['RVOL']} | <b>RSI(14):</b> {row['RSI(14)']} | {row['Trend']}\n"
            f"   • <b>Setup:</b> <code>{row['Setups Triggered']}</code>\n"
        )
    send_telegram_message("\n".join(lines))


def job_morning_orb_scan() -> None:
    now_str = datetime.now(IST).strftime("%d %b %Y | %I:%M %p IST")
    df = run_intraday_preopen_and_orb_scan(NSE_FO_WATCHLIST, capital=TRADING_CAPITAL)
    logged = log_paper_trades(df)

    if df.empty:
        send_telegram_message(f"<b>⚡ 5-Min Live Confluence Scan ({now_str})</b>\nNo high-conviction setups right now.")
        return

    lines = [f"<b>⚡ 5-MIN CANDLESTICK & CONFLUENCE ALERTS ({now_str})</b>\n"]
    for _, row in df.iterrows():
        trade_block = ""
        if row["Qty (1% Risk)"] > 0:
            trade_block = (
                f"   🎯 <b>Entry:</b> ₹{row['Entry']} | <b>SL:</b> ₹{row['SL']} | <b>Target (1:2):</b> ₹{row['Target (1:2)']}\n"
                f"   🛡️ <b>1% Risk Qty:</b> <code>{row['Qty (1% Risk)']} Shares</code>\n"
            )
        lines.append(
            f"🔥 <b>{row['Stock']}</b> | LTP: ₹{row['LTP (₹)']} | Vol: {row['5m Vol']} | RSI: {row['RSI(14)']}\n"
            f"   • <b>VWAP:</b> ₹{row['VWAP']} | <b>20 EMA:</b> ₹{row['20 EMA']}\n"
            f"   • <b>Candle:</b> {row['Candle']} | <b>Signal:</b> <code>{row['Signal']}</code>\n"
            f"{trade_block}"
        )
    if logged > 0:
        lines.append(f"<i>📝 Logged {logged} new paper trade(s) to SQLite for 3:15 PM evaluation.</i>")
    send_telegram_message("\n".join(lines))


def handle_command(cmd_text: str) -> None:
    parts = cmd_text.strip().split()
    if not parts:
        return
    cmd = parts[0].lower()

    if cmd in ("/start", "/help"):
        send_telegram_message(
            "<b>📊 NSE Intraday Confluence Bot Ready!</b>\n\n"
            "• <code>/eod</code> — Night-Before NR7/RVOL Watchlist\n"
            "• <code>/orb</code> — Live 5-Min Candlestick, VWAP & ORB Scan\n"
            "• <code>/pnl</code> — Evaluate Paper Trades & Win Rate\n"
            "• <code>/size [Cap] [Entry] [SL]</code> — 1% Risk Calculator"
        )
    elif cmd == "/eod":
        job_evening_watchlist()
    elif cmd == "/orb":
        job_morning_orb_scan()
    elif cmd == "/pnl":
        send_telegram_message(evaluate_open_paper_trades())
    elif cmd == "/size" and len(parts) == 4:
        try:
            cap, entry, sl = float(parts[1]), float(parts[2]), float(parts[3])
            risk_per_share = abs(entry - sl)
            if risk_per_share <= 0:
                return
            qty = int((cap * 0.01) // risk_per_share)
            target = entry + (2 * risk_per_share) if entry > sl else entry - (2 * risk_per_share)
            send_telegram_message(
                f"<b>🧮 1% RISK CALCULATOR</b>\n"
                f"• <b>Qty:</b> <code>{qty} Shares</code> | <b>1:2 Target:</b> <code>₹{target:,.2f}</code>"
            )
        except ValueError:
            pass


if __name__ == "__main__":
    scheduler = BackgroundScheduler(timezone=IST)
    scheduler.add_job(job_morning_orb_scan, "cron", day_of_week="mon-fri", hour=9, minute=30, second=15)
    scheduler.add_job(job_morning_orb_scan, "cron", day_of_week="mon-fri", hour=10, minute=15, second=10)
    scheduler.add_job(
        lambda: send_telegram_message(evaluate_open_paper_trades()),
        "cron", day_of_week="mon-fri", hour=15, minute=15, second=10
    )
    scheduler.add_job(job_evening_watchlist, "cron", day_of_week="mon-fri", hour=16, minute=10, second=0)
    scheduler.start()
    print("[+] Scheduler started. Listening for Telegram commands...")

    offset = None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    while True:
        try:
            resp = requests.get(url, params={"timeout": 30, "offset": offset}, timeout=35).json()
            for update in resp.get("result", []):
                offset = update["update_id"] + 1
                text = update.get("message", {}).get("text", "")
                if text.startswith("/"):
                    handle_command(text)
        except Exception:
            time.sleep(5)
