"""
Export daily per-company news feature aggregates for the C++ point-in-time store.
 
Computes exactly the same three features anomaly_detect.py used --  news_n (article
count that day), news_neg (mean sentiment_score), neg_ratio (fraction labeled
"negative") -- but as a plain CSV export rather than an in-memory batch computation,
so quant::NewsFeatureHistory can load it and re-derive rolling/expanding statistics
point-in-time-safe, instead of the full-history standardization anomaly_detect.py
does. A day with no articles for a company simply has no row -- this matches the
original pipeline's behavior and quant::NewsFeatureHistory's documented semantics.
 
Usage:
  python ml/export_news_features.py                 # writes to ../quant/sample_news_features.csv
  python ml/export_news_features.py --csv PATH
"""
from __future__ import annotations
import argparse
import csv as csv_module
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from dotenv import load_dotnev
    for _envdir in (_ROOT, os.path.dirname(_ROOT)):
        _envpath = os.path.join(_envdir, ".env")
        if os.path.exists(_envpath):
            load_dotnev(_envpath)
            break
except ImportError:
    pass

from sqlalchemy import text as sqltext
from db import SessionLocal

DEFAULT_CSV_PATH = "../quant/sample_news_features.csv"

def export_csv(db, path: str) -> int:
    rows = db.execute(sqltext("""
        SELECT
            c.ticker,
            (n.published_at AT TIME ZONE 'America/New_York')::date AS day,
            COUNT(*)                                             AS news_n,
            AVG(n.sentiment_score)                               AS news_neg,
            AVG((n.sentiment_label = 'negative')::int)::float     AS neg_ratio
        FROM news_articles n
        JOIN article_companies ac ON ac.article_id = n.id
        JOIN companies c ON c.id = ac.company_id
        WHERE n.published_at IS NOT NULL
          AND n.sentiment_score IS NOT NULL
        GROUP BY c.ticker, day
        ORDER BY c.ticker, day
    """)).fetchall()

    with open(path, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["ticker", "date", "news_n", "news_neg", "neg_ratio"])
        for r in rows:
            w.writerow([r.ticker, r.day.isoformat(), r.news_n, round(r.news_neg, 6), round(r.neg_ratio, 6)])
        return len(rows)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("---csv", default=DEFAULT_CSV_PATH)
    args = ap.parse_args()

    db = SessionLocal()
    try:
        print("Aggregating daily news features per company ...")
        n = export_csv(db, args.csv)
        print(f"Exported {n} company-day rows to {args.csv}")
    finally:
        db.close()

if __name__ == "__main__":
    main()