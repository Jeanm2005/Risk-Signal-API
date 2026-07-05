import os
import numpy as np
import pandas as pd
from scipy import stats
from db import SessionLocal
from models import Filing, RiskScore, FilingLabel, Company

BASELINE_VERSION = "finbert-base"
DELTA_FEATURES = ["d_mean_negative", "d_risk_density", "d_n_sentences"]

def load_perfiling(db) -> pd.DataFrame:
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
        f = rs.signal_breakdown or {}
        rows.append({
            "ticker": ticker, "sector": sector or "Unknown", "filed_date": filed_date,
            "realized_vol": lbl.realized_vol, "vol_label": lbl.vol_label,
            "mean_negative": f.get("mean_negative"), "risk_density": f.get("risk_density"),
            "n_sentences": f.get("n_sentences"),
        })
    return pd.DataFrame(rows)

def build_changes(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["ticker", "filed_date"]).copy()
    g = df.groupby("ticker", sort=False)
    df["d_mean_negative"] = g["mean_negative"].diff()
    df["d_risk_density"] = g["risk_density"].diff()
    df["d_n_sentences"] = g["n_sentences"].diff()
    df["d_realized_vol"] = g["realized_vol"].diff()
    df["prev_filed"] = g["filed_date"].shift()
    df["gap_days"] = (pd.to_datetime(df["filed_date"]) - pd.to_datetime(df["prev_filed"])).dt.days
    return df.dropna(subset=["d_mean_negative", "d_realized_vol"]).reset_index(drop=True)

def _spear(x, y):
    s = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(s) < 5 or s["x"].nunique() < 2:
        return np.nan, np.nan, len(s)
    r, p = stats.spearmanr(s["x"], s["y"])
    return r, p, len(s)

def analyze_change(ch: pd.DataFrame) -> None:
    print("=" * 78)
    print("CHANGE_LAYER VALIDATION (YoY change in risk language vs volatility)")
    print("=" * 78)
    if ch.empty:
        print("No paired filings -- need >=2 filings per company.")
        return
    
    gap = ch["gap_days"].dropna()
    off = int(((gap < 200) | (gap > 500)).sum())
    print(f"Delta observations: {len(ch)} | companies: {ch['ticker'].nunique()} | " f"median gap: {gap.median():.0f}d | off-cycle pairs (<200 or >500d): {off}")

    # Headline table: each delta-feature vs vol level AND vs delta-vol
    print(f"\n  {'delta-feature':<16} {'vs vol level':>22}   {'vs delta-vol (within-co)':>26}")
    print(f"  {'':<16} {'spearman':>10} {'p':>10}   {'spearman':>12} {'p':>12}")
    for f in DELTA_FEATURES:
        r1, p1, _ = _spear(ch[f], ch["realized_vol"])
        r2, p2, _ = _spear(ch[f], ch["d_realized_vol"])
        print(f"  {f:<16} {r1:>10.3f} {p1:>10.3f}   {r2:>12.3f} {p2:>12.3f}")

    # Interpretable cut
    up = ch[ch["d_mean_negative"] > 0]
    dn = ch[ch["d_mean_negative"] <= 0]
    print(f"\n  Risk-language ROSE YoY:  n={len(up):>3}  "
          f"median subsequent vol={up['realized_vol'].median():.3f}  "
          f"median delta-vol={up['d_realized_vol'].median():+.3f}")
    print(f"  Risk-language FELL YoY:  n={len(dn):>3}  "
          f"median subsequent vol={dn['realized_vol'].median():.3f}  "
          f"median delta-vol={dn['d_realized_vol'].median():+.3f}")
    if len(up) >= 5 and len(dn) >= 5:
        u, pu = stats.mannwhitneyu(up["realized_vol"].dropna(),
                                   dn["realized_vol"].dropna(), alternative="two-sided")
        ud, pud = stats.mannwhitneyu(up["d_realized_vol"].dropna(),
                                     dn["d_realized_vol"].dropna(), alternative="two-sided")
        print(f"  Mann-Whitney U  vol level: p={pu:.3f}   delta-vol: p={pud:.3f}")
 
    # Verdict
    r_dd, p_dd, n_dd = _spear(ch["d_mean_negative"], ch["d_realized_vol"])
    print("\n" + "-" * 78)
    print("READ THIS:")
    print(f"  delta_mean_negative vs delta_vol (the key test): "
          f"spearman={r_dd:+.3f}, p={p_dd:.3f}, n={n_dd}")
    if np.isnan(r_dd) or p_dd > 0.10:
        print("  No within-company change signal either. Combined with the null level")
        print("  result, this is a robust negative: 10-K risk language -- level OR")
        print("  change -- does not track this volatility proxy. Time to reframe, not tune.")
    elif r_dd > 0:
        print("  Positive within-company change signal. Rising risk language tracks")
        print("  rising vol even after differencing out company baseline. THIS is the")
        print("  feature to build on -- and a real reason fine-tuning could add value.")
    else:
        print("  Negative change relationship -- unexpected; inspect before trusting.")
    print("-" * 78)

def save_plot(ch: pd.DataFrame, outdir: str = ".") -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.axhline(0, color="gray", lw=0.7); ax.axvline(0, color="gray", lw=0.7)
    ax.scatter(ch["d_mean_negative"], ch["d_realized_vol"], s=20, alpha=0.6)
    ax.set_xlabel("delta mean_negative (YoY)"); ax.set_ylabel("delta realized_vol (YoY)")
    ax.set_title("Change in risk language vs change in volatility")
    p = os.path.join(outdir, "change_risk_vs_change_vol.png")
    fig.tight_layout(); fig.savefig(p, dpi=120)
    return p

def main():
    db = SessionLocal()
    try:
        per = load_perfiling(db)
    finally:
        db.close()
    ch = build_changes(per)
    analyze_change(ch)
    if not ch.empty:
        ch.to_csv("signal_change_matrix.csv", index=False)
        print(f"\nWrote signal_change_matrix.csv and plot: {save_plot(ch)}")

if __name__ == "__main__":
    main()