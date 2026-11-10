import { ReactNode, useEffect, useState } from "react";
import { api, Finding, ParsedResume, Resume, Review, UploadResult } from "../api";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import ResumeTabs from "./ResumeTabs";
import { Loading, Spinner } from "./ui";

const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
const period = (a: string, b: string) => [a, b].filter(Boolean).join(" – ");

const CATEGORY_LABEL: Record<Finding["category"], string> = {
  parse: "ATS 可读性",
  content: "内容品质",
  keyword: "关键词覆盖",
};
// 每一类分数在看什么（显示在分数下方）
const CATEGORY_HINT: Record<Finding["category"], string> = {
  parse: "招聘系统能不能把你的履历读对：只看格式（文字能否抽出、表格、双栏、标题、联系方式、日期），不看内容好坏。",
  content: "内容写得好不好：量化成果、行动动词开头、具体不重复、篇幅，各 25 分。",
  keyword: "对照目标职位常见的技能关键词，履历涵盖了多少。",
};
const STATUS_LABEL = { pass: "通过", warn: "注意", fail: "未通过" };
const BASIC_LABEL = { name: "姓名", email: "邮箱", phone: "电话", location: "地点" };
const EXP_LABEL = { title: "职称", company: "公司", location: "地点", start: "开始", end: "结束" };
const EDU_LABEL = { school: "学校", degree: "学位", field: "专业", start: "开始", end: "结束" };

/** 「评分」与「履历内容」两个分页：上方选版本，下方显示该版本的评分或内容。 */
export default function Resumes({ view }: { view: "score" | "content" }) {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  // 从「上传」分页上传完跳过来时，带着上传结果（结构化提醒、原文找不到的项目）
  const upload = (location.state as { upload?: UploadResult } | null)?.upload ?? null;
  const [resumes, setResumes] = useState<Resume[] | null>(null);
  const [error, setError] = useState("");

  const selected = params.get("id") ?? resumes?.find((r) => r.is_active)?.id ?? resumes?.[0]?.id ?? null;
  const choose = (id: string) => setParams({ id }, { replace: true, state: location.state });

  const load = () =>
    api
      .get<Resume[]>("/api/resumes")
      .then(setResumes)
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const current = resumes?.find((r) => r.id === selected) ?? null;

  return (
    <div className="stack">
      <ResumeTabs
        tab={view}
        left={
          <>
            {resumes && resumes.length > 0 && (
              <select aria-label="履历版本" value={selected ?? ""} onChange={(e) => choose(e.target.value)} style={{ fontWeight: 600, maxWidth: "100%" }}>
                {resumes.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                    {r.is_active ? " · 使用中" : ""}
                  </option>
                ))}
              </select>
            )}
            {current && (
              <span className="muted" title={`${current.filename} · SHA-256 ${current.sha256.slice(0, 10)}…`}>
                {current.parsed_confirmed_at ? `已确认 · ${current.chunk_count} 个检索切块` : "尚未确认"}
              </span>
            )}
          </>
        }
      />
      {error && <p className="error">{error}</p>}
      {upload?.parse_error && upload.resume.id === selected && <p className="error">{upload.parse_error}</p>}
      {resumes && resumes.length === 0 && (
        <div className="card muted">
          还没有履历。请到 <Link to="/resumes/upload">上传</Link> 分页上传 PDF 或 DOCX，档案只存在本机 data/ 目录。
        </div>
      )}
      {selected && view === "score" && <ReviewPanel key={selected} resumeId={selected} />}
      {selected && view === "content" && (
        <ResumeContent key={selected} id={selected} unverified={upload?.resume.id === selected ? upload.unverified_items : []} onChanged={load} />
      )}
    </div>
  );
}

function Section({
  id,
  group,
  title,
  editing,
  onToggle,
  children,
  edit,
}: {
  id: string;
  group: string;
  title: string;
  editing: string | null;
  onToggle: (id: string) => void;
  children?: ReactNode;
  edit: ReactNode;
}) {
  const open = editing === id;
  return (
    <div className="section">
      <div className="section-head">
        <div style={{ flex: "1 1 auto", minWidth: 0 }}>
          <h2 className="section-group">{group}</h2>
          <div className="section-title">{title || "（未填写）"}</div>
          {!open && children}
        </div>
        <button type="button" className="link" onClick={() => onToggle(id)}>
          {open ? "收起" : "编辑"}
        </button>
      </div>
      {open && <div className="section-edit">{edit}</div>}
    </div>
  );
}

function ResumeContent({ id, unverified, onChanged }: { id: string; unverified: string[]; onChanged: () => void }) {
  const [resume, setResume] = useState<Resume | null>(null);
  const [parsed, setParsed] = useState<ParsedResume | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [flagged] = useState(unverified);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = () =>
    api.get<Resume>(`/api/resumes/${id}`).then((r) => {
      setResume(r);
      setParsed(r.parsed);
    });
  useEffect(() => {
    load();
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    setError("");
    setMsg("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };


  if (!resume || !parsed) return <Loading className="card" />;

  const save = () =>
    run("save", async () => {
      await api.put(`/api/resumes/${id}/parsed`, { parsed, confirm: true });
      const c = await api.post<{ chunk_count: number; error: string | null }>(`/api/resumes/${id}/chunks`);
      setMsg(c.error ? `已确认。检索资料未建立：${c.error}` : `已确认，并建立 ${c.chunk_count} 个检索切块。`);
      setEditing(null);
      await load();
      onChanged();
    });

  const set = (patch: Partial<ParsedResume>) => setParsed({ ...parsed, ...patch });
  const toggle = (s: string) => setEditing((cur) => (cur === s ? null : s));
  const Line = ({ text }: { text: string }) => <div className={`section-line${flagged.includes(text) ? " unverified" : ""}`}>{text}</div>;
  const b = parsed.basics;

  return (
    <section className="card flush">
      <div className="form-head">
        <span className="muted">生成材料时只使用确认过的内容。</span>
        <button type="button" className="primary" onClick={save} disabled={!!busy}>
          {busy === "save" ? <><Spinner />保存中…</> : "确认并保存"}
        </button>
      </div>
      {parsed.experience.length === 0 && !busy && (
        <div style={{ padding: "12px 32px 0" }}>
          <p className="badge warn" style={{ margin: 0, whiteSpace: "normal", padding: "8px 12px" }}>
            结构化结果里没有任何工作经历。如果履历其实有经历，可能是模型漏抓：请到「版本管理」分页点这个版本的「重新结构化」，或在下方「+ 新增经历」手动补上。
          </p>
        </div>
      )}
      {(msg || error || flagged.length > 0) && (
        <div style={{ padding: "12px 32px 0", display: "flex", flexDirection: "column", gap: 8 }}>
          {flagged.length > 0 && <p className="badge warn" style={{ margin: 0, whiteSpace: "normal", padding: "8px 12px" }}>{flagged.length} 项在原文里找不到完全相同的文字，可能被模型改写，已用琥珀色标出，请确认或修正。</p>}
          {msg && <p className="notice">{msg}</p>}
          {error && <p className="error">{error}</p>}
        </div>
      )}
      <div style={{ padding: "8px 32px 20px" }}>
        <Section
          id="basics"
          group="基本信息"
          title={b.name}
          editing={editing}
          onToggle={toggle}
          edit={
            <div className="grid">
              {(["name", "email", "phone", "location"] as const).map((k) => (
                <label key={k}>
                  {BASIC_LABEL[k]}
                  <input value={b[k]} onChange={(e) => set({ basics: { ...b, [k]: e.target.value } })} />
                </label>
              ))}
            </div>
          }
        >
          <div className="section-line">{[b.email, b.phone, b.location].filter(Boolean).join(" · ")}</div>
        </Section>

        <Section id="summary" group="简介" title="Summary" editing={editing} onToggle={toggle} edit={<textarea rows={4} aria-label="Summary" value={parsed.summary} onChange={(e) => set({ summary: e.target.value })} />}>
          <Line text={parsed.summary} />
        </Section>

        <Section
          id="skills"
          group="技能"
          title={parsed.skills.join("、")}
          editing={editing}
          onToggle={toggle}
          edit={
            <label>
              逗号分隔
              <textarea rows={3} defaultValue={parsed.skills.join(", ")} onBlur={(e) => set({ skills: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
            </label>
          }
        />

        {parsed.experience.map((exp, i) => (
          <Section
            key={`exp-${i}`}
            id={`exp-${i}`}
            group="工作经历"
            title={[exp.title, exp.company].filter(Boolean).join(" · ")}
            editing={editing}
            onToggle={toggle}
            edit={
              <>
                <div className="grid">
                  {(["title", "company", "location", "start", "end"] as const).map((k) => (
                    <label key={k}>
                      {EXP_LABEL[k]}
                      <input value={exp[k]} onChange={(e) => set({ experience: parsed.experience.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)) })} />
                    </label>
                  ))}
                </div>
                <label>
                  Bullets（一行一条）
                  <textarea rows={Math.max(3, exp.bullets.length + 1)} defaultValue={exp.bullets.join("\n")} onBlur={(e) => set({ experience: parsed.experience.map((x, j) => (j === i ? { ...x, bullets: lines(e.target.value) } : x)) })} />
                </label>
                <div>
                  <button
                    type="button"
                    className="link danger"
                    onClick={() => {
                      set({ experience: parsed.experience.filter((_, j) => j !== i) });
                      setEditing(null);
                    }}
                  >
                    删除这段
                  </button>
                </div>
              </>
            }
          >
            <div className="section-line">{[exp.location, period(exp.start, exp.end)].filter(Boolean).join(" · ")}</div>
            {exp.bullets.map((t) => (
              <Line key={t} text={t} />
            ))}
          </Section>
        ))}
        <div className="section">
          <button
            type="button"
            className="link"
            onClick={() => {
              set({ experience: [...parsed.experience, { company: "", title: "", location: "", start: "", end: "", bullets: [] }] });
              setEditing(`exp-${parsed.experience.length}`);
            }}
          >
            + 新增经历
          </button>
        </div>

        {parsed.projects.map((p, i) => (
          <Section
            key={`proj-${i}`}
            id={`proj-${i}`}
            group="项目"
            title={[p.name, p.tech.join("、")].filter(Boolean).join(" · ")}
            editing={editing}
            onToggle={toggle}
            edit={
              <>
                <div className="grid">
                  <label>
                    名称
                    <input value={p.name} onChange={(e) => set({ projects: parsed.projects.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })} />
                  </label>
                  <label>
                    技术（逗号分隔）
                    <input
                      defaultValue={p.tech.join(", ")}
                      onBlur={(e) => set({ projects: parsed.projects.map((x, j) => (j === i ? { ...x, tech: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } : x)) })}
                    />
                  </label>
                </div>
                <label>
                  Bullets（一行一条）
                  <textarea rows={Math.max(3, p.bullets.length + 1)} defaultValue={p.bullets.join("\n")} onBlur={(e) => set({ projects: parsed.projects.map((x, j) => (j === i ? { ...x, bullets: lines(e.target.value) } : x)) })} />
                </label>
              </>
            }
          >
            {p.bullets.map((t) => (
              <Line key={t} text={t} />
            ))}
          </Section>
        ))}

        {parsed.education.map((ed, i) => (
          <Section
            key={`edu-${i}`}
            id={`edu-${i}`}
            group="学历"
            title={[[ed.degree, ed.field].filter(Boolean).join(" "), ed.school].filter(Boolean).join(" · ")}
            editing={editing}
            onToggle={toggle}
            edit={
              <div className="grid">
                {(["school", "degree", "field", "start", "end"] as const).map((k) => (
                  <label key={k}>
                    {EDU_LABEL[k]}
                    <input value={ed[k]} onChange={(e) => set({ education: parsed.education.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)) })} />
                  </label>
                ))}
              </div>
            }
          >
            <div className="section-line">{period(ed.start, ed.end)}</div>
          </Section>
        ))}
      </div>
    </section>
  );
}

function ReviewPanel({ resumeId }: { resumeId: string }) {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [ats, setAts] = useState<{ zh: string; en: string } | null>(null);
  const [role, setRole] = useState("");
  const [cat, setCat] = useState<Finding["category"] | null>(null);
  const [showPassed, setShowPassed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Review[]>(`/api/resumes/${resumeId}/reviews`).then(setReviews).catch((e) => setError(e.message));
    api.get<{ zh: string; en: string }>("/api/ats-explained").then(setAts).catch(() => undefined);
  }, [resumeId]);

  const runReview = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.post<Review>(`/api/resumes/${resumeId}/reviews`, { target_role: role || null });
      setReviews([r, ...reviews]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const latest = reviews[0];
  const match = (f: Finding) => !cat || f.category === cat;
  const issues = latest ? latest.findings.filter((f) => f.status !== "pass" && match(f)).sort((a, b) => b.points_lost - a.points_lost) : [];
  const passed = latest ? latest.findings.filter((f) => f.status === "pass" && match(f)) : [];
  const scores = latest
    ? ([
        ["parse", latest.parse_score],
        ["content", latest.content_score],
        ["keyword", latest.keyword_score],
      ] as const)
    : [];

  return (
    <section className="card flush">
      <div className="row" style={{ padding: "16px 24px" }}>
        <input aria-label="目标职位" placeholder="目标职位（留空则用求职需求的第一个）" value={role} onChange={(e) => setRole(e.target.value)} style={{ flex: "999 1 280px", minWidth: 0 }} />
        <button type="button" className="primary" onClick={runReview} disabled={busy} style={{ flex: "1 1 110px" }}>
          {busy ? <><Spinner />评分中…</> : "开始评分"}
        </button>
      </div>
      {error && <p className="error" style={{ margin: "0 24px 12px" }}>{error}</p>}

      {latest ? (
        <>
          <div className="score-tabs" role="tablist" aria-label="评分类别">
            {scores.map(([c, score]) => (
              <button key={c} type="button" role="tab" aria-selected={cat === c} className={`score-tab${cat === c ? " on" : ""}`} onClick={() => setCat(cat === c ? null : c)}>
                <span className="muted" style={{ display: "block" }}>
                  {CATEGORY_LABEL[c]}
                  {c === "keyword" && latest.target_role ? `（${latest.target_role}）` : ""}
                </span>
                <span className="stat-big">
                  {score ?? "—"}
                  {score != null && <span className="muted small"> / 100</span>}
                </span>
                <span className="muted small">{score == null ? "未检查" : `${latest.findings.filter((f) => f.category === c && f.status !== "pass").length} 项需要处理`}</span>
                <span className="muted small" style={{ display: "block", marginTop: 4, whiteSpace: "normal" }}>
                  {CATEGORY_HINT[c]}
                </span>
                <span className="score-tab-cta">{cat === c ? "✓ 正在只看这一类" : "只看这一类 →"}</span>
              </button>
            ))}
          </div>
          <div className="findings-head">
            <b>{cat ? `「${CATEGORY_LABEL[cat]}」的问题` : "全部问题"}</b>
            <span className="muted small">{issues.length} 项需要处理</span>
            {cat && (
              <button type="button" className="link" onClick={() => setCat(null)} style={{ marginLeft: "auto" }}>
                ← 显示全部
              </button>
            )}
          </div>
          <div style={{ padding: "4px 24px 8px" }}>
            {issues.map((f, i) => (
              <div className="finding" key={i}>
                <span className={`finding-status ${f.status}`}>{STATUS_LABEL[f.status]}</span>
                <span>
                  {f.message}
                  {f.evidence && <pre className="evidence">{f.evidence}</pre>}
                </span>
                <span className="finding-lost">{f.points_lost > 0 ? `−${f.points_lost}` : ""}</span>
              </div>
            ))}
            {issues.length === 0 && <p className="muted">这一类没有需要处理的项目。</p>}
            <button type="button" className="link" aria-expanded={showPassed} onClick={() => setShowPassed(!showPassed)} style={{ padding: 0 }}>
              {showPassed ? "▼" : "▶"} 已通过 {passed.length} 项
            </button>
            {showPassed &&
              passed.map((f, i) => (
                <div key={i} style={{ padding: "6px 0", color: "var(--plain-text)" }}>
                  {f.message}
                </div>
              ))}
            <p className="muted small">
              {new Date(latest.created_at).toLocaleString()} · 内容评分模型：{latest.model}
            </p>
          </div>
        </>
      ) : (
        <p className="muted" style={{ padding: "0 24px" }}>
          这个版本还没有评分。
        </p>
      )}

      {ats && (
        <div className="ats-note">
          <p>{ats.zh}</p>
          <p>{ats.en}</p>
        </div>
      )}
    </section>
  );
}

