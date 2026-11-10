import { useEffect, useState } from "react";
import { api, Capabilities, CliStatus, Provider, ProviderKind, SearchSource, TaskRoute } from "../api";
import { CLI_LABEL, CLI_STATE, CliLoginState, LoginSteps, useCliLogin } from "./CliLogin";
import { ConfirmButton, Seg, Spinner } from "./ui";

const KINDS: { kind: ProviderKind; label: string; needsKey: boolean; needsUrl: boolean; model: string }[] = [
  { kind: "openai", label: "OpenAI API key", needsKey: true, needsUrl: false, model: "gpt-4o-mini" },
  { kind: "anthropic", label: "Anthropic API key", needsKey: true, needsUrl: false, model: "claude-haiku-5-5" },
  { kind: "openai_compatible", label: "OpenAI 兼容端点", needsKey: true, needsUrl: true, model: "" },
  { kind: "ollama", label: "Ollama（本地）", needsKey: false, needsUrl: true, model: "llama3.1" },
  { kind: "claude_cli", label: "本机 Claude Code CLI", needsKey: false, needsUrl: false, model: "default" },
  { kind: "codex_cli", label: "本机 Codex CLI", needsKey: false, needsUrl: false, model: "default" },
];
const CAP_LABELS: Record<keyof Capabilities, string> = {
  structured_output: "结构化输出",
  vision: "图片",
  web_search: "网络搜索",
  tool_calling: "工具调用",
};

const cliOf = (kind: ProviderKind): "claude" | "codex" | null => (kind === "claude_cli" ? "claude" : kind === "codex_cli" ? "codex" : null);

export default function Settings() {
  const [view, setView] = useState<"conn" | "routes" | "search">("conn");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [routes, setRoutes] = useState<TaskRoute[]>([]);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const [cliRefresh, setCliRefresh] = useState(0);
  const cli = useCliLogin(cliRefresh);

  const load = () =>
    Promise.all([api.get<Provider[]>("/api/providers"), api.get<TaskRoute[]>("/api/task-routes")])
      .then(([p, r]) => {
        setProviders(p);
        setRoutes(r);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  const setRoute = async (task: string, providerId: string, model: string) => {
    setError("");
    try {
      if (!providerId) await api.del(`/api/task-routes/${task}`);
      else await api.put(`/api/task-routes/${task}`, { provider_id: providerId, model });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const linked = new Set(providers.map((p) => cliOf(p.kind)).filter(Boolean));
  const unlinkedClis = (cli.info?.clis ?? []).filter((c) => !linked.has(c.name));

  return (
    <div className="stack">
      <section className="row between" aria-label="页面内容">
        <Seg
          label="模型连接"
          value={view}
          onChange={setView}
          options={[
            { value: "conn", label: "连接" },
            { value: "routes", label: "任务模型" },
            { value: "search", label: "搜索来源" },
          ]}
        />
        {view === "conn" && (
          <button type="button" className="primary" aria-expanded={adding} onClick={() => setAdding(!adding)}>
            {adding ? "收起" : "+ 新增连接"}
          </button>
        )}
      </section>
      {error && <p className="error">{error}</p>}

      {view === "conn" && (
        <>
          {adding && (
            <AddProvider
              cli={cli}
              onAdded={() => {
                setAdding(false);
                load();
              }}
            />
          )}
          <section className="card flush" aria-label="已设定的连接">
            {providers.length === 0 && unlinkedClis.length === 0 && <p className="muted" style={{ padding: "12px 24px" }}>还没有任何连接。</p>}
            {providers.map((p) => (
              <ProviderRow key={p.id} p={p} cli={cli} onChanged={load} onCliTested={() => setCliRefresh((n) => n + 1)} onError={setError} />
            ))}
            {unlinkedClis.map((c) => (
              <div className="conn" key={c.name}>
                <div className="conn-main">
                  <div className="conn-info">
                    <b>{CLI_LABEL[c.name]}</b>
                    <div className="muted">{c.version ?? "本机 CLI"} · 还没有添加为连接</div>
                  </div>
                  <CliActions c={c} state={cli} />
                </div>
                <LoginSteps cli={c.name} state={cli} />
              </div>
            ))}
            {(cli.msg || cli.error) && (
              <div style={{ padding: "10px 24px 0" }}>
                {cli.msg && <p className="notice">{cli.msg}</p>}
                {cli.error && <p className="error">{cli.error}</p>}
              </div>
            )}
            <div className="muted small" style={{ padding: "10px 24px" }}>
              API key 只加密保存在本机，保存后只显示末四码。{cli.info?.notice}
            </div>
          </section>
        </>
      )}

      {view === "routes" && (
        <section className="card" aria-label="任务模型" style={{ paddingTop: 4 }}>
          {routes.map((r) => (
            <RouteRow key={r.task} route={r} providers={providers} onSave={setRoute} />
          ))}
          <p className="muted small" style={{ marginBottom: 0 }}>
            未指定时用第一个启用的连接及其预设模型。Embedding 必须指定 OpenAI、OpenAI 兼容端点或 Ollama。
          </p>
        </section>
      )}

      {view === "search" && <SearchSourceCard key={routes.map((r) => r.provider_id).join()} />}
    </div>
  );
}

function CliActions({ c, state }: { c: CliStatus; state: CliLoginState }) {
  const st = CLI_STATE[c.state];
  return (
    <>
      <div className={`conn-status ${st.cls}`} title={c.state === "not_installed" ? `${c.error ?? ""} 后端必须直接在本机执行，才找得到你的 CLI。` : c.email ?? undefined}>
        {st.text}
      </div>
      {c.available && (
        <button type="button" className="btn accent" disabled={state.busy || !!state.login?.running} onClick={() => state.start(c.name)}>
          {c.state === "signed_in" ? "重新登录" : "登录"}
        </button>
      )}
    </>
  );
}

function ProviderRow({
  p,
  cli,
  onChanged,
  onCliTested,
  onError,
}: {
  p: Provider;
  cli: CliLoginState;
  onChanged: () => void;
  onCliTested: () => void;
  onError: (m: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const cliName = cliOf(p.kind);
  const cs = cliName ? cli.info?.clis.find((c) => c.name === cliName) : undefined;

  const test = async () => {
    setTesting(true);
    try {
      const r = await api.post<{ ok: boolean; message: string; sample: string | null }>(`/api/providers/${p.id}/test`);
      setResult({ ok: r.ok, text: r.message });
    } catch (e) {
      setResult({ ok: false, text: (e as Error).message });
    } finally {
      setTesting(false);
      onChanged();
      if (cliName) onCliTested();
    }
  };

  const toggleCap = async (cap: keyof Capabilities) => {
    try {
      await api.patch(`/api/providers/${p.id}`, { capabilities: { ...p.capabilities, [cap]: !p.capabilities[cap] } });
      onChanged();
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const remove = async () => {
    try {
      await api.del(`/api/providers/${p.id}`);
      onChanged();
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const meta = [KINDS.find((k) => k.kind === p.kind)?.label, p.base_url, p.has_api_key ? `key ••••${p.api_key_last4}` : null, `模型 ${p.default_model}`].filter(Boolean).join(" · ");
  const status = result
    ? { cls: result.ok ? "pass" : "fail", text: result.ok ? "连接正常" : `测试失败：${result.text}` }
    : p.last_check_error
      ? { cls: "fail", text: `上次测试失败：${p.last_check_error}` }
      : !cs && p.last_checked_at
        ? { cls: "pass", text: "连接正常" }
        : null;

  return (
    <div className="conn">
      <div className="conn-main">
        <div className="conn-info">
          <b>{p.name}</b>
          <div className="muted">{meta}</div>
        </div>
        {status && <div className={`conn-status ${status.cls}`}>{status.text}</div>}
        {cs && <CliActions c={cs} state={cli} />}
        <button type="button" onClick={test} disabled={testing}>
          {testing ? <><Spinner />测试中…</> : "测试"}
        </button>
        <button type="button" className="link" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "收起" : "详情"}
        </button>
      </div>
      {cliName && <LoginSteps cli={cliName} state={cli} />}
      {open && (
        <div className="conn-extra">
          <div className="row">
            {(Object.keys(CAP_LABELS) as (keyof Capabilities)[]).map((c) => (
              <label key={c} className="inline" style={{ marginRight: 12 }}>
                <input type="checkbox" checked={p.capabilities[c]} onChange={() => toggleCap(c)} />
                {CAP_LABELS[c]}
              </label>
            ))}
          </div>
          <div className="row">
            {cs && cs.available && cs.state !== "signed_out" && (
              <ConfirmButton
                className="link"
                disabled={cli.busy}
                message="登出后，你在终端使用这个 CLI 也要重新登录。"
                confirmLabel="确定登出"
                onConfirm={() => cli.logout(cs.name)}
              >
                登出这个 CLI
              </ConfirmButton>
            )}
            <ConfirmButton className="link danger" message={`删除「${p.name}」？`} onConfirm={remove}>
              删除连接
            </ConfirmButton>
          </div>
        </div>
      )}
    </div>
  );
}

function SearchSourceCard() {
  const [src, setSrc] = useState<SearchSource | null>(null);
  const [kind, setKind] = useState<"none" | "tavily" | "searxng">("none");
  const [key, setKey] = useState("");
  const [base, setBase] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<SearchSource>("/api/search/source")
      .then((s) => {
        setSrc(s);
        setKind(s.integration?.kind ?? "none");
        setBase(s.integration?.base_url ?? "");
      })
      .catch((e) => setError(e.message));
  }, []);

  const save = async () => {
    setError("");
    setMsg("");
    try {
      const s = await api.put<SearchSource>("/api/search/integration", { kind, api_key: key || null, base_url: base || null });
      setSrc(s);
      setKey("");
      setMsg("已保存。");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const test = async () => {
    setError("");
    setMsg("测试中…");
    try {
      const r = await api.post<{ results: number }>("/api/search/integration/test");
      setMsg(`连线正常，测试查询回传 ${r.results} 笔结果。`);
    } catch (e) {
      setMsg("");
      setError((e as Error).message);
    }
  };

  const options = [
    ["none", "模型自带搜索", "使用“职位搜索”任务的模型"],
    ["tavily", "Tavily", "搜索 API，有免费额度"],
    ["searxng", "SearXNG", "自己架设的搜索服务"],
  ] as const;

  return (
    <section className="card stack" aria-label="职位搜索来源">
      <div className="muted">LinkedIn、Indeed、Built In 等网站要先用网页搜索找到公开职位页；Greenhouse、Lever、Ashby 走官方公开 API，不需要搜索来源。Claude CLI 只开放 WebSearch 一个工具，其他任务仍关闭所有工具。</div>
      <div className="source-options" role="radiogroup" aria-label="搜索来源">
        {options.map(([k, label, note]) => (
          <button key={k} type="button" role="radio" aria-checked={kind === k} className={`source-option${kind === k ? " on" : ""}`} onClick={() => setKind(k)}>
            <b style={{ display: "block" }}>{label}</b>
            <span className="muted small">{note}</span>
          </button>
        ))}
      </div>
      {kind === "tavily" && (
        <input
          type="password"
          aria-label="Tavily API key"
          autoComplete="off"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder={src?.integration?.kind === "tavily" && src.integration.key_last4 ? `已保存，末四码 ${src.integration.key_last4}；留空则沿用` : "Tavily API key（tvly-…）"}
        />
      )}
      {kind === "searxng" && <input aria-label="SearXNG 网址" value={base} onChange={(e) => setBase(e.target.value)} placeholder="SearXNG 网址，例如 http://localhost:8888（需开启 json 格式）" />}
      <div className="row">
        <button type="button" className="primary" onClick={save}>
          保存
        </button>
        {src?.integration && (
          <button type="button" onClick={test}>
            测试连线
          </button>
        )}
        {src && <span className={src.ready ? "muted" : "error"}>目前：{src.label}</span>}
      </div>
      {msg && <p className="notice">{msg}</p>}
      {error && <p className="error">{error}</p>}
    </section>
  );
}

function RouteRow({ route, providers, onSave }: { route: TaskRoute; providers: Provider[]; onSave: (task: string, providerId: string, model: string) => void }) {
  const [pid, setPid] = useState(route.provider_id ?? "");
  const [model, setModel] = useState(route.model ?? "");
  useEffect(() => {
    setPid(route.provider_id ?? "");
    setModel(route.model ?? "");
  }, [route.provider_id, route.model]);
  return (
    <div className="route-row">
      <div style={{ fontWeight: 500 }}>{route.label}</div>
      <select
        aria-label={`${route.label}的连接`}
        value={pid}
        onChange={(e) => {
          setPid(e.target.value);
          const p = providers.find((x) => x.id === e.target.value);
          if (p && !model) setModel(p.default_model);
        }}
      >
        <option value="">（未指定）</option>
        {providers.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      <input aria-label={`${route.label}的模型`} value={model} placeholder="模型名称" onChange={(e) => setModel(e.target.value)} />
      <button type="button" onClick={() => onSave(route.task, pid, model)} disabled={!!pid && !model}>
        保存
      </button>
    </div>
  );
}

function AddProvider({ cli, onAdded }: { cli: CliLoginState; onAdded: () => void }) {
  const [kind, setKind] = useState<ProviderKind>("openai");
  const meta = KINDS.find((k) => k.kind === kind)!;
  const [name, setName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState(meta.model);
  const [error, setError] = useState("");

  useEffect(() => {
    setModel(meta.model);
    setBaseUrl(kind === "ollama" ? "http://localhost:11434" : "");
  }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps

  const cliName = cliOf(kind);
  const cliStatus = cliName ? cli.info?.clis.find((c) => c.name === cliName) : null;

  const save = async () => {
    setError("");
    try {
      await api.post<Provider>("/api/providers", {
        kind,
        name: name || meta.label,
        api_key: meta.needsKey ? apiKey : undefined,
        base_url: meta.needsUrl ? baseUrl : undefined,
        default_model: model,
      });
      setApiKey("");
      setName("");
      onAdded();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <section className="card stack" aria-label="新增连接">
      <div className="grid">
        <label>
          类型
          <select value={kind} onChange={(e) => setKind(e.target.value as ProviderKind)}>
            {KINDS.map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          显示名称
          <input value={name} placeholder={meta.label} onChange={(e) => setName(e.target.value)} />
        </label>
        {meta.needsUrl && (
          <label>
            Base URL
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1" />
          </label>
        )}
        {meta.needsKey && (
          <label>
            API key
            <input type="password" autoComplete="off" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          </label>
        )}
        <label>
          预设模型
          <input value={model} onChange={(e) => setModel(e.target.value)} />
        </label>
      </div>
      {cliName && (
        <div className="muted">
          {cliStatus?.available ? `已检测到 ${cliName}：${cliStatus.version}` : `${cliStatus?.error ?? "检测中…"}`} · 添加后在列表里登录。{cli.info?.notice}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      <div className="row">
        <button type="button" className="primary" onClick={save} disabled={!model || (meta.needsKey && !apiKey)}>
          新增
        </button>
        {meta.needsKey && <span className="muted small">key 只加密保存在本机数据库；保存后只显示末四码。</span>}
      </div>
    </section>
  );
}
