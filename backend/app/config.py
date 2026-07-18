from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _env_int(key: str, default: int) -> int:
    raw = _env(key, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _build_database_url() -> str:
    if _env("DATABASE_URL"):
        return _env("DATABASE_URL")

    host = _env("DB_HOST")
    port = _env("DB_PORT", "5432")
    user = _env("DB_USER")
    password = _env("DB_PASSWORD").strip("\"'")
    db_name = _env("DB_NAME", "ksp_crime")
    sslmode = _env("DB_SSL", "require")

    if not host or not user:
        return "postgresql+psycopg://postgres:postgres@localhost:5432/ksp_crime"
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db_name}?sslmode={sslmode}"


@dataclass(frozen=True)
class Settings:
    app_name: str = "KSP Catalyst Ingestion Backend"
    api_prefix: str = "/api/v1"
    listen_host: str = "0.0.0.0"
    listen_port: int = _env_int("X_ZOHO_CATALYST_LISTEN_PORT", 9000)

    database_url: str = _build_database_url()

    # Upload constraints.
    max_files_per_upload: int = _env_int("MAX_FILES_PER_UPLOAD", 15)
    max_total_upload_mb: int = _env_int("MAX_TOTAL_UPLOAD_MB", 60)
    default_max_file_mb: int = _env_int("DEFAULT_MAX_FILE_MB", 15)
    default_allowed_exts: tuple[str, ...] = ("txt", "html", "pdf", "docx", "csv", "png", "jpg", "jpeg", "webp")

    # Queue / function config.
    catalyst_jobpool_id: str = _env("CATALYST_JOBPOOL_ID")
    catalyst_jobpool_name: str = _env("CATALYST_JOBPOOL_NAME", "ingestion-job-pool")
    catalyst_function_id: str = _env("CATALYST_FUNCTION_ID")
    catalyst_function_name: str = _env("CATALYST_FUNCTION_NAME", "ingest_processor")
    catalyst_job_submit_rest_url: str = _env("CATALYST_JOB_SUBMIT_REST_URL")
    ingest_local_invoke: bool = _env("INGEST_LOCAL_INVOKE", "false").lower() in ("1", "true", "yes")

    # Zoho Catalyst auth.
    zoho_project_id: str = _env("ZOHO_CATALYST_PROJECT_ID")
    zoho_project_key: str = _env("ZOHO_CATALYST_PROJECT_KEY")
    zoho_environment: str = _env("ZOHO_CATALYST_ENVIRONMENT", "Development")
    zoho_project_domain: str = _env("ZOHO_CATALYST_PROJECT_DOMAIN", "https://api.catalyst.zoho.in")
    zoho_auth_domain: str = _env("ZOHO_CATALYST_AUTH_DOMAIN", "https://accounts.zohoportal.in")
    zoho_client_id: str = _env("ZOHO_CATALYST_CLIENT_ID")
    zoho_client_secret: str = _env("ZOHO_CATALYST_CLIENT_SECRET")
    zoho_refresh_token: str = _env("ZOHO_CATALYST_REFRESH_TOKEN")
    zoho_stratus_bucket: str = _env("ZOHO_STRATUS_BUCKET", "ksp-data-files")

    # LLM provider selection.
    data_ingestion_llm: str = _env("DATA_INGESTION_LLM", "zoho").lower()

    # Fixed "today" for all demo temporal analysis. The synthetic data is anchored to this
    # date (data_generation/config.DEMO_DATE_STR), and the demo runs long after generation,
    # so comparing surge/recency windows against the real wall clock (NOW()) silently ages
    # the "last 21 days" cluster out of range. Every date-relative demo query and the agent's
    # sense of "now" must use THIS anchor instead. Keep it in sync with data_generation.
    demo_reference_date: str = _env("DEMO_REFERENCE_DATE", "2026-06-26")
    # The assistant's model. CHAT_LLM_PROVIDER picks the provider
    # (zoho|openai|anthropic|bedrock|bedrock_mantle); CHAT_LLM_ID overrides that provider's default
    # model id, so switching model doesn't need a code change. Falls back to the older
    # CONV_AI_LLM name when unset. Whatever the primary is, the fallback chain lands on
    # OpenAI (see llm.py::_FALLBACK_PROVIDER) -- one provider being down or rate-limited
    # must not end the demo.
    chat_llm_provider: str = _env("CHAT_LLM_PROVIDER", _env("CONV_AI_LLM", "openai")).lower()
    chat_llm_id: str = _env("CHAT_LLM_ID")
    conv_ai_llm: str = _env("CONV_AI_LLM", "openai").lower()
    openai_api_key: str = _env("OPENAI_API_KEY")
    anthropic_api_key: str = _env("ANTHROPIC_API_KEY")
    openai_model: str = _env("OPENAI_MODEL", "gpt-5.4")
    anthropic_model: str = _env("ANTHROPIC_MODEL", "claude-sonnet-5")
    bedrock_model_id: str = _env("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-6")
    aws_region: str = _env("AWS_REGION") or _env("AWS_DEFAULT_REGION", "us-east-1")
    # Bedrock **Mantle** (provider "bedrock_mantle"): the OpenAI-compatible endpoint that
    # serves models Converse can't (e.g. xai.grok-*, zai.glm-*). Base URL is region-scoped;
    # auth is a short-term bearer minted from the same AWS creds (see llm.py). Default is
    # derived from the region so it tracks AWS_REGION without a second env var.
    bedrock_mantle_base_url: str = _env(
        "BEDROCK_MANTLE_BASE_URL",
        f"https://bedrock-mantle.{_env('AWS_REGION') or _env('AWS_DEFAULT_REGION', 'us-east-1')}.api.aws/v1",
    )
    # Long-term Bedrock API key (from the console). When set, it's used as-is; otherwise
    # llm.py mints a short-term bearer from the AWS IAM creds. Either authenticates Mantle.
    bedrock_mantle_api_key: str = _env("MANTLE_API_KEY")
    zoho_quickml_endpoint_url: str = _env("ZOHO_QUICKML_ENDPOINT_URL")
    zoho_quickml_catalyst_org: str = _env("ZOHO_QUICKML_CATALYST_ORG")
    zoho_quickml_model_name: str = _env("ZOHO_QUICKML_MODEL_NAME", "crm-di-glm47b_30b_it")
    zoho_quickml_vlm_endpoint_url: str = _env("ZOHO_QUICKML_VLM_ENDPOINT_URL")
    zoho_quickml_vlm_model_name: str = _env("ZOHO_QUICKML_VLM_MODEL_NAME", "VL-Qwen3.6-35B-A3B")
    llm_requests_per_second: float = float(_env("LLM_REQUESTS_PER_SECOND", "0.8"))
    assistant_multi_agent: bool = _env("ASSISTANT_MULTI_AGENT", "true").lower() in ("1", "true", "yes")
    assistant_code_timeout_seconds: int = _env_int("ASSISTANT_CODE_TIMEOUT_SECONDS", 20)

    # Chat LLM parameters
    chat_max_tokens: int = _env_int("CHAT_MAX_TOKENS", 4096)
    chat_reasoning_effort: str = os.environ.get("CHAT_REASONING_EFFORT", "high")

    # Sarvam STT (streaming speech-to-text for the assistant mic). Key stays server-side;
    # the browser talks to our /ws/assistant/transcribe relay, which attaches this header.
    sarvam_api_key: str = _env("SARVAM_API_KEY")

    # Splink endpoint and auth.
    splink_shared_secret: str = _env("SPLINK_SHARED_SECRET", "change-me")
    splink_endpoint_url: str = _env("SPLINK_ENDPOINT_URL")
    splink_match_limit: int = _env_int("SPLINK_MATCH_LIMIT", 10)

    # Status streaming. This is only a fallback for a missed/duplicate Signals
    # webhook delivery -- the push path (pipeline_broadcast) carries most updates --
    # so it doesn't need to be sub-second.
    ws_poll_seconds: float = float(_env("WS_POLL_SECONDS", "3.0"))
    signals_pipeline_publisher_url: str = _env("SIGNALS_PIPELINE_PUBLISHER_URL")
    internal_shared_secret: str = _env("SPLINK_SHARED_SECRET", "change-me")

    # Watchdog: a run stuck in QUEUED/RUNNING with no progress for this long is
    # presumed lost (job never executed -- cold start failure, platform drop, queue
    # never delivered it) and gets swept to FAILED. REVIEW_PENDING is untouched --
    # that's a legitimate idle-until-officer-clicks-proceed state, not stale.
    run_stale_timeout_seconds: int = _env_int("RUN_STALE_TIMEOUT_SECONDS", 600)


settings = Settings()

