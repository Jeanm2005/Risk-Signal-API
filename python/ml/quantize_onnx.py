import argparse
import json
import os
import numpy as np
import onnxruntime as ort
from onnxruntime.quantization import quantize_dynamic, QuantType
from onnxruntime.quantization.shape_inference import quant_pre_process

MAX_LEN = 512

SAMPLES = [
    "The company reported record quarterly revenue and raised its full-year guidance.",
    "Shares collapsed after the firm disclosed an SEC probe and suspended its dividend.",
    "The board of directors will convene on Thursday to review the quarterly report.",
    "Rising input costs and weak demand pressured margins, and management withdrew guidance.",
    "The acquisition closed on schedule and is expected to be modestly accretive next year.",
    "Despite a challenging macro backdrop, the bank maintained strong capital ratios and "
    "grew net interest income, though it flagged elevated credit risk in commercial real estate.",
]

EVAL_TEXTS = SAMPLES + [
    "Quarterly earnings beat expectations but revenue came in slightly below consensus.",
    "The company announced a $2 billion share buyback program.",
    "Management reaffirmed full-year guidance despite softening demand in Europe.",
    "The firm took a one-time charge related to restructuring its retail segment.",
    "Profit margins narrowed on higher input costs, though volumes grew modestly.",
    "Regulators opened an inquiry into the company's accounting practices.",
    "The CEO resigned unexpectedly, and the CFO will serve as interim chief executive.",
    "Same-store sales rose 3% year over year, in line with analyst estimates.",
    "The company cut its dividend for the first time in a decade.",
    "A major customer contract was renewed on less favorable terms.",
    "Free cash flow improved sequentially, aided by working capital discipline.",
    "Shares fell despite an earnings beat, as investors focused on weak forward guidance.",
    "Credit losses ticked higher in the consumer lending portfolio.",
    "The merger received antitrust clearance and is expected to close next quarter.",
    "Inventory levels remain elevated relative to historical norms.",
    "The company raised its full-year outlook following a strong holiday season.",
    "An impairment charge was recorded against goodwill from a prior acquisition.",
    "Debt was refinanced at a lower rate, extending the maturity profile.",
    "The board authorized an increase to the quarterly dividend.",
    "Supply chain disruptions weighed on deliveries during the period.",
    "Operating expenses grew faster than revenue for the third consecutive quarter.",
    "The company disclosed a material weakness in internal controls.",
    "Bookings accelerated, driven by strength in the enterprise segment.",
    "Currency headwinds reduced reported revenue by approximately 200 basis points.",
]

def _softmax(x):
    e = np.exp(x - np.max(x))
    return e / e.sum()

def run(session, feeds):
    return session.run(["logits"], feeds)[0]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="artifacts")
    ap.add_argument("--model", default="ProsusAI/finbert", help="only used to load the tokenizer")
    ap.add_argument("--no-preprocess", action="store_true", help="skip shape inference + graph optimization")
    args = ap.parse_args()

    fp32_path = os.path.join(args.out, "finbert.onnx")
    prep_path = os.path.join(args.out, "finbert-preprocessed.onnx")
    int8_path = os.path.join(args.out, "finbert-int8.onnx")
    ref_path = os.path.join(args.out, "parity_reference_int8.json")

    if not os.path.exists(fp32_path):
        raise SystemExit(f"FP32 model not found at {fp32_path}.")
    
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.model)

    fp32_mb = os.path.getsize(fp32_path) / (1024 * 1024)
    print(f"FP32 model: {fp32_path} ({fp32_mb:.1f} MB)")

    source_for_quant = fp32_path
    if not args.no_preprocess:
        print("Pre-processing ...")
        try:
            quant_pre_process(
                input_model_path=fp32_path,
                output_model_path=prep_path,
                skip_optimization=False,
                skip_onnx_shape=False,
                skip_symbolic_shape=False,
            )
            source_for_quant = prep_path
            print(f" preprocessed -> {prep_path}"
                  f"({os.path.gentize(prep_path) / (1024 * 1024):.1f} MB)")
        except Exception as e:
            print(f" preprocessing failed ({type(e).__name__}: {e}); "
                  "falling back to the raw FP32 graph")
            source_for_quant = fp32_path

    print("Quantizing to INT8 ...")

    quantize_dynamic(
        model_input=source_for_quant,
        model_output=int8_path,
        weight_type=QuantType.QInt8,
    )

    int8_mb = os.path.getsize(int8_path) / (1024 * 1024)
    print(f"INT8 model: {int8_path} ({int8_mb:.1f} MB)"
          f"[{fp32_mb / int8_mb:.1f}x smaller]")
    
    sess_fp32 = ort.InferenceSession(fp32_path, providers=["CPUExecutionProvider"])
    sess_int8 = ort.InferenceSession(int8_path, providers=["CPUExecutionProvider"])

    batch = tok(EVAL_TEXTS, padding=True, truncation=True, max_length=MAX_LEN, return_tensors="np")
    feeds = {k: batch[k] for k in ("input_ids", "attention_mask", "token_type_ids")}

    logits_fp32 = run(sess_fp32, feeds)
    logits_int8 = run(sess_int8, feeds)

    abs_diff = np.abs(logits_fp32 - logits_int8)
    max_logit_diff = float(abs_diff.max())
    mean_logit_diff = float(abs_diff.mean())

    pred_fp32 = logits_fp32.argmax(1)
    pred_int8 = logits_int8.argmax(1)
    n = len(EVAL_TEXTS)
    flips = int((pred_fp32 != pred_int8).sum())
    class_agreement = flips == 0
    agreement_rate = (n - flips) / n

    probs_fp32 = np.array([_softmax(r) for r in logits_fp32])
    probs_int8 = np.array([_softmax(r) for r in logits_int8])
    max_prob_shift = float(np.abs(probs_fp32 - probs_int8).max())
    mean_prob_shift = float(np.abs(probs_fp32 - probs_int8).mean())

    print(f"\n--- Quantization cost (INT8 vs FP32, n={n} texts) ---")
    print(f"  max  |logit diff|:       {max_logit_diff:.4f}")
    print(f"  mean |logit diff|:       {mean_logit_diff:.4f}")
    print(f"  max  probability shift:  {max_prob_shift:.4f}")
    print(f"  mean probability shift:  {mean_prob_shift:.4f}")
    print(f"  predicted class agreement: {n - flips}/{n} ({agreement_rate:.1%})"
          f"{'  ALL MATCH' if class_agreement else f'  {flips} FLIPPED'}")
    
    if flips:
        for i in range(n):
            if pred_fp32[i] != pred_int8[i]:
                print(f" Flipped fp32={pred_fp32[i]} int8={pred_int8[i]} :: {EVAL_TEXTS[i][:65]}...")
        raise SystemExit(
            f"\nQuantization flipped {flips} predicted class(es)."
        )
    
    tolerance = float(max(round(max_logit_diff * 2, 3), 0.05))

    id2label = {0: "positive", 1: "negative", 2: "neutral"}
    samples_out = []
    for i, text in enumerate(SAMPLES):
        e = tok(text, truncation=True, max_length=MAX_LEN, return_tensors="np")
        f = {k: e[k] for k in ("input_ids", "attention_mask", "token_type_ids")}
        logits = run(sess_int8, f)[0]
        probs = _softmax(logits)
        samples_out.append({
            "text": text,
            "input_ids": e["input_ids"][0].tolist(),
            "attention_mask": e["attention_mask"][0].tolist(),
            "token_type_ids": e["token_type_ids"][0].tolist(),
            "logits": [round(float(x), 6) for x in logits],
            "probs": {id2label[j]: round(float(p), 6) for j, p in enumerate(probs)},
        })

    with open(ref_path, "w") as f:
        json.dump({
            "model": "finbert-int8.onnx",
            "quantization": "dynamic INT8 (QInt8 weights)",
            "derived_from": "finbert.onnx (FP32)",
            "max_length": MAX_LEN,
            "id2label": id2label,
            "tolerance": tolerance,
            "measured_vs_fp32": {
                "n_eval_texts": n,
                "max_logit_diff": round(max_logit_diff, 6),
                "mean_logit_diff": round(mean_logit_diff, 6),
                "max_prob_shift": round(max_prob_shift, 6),
                "mean_prob_shift": round(mean_prob_shift, 6),
                "predicted_class_agreement": class_agreement,
                "class_agreement_rate": round(agreement_rate, 4),
            },
            "note": "Quantization changes the numbers. This reference is the INT8 model's own "
                    "golden output, with a tolerance derived from its measured deviation from "
                    "FP32. The FP32 model keeps its stricter 1e-3 reference. The predicted class "
                    "is unchanged on every sample, which is the property that matters for serving.",
            "samples": samples_out,
        }, f, indent=2)

    print(f"\nWrote {ref_path} (tolerance {tolerance})")
    print(f"\nDone. Deploy {int8_path} ({int8_mb:.1f} MB) with parity_reference_int8.json.")

if __name__ == "__main__":
    main()