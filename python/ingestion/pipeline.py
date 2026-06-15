import asyncio
import httpx
from sqlalchemy.orm import Session
from db import SessionLocal
from ingestion.edgar import (
    HEADERS, RATE_LIMIT_DELAY,
    fetch_ticker_to_cik_map, fetch_filing_history,
    extract_10k_filings, build_filing_url,
    fetch_filing_document, extract_item_1a,
    assess_extraction_quality,
)
from ingestion.store import upsert_company, upsert_filing

async def ingest_ticker(
    client: httpx.AsyncClient,
    db: Session,
    ticker: str,
    ticker_map: dict,
    max_filings: int = 3,
) -> dict:
    """
    Full ingestion for one company: SEC -> extract -> database.
    
    Derives ticker and cik together from the SEC mapping so they
    can never disagree.
    
    Returns a summary dict for reporting.
    """
    ticker = ticker.upper()
    if ticker not in ticker_map:
        return {"ticker": ticker, "status": "not_found", "filings_stored": 0}
    
    info = ticker_map[ticker]
    cik = info["cik"]
    name = info["name"]
    
    # Persist the company first; ticker and cik come from the same source.
    company_id = upsert_company(db, ticker=ticker, name=name, cik=cik)
    
    # Fetch filing history
    submissions = await fetch_filing_history(client, cik)
    await asyncio.sleep(RATE_LIMIT_DELAY)
    
    tenks = extract_10k_filings(submissions)
    if not tenks:
        return {"ticker": ticker, "status": "no_10k", "filings_stored": 0}
    
    stored = 0
    quality_summary = []
    
    for filing in tenks[:max_filings]:
        url = build_filing_url(
            cik, filing["accession_number"], filing["primary_document"]
        )
        try:
            html = await fetch_filing_document(client, url)
        except httpx.HTTPStatusError as e:
            quality_summary.append(
                {"accession": filing["accession_number"],
                 "status": f"fetch_failed_{e.response.status_code}"}
            )
            await asyncio.sleep(RATE_LIMIT_DELAY)
            continue
        await asyncio.sleep(RATE_LIMIT_DELAY)
        
        item_1a = extract_item_1a(html)
        quality = assess_extraction_quality(item_1a)
        
        upsert_filing(
            db,
            company_id=company_id,
            accession_number=filing["accession_number"],
            form_type="10-K",
            filed_date=filing["filed_date"],
            raw_text=item_1a,
        )
        stored += 1
        quality_summary.append(
            {"accession": filing["accession_number"],
             "filed": filing["filed_date"],
             "status": quality["status"],
             "length": quality["length"],
             "flags": quality["flags"]}
        )
        
    return {
        "ticker": ticker,
        "status": "ok",
        "filings_stored": stored,
        "quality": quality_summary,
    }
    
async def diagnose_old_aapl():
    import re
    from bs4 import BeautifulSoup
    async with httpx.AsyncClient(timeout=30.0) as client:
        ticker_map = await fetch_ticker_to_cik_map(client)
        await asyncio.sleep(RATE_LIMIT_DELAY)
        cik = ticker_map["AAPL"]["cik"]
        submissions = await fetch_filing_history(client, cik)
        await asyncio.sleep(RATE_LIMIT_DELAY)
        tenks = extract_10k_filings(submissions)
        
        filing = tenks[1]
        url = build_filing_url(cik, filing["accession_number"], filing["primary_document"])
        print(f"2024 filing URL: {url}")
        print(f"Primary document: {filing['primary_document']}")
        html = await fetch_filing_document(client, url)

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator=" ").replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text)
        print(f"Doc size: {len(html):,} html, {len(text):,} text")

        for pat_name, pat in [("item 1a", r"item\s*1a"), ("risk factors", r"risk\s*factors")]:
            matches = [m.start() for m in re.finditer(pat, text, re.IGNORECASE)]
            print(f"\n'{pat_name}': {len(matches)} mentions")
            for idx in matches[:8]:
                print(f"  @ {idx}: ...{text[idx:idx+70]}...")    
    
async def main():
    """Test the orchestrator on a single ticker, end to end."""
    db = SessionLocal()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            print("Fetching SEC ticker map...")
            ticker_map = await fetch_ticker_to_cik_map(client)
            await asyncio.sleep(RATE_LIMIT_DELAY)
            print(f"Loaded {len(ticker_map)} tickers\n")
            result = await ingest_ticker(client, db, "AAPL", ticker_map, max_filings=3)
            print(f"Ticker: {result['ticker']}")
            print(f"Status: {result['status']}")
            print(f"Stored: {result['filings_stored']} filings\n")
            for q in result.get("quality", []):
                print(f" {q['filed']} {q['status']:8} "
                      f"{q['length']:>8,} chars flags={q['flags']}")
    finally:
        db.close()
        
if __name__ == "__main__":
    asyncio.run(diagnose_old_aapl())