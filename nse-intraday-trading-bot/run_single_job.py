import sys
from telegram_trading_bot import (
    job_evening_watchlist,
    job_morning_orb_scan,
    send_telegram_message,
)
from paper_trade_logger import evaluate_open_paper_trades

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "orb"
    if mode == "orb":
        job_morning_orb_scan()
    elif mode == "pnl":
        send_telegram_message(evaluate_open_paper_trades())
    elif mode == "eod":
        job_evening_watchlist()
    else:
        sys.exit(1)
