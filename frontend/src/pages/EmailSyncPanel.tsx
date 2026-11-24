// 统计页的「Check email for updates」：读 Gmail（只读）更新投递状态，完成后显示 summary；需要确认的信在这里直接处理
import { ReactNode, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, DEMO, EmailSync, GmailStatus, MailItem, MailMsg, ReviewItem } from "../api";
import { lang, t } from "../i18n";
import { APP_STATUS, MAIL_KIND } from "./labels";
import { ConfirmButton, Spinner } from "./ui";

const date = (iso: string) => new Date(iso).toLocaleDateString(lang === "zh" ? "zh-CN" : "en-US");
const statusText = (s: string | null) => (s ? APP_STATUS[s]?.text ?? s : t("没有记录"));

export default function EmailSyncPanel({ onChanged }: { onChanged: () => void }) {
  const [gmail, setGmail] = useState<GmailStatus | null>(null);
  const [sync, setSync] = useState<EmailSync | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  const poll = (id: string) => {
    window.clearTimeout(timer.current);
    api
      .get<EmailSync>(`/api/email/syncs/${id}`)
      .then((s) => {
        setSync(s);
        if (s.status === "running") timer.current = window.setTimeout(() => poll(id), 2000);
        else onChanged();
      })
      .catch((e) => setError(e.message));
  };

  const reload = () =>
    api
      .get<EmailSync>("/api/email/syncs/latest")
      .then((s) => {
        setSync(s);
        if (s.status === "running" && s.id) poll(s.id);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    api.get<GmailStatus>("/api/email/gmail").then(setGmail).catch((e) => setError(e.message));
    reload();
    return () => window.clearTimeout(timer.current);
  }, []);

  const start = async () => {
    setError("");
    try {
      const { id } = await api.post<{ id: string }>("/api/email/sync");
      poll(id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const running = sync?.status === "running";
  const s = sync?.summary;
  const review = sync?.needs_review ?? [];
  // 同公司的信放在一起，信多的公司排前面
  const groups = new Map<string, ReviewItem[]>();
  for (const r of review) groups.set(r.message.company ?? "", [...(groups.get(r.message.company ?? "") ?? []), r]);
  const sorted = [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
  const creatable = review.filter((r) => r.bulk_create).map((r) => r.message.id);

  const done = (rechecked = 0) => {
    setMsg(rechecked ? t("同公司另外 {n} 封也一起处理了。", { n: rechecked }) : "");
    reload();
    onChanged();
  };
  const bulk = async (action: "create" | "ignore", ids: string[]) => {
    setError("");
    setBusy(true);
    try {
      const r = await api.post<{ resolved: number }>("/api/email/messages/resolve-bulk", { action, ids });
      setMsg(action === "create" ? t("已新建 {n} 个职位。", { n: r.resolved }) : t("已忽略 {n} 封。", { n: r.resolved }));
      reload();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card stack" aria-label={t("邮件更新")}>
      <div className="row between">
        <div>
          <b>{t("邮件更新")}</b>
          <div className="muted small">
            {gmail?.connected
              ? t("读取 {email} 的求职邮件（只读），建出你自己投的职位、更新投递状态。", { email: gmail.email ?? "Gmail" })
              : t("连接 Gmail（只读）后，可以从邮件建出你自己投的职位、更新投递状态。")}
          </div>
        </div>
        {gmail && !gmail.connected ? (
          <Link className="btn" to="/settings?view=email">
            {t("去连接 Gmail →")}
          </Link>
        ) : (
          <button type="button" className="primary" onClick={start} disabled={running || DEMO || !gmail}>
            {running ? <><Spinner /> {t("同步中…")}</> : t("Check email for updates")}
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {running && <p className="notice">{t("已读 {n} / {total} 封", { n: sync?.processed ?? 0, total: sync?.fetched ?? 0 })}</p>}
      {sync?.status === "failed" && <p className="error">{sync.error}</p>}

      {(sync?.status === "completed" || sync?.status === "failed") && s && (
        <details className="stack" open>
          <summary>
            {t("上次同步 {time}：新增 {created} 个职位、更新 {updated} 个状态、需要确认 {review} 封、忽略 {ignored} 封", {
              time: sync.finished_at ? new Date(sync.finished_at).toLocaleString() : "",
              created: s.created.length,
              updated: s.updated.length,
              review: review.length,
              ignored: s.ignored,
            })}
          </summary>
          {sync.window_after && (
            <div className="muted small">
              {t("读取范围：{from} 到 {to}，共 {n} 封新信。", { from: date(sync.window_after), to: sync.window_before ? date(sync.window_before) : "", n: sync.fetched ?? 0 })}
            </div>
          )}
          {sync.truncated && <p className="notice">{t("还有信没读完，再按一次继续。")}</p>}
          <ItemList title={t("新增的职位")} items={s.created} render={(i) => <>{statusText(i.to)}</>} />
          <ItemList title={t("状态变更")} items={s.updated} render={(i) => <>{statusText(i.from)} → <b>{statusText(i.to)}</b></>} />
          <ItemList title={t("只记下证据（状态不变）")} items={s.evidence_only} render={(i) => <>{statusText(i.status)}</>} />
        </details>
      )}

      {msg && <p className="notice">{msg}</p>}
      {review.length > 0 && (
        <div className="stack">
          <div className="row between">
            <b>{t("需要确认（{n} 封）", { n: review.length })}</b>
            <div className="row">
              {creatable.length > 0 && (
                <button type="button" onClick={() => bulk("create", creatable)} disabled={busy}>
                  {t("全部新建为职位（{n} 封）", { n: creatable.length })}
                </button>
              )}
              <ConfirmButton
                message={t("这 {n} 封信都不处理，之后不会再出现在这里。", { n: review.length })}
                confirmLabel={t("确定忽略")}
                onConfirm={() => bulk("ignore", review.map((r) => r.message.id))}
                disabled={busy}
              >
                {t("全部忽略")}
              </ConfirmButton>
            </div>
          </div>
          {creatable.length > 0 && (
            <div className="muted small">{t("「全部新建为职位」只处理信里写明公司与职称、而且找不到对应职位的拒信与 offer，状态照信的内容记。")}</div>
          )}
          {sorted.map(([company, items]) => (
            <details className="card" key={company}>
              <summary>
                <b>{company || t("（信里没写公司）")}</b> · {t("{n} 封", { n: items.length })}
              </summary>
              <div className="stack" style={{ marginTop: 8 }}>
                {items.length > 1 && (
                  <div className="row">
                    <button type="button" onClick={() => bulk("ignore", items.map((r) => r.message.id))} disabled={busy}>
                      {t("忽略这 {n} 封", { n: items.length })}
                    </button>
                  </div>
                )}
                {items.map((r) => (
                  <ReviewRow key={r.message.id} item={r} onDone={done} />
                ))}
              </div>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}

function MailLine({ m }: { m: MailMsg }) {
  return (
    <div className="muted small">
      {MAIL_KIND[m.kind] ?? m.kind} · {m.from_addr} · {date(m.received_at)} · {m.subject}{" "}
      <a href={m.gmail_url} target="_blank" rel="noreferrer">
        {t("在 Gmail 打开")}
      </a>
    </div>
  );
}

function ItemList({ title, items, render }: { title: string; items: MailItem[]; render: (i: MailItem) => ReactNode }) {
  if (!items.length) return null;
  return (
    <div className="stack" style={{ gap: 6 }}>
      <b>{title}</b>
      {items.map((i) => (
        <div key={i.message.id}>
          {i.job_id ? <Link to={`/jobs/${i.job_id}`}>{i.company} · {i.title}</Link> : t("（职位已删除）")} · {render(i)}
          <MailLine m={i.message} />
        </div>
      ))}
    </div>
  );
}

function ReviewRow({ item, onDone }: { item: ReviewItem; onDone: (rechecked?: number) => void }) {
  const m = item.message;
  const unclassified = m.kind === "not_evidence"; // 模型没能判断：只能自己去 Gmail 看，然后忽略
  const [jobId, setJobId] = useState(item.candidates[0]?.job_id ?? "");
  const [company, setCompany] = useState(m.company ?? "");
  const [title, setTitle] = useState(m.title ?? "");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const act = async (body: Record<string, unknown>) => {
    setError("");
    try {
      const r = await api.post<{ decision: { rechecked: number } }>(`/api/email/messages/${m.id}/resolve`, body);
      onDone(r.decision.rechecked);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="card stack" style={{ gap: 8 }}>
      <div>
        <b>{m.subject || t("（没有主旨）")}</b>
        <MailLine m={m} />
      </div>
      {item.reason && <div>{item.reason}</div>}
      {m.excerpt && <blockquote className="muted" style={{ margin: 0 }}>{m.excerpt}</blockquote>}
      <div className="row">
        {!unclassified && item.candidates.length > 0 && (
          <>
            <select aria-label={t("对应的职位")} value={jobId} onChange={(e) => setJobId(e.target.value)}>
              {item.candidates.map((c) => (
                <option key={c.job_id ?? ""} value={c.job_id ?? ""}>
                  {c.company} · {c.title} · {statusText(c.status)}
                </option>
              ))}
            </select>
            <button type="button" onClick={() => act({ action: "link", job_id: jobId })} disabled={!jobId}>
              {t("对应到这个职位")}
            </button>
          </>
        )}
        {!unclassified && (
          <button type="button" onClick={() => setCreating(!creating)} aria-expanded={creating}>
            {t("新建为职位")}
          </button>
        )}
        <button type="button" onClick={() => act({ action: "ignore" })}>
          {t("忽略")}
        </button>
      </div>
      {creating && (
        <div className="row">
          <input aria-label={t("公司名称")} placeholder={t("公司名称")} value={company} onChange={(e) => setCompany(e.target.value)} />
          <input aria-label={t("职称")} placeholder={t("职称")} value={title} onChange={(e) => setTitle(e.target.value)} />
          <button type="button" className="primary" onClick={() => act({ action: "create", company, title })} disabled={!company.trim() || !title.trim()}>
            {t("建立")}
          </button>
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
