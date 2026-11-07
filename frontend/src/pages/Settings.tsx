import { useEffect, useState } from "react";
import { api, Capabilities, CliInfo, Provider, ProviderKind, TaskRoute } from "../api";
import CliLoginPanel from "./CliLogin";

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

export default function Settings() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [routes, setRoutes] = useState<TaskRoute[]>([]);
  const [cli, setCli] = useState<CliInfo | null>(null);
  const [error, setError] = useState("");
  const [testing, setTesting] = useState<string | null>(null);
  const [testMsg, setTestMsg] = useState<Record<string, string>>({});
  const [cliRefresh, setCliRefresh] = useState(0);

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

  const test = async (p: Provider) => {
    setTesting(p.id);
    try {
      const r = await api.post<{ ok: boolean; message: string; sample: string | null }>(`/api/providers/${p.id}/test`);
      setTestMsg({ ...testMsg, [p.id]: r.ok ? `✅ ${r.message}：${r.sample ?? ""}` : `❌ ${r.message}` });
    } finally {
      setTesting(null);
      load();
      if (p.kind === "claude_cli" || p.kind === "codex_cli") setCliRefresh((n) => n + 1);
    }
  };

  const toggleCap = async (p: Provider, cap: keyof Capabilities) => {
    await api.patch(`/api/providers/${p.id}`, { capabilities: { ...p.capabilities, [cap]: !p.capabilities[cap] } });
    load();
  };

  const remove = async (p: Provider) => {
    if (!confirm(`删除「${p.name}」？`)) return;
    try {
      await api.del(`/api/providers/${p.id}`);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

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

  return (
    <>
      <h2>模型设置</h2>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h3>已设定的连接</h3>
        {providers.length === 0 && <p className="muted">还没有任何连接。请在下方新增。</p>}
        {providers.map((p) => (
          <div key={p.id} className="card">
            <div className="row">
              <b>{p.name}</b>
              <span className="badge">{KINDS.find((k) => k.kind === p.kind)?.label}</span>
              <span className="muted">模型：{p.default_model}</span>
              {p.has_api_key && <span className="muted">key：••••{p.api_key_last4}</span>}
              {p.base_url && <span className="muted">{p.base_url}</span>}
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              {(Object.keys(CAP_LABELS) as (keyof Capabilities)[]).map((c) => (
                <label key={c} className="inline">
                  <input type="checkbox" checked={p.capabilities[c]} onChange={() => toggleCap(p, c)} />
                  {CAP_LABELS[c]}
                </label>
              ))}
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <button onClick={() => test(p)} disabled={testing === p.id}>
                {testing === p.id ? "测试中…" : "测试连接"}
              </button>
              <button onClick={() => remove(p)}>删除</button>
              <span className="muted">{testMsg[p.id] ?? (p.last_check_error ? `上次测试失败：${p.last_check_error}` : "")}</span>
            </div>
          </div>
        ))}
      </div>

      <AddProvider cli={cli} onAdded={load} />

      <CliLoginPanel onChange={setCli} refreshKey={cliRefresh} />

      <div className="card">
        <h3>任务路由</h3>
        <p className="muted">
          为不同任务指定模型（例如评分用便宜的模型、cover letter 用好的模型）。没有指定时，使用第一个启用的连接与它的预设模型；
          Embedding 必须明确指定（OpenAI、OpenAI 兼容端点或 Ollama）。
        </p>
        <table>
          <tbody>
            {routes.map((r) => (
              <RouteRow key={r.task} route={r} providers={providers} onSave={setRoute} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function RouteRow({
  route,
  providers,
  onSave,
}: {
  route: TaskRoute;
  providers: Provider[];
  onSave: (task: string, providerId: string, model: string) => void;
}) {
  const [pid, setPid] = useState(route.provider_id ?? "");
  const [model, setModel] = useState(route.model ?? "");
  useEffect(() => {
    setPid(route.provider_id ?? "");
    setModel(route.model ?? "");
  }, [route.provider_id, route.model]);
  return (
    <tr>
      <td style={{ width: 140 }}>{route.label}</td>
      <td>
        <select
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
      </td>
      <td>
        <input value={model} placeholder="模型名称" onChange={(e) => setModel(e.target.value)} />
      </td>
      <td>
        <button onClick={() => onSave(route.task, pid, model)} disabled={!!pid && !model}>
          保存
        </button>
      </td>
    </tr>
  );
}

function AddProvider({ cli, onAdded }: { cli: CliInfo | null; onAdded: () => void }) {
  const [kind, setKind] = useState<ProviderKind>("openai");
  const meta = KINDS.find((k) => k.kind === kind)!;
  const [name, setName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState(meta.model);
  const [error, setError] = useState("");
  const [models, setModels] = useState<string[]>([]);

  useEffect(() => {
    setModel(meta.model);
    setBaseUrl(kind === "ollama" ? "http://localhost:11434" : "");
    setModels([]);
  }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps

  const cliName = kind === "claude_cli" ? "claude" : kind === "codex_cli" ? "codex" : null;
  const cliStatus = cliName ? cli?.clis.find((c) => c.name === cliName) : null;

  const save = async () => {
    setError("");
    try {
      const p = await api.post<Provider>("/api/providers", {
        kind,
        name: name || meta.label,
        api_key: meta.needsKey ? apiKey : undefined,
        base_url: meta.needsUrl ? baseUrl : undefined,
        default_model: model,
      });
      setApiKey("");
      setName("");
      onAdded();
      if (kind === "ollama") {
        api.get<string[]>(`/api/providers/${p.id}/models`).then(setModels).catch(() => undefined);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="card">
      <h3>新增连接</h3>
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
          <input value={model} onChange={(e) => setModel(e.target.value)} list="model-options" />
          <datalist id="model-options">
            {models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </label>
      </div>
      {cliName && (
        <div style={{ marginTop: 10 }}>
          <p className="notice">{cli?.notice}</p>
          <p className="muted">
            {cliStatus?.available ? `✅ 已检测到 ${cliName}：${cliStatus.version}` : `❌ ${cliStatus?.error ?? "检测中…"}`}
            {" · "}登录状态与登录按钮在下方「本机 CLI 登录」。
          </p>
        </div>
      )}
      {meta.needsKey && <p className="muted">key 只加密保存在本机数据库；保存后只显示末四码。</p>}
      {error && <p className="error">{error}</p>}
      <button className="primary" onClick={save} disabled={!model || (meta.needsKey && !apiKey)}>
        新增
      </button>
    </div>
  );
}
