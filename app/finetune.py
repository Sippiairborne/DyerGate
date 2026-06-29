import asyncio
import logging
import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import FinetuneJob, ClientAccount, UsageLedger

logger = logging.getLogger("dyergate.finetune")


FINETUNE_COST_PER_HOUR = {
    "llama3-8b": 2.0,
    "llama3-70b": 8.0,
    "mistral-7b": 1.5,
    "qwen-7b": 1.8,
}


async def run_finetune_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(FinetuneJob).filter(FinetuneJob.id == job_id).first()
        if not job:
            return
        client = db.query(ClientAccount).filter(ClientAccount.id == job.client_id).first()
        if not client:
            job.status = "failed"
            job.error = "Client not found"
            db.commit()
            return

        job.status = "validating_files"
        job.progress_pct = 5.0
        db.commit()

        # Simulate file validation
        await asyncio.sleep(2)

        job.status = "running"
        job.started_at = datetime.utcnow()
        db.commit()

        # Simulate training loop with progress updates
        total_steps = 100
        rate = FINETUNE_COST_PER_HOUR.get(job.base_model, 2.0)
        estimated_hours = max(0.5, job.dataset_rows / 1000)
        estimated_cost = rate * estimated_hours

        for step in range(total_steps):
            await asyncio.sleep(0.5)
            job.progress_pct = 5 + (step / total_steps) * 95
            if step % 20 == 0:
                db.commit()
        db.commit()

        job.output_model_id = f"{client.client_identity}-{job.name}-ft-{int(time.time())}"
        job.status = "succeeded"
        job.completed_at = datetime.utcnow()
        job.progress_pct = 100.0
        job.cost = estimated_cost
        client.credit_balance = max(0.0, client.credit_balance - estimated_cost)
        db.add(UsageLedger(
            org_id=client.org_id, client_id=client.id,
            endpoint=f"/v1/fine_tuning/{job.id}",
            model=job.output_model_id, input_tokens=0, output_tokens=0,
            total_cost=estimated_cost, success=True,
        ))
        db.commit()
    except Exception as e:
        logger.exception("finetune job %s failed", job_id)
        try:
            job = db.query(FinetuneJob).filter(FinetuneJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error = str(e)
                job.completed_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def create_finetune_job(
    db: Session, client: ClientAccount,
    name: str, base_model: str, dataset_rows: int,
    training_file_id: str = None,
    hyperparameters: dict = None,
) -> FinetuneJob:
    job = FinetuneJob(
        org_id=client.org_id, client_id=client.id,
        name=name, base_model=base_model,
        training_file_id=training_file_id,
        dataset_rows=dataset_rows,
        hyperparameters=hyperparameters or {"epochs": 3, "lr": 2e-5},
        status="pending",
    )
    db.add(job); db.commit(); db.refresh(job)
    asyncio.create_task(run_finetune_job(job.id))
    return job
