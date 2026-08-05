import json

from app.channels.base import PublishRequest
from app.channels.dryrun import DryRunAdapter


def test_dryrun_appends_jsonl_and_returns_ref(tmp_path):
    adapter = DryRunAdapter(str(tmp_path / "feed.jsonl"))
    req = PublishRequest(
        item_id="abc", channel="dryrun", title=None, body="สวัสดี", media_url=None, state=None
    )
    out1 = adapter.publish(req)
    out2 = adapter.publish(req)
    assert out1.status == "posted" and out1.post_ref == "dryrun-1"
    assert out2.post_ref == "dryrun-2"
    lines = (tmp_path / "feed.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["body"] == "สวัสดี"
