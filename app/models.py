
# ---------- Voice / Audio ----------

class VoiceTranscription(Base):
    __tablename__ = "voice_transcriptions"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("client_accounts.id"), nullable=False, index=True)
    model = Column(String(64), nullable=False)
    duration_seconds = Column(Float, default=0.0, nullable=False)
    file_size_bytes = Column(Integer, default=0, nullable=False)
    language = Column(String(16), nullable=True)
    text = Column(Text, nullable=True)
    cost = Column(Float, default=0.0, nullable=False)
    success = Column(Boolean, default=True, nullable=False)
    request_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class VoiceSynthesis(Base):
    __tablename__ = "voice_synthesis"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("client_accounts.id"), nullable=False, index=True)
    model = Column(String(64), nullable=False)
    voice = Column(String(64), default="alloy", nullable=False)
    input_text_length = Column(Integer, default=0, nullable=False)
    output_audio_seconds = Column(Float, default=0.0, nullable=False)
    cost = Column(Float, default=0.0, nullable=False)
    success = Column(Boolean, default=True, nullable=False)
    request_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


# ---------- Vision / Image ----------

class VisionRequest(Base):
    __tablename__ = "vision_requests"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("client_accounts.id"), nullable=False, index=True)
    model = Column(String(64), nullable=False)
    image_count = Column(Integer, default=1, nullable=False)
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    cost = Column(Float, default=0.0, nullable=False)
    success = Column(Boolean, default=True, nullable=False)
    request_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class ImageGeneration(Base):
    __tablename__ = "image_generations"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("client_accounts.id"), nullable=False, index=True)
    model = Column(String(64), nullable=False)
    prompt = Column(Text, nullable=False)
    size = Column(String(16), default="1024x1024", nullable=False)
    n = Column(Integer, default=1, nullable=False)
    image_urls = Column(JSON, nullable=True)
    cost = Column(Float, default=0.0, nullable=False)
    success = Column(Boolean, default=True, nullable=False)
    request_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


# ---------- Fine-tuning ----------

class FinetuneJob(Base):
    __tablename__ = "finetune_jobs"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("client_accounts.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    base_model = Column(String(128), nullable=False)
    training_file_id = Column(String(128), nullable=True)  # S3 path / Ollama Modelfile
    dataset_rows = Column(Integer, default=0, nullable=False)
    hyperparameters = Column(JSON, nullable=True)
    status = Column(String(32), default="pending", nullable=False, index=True)
    # pending|validating_files|running|succeeded|failed|canceled
    progress_pct = Column(Float, default=0.0, nullable=False)
    output_model_id = Column(String(256), nullable=True)  # resulting model name
    cost = Column(Float, default=0.0, nullable=False)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


# ---------- Eval Harness ----------

class EvalDataset(Base):
    __tablename__ = "eval_datasets"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    format = Column(String(32), default="jsonl", nullable=False)  # jsonl|csv
    s3_path = Column(String(512), nullable=True)
    row_count = Column(Integer, default=0, nullable=False)
    schema = Column(JSON, nullable=True)  # {"input":"prompt","expected":"gold"}
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    dataset_id = Column(Integer, ForeignKey("eval_datasets.id"), nullable=False, index=True)
    model = Column(String(128), nullable=False)
    metrics = Column(JSON, nullable=True)  # {"accuracy":0.92,"f1":0.88,...}
    per_row_results = Column(JSON, nullable=True)
    total_rows = Column(Integer, default=0, nullable=False)
    passed = Column(Integer, default=0, nullable=False)
    failed = Column(Integer, default=0, nullable=False)
    cost = Column(Float, default=0.0, nullable=False)
    status = Column(String(32), default="pending", nullable=False, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


# ---------- Marketplace Storefront ----------

class MarketplaceListing(Base):
    """A curated marketplace listing for a skill (different from raw AgentSkill)."""
    __tablename__ = "marketplace_listings"
    id = Column(Integer, primary_key=True)
    skill_id = Column(Integer, ForeignKey("agent_skills.id"), nullable=False, unique=True, index=True)
    title = Column(String(128), nullable=False)
    tagline = Column(String(256), nullable=True)
    long_description = Column(Text, nullable=True)
    categories = Column(String(512), nullable=True)  # comma-separated
    screenshots = Column(JSON, nullable=True)  # [{url:"..."}]
    install_count = Column(Integer, default=0, nullable=False)
    rating_avg = Column(Float, default=0.0, nullable=False)
    rating_count = Column(Integer, default=0, nullable=False)
    is_featured = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MarketplaceInstall(Base):
    __tablename__ = "marketplace_installs"
    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("marketplace_listings.id"), nullable=False, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    installed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("listing_id", "org_id", name="uq_listing_org"),)


class MarketplaceReview(Base):
    __tablename__ = "marketplace_reviews"
    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("marketplace_listings.id"), nullable=False, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


# ---------- Existing models from Phases 1-9 (abbreviated) ----------



# ---------- WebSocket ----------

class WsConnection(Base):
    """Active WebSocket connection tracking."""
    __tablename__ = "ws_connections"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("client_accounts.id"), nullable=False, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    session_id = Column(String(64), nullable=False, unique=True, index=True)
    ip_address = Column(String(64), nullable=True)
    connected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    metadata = Column(JSON, nullable=True)


class WsRoom(Base):
    """Pub/sub room for streaming events between clients."""
    __tablename__ = "ws_rooms"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(128), nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("client_accounts.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ---------- Forecasting ----------

class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    horizon_days = Column(Integer, default=30, nullable=False)
    predicted_total_cost = Column(Float, default=0.0, nullable=False)
    predicted_input_tokens = Column(Integer, default=0, nullable=False)
    predicted_output_tokens = Column(Integer, default=0, nullable=False)
    predicted_requests = Column(Integer, default=0, nullable=False)
    daily_forecast = Column(JSON, nullable=True)  # [{day:"2025-02-01",cost:1.23}, ...]
    confidence_low = Column(Float, default=0.0, nullable=False)
    confidence_high = Column(Float, default=0.0, nullable=False)
    model_used = Column(String(64), default="linear_regression", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


# ---------- On-call Integrations ----------

class Integration(Base):
    """Per-org outbound integration config."""
    __tablename__ = "integrations"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    kind = Column(String(32), nullable=False)  # pagerduty|opsgenie|slack|discord|teams
    config = Column(JSON, nullable=False)  # {"webhook_url":"...","channel":"#alerts"}
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
