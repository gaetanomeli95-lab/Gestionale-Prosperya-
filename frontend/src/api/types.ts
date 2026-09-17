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

// --- management: classification, contribution margin, break-even --------

export interface MgmtCostCenter {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
}

export interface MgmtCategory {
  id: string;
  name: string;
  kind: "revenue" | "cost";
  cost_nature: "fixed" | "variable" | null;
  cost_center_id: string | null;
  cost_center_code: string | null;
  cost_center_name: string | null;
}

export interface MgmtCategories {
  categories: MgmtCategory[];
  cost_natures: ("fixed" | "variable")[];
  unclassified_costs: string[];
  classification_complete: boolean;
  note: string;
}

export interface Contribution {
  period: { year: number; through_month: number; label: string };
  currency: string;
  revenue: string | null;
  variable_costs: string | null;
  fixed_costs: string | null;
  contribution_margin: string | null;
  contribution_margin_percent: string | null;
  contribution_margin_ratio: string | null;
  break_even_revenue: string | null;
  break_even_coverage: string | null;
  break_even_status: "available" | "not_calculable";
  status: "available" | "not_calculable";
  unclassified_costs: { category: string; amount: string }[];
  cost_centers: {
    cost_center_id: string | null; code: string | null; name: string;
    revenue: string | null; costs: string | null; result: string | null;
  }[];
  reasons: string[];
  alerts: MgmtAlert[];
  quality: { classification_complete: boolean; cost_rows: number; issues: string[] };
  trace: { formula_version: string; formulas: Record<string, string>; source_count: number };
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
    contribution_margin: string | null;
    contribution_margin_percent: string | null;
    break_even_revenue: string | null;
    break_even_status: "available" | "not_calculable";
  };
  cash: {
    position: string | null; position_status: string;
    first_negative_date: string | null; days_to_negative: number | null;
    receivable_residual: string | null; payable_residual: string | null;
    overdue_receivables: string | null; overdue_payables: string | null;
    unreconciled_transactions: number;
  };
  fiscal: {
    next_obligation: FiscalDeadline | null;
    open_deadlines: number;
    pending_entries: number;
    validated_settlements: number;
    f24_drafts: number;
  };
  controlling: { open_alerts: number; critical_alerts: number };
  signal_count: number;
  top_signal: string | null;
}

export interface Hub {
  as_of: string;  period: { year: number; through_month: number };
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
  contribution: Contribution;
  treasury: TreasurySnapshot;
  fiscal: FiscalCockpit;
  controlling: {
    open_alerts: number;
    alerts: ControllingAlert[];
    note: string;
  };
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

// --- fiscal ---------------------------------------------------------------
// Same contract: amounts are decimal STRINGS or null. Null, "insufficient
// data", "unsupported" and "requires review" are distinct states — the UI
// must never render any of them as €0.

export type VatDirection = "sale" | "purchase";
export type VatTreatment =
  | "supported" | "unsupported" | "requires_review" | "insufficient_data";
export type FiscalPeriodStatus =
  | "open" | "calculated" | "review_required" | "validated" | "locked";
export type SettlementStatus = "calculated" | "review_required" | "validated" | "superseded";
export type DeadlineStatus = "pending" | "validated" | "settled" | "cancelled";
export type F24Status =
  | "generated" | "validation_required" | "validated" | "approved" | "exported";

export interface FiscalPeriod {
  id: string;
  year: number;
  period_no: number;
  frequency: "monthly" | "quarterly";
  label: string;
  start_date: string;
  end_date: string;
  status: FiscalPeriodStatus;
}

export interface VatEntry {
  id: string;
  direction: VatDirection;
  source: "manual" | "import" | "invoice" | "system_derived" | string;
  source_ref: string;
  invoice_id: string | null;
  document_number: string | null;
  document_date: string | null;
  competence_date: string;
  counterparty_name: string | null;
  counterparty_vat: string | null;
  taxable_amount: string;
  vat_amount: string | null;
  vat_rate: string | null;
  vat_nature: string | null;
  deductible: boolean | null;
  treatment: VatTreatment;
  treatment_reason: string | null;
  notes: string | null;
  reverses_entry_id: string | null;
  created_at: string | null;
  superseded?: boolean;
}

export interface VatRegister {
  period: { label: string; start: string; end: string };
  entries: VatEntry[];
  counters: {
    total: number; effective: number; requires_review: number;
    sales: number; purchases: number;
  };
  pending_review: VatEntry[];
  limitations: string[];
}

export interface FiscalWarning {
  code: string;
  severity: "critical" | "warning" | "info";
  category: string;
  title: string;
  message: string;
  formula?: string;
  formula_version?: string;
  evidence?: Record<string, unknown>;
  action_required?: boolean;
}

export interface FiscalDeadline {
  id: string;
  kind: string;
  period_id: string | null;
  settlement_id: string | null;
  statutory_date: string | null;
  due_date: string | null;
  due_date_status: "resolved" | "review_required";
  deferral_reason: string | null;
  amount: string | null;
  status: DeadlineStatus;
  open_item_id: string | null;
  notes: string | null;
}

export interface SettlementTraceSource {
  id: string;
  document_number: string | null;
  competence_date: string;
  counterparty_name: string | null;
  vat_amount: string | null;
  deductible?: boolean | null;
  treatment?: string;
  reason?: string | null;
}

export interface FiscalRuleSet {
  id: string;
  code: string;
  rule_family: string;
  version: string;
  status: string;
  jurisdiction: string;
  effective_from: string;
  effective_to: string | null;
  source: {
    authority: string;
    title: string;
    url: string;
    published_at: string | null;
    retrieved_at: string;
    fingerprint: string;
    legal_reference: string | null;
  };
  engine_version: string;
  notes: string | null;
  payload: Record<string, unknown> & {
    formula?: { steps?: string[] };
    supported_cases?: string[];
    unsupported_cases?: string[];
  };
}

export interface Settlement {
  id: string;
  version: number;
  status: SettlementStatus;
  currency: string;
  period: FiscalPeriod | null;
  debit_total: string | null;
  credit_total: string | null;
  prior_credit: string | null;
  prior_small_debit: string | null;
  interest_amount: string | null;
  net_position: string | null;
  payable_amount: string | null;
  carry_forward_credit: string | null;
  carry_forward_debit: string | null;
  outcome: string | null;
  source_count: number;
  unsupported_count: number;
  warnings: FiscalWarning[];
  trace: {
    formula_version: string;
    engine_version: string;
    rule_set?: FiscalRuleSet;
    calendar_rule_set?: FiscalRuleSet;
    formula_steps?: string[];
    applied_rules?: string[];
    components?: Record<string, string | null>;
    prior_source?: { settlement_id: string; period: string; status: string; version: number } | null;
    debit_sources?: SettlementTraceSource[];
    credit_sources?: SettlementTraceSource[];
    excluded_sources?: SettlementTraceSource[];
    due_date?: {
      statutory: string; resolved: string | null; status: string;
      applied_rules: string[]; reason: string | null; formula_version: string;
    };
    supported_cases?: string[];
    unsupported_cases?: string[];
  };
  formula_version: string;
  rule_set_id: string;
  calculated_at: string | null;
  validated_at: string | null;
  validated_by_id: string | null;
  validation_note: string | null;
  superseded_by_id: string | null;
  deadline: FiscalDeadline | null;
  f24_draft_id: string | null;
  limitations: string[];
}

export interface F24DraftSummary {
  id: string;
  status: F24Status;
  balance: string | null;
  due_date: string | null;
  settlement_id: string | null;
}

export interface F24Draft {
  id: string;
  status: F24Status;
  currency: string;
  settlement_id: string | null;
  deadline_id: string | null;
  total_debit: string | null;
  total_credit: string | null;
  balance: string | null;
  due_date: string | null;
  taxpayer: Record<string, unknown> | null;
  notes: string | null;
  validated_at: string | null;
  approved_at: string | null;
  exported_at: string | null;
  export_format: string | null;
  export_fingerprint: string | null;
  transmission: { supported: boolean; note: string };
  lines: {
    id: string; position: number; section: string;
    tax_code: string; tax_code_description: string | null;
    reference_year: number | null; reference_period: string | null;
    debit_amount: string | null; credit_amount: string | null;
    origin_kind: string | null; origin_settlement_id: string | null;
    rule_reference: string | null; explanation: string | null;
  }[];
}

export interface FiscalSnapshot {
  as_of: string;
  year: number;
  currency: string;
  engine_version: string;
  latest_settlement: Settlement | null;
  periods: (FiscalPeriod & {
    settlement: {
      id: string; status: SettlementStatus; version: number;
      net_position: string | null; payable_amount: string | null;
      unsupported_count: number;
    } | null;
  })[];
  deadlines: FiscalDeadline[];
  f24_drafts: F24DraftSummary[];
  counters: {
    periods: number; calculated: number; validated: number;
    pending_entries: number; open_deadlines: number; f24_drafts: number;
  };
  pending_entries: VatEntry[];
  warnings: FiscalWarning[];
  limitations: string[];
  transmission: { supported: boolean; note: string };
}

export interface FiscalCockpit {
  year: number;
  engine_version: string;
  latest_settlement: Settlement | null;
  next_obligation: FiscalDeadline | null;
  deadlines: FiscalDeadline[];
  counters: FiscalSnapshot["counters"];
  pending_entries: VatEntry[];
  f24_drafts: F24DraftSummary[];
  limitations: string[];
  transmission: { supported: boolean; note: string };
}

export interface FiscalRuleSetsResponse {
  rule_sets: FiscalRuleSet[];
  tax_codes: {
    id: string; code: string; description: string | null; section: string;
    usage: string | null; reference_number: string | null;
    valid_from: string; valid_to: string | null;
    requires_reference_period: boolean;
    source_url: string | null; notes: string | null; rule_set_id: string;
  }[];
  engine_version: string;
  limitations: string[];
}

// --- controlling & early warning -----------------------------------------
// Same contract as fiscal/treasury: amounts are decimal STRINGS or null.
// `insufficient_data`, `not_applicable`, `unsupported` and `partial` are
// first-class states — the UI must never render any of them as €0, and must
// never present an early-warning signal as a legal determination.

export type MetricStatus = "available" | "partial" | "insufficient_data" | "not_applicable";
export type EvalState = "fired" | "not_fired" | "insufficient_data" | "unsupported";
export type AlertLifecycle = "open" | "acknowledged" | "resolved" | "dismissed";
export type InstalmentState = "scheduled" | "paid" | "waived";

export interface DscrResult {
  status: MetricStatus;
  value: string | null;
  horizon_days: number;
  horizon_state?: "full" | "partial";
  as_of: string;
  horizon_end: string;
  covered_until?: string;
  coverage_percent?: string;
  numerator: string | null;
  denominator: string | null;
  opening_balance?: string | null;
  components?: {
    expected_inflows: string | null;
    expected_outflows_ex_debt: string | null;
    debt_service_due: string | null;
    instalments_due: number;
  };
  reasons: string[];
  formulas: Record<string, string>;
  formula_version: string;
  engine_version: string;
  assumptions: string[];
  source_ids: string[];
  debt_line_ids: string[];
}

export interface ContinuityBucket {
  year: number;
  month: number;
  label: string;
  inflows: string;
  outflows: string;
  net: string;
  outflow_by_nature: Record<string, string>;
  projected_balance: string | null;
  item_count: number;
  has_data: boolean;
}

export interface ContinuityView {
  as_of: string;
  months: number;
  currency: string;
  opening_balance: string | null;
  opening_balance_status: "available" | "not_calculable";
  buckets: ContinuityBucket[];
  minimum_projected_balance: string | null;
  minimum_projected_date: string | null;
  first_negative_date: string | null;
  runway_days: number | null;
  runway_status: "limited" | "beyond_horizon" | "not_calculable";
  coverage: { months_with_data: number; months_total: number; horizon_end: string | null };
  certainty_model: Record<string, string>;
  formulas: Record<string, string>;
  formula_version: string;
  engine_version: string;
  issues: string[];
}

export interface MetricResult {
  status: MetricStatus;
  value: string | null;
  reasons: string[];
  evidence: Record<string, unknown>;
}

export interface TrendResult {
  metric: string;
  status: "available" | "no_baseline";
  current: string | number | null;
  previous: string | number | null;
  delta: string | number | null;
  direction: "improving" | "worsening" | "flat" | null;
}

export interface EwEvaluation {
  rule_code: string;
  rule_version: number;
  formula_version: string;
  category: "ccii_legal" | "organizational";
  state: EvalState;
  severity?: "critical" | "warning" | "info";
  title?: string;
  message?: string;
  reason?: string;
  evidence?: Record<string, unknown>;
}

export interface ControllingAlert {
  id: string;
  kind: "early_warning" | "management";
  rule_code: string;
  rule_version: number;
  severity: "critical" | "warning" | "info";
  title: string;
  message: string;
  formula: string;
  formula_version: string;
  evidence: Record<string, unknown>;
  status: AlertLifecycle;
  detected_at: string;
  first_detected_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  resolution_kind: "auto" | "human" | null;
  resolution_note: string | null;
  created_at: string | null;
}

export interface EwRule {
  id: string;
  code: string;
  version: number;
  category: "ccii_legal" | "organizational";
  title: string;
  description: string;
  legal_reference: string;
  source_authority: string;
  source_url: string;
  source_retrieved_at: string;
  effective_from: string;
  effective_to: string | null;
  status: string;
  params: Record<string, { value: string | number; kind: "statutory" | "operational" }>;
  data_requirements: string[];
  formula: string;
  formula_version: string;
}

export interface EwRulesResponse {
  as_of: string;
  rules: EwRule[];
  formula_version: string;
  disclaimer: string;
}

export interface DebtLine {
  id: string;
  facility_id: string;
  instalment_no: number;
  due_date: string;
  principal: string;
  interest: string;
  service: string;
  currency: string;
  status: InstalmentState;
  settled_on: string | null;
  status_note: string | null;
  created_at: string | null;
}

export interface DebtFacility {
  id: string;
  name: string;
  lender_name: string | null;
  facility_type: string;
  outstanding_principal: string | null;
  currency: string;
  notes: string | null;
  is_active: boolean;
  created_at: string | null;
  lines?: DebtLine[];
  scheduled_count?: number;
  scheduled_service?: string | null;
}

export interface FacilitiesResponse {
  facilities: DebtFacility[];
  counters: {
    facilities: number; instalments: number;
    scheduled: number; paid: number; waived: number;
  };
  engine_version: string;
}

export interface AlertsResponse {
  alerts: ControllingAlert[];
  counters: { total: number; open: number; acknowledged: number; resolved: number; dismissed: number };
  engine_version: string;
}

export interface DetectionResult {
  as_of: string;
  evaluations: EwEvaluation[];
  counters: {
    rules_evaluated: number; created: number; refreshed: number;
    reopened: number; auto_resolved: number;
  };
  engine_version: string;
  formula_version: string;
}

export interface ControllingSnapshot {
  as_of: string;
  currency: string;
  opening_balance: string | null;
  opening_balance_status: string;
  dscr: DscrResult;
  continuity: ContinuityView;
  profitability: {
    contribution: Contribution;
    margin_of_safety: MetricResult;
  };
  trends: TrendResult[];
  evaluations: EwEvaluation[];
  alerts: ControllingAlert[];
  counters: {
    open_items: number; debt_lines_scheduled: number;
    alerts_open: number; rules_active: number; rules_fired: number;
  };
  engine_version: string;
  formula_versions: Record<string, string>;
  limitations: string[];
}

export interface ScenarioAssumptionsOut {
  revenue_change_pct: string;
  collection_delay_days: number;
  supplier_delay_days: number;
  fixed_cost_monthly_delta: string;
  variable_cost_change_pct: string;
  debt_service_change_pct: string;
}

export interface ScenarioResult {
  label: string;
  assumptions: ScenarioAssumptionsOut;
  profitability: {
    revenue: string | null;
    variable_costs: string | null;
    fixed_costs: string | null;
    contribution_margin: string | null;
    contribution_margin_percent: string | null;
    break_even_revenue: string | null;
    margin_of_safety_percent: string | null;
  };
  dscr: DscrResult;
  continuity: {
    minimum_projected_balance: string | null;
    first_negative_date: string | null;
    runway_days: number | null;
    runway_status: string;
  };
  note: string;
  formula_version: string;
  as_of?: string;
  engine_version?: string;
}

export interface ScenarioPresets {
  presets: Record<string, { label: string; assumptions: ScenarioAssumptionsOut }>;
  bounds: Record<string, [number, number]>;
  formula_version: string;
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

// --- funding (finanza agevolata) -------------------------------------------

export interface FundingAuthority {
  id: string;
  code: string;
  name: string;
  level: string;
  website: string | null;
}

export interface AidRegime {
  id: string;
  code: string;
  name: string;
  authority: string;
  legal_reference: string;
  effective_from: string;
  effective_to: string | null;
  threshold: string;
  period_months: number;
  rolling: boolean;
  sector_exclusions: string[];
  formula_version: string;
}

export interface FundingSource {
  id: string;
  provider: string;
  title: string;
  reference: string;
  url: string | null;
  published_on: string | null;
  retrieved_at: string | null;
}

export interface FundingWindow {
  id: string;
  kind: string;
  opens_at: string | null;
  closes_at: string | null;
  timezone: string | null;
  notes: string | null;
}

export interface FundingRequirement {
  id: string;
  rule_code: string;
  params: Record<string, unknown>;
  description: string;
  mandatory: boolean;
  sort: number;
}

export interface FundingBenefit {
  id: string;
  benefit_type: string;
  max_aid_intensity: string | null;
  max_amount: string | null;
  min_investment: string | null;
  max_investment: string | null;
  financing_share: string | null;
  repayment_term_months: number | null;
  notes: string | null;
}

export interface FundingExpenseCategory {
  id: string;
  category_code: string;
  label: string;
  status: string;
  conditions: string | null;
}

export interface FundingDocumentRequirement {
  id: string;
  doc_type: string;
  label: string;
  required: boolean;
  stage: string | null;
  notes: string | null;
}

export interface FundingProgrammeVersion {
  id: string;
  programme_id: string;
  version_no: number;
  status: string;
  publication_date: string | null;
  effective_from: string | null;
  effective_to: string | null;
  aid_regime_code: string | null;
  change_summary: string | null;
  windows: FundingWindow[];
  requirements?: FundingRequirement[];
  benefits?: FundingBenefit[];
  expense_categories?: FundingExpenseCategory[];
  document_requirements?: FundingDocumentRequirement[];
  source?: FundingSource | null;
}

export interface FundingProgramme {
  id: string;
  code: string;
  title: string;
  status: string;
  authority_id: string | null;
  authority_name: string | null;
  geography: string | null;
  description: string | null;
  tags: string[];
  current_version: FundingProgrammeVersion | null;
  version_count: number;
  versions?: FundingProgrammeVersion[];
}

export interface FundingProfile {
  id: string;
  company_id: string;
  incorporated_on: string | null;
  is_startup: boolean | null;
  is_innovative_startup: boolean | null;
  female_ownership_pct: string | null;
  youth_ownership_pct: string | null;
  project_region: string | null;
  project_location: string | null;
  single_undertaking_known: boolean | null;
  group_notes: string | null;
  aid_history_complete: boolean | null;
  notes: string | null;
}

export interface CompanyAid {
  id: string;
  programme_label: string;
  authority: string | null;
  regime_code: string | null;
  granted_on: string;
  amount: string;
  gge_amount: string | null;
  reference: string | null;
  source: string | null;
  status: string;
}

export interface DeMinimisPosition {
  status: string;
  reasons?: string[];
  reason?: string;
  regime: {
    code: string; legal_reference: string; threshold: string;
    period_months: number; effective_from: string | null;
    formula_version: string;
  } | null;
  window_start?: string;
  aid_total?: string;
  headroom?: string;
}

export interface AssessmentItem {
  id: string;
  rule_code: string;
  description: string;
  mandatory: boolean;
  result: string;
  evidence: Record<string, unknown>;
}

export interface FundingAssessment {
  id: string;
  company_id: string;
  version_id: string;
  assessed_at: string;
  engine_version: string;
  result: string;
  status: string;
  company_snapshot: Record<string, unknown>;
  missing_data: { rule_code: string; description: string; missing: unknown }[];
  unsupported_rules: string[];
  reviewed_by_id: string | null;
  reviewed_at: string | null;
  reviewer_notes: string | null;
  items?: AssessmentItem[];
  programme_version?: FundingProgrammeVersion | null;
}

export interface PracticeDocument {
  id: string;
  doc_type: string;
  label: string;
  required: boolean;
  status: string;
  document_ref: string | null;
  notes: string | null;
}

export interface PracticeDeadline {
  id: string;
  kind: string;
  title: string;
  due_at: string;
  status: string;
  task_id: string | null;
  notes: string | null;
}

export interface FundingPractice {
  id: string;
  company_id: string;
  version_id: string;
  assessment_id: string | null;
  owner_id: string | null;
  status: string;
  notes: string | null;
  documents?: PracticeDocument[];
  deadlines?: PracticeDeadline[];
  programme_title?: string;
}

export interface FundingMatch {
  company_id: string;
  engine_version: string;
  groups: Record<string, {
    version_id: string; programme_id: string; programme_title: string;
    version_no: number; status: string;
    results: { rule_code: string; result: string; description: string }[];
  }[]>;
}

export interface FundingOverview {
  company_id: string;
  profile: FundingProfile | null;
  aids: CompanyAid[];
  assessments: FundingAssessment[];
  practices: FundingPractice[];
  deadlines: PracticeDeadline[];
  de_minimis: DeMinimisPosition;
  limitations: string[];
}
