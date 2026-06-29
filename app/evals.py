import asyncio
import json
import logging
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import EvalDataset, EvalRun, ClientAccount, UsageLedger
from app.metering import tokens, compute_cost
from app.proxy import run_blocking_chat

logger = logging.getLogger("dyergate.evals")


# Built-in evaluators (return 1.0 for pass, 0.0 for fail)
EVALUATORS = {
    "exact_match": lambda gold, pred: 1.0 if (gold or "").strip() == (pred or "").strip() else 0.0,
    "contains": lambda gold, pred: 1.0 if (gold or "").strip().lower() in (pred or "").lower() else 0.0,
    "fuzzy": lambda gold, pred: _fuzzy_match(gold, pred),
    "regex": lambda gold, pred: 1.0 if re.search(gold, pred or "") else 0.0,
    "json_valid": lambda gold, pred: 1.0 if _try_json(pred) is not None else 0.0,
    "levenshtein": lambda gold, pred: _levenshtein_similarity(gold or "", pred or ""),
}


def _try_json(s: str) -> Optional[dict]:
    try:
        return json.loads(s)
    except Exception:
        return None


def _levenshtein_similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    a, b = a.lower(), b.lower()
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1): dp[i][0] = i
    for j in range(n + 1): dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return 1.0 - dp[m][n] / max(m, n)


def _fuzzy_match(gold: str, pred: str) -> float:
    if not gold or not pred:
        return 0.0
    return _levenshtein_similarity(gold, pred)


async def run_eval(
    db: Session, client: ClientAccount,
    dataset_id: int, model: str, evaluator: str = "exact_match",
    sample_size: Optional[int] = None,
) -> EvalRun:
    import re
    dataset = db.query(EvalDataset).filter(EvalDataset.id == dataset_id).first()
    if not dataset:
        raise ValueError("Dataset not found.")

    run = EvalRun(
        org_id=client.org_id, dataset_id=dataset_id, model=model,
        total_rows=0, passed=0, failed=0, cost=0.0,
        status="running", started_at=datetime.utcnow(),
    )
    db.add(run); db.commit(); db.refresh(run)

    # Load dataset rows from S3 or local
    rows = await _load_dataset_rows(dataset, sample_size)
    run.total_rows = len(rows)
    db.commit()

    eval_fn = EVALUATORS.get(evaluator)
    if not eval_fn:
        run.status = "failed"
        run.error = f"Unknown evaluator: {evaluator}"
        db.commit()
        return run

    schema = dataset.schema or {"input": "prompt", "expected": "gold"}
    input_key = schema.get("input", "prompt")
    expected_key = schema.get("expected", "gold")

    per_row = []
    total_cost = 0.0
    passed = 0
    for i, row in enumerate(rows):
        prompt = row.get(input_key, "")
        gold = row.get(expected_key, "")
        body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
        try:
            resp = await run_blocking_chat(body, client, client.tier, db)
            pred = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            cost = resp.get("usage", {}).get("cost", 0.0)
            total_cost += cost
            score = eval_fn(gold, pred)
            if score >= 0.5:
                passed += 1
            per_row.append({"i": i, "score": score, "expected": gold[:200], "predicted": pred[:200]})
        except Exception as e:
            per_row.append({"i": i, "error": str(e)[:200]})
        if (i + 1) % 50 == 0:
            run.passed = passed
            run.failed = i + 1 - passed
            run.cost = total_cost
            db.commit()

    accuracy = passed / len(rows) if rows else 0.0
    run.metrics = {evaluator: accuracy}
    run.per_row_results = per_row[:1000]  # cap stored detail
    run.passed = passed
    run.failed = len(rows) - passed
    run.cost = total_cost
    run.status = "completed"
    run.completed_at = datetime.utcnow()
    db.commit()
    return run


async def _load_dataset_rows(dataset: EvalDataset, sample_size: Optional[int]) -> list[dict]:
    """Load JSONL rows. If S3 path, fetch; else assume local."""
    rows = []
    if dataset.s3_path and dataset.s3_path.startswith("s3://"):
        import boto3
        s3 = boto3.client("s3", region_name=settings.ARCHIVE_S3_REGION)
        bucket, key = dataset.s3_path[5:].split("/", 1)
        obj = s3.get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read().decode("utf-8")
        for line in body.splitlines():
            if line.strip():
                rows.append(json.loads(line))
    else:
        # Treat s3_path as local file path
        path = dataset.s3_path or f"./data/eval/{dataset.id}.jsonl"
        try:
            with open(path, "r") as f:
                for line in f:
                    if line.strip():
                        rows.append(json.loads(line))
        except FileNotFoundError:
            pass
    if sample_size and len(rows) > sample_size:
        rows = rows[:sample_size]
    return rows
