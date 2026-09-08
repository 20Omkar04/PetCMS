-- =========================================================================
-- PetCMS Supabase schema
-- Run this in the Supabase SQL editor (Project -> SQL Editor -> New query)
-- Assumes Supabase Auth is already enabled (auth.users table exists).
-- =========================================================================

create extension if not exists "uuid-ossp";

-- ---------------------------------------------------------------- profiles
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text unique,
  encrypted_api_key text,          -- AES-encrypted AI API key, set via Settings page
  api_key_provider text,           -- 'openai' | 'gemini'
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "profiles_select_own" on public.profiles
  for select using (auth.uid() = id);
create policy "profiles_upsert_own" on public.profiles
  for insert with check (auth.uid() = id);
create policy "profiles_update_own" on public.profiles
  for update using (auth.uid() = id);

-- ------------------------------------------------------------- categories
create table if not exists public.categories (
  id uuid primary key default uuid_generate_v4(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  created_at timestamptz not null default now(),
  unique (owner_id, name)
);

alter table public.categories enable row level security;
create policy "categories_owner_all" on public.categories
  for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

-- ----------------------------------------------------------------- images
create table if not exists public.images (
  id uuid primary key default uuid_generate_v4(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  storage_path text not null,
  filename text,
  caption text,
  pet_type text,                     -- e.g. dog, cat, bird, other
  categories text[] default '{}',    -- manual categories
  tags text[] default '{}',          -- merged manual + AI tags
  ai_tags text[] default '{}',
  manual_tags text[] default '{}',
  exif jsonb default '{}'::jsonb,     -- raw extracted EXIF
  gps_lat double precision,
  gps_lng double precision,
  taken_at timestamptz,               -- from EXIF DateTimeOriginal, falls back to upload time
  device text,                        -- camera/phone model from EXIF
  created_at timestamptz not null default now()
);

create index if not exists images_owner_idx on public.images (owner_id);
create index if not exists images_taken_at_idx on public.images (taken_at);
create index if not exists images_tags_idx on public.images using gin (tags);
create index if not exists images_categories_idx on public.images using gin (categories);

alter table public.images enable row level security;
create policy "images_owner_all" on public.images
  for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

-- --------------------------------------------------------- memory_events
create table if not exists public.memory_events (
  id uuid primary key default uuid_generate_v4(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  image_id uuid references public.images(id) on delete set null,
  event_type text not null,          -- 'upload' | 'tagged' | 'note' | 'deleted'
  description text not null,
  event_time timestamptz not null default now()
);

create index if not exists memory_owner_idx on public.memory_events (owner_id, event_time desc);

alter table public.memory_events enable row level security;
create policy "memory_owner_all" on public.memory_events
  for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

-- ----------------------------------------------------------- chat_history
create table if not exists public.chat_history (
  id uuid primary key default uuid_generate_v4(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  role text not null,                -- 'user' | 'assistant'
  message text not null,
  created_at timestamptz not null default now()
);

create index if not exists chat_owner_idx on public.chat_history (owner_id, created_at);

alter table public.chat_history enable row level security;
create policy "chat_owner_all" on public.chat_history
  for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

-- ---------------------------------------------------------------- storage
insert into storage.buckets (id, name, public)
values ('pet-images', 'pet-images', false)
on conflict (id) do nothing;

create policy "storage_owner_select" on storage.objects
  for select using (bucket_id = 'pet-images' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "storage_owner_insert" on storage.objects
  for insert with check (bucket_id = 'pet-images' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "storage_owner_delete" on storage.objects
  for delete using (bucket_id = 'pet-images' and (storage.foldername(name))[1] = auth.uid()::text);
