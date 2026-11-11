// 后端 API 的型别与呼叫。型别对应 backend/app/schemas。
import { lang } from "./i18n";

export type ProviderKind = "openai" | "anthropic" | "openai_compatible" | "ollama" | "claude_cli" | "codex_cli";

export interface Capabilities {
  structured_output: boolean;
  vision: boolean;
  web_search: boolean;
  tool_calling: boolean;
}

export interface Provider {
  id: string;
  kind: ProviderKind;
  name: string;
  base_url: string | null;
  api_key_last4: string | null;
  has_api_key: boolean;
  default_model: string;
  capabilities: Capabilities;
  enabled: boolean;
  last_checked_at: string | null;
  last_check_error: string | null;
}

export interface TaskRoute {
  task: string;
  label: string;
  provider_id: string | null;
  model: string | null;
  chunk_count?: number | null;
  chunk_error?: string | null;
}

export type CliAuthState = "not_installed" | "signed_in" | "signed_out" | "invalid" | "unknown";

export interface CliStatus {
  name: "claude" | "codex";
  available: boolean;
  version: string | null;
  error: string | null;
  state: CliAuthState;
  email: string | null;
  auth_method: string | null;
}

export interface CliLogin {
  cli: string;
  running: boolean;
  url: string | null;
  output: string;
  exit_code: number | null;
  message: string;
}

export interface CliInfo {
  clis: CliStatus[];
  notice: string;
  login: CliLogin | null;
}

export interface Experience {
  company: string;
  title: string;
  location: string;
  start: string;
  end: string;
  bullets: string[];
}
export interface Project {
  name: string;
  description: string;
  tech: string[];
  bullets: string[];
}
export interface Education {
  school: string;
  degree: string;
  field: string;
  start: string;
  end: string;
  details: string[];
}
export interface ParsedResume {
  basics: { name: string; email: string; phone: string; location: string; links: { label: string; url: string }[] };
  summary: string;
  skills: string[];
  experience: Experience[];
  projects: Project[];
  education: Education[];
}

export interface Resume {
  id: string;
  label: string;
  filename: string;
  mime: string;
  sha256: string;
  parsed: ParsedResume;
  parsed_confirmed_at: string | null;
  is_active: boolean;
  created_at: string;
  chunk_count: number;
  latest_review: { parse_score: number; content_score: number; keyword_score: number | null; created_at: string } | null;
  raw_text?: string;
}

export interface UploadResult {
  resume: Resume;
  parse_error: string | null;
  unverified_items: string[];
}

export interface Finding {
  category: "parse" | "content" | "keyword";
  check: string;
  status: "pass" | "warn" | "fail";
  message: string;
  evidence: string | null;
  points_lost: number;
}

export interface Review {
  id: string;
  target_role: string | null;
  parse_score: number;
  content_score: number;
  keyword_score: number | null;
  findings: Finding[];
  model: string;
  created_at: string;
}

export interface JobPreferences {
  target_roles: string[];
  paused_roles: string[];
  blacklist: { companies: string[]; titles: string[] };
  seniority: string[];
  locations: string[];
  work_modes: string[];
  employment_types: string[];
  min_salary: number | null;
  salary_rule: string;
  exclude_new_grad_only: boolean;
  work_authorization: {
    status: VisaStatus | null;
    authorized_in_us: boolean | null;
    needs_sponsorship_now: boolean | null;
    needs_sponsorship_future: boolean | null;
    note: string;
  };
  search: { sites: string[]; per_site_limit: number; total_limit: number; target_jobs: number };
}

export type VisaStatus = "us_citizen" | "green_card" | "h1b" | "opt" | "other";

export interface Fact {
  id: string;
  key: string;
  question: string;
  value: string;
  value_type: "text" | "number" | "date" | "boolean" | "choice";
  source: string;
  confirmed_at: string | null;
}

export interface FactTemplate {
  key: string;
  question: string;
  value_type: Fact["value_type"];
}

export class ApiError extends Error {}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  // 后端产生的说明、错误讯息、模型输出都跟着介面语言
  const init: RequestInit = { method, headers: { "X-UI-Lang": lang } };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((d: { msg: string }) => d.msg).join("；");
    } catch {
      /* 非 JSON 回应 */
    }
    throw new ApiError(detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b),
  put: <T>(p: string, b?: unknown) => request<T>("PUT", p, b),
  patch: <T>(p: string, b?: unknown) => request<T>("PATCH", p, b),
  del: (p: string) => request<void>("DELETE", p),
};

// ---------- M2：职位、匹配、签证、材料 ----------

export interface CompanyRef {
  id: string;
  display_name: string;
  website: string | null;
  is_staffing_agency: boolean;
}

export interface JobSummary {
  id: string;
  title: string;
  company: CompanyRef;
  location_text: string | null;
  work_mode: string;
  employment_type: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_period: string | null;
  sponsorship_policy: "explicit_yes" | "explicit_no" | "unclear";
  status: string;
  created_at: string;
  score: number | null;
  recommendation: "apply" | "maybe" | "skip" | null;
  excluded: boolean;
  sponsor_status: SponsorStatusCode | null;
  sponsor_h1b: boolean | null;
  sponsor_perm: boolean | null;
  location_tier: number | null;
  posted_text: string | null;
  posted_at: string | null;
  apply_url: string | null;
  application_status: ApplicationStatus | null;
  applied_at: string | null;
  status_at: string | null;
}

// ---------- 投递追踪（F5） ----------

export type ApplicationStatus = "saved" | "applied" | "interviewing" | "offer" | "rejected" | "ghosted" | "dismissed";

export interface Application {
  id: string;
  job_id: string;
  status: ApplicationStatus;
  previous_status: ApplicationStatus | null;
  applied_at: string | null;
  resume_id: string | null;
  cover_letter_id: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  events: { id: number; from_status: string | null; to_status: ApplicationStatus; note: string | null; at: string }[];
}

// ---------- 搜索（F3） ----------

export interface JobSite {
  id: string;
  name: string;
  access_method: "web_search" | "ats_api" | "paste_only";
  enabled: boolean;
  max_results: number;
  sort_order: number;
  limitation_note: string | null;
  boards: number;
}

export interface SearchSource {
  ready: boolean;
  label: string;
  integration: { kind: "tavily" | "searxng"; base_url: string | null; key_last4: string | null } | null;
}

export interface AtsBoard {
  company_id: string;
  company: string;
  kind: string;
  token: string;
}

export type RunSiteStatus = "ok" | "partial" | "blocked" | "failed" | "skipped" | "searching";

export interface RunSite {
  site_id: string;
  name: string;
  status: RunSiteStatus;
  found_count: number;
  kept_count: number;
  message: string | null;
}

export interface RunJob extends JobSummary {
  outcome: "kept" | "excluded" | "duplicate";
  exclusion_reasons: { code: string; label: string }[];
  found_on: string[];
}

export interface SearchRun {
  id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  search_source: string | null;
  sponsor_history: boolean;
  sites: RunSite[];
  target_jobs: number | null;
  progress: { phase: string; total: number; done: number; checked: number; outcomes: Record<string, number> } | null;
  counts: Record<string, number>;
}

export interface SearchRunDetail extends SearchRun {
  jobs: RunJob[];
}

export type SponsorStatusCode = "records_found" | "no_match_in_scope" | "not_checked" | "employer_unknown";

export interface SponsorYear {
  fiscal_year: number;
  filed: number;
  certified_or_approved: number;
  denied: number;
}

export interface SponsorStatus {
  status: SponsorStatusCode;
  h1b_years: number[] | null;
  perm_years: number[] | null;
  summary: {
    notes: string[];
    reason?: string;
    programs: Record<string, SponsorYear[]>;
    entities: { name: string; method: string; evidence_url: string | null; note: string | null }[];
    pending: {
      alias_id: string;
      name: string;
      city: string | null;
      state: string | null;
      method: string;
      confidence: number;
      evidence_url: string | null;
      note: string | null;
    }[];
  };
  coverage: { programs: Record<string, number[]>; sources: string[]; dataset_count: number };
  computed_at: string;
}

export interface BreakdownPart {
  score: number;
  max: number;
  reason: string;
}

export interface Match {
  id: string;
  score: number;
  breakdown: Record<"role" | "tech" | "experience" | "location" | "recency", BreakdownPart>;
  recommendation: "apply" | "maybe" | "skip";
  reasons: { text: string; chunk_ids: string[] }[];
  gaps: { text: string; severity: "low" | "medium" | "high" }[];
  exclusion_reasons: string[] | null;
  model: string;
  preferences_version: number;
  created_at: string;
}

export interface JobDetail extends JobSummary {
  requisition_id: string | null;
  seniority: string | null;
  location_tier: number | null;
  salary_currency: string | null;
  posted_text: string | null;
  sponsorship_evidence: string | null;
  new_grad_only: boolean | null;
  citizenship_required: boolean | null;
  clearance_required: boolean | null;
  easy_apply: boolean | null;
  apply_url: string | null;
  verification_source: string | null;
  verified_at: string | null;
  jd_text: string | null;
  extracted: { required_skills?: string[]; nice_to_have_skills?: string[] } | null;
  sources: { site_id: string; url: string }[];
  exclusion: { reasons: { code: string; label: string }[]; flags: { code: string; label: string }[] };
  match: Match | null;
  sponsor: SponsorStatus | null;
  evidence: Record<string, string>;
}

export interface Material {
  id: string;
  job_id: string | null;
  kind: "cover_letter" | "qa";
  question: string | null;
  requirements: string | null;
  jd_source: string;
  facts_used: string[] | null;
  status: string;
  output_text: string | null;
  edited_text: string | null;
  needs_confirmation: { item: string; why: string }[] | null;
  citations: { sentence: string; chunk_ids: string[]; fact_keys: string[]; supported: boolean }[] | null;
  provider_kind: string;
  model: string;
  error: string | null;
  created_at: string;
  images: { position: number; mime: string; width: number; height: number; size_bytes: number }[];
  evidence: Record<string, string>;
}
