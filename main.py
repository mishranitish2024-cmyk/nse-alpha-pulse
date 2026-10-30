import os
import pytz
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Header, status
from fastapi.responses import JSONResponse

from telegram_trading_bot import (
    job_evening_watchlist,
    job_morning_orb_scan,
    send_telegram_message,
)
from paper_trade_logger import evaluate_open_paper_trades

app = FastAPI(
    title="NSE Intraday Alpha Pulse API",
    description="FastAPI Backend for NSE Intraday Market Scanner, Telegram Alerts & Paper Trading",
    version="1.0.0",
)

IST = pytz.timezone("Asia/Kolkata")
CRON_SECRET = os.getenv("CRON_SECRET", "").strip()


def verify_secret(secret_query: Optional[str] = None, x_cron_secret: Optional[str] = None) -> bool:
    """Validates the optional cron secret if configured in environment variables."""
    if not CRON_SECRET:
        return True  # No secret required if CRON_SECRET is not set
    return (secret_query == CRON_SECRET) or (x_cron_secret == CRON_SECRET)


def run_scanner_job(job_name: str) -> None:
    """Executes the appropriate scanner function in the background."""
    print(f"[*] Starting background scanner job: {job_name}")
    try:
        if job_name == "orb":
            job_morning_orb_scan()
        elif job_name == "pnl":
            report = evaluate_open_paper_trades()
            send_telegram_message(report)
        elif job_name == "eod":
            job_evening_watchlist()
        else:
            print(f"[!] Unknown job type: {job_name}")
            return
        print(f"[+] Finished scanner job successfully: {job_name}")
    except Exception as exc:
        print(f"[!] Error executing scanner job {job_name}: {exc}")
        send_telegram_message(f"⚠️ <b>Backend Error ({job_name.upper()} Scan)</b>\n<code>{exc}</code>")


@app.get("/")
@app.get("/health")
def health_check():
    """Keep-alive ping endpoint for cron-job.org / uptime monitoring.
    Hit this every 10-14 minutes so Render free instances stay awake during market hours.
    """
    now_ist = datetime.now(IST).strftime("%Y-%m-%d %I:%M:%S %p IST")
    return {
        "status": "online",
        "service": "NSE Intraday Scanner & Paper-Trading Bot",
        "current_time_ist": now_ist,
        "available_triggers": {
            "orb_scan": "/scan/orb",
            "eod_scan": "/scan/eod",
            "pnl_scorecard": "/scan/pnl",
        },
    }


@app.api_route("/scan/{mode}", methods=["GET", "POST"])
def trigger_scan(
    mode: str,
    background_tasks: BackgroundTasks,
    secret: Optional[str] = Query(None, description="Optional cron secret authentication"),
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
):
    """Triggers market scanner jobs asynchronously.
    Supports both GET and POST so cron-job.org can hit it effortlessly.
    Modes:
      - 'orb': 9:30 AM 15-min Opening Range Breakout & Candlestick Scan
      - 'pnl': 3:15 PM Auto Square-Off & Daily/All-Time PnL Scorecard
      - 'eod': 4:10 PM Night-Before NR7, Inside Bar & RVOL Watchlist
    """
    if not verify_secret(secret_query=secret, x_cron_secret=x_cron_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing cron secret authorization.",
        )

    clean_mode = mode.lower().strip()
    if clean_mode not in ("orb", "pnl", "eod"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported mode '{mode}'. Choose from: 'orb', 'pnl', or 'eod'.",
        )

    # Queue scanner to run in background so cron-job.org receives an immediate 200 OK without timing out
    background_tasks.add_task(run_scanner_job, clean_mode)

    now_ist = datetime.now(IST).strftime("%Y-%m-%d %I:%M:%S %p IST")
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "status": "accepted",
            "message": f"Scan job '{clean_mode}' queued for immediate execution.",
            "timestamp": now_ist,
        },
    )

