import sys
import warnings
import pytz
from datetime import datetime, time as dtime, timedelta
import yfinance as yf
import pandas as pd
from tabulate import tabulate

IST = pytz.timezone("Asia/Kolkata")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

warnings.filterwarnings("ignore")

# =====================================================================
# 50 LARGE-CAP BEST COMPANIES (Nifty 50 Blue Chips)
# =====================================================================
LARGE_CAP_50 = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "BHARTIARTL.NS", "SBIN.NS", "ITC.NS", "LT.NS", "HCLTECH.NS",
    "BAJFINANCE.NS", "SUNPHARMA.NS", "M&M.NS", "MARUTI.NS", "KOTAKBANK.NS",
    "AXISBANK.NS", "TITAN.NS", "ONGC.NS", "NTPC.NS", "POWERGRID.NS",
    "ADANIENT.NS", "ADANIPORTS.NS", "COALINDIA.NS", "BAJAJFINSV.NS", "TATASTEEL.NS",
    "ASIANPAINT.NS", "HINDUNILVR.NS", "ULTRACEMCO.NS", "JSWSTEEL.NS", "GRASIM.NS",
    "HINDALCO.NS", "TECHM.NS", "WIPRO.NS", "CIPLA.NS", "DRREDDY.NS",
    "APOLLOHOSP.NS", "EICHERMOT.NS", "TRENT.NS", "BEL.NS", "HAL.NS",
    "BPCL.NS", "HEROMOTOCO.NS", "SHREECEM.NS", "DIVISLAB.NS", "SBILIFE.NS",
    "HDFCLIFE.NS", "BRITANNIA.NS", "NESTLEIND.NS", "INDUSINDBK.NS", "BAJAJ-AUTO.NS"
]

# =====================================================================
# 50 MID-CAP BEST COMPANIES (High Liquidity F&O Leaders)
# =====================================================================
MID_CAP_50 = [
    "DLF.NS", "INDIGO.NS", "PFC.NS", "RECLTD.NS", "POLYCAB.NS",
    "PERSISTENT.NS", "COFORGE.NS", "LTTS.NS", "CUMMINSIND.NS", "BHARATFORG.NS",
    "ASHOKLEY.NS", "AUROPHARMA.NS", "LUPIN.NS", "ALKEM.NS", "TORNTPHARM.NS",
    "PIIND.NS", "COLPAL.NS", "MARICO.NS", "BERGEPAINT.NS", "DABUR.NS",
    "GODREJCP.NS", "VOLTAS.NS", "HAVELLS.NS", "CROMPTON.NS", "DIXON.NS",
    "BHEL.NS", "SAIL.NS", "NMDC.NS", "JINDALSTEL.NS", "FEDERALBNK.NS",
    "IDFCFIRSTB.NS", "BANDHANBNK.NS", "AUBANK.NS", "BANKBARODA.NS", "PNB.NS",
    "CANBK.NS", "UNIONBANK.NS", "CHOLAFIN.NS", "SHRIRAMFIN.NS", "MUTHOOTFIN.NS",
    "M&MFIN.NS", "ABCAPITAL.NS", "TATACOMM.NS", "JUBLFOOD.NS", "CONCOR.NS",
    "TATAPOWER.NS", "OBEROIRLTY.NS", "GODREJPROP.NS", "PRESTIGE.NS", "ESCORTS.NS"
]

# =====================================================================
# 50 SMALL-CAP BEST COMPANIES (High Growth & Active Momentum Leaders)
# =====================================================================
SMALL_CAP_50 = [
    "CDSL.NS", "ANGELONE.NS", "BSE.NS", "MCX.NS", "IEX.NS",
    "SUZLON.NS", "IRFC.NS", "RVNL.NS", "IRCTC.NS", "MAZDOCK.NS",
    "COCHINSHIP.NS", "GRSE.NS", "DEVYANI.NS", "KPITTECH.NS", "TATAELXSI.NS",
    "CYIENT.NS", "SONACOMS.NS", "KAYNES.NS", "TITAGARH.NS", "JUPITERWAG.NS",
    "RITES.NS", "RAILTEL.NS", "NBCC.NS", "HUDCO.NS", "MOTILALOFS.NS",
    "MANAPPURAM.NS", "POONAWALLA.NS", "KARURVYSYA.NS", "CUB.NS", "EQUITASBNK.NS",
    "UJJIVANSFB.NS", "RBLBANK.NS", "JYOTHYLAB.NS", "BIKAJI.NS", "CEATLTD.NS",
    "APOLLOTYRE.NS", "MRF.NS", "EXIDEIND.NS", "KEC.NS", "DEEPAKNTR.NS",
    "TATACHEM.NS", "AARTIIND.NS", "ATUL.NS", "CASTROLIND.NS", "CESC.NS",
    "TATAINVEST.NS", "BLS.NS", "REDINGTON.NS", "HBLPOWER.NS", "RADICO.NS"
]

# Unified 150-Stock High Alpha Watchlist
NSE_FO_WATCHLIST = LARGE_CAP_50 + MID_CAP_50 + SMALL_CAP_50


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
    """Stage A: Night-Before Scanner for NR7, Inside Bars, RVOL > 1.5x, and PDH/PDL.
    Uses 5m intraday bar aggregation to ensure today's High/Low/Close are accurate and avoids
    the 4:00 PM yfinance incomplete candle anomaly where Close == High.
    """
    data = yf.download(tickers, period="1y", interval="1d", group_by="ticker", progress=False, threads=True)
    intra_data = yf.download(tickers, period="5d", interval="5m", group_by="ticker", progress=False, threads=True)
    results = []

    for ticker in tickers:
        try:
            df = data[ticker].dropna()
            if len(df) < 205:
                continue

            # Overwrite today's daily candle with true aggregated 5-minute bars
            try:
                df_5m = intra_data[ticker].dropna()
                if not df_5m.empty:
                    if isinstance(df_5m.columns, pd.MultiIndex):
                        df_5m.columns = df_5m.columns.get_level_values(0)
                    latest_date = df_5m.index[-1].date()
                    today_bars = df_5m[df_5m.index.date == latest_date]
                    if len(today_bars) >= 5:
                        df.loc[df.index[-1], "Open"] = round(float(today_bars["Open"].iloc[0]), 2)
                        df.loc[df.index[-1], "High"] = round(float(today_bars["High"].max()), 2)
                        df.loc[df.index[-1], "Low"] = round(float(today_bars["Low"].min()), 2)
                        df.loc[df.index[-1], "Close"] = round(float(today_bars["Close"].iloc[-1]), 2)
                        intraday_vol = int(today_bars["Volume"].sum())
                        if intraday_vol > 0:
                            df.loc[df.index[-1], "Volume"] = intraday_vol
            except Exception:
                pass

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

            # Sanity Guard for Close Location Value (CLV)
            # Require minimum 0.8% intraday range so corrupted zero-wick candles don't trigger false StrongClose
            day_range = latest["High"] - latest["Low"]
            has_valid_range = (latest["Low"] > 0) and ((day_range / latest["Low"]) >= 0.008)
            clv = (latest["Close"] - latest["Low"]) / day_range if day_range > 0 else 0.5
            is_strong_close = (clv >= 0.80) and has_valid_range
            is_weak_close = (clv <= 0.20) and has_valid_range

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
            if is_strong_close:
                setups.append("StrongClose(High)")
            elif is_weak_close:
                setups.append("WeakClose(Low)")

            # Add +0.10% buffer above true PDH and -0.10% buffer below true PDL for breakout triggers
            buy_above_pdh = round(latest["High"] * 1.001, 2)
            short_below_pdl = round(latest["Low"] * 0.999, 2)

            if setups:
                results.append({
                    "Stock": ticker.replace(".NS", ""),
                    "Close (₹)": round(latest["Close"], 2),
                    "PDH (Buy >)": buy_above_pdh,
                    "PDL (Short <)": short_below_pdl,
                    "Raw High": round(latest["High"], 2),
                    "Raw Low": round(latest["Low"], 2),
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


def get_completed_5m_candles(df: pd.DataFrame) -> pd.DataFrame:
    """
    Processes 5m data from yfinance and removes any currently forming (incomplete)
    5-minute candle so indicators and breakouts only evaluate closed bars.
    """
    if df.empty:
        return df

    # Flatten MultiIndex columns if using yfinance >= 0.2.40
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Ensure index is timezone-aware in IST
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(IST)
    else:
        df.index = df.index.tz_convert(IST)

    now_ist = datetime.now(IST)

    # Floor current time to the active 5-minute bucket
    # Example: At 09:21:14 IST, current_bucket_start is 09:20:00 IST
    # Only strip active forming bar during market hours (09:15-15:30) on trading days
    if now_ist.date() == df.index[-1].date() and dtime(9, 15) <= now_ist.time() < dtime(15, 30):
        current_bucket_start = now_ist.replace(
            minute=(now_ist.minute // 5) * 5, second=0, microsecond=0
        )
        # Keep ONLY candles strictly BEFORE the active forming bucket
        completed_df = df[df.index < current_bucket_start].copy()
        return completed_df

    return df


def get_nifty_regime(intra_data: pd.DataFrame) -> dict:
    """Evaluates 5m VWAP & 20 EMA trend of Nifty 50 index (^NSEI)."""
    try:
        if "^NSEI" in intra_data:
            nifty_raw = intra_data["^NSEI"].dropna()
        else:
            nifty_raw = yf.download("^NSEI", period="5d", interval="5m", progress=False).dropna()

        nifty_df = get_completed_5m_candles(nifty_raw)
        if len(nifty_df) < 10:
            return {"regime": "NEUTRAL", "allow_long": True, "allow_short": True}

        latest_date = nifty_df.index[-1].date()
        today_nifty = nifty_df[nifty_df.index.date == latest_date].copy()
        if len(today_nifty) < 2:
            return {"regime": "NEUTRAL", "allow_long": True, "allow_short": True}

        typ = (today_nifty["High"] + today_nifty["Low"] + today_nifty["Close"]) / 3
        today_nifty["VWAP"] = (typ * today_nifty["Volume"]).cumsum() / today_nifty["Volume"].cumsum()
        nifty_df["EMA20"] = nifty_df["Close"].ewm(span=20, adjust=False).mean()

        last_c = float(nifty_df["Close"].iloc[-1])
        last_vwap = float(today_nifty["VWAP"].iloc[-1])
        last_ema20 = float(nifty_df["EMA20"].iloc[-1])

        if last_c > last_vwap and last_c > last_ema20:
            return {
                "regime": "🚀 BULLISH (Nifty > VWAP & 20 EMA)",
                "allow_long": True,
                "allow_short": False,
            }
        elif last_c < last_vwap and last_c < last_ema20:
            return {
                "regime": "🩸 BEARISH (Nifty < VWAP & 20 EMA)",
                "allow_long": False,
                "allow_short": True,
            }
        else:
            return {
                "regime": "⚖️ CHOPPY / SIDEWAYS (Nifty inside range)",
                "allow_long": True,
                "allow_short": True,
            }
    except Exception as e:
        print(f"[!] Nifty regime evaluation warning: {e}")
        return {"regime": "NEUTRAL", "allow_long": True, "allow_short": True}


def run_intraday_preopen_and_orb_scan(tickers: list[str], capital: float = 50000.0) -> pd.DataFrame:
    """Stage B: 5-Minute Intraday Candlestick, VWAP, 20/200 EMA, RSI & 15m ORB Engine."""
    now_ist = datetime.now(IST)

    # 1. Block execution if triggered before 09:20 AM IST on market days
    market_first_close = now_ist.replace(hour=9, minute=20, second=0, microsecond=0)
    if now_ist.weekday() < 5 and now_ist < market_first_close:
        print("Skipping: First 5-minute candle (09:15-09:20 AM IST) has not closed yet.")
        return pd.DataFrame()

    scan_tickers = list(set(tickers + ["^NSEI"]))
    daily_data = yf.download(scan_tickers, period="5d", interval="1d", group_by="ticker", progress=False, threads=True)
    intra_data = yf.download(scan_tickers, period="5d", interval="5m", group_by="ticker", progress=False, threads=True)
    results = []

    # Market Direction Gate
    nifty_info = get_nifty_regime(intra_data)

    for ticker in tickers:
        try:
            d_df = daily_data[ticker].dropna()
            raw_i = intra_data[ticker].dropna()
            i_df = get_completed_5m_candles(raw_i)
            if len(d_df) < 2 or len(i_df) < 30:
                continue

            last_candle = i_df.iloc[-1]
            candle_open_time = i_df.index[-1]
            candle_close_time = candle_open_time + timedelta(minutes=5)

            # 2. Staleness Guard during live market hours:
            if now_ist.weekday() < 5 and dtime(9, 20) <= now_ist.time() <= dtime(15, 30):
                if candle_open_time.date() != now_ist.date():
                    continue
                if (now_ist - candle_close_time) > timedelta(minutes=15):
                    continue

            latest_date = i_df.index[-1].date()
            today_df = i_df[i_df.index.date == latest_date].copy()
            if len(today_df) < 1:
                continue

            # 3. Gap Protection Filter: Skip if stock gapped > 2.2% at open
            if len(d_df) >= 2 and len(today_df) >= 1:
                prev_close = float(d_df["Close"].iloc[-2])
                today_open = float(today_df["Open"].iloc[0])
                if prev_close > 0 and (abs(today_open - prev_close) / prev_close) > 0.022:
                    continue  # Exhaustion gap risk

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

            # 4. Trading Day Segmentation (Midday Lull & Closing Exit)
            current_t = now_ist.time()
            is_entry_window = True
            if now_ist.weekday() < 5:
                # 11:15 AM - 01:30 PM: Midday lull (no new entries)
                # 02:30 PM+: Closing volatility (no new entries)
                if (dtime(11, 15) <= current_t < dtime(13, 30)) or (current_t >= dtime(14, 30)):
                    is_entry_window = False

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

            # 5. Enforce Nifty 50 Directional Gate (Require RVOL >= 2.5x for Counter-Trend)
            if action:
                if "BUY" in action and not nifty_info.get("allow_long", True) and vol_ratio < 2.5:
                    action = None
                elif "SHORT" in action and not nifty_info.get("allow_short", True) and vol_ratio < 2.5:
                    action = None

            # Block action outside entry window
            if action and not is_entry_window:
                action = None

            if action and abs(entry_price - stop_loss) > 0:
                risk_per_share = abs(entry_price - stop_loss)
                qty = int((capital * 0.01) // risk_per_share)
                target_price = round(
                    entry_price + (2 * risk_per_share) if "BUY" in action else entry_price - (2 * risk_per_share), 2
                )

            if action or candle_pattern:
                bar_window = f"{candle_open_time.strftime('%H:%M')}-{candle_close_time.strftime('%H:%M')}"
                results.append({
                    "Stock": ticker.replace(".NS", ""),
                    "Bar": bar_window,
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
