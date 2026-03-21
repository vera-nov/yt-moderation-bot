from math import ceil


class QuotaManager:
    """
    Manage daily quota
    """
    def __init__(self, store, daily_limit: int, stop_percent: float):
        self.store = store
        self.daily_limit = daily_limit
        self.stop_percent = stop_percent

    def get_status(self) -> dict:
        usage = self.store.get_quota_usage_today()
        stop_units = ceil(self.daily_limit * self.stop_percent)
        percent = (usage["units_spent"] / self.daily_limit * 100) if self.daily_limit else 0.0
        return {
            "units_spent": usage["units_spent"],
            "warning_sent": usage["warning_sent"],
            "daily_limit": self.daily_limit,
            "stop_percent": self.stop_percent,
            "stop_units": stop_units,
            "percent": round(percent, 2),
        }

    def will_hit_threshold_with(self, units: int) -> bool:
        """
        Calculate whether next call will hit the limit
        """
        status = self.get_status()
        return status["units_spent"] + units >= status["stop_units"]

    def charge_comment_threads_list(self) -> dict:
        """
        Add units for using CommentThreads
        """
        self.store.add_quota_units(1)
        return self.get_status()

    def charge_moderation_call(self) -> dict:
        """
        Add units for using setModerationStatus
        """
        self.store.add_quota_units(50)
        return self.get_status()

    def mark_warning_sent(self) -> None:
        self.store.set_quota_warning_sent(True)