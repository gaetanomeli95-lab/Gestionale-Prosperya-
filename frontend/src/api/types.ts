export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: "admin" | "management" | "consultant" | "backoffice" | "readonly";
  team: string | null;
  is_active: boolean;
}

export interface CompanyListItem {
  id: string;
  legal_name: string;
  vat_number: string | null;
  city: string | null;
  region: string | null;
  status: string;
  lifecycle_stage: string;
  size_band: string;
  owner_id: string | null;
  updated_at: string;
}

export interface Company {
  id: string;
  version: number;
  legal_name: string;
  trading_name: string | null;
  vat_number: string | null;
  tax_code: string | null;
  legal_form: string | null;
  ateco_code: string | null;
  industry: string | null;
  size_band: string;
  revenue_eur: number | null;
  employee_count: number | null;
  country: string | null;
  region: string | null;
  city: string | null;
  address: string | null;
  postal_code: string | null;
  website: string | null;
  email: string | null;
  pec: string | null;
  phone: string | null;
  source: string | null;
  status: string;
  lifecycle_stage: string;
  tags: string[];
  owner_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Contact {
  id: string;
  version: number;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  role_title: string | null;
  owner_id: string | null;
}

export interface Lead {
  id: string;
  version: number;
  company_name: string;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  source: string;
  status: string;
  priority: string;
  interest: string | null;
  estimated_value_eur: number | null;
  owner_id: string | null;
  converted_company_id: string | null;
  created_at: string;
}

export interface PipelineStage {
  id: string;
  name: string;
  position: number;
  default_probability: number | null;
  is_won: boolean;
  is_lost: boolean;
}

export interface ServiceLine {
  id: string;
  code: string;
  name: string;
}

export interface Opportunity {
  id: string;
  version: number;
  title: string;
  company_id: string;
  stage_id: string;
  status: string;
  probability: number | null;
  expected_value_eur: number | null;
  expected_close_date: string | null;
  owner_id: string | null;
  next_action: string | null;
  next_action_date: string | null;
  updated_at: string;
}

export interface Task {
  id: string;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  owner_id: string | null;
  due_date: string | null;
  completed_at: string | null;
  entity_type: string | null;
  entity_id: string | null;
}

export interface Note {
  id: string;
  body: string;
  pinned: boolean;
  created_at: string;
}

export interface ActivityEvent {
  id: string;
  event_type: string;
  summary: string;
  created_at: string;
}

export interface SearchHit {
  type: "company" | "contact" | "lead" | "opportunity";
  id: string;
  title: string;
  subtitle: string | null;
}

export interface Dashboard {
  my_open_tasks: number;
  my_overdue_tasks: number;
  overdue_task_items: { id: string; title: string; due_date: string | null; priority: string }[];
  upcoming_tasks: { id: string; title: string; due_date: string | null; priority: string }[];
  open_opportunities: number;
  pipeline_value_eur: number;
  pipeline_by_stage: { stage_id: string; stage_name: string; count: number; total_value: number }[];
  stale_opportunities: number;
  new_leads_30d: number;
  companies_total: number;
  customers_total: number;
  unassigned_companies: number;
}

export interface Invoice {
  id: string;
  version: number;
  number: number | null;
  series: string;
  fiscal_year: number | null;
  issue_date: string | null;
  company_id: string;
  status: string;
  provider_status: string | null;
  sdi_status: string | null;
  taxable_amount: number | null;
  vat_amount: number | null;
  total_amount: number | null;
  provider_key: string | null;
  provider_external_id: string | null;
  notes: string | null;
  lines?: { id: string; description: string; quantity: number; unit_price: number; vat_rate: number; line_total: number | null }[];
  created_at: string;
}

export interface ProviderStatus {
  configured: boolean;
  provider: {
    provider_key: string;
    api_version: string;
    environment: string;
    is_active: boolean;
    last_health_status: string | null;
    last_health_check_at: string | null;
    credentials_configured: boolean;
  } | null;
  health_status: string | null;
  health_detail?: string | null;
  available_providers: { key: string; api_version: string }[];
}
