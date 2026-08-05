# Deploy Runbook (Cloud Run)

> **Run by a human or an approved session — this file is the script for Task 15's cloud half.**
> Everything below issues real `gcloud`/`docker` commands against a real GCP
> project: it provisions a database, a storage bucket, secrets, and public
> Cloud Run services. Nothing in `backend/Dockerfile`, `frontend/Dockerfile`,
> or `cloudbuild.yaml` runs any of this on its own — those are file-only
> artifacts (Task 15's file half); this doc is what turns them into a live
> deployment. Read a step fully before running it; several steps carry
> values forward into later steps.

## 0. Variables

This deploy reuses the **existing eduverse GCP project and Cloud SQL
instance** rather than provisioning new ones — same account, same org
constraints (no public Cloud SQL IP, no public GCS buckets) already worked
out for `eduverse-one`. `PROJECT` and `SQL_INSTANCE` below are carried over
from that deployment; confirm both before running anything (`gcloud config
get-value project`, `gcloud sql instances list --project=$PROJECT`) since
this session cannot verify them without running cloud commands.

```bash
PROJECT=eduverse-personal-krainat        # confirm: gcloud sql instances list --project=$PROJECT
REGION=asia-southeast1
REPO=automarketing                       # Artifact Registry repo (matches cloudbuild.yaml's _REPO)
SQL_INSTANCE=eduverse-one-staging        # existing instance — confirm name before use
DB_NAME=automarketing
DB_USER=automarketing
# hex, not base64: this password gets embedded directly in a libpq URI
# below (postgresql://user:pw@host/db) and in DATABASE_URL in step 6 — a
# base64 password can contain `/` or `+`, which breaks that URI's parsing.
DB_PASSWORD='<generate: openssl rand -hex 24 — save in password manager>'
BUCKET="${PROJECT}-automarketing-media"
BACKEND_SVC=automarketing-backend
FRONTEND_SVC=automarketing-frontend

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
# Cloud Run URLs are deterministic from project number + service + region
# (verified working for eduverse-one's own CORS_ORIGINS setup) — this lets
# the frontend build know the backend URL before the backend is ever
# deployed, no placeholder/redeploy dance needed.
BACKEND_URL="https://${BACKEND_SVC}-${PROJECT_NUMBER}.${REGION}.run.app"
FRONTEND_URL="https://${FRONTEND_SVC}-${PROJECT_NUMBER}.${REGION}.run.app"
```

Safety net: after step 6 deploys the backend, confirm the real URL matches
what was predicted — `gcloud run services describe "$BACKEND_SVC" --region="$REGION" --project="$PROJECT" --format='value(status.url)'`.
If it differs, rebuild the frontend image with the corrected `_BACKEND_URL`
(step 5) before deploying it (step 7) — `NEXT_PUBLIC_API_URL` only takes
effect at build time.

## 1. One-time per project

```bash
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker --location="$REGION" --project="$PROJECT"
```

(Skip if it already exists — `gcloud artifacts repositories describe "$REPO" --location="$REGION" --project="$PROJECT"` to check.)

## 2. Cloud SQL: new database + user on the existing instance

Connect through the Cloud SQL Auth Proxy (install: https://cloud.google.com/sql/docs/postgres/sql-proxy#install)
using an existing admin login for `$SQL_INSTANCE` (the same credential
eduverse-one's operator already has):

```bash
cloud-sql-proxy --port 5432 "${PROJECT}:${REGION}:${SQL_INSTANCE}" &
PROXY_PID=$!

psql "postgresql://<admin-user>:<admin-password>@127.0.0.1:5432/postgres" <<SQL
CREATE DATABASE ${DB_NAME};
CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
\c ${DB_NAME}
-- Postgres 15+ revokes CREATE on the public schema from PUBLIC by default;
-- without this alembic's CREATE TABLE fails with "permission denied for
-- schema public" even though the user owns the database.
GRANT ALL ON SCHEMA public TO ${DB_USER};
SQL
```

Then run the migration against that same proxy tunnel (still port 5432):

```bash
cd backend
DATABASE_URL="postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}" \
  alembic upgrade head
cd ..

kill $PROXY_PID
```

> **If `$SQL_INSTANCE` has no public IP** (it doesn't, for eduverse-one —
> `--no-assign-ip`), the machine running `cloud-sql-proxy` needs a network
> path to the instance's private IP: a GCE VM on the same VPC, a bastion
> reached via `gcloud compute ssh --tunnel-through-iap`, or a temporary
> public IP on the instance for this one session. This is an execution-time
> networking decision for whoever runs this file — pick whichever the
> account already has available.

## 3. GCS bucket for media (non-public)

```bash
gcloud storage buckets create "gs://${BUCKET}" \
  --location="$REGION" --project="$PROJECT" \
  --uniform-bucket-level-access --public-access-prevention=enforced

# Runtime SA needs to read/write objects; do NOT bind allUsers — the org
# policy rejects that binding outright (HTTP 412) and app/media.py always
# serves video through the backend's own /media/{token} route, never a
# bucket URL directly.
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role=roles/storage.objectAdmin --project="$PROJECT"
```

## 4. Secret Manager

```bash
ADMIN_TOKEN_VALUE='<generate: openssl rand -hex 24>'
TICK_TOKEN_VALUE='<generate: openssl rand -hex 24>'
ANTHROPIC_API_KEY_VALUE='<from console.anthropic.com>'

printf '%s' "$ADMIN_TOKEN_VALUE"      | gcloud secrets create ADMIN_TOKEN      --data-file=- --project="$PROJECT"
printf '%s' "$TICK_TOKEN_VALUE"       | gcloud secrets create TICK_TOKEN       --data-file=- --project="$PROJECT"
printf '%s' "$ANTHROPIC_API_KEY_VALUE" | gcloud secrets create ANTHROPIC_API_KEY --data-file=- --project="$PROJECT"

for SECRET in ADMIN_TOKEN TICK_TOKEN ANTHROPIC_API_KEY; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role=roles/secretmanager.secretAccessor --project="$PROJECT"
done
```

Save `$ADMIN_TOKEN_VALUE`, `$TICK_TOKEN_VALUE`, and `$DB_PASSWORD` in a
password manager now — `$TICK_TOKEN_VALUE` is needed again in cleartext for
the Cloud Scheduler header in step 8 (Scheduler can't read Secret Manager
for arbitrary HTTP headers).

## 5. Build and push both images

```bash
gcloud builds submit \
  --config=cloudbuild.yaml \
  --substitutions=_BACKEND_URL="$BACKEND_URL" \
  --region="$REGION" --project="$PROJECT" \
  .
```

Run from the **repo root** (`cloudbuild.yaml` builds the backend with
repo-root context so it can `COPY strategy.yaml`). Note the `$BUILD_ID`
Cloud Build prints — that's the image tag both deploys below use (or use
the `:latest` tag `cloudbuild.yaml` also pushes).

```bash
TAG=latest   # or the $BUILD_ID from the build above
```

## 6. Deploy the backend

```bash
gcloud run deploy "$BACKEND_SVC" \
  --image="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/backend:${TAG}" \
  --region="$REGION" --project="$PROJECT" \
  --allow-unauthenticated \
  --add-cloudsql-instances="${PROJECT}:${REGION}:${SQL_INSTANCE}" \
  --set-env-vars="^##^DATABASE_URL=postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@/${DB_NAME}?host=/cloudsql/${PROJECT}:${REGION}:${SQL_INSTANCE}##PUBLIC_BASE_URL=${BACKEND_URL}##FRONTEND_ORIGIN=${FRONTEND_URL}##MEDIA_BACKEND=gcs##GCS_BUCKET=${BUCKET}##MEDIA_ROOT=/tmp##ENABLED_CHANNELS=dryrun" \
  --set-secrets="ADMIN_TOKEN=ADMIN_TOKEN:latest,TICK_TOKEN=TICK_TOKEN:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest"
```

Notes:
- `--add-cloudsql-instances` mounts the Cloud SQL Auth Proxy's unix socket
  at `/cloudsql/...` inside the container regardless of whether the
  instance has a public IP — this is why `DATABASE_URL` uses the
  `?host=/cloudsql/...` socket form here instead of a TCP host:port.
- `MEDIA_ROOT=/tmp`: with `MEDIA_BACKEND=gcs`, `media_root` is used for
  exactly one thing — `DryRunAdapter`'s feed file
  (`app/channels/registry.py`) — but its default `./media` would try to
  `os.makedirs` a path Cloud Run's writable filesystem doesn't guarantee
  outside `/tmp` on gen1. Without this, every `/internal/tick` 500s and
  step 9's dryrun check never reaches `posted`.
- `ENABLED_CHANNELS=dryrun` on purpose: verification (step 9) proves the
  scheduler → DB → publisher → media path end-to-end before any real
  platform token is live. Flip channels on with the `gcloud run services
  update` command at the end of step 9 once that check passes.
- `ANTHROPIC_API_KEY` **must be a real, working key before step 9** — not
  optional. An item whose caption generation fails never leaves status
  `idea` (`app/api/items.py`'s `_generate` only transitions `idea →
  in_review` on success), and `approve()` requires status `in_review` to
  transition to `approved` (`app/state.py`'s `ITEM_TRANSITIONS`) — it
  checks that state transition before it ever reaches the dryrun-caption
  exemption, so a caption failure 409s the approve call outright, not a
  soft degradation.
  If `$ANTHROPIC_API_KEY_VALUE` was a placeholder when this service was
  deployed, update the secret with a real key
  (`printf '%s' "$REAL_KEY" | gcloud secrets versions add ANTHROPIC_API_KEY
  --data-file=- --project="$PROJECT"`) and redeploy — Cloud Run resolves
  `--set-secrets` to `:latest` at container start, so a fresh revision (or
  `gcloud run services update "$BACKEND_SVC" --region="$REGION"
  --project="$PROJECT" --update-secrets=ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest`)
  is enough — no image rebuild needed.

## 7. Deploy the frontend

```bash
gcloud run deploy "$FRONTEND_SVC" \
  --image="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/frontend:${TAG}" \
  --region="$REGION" --project="$PROJECT" \
  --allow-unauthenticated
```

No env vars here — `NEXT_PUBLIC_API_URL` is already baked into the built
JS bundle from step 5's `_BACKEND_URL` substitution. A frontend code
change (or a backend URL change) requires rebuilding the image, not just
redeploying.

## 8. Cloud Scheduler tick

```bash
gcloud scheduler jobs create http automarketing-tick \
  --schedule="*/5 * * * *" \
  --uri="${BACKEND_URL}/internal/tick" \
  --http-method=POST \
  --headers="X-Tick-Token=${TICK_TOKEN_VALUE}" \
  --location="$REGION" --project="$PROJECT"
```

## 9. Post-deploy verification

Do not skip — a `200` from `/healthz` proves the backend booted, nothing
about the frontend, the DB, the scheduler, or the media path.

1. **Backend health:**
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' "${BACKEND_URL}/healthz"   # expect 200
   ```
2. **Frontend loads and logs in:** open `$FRONTEND_URL` in a browser →
   redirects to `/login` → paste `$ADMIN_TOKEN_VALUE` → lands on the queue
   page with no console errors.
3. **Create a real item, dryrun-approve it, and watch it post:**

   This step **requires a working `ANTHROPIC_API_KEY`** in Secret Manager
   (see the step-6 note) — not optional, and not something the dryrun
   channel exempts you from. `create_item` only transitions an item out of
   status `idea` into `in_review` when caption generation succeeds
   (`app/api/items.py`'s `_generate`); `approve()` requires status
   `in_review` to transition to `approved`, so an item stuck in `idea`
   409s on approve regardless of channel — the dryrun caption exemption in
   `approve()` only skips the *caption-existence* check, not the
   *state-machine* check, and state comes first.

   ```bash
   ITEM=$(curl -s -X POST "${BACKEND_URL}/api/items" \
     -H "Authorization: Bearer ${ADMIN_TOKEN_VALUE}" \
     -F "topic=deploy smoke test" \
     -F "link=https://eduverse.one" \
     -F "file=@/path/to/tiny.mp4")
   ITEM_ID=$(echo "$ITEM" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
   echo "$ITEM" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("caption_error"))'
   ```

   If that prints anything other than `None`, caption generation failed
   (commonly: `ANTHROPIC_API_KEY` is still a placeholder — fix it per the
   step-6 note, then retry). Once the key is real, either recreate the
   item (command above) or regenerate captions on this one before
   approving:

   ```bash
   curl -s -X POST "${BACKEND_URL}/api/items/${ITEM_ID}/captions" \
     -H "Authorization: Bearer ${ADMIN_TOKEN_VALUE}"   # idea -> in_review on success
   ```

   Then approve for dryrun:

   ```bash
   curl -s -X POST "${BACKEND_URL}/api/items/${ITEM_ID}/approve" \
     -H "Authorization: Bearer ${ADMIN_TOKEN_VALUE}" -H "Content-Type: application/json" \
     -d "{\"scheduled_at\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\", \"channels\": [\"dryrun\"]}"
   ```
4. **Wait ≤5 minutes** (one scheduler tick), or trigger it immediately:
   ```bash
   gcloud scheduler jobs run automarketing-tick --location="$REGION" --project="$PROJECT"
   ```
5. **Confirm `posted`:**
   ```bash
   curl -s "${BACKEND_URL}/api/items/${ITEM_ID}" \
     -H "Authorization: Bearer ${ADMIN_TOKEN_VALUE}" \
     | python3 -c 'import sys,json;print(json.load(sys.stdin)["publications"])'
   # expect a "dryrun" entry with "status": "posted"
   ```
   This proves the scheduler, the DB, the publisher's row-level locking,
   and the media path all work in prod — the same thing a real channel
   post would exercise, minus the external API call.

Once this passes, flipping `ENABLED_CHANNELS` to the real channel list and
making one real scheduled post to each configured channel (per
`docs/PLATFORM_SETUP.md`'s Task 14 credentials) is the remaining Phase 1
cloud step — out of scope for this file's authorship but the natural next
command is:

```bash
gcloud run services update "$BACKEND_SVC" --region="$REGION" --project="$PROJECT" \
  --update-env-vars="ENABLED_CHANNELS=facebook,instagram,x,line,dryrun"
```
