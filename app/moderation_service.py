from datetime import datetime, timedelta, timezone


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class ModerationService:
    def __init__(self, settings, store, youtube, telegram, rules, quota):
        self.settings = settings
        self.store = store
        self.youtube = youtube
        self.telegram = telegram
        self.rules = rules
        self.quota = quota

    def run_iteration(self) -> None:
        """
        One bot run cycle: get new comments, reject upon matching, write to db and Telegram bot
        """
        # check whether bot is active
        bot_state = self.store.get_bot_state()
        if not bot_state["enabled"]:
            return
        if bot_state["state"] not in {"ACTIVE", "DRY_RUN"}:
            return
        if not bot_state["enabled_at"]:
            return

        enabled_at = parse_utc(bot_state["enabled_at"])
        comment_cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.settings.yt_min_comment_age_sec)
        dry_run = bot_state["state"] == "DRY_RUN"

        # if next API call hits the quota threshold, pause the bot first
        if self.quota.will_hit_threshold_with(1):
            self._pause_for_quota(self.quota.get_status())
            return

        # get latest comments
        items = self.youtube.list_comment_threads(
            channel_id=self.settings.yt_channel_id,
            fetch_limit=self.settings.yt_fetch_limit,
            text_format=self.settings.yt_text_format,
        )
        quota_status = self.quota.charge_comment_threads_list()

        if quota_status["units_spent"] >= quota_status["stop_units"]:
            flush_quota_status = self.flush_before_disable()
            self._pause_for_quota(flush_quota_status or self.quota.get_status())
            return

        for item in items:
            # first: check top-level comment
            top = self._extract_top_level(item)

            top_published_at = parse_utc(top["published_at"])

            if top_published_at > comment_cutoff:
                continue

            if top_published_at < enabled_at:
                break

            existing_top = self.store.get_processed_comment(top["comment_id"])
            top_was_rejected = False

            if existing_top:
                top_was_rejected = existing_top["processed_result"] in {
                    "rejected",
                    "dry_run_reject",
                    "pending_reject",
                }
            else:
                matched_word = self.rules.match(top["text"])
                if matched_word:
                    top_was_rejected = True
                    candidate = {
                        **top,
                        "comment_type": "top_level",
                        "matched_word": matched_word,
                    }
                    if dry_run:
                        self._finalize_dry_run(candidate)
                    else:
                        self._save_pending(candidate)
                        if self.store.get_pending_rejections_count() >= self.settings.moderation_batch_size:
                            quota_status = self._reject_pending_batch(self.settings.moderation_batch_size)
                            if quota_status and quota_status["units_spent"] >= quota_status["stop_units"]:
                                flush_quota_status = self.flush_before_disable()
                                self._pause_for_quota(flush_quota_status or self.quota.get_status())
                                return
                else:
                    self.store.add_processed_comment(
                        comment_id=top["comment_id"],
                        comment_type="top_level",
                        thread_id=top["thread_id"],
                        parent_comment_id=None,
                        video_id=top["video_id"],
                        published_at=top["published_at"],
                        processed_result="ignored",
                        rule_name=None,
                    )

            if top_was_rejected:
                continue

            if not self.settings.enable_reply_scan:
                continue

            for reply in self._extract_replies(item, top["comment_id"]):
                reply_published_at = parse_utc(reply["published_at"])

                if reply_published_at > comment_cutoff:
                    continue

                if reply_published_at < enabled_at:
                    continue

                existing_reply = self.store.get_processed_comment(reply["comment_id"])
                if existing_reply:
                    continue

                matched_word = self.rules.match(reply["text"])
                if matched_word:
                    candidate = {
                        **reply,
                        "comment_type": "reply",
                        "matched_word": matched_word,
                    }
                    if dry_run:
                        self._finalize_dry_run(candidate)
                    else:
                        self._save_pending(candidate)
                        if self.store.get_pending_rejections_count() >= self.settings.moderation_batch_size:
                            quota_status = self._reject_pending_batch(self.settings.moderation_batch_size)
                            if quota_status and quota_status["units_spent"] >= quota_status["stop_units"]:
                                flush_quota_status = self.flush_before_disable()
                                self._pause_for_quota(flush_quota_status or self.quota.get_status())
                                return
                else:
                    self.store.add_processed_comment(
                        comment_id=reply["comment_id"],
                        comment_type="reply",
                        thread_id=reply["thread_id"],
                        parent_comment_id=reply["parent_comment_id"],
                        video_id=reply["video_id"],
                        published_at=reply["published_at"],
                        processed_result="ignored",
                        rule_name=None,
                    )

        quota_status = self.quota.get_status()
        if quota_status["units_spent"] >= quota_status["stop_units"]:
            self._pause_for_quota(quota_status)

    def _save_pending(self, item: dict) -> None:
        """
        Updates pending for rejections table in db
        """
        self.store.add_processed_comment(
            comment_id=item["comment_id"],
            comment_type=item["comment_type"],
            thread_id=item["thread_id"],
            parent_comment_id=item.get("parent_comment_id"),
            video_id=item.get("video_id"),
            published_at=item["published_at"],
            processed_result="pending_reject",
            rule_name=item["matched_word"],
            text=item.get("text"),
            author_display_name=item.get("author_display_name"),
            author_channel_id=item.get("author_channel_id"),
        )
        self.store.append_audit_log(
            event_type="PENDING_MATCH",
            payload=item,
        )

    def _reject_pending_batch(self, limit: int) -> dict | None:
        """
        Reject comments (call API, write to db, log in Telegram)
        """
        batch = self.store.get_pending_rejections(limit)
        if not batch:
            return None

        if len(batch) == 1:
            return self._reject_single_comment(batch[0])

        # if self.quota.will_hit_threshold_with(50):
        #     self._pause_for_quota(self.quota.get_status())
        #     return

        ids = [item["comment_id"] for item in batch]

        try:
            self.youtube.reject_comments(ids)
        except Exception as exc:
            return self._reject_comments_one_by_one(batch, exc)

        quota_status = self.quota.charge_moderation_call()
        self.store.mark_comments_rejected(ids)

        for item in batch:
            self.store.append_audit_log(
                event_type="COMMENT_REJECTED",
                payload=item,
            )
            self._send_telegram_message_safe(
                self._format_comment_message(item, quota_status, dry_run=False),
            )

        return quota_status

    def _reject_comments_one_by_one(self, batch: list[dict], batch_error: Exception) -> dict | None:
        """
        Reject comments one by one if batch reject was not successful
        """
        self._send_telegram_message_safe(
            f"YT ERROR: batch reject failed, fallback to single reject: {batch_error}",
        )

        last_quota_status = None
        for item in batch:
            quota_status = self._reject_single_comment(item)
            if quota_status is not None:
                last_quota_status = quota_status

        return last_quota_status

    def _reject_single_comment(self, item: dict) -> dict | None:
        """
        Reject one comment, mark reject_failed upon YT error
        """
        comment_id = item["comment_id"]
        # if self.quota.will_hit_threshold_with(50):
        #     self._pause_for_quota(self.quota.get_status())
        #     return

        try:
            self.youtube.reject_comments([comment_id])
        except Exception as exc:
            self.store.mark_comments_reject_failed([comment_id])
            self.store.append_audit_log(
                event_type="COMMENT_REJECT_FAILED",
                payload={**item, "error": str(exc)},
            )
            self._send_telegram_message_safe(
                f"YT ERROR: reject failed for commentId={comment_id}: {exc}",
            )
            return None

        quota_status = self.quota.charge_moderation_call()
        self.store.mark_comments_rejected([comment_id])
        self.store.append_audit_log(
            event_type="COMMENT_REJECTED",
            payload=item,
        )
        self._send_telegram_message_safe(
            self._format_comment_message(item, quota_status, dry_run=False),
        )
        return quota_status

    def flush_before_disable(self) -> dict | None:
        pending_count = self.store.get_pending_rejections_count()
        if pending_count == 0:
            return None
        return self._reject_pending_batch(pending_count)
    
    def _finalize_dry_run(self, item: dict) -> None:
        """
        'Reject' comments in dry run mode (write to db, log in Telegram)
        """
        quota_status = self.quota.get_status()

        self.store.add_processed_comment(
            comment_id=item["comment_id"],
            comment_type=item["comment_type"],
            thread_id=item["thread_id"],
            parent_comment_id=item.get("parent_comment_id"),
            video_id=item.get("video_id"),
            published_at=item["published_at"],
            processed_result="dry_run_reject",
            rule_name=item["matched_word"],
        )
        self.store.append_audit_log(
            event_type="DRY_RUN_MATCH",
            payload=item,
        )
        self.telegram.send_message(
            self.settings.tg_admin_chat_id,
            self._format_comment_message(item, quota_status, dry_run=True),
        )

    def _send_telegram_message_safe(self, text: str) -> None:
        """
        Send log to Telegram, do not stop bot upon TG error
        """
        try:
            self.telegram.send_message(self.settings.tg_admin_chat_id, text)
        except Exception:
            pass

    def _pause_for_quota(self, quota_status: dict) -> None:
        """
        Pause the bot if quota will be reached soon, send log to Telegram
        """
        if not quota_status["warning_sent"]:
            self.telegram.send_message(
                self.settings.tg_admin_chat_id,
                (
                    "QUOTA_WARNING\n"
                    f"units_spent={quota_status['units_spent']}\n"
                    f"limit={quota_status['daily_limit']}\n"
                    f"percent={quota_status['percent']}%\n"
                    "Бот переведен в QUOTA_PAUSED."
                ),
            )
            self.quota.mark_warning_sent()

        self.store.set_quota_paused()

    def _extract_top_level(self, item: dict) -> dict:
        """
        Get the top level comment info
        """
        top_obj = item["snippet"]["topLevelComment"]
        sn = top_obj["snippet"]
        author_channel = sn.get("authorChannelId", {})
        if isinstance(author_channel, dict):
            author_channel = author_channel.get("value")

        return {
            "thread_id": item["id"],
            "video_id": item["snippet"].get("videoId"),
            "comment_id": top_obj["id"],
            "text": sn.get("textDisplay", ""),
            "author_display_name": sn.get("authorDisplayName", ""),
            "author_channel_id": author_channel,
            "like_count": sn.get("likeCount", 0),
            "published_at": sn["publishedAt"],
        }

    def _extract_replies(self, item: dict, parent_comment_id: str) -> list[dict]:
        """
        Get replies info
        """
        result = []
        for reply in item.get("replies", {}).get("comments", []):
            sn = reply["snippet"]
            author_channel = sn.get("authorChannelId", {})
            if isinstance(author_channel, dict):
                author_channel = author_channel.get("value")

            result.append(
                {
                    "thread_id": item["id"],
                    "video_id": sn.get("videoId"),
                    "comment_id": reply["id"],
                    "parent_comment_id": parent_comment_id,
                    "text": sn.get("textDisplay", ""),
                    "author_display_name": sn.get("authorDisplayName", ""),
                    "author_channel_id": author_channel,
                    "like_count": sn.get("likeCount", 0),
                    "published_at": sn["publishedAt"],
                }
            )
        return result

    def _format_comment_message(self, item: dict, quota_status: dict, dry_run: bool) -> str:
        event_type = "REPLY_REJECTED" if item["comment_type"] == "reply" else "TOP_LEVEL_REJECTED"
        matched_word = item.get("matched_word") or item.get("rule_name")
        text = item.get("text", "")
        author_display_name = item.get("author_display_name", "")
        author_channel_id = item.get("author_channel_id")

        return (
            f"{event_type}\n"
            f"dry_run={str(dry_run).lower()}\n"
            f"text={text}\n"
            f"authorDisplayName={author_display_name}\n"
            f"authorChannelId={author_channel_id}\n"
            f"commentId={item['comment_id']}\n"
            f"videoId={item.get('video_id')}\n"
            f"matchedWord={matched_word}\n"
            f"publishedAt={item['published_at']}\n"
            f"quotaSpentToday={quota_status['units_spent']}"
        )

    def flush_ready_pending_batches(self) -> bool:
        """
        Reject all full pending batches even if no new comments were found.
        Returns True if the bot was paused because of quota.
        """
        bot_state = self.store.get_bot_state()
        if not bot_state["enabled"]:
            return False
        if bot_state["state"] not in {"ACTIVE", "DRY_RUN"}:
            return False
        if bot_state["state"] == "DRY_RUN":
            return False

        while self.store.get_pending_rejections_count() >= self.settings.moderation_batch_size:
            quota_status = self._reject_pending_batch(self.settings.moderation_batch_size)

            if quota_status and quota_status["units_spent"] >= quota_status["stop_units"]:
                flush_quota_status = self.flush_before_disable()
                self._pause_for_quota(flush_quota_status or self.quota.get_status())
                return True

        return False