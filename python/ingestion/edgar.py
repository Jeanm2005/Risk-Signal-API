import httpx
import asyncio
import os
import time
from dotenv import load_dotenv
import re
from bs4 import BeautifulSoup
import warnings
from bs4 import XMLParsedAsHTMLWarning
from dataclasses import dataclass, field

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
    resp.encoding = "utf-8"
    return resp.text

@dataclass
class ExtractionResult:
    """
    Result of attempting to extract Item 1A from a filing.

    status:
      'extracted'                 - real risk factor text found inline
      'incorporated_by_reference' - filing points to a separate exhibit
      'not_found'                 - no recognizable section at all
    """
    status: str
    text: str | None = None
    length: int = 0
    flags: list = field(default_factory=list)
    
def _detect_incorporation_by_reference(text: str) -> bool:
    item_1a_pattern = re.compile(r"item\s*1a", re.IGNORECASE)
    ref_phrases = [
        "incorporated by reference",
        "incorporated herein by reference",
        "annual report to shareholders",
        "information in response to this item",
    ]
    for m in item_1a_pattern.finditer(text):
        window = text[m.start():m.start() + 300].lower()
        if any(phrase in window for phrase in ref_phrases):
            return True
    return False

def extract_item_1a(html: str) -> ExtractionResult:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)

    # CHECK FIRST: does this filing incorporate Item 1A by reference?
    # If the Item 1A header is immediately followed by reference language,
    # the risk factors are in a separate exhibit, not this document.
    item_1a_header = re.search(r"item\s*1a\.?\s*risk\s*factors", text, re.IGNORECASE)
    if item_1a_header:
        following = text[item_1a_header.end():item_1a_header.end() + 250].lower()
        ref_phrases = [
            "incorporated by reference",
            "incorporated herein by reference",
            "can be found in this report under",
            "information in response to this item",
        ]
        if any(p in following for p in ref_phrases):
            return ExtractionResult(status="incorporated_by_reference",
                                    flags=["incorporated_by_reference"])

    header_pattern = re.compile(
        r"(item\s*1a\.?\s*)?risk\s*factors\s*[\.\:\u201d\"]?\s+(?=[A-Z])",
        re.IGNORECASE,
    )
    end_pattern = re.compile(
        r"(?:item\s*)?1b\.?\s*unresolved\s*staff\s*comments"
        r"|(?:item\s*)?1c\.?\s*cybersecurity"
        r"|(?:item\s*)?2\.?\s*properties"
        r"|(?:item\s*)?3\.?\s*legal\s*proceedings"
        r"|form\s*10-k\s*cross\s*reference\s*index",
        re.IGNORECASE,
    )

    def is_cross_reference(text, header_match):
        had_item_prefix = bool(re.match(r"item\s*1a", header_match.group(), re.IGNORECASE))
        if had_item_prefix:
            return False
        after = text[header_match.end():header_match.end() + 40].lower()
        pointer_phrases = ["section", "above", "below", "of this form", "discussed"]
        return any(p in after for p in pointer_phrases)

    def is_toc_entry(text, header_start):
        after = text[header_start:header_start + 40]
        return bool(re.match(r"\s*(item\s*1a\.?\s*)?risk\s*factors\s*\d{1,4}\s+item\s*1b",
                             after, re.IGNORECASE))

    candidates = []
    for m in header_pattern.finditer(text):
        start_idx = m.end()
        if is_cross_reference(text, m):
            continue
        if is_toc_entry(text, m.start()):
            continue
        end_match = end_pattern.search(text, start_idx)
        end_idx = end_match.start() if end_match else len(text)
        section = text[start_idx:end_idx].strip()
        if len(section) > 2000:
            candidates.append((start_idx, section))

    if candidates:
        candidates.sort(key=lambda c: c[0])
        section = candidates[0][1]
        flags = []
        length = len(section)
        if length > 300000:
            flags.append("suspiciously_long_possible_overrun")
        tail = section[-200:].lower()
        if "cross reference" in tail:
            flags.append("possible_toc_overrun_at_end")
        return ExtractionResult(status="extracted", text=section,
                                length=length, flags=flags)

    if _detect_incorporation_by_reference(text):
        return ExtractionResult(status="incorporated_by_reference",
                                flags=["incorporated_by_reference"])

    return ExtractionResult(status="not_found", flags=["no_section_found"])

ARCHIVE_URL = "https://data.sec.gov/submissions/{filename}"

async def fetch_archived_filings(client: httpx.AsyncClient, filename: str) -> list[dict]:
    """
    Fetch one archived submissions file and return its 10-K filings.
    """
    url = ARCHIVE_URL.format(filename=filename)
    resp = await client.get(url, headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()
    
    forms = data["form"]
    accession_number = data["accessionNumber"]
    filing_dates = data["filingDate"]
    primary_docs = data["primaryDocument"]
    
    results = []
    for i, form in enumerate(forms):
        if form.strip().replace("\xa0", " ") == "10-K":
            results.append({
                "accession_number": accession_number[i],
                "filed_date": filing_dates[i],
                "primary_document": primary_docs[i],
            })
    return results

async def fetch_all_10k_filings(client: httpx.AsyncClient, submissions: dict, target_count: int = 3) -> list[dict]:
    """
    Get up to target_count of the most recent 10-K filings, walking both
    the recent array and archived files as needed.

    Stops fetching archive files as soon as target_count 10-Ks are found,
    so a high-volume filer like JPM costs only a few extra requests.
    """
    tenks = extract_10k_filings(submissions)
    
    if len(tenks) >= target_count:
        return tenks[:target_count]
    
    files = submissions["filings"].get("files", [])
    for file_entry in files:
        if len(tenks) >= target_count:
            break
        
        archived = await fetch_archived_filings(client, file_entry["name"])
        await asyncio.sleep(RATE_LIMIT_DELAY)
        tenks.extend(archived)
        
    tenks.sort(key=lambda f: f["filed_date"], reverse=True)
    return tenks[:target_count]

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