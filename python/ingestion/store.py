from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from datetime import datetime
from models import Company, Filing, NewsArticle

def upsert_company(db: Session, ticker: str, name: str, cik: str, sector: str = None, sic_code: str = None) -> int:
    """
    Insert a company, or update name/sector if it already exists.
    Returns the company's id. Idempotent: safe to run repeatedly.
    """
    stmt = insert(Company).values(
        ticker=ticker, name=name, cik=cik,
        sector=sector, sic_code=sic_code
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["cik"],
        set_={"name": name, "sector": sector, "sic_code": sic_code},
    ).returning(Company.id)
    
    result = db.execute(stmt)
    db.commit()
    return result.scalar_one()

def upsert_filing(db: Session, company_id: int, accession_number: str, form_type: str, filed_date: str, raw_text: str = None) -> int:
    """
    Insert a filing, or update its text if re-fetched.
    Idempotent on the unique 'accession_number'.
    """
    filed = datetime.strptime(filed_date, "%Y-%m-%d").date()
    
    stmt = insert(Filing).values(
        company_id=company_id,
        accession_number=accession_number,
        form_type=form_type,
        filed_date=filed,
        raw_text=raw_text,
        processed=False,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["accession_number"],
        set_={"raw_text": raw_text},
    ).returning(Filing.id)
    
    result = db.execute(stmt)
    db.commit()
    return result.scalar_one()

def upsert_news_article(db: Session, company_id: int, headline: str, url: str,
                        body: str = None, published_at=None, source: str = None,
                        av_relevance: float = None,
                        av_sentiment_score: str = None,
                        av_sentiment_label: str = None) -> int:
    """
    Insert a news article, deduplicating on the unique 'url'.
    Idempotent: re-running updates AV metadata but won't duplicate.
    """
    stmt = insert(NewsArticle).values(
        company_id=company_id,
        headline=headline,
        url=url,
        body=body,
        published_at=published_at,
        source=source,
        av_relevance=av_relevance,
        av_sentiment_score=av_sentiment_score,
        av_sentiment_label=av_sentiment_label,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["url"],
        set_={
            "av_relevance": av_relevance,
            "av_sentiment_score": av_sentiment_score,
            "av_sentiment_label": av_sentiment_label,
        },
    ).returning(NewsArticle.id)
    
    result = db.execute(stmt)
    db.commit()
    return result.scalar_one()