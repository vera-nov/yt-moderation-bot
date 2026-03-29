from datetime import datetime, timezone


class CleanupService:
    """
    Service for deleting old records in the database.
    Runs once a day.
    """
    def __init__(self, store, processed_ttl_days: int, audit_ttl_days: int):
        """
        Initialize cleanup service settings
        """
        self.store = store
        self.processed_ttl_days = processed_ttl_days
        self.audit_ttl_days = audit_ttl_days
        self._last_cleanup_day: str | None = None

    def run_if_needed(self) -> None:
        """
        Run daily cleanup once per UTC day
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_cleanup_day == today:
            return

        self.store.cleanup_old_records(
            processed_ttl_days=self.processed_ttl_days,
            audit_ttl_days=self.audit_ttl_days,
        )
        self._last_cleanup_day = today