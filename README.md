# AutoMarketing

Marketing automation for [Eduverse One](https://eduverse.one) — the Thai AI-tutor app.
Upload a clip → Claude writes per-platform Thai captions → you approve in a phone-friendly
review queue → it auto-posts on schedule to **Facebook, Instagram, X, and LINE OA** with
UTM tracking, retries, and LINE failure alerts. TikTok and YouTube captions are generated
for manual posting until their platform audits clear.

## How it works

```
idea/clip ──► caption writer ──► review queue ──► scheduler ──► channel adapters ──► posted
              (Claude, Thai,      (human gate:     (5-min tick,   Meta / X / LINE
               6 channels)         approve/edit/    retries,       + DryRun for staging)
                                   reject)          backoff)
```

- **Nothing posts without human approval.** Captions lock once approved.
- **Every outbound link carries UTM** (`utm_source=<channel>&utm_campaign=<slug>`).
- A **banned-words gate** (from `strategy.yaml`) blocks risky Thai copy before review.

## Stack

FastAPI + SQLAlchemy/Postgres + Alembic · Next.js (App Router) + Tailwind ·
Gemini (`gemini-3.6-flash`, structured outputs — same model family as eduverse-one;
Anthropic `claude-opus-5` available via `CAPTION_PROVIDER=anthropic`) ·
Cloud Run + Cloud Scheduler + GCS.

## Local development

```bash
# database
docker compose up -d db

# backend (Python 3.12)
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload          # http://localhost:8000
.venv/bin/pytest                                  # test suite

# frontend (Node 20)
cd frontend
npm install && npm run dev                        # http://localhost:3000
```

Copy `.env.example` to `backend/.env` and fill values — see
[`docs/PLATFORM_SETUP.md`](docs/PLATFORM_SETUP.md) for how to obtain each platform
credential (and which audits to file for TikTok/YouTube). With no credentials, set
`ENABLED_CHANNELS=dryrun` to exercise the whole pipeline against a local fake feed.

## Deployment

[`docs/DEPLOY.md`](docs/DEPLOY.md) is the Cloud Run runbook (region `asia-southeast1`):
both Docker images, Cloud Build, Cloud SQL, non-public GCS media bucket, Secret Manager,
and the 5-minute publisher tick via Cloud Scheduler. The smoke test requires a working
`GEMINI_API_KEY`.

## Documents

| Doc | What it is |
|---|---|
| [`docs/superpowers/specs/2026-08-05-automarketing-design.md`](docs/superpowers/specs/2026-08-05-automarketing-design.md) | Full system design (all 4 phases) |
| [`docs/superpowers/plans/2026-08-05-automarketing-phase1-spine.md`](docs/superpowers/plans/2026-08-05-automarketing-phase1-spine.md) | Phase 1 implementation plan |
| [`docs/PLATFORM_SETUP.md`](docs/PLATFORM_SETUP.md) | Founder checklist: tokens + audit applications |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Cloud Run deploy runbook |

## Roadmap

- **Phase 1 — Spine** ✅ multi-channel auto-posting with review queue (this release)
- **Phase 2 — Video Factory**: auto-rendered product demos + tips cards, Kavee TTS voiceover, YouTube/TikTok adapters
- **Phase 3 — Content Brain + Attribution**: weekly AI content planning from `strategy.yaml`; views → clicks → signups → activated → D7 funnel per channel; weekly LINE digest
- **Phase 4 — Autopilot extras**: AI avatar presenter, social-proof clips, full auto-post once platform audits clear
