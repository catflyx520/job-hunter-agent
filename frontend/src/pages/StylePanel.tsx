// 材料历史页的「我的写法」：显示从保存的修改里学到的规则，可删除、恢复、自己加、重新整理
import { FormEvent, useEffect, useState } from "react";
import { api, DEMO, KindStyle, LearnResult, StyleRule, StyleRules } from "../api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { t } from "../i18n";
import { KIND_LABEL } from "./labels";
import type { MaterialKind } from "./MaterialsPanel";
import { Spinner } from "./ui";

const KINDS: MaterialKind[] = ["cover_letter", "qa"];

function RuleList({ title, rules }: { title: string; rules: string[] }) {
  return (
    <div>
      {title}
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        {rules.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
    </div>
  );
}

/** 重新整理后的结果：新增、去掉了哪些规则。 */
export function LearnSummary({ result }: { result: LearnResult }) {
  const { added, dropped } = result;
  if (!added.length && !dropped.length) return <p className="muted small">{t("写法没有变化。")}</p>;
  return (
    <div className="notice small">
      <div>{t("这次学到：新增 {a} 条，去掉 {d} 条。", { a: added.length, d: dropped.length })}</div>
      {added.length > 0 && <RuleList title={t("新增：")} rules={added} />}
      {dropped.length > 0 && <RuleList title={t("去掉：")} rules={dropped} />}
    </div>
  );
}

function origin(r: StyleRule) {
  if (r.origin === "manual") return t("你加的");
  return r.source_count > 0 ? t("来自 {n} 份", { n: r.source_count }) : t("来源的修改已经不在");
}

function KindBlock({ kind, style, reload, onLearned }: { kind: MaterialKind; style: KindStyle; reload: () => void; onLearned: (s: KindStyle) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [learning, setLearning] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState<LearnResult | null>(null);

  const run = async (fn: () => Promise<void>) => {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const setStatus = (r: StyleRule, status: "active" | "removed") =>
    run(async () => {
      await api.patch(`/api/style-rules/${r.id}`, { status });
      reload();
    });
  const add = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim() || busy || DEMO) return;
    run(async () => {
      await api.post("/api/style-rules", { kind, text: text.trim() });
      setText("");
      reload();
    });
  };
  const learn = async () => {
    setLearning(true);
    await run(async () => {
      const r = await api.post<LearnResult>("/api/style-rules/learn", { kind });
      setSummary(r);
      onLearned(r.style);
    });
    setLearning(false);
  };

  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row between">
        <b>
          {KIND_LABEL[kind]} <span className="muted small">{t("从 {n} 份修改整理", { n: style.samples })}</span>
          {style.pending > 0 && <span className="muted small"> · {t("有 {n} 份修改还没整理", { n: style.pending })}</span>}
        </b>
        <Button variant="outline" size="sm" onClick={learn} disabled={style.samples === 0 || busy || DEMO}>
          {learning ? (
            <>
              <Spinner /> {t("整理中…")}
            </>
          ) : (
            t("重新整理")
          )}
        </Button>
      </div>
      <div role="status">
        {learning && <span className="sr-only">{t("整理中…")}</span>}
        {summary && <LearnSummary result={summary} />}
        {error && <p className="error">{error}</p>}
      </div>

      {style.rules.length === 0 ? (
        <p className="muted small">{t("还没有学到写法。在草稿里改好内容、按「保存修改」，这里就会出现。")}</p>
      ) : (
        <ul className="stack" style={{ gap: 6, margin: 0, paddingLeft: 18 }}>
          {style.rules.map((r) => (
            <li key={r.id}>
              <span className="row between" style={{ flexWrap: "wrap", gap: 4 }}>
                <span>
                  {r.text} <span className="muted small">· {origin(r)}</span>
                </span>
                <Button
                  variant="link"
                  size="sm"
                  onClick={() => setStatus(r, "removed")}
                  disabled={busy || DEMO}
                  aria-label={t("移除：{rule}", { rule: r.text })}
                >
                  {t("移除")}
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <form className="row" style={{ gap: 8, flexWrap: "wrap" }} onSubmit={add}>
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t("自己加一条…")}
          aria-label={t("自己加一条…")}
          maxLength={200}
          disabled={DEMO}
          className="flex-1"
        />
        <Button type="submit" variant="outline" size="sm" disabled={!text.trim() || busy || DEMO}>
          {t("加入")}
        </Button>
      </form>

      {style.removed.length > 0 && (
        <details>
          <summary className="muted small">{t("已删除 {n} 条（可以恢复）", { n: style.removed.length })}</summary>
          <ul className="stack" style={{ gap: 6, margin: "6px 0 0", paddingLeft: 18 }}>
            {style.removed.map((r) => (
              <li key={r.id}>
                <span className="row between" style={{ flexWrap: "wrap", gap: 4 }}>
                  <span className="muted">{r.text}</span>
                  <Button
                    variant="link"
                    size="sm"
                    onClick={() => setStatus(r, "active")}
                    disabled={busy || DEMO}
                    aria-label={t("恢复：{rule}", { rule: r.text })}
                  >
                    {t("恢复")}
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export default function StylePanel({ kind, reloadKey }: { kind: "all" | MaterialKind; reloadKey: number }) {
  const [rules, setRules] = useState<StyleRules | null>(null);
  const [error, setError] = useState("");

  const reload = () =>
    api
      .get<StyleRules>("/api/style-rules")
      .then((r) => {
        setRules(r);
        setError("");
      })
      .catch((e) => setError(e.message));
  useEffect(() => {
    reload();
  }, [reloadKey]);

  return (
    <section className="card stack" aria-label={t("我的写法")}>
      <div>
        <h3 style={{ margin: 0 }}>{t("我的写法")}</h3>
        <p className="muted small" style={{ margin: 0 }}>
          {t("程序从你保存的修改里整理出来的写法，写新草稿时会照着写。")}
        </p>
      </div>
      {error && <p className="error">{error}</p>}
      {rules &&
        KINDS.filter((k) => kind === "all" || kind === k).map((k) => (
          <KindBlock key={k} kind={k} style={rules[k]} reload={reload} onLearned={(s) => setRules((p) => p && { ...p, [k]: s })} />
        ))}
    </section>
  );
}
