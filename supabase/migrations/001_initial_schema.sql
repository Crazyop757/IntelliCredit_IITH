-- FinSight — initial Supabase schema
-- Run via: supabase db push  OR  paste into Supabase SQL editor

-- ── Extensions ───────────────────────────────────────────────────────────────
create extension if not exists "uuid-ossp";

-- ── companies ────────────────────────────────────────────────────────────────
create table if not exists companies (
    id           text primary key,          -- slug / sha256-derived id
    name         text not null,
    cin          text,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now()
);

-- ── appraisals ───────────────────────────────────────────────────────────────
create table if not exists appraisals (
    id                  uuid primary key default uuid_generate_v4(),
    user_id             uuid not null references auth.users(id) on delete cascade,
    company_id          text not null references companies(id),
    company_name        text not null,
    job_id              text unique,
    status              text not null default 'PENDING'
                            check (status in ('PENDING','RUNNING','DONE','FAILED')),
    decision            text,
    risk_band           text,
    default_probability numeric(6,4),
    credit_limit        numeric(18,2),
    interest_rate       numeric(6,2),
    loan_amount_requested numeric(18,2),
    fiscal_year         int,
    result_json         jsonb,
    cam_storage_path    text,
    error               text,
    created_at          timestamptz default now(),
    updated_at          timestamptz default now()
);

create index if not exists appraisals_user_id_idx   on appraisals(user_id);
create index if not exists appraisals_company_id_idx on appraisals(company_id);
create index if not exists appraisals_created_at_idx on appraisals(created_at desc);

-- ── updated_at trigger ────────────────────────────────────────────────────────
create or replace function update_updated_at_column()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

create trigger companies_updated_at
    before update on companies
    for each row execute function update_updated_at_column();

create trigger appraisals_updated_at
    before update on appraisals
    for each row execute function update_updated_at_column();

-- ── Row Level Security ────────────────────────────────────────────────────────
alter table companies  enable row level security;
alter table appraisals enable row level security;

-- companies: readable by all authenticated users; writable by backend (service role bypasses RLS)
create policy "companies_select" on companies
    for select to authenticated using (true);

create policy "companies_insert" on companies
    for insert to authenticated with check (true);

create policy "companies_update" on companies
    for update to authenticated using (true);

-- appraisals: users can only see / modify their own rows
create policy "appraisals_select_own" on appraisals
    for select using (auth.uid() = user_id);

create policy "appraisals_insert_own" on appraisals
    for insert with check (auth.uid() = user_id);

create policy "appraisals_update_own" on appraisals
    for update using (auth.uid() = user_id);

-- ── Storage bucket ────────────────────────────────────────────────────────────
insert into storage.buckets (id, name, public)
values ('cam-reports', 'cam-reports', false)
on conflict do nothing;

-- Authenticated users can upload to their own folder
create policy "cam_reports_insert_own" on storage.objects
    for insert to authenticated
    with check (
        bucket_id = 'cam-reports'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

-- Users can read their own CAM reports
create policy "cam_reports_select_own" on storage.objects
    for select to authenticated
    using (
        bucket_id = 'cam-reports'
        and (storage.foldername(name))[1] = auth.uid()::text
    );
