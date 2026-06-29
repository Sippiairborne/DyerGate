"""initial schema

Revision ID: 0001
Revises:
Create Date: 2025-01-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), unique=True, nullable=False, index=True),
        sa.Column("slug", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("quota_usd", sa.Float, default=1000.0, nullable=False),
        sa.Column("is_active", sa.Boolean, default=True, nullable=False),
        sa.Column("stripe_customer_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(256), unique=True, nullable=False, index=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("is_active", sa.Boolean, default=True, nullable=False),
        sa.Column("is_superadmin", sa.Boolean, default=False, nullable=False),
        sa.Column("totp_secret", sa.String(64), nullable=True),
        sa.Column("totp_enabled", sa.Boolean, default=False, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime, nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "account_tiers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("rate_limit_per_min", sa.Integer, default=60, nullable=False),
        sa.Column("cost_per_thousand_input", sa.Float, default=0.0015, nullable=False),
        sa.Column("cost_per_thousand_output", sa.Float, default=0.0020, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "client_accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("client_identity", sa.String(128), nullable=False, index=True),
        sa.Column("tier_id", sa.Integer, sa.ForeignKey("account_tiers.id"), nullable=False),
        sa.Column("credit_balance", sa.Float, default=10.0, nullable=False),
        sa.Column("is_active", sa.Boolean, default=True, nullable=False),
        sa.Column("auto_topup_enabled", sa.Boolean, default=False, nullable=False),
        sa.Column("auto_topup_threshold", sa.Float, default=5.0, nullable=False),
        sa.Column("auto_topup_amount", sa.Float, default=25.0, nullable=False),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime, nullable=True),
        sa.Column("last_low_balance_alert_at", sa.DateTime, nullable=True),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_client_org_id", "client_accounts", ["org_id"])
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client_accounts.id"), nullable=False, index=True),
        sa.Column("key_hash", sa.String(128), nullable=False, index=True),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.Column("expires_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "usage_ledger",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client_accounts.id"), nullable=False, index=True),
        sa.Column("endpoint", sa.String(128), nullable=False, index=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("input_tokens", sa.Integer, default=0, nullable=False),
        sa.Column("output_tokens", sa.Integer, default=0, nullable=False),
        sa.Column("total_cost", sa.Float, default=0.0, nullable=False),
        sa.Column("success", sa.Boolean, default=True, nullable=False),
        sa.Column("upstream_status", sa.Integer, nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True, index=True),
        sa.Column("archived_at", sa.DateTime, nullable=True, index=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_usage_org_time", "usage_ledger", ["org_id", "created_at"])
    op.create_table(
        "credit_packages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("usd_cents", sa.Integer, nullable=False),
        sa.Column("credit_amount", sa.Float, nullable=False),
        sa.Column("is_active", sa.Boolean, default=True, nullable=False),
        sa.Column("stripe_price_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client_accounts.id"), nullable=False, index=True),
        sa.Column("stripe_session_id", sa.String(256), unique=True, nullable=True, index=True),
        sa.Column("stripe_payment_intent_id", sa.String(256), nullable=True, index=True),
        sa.Column("package_name", sa.String(64), nullable=True),
        sa.Column("usd_cents", sa.Integer, nullable=False),
        sa.Column("credit_amount", sa.Float, nullable=False),
        sa.Column("status", sa.String(32), default="pending", nullable=False),
        sa.Column("source", sa.String(32), default="stripe_checkout", nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "client_webhooks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client_accounts.id"), nullable=False, index=True),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("secret", sa.String(128), nullable=False),
        sa.Column("event_types", sa.String(512), default="low_balance,payment_succeeded", nullable=False),
        sa.Column("is_active", sa.Boolean, default=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "alert_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=True, index=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client_accounts.id"), nullable=True, index=True),
        sa.Column("event_type", sa.String(64), nullable=False, index=True),
        sa.Column("payload", sa.Text, nullable=True),
        sa.Column("delivered", sa.Boolean, default=False, nullable=False),
        sa.Column("response_status", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=True, index=True),
        sa.Column("actor", sa.String(128), nullable=False, index=True),
        sa.Column("action", sa.String(64), nullable=False, index=True),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.String(128), nullable=True),
        sa.Column("details", sa.Text, nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "scheduled_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("cadence", sa.String(16), default="weekly", nullable=False),
        sa.Column("target", sa.String(16), default="webhook", nullable=False),
        sa.Column("target_url", sa.String(512), nullable=True),
        sa.Column("is_active", sa.Boolean, default=True, nullable=False),
        sa.Column("last_run_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ip_allowlist",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cidr", sa.String(64), nullable=False, index=True),
        sa.Column("label", sa.String(128), nullable=True),
        sa.Column("is_active", sa.Boolean, default=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "org_members",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("admin_users.id"), nullable=False, index=True),
        sa.Column("org_id", sa.Integer, sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "org_id", name="uq_user_org"),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("admin_users.id"), nullable=False, index=True),
        sa.Column("token_hash", sa.String(128), unique=True, nullable=False, index=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime, nullable=False, index=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    for t in [
        "admin_sessions", "org_members", "ip_allowlist", "scheduled_reports",
        "audit_log", "alert_log", "client_webhooks", "payments",
        "credit_packages", "usage_ledger", "api_keys", "client_accounts",
        "account_tiers", "admin_users", "organizations",
    ]:
        op.drop_table(t)
