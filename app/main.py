
if settings.VOICE_API_ENABLED:
    from app.voice import transcribe, synthesize

    @app.post("/v1/audio/transcriptions")
    async def v1_transcribe(
        file: UploadFile = File(...),
        model: str = Form(default=None),
        language: str = Form(default=None),
        client: ClientAccount = Depends(verify_client),
        db: Session = Depends(get_db),
        request: Request = None,
    ):
        rid = getattr(request.state, "request_id", None)
        return await transcribe(db, client, file, model, language, rid)

    @app.post("/v1/audio/speech")
    async def v1_speech(
        body: dict,
        client: ClientAccount = Depends(verify_client),
        db: Session = Depends(get_db),
        request: Request = None,
    ):
        from fastapi.responses import Response
        rid = getattr(request.state, "request_id", None)
        audio = await synthesize(
            db, client, body.get("input", ""),
            body.get("model"), body.get("voice", "alloy"),
            body.get("response_format", "mp3"), rid,
        )
        return Response(content=audio, media_type="audio/mpeg")


if settings.VISION_API_ENABLED:
    from app.vision import vision_chat, generate_image

    @app.post("/v1/vision/chat")
    async def v1_vision(
        body: dict,
        client: ClientAccount = Depends(verify_client),
        db: Session = Depends(get_db),
        request: Request = None,
    ):
        rid = getattr(request.state, "request_id", None)
        model = body.get("model", "gpt-4o")
        images = body.get("images", [])
        messages = body.get("messages", [])
        resp = await vision_chat(db, client, model, messages, images,
                                 body.get("max_tokens", 1024), rid)
        return JSONResponse(content=resp)

    @app.post("/v1/images/generations")
    async def v1_image_gen(
        body: dict,
        client: ClientAccount = Depends(verify_client),
        db: Session = Depends(get_db),
        request: Request = None,
    ):
        rid = getattr(request.state, "request_id", None)
        result = await generate_image(
            db, client,
            body.get("prompt", ""), body.get("model"),
            body.get("size", "1024x1024"), body.get("n", 1), rid,
        )
        return JSONResponse(content=result)


if settings.FINETUNE_ENABLED:
    from app.finetune import create_finetune_job
    from app.models import FinetuneJob

    @app.post("/v1/fine_tuning/jobs")
    def create_finetune(
        body: dict,
        client: ClientAccount = Depends(verify_client),
        db: Session = Depends(get_db),
    ):
        job = create_finetune_job(
            db, client, body.get("name"), body.get("base_model"),
            body.get("dataset_rows", 0),
            body.get("training_file_id"), body.get("hyperparameters"),
        )
        return {"id": job.id, "status": job.status}

    @app.get("/v1/fine_tuning/jobs/{job_id}")
    def get_finetune(
        job_id: int,
        client: ClientAccount = Depends(verify_client),
        db: Session = Depends(get_db),
    ):
        job = db.query(FinetuneJob).filter(
            FinetuneJob.id == job_id, FinetuneJob.client_id == client.id
        ).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        return {
            "id": job.id, "name": job.name, "base_model": job.base_model,
            "status": job.status, "progress_pct": job.progress_pct,
            "output_model_id": job.output_model_id, "cost": job.cost,
            "error": job.error, "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }


if settings.EVAL_ENABLED:
    from app.evals import run_eval
    from app.models import EvalDataset, EvalRun

    @app.post("/v1/evals/datasets")
    def create_eval_dataset(
        name: str, s3_path: str = None, schema: str = None,
        row_count: int = 0,
        client: ClientAccount = Depends(verify_client),
        db: Session = Depends(get_db),
    ):
        import json as _json
        ds = EvalDataset(
            org_id=client.org_id, name=name, s3_path=s3_path,
            row_count=row_count,
            schema=_json.loads(schema) if schema else None,
        )
        db.add(ds); db.commit(); db.refresh(ds)
        return {"id": ds.id, "name": ds.name}

    @app.post("/v1/evals/run")
    async def start_eval(
        dataset_id: int, model: str, evaluator: str = "exact_match",
        sample_size: int = None,
        client: ClientAccount = Depends(verify_client),
        db: Session = Depends(get_db),
    ):
        run = await run_eval(db, client, dataset_id, model, evaluator, sample_size)
        return {"id": run.id, "status": run.status, "metrics": run.metrics,
                "passed": run.passed, "failed": run.failed, "cost": run.cost}

    @app.get("/v1/evals/runs/{run_id}")
    def get_eval_run(
        run_id: int,
        client: ClientAccount = Depends(verify_client),
        db: Session = Depends(get_db),
    ):
        run = db.query(EvalRun).filter(
            EvalRun.id == run_id, EvalRun.org_id == client.org_id,
        ).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found.")
        return {
            "id": run.id, "status": run.status, "metrics": run.metrics,
            "total_rows": run.total_rows, "passed": run.passed, "failed": run.failed,
            "cost": run.cost, "model": run.model,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }


# ---------- Marketplace Storefront (public) ----------

if settings.STOREFRONT_ENABLED:
    from app.marketplace_storefront import browse, install, uninstall, review

    @app.get("/v1/storefront")
    def storefront_browse(
        category: str = None, search: str = None, sort_by: str = "popular",
        limit: int = 50,
        _: ClientAccount = Depends(verify_client),
        db: Session = Depends(get_db),
    ):
        return browse(db, category, search, sort_by, limit)

    @app.post("/v1/storefront/install/{listing_id}")
    def storefront_install(
        listing_id: int,
        client: ClientAccount = Depends(verify_client),
        db: Session = Depends(get_db),
    ):
        from app.models import Organization
        org = db.query(Organization).filter(Organization.id == client.org_id).first()
        if not org:
            raise HTTPException(status_code=404, detail="Org not found.")
        inst = install(db, listing_id, org)
        return {"install_id": inst.id}

    @app.post("/v1/storefront/review/{listing_id}")
    def storefront_review(
        listing_id: int, rating: int, comment: str = None,
        client: ClientAccount = Depends(verify_client),
        db: Session = Depends(get_db),
    ):
        from app.models import Organization
        org = db.query(Organization).filter(Organization.id == client.org_id).first()
        rv = review(db, listing_id, org, rating, comment)
        return {"id": rv.id, "rating": rv.rating}



from fastapi import WebSocket
from app.config import settings

# WebSocket route
if settings.WS_ENABLED:
    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        from app.ws import chat_websocket
        await chat_websocket(websocket)


# Chat UI (public, embedded)
@app.get("/chat", response_class=HTMLResponse, include_in_schema=False)
def chat_ui():
    if not settings.CHAT_UI_ENABLED:
        return HTMLResponse("<h1>Chat UI disabled</h1>", status_code=404)
    with open("app/templates/chat.html") as f:
        return HTMLResponse(f.read())


# Studio UI (no-code workflow builder)
@app.get("/studio", response_class=HTMLResponse, include_in_schema=False)
def studio_ui():
    if not settings.STUDIO_ENABLED:
        return HTMLResponse("<h1>Studio disabled</h1>", status_code=404)
    with open("app/templates/studio.html") as f:
        return HTMLResponse(f.read())


# Reuse all previous endpoints from Phases 1-10
