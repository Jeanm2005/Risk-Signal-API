"""Unsupervised anomaly detection over company-days."""
from datetime import timedelta
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from db import SessionLocal
from models import Company, NewsArticle, ArticleCompany, Alert

FEATURES = ["news_n", "news_neg", "neg_ratio", "abs_ret"]
FEATURE_LABELS = {"news_n": "news volume", "news_neg": "negative", "neg_ratio": "neg-news ratio", "abs_ret": "|return|"}
MIN_DAYS = 8
CONTAMINATION = 0.03
ALERT_TYPE = "news_market_anomaly"
RANDOM_STATE = 42

def load_news(db) -> pd.DataFrame:
    q = (db.query(Company.id.label("company_id"), Company.ticker, NewsArticle.published_at, NewsArticle.sentiment_score, NewsArticle.sentiment_label)
            .join(ArticleCompany, ArticleCompany.company_id == Company.id)
            .join(NewsArticle, ArticleCompany.article_id == NewsArticle.id)
            .filter(NewsArticle.published_at.isnot(None))
            .filter(NewsArticle.sentiment_score.isnot(None)))
    df = pd.DataFrame(q.all(), columns=["company_id", "ticker", "published_at", "neg", "label"])
    if not df.empty:
        d = pd.to_datetime(df["published_at"], utc=True).dt.tz_convert("America/New_York")
        df["pub_day"] = d.dt.normalize().dt.tz_localize(None)
        df["is_neg"] = (df["label"] == "negative").astype(float)
    return df

def fetch_prices(tickers, start, end) -> dict:
    import yfinance as yf
    out = {}
    for t in tickers:
        try:
            h = yf.Ticker(t.replace(".", "-")).history(start=start, end=end, auto_adjust=True)
        except Exception as e:
            print(f" ! {t}: {e}"); continue
        if h is None or h.empty or "Close" not in h:
            continue
        idx = pd.to_datetime([ts.date() for ts in h.index])
        out[t] = pd.Series([float(x) for x in h["Close"]], index=idx).sort_index()
    return out

def build_features(news: pd.DataFrame, prices: dict) -> pd.DataFrame:
    id_by_ticker = news.groupby("ticker")["company_id"].first().to_dict()
    news_by_t = {t: g for t, g in news.groupby("ticker")}
    frames = []
    for t, closes in prices.items():
        if t not in news_by_t or len(closes) < 3:
            continue
        abs_ret = np.log(closes / closes.shift(1)).abs()
        g = news_by_t[t]
        tdays = closes.index
        pos = np.searchsorted(tdays.values, g["pub_day"].values, side="left")
        keep = pos < len(tdays)
        gg = g.loc[keep].copy()
        gg["day"] = tdays.values[pos[keep]]
        agg = gg.groupby("day").agg(news_n=("neg", "size"), news_neg=("neg", "mean"), neg_ratio=("is_neg", "mean"))
        m = agg.join(abs_ret.rename("abs_ret"), how="inner").reset_index(names="day")
        m["ticker"] = t
        m["company_id"] = id_by_ticker[t]
        frames.append(m)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).dropna(subset=FEATURES)

def _zscore_within(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for f in FEATURES:
        df["z_" + f] = df.groupby("ticker")[f].transform(lambda s: (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) > 0 else s * 0.0)
    return df

def _severity(max_abs_z: float) -> str:
    if max_abs_z >= 4:
        return "high"
    if max_abs_z >= 3:
        return "medium"
    return "low"

def _explain(row) -> str:
    zs = [(f, row["z_" + f]) for f in FEATURES]
    zs.sort(key=lambda kv: abs(kv[1]), reverse=True)
    parts = [f"{FEATURE_LABELS[f]} {z:+.1f}\u03c3" for f, z in zs[:3] if abs(z) >= 1.0]
    if not parts:
        parts = [f"{FEATURE_LABELS[zs[0][0]]} {zs[0][1]:+.1f}\u03c3"]
    return (f"Unusual for {row['ticker']} on {pd.Timestamp(row['day']).date()}: " + ", ".join(parts) + f". Anomaly score {row['score']:.3f}.")

def run_detection(df: pd.DataFrame, contamination: float = CONTAMINATION) -> pd.DataFrame:
    if df.empty:
        return df
    counts = df.groupby("ticker")["day"].transform("size")
    df = df[counts >= MIN_DAYS].copy()
    if df.empty:
        return df
    df = _zscore_within(df)
    X = df[["z_" + f for f in FEATURES]].values
    
    iso = IsolationForest(n_estimators=300, contamination=contamination, random_state=RANDOM_STATE)
    df["flag"] = iso.fit_predict(X)
    df["score"] = iso.score_samples(X)
    df["max_abs_z"] = np.abs(df[["z_" + f for f in FEATURES]].values).max(axis=1)
    flagged = df[df["flag"] == -1].copy().sort_values("score")
    flagged["severity"] = flagged["max_abs_z"].map(_severity)
    flagged["explanation"] = flagged.apply(_explain, axis=1)
    return flagged

def write_alerts(db, flagged: pd.DataFrame) -> int:
    db.query(Alert).filter(Alert.alert_type == ALERT_TYPE).delete()
    objs = [Alert(company_id=int(r.company_id), triggered_at=pd.Timestamp(r.day).to_pydatetime(), alert_type=ALERT_TYPE, severity=r.severity, explanation=r.explanation, resolved=False) for r in flagged.itertuples(index=False)]
    db.add_all(objs)
    db.commit()
    written = db.query(Alert).filter(Alert.alert_type == ALERT_TYPE).count()
    if written != len(flagged):
        raise RuntimeError(f"Alert write mismatch: {written} of {len(flagged)}")
    return written

def main():
    db = SessionLocal()
    try:
        news = load_news(db)
    finally:
        db.close()
    if news.empty:
        print("No scored, dated news."); return
    lo = (news["pub_day"].min() - timedelta(days=5)).date()
    hi = (news["pub_day"].max() + timedelta(days=3)).date()
    tickers = sorted(news["ticker"].unique())
    print(f"News: {len(news)} rows, {len(tickers)} tickers, " f"{news['pub_day'].min().date()} -> {news['pub_day'].max().date()}")
    print(f"Fetching prices {lo} -> {hi} ...")
    prices = fetch_prices(tickers, lo, hi)
    print(f"Got prices for {len(prices)}/{len(tickers)} tickers")
    feats = build_features(news, prices)
    print(f"Company-days: {len(feats)} across {feats['ticker'].nunique()} tickers")
    flagged = run_detection(feats)
    if flagged.empty:
        print("No anomalies flagged."); return
    print(f"\n Flagged {len(flagged)} company_days " f"(high={sum(flagged.severity=='high')}, " f"medium={sum(flagged.severity=='medium')}, " f"low={sum(flagged.severity=='low')})")
    print("\nTop 15 anomalies:")
    for r in flagged.head(15).itertuples(index=False):
        print(f" [{r.severity:<6}] {r.explanation}")
    db = SessionLocal()
    try:
        n = write_alerts(db, flagged)
    finally:
        db.close()
    print(f"\nWrote {n} rows to alerts (alert_type='{ALERT_TYPE}').")
    flagged.drop(columns=["flag"]).to_csv("anomaly_alerts.csv", index=False)
    print("Wrote anomaly_alerts.csv")

if __name__ == "__main__":
    main()