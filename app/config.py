from dataclasses import dataclass
from dotenv import load_dotenv
import os

load_dotenv()


def _get_bool(name: str, default: str = "false") -> bool:
    """
    Read boolean value from environment variable
    """
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    yt_channel_id: str
    yt_fetch_limit: int
    yt_poll_interval_sec: int
    yt_text_format: str
    yt_quota_daily_limit: int
    yt_quota_stop_percent: float
    yt_min_comment_age_sec: int
    enable_reply_scan: bool
    moderation_batch_size: int
    dry_run: bool
    tg_bot_token: str
    tg_admin_chat_id: int
    processed_ttl_days: int
    audit_ttl_days: int
    stop_words_file: str
    sqlite_path: str
    client_secret_path: str
    token_path: str


def load_settings() -> Settings:
    """
    Load bot settings from environment variables
    """
    return Settings(
        yt_channel_id=os.environ["YT_CHANNEL_ID"],
        yt_fetch_limit=int(os.getenv("YT_FETCH_LIMIT", "100")),
        yt_poll_interval_sec=int(os.getenv("YT_POLL_INTERVAL_SEC", "60")),
        yt_text_format=os.getenv("YT_TEXT_FORMAT", "plainText"),
        yt_quota_daily_limit=int(os.getenv("YT_QUOTA_DAILY_LIMIT", "10000")),
        yt_quota_stop_percent=float(os.getenv("YT_QUOTA_STOP_PERCENT", "0.9")),
        yt_min_comment_age_sec=int(os.getenv("YT_MIN_COMMENT_AGE_SEC", "300")),
        enable_reply_scan=_get_bool("ENABLE_REPLY_SCAN", "true"),
        moderation_batch_size=int(os.getenv("MODERATION_BATCH_SIZE", "50")),
        dry_run=_get_bool("DRY_RUN", "false"),
        tg_bot_token=os.environ["TG_BOT_TOKEN"],
        tg_admin_chat_id=int(os.environ["TG_ADMIN_CHAT_ID"]),
        processed_ttl_days=int(os.getenv("PROCESSED_TTL_DAYS", "30")),
        audit_ttl_days=int(os.getenv("AUDIT_TTL_DAYS", "30")),
        stop_words_file=os.getenv("STOP_WORDS_FILE", "./stop_words.txt"),
        sqlite_path=os.getenv("SQLITE_PATH", "./state.sqlite"),
        client_secret_path=os.getenv("CLIENT_SECRET_PATH", "./client_secret.json"),
        token_path=os.getenv("TOKEN_PATH", "./token.json"),
    )