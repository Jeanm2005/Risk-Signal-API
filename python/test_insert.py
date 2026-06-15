from db import SessionLocal
from ingestion.store import upsert_company, upsert_filing

def main():
    db = SessionLocal()
    try:
        company_id = upsert_company(
            db, ticker="AAPL", name="Apple Inc.",
            cik="0000320193", sector="Technology", sic_code="3571",
        )
        print(f"Company upserted, id={company_id}")
        
        filing_id = upsert_filing(
            db, company_id=company_id,
            accession_number="0000320193-25-000079",
            form_type="10-K", filed_date="2025-10-31",
            raw_text="TEST: risk factors placeholder text",
        )
        print(f"Filing upserted, id={filing_id}")
        
        company_id2 = upsert_company(
            db, ticker="AAPL", name="Apple Inc.",
            cik="0000320193", sector="Technology", sic_code="3571",
        )
        print(f"Second upsert, id={company_id2} (should match {company_id})")
    finally:
        db.close()
        
if __name__ == "__main__":
    main()