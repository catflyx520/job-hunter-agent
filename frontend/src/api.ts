/// <reference types="vite/client" />
// 后端 API 的型别与呼叫。型别对应 backend/app/schemas。
import { lang, t } from "./i18n";

// vite build --mode demo：没有后端，读 demo.ts 的假资料
export const DEMO = import.meta.env.MODE === "demo";

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
  linkedin_premium: boolean;
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
  if (DEMO) {
    if (method !== "GET") throw new ApiError(t("演示模式只能查看。想完整使用，请下载到自己电脑上运行。"));
    return (await import("./demo")).demoGet<T>(path);
  }
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
  found_on: string[]; // 在哪些网站找到（job_sites.id）
}

// ---------- 投递追踪（F5） ----------

export type ApplicationStatus = "saved" | "referred" | "applied" | "interviewing" | "offer" | "rejected" | "ghosted" | "dismissed";

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
  events: {
    id: number;
    from_status: string | null;
    to_status: ApplicationStatus;
    note: string | null;
    at: string;
    source?: "user" | "email";
    email_message?: EmailEvidence | null;
  }[];
}

// ---------- 邮件同步（F5，Gmail 只读） ----------

export interface EmailEvidence {
  from_addr: string;
  subject: string;
  received_at: string;
  gmail_url: string;
}

export interface GmailStatus {
  connected: boolean;
  email: string | null;
  connected_at: string | null;
  client_id: string | null;
  has_client_secret: boolean;
  mode: "claude_cli" | "oauth" | null;
  last_sync: { id: string; status: string; started_at: string } | null;
}

export type MailKind = "application_received" | "rejection" | "interview" | "offer" | "not_evidence";

export interface MailMsg extends EmailEvidence {
  id: string;
  excerpt: string | null;
  kind: MailKind;
  company: string | null;
  title: string | null;
}

export interface MailJob {
  job_id: string | null;
  company: string | null;
  title: string | null;
  status: ApplicationStatus | null;
}

export interface MailItem extends MailJob {
  message: MailMsg;
  from: ApplicationStatus | null;
  to: ApplicationStatus | null;
}

export interface ReviewItem {
  message: MailMsg;
  reason: string | null;
  candidates: MailJob[];
  bulk_create: boolean; // 信里写明公司与职称、找不到对应职位：可以一次全部新建
}

export interface EmailSync {
  id: string | null;
  status: "running" | "completed" | "failed" | null;
  window_after?: string;
  window_before?: string | null;
  fetched?: number;
  processed?: number;
  truncated?: boolean;
  error?: string | null;
  finished_at?: string | null;
  summary: { created: MailItem[]; updated: MailItem[]; evidence_only: MailItem[]; needs_review: number; ignored: number } | null;
  needs_review: ReviewItem[];
}

// ---------- 搜索（F3） ----------

export interface JobSite {
  id: string;
  name: string;
  access_method: "web_search" | "ats_api" | "paste_only" | "browser";
  enabled: boolean;
  max_results: number;
  sort_order: number;
  limitation_note: string | null;
  boards: number;
}

// ---------- Reach out ----------

export type RoleKind = "engineer" | "eng_manager" | "recruiter" | "other";
export type Channel = "connect_note" | "inmail" | "linkedin_message" | "email";
export type OutreachStyle = "technical" | "general";

export interface Candidate {
  full_name: string;
  title: string;
  linkedin_url: string | null;
  email: string | null;
  email_confidence: number | null;
  found_via: "web_search" | "hunter";
  role_kind: RoleKind;
  why: string;
  contact_id: string | null;
}

export interface Contact {
  id: string;
  company_id: string | null;
  company_name: string | null;
  full_name: string;
  title: string | null;
  linkedin_url: string | null;
  email: string | null;
  email_source: "hunter" | "user" | null;
  email_confidence: number | null;
  found_via: string;
  role_kind: RoleKind;
  notes: string | null;
  created_at: string;
}

export interface ContactSummary {
  id: string;
  full_name: string;
  title: string | null;
  company_id: string | null;
  company_name: string | null;
  last_message_at: string | null;
  last_direction: "out" | "in" | null;
  message_count: number;
}

export interface OutreachMessage {
  id: string;
  contact_id: string;
  job_id: string | null;
  direction: "out" | "in";
  channel: Channel;
  style: OutreachStyle | null;
  subject: string | null;
  body: string;
  material_meta: Record<string, unknown> | null;
  sent_at: string;
}

export interface ContactDetail extends Contact {
  messages: OutreachMessage[];
  jobs: JobSummary[];
}

export interface DraftVersion {
  channel: Channel;
  subject: string | null;
  body: string;
  length: number;
  limit: number | null;
  over_limit: boolean;
  citations: { sentence: string; supported: boolean }[];
  needs_confirmation: { item: string; why: string }[];
}

export interface DraftsOut {
  style: OutreachStyle;
  language: "en" | "zh";
  versions: DraftVersion[];
  material_meta: Record<string, unknown>;
}

export interface HunterSettings {
  enabled: boolean;
  key_last4: string | null;
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
  // note：需要你处理的事（例如到浏览器窗口登录）
  progress: { phase: string; total: number; done: number; checked: number; outcomes: Record<string, number>; note?: string | null } | null;
  counts: Record<string, number>;
}

// 登录浏览器：用自己的登录身份搜索（目前只有 LinkedIn）
export interface BrowserStatus {
  enabled: boolean;
  available: boolean;
  reason: string | null;
  window_open: boolean;
  logged_in: Record<string, boolean | null>;
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

export interface StyleRule {
  id: string;
  kind: "cover_letter" | "qa";
  text: string;
  origin: "learned" | "manual";
  status: "active" | "removed";
  source_count: number;
  updated_at: string;
}
export interface KindStyle {
  rules: StyleRule[];
  removed: StyleRule[];
  samples: number;
  pending: number;
}
export type StyleRules = Record<"cover_letter" | "qa", KindStyle>;
export interface LearnResult {
  added: string[];
  dropped: string[];
  style: KindStyle;
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
  style_rules: string[] | null;
  job_title: string | null;
  company: string | null;
}
