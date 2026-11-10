import { useEffect, useRef, useState } from "react";
import { api, CliInfo, CliLogin, CliStatus } from "../api";
import { t } from "../i18n";

export const CLI_LABEL = { claude: "Claude Code CLI", codex: "Codex CLI" };
export const CLI_STATE: Record<CliStatus["state"], { text: string; cls: string }> = {
  signed_in: { text: t("已登录"), cls: "pass" },
  signed_out: { text: t("未登录"), cls: "warn" },
  invalid: { text: t("登录已失效"), cls: "fail" },
  not_installed: { text: t("未安装"), cls: "fail" },
  unknown: { text: t("状态不明"), cls: "warn" },
};

/** 本机 CLI 的登录状态与页面一键登录。refreshKey 改变时重新查询（例如测试连接之后）。 */
export function useCliLogin(refreshKey: number) {
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
    });

  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // 登录进行中每秒拉一次状态；结束后重新检查登录状态
  useEffect(() => {
    if (!login?.running) {
      if (wasRunning.current) {
        wasRunning.current = false;
        void refresh();
      }
      return;
    }
    wasRunning.current = true;
    const timer = setInterval(() => {
      api.get<CliLogin | null>("/api/cli/login").then(setLogin).catch(() => undefined);
    }, 1000);
    return () => clearInterval(timer);
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
      setMsg(r.status === "submitted" ? t("验证码已送出，等待 CLI 确认…") : r.status === "invalid" ? t("验证码格式不对。") : t("登录程序已结束，请重新开始。"));
    });

  const cancel = () =>
    act(async () => {
      await api.post("/api/cli/login/cancel");
      setLogin(await api.get<CliLogin | null>("/api/cli/login"));
    });

  const logout = (name: "claude" | "codex") =>
    act(async () => {
      const r = await api.post<{ ok: boolean; message: string }>(`/api/cli/${name}/logout`);
      setMsg(r.message);
      await refresh();
    });

  return { info, login, code, setCode, msg, error, busy, start, submit, cancel, logout };
}

export type CliLoginState = ReturnType<typeof useCliLogin>;

/** 登录步骤：显示在对应连接行的下方。 */
export function LoginSteps({ cli, state }: { cli: "claude" | "codex"; state: CliLoginState }) {
  const { login, code, setCode, busy, submit, cancel } = state;
  if (!login || login.cli !== cli) return null;
  return (
    <div className="conn-extra login">
      <div className="row between">
        <b>{t("登录 {cli}", { cli: CLI_LABEL[cli] })}</b>
        {login.running && (
          <button type="button" className="link" onClick={cancel}>
            {t("取消登录")}
          </button>
        )}
      </div>
      <div>{login.message}</div>
      {login.url && login.running && (
        <div>
          1.{" "}
          <a href={login.url} target="_blank" rel="noopener noreferrer">
            {t("打开 {host} 授权页面 ↗", { host: new URL(login.url).host })}
          </a>
        </div>
      )}
      {login.running && cli === "claude" && (
        <div className="row">
          <span>{t("2. 授权后如果显示验证码，贴到这里")}</span>
          <input aria-label={t("验证码")} value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" style={{ flex: "1 1 200px", minWidth: 0 }} />
          <button type="button" className="primary" disabled={!code.trim() || busy} onClick={submit}>
            {t("送出")}
          </button>
        </div>
      )}
      {login.running && cli === "codex" && <div className="muted">{t("2. 在浏览器完成授权后，这里会自动更新。")}</div>}
      <details>
        <summary className="muted">{t("CLI 输出")}</summary>
        <pre className="evidence">{login.output}</pre>
      </details>
    </div>
  );
}
