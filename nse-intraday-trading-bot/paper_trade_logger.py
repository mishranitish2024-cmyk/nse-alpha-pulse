import sqlite3
from datetime import datetime
import pytz
import pandas as pd
import yfinance as yf

IST = pytz.timezone("Asia/Kolkata")
DB_FILE = "paper_trades.db"


def init_db() -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT,
                signal_time TEXT,
                stock TEXT,
                direction TEXT,
                setup TEXT,
                entry_price REAL,
                stop_loss REAL,
                target_price REAL,
                qty INTEGER,
                status TEXT DEFAULT 'OPEN',
                exit_price REAL DEFAULT 0.0,
                exit_reason TEXT DEFAULT '',
                pnl REAL DEFAULT 0.0,
                UNIQUE(trade_date, stock, direction)
            )
            """
        )


def log_paper_trades(df: pd.DataFrame) -> int:
    init_db()
    if df.empty:
        return 0

    now = datetime.now(IST)
    trade_date = now.strftime("%Y-%m-%d")
    signal_time = now.strftime("%H:%M")
    logged_count = 0

    with sqlite3.connect(DB_FILE) as conn:
        for _, row in df.iterrows():
            if row.get("Qty (1% Risk)", 0) <= 0:
                continue
            direction = "LONG" if "BUY" in str(row["Signal"]) else "SHORT"
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO paper_trades
                (trade_date, signal_time, stock, direction, setup, entry_price, stop_loss, target_price, qty)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade_date,
                    signal_time,
                    row["Stock"],
                    direction,
                    row["Signal"],
                    float(row["Entry"]),
                    float(row["SL"]),
                    float(row["Target (1:2)"]),
                    int(row["Qty (1% Risk)"]),
                ),
            )
            if cursor.rowcount > 0:
                logged_count += 1
    return logged_count


def evaluate_open_paper_trades() -> str:
    init_db()
    today_str = datetime.now(IST).strftime("%Y-%m-%d")

    with sqlite3.connect(DB_FILE) as conn:
        open_trades = pd.read_sql_query(
            "SELECT * FROM paper_trades WHERE trade_date = ? AND status = 'OPEN'",
            conn,
            params=(today_str,),
        )

    if open_trades.empty:
        return f"<b>📊 3:15 PM Paper-Trade Scorecard ({today_str})</b>\nNo open paper trades recorded today."

    tickers = [f"{s}.NS" for s in open_trades["stock"].unique()]
    intra_data = yf.download(tickers, period="1d", interval="5m", group_by="ticker", progress=False, threads=True)

    summary_lines = [f"<b>📊 3:15 PM PAPER-TRADING SCORECARD ({today_str})</b>\n"]
    total_day_pnl = 0.0
    wins = losses = 0

    with sqlite3.connect(DB_FILE) as conn:
        for _, trade in open_trades.iterrows():
            ticker = f"{trade['stock']}.NS"
            try:
                df_5m = intra_data[ticker].dropna() if len(tickers) > 1 else intra_data.dropna()
            except Exception:
                continue
            if df_5m.empty:
                continue

            df_5m.index = df_5m.index.tz_convert(IST)
            post_signal = df_5m[df_5m.index.strftime("%H:%M") > trade["signal_time"]]
            if post_signal.empty:
                post_signal = df_5m.iloc[-1:]

            entry, sl, target, qty = trade["entry_price"], trade["stop_loss"], trade["target_price"], trade["qty"]
            direction = trade["direction"]
            exit_price = float(post_signal.iloc[-1]["Close"])
            exit_reason = "⏰ 3:15 PM Auto Square-Off"

            for _, candle in post_signal.iterrows():
                if direction == "LONG":
                    if candle["Low"] <= sl:
                        exit_price, exit_reason = sl, "🛑 Stop-Loss Hit"
                        break
                    if candle["High"] >= target:
                        exit_price, exit_reason = target, "✅ 1:2 Target Hit"
                        break
                else:
                    if candle["High"] >= sl:
                        exit_price, exit_reason = sl, "🛑 Stop-Loss Hit"
                        break
                    if candle["Low"] <= target:
                        exit_price, exit_reason = target, "✅ 1:2 Target Hit"
                        break

            pnl = round((exit_price - entry) * qty if direction == "LONG" else (entry - exit_price) * qty, 2)
            total_day_pnl += pnl
            wins += 1 if pnl > 0 else 0
            losses += 0 if pnl > 0 else 1

            conn.execute(
                "UPDATE paper_trades SET status='CLOSED', exit_price=?, exit_reason=?, pnl=? WHERE id=?",
                (round(exit_price, 2), exit_reason, pnl, trade["id"]),
            )
            pnl_str = f"+₹{pnl:,.2f}" if pnl >= 0 else f"-₹{abs(pnl):,.2f}"
            summary_lines.append(
                f"• <b>{trade['stock']} ({direction})</b> | {exit_reason}\n"
                f"  Entry: ₹{entry} → Exit: ₹{exit_price:.2f} | Qty: {qty} | <b>PnL: {pnl_str}</b>"
            )

        stats = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), SUM(pnl) FROM paper_trades WHERE status='CLOSED'"
        ).fetchone()

    total_trades, total_wins, cum_pnl = stats[0] or 0, stats[1] or 0, stats[2] or 0.0
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
    day_str = f"+₹{total_day_pnl:,.2f}" if total_day_pnl >= 0 else f"-₹{abs(total_day_pnl):,.2f}"
    cum_str = f"+₹{cum_pnl:,.2f}" if cum_pnl >= 0 else f"-₹{abs(cum_pnl):,.2f}"

    summary_lines.append(
        f"\n<b>📈 TODAY:</b> {wins}W - {losses}L | <b>Net PnL: {day_str}</b>\n"
        f"<b>🏆 ALL-TIME:</b> {total_trades} Trades | <b>Win Rate: {win_rate:.1f}%</b> | <b>Total PnL: {cum_str}</b>"
    )
    return "\n".join(summary_lines)
