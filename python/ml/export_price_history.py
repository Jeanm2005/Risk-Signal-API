from __future__ import annotations

import argparse
import csv as csv_module
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import text as sqltext

from db import SessionLocal
from models import Company

DEFAULT_CSV_PATH = "../quant/sample_prices.csv"


def ensure_table(db) -> None:
    db.execute(sqltext("""
        CREATE TABLE IF NOT EXISTS price_history (
            id         SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            date       DATE NOT NULL,
            open       DOUBLE PRECISION,
            high       DOUBLE PRECISION,
            low        DOUBLE PRECISION,
            close      DOUBLE PRECISION,
            adj_close  DOUBLE PRECISION,
            volume     BIGINT,
            UNIQUE (company_id, date)
        )
    """))
    db.execute(sqltext(
        "CREATE INDEX IF NOT EXISTS idx_price_history_company_date "
        "ON price_history (company_id, date)"))
    db.commit()


def fetch_and_persist(db, tickers_and_ids: list[tuple[str, int]],
                      start: str, end: str) -> int:
    import yfinance as yf
    written = 0
    for ticker, company_id in tickers_and_ids:
        try:
            h = yf.Ticker(ticker.replace(".", "-")).history(
                start=start, end=end, auto_adjust=False)
        except Exception as e:
            print(f"  ! {ticker}: {e}")
            continue
        if h is None or h.empty:
            continue

        rows = []
        for idx, row in h.iterrows():
            rows.append({
                "company_id": company_id,
                "date": idx.date().isoformat(),
                "open": float(row["Open"]) if not _isnan(row["Open"]) else None,
                "high": float(row["High"]) if not _isnan(row["High"]) else None,
                "low": float(row["Low"]) if not _isnan(row["Low"]) else None,
                "close": float(row["Close"]) if not _isnan(row["Close"]) else None,
                "adj_close": float(row["Adj Close"]) if "Adj Close" in row and not _isnan(row["Adj Close"]) else float(row["Close"]),
                "volume": int(row["Volume"]) if not _isnan(row["Volume"]) else None,
            })
        if not rows:
            continue

        db.execute(sqltext("""
            INSERT INTO price_history (company_id, date, open, high, low, close, adj_close, volume)
            VALUES (:company_id, :date, :open, :high, :low, :close, :adj_close, :volume)
            ON CONFLICT (company_id, date) DO UPDATE SET
                open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                close = EXCLUDED.close, adj_close = EXCLUDED.adj_close, volume = EXCLUDED.volume
        """), rows)
        db.commit()
        written += len(rows)
        print(f"  {ticker}: {len(rows)} bars")
    return written


def _isnan(x) -> bool:
    try:
        return x != x  # NaN != NaN
    except Exception:
        return False


def export_csv(db, path: str) -> int:
    rows = db.execute(sqltext("""
        SELECT c.ticker, p.date, p.open, p.high, p.low, p.close, p.adj_close, p.volume
        FROM price_history p
        JOIN companies c ON c.id = p.company_id
        ORDER BY c.ticker, p.date
    """)).fetchall()

    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"])
        for r in rows:
            w.writerow([r.ticker, r.date.isoformat(),
                       r.open, r.high, r.low, r.close, r.adj_close, r.volume])
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default=None, help="default: today")
    ap.add_argument("--csv", default=DEFAULT_CSV_PATH)
    ap.add_argument("--db-only", action="store_true")
    ap.add_argument("--csv-only", metavar="PATH", nargs="?", const=DEFAULT_CSV_PATH,
                    help="skip fetching, just export existing DB rows to CSV")
    args = ap.parse_args()

    import datetime
    end = args.end or datetime.date.today().isoformat()

    db = SessionLocal()
    try:
        ensure_table(db)

        if not args.csv_only:
            companies = db.query(Company.ticker, Company.id).all()
            print(f"Fetching price history for {len(companies)} companies "
                  f"({args.start} -> {end}) ...")
            n = fetch_and_persist(db, [(c.ticker, c.id) for c in companies], args.start, end)
            print(f"\nWrote {n} price rows to price_history.")

        if not args.db_only:
            path = args.csv_only or args.csv
            n = export_csv(db, path)
            print(f"Exported {n} rows to {path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()