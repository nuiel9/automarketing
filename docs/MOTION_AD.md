# Motion Ad

A Motion Ad is a fixed 11-second, 1080×1920 branded spot that AIVDO renders
end-to-end: you send it a screenshot, brand copy, and a voice; it handles the
template, the voiceover, and the music mix, and hands back a finished MP4.
`app/video/worker.py: _render_motion_ad` never calls `compose()` for this
format — there are no subtitles, no local music bed, and no hook overlay on
this path, because AIVDO already produced all of that.

It costs **5 credits per ad**, deducted from the AIVDO account behind
`AIVDO_API_KEY`. It is not a replacement for `tips` or `demo` — it's a third
render format alongside them (`RENDERABLE_FORMATS` in
`backend/app/api/items.py`), for when a fixed-length, agency-produced-looking
spot fits an item better than a Playwright screen recording or an on-screen
tips card.

## Setup

1. Create an API key in the AIVDO UI, under the account that holds the
   credit balance.
2. Store it in Secret Manager — never paste it into a chat, a commit, or
   `.env`:

   ```bash
   printf '%s' '<key>' | gcloud secrets create AIVDO_API_KEY --data-file=- --project=eduverse-personal-krainat
   ```

   Piping the value in through `--data-file=-` keeps it out of your shell
   history and out of the process list, unlike passing it as a `--value`
   flag would. The key is the credential that spends the account's credit
   balance directly — anyone who has it can drain it, and a copy that lands
   in git history or a chat transcript is compromised for good, not just
   until the next rotation.

This creates the secret. Wiring it into the deployed render job — the IAM
binding that lets the job read it, and the flag that attaches it to
`automarketing-render` — is covered in `docs/DEPLOY.md`'s Secret Manager
section and its render-job section. This page only covers what the ad
itself does.

## Running one

Open the review queue, pick an item, choose the `motion_ad` format, and
press Render (`POST /api/items/{id}/render` with `{"format": "motion_ad"}`).

The photo is captured automatically from `AD_SHOT_URL`
(`https://eduverse.one/th` by default) — no login and no upload is involved
(`backend/app/video/shot.py`). That's deliberate: this path never touches
the demo account's credentials, so rendering a `motion_ad` item can't
trigger the goal-accumulation side effect a real login to eduverse.one
causes on the `demo` account. The screenshot is captured square, not 9:16 —
AIVDO's `blueprint` template frames the photo in an 840×820 window with the
ad copy drawn outside it, so a 1080×1920 capture would just get
centre-cropped to a narrow band.

Pressing Render is also the point where credits get spent, once the
banned-words gate and AIVDO's own moderation both pass — see "When it
fails" below for exactly what does and doesn't cost you. A healthy render
takes about two minutes; `AIVDO_POLL_TIMEOUT` (900s / 15 minutes) is the
ceiling before the item is failed rather than left waiting forever.

## Tuning

**`AIVDO_STYLE`** selects AIVDO's template. `blueprint` (the default) is
AIVDO's education/B2B template — "structured, technical, clean grid" — which
is why the photo capture above is square. It's a plain env var on the
`automarketing-render` job, so changing it is a
`gcloud run jobs update automarketing-render --update-env-vars=AIVDO_STYLE=...`
away; no rebuild needed.

**`strategy.yaml`'s `music.motion_ad`** lists candidate track ids; one is
chosen per item, deterministically, the same way `tips` and `demo` pick
theirs (`app/video/music.py: pick_track_id` — see `docs/MUSIC.md` for the
full mechanism and why the choice is deterministic). The difference: these
ids are never downloaded into the render image. They're passed straight to
AIVDO in the dispatch payload, and AIVDO builds the bed itself —
`render/fetch_music.py` only fetches the `tips` and `demo` lists at build
time, so adding a `motion_ad` id there would grow the image with a file
nothing reads. That doesn't mean a `music.motion_ad` edit skips a rebuild,
though: `strategy.yaml` itself is `COPY`'d into the render image
(`render/Dockerfile`) and read from that baked-in copy, not fetched live at
render time, so a track-list change still needs the render image rebuilt
and redeployed before a render picks it up — same as any other
`strategy.yaml` change.

**`AIVDO_VOICE`** is the voiceover. `Charon` (the default) is the same
Gemini TTS voice Phase 2 uses for Kavee, and it's registered in AIVDO's own
voice list as male/Informative — so a `motion_ad` sounds like the same
narrator as every `tips` and `demo` video, not a stranger.

## When it fails

"Did that cost me credits?" is the first question worth asking when a
`motion_ad` item lands in `failed` — a render is worth 5 credits by the
time AIVDO takes it, so an operator needs to know before deciding whether
to just press Render again.

| `render_error` says | Cause | Credits spent |
|---|---|---|
| `ad copy contains banned words: …` | Our gate caught brand-voice copy | **No** — never reached AIVDO |
| `AIVDO rejected the ad copy: Content blocked: …` | AIVDO's moderation | **No** — it moderates before deducting |
| `AIVDO is out of credits: …` | Account balance below 5 | **No** — top up and retry |
| `AIVDO job … failed/canceled: …` | Render failed on AIVDO's side | **Yes** — not refunded |
| `AIVDO job … did not finish within …s` | Timed out while polling | **Yes** — but the job id is saved, so a retry resumes rather than paying again |
| `could not reach AIVDO: …` | Every connection attempt failed before the request reached AIVDO | **No** — nothing was ever sent |
| `AIVDO dispatch request failed after it may have reached the server …` / `AIVDO returned <5xx>; a job may already exist …` | A read timeout, or a 5xx other than 503, while dispatching | **Unknown** — check AIVDO's job list before re-running rather than guessing |

The last two rows are why a failed dispatch doesn't just retry itself
(`backend/app/video/aivdo.py: generate_ad`). A `ConnectError` or
`ConnectTimeout` fires before the POST ever leaves the process, so nothing
was charged and retrying is safe — that case retries automatically, up to
four attempts with backoff, and only becomes `could not reach AIVDO: …`
once all four fail. A `ReadTimeout`, or a 5xx AIVDO hasn't documented a
refund contract for, can happen *after* the request was fully sent — AIVDO
may already have created the job and spent the 5 credits before the
response was lost. Retrying blind in that case risks a second dispatch
with no job id ever saved to resume from, which is unrecoverable, so it
raises immediately instead and tells you to check AIVDO first.

One more case worth knowing about, because the numbers line up in a way
that hides it: `AIVDO_POLL_TIMEOUT` defaults to 900s (15 minutes), and
`docs/DEPLOY.md`'s `automarketing-render` job is created with
`--task-timeout=15m` — the same 900 seconds. The screenshot capture and the
ad-copy generation both run *before* polling starts, so a job genuinely
stuck at AIVDO can hit Cloud Run's task timeout and get killed before
`poll()` ever gets a chance to raise its own "did not finish within 900s"
error. When that happens, the item is left sitting at `rendering` with
`render_error` still null and no LINE alert — the process was killed, not
raised, so nothing runs the except block that would have sent one. The 5
credits are spent either way, and `aivdo_job_id` is still saved on the
item, so the fix is the same as an ordinary poll timeout: check the job on
AIVDO, then re-render the item to resume polling rather than paying again.
