"""
Distant-supervision labels for filings: realized stock volatility AFTER each
10-K, bucketed into low / medium / high by terciles.

Rationale (defensible in an interview): SEC filings carry no ground-truth risk
label. We use 30-calendar-day realized volatility of the company's stock, measured
strictly AFTER the filing, as a noisy proxy. The claim is only that risk *language*
correlates with subsequent *volatility* -- never that the model predicts prices.

Window convention: "opens at t+1". We take adjusted-close prices for every trading
day strictly after filed_date, through filed_date + 30 calendar days, and compute the
annualized std of close-to-close log returns among them. The first return is therefore
t+1 -> t+2; the filing-day reaction gap (filed_date -> t+1) is intentionally excluded
so the label doesn't depend on the intraday timing of when the 10-K posted.
(Alternative, if you ever want the announcement move: anchor the first return on the
close of the last trading day <= filed_date. Not done here on purpose.)

Price source: yfinance, adjusted close (auto_adjust=True) so splits/dividends don't
masquerade as volatility. Free, keyless, full S&P 500 coverage -- fine for a one-shot
historical labeling job that never runs in the serving path.
"""
import math
import time
from datetime import timedelta
import numpy as np
from db import SessionLocal, Base, engine
from models import Company, Filing, FilingLabel

WINDOW_DAYS = 30
MIN_RETURNS = 10          
TRADING_DAYS_PER_YEAR = 252
PRICE_SOURCE = "yfinance"

def realized_vol(dates, closes, filed_date,
                 window_days=WINDOW_DAYS, min_returns=MIN_RETURNS):
    """
    Annualized realized volatility over (filed_date, filed_date + window_days].

    dates:  sorted sequence of date objects (one per trading day)
    closes: matching sequence of adjusted closes (floats), same length as dates

    Returns dict: {realized_vol, window_start, window_end, n_returns}. realized_vol
    and window_start are None if fewer than `min_returns` returns are available.
    """
    window_end = filed_date + timedelta(days=window_days)

    # "Opens at t+1": strictly after filed_date, up to and including window_end.
    win = [(d, c) for d, c in zip(dates, closes)
           if filed_date < d <= window_end and c is not None and c > 0]

    result = {"realized_vol": None, "window_start": None,
              "window_end": window_end, "n_returns": 0}
    if len(win) < min_returns + 1:      # need N+1 prices for N returns
        result["n_returns"] = max(len(win) - 1, 0)
        return result

    win.sort(key=lambda t: t[0])
    prices = np.array([c for _, c in win], dtype=float)
    log_returns = np.diff(np.log(prices))

    result["window_start"] = win[0][0]
    result["n_returns"] = len(log_returns)
    if len(log_returns) < min_returns:
        return result

    daily_std = float(np.std(log_returns, ddof=1))
    result["realized_vol"] = daily_std * math.sqrt(TRADING_DAYS_PER_YEAR)
    return result


def assign_terciles(vols):
    """
    Given a list of realized-vol floats, return (q_low, q_high, labeler) where
    labeler(v) -> 'low' | 'medium' | 'high' using the 1/3 and 2/3 quantiles.
    Buckets are relative to the observed distribution (balanced classes by design).
    """
    arr = np.asarray(vols, dtype=float)
    q_low, q_high = np.quantile(arr, [1 / 3, 2 / 3])

    def labeler(v):
        if v <= q_low:
            return "low"
        if v <= q_high:
            return "medium"
        return "high"

    return float(q_low), float(q_high), labeler

# Price fetch (yfinance) -- isolated so the math above stays testable offline.
def _yahoo_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


def fetch_prices(tickers, start, end):
    """
    Return {ticker: (dates_list, closes_list)} of adjusted closes.
    Tickers that fail or come back empty are simply omitted (and flagged by caller).
    """
    import yfinance as yf

    out = {}
    for ticker in tickers:
        sym = _yahoo_symbol(ticker)
        try:
            hist = yf.Ticker(sym).history(
                start=start, end=end, auto_adjust=True, raise_errors=False
            )
        except Exception as e:
            print(f"  ! {ticker} ({sym}): fetch failed: {e}")
            continue
        if hist is None or hist.empty or "Close" not in hist:
            print(f"  ! {ticker} ({sym}): no price data returned")
            continue
        dates = [ts.date() for ts in hist.index]
        closes = [float(x) for x in hist["Close"].tolist()]
        out[ticker] = (dates, closes)
        time.sleep(0.15)  # be polite to Yahoo across ~50 tickers
    return out


# Orchestration
def label_all_filings():
    FilingLabel.__table__.drop(engine, checkfirst=True)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        rows = (
            db.query(Filing, Company.ticker)
              .join(Company, Filing.company_id == Company.id)
              .filter(Filing.filed_date.isnot(None))
              .all()
        )
        print(f"Filings to label: {len(rows)}")
        if not rows:
            return

        tickers = sorted({t for _, t in rows})
        min_date = min(f.filed_date for f, _ in rows) - timedelta(days=10)
        max_date = max(f.filed_date for f, _ in rows) + timedelta(days=WINDOW_DAYS + 10)
        print(f"Fetching prices for {len(tickers)} tickers, "
              f"{min_date} -> {max_date} ...")
        prices = fetch_prices(tickers, min_date, max_date)
        print(f"Got prices for {len(prices)}/{len(tickers)} tickers\n")

        # Pass 1: realized vol per filing
        computed = []   # (filing, ticker, vol_dict)
        missing_price, too_short = 0, 0
        for filing, ticker in rows:
            if ticker not in prices:
                computed.append((filing, ticker, None))
                missing_price += 1
                continue
            dates, closes = prices[ticker]
            vd = realized_vol(dates, closes, filing.filed_date)
            computed.append((filing, ticker, vd))
            if vd["realized_vol"] is None:
                too_short += 1

        valid_vols = [vd["realized_vol"] for _, _, vd in computed
                      if vd and vd["realized_vol"] is not None]
        if not valid_vols:
            print("No valid volatilities computed -- aborting before writing labels.")
            return

        q_low, q_high, labeler = assign_terciles(valid_vols)
        print(f"Valid vols: {len(valid_vols)} | "
              f"tercile boundaries: low<= {q_low:.3f} < med <= {q_high:.3f} < high\n")

        # Pass 2: write labels
        counts = {"low": 0, "medium": 0, "high": 0, "null": 0}
        objs = []
        for filing, ticker, vd in computed:
            vol = vd["realized_vol"] if vd else None
            label = labeler(vol) if vol is not None else None
            counts[label if label else "null"] += 1
            objs.append(FilingLabel(
                filing_id=filing.id,
                realized_vol=vol,
                vol_label=label,
                window_start=(vd or {}).get("window_start"),
                window_end=(vd or {}).get("window_end"),
                n_returns=(vd or {}).get("n_returns", 0),
                price_source=PRICE_SOURCE,
                tercile_low=q_low,
                tercile_high=q_high,
            ))
        db.add_all(objs)
        db.commit()

        # Never trust a bulk write without counting it.
        written = db.query(FilingLabel).count()
        print("Label counts:", counts)
        print(f"Rows written: {written} (expected {len(computed)})")
        if written != len(computed):
            raise RuntimeError(
                f"Row-count mismatch: {written} of {len(computed)} labels persisted. "
                "Check for a duplicate filing_id or a stale filing_labels schema."
            )
        print(f"(missing price data: {missing_price}, window too short: {too_short})")
    finally:
        db.close()


if __name__ == "__main__":
    label_all_filings()