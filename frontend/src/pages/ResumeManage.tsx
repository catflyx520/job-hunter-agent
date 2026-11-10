import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, Resume, UploadResult } from "../api";
import ResumeTabs from "./ResumeTabs";
import { ConfirmButton, Spinner } from "./ui";
import { locale, t } from "../i18n";

/** 「版本管理」分页：上传历史、使用中的版本、改名、设为使用中、重新结构化、删除。 */
export default function ResumeVersions() {
  const [resumes, setResumes] = useState<Resume[] | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState<string | null>(null); // `${动作}:${id}`

  const load = () =>
    api
      .get<Resume[]>("/api/resumes")
      .then(setResumes)
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const act = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError("");
    setMsg("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const activate = (r: Resume) =>
    act(`activate:${r.id}`, async () => {
      await api.post(`/api/resumes/${r.id}/activate`);
      setMsg(t("已把「{label}」设为使用中。搜索职位、匹配评分和生成材料都会用这个版本。", { label: r.label }));
    });

  const reparse = (r: Resume) =>
    act(`reparse:${r.id}`, async () => {
      const out = await api.post<UploadResult>(`/api/resumes/${r.id}/parse`);
      if (out.parse_error) throw new Error(out.parse_error);
      setMsg(
        t("「{label}」重新结构化完成{extra}。请到「履历内容」检查后确认。", { label: r.label, extra: out.unverified_items.length ? t("，{n} 项在原文找不到", { n: out.unverified_items.length }) : "" }),
      );
    });

  const remove = (r: Resume) =>
    act(`delete:${r.id}`, async () => {
      await api.del(`/api/resumes/${r.id}`);
      setMsg(t("已删除「{label}」。职位评分、申请材料、投递记录都保留。", { label: r.label }));
    });

  const rename = (r: Resume, label: string) =>
    act(`rename:${r.id}`, async () => {
      await api.patch(`/api/resumes/${r.id}`, { label });
    });

  return (
    <div className="stack">
      <ResumeTabs tab="versions" />
      {msg && <p className="notice">{msg}</p>}
      {error && <p className="error">{error}</p>}

      <section className="card flush">
        <div className="form-head">
          <b>{t("上传历史")}</b>
          <span className="muted small">{resumes ? t("{n} 个版本，新的在上面", { n: resumes.length }) : <><Spinner />{t("读取中…")}</>}</span>
        </div>
        {resumes && resumes.length === 0 && (
          <p className="muted" style={{ padding: "0 24px 16px" }}>
            {t("还没有履历，请到")} <Link to="/resumes/upload">{t("上传")}</Link> {t("分页上传。")}
          </p>
        )}
        {resumes?.map((r) => (
          <VersionRow
            key={r.id}
            r={r}
            busy={busy}
            onActivate={() => activate(r)}
            onReparse={() => reparse(r)}
            onDelete={() => remove(r)}
            onRename={(label) => rename(r, label)}
          />
        ))}
      </section>
    </div>
  );
}

function VersionRow({
  r,
  busy,
  onActivate,
  onReparse,
  onDelete,
  onRename,
}: {
  r: Resume;
  busy: string | null;
  onActivate: () => void;
  onReparse: () => void;
  onDelete: () => void;
  onRename: (label: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(r.label);
  const empty = r.parsed.experience.length === 0;
  const s = r.latest_review;
  const is = (action: string) => busy === `${action}:${r.id}`;

  return (
    <div className={`version-row${r.is_active ? " active" : ""}`}>
      <div className="version-main">
        {editing ? (
          <form
            className="row"
            onSubmit={async (e) => {
              e.preventDefault();
              if (!label.trim()) return;
              await onRename(label.trim());
              setEditing(false);
            }}
          >
            <input aria-label={t("版本名称")} value={label} onChange={(e) => setLabel(e.target.value)} autoFocus style={{ flex: "1 1 200px" }} />
            <button type="submit" className="primary" disabled={!label.trim() || is("rename")}>
              {t("保存")}
            </button>
            <button
              type="button"
              onClick={() => {
                setLabel(r.label);
                setEditing(false);
              }}
            >
              {t("取消")}
            </button>
          </form>
        ) : (
          <div className="row" style={{ gap: 8 }}>
            <b style={{ fontSize: 16 }}>{r.label}</b>
            {r.is_active && <span className="badge pass">{t("使用中")}</span>}
            <button type="button" className="link" onClick={() => setEditing(true)}>
              {t("改名")}
            </button>
          </div>
        )}
        <div className="muted small">
          {r.filename} · {t("上传于 {time}", { time: new Date(r.created_at).toLocaleString(locale) })}
        </div>
        <div className="row small" style={{ gap: 8, marginTop: 4 }}>
          {empty ? (
            <span className="badge warn">{t("结构化没有经历，建议重新结构化")}</span>
          ) : r.parsed_confirmed_at ? (
            <span className="badge">{t("已确认 · {n} 个检索切块", { n: r.chunk_count })}</span>
          ) : (
            <span className="badge">{t("尚未确认")}</span>
          )}
          <span className="muted">
            {s
              ? t("最近评分：ATS 可读性 {a} · 内容品质 {b} · 关键词 {c}（{date}）", { a: s.parse_score, b: s.content_score, c: s.keyword_score ?? "—", date: new Date(s.created_at).toLocaleDateString(locale) })
              : t("还没有评分")}
          </span>
        </div>
      </div>
      <div className="version-actions">
        <Link to={`/resumes?id=${r.id}`}>{t("查看评分")}</Link>
        <Link to={`/resumes/content?id=${r.id}`}>{t("履历内容")}</Link>
        {!r.is_active && (
          <button type="button" className="link" onClick={onActivate} disabled={!!busy}>
            {is("activate") ? <><Spinner />{t("设定中…")}</> : t("设为使用中")}
          </button>
        )}
        <button type="button" className="link" onClick={onReparse} disabled={!!busy}>
          {is("reparse") ? <><Spinner />{t("结构化中…")}</> : t("重新结构化")}
        </button>
        <ConfirmButton
          className="link danger"
          disabled={!!busy}
          message={t("档案、评分、检索资料会删除；职位评分、材料、投递记录保留。无法复原。")}
          onConfirm={onDelete}
        >
          {is("delete") ? <><Spinner />{t("删除中…")}</> : t("删除")}
        </ConfirmButton>
      </div>
    </div>
  );
}

/** 「上传」分页：上传新版本，完成后跳到这个版本的「履历内容」检查结构化结果。 */
export function ResumeUpload() {
  const navigate = useNavigate();
  return (
    <div className="stack">
      <ResumeTabs tab="upload" />
      <Upload onUploaded={(r) => navigate(`/resumes/content?id=${r.resume.id}`, { state: { upload: r } })} />
    </div>
  );
}

function Upload({ onUploaded }: { onUploaded: (r: UploadResult) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("file", file);
    form.append("label", label);
    try {
      onUploaded(await api.post<UploadResult>("/api/resumes", form));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h3 style={{ marginTop: 0 }}>{t("上传新版本")}</h3>
      <div className="grid">
        <FilePicker file={file} onChange={setFile} />
        <label>
          {t("版本名称（选填，留空就用档名）")}
          <input placeholder={t("例如 Full-stack 版、AI Engineer 版")} value={label} onChange={(e) => setLabel(e.target.value)} />
        </label>
      </div>
      <div className="row" style={{ marginTop: 12 }}>
        <button type="button" className="primary" onClick={submit} disabled={!file || busy}>
          {busy ? <><Spinner />{t("上传并结构化中…（约半分钟）")}</> : t("上传")}
        </button>
        <span className="muted small">{t("第一个上传的版本会自动设为使用中。档案只存在本机 data/ 目录。")}</span>
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

const ACCEPT = [".pdf", ".docx"];
const sizeText = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

/** 选择档案：按钮或拖拽进虚线框；选好后显示档名与大小。 */
function FilePicker({ file, onChange }: { file: File | null; onChange: (f: File | null) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [error, setError] = useState("");

  const take = (f: File | undefined) => {
    if (!f) return;
    if (!ACCEPT.some((ext) => f.name.toLowerCase().endsWith(ext))) {
      setError(t("只支援 PDF 或 DOCX。"));
      return;
    }
    setError("");
    onChange(f);
  };

  return (
    <div className="field">
      <span>{t("档案（PDF、DOCX）")}</span>
      <div
        className={`file-drop${over ? " over" : ""}${file ? " has-file" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          take(e.dataTransfer.files?.[0]);
        }}
      >
        <button type="button" onClick={() => ref.current?.click()}>
          {file ? t("换一个档案") : t("选择文件")}
        </button>
        <span className="file-name">
          {file ? (
            <>
              <b>{file.name}</b>
              <span className="muted small"> · {sizeText(file.size)}</span>
            </>
          ) : (
            <span className="muted">{t("或把档案拖到这里")}</span>
          )}
        </span>
        {file && (
          <button type="button" className="link" onClick={() => onChange(null)} aria-label={t("移除已选的档案")}>
            {t("移除")}
          </button>
        )}
        <input
          ref={ref}
          type="file"
          accept={ACCEPT.join(",")}
          hidden
          onChange={(e) => {
            take(e.target.files?.[0]);
            e.target.value = ""; // 同一个档案可以再选一次
          }}
        />
      </div>
      {error && <span className="error small">{error}</span>}
    </div>
  );
}
