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
from ingestion.sp500_subset import SP500_SUBSET

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

async def ingest_all(max_filings: int = 3):
    """
    Ingest the full SP500 subset. Reports a summary at the end including
    extraction quality stats.
    """    
    db = SessionLocal()
    results = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            print("Fetching SEC ticker map...")
            ticker_map = await fetch_ticker_to_cik_map(client)
            await asyncio.sleep(RATE_LIMIT_DELAY)
            print(f"Loaded {len(ticker_map)} tickers\n")
            
            for i, (ticker, sector) in enumerate(SP500_SUBSET, 1):
                try:
                    result = await ingest_ticker(
                        client, db, ticker, ticker_map, max_filings=max_filings
                    )
                    _set_sector(db, ticker, sector)
                    results.append(result)
                    print(f"[{i:2}/{len(SP500_SUBSET)}] {ticker:6}"
                          f"{result['status']:10} stored={result['filings_stored']}")
                except Exception as e:
                    print(f"[{i:2}/{len(SP500_SUBSET)}] {ticker:6} ERROR: {e}")
                    results.append({"ticker": ticker, "status": "error", "filings_stored": 0})
    finally:
        db.close()
        
    _print_quality_report(results)
    
def _set_sector(db, ticker, sector):
    from models import Company
    company = db.query(Company).filter(Company.ticker == ticker.upper()).first()
    if company:
        company.sector = sector
        db.commit()
        
def _print_quality_report(results):
    print("\n" + "=" * 60)
    print("INGESTION QUALITY REPORT")
    print("=" * 60)
    
    total_filings = 0
    clean = 0
    flagged = 0
    failed = 0
    no_data = []
    
    for r in results:
        if r["status"] not in ("ok",):
            no_data.append(r['ticker'])
            continue
        for q in r.get("quality", []):
            total_filings += 1
            if q["status"] == "clean":
                clean += 1
            elif q["status"] == "flagged":
                flagged += 1
            else:
                failed += 1
                
    print(f"Companies processed: {len(results)}")
    print(f"Total filings: {total_filings}")
    print(f"  Clean:   {clean}")
    print(f"  Flagged: {flagged}")
    print(f"  Failed:  {failed}")
    if total_filings:
        print(f"  Clean rate: {clean/total_filings*100:.1f}%")
    if no_data:
        print(f"Companies with no data: {', '.join(no_data)}")
    
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
    asyncio.run(ingest_all(max_filings=3))