import os
import pytz
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Header, status
from fastapi.responses import JSONResponse

from telegram_trading_bot import (
    job_premarket_scan,
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
        if job_name == "premarket":
            job_premarket_scan()
        elif job_name == "orb":
            job_morning_orb_scan()
        elif job_name == "pnl":
            report = evaluate_open_paper_trades()
            send_telegram_message(report)
            try:
                from chart_generator import generate_equity_curve_chart
                generate_equity_curve_chart()
            except Exception as chart_err:
                print(f"[!] Chart generation error: {chart_err}")
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
            "premarket_bias": "/scan/premarket",
            "orb_scan": "/scan/orb",
            "eod_scan": "/scan/eod",
            "pnl_scorecard": "/scan/pnl",
        },
    }


@app.get("/scan/{mode}")
@app.post("/scan/{mode}")
def trigger_scan(
    mode: str,
    background_tasks: BackgroundTasks,
    secret: Optional[str] = Query(None, description="Optional cron secret authentication"),
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
):
    """Triggers market scanner jobs asynchronously via GET or POST.
    Modes:
      - 'premarket': 09:00 AM 4-Check Market Bias (US, VIX, Breadth, GIFT Nifty)
      - 'orb': 09:30 AM 15-min Opening Range Breakout & Candlestick Scan
      - 'pnl': 03:15 PM Auto Square-Off & Daily/All-Time PnL Scorecard
      - 'eod': 04:10 PM Night-Before NR7, Inside Bar & RVOL Watchlist
    """
    if not verify_secret(secret_query=secret, x_cron_secret=x_cron_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing cron secret authorization.",
        )

    clean_mode = mode.lower().strip()
    if clean_mode not in ("premarket", "orb", "pnl", "eod"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported mode '{mode}'. Choose from: 'premarket', 'orb', 'pnl', or 'eod'.",
        )

    # Queue scanner in the background so cron-job.org / browsers get an immediate 200 OK without timing out
    background_tasks.add_task(run_scanner_job, clean_mode)

    now_ist = datetime.now(IST).strftime("%Y-%m-%d %I:%M:%S %p IST")
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "mode": clean_mode,
            "message": f"Scan job '{clean_mode}' accepted and queued for execution.",
            "timestamp": now_ist,
        },
    )

