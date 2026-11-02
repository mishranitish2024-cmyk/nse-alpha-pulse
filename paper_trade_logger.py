import sqlite3
import html
from datetime import datetime
import pytz
import pandas as pd
import yfinance as yf

IST = pytz.timezone("Asia/Kolkata")
DB_FILE = "paper_trades.db"


def init_db() -> None:
    """Initializes SQLite schema and applies column migrations if upgrading."""
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
                remaining_qty INTEGER DEFAULT 0,
                stage TEXT DEFAULT 'OPEN',
                status TEXT DEFAULT 'OPEN',
                exit_price REAL DEFAULT 0.0,
                exit_reason TEXT DEFAULT '',
                gross_pnl REAL DEFAULT 0.0,
                charges REAL DEFAULT 0.0,
                net_pnl REAL DEFAULT 0.0,
                pnl REAL DEFAULT 0.0,
                UNIQUE(trade_date, stock, direction)
            )
            """
        )
        # Apply column migrations safely for backward compatibility
        existing_cols = [c[1] for c in conn.execute("PRAGMA table_info(paper_trades)").fetchall()]
        migrations = {
            "remaining_qty": "INTEGER DEFAULT 0",
            "stage": "TEXT DEFAULT 'OPEN'",
            "gross_pnl": "REAL DEFAULT 0.0",
            "charges": "REAL DEFAULT 0.0",
            "net_pnl": "REAL DEFAULT 0.0",
        }
        for col_name, col_type in migrations.items():
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE paper_trades ADD COLUMN {col_name} {col_type}")


def calculate_net_intraday_pnl(entry: float, exit_p: float, qty: int, direction: str) -> dict:
    """
    Calculates gross profit, realistic Indian discount broker statutory charges
    (STT, Exchange Turnover, SEBI, Stamp Duty, GST, ₹20/order brokerage), and 1-tick slippage.
    """
    gross_pnl = (exit_p - entry) * qty if direction == "LONG" else (entry - exit_p) * qty
    buy_turnover = (entry if direction == "LONG" else exit_p) * qty
    sell_turnover = (exit_p if direction == "LONG" else entry) * qty
    total_turnover = buy_turnover + sell_turnover

    # Indian Discount Broker Intraday Cost Structure
    brokerage = min(20.0, buy_turnover * 0.0003) + min(20.0, sell_turnover * 0.0003)
    stt = sell_turnover * 0.00025               # 0.025% on intraday sell side
    exchange_sebi = total_turnover * 0.0000345  # NSE turnover + SEBI turnover fee
    stamp_duty = buy_turnover * 0.00003         # 0.003% on buy side
    gst = 0.18 * (brokerage + exchange_sebi)    # 18% GST on services
    est_slippage = total_turnover * 0.0004      # ~0.02% per leg execution slippage

    total_charges = brokerage + stt + exchange_sebi + stamp_duty + gst + est_slippage
    net_pnl = gross_pnl - total_charges

    return {
        "gross_pnl": round(gross_pnl, 2),
        "charges": round(total_charges, 2),
        "net_pnl": round(net_pnl, 2),
    }


def check_daily_kill_switch(max_loss_r: float = 2.5, capital: float = 50000.0) -> bool:
    """
    Kill-Switch: Returns True if today's net realized loss has reached -2.5R (-₹1,250 on ₹50k capital).
    Prevents revenge trading on adverse trend days.
    """
    init_db()
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    max_loss_amount = (capital * 0.01) * max_loss_r  # 1% risk = ₹500 * 2.5 = ₹1,250

    with sqlite3.connect(DB_FILE) as conn:
        res = conn.execute(
            "SELECT SUM(COALESCE(net_pnl, pnl)) FROM paper_trades WHERE trade_date = ? AND status = 'CLOSED'",
            (today_str,),
        ).fetchone()
        today_loss = res[0] or 0.0

    return today_loss <= -max_loss_amount


def log_paper_trades(df: pd.DataFrame, capital: float = 50000.0) -> int:
    init_db()
    if df.empty:
        return 0

    # 1. Enforce Daily Kill-Switch
    if check_daily_kill_switch(max_loss_r=2.5, capital=capital):
        print("🛑 DAILY KILL-SWITCH ACTIVE: Today's loss reached -2.5R (-₹1,250). No new trades logged.")
        return 0

    now = datetime.now(IST)
    trade_date = now.strftime("%Y-%m-%d")
    signal_time = now.strftime("%H:%M")
    logged_count = 0

    with sqlite3.connect(DB_FILE) as conn:
        for _, row in df.iterrows():
            qty = int(row.get("Qty (1% Risk)", 0))
            if qty <= 0:
                continue
            direction = "LONG" if "BUY" in str(row["Signal"]) else "SHORT"
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO paper_trades
                (trade_date, signal_time, stock, direction, setup, entry_price, stop_loss, target_price, qty, remaining_qty, stage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
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
                    qty,
                    qty,
                ),
            )
            if cursor.rowcount > 0:
                logged_count += 1
    return logged_count


def evaluate_open_paper_trades() -> str:
    """
    Evaluates open paper trades using Two-Stage Exit Engine:
      1. At +1R: Lock in 50% partial profit and trail remaining stop-loss to Breakeven (Entry).
      2. At +2R: Exit remaining 50% at full 1:2 target.
      3. At 3:15 PM: Auto square-off remaining open quantity.
      4. Calculates realistic NSE transaction costs, taxes, and slippage.
    """
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

    summary_lines = [f"<b>📊 3:15 PM TWO-STAGE EXIT SCORECARD ({today_str})</b>\n"]
    total_day_gross = 0.0
    total_day_charges = 0.0
    total_day_net = 0.0
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

            # Flatten MultiIndex columns if present
            if isinstance(df_5m.columns, pd.MultiIndex):
                df_5m.columns = df_5m.columns.get_level_values(0)

            df_5m.index = df_5m.index.tz_convert(IST)
            post_signal = df_5m[df_5m.index.strftime("%H:%M") > trade["signal_time"]]
            if post_signal.empty:
                post_signal = df_5m.iloc[-1:]

            entry = float(trade["entry_price"])
            initial_sl = float(trade["stop_loss"])
            target = float(trade["target_price"])
            total_qty = int(trade["qty"])
            direction = str(trade["direction"])

            # 1R distance
            r_distance = abs(entry - initial_sl)
            target_1r = round(entry + r_distance if direction == "LONG" else entry - r_distance, 2)
            half_qty = max(1, total_qty // 2)
            rem_qty = total_qty - half_qty

            stage = "OPEN"
            active_sl = initial_sl
            partial_exit_price = 0.0
            final_exit_price = float(post_signal.iloc[-1]["Close"])
            exit_reason = "⏰ 3:15 PM Auto Square-Off"

            for _, candle in post_signal.iterrows():
                high = float(candle["High"])
                low = float(candle["Low"])

                # Check Stop-Loss
                if direction == "LONG":
                    if low <= active_sl:
                        if stage == "OPEN":
                            final_exit_price = active_sl
                            exit_reason = "🛑 Stop-Loss Hit (-1R)"
                            break
                        else:  # stage == 'BREAKEVEN_TRAIL'
                            final_exit_price = active_sl
                            exit_reason = "🛡️ Breakeven Exit (+0.5R Locked)"
                            break
                    # Check +1R Partial Profit Booking
                    if stage == "OPEN" and high >= target_1r:
                        stage = "BREAKEVEN_TRAIL"
                        partial_exit_price = target_1r
                        active_sl = entry  # Move stop-loss to Breakeven
                    # Check +2R Final Target
                    if stage == "BREAKEVEN_TRAIL" and high >= target:
                        final_exit_price = target
                        exit_reason = "🎯 1:2 Target Hit (+1.5R Total)"
                        break
                else:  # SHORT
                    if high >= active_sl:
                        if stage == "OPEN":
                            final_exit_price = active_sl
                            exit_reason = "🛑 Stop-Loss Hit (-1R)"
                            break
                        else:
                            final_exit_price = active_sl
                            exit_reason = "🛡️ Breakeven Exit (+0.5R Locked)"
                            break
                    if stage == "OPEN" and low <= target_1r:
                        stage = "BREAKEVEN_TRAIL"
                        partial_exit_price = target_1r
                        active_sl = entry
                    if stage == "BREAKEVEN_TRAIL" and low <= target:
                        final_exit_price = target
                        exit_reason = "🎯 1:2 Target Hit (+1.5R Total)"
                        break

            # Calculate PnL based on Two-Stage Execution
            if stage == "BREAKEVEN_TRAIL":
                # Leg 1: 50% booked at +1R
                leg1 = calculate_net_intraday_pnl(entry, partial_exit_price, half_qty, direction)
                # Leg 2: Remaining 50% exited at final_exit_price
                leg2 = calculate_net_intraday_pnl(entry, final_exit_price, rem_qty, direction)
                trade_gross = leg1["gross_pnl"] + leg2["gross_pnl"]
                trade_charges = leg1["charges"] + leg2["charges"]
                trade_net = leg1["net_pnl"] + leg2["net_pnl"]
                details_str = f"Leg1 (+1R): ₹{partial_exit_price:.2f} ({half_qty} sh) | Leg2: ₹{final_exit_price:.2f} ({rem_qty} sh)"
            else:
                # 100% exited in single leg
                calc = calculate_net_intraday_pnl(entry, final_exit_price, total_qty, direction)
                trade_gross = calc["gross_pnl"]
                trade_charges = calc["charges"]
                trade_net = calc["net_pnl"]
                details_str = f"Exit: ₹{final_exit_price:.2f} ({total_qty} sh)"

            total_day_gross += trade_gross
            total_day_charges += trade_charges
            total_day_net += trade_net

            if trade_net > 0:
                wins += 1
            else:
                losses += 1

            conn.execute(
                """
                UPDATE paper_trades
                SET status='CLOSED', stage=?, exit_price=?, exit_reason=?,
                    gross_pnl=?, charges=?, net_pnl=?, pnl=?
                WHERE id=?
                """,
                (stage, round(final_exit_price, 2), exit_reason, trade_gross, trade_charges, trade_net, trade_net, trade["id"]),
            )

            pnl_badge = f"+₹{trade_net:,.2f}" if trade_net >= 0 else f"-₹{abs(trade_net):,.2f}"
            stk_clean = html.escape(str(trade["stock"]), quote=False)
            summary_lines.append(
                f"• <b>{stk_clean} ({direction})</b> | {exit_reason}\n"
                f"  Entry: ₹{entry} → {details_str}\n"
                f"  Gross: ₹{trade_gross:,.2f} | Taxes/Fees: -₹{trade_charges:,.2f} | <b>Net PnL: {pnl_badge}</b>"
            )

        # Cumulative All-Time Stats
        stats = conn.execute(
            """
            SELECT COUNT(*),
                   SUM(CASE WHEN COALESCE(net_pnl, pnl) > 0 THEN 1 ELSE 0 END),
                   SUM(COALESCE(gross_pnl, pnl)),
                   SUM(COALESCE(charges, 0)),
                   SUM(COALESCE(net_pnl, pnl))
            FROM paper_trades
            WHERE status='CLOSED'
            """
        ).fetchone()

    tot_trades = stats[0] or 0
    tot_wins = stats[1] or 0
    tot_gross = stats[2] or 0.0
    tot_charges = stats[3] or 0.0
    tot_net = stats[4] or 0.0
    win_rate = (tot_wins / tot_trades * 100) if tot_trades > 0 else 0.0

    day_net_str = f"+₹{total_day_net:,.2f}" if total_day_net >= 0 else f"-₹{abs(total_day_net):,.2f}"
    tot_net_str = f"+₹{tot_net:,.2f}" if tot_net >= 0 else f"-₹{abs(tot_net):,.2f}"

    summary_lines.append(
        f"\n<b>📈 TODAY:</b> {wins}W - {losses}L | Gross: ₹{total_day_gross:,.2f} | Taxes/Fees: -₹{total_day_charges:,.2f} | <b>Net: {day_net_str}</b>\n"
        f"<b>🏆 ALL-TIME:</b> {tot_trades} Trades | <b>Win Rate: {win_rate:.1f}%</b> | Friction: -₹{tot_charges:,.2f} | <b>Total Net PnL: {tot_net_str}</b>"
    )
    return "\n".join(summary_lines)
