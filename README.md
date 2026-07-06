# Risk Signal API
![CI](https://github.com/Jeanm2005/Risk-Signal-API/actions/workflows/ci.yml/badge.svg)

A production-style machine-learning service that ingests SEC filings and financial
news, scores them with a transformer sentiment model (FinBERT), and serves calibrated
risk scores through an authenticated C# API — with the exported model **provably
identical** to the Python original.

It **rigorously tests, and largely refutes, its own core hypothesis** (that filing risk-language
predicts stock volatility), finds where signal *actually* lives, and reports the
result honestly instead of overclaiming.

---

## TL;DR

- **Pipeline:** EDGAR + news ingestion over 500 S&P companies → GPU FinBERT scoring →
  PostgreSQL → distant-supervision volatility labels → unsupervised anomaly detection.
- **Investigation:** four independent tests of "does financial text track market risk."
  Filing risk-language (level **and** year-over-year change) shows **no** relationship
  to realized volatility. Timely **news** sentiment and volume **do** co-move with
  volatility (ρ ≈ 0.20, beta-controlled, on well-covered names).
- **Serving:** FinBERT exported to ONNX, verified to match PyTorch to **1e-6**, served
  by a C# / ASP.NET Core API with hashed API-key auth, request logging, and a
  self-verifying parity endpoint.

The headline conclusion is itself a finding: **timeliness and coverage, not model
sophistication, determine whether financial-text signal is real.**

---

## Architecture

```
 ingestion            ml (pipeline)             serving
 ─────────            ─────────────             ───────
 EDGAR filings  ┐     FinBERT scorer (GPU)      ONNX export ──► finbert.onnx
 financial news ┼──►  ├─ filings → risk_scores       │              │
 500 companies  ┘     ├─ news    → sentiment          │ parity gate  │ (1e-6)
                      ├─ volatility labels             ▼              ▼
                      └─ Isolation Forest ──► alerts   C# API: /score  (auth + logging)
                                                               /parity (self-test)
        PostgreSQL  ◄──────────── everything reads/writes here ──────────►
```

Two clearly separated Python layers: **`ml/`** is the production pipeline; **`analysis/`**
holds the one-off statistical studies that decided *what* to build.

---

## The signal investigation (the honest part)

The original premise was "risk-language in SEC filings predicts volatility." Rather than
assume it, it was tested four ways. Volatility is 30-day realized vol measured strictly
after each event, from adjusted daily prices; all correlations are Spearman and
beta-controlled by standardizing **within each company**.

| Test | What it asks | Result |
|------|--------------|--------|
| Filing risk-language **level** | Do higher-risk-language filings precede higher vol? | **Null** (ρ ≈ 0.09, ns) |
| Filing risk-language **change** | Does a YoY *rise* in risk-language precede rising vol? | **Null** (ρ ≈ 0.00) |
| **News** sentiment/volume **co-movement** | Does timely news track same-window vol? | **Positive** (within-company ρ = 0.15–0.22) |
| News **lead** | Does today's news *predict* next week's vol? | **Null** (efficient-market prior holds) |

Key numbers from the news co-movement panel (May–June 2026, ~9.5k company-days):

- **Article volume** vs same-day |return|: within-company ρ = **+0.154** (p ≈ 3e-51),
  positive for **74%** of companies.
- On the **well-covered top-50** names (median 16 articles/day): sentiment ρ = **+0.202**,
  volume ρ = **+0.220** (both p < 1e-8).
- A **coverage sweep** shows the sentiment effect more than doubling as daily article
  count rises (0.06 → 0.15), i.e. thin coverage — not a weak effect — capped the raw signal.

**Takeaway:** annual filings are too boilerplate and too pre-priced to carry
volatility signal; timely, well-covered news does. This contrast is the result.

Figures are in [`python/analysis/`](python/analysis) (`news_vol_comovement.png`,
`risk_vs_vol_scatter.png`, and the exported matrices).

---

## The serving layer

The model is trained/run in Python but served in C# — a realistic production split, and
the place where subtle bugs hide (a tokenizer that drifts by one token silently corrupts
every score). This project treats that boundary as a first-class correctness problem:

- **ONNX export** (`ml/export_onnx.py`): FinBERT wrapped to emit raw logits, exported
  FP32 with dynamic batch/sequence axes, then **gated** — inputs are run through both
  PyTorch and ONNX Runtime and the export is rejected if logits diverge. Measured max
  difference: **1.55e-6**.
- **Golden reference:** the export writes `parity_reference.json` (token ids *and*
  logits, stored separately) as the contract the C# side must reproduce.
- **C# API** (`csharp/RiskSignalApi`): ONNX Runtime + a WordPiece tokenizer that
  reproduces HuggingFace exactly. A **`/parity`** endpoint replays the golden reference
  and reports tokenizer-parity and runtime-parity *separately*, so any divergence is
  localized instantly. Result: all samples pass at ≤ 1e-6.
- **Auth & observability:** `X-API-Key` middleware validated against **SHA-256-hashed**
  keys (raw keys are never stored); every scored request is logged to `prediction_logs`
  (text hash — not raw text — label, scores, latency, backend).

### API quickstart

```bash
# 1. mint a key (stores only its SHA-256)
python -m tools.generate_api_key "my-client"

# 2. run the API
cd csharp/RiskSignalApi && dotnet run

# 3. score text
curl -X POST http://localhost:5000/score \
  -H "X-API-Key: rsk_..." -H "Content-Type: application/json" \
  -d '{"text":"Shares plunged after the company slashed guidance and disclosed an SEC probe."}'
# -> {"label":"negative","scores":{...},"riskScore":0.958,"tokenCount":15}

# 4. verify Python↔C# parity
curl http://localhost:5000/parity          # -> {"all_pass": true, ...}
```

---

## Tech stack

**Python:** PyTorch, Transformers (FinBERT), ONNX / ONNX Runtime, scikit-learn
(Isolation Forest), SQLAlchemy, pandas / scipy, yfinance.
**C# / .NET 10:** ASP.NET Core minimal API, ONNX Runtime, `Microsoft.ML.Tokenizers`, Npgsql.
**Data:** PostgreSQL. **Model:** ProsusAI/finbert. **GPU:** CUDA (RTX 50-series, cu128).

---

## Repository layout

```
python/
  ingestion/        EDGAR + news ingestion, S&P universe
  ml/               PRODUCTION pipeline: scorer, score_filings, score_news,
                    label_volatility, anomaly_detect, export_onnx
  analysis/         one-off studies: validate_signal(_change), news_vol_panel (+ figures)
  tools/            generate_api_key
  models.py db.py   SQLAlchemy schema (all tables defined in code) + engine
csharp/RiskSignalApi/
  Program.cs        endpoints + middleware wiring
  Services/         TokenizerService, ScoringService, PostgresService
  Middleware/       ApiKeyMiddleware
  Models/           DTOs
```

## Pipeline run order

```
python -m ingestion.pipeline          # ingest filings + news
python -m ml.score_filings            # FinBERT risk scores for filings
python -m ml.score_news               # FinBERT sentiment for ~33k articles
python -m ml.label_volatility         # distant-supervision vol labels
python -m ml.anomaly_detect           # Isolation Forest -> alerts
python -m ml.export_onnx              # export + parity gate + vocab.txt
# then: cd csharp/RiskSignalApi && dotnet run
```

---

## Honest limitations

- **Distant supervision.** Volatility labels are a *proxy*; both the risk score and the
  label derive from public market perception, so associations partly reflect shared
  reactions, not filing-text causation.
- **Large-cap only.** Findings are on ~500 mega-caps, which are heavily pre-priced and
  scrutinized. Signal may differ in small/mid-caps.
- **Co-movement, not prediction.** News tracks *contemporaneous* volatility; it does not
  lead it (consistent with efficient markets). No forecasting claim is made.
- **Short news window.** The news dataset spans ~2 months, dense but limited in time.

## Possible extensions

- LoRA domain-adaptation of FinBERT on Financial PhraseBank (measured F1 lift), then
  re-score news and test whether co-movement strengthens.
- Rate limiting via `api_keys.requests_per_hour`; JWT auth (schema already provisioned).
- Containerize the API (ONNX Runtime needs no CUDA/torch — the serving image is small).

---

*This project prioritizes correctness and honest evaluation over a flashy result. The
nulls are reported as prominently as the positive finding, because knowing where a
signal isn't is as valuable as knowing where it is.*
