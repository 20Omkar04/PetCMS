# PetCMS

An Imgur-style photo gallery for your pets, built as ~12 small Dockerized
services behind a single gateway, using Supabase for auth/database/storage,
vanilla HTML/CSS/JS on the frontend, and your own AI API key for tagging and
chat.

## Architecture

```
                              ┌─────────────┐
                    (browser) │   Gateway    │  :8080  — serves frontend + proxies /api/*
                              └──────┬──────┘
        ┌───────────┬────────────────┼────────────────┬───────────────┬─────────────┐
        │            │                │                │               │             │
   Auth Svc     User Svc        Upload Svc        Search Svc      Memory Svc    Chatbot Svc
   :5001        :5002           :5003             :5008           :5009         :5010
                                   │                                                │
                        ┌──────────┼──────────┬─────────────┐                       │
                        │          │          │             │                       │
                  Storage Svc  Exif Svc   AI Tagging Svc     └── (reads Memory + Search data)
                  :5004        :5005      :5006

   Category Svc :5007          Vet/Map Svc :5011 (Overpass API / OpenStreetMap)
```

All state lives in **Supabase**: Postgres tables (with row-level security),
Supabase Auth, and Supabase Storage for the image files. Every service holds
a `SUPABASE_SERVICE_ROLE_KEY` and therefore bypasses RLS at the DB layer —
**each service manually filters every query by `owner_id = <the authenticated
user>`**, so the security boundary is enforced in application code, not by
RLS alone. Keep the service-role key server-side only; never ship it to the
browser (the gateway/frontend never receives it).

## What's genuinely implemented vs. simplified

This is a full working scaffold, not a toy — but a few things are worth
knowing before you treat it as production-ready:

- **Username/password login**: Supabase Auth is email-based under the hood,
  so each username is mapped to `username@petcms.local` internally. This is
  a common workaround but means you can't use Supabase's email-verification
  or password-reset-by-email flows as-is.
- **AI tagging / chatbot**: both call the user's own stored OpenAI or Gemini
  key server-side. If no key is set, tagging returns no tags and the
  chatbot falls back to simple rule-based answers over your stored
  metadata — uploads and browsing still work fully either way.
- **EXIF extraction**: works for JPEG/TIFF files with embedded EXIF (most
  phone photos). Many web-downloaded or already-stripped images won't have
  GPS/timestamp data — that's a property of the file, not a bug.
- **Overpass API**: public instance, rate-limited and occasionally slow.
  For heavy use, point `vet-map-service` at a self-hosted Overpass instance.
- **The frontend is served by mounting `./frontend` into the gateway
  container** (see `docker-compose.yml`) rather than copying it into the
  image at build time — convenient for local editing, but if you deploy the
  gateway image elsewhere without that volume, copy `frontend/` into the
  image (`COPY ./frontend /app/frontend`) first.

## Setup

### 1. Create a Supabase project
1. Go to https://supabase.com and create a new project.
2. In **Project Settings → API**, copy the Project URL, `anon` public key,
   and `service_role` key.
3. In **Project Settings → Auth → Providers**, make sure Email is enabled
   (it is by default) and, if you want frictionless registration during
   testing, turn off "Confirm email" under **Auth → Settings**.
4. Open the **SQL Editor**, paste in `supabase/schema.sql` from this repo,
   and run it. This creates all tables, RLS policies, and the storage
   bucket.

### 2. Configure environment
```bash
cp .env.example .env
# edit .env with your Supabase URL/keys and a random API_KEY_ENCRYPTION_SECRET
```

Generate a secret:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Build and run
```bash
docker compose up --build
```

The app will be available at **http://localhost:8080**.

### 4. Use it
1. Register a user ID + password on the landing page.
2. Optionally paste an OpenAI or Gemini API key (Settings page can add/remove
   this anytime).
3. Upload a photo — if it has EXIF GPS/timestamp data, it'll show up on the
   Map page and in the memory timeline automatically.
4. Use the chatbot (bottom-right bubble) to ask things like "when's my most
   recent upload?" or "show me anything tagged outdoors."

## Repo layout

```
gateway/                 Public entry point: serves frontend, proxies /api/*
frontend/                Vanilla HTML/CSS/JS SPA
services/
  auth-service/          Register/login/refresh via Supabase Auth
  user-service/          Profile + encrypted AI API key storage
  upload-service/        Orchestrates storage + EXIF + AI tagging + memory log on upload
  storage-service/       Supabase Storage wrapper (upload/signed-url/delete)
  exif-service/          Pillow-based EXIF/GPS/device extraction
  ai-tagging-service/    Calls the user's OpenAI/Gemini key to generate tags
  category-service/      CRUD for custom categories
  search-service/        Gallery listing, filtering, image get/edit
  memory-service/        Memory timeline events + manual notes
  chatbot-service/       Q&A over stored images + timeline, using the user's AI key
  vet-map-service/       Overpass API lookup for nearby vet clinics
supabase/schema.sql      Full DB schema, RLS policies, storage bucket + policies
scripts/sync_shared.sh   Re-copies _shared/common.py into each service (run after editing it)
```

## Editing the shared auth/DB helper

`_shared/common.py` holds the Supabase client helpers and the `require_auth`
decorator used by most services. It's copied (not symlinked, so each
service stays an independent Docker build context) into every service that
needs it. After changing it, re-run:
```bash
bash scripts/sync_shared.sh
docker compose build
```

## Security notes before going further than local dev

- Put the gateway behind HTTPS (a reverse proxy like Caddy/Traefik/nginx in
  front of it) — tokens and the API key form should never travel over plain
  HTTP outside of local development.
- Rotate `API_KEY_ENCRYPTION_SECRET` only if you're prepared to lose access
  to previously-encrypted keys (users would need to re-enter them).
- Consider rate-limiting `/api/auth/*` and `/api/chat` at the gateway if
  exposing this beyond trusted users.
