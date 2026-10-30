import sys
import warnings
import yfinance as yf
import pandas as pd
from tabulate import tabulate

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

warnings.filterwarnings("ignore")

NSE_FO_WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "AXISBANK.NS",
    "KOTAKBANK.NS", "TATAMOTORS.NS", "M&M.NS", "MARUTI.NS", "SUNPHARMA.NS",
    "TATASTEEL.NS", "HINDALCO.NS", "JSWSTEEL.NS", "BAJFINANCE.NS", "ADANIENT.NS",
    "HAL.NS", "BEL.NS", "TRENT.NS", "DLF.NS", "INDIGO.NS",
    "ZOMATO.NS", "PFC.NS", "RECLTD.NS", "TITAN.NS", "ULTRACEMCO.NS"
]


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculates Wilder's 14-period RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def detect_5m_candlestick_pattern(curr: pd.Series, prev: pd.Series) -> str | None:
    """Detects Hammer, Shooting Star, Bullish/Bearish Engulfing, and Marubozu."""
    o, h, l, c = curr["Open"], curr["High"], curr["Low"], curr["Close"]
    po, ph, pl, pc = prev["Open"], prev["High"], prev["Low"], prev["Close"]

    rng = h - l
    if rng <= 0:
        return None

    body = abs(c - o)
    prev_body = abs(pc - po)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    is_bull, is_bear = c > o, c < o
    was_bull, was_bear = pc > po, pc < po

    if is_bull and was_bear and (c >= po) and (o <= pc) and (body > prev_body * 1.05):
        return "🟢 Bullish Engulfing"
    if is_bear and was_bull and (c <= po) and (o >= pc) and (body > prev_body * 1.05):
        return "🔴 Bearish Engulfing"

    effective_body = max(body, rng * 0.05)
    if (lower_wick >= 2.0 * effective_body) and (upper_wick <= 0.18 * rng):
        return "🟢 Hammer (Pin Bar)"
    if (upper_wick >= 2.0 * effective_body) and (lower_wick <= 0.18 * rng):
        return "🔴 Shooting Star"
    if (body / rng) >= 0.80:
        return "🟢 Bullish Marubozu" if is_bull else "🔴 Bearish Marubozu"

    return None


def run_eod_watchlist_scan(tickers: list[str]) -> pd.DataFrame:
    """Stage A: Night-Before Scanner for NR7, Inside Bars, RVOL > 1.5x, and PDH/PDL."""
    data = yf.download(tickers, period="1y", interval="1d", group_by="ticker", progress=False, threads=True)
    results = []

    for ticker in tickers:
        try:
            df = data[ticker].dropna()
            if len(df) < 205:
                continue

            df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
            df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
            df["RSI"] = compute_rsi(df["Close"], 14)
            df["Range"] = df["High"] - df["Low"]
            df["AvgVol20"] = df["Volume"].rolling(20).mean()
            df["RVOL"] = df["Volume"] / df["AvgVol20"]

            latest = df.iloc[-1]
            prev = df.iloc[-2]
            is_nr7 = latest["Range"] == df["Range"].iloc[-7:].min()
            is_inside = (latest["High"] < prev["High"]) and (latest["Low"] > prev["Low"])
            vol_spike = latest["RVOL"] >= 1.5
            close_pos = (latest["Close"] - latest["Low"]) / latest["Range"] if latest["Range"] > 0 else 0.5

            if latest["Close"] > latest["EMA200"] and latest["Close"] > latest["EMA20"]:
                trend = "BULLISH (>20/200 EMA)"
            elif latest["Close"] < latest["EMA200"] and latest["Close"] < latest["EMA20"]:
                trend = "BEARISH (<20/200 EMA)"
            else:
                trend = "SIDEWAYS / PULLBACK"

            setups = []
            if is_nr7:
                setups.append("NR7")
            if is_inside:
                setups.append("InsideBar")
            if vol_spike:
                setups.append(f"RVOL({latest['RVOL']:.1f}x)")
            if close_pos >= 0.85:
                setups.append("StrongClose(High)")
            elif close_pos <= 0.15:
                setups.append("WeakClose(Low)")

            if setups:
                results.append({
                    "Stock": ticker.replace(".NS", ""),
                    "Close (₹)": round(latest["Close"], 2),
                    "PDH (Buy >)": round(latest["High"], 2),
                    "PDL (Short <)": round(latest["Low"], 2),
                    "RVOL": f"{latest['RVOL']:.2f}x",
                    "RSI(14)": round(latest["RSI"], 1),
                    "Trend": trend,
                    "Setups Triggered": ", ".join(setups)
                })
        except Exception:
            continue

    res_df = pd.DataFrame(results)
    if not res_df.empty:
        res_df = res_df.sort_values(by="RVOL", ascending=False)
    return res_df


def run_intraday_preopen_and_orb_scan(tickers: list[str], capital: float = 50000.0) -> pd.DataFrame:
    """Stage B: 5-Minute Intraday Candlestick, VWAP, 20/200 EMA, RSI & 15m ORB Engine."""
    daily_data = yf.download(tickers, period="5d", interval="1d", group_by="ticker", progress=False, threads=True)
    intra_data = yf.download(tickers, period="5d", interval="5m", group_by="ticker", progress=False, threads=True)
    results = []

    for ticker in tickers:
        try:
            d_df = daily_data[ticker].dropna()
            i_df = intra_data[ticker].dropna()
            if len(d_df) < 2 or len(i_df) < 30:
                continue

            latest_date = i_df.index[-1].date()
            today_df = i_df[i_df.index.date == latest_date].copy()
            if len(today_df) < 2:
                continue

            i_df["EMA20"] = i_df["Close"].ewm(span=20, adjust=False).mean()
            i_df["EMA200"] = i_df["Close"].ewm(span=200, adjust=False).mean()
            i_df["RSI14"] = compute_rsi(i_df["Close"], 14)
            i_df["VolAvg10"] = i_df["Volume"].rolling(10).mean()

            typ_price = (today_df["High"] + today_df["Low"] + today_df["Close"]) / 3
            today_df["VWAP"] = (typ_price * today_df["Volume"]).cumsum() / today_df["Volume"].cumsum()

            curr = i_df.iloc[-1]
            prev = i_df.iloc[-2]
            current_vwap = today_df["VWAP"].iloc[-1]

            orb_candles = today_df.iloc[:3]
            orb_high = orb_candles["High"].max()
            orb_low = orb_candles["Low"].min()

            candle_pattern = detect_5m_candlestick_pattern(curr, prev)
            near_ema20 = abs(curr["Low"] - curr["EMA20"]) / curr["Close"] <= 0.0035 or abs(curr["High"] - curr["EMA20"]) / curr["Close"] <= 0.0035
            near_vwap = abs(curr["Low"] - current_vwap) / curr["Close"] <= 0.0035 or abs(curr["High"] - current_vwap) / curr["Close"] <= 0.0035

            loc_tags = []
            if near_vwap:
                loc_tags.append("@VWAP")
            if near_ema20:
                loc_tags.append("@20EMA")

            vol_ratio = curr["Volume"] / curr["VolAvg10"] if curr["VolAvg10"] > 0 else 1.0
            action = None
            entry_price = stop_loss = target_price = 0.0
            qty = 0

            # Bullish Confluence Check
            if curr["Close"] > current_vwap and curr["Close"] > curr["EMA200"]:
                if candle_pattern and "🟢" in candle_pattern and (near_vwap or near_ema20 or curr["Close"] > orb_high):
                    action = f"BUY ({candle_pattern} {'/'.join(loc_tags)})"
                    entry_price = round(curr["High"] + 0.05, 2)
                    stop_loss = round(min(curr["Low"], current_vwap) - 0.05, 2)
                elif len(today_df) >= 3 and curr["Close"] > orb_high and vol_ratio >= 1.5 and curr["RSI14"] >= 60:
                    action = "BUY (15m ORB Breakout + Vol Spike)"
                    entry_price = round(curr["Close"], 2)
                    stop_loss = round(max(orb_low, current_vwap), 2)

            # Bearish Confluence Check
            elif curr["Close"] < current_vwap and curr["Close"] < curr["EMA200"]:
                if candle_pattern and "🔴" in candle_pattern and (near_vwap or near_ema20 or curr["Close"] < orb_low):
                    action = f"SHORT ({candle_pattern} {'/'.join(loc_tags)})"
                    entry_price = round(curr["Low"] - 0.05, 2)
                    stop_loss = round(max(curr["High"], current_vwap) + 0.05, 2)
                elif len(today_df) >= 3 and curr["Close"] < orb_low and vol_ratio >= 1.5 and curr["RSI14"] <= 40:
                    action = "SHORT (15m ORB Breakdown + Vol Spike)"
                    entry_price = round(curr["Close"], 2)
                    stop_loss = round(min(orb_high, current_vwap), 2)

            if action and abs(entry_price - stop_loss) > 0:
                risk_per_share = abs(entry_price - stop_loss)
                qty = int((capital * 0.01) // risk_per_share)
                target_price = round(
                    entry_price + (2 * risk_per_share) if "BUY" in action else entry_price - (2 * risk_per_share), 2
                )

            if action or candle_pattern:
                results.append({
                    "Stock": ticker.replace(".NS", ""),
                    "LTP (₹)": round(curr["Close"], 2),
                    "VWAP": round(current_vwap, 2),
                    "20 EMA": round(curr["EMA20"], 2),
                    "RSI(14)": round(curr["RSI14"], 1),
                    "5m Vol": f"{vol_ratio:.1f}x",
                    "Candle": candle_pattern or "Standard",
                    "Signal": action or f"Watch ({candle_pattern})",
                    "Entry": entry_price,
                    "SL": stop_loss,
                    "Target (1:2)": target_price,
                    "Qty (1% Risk)": qty,
                })
        except Exception:
            continue

    return pd.DataFrame(results)


if __name__ == "__main__":
    print("\n=== STAGE A: NIGHT-BEFORE WATCHLIST (NR7 / INSIDE BAR / RVOL) ===")
    eod_df = run_eod_watchlist_scan(NSE_FO_WATCHLIST)
    print(tabulate(eod_df, headers="keys", tablefmt="psql", showindex=False) if not eod_df.empty else "No EOD setups.")

    print("\n=== STAGE B: 5-MIN INTRADAY CANDLESTICK, VWAP & ORB SCANNER ===")
    intra_df = run_intraday_preopen_and_orb_scan(NSE_FO_WATCHLIST)
    print(tabulate(intra_df, headers="keys", tablefmt="psql", showindex=False) if not intra_df.empty else "No Intraday signals.")
