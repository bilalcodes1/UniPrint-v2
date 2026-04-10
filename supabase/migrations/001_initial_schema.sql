-- ─────────────────────────────────────────────────────────────────────────────
-- UniPrint – Supabase Initial Schema
-- ─────────────────────────────────────────────────────────────────────────────

-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- ── students ─────────────────────────────────────────────────────────────────
create table if not exists public.students (
  national_id_hash  text primary key,
  name              text,
  department        text,
  stage             text,
  device_fingerprint text,
  total_prints      integer default 0,
  last_seen         timestamptz,
  created_at        timestamptz default now(),
  updated_at        timestamptz default now()
);

-- ── print_requests ────────────────────────────────────────────────────────────
create table if not exists public.print_requests (
  id                      text primary key,
  student_national_id_hash text references public.students(national_id_hash) on delete set null,
  student_name            text,
  source                  text default 'lan',   -- 'lan' | 'online'
  status                  text default 'received',
  verification_code       text,
  notes                   text,
  notification_method     text default 'none',
  contact                 text,
  notification_sent       boolean default false,
  total_pages             integer default 0,
  rating                  integer,
  created_at              timestamptz default now(),
  updated_at              timestamptz default now(),
  delivered_at            timestamptz,
  row_version             integer default 1
);

-- ── request_files ─────────────────────────────────────────────────────────────
create table if not exists public.request_files (
  id            text primary key,
  request_id    text references public.print_requests(id) on delete cascade,
  original_name text,
  storage_path  text,   -- Supabase Storage path
  pages         integer default 0,
  copies        integer default 1,
  color         boolean default false,
  sides         text default 'one',
  file_size     integer,
  mime_type     text,
  created_at    timestamptz default now()
);

-- ── library_files ─────────────────────────────────────────────────────────────
create table if not exists public.library_files (
  id          serial primary key,
  path        text unique,
  name        text,
  pages       integer default 0,
  size        integer,
  department  text,
  stage       text,
  subject     text,
  professor   text,
  hash        text,
  indexed_at  timestamptz default now()
);

-- ── outbox ────────────────────────────────────────────────────────────────────
create table if not exists public.outbox (
  id          serial primary key,
  event_type  text,
  payload     jsonb,
  processed   boolean default false,
  retries     integer default 0,
  created_at  timestamptz default now()
);

-- ── daily_stats ───────────────────────────────────────────────────────────────
create table if not exists public.daily_stats (
  date                  date primary key,
  total_requests        integer default 0,
  total_pages_printed   integer default 0,
  total_delivered       integer default 0
);

-- ── settings ─────────────────────────────────────────────────────────────────
create table if not exists public.settings (
  key    text primary key,
  value  text
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Row Level Security (RLS)
-- ─────────────────────────────────────────────────────────────────────────────

alter table public.students        enable row level security;
alter table public.print_requests  enable row level security;
alter table public.request_files   enable row level security;
alter table public.library_files   enable row level security;
alter table public.outbox          enable row level security;
alter table public.daily_stats     enable row level security;
alter table public.settings        enable row level security;

-- Students: anyone can insert (submit), only service_role can read all
create policy "students_insert_anon" on public.students
  for insert to anon with check (true);

create policy "students_select_own" on public.students
  for select to anon using (true);  -- read by hash only (no PII leak)

-- Print requests: anon can insert + read their own by ID
create policy "requests_insert_anon" on public.print_requests
  for insert to anon with check (true);

create policy "requests_select_anon" on public.print_requests
  for select to anon using (true);

create policy "requests_update_service" on public.print_requests
  for update to service_role using (true);

-- Request files: anon can insert
create policy "files_insert_anon" on public.request_files
  for insert to anon with check (true);

create policy "files_select_anon" on public.request_files
  for select to anon using (true);

-- Library files: anon can read
create policy "library_select_anon" on public.library_files
  for select to anon using (true);

-- Outbox, daily_stats, settings: service_role only
create policy "outbox_service" on public.outbox
  for all to service_role using (true);

create policy "stats_service" on public.daily_stats
  for all to service_role using (true);

create policy "settings_service" on public.settings
  for all to service_role using (true);

-- ─────────────────────────────────────────────────────────────────────────────
-- Supabase Storage – bucket for request files
-- ─────────────────────────────────────────────────────────────────────────────
insert into storage.buckets (id, name, public)
values ('request-files', 'request-files', false)
on conflict (id) do nothing;

-- Allow anon to upload to request-files bucket
create policy "request_files_upload" on storage.objects
  for insert to anon with check (bucket_id = 'request-files');

create policy "request_files_read" on storage.objects
  for select to anon using (bucket_id = 'request-files');

-- ─────────────────────────────────────────────────────────────────────────────
-- Realtime – enable for print_requests (for online students)
-- ─────────────────────────────────────────────────────────────────────────────
alter publication supabase_realtime add table public.print_requests;
