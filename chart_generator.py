import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf

DB_FILE = "paper_trades.db"


def generate_equity_curve_chart(output_path: str = "equity_curve.png") -> str:
    """Generates and saves the cumulative paper-trading PnL growth curve."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            df = pd.read_sql_query(
                "SELECT trade_date, pnl FROM paper_trades WHERE status = 'CLOSED' ORDER BY trade_date ASC",
                conn
            )
        if df.empty:
            # Create a placeholder chart if no trades are closed yet
            plt.figure(figsize=(9, 4.5))
            plt.title("Algorithm Paper-Trading Cumulative PnL Curve (Awaiting Trades)", fontsize=11, fontweight="bold")
            plt.xlabel("Total Trades Executed", fontsize=10)
            plt.ylabel("Cumulative Profit / Loss (₹)", fontsize=10)
            plt.grid(True, linestyle=":", alpha=0.6)
            plt.tight_layout()
            plt.savefig(output_path, dpi=300)
            plt.close()
            return output_path

        df["Cumulative_PnL"] = df["pnl"].cumsum()
        total_pnl = df["Cumulative_PnL"].iloc[-1]

        plt.figure(figsize=(9, 4.5))
        plt.plot(range(1, len(df) + 1), df["Cumulative_PnL"], marker="o", color="#2ca02c", linewidth=2.2, label=f"Net PnL: ₹{total_pnl:,.2f}")
        plt.axhline(0, color="gray", linestyle="--", alpha=0.7)
        plt.title("Algorithm Paper-Trading Cumulative PnL Curve", fontsize=12, fontweight="bold")
        plt.xlabel("Total Trades Executed", fontsize=10)
        plt.ylabel("Cumulative Profit / Loss (₹)", fontsize=10)
        plt.grid(True, linestyle=":", alpha=0.6)
        plt.legend(loc="upper left", fontsize=10)
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=300)
        plt.close()
        return output_path
    except Exception as e:
        print(f"[!] Chart generation error: {e}")
        return ""

