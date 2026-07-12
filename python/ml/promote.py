import argparse
import sys
import mlflow
from mlflow.tracking import MlflowClient

TRACKING_URI = "sqlite:///mlflow.db"
EXPERIMENT = "finbert-onnx-export"
MODEL_NAME = "finbert-risk-signal"
ARTIFACT = "finbert.onnx"
PROD_ALIAS = "production"

def latest_run_id(client: MlflowClient, experiment_name: str) -> str | None:
    exp = client.get_experiment_by_name(experiment_name)
    if exp is None:
        return None
    runs = client.search_runs([exp.experiment_id], order_by=["start_time DESC"], max_results=1)
    return runs[0].info.run_id if runs else None

def current_production(client: MlflowClient, name: str):
    try:
        return client.get_model_version_by_alias(name, PROD_ALIAS)
    except Exception:
        return None
    
def ensure_model(client: MlflowClient, name: str) -> None:
    try:
        client.create_registered_model(name)
    except Exception:
        pass

def promote(tracking_uri: str, experiment: str, model_name: str, run_id: str | None = None, dry_run: bool = False) -> int:
    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient(tracking_uri=tracking_uri)

    rid = run_id or latest_run_id(client, experiment)
    if rid is None:
        print(f"No runs found in experiment '{experiment}'. Run export_onnx.py first.")
        return 2
    
    run = client.get_run(rid)
    metrics = run.data.metrics
    parity_passed = int(metrics.get("parity_passed", 0)) == 1
    diff = metrics.get("batched_max_logit_diff")
    diff_str = f"{diff:.2e}" if diff is not None else "n/a"

    prev = current_production(client, model_name)
    prev_str = f"v{prev.version}" if prev else "none"

    print(f"Run:               {rid}")
    print(f"  parity_passed:   {parity_passed}")
    print(f"  max logit diff:  {diff_str}")
    print(f"  current prod:    {prev_str}")

    if dry_run:
        action = "promote to production" if parity_passed else "register only"
        print(f"\n[dry-run] Would register a new version and {action}. No changes made.")
        return 0
    
    ensure_model(client, model_name)
    art_uri = f"runs:/{rid}/{ARTIFACT}"
    src = client.get_run(rid).info.artifact_uri.rstrip("/") + "/" + ARTIFACT
    mv = client.create_model_version(name=model_name, source=src, run_id=rid)
    client.set_model_version_tag(model_name, mv.version, "parity_passed", str(parity_passed))
    client.set_model_version_tag(model_name, mv.version, "max_logit_diff", diff_str)
    print(f"\nRegistered {model_name} v{mv.version} (candidate).")

    if not parity_passed:
        print(f"\nParity Gate Blocked promotion. v{mv.version} registered but NOT promoted. "
              f"Production stays at {prev_str}.")
        return 1
    
    client.set_registered_model_alias(model_name, PROD_ALIAS, mv.version)
    print(f"\nPARITY GATE PASSED. Promoted v{mv.version} to @{PROD_ALIAS} "
          f"(was {prev_str}).")
    return 0

def main():
    ap = argparse.ArgumentParser(description="Promote an export run to production if it passed parity.")
    ap.add_argument("--tracking-uri", default=TRACKING_URI)
    ap.add_argument("--experiment", default=EXPERIMENT)
    ap.add_argument("--model-name", default=MODEL_NAME)
    ap.add_argument("--run-id", default=None, help="Run to promote (default: latest export run)")
    ap.add_argument("--dry-run", action="store_true", help="Report the decision without changing anything")
    args = ap.parse_args()
    sys.exit(promote(args.tracking_uri, args.experiment, args.model_name,
                     run_id=args.run_id, dry_run=args.dry_run))
 
 
if __name__ == "__main__":
    main()