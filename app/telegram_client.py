import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class TelegramClient:
    def __init__(self, bot_token: str):
        """
        Initialize Telegram API client
        """
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.client = httpx.Client(timeout=20.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict | None = None,
        reply_to_message_id: int | None = None,
        ) -> dict:
        """
        Send text message via Telegram bot API
        """
        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id

        resp = self.client.post(f"{self.base_url}/sendMessage", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {data}")
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def get_updates(self, offset: int | None = None, timeout: int = 1) -> list[dict]:
        """
        Send json request to get new messages in Telegram bot
        """
        payload = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset

        resp = self.post_json("getUpdates", payload)
        return resp.get("result", [])

    def post_json(self, method: str, payload: dict) -> dict:
        """
        Send API POST request
        """
        resp = self.client.post(f"{self.base_url}/{method}", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error on {method}: {data}")
        return data

    @staticmethod
    def extract_message(update: dict) -> dict | None:
        """
        Get message from one update
        """
        return update.get("message") or update.get("edited_message")

    @staticmethod
    def extract_command(update: dict) -> tuple[str | None, int | None, int | None]:
        """
        Extracts message, chat_id, user_id
        """
        message = TelegramClient.extract_message(update)
        if not message:
            return None, None, None

        text = message.get("text")
        if not text:
            return None, None, None

        chat_id = message.get("chat", {}).get("id")
        user_id = message.get("from", {}).get("id")
        return text.strip(), chat_id, user_id