# Background music

Every rendered video carries a quiet CC0 music bed under the Thai narration.

## Where the tracks come from

AIVDO (`https://aivdo-api-b7iz53omoq-as.a.run.app`) serves a FreePD/CC0 library
**publicly and without authentication** — both the catalogue and the files:

```bash
curl -s https://aivdo-api-b7iz53omoq-as.a.run.app/api/music/tracks | jq '.tracks[] | {id, label, moods}'
curl -sO https://aivdo-api-b7iz53omoq-as.a.run.app/static/music/city-sunshine.mp3
```

38 tracks, tagged `upbeat` / `chill` / `dramatic` / `inspiring` / `playful`.
No API key, no credits, no AIVDO account is involved in music — that is
entirely separate from the Motion Ad integration, which does need a key.

The tracks are **not** in git. `render/fetch_music.py` downloads exactly the
ids named in `strategy.yaml` at image-**build** time (`render/Dockerfile`), so
a render never depends on a third-party host being reachable, and ~12MB of
binaries stay out of the repo. A renamed or missing track fails the build
loudly rather than shipping an image that quietly renders without music.

## Choosing tracks

`strategy.yaml`:

```yaml
music:
  tips: [city-sunshine, funshine, motions]
  demo: [inspiration, emotional-piano]
  gain_lufs: -33.0
```

Each format lists several tracks and one is picked per item, keyed on the item
id (`app/video/music.py: pick_track`). That choice is deterministic, which
matters twice over: re-rendering an item after a fix keeps the music it
already had rather than swapping the soundtrack under a reviewer, while
different items still spread across the whole list — a feed where every post
carries identical audio reads as templated.

To change the music, edit the lists and rebuild the render image. Adding an id
that is not in AIVDO's catalogue fails the build.

## Levels

The bed is normalised to **-33 LUFS before** being mixed under the narration
(AIVDO's own Motion Ad value), then `amix ... normalize=0` sums the sources
without rescaling, and a final `loudnorm` lifts the whole mix to spec. That
ordering is what preserves the level gap: the bed is meant to be felt, not
heard over a Thai voiceover. Moving `gain_lufs` toward -24 starts burying the
narration.

A 1.2s fade in and out tops and tails the bed. Without them it starts and
stops on a hard cut, which is audible and cheap-sounding at precisely the two
moments a viewer decides whether to keep watching.

## When music is absent

Music is a polish layer, so every failure degrades to "this video has no
music" rather than failing the render: no `music` block in `strategy.yaml`, an
empty list for the format, a track missing from the image, or a malformed
`strategy.yaml` all yield a perfectly good video without a bed. Note that
before this feature a `demo` render did not read `strategy.yaml` at all — the
degradation in `worker.py: _music_for` is what keeps a bad config from
breaking renders that used to work.

## Licensing

AIVDO's catalogue reports every track as `CC0 / Public Domain (FreePD)` in the
`license` field of `/api/music/tracks`. That is the upstream claim, taken at
face value here and not independently verified against FreePD — if music
rights ever need to hold up to scrutiny (a paid campaign, a platform dispute),
confirm each track at freepd.com first rather than relying on this file.
