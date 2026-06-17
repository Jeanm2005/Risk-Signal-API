import httpx
import csv
import io
from db import SessionLocal
from ingestion.store import upsert_company

SP500_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/"
    "s-and-p-500-companies/main/data/constituents.csv"
)

def fetch_sp500_constituents() -> list[dict]:
    """Fetch the S&P 500 list. Returns list of dicts with ticker, name, cik, sector."""
    resp = httpx.get(SP500_CSV_URL, timeout=30.0)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    companies = []
    for row in reader:
        ticker = row["Symbol"].strip().upper()
        # SEC submissions API needs CIK zero-padded to 10 digits
        cik = row["CIK"].strip().zfill(10)
        companies.append({
            "ticker": ticker,
            "name": row["Security"].strip(),
            "cik": cik,
            "sector": row["GICS Sector"].strip(),
        })
    return companies

def load_all_companies():
    """Upsert all S&P 500 companies into the database."""
    constituents = fetch_sp500_constituents()
    print(f"Fetched {len(constituents)} S&P 500 constituents")
    
    db = SessionLocal()
    inserted = 0
    try:
        for c in constituents:
            upsert_company(
                db,
                ticker=c["ticker"],
                name=c["name"],
                cik=c["cik"],
                sector=c["sector"],
            )
            inserted += 1
        print(f"Upserted {inserted} companies")
    finally:
        db.close()
        
if __name__ == "__main__":
    load_all_companies()