from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from tenacity import retry, stop_after_attempt, wait_exponential


SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


class YouTubeClient:

    def __init__(self, client_secret_path: str, token_path: str):
        """
        Initialize YouTube client and authorized service
        """
        self.client_secret_path = client_secret_path
        self.token_path = token_path
        self.service = self._build_service()

    def _build_service(self):
        """
        Initialize authorization and API client
        """
        creds = None
        token_file = Path(self.token_path)

        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.client_secret_path, SCOPES)
                creds = flow.run_local_server(port=0)

            token_file.write_text(creds.to_json(), encoding="utf-8")

        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def list_comment_threads(
        self,
        *,
        channel_id: str,
        fetch_limit: int,
        text_format: str,
    ) -> list[dict]:
        """
        Get top-level comments
        """
        print("Getting top-level comments")
        response = (
            self.service.commentThreads()
            .list(
                part="snippet,replies",
                allThreadsRelatedToChannelId=channel_id,
                order="time",
                textFormat=text_format,
                maxResults=fetch_limit,
            )
            .execute()
        )
        return response.get("items", [])

    def reject_comments(self, comment_ids: list[str]) -> None:
        """
        Reject selected comments
        """
        if not comment_ids:
            return
        print(f"Rejecting {len(comment_ids)} comments.")
        (
            self.service.comments()
            .setModerationStatus(
                id=",".join(comment_ids),
                moderationStatus="rejected",
                # banAuthor=True,
            )
            .execute()
        )