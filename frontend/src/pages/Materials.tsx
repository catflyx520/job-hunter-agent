import { ClipboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, JobSummary, Material } from "../api";
import { Spinner } from "./ui";

const MAX_IMAGES = 6;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_TOTAL = 12 * 1024 * 1024;
const OK_TYPES = ["image/png", "image/jpeg", "image/webp"];
const KIND_LABEL = { cover_letter: "Cover letter", qa: "申请问答" };
const JD_SOURCE: Record<string, string> = { stored: "已存的完整 JD", url: "读取网址", pasted: "贴上的 JD", none: "没有 JD" };

export default function Materials() {
  const [params] = useSearchParams();
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [history, setHistory] = useState<Material[]>([]);
  const [current, setCurrent] = useState<Material | null>(null);

  const loadHistory = () => api.get<Material[]>("/api/materials").then(setHistory);
  useEffect(() => {
    api.get<JobSummary[]>("/api/jobs").then(setJobs);
    loadHistory();
  }, []);

  return (
    <>
      <h2>Cover letter 与申请问答</h2>
      <Generator
        jobs={jobs}
        initialJob={params.get("job") ?? ""}
        initialKind={(params.get("kind") as "cover_letter" | "qa") ?? "cover_letter"}
        onDone={(m) => {
          setCurrent(m);
          loadHistory();
        }}
      />
      {current && <Draft key={current.id} m={current} jobs={jobs} onSaved={(m) => (setCurrent(m), loadHistory())} />}
      <div className="card">
        <h3>历史草稿</h3>
        {history.length === 0 && <p className="muted">还没有草稿。</p>}
        <table>
          <tbody>
            {history.map((h) => (
              <tr key={h.id}>
                <td style={{ width: 110 }}>
                  <span className="badge">{KIND_LABEL[h.kind]}</span>
                </td>
                <td>
                  <a href="#" onClick={(e) => (e.preventDefault(), setCurrent(h), window.scrollTo({ top: 0, behavior: "smooth" }))}>
                    {h.question?.slice(0, 80) || jobs.find((j) => j.id === h.job_id)?.title || "（无标题）"}
                  </a>
                  {h.edited_text && <span className="muted">（已修改）</span>}
                  {h.status === "failed" && <span className="badge fail">失败</span>}
                </td>
                <td className="muted" style={{ width: 170 }}>
                  {new Date(h.created_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Generator({
  jobs,
  initialJob,
  initialKind,
  onDone,
}: {
  jobs: JobSummary[];
  initialJob: string;
  initialKind: "cover_letter" | "qa";
  onDone: (m: Material) => void;
}) {
  const [kind, setKind] = useState(initialKind);
  const [jobId, setJobId] = useState(initialJob);
  const [url, setUrl] = useState("");
  const [jd, setJd] = useState("");
  const [question, setQuestion] = useState("");
  const [requirements, setRequirements] = useState("");
  const [language, setLanguage] = useState<"en" | "zh">("en");
  const [images, setImages] = useState<File[]>([]);
  const [similar, setSimilar] = useState<Material[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const previews = useMemo(() => images.map((f) => URL.createObjectURL(f)), [images]);
  useEffect(() => () => previews.forEach((u) => URL.revokeObjectURL(u)), [previews]);

  // 题库：输入问题时找过往相似的答案
  useEffect(() => {
    if (kind !== "qa" || question.trim().length < 12) return setSimilar([]);
    const t = setTimeout(() => {
      api.get<Material[]>(`/api/materials/similar?q=${encodeURIComponent(question)}`).then(setSimilar).catch(() => undefined);
    }, 600);
    return () => clearTimeout(t);
  }, [question, kind]);

  const addImages = (files: File[]) => {
    setError("");
    const next = [...images];
    for (const f of files) {
      if (!OK_TYPES.includes(f.type)) return setError("只支援 PNG、JPG、WebP 截图（不接受 SVG、GIF、PDF）。");
      if (f.size > MAX_IMAGE_BYTES) return setError("每张图片最多 5MB。");
      next.push(f);
    }
    if (next.length > MAX_IMAGES) return setError(`最多 ${MAX_IMAGES} 张图片。`);
    if (next.reduce((s, f) => s + f.size, 0) > MAX_TOTAL) return setError("图片合计最多 12MB。");
    setImages(next);
  };

  const onPaste = (e: ClipboardEvent) => {
    const files = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith("image/"));
    if (files.length) {
      e.preventDefault();
      addImages(files.map((f, i) => new File([f], `paste-${Date.now()}-${i}.${f.type.split("/")[1]}`, { type: f.type })));
    }
  };

  const submit = async () => {
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("kind", kind);
    if (jobId) form.append("job_id", jobId);
    if (!jobId && url) form.append("url", url);
    if (!jobId && jd) form.append("jd_text", jd);
    if (question) form.append("question", question);
    if (requirements) form.append("requirements", requirements);
    form.append("language", language);
    images.forEach((f) => form.append("images", f));
    try {
      const m = await api.post<Material>("/api/materials", form);
      if (m.status === "failed") setError(`生成失败：${m.error}`);
      onDone(m);
      setImages([]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const canSubmit = kind === "qa" ? question.trim() || images.length : jobId || url.trim() || jd.trim();
  return (
    <div className="card" onPaste={onPaste}>
      <div className="row">
        {(["cover_letter", "qa"] as const).map((k) => (
          <label key={k} className="inline">
            <input type="radio" checked={kind === k} onChange={() => setKind(k)} />
            {KIND_LABEL[k]}
          </label>
        ))}
        <span className="muted">·</span>
        <label className="inline">
          语言
          <select value={language} onChange={(e) => setLanguage(e.target.value as "en" | "zh")}>
            <option value="en">English</option>
            <option value="zh">中文</option>
          </select>
        </label>
      </div>

      <label style={{ marginTop: 10 }}>
        职位
        <select value={jobId} onChange={(e) => setJobId(e.target.value)}>
          <option value="">（不选已存职位，改贴网址或 JD）</option>
          {jobs.map((j) => (
            <option key={j.id} value={j.id}>
              {j.title} — {j.company.display_name}
            </option>
          ))}
        </select>
      </label>
      {!jobId && (
        <div className="grid" style={{ marginTop: 8 }}>
          <label>
            职位网址
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
          </label>
          <label style={{ gridColumn: "1 / -1" }}>
            或贴上 JD
            <textarea rows={4} value={jd} onChange={(e) => setJd(e.target.value)} />
          </label>
        </div>
      )}

      {kind === "qa" && (
        <>
          <label style={{ marginTop: 10 }}>
            申请问题（可以只附截图、不打字；在此区块按 Ctrl+V 可贴上截图）
            <textarea rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} />
          </label>
          {similar.length > 0 && (
            <div className="notice" style={{ marginTop: 8 }}>
              题库里有相似的问题：
              {similar.map((s) => (
                <details key={s.id}>
                  <summary>{s.question}</summary>
                  <pre className="evidence">{s.edited_text || s.output_text}</pre>
                </details>
              ))}
            </div>
          )}
          <div className="row" style={{ marginTop: 8 }}>
            <button onClick={() => fileRef.current?.click()}>附上截图</button>
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              hidden
              onChange={(e) => {
                addImages(Array.from(e.target.files ?? []));
                e.target.value = "";
              }}
            />
            <span className="muted">PNG / JPG / WebP，最多 6 张，每张 5MB、合计 12MB；需要支援图片的模型。</span>
          </div>
          {images.length > 0 && (
            <div className="row" style={{ marginTop: 8 }}>
              {images.map((f, i) => (
                <div key={i} style={{ position: "relative" }}>
                  <img src={previews[i]} alt={f.name} style={{ height: 90, border: "1px solid var(--border)", borderRadius: 6 }} />
                  <button style={{ position: "absolute", top: 2, right: 2, padding: "0 6px" }} onClick={() => setImages(images.filter((_, j) => j !== i))}>
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      )}
      <label style={{ marginTop: 10 }}>
        字数 / 语气要求（选填）
        <input value={requirements} onChange={(e) => setRequirements(e.target.value)} placeholder="例如：150 字以内，语气自然" />
      </label>
      <p className="muted">只会使用你的履历与「已确认」的个人事实；缺少的事实会列在「需要确认」，不会猜。</p>
      <button className="primary" disabled={busy || !canSubmit} onClick={submit}>
        {busy ? <><Spinner />生成中…</> : "生成草稿"}
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function Draft({ m, jobs, onSaved }: { m: Material; jobs: JobSummary[]; onSaved: (m: Material) => void }) {
  const [text, setText] = useState(m.edited_text ?? m.output_text ?? "");
  const [msg, setMsg] = useState("");
  const [factKey, setFactKey] = useState("");
  const dirty = text !== (m.edited_text ?? m.output_text ?? "");
  const job = jobs.find((j) => j.id === m.job_id);

  if (m.status === "failed") {
    return (
      <div className="card">
        <h3>生成失败</h3>
        <p className="error">{m.error}</p>
      </div>
    );
  }

  const save = async () => onSaved(await api.patch<Material>(`/api/materials/${m.id}`, { edited_text: text }));
  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setMsg("已复制。");
  };
  const saveFact = async () => {
    try {
      await api.post("/api/facts", { key: factKey, question: m.question, value: text, source: "from_answer", confirm: true });
      setMsg(`已存进个人事实库（${factKey}），下次可直接使用。`);
      setFactKey("");
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>
          {KIND_LABEL[m.kind]}
          {job ? ` · ${job.title} — ${job.company.display_name}` : ""}
        </h3>
        <span className="muted">
          {JD_SOURCE[m.jd_source]} · {m.provider_kind}:{m.model}
        </span>
      </div>
      {m.question && <p className="muted">问题：{m.question}</p>}
      {m.images.length > 0 && (
        <div className="row">
          {m.images.map((img) => (
            <img key={img.position} src={`/api/materials/${m.id}/images/${img.position}`} alt={`截图 ${img.position}`} style={{ height: 70, borderRadius: 4 }} />
          ))}
        </div>
      )}
      {m.needs_confirmation && m.needs_confirmation.length > 0 && (
        <div className="notice" style={{ marginTop: 8 }}>
          <b>需要确认（{m.needs_confirmation.length}）</b>
          <ul>
            {m.needs_confirmation.map((n, i) => (
              <li key={i}>
                {n.item}：<span className="muted">{n.why}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <textarea rows={14} value={text} onChange={(e) => setText(e.target.value)} style={{ marginTop: 8 }} />
      <div className="row" style={{ marginTop: 8 }}>
        <button className="primary" disabled={!dirty} onClick={save}>
          保存修改
        </button>
        <button onClick={copy}>复制</button>
        <a href={`/api/materials/${m.id}/download`}>
          <button>下载 TXT</button>
        </a>
        {m.edited_text && (
          <button onClick={() => setText(m.output_text ?? "")} title="原始版本仍保留">
            还原成模型原稿
          </button>
        )}
      </div>
      {m.kind === "qa" && m.question && (
        <div className="row" style={{ marginTop: 8 }}>
          <input value={factKey} onChange={(e) => setFactKey(e.target.value)} placeholder="存进事实库的 key，例如 why_this_company" style={{ minWidth: 280 }} />
          <button disabled={!/^[a-z][a-z0-9_]{1,63}$/.test(factKey)} onClick={saveFact}>
            存进个人事实库
          </button>
        </div>
      )}
      {msg && <p className="notice">{msg}</p>}
      {m.citations && m.citations.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary className="muted">证据对照（{m.citations.filter((c) => c.supported).length} / {m.citations.length} 句有来源）</summary>
          <table>
            <tbody>
              {m.citations.map((c, i) => (
                <tr key={i}>
                  <td style={{ width: 60 }}>
                    <span className={`badge ${c.supported ? "pass" : "fail"}`}>{c.supported ? "有来源" : "无来源"}</span>
                  </td>
                  <td>
                    {c.sentence}
                    {c.chunk_ids.map((id) => (
                      <pre key={id} className="evidence">
                        履历：{m.evidence[id] ?? id}
                      </pre>
                    ))}
                    {c.fact_keys.map((k) => (
                      <pre key={k} className="evidence">
                        事实库：{k}
                      </pre>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}
