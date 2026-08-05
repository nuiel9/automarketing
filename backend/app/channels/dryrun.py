import json
import os

from app.channels.base import PublishOutcome, PublishRequest


class DryRunAdapter:
    def __init__(self, feed_path: str):
        self.feed_path = feed_path
        os.makedirs(os.path.dirname(feed_path) or ".", exist_ok=True)

    def publish(self, req: PublishRequest) -> PublishOutcome:
        count = 0
        if os.path.exists(self.feed_path):
            with open(self.feed_path, encoding="utf-8") as f:
                count = sum(1 for _ in f)
        with open(self.feed_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"item_id": req.item_id, "body": req.body}, ensure_ascii=False) + "\n")
        return PublishOutcome(status="posted", post_ref=f"dryrun-{count + 1}")
