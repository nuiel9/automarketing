# Platform Setup Guide for AutoMarketing

This guide walks through connecting each social platform to AutoMarketing. Each section provides concrete steps a non-engineer founder can follow to obtain the necessary credentials.

---

## 1. Meta (Facebook Page + Instagram)

### Overview
AutoMarketing uses Meta's Graph API to publish directly to your Facebook Page and Instagram Business account. Your app runs in **Development Mode**, which means you can post to your own properties without waiting for App Review.

### Steps

1. **Create a Meta App** at https://developers.facebook.com/
   - Click "Create App" → Business Type
   - Name it something like "AutoMarketing"
   - Accept Terms, click "Create App"

2. **Add Products to Your App**
   - From the app dashboard, find "Add Products"
   - Search for and add **Facebook Login**
   - Search for and add **Instagram Graph API**

3. **Configure Facebook Login (optional but recommended)**
   - In the left menu under Facebook Login, go to Settings
   - Add your development URL (e.g., `http://localhost:3000`) to "Valid OAuth Redirect URIs"
   - This allows you to test locally

4. **Verify App is in Dev Mode**
   - Top of your app dashboard, you should see "Development" mode label
   - Dev Mode allows posting to your own Page/IG without App Review
   - (To publish to others' pages later, you'd need to submit for App Review — but we don't need that yet)

5. **Link Your Instagram Business Account to Your Facebook Page**
   - Go to your Facebook Page
   - Settings → Instagram Account → Link Account
   - Select your Instagram Business Account
   - Complete the linking flow

6. **Generate a Long-Lived Page Access Token**
   - Go to https://developers.facebook.com/tools/explorer
   - In the dropdown at the top, select your app name
   - Make sure the page selector shows your Facebook Page
   - Look for an option to generate an access token; labels may differ as the console changes
   - Authenticate with your Facebook account
   - Copy the token (it will be very long)
   - Look for an option to convert it to a long-lived token (lasts ~60 days); copy the result

7. **Get Your Page ID and Instagram User ID**
   - While in the Graph API Explorer (same URL as above), make a GET request to `me`
   - Look for the response showing your user ID
   - Make a GET request to `me/accounts` — this shows your pages
   - Find your page in the list; note the `id` (this is your `META_PAGE_ID`)
   - Make a GET request to `{PAGE_ID}/instagram_business_account` — note the `id` (this is your `META_IG_USER_ID`)
   - Alternatively, you can get these from your Page Settings or Instagram Settings

8. **Fill Environment Variables**
   - `META_PAGE_ID`: Your Facebook Page ID (from step 7)
   - `META_IG_USER_ID`: Your Instagram Business Account User ID (from step 7)
   - `META_ACCESS_TOKEN`: The long-lived token from step 6

### Required Graph API Scopes
- `pages_manage_posts` — publish to your Page
- `pages_read_engagement` — read insights (likes, comments)
- `instagram_basic` — read Instagram data
- `instagram_content_publish` — publish to Instagram

---

## 2. X (Twitter)

### Overview
AutoMarketing uses X's API to publish posts to your brand account. X offers a free tier with OAuth 1.0a user context (your account credentials), allowing Read and Write access.

### Steps

1. **Create a Developer Account**
   - Go to https://developer.x.com/
   - Sign in with your X account (the account you want to post from)
   - Complete the sign-up flow (verify email, accept terms)

2. **Create a Project and App**
   - Click "Projects & Apps" → "Create Project"
   - Name it "AutoMarketing"
   - Select use case (e.g., "I want to build a tool for creators")
   - Click "Create Project"
   - You'll be prompted to create an App within the project; name it "AutoMarketing"
   - Click "Create"

3. **Get Your API Keys**
   - In your app dashboard, go to the "Keys and tokens" tab
   - You should see:
     - API Key (Consumer Key) → copy as `X_CONSUMER_KEY`
     - API Key Secret (Consumer Secret) → copy as `X_CONSUMER_SECRET`
   - If they're not shown, click "Regenerate" to create new ones

4. **Enable OAuth 1.0a**
   - In your app settings, find "Authentication Settings"
   - Toggle **OAuth 1.0a** to ON
   - Set **User context permissions** to: `Read and Write`
   - Set **Callback URI / Redirect URL** to: `http://localhost:3000/callback` (or your production URL later)
   - Save

5. **Generate Access Token and Secret**
   - Go to the "Keys and tokens" tab
   - Look for an option to generate authentication tokens
   - Select "User context" and Read and Write permissions
   - Complete the authorization flow
   - Copy:
     - Access Token → `X_ACCESS_TOKEN`
     - Access Token Secret → `X_ACCESS_TOKEN_SECRET`

6. **Fill Environment Variables**
   - `X_CONSUMER_KEY`: From step 3
   - `X_CONSUMER_SECRET`: From step 3
   - `X_ACCESS_TOKEN`: From step 5
   - `X_ACCESS_TOKEN_SECRET`: From step 5

### Notes
- The free tier's monthly post cap is limited but comfortably covers our ~16 posts/month; check current limits at developer.x.com when you create the app.
- The user context approach means AutoMarketing posts as you (your brand account)

---

## 3. YouTube (Audit Application — File Now)

### Overview
YouTube requires API approval (audit) for the `youtube.upload` scope, which lets you programmatically upload videos. The audit process takes 1–2 weeks. **File your audit application now**, even though the YouTube adapter lands in Phase 2 (we'll be ready when it's available).

**Important:** Until your app passes audit, video uploads will be locked as **private**. This is our planned interim behavior — you can test uploads, but they won't be public until audit clears.

### Steps

1. **Create a Google Cloud Project**
   - Go to https://console.cloud.google.com/
   - Look for an option to create a new project (labels may differ as the console changes)
   - Name it "AutoMarketing"
   - Wait for the project to initialize

2. **Enable the YouTube Data API v3**
   - In the console, navigate to APIs & Services (look for "Library" or "APIs")
   - Search for "YouTube Data API v3"
   - Find it in the list and enable it

3. **Create an OAuth 2.0 Credential**
   - Go to APIs & Services → Credentials (or equivalent)
   - Look for an option to create OAuth credentials; select OAuth client ID
   - If prompted to configure the consent screen first:
     - Look for "Configure Consent Screen"
     - Select "External" (your app will be yours initially)
     - Fill in App Name ("AutoMarketing"), User Support Email, Developer Contact Info
     - Add or find the `youtube.upload` scope
     - Save and continue
   - Back on Credentials, create the OAuth client ID again
   - Application type: "Web application" or "Desktop app"
   - Name it "AutoMarketing"
   - Download the JSON file (save it securely — this is sensitive)

4. **Request Audit for `youtube.upload` Scope**
   - Go to APIs & Services → OAuth consent screen (or similar)
   - Look for the "Scopes" section
   - Find `youtube.upload` listed as a restricted scope
   - Look for a "Request Verification" option next to it
   - Fill out the audit form:
     - **App name:** AutoMarketing
     - **Scope justification:** Explain briefly: "We publish pre-approved marketing videos to YouTube on behalf of content creators. Videos are initially private to allow review before publication."
     - **Video demonstrating the feature:** Upload a short screen recording showing your app's publish flow (or state N/A if not ready)
     - **Link to your privacy policy:** Provide a link to your privacy policy (create one if needed)
   - Submit

5. **Await Audit Decision**
   - Google will review your application (typically 1–2 weeks)
   - You'll receive an email when the decision is made
   - Once approved, the `youtube.upload` scope becomes available for your app

### Important: Interim Behavior
- Until audit approval, uploaded videos are locked **private**
- This allows testing without public exposure
- Once audit clears, you can set videos to public via the API

### Storing Your Credentials
Store the credentials you created (Google Cloud Project ID, OAuth Client ID, and Client Secret) in your password manager — the corresponding env vars ship with the Phase 2 adapters.

---

## 4. TikTok (Audit Application — File Now)

### Overview
TikTok requires audit approval for the Content Posting API. Like YouTube, **file your audit application now** (adapter lands Phase 2). Until your app is audited, it can only push drafts to your own inbox — perfect for testing.

### Steps

1. **Create a TikTok Developer Account**
   - Go to https://developers.tiktok.com/
   - Click "Start Building"
   - Sign in with your TikTok account or create a TikTok account if needed
   - Accept terms and complete registration

2. **Create an Application**
   - Go to your developer dashboard
   - Look for an option to create a new application (labels may differ)
   - **Application name:** AutoMarketing
   - **Application category:** Marketing
   - Accept terms and create

3. **Request Access to Content Posting API**
   - In your app dashboard, look for "Products," "Permissions," or similar
   - Find "Content Posting API"
   - Look for a "Request Access" or "Add Permission" option
   - Fill out the form asking about your use case
   - Fill it out:
     - **Use case:** Programmatic video publishing for marketing campaigns
     - **Target audience:** Your own TikTok account
     - **Expected volume:** 3–4 posts per week (our content cadence)
   - Submit the request

4. **Complete Audit Application**
   - TikTok will send you an email with next steps
   - The audit may require:
     - A video demonstration of your app's functionality
     - Your privacy policy
     - Proof of your TikTok account (screenshot of your profile)
   - Follow TikTok's email instructions to submit these materials
   - Typical timeline: 1–2 weeks

5. **Interim Behavior**
   - Before audit approval, your app can **push videos as drafts to your own inbox**
   - This lets you review and manually publish, perfect for testing
   - Once audited, you can auto-publish

### Important: Interim Behavior
- Unaudited apps can only push drafts to your inbox
- You manually review and publish from TikTok
- This is our planned interim behavior — it's safe and controllable

### Storing Your Credentials
Record whatever credentials the app's detail page shows (typically a client key and secret) in your password manager — the corresponding env vars ship with the Phase 2 adapter.

---

## 5. LINE Official Account (LINE OA)

### Overview
You already have a LINE OA (Official Account) for Eduverse. We'll reuse its existing channel access token. You also need your personal LINE user ID to receive publish-failure alerts.

### Steps

1. **Get the Existing LINE OA Channel Access Token**
   - The channel access token already in use by the support bot is stored in that bot's deployment secrets
   - Ask the engineer for its value and reuse it
   - **Important:** Do NOT click "Issue" in the LINE Developers Console (https://developers.line.biz/) — issuing a new token invalidates the current one and would break the running support bot
   - This is your `LINE_CHANNEL_ACCESS_TOKEN`

2. **Get Your Personal LINE User ID**
   - Your support-bot's webhook events (stored in message logs or database) contain your LINE user ID
   - Ask an engineer to extract your user ID from the support-bot's webhook logs
   - This is your `LINE_FOUNDER_USER_ID`

3. **Check Broadcast Quota**
   - Go to your LINE Official Account Settings
   - Check "Plan & Pricing" or "Billing"
   - Note your current plan's broadcast limit (e.g., 1000/month, unlimited, etc.)
   - Document this for reference
   - Add a note to your team: If you hit the broadcast quota, upgrade your plan or wait for the monthly reset

4. **Fill Environment Variables**
   - `LINE_CHANNEL_ACCESS_TOKEN`: The existing long-lived token from step 1
   - `LINE_FOUNDER_USER_ID`: Your personal LINE user ID from step 2

### Important: Broadcast Quota
- LINE Official Accounts have a monthly broadcast limit based on plan
- Each auto-post to LINE counts as 1 broadcast message
- If you hit the limit, you'll need to upgrade your plan or wait for the next month
- Check your plan's limits in LINE Business Center to avoid surprise blocks

---

## Summary: Environment Variables

Copy the values you've obtained into your `.env` file:

| Variable | Source |
|----------|--------|
| `META_PAGE_ID` | Meta Graph API Explorer (`me/accounts`) |
| `META_IG_USER_ID` | Meta Graph API Explorer (`{PAGE_ID}/instagram_business_account`) |
| `META_ACCESS_TOKEN` | Meta Graph API Explorer (long-lived token) |
| `X_CONSUMER_KEY` | X Developer Dashboard (API Key) |
| `X_CONSUMER_SECRET` | X Developer Dashboard (API Key Secret) |
| `X_ACCESS_TOKEN` | X Developer Dashboard (User Context token) |
| `X_ACCESS_TOKEN_SECRET` | X Developer Dashboard (User Context secret) |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Developers Console (long-lived Eduverse channel token) |
| `LINE_FOUNDER_USER_ID` | Support-bot webhook logs |

---

## Next Steps

1. Complete the checklists above for each platform you plan to enable
2. Copy obtained credentials to your `.env` file (copy `.env.example` → `backend/.env`)
3. Enable each channel in `ENABLED_CHANNELS` in your `.env` (comma-separated list)
4. For YouTube and TikTok: submit audit applications now, even though those adapters launch in Phase 2

For questions or issues, refer to each platform's official documentation or reach out to your team.
