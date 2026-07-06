import os
from datetime import timedelta
import numpy as np
import pandas as pd
from scipy import stats

 
TRADING_DAYS = 252
FWD = 5
 
 
def load_news(db) -> pd.DataFrame:
    q = (db.query(Company.ticker, NewsArticle.published_at,
                  NewsArticle.sentiment_score, NewsArticle.sentiment_label)
           .join(ArticleCompany, ArticleCompany.company_id == Company.id)
           .join(NewsArticle, ArticleCompany.article_id == NewsArticle.id)
           .filter(NewsArticle.published_at.isnot(None))
           .filter(NewsArticle.sentiment_score.isnot(None)))
    df = pd.DataFrame(q.all(), columns=["ticker", "published_at", "neg", "label"])
    if not df.empty:
        # US market TZ, normalized to the calendar day the article would first trade on
        d = pd.to_datetime(df["published_at"], utc=True).dt.tz_convert("America/New_York")
        df["pub_day"] = d.dt.normalize().dt.tz_localize(None)
        df["is_neg"] = (df["label"] == "negative").astype(float)
    return df
 
 
def fetch_prices(tickers, start, end) -> dict:
    import yfinance as yf
    out = {}
    for t in tickers:
        sym = t.replace(".", "-")
        try:
            h = yf.Ticker(sym).history(start=start, end=end, auto_adjust=True)
        except Exception as e:
            print(f"  ! {t}: {e}"); continue
        if h is None or h.empty or "Close" not in h:
            print(f"  ! {t}: no price data"); continue
        idx = pd.to_datetime([ts.date() for ts in h.index])
        out[t] = pd.Series([float(x) for x in h["Close"]], index=idx).sort_index()
    return out
 
 
def build_panel(news: pd.DataFrame, prices: dict, fwd: int = FWD) -> pd.DataFrame:
    news_by_t = {t: g for t, g in news.groupby("ticker")} if not news.empty else {}
    frames = []
    for t, closes in prices.items():
        if len(closes) < fwd + 2:
            continue
        r = np.log(closes / closes.shift(1))
        abs_ret = r.abs()
        fwd_vol = r.rolling(fwd).std().shift(-fwd) * np.sqrt(TRADING_DAYS)
 
        px = pd.DataFrame({"abs_ret": abs_ret, "fwd_vol": fwd_vol})
        px.index.name = "day"
 
        g = news_by_t.get(t)
        if g is None or g.empty:
            continue
        tdays = closes.index  # DatetimeIndex, sorted
        pos = np.searchsorted(tdays.values, g["pub_day"].values, side="left")
        keep = pos < len(tdays)
        eff = pd.Series(tdays.values[pos[keep]], name="day")
        gg = g.loc[keep].copy()
        gg["day"] = eff.values
        agg = gg.groupby("day").agg(news_n=("neg", "size"),
                                    news_neg=("neg", "mean"),
                                    neg_ratio=("is_neg", "mean"))
        m = px.join(agg, how="inner").reset_index()
        m["ticker"] = t
        frames.append(m)
 
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
 
 
def _z_within(df, col):
    return df.groupby("ticker")[col].transform(
        lambda s: (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) > 0 else s * 0.0)
 
 
def _spear(x, y):
    s = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(s) < 5 or s["x"].nunique() < 2:
        return np.nan, np.nan, len(s)
    r, p = stats.spearmanr(s["x"], s["y"])
    return r, p, len(s)
 
 
def _per_company(df, xcol, ycol):
    rhos = []
    for t, g in df.groupby("ticker"):
        r, _, n = _spear(g[xcol], g[ycol])
        if not np.isnan(r) and n >= 8:
            rhos.append(r)
    if not rhos:
        return np.nan, np.nan, 0
    rhos = np.array(rhos)
    return float(np.median(rhos)), float((rhos > 0).mean()), len(rhos)
 
 
def _block(df, xcol, ycol, title):
    r_pool, p_pool, n = _spear(df[xcol], df[ycol])
    dfz = df.copy()
    dfz["zx"] = _z_within(dfz, xcol)
    dfz["zy"] = _z_within(dfz, ycol)
    r_w, p_w, nw = _spear(dfz["zx"], dfz["zy"])
    med, frac_pos, ncomp = _per_company(df, xcol, ycol)
    print(f"\n{title}   (n={n} company-days)")
    print(f"  pooled:          spearman={r_pool:+.3f}  p={p_pool:.3g}")
    print(f"  within-company:  spearman={r_w:+.3f}  p={p_w:.3g}   (beta-controlled)")
    print(f"  per-company:     median rho={med:+.3f}, {frac_pos*100:.0f}% positive "
          f"across {ncomp} companies")
    return r_w, p_w
 
 
def analyze(panel: pd.DataFrame) -> None:
    print("=" * 78)
    print("NEWS <-> VOLATILITY  daily company panel")
    print("=" * 78)
    if panel.empty:
        print("Empty panel -- no overlap between news and price days."); return
    span = (panel["day"].min().date(), panel["day"].max().date())
    print(f"Company-days: {len(panel)} | companies: {panel['ticker'].nunique()} | "
          f"span: {span[0]} -> {span[1]}")
    print(f"Median articles per company-day: {panel['news_n'].median():.0f}")
 
    # Sentiment co-movement + lead (full panel)
    rc, pc = _block(panel, "news_neg", "abs_ret",
                    "[CO-MOVEMENT: sentiment] news negativity vs same-day |return|")
    # Volume co-movement: article COUNT vs |return|. Needs the full panel (the
    # quiet-day vs busy-day contrast IS the signal), so it is not coverage-filtered.
    rv, pv = _block(panel, "news_n", "abs_ret",
                    "[CO-MOVEMENT: volume] article count vs same-day |return|")
    rl, pl = _block(panel.dropna(subset=["fwd_vol"]), "news_neg", "fwd_vol",
                    "[LEAD: sentiment] news negativity vs next-5-day realized vol")
    _block(panel.dropna(subset=["fwd_vol"]), "news_n", "fwd_vol",
           "[LEAD: volume] article count vs next-5-day realized vol")
 
    # Coverage sweep: sentiment needs enough articles/day to be a stable mean.
    # If thin coverage is diluting it, within-company rho should RISE with threshold.
    print("\n[COVERAGE SWEEP] within-company sentiment co-movement vs min articles/day")
    print(f"  {'min/day':>7} {'co-days':>8} {'companies':>9} {'sent_rho':>9} {'p':>10}")
    for thr in (1, 3, 5, 10, 20):
        sub = panel[panel["news_n"] >= thr]
        if len(sub) < 30 or sub["ticker"].nunique() < 5:
            print(f"  {thr:>7} {len(sub):>8}   (too few to test)"); continue
        s = sub.copy()
        s["zx"] = _z_within(s, "news_neg"); s["zy"] = _z_within(s, "abs_ret")
        r, p, _ = _spear(s["zx"], s["zy"])
        print(f"  {thr:>7} {len(sub):>8} {sub['ticker'].nunique():>9} {r:>9.3f} {p:>10.2g}")
 
    # Well-covered subset: the ~50 tickers with the most articles (mega-cap-like).
    counts = panel.groupby("ticker")["news_n"].sum().sort_values(ascending=False)
    top = counts.head(50).index
    wc = panel[panel["ticker"].isin(top)]
    print(f"\n[WELL-COVERED SUBSET] top {len(top)} tickers by article volume "
          f"(median {wc['news_n'].median():.0f} articles/day)")
    _block(wc, "news_neg", "abs_ret", "  sentiment vs |return|")
    _block(wc, "news_n", "abs_ret", "  volume vs |return|")
 
    print("\n" + "-" * 78)
    print("READ THIS:")
    print(f"  sentiment co-movement (within-co): {rc:+.3f} (p={pc:.3g})")
    print(f"  volume    co-movement (within-co): {rv:+.3f} (p={pv:.3g})")
    print(f"  lead      (within-co):             {rl:+.3f} (p={pl:.3g})")
    if not np.isnan(rv) and pv < 0.05 and rv > 0 and (np.isnan(rc) or rv > rc):
        print("  Volume is the stronger co-movement signal -- article count tracks vol")
        print("  better than sentiment does. Lead with volume, keep sentiment alongside.")
    if not np.isnan(rc) and pc < 0.05 and rc > 0:
        print("  Sentiment co-moves with realized volatility within each company. The")
        print("  signal is NOT empty -- it tracks the market. Check the sweep: if rho")
        print("  rises with coverage, thin data (not a weak effect) capped the headline.")
        if not np.isnan(rl) and pl < 0.05 and rl > 0:
            print("  Bonus: it also LEADS next-week vol -- a predictive claim worth testing")
            print("  further (add controls, lagged vol) before leaning on it.")
        else:
            print("  Lead effect is weak/absent -- expected under efficient markets. Frame")
            print("  the result as contemporaneous tracking, not prediction.")
    else:
        print("  Even properly aligned, co-movement is weak. That would be surprising;")
        print("  check article->company mapping density and per-company article counts.")
    print("-" * 78)
 
 
def save_plot(panel, outdir="."):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    d = panel.copy()
    d["zneg"] = _z_within(d, "news_neg")
    d["zvol"] = _z_within(d, "abs_ret")
    d = d.dropna(subset=["zneg", "zvol"])
    # bin z-news into deciles, plot mean z-vol -> shows monotone co-movement cleanly
    d["bin"] = pd.qcut(d["zneg"], 10, duplicates="drop")
    b = d.groupby("bin", observed=True).agg(x=("zneg", "mean"), y=("zvol", "mean"))
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(b["x"], b["y"], "o-")
    ax.axhline(0, color="gray", lw=0.6); ax.axvline(0, color="gray", lw=0.6)
    ax.set_xlabel("news negativity (within-company z)")
    ax.set_ylabel("|return| (within-company z)")
    ax.set_title("News negativity vs volatility (decile-binned, beta-controlled)")
    p = os.path.join(outdir, "news_vol_comovement.png")
    fig.tight_layout(); fig.savefig(p, dpi=120)
    return p
 
 
def main():
    from models import Company, NewsArticle, ArticleCompany
    from db import SessionLocal
    db = SessionLocal()
    try:
        news = load_news(db)
    finally:
        db.close()
    if news.empty:
        print("No dated, scored news found."); return
    lo = (news["pub_day"].min() - timedelta(days=5)).date()
    hi = (news["pub_day"].max() + timedelta(days=FWD + 5)).date()
    tickers = sorted(news["ticker"].unique())
    print(f"News: {len(news)} article-company rows, {len(tickers)} tickers, "
          f"{news['pub_day'].min().date()} -> {news['pub_day'].max().date()}")
    print(f"Fetching prices {lo} -> {hi} ...")
    prices = fetch_prices(tickers, lo, hi)
    print(f"Got prices for {len(prices)}/{len(tickers)} tickers")
    panel = build_panel(news, prices)
    analyze(panel)
    if not panel.empty:
        panel.to_csv("news_vol_panel.csv", index=False)
        print(f"\nWrote news_vol_panel.csv and plot: {save_plot(panel)}")
 
 
if __name__ == "__main__":
    main()
 