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
  role:
    | "admin"
    | "management"
    | "consultant"
    | "backoffice"
    | "readonly"
    | "client_admin"
    | "client_operator"
    | "client_readonly";
  team: string | null;
  tenant_id: string | null;
  is_active: boolean;
}

export interface Tenant {
  id: string;
  slug: string;
  display_name: string;
  legal_name: string | null;
  is_platform_org: boolean;
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

// --- management control -------------------------------------------------
// All monetary values are decimal STRINGS or null (null = no evidence, not 0).

export interface MgmtMonthly {
  month: number;
  revenue: string | null;
  costs: string | null;
  result: string | null;
  budget_revenue: string | null;
  budget_costs: string | null;
}

export interface MgmtAlert {
  code: string;
  severity: "info" | "warning" | "danger";
  title: string;
  message: string;
  formula?: string;
}

export interface MgmtOverview {
  period: { year: number; through_month: number; label: string; start: string; end: string };
  currency: string;
  revenue: string | null;
  costs: string | null;
  result: string | null;
  margin: string | null;
  margin_percent: string | null;
  budget: {
    revenue: string | null; costs: string | null; result: string | null;
    revenue_variance: string | null; cost_variance: string | null; result_variance: string | null;
  };
  monthly: MgmtMonthly[];
  cost_categories: { category: string; amount: string }[];
  comparison: {
    period: { label: string };
    revenue: string | null; costs: string | null; result: string | null;
    revenue_change_percent: string | null; cost_change_percent: string | null;
    quality: string;
  };
  quality: {
    status: "partial" | "empty";
    certified_complete: boolean;
    covered_months: number;
    expected_months: number;
    issues: string[];
  };
  alerts: MgmtAlert[];
  trace: { formula_version: string; formulas: Record<string, string>; source_count: number };
}

export interface ImportBatch {
  id: string;
  filename: string;
  idempotency_key: string;
  row_count: number;
  duplicate_count: number;
  created_at: string | null;
  origin: string;
  replayed: boolean;
}

export interface BudgetRow {
  id: string; year: number; month: number; version: number;
  revenue: string | null; costs: string | null; result: string | null;
}

export interface MgmtHub {
  companies: { company: { id: string; name: string; currency: string }; overview: MgmtOverview }[];
  totals: {
    revenue: string | null; costs: string | null; result: string | null; margin_percent: string | null;
    company_count: number; issues: string[];
  };
  alerts: (MgmtAlert & { company_id: string; company_name: string })[];
}

// --- treasury -----------------------------------------------------------
// Same contract as management: monetary values are decimal STRINGS or null.

export interface BankAccount {
  id: string;
  label: string;
  bank_name: string | null;
  iban_last4: string | null;
  currency: string;
  provider_key: string;
  provider_api_version: string | null;
  provider_account_id: string;
  is_real_institution: boolean;
  supports_transactions: boolean;
  credentials_configured: boolean;
  connection_status: string;
  last_sync_at: string | null;
  last_sync_error: string | null;
  balance: string | null;
  balance_date: string | null;
  balance_source: string;
  is_active: boolean;
}

export interface TreasuryAllocation {
  id: string;
  amount: string;
  method: "exact" | "fuzzy" | "manual" | "write_off" | "cancellation";
  bank_transaction_id?: string | null;
  open_item_id?: string;
  confidence: string | null;
  reason: string | null;
  engine_version: string | null;
  created_at: string | null;
}

export interface BankTransaction {
  id: string;
  bank_account_id: string;
  provider_tx_id: string;
  booking_date: string;
  value_date: string;
  amount: string;
  currency: string;
  counterparty_name: string | null;
  description: string;
  source: string;
  allocated: string;
  unallocated: string;
  is_reconciled: boolean;
  allocations: TreasuryAllocation[];
}

export type OpenItemStatus =
  | "open" | "partially_settled" | "settled" | "written_off" | "cancelled";

export interface OpenItem {
  id: string;
  direction: "receivable" | "payable";
  counterparty_name: string;
  counterparty_vat: string | null;
  document_number: string | null;
  document_date: string | null;
  due_date: string;
  amount: string;
  currency: string;
  settled: string;
  written_off: string;
  residual: string;
  status: OpenItemStatus;
  days_overdue: number;
  is_overdue: boolean;
  category: string | null;
  source: "invoice" | "manual" | "import";
  source_ref: string;
  invoice_id: string | null;
  notes: string | null;
  allocations: TreasuryAllocation[];
}

export interface TreasuryWarning {
  code: string;
  severity: "critical" | "warning" | "info";
  category: "treasury" | "financial" | "data_quality" | "management" | "commercial";
  title: string;
  message: string;
  formula: string;
  formula_version: string;
  evidence: Record<string, unknown>;
  action_required: boolean;
}

export interface CashPosition {
  as_of: string;
  currency: string;
  amount: string | null;
  status: "available" | "not_calculable";
  oldest_balance_date: string | null;
  staleness_days: number | null;
  accounts: {
    id: string; label: string; bank_name: string | null; iban_last4: string | null;
    provider_key: string; is_real_institution: boolean; connection_status: string;
    balance: string | null; balance_date: string | null; balance_source: string;
    last_sync_at: string | null;
  }[];
  issues: string[];
  formula: string;
  formula_version: string;
}

export interface CashForecast {
  as_of: string;
  horizon_days: number;
  opening_balance: string | null;
  opening_balance_status: string;
  horizons: {
    horizon_days: number; end_date: string;
    expected_inflows: string | null; expected_outflows: string | null;
    net_flow: string | null; projected_balance: string | null; item_count: number;
  }[];
  daily: { date: string; inflow: string | null; outflow: string | null; net_cumulative: string | null; projected_balance: string | null }[];
  first_negative_date: string | null;
  days_to_negative: number | null;
  overdue_excluded: { receivable: string | null; payable: string | null; count: number };
  facts: string[];
  assumptions: string[];
  formulas: Record<string, string>;
  formula_version: string;
  issues: string[];
}

export interface AgingSide {
  total: string | null;
  count: number;
  buckets: Record<string, { amount: string | null; count: number }>;
  overdue: {
    amount: string | null; count: number; max_days: number;
    items: {
      id: string; counterparty_name: string; document_number: string | null;
      due_date: string; residual: string; days_overdue: number;
      source: string; invoice_id: string | null;
    }[];
  };
}

export interface TreasurySnapshot {
  as_of: string;
  currency: string;
  position: CashPosition;
  forecast: CashForecast;
  aging: { as_of: string; receivables: AgingSide; payables: AgingSide; formula: string };
  warnings: TreasuryWarning[];
  counters: {
    accounts: number; open_items: number; overdue_items: number;
    unreconciled_transactions: number; unreconciled_amount: string | null;
    receivable_residual: string | null; payable_residual: string | null;
  };
  reconciliation: { engine_version: string; levels_implemented: number[]; level_3_ai_triage: string };
  formula_version: string;
  limitations: string[];
}

export interface SuggestionEntry {
  bank_transaction_id: string;
  amount: string;
  unallocated: string;
  value_date: string;
  description: string;
  counterparty_name: string | null;
  auto_applicable: boolean;
  suggestions: {
    method: "exact" | "fuzzy";
    level: number;
    confidence: string;
    requires_approval: boolean;
    allocations: { open_item_id: string; amount: string }[];
    reasons: string[];
    evidence: Record<string, unknown>;
    engine_version: string;
  }[];
}

export interface SuggestionPlan {
  engine_version: string;
  levels: Record<string, string>;
  transactions: SuggestionEntry[];
  unmatched_transaction_ids: string[];
  counters: {
    evaluated: number; with_suggestions: number; auto_applicable: number;
    unmatched: number; open_items_considered: number;
  };
  open_items: {
    id: string; direction: string; counterparty_name: string;
    document_number: string | null; due_date: string; residual: string;
  }[];
  approval_policy: string;
}

// --- cockpit / hub ------------------------------------------------------

export interface ActionSignal {
  code: string;
  severity: "critical" | "warning" | "info";
  category: string;
  title: string;
  message: string;
  formula: string;
  formula_version: string;
  evidence: Record<string, unknown>;
  action_required: boolean;
  priority: number;
  priority_version: string;
  company_id?: string;
  company_name?: string;
}

export interface HubEntry {
  company: {
    id: string; legal_name: string; vat_number: string | null;
    region: string | null; ateco_code: string | null; size_band: string;
  };
  attention_score: number;
  health: {
    status: "critical" | "attention" | "data_incomplete" | "not_calculable" | "ok";
    reason: string; has_economics: boolean; has_cash_data: boolean;
  };
  economics: {
    period: { label: string }; revenue: string | null; costs: string | null;
    result: string | null; margin_percent: string | null;
    quality: string; covered_months: number; expected_months: number;
  };
  cash: {
    position: string | null; position_status: string;
    first_negative_date: string | null; days_to_negative: number | null;
    receivable_residual: string | null; payable_residual: string | null;
    overdue_receivables: string | null; overdue_payables: string | null;
    unreconciled_transactions: number;
  };
  signal_count: number;
  top_signal: string | null;
}

export interface Hub {
  as_of: string;
  period: { year: number; through_month: number };
  horizon_days: number;
  companies: HubEntry[];
  actions: ActionSignal[];
  counters: {
    companies: number; critical: number; warning: number; info: number;
    action_required: number; companies_needing_attention: number;
  };
  priority: { formula: string; version: string };
  aggregation_note: string;
  limitations: string[];
}

export interface CompanyCockpit {
  as_of: string;
  company: Company & { status: string; lifecycle_stage: string };
  management: MgmtOverview;
  treasury: TreasurySnapshot;
  commercial: {
    open_opportunities: number;
    stale_days_threshold: number;
    items: { id: string; title: string; expected_value_eur: string | null; days_inactive: number | null }[];
    expected_value_note: string;
  };
  actions: ActionSignal[];
  priority: { formula: string; version: string };
  limitations: string[];
}

// --- assistant ----------------------------------------------------------

export type AnswerItemType =
  | "FACT" | "CALCULATION" | "ASSUMPTION" | "SUGGESTION" | "WARNING" | "ACTION_REQUIRED";

export interface ChatResponse {
  provider: string;
  mode: string;
  items: { type: AnswerItemType; text: string }[];
  tools_used: string[];
  evidence: Record<string, unknown> & { source_ids?: string[]; scenario?: Record<string, unknown> };
  limitations: string[];
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
