import httpx
import asyncio
import os
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta
from db import SessionLocal
from models import Company
from ingestion.store import upsert_article, link_article_company

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
        
class RateLimiter:
    """Paces operations to `rate` per `period` seconds, evenly spaced."""
    def __init__(self, rate: int, period: float = 60.0):
        self.min_interval = period / rate
        self._lock = asyncio.Lock()
        self._last = 0.0
        
    async def acquire(self):
        async with self._lock:
            now = asyncio.get_event_loop().time()
            wait = self._last + self.min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = asyncio.get_event_loop().time()
            
async def fetch_one_with_limits(
    client: httpx.AsyncClient,
    ticker: str,
    limiter: RateLimiter,
    sem: asyncio.Semaphore,
    days_back: int,
    max_retries: int = 2,
) -> tuple[str, list[dict] | None]:
    """
    Fetch one company's news under rate + concurrency limits, with retry on 429.
    Returns (ticker, articles) or (ticker, None) if it ultimately failed.
    """
    for attempt in range(max_retries + 1):
        async with sem:
            await limiter.acquire()
            try:
                feed = await fetch_company_news(client, ticker, days_back)
                if feed is not None:
                    return ticker, feed
                # None means 429
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                if attempt == max_retries:
                    print(f" {ticker}: failed after retries ({type(e).__name__})")
                    return ticker, None
        await asyncio.sleep(2.0 * (attempt + 1))
    return ticker, None

async def ingest_news_concurrent(days_back: int = 30, rate: int = 55, max_concurrent: int = 10, limit_companies: int = None):
    """
    Concurrent news ingestion across all tracked companies.

    Architecture: concurrent paced FETCH -> collect -> sequential STORE.
    - RateLimiter keeps us under Finnhub's 60/min (default 55 for safety).
    - Semaphore caps simultaneous connections.
    - DB writes happen sequentially after fetching, avoiding session races.
    """
    db = SessionLocal()
    try:
        companies = {c.ticker: c.id for c in db.query(Company).all()}
        tickers = sorted(companies.keys())
        if limit_companies:
            tickers = tickers[:limit_companies]
        print(f"Concurrent fetch: {len(tickers)} companies, "
              f"rate={rate}/min, concurrency={max_concurrent}\n")
        
        limiter = RateLimiter(rate=rate)
        sem = asyncio.Semaphore(max_concurrent)
        
        # --- Phase 1: concurrent fetch ---
        import time
        t0 = time.time()
        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = [
                fetch_one_with_limits(client, t, limiter, sem, days_back)
                for t in tickers
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        fetch_time = time.time() - t0
        print(f"Fetch complete in {fetch_time:.1f}s\n")

        # --- Phase 2: sequential store ---
        total_stored = 0
        failed = []
        empty = []
        for res in results:
            if isinstance(res, Exception):
                print(f"  Task exception: {res}")
                continue
            ticker, feed = res
            if feed is None:
                failed.append(ticker)
                continue
            if not feed:
                empty.append(ticker)
                continue
            seen = set()
            for raw in feed:
                rec = normalize_article(raw)
                if not rec or rec["url"] in seen:
                    continue
                seen.add(rec["url"])
                article_id = upsert_article(
                    db,
                    url=rec["url"],
                    headline=rec["headline"],
                    body=rec["body"],
                    source=rec["source"],
                    published_at=rec["published_at"],
                )
                link_article_company(db, article_id, companies[ticker])
                total_stored += 1

        print(f"\n{'='*50}")
        print(f"Stored: {total_stored} articles")
        print(f"Companies fetched OK: {len(tickers) - len(failed)}")
        if failed:
            print(f"Failed ({len(failed)}): {', '.join(failed[:20])}"
                  f"{'...' if len(failed) > 20 else ''}")
        if empty:
            print(f"No articles ({len(empty)}): {', '.join(empty[:20])}"
                  f"{'...' if len(empty) > 20 else ''}")
    finally:
        db.close()
            
if __name__ == "__main__":
    asyncio.run(ingest_news_concurrent(days_back=30))