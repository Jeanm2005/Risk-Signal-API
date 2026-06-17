import httpx
import asyncio
import os
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta
from db import SessionLocal
from models import Company
from ingestion.store import upsert_news_article

load_dotenv()

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/company-news"

# Finnhub free tier: 60 calls/min. Stay safely under with a small delay.
RATE_LIMIT_DELAY = 1.1  # seconds between calls -> ~55/min

async def fetch_company_news(client: httpx.AsyncClient, ticker: str, days_back: int = 30) -> list[dict] | None:
    """
    Fetch news for one company over the trailing `days_back` days.
    Returns a list of articles, or None if rate-limited (429).
    """
    end = datetime.now()
    start = end - timedelta(days=days_back)
    params = {
        "symbol": ticker,
        "from": start.strftime("%Y-%m-%d"),
        "to": end.strftime("%Y-%m-%d"),
        "token": FINNHUB_API_KEY,
    }
    resp = await client.get(FINNHUB_NEWS_URL, params=params)
    if resp.status_code == 429:
        print(f" Rate limited on {ticker}")
        return None
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        print(f" Unexpected response for {ticker}: {str(data)[:150]}")
        return []
    return data

def parse_finnhub_timestamp(ts) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(ts))
    except (ValueError, TypeError, OSError):
        return None
    
def normalize_article(raw: dict) -> dict | None:
    """Convert one Finnhub article to the schema. None if unusable."""
    url = raw.get("url", "")
    headline = raw.get("headline", "")
    if not url or not headline:
        return None
    return {
        "headline": headline,
        "body": raw.get("summary", ""),
        "url": url,
        "published_at": parse_finnhub_timestamp(raw.get("datetime")),
        "source": raw.get("source", "finnhub"),
    }
    
async def ingest_news(days_back: int = 30, max_companies: int = None):
    """Fetch news for all tracked companies via Finnhub (one call each)."""
    db = SessionLocal()
    try:
        companies = {c.ticker: c.id for c in db.query(Company).all()}
        tickers = sorted(companies.keys())
        if max_companies:
            tickers = tickers[:max_companies]
        print(f"Fetching news for {len(tickers)} companies"
              f"(trailing {days_back} days)\n")
        
        total_articles = 0
        total_stored = 0
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for ticker in tickers:
                feed = await fetch_company_news(client, ticker, days_back)
                await asyncio.sleep(RATE_LIMIT_DELAY)
                
                if feed is None:
                    print("Stopping due to rate limit.")
                    break
                
                stored = 0
                seen = set()
                for raw in feed:
                    rec = normalize_article(raw)
                    if not rec or rec["url"] in seen:
                        continue
                    seen.add(rec["url"])
                    upsert_news_article(db, company_id=companies[ticker], **rec)
                    stored += 1
                    
                total_articles += len(feed)
                total_stored += stored
                print(f" {ticker:6} {len(feed):4} fetched, {stored:4} stored")
    finally:
        db.close()
        
async def probe_finnhub():
    async with httpx.AsyncClient(timeout=30.0) as client:
        feed = await fetch_company_news(client, "AAPL", days_back=7)
        print(f"Got {len(feed) if feed else 0} articles")
        if feed:
            a = feed[0]
            print("Keys:", list(a.keys()))
            print("Sample headline:", a.get("headline", "")[:90])
            print("Sample source:", a.get("source"))
            print("Sample datetime:", parse_finnhub_timestamp(a.get("datetime")))
            
if __name__ == "__main__":
    asyncio.run(ingest_news(days_back=30))