from __future__ import annotations
import argparse
import datetime as dt
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)          
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from dotenv import load_dotenv
    for _envdir in (_ROOT, os.path.dirname(_ROOT)):
        _envpath = os.path.join(_envdir, ".env")
        if os.path.exists(_envpath):
            load_dotenv(_envpath)
            break
except ImportError:
    pass

from sqlalchemy import text as sqltext
from db import SessionLocal
from models import Company, NewsArticle, ArticleCompany, Alert
from explain import AnomalyFacts, Headline, explain_anomaly
from claude_adapter import ClaudeAdapter

HEADLINES_PER_ALERT = 5


def top_negative_headlines(db, company_id: int, day: dt.datetime, limit: int) -> list[Headline]:
    """That company's most-negative headlines on the anomaly day (same axis as the pipeline)."""
    rows = (
        db.query(NewsArticle.id, NewsArticle.headline, NewsArticle.source,
                 NewsArticle.sentiment_score)
        .join(ArticleCompany, ArticleCompany.article_id == NewsArticle.id)
        .filter(ArticleCompany.company_id == company_id)
        .filter(sqltext("news_articles.published_at::date = :d")).params(d=day.date())
        .order_by(NewsArticle.sentiment_score.desc().nullslast())
        .limit(limit)
        .all()
    )
    return [Headline(id=r[0], text=r[1], source=r[2], sentiment_score=r[3]) for r in rows]


def ensure_table(db) -> None:
    db.execute(sqltext("""
        CREATE TABLE IF NOT EXISTS alert_explanations (
            id           SERIAL PRIMARY KEY,
            alert_id     INTEGER NOT NULL UNIQUE REFERENCES alerts(id) ON DELETE CASCADE,
            status       VARCHAR(20)  NOT NULL,      -- 'generated' | 'abstained'
            narrative    TEXT,
            cited_ids    INTEGER[],
            model        VARCHAR(80),
            abstain_reason VARCHAR(120),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    db.commit()


def already_done(db, alert_id: int) -> bool:
    row = db.execute(sqltext("SELECT 1 FROM alert_explanations WHERE alert_id = :a"),
                     {"a": alert_id}).first()
    return row is not None


def store(db, alert_id: int, result) -> None:
    db.execute(sqltext("""
        INSERT INTO alert_explanations
            (alert_id, status, narrative, cited_ids, model, abstain_reason)
        VALUES (:a, :s, :n, :c, :m, :r)
        ON CONFLICT (alert_id) DO UPDATE SET
            status = EXCLUDED.status, narrative = EXCLUDED.narrative,
            cited_ids = EXCLUDED.cited_ids, model = EXCLUDED.model,
            abstain_reason = EXCLUDED.abstain_reason, created_at = now()
    """), {"a": alert_id, "s": result.status, "n": result.narrative,
           "c": result.cited_ids or None, "m": result.model,
           "r": result.abstain_reason})
    db.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--severity", default="high", choices=["high", "medium", "low", "all"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--redo", action="store_true", help="regenerate even if already stored")
    ap.add_argument("--model", default="claude-sonnet-4-6")
    args = ap.parse_args()

    adapter = ClaudeAdapter(model=args.model)
    db = SessionLocal()
    try:
        ensure_table(db)

        q = db.query(Alert, Company).join(Company, Company.id == Alert.company_id) \
              .filter(Alert.alert_type == "news_market_anomaly")
        if args.severity != "all":
            q = q.filter(Alert.severity == args.severity)
        q = q.order_by(Alert.triggered_at.desc())
        if args.limit:
            q = q.limit(args.limit)
        alerts = q.all()

        print(f"{len(alerts)} alert(s) at severity='{args.severity}'.")
        gen = ab = skip = 0
        for alert, company in alerts:
            if not args.redo and already_done(db, alert.id):
                skip += 1
                continue
            headlines = top_negative_headlines(db, company.id, alert.triggered_at, HEADLINES_PER_ALERT)
            facts = AnomalyFacts(
                ticker=company.ticker, company_name=company.name,
                date=alert.triggered_at.date().isoformat(),
                sigma_explanation=alert.explanation or "",
                severity=alert.severity or "", headlines=headlines,
            )
            result = explain_anomaly(facts, adapter)
            store(db, alert.id, result)
            if result.status == "generated":
                gen += 1
                print(f"  [gen ] {company.ticker} {facts.date}: {result.narrative[:90]}...")
            else:
                ab += 1
                print(f"  [abst] {company.ticker} {facts.date}: {result.abstain_reason}")

        print(f"\nDone. generated={gen}  abstained={ab}  skipped={skip}")
    finally:
        db.close()


if __name__ == "__main__":
    main()