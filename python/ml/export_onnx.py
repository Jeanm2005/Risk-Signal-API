"""
Export FinBERT to ONNX and PROVE the export is correct before any C# is written.
 
Pipeline:
  1. Wrap the HF model so the graph emits a single clean output: raw logits
     (no softmax in the graph -- softmax is applied in app code on both sides).
  2. Export FP32 with dynamic batch and sequence axes (opset 17), so the served
     model accepts any batch size and text length.
  3. PARITY GATE: run identical inputs through PyTorch and ONNX Runtime; abort if
     max logit difference exceeds tolerance. A wrong export is worthless, and it is
     far cheaper to catch here than across the C# boundary.
  4. Write parity_reference.json -- the golden contract the C# side must reproduce.
     Token ids and logits are stored SEPARATELY so a future C# mismatch can be
     localized: same ids but wrong logits => runtime bug; wrong ids => tokenizer bug.
 
MLOps:
  Every export is logged as an MLflow run under the 'finbert-onnx-export' experiment:
  params (model, opset, tolerance...), metrics (the parity delta, class agreement,
  pass/fail, model size), and artifacts (the .onnx, the golden reference, the
  tokenizer). A FAILED parity run is still logged -- you want the failures on the
  record, not silently discarded -- and then the process exits non-zero. This makes
  the parity gate an auditable, comparable validation step rather than a one-off print.
 
Outputs (into --out, default ./artifacts):
  finbert.onnx              the model
  tokenizer/                vocab.txt etc. for the C# tokenizer to load
  parity_reference.json     texts -> {input_ids, attention_mask, token_type_ids,
                                      logits, probs}
"""
import argparse
import json
import os
import numpy as np
import torch
import mlflow

MODEL_NAME = "ProsusAI/finbert"
OPSET = 17
MAX_LEN = 512
TOLERANCE = 1e-3

SAMPLES = [
    "The company reported record quarterly revenue and raised its full-year guidance.",
    "Shares collapsed after the firm disclosed an SEC probe and suspended its dividend.",
    "The board of directors will convene on Thursday to review the quarterly report.",
    "Rising input costs and weak demand pressured margins, and management withdrew guidance.",
    "The acquisition closed on schedule and is expected to be modestly accretive next year.",
    "Despite a challenging macro backdrop, the bank maintained strong capital ratios and "
    "grew net interest income, though it flagged elevated credit risk in commercial real estate.",
]

class LogitsOnly(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, input_ids, attention_mask, token_type_ids):
        return self.model(input_ids=input_ids, attention_mask=attention_mask, token_type_ids=token_type_ids).logits
    
def export_model(wrapper, dummy, onnx_path, opset=OPSET):
    dynamic_axes = {
        "input_ids": {0: "batch", 1: "seq"},
        "attention_mask": {0: "batch", 1: "seq"},
        "token_type_ids": {0: "batch", 1: "seq"},
        "logits": {0: "batch"},
    }
    torch.onnx.export(
        wrapper, dummy, onnx_path,
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["logits"],
        dynamic_axes=dynamic_axes,
        opset_version=opset,
        do_constant_folding=True,
        dynamo=False,
    )

def run_parity(model, feeds, onnx_path):
    import onnxruntime as ort
    with torch.no_grad():
        pt = model(input_ids=torch.tensor(feeds["input_ids"]),
                   attention_mask=torch.tensor(feeds["attention_mask"]),
                   token_type_ids=torch.tensor(feeds["token_type_ids"])).logits.numpy()
        sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        ortl = sess.run(["logits"], feeds)[0]
        return pt, ortl, float(np.abs(pt - ortl).max())
    
def _softmax(x):
    e = np.exp(x - np.max(x))
    return e / e.sum()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MODEL_NAME)
    ap.add_argument("--out", default="artifacts")
    ap.add_argument("--opset", type=int, default=OPSET)
    ap.add_argument("--mlflow-uri", default="sqlite:///mlflow.db", help="MLflow tracking URI. SQLite by default -- the file store is deprecated in MLflow 3.x and a DB backend is required for the model registry.")
    ap.add_argument("--experiment", default="finbert-onnx-export", help="MLflow experiment name")
    args = ap.parse_args()

    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    os.makedirs(args.out, exist_ok=True)
    onnx_path = os.path.join(args.out, "finbert.onnx")
    tok_dir = os.path.join(args.out, "tokenizer")
    
    mlflow.set_tracking_uri(args.mlflow_uri)
    mlflow.set_experiment(args.experiment)

    with mlflow.start_run(run_name=f"export-opset{args.opset}") as run:
        mlflow.log_params({
            "model": args.model,
            "opset": args.opset,
            "max_length": MAX_LEN,
            "tolerance": TOLERANCE,
            "num_parity_samples": len(SAMPLES),
            "precision": "fp32",
        })

        print(f"Loading {args.model} ...")
        tok = AutoTokenizer.from_pretrained(args.model)
        model = AutoModelForSequenceClassification.from_pretrained(args.model).eval()
        id2label = {int(k): v for k, v in model.config.id2label.items()}
        print(f"Labels: {id2label}")
        mlflow.set_tag("labels", json.dumps(id2label))

        wrapper = LogitsOnly(model).eval()
        enc = tok(SAMPLES[0], return_tensors="pt", truncation=True, max_length=MAX_LEN)
        dummy = (enc["input_ids"], enc["attention_mask"], enc["token_type_ids"])
        print(f"Exporting -> {onnx_path} (opset {args.opset}, dynamic batch+seq) ...")
        export_model(wrapper, dummy, onnx_path, opset=args.opset)
        tok.save_pretrained(tok_dir)
        _vocab = sorted(tok.get_vocab().items(), key=lambda kv: kv[1])
        with open(os.path.join(tok_dir, "vocab.txt"), "w", encoding="utf-8") as _f:
            _f.write("\n".join(t for t, _ in _vocab))

        onnx_size_mb = os.path.getsize(onnx_path) / (1024 * 1024)
        mlflow.log_metric("onnx_size_mb", round(onnx_size_mb, 2))

        # Parity Gate
        batch = tok(SAMPLES, padding=True, truncation=True, max_length=MAX_LEN, return_tensors="np")
        feeds = {k: batch[k] for k in ("input_ids", "attention_mask", "token_type_ids")}
        pt, ortl, max_diff = run_parity(model, feeds, onnx_path)
        agree = bool((pt.argmax(1) == ortl.argmax(1)).all())
        passed = (max_diff <= TOLERANCE) and agree
        print(f"\nParity (batched): max |PyTorch - ONNX| logit diff = {max_diff:.2e} "
              f"(tolerance {TOLERANCE:.0e})")
        print(f"Predicted-class agreement: {'ALL MATCH' if agree else 'MISMATCH'}")
 
        # Metrics: the parity gate's outcome, logged whether it passes or fails.
        mlflow.log_metric("batched_max_logit_diff", max_diff)
        mlflow.log_metric("predicted_class_agreement", int(agree))
        mlflow.log_metric("parity_passed", int(passed))
        mlflow.set_tag("parity", "passed" if passed else "FAILED")

        # Golden Reference
        samples_out = []
        for text in SAMPLES:
            e = tok(text, truncation=True, max_length=MAX_LEN, return_tensors="np")
            with torch.no_grad():
                logits = model(input_ids=torch.tensor(e["input_ids"]),
                               attention_mask=torch.tensor(e["attention_mask"]),
                               token_type_ids=torch.tensor(e["token_type_ids"])).logits.numpy()[0]
                probs = _softmax(logits)
                samples_out.append({
                    "text": text,
                "input_ids": e["input_ids"][0].tolist(),
                "attention_mask": e["attention_mask"][0].tolist(),
                "token_type_ids": e["token_type_ids"][0].tolist(),
                "logits": [round(float(x), 6) for x in logits],
                "probs": {id2label[i]: round(float(p), 6) for i, p in enumerate(probs)},
                })

        ref_path = os.path.join(args.out, "parity_reference.json")
        with open(ref_path, "w") as f:
            json.dump({
                "model": args.model,
                "opset": args.opset,
                "max_length": MAX_LEN,
                "id2label": id2label,
                "tolerance": TOLERANCE,
                "batched_max_logit_diff": round(max_diff, 8),
                "note": "C# must reproduce input_ids (tokenizer parity) AND logits "
                        "(runtime parity). Compare each separately to localize failures.",
                "samples": samples_out,
            }, f, indent=2)
        print(f"Wrote golden reference -> {ref_path} ({len(samples_out)} samples)")
 
        # Artifacts: the model, its golden contract, and the tokenizer travel together.
        mlflow.log_artifact(onnx_path)
        mlflow.log_artifact(ref_path)
        mlflow.log_artifacts(tok_dir, artifact_path="tokenizer")
 
        print(f"\nMLflow run {run.info.run_id} logged to {args.mlflow_uri} "
              f"(experiment '{args.experiment}').")
 
        if not passed:
            raise SystemExit(f"\nPARITY FAILED (max diff {max_diff:.2e}). Do NOT ship this "
                             "export -- investigate before building the C# layer. "
                             "(Run is logged in MLflow, tagged parity=FAILED.)")
        print(f"\nPARITY PASSED. finbert.onnx matches PyTorch within {TOLERANCE:.0e}. "
              "Safe to build the C# serving layer against parity_reference.json.")
 
 
if __name__ == "__main__":
    main()