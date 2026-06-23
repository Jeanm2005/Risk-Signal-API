import time
from db import SessionLocal
from models import Filing, RiskScore
from ml.scorer import score_document

def score_all_filings(model_version: str = "finbert-base"):
    """
    Score every filing that has extracted Item 1A text and isn't yet scored.
    Stores a feature vector per filing, linked to company and filing.
    """
    db = SessionLocal()
    try:
        scored_filing_ids = {
            r.filing_id for r in
            db.query(RiskScore.filing_id)
                .filter(RiskScore.model_version == model_version)
                .all()
        }
        filings = (
            db.query(Filing)
                .filter(Filing.raw_text.isnot(None))
                .all()
        )
        todo = [f for f in filings if f.id not in scored_filing_ids]
        
        print(f"Filings with text: {len(filings)}")
        print(f"Already scored: {len(scored_filing_ids)}")
        print(f"To score: {len(todo)}\n")
        
        t0 = time.time()
        for i, filing in enumerate(todo, 1):
            features = score_document(filing.raw_text)
            
            score = RiskScore(
                company_id=filing.company_id,
                filing_id=filing.id,
                risk_score=features["mean_negative"],
                confidence=features["max_negative"],
                signal_breakdown=features,
                model_version=model_version,
            )
            db.add(score)
            db.commit()
            
            elapsed = time.time() - t0
            rate = i / elapsed
            print(f"[{i:3}/{len(todo)}] filing {filing.id} "
                  f"({filing.filed_date}): "
                  f"mean_neg={features['mean_negative']:.3f} "
                  f"risk_density={features['risk_density']:.3f} "
                  f"n_sent={features['n_sentences']} "
                  f"| {rate:.1f} filings/s")

        print(f"\nDone in {time.time() - t0:.1f}s")
    finally:
        db.close()
        
if __name__ == "__main__":
    score_all_filings()