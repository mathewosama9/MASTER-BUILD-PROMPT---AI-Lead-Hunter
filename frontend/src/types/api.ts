export type Role = "owner" | "admin" | "analyst" | "viewer";

export interface Me {
  user: {
    id: string;
    email: string;
    full_name: string;
    is_active: boolean;
    is_superuser?: boolean;
    email_verified_at?: string | null;
    nationality?: string | null;
    approval_status?: "pending" | "approved" | "rejected";
    locale: string;
  };
  workspace_id: string;
  workspace_name: string;
  role: Role;
  csrf_token: string | null;
  demo_mode: boolean;
  telegram_status?: "linked" | "pending" | "none";
  telegram_username?: string | null;
  impersonated_by?: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type CampaignStatus =
  | "draft"
  | "queued"
  | "discovering"
  | "enriching"
  | "analyzing"
  | "completed"
  | "partially_completed"
  | "failed"
  | "paused"
  | "cancelled";

export interface CampaignStats {
  target?: number;
  discovered?: number;
  duplicates_removed?: number;
  unique_leads?: number;
  enriched?: number;
  analyzed?: number;
  scored?: number;
  qualified?: number;
  high_priority?: number;
  lead_errors?: number;
  contacts_found?: number;
  businesses_with_contacts?: number;
  emails_found?: number;
  verified_emails?: number;
  rate_limit_warnings?: number;
  provider_failures?: number;
  ai_provider?: string | null;
  progress?: { percent: number | null; completed_units: number; total_units: number | null };
}

export interface CampaignSource {
  provider_key: string;
  status: string;
  results_count: number;
  last_error: string | null;
  manual_urls: string[];
}

export interface Campaign {
  id: string;
  name: string;
  status: CampaignStatus;
  stage: string;
  origin: string;
  is_demo: boolean;
  country: string;
  city: string | null;
  region: string | null;
  language: string;
  industry: string;
  keywords: string[];
  excluded_keywords: string[];
  company_size: string | null;
  characteristics: string[];
  services: string[];
  nl_query: string | null;
  settings: Record<string, number | boolean>;
  stats: CampaignStats;
  cost_discovery: number;
  cost_ai: number;
  last_error: string | null;
  sources: CampaignSource[];
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface JobEvent {
  id: string;
  stage: string;
  level: "info" | "warning" | "error";
  event_type: string;
  message: string;
  provider_key: string | null;
  data: Record<string, unknown>;
  created_at: string;
}

export interface LeadRow {
  id: string;
  name: string;
  website_url: string | null;
  normalized_domain: string | null;
  country: string | null;
  city: string | null;
  industry: string | null;
  latest_score: number | null;
  latest_priority: string | null;
  recommended_service: string | null;
  crm_status: string;
  contact_count: number;
  has_verified_contact: boolean;
  is_demo: boolean;
  sources: string[];
  campaigns: { id: string; name: string; score: number | null }[];
  tags: string[];
  outreach_eligible: boolean;
  updated_at: string;
}

export interface Contact {
  id: string;
  type: string;
  subtype: string | null;
  value: string;
  person_name: string | null;
  person_role: string | null;
  source_url: string | null;
  source_provider: string;
  retrieved_at: string;
  verification_status: string;
  verified_at: string | null;
  confidence: number;
  usage_restrictions: string | null;
  is_suppressed: boolean;
  /** Verified decision maker: pages that prove them. */
  proof_links?: string[];
  /** Independent sources behind the value (decision maker: proof sites; contact: publishers). */
  sources_count?: number | null;
}

export interface Assessment {
  id: string;
  campaign_id: string | null;
  provider: string;
  model: string | null;
  summary: string;
  observed_signals: { signal: string; evidence_ids: string[] }[];
  hypotheses: { statement: string; basis_evidence_ids: string[]; confidence: string }[];
  potential_problems: string[];
  evidence_links: { id: string; url: string | null; title: string | null }[];
  recommended_services: { service: string; name?: string; rationale: string; evidence_ids: string[] }[];
  opportunity: string;
  suggested_pitch: string;
  unknowns: string[];
  confidence: number;
  industry_fit: number;
  characteristics_fit: number;
  cost_usd: number;
  created_at: string;
}

export interface Score {
  id: string;
  total: number;
  priority: string;
  factors: Record<string, number>;
  weights: Record<string, number>;
  explanation: string[];
  scoring_version: string;
  created_at: string;
}

export interface Draft {
  id: string;
  language: string;
  tone: string;
  length: string;
  service: string | null;
  short_intro: string;
  email_subject: string;
  email_body: string;
  whatsapp_message: string;
  follow_up: string;
  proposal_summary: string;
  provider: string;
  created_at: string;
}

export interface LeadDetail {
  business: Record<string, unknown> & {
    id: string;
    name: string;
    website_url: string | null;
    crm_status: string;
    is_demo: boolean;
    country: string | null;
    city: string | null;
    industry: string | null;
    description: string | null;
    latest_score: number | null;
    latest_priority: string | null;
    address: string | null;
  };
  contacts: Contact[];
  sources: { id: string; provider_key: string; source_url: string; title: string | null; snippet: string | null; discovered_at: string; campaign_id: string | null }[];
  evidence: { id: string; kind: string; signal_key: string | null; url: string | null; title: string | null; excerpt: string | null; observed: boolean; captured_at: string }[];
  assessment: Assessment | null;
  assessments: Assessment[];
  score: Score | null;
  campaigns: { id: string; name: string; status: string; score: number | null; priority: string | null; qualified: boolean; added_at: string; discovered_via: string }[];
  notes: { id: string; body: string; author_id: string | null; created_at: string }[];
  tags: string[];
  activities: { id: string; type: string; payload: Record<string, unknown>; user_id: string | null; created_at: string }[];
  drafts: Draft[];
  outreach_eligible: boolean;
  suppressed: boolean;
}

export interface Provider {
  key: string;
  name: string;
  kind: string;
  description: string;
  requires: string[];
  docs_url: string | null;
  status: "connected" | "requires_api_key" | "requires_permission" | "unsupported" | "disabled" | "rate_limited" | "error";
  status_detail: string | null;
  enabled: boolean;
  credential_source: "env" | "workspace" | "platform" | null;
  has_env_key?: boolean;
  credentials_masked: Record<string, string | null>;
  settings: Record<string, unknown>;
  last_tested_at: string | null;
  last_error: string | null;
  usage_month: { requests: number; cost_usd: number };
}

export interface Offering {
  id: string;
  name: string;
  description: string;
  keywords: string[];
}

/** What the workspace sells and who it sells to (`/profile`). */
export interface Profile {
  company_name: string;
  website: string | null;
  business_category: string | null;
  description: string;
  value_proposition: string;
  offerings: Offering[];
  target_industries: string[];
  target_countries: string[];
  target_cities: string[];
  company_sizes: string[];
  good_signals: string[];
  disqualifiers: string[];
  channels: string[];
  sender_name: string;
  outreach_language: "ar" | "en";
  tone: string;
  onboarding: { step: number; completed: boolean; steps: number };
}

export interface Meta {
  demo_mode: boolean;
  countries: { code: string; name_en: string; name_ar: string; cities: { en: string; ar: string }[] }[];
  industries: { key: string; en: string; ar: string; group?: string }[];
  industry_groups?: { key: string; en: string; ar: string }[];
  provider_categories?: {
    key: string;
    en: string;
    ar: string;
    offerings: { en: string; ar: string }[];
    targets: string[];
  }[];
  /** Labels of the fixed service list the product shipped with; old leads may still carry these keys. */
  services: { key: string; en: string; ar: string }[];
  scoring: { weights: Record<string, number>; thresholds: Record<string, number>; version: string };
}

export interface DashboardStats {
  totals: {
    businesses: number;
    qualified_leads: number;
    with_contact: number;
    with_verified_contact: number;
    average_score: number | null;
    active_campaigns: number;
    completed_campaigns: number;
    failed_campaigns: number;
    /** Platform admins only. */
    ai_cost_usd?: number;
    discovery_cost_usd?: number;
    today: number;
    week: number;
    month: number;
    conversion_rate: number | null;
    reached: number;
  };
  /** Last 30 days against the 30 before. */
  period: Record<"new" | "with_contact" | "qualified" | "credits_used", { current: number; previous: number }>;
  pipeline: Record<string, number>;
  next_actions: {
    id: string;
    name: string;
    city: string | null;
    country: string | null;
    industry: string | null;
    score: number | null;
    priority: string | null;
    crm_status: string;
    whatsapp: string | null;
    phone: string | null;
    /** The latest ready first message for this lead, pre-filled in the WhatsApp link. */
    whatsapp_message: string | null;
  }[];
  checklist: Record<"email_verified" | "profile" | "telegram" | "campaign" | "contacted", boolean>;
  trend: { date: string; count: number }[];
  by_country: { key: string; count: number }[];
  by_industry: { key: string; count: number }[];
  by_source: { key: string; count: number }[];
  score_distribution: { bucket: string; count: number }[];
  recent_leads: { id: string; name: string; city: string | null; country: string | null; score: number | null; priority: string | null; is_demo: boolean; created_at: string }[];
  active_campaigns: { id: string; name: string; status: CampaignStatus; stage: string; stats: CampaignStats; is_demo: boolean }[];
  recent_activity: {
    id: string;
    campaign_id: string;
    campaign: string;
    message: string;
    data?: Record<string, unknown>;
    level: string;
    created_at: string;
  }[];
}

export interface BillingSummary {
  billing_exempt: boolean;
  balance: number;
  on_trial: boolean;
  trial_ends_at: string | null;
  trial_days_left: number | null;
  trial_expired: boolean;
  awaiting_verification?: boolean;
  awaiting_approval?: boolean;
  credits_per_contact: number;
  low_balance: boolean;
  pending_topups: number;
  payment_instructions_ar: string;
  payment_instructions_en: string;
  paypal_enabled: boolean;
}

export type CreditKind = "trial_grant" | "purchase" | "manual_adjust" | "campaign_charge" | "refund";
export type PaymentMethod = "instapay" | "bank_transfer" | "vodafone_cash" | "paypal";
export type TopUpStatus = "pending" | "approved" | "rejected";

export interface CreditTransaction {
  id: string;
  delta: number;
  balance_after: number;
  kind: CreditKind;
  campaign_id: string | null;
  business_id: string | null;
  note: string | null;
  created_at: string;
}

export interface CreditPackage {
  id: string;
  name_ar: string;
  name_en: string;
  credits: number;
  price: string;
  currency: string;
  featured?: boolean;
}

export interface TopUp {
  id: string;
  package_id: string | null;
  credits: number;
  amount: string;
  currency: string;
  method: PaymentMethod;
  reference: string | null;
  receipt_filename: string | null;
  status: TopUpStatus;
  reason: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface PublicTestimonial {
  id: string;
  author_name: string;
  author_role: string | null;
  company: string | null;
  city: string | null;
  country: string | null;
  rating: number;
  body_ar: string;
  body_en: string;
  is_featured: boolean;
}

export type NotifyChannel = "in_app" | "email" | "telegram";

export interface NotificationItem {
  id: string;
  kind: string;
  title: string;
  body: string;
  link: string | null;
  read_at: string | null;
  created_at: string;
}

export interface NotificationPage {
  items: NotificationItem[];
  total: number;
  unread: number;
}

export interface NotificationPrefs {
  kinds: {
    key: string;
    category: string;
    locked: boolean;
    channels: Record<NotifyChannel, { allowed: boolean; on: boolean }>;
  }[];
  telegram_linked: boolean;
  email_verified: boolean;
}
