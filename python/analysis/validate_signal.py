import os
import numpy as np
import pandas as pd
from scipy import stats
from db import SessionLocal
from models import Filing, RiskScore, FilingLabel, Company

BASELINE_VERSION = "finbert-base"
RISK_FEATURES = ["mean_negative", "max_negative", "risk_density",
                 "mean_neutral", "mean_positive"]
BUCKET_ORDER = ["low", "medium", "high"]
LOW_SENTENCE_FLOOR = 50   # filings with fewer scored sentences are low-confidence


# Data loading (DB)
def load_dataset(db) -> pd.DataFrame:
    """Filing-level join: baseline risk features + volatility label + sector."""
    q = (
        db.query(RiskScore, FilingLabel, Filing.filed_date, Company.ticker, Company.sector)
          .join(Filing, RiskScore.filing_id == Filing.id)
          .join(FilingLabel, FilingLabel.filing_id == Filing.id)
          .join(Company, RiskScore.company_id == Company.id)
          .filter(RiskScore.model_version == BASELINE_VERSION)
          .filter(FilingLabel.realized_vol.isnot(None))
    )
    rows = []
    for rs, lbl, filed_date, ticker, sector in q.all():
        feat = rs.signal_breakdown or {}
        rows.append({
            "filing_id": rs.filing_id,
            "ticker": ticker,
            "sector": sector or "Unknown",
            "filed_date": filed_date,
            "realized_vol": lbl.realized_vol,
            "vol_label": lbl.vol_label,
            "n_sentences": feat.get("n_sentences"),
            "mean_negative": feat.get("mean_negative"),
            "max_negative": feat.get("max_negative"),
            "risk_density": feat.get("risk_density"),
            "mean_neutral": feat.get("mean_neutral"),
            "mean_positive": feat.get("mean_positive"),
        })
    return pd.DataFrame(rows)

# Analysis (pure pandas/scipy) -- this is the testable core
def _spearman(df, feature, target="realized_vol"):
    sub = df[[feature, target]].dropna()
    if len(sub) < 5 or sub[feature].nunique() < 2:
        return np.nan, np.nan, len(sub)
    rho, p = stats.spearmanr(sub[feature], sub[target])
    return rho, p, len(sub)


def _kruskal(df, feature, group="vol_label"):
    groups = [df.loc[df[group] == b, feature].dropna().values for b in BUCKET_ORDER]
    groups = [g for g in groups if len(g) > 0]
    if len(groups) < 2:
        return np.nan, np.nan
    h, p = stats.kruskal(*groups)
    return h, p


def _bucket_means(df, feature):
    m = df.groupby("vol_label")[feature].mean()
    return {b: m.get(b, np.nan) for b in BUCKET_ORDER}


def _print_correlation_block(df, title):
    print(f"\n{title}  (n={len(df)}, companies={df['ticker'].nunique()})")
    print(f"  {'feature':<14} {'low':>8} {'med':>8} {'high':>8}   "
          f"{'spearman':>9} {'p':>8}   {'kruskalH':>9} {'p':>8}")
    for f in RISK_FEATURES:
        b = _bucket_means(df, f)
        rho, sp, _ = _spearman(df, f)
        h, kp = _kruskal(df, f)
        trend = "  UP" if b["high"] > b["low"] else "DOWN"
        print(f"  {f:<14} {b['low']:>8.3f} {b['medium']:>8.3f} {b['high']:>8.3f}   "
              f"{rho:>9.3f} {sp:>8.3f}   {h:>9.2f} {kp:>8.3f} {trend}")


def analyze(df: pd.DataFrame) -> None:
    if df.empty:
        print("No rows to analyze -- check that finbert-base scores and labels both exist.")
        return

    print("=" * 78)
    print("BASELINE SIGNAL VALIDATION  (finbert-base risk features vs realized vol)")
    print("=" * 78)
    print(f"Filings: {len(df)} | companies: {df['ticker'].nunique()} | "
          f"sectors: {df['sector'].nunique()}")
    low_n = int((df['n_sentences'].fillna(0) < LOW_SENTENCE_FLOOR).sum())
    print(f"Low-confidence filings (<{LOW_SENTENCE_FLOOR} sentences): {low_n}")

    # 1) Headline: full sample, filing-level
    _print_correlation_block(df, "[1] All filings, filing-level")

    # 2) Drop low-sentence filings
    clean = df[df['n_sentences'].fillna(0) >= LOW_SENTENCE_FLOOR]
    if len(clean) < len(df):
        _print_correlation_block(clean, "[2] Excluding low-confidence filings")

    # 3) Sector confounder
    print("\n[3] Sector view  (mean risk-language vs mean realized vol)")
    sec = (df.groupby("sector")
             .agg(n=("filing_id", "size"),
                  mean_neg=("mean_negative", "mean"),
                  mean_vol=("realized_vol", "mean"))
             .sort_values("mean_neg", ascending=False))
    print(f"  {'sector':<26} {'n':>4} {'mean_neg':>9} {'mean_vol':>9}")
    for s, r in sec.iterrows():
        print(f"  {s:<26} {int(r['n']):>4} {r['mean_neg']:>9.3f} {r['mean_vol']:>9.3f}")

    # 4) Remove financials -- does any signal survive the confounder?
    fin_mask = df['sector'].str.contains("Financ", case=False, na=False)
    if fin_mask.any():
        _print_correlation_block(df[~fin_mask], "[4] Financials excluded")

    # 5) Company-averaged (kills pseudoreplication from 3 filings/company)
    comp = (df.groupby("ticker")
              .agg(sector=("sector", "first"),
                   realized_vol=("realized_vol", "mean"),
                   **{f: (f, "mean") for f in RISK_FEATURES})
              .reset_index())
    rho, p, n = _spearman(comp, "mean_negative")
    print(f"\n[5] Company-averaged: mean_negative vs mean realized_vol  "
          f"(n={n} companies): spearman={rho:.3f}, p={p:.3f}")

    # Verdict cue
    rho_all, p_all, _ = _spearman(df, "mean_negative")
    if fin_mask.any():
        rho_nofin, _, _ = _spearman(df[~fin_mask], "mean_negative")
        nofin_str = f"{rho_nofin:+.3f}"
    else:
        rho_nofin, nofin_str = np.nan, "n/a (no financials in sample)"
    print("\n" + "-" * 78)
    print("READ THIS:")
    print(f"  mean_negative vs vol  ->  all: {rho_all:+.3f}   ex-financials: {nofin_str}")
    if np.isnan(rho_all) or abs(rho_all) < 0.15:
        print("  Weak/no monotonic relationship. FinBERT risk-language may not track")
        print("  realized volatility. Fine-tuning to raise scores won't fix a signal")
        print("  that doesn't correlate -- investigate WHY before tuning.")
    elif rho_all < 0:
        print("  NEGATIVE: higher risk-language -> LOWER vol. Almost certainly the")
        print("  sector effect (verbose financials are low-vol). Check [3]/[4]: if the")
        print("  sign flips or vanishes ex-financials, the raw signal is a sector proxy.")
    else:
        print("  Positive relationship present. Confirm it survives [4] ex-financials")
        print("  and [5] company-averaging before calling it real predictive signal.")
    print("-" * 78)


def save_plots(df: pd.DataFrame, outdir: str = ".") -> list:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    paths = []
    # Box: mean_negative by vol bucket
    fig, ax = plt.subplots(figsize=(6, 4))
    data = [df.loc[df.vol_label == b, "mean_negative"].dropna() for b in BUCKET_ORDER]
    ax.boxplot(data)
    ax.set_xticks(range(1, len(BUCKET_ORDER) + 1))
    ax.set_xticklabels(BUCKET_ORDER)
    ax.set_xlabel("realized-vol bucket"); ax.set_ylabel("mean_negative (finbert-base)")
    ax.set_title("Risk-language by volatility bucket")
    p1 = os.path.join(outdir, "risk_by_vol_bucket.png"); fig.tight_layout(); fig.savefig(p1, dpi=120)
    paths.append(p1)

    # Scatter: risk vs vol, colored by financial/other
    fig, ax = plt.subplots(figsize=(6, 4))
    fin = df['sector'].str.contains("Financ", case=False, na=False)
    ax.scatter(df.loc[~fin, "mean_negative"], df.loc[~fin, "realized_vol"],
               s=18, alpha=0.6, label="other")
    ax.scatter(df.loc[fin, "mean_negative"], df.loc[fin, "realized_vol"],
               s=18, alpha=0.8, label="financials")
    ax.set_xlabel("mean_negative"); ax.set_ylabel("realized_vol (annualized)")
    ax.set_title("Risk-language vs realized volatility"); ax.legend()
    p2 = os.path.join(outdir, "risk_vs_vol_scatter.png"); fig.tight_layout(); fig.savefig(p2, dpi=120)
    paths.append(p2)
    return paths


def main():
    db = SessionLocal()
    try:
        df = load_dataset(db)
    finally:
        db.close()
    analyze(df)
    if not df.empty:
        df.to_csv("signal_validation_matrix.csv", index=False)
        plots = save_plots(df)
        print(f"\nWrote signal_validation_matrix.csv and plots: {', '.join(plots)}")


if __name__ == "__main__":
    main()