import { ClipboardEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { api, DEMO, Material } from "../api";
import { locale, t } from "../i18n";
import { Seg, Spinner } from "./ui";

export type MaterialKind = "cover_letter" | "qa";

const MAX_IMAGES = 6;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_TOTAL = 12 * 1024 * 1024;
const OK_TYPES = ["image/png", "image/jpeg", "image/webp"];
export const KIND_LABEL: Record<MaterialKind, string> = { cover_letter: "Cover letter", qa: t("申请问答") };
const JD_SOURCE: Record<string, string> = { stored: t("已存的完整 JD"), url: t("读取网址"), pasted: t("贴上的 JD"), none: t("没有 JD") };

/** 职位详情页的「申请材料」：为这个职位写 cover letter 或回答申请问题，下面列出这个职位的草稿。 */
export function JobMaterials({ jobId, initialKind, hasJd }: { jobId: string; initialKind: MaterialKind; hasJd: boolean }) {
  const [kind, setKind] = useState<MaterialKind>(initialKind);
  const [drafts, setDrafts] = useState<Material[] | null>(null);
  const [current, setCurrent] = useState<Material | null>(null);

  const load = () => api.get<Material[]>(`/api/materials?job_id=${jobId}`).then(setDrafts);
  useEffect(() => {
    load().catch(() => setDrafts([]));
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setKind(initialKind), [initialKind]);

  const mine = (drafts ?? []).filter((d) => d.kind === kind);
  return (
    <section className="card" id="materials" aria-label={t("申请材料")}>
      <div className="row between">
        <h3 style={{ margin: 0 }}>{t("申请材料")}</h3>
        <Seg<MaterialKind>
          label={t("材料类型")}
          value={kind}
          onChange={(k) => {
            setKind(k);
            setCurrent(null);
          }}
          options={[
            { value: "cover_letter", label: KIND_LABEL.cover_letter },
            { value: "qa", label: KIND_LABEL.qa },
          ]}
        />
      </div>
      <Generator
        key={kind}
        jobId={jobId}
        kind={kind}
        hasJd={hasJd}
        onDone={(m) => {
          setCurrent(m);
          load();
        }}
      />
      {current && <DraftView key={current.id} m={current} onSaved={(m) => (setCurrent(m), load())} />}
      <h4 style={{ marginBottom: 4 }}>{t("这个职位的{kind}草稿", { kind: KIND_LABEL[kind] })}</h4>
      {drafts === null ? (
        <p className="muted loading-line">
          <Spinner />
          {t("读取中…")}
        </p>
      ) : mine.length === 0 ? (
        <p className="muted">{t("还没有草稿。")}</p>
      ) : (
        <DraftList items={mine} activeId={current?.id} onPick={setCurrent} />
      )}
    </section>
  );
}

/** 草稿清单（职位详情页与材料历史共用）。 */
export function DraftList({
  items,
  activeId,
  onPick,
  jobTitle,
}: {
  items: Material[];
  activeId?: string;
  onPick: (m: Material) => void;
  jobTitle?: (m: Material) => string | undefined;
}) {
  return (
    <table>
      <tbody>
        {items.map((h) => (
          <tr key={h.id} className={h.id === activeId ? "on" : undefined}>
            <td style={{ width: 120 }}>
              <span className="badge">{KIND_LABEL[h.kind]}</span>
            </td>
            <td>
              <button type="button" className="link" style={{ padding: 0, textAlign: "left" }} onClick={() => onPick(h)}>
                {h.question?.slice(0, 80) || jobTitle?.(h) || t("（无标题）")}
              </button>
              {h.edited_text && <span className="muted"> {t("（已修改）")}</span>}
              {h.status === "failed" && <span className="badge fail"> {t("失败")}</span>}
            </td>
            <td className="muted" style={{ width: 180 }}>
              {new Date(h.created_at).toLocaleString(locale)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Generator({ jobId, kind, hasJd, onDone }: { jobId: string; kind: MaterialKind; hasJd: boolean; onDone: (m: Material) => void }) {
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

  // 输入问题时找过往相似的答案
  useEffect(() => {
    if (kind !== "qa" || question.trim().length < 12) return setSimilar([]);
    const timer = setTimeout(() => {
      api.get<Material[]>(`/api/materials/similar?q=${encodeURIComponent(question)}`).then(setSimilar).catch(() => undefined);
    }, 600);
    return () => clearTimeout(timer);
  }, [question, kind]);

  const addImages = (files: File[]) => {
    setError("");
    const next = [...images];
    for (const f of files) {
      if (!OK_TYPES.includes(f.type)) return setError(t("只支援 PNG、JPG、WebP 截图（不接受 SVG、GIF、PDF）。"));
      if (f.size > MAX_IMAGE_BYTES) return setError(t("每张图片最多 5MB。"));
      next.push(f);
    }
    if (next.length > MAX_IMAGES) return setError(t("最多 {n} 张图片。", { n: MAX_IMAGES }));
    if (next.reduce((s, f) => s + f.size, 0) > MAX_TOTAL) return setError(t("图片合计最多 12MB。"));
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
    form.append("job_id", jobId);
    if (!hasJd && jd.trim()) form.append("jd_text", jd);
    if (question) form.append("question", question);
    if (requirements) form.append("requirements", requirements);
    form.append("language", language);
    images.forEach((f) => form.append("images", f));
    try {
      const m = await api.post<Material>("/api/materials", form);
      if (m.status === "failed") setError(t("生成失败：{error}", { error: m.error }));
      onDone(m);
      setImages([]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const canSubmit = kind === "qa" ? question.trim() || images.length : hasJd || jd.trim();
  return (
    <div onPaste={onPaste} style={{ marginTop: 12 }}>
      {!hasJd && (
        <label style={{ marginBottom: 10 }}>
          {t("这个职位没有存 JD，请贴上 JD 全文")}
          <textarea rows={5} value={jd} onChange={(e) => setJd(e.target.value)} />
        </label>
      )}
      {kind === "qa" && (
        <>
          <label>
            {t("申请问题（可以只附截图、不打字；在此区块按 Ctrl+V 可贴上截图）")}
            <textarea rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} />
          </label>
          {similar.length > 0 && (
            <div className="notice" style={{ marginTop: 8 }}>
              {t("以前回答过相似的问题：")}
              {similar.map((s) => (
                <details key={s.id}>
                  <summary>{s.question}</summary>
                  <pre className="evidence">{s.edited_text || s.output_text}</pre>
                </details>
              ))}
            </div>
          )}
          <div className="row" style={{ marginTop: 8 }}>
            <button type="button" onClick={() => fileRef.current?.click()}>
              {t("附上截图")}
            </button>
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
            <span className="muted small">{t("PNG / JPG / WebP，最多 6 张，每张 5MB、合计 12MB；需要支援图片的模型。")}</span>
          </div>
          {images.length > 0 && (
            <div className="row" style={{ marginTop: 8 }}>
              {images.map((f, i) => (
                <div key={i} style={{ position: "relative" }}>
                  <img src={previews[i]} alt={f.name} style={{ height: 90, border: "1px solid var(--border)" }} />
                  <button
                    type="button"
                    aria-label={t("移除")}
                    style={{ position: "absolute", top: 2, right: 2, minHeight: 0, padding: "0 6px" }}
                    onClick={() => setImages(images.filter((_, j) => j !== i))}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      )}
      <div className="grid" style={{ marginTop: 10 }}>
        <label>
          {t("字数 / 语气要求（选填）")}
          <input value={requirements} onChange={(e) => setRequirements(e.target.value)} placeholder={t("例如：150 字以内，语气自然")} />
        </label>
        <label>
          {t("草稿语言")}
          <select value={language} onChange={(e) => setLanguage(e.target.value as "en" | "zh")}>
            <option value="en">English</option>
            <option value="zh">中文</option>
          </select>
        </label>
      </div>
      <p className="muted small">{t("只会使用这个职位的 JD 和你的履历；履历里没有的事实会列在「需要确认」，不会猜。")}</p>
      <button type="button" className="primary" disabled={busy || !canSubmit} onClick={submit}>
        {busy ? (
          <>
            <Spinner />
            {t("生成中…")}
          </>
        ) : (
          t("生成草稿")
        )}
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

/** 一份草稿：需要确认的事项、可编辑的内容、复制 / 下载、证据对照。 */
export function DraftView({ m, onSaved, header }: { m: Material; onSaved: (m: Material) => void; header?: ReactNode }) {
  const [text, setText] = useState(m.edited_text ?? m.output_text ?? "");
  const [msg, setMsg] = useState("");
  const dirty = text !== (m.edited_text ?? m.output_text ?? "");

  if (m.status === "failed") {
    return (
      <div className="draft">
        {header}
        <h4>{t("生成失败")}</h4>
        <p className="error">{m.error}</p>
      </div>
    );
  }

  const save = async () => onSaved(await api.patch<Material>(`/api/materials/${m.id}`, { edited_text: text }));
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setMsg(t("已复制。"));
    } catch {
      setMsg(t("浏览器不允许复制，请手动选取文字。"));
    }
  };

  return (
    <div className="draft">
      {header}
      <div className="row between">
        <b>{KIND_LABEL[m.kind]}</b>
        <span className="muted small">
          {JD_SOURCE[m.jd_source]} · {m.provider_kind}:{m.model} · {new Date(m.created_at).toLocaleString(locale)}
        </span>
      </div>
      {m.question && <p className="muted">{t("问题：{q}", { q: m.question })}</p>}
      {m.images.length > 0 && (
        <div className="row">
          {m.images.map((img) => (
            <img key={img.position} src={`/api/materials/${m.id}/images/${img.position}`} alt={t("截图 {n}", { n: img.position })} style={{ height: 70 }} />
          ))}
        </div>
      )}
      {m.needs_confirmation && m.needs_confirmation.length > 0 && (
        <div className="notice" style={{ marginTop: 8 }}>
          <b>{t("需要确认（{n}）", { n: m.needs_confirmation.length })}</b>
          <ul>
            {m.needs_confirmation.map((n, i) => (
              <li key={i}>
                {n.item}: <span className="muted">{n.why}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <textarea aria-label={t("草稿内容")} rows={14} value={text} onChange={(e) => setText(e.target.value)} style={{ marginTop: 8 }} />
      <div className="row" style={{ marginTop: 8 }}>
        <button type="button" className="primary" disabled={!dirty} onClick={save}>
          {t("保存修改")}
        </button>
        <button type="button" onClick={copy}>
          {t("复制")}
        </button>
        {!DEMO && (
          <a className="btn" href={`/api/materials/${m.id}/download`}>
            {t("下载 TXT")}
          </a>
        )}
        {m.edited_text && (
          <button type="button" onClick={() => setText(m.output_text ?? "")} title={t("原始版本仍保留")}>
            {t("还原成模型原稿")}
          </button>
        )}
      </div>
      {msg && <p className="notice">{msg}</p>}
      {m.citations && m.citations.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary className="muted">{t("证据对照（{ok} / {n} 句有来源）", { ok: m.citations.filter((c) => c.supported).length, n: m.citations.length })}</summary>
          <table>
            <tbody>
              {m.citations.map((c, i) => (
                <tr key={i}>
                  <td style={{ width: 70 }}>
                    <span className={`badge ${c.supported ? "pass" : "fail"}`}>{c.supported ? t("有来源") : t("无来源")}</span>
                  </td>
                  <td>
                    {c.sentence}
                    {c.chunk_ids.map((id) => (
                      <pre key={id} className="evidence">
                        {t("履历：{text}", { text: m.evidence[id] ?? id })}
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
