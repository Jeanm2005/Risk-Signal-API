import time
from db import SessionLocal
from models import NewsArticle
from ml.scorer import score_sentences

LABELS = ("positive", "negative", "neutral") # FinBERT id2label order: 0=pos, 1=neg, 2=neu

def _article_text(article: NewsArticle) -> str:
    """Headline + summary, joined. body (summary) may be NULL."""
    headline = (article.headline or "").strip()
    body = (article.body or "").strip()
    if not body:
        return headline
    return f"{headline}. {body}"

def score_all_news(batch_size: int = 128, chunk_size: int = 2000) -> None:
    """Score every unprocessed news article with base FinBERT"""
    db = SessionLocal()
    try:
        total = db.query(NewsArticle).filter(NewsArticle.processed.is_(False)).count()
        print(f"Unscored articles: {total}")
        if total == 0:
            print("Nothing to do.")
            return
        
        done = 0
        t0 = time.time()
        while True:
            chunk = (
                db.query(NewsArticle)
                    .filter(NewsArticle.processed.is_(False))
                    .order_by(NewsArticle.id)
                    .limit(chunk_size)
                    .all()
            )
            if not chunk:
                break

            texts = [_article_text(a) for a in chunk]
            scores = score_sentences(texts, batch_size=batch_size)

            for article, s in zip(chunk, scores):
                probs = (s["positive"], s["negative"], s["neutral"])
                article.sentiment_label = LABELS[probs.index(max(probs))]
                article.sentiment_score = s["negative"]
                article.processed = True

            db.commit()

            done += len(chunk)
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed else 0.0
            remaining = (total - done) / rate if rate else 0.0
            print(f"[{done}/{total} {rate:.0f} article/s (~{remaining:.0f}s left)]")

        print(f"\nDone {done} articles in {time.time() - t0:.1f}s")

    finally:
        db.close()

if __name__ == "__main__":
    score_all_news()