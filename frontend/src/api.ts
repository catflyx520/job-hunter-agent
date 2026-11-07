// 后端 API 的型别与呼叫。型别对应 backend/app/schemas。

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
  seniority: string[];
  locations: string[];
  work_modes: string[];
  employment_types: string[];
  min_salary: number | null;
  salary_rule: string;
  exclude_new_grad_only: boolean;
  work_authorization: {
    authorized_in_us: boolean | null;
    needs_sponsorship_now: boolean | null;
    needs_sponsorship_future: boolean | null;
    note: string;
  };
  search: { sites: string[]; per_site_limit: number; total_limit: number };
}

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
  const init: RequestInit = { method, headers: {} };
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
