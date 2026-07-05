import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import nltk

for _pkg in ("punkt", "punkt_tab"):
    try:
        nltk.data.find(f"tokenizers/{_pkg}")
    except LookupError:
        nltk.download(_pkg)

from nltk.tokenize import sent_tokenize

MODEL_NAME = "ProsusAI/finbert"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

if DEVICE == "cpu":
    torch.set_num_threads(6)

_tokenizer = None
_model = None

def load_model():
    """Load FinBERT once and cache it on DEVICE"""
    global _tokenizer, _model
    if _model is None:
        print(f"Loading {MODEL_NAME} on {DEVICE}...")
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        _model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
        _model.to(DEVICE)
        _model.eval()
        print(f"Loaded on {DEVICE}. Label map:", _model.config.id2label)
    return _tokenizer, _model

def split_sentences(text: str, min_length: int = 20) -> list[str]:
    """
    Split document text into sentences for scoring.
    Filters out very short fragments (headers, page numbers, list bullets)
    that carry no sentiment signal and would dilute aggregates.
    """
    if not text:
        return []
    sentences = sent_tokenize(text)
    return [s.strip() for s in sentences if len(s.strip()) >= min_length]

def score_document(text: str, batch_size: int = 64, max_sentences: int = 400) -> dict:
    """
    Score a full document.
    Splits into sentences, scores each, aggregates into distribution features.

    Returns the feature dict that feeds risk_scores and the Isolation Forest.
    """
    sentences = split_sentences(text)
    if not sentences:
        return {
            "n_sentences": 0,
            "mean_negative": None,
            "max_negative": None,
            "risk_density": None,
            "mean_neutral": None,
            "mean_positive": None,
        }
    
    capped = len(sentences) > max_sentences
    if capped:
        sentences = sentences[:max_sentences]

    scores = score_sentences(sentences, batch_size=batch_size)
    negs = [s["negative"] for s in scores]
    poss = [s["positive"] for s in scores]
    neus = [s["neutral"] for s in scores]

    # Risk density
    HIGH_NEG = 0.5
    high_neg_count = sum(1 for n in negs if n >= HIGH_NEG)

    return {
        "n_sentences": len(sentences),
        "mean_negative": sum(negs) / len(negs),
        "max_negative": max(negs),
        "risk_density": high_neg_count / len(negs),
        "mean_neutral": sum(neus) / len(neus),
        "mean_positive": sum(poss) / len(poss),
        "capped": capped,
    }

def score_sentences(sentences: list[str], batch_size: int = 64) -> list[dict]:
    """
    Score a list of texts with FinBERT. Each text is classified independently.
    Returns one dict per input text: {positive, negative, neutral}.
    """
    tokenizer, model = load_model()
    results = []

    for i in range(0, len(sentences), batch_size):
        batch = sentences[i:i + batch_size]
        inputs = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        ).to(DEVICE)
        with torch.no_grad():
            logits = model(**inputs).logits
            probs = torch.softmax(logits, dim=1)

            probs = probs.cpu()
            for row in probs:
                results.append({
                    "positive": float(row[0]),
                    "negative": float(row[1]),
                    "neutral": float(row[2]),
                })
    return results

if __name__ == "__main__":
    doc = (
        "The company faces significant liquidity risk and may default on its obligations. "
        "Our supply chain remains vulnerable to disruption from geopolitical events. "
        "We have maintained strong relationships with our key vendors. "
        "Adverse changes in interest rates could materially harm our financial position. "
        "The board met on Tuesday to review the quarterly report. "
        "Litigation risk from ongoing regulatory investigations could result in substantial penalties."
    )
    features = score_document(doc)
    print("\nDocument-level features:")
    for k, v in features.items():
        if isinstance(v, float):
            print(f" {k}: {v:.3f}")
        else:
            print(f" {k}: {v}")