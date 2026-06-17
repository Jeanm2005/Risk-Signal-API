from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Date, DateTime,
    Float, ForeignKey, func
)
from sqlalchemy.orm import relationship
from db import Base

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