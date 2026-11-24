import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, Candidate, Channel, Contact, ContactSummary, DraftsOut, DraftVersion, HunterSettings, JobPreferences, JobSummary, OutreachStyle, RoleKind } from "../api";
import { APP_STATUS } from "./labels";
import { Seg, Spinner } from "./ui";
import { t } from "../i18n";

export const CHANNEL_LABEL: Record<Channel, string> = {
  connect_note: t("连接附言"),
  inmail: "InMail",
  linkedin_message: t("LinkedIn 私信"),
  email: t("邮件"),
};
export const ROLE_LABEL: Record<RoleKind, string> = {
  engineer: t("工程师"),
  eng_manager: t("工程经理"),
  recruiter: t("招聘"),
  other: t("其他"),
};
const STYLE_LABEL: Record<OutreachStyle, string> = { technical: t("技术型"), general: t("一般型") };
const MAILTO_MAX = 1800; // mailto 网址太长时有些邮件程式打不开

export function useHunter() {
  const [hunter, setHunter] = useState(false);
  useEffect(() => {
    api.get<HunterSettings>("/api/outreach/hunter").then((h) => setHunter(h.enabled)).catch(() => setHunter(false));
  }, []);
  return hunter;
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** 联系人的邮箱：手动填，或用 Hunter 查（会用掉额度）。 */
export function EmailField({ contact, hunter, onChange }: { contact: Contact; hunter: boolean; onChange: (c: Contact) => void }) {
  const [email, setEmail] = useState(contact.email ?? "");
  const [domain, setDomain] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  useEffect(() => setEmail(contact.email ?? ""), [contact.email]);

  const save = async () => {
    setMsg("");
    try {
      onChange(await api.patch<Contact>(`/api/contacts/${contact.id}`, { email: email.trim() || null }));
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  const lookup = async () => {
    setBusy(true);
    setMsg("");
    try {
      const r = await api.post<{ found: boolean; contact: Contact }>(`/api/contacts/${contact.id}/email-lookup`, { domain: domain.trim() || null });
      onChange(r.contact);
      setMsg(r.found ? t("找到了（可信度 {n}）。", { n: r.contact.email_confidence ?? "?" }) : t("Hunter 没有找到这个人的邮箱。"));
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack" style={{ gap: 4 }}>
      <div className="row">
        <input aria-label={t("邮箱")} value={email} onChange={(e) => setEmail(e.target.value)} placeholder={t("邮箱（选填）")} style={{ flex: "1 1 200px" }} />
        <button type="button" onClick={save} disabled={email.trim() === (contact.email ?? "")}>
          {t("保存邮箱")}
        </button>
        {hunter && (
          <>
            <input aria-label={t("公司网址")} value={domain} onChange={(e) => setDomain(e.target.value)} placeholder={t("公司网址（不知道时选填）")} style={{ flex: "1 1 160px" }} />
            <button type="button" onClick={lookup} disabled={busy} title={t("会用掉一次 Hunter 额度")}>
              {busy && <Spinner />}
              {t("用 Hunter 查邮箱")}
            </button>
          </>
        )}
      </div>
      {contact.email_source === "hunter" && contact.email && <span className="muted small">{t("来自 Hunter，可信度 {n}", { n: contact.email_confidence ?? "?" })}</span>}
      {msg && <span className="muted small">{msg}</span>}
    </div>
  );
}

/** 生成、编辑、复制草稿，发完按「我已发送」记录。草稿不存，离开页面就没了。 */
export function DraftEditor({
  contact,
  jobId,
  followUp = false,
  auto = false,
  onSent,
}: {
  contact: Contact;
  jobId: string | null;
  followUp?: boolean;
  /** 一打开就开始写，不用再按一次 */
  auto?: boolean;
  onSent: (status: string | null) => void;
}) {
  const [drafts, setDrafts] = useState<DraftsOut | null>(null);
  const [style, setStyle] = useState<OutreachStyle | null>(null);
  const [language, setLanguage] = useState<"en" | "zh">("en");
  const [tab, setTab] = useState<Channel>("connect_note");
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [subject, setSubject] = useState("");
  const [sentAs, setSentAs] = useState<Channel>("connect_note");
  const [prefs, setPrefs] = useState<JobPreferences | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!followUp) api.get<{ data: JobPreferences }>("/api/preferences").then((r) => setPrefs(r.data)).catch(() => {});
  }, [followUp]);

  const generate = async (s: OutreachStyle | null = style) => {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const d = await api.post<DraftsOut>("/api/outreach/drafts", { contact_id: contact.id, job_id: jobId, style: s, language, follow_up: followUp });
      setDrafts(d);
      setStyle(d.style);
      setTexts(Object.fromEntries(d.versions.map((v) => [v.channel, v.body])));
      setSubject(d.versions.find((v) => v.channel === "email")?.subject ?? "");
      setTab(d.versions[0].channel);
      setSentAs(d.versions[0].channel);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const started = useRef(false); // StrictMode 下 effect 会跑两次，只生成一次
  useEffect(() => {
    if (!auto || started.current) return;
    started.current = true;
    generate();
  }, []);

  const setPremium = async (on: boolean) => {
    if (!prefs) return;
    const next = { ...prefs, linkedin_premium: on };
    setPrefs(next);
    try {
      await api.put("/api/preferences", next);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const version: DraftVersion | undefined = drafts?.versions.find((v) => v.channel === tab);
  const text = texts[tab] ?? "";
  const limit = tab === "connect_note" && prefs ? (prefs.linkedin_premium ? 300 : 200) : version?.limit ?? null;

  const copyOpen = async () => {
    const ok = await copyText(text);
    setMsg(ok ? t("已复制，贴到 LinkedIn 发送，发完回来按「我已发送」。") : t("浏览器不允许复制，请手动选取文字。"));
    if (contact.linkedin_url) window.open(contact.linkedin_url, "_blank", "noopener");
  };
  const openMail = async () => {
    const url = `mailto:${encodeURIComponent(contact.email ?? "")}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(text)}`;
    if (url.length > MAILTO_MAX) {
      const ok = await copyText(`${subject}\n\n${text}`);
      setMsg(ok ? t("内容太长，已复制，请贴进邮件。") : t("浏览器不允许复制，请手动选取文字。"));
      return;
    }
    window.location.href = url;
    setMsg(t("发完回来按「我已发送」。"));
  };
  const markSent = async () => {
    setError("");
    setBusy(true);
    try {
      const r = await api.post<{ application_status: string | null }>(`/api/contacts/${contact.id}/messages`, {
        direction: "out",
        channel: sentAs,
        body: text,
        subject: sentAs === "email" ? subject : null,
        style,
        job_id: jobId,
        material_meta: drafts?.material_meta ?? null,
      });
      setDrafts(null);
      setTexts({});
      const st = r.application_status;
      setMsg(st ? t("已记录。职位状态：{s}", { s: APP_STATUS[st]?.text ?? st }) : t("已记录。"));
      onSent(st);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row">
        {style && <Seg label={t("风格")} value={style} options={(["technical", "general"] as const).map((v) => ({ value: v, label: STYLE_LABEL[v] }))} onChange={(v) => { setStyle(v); generate(v); }} />}
        <select aria-label={t("草稿语言")} value={language} onChange={(e) => setLanguage(e.target.value as "en" | "zh")}>
          <option value="en">English</option>
          <option value="zh">中文</option>
        </select>
        {prefs && (
          <label className="inline">
            <input type="checkbox" checked={prefs.linkedin_premium} onChange={(e) => setPremium(e.target.checked)} />
            {t("我有 LinkedIn Premium（附言 300 字符）")}
          </label>
        )}
        <button type="button" className="primary" onClick={() => generate()} disabled={busy}>
          {busy && <Spinner />}
          {busy ? t("生成中…") : drafts ? t("重写") : followUp ? t("写跟进") : t("写内推请求")}
        </button>
      </div>
      {!drafts && !busy && !followUp && <p className="muted small">{t("对照 JD 的要求和你的履历，说明你为什么适合这个职位。工程师 / 工程经理预设写技术型，其他写一般型；履历里没有的事实列为「需要确认」。")}</p>}
      {drafts && version && (
        <div className="draft">
          {drafts.versions.length > 1 && (
            <Seg label={t("版本")} value={tab} options={drafts.versions.map((v) => ({ value: v.channel, label: CHANNEL_LABEL[v.channel] }))} onChange={(v) => { setTab(v); setSentAs(v); }} />
          )}
          {version.needs_confirmation.length > 0 && (
            <div className="notice" style={{ marginTop: 8 }}>
              <b>{t("需要确认（{n}）", { n: version.needs_confirmation.length })}</b>
              <ul>
                {version.needs_confirmation.map((n, i) => (
                  <li key={i}>
                    {n.item}: <span className="muted">{n.why}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {followUp && tab === "linkedin_message" && <p className="muted small">{t("LinkedIn 私信要等对方接受你的连接后才发得出去。")}</p>}
          {tab === "email" && <input aria-label={t("邮件主旨")} value={subject} onChange={(e) => setSubject(e.target.value)} style={{ marginTop: 8 }} />}
          <textarea aria-label={t("草稿内容")} rows={tab === "connect_note" ? 4 : 10} value={text} onChange={(e) => setTexts({ ...texts, [tab]: e.target.value })} style={{ marginTop: 8 }} />
          {limit && (
            <span className={`small ${text.length > limit ? "error" : "muted"}`}>
              {t("{n} / {limit} 字符", { n: text.length, limit })}
              {text.length > limit && t("，超过上限，LinkedIn 发不出去，请删短。")}
            </span>
          )}
          <div className="row" style={{ marginTop: 8 }}>
            {tab === "email" ? (
              <button type="button" onClick={openMail} disabled={!contact.email}>
                {t("用邮件打开")}
              </button>
            ) : (
              <button type="button" onClick={copyOpen} disabled={!contact.linkedin_url} title={contact.linkedin_url ? "" : t("这个联系人没有 LinkedIn 网址")}>
                {t("复制并打开 LinkedIn")}
              </button>
            )}
            <button type="button" onClick={async () => setMsg((await copyText(text)) ? t("已复制。") : t("浏览器不允许复制，请手动选取文字。"))}>
              {t("复制")}
            </button>
            <span className="row" style={{ gap: 4, marginLeft: "auto" }}>
              <select aria-label={t("实际用的渠道")} value={sentAs} onChange={(e) => setSentAs(e.target.value as Channel)}>
                {(Object.keys(CHANNEL_LABEL) as Channel[]).map((c) => (
                  <option key={c} value={c}>
                    {CHANNEL_LABEL[c]}
                  </option>
                ))}
              </select>
              <button type="button" className="primary" onClick={markSent} disabled={busy || !text.trim()}>
                {t("我已发送")}
              </button>
            </span>
          </div>
        </div>
      )}
      {msg && <p className="notice">{msg}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

const candKey = (c: Candidate) => c.linkedin_url ?? c.email ?? c.full_name;

/** 职位详情页：找这家公司可能内推的人、写请求、记录发送。 */
export default function OutreachPanel({ job, onSent }: { job: JobSummary; onSent: () => void }) {
  const hunter = useHunter();
  const [useHunterToo, setUseHunterToo] = useState(false);
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [contacts, setContacts] = useState<ContactSummary[]>([]);
  const [open, setOpen] = useState<Contact | null>(null);
  const [inSearch, setInSearch] = useState(false); // 草稿开在搜索结果那一行下面（否则在联系人清单里）
  const [manual, setManual] = useState({ full_name: "", title: "", linkedin_url: "" });
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");

  const loadContacts = useCallback(
    () => api.get<ContactSummary[]>(`/api/contacts?company_id=${job.company.id}`).then(setContacts).catch((e) => setError(e.message)),
    [job.company.id],
  );
  useEffect(() => {
    loadContacts();
  }, [loadContacts]);

  const find = async () => {
    setBusy(true);
    setError("");
    try {
      const found = await api.post<Candidate[]>(`/api/jobs/${job.id}/outreach/candidates`, { use_hunter: useHunterToo });
      // 再搜一次：之前找到的人和已加入的记号都留着，正在写的草稿不会跟着那一行消失
      setCandidates((prev) => {
        const old = new Map((prev ?? []).map((c) => [candKey(c), c]));
        const next = found.map((c) => ({ ...c, contact_id: c.contact_id ?? old.get(candKey(c))?.contact_id ?? null }));
        next.forEach((c) => old.delete(candKey(c)));
        return [...next, ...old.values()];
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const add = async (body: Record<string, unknown>, fromSearch = false) => {
    if (adding) return;
    setAdding(true);
    setError("");
    try {
      const c = await api.post<Contact>("/api/contacts", { company_id: job.company.id, ...body });
      await loadContacts();
      setInSearch(fromSearch);
      setOpen(c);
      return c;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAdding(false);
    }
  };
  const toggle = async (id: string, fromSearch = false) => {
    const closing = open?.id === id && inSearch === fromSearch;
    setInSearch(fromSearch);
    setOpen(closing ? null : await api.get<Contact>(`/api/contacts/${id}`));
  };
  const added = new Set(contacts.map((c) => c.id));
  const editor = open && (
    <div className="stack" style={{ gap: 8, paddingLeft: 16 }}>
      <EmailField contact={open} hunter={hunter} onChange={setOpen} />
      <DraftEditor
        key={open.id}
        contact={open}
        jobId={job.id}
        auto={inSearch}
        onSent={() => {
          loadContacts();
          onSent();
        }}
      />
    </div>
  );

  return (
    <section className="card stack" id="reach-out" aria-label={t("内推")}>
      <h3 style={{ margin: 0 }}>{t("内推")}</h3>
      <p className="muted small">{t("先找这家公司里可能帮你内推的人，再按那个人的「写内推请求」：会对照 JD 和你的履历，写一封说明你为什么适合这个职位的消息。只看公开搜索结果，不登录 LinkedIn；消息由你自己发送。")}</p>
      <div className="row">
        <button type="button" className="primary" onClick={find} disabled={busy}>
          {busy && <Spinner />}
          {busy ? t("搜索中…") : t("找内推人")}
        </button>
        {hunter && (
          <label className="inline">
            <input type="checkbox" checked={useHunterToo} onChange={(e) => setUseHunterToo(e.target.checked)} />
            {t("同时用 Hunter 查（会用掉额度）")}
          </label>
        )}
      </div>
      {busy && <p className="notice" role="status">{t("正在搜索公开结果并整理名单，通常要 1–2 分钟，请留在这一页。")}</p>}
      {error && <p className="error">{error}</p>}

      {candidates && (
        <div className="stack" style={{ gap: 6 }}>
          {candidates.length === 0 && <p className="notice" role="status">{t("公开搜索结果里没有找到这家公司的人（小公司常会这样）。可以再搜一次，或按下面的「手动加入」。")}</p>}
          {candidates.map((c) => {
            const known = c.contact_id && added.has(c.contact_id);
            const here = inSearch && !!open && open.id === c.contact_id;
            return (
              <div key={candKey(c)} className="stack" style={{ gap: 6 }}>
                <div className="row between">
                  <span>
                    <b>{c.full_name}</b> <span className="muted">· {c.title}</span> <span className="badge">{ROLE_LABEL[c.role_kind]}</span>
                    <br />
                    <span className="small">{c.why}</span>{" "}
                    {c.linkedin_url && (
                      <a href={c.linkedin_url} target="_blank" rel="noopener noreferrer" className="small">
                        LinkedIn ↗
                      </a>
                    )}
                    {c.email && <span className="muted small"> · {c.email}</span>}
                  </span>
                  {c.contact_id && !known ? (
                    <Link to={`/outreach/${c.contact_id}`} className="small">
                      {t("已联系过 →")}
                    </Link>
                  ) : (
                    <button
                      type="button"
                      disabled={adding}
                      aria-expanded={here}
                      onClick={async () => {
                        if (c.contact_id) return toggle(c.contact_id, true);
                        const saved = await add({ ...c, why: c.why, found_via: c.found_via }, true);
                        if (saved) setCandidates((cs) => cs && cs.map((x) => (x === c ? { ...x, contact_id: saved.id } : x)));
                      }}
                    >
                      {here ? t("收起") : t("写内推请求")}
                    </button>
                  )}
                </div>
                {here && editor}
              </div>
            );
          })}
        </div>
      )}

      <details>
        <summary className="small">{t("手动加入")}</summary>
        <div className="row" style={{ marginTop: 6 }}>
          <input aria-label={t("姓名")} placeholder={t("姓名")} value={manual.full_name} onChange={(e) => setManual({ ...manual, full_name: e.target.value })} />
          <input aria-label={t("对方职位")} placeholder={t("职位（选填）")} value={manual.title} onChange={(e) => setManual({ ...manual, title: e.target.value })} />
          <input aria-label={t("LinkedIn 网址")} placeholder={t("LinkedIn 网址（选填）")} value={manual.linkedin_url} onChange={(e) => setManual({ ...manual, linkedin_url: e.target.value })} />
          <button
            type="button"
            disabled={adding || !manual.full_name.trim()}
            onClick={async () => {
              if (await add(manual)) setManual({ full_name: "", title: "", linkedin_url: "" });
            }}
          >
            {t("加入")}
          </button>
        </div>
      </details>

      {contacts.length > 0 && (
        <div className="stack" style={{ gap: 6 }}>
          <b>{t("这家公司的联系人")}</b>
          {contacts.map((c) => (
            <div key={c.id} className="stack" style={{ gap: 6 }}>
              <div className="row between">
                <button type="button" className="link" onClick={() => toggle(c.id)} aria-expanded={!inSearch && open?.id === c.id}>
                  {!inSearch && open?.id === c.id ? "▾" : "▸"} {c.full_name}
                </button>
                <span className="muted" style={{ marginRight: "auto", marginLeft: 6 }}>{c.title ?? ""}</span>
                <span className="muted small">
                  {c.message_count ? t("消息 {n} 条", { n: c.message_count }) : t("还没联系")} ·{" "}
                  <Link to={`/outreach/${c.id}`}>{t("收件箱 →")}</Link>
                </span>
              </div>
              {!inSearch && open?.id === c.id && editor}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
