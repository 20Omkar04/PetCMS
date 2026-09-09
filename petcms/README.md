<img width="1900" height="1440" alt="image" src="https://github.com/user-attachments/assets/1405e273-cf50-4498-a60f-aee350361d1d" /># PetCMS

An Imgur-style photo gallery for your pets: upload a photo and PetCMS
automatically reads its location and timestamp, suggests AI tags using
*your own* OpenAI or Gemini key, plots where it was taken on an
OpenStreetMap view with nearby vet clinics, and logs everything to a
searchable memory timeline you can ask a built-in chatbot about.

It's built as 12 small Dockerized services behind a single gateway, using
Supabase for auth/database/storage, and vanilla HTML/CSS/JS on the frontend
— no frameworks, no build step.

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
      ├── Upload service       (orchestrates the pipeline below)
      │     ├── Storage service    (Supabase Storage)
      │     ├── EXIF service       (Pillow — GPS/timestamp/device)
      │     ├── AI Tagging service (OpenAI/Gemini, user's own key)
      │     └── Memory service     (timeline logging)
      ├── Category service     (custom categories CRUD)
      ├── Search service       (gallery list/filter/edit)
      ├── Memory service       (timeline + notes)
      ├── Chatbot service      (Q&A over your images + timeline)
      └── Vet/Map service      (OSM Overpass — nearby vet clinics)
```

All state lives in Supabase: Postgres (with row-level security), Supabase
Auth, and Supabase Storage. Every service holds the service-role key and
therefore *can* bypass RLS — each one manually filters every query by
`owner_id = <the authenticated user>`, so the real security boundary is in
application code, not RLS alone. Never ship the service-role key to the
browser.

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
