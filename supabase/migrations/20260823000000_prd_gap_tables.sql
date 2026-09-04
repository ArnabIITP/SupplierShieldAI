-- SupplierShield AI — Migration 002
-- PRD §9.2: Missing tables and columns not in initial migration
-- Adds: profiles, ai_explanations, evidence_items
-- Updates: suppliers (additional contact fields), transactions, documents, assessments, risk_factors, verification_items

-- ── profiles (PRD §9.2) ──────────────────────────────────────────────────────
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  display_name text,
  status text not null default 'active' check (status in ('active', 'inactive')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table public.profiles enable row level security;
create policy "users read own profile" on public.profiles for select to authenticated using (id = (select auth.uid()));
create policy "users update own profile" on public.profiles for update to authenticated using (id = (select auth.uid()));
-- Service role inserts on signup
create policy "service insert profile" on public.profiles for insert to service_role with check (true);

-- Auto-create profile on Supabase Auth signup
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, display_name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1)))
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- ── suppliers — additional PRD §9.2 columns ───────────────────────────────────
-- The current schema stores contact data in contact_data JSONB.
-- Add explicit columns for contact_phone and country per PRD.
alter table public.suppliers
  add column if not exists contact_phone text,
  add column if not exists country text not null default 'India';

-- ── transactions — additional PRD §9.2 columns ───────────────────────────────
alter table public.transactions
  add column if not exists expected_delivery_date date,
  add column if not exists payment_reference text,
  add column if not exists quote_reference_price numeric(14,2);

-- ── documents — align column names with PRD §9.2 ────────────────────────────
-- PRD uses: storage_path, original_filename, file_size, processing_status
-- Add aliases/extra columns (keep existing columns for backwards compat)
alter table public.documents
  add column if not exists processing_status text not null default 'pending'
    check (processing_status in ('pending', 'extracted', 'failed', 'not_required'));

-- ── assessments — additional PRD §9.2 columns ────────────────────────────────
alter table public.assessments
  add column if not exists feature_version text not null default 'features-v1',
  add column if not exists status text not null default 'completed'
    check (status in ('processing', 'completed', 'failed')),
  add column if not exists completed_at timestamptz;

-- ── risk_factors — align with PRD §9.2 ───────────────────────────────────────
alter table public.risk_factors
  add column if not exists observed_value text;

-- ── verification_cases — add priority column ─────────────────────────────────
alter table public.verification_cases
  add column if not exists priority text not null default 'normal'
    check (priority in ('urgent', 'high', 'normal', 'low'));

-- ── verification_items — align with PRD §9.2 ────────────────────────────────
alter table public.verification_items
  add column if not exists description text;

-- ── ai_explanations (PRD §9.2) ───────────────────────────────────────────────
-- PRD requires a separate table for AI explanations, not JSONB in assessments
create table if not exists public.ai_explanations (
  id uuid primary key default gen_random_uuid(),
  assessment_id uuid not null references public.assessments(id) on delete cascade,
  provider text not null default 'gemini',
  model text,
  prompt_version text not null default 'prompt-v1',
  status text not null check (status in ('available', 'fallback', 'failed')),
  summary text,
  risk_interpretation text,
  risk_factors_json jsonb,
  missing_information_json jsonb,
  recommended_actions_json jsonb,
  uncertainty text,
  disclaimer text,
  created_at timestamptz not null default now()
);
alter table public.ai_explanations enable row level security;
create policy "members read ai explanations" on public.ai_explanations for select to authenticated
  using (exists (
    select 1 from public.assessments a
    join public.workspace_members m on m.workspace_id = a.workspace_id
    where a.id = ai_explanations.assessment_id and m.user_id = (select auth.uid())
  ));
create policy "service insert ai explanations" on public.ai_explanations for insert to service_role with check (true);

-- ── evidence_items (PRD §9.2) ────────────────────────────────────────────────
-- Structured evidence extracted from documents, compared against supplier fields
create table if not exists public.evidence_items (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  supplier_id uuid references public.suppliers(id) on delete cascade,
  transaction_id uuid references public.transactions(id) on delete cascade,
  document_id uuid references public.documents(id) on delete cascade,
  evidence_type text not null check (evidence_type in ('extracted_field', 'mismatch', 'missing', 'verified')),
  field_name text not null,
  observed_value text,
  source_reference text,
  confidence numeric(5,2) check (confidence between 0 and 100),
  created_at timestamptz not null default now()
);
alter table public.evidence_items enable row level security;
create policy "members read evidence" on public.evidence_items for select to authenticated
  using (exists (
    select 1 from public.workspace_members m
    where m.workspace_id = evidence_items.workspace_id and m.user_id = (select auth.uid())
  ));
create policy "analysts create evidence" on public.evidence_items for insert to authenticated
  with check (exists (
    select 1 from public.workspace_members m
    where m.workspace_id = evidence_items.workspace_id
      and m.user_id = (select auth.uid())
      and m.role in ('owner', 'admin', 'analyst')
  ));
