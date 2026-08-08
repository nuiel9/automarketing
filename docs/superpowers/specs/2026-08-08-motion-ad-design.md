# Motion Ad format — design

**Status:** approved 2026-08-08
**Builds on:** `2026-08-05-automarketing-design.md` (Phase 1 spine), `2026-08-05-video-factory-design.md` (Phase 2)

## Goal

Add a third renderable format, `motion_ad`, that produces an 11-second branded
vertical spot by calling AIVDO's Motion Ad pipeline, so Eduverse One can post
short punchy ads alongside the existing `tips` cards and `demo` walkthroughs.

## What a Motion Ad is, and is not

Every number here was verified against AIVDO's source and one live render
(job `dcaa45b5…`, 2026-08-08) rather than inferred:

- **Fixed 11 seconds**, 1080×1920, h264 + 48kHz AAC. Not configurable.
- The voiceover script must read aloud in ~8s — **under ~110 Thai characters**.
- **A photo is mandatory** (1–3 data URIs, `image/png|jpeg|jpg`).
- **5 credits per ad**, deducted at dispatch.
- Renders in roughly 2 minutes.

It is therefore *not* a replacement for the ~20s `demo` walkthrough or the
longer `tips` video. It is a third, distinct format that shares the item
lifecycle but produces a different kind of asset.

## Architecture

`motion_ad` reuses the existing item lifecycle, review queue, channel adapters
and LINE alerting, and runs inside the same `automarketing-render` Cloud Run
job. It **bypasses `compose()` entirely** — AIVDO returns a finished MP4, so
there are no subtitles, no AutoMarketing-side music bed, and no hook overlay on
this path. That keeps the two pipelines from interleaving.

Three new modules, each with one responsibility:

| Module | Responsibility | Depends on |
|---|---|---|
| `app/video/shot.py` | Screenshot a public URL into a square PNG | Playwright |
| `app/video/ad_copy.py` | Write the 8 AIVDO copy fields in Eduverse's voice | Gemini, `strategy.yaml` |
| `app/video/aivdo.py` | Generate → poll → fetch against AIVDO's API | httpx |

`app/video/worker.py` orchestrates them for `item.format == "motion_ad"`.

### Data flow

```
capture square screenshot of eduverse.one/th   (shot.py)
      ↓ PNG bytes → data URI
Gemini writes 8 copy fields from item.topic    (ad_copy.py)
      ↓
banned-words gate  ──fail──▶ item.failed, no credits spent
      ↓ pass
POST /api/ads/generate                          (aivdo.py)
      ↓ {job_id, credits_used, credits_remaining}
persist job_id on the item  ← commit before polling
      ↓
poll GET /api/jobs/{job_id} until terminal
      ↓ output_url (GCS v4 signed URL)
download → upload to our GCS → item.media_path → in_review
```

The banned-words gate runs **before** the API call, so a brand-voice violation
costs zero credits. This ordering is only possible because
`/api/ads/generate` renders "the PRE-APPROVED style+copy directly (no
re-analyze)" (`aivdo/worker.py`) — the copy we send is the copy that ships,
confirmed by the live render reproducing our text verbatim. AIVDO's own Gemini
copywriter belongs to a different endpoint we do not call, so our brand voice
and banned-words list remain authoritative.

## The photo

`shot.py` captures **a square image, not 9:16**. In the `blueprint` template
the photo is not a full-bleed background: `#spec` is positioned
`left:120px; right:120px; top:360px; height:820px`, an 840×820 window with the
ad copy drawn *outside* it, and `#photo` uses `object-fit: cover`. Feeding it a
1080×1920 capture would centre-crop to a narrow horizontal band of the page.

Because the copy sits outside the frame, a screenshot carrying the site's own
Thai text does **not** collide with the ad copy — verified in the live render.

Capture uses no login. That is a deliberate constraint, not an accident: it
keeps the demo account's credentials out of this path entirely and avoids the
goal-accumulation side effect that the `demo` scenario has on the production
account.

Default target: `https://eduverse.one/th`, viewport 540×528 at
`device_scale_factor=2`, `wait_until="networkidle"` plus a settle delay, giving
a ~1080×1056 PNG.

## The copy

`ad_copy.py` mirrors `tips.py`: Gemini reads `item.topic` and `strategy.yaml`'s
voice and audiences, and returns a validated model with exactly these fields,
each truncated to AIVDO's own cap so the API never silently trims:

| Field | Cap | Content |
|---|---|---|
| `kicker` | 120 | short category line |
| `name` | 120 | brand name (`Eduverse One`) |
| `tagline` | 120 | one-line promise |
| `hl1`, `hl2` | 120 each | two benefit lines |
| `promo` | 120 | offer line |
| `cta` | 120 | action + destination |
| `vo_script` | 160 | Thai voiceover, **under ~110 characters** so it fits 8s |

`banned_violations()` runs over the concatenation of all eight. A violation
fails the item with the matched words, before any credits are spent.

## The client

`aivdo.py` wraps three calls. Auth is `X-API-Key` on every request —
`get_current_user` accepts a key in place of a JWT, and `require_verified_email`
chains off it, so a key alone suffices for generation.

**Generate** — `POST /api/ads/generate` (rate limit 5/min):

```json
{"photos": ["data:image/png;base64,…"], "brief": "…", "style": "blueprint",
 "copy": {…8 fields…}, "voice": "Charon", "gender": "male",
 "music_track": "inspiration"}
```

`style` defaults to `blueprint` — AIVDO's own template for
"courses, education, B2B — structured, technical, clean grid".
`voice` defaults to `Charon`, which is in AIVDO's `VOICE_REGISTRY` as
male/Informative and is the same Gemini TTS voice Phase 2 uses for Kavee, so
the ads sound like the rest of the channel. `gender: "male"` matches Charon so
AIVDO's Thai particle correction produces ครับ.

Returns `{job_id, credits_used, credits_remaining}`. Log
`credits_remaining` at INFO on every render — it is the only visibility we get
into the budget.

**Poll** — `GET /api/jobs/{job_id}` (60/min) returns
`{job_id, status, progress, current_stage, message, output_url, error}`.
Statuses observed and in source: `queued` → `running` → `completed`, plus
`failed` and `retrying`; the terminal set is `{completed, failed, canceled}`.
Poll every 10s up to `aivdo_poll_timeout` (default 15 minutes — a healthy
render takes ~2).

**Fetch** — `output_url` is a **GCS v4 signed URL** on `storage.googleapis.com`
(7-day expiry free tier, 30-day paid), fetchable with a plain GET and no
credentials. Verified live: `200 video/mp4`. Download it and re-upload through
our own `MediaStore` so the item's media does not depend on someone else's
signed URL expiring.

## Not spending credits twice

Credits are deducted at dispatch and refunded **only if dispatch itself
fails**. Once the Celery task is queued, a crash on our side costs 5 credits
regardless. Two consequences shape the design:

1. **Persist `aivdo_job_id` on the item, committed before polling begins.** If
   our render job dies mid-poll, a retry resumes polling the existing job
   instead of generating a new one. This is the only change requiring a
   **migration** (`content_items.aivdo_job_id`, nullable string).
2. The publisher's existing 20-minute stuck-render sweep would otherwise
   re-dispatch a `motion_ad` render and spend another 5 credits. With the
   job id persisted, the re-dispatch resumes.

Known AIVDO-side gap that motivates our own timeout: `sweep_stalled_jobs`
selects only `Job.status == "running"`, so a job that dies before the
`queued → running` write is never swept and never refunded. We must not rely on
AIVDO to fail a stuck job for us.

## Music

For this format we pass a **track id** to AIVDO, which builds its own bed at
−33 LUFS. The mp3 is never needed locally. Therefore:

- `strategy.yaml` gains `music.motion_ad: [<track ids>]`, and
  `MusicConfig.for_format` must be extended to map it — it currently maps only
  `tips` and `demo` and returns `[]` for anything else, which would silently
  mean "no music" here.
- Selection must **not** reuse `pick_track`, which requires the file on disk
  and would silently return `None` — shipping every ad with the template's
  default bed. Add `pick_track_id(track_ids, key) -> str | None` in
  `app/video/music.py`: same deterministic item-id hashing as `pick_track`,
  same id validation, but no filesystem check, returning the bare id.
- `render/fetch_music.py` must keep downloading only `tips` and `demo` tracks.
  Adding `motion_ad` ids to its fetch list would bloat the image with files
  nothing reads.

## Errors

All failures follow the existing path: set `item.render_error`, transition to
`failed`, and fire the LINE alert.

| Condition | Handling |
|---|---|
| Banned words | Fail before the API call. Message lists the matched words. **No credits spent.** |
| `400` moderation | Fail with AIVDO's `Content blocked: {category}` detail. No credits spent (AIVDO moderates before deducting). |
| `402` | Out of credits. Message states how many are needed. Distinct wording so the founder can top up. |
| `429` | Retry with backoff inside the client (limit is 5/min). |
| `5xx` / network | Retry with backoff; fail after exhausting attempts. |
| Poll timeout | Fail with elapsed time and the last-seen `status`/`current_stage`. Job id is persisted, so a retry resumes. |
| Terminal `failed`/`canceled` | Fail with AIVDO's `error` text. |

## Settings

| Setting | Default | Notes |
|---|---|---|
| `aivdo_api_key` | `""` | From Secret Manager `AIVDO_API_KEY` |
| `aivdo_base_url` | `https://aivdo-api-b7iz53omoq-as.a.run.app` | |
| `aivdo_style` | `blueprint` | AIVDO's education/courses template |
| `aivdo_voice` | `Charon` | Kavee's voice |
| `aivdo_poll_timeout` | `900` | Seconds |
| `ad_shot_url` | `https://eduverse.one/th` | Public page, no login |

`motion_ad` joins `RENDERABLE_FORMATS`. The `format` column is
`String(20)` and `motion_ad` is 9 characters, so it needs no migration — the
only migration is `aivdo_job_id` above.

## Testing

No test may call AIVDO for real; each call costs 5 credits.

- **Client** (respx): success path through polling to `completed`; `400`,
  `402`, `429`-then-success, `5xx`-then-success, terminal `failed`, and poll
  timeout. Assert the request body carries the configured style, voice and
  track id.
- **Copy** (mocked Gemini): all eight fields present; each capped; a
  banned-word response is rejected *before* any HTTP call — asserted by a
  respx mock that fails the test if called.
- **Shot** (slow, real Playwright, local fixture page): output is square and
  a valid PNG.
- **Worker**: `motion_ad` reaches `in_review` with media stored; `job_id` is
  persisted before polling; a retry with a persisted id resumes instead of
  re-generating; each error condition sets `render_error` and alerts.
- **Music**: `pick_track_id` returns a track id with **no file on disk**
  (the assertion that distinguishes it from `pick_track`), is deterministic per
  item, spreads across the configured list, and rejects malformed ids.
  `MusicConfig.for_format("motion_ad")` returns the configured list.

## Out of scope

- Custom-style controls (`color`, `font`, `scrim`, `position`, …). They apply
  only to `style: "custom"`; we ship `blueprint`.
- Multi-photo ads. The API accepts up to 3; we send 1. Adding a second capture
  is a later change, not a design constraint.
- Operator-supplied photos. The capture is automatic; an upload path can come
  later if the auto-capture proves visually limiting.
- Fixing AIVDO's `sweep_stalled_jobs` gap. Noted above, tracked separately.
