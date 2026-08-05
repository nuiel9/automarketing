# AutoMarketing Phase 2 — Video Factory Design

**Date:** 2026-08-05
**Status:** Approved in brainstorm; pending final spec review
**Builds on:** `2026-08-05-automarketing-design.md` §4.2 (Phase 2), Phase 1 shipped and in production

## 1. Purpose

Remove the filming bottleneck. Today AutoMarketing can write Thai captions and
auto-post, but a human must supply every video. Phase 2 generates the videos:
Playwright drives the real product and screen-records it, Kavee narrates in Thai,
and the result is a 1080×1920 MP4 that flows into the review queue already built.

The output contract is unchanged from Phase 1 — a vertical MP4 in GCS on a
`content_item` — so the publisher and every channel adapter need no changes.

## 2. Decisions (from the brainstorm)

| Decision | Choice | Rationale |
|---|---|---|
| Demo target | Production `eduverse.one` + dedicated demo account | Viewers see the real product; staging drift would put staging-only bugs in public videos |
| Trigger | Button in the review queue (`POST /api/items/{id}/render`) | Founder controls what gets made; no credits burned on ideas that get rejected |
| Audio | Kavee TTS + synthesized UI blips, **no music** | Zero third-party audio provenance risk in a public repo; platforms layer their own trending audio anyway |
| Scope | `demo` + `tips` renderers | The two formats the marketing plan calls for weekly; social-proof and avatar stay Phase 4 |
| Voice | `gemini-3.1-flash-tts-preview`, voice `Charon` | Byte-for-byte the product's own Kavee voice (same config as eduverse-one), same API key |

**Topic selection is deliberately not fixed here.** Scenario files are ~10 lines
of YAML, so the launch topic is chosen from evidence after the renderer exists.
Recorded caution from the brainstorm: exam-prep topics (especially TGAT math)
carry content-accuracy risk that upskilling topics (Excel, English, finance) do
not, and the plan's audience 3 converts fastest. Test real output before
authoring the first public scenario.

## 3. Architecture

```
review queue ──POST /api/items/{id}/render──► API (status → rendering)
                                              │ RenderDispatcher.dispatch(item_id)
                                              ▼
                                    Cloud Run Job: automarketing-render
                                    (Chromium + ffmpeg + Thai fonts, VPC, 2CPU/4GB)
                                              │
                        ┌─────────────────────┼─────────────────────┐
                        ▼                     ▼                     ▼
                  DemoRenderer          TipsRenderer            KaveeVoice
              (Playwright on prod)   (HTML cards + Ken Burns)  (Gemini TTS)
                        └─────────────────────┼─────────────────────┘
                                              ▼
                                     Composer (ffmpeg)
                              segments + narration + blips + SRT
                                     + hook overlay + loudnorm
                                              ▼
                        GCS (MP4 + poster) ──► item → in_review
```

The job reads and writes the database directly over the VPC. There is no
callback endpoint and no polling.

## 4. Components

### 4.1 Scenario files (`scenarios/*.yaml`)

The entire authoring surface for demos. Each step carries **its own Thai
narration**, which is what makes audio/video drift impossible: the clip for a
step is cut to that step's measured narration duration.

```yaml
name: tgat-demo
steps:
  - narration: "อยากติว TGAT แต่ไม่รู้จะเริ่มตรงไหน"
    action: goto
    url: https://eduverse.one/th
  - narration: "แค่พิมพ์เป้าหมายลงไป"
    action: type
    selector: "[data-testid=goal-input]"
    text: "ติว TGAT คณิต ให้ทันสอบ"
    sound: keystroke
  - narration: "ระบบสร้างให้ทั้งคอร์ส"
    action: click
    selector: "[data-testid=generate]"
    sound: click
    fit: speedup
  - narration: "พร้อมพี่กวี ติวเตอร์เสียงไทยที่คุยได้จริง"
    action: wait_for
    selector: "[data-testid=course-title]"
```

Actions: `goto`, `type`, `click`, `wait_for`, `wait_ms`, `scroll`.
`fit` ∈ `speedup` (default for long waits) | `tail` | `hold`.
`sound` ∈ `keystroke` | `click` | absent.
Validated by a pydantic model at load; an invalid scenario fails before any
browser starts.

### 4.2 DemoRenderer

1. Synthesize each step's narration first (durations drive everything downstream).
2. Launch Chromium at 1080×1920, log in as the demo account, start recording.
3. Execute steps, recording a start/end timestamp per step.
4. Stop recording; cut the session video per step; fit each clip to its
   narration duration per its `fit` mode — a 60-second course build becomes four
   visible seconds of progress.

### 4.3 TipsRenderer

Gemini writes N Thai tips on the topic (structured output). Each becomes a
styled HTML card screenshotted by the same Chromium — real Thai typography, not
an image-library approximation — with a slow Ken Burns push for motion. Kavee
narrates each card.

### 4.4 KaveeVoice

`gemini-3.1-flash-tts-preview`, voice `Charon`, one call per narration segment,
returning audio plus measured duration. Cached by text hash so re-renders of an
unchanged scenario cost nothing.

### 4.5 Composer

One ffmpeg pipeline for both renderers: concat segments → lay narration →
mix UI blips at step boundaries → burn SRT built from narration text and
*measured* segment durations → hook overlay over the first three seconds →
loudness normalization → 1080×1920 H.264 `yuv420p`. Also emits a poster frame
for the queue card.

UI sounds are **synthesized at build time with ffmpeg** (a short click
transient, a softer keystroke tick) — no third-party audio files enter the repo.

### 4.6 RenderDispatcher

```python
class RenderDispatcher(Protocol):
    def dispatch(self, item_id: str) -> None: ...
```

`CloudRunDispatcher` executes the job with an `ITEM_ID` override and returns
immediately. `LocalDispatcher` runs the worker as a subprocess, so the whole
flow works on a laptop and in tests without GCP.

## 5. Data model and state

- `content_items` gains `scenario` (nullable) and `render_error` (nullable).
- `format` values extend to `demo` and `tips` alongside `founder_clip`.
- State machine gains `idea → rendering` and `failed → rendering`.
  (`rendering → in_review | failed` already exist from Phase 1.)

## 6. Error handling

| Failure | Behavior |
|---|---|
| Selector not found | Screenshot at the failing step uploaded; item `failed` with a message naming the step |
| TTS error | Fail fast; error tail on the item |
| ffmpeg error | stderr tail captured on the item |
| Job dies silently | The existing 5-minute publisher tick sweeps items `rendering` > 20 min → `failed` |
| Any of the above | LINE alert to the founder (working since Phase 1) |

## 7. Testing

- **Unit** (no I/O; TTS and Playwright mocked): scenario validation, fit-to-narration
  timing math, SRT construction, ffmpeg command building, dispatcher selection.
- **End-to-end golden render**: a real MP4 produced from a **local fixture HTML
  page** (never production) with real ffmpeg — asserts duration in range, an audio
  stream is present, and subtitles are burned in.
- **Manual gate**: the first production render is reviewed by the founder before
  any scenario is used for a public post.

## 8. Operational requirements

- A **demo account on production with credits**; its login lives in Secret
  Manager (`DEMO_EMAIL`, `DEMO_PASSWORD`) and never in the repo.
- **Every demo render creates a real course** and burns that account's credits.
  Scenarios that browse an existing course cost nothing.
- Backend service account needs permission to run the render job.

## 9. Cost per video

≈ ฿0.30 TTS + ฿1–2 job compute + one course of demo-account credits (demo
renders only). A four-clip week is immaterial against the ฿15,000/month
Phase-0 budget.

## 10. Risks

- **Product UI changes break scenarios** → failures produce a screenshot naming
  the step; scenarios are ~10 lines to repair; the golden-render test catches
  pipeline regressions but not selector drift on production.
- **Content quality on exam topics** → see §2; choose launch topics from tested
  output, not assumption.
- **Demo account exhausts credits** → renders fail with the app's own error
  visible in the screenshot; top up or point scenarios at existing courses.
- **Cold Chromium image is large (~1.5 GB)** → job start latency of tens of
  seconds, irrelevant for a minutes-long render.
