import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, Material } from "../api";
import { t } from "../i18n";
import { DraftList, DraftView, jobLabel, KIND_LABEL, MaterialKind } from "./MaterialsPanel";
import StylePanel from "./StylePanel";
import { Loading, Seg } from "./ui";

/** 材料历史：所有写过的 cover letter 与申请问答。要写新的，到职位详情页的「申请材料」。 */
export default function Materials() {
  const [history, setHistory] = useState<Material[] | null>(null);
  const [current, setCurrent] = useState<Material | null>(null);
  const [kind, setKind] = useState<"all" | MaterialKind>("all");
  const [error, setError] = useState("");
  const [styleKey, setStyleKey] = useState(0);

  const openRef = useRef<HTMLElement>(null);

  const refreshStyle = () => setStyleKey((k) => k + 1);
  const load = () => api.get<Material[]>("/api/materials").then(setHistory);
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);
  // 打开的草稿在「我的写法」下面，滚动到草稿那里
  useEffect(() => {
    if (current) openRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [current?.id]);

  const shown = (history ?? []).filter((m) => kind === "all" || m.kind === kind);
  const count = (k: "all" | MaterialKind) => (history ?? []).filter((m) => k === "all" || m.kind === k).length;

  return (
    <div className="stack">
      <div className="row between">
        <h2 style={{ margin: 0 }}>{t("材料历史")}</h2>
        <Seg<"all" | MaterialKind>
          label={t("材料类型")}
          value={kind}
          onChange={setKind}
          options={[
            { value: "all", label: t("全部 {n}", { n: count("all") }) },
            { value: "cover_letter", label: `${KIND_LABEL.cover_letter} ${count("cover_letter")}` },
            { value: "qa", label: `${KIND_LABEL.qa} ${count("qa")}` },
          ]}
        />
      </div>
      <p className="muted small" style={{ margin: 0 }}>
        {t("要写新的 cover letter 或申请问答，请到")} <Link to="/jobs">{t("职位")}</Link> {t("打开职位，在「申请材料」里生成。")}
      </p>
      {error && <p className="error">{error}</p>}
      <StylePanel kind={kind} reloadKey={styleKey} />

      {current && (
        <section className="card" ref={openRef}>
          <DraftView
            key={current.id}
            m={current}
            onSaved={(m) => (setCurrent(m), load(), refreshStyle())}
            onDeleted={() => (setCurrent(null), load(), refreshStyle())}
            onLearned={refreshStyle}
            header={
              <div className="row between" style={{ marginBottom: 8 }}>
                <b>{jobLabel(current)}</b>
                <span className="row" style={{ gap: 12 }}>
                  {current.job_id && <Link to={`/jobs/${current.job_id}?material=${current.kind}#materials`}>{t("到这个职位 →")}</Link>}
                  <button type="button" className="link" onClick={() => setCurrent(null)}>
                    {t("收起")}
                  </button>
                </span>
              </div>
            }
          />
        </section>
      )}

      <section className="card">
        {history === null && !error ? (
          <Loading />
        ) : shown.length === 0 ? (
          <p className="muted">{t("还没有草稿。到职位详情页的「申请材料」生成第一份。")}</p>
        ) : (
          <DraftList
            items={shown}
            activeId={current?.id}
            showJob
            onPick={setCurrent}
          />
        )}
      </section>
    </div>
  );
}
