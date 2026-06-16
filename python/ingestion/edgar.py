import httpx
import asyncio
import os
import time
from dotenv import load_dotenv
import re
from bs4 import BeautifulSoup
import warnings
from bs4 import XMLParsedAsHTMLWarning
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

load_dotenv()

USER_AGENT = os.getenv("EDGAR_USER_AGENT")
if not USER_AGENT:
    raise RuntimeError("EDGAR_USER_AGENT not set in .env")

HEADERS = {"User-Agent": USER_AGENT}

RATE_LIMIT_DELAY = 0.15 # seconds between requests

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

async def fetch_ticker_to_cik_map(client: httpx.AsyncClient) -> dict:
    """
    Fetch SEC's master ticker->CIK mapping.
    Returns dict like {'AAPL': {'cik': '0000320193', 'name': 'Apple Inc.'}}
    CIK must be zero-padded to 10 digits for the submissions API.
    """
    resp = await client.get(TICKER_MAP_URL, headers=HEADERS)
    resp.raise_for_status()
    raw = resp.json()
    
    mapping = {}
    for entry in raw.values():
        ticker = entry["ticker"].upper()
        cik_padded = str(entry["cik_str"]).zfill(10)
        mapping[ticker] = {"cik": cik_padded, "name": entry["title"]}
    return mapping

async def fetch_filing_history(client: httpx.AsyncClient, cik: str) -> dict:
    """
    Fetch a company's full submission history from the SEC submissions API.
    cik must be zero-padded to 10 digits.
    """
    url = SUBMISSIONS_URL.format(cik=cik)
    resp = await client.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()

def extract_10k_filings(submissions: dict) -> list[dict]:
    """
    From a submissions payload, pull out 10-K filings.
    The recent filings live in submissions['filings']['recent'] as
    parallel arrays (column-oriented), so they get zipped back into rows.
    """
    recent = submissions["filings"]["recent"]
    forms = recent["form"]
    accession_numbers = recent["accessionNumber"]
    filing_dates = recent["filingDate"]
    primary_docs = recent["primaryDocument"]
    
    results = []
    for i, form in enumerate(forms):
        if form.strip().replace("\xa0", " ") == "10-K":
            results.append({
                "accession_number": accession_numbers[i],
                "filed_date": filing_dates[i],
                "primary_document": primary_docs[i],
            })
    return results

def build_filing_url(cik: str, accession_number: str, primary_document: str) -> str:
    """Construct the URL to a filing's primary HTML document."""
    cik_int = str(int(cik)) # strip leading zeros for the archives path
    accession_no_dashes = accession_number.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_int}/{accession_no_dashes}/{primary_document}"
    )
    
async def fetch_filing_document(client: httpx.AsyncClient, url: str) -> str:
    """Fetch the raw HTML of a filing document."""
    resp = await client.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.text

def extract_item_1a(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    
    header_pattern = re.compile(
        r"(item\s*1a\.?\s*)?risk\s*factors\s*[\.\:\u201d\"]?\s+(?=[A-Z])",
        re.IGNORECASE,
    )
    end_pattern = re.compile(
        r"item\s*1b\.?\s*unresolved"
        r"|item\s*2\.?\s*properties"
        r"|item\s*3\.?\s*legal\s*proceedings"
        r"|unresolved\s*staff\s*comments"
        r"|form\s*10-k\s*cross\s*reference",
        re.IGNORECASE,
    )
    
    def is_cross_reference(text: str, header_end: int) -> bool:
        window = text[max(0, header_end - 80):header_end + 80].lower()
        ref_signals = [
            "of this form", "under the heading", "see risk factors",
            "refer to", "described in", "set forth in", "in the risk factors",
        ]
        return any(sig in window for sig in ref_signals)
    
    def is_toc_entry(text: str, header_end: int) -> bool:
        after = text[header_end:header_end + 40]
        return bool(re.match(r"\s*\d{1,4}\s+item\s*1b", after, re.IGNORECASE))
    
    candidates = []
    for m in header_pattern.finditer(text):
        start_idx = m.end()
        
        if is_cross_reference(text, start_idx):
            continue
        if is_toc_entry(text, m.start()):
            continue
        
        end_match = end_pattern.search(text, start_idx)
        end_idx = end_match.start() if end_match else len(text)
        section = text[start_idx:end_idx].strip()
        if len(section) > 2000:
            candidates.append((start_idx, section))
            
    if not candidates:
        return None
    
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]
    
    
def assess_extraction_quality(section: str | None) -> dict:
    """
    Return a quality assessment for an extracted Item 1A section.
    Used to flag questionable extractions for the data-quality report
    rather than silently trusting them.
    """
    if section is None:
        return {"status": "failed", "length": 0, "flags": ["no_section_found"]}
    
    flags = []
    length = len(section)
    
    if length < 5000:
        flags.append("suspiciously_short")
    if length > 300000:
        flags.append("suspiciously_long_possible_overrun")
    tail = section[-200:].lower()
    if "cross reference" in tail or re.search(r"\d+=\d+", tail):
        flags.append("possible_toc_overrun_at_end")
        
    status = "clean" if not flags else "flagged"
    return {"status": status, "length": length, "flags": flags}    

async def main():
    """Validation run: resolve a few tickers and list their 10-K filings."""
    test_tickers = ["AAPL", "JPM", "XOM", "GE", "F"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        ticker_map = await fetch_ticker_to_cik_map(client)
        await asyncio.sleep(RATE_LIMIT_DELAY)

        for ticker in test_tickers:
            if ticker not in ticker_map:
                print(f"{ticker}: not found\n")
                continue

            info = ticker_map[ticker]
            cik = info["cik"]
            submissions = await fetch_filing_history(client, cik)
            await asyncio.sleep(RATE_LIMIT_DELAY)

            tenks = extract_10k_filings(submissions)
            if not tenks:
                print(f"{ticker}: no 10-Ks in recent window\n")
                continue

            most_recent = tenks[0]
            url = build_filing_url(cik, most_recent["accession_number"], most_recent["primary_document"])
            html = await fetch_filing_document(client, url)
            await asyncio.sleep(RATE_LIMIT_DELAY)

            item_1a = extract_item_1a(html)
            quality = assess_extraction_quality(item_1a)
            if item_1a:
                print(f"{ticker} ({most_recent['filed_date']}): {quality['status']} "
                      f"{quality['length']:,} chars flags={quality['flags']}")
                print(f"  START: {item_1a[:120]}")
                print(f"  END:   {item_1a[-120:]}\n")
            else:
                print(f"{ticker}: FAILED flags={quality['flags']}\n")
            
if __name__ == "__main__":
    asyncio.run(main())