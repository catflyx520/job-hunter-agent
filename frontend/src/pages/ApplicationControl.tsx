import { useEffect, useState } from "react";
import { api, Application, ApplicationStatus, Material } from "../api";
import { APP_STATUS, APP_STATUS_ORDER } from "./labels";
import { locale, t } from "../i18n";

/** 职位列表里的精简版：一个下拉选单改状态。 */
export function StatusSelect({
  jobId,
  status,
  onChange,
}: {
  jobId: string;
  status: ApplicationStatus | null;
  onChange?: (s: ApplicationStatus) => void;
}) {
  const [value, setValue] = useState<ApplicationStatus | null>(status);
  const [error, setError] = useState("");
  useEffect(() => setValue(status), [status]);

  const set = async (s: ApplicationStatus) => {
    setError("");
    try {
      const a = await api.put<Application>(`/api/jobs/${jobId}/application`, { status: s });
      setValue(a.status);
      onChange?.(a.status);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <span title={error || t("投递状态（你自己标记；本工具不会代你投递）")}>
      <select
        value={value ?? ""}
        onChange={(e) => e.target.value && set(e.target.value as ApplicationStatus)}
        aria-label={t("投递状态")}
      >
        <option value="">{t("未标记")}</option>
        {APP_STATUS_ORDER.map((s) => (
          <option key={s} value={s}>
            {APP_STATUS[s].text}
          </option>
        ))}
      </select>
      {error && <span className="badge fail">{t("失败")}</span>}
    </span>
  );
}

/** 职位详情页：状态、这次变更的备注、整体备注、附上的 cover letter、变更历史。 */
export default function ApplicationPanel({ jobId }: { jobId: string }) {
  const [app, setApp] = useState<Application | null>(null);
  const [letters, setLetters] = useState<Material[]>([]);
  const [note, setNote] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<Application | null>(`/api/jobs/${jobId}/application`)
      .then((a) => {
        setApp(a);
        setNotes(a?.notes ?? "");
      })
      .catch((e) => setError(e.message));
    api
      .get<Material[]>(`/api/materials?job_id=${jobId}&kind=cover_letter`)
      .then(setLetters)
      .catch(() => undefined);
  }, [jobId]);

  const save = async (patch: { status?: ApplicationStatus; cover_letter_id?: string }) => {
    setError("");
    try {
      const a = await api.put<Application>(`/api/jobs/${jobId}/application`, {
        status: patch.status ?? app?.status ?? "saved",
        note: patch.status ? note || null : null,
        notes,
        cover_letter_id: patch.cover_letter_id ?? null,
      });
      setApp(a);
      setNote("");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const restore = async () => {
    try {
      setApp(await api.post<Application>(`/api/jobs/${jobId}/application/restore`));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="card">
      <h3>{t("投递状态")}</h3>
      <p className="muted">
        {t("状态由你自己标记；「已投递」的时间就是你标记的时间。本工具不会代你投递、填表或联系雇主。")}
      </p>
      <div className="row">
        {APP_STATUS_ORDER.map((s) => (
          <button
            key={s}
            className={app?.status === s ? "primary" : ""}
            onClick={() => save({ status: s })}
            disabled={app?.status === s}
          >
            {APP_STATUS[s].text}
          </button>
        ))}
        {app?.status === "dismissed" && <button onClick={restore}>{t("还原")}</button>}
      </div>
      <div className="grid" style={{ marginTop: 10 }}>
        <label>
          {t("这次变更的备注（选填，写进历史）")}
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("例如：用 LinkedIn Easy Apply 投递")} />
        </label>
        <label>
          {t("附上的 cover letter")}
          <select
            value={app?.cover_letter_id ?? ""}
            disabled={!app}
            onChange={(e) => e.target.value && save({ cover_letter_id: e.target.value })}
          >
            <option value="">{letters.length ? t("未选择") : t("这个职位还没有 cover letter")}</option>
            {letters.map((m) => (
              <option key={m.id} value={m.id}>
                {new Date(m.created_at).toLocaleString()}
                {m.edited_text ? t("（已修改）") : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label style={{ marginTop: 10 }}>
        {t("备注")}
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => app && notes !== (app.notes ?? "") && save({})} />
      </label>
      {error && <p className="error">{error}</p>}
      {app && (
        <>
          <p className="muted">
            {app.applied_at ? t("标记投递于 {time}", { time: new Date(app.applied_at).toLocaleString(locale) }) : t("尚未标记投递")}
          </p>
          <table>
            <tbody>
              {[...app.events].reverse().map((e) => (
                <tr key={e.id}>
                  <td style={{ width: 170 }} className="muted">
                    {new Date(e.at).toLocaleString()}
                  </td>
                  <td>
                    {e.from_status ? `${APP_STATUS[e.from_status]?.text ?? e.from_status} → ` : ""}
                    <b>{APP_STATUS[e.to_status].text}</b>
                    {e.note && <span className="muted"> · {e.note}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
