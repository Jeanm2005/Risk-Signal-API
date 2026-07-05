from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Date, DateTime,
    Float, ForeignKey, func
)
from sqlalchemy.orm import relationship
from db import Base
from sqlalchemy.dialects.postgresql import JSONB

class Company(Base):
    __tablename__ = "companies"
    
    id = Column(Integer, primary_key=True)
    ticker = Column(String(10), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    cik = Column(String(10), unique=True, nullable=False)
    sector = Column(String(100))
    sic_code = Column(String(10))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    filings = relationship("Filing", back_populates="company")
    
class Filing(Base):
    __tablename__ = "filings"
    
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"))
    accession_number = Column(String(25), unique=True, nullable=False)
    form_type = Column(String(10), nullable=False)
    filed_date = Column(Date, nullable=False)
    fiscal_year_end = Column(Date)
    raw_text = Column(Text)
    processed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    company = relationship("Company", back_populates="filings")
    
class NewsArticle(Base):
    __tablename__ = "news_articles"
    
    id = Column(Integer, primary_key=True)
    url = Column(Text, unique=True, nullable=False)
    headline = Column(Text, nullable=False)
    body = Column(Text)
    source = Column(String(100))
    published_at = Column(DateTime(timezone=True))
    sentiment_label = Column(String(20))
    sentiment_score = Column(Float)
    processed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company_links = relationship("ArticleCompany", back_populates="article")
    
class ArticleCompany(Base):
    __tablename__ = "article_companies"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("news_articles.id", ondelete="CASCADE"))
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    article = relationship("NewsArticle", back_populates="company_links")
    company = relationship("Company")
    
class RiskScore(Base):
    __tablename__ = "risk_scores"
    
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"))
    scored_at = Column(DateTime(timezone=True), server_default=func.now())
    risk_score = Column(Float, nullable=False)
    confidence = Column(Float)
    signal_breakdown = Column(JSONB)
    model_version = Column(String(50))
    company = relationship("Company")
    filing_id = Column(Integer, ForeignKey("filings.id", ondelete="CASCADE"))

class FilingLabel(Base):
    __tablename__ = "filing_labels"

    id = Column(Integer, primary_key=True)
    filing_id = Column(Integer, ForeignKey("filings.id", ondelete="CASCADE"), unique=True,  nullable=False)
    realized_vol = Column(Float)          # annualized; NULL if not computable  
    vol_label = Column(String(10))        # 'low' / 'medium' / 'high'; NULL if no vol
    window_start = Column(Date)           # first trading day used (t+1)
    window_end = Column(Date)             # filed_date + 30 calendar days
    n_returns = Column(Integer)           # daily returns actually used
    price_source = Column(String(20))     # 'yfinance'
    tercile_low = Column(Float)           # 1/3 quantile at labeling time (provenance)
    tercile_high = Column(Float)          # 2/3 quantile at labeling time (provenance)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
 
    filing = relationship("Filing")

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"))
    triggered_at = Column(DateTime(timezone=True), server_default=func.now())
    alert_type = Column(String(50))
    severity = Column(String(20))
    explanation = Column(Text)
    resolved = Column(Boolean, default=False)
    company = relationship("Company")