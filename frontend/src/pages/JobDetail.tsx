import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, JobDetail as Job, SponsorStatus } from "../api";
import {
  EMPLOYMENT,
  PROGRAM,
  RECOMMENDATION,
  SPONSOR_STATUS,
  SPONSORSHIP,
  VERIFICATION,
  WORK_MODE,
  salary,
  show,
  yesNo,
} from "./labels";

const PART_LABEL = { role: "职位 / 产品内容", tech: "技术栈", experience: "年资与范围", location: "地点与工作方式", recency: "新鲜度与可信度" };
const SEVERITY = { low: "低", medium: "中", high: "高" };

export default function JobDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const notes = (useLocation().state as { notes?: string[] } | null)?.notes;
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () => api.get<Job>(`/api/jobs/${id}`).then(setJob).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!job) return error ? <p className="error">{error}</p> : null;

  const rescore = async () => {
    setBusy(true);
    setError("");
    try {
      setJob(await api.post<Job>(`/api/jobs/${job.id}/match`));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!confirm(`删除「${job.title}」？`)) return;
    await api.del(`/api/jobs/${job.id}`);
    nav("/jobs");
  };

  const m = job.match;
  const sp = SPONSORSHIP[job.sponsorship_policy];
  return (
    <>
      <p>
        <Link to="/jobs">← 职位列表</Link>
      </p>
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h2 style={{ marginBottom: 4 }}>{job.title}</h2>
            <div className="muted">
              {job.company.display_name}
              {job.company.is_staffing_agency && "（猎头 / 人力公司）"} · {show(job.location_text)} · {WORK_MODE[job.work_mode]} ·{" "}
              {EMPLOYMENT[job.employment_type]} · {salary(job.salary_min, job.salary_max, job.salary_period)}
            </div>
          </div>
          <div className="row">
            <button className="primary" onClick={() => nav(`/materials?job=${job.id}&kind=cover_letter`)}>
              生成 Cover Letter
            </button>
            <button className="primary" onClick={() => nav(`/materials?job=${job.id}&kind=qa`)}>
              申请问答
            </button>
          </div>
        </div>
        {notes && notes.length > 0 && (
          <ul className="notice">
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
        <div className="grid" style={{ marginTop: 12 }}>
          <Field label="资历" value={show(job.seniority === "unknown" ? null : job.seniority)} />
          <Field label="发布时间" value={show(job.posted_text)} />
          <Field label="职位编号" value={show(job.requisition_id)} />
          <Field label="资料来源" value={job.verification_source ? VERIFICATION[job.verification_source] : "未知"} />
          <Field label="只收 New Grad" value={yesNo(job.new_grad_only)} />
          <Field label="要求公民 / 绿卡身份" value={yesNo(job.citizenship_required)} />
          <Field label="Easy Apply" value={yesNo(job.easy_apply)} />
          <Field label="状态" value={job.status === "unverified" ? "未在官网核实是否仍在招聘" : job.status} />
        </div>
        <p>
          <span className={`badge ${sp.cls}`}>{sp.text}</span>
          {job.sponsorship_evidence && <span className="muted"> JD 原文：「{job.sponsorship_evidence}」</span>}
        </p>
        <div className="row">
          {job.apply_url && (
            <a href={job.apply_url} target="_blank" rel="noopener noreferrer">
              申请页面 ↗
            </a>
          )}
          {job.sources.map((s) => (
            <a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer" className="muted">
              来源：{s.site_id} ↗
            </a>
          ))}
          <button onClick={remove}>删除职位</button>
        </div>
        <p className="muted">投递请自己到申请页面完成；本工具不会代你投递。</p>
      </div>

      {(job.exclusion.reasons.length > 0 || job.exclusion.flags.length > 0) && (
        <div className="card">
          <h3>硬性排除</h3>
          {job.exclusion.reasons.map((r) => (
            <p key={r.code}>
              <span className="badge fail">排除</span> {r.label}
            </p>
          ))}
          {job.exclusion.flags.map((f) => (
            <p key={f.code}>
              <span className="badge warn">注意</span> {f.label}
            </p>
          ))}
          <p className="muted">排除依据你的「求职需求」；被排除的职位仍保留，你可以自己判断。</p>
        </div>
      )}

      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>匹配评分</h3>
          <button onClick={rescore} disabled={busy}>
            {busy ? "评分中…" : m ? "重新评分" : "开始评分"}
          </button>
        </div>
        {error && <p className="error">{error}</p>}
        {!m && !error && <p className="muted">尚未评分。</p>}
        {m && (
          <>
            <div className="row" style={{ marginTop: 12 }}>
              <span style={{ fontSize: 36, fontWeight: 700 }}>{m.score}</span>
              <span className="muted">/ 100</span>
              <span className={`badge ${RECOMMENDATION[m.recommendation].cls}`}>{RECOMMENDATION[m.recommendation].text}</span>
              <span className="muted">分数是「契合度估计」，不是录取概率。</span>
            </div>
            <table style={{ marginTop: 8 }}>
              <tbody>
                {(Object.keys(PART_LABEL) as (keyof typeof PART_LABEL)[]).map((k) => (
                  <tr key={k}>
                    <td style={{ width: 140 }}>{PART_LABEL[k]}</td>
                    <td style={{ width: 70 }}>
                      {m.breakdown[k].score} / {m.breakdown[k].max}
                    </td>
                    <td className="muted">{m.breakdown[k].reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h4>匹配理由</h4>
            {m.reasons.length === 0 && <p className="muted">没有可以引用履历证据的理由。</p>}
            {m.reasons.map((r, i) => (
              <div key={i} style={{ marginBottom: 8 }}>
                ✓ {r.text}
                {r.chunk_ids.map((c) => (
                  <pre key={c} className="evidence">
                    履历证据：{job.evidence[c] ?? c}
                  </pre>
                ))}
              </div>
            ))}
            <h4>缺口与风险</h4>
            {m.gaps.length === 0 && <p className="muted">无。</p>}
            {m.gaps.map((g, i) => (
              <p key={i}>
                <span className={`badge ${g.severity === "high" ? "fail" : "warn"}`}>{SEVERITY[g.severity]}</span> {g.text}
              </p>
            ))}
            <p className="muted">
              {new Date(m.created_at).toLocaleString()} · {m.model} · 求职需求第 {m.preferences_version} 版
            </p>
          </>
        )}
      </div>

      <SponsorPanel
        job={job}
        onChange={(s) => {
          setJob({ ...job, sponsor: s, sponsor_status: s.status });
          load();
        }}
      />

      <details className="card">
        <summary>JD 全文</summary>
        <pre style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{job.jd_text}</pre>
      </details>
    </>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="muted">{label}</div>
      <div>{value}</div>
    </div>
  );
}

function SponsorPanel({ job, onChange }: { job: Job; onChange: (s: SponsorStatus) => void }) {
  const s = job.sponsor;
  const [website, setWebsite] = useState(job.company.website ?? "");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const act = async (name: string, fn: () => Promise<void>) => {
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

  const cid = job.company.id;
  const st = s ? SPONSOR_STATUS[s.status] : null;
  return (
    <div className="card">
      <h3>公司 H-1B / 绿卡历史</h3>
      {s && st && (
        <>
          <p>
            <span className={`badge ${st.cls}`}>{st.text}</span> <span className="muted">{st.desc}</span>
          </p>
          {s.summary.reason && <p>{s.summary.reason}</p>}
          {Object.entries(s.summary.programs).map(([prog, years]) => (
            <div key={prog}>
              <h4>{PROGRAM[prog] ?? prog}</h4>
              <table>
                <thead>
                  <tr>
                    <th>财年</th>
                    <th>{prog === "uscis_h1b" ? "批准 + 拒绝" : "申请件数"}</th>
                    <th>{prog === "uscis_h1b" ? "批准" : "核准"}</th>
                    <th>拒绝</th>
                  </tr>
                </thead>
                <tbody>
                  {years.map((y) => (
                    <tr key={y.fiscal_year}>
                      <td>FY{y.fiscal_year}</td>
                      <td>{y.filed}</td>
                      <td>{y.certified_or_approved}</td>
                      <td>{y.denied}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          {s.summary.entities.length > 0 && (
            <p className="muted">
              已确认的实体：
              {s.summary.entities.map((e) => `${e.name}（${e.method === "exact" ? "名称完全相同" : e.method === "user" ? "你指定" : "你已确认"}）`).join("、")}
            </p>
          )}
          {s.summary.pending.length > 0 && (
            <>
              <h4>待你确认的比对</h4>
              <table>
                <tbody>
                  {s.summary.pending.map((p) => (
                    <tr key={p.alias_id}>
                      <td>
                        <b>{p.name}</b>
                        <div className="muted">
                          {[p.city, p.state].filter(Boolean).join(", ") || "地点未知"} · 信心 {Math.round(p.confidence * 100)}% ·{" "}
                          {p.method === "llm_suggested" ? "AI 从官网推测" : "名称相似"}
                        </div>
                        {p.note && <div className="muted">{p.note}</div>}
                        {p.evidence_url && (
                          <a href={p.evidence_url} target="_blank" rel="noopener noreferrer">
                            来源 ↗
                          </a>
                        )}
                      </td>
                      <td style={{ width: 170 }}>
                        <div className="row">
                          <button
                            className="primary"
                            disabled={!!busy}
                            onClick={() => act("alias", async () => onChange(await api.post<SponsorStatus>(`/api/sponsor/aliases/${p.alias_id}`, { status: "confirmed" })))}
                          >
                            是同一家
                          </button>
                          <button
                            disabled={!!busy}
                            onClick={() => act("alias", async () => onChange(await api.post<SponsorStatus>(`/api/sponsor/aliases/${p.alias_id}`, { status: "rejected" })))}
                          >
                            不是
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <p className="muted">
            资料范围：
            {Object.keys(s.coverage.programs).length
              ? Object.entries(s.coverage.programs)
                  .map(([p, ys]) => `${PROGRAM[p] ?? p} FY${ys.join("、FY")}`)
                  .join("；")
              : "未导入"}
          </p>
          <ul className="muted">
            {s.summary.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </>
      )}
      <div className="row">
        <input value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="公司官网，例如 https://example.com" style={{ minWidth: 280 }} />
        <button
          disabled={!!busy}
          onClick={() =>
            act("site", async () => {
              onChange(await api.patch<SponsorStatus>(`/api/companies/${cid}`, { website }));
              setMsg("已保存官网。");
            })
          }
        >
          保存官网
        </button>
        <button
          disabled={!!busy || !website.trim() || s?.status === "not_checked"}
          onClick={() =>
            act("entity", async () => {
              await api.patch(`/api/companies/${cid}`, { website });
              const r = await api.post<{ legal_name: string; source_url: string; suggested: string[]; sponsor: SponsorStatus }>(
                `/api/companies/${cid}/sponsor/suggest-entity`,
              );
              onChange(r.sponsor);
              setMsg(
                `官网写明的法律实体：${r.legal_name}。` +
                  (r.suggested.length ? `找到 ${r.suggested.length} 个可能的官方记录，请在上方确认。` : "官方资料里没有相近的名称。"),
              );
            })
          }
        >
          {busy === "entity" ? "推测中…" : "AI 从官网推测法律实体"}
        </button>
        <label className="inline">
          <input
            type="checkbox"
            checked={job.company.is_staffing_agency}
            onChange={(e) => act("agency", async () => onChange(await api.patch<SponsorStatus>(`/api/companies/${cid}`, { is_staffing_agency: e.target.checked })))}
          />
          这是猎头 / 人力公司
        </label>
      </div>
      {msg && <p className="notice">{msg}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
