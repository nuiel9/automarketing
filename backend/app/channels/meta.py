import httpx

from app.channels.base import ChannelAuthError, ChannelError, PublishOutcome, PublishRequest
from app.config import Settings

GRAPH = "https://graph.facebook.com/v21.0"


class MetaAdapter:
    def __init__(self, settings: Settings):
        self.page_id = settings.meta_page_id
        self.ig_user_id = settings.meta_ig_user_id
        self.token = settings.meta_access_token

    def _check(self, resp: httpx.Response) -> dict:
        if resp.status_code >= 500:
            raise ChannelError(f"meta {resp.status_code}")
        if resp.status_code >= 400:
            try:
                data = resp.json()
            except ValueError:
                # A proxy/WAF in front of the Graph API can return a non-JSON
                # (e.g. HTML) error body. Fall back to a generic ChannelError
                # instead of letting a raw JSONDecodeError escape the adapter.
                raise ChannelError(f"meta {resp.status_code}")
            err = data.get("error", {})
            if err.get("code") == 190:  # invalid/expired token
                raise ChannelAuthError(err.get("message", "token invalid"))
            raise ChannelError(err.get("message", f"meta {resp.status_code}"))
        return resp.json()

    def publish(self, req: PublishRequest) -> PublishOutcome:
        if req.channel == "facebook":
            data = self._check(
                httpx.post(
                    f"{GRAPH}/{self.page_id}/videos",
                    data={
                        "file_url": req.media_url,
                        "description": req.body,
                        "access_token": self.token,
                    },
                    timeout=60,
                )
            )
            return PublishOutcome(status="posted", post_ref=data["id"])

        if req.channel == "instagram":
            state = req.state or {}
            if "creation_id" not in state:
                data = self._check(
                    httpx.post(
                        f"{GRAPH}/{self.ig_user_id}/media",
                        data={
                            "media_type": "REELS",
                            "video_url": req.media_url,
                            "caption": req.body,
                            "access_token": self.token,
                        },
                        timeout=60,
                    )
                )
                return PublishOutcome(status="pending", state={"creation_id": data["id"]})

            creation_id = state["creation_id"]
            status = self._check(
                httpx.get(
                    f"{GRAPH}/{creation_id}",
                    params={"fields": "status_code", "access_token": self.token},
                    timeout=30,
                )
            )
            code = status.get("status_code")
            if code == "FINISHED":
                data = self._check(
                    httpx.post(
                        f"{GRAPH}/{self.ig_user_id}/media_publish",
                        data={"creation_id": creation_id, "access_token": self.token},
                        timeout=60,
                    )
                )
                return PublishOutcome(status="posted", post_ref=data["id"])
            if code == "ERROR":
                raise ChannelError("instagram container processing failed")
            return PublishOutcome(status="pending", state=state)

        raise ChannelError(f"MetaAdapter cannot publish channel {req.channel}")
