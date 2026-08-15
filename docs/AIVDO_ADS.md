# AIVDO ads — campaign one (Thai only)

Written 2026-08-13, on the **same personal ad account as Eduverse**
(`267031898`, THB, Visa ••••8227). Thai market first. Nothing published.

Companion to [FACEBOOK_ADS.md](FACEBOOK_ADS.md) (Eduverse) and
[research-meta-2026.md](research-meta-2026.md) (Meta mechanics). **The Eduverse
campaign's lessons are baked in here rather than relearned** — see §6.

---

## 1. ⚠️ One blocker before anything else

✅ **Page exists** — `facebook.com/aivdothai` (AIVDO | Bangkok). Run the ads from
this, never from `Eduverse.digital`: a shared Page would blur two brands and
pollute both Pages' audiences and insights.

⚠️ **Its follower count and posting history are unknown to me** (the Page render
didn't expose them). Worth a glance before launch — a Page with no posts at all
reads as abandoned to anyone who taps the advertiser name, and that is a cheap
thing to fix with two or three organic Motion Ad posts first.

**The ad account is shared, and it is nearly capped.** The Eduverse campaign is
live until **08-17** on this same account, which has a **฿5,000 account spending
limit** with ~฿583 already spent. Two campaigns on one account share:

- that spending limit,
- the billing threshold (bills at ฿8,000 or month end),
- and the payment method.

**DECIDED 2026-08-13: launch 08-14, in parallel with Eduverse's last four
days.** An earlier version of this doc recommended waiting until 08-17. One
argument in it was wrong and is worth correcting rather than deleting:

⚠️ **Measurement is NOT contaminated by running both.** The two campaigns land
on different domains with separate Cloud Run request logs and separate user
tables, so attribution stays cleanly separated. The overlap is budget and
delivery only.

What running in parallel actually costs:

- **~฿305/day combined** (Eduverse ฿155 + AIVDO ฿150) against the shared
  ฿5,000 account spending limit. **Check the current counter before launch** —
  when it is reached, *both* campaigns stop, not just the newer one.
- **The ฿8,000 billing threshold arrives sooner.** Cash-flow timing, not a
  performance issue.
- **Auction overlap.** Both target broad Thailand with overlapping age bands, so
  the same person can be eligible for both. Meta resolves same-advertiser
  collisions by picking one and suppressing the other, which can under-deliver
  whichever ad set it judges weaker. ⚠️ Stated from general knowledge — I could
  not re-verify it against Meta's docs this session (the `meta-devtools` MCP had
  disconnected). Worth confirming in the Help Center before drawing conclusions
  from a low-delivery day.

**Why the timing is defensible anyway:** Eduverse's read is largely in — CTR has
settled at ~2.1% and both its conversions have landed. Four more days at ฿155
buys little new information, so the delivery it loses to AIVDO is cheap.

## 2. What AIVDO is, from its own site

Positioning: *"สตูดิโอ AI สำหรับคอนเทนต์ครีเอเตอร์ไทย"* — AI studio for Thai
content creators. Headline *"สตูดิโอเล่าเรื่องด้วย AI"*, CTA
*"เริ่มสร้าง — ฟรี"*, with **✓ ไม่ต้องใช้บัตรเครดิต ✓ ได้ 10 เครดิตฟรี**.

Formats: narrative video 1–10 min, AISlide, **Motion Ad**, Omni Studio, AIVDO
Learn. Languages TH/EN/JP/CN/KR.

Pricing: Free (10 credits) · **฿199** Starter (100) · **฿499** Creator (300) ·
**฿1,490** Business (1,000).

✅ **The funnel is clean — verified 2026-08-13.** `/app` bounces a logged-out
visitor to `/`, and **เริ่มสร้าง — ฟรี** opens a signup modal in place (email +
Google). No navigation, no dead end. Nothing resembling the silent 401 that cost
Eduverse three days.

## 3. Why this is a better paid-acquisition bet than Eduverse

**The economics work.** Eduverse cost **฿292/signup** against a ฿149–259/month
product — marginal. AIVDO's tiers are ฿199 / ฿499 / ฿1,490, so the same ฿292
pays back inside two months on Starter and under one on Creator. The CAC ceiling
is several times higher.

**The free tier removes the wall.** Eduverse's ad promised a goal box that
needed an account. AIVDO can promise *10 free credits, no card* and deliver
exactly that.

**The product makes its own ads.** Motion Ad generates 11-second vertical spots.
So AIVDO can be advertised *with AIVDO output* — self-demonstrating proof, and
it dissolves the creative-volume constraint every 2026 source names. Very few
advertisers have this.

## 4. The wedge: Motion Ad for sellers, not documentaries

The site leads with documentary storytelling. **The ads should lead with Motion
Ad**, for three reasons:

1. **Demonstrated willingness to pay.** A Thai seller monetises a ฿990 Claude
   Skill that animates product photos into motion ads, claiming ROAS 2.5–4
   (wiki: `Claude Motion Clip — Motion-Ad Signal (2026-06-30)`). That is a
   narrower tool at a higher price than AIVDO Starter.
2. **Sellers are targetable.** Facebook can reach people running commerce pages;
   "documentary creator" is not a targeting concept.
3. **The value is judged in seconds** — a product photo becomes an ad. Narrative
   video needs a script the viewer hasn't written yet.

Storytelling stays the better *product* positioning. This is about which door
cold traffic walks through.

## 5. Campaign one

| Setting | Value |
|---|---|
| Objective | **Traffic** — no pixel exists (verified: no `connect.facebook.net`, `fbq(` or gtag on `/` or `/pricing`) |
| Location | Thailand |
| Age | **22–45** — younger skew than Eduverse; creators and sellers start earlier |
| Gender | All |
| Detailed targeting | *Empty* — broad, same as Eduverse. Add interests only after a baseline exists |
| **Advantage+ audience** | **OFF** — it overrides age targeting (`age_max` fixed at 65, per Meta's docs) and **defaults ON for every new ad set** |
| **Advantage+ creative** | **OFF** — rewrites headlines and breaks the A/B |
| Placements | Facebook Feed + Instagram Feed + **Reels** — see the creative note |
| Budget | ฿150/day × 7 days ≈ ฿1,050 |
| Landing | `https://www.aivdo.ai/?utm_source=facebook&utm_medium=paid_social&utm_campaign=w34-aivdo-motion` (and `…-narrative`) |
| CTA | **Sign up** — the button opens a signup modal, so it is honest |

**On Reels:** unlike Eduverse, AIVDO *has* native 9:16 video — its own Motion Ad
output. So Reels should be **included**, not excluded. The Eduverse restriction
was a consequence of a 1:1 asset, not a rule.

## 6. Lessons carried over from Eduverse, so they aren't relearned

- **Verify the funnel before spending.** Done — §2. That check would have saved
  ฿583 and three days on Eduverse.
- **Set up UTM capture before launch, not after.** AIVDO is on Cloud Run, so the
  request-log method works retroactively, but landing `utm_*` on the user row
  from day one avoids the archaeology. **This is the one build task.**
- **Read breakdowns, never summary cards.** Every real Eduverse finding came
  from a breakdown; three dashboards reported three different numbers.
- **Match the CTA to the page.** "Apply now" against a page with nothing to
  apply to cost Eduverse its first two days.
- **Advantage+ is opt-out and silently overrides intent.**
- **Don't judge before ~3 clean days**, and don't edit mid-flight — Eduverse
  absorbed three learning-phase resets.

## 7. The two ads

One ad set, two ads, same creative treatment. Varying the **wedge** rather than
the wording is what tells you something.

Both checked for length; Thai is **AI-written and unverified** — have a native
speaker read it before publishing, same rule as eduverse-one.

---

### Ad A — Motion Ad for sellers · `w34-aivdo-motion`

primary 203 · headline 25 · description 26

> มีแค่รูปสินค้า แต่อยากได้คลิปโฆษณาที่ดูมืออาชีพ? อัปโหลดรูปขึ้น AIVDO เลือกสไตล์ แล้วได้คลิปแนวตั้ง 11 วินาที พร้อมเสียงพากย์ไทยและเพลงประกอบ เอาไปลงเพจหรือ Reels ได้เลย
>
> เริ่มฟรี 10 เครดิต ไม่ต้องผูกบัตร

**Headline** รูปสินค้า ทำเป็นคลิปโฆษณา
**Description** เสียงพากย์ไทย พร้อมลงโฆษณา

### Ad B — Narrative video for creators · `w34-aivdo-narrative`

primary 206 · headline 22 · description 26

> มีสคริปต์อยู่แล้ว แต่ไม่มีเวลาตัดต่อ? วางสคริปต์ลง AIVDO แล้วได้วิดีโอเล่าเรื่องยาว 1–10 นาที พร้อมเสียงบรรยายไทยและซับไตเติล เหมาะกับ YouTube, TikTok long-form และ podcast
>
> เริ่มฟรี 10 เครดิต ไม่ต้องผูกบัตร

**Headline** สคริปต์ กลายเป็นวิดีโอ
**Description** เสียงบรรยายไทย + ซับไตเติล

## 8. Creative — use the product's own output

**Ad A:** a real Motion Ad, 11s 9:16 with Thai VO. The strongest possible proof
is the thing the ad is selling. Costs 5 AIVDO credits.

**Ad B:** a 15–30s excerpt of a real narrative render, 9:16 or 4:5.

⚠️ **Do not use a website screenshot.** That was the right call for Eduverse
because the product is a web app; AIVDO's product *is* video, and a static
screenshot of a video tool argues against itself.

## 9. Reading it

- **CTR** vs ~1.71% traffic / ~1.80% education benchmark. Eduverse settled at
  ~2.1% once fixed — a fair internal comparison.
- **Which wedge wins**, A or B. That is the real question and it is a product
  signal, not just an ad one.
- **Signups**, via the UTM on the user row (§6) — not the Meta dashboard.
- **Cost per signup against ฿199/฿499.** Below ~฿400 is workable; Eduverse's
  ฿292 would be comfortably profitable here.

Don't judge before day 3. Don't edit before then either.
