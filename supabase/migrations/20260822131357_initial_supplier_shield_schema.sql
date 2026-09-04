create extension if not exists pgcrypto;

create type public.workspace_role as enum ('owner', 'admin', 'analyst', 'reviewer', 'viewer');
create type public.risk_category as enum ('Low', 'Medium', 'High', 'Critical');
create type public.verification_status as enum ('pending', 'verified', 'rejected', 'not_applicable');

create table public.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 2 and 120),
  owner_id uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.workspace_members (
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role public.workspace_role not null default 'viewer',
  created_at timestamptz not null default now(),
  primary key (workspace_id, user_id)
);

create table public.suppliers (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  legal_name text not null check (char_length(legal_name) between 2 and 160),
  category text not null,
  contact_data jsonb not null default '{}'::jsonb,
  city text not null,
  state text not null,
  business_age_years numeric(5,2) not null check (business_age_years between 0 and 100),
  registration_identifier text not null,
  source text not null,
  notes text,
  status text not null default 'active' check (status in ('active', 'inactive', 'under_review')),
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index suppliers_workspace_name_idx on public.suppliers (workspace_id, legal_name);

create table public.supplier_accounts (
  id uuid primary key default gen_random_uuid(),
  supplier_id uuid not null references public.suppliers(id) on delete cascade,
  account_reference_hash text not null,
  beneficiary_name text not null,
  change_detected_at timestamptz,
  created_at timestamptz not null default now()
);

create table public.transactions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  supplier_id uuid not null references public.suppliers(id) on delete restrict,
  amount numeric(14,2) not null check (amount > 0),
  currency char(3) not null default 'INR',
  category text not null,
  quantity numeric(14,3) not null check (quantity > 0),
  unit_price numeric(14,2) not null check (unit_price > 0),
  payment_method text not null,
  advance_percentage numeric(5,2) not null check (advance_percentage between 0 and 100),
  delivery_days integer not null check (delivery_days between 0 and 3650),
  delivery_terms text not null,
  payment_destination_changed boolean not null default false,
  quote_deviation_percent numeric(7,2) not null default 0,
  missing_information_count integer not null default 0 check (missing_information_count between 0 and 20),
  document_mismatch boolean not null default false,
  status text not null default 'draft' check (status in ('draft', 'assessed', 'hold', 'approved', 'rejected')),
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index transactions_workspace_created_idx on public.transactions (workspace_id, created_at desc);

create table public.assessments (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null unique references public.transactions(id) on delete cascade,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  model_version text not null,
  ruleset_version text not null,
  prompt_version text not null,
  risk_score smallint not null check (risk_score between 0 and 100),
  risk_category public.risk_category not null,
  confidence smallint not null check (confidence between 0 and 100),
  anomaly_score smallint not null check (anomaly_score between 0 and 100),
  recommendation text not null,
  ai_status text not null,
  ai_analysis jsonb,
  created_at timestamptz not null default now()
);
create index assessments_workspace_risk_idx on public.assessments (workspace_id, risk_score desc, created_at desc);

create table public.risk_factors (
  id uuid primary key default gen_random_uuid(),
  assessment_id uuid not null references public.assessments(id) on delete cascade,
  factor_code text not null,
  title text not null,
  severity public.risk_category not null,
  contribution smallint not null check (contribution between 0 and 100),
  evidence_reference jsonb not null,
  suggested_verification text not null,
  created_at timestamptz not null default now()
);

create table public.documents (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  supplier_id uuid references public.suppliers(id) on delete cascade,
  transaction_id uuid references public.transactions(id) on delete cascade,
  storage_reference text not null unique,
  document_type text not null check (document_type in ('invoice', 'quotation', 'business_document')),
  filename text not null,
  mime_type text not null,
  size_bytes integer not null check (size_bytes > 0),
  checksum text not null,
  extracted_fields jsonb,
  uploaded_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  check (supplier_id is not null or transaction_id is not null)
);

create table public.verification_cases (
  id uuid primary key default gen_random_uuid(),
  assessment_id uuid not null unique references public.assessments(id) on delete cascade,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  status text not null default 'open' check (status in ('open', 'in_progress', 'closed')),
  assigned_to uuid references auth.users(id),
  created_at timestamptz not null default now(),
  closed_at timestamptz
);

create table public.verification_items (
  id uuid primary key default gen_random_uuid(),
  verification_case_id uuid not null references public.verification_cases(id) on delete cascade,
  item_type text not null,
  title text not null,
  status public.verification_status not null default 'pending',
  evidence_reference jsonb,
  reviewer_note text,
  updated_by uuid references auth.users(id),
  updated_at timestamptz not null default now()
);

create table public.decisions (
  id uuid primary key default gen_random_uuid(),
  assessment_id uuid not null references public.assessments(id) on delete cascade,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  user_id uuid not null references auth.users(id),
  action text not null check (action in ('approve', 'request_information', 'maintain_hold', 'reject')),
  reason text not null check (char_length(reason) >= 5),
  created_at timestamptz not null default now()
);

create table public.audit_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  actor_id uuid references auth.users(id),
  event_type text not null,
  entity_type text not null,
  entity_id uuid,
  metadata jsonb not null default '{}'::jsonb,
  request_id uuid,
  created_at timestamptz not null default now()
);
create index audit_workspace_created_idx on public.audit_events (workspace_id, created_at desc);

alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;
alter table public.suppliers enable row level security;
alter table public.supplier_accounts enable row level security;
alter table public.transactions enable row level security;
alter table public.assessments enable row level security;
alter table public.risk_factors enable row level security;
alter table public.documents enable row level security;
alter table public.verification_cases enable row level security;
alter table public.verification_items enable row level security;
alter table public.decisions enable row level security;
alter table public.audit_events enable row level security;

create policy "members read workspace" on public.workspaces for select to authenticated using (exists (select 1 from public.workspace_members m where m.workspace_id = id and m.user_id = (select auth.uid())));
create policy "members read memberships" on public.workspace_members for select to authenticated using (user_id = (select auth.uid()) or exists (select 1 from public.workspace_members m where m.workspace_id = workspace_members.workspace_id and m.user_id = (select auth.uid()) and m.role in ('owner', 'admin')));
create policy "members read suppliers" on public.suppliers for select to authenticated using (exists (select 1 from public.workspace_members m where m.workspace_id = suppliers.workspace_id and m.user_id = (select auth.uid())));
create policy "members read accounts" on public.supplier_accounts for select to authenticated using (exists (select 1 from public.suppliers s join public.workspace_members m on m.workspace_id = s.workspace_id where s.id = supplier_accounts.supplier_id and m.user_id = (select auth.uid())));
create policy "members read transactions" on public.transactions for select to authenticated using (exists (select 1 from public.workspace_members m where m.workspace_id = transactions.workspace_id and m.user_id = (select auth.uid())));
create policy "members read assessments" on public.assessments for select to authenticated using (exists (select 1 from public.workspace_members m where m.workspace_id = assessments.workspace_id and m.user_id = (select auth.uid())));
create policy "members read factors" on public.risk_factors for select to authenticated using (exists (select 1 from public.assessments a join public.workspace_members m on m.workspace_id = a.workspace_id where a.id = risk_factors.assessment_id and m.user_id = (select auth.uid())));
create policy "members read documents" on public.documents for select to authenticated using (exists (select 1 from public.workspace_members m where m.workspace_id = documents.workspace_id and m.user_id = (select auth.uid())));
create policy "members read verification cases" on public.verification_cases for select to authenticated using (exists (select 1 from public.workspace_members m where m.workspace_id = verification_cases.workspace_id and m.user_id = (select auth.uid())));
create policy "members read verification items" on public.verification_items for select to authenticated using (exists (select 1 from public.verification_cases v join public.workspace_members m on m.workspace_id = v.workspace_id where v.id = verification_items.verification_case_id and m.user_id = (select auth.uid())));
create policy "members read decisions" on public.decisions for select to authenticated using (exists (select 1 from public.workspace_members m where m.workspace_id = decisions.workspace_id and m.user_id = (select auth.uid())));
create policy "members read audit events" on public.audit_events for select to authenticated using (exists (select 1 from public.workspace_members m where m.workspace_id = audit_events.workspace_id and m.user_id = (select auth.uid())));

create policy "analysts create suppliers" on public.suppliers for insert to authenticated with check (exists (select 1 from public.workspace_members m where m.workspace_id = suppliers.workspace_id and m.user_id = (select auth.uid()) and m.role in ('owner', 'admin', 'analyst')));
create policy "analysts create transactions" on public.transactions for insert to authenticated with check (exists (select 1 from public.workspace_members m where m.workspace_id = transactions.workspace_id and m.user_id = (select auth.uid()) and m.role in ('owner', 'admin', 'analyst')));
create policy "members create accounts" on public.supplier_accounts for insert to authenticated with check (exists (select 1 from public.suppliers s join public.workspace_members m on m.workspace_id = s.workspace_id where s.id = supplier_accounts.supplier_id and m.user_id = (select auth.uid()) and m.role in ('owner', 'admin', 'analyst')));
create policy "members create documents" on public.documents for insert to authenticated with check (exists (select 1 from public.workspace_members m where m.workspace_id = documents.workspace_id and m.user_id = (select auth.uid()) and m.role in ('owner', 'admin', 'analyst')));
create policy "reviewers create decisions" on public.decisions for insert to authenticated with check (exists (select 1 from public.workspace_members m where m.workspace_id = decisions.workspace_id and m.user_id = (select auth.uid()) and m.role in ('owner', 'admin', 'reviewer')));
create policy "members create verification cases" on public.verification_cases for insert to authenticated with check (exists (select 1 from public.workspace_members m where m.workspace_id = verification_cases.workspace_id and m.user_id = (select auth.uid())));
create policy "members create verification items" on public.verification_items for insert to authenticated with check (exists (select 1 from public.verification_cases v join public.workspace_members m on m.workspace_id = v.workspace_id where v.id = verification_items.verification_case_id and m.user_id = (select auth.uid())));
create policy "members create audit events" on public.audit_events for insert to authenticated with check (exists (select 1 from public.workspace_members m where m.workspace_id = audit_events.workspace_id and m.user_id = (select auth.uid())));

insert into storage.buckets (id, name, public) values ('supplier-documents', 'supplier-documents', false) on conflict (id) do update set public = false;
create policy "members access documents by workspace path" on storage.objects for select to authenticated using (bucket_id = 'supplier-documents' and exists (select 1 from public.workspace_members m where m.workspace_id::text = (storage.foldername(name))[2] and m.user_id = (select auth.uid())));
