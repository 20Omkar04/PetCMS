# PetCMS

An Imgur-style photo gallery for your pets: upload a photo and PetCMS
automatically reads its location and timestamp, suggests AI tags using
*your own* OpenAI or Gemini key, plots where it was taken on an
OpenStreetMap view with nearby vet clinics, and logs everything to a
searchable memory timeline you can ask a built-in chatbot about.

It's built as 12 small Dockerized services behind a single gateway, using
Supabase for auth/database/storage, and vanilla HTML/CSS/JS on the frontend
— no frameworks, no build step.

![PetCMS architecture](docs/architecture.png)

## Features

- **Email + password auth** via Supabase Auth, issuing real JWTs — every
  backend service independently verifies the token before trusting a
  request (see `_shared/common.py`'s `require_auth`).
- **Gallery** with search, and filters by pet type, category, tag, and date.
- **Upload pipeline**: EXIF extraction (GPS, timestamp, device) → AI tagging
  (OpenAI or Gemini, using a key you provide and control) → persisted once,
  never recomputed → logged to the memory timeline.
- **Editable tags** — remove or add tags on any photo after upload, AI- or
  manually-sourced.
- **Map & nearby vets** — Leaflet/OpenStreetMap view of everywhere you've
  taken photos, with live OSM Overpass lookups for nearby veterinary clinics.
- **Memory timeline** — an automatic log of uploads and events, plus your
  own manual notes.
- **Chatbot** — answers questions about your own photos/timeline, using
  your AI key when set, with a rule-based fallback when it isn't.
- **Settings** page for managing your AI key and categories, plus a
  **Session & JWT inspector** that decodes your live token (header, claims,
  expiry countdown) for transparency/debugging.

## Architecture

```
Browser (vanilla JS SPA)
      │
      ▼
Gateway  ── serves the frontend, proxies /api/*, every route is JWT-checked
      │
      ├── Auth service        (register/login/refresh via Supabase Auth)
      ├── User service         (profile + encrypted AI API key)
      ├── Upload service       (orchestrates storage + EXIF, then enqueues tagging)
      │     ├── Storage service    (Supabase Storage)
      │     └── EXIF service       (Pillow — GPS/timestamp/device)
      ├── Category service     (custom categories CRUD)
      ├── Search service       (gallery list/filter/edit)
      ├── Memory service       (timeline + notes)
      ├── Chatbot service      (Q&A over your images + timeline)
      └── Vet/Map service      (OSM Overpass — nearby vet clinics)

Redis (queue) ── AI Tagging worker(s) ── OpenAI/Gemini (user's own key)
      ▲                  │
      └── enqueued by Upload service     writes result back to Supabase
```

All state lives in Supabase: Postgres (with row-level security), Supabase
Auth, and Supabase Storage. Every service holds the service-role key and
therefore *can* bypass RLS — each one manually filters every query by
`owner_id = <the authenticated user>`, so the real security boundary is in
application code, not RLS alone. Never ship the service-role key to the
browser.

### Asynchronous AI tagging (event queue)

AI tagging is the one step in the upload pipeline that calls an external,
sometimes-slow, sometimes-unreliable third party (OpenAI/Gemini). Rather
than call it synchronously from `upload-service` — where a provider
timeout would fail the whole upload — it's decoupled via a Redis-backed
job queue (RQ):

1. `upload-service` stores the file and extracts EXIF synchronously (both
   fast, both local to our own infrastructure), writes the `images` row
   with `tagging_status: "processing"`, and enqueues a tagging job.
2. One or more `ai-tagging-worker` containers consume that queue in the
   background, fetch the image bytes from storage, call the AI provider,
   and update the row to `tagging_status: "ready"` (or `"failed"` /
   `"skipped_no_key"`, with the reason logged to the memory timeline).
3. The frontend shows a "🕒 tagging…" badge on a photo while processing,
   and polls briefly until it resolves — so tags visibly appear a few
   seconds after upload without a manual refresh.

This means an upload never fails because of AI provider slowness or
downtime, and every image's photo (bytes, storage, EXIF) is safely
persisted regardless of AI availability.

### Horizontal scaling

The tagging workers are intentionally decoupled from any specific service
address — they pull from a shared queue rather than being called by URL —
so scaling them is just running more consumers of the same queue:
```bash
docker compose up --scale ai-tagging-worker=3
```
No load-balancer configuration is needed for this: Docker Compose's
embedded DNS already round-robins requests across any scaled replica
addressed by service name (e.g. `http://exif-service:5005` from another
container), so `docker compose up --scale exif-service=3` works the same
way today with zero code changes, for services that *are* called
synchronously by URL. A custom reverse-proxy load balancer would be
redundant in a Compose (single-host) setup — it starts to matter in a
multi-host orchestrator like Kubernetes, which does its own service
discovery/load-balancing the same way for a different reason (spreading
work across physical nodes, not just processes).

### Observability

Prometheus + Grafana are included, scraping a `/metrics` endpoint
(via `prometheus-flask-exporter`) exposed by every HTTP service:
```bash
docker compose up --build
# Grafana:    http://localhost:3000  (admin / admin)
# Prometheus: http://localhost:9090
```
Grafana comes pre-provisioned with a "PetCMS — Service Overview" dashboard
(`monitoring/grafana/provisioning/dashboards/petcms-overview.json`)
showing request rate, average latency, and HTTP status code breakdown per
service — no manual dashboard setup needed.

## Setup


### 1. Create a Supabase project
1. Create a project at https://supabase.com.
2. **Project Settings → API**: copy the Project URL, `anon` key, and
   `service_role` key.
3. **Authentication → Providers → Email**: leave email confirmation on for
   real use; PetCMS uses real email addresses (not a placeholder domain).
4. **SQL Editor**: run `supabase/schema.sql` — creates all tables, RLS
   policies, and the storage bucket.

### 2. Configure environment
```bash
cp .env.example .env
# fill in SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY
# and generate a random API_KEY_ENCRYPTION_SECRET:
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Run it
```bash
docker compose up --build
```
Open **http://localhost:8080**, register with a real email + password, and
optionally add an OpenAI or Gemini key (Settings, or during onboarding).

## Repo layout

```
gateway/                 Public entry point: serves frontend, proxies /api/*
frontend/                Vanilla HTML/CSS/JS SPA
  ├── index.html
  ├── css/style.css
  └── js/                api.js, auth.js, app.js, map.js, timeline.js,
                          chatbot.js, settings.js, jwt-utils.js
services/
  ├── auth-service/       Register/login/refresh via Supabase Auth (real email)
  ├── user-service/       Profile + encrypted AI API key storage
  ├── upload-service/     Orchestrates storage + EXIF + AI tagging + memory log
  ├── storage-service/    Supabase Storage wrapper
  ├── exif-service/       Pillow-based EXIF/GPS/device extraction
  ├── ai-tagging-service/ Calls the user's OpenAI/Gemini key to generate tags
  ├── category-service/   CRUD for custom categories
  ├── search-service/     Gallery listing, filtering, image get/edit (incl. tags)
  ├── memory-service/     Memory timeline events + manual notes
  ├── chatbot-service/    Q&A over stored images + timeline
  └── vet-map-service/    Overpass API lookup for nearby vet clinics
supabase/schema.sql       Full DB schema, RLS policies, storage bucket + policies
docs/
  ├── architecture.png            The diagram above
  └── GREEN_AI_AND_ARCHITECTURE.md  Design rationale: JWT auth flow explained,
                                     and how the AI-usage design maps to
                                     Green AI principles (with citations)
scripts/
  ├── sync_shared.sh      Re-copies _shared/common.py into each service
  └── make_diagram.py     Regenerates docs/architecture.png
```

## Known limitations

- **OSM Overpass reliability**: the free public Overpass API (used for
  nearby-vet lookups) is occasionally flaky or rate-limited. The service
  tries several mirrors in sequence (`services/vet-map-service/app.py`);
  if all fail, the UI shows an error rather than crashing. For production
  use, consider self-hosting Overpass or adding a paid geocoding fallback.
- **EXIF depends on the photo**: screenshots, WhatsApp-forwarded images,
  and many web-downloaded photos have no EXIF data — that's a property of
  the file, not a bug.
- **AI tagging/chat degrade gracefully** with no API key configured
  (empty tags / rule-based chatbot answers) rather than blocking uploads.
- **AI model names drift** — providers deprecate models (this happened
  once already during development; see `docs/GREEN_AI_AND_ARCHITECTURE.md`
  for the broader design notes). If tagging silently stops working, check
  the current valid model string for your provider first.
- **Images are normalized before tagging** (`ai-tagging-service`'s
  `normalize_image`): web-downloaded photos in WEBP, CMYK JPEG, or with a
  mismatched extension were previously failing AI tagging silently, since
  vision APIs can reject those formats/color modes outright. Every image
  is now re-encoded to a clean sRGB JPEG before being sent to the provider.
- **The Redis queue has no persistence configured** (default in-memory
  `redis:7-alpine`). If the `redis` container restarts while jobs are
  queued or in flight, those jobs are lost — the affected photos stay at
  `tagging_status: "processing"` indefinitely. For anything beyond local
  use, either enable Redis AOF/RDB persistence or accept that a stuck
  "processing" badge means a manual re-tag is needed.

## Editing the shared auth/DB helper

`_shared/common.py` holds the Supabase client helpers and `require_auth`
decorator used by most services — copied (not symlinked) into each service
that needs it, so every service stays an independent Docker build context.
After changing it:
```bash
bash scripts/sync_shared.sh
docker compose build
```

## Security notes before going further than local/personal use

- Put the gateway behind HTTPS (a reverse proxy like Caddy/Traefik/nginx)
  — tokens should never travel over plain HTTP outside local development.
- Rotate `API_KEY_ENCRYPTION_SECRET` only if you're prepared to lose access
  to previously-encrypted keys (users would need to re-enter them).
- Consider rate-limiting `/api/auth/*` and `/api/chat` at the gateway.
