-- AI Embroidery Studio - Gate B schema (mirrors services/core/db.py).
-- The API uses the service role and scopes every query by user_id; RLS below is
-- defence in depth for any direct client access through Supabase.

create table if not exists public.emb_projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 120),
  fabric_preset text not null,
  status text not null default 'draft' check (status in ('draft', 'awaiting_test_sew', 'accepted')),
  current_revision integer not null default 0,
  compiled_revision integer,
  width_mm double precision,
  height_mm double precision,
  color_count integer,
  stitch_count integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists emb_projects_user_idx on public.emb_projects (user_id, updated_at desc);

create table if not exists public.emb_revisions (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.emb_projects(id) on delete cascade,
  revision integer not null,
  design_json jsonb not null,
  created_at timestamptz not null default now(),
  unique (project_id, revision)
);

create table if not exists public.emb_uploads (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.emb_projects(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  filename text not null,
  content_type text not null,
  declared_size integer not null,
  storage_key text not null,
  status text not null default 'pending' check (status in ('pending', 'uploaded', 'used')),
  created_at timestamptz not null default now()
);

create table if not exists public.emb_jobs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.emb_projects(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  revision integer,
  kind text not null check (kind in ('analyze', 'compile', 'export', 'ai_plan')),
  status text not null default 'queued',
  progress integer not null default 0,
  params jsonb,
  error_code text,
  error_message text,
  result jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists emb_jobs_user_status_idx on public.emb_jobs (user_id, status);

create table if not exists public.emb_artifacts (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.emb_projects(id) on delete cascade,
  revision integer not null,
  job_id uuid,
  kind text not null,
  storage_key text not null,
  checksum text not null,
  size_bytes integer not null,
  created_at timestamptz not null default now(),
  unique (project_id, revision, kind)
);

create table if not exists public.emb_test_sews (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.emb_projects(id) on delete cascade,
  revision integer not null,
  photo_storage_key text,
  issue_tags jsonb,
  notes text,
  created_at timestamptz not null default now()
);

-- Row level security: owners may read their own rows; all writes go through the API (service role).
alter table public.emb_projects  enable row level security;
alter table public.emb_revisions enable row level security;
alter table public.emb_uploads   enable row level security;
alter table public.emb_jobs      enable row level security;
alter table public.emb_artifacts enable row level security;
alter table public.emb_test_sews enable row level security;

create policy emb_projects_owner_read on public.emb_projects
  for select using (user_id = (select auth.uid()));
create policy emb_uploads_owner_read on public.emb_uploads
  for select using (user_id = (select auth.uid()));
create policy emb_jobs_owner_read on public.emb_jobs
  for select using (user_id = (select auth.uid()));
create policy emb_revisions_owner_read on public.emb_revisions
  for select using (exists (select 1 from public.emb_projects p where p.id = project_id and p.user_id = (select auth.uid())));
create policy emb_artifacts_owner_read on public.emb_artifacts
  for select using (exists (select 1 from public.emb_projects p where p.id = project_id and p.user_id = (select auth.uid())));
create policy emb_test_sews_owner_read on public.emb_test_sews
  for select using (exists (select 1 from public.emb_projects p where p.id = project_id and p.user_id = (select auth.uid())));

-- Private bucket; objects live under embroidery/private/{userId}/... and are only
-- handed out through short-lived signed URLs created by the API.
-- 50 MB cap per object; uploads are further limited to 8 MB by the API/worker.
insert into storage.buckets (id, name, public, file_size_limit) values ('embroidery', 'embroidery', false, 52428800)
  on conflict (id) do nothing;
create policy emb_storage_owner_read on storage.objects
  for select using (bucket_id = 'embroidery' and (storage.foldername(name))[2] = (select auth.uid())::text);
