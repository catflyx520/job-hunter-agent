import { useEffect, useState } from "react";
import { api, Fact, FactTemplate } from "../api";
import { t } from "../i18n";

const SOURCE_LABEL: Record<string, string> = {
  user_confirmed: t("用户填写"),
  resume_derived: t("从履历推得"),
  from_answer: t("来自问答"),
};

export default function Facts() {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [templates, setTemplates] = useState<FactTemplate[]>([]);
  const [error, setError] = useState("");
  const [custom, setCustom] = useState({ key: "", question: "" });

  const load = () =>
    Promise.all([api.get<Fact[]>("/api/facts"), api.get<FactTemplate[]>("/api/facts/templates")]).then(([f, t]) => {
      setFacts(f);
      setTemplates(t);
    });
  useEffect(() => {
    load();
  }, []);

  const act = async (fn: () => Promise<unknown>) => {
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      <h2>{t("个人事实库")}</h2>
      <p className="muted">
        {t("求职申请常见问题的标准答案。生成 cover letter 与申请问答时，")}<b>{t("只会使用已确认的事实")}</b>{t("；缺少的会列在「需要确认」，不会猜。")}
      </p>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>{t("问题")}</th>
              <th>{t("答案")}</th>
              <th>{t("状态")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {facts.map((f) => (
              <FactRow key={f.id} fact={f} act={act} />
            ))}
          </tbody>
        </table>
        {facts.length === 0 && <p className="muted">{t("还没有任何事实。可以从下方的常见问题开始。")}</p>}
      </div>

      {templates.length > 0 && (
        <div className="card">
          <h3>{t("常见问题")}</h3>
          <div className="row">
            {templates.map((tpl) => (
              <button
                key={tpl.key}
                onClick={() => act(() => api.post("/api/facts", { key: tpl.key, question: tpl.question, value_type: tpl.value_type }))}
              >
                + {tpl.question}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <h3>{t("自订问题")}</h3>
        <div className="row">
          <input
            placeholder={t("key（小写英文与底线，例如 security_clearance）")}
            value={custom.key}
            onChange={(e) => setCustom({ ...custom, key: e.target.value })}
            style={{ minWidth: 280 }}
          />
          <input
            placeholder={t("问题")}
            value={custom.question}
            onChange={(e) => setCustom({ ...custom, question: e.target.value })}
            style={{ flex: 1 }}
          />
          <button
            onClick={() =>
              act(async () => {
                await api.post("/api/facts", custom);
                setCustom({ key: "", question: "" });
              })
            }
            disabled={!custom.key || !custom.question}
          >
            {t("新增")}
          </button>
        </div>
      </div>
    </>
  );
}

function FactRow({ fact, act }: { fact: Fact; act: (fn: () => Promise<unknown>) => void }) {
  const [value, setValue] = useState(fact.value);
  useEffect(() => setValue(fact.value), [fact.value]);
  const dirty = value !== fact.value;

  const input =
    fact.value_type === "boolean" ? (
      <select value={value} onChange={(e) => setValue(e.target.value)}>
        <option value="">{t("（未填）")}</option>
        <option value="Yes">Yes</option>
        <option value="No">No</option>
      </select>
    ) : (
      <input
        type={fact.value_type === "date" ? "date" : fact.value_type === "number" ? "number" : "text"}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        style={{ width: "100%" }}
      />
    );

  return (
    <tr>
      <td>
        {fact.question}
        <div className="muted">{fact.key}</div>
      </td>
      <td style={{ minWidth: 220 }}>{input}</td>
      <td>
        {fact.confirmed_at && !dirty ? (
          <span className="badge pass">{t("已确认")}</span>
        ) : (
          <span className="badge warn">{t("未确认")}</span>
        )}
        <div className="muted">{SOURCE_LABEL[fact.source]}</div>
      </td>
      <td>
        <div className="row">
          <button
            className="primary"
            disabled={!value.trim() || (!dirty && !!fact.confirmed_at)}
            onClick={() => act(() => api.patch(`/api/facts/${fact.id}`, { value, confirm: true }))}
          >
            {t("确认")}
          </button>
          <button onClick={() => act(() => api.del(`/api/facts/${fact.id}`))}>{t("删除")}</button>
        </div>
      </td>
    </tr>
  );
}
