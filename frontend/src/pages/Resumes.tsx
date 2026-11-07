import { useEffect, useState } from "react";
import { api, Finding, ParsedResume, Resume, Review, UploadResult } from "../api";

const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

export default function Resumes() {
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = () =>
    api
      .get<Resume[]>("/api/resumes")
      .then((rs) => {
        setResumes(rs);
        setSelected((cur) => cur ?? rs.find((r) => r.is_active)?.id ?? rs[0]?.id ?? null);
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  return (
    <>
      <h2>履历与评分</h2>
      {error && <p className="error">{error}</p>}
      <Upload
        onUploaded={(r) => {
          setSelected(r.resume.id);
          load();
        }}
      />
      {resumes.length > 0 && (
        <div className="card">
          <h3>版本</h3>
          <table>
            <tbody>
              {resumes.map((r) => (
                <tr key={r.id} style={{ fontWeight: r.id === selected ? 600 : undefined }}>
                  <td>
                    <a href="#" onClick={(e) => (e.preventDefault(), setSelected(r.id))}>
                      {r.label}
                    </a>
                    {r.is_active && <span className="badge pass" style={{ marginLeft: 6 }}>使用中</span>}
                  </td>
                  <td className="muted">{r.filename}</td>
                  <td className="muted">{new Date(r.created_at).toLocaleString()}</td>
                  <td className="muted">SHA-256 {r.sha256.slice(0, 10)}…</td>
                  <td>
                    {!r.is_active && (
                      <button onClick={() => api.post(`/api/resumes/${r.id}/activate`).then(load)}>设为使用中</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {selected && <ResumeDetail key={selected} id={selected} onChanged={load} onDeleted={() => (setSelected(null), load())} />}
    </>
  );
}

function Upload({ onUploaded }: { onUploaded: (r: UploadResult) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<UploadResult | null>(null);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("file", file);
    form.append("label", label);
    try {
      const r = await api.post<UploadResult>("/api/resumes", form);
      setResult(r);
      onUploaded(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h3>上传履历</h3>
      <div className="row">
        <input type="file" accept=".pdf,.docx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <input placeholder="版本名称，例如「Full-stack 版」" value={label} onChange={(e) => setLabel(e.target.value)} />
        <button className="primary" onClick={submit} disabled={!file || busy}>
          {busy ? "上传并结构化中…" : "上传"}
        </button>
      </div>
      <p className="muted">支援 PDF、DOCX。档案只存在本机 data/ 目录。</p>
      {error && <p className="error">{error}</p>}
      {result?.parse_error && <p className="error">{result.parse_error}</p>}
      {result && result.unverified_items.length > 0 && (
        <div className="notice">
          以下内容在原文里找不到完全相同的文字，可能被模型改写，请在下方确认或修正：
          <ul>
            {result.unverified_items.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ResumeDetail({ id, onChanged, onDeleted }: { id: string; onChanged: () => void; onDeleted: () => void }) {
  const [resume, setResume] = useState<Resume | null>(null);
  const [parsed, setParsed] = useState<ParsedResume | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [ver, setVer] = useState(0); // 重新载入时让未受控的 textarea 重建

  const load = () =>
    api.get<Resume>(`/api/resumes/${id}`).then((r) => {
      setResume(r);
      setParsed(r.parsed);
      setVer((v) => v + 1);
    });
  useEffect(() => {
    load();
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!resume || !parsed) return null;

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

  const save = () =>
    run("save", async () => {
      await api.put(`/api/resumes/${id}/parsed`, { parsed, confirm: true });
      const c = await api.post<{ chunk_count: number; error: string | null }>(`/api/resumes/${id}/chunks`);
      setMsg(
        c.error
          ? `已确认。检索资料未建立：${c.error}`
          : `已确认，并建立 ${c.chunk_count} 个检索切块。`,
      );
      await load();
      onChanged();
    });

  const reparse = () =>
    run("reparse", async () => {
      const r = await api.post<UploadResult>(`/api/resumes/${id}/parse`);
      setParsed(r.resume.parsed);
      setMsg(r.unverified_items.length ? `重新结构化完成；${r.unverified_items.length} 项在原文找不到，请检查。` : "重新结构化完成，请检查后确认。");
      await load();
    });

  const remove = () =>
    run("delete", async () => {
      if (!confirm(`删除「${resume.label}」？档案与评分记录会一起删除。`)) return;
      await api.del(`/api/resumes/${id}`);
      onDeleted();
    });

  const set = (patch: Partial<ParsedResume>) => setParsed({ ...parsed, ...patch });

  return (
    <>
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>结构化履历：{resume.label}</h3>
          <span className="muted">
            {resume.parsed_confirmed_at ? `已确认 · ${resume.chunk_count} 个检索切块` : "尚未确认"}
          </span>
        </div>
        <p className="muted">请检查模型抽出的内容。生成 cover letter 与问答时只会使用这里确认过的经历。</p>

        <h4>基本信息</h4>
        <div className="grid">
          {(["name", "email", "phone", "location"] as const).map((k) => (
            <label key={k}>
              {k}
              <input value={parsed.basics[k]} onChange={(e) => set({ basics: { ...parsed.basics, [k]: e.target.value } })} />
            </label>
          ))}
        </div>

        <h4>Summary</h4>
        <textarea value={parsed.summary} onChange={(e) => set({ summary: e.target.value })} />

        <h4>技能（逗号分隔）</h4>
        <textarea
          value={parsed.skills.join(", ")}
          onChange={(e) => set({ skills: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
        />

        <div key={ver}>
        <h4>工作经历</h4>
        {parsed.experience.map((exp, i) => (
          <div key={i} className="card">
            <div className="grid">
              {(["title", "company", "location", "start", "end"] as const).map((k) => (
                <label key={k}>
                  {k}
                  <input
                    value={exp[k]}
                    onChange={(e) =>
                      set({ experience: parsed.experience.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)) })
                    }
                  />
                </label>
              ))}
            </div>
            <label>
              Bullets（一行一条）
              <textarea
                rows={Math.max(3, exp.bullets.length + 1)}
                defaultValue={exp.bullets.join("\n")}
                onBlur={(e) =>
                  set({ experience: parsed.experience.map((x, j) => (j === i ? { ...x, bullets: lines(e.target.value) } : x)) })
                }
              />
            </label>
            <button onClick={() => set({ experience: parsed.experience.filter((_, j) => j !== i) })}>删除这段</button>
          </div>
        ))}
        <button
          onClick={() =>
            set({ experience: [...parsed.experience, { company: "", title: "", location: "", start: "", end: "", bullets: [] }] })
          }
        >
          新增经历
        </button>

        <h4>项目</h4>
        {parsed.projects.map((p, i) => (
          <div key={i} className="card">
            <div className="grid">
              <label>
                名称
                <input
                  value={p.name}
                  onChange={(e) => set({ projects: parsed.projects.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })}
                />
              </label>
              <label>
                技术（逗号分隔）
                <input
                  value={p.tech.join(", ")}
                  onChange={(e) =>
                    set({
                      projects: parsed.projects.map((x, j) =>
                        j === i ? { ...x, tech: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } : x,
                      ),
                    })
                  }
                />
              </label>
            </div>
            <label>
              Bullets（一行一条）
              <textarea
                defaultValue={p.bullets.join("\n")}
                onBlur={(e) =>
                  set({ projects: parsed.projects.map((x, j) => (j === i ? { ...x, bullets: lines(e.target.value) } : x)) })
                }
              />
            </label>
          </div>
        ))}

        </div>
        <h4>学历</h4>
        {parsed.education.map((ed, i) => (
          <div key={i} className="grid" style={{ marginBottom: 8 }}>
            {(["school", "degree", "field", "start", "end"] as const).map((k) => (
              <label key={k}>
                {k}
                <input
                  value={ed[k]}
                  onChange={(e) =>
                    set({ education: parsed.education.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)) })
                  }
                />
              </label>
            ))}
          </div>
        ))}

        <div className="row" style={{ marginTop: 12 }}>
          <button className="primary" onClick={save} disabled={!!busy}>
            {busy === "save" ? "保存中…" : "确认并保存"}
          </button>
          <button onClick={reparse} disabled={!!busy}>
            {busy === "reparse" ? "结构化中…" : "重新结构化"}
          </button>
          <button onClick={remove} disabled={!!busy}>
            删除这个版本
          </button>
        </div>
        {msg && <p className="notice">{msg}</p>}
        {error && <p className="error">{error}</p>}
      </div>
      <ReviewPanel resumeId={id} />
    </>
  );
}

const CATEGORY_LABEL: Record<Finding["category"], string> = {
  parse: "可解析度",
  content: "内容品质",
  keyword: "关键词覆盖",
};
const STATUS_LABEL = { pass: "通过", warn: "注意", fail: "未通过" };

function ReviewPanel({ resumeId }: { resumeId: string }) {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [ats, setAts] = useState<{ zh: string; en: string } | null>(null);
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Review[]>(`/api/resumes/${resumeId}/reviews`).then(setReviews);
    api.get<{ zh: string; en: string }>("/api/ats-explained").then(setAts);
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
  return (
    <div className="card">
      <h3>履历评分</h3>
      {ats && (
        <div className="notice">
          <p style={{ marginTop: 0 }}>{ats.zh}</p>
          <p style={{ marginBottom: 0 }} className="muted">
            {ats.en}
          </p>
        </div>
      )}
      <div className="row" style={{ marginTop: 12 }}>
        <input
          placeholder="目标职位（留空则用求职需求的第一个）"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          style={{ minWidth: 300 }}
        />
        <button className="primary" onClick={runReview} disabled={busy}>
          {busy ? "评分中…" : "开始评分"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {latest && (
        <>
          <div className="scores" style={{ marginTop: 16 }}>
            <div className="score card">
              <b>{latest.parse_score}</b>可解析度
            </div>
            <div className="score card">
              <b>{latest.content_score}</b>内容品质
            </div>
            <div className="score card">
              <b>{latest.keyword_score ?? "—"}</b>关键词覆盖{latest.target_role ? `（${latest.target_role}）` : "（未检查）"}
            </div>
          </div>
          <p className="muted">
            {new Date(latest.created_at).toLocaleString()} · 内容评分模型：{latest.model}
          </p>
          {(["parse", "content", "keyword"] as const).map((cat) => (
            <div key={cat}>
              <h4>{CATEGORY_LABEL[cat]}</h4>
              <table>
                <tbody>
                  {latest.findings
                    .filter((f) => f.category === cat)
                    .map((f, i) => (
                      <tr key={i}>
                        <td style={{ width: 70 }}>
                          <span className={`badge ${f.status}`}>{STATUS_LABEL[f.status]}</span>
                        </td>
                        <td>
                          {f.message}
                          {f.evidence && <pre className="evidence">{f.evidence}</pre>}
                        </td>
                        <td style={{ width: 60 }} className="muted">
                          {f.points_lost > 0 ? `-${f.points_lost}` : ""}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
