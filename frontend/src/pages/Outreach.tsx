import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, Channel, Contact, ContactDetail, ContactSummary, OutreachMessage, RoleKind } from "../api";
import { StatusSelect } from "./ApplicationControl";
import { CHANNEL_LABEL, DraftEditor, EmailField, ROLE_LABEL, useHunter } from "./OutreachPanel";
import { ConfirmButton, Loading, Seg } from "./ui";
import { locale, t } from "../i18n";

type Filter = "all" | "waiting" | "replied";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" }) : "");
// datetime-local 输入框用本地时间，不带时区
const localInput = (d = new Date()) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);

/** Reach out 收件箱：左边联系人，中间往来消息，右边联系人资料与相关职位。消息都是你自己发、自己贴进来的。 */
export default function Outreach() {
  const { contactId } = useParams();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [list, setList] = useState<ContactSummary[] | null>(null);
  const [error, setError] = useState("");

  const loadList = useCallback(
    () => api.get<ContactSummary[]>(`/api/contacts?filter=${filter}`).then(setList).catch((e) => setError(e.message)),
    [filter],
  );
  useEffect(() => {
    loadList();
  }, [loadList]);

  const q = query.trim().toLowerCase();
  const shown = (list ?? []).filter((c) => !q || `${c.full_name} ${c.company_name ?? ""} ${c.title ?? ""}`.toLowerCase().includes(q));

  return (
    <div className={`inbox${contactId ? " has-open" : ""}`}>
      <section className="card inbox-list" aria-label={t("联系人")}>
        <Seg
          label={t("筛选")}
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: t("全部") },
            { value: "waiting", label: t("等对方回复") },
            { value: "replied", label: t("对方已回") },
          ]}
        />
        <input aria-label={t("搜索联系人")} placeholder={t("搜索姓名或公司")} value={query} onChange={(e) => setQuery(e.target.value)} style={{ marginTop: 8 }} />
        {error && <p className="error">{error}</p>}
        {!list ? (
          <Loading />
        ) : shown.length === 0 ? (
          <p className="muted small">{list.length ? t("没有符合的联系人。") : t("还没有联系人。到职位卡的「材料与内推」→「内推」找人。")}</p>
        ) : (
          <ul className="inbox-people">
            {shown.map((c) => (
              <li key={c.id}>
                <Link to={`/outreach/${c.id}`} className={c.id === contactId ? "on" : ""} aria-current={c.id === contactId ? "page" : undefined}>
                  <b>{c.full_name}</b>
                  <span className="muted small">{[c.title, c.company_name].filter(Boolean).join(" · ")}</span>
                  <span className="small">
                    {c.last_direction === "in" ? <span className="badge pass">{t("对方已回")}</span> : c.last_direction === "out" ? <span className="badge">{t("等对方回复")}</span> : <span className="muted">{t("还没联系")}</span>}{" "}
                    <span className="muted">{when(c.last_message_at)}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
      {contactId ? (
        <Conversation key={contactId} id={contactId} onChanged={loadList} onDeleted={() => { loadList(); navigate("/outreach"); }} />
      ) : (
        <section className="card inbox-empty muted">{t("选一个联系人看往来消息。")}</section>
      )}
    </div>
  );
}

function Conversation({ id, onChanged, onDeleted }: { id: string; onChanged: () => void; onDeleted: () => void }) {
  const hunter = useHunter();
  const [c, setC] = useState<ContactDetail | null>(null);
  const [error, setError] = useState("");
  const [replyError, setReplyError] = useState("");
  const [warning, setWarning] = useState("");
  const [reply, setReply] = useState({ body: "", channel: "linkedin_message" as Channel, at: localInput() });
  const [writing, setWriting] = useState(false);

  const load = useCallback(() => api.get<ContactDetail>(`/api/contacts/${id}`).then(setC).catch((e) => setError(e.message)), [id]);
  useEffect(() => {
    load();
  }, [load]);

  if (error) return <section className="card error">{error}</section>;
  if (!c) return <Loading className="card" />;
  const refresh = () => {
    load();
    onChanged();
  };
  const lastJob = [...c.messages].reverse().find((m) => m.job_id)?.job_id ?? c.jobs[0]?.id ?? null;

  const addReply = async () => {
    setReplyError("");
    try {
      await api.post(`/api/contacts/${c.id}/messages`, {
        direction: "in",
        channel: reply.channel,
        body: reply.body,
        job_id: lastJob,
        sent_at: new Date(reply.at).toISOString(),
      });
      setReply({ body: "", channel: reply.channel, at: localInput() });
      refresh();
    } catch (e) {
      setReplyError((e as Error).message);
    }
  };

  return (
    <>
      <section className="card inbox-thread" aria-label={t("往来消息")}>
        <div className="row between">
          <Link to="/outreach" className="inbox-back small">
            {t("← 联系人")}
          </Link>
          <b>{c.full_name}</b>
        </div>
        {warning && <p className="notice">{warning}</p>}
        {c.messages.length === 0 && <p className="muted">{t("还没有往来消息。到职位页写内推请求，发完按「我已发送」就会出现在这里。")}</p>}
        <div className="stack" style={{ gap: 8 }}>
          {c.messages.map((m) => (
            <Message
              key={m.id}
              m={m}
              name={c.full_name}
              onChanged={refresh}
              onDeleted={(w) => {
                setWarning(w ?? "");
                refresh();
              }}
            />
          ))}
        </div>
        <details className="inbox-compose" open={c.messages.length > 0 && c.messages[c.messages.length - 1].direction === "out"}>
          <summary>{t("贴上对方回复")}</summary>
          <textarea aria-label={t("对方回复")} rows={4} value={reply.body} onChange={(e) => setReply({ ...reply, body: e.target.value })} placeholder={t("从 LinkedIn 或邮件复制对方的回复贴在这里")} />
          <div className="row">
            <select aria-label={t("渠道")} value={reply.channel} onChange={(e) => setReply({ ...reply, channel: e.target.value as Channel })}>
              {(["linkedin_message", "inmail", "email"] as Channel[]).map((ch) => (
                <option key={ch} value={ch}>
                  {CHANNEL_LABEL[ch]}
                </option>
              ))}
            </select>
            <input type="datetime-local" aria-label={t("收到时间")} value={reply.at} onChange={(e) => setReply({ ...reply, at: e.target.value })} />
            <button type="button" className="primary" disabled={!reply.body.trim()} onClick={addReply}>
              {t("加入对话")}
            </button>
          </div>
          {replyError && <p className="error">{replyError}</p>}
        </details>
        {c.messages.some((m) => m.direction === "out") && (
          <div className="inbox-compose">
            {writing ? (
              <DraftEditor contact={c} jobId={lastJob} followUp onSent={() => refresh()} />
            ) : (
              <button type="button" onClick={() => setWriting(true)}>
                {t("写跟进")}
              </button>
            )}
          </div>
        )}
      </section>
      <ContactSide c={c} hunter={hunter} onSaved={(x) => setC({ ...c, ...x })} onDeleted={onDeleted} onStatus={refresh} />
    </>
  );
}

function Message({ m, name, onChanged, onDeleted }: { m: OutreachMessage; name: string; onChanged: () => void; onDeleted: (warning: string | null) => void }) {
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(m.body);
  const [error, setError] = useState("");

  const save = async () => {
    try {
      await api.patch(`/api/messages/${m.id}`, { body });
      setEditing(false);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const remove = async () => {
    try {
      const r = (await api.del(`/api/messages/${m.id}`)) as unknown as { warning: string | null } | undefined;
      onDeleted(r?.warning ?? null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <article className={`bubble ${m.direction}`}>
      <div className="row between small muted">
        <span>
          {m.direction === "out" ? t("你") : name} · {CHANNEL_LABEL[m.channel]} · {when(m.sent_at)}
        </span>
        <span className="row" style={{ gap: 4 }}>
          <button type="button" className="link small" onClick={() => setEditing(!editing)}>
            {editing ? t("取消") : t("编辑")}
          </button>
          <ConfirmButton className="link small" message={t("删除这条消息？")} onConfirm={remove}>
            {t("删除")}
          </ConfirmButton>
        </span>
      </div>
      {m.subject && <b className="small">{m.subject}</b>}
      {editing ? (
        <>
          <textarea aria-label={t("消息内容")} rows={5} value={body} onChange={(e) => setBody(e.target.value)} />
          <button type="button" className="primary" onClick={save} disabled={!body.trim()}>
            {t("保存修改")}
          </button>
        </>
      ) : (
        <p className="bubble-body">{m.body}</p>
      )}
      {error && <p className="error">{error}</p>}
    </article>
  );
}

function ContactSide({
  c,
  hunter,
  onSaved,
  onDeleted,
  onStatus,
}: {
  c: ContactDetail;
  hunter: boolean;
  onSaved: (c: Contact) => void;
  onDeleted: () => void;
  onStatus: () => void;
}) {
  const [form, setForm] = useState({ title: c.title ?? "", linkedin_url: c.linkedin_url ?? "", role_kind: c.role_kind, notes: c.notes ?? "" });
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const dirty = form.title !== (c.title ?? "") || form.linkedin_url !== (c.linkedin_url ?? "") || form.role_kind !== c.role_kind || form.notes !== (c.notes ?? "");

  const save = async () => {
    setError("");
    try {
      onSaved(await api.patch<Contact>(`/api/contacts/${c.id}`, form));
      setMsg(t("已保存。"));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const remove = async () => {
    try {
      await api.del(`/api/contacts/${c.id}`);
      onDeleted();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <aside className="card inbox-side stack" aria-label={t("联系人资料")}>
      <div>
        <b>{c.full_name}</b>
        <div className="muted small">{[c.title, c.company_name].filter(Boolean).join(" · ")}</div>
        {c.linkedin_url && (
          <a href={c.linkedin_url} target="_blank" rel="noopener noreferrer" className="small">
            LinkedIn ↗
          </a>
        )}
      </div>
      <label>
        {t("对方职位")}
        <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
      </label>
      <label>
        {t("LinkedIn 网址")}
        <input value={form.linkedin_url} onChange={(e) => setForm({ ...form, linkedin_url: e.target.value })} />
      </label>
      <label>
        {t("类型")}
        <select value={form.role_kind} onChange={(e) => setForm({ ...form, role_kind: e.target.value as RoleKind })}>
          {(Object.keys(ROLE_LABEL) as RoleKind[]).map((k) => (
            <option key={k} value={k}>
              {ROLE_LABEL[k]}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("备注")}
        <textarea rows={3} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      </label>
      <div className="row">
        <button type="button" className="primary" disabled={!dirty} onClick={save}>
          {t("保存")}
        </button>
        <ConfirmButton message={t("删除「{name}」和所有往来消息？", { name: c.full_name })} onConfirm={remove}>
          {t("删除联系人")}
        </ConfirmButton>
      </div>
      {msg && <span className="muted small">{msg}</span>}
      {error && <p className="error">{error}</p>}
      <EmailField contact={c} hunter={hunter} onChange={onSaved} />

      <b>{t("相关职位")}</b>
      {c.jobs.length === 0 && <span className="muted small">{t("消息里还没提到职位。")}</span>}
      {c.jobs.map((j) => (
        <div key={j.id} className="stack" style={{ gap: 4 }}>
          <Link to={`/jobs/${j.id}`}>
            <b>{j.title}</b>
          </Link>
          <span className="muted small">
            {[j.company.display_name, j.location_text, j.score != null ? t("分数 {n}", { n: j.score }) : null].filter(Boolean).join(" · ")}
          </span>
          {(j.sponsor_h1b || j.sponsor_perm) && (
            <span className="small">
              {j.sponsor_h1b && <span className="badge pass">H-1B</span>} {j.sponsor_perm && <span className="badge pass">PERM</span>}
            </span>
          )}
          <StatusSelect jobId={j.id} status={j.application_status} onChange={onStatus} />
        </div>
      ))}
    </aside>
  );
}
