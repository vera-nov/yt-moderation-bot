import time

from app.cleanup_service import CleanupService
from app.config import load_settings
from app.moderation_service import ModerationService
from app.quota_manager import QuotaManager
from app.rules_engine import RulesEngine
from app.state_store import StateStore
from app.telegram_client import TelegramClient
from app.youtube_client import YouTubeClient

from tenacity import RetryError
from googleapiclient.errors import HttpError

def build_activation_message(store, quota) -> str:
    bot_state = store.get_bot_state()
    quota_status = quota.get_status()
    counts = store.get_today_counts()

    return (
        "Бот активирован\n"
        f"state={bot_state['state']}\n"
        f"enabled={str(bot_state['enabled']).lower()}\n"
        f"enabled_at={bot_state['enabled_at']}\n"
        f"dry_run={str(bot_state['dry_run']).lower()}\n"
        f"units_spent={quota_status['units_spent']}\n"
        f"daily_limit={quota_status['daily_limit']}\n"
        f"quota_percent={quota_status['percent']}%\n"
        f"stop_units={quota_status['stop_units']}\n"
        f"processed_today={counts['processed_today']}\n"
        f"rejected_today={counts['rejected_today']}"
    )
    
def process_telegram_commands(settings, store, telegram, quota, moderation) -> None:
    offset = store.get_last_update_id() + 1
    updates = telegram.get_updates(offset=offset, timeout=1)

    for update in updates:
        store.set_last_update_id(update["update_id"])

        text, chat_id, user_id = telegram.extract_command(update)
        if not text:
            continue

        if chat_id != settings.tg_admin_chat_id or user_id != settings.tg_admin_user_id:
            continue

        if text == "/enable":
            current = store.get_bot_state()
            store.reset_session_data()
            enabled_at = store.enable_bot(dry_run=current["dry_run"])
            telegram.send_message(
                chat_id,
                f"Бот включен.\nstate={'DRY_RUN' if current['dry_run'] else 'ACTIVE'}\nenabled_at={enabled_at}",
            )

        elif text == "/disable":
            moderation.flush_before_disable()
            store.disable_bot()
            telegram.send_message(chat_id, "Бот выключен. state=OFF")

        elif text == "/dryrun_on":
            store.set_dry_run(True)
            state = store.get_bot_state()
            telegram.send_message(chat_id, f"dry_run=true\nstate={state['state']}")

        elif text == "/dryrun_off":
            store.set_dry_run(False)
            state = store.get_bot_state()
            telegram.send_message(chat_id, f"dry_run=false\nstate={state['state']}")

        elif text == "/quota":
            quota_status = quota.get_status()
            telegram.send_message(
                chat_id,
                (
                    "Quota status\n"
                    f"units_spent={quota_status['units_spent']}\n"
                    f"daily_limit={quota_status['daily_limit']}\n"
                    f"percent={quota_status['percent']}%\n"
                    f"stop_units={quota_status['stop_units']}"
                ),
            )

        elif text == "/status":
            bot_state = store.get_bot_state()
            quota_status = quota.get_status()
            counts = store.get_today_counts()
            telegram.send_message(
                chat_id,
                (
                    "Bot status\n"
                    f"state={bot_state['state']}\n"
                    f"enabled={str(bot_state['enabled']).lower()}\n"
                    f"enabled_at={bot_state['enabled_at']}\n"
                    f"dry_run={str(bot_state['dry_run']).lower()}\n"
                    f"units_spent={quota_status['units_spent']}\n"
                    f"quota_percent={quota_status['percent']}%\n"
                    f"processed_today={counts['processed_today']}\n"
                    f"rejected_today={counts['rejected_today']}"
                ),
            )


def main() -> None:
    settings = load_settings()

    store = StateStore(settings.sqlite_path)
    store.init_db(dry_run=settings.dry_run)

    telegram = TelegramClient(settings.tg_bot_token)
    youtube = YouTubeClient(settings.client_secret_path, settings.token_path)
    rules = RulesEngine(settings.stop_words_file)
    quota = QuotaManager(store, settings.yt_quota_daily_limit, settings.yt_quota_stop_percent)
    cleanup = CleanupService(store, settings.processed_ttl_days, settings.audit_ttl_days)
    moderation = ModerationService(settings, store, youtube, telegram, rules, quota)

    print("Initialization completed, bot active")

    tg_poll_interval_sec = 5
    next_tg_poll = 0.0
    next_yt_poll = 0.0

    while True:
        now = time.monotonic()

        if now >= next_tg_poll:
            try:
                process_telegram_commands(settings, store, telegram, quota, moderation)
            except Exception as exc:
                try:
                    telegram.send_message(settings.tg_admin_chat_id, f"TG ERROR: {exc}")
                except Exception:
                    pass
                print(f"TG ERROR: {exc}", flush=True)
            next_tg_poll = now + tg_poll_interval_sec

        if now >= next_yt_poll:
            try:
                current = store.get_bot_state()
                pending_before = store.get_pending_rejections_count()

                print(
                    f"Running iteration... dry_run={current['dry_run']} pending_reject={pending_before}",
                    flush=True,
                )

                if pending_before >= settings.moderation_batch_size:
                    moderation.flush_ready_pending_batches() 
                    pending_after = store.get_pending_rejections_count()
                    print(f"After flush: pending_reject={pending_after}", flush=True)

                    next_yt_poll = time.monotonic() + settings.yt_poll_interval_sec
                    continue

                moderation.run_iteration()
                cleanup.run_if_needed()

            except Exception as exc:
                details = str(exc)

                if isinstance(exc, RetryError):
                    inner = exc.last_attempt.exception()
                    details = str(inner)

                    if isinstance(inner, HttpError):
                        body = inner.content.decode("utf-8", errors="ignore")
                        details = f"HttpError status={inner.resp.status} body={body}"

                try:
                    telegram.send_message(settings.tg_admin_chat_id, f"YT ERROR: {details}")
                except Exception:
                    pass

                print(f"YT ERROR: {details}", flush=True)
            next_yt_poll = now + settings.yt_poll_interval_sec

        time.sleep(1)

if __name__ == "__main__":
    main()