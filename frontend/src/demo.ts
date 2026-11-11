// 演示模式（vite --mode demo）的假资料，不连后端。公司和职位全是虚构的。
// 匹配理由和 cover letter 只从履历内容算出来：demo 可能放真人履历，不能替本人编经历。
// 身份、薪资这类个人条件一律留空。
import type {
  Application,
  ApplicationStatus,
  JobDetail,
  JobPreferences,
  JobSite,
  JobSummary,
  Material,
  ParsedResume,
  Resume,
  RunJob,
  SearchRun,
  SearchRunDetail,
  SponsorStatus,
} from "./api";

const DAY = 86_400_000;
const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString();

const SAMPLE_RESUME: ParsedResume = {
  basics: { name: "Alex Sample", email: "", phone: "", location: "Remote", links: [] },
  summary: "Synthetic resume used by the demo: a software engineer who builds web products.",
  skills: ["TypeScript", "React", "Python", "FastAPI", "PostgreSQL", "Docker", "AWS", "REST APIs"],
  experience: [
    {
      company: "Example Software",
      title: "Software Engineer",
      location: "Remote",
      start: "2021",
      end: "Present",
      bullets: ["Built internal tools with React and Python."],
    },
  ],
  projects: [],
  education: [],
};

// 部署时放在 public/ 的履历（不进 git）；没有就用合成履历
let resumeFile: Promise<ParsedResume> | undefined;
const loadResume = () =>
  (resumeFile ??= fetch("/demo-resume.json")
    .then((r) => r.json() as Promise<ParsedResume>)
    .catch(() => SAMPLE_RESUME));

interface Row {
  title: string;
  company: string;
  place: string;
  mode: string;
  pay: [number, number] | null;
  policy: JobSummary["sponsorship_policy"];
  visa: "both" | "h1b" | "none";
  tier: number | null;
  score: number | null;
  site: string;
  days: number;
  status?: ApplicationStatus;
  excluded?: [string, string];
  duplicate?: boolean;
}

const ROWS: Row[] = [
  { title: "Senior Full Stack Engineer", company: "Brightloop Labs", place: "Remote, US", mode: "remote", pay: [150000, 190000], policy: "explicit_yes", visa: "both", tier: 1, score: 91, site: "greenhouse", days: 1 },
  { title: "AI Product Engineer", company: "Kestrel Robotics", place: "San Francisco, CA", mode: "hybrid", pay: [165000, 210000], policy: "unclear", visa: "both", tier: 3, score: 86, site: "ashby", days: 2 },
  { title: "Software Engineer, Platform", company: "Meridian Cloudworks", place: "New York, NY", mode: "hybrid", pay: [140000, 175000], policy: "explicit_yes", visa: "h1b", tier: 2, score: 82, site: "lever", days: 2 },
  { title: "Frontend Engineer", company: "Nimbus Learning Co", place: "Remote, US", mode: "remote", pay: [125000, 155000], policy: "unclear", visa: "h1b", tier: 1, score: 78, site: "greenhouse", days: 3 },
  { title: "Backend Engineer", company: "Quarry Data Works", place: "Austin, TX", mode: "onsite", pay: [130000, 160000], policy: "unclear", visa: "none", tier: null, score: 68, site: "web", days: 3 },
  { title: "Full Stack Developer", company: "Pinecrest Media Group", place: "Remote, US", mode: "remote", pay: null, policy: "unclear", visa: "none", tier: 1, score: 61, site: "web", days: 4 },
  { title: "Machine Learning Engineer", company: "Solstice Grid", place: "Denver, CO", mode: "hybrid", pay: [155000, 185000], policy: "explicit_yes", visa: "both", tier: null, score: 52, site: "ashby", days: 5 },
  { title: "Software Engineer II", company: "Tidewater Freight Tech", place: "New York, NY", mode: "onsite", pay: [120000, 145000], policy: "unclear", visa: "h1b", tier: 2, score: 74, site: "lever", days: 6, status: "saved" },
  { title: "Product Engineer", company: "Lattice Commerce Labs", place: "Remote, US", mode: "remote", pay: [145000, 180000], policy: "explicit_yes", visa: "both", tier: 1, score: 88, site: "greenhouse", days: 8, status: "offer" },
  { title: "Senior Software Engineer", company: "Harbor Analytics Co", place: "San Francisco, CA", mode: "hybrid", pay: [170000, 215000], policy: "explicit_yes", visa: "both", tier: 3, score: 84, site: "ashby", days: 10, status: "interviewing" },
  { title: "Web Platform Engineer", company: "Cedar Health Systems", place: "Remote, US", mode: "remote", pay: [135000, 165000], policy: "unclear", visa: "h1b", tier: 1, score: 79, site: "lever", days: 12, status: "interviewing" },
  { title: "Software Engineer", company: "Orchard Ledger", place: "New York, NY", mode: "hybrid", pay: [130000, 160000], policy: "unclear", visa: "both", tier: 2, score: 76, site: "greenhouse", days: 5, status: "applied" },
  { title: "Application Engineer", company: "Redwood Mobility Inc", place: "Remote, US", mode: "remote", pay: [115000, 140000], policy: "unclear", visa: "none", tier: 1, score: 66, site: "web", days: 20, status: "applied" },
  { title: "Full Stack Engineer", company: "Fernhill Studio", place: "Remote, US", mode: "remote", pay: [110000, 135000], policy: "unclear", visa: "none", tier: 1, score: 63, site: "web", days: 24, status: "rejected" },
  { title: "Developer Tools Engineer", company: "Juniper Stack", place: "San Francisco, CA", mode: "hybrid", pay: [150000, 180000], policy: "unclear", visa: "h1b", tier: 3, score: 71, site: "ashby", days: 26, status: "ghosted" },
  { title: "Solutions Developer", company: "Wren Consulting", place: "Chicago, IL", mode: "onsite", pay: null, policy: "unclear", visa: "none", tier: null, score: 44, site: "web", days: 9, status: "dismissed" },
  { title: "Sales Engineer", company: "Vantage Signal", place: "Remote, US", mode: "remote", pay: null, policy: "unclear", visa: "none", tier: 1, score: null, site: "web", days: 2, excluded: ["blacklisted_title", "Title matches your blacklist"] },
  { title: "Software Developer", company: "Umbra Staffing", place: "Remote, US", mode: "remote", pay: null, policy: "unclear", visa: "none", tier: 1, score: null, site: "web", days: 3, excluded: ["blacklisted_company", "Company is on your blacklist"] },
  { title: "Graduate Software Engineer", company: "Alder Works", place: "New York, NY", mode: "onsite", pay: [90000, 110000], policy: "unclear", visa: "none", tier: 2, score: null, site: "lever", days: 4, excluded: ["new_grad_only", "Limited to new graduates"] },
  { title: "Frontend Engineer", company: "Nimbus Learning Co", place: "Remote, US", mode: "remote", pay: [125000, 155000], policy: "unclear", visa: "h1b", tier: 1, score: 78, site: "web", days: 3, duplicate: true },
];

const SITE_NAMES: Record<string, string> = { greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", web: "Web search" };
const SUBMITTED: (string | undefined)[] = ["applied", "interviewing", "offer", "rejected", "ghosted"];
const RUN_ID = "demo-run";
const recommend = (s: number | null) => (s == null ? null : s >= 75 ? "apply" : s >= 55 ? "maybe" : "skip");

function summary(r: Row, i: number): JobSummary {
  return {
    id: `demo-job-${i}`,
    title: r.title,
    company: { id: `demo-company-${i}`, display_name: r.company, website: "https://example.com", is_staffing_agency: false },
    location_text: r.place,
    work_mode: r.mode,
    employment_type: "full_time",
    salary_min: r.pay?.[0] ?? null,
    salary_max: r.pay?.[1] ?? null,
    salary_period: r.pay ? "year" : null,
    sponsorship_policy: r.policy,
    status: "active",
    created_at: ago(r.days),
    score: r.score,
    recommendation: recommend(r.score),
    excluded: !!r.excluded,
    sponsor_status: r.visa === "none" ? "no_match_in_scope" : "records_found",
    sponsor_h1b: r.visa !== "none",
    sponsor_perm: r.visa === "both",
    location_tier: r.tier,
    posted_text: `${r.days}d ago`,
    posted_at: ago(r.days),
    apply_url: "https://example.com/careers",
    application_status: r.status ?? null,
    applied_at: SUBMITTED.includes(r.status) ? ago(r.days) : null,
    status_at: r.status ? ago(Math.max(r.days - 1, 0)) : null,
  };
}

const JOBS = ROWS.map(summary);
const jobIndex = (id: string) => JOBS.findIndex((j) => j.id === id);

function sponsor(r: Row): SponsorStatus {
  const years = [2023, 2024, 2025];
  const records = (n: number) => years.map((fiscal_year, k) => ({ fiscal_year, filed: n + k * 3, certified_or_approved: n + k * 3 - 1, denied: 1 }));
  return {
    status: r.visa === "none" ? "no_match_in_scope" : "records_found",
    h1b_years: r.visa === "none" ? null : years,
    perm_years: r.visa === "both" ? years : null,
    summary: {
      notes: ["Sample numbers for the demo. This company is fictional."],
      programs: r.visa === "none" ? {} : { lca: records(18), uscis_h1b: records(12), ...(r.visa === "both" ? { perm: records(4) } : {}) },
      entities: r.visa === "none" ? [] : [{ name: `${r.company} (sample entity)`, method: "exact", evidence_url: null, note: null }],
      pending: [],
    },
    coverage: { programs: { lca: years, perm: years, uscis_h1b: years }, sources: [], dataset_count: 6 },
    computed_at: ago(0),
  };
}

// 职位要求的技能取自履历，再加一个履历上没有的当缺口
function skillsFor(resume: ParsedResume, i: number) {
  const have = Array.from(new Set([0, 1, 2, 3].map((k) => resume.skills[(i * 3 + k) % resume.skills.length]))).filter(Boolean);
  const listed = resume.skills.map((s) => s.toLowerCase());
  const gap = ["Kubernetes", "Terraform", "Kafka", "Rust", "Scala"].find((g, k) => k >= i % 3 && !listed.includes(g.toLowerCase())) ?? "Kafka";
  return { have, gap };
}

function detail(resume: ParsedResume, i: number): JobDetail {
  const r = ROWS[i];
  const base = JOBS[i];
  const { have, gap } = skillsFor(resume, i);
  const recent = resume.experience[0];
  const score = r.score ?? 0;
  const sample = "Sample score for the demo.";
  const part = (max: number) => Math.floor((score * max) / 100);
  const rest = score - part(30) - part(20) - part(10) * 2;
  return {
    ...base,
    requisition_id: `DEMO-${1000 + i}`,
    seniority: r.title.includes("Senior") ? "senior" : "mid",
    salary_currency: r.pay ? "USD" : null,
    sponsorship_evidence: r.policy === "explicit_yes" ? "Visa sponsorship is available for this role." : null,
    new_grad_only: r.excluded?.[0] === "new_grad_only",
    citizenship_required: false,
    clearance_required: false,
    easy_apply: i % 3 === 0,
    verification_source: r.site === "web" ? "search_snippet" : "ats_api",
    verified_at: ago(r.days),
    jd_text: `This is a fictional posting created for the demo.\n\n${r.title} at ${r.company}\n\nWhat you will do\n- Design, build and ship product features end to end.\n- Work with product and design on what to build next.\n\nWhat we look for\n- Experience with ${have.join(", ")}.\n- Familiarity with ${gap}.`,
    extracted: { required_skills: have, nice_to_have_skills: [gap] },
    sources: [{ site_id: r.site, url: "https://example.com/careers" }],
    exclusion: { reasons: r.excluded ? [{ code: r.excluded[0], label: r.excluded[1] }] : [], flags: [] },
    match:
      r.score == null
        ? null
        : {
            id: `demo-match-${i}`,
            score,
            breakdown: {
              role: { score: part(30), max: 30, reason: sample },
              tech: { score: rest, max: 30, reason: `Compared the posting with the skills on the resume. ${sample}` },
              experience: { score: part(20), max: 20, reason: sample },
              location: { score: part(10), max: 10, reason: sample },
              recency: { score: part(10), max: 10, reason: sample },
            },
            recommendation: recommend(r.score)!,
            reasons: [
              { text: `The posting asks for ${have.join(", ")}, which the resume lists.`, chunk_ids: ["skills"] },
              ...(recent ? [{ text: `Most recent role on the resume: ${recent.title}.`, chunk_ids: ["experience"] }] : []),
            ],
            gaps: [{ text: `The posting mentions ${gap}, which is not on the resume.`, severity: "low" }],
            exclusion_reasons: null,
            model: "demo-sample",
            preferences_version: 1,
            created_at: ago(r.days),
          },
    sponsor: sponsor(r),
    evidence: { skills: resume.skills.join(", "), experience: recent ? `${recent.title}, ${recent.company}` : "" },
  };
}

function letter(resume: ParsedResume, i: number): Material {
  const r = ROWS[i];
  const { have } = skillsFor(resume, i);
  const recent = resume.experience[0];
  const text = [
    `Dear ${r.company} hiring team,`,
    resume.summary,
    `${recent ? `My most recent role is ${recent.title} at ${recent.company}. ` : ""}The ${r.title} posting asks for ${have.join(", ")}, all of which are on my resume.`,
    `Best regards,\n${resume.basics.name}`,
  ].join("\n\n");
  return {
    id: `demo-letter-${i}`,
    job_id: JOBS[i].id,
    kind: "cover_letter",
    question: null,
    requirements: null,
    jd_source: "job",
    facts_used: [],
    status: "draft",
    output_text: text,
    edited_text: null,
    needs_confirmation: [{ item: `Why ${r.company}`, why: "The resume does not say, so the tool asks instead of inventing a reason." }],
    citations: null,
    provider_kind: "demo",
    model: "demo-sample",
    error: null,
    created_at: ago(r.days),
    images: [],
    evidence: {},
  };
}

function application(i: number): Application | null {
  const j = JOBS[i];
  if (!j.application_status) return null;
  return {
    id: `demo-app-${i}`,
    job_id: j.id,
    status: j.application_status,
    previous_status: null,
    applied_at: j.applied_at,
    resume_id: "demo-resume",
    cover_letter_id: null,
    notes: null,
    created_at: j.created_at,
    updated_at: j.status_at ?? j.created_at,
    events: [{ id: i, from_status: null, to_status: j.application_status, note: null, at: j.status_at ?? j.created_at }],
  };
}

const PREFERENCES: JobPreferences = {
  target_roles: ["Software Engineer", "Full Stack Engineer", "AI Product Engineer"],
  paused_roles: ["Machine Learning Engineer"],
  blacklist: { companies: ["Umbra Staffing"], titles: ["Sales Engineer"] },
  seniority: ["mid", "senior"],
  locations: ["Remote", "New York, NY", "San Francisco, CA"],
  work_modes: ["remote", "hybrid"],
  employment_types: ["full_time"],
  min_salary: null,
  salary_rule: "exclude_if_entire_range_below",
  exclude_new_grad_only: true,
  work_authorization: { status: null, authorized_in_us: null, needs_sponsorship_now: null, needs_sponsorship_future: null, note: "" },
  search: { sites: Object.keys(SITE_NAMES), per_site_limit: 20, total_limit: 100, target_jobs: 20 },
};

const SITES: JobSite[] = Object.entries(SITE_NAMES).map(([id, name], i) => ({
  id,
  name,
  access_method: id === "web" ? "web_search" : "ats_api",
  enabled: true,
  max_results: 20,
  sort_order: i,
  limitation_note: null,
  boards: id === "web" ? 0 : 12,
}));

const outcome = (r: Row): RunJob["outcome"] => (r.excluded ? "excluded" : r.duplicate ? "duplicate" : "kept");
const countBy = <T>(items: T[], key: (x: T) => string) =>
  items.reduce<Record<string, number>>((acc, x) => ({ ...acc, [key(x)]: (acc[key(x)] ?? 0) + 1 }), {});

const RUN: SearchRun = {
  id: RUN_ID,
  status: "completed",
  created_at: ago(1),
  started_at: ago(1),
  finished_at: ago(1),
  error: null,
  search_source: "Demo",
  sponsor_history: true,
  sites: SITES.map((s) => {
    const rows = ROWS.filter((r) => r.site === s.id);
    return { site_id: s.id, name: s.name, status: "ok", found_count: rows.length, kept_count: rows.filter((r) => outcome(r) === "kept").length, message: null };
  }),
  target_jobs: null,
  progress: null,
  counts: countBy(ROWS, outcome),
};

const runDetail = (): SearchRunDetail => ({
  ...RUN,
  jobs: JOBS.map((j, i) => ({
    ...j,
    outcome: outcome(ROWS[i]),
    exclusion_reasons: ROWS[i].excluded ? [{ code: ROWS[i].excluded![0], label: ROWS[i].excluded![1] }] : [],
    found_on: [ROWS[i].site],
  })),
});

// 统计和下钻用同一张分类表，两边数字才对得上
const SALARY: [number, string][] = [[80000, "< $80k"], [100000, "$80k–100k"], [130000, "$100k–130k"], [160000, "$130k–160k"], [200000, "$160k–200k"], [Infinity, "≥ $200k"]];
const SCORE: [number, string][] = [[40, "0–39"], [55, "40–54"], [75, "55–74"], [101, "75–100"]];
const bucket = (v: number | null, table: [number, string][], none: string) => (v == null ? none : table.find(([top]) => v < top)![1]);
const STALE_DAYS = 14;
const status = (j: JobSummary) => j.application_status ?? "none";
const submitted = (j: JobSummary) => SUBMITTED.includes(j.application_status ?? undefined);
const DIMS: Record<string, (j: JobSummary, i: number) => string> = {
  application_status: status,
  sponsorship_policy: (j) => j.sponsorship_policy,
  sponsor_status: (j) => j.sponsor_status ?? "not_checked",
  location_tier: (j) => (j.location_tier ? String(j.location_tier) : "none"),
  work_mode: (j) => j.work_mode,
  salary: (j) => bucket(j.salary_max, SALARY, "unknown"),
  score: (j) => bucket(j.score, SCORE, "none"),
  recommendation: (j) => j.recommendation ?? "none",
  easy_apply: (_, i) => (i % 3 === 0 ? "yes" : "no"),
  exclusion: (_, i) => ROWS[i].excluded?.[0] ?? "",
  site: (_, i) => ROWS[i].site,
  backlog: (j, i) => (j.application_status === "saved" ? "saved_not_applied" : j.application_status === "applied" && ROWS[i].days > STALE_DAYS ? "applied_no_update" : ""),
};
const STAGES: [string, string, (j: JobSummary) => boolean][] = [
  ["found", "搜索到", () => true],
  ["saved", "收藏以上", (j) => !!j.application_status && j.application_status !== "dismissed"],
  ["applied", "已投递", submitted],
  ["interviewing", "面试", (j) => j.application_status === "interviewing" || j.application_status === "offer"],
  ["offer", "Offer", (j) => j.application_status === "offer"],
];

function trend(windows: number, step: number) {
  return Array.from({ length: windows }, (_, k) => {
    const from = (windows - k - 1) * step;
    const inside = JOBS.filter((j, i) => submitted(j) && ROWS[i].days >= from && ROWS[i].days < from + step);
    return {
      date: ago(from).slice(0, 10),
      applied: inside.length,
      interviewing: inside.filter((j) => j.application_status === "interviewing").length,
      other: 0,
    };
  });
}

function stats() {
  const dim = (key: string) => countBy(JOBS.map(DIMS[key]), (v) => v);
  const st = dim("application_status");
  const sent = JOBS.filter(submitted).length;
  const replied = (st.interviewing ?? 0) + (st.offer ?? 0) + (st.rejected ?? 0);
  const backlog = dim("backlog");
  const excluded = ROWS.filter((r) => r.excluded);
  return {
    totals: {
      found: JOBS.length,
      saved: st.saved ?? 0,
      submitted: sent,
      interviewing: st.interviewing ?? 0,
      offer: st.offer ?? 0,
      rejected: st.rejected ?? 0,
      ghosted: st.ghosted ?? 0,
      dismissed: st.dismissed ?? 0,
      reply_rate: Math.round((replied / sent) * 1000) / 1000,
    },
    funnel: STAGES.map(([stage, label, fn]) => ({ stage, label, count: JOBS.filter(fn).length })),
    application_status: st,
    sponsorship_policy: dim("sponsorship_policy"),
    sponsor_status: dim("sponsor_status"),
    location_tier: dim("location_tier"),
    work_mode: dim("work_mode"),
    exclusions: excluded.map((r) => ({ code: r.excluded![0], label: r.excluded![1], count: 1 })),
    sources: SITES.map((s) => {
      const on = JOBS.filter((_, i) => ROWS[i].site === s.id);
      return {
        site: s.id,
        name: s.name,
        found: on.length,
        kept: on.filter((j) => !j.excluded).length,
        applied: on.filter(submitted).length,
        interviews: on.filter((j) => j.application_status === "interviewing" || j.application_status === "offer").length,
      };
    }),
    easy_apply: dim("easy_apply"),
    salary: dim("salary"),
    score: dim("score"),
    recommendation: dim("recommendation"),
    trend: { day: trend(30, 1), week: trend(5, 7) },
    backlog: { saved_not_applied: backlog.saved_not_applied ?? 0, applied_no_update: backlog.applied_no_update ?? 0, stale_days: STALE_DAYS },
  };
}

function drill(dim: string, value: string) {
  if (dim === "stage") return JOBS.filter(STAGES.find(([k]) => k === value)?.[2] ?? (() => false));
  return JOBS.filter((j, i) => DIMS[dim]?.(j, i) === value);
}

function resumeRow(parsed: ParsedResume): Resume {
  return {
    id: "demo-resume",
    label: "Demo",
    filename: "resume.pdf",
    mime: "application/pdf",
    sha256: "",
    parsed,
    parsed_confirmed_at: ago(7),
    is_active: true,
    created_at: ago(7),
    chunk_count: parsed.experience.length + parsed.projects.length + 1,
    latest_review: null,
  };
}

async function route(path: string, q: URLSearchParams): Promise<unknown> {
  const resume = await loadResume();
  const job = path.match(/^\/api\/jobs\/([^/]+)(\/application)?$/);
  if (job) {
    const i = jobIndex(job[1]);
    if (i < 0) throw new Error("Not found");
    return job[2] ? application(i) : detail(resume, i);
  }
  switch (path) {
    case "/api/providers":
      return [{ id: "demo-model", kind: "openai_compatible", name: "Demo model", base_url: null, api_key_last4: null, has_api_key: false, default_model: "demo-sample", capabilities: { structured_output: true, vision: false, web_search: true, tool_calling: true }, enabled: true, last_checked_at: ago(0), last_check_error: null }];
    case "/api/task-routes":
      return [];
    case "/api/cli-status":
      return { clis: [], notice: "", login: null };
    case "/api/resumes":
      return [resumeRow(resume)];
    case "/api/resumes/demo-resume":
      return resumeRow(resume);
    case "/api/resumes/demo-resume/reviews":
      return []; // 不给真人履历打虚构的分数
    case "/api/ats-explained":
      return { zh: "", en: "" };
    case "/api/preferences":
      return { data: PREFERENCES, version: 1 };
    case "/api/job-sites":
      return SITES;
    case "/api/ats-boards":
      return [];
    case "/api/search/source":
      return { ready: true, label: "Demo", integration: null };
    case "/api/sponsor/coverage":
      return { dataset_count: 6, import: null };
    case "/api/search-runs":
      return [RUN];
    case `/api/search-runs/${RUN_ID}`:
      return runDetail();
    case "/api/jobs":
      return JOBS;
    case "/api/materials": {
      const all = [letter(resume, 0), letter(resume, 8)];
      const jobId = q.get("job_id");
      return jobId ? all.filter((m) => m.job_id === jobId) : all;
    }
    case "/api/materials/similar":
      return [];
    // shortcut: 统计页的筛选条件在 demo 里不生效，要演示筛选时再按 q 过滤
    case "/api/stats":
      return stats();
    case "/api/stats/jobs":
      return drill(q.get("dim") ?? "", q.get("value") ?? "");
    case "/api/stats/options":
      return { companies: JOBS.map((j) => ({ id: j.company.id, name: j.company.display_name })), sites: SITES.map((s) => ({ id: s.id, name: s.name })), runs: [RUN_ID] };
    default:
      throw new Error(`Not available in the demo: ${path}`);
  }
}

export async function demoGet<T>(url: string): Promise<T> {
  const u = new URL(url, "http://demo.invalid");
  return (await route(u.pathname, u.searchParams)) as T;
}
