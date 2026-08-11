# research-meta-2026 — Meta ads mechanics, for Eduverse (Thailand, EdTech)

Research stage output. Reference for the Audit and Plan stages.
**All sources accessed 2026-08-11.** Meta's own documentation is the primary
source; agency material is used only where labelled, and never to establish a
fact.

Companion to [FACEBOOK_ADS.md](FACEBOOK_ADS.md), which holds the campaign-one
plan and the creative. This file holds the mechanics behind it.

---

## 0. Scope note — what binds Eduverse today, and what does not

Most published Meta guidance is written for accounts with conversion signal,
many ad sets, and a creative pipeline. **Eduverse currently has none of those**,
so a large part of the literature below is not yet actionable. Stated plainly so
the Audit stage does not act on advice whose preconditions are absent:

| Mechanic | Applies at | Eduverse now |
|---|---|---|
| Learning phase exit | ~50 optimisation events/week | **0 conversions** |
| Ad set consolidation / budget fragmentation | several ad sets | **1 ad set** |
| Creative fatigue | frequency ≳ 2 | **frequency 1.0** |
| Advantage+ / automated optimisation | conversion signal present | **no pixel, no CAPI** |
| Creative diversity | a creative pipeline | **1 creative** |

The binding constraints are signal (no pixel/CAPI), creative volume (one asset),
and API access (App Review `NO_SUBMISSION`, zero approved privileges). None of
those are solved by research.

---

## 1. ยืนยันแล้วจากแหล่งทางการ / Verified from official sources

Every row below is Meta's own documentation.

| # | Finding | Source | Doc updated |
|---|---|---|---|
| 1 | **Advantage+ audience overrides your age targeting.** "the delivery system resets `age_min` and `age_max` to default values… you can pass `age_min` values ranging between 18 and 25 only… `age_max` is fixed at 65." | [Advantage+ audience](https://developers.facebook.com/documentation/ads-commerce/marketing-api/audiences/reference/targeting-expansion/advantage-audience) | 2026-06-26 |
| 2 | **`advantage_audience` defaults to `1`** from Marketing API v23.0 for **new** ad sets; must be explicitly set to `0` to opt out. Updating an existing ad set does not exhibit this. | same | 2026-06-26 |
| 3 | **The ASC API is being removed.** As of v25.0, `smart_promotion_type=AUTOMATED_SHOPPING_ADS` can no longer create ASC campaigns; use Advantage+ audience/budget/placements instead. | [Advantage+ Shopping Campaigns](https://developers.facebook.com/documentation/ads-commerce/marketing-api/advantage-shopping-campaigns/) | 2026-06-16 |
| 4 | **New Advantage+ creative features, June 2026**: `image_animation` (static image → short animated video), `video_filter`, `video_uncrop` (expands video to fill vertical placements "instead of cropping or letterboxing"). | [2026 Out-Of-Cycle Changes](https://developers.facebook.com/documentation/ads-commerce/marketing-api/out-of-cycle-changes/occ-2026) | 2026-06-28 |
| 5 | **`adapt_to_placement` is default opt-in**, and "By default, 4:5 and 9:16 placements are enabled" — i.e. Advantage+ creative will reshape a square image for vertical surfaces unless opted out. | [Get Started with Advantage+ Creative](https://developers.facebook.com/documentation/ads-commerce/marketing-api/creative/advantage-creative/get-started) | 2026-06-28 |
| 6 | ⚠️ **Ads Insights breakdown changes, effective 2026-08-06** (five days ago): `impression_device`, `hourly_stats_aggregated_by_audience_time_zone` and `frequency_value` **require opt-in** for non-sales-supported accounts; requests may return **no results**. | [2026 Out-Of-Cycle Changes](https://developers.facebook.com/documentation/ads-commerce/marketing-api/out-of-cycle-changes/occ-2026) | 2026-06-28 |
| 7 | **Targeting limits**: min age 13, max 65; `age_min` defaults to 18. Education is **not** a Special Ad Category (those are housing / employment / financial products, and bind US-, Canada- and Europe-facing ads). | [Targeting Restrictions](https://developers.facebook.com/documentation/ads-commerce/marketing-api/audiences/reference/targeting-restrictions) · [Basic Targeting](https://developers.facebook.com/documentation/ads-commerce/marketing-api/audiences/reference/basic-targeting) | 2026-05-21 / 2026-06-30 |
| 8 | **Marketing API access requires App Review**: `ads_management`, `ads_read`, `business_management` are all "required, cannot be removed" for the Create & manage ads use case, plus Marketing API Access Tier. Business verification is required **before you can run ads** through the API. | [Marketing API Authorization](https://developers.facebook.com/documentation/ads-commerce/marketing-api/get-started/authorization) | 2026-05-05 |
| 9 | **Budget fragmentation is real and named by Meta**: splitting budget across ad sets in a fixed way prevents spend moving to the efficient one. Meta's stated levers are "improving data quality, optimizing for true business results, and relaxing unnecessary constraints." ⚠️ Source is a **2016** blog post — principle still cited by Meta, but the post is a decade old. | [Dynamic Ads Best Practices](https://developers.facebook.com/ads/blog/post/v2/2016/07/27/dynamic-ads-best-practices/) | 2016-07-27 |
| 10 | **Scaling guidance**: raise budgets by ≤20%/day; "Large, sudden budget increases can reset the learning phase." Start at 50–70% of target daily budget. Min-ROAS bidding "needs a sufficient volume of purchase events (50+ per week)". ⚠️ Found in the **games / click-to-play** vertical docs, not general ads docs — treat as indicative, not binding on an education advertiser. | [Click-to-Play Ads: Budget](https://developers.facebook.com/documentation/games/acquire/click-to-play-ads/budget) | n/a |

**Row 6 is the one with a deadline.** The Audit stage depends on placement and
demographic breakdowns — which is exactly how the Reels problem was found. Check
whether this account is affected before relying on breakdown data.

**Row 1 is the one that already cost money.** Advantage+ audience was on at
launch with a 25–45 target; per Meta's own docs the ceiling would have been
overridden to 65.

## 2. Case studies — reporting the gap honestly

The brief asked for 3–5 comparable case studies. **I found none that meet the
bar**, and padding the list would defeat the purpose of the exercise.

What was searched: Meta's own success-stories library, and general web search
for EdTech / online-learning Meta ads results in Southeast Asia.

What came back:

- **Spotify Southeast Asia** ([Meta for Business](https://www.facebook.com/business/success/spotify-southeast-asia)) — real Meta-published case study, SEA market, reports a 4.4-point lift in ad recall. **Wrong vertical** (audio streaming, brand-awareness objective, enormous budget). Not transferable.
- **Student-enrolment tactics** ([modifyed.in](https://modifyed.in/facebook-ads-targeting-strategies-for-student-enrollment/)) — agency post; suggests campus video → testimonial ads → lead forms. **Not a case study**, no reported numbers, Indian market.
- Assorted e-commerce Meta-ads case studies — wrong vertical, no education relevance.

⚠️ **The structural reason to distrust this category**: published case studies
are marketing artifacts. Nobody publishes the campaign that failed, so the
sample is selected on success. Even a well-matched case would show what worked
once for one account, not what will work here.

**Recommended substitute**: your own account is the only comparable case. The
Audit stage should treat the first three clean days as the baseline, not any
published benchmark.

**Benchmarks, used as orientation only** (agency-aggregated, US-weighted, so
cost figures do not transfer to Thailand; the ratio does):

| Metric | Benchmark | Eduverse (pre-fix) |
|---|---|---|
| CTR, traffic campaigns | ~1.71% | **0.85%** |
| CTR, education | ~1.80% median | **0.85%** |
| CPC, traffic campaigns | ~$0.70 | ฿2.09 (~$0.06) |

Sources: [digitalapplied](https://www.digitalapplied.com/blog/facebook-ads-benchmarks-2026-cpc-cpm-ctr-industry), [superads education CTR](https://www.superads.ai/facebook-ads-costs/ctr-click-through-rate/education). **Not official.** The CTR ratio (~half benchmark) is the usable signal; the CPC column is not comparable across markets.

## 3. แนวปฏิบัติที่ควรทดลอง / Practices worth testing

Not established fact. Each needs a test on this account.

| Practice | Rationale | How to test | Risk if wrong |
|---|---|---|---|
| **Feed-only placements while the creative is 1:1** | Day-1 data: ~⅔ of delivery went to Reels/in-stream, Instagram Feed got 1 result. Meta's own preview panel recommends 9:16 for those surfaces. | Already running. Compare CTR Feed-only vs the Reels-heavy baseline. | Higher CPM, less volume — Meta warns "fewer than 6 placements may increase cost per result" |
| **Creative volume over targeting precision** | Every 2026 agency source says this; Meta's own "relax constraints" framing points the same way. AutoMarketing can produce Thai video at near-zero marginal cost. | Ship 3–5 creatives from `tips`/`demo`/`motion_ad`, run in one ad set. | Wasted render effort if the hook, not the format, is the problem |
| **9:16 video to unlock Reels** | `motion_ad` is 11s 9:16 with Thai VO — the format Reels wants. Would remove the reason placements are restricted. | One `motion_ad` render (5 AIVDO credits), Reels-only ad set. | 5 credits, non-refundable after dispatch |
| **CTA "Sign up" over "Learn more"** | Pre-qualifies for the account step that follows; the goal box now leads to `/register`. | Live as of 2026-08-11. Expect CTR to fall, judge on signups. | Fewer clicks, and with no conversion tracking you cannot yet see the upside |
| **Broad targeting, no interests** | Audience is 31–37M and reach was 4,699 at frequency 1.0 — nowhere near exhausted. Meta's "relax constraints" supports broad. | Hold interests off until CAPI ships. | May be leaving qualified-audience gains unclaimed |

## 4. ข้ออ้างที่ไม่มีหลักฐานพอ หรือขัดกับแหล่งทางการ / Unsupported or contradicted

| Claim | Where it comes from | Status |
|---|---|---|
| **"Project Andromeda" changed the ad algorithm in 2026** | [jetfuel](https://jetfuel.agency/metas-2026-algorithm-update-what-andromeda-changed-and-how-to-adapt-your-ads/), [segwise](https://segwise.ai/blog/meta-andromeda-update-creative-strategy-2026), [anchour](https://www.anchour.com/articles/meta-ads-2026-playbook/) | **Zero mentions in Meta's developer documentation** (searched 2026-08-11). May describe real infrastructure, but it is not an advertiser-facing concept Meta documents. Do not build a plan on it. |
| **"22% higher ROAS for advertisers who adapt"** | agency posts, attributed to "Meta AI Research" | **No primary source located.** Unverifiable. |
| **"Fewer than 8 new creatives/month = borrowed time"** | agency posts | **No source.** Directionally plausible; the specific number is invented. |
| **"Make ASC primary"** | agency posts | **Contradicted by Meta.** The ASC API is being removed at v25.0 (§1 row 3). Also a *shopping* product — wrong shape for education signup. |
| **"Targeting no longer matters, creative is the only lever"** | agency posts | **Overstated and contradicted in part.** Meta's docs still define hard targeting constraints (§1 rows 1, 7), and Advantage+ explicitly preserves "non-negotiable business constraints" — location, minimum age, language, custom-audience exclusions. Targeting matters less; it has not stopped mattering. |
| **Landing-page views cannot be measured without a pixel** | *my own earlier claim in this project* | **Wrong, corrected 2026-08-11.** The metric populated (40 LPV) with no pixel installed — Meta measures loads in its own in-app browser. Recorded so it is not repeated. |

## 5. Conflicts, both sides shown

### 5.1 Automate vs restrict

**Agency 2026 consensus**: let Advantage+ run; targeting precision matters less
than creative diversity.
**Meta's own docs**: agree in direction — "relaxing unnecessary constraints",
budget fragmentation is bad, complexity is the enemy (§1 row 9).
**Against, for this account**: automation optimises toward the objective it is
given. With **Traffic/link-clicks and no conversion signal**, Advantage+
optimises for cheap clicks — which is the observed failure (Reels traffic, 40
LPV, 0 signups). Meta's own "improve data quality" is listed *first* among its
three levers.

**Not resolved by argument. What to check:** does the account have a conversion
signal? Today, no. **The two positions are sequential, not opposed** — restrict
while blind, automate once CAPI is feeding events. Revisit after CAPI ships.

### 5.2 Advantage+ creative: harmful or helpful here?

**For**: `adapt_to_placement` is default opt-in and reshapes images for 4:5 and
9:16 (§1 row 5) — it would have mitigated the Reels letterboxing without any
placement restriction.
**Against**: it also generates headline and copy variations, which makes an A/B
between two copy variants unreadable, and the Thai copy is deliberately written
and gate-checked.

**What to check**: whether the individual features can be opted into
selectively. The API exposes per-feature `enroll_status` (`OPT_IN`/`OPT_OUT`) in
`creative_features_spec` — so `adapt_to_placement` **on** with text variation
**off** may be possible via the API. **Not verified as available in the Ads
Manager UI.** Worth testing once API access exists.

### 5.3 Learning phase — the 50-events number

Widely cited as ~50 optimisation events per week. **Not located in Meta's
developer documentation**; the closest primary statement found is that min-ROAS
bidding "needs a sufficient volume of purchase events (50+ per week)" (§1 row
10), which is a *bidding* requirement in the games vertical, not a general
learning-phase definition.

**What to check**: Meta Help Center (business.facebook.com/business/help), which
is where the learning-phase definition lives and which the developer doc search
does not index. Treat 50/week as a working assumption, not a verified fact.

---

## 6. What this changes for the Audit stage

1. **Verify breakdown availability before relying on it** (§1 row 6, effective five days ago).
2. **Baseline against your own pre-fix numbers**, not published benchmarks (§2).
3. **Do not re-enable Advantage+ audience** while age targeting is load-bearing (§1 row 1).
4. **Do not plan around Andromeda, ASC, or the 8-creatives rule** (§4).
5. **Signal first, automation second** (§5.1) — CAPI is the gate on everything else, and it is already handed off to the eduverse-one session.
