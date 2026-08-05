# AutoMarketing — Design

**Date:** 2026-08-05
**Status:** Approved in brainstorm (CMO/CPO/CTO session); pending final spec review
**Product:** Eduverse One (Thai AI-tutor edtech, https://github.com/eduverse-global/eduverse-one)
**Source strategy:** `EduverseOneMarketingPlanTH.pdf` (2026-08-03)

## 1. Purpose

A marketing automation system for Eduverse One that generates video content, writes
per-platform Thai copy, and auto-posts to six channels — TikTok, Instagram, Facebook,
YouTube Shorts, X, and LINE OA — with a human review queue before anything goes live,
and an attribution loop that reports the funnel the marketing plan requires
(views → clicks → signups → activated → D7 per channel).

Grounding constraints from the marketing plan:

- Product stage: 10 users, D7 retention ~20%. No paid ads until D7 ≥ 35–40%.
- Content cadence target: 3–4 short vertical videos per week, Phase-0 budget ≤ ฿15,000/month.
- LINE OA is the CRM channel (weekly broadcast); certificate/social-proof loops matter.
- UTM/source capture at signup is explicitly named as the gap to close before ad spend.
- AI-drafted Thai copy must be human-checked before external use (plan's own warning).

## 2. Decisions made (with rationale)

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Full suite: content generation → posting → attribution, designed together, built in phases | User choice |
| Video source | Tool auto-generates videos (all 4 formats); founder clips also supported as manual uploads | User choice |
| Video formats | Product demos, tips/listicle cards, social-proof clips, AI avatar (avatar phased last — only format with an external paid dependency) | User choice |
| Posting rails | Direct platform APIs, ฿0/month ("direct + patience"): Meta + X full auto day 1; TikTok draft-mode and YouTube private-mode until platform audits clear; audits filed in week 1 | User choice |
| Approval | Review queue — nothing posts without human approval; AI Thai copy risk | User choice |
| Runtime | FastAPI + Next.js + Postgres on Cloud Run (same stack/ops as eduverse-one); render worker as Cloud Run Job | User choice |
| Architecture | Monolith + worker (one repo, one DB, one deploy; `PostingAdapter`/`VideoRenderer` interfaces keep parts swappable) | Unanimous over serverless pipeline / n8n |
| Voiceover | Same TTS vendor/voice as the product's "Kavee" tutor (measured ฿0.376/min) | On-brand, cheap, already proven |
| LLM | Claude API, `claude-opus-5`, Python SDK, structured outputs for captions/plans | Current default model; volume is tiny (~5 posts/week × 6 channels) so cost is a few USD/month |
| Channel #6 | LINE OA broadcast included from day 1 (reuses existing eduverse LINE OA channel) | Thailand; the plan calls LINE "the CRM" |

## 3. Architecture

One repository, three deployables built from one codebase:

```
┌─────────────────────────── AutoMarketing repo ───────────────────────────┐
│                                                                          │
│  Next.js web app ──── FastAPI API ────────────── Postgres                │
│  (review queue,        (content items, queue,                            │
│   calendar, dashboard)  scheduler endpoints)                             │
│                              │                                           │
│  Cloud Scheduler ── ticks ───┤                                           │
│   (plan weekly /             │                                           │
│    publish 5-min /     Render worker (Cloud Run Job)                     │
│    metrics daily)       Playwright + ffmpeg + TTS + Thai fonts           │
│                              │                                           │
│                         GCS bucket (rendered MP4s, previews)             │
└──────────────────────────────────────────────────────────────────────────┘
        │ publish/metrics                       │ attribution pull
        ▼                                       ▼
  Platform APIs                          eduverse-one admin API
  (Meta, X, YouTube, TikTok, LINE)       (signups/activation/D7 by UTM)
```

- **API + web** run as one Cloud Run service (same deploy pattern as eduverse-one;
  the existing `deploy-fastapi-nextjs-cloud-run` skill applies).
- **Render worker** is the same container image with a different entrypoint, run as a
  Cloud Run Job — renders are minutes-long, retryable, and isolated from the API.
- **Secrets** (platform tokens, API keys) in GCP Secret Manager.

## 4. Components

### 4.1 Content Brain (planner)

- **Weekly planning job** (Cloud Scheduler, Sundays): reads `strategy.yaml` — a
  version-controlled config encoding the marketing plan: audiences (exam-prep
  students+parents, university students, working upskillers), content pillars,
  format mix, cadence (3–4/week), banned words, brand voice notes. Calls Claude
  (`claude-opus-5`, structured output) to propose next week's slots: each slot =
  format + topic + hook + narration script draft (Thai).
- **Ad-hoc creation**: a form/endpoint where the founder types an idea; the same
  generation path produces one content item.
- Proposed slots enter the pipeline as `planned` items; nothing renders until the
  founder promotes them (or auto-render on plan acceptance — config flag).

### 4.2 Video Factory (worker)

Output contract: 1080×1920 MP4 + thumbnail + SRT, written to GCS.

Shared spine for all formats:

1. Claude produces the narration script segmented into timed chunks.
2. `VoiceOver` interface renders each chunk with the product's Kavee voice
   (same TTS vendor + voice ID as eduverse-one).
3. Chunk audio durations drive subtitle timing (SRT) and scene pacing.
4. ffmpeg composes: visual track + voiceover + royalty-free music bed (assets/),
   burned Thai subtitles (Noto Sans Thai/Sarabun), hook text overlay,
   loudness normalization.

Per-format visual sources (`VideoRenderer` implementations):

| Renderer | Visual source | Notes |
|---|---|---|
| `DemoRenderer` | Playwright drives live eduverse.one from a YAML *scenario* (steps: goto, type, click, wait); screen recording is the track | New demo = new ~10-line YAML, no code. Debug screenshot captured on scenario failure |
| `TipsRenderer` | Templated text cards + product screenshots | "5 ข้อสอบ TGAT ที่คนพลาดบ่อย" style |
| `SocialProofRenderer` | Card template fed by consented-milestones JSON from eduverse-one | Requires new eduverse endpoint + consent flag; Phase 4 |
| `AvatarRenderer` | External avatar API (HeyGen-class) returns talking-head track | Phase 4; only paid external dependency |

Worker image bundles Chromium, ffmpeg, Thai fonts.

### 4.3 Caption Writer

One content item → per-platform Thai copy via Claude structured outputs
(`client.messages.parse` with a Pydantic schema):

- TikTok: casual caption + hashtags (#DEK69 #TCAS community tags per plan)
- YouTube: searchable title + description + tags
- Instagram: caption + hashtags
- Facebook: caption
- X: short text
- LINE OA: broadcast message text

Every link is generated by the UTM builder: `utm_source=<channel>&utm_medium=social&utm_campaign=<slug>`
where slug = `w{week}-{format}-{topic}` (e.g. `w32-demo-tgat`). Banned-words check
runs on all copy before the item may enter review.

### 4.4 Review Queue (Next.js, mobile-friendly)

- Card per content item: video preview (GCS signed URL) + all platform captions +
  scheduled time.
- Actions: approve / edit captions inline / reject (with reason) / reschedule.
- Approval moves item to `approved`; the publisher takes it from there.
- Also surfaces `failed` items with the platform error and re-try button.

### 4.5 Publisher & Channel Adapters

Cloud Scheduler ticks a publish endpoint every 5 minutes; due `approved` items are
published per channel through `ChannelAdapter`:

```python
class ChannelAdapter(Protocol):
    def publish(self, media: MediaRef, caption: Caption) -> PostRef: ...
    def fetch_metrics(self, post: PostRef) -> PostMetrics: ...
```

| Adapter | Day-1 behavior | Mechanism | Path to full auto |
|---|---|---|---|
| `MetaAdapter` (FB Page + IG) | Full auto | Graph API, dev-mode app, long-lived page token; IG media container → publish (Reels) | Already full auto for own assets |
| `XAdapter` | Full auto | API v2 free tier (~500 posts/month), chunked media upload | — |
| `YouTubeAdapter` | Uploads **private** | Data API v3 `videos.insert`, OAuth refresh token; #Shorts | Auto-publishes backlog when Google audit clears (config flag flips) |
| `TikTokAdapter` | Uploads to founder's **drafts** + LINE notification "tap to post" | Content Posting API, unaudited mode | Direct-post after TikTok audit |
| `LineAdapter` | Full auto weekly broadcast | Messaging API broadcast, existing eduverse LINE OA channel token, within plan quota | — |
| `DryRunAdapter` | Writes to a local "fake feed" page | For staging/e2e testing | — |

Cross-cutting publisher rules:

- Idempotency key per (item, channel) — retries can never double-post.
- Per-channel rate limiting; exponential backoff ×3 → `failed` + LINE notification.
- Auth errors mark the channel `needs_reauth` (banner + LINE alert); other channels
  keep flowing; held items stay `scheduled`.
- TikTok + YouTube audit applications are filed in Phase 1 so the clock starts.

### 4.6 Attribution & Analytics

- **eduverse-one side** (separate small PR in that repo): store
  `utm_source/utm_medium/utm_campaign` + referrer on the user at signup; one
  admin-authenticated endpoint returning signups / activation / D7 grouped by
  source+campaign.
- **AutoMarketing side**: daily metrics job calls each adapter's `fetch_metrics`
  (views, likes, comments, link clicks where available) and the eduverse endpoint;
  stores time-series `PostMetrics` rows; joins on campaign slug.
- **Dashboard**: per-channel funnel (views → clicks → signups → activated → D7),
  per-item leaderboard, weekly trend.
- **LINE weekly digest** to the founder: totals, best/worst clip, funnel deltas,
  reminder that next week's plan awaits review.

## 5. Data model (core tables)

- `content_items` — id, slug, format, topic, hook, script, status
  (`idea|planned|rendering|in_review|approved|scheduled|posted|rejected|failed`),
  media refs (GCS), created_by (planner|manual), timestamps.
- `captions` — content_item_id, channel, title, body, hashtags, edited_by_human.
- `publications` — content_item_id, channel, scheduled_at, posted_at, post_ref,
  idempotency_key, status, last_error.
- `post_metrics` — publication_id, captured_at, views, likes, comments, shares, clicks.
- `attribution_snapshots` — campaign slug, source, signups, activated, d7, captured_at.
- `channel_state` — channel, auth status, quota counters, audit status
  (e.g. YouTube `private_until_audit`, TikTok `draft_mode`).

## 6. Error handling

- **Render failure**: 1 retry; then item → `failed` in queue with log tail and (for
  scenarios) a debug screenshot.
- **Publish failure**: backoff ×3 → `failed` + LINE notification; manual retry button.
- **Token expiry / auth error**: channel paused (`needs_reauth`), LINE alert, other
  channels unaffected.
- **LLM schema mismatch**: SDK-level retry via `messages.parse`; persistent failure
  flags the item `needs_attention` — malformed copy is never queued.
- **Brand safety**: banned-words list gate + mandatory human approval.

## 7. Testing

- Unit: pipeline state machine, UTM builder, subtitle-timing math, banned-words gate.
- Adapter contract tests against recorded HTTP fixtures (no live calls in CI).
- One golden-render e2e test: fixture scenario → real short MP4, assert duration,
  audio track, subtitle presence.
- `DryRunAdapter` staging path exercises idea → render → approve → publish without
  touching real platforms.
- Frontend: minimal component tests for the review queue actions.

## 8. Build phases

1. **Spine** — repo scaffold, DB, review queue UI, caption writer, UTM builder,
   publisher with Meta + X + LINE adapters. Founder-filmed clips uploaded manually:
   multi-channel auto-posting is useful before any video generation exists.
   File TikTok + YouTube audit applications.
2. **Video Factory** — demo + tips renderers, Kavee TTS integration, scenario YAML,
   GCS previews; YouTube (private-mode) + TikTok (draft-mode) adapters.
3. **Content Brain + Attribution** — weekly planner from `strategy.yaml`;
   eduverse-one UTM-capture PR + admin endpoint; metrics collectors; funnel
   dashboard; LINE weekly digest.
4. **Autopilot extras** — avatar renderer, social-proof clips (consented milestones
   endpoint in eduverse-one), audit-clear flips to full auto for YouTube/TikTok.

## 9. Risks & mitigations

- **Platform audits are slow/unpredictable** → day-1 flows don't depend on them
  (draft/private modes); revisit an aggregator API only if audits stall past Phase 3.
- **AI Thai copy quality** → human gate on everything; banned-words list; founder
  edits feed back as few-shot examples in `strategy.yaml` over time.
- **Demo scenarios break when the product UI changes** → scenarios are tiny YAML,
  failures produce screenshots, and the golden-render test catches regressions.
- **X free-tier posting quota changes** → adapter isolates it; volume is ~16
  posts/month, far under any plausible cap.
- **LINE broadcast quota on current plan** → weekly cadence only; quota counter in
  `channel_state` warns before send.
- **Kavee TTS coupling** → `VoiceOver` interface; any TTS vendor/voice can be swapped.
