import { useEffect, useRef, useState } from "react";
import { api, CliInfo, CliLogin, CliStatus } from "../api";

const LABEL = { claude: "Claude Code CLI", codex: "Codex CLI" };
const STATE_TEXT: Record<CliStatus["state"], { text: string; cls: string }> = {
  signed_in: { text: "已登录", cls: "pass" },
  signed_out: { text: "未登录", cls: "warn" },
  invalid: { text: "登录已失效", cls: "fail" },
  not_installed: { text: "未安装", cls: "fail" },
  unknown: { text: "状态不明", cls: "warn" },
};

/** 本机 CLI 的登录状态与页面一键登录。 */
export default function CliLoginPanel({
  onChange,
  refreshKey = 0,
}: {
  onChange?: (info: CliInfo) => void;
  refreshKey?: number; // 改变时重新查询登录状态（例如测试连接之后）
}) {
  const [info, setInfo] = useState<CliInfo | null>(null);
  const [login, setLogin] = useState<CliLogin | null>(null);
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const wasRunning = useRef(false);

  const refresh = () =>
    api.get<CliInfo>("/api/cli-status").then((i) => {
      setInfo(i);
      setLogin(i.login);
      onChange?.(i);
    });

  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // 登录进行中每秒拉一次状态；结束后重新检查登录状态
  useEffect(() => {
    if (!login?.running) {
      if (wasRunning.current) {
        wasRunning.current = false;
        refresh();
      }
      return;
    }
    wasRunning.current = true;
    const t = setInterval(() => {
      api.get<CliLogin | null>("/api/cli/login").then(setLogin).catch(() => undefined);
    }, 1000);
    return () => clearInterval(t);
  }, [login?.running]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const start = (name: string) =>
    act(async () => {
      setCode("");
      setLogin(await api.post<CliLogin>(`/api/cli/${name}/login`));
    });

  const submit = () =>
    act(async () => {
      const r = await api.post<{ status: string }>("/api/cli/login/code", { code });
      setCode("");
      setMsg(
        r.status === "submitted" ? "验证码已送出，等待 CLI 确认…" : r.status === "invalid" ? "验证码格式不对。" : "登录程序已结束，请重新开始。",
      );
    });

  const logout = (name: "claude" | "codex") =>
    act(async () => {
      if (!confirm(`登出本机 ${LABEL[name]}？这会影响你在终端使用这个 CLI。`)) return;
      const r = await api.post<{ ok: boolean; message: string }>(`/api/cli/${name}/logout`);
      setMsg(r.message);
      await refresh();
    });

  if (!info) return null;
  return (
    <div className="card">
      <h3>本机 CLI 登录</h3>
      <p className="notice">{info.notice}</p>
      <table>
        <tbody>
          {info.clis.map((c) => {
            const st = STATE_TEXT[c.state];
            return (
              <tr key={c.name}>
                <td style={{ width: 150 }}>
                  <b>{LABEL[c.name]}</b>
                  <div className="muted">{c.version ?? ""}</div>
                </td>
                <td>
                  <span className={`badge ${st.cls}`}>{st.text}</span>{" "}
                  {c.email && <span className="muted">{c.email}</span>}
                  {c.state === "invalid" && (
                    <div className="muted">CLI 显示已登录，但实际调用时回报 token 已失效，需要重新登录。</div>
                  )}
                  {c.state === "not_installed" && (
                    <div className="muted">
                      {c.error} 后端必须直接在本机执行（不能在 docker 容器里），才找得到你的 CLI。
                    </div>
                  )}
                </td>
                <td style={{ width: 200 }}>
                  {c.available && (
                    <div className="row">
                      <button className="primary" disabled={busy || !!login?.running} onClick={() => start(c.name)}>
                        {c.state === "signed_in" ? "重新登录" : "登录"}
                      </button>
                      {c.state !== "signed_out" && (
                        <button disabled={busy} onClick={() => logout(c.name)}>
                          登出
                        </button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {login && (
        <div className="card" style={{ marginTop: 12 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <b>登录 {LABEL[login.cli as "claude" | "codex"]}</b>
            {login.running && (
              <button onClick={() => act(async () => (await api.post("/api/cli/login/cancel"), setLogin(await api.get("/api/cli/login"))))}>
                取消
              </button>
            )}
          </div>
          <p>{login.message}</p>
          {login.url && login.running && (
            <p>
              1. 打开授权网址：{" "}
              <a href={login.url} target="_blank" rel="noopener noreferrer">
                {new URL(login.url).host} 授权页面 ↗
              </a>
            </p>
          )}
          {login.running && login.cli === "claude" && (
            <div className="row">
              2. 授权后如果页面显示验证码，贴到这里：
              <input value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" style={{ minWidth: 260 }} />
              <button className="primary" disabled={!code.trim() || busy} onClick={submit}>
                送出
              </button>
            </div>
          )}
          {login.running && login.cli === "codex" && <p className="muted">在浏览器完成授权后，这里会自动更新。</p>}
          <details>
            <summary className="muted">CLI 输出</summary>
            <pre className="evidence">{login.output}</pre>
          </details>
        </div>
      )}
      {msg && <p className="notice">{msg}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
