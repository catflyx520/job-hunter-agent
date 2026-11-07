import { useEffect, useState } from "react";
import { api, JobPreferences } from "../api";

const SENIORITY = { junior: "Junior", mid: "Mid", senior: "Senior", staff_plus: "Staff+" };
const WORK_MODES = { onsite: "Onsite", hybrid: "Hybrid", remote: "Remote" };
const EMPLOYMENT = {
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
  contract_to_hire: "Contract-to-hire",
  c2c: "C2C",
  internship: "Internship",
};

function toggle(list: string[], v: string) {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

function TriState({ value, onChange }: { value: boolean | null; onChange: (v: boolean | null) => void }) {
  return (
    <select value={value === null ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? null : e.target.value === "true")}>
      <option value="">未填写</option>
      <option value="true">是</option>
      <option value="false">否</option>
    </select>
  );
}

export default function Preferences() {
  const [prefs, setPrefs] = useState<JobPreferences | null>(null);
  const [version, setVersion] = useState(0);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<{ data: JobPreferences; version: number }>("/api/preferences").then((r) => {
      setPrefs(r.data);
      setVersion(r.version);
    });
  }, []);

  if (!prefs) return null;
  const set = (patch: Partial<JobPreferences>) => setPrefs({ ...prefs, ...patch });
  const auth = prefs.work_authorization;

  const save = async () => {
    setError("");
    try {
      const r = await api.put<{ data: JobPreferences; version: number }>("/api/preferences", prefs);
      setPrefs(r.data);
      setVersion(r.version);
      setMsg(`已保存（第 ${r.version} 版）`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const moveLocation = (i: number, d: -1 | 1) => {
    const locs = [...prefs.locations];
    const j = i + d;
    if (j < 0 || j >= locs.length) return;
    [locs[i], locs[j]] = [locs[j], locs[i]];
    set({ locations: locs });
  };

  return (
    <>
      <h2>求职需求</h2>
      <p className="muted">目前版本：{version || "尚未保存"}。每次修改会加一版，匹配评分会记录用了哪一版。</p>

      <div className="card">
        <h3>目标职位</h3>
        <label>
          职位（一行一个，例如 Full-stack Engineer、Backend Engineer、AI Engineer）
          <textarea
            defaultValue={prefs.target_roles.join("\n")}
            onBlur={(e) => set({ target_roles: e.target.value.split("\n") })}
          />
        </label>
        <div className="row" style={{ marginTop: 8 }}>
          资历：
          {Object.entries(SENIORITY).map(([k, v]) => (
            <label key={k} className="inline">
              <input type="checkbox" checked={prefs.seniority.includes(k)} onChange={() => set({ seniority: toggle(prefs.seniority, k) })} />
              {v}
            </label>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>地点优先顺序</h3>
        {prefs.locations.map((loc, i) => (
          <div key={i} className="list-item">
            <span className="muted" style={{ width: 20 }}>{i + 1}.</span>
            <input value={loc} onChange={(e) => set({ locations: prefs.locations.map((x, j) => (j === i ? e.target.value : x)) })} />
            <button onClick={() => moveLocation(i, -1)}>↑</button>
            <button onClick={() => moveLocation(i, 1)}>↓</button>
            <button onClick={() => set({ locations: prefs.locations.filter((_, j) => j !== i) })}>✕</button>
          </div>
        ))}
        <button onClick={() => set({ locations: [...prefs.locations, ""] })}>新增地点</button>
        <p className="muted">例如：Los Angeles 都会区 → 南加 → 可在加州远程 → 可搬迁</p>
        <div className="row">
          工作方式：
          {Object.entries(WORK_MODES).map(([k, v]) => (
            <label key={k} className="inline">
              <input type="checkbox" checked={prefs.work_modes.includes(k)} onChange={() => set({ work_modes: toggle(prefs.work_modes, k) })} />
              {v}
            </label>
          ))}
        </div>
      </div>

      <div className="card">
        <h3>雇佣类型与薪资</h3>
        <div className="row">
          接受：
          {Object.entries(EMPLOYMENT).map(([k, v]) => (
            <label key={k} className="inline">
              <input
                type="checkbox"
                checked={prefs.employment_types.includes(k)}
                onChange={() => set({ employment_types: toggle(prefs.employment_types, k) })}
              />
              {v}
            </label>
          ))}
        </div>
        <div className="grid" style={{ marginTop: 10 }}>
          <label>
            最低年薪（USD）
            <input
              type="number"
              value={prefs.min_salary ?? ""}
              onChange={(e) => set({ min_salary: e.target.value === "" ? null : Number(e.target.value) })}
            />
          </label>
          <label>
            薪资期望规则
            <input value={prefs.salary_rule} placeholder="例如：取职位区间下段" onChange={(e) => set({ salary_rule: e.target.value })} />
          </label>
        </div>
        <label className="inline" style={{ marginTop: 10 }}>
          <input type="checkbox" checked={prefs.exclude_new_grad_only} onChange={(e) => set({ exclude_new_grad_only: e.target.checked })} />
          排除明确写 New Grad / 毕业年份限制的职位（只看职位内文，不单凭 Junior 等字样判断）
        </label>
      </div>

      <div className="card">
        <h3>工作授权</h3>
        <div className="grid">
          <label>
            已可在美国工作
            <TriState value={auth.authorized_in_us} onChange={(v) => set({ work_authorization: { ...auth, authorized_in_us: v } })} />
          </label>
          <label>
            现在需要 sponsorship
            <TriState value={auth.needs_sponsorship_now} onChange={(v) => set({ work_authorization: { ...auth, needs_sponsorship_now: v } })} />
          </label>
          <label>
            未来需要 sponsorship
            <TriState
              value={auth.needs_sponsorship_future}
              onChange={(v) => set({ work_authorization: { ...auth, needs_sponsorship_future: v } })}
            />
          </label>
        </div>
        <label style={{ marginTop: 10 }}>
          备注
          <input value={auth.note} onChange={(e) => set({ work_authorization: { ...auth, note: e.target.value } })} />
        </label>
      </div>

      <div className="card">
        <h3>搜索设置</h3>
        <p className="muted">要搜的网站在 M3（自动搜索）加入。</p>
        <div className="grid">
          <label>
            每个网站上限
            <input
              type="number"
              value={prefs.search.per_site_limit}
              onChange={(e) => set({ search: { ...prefs.search, per_site_limit: Number(e.target.value) } })}
            />
          </label>
          <label>
            总上限
            <input
              type="number"
              value={prefs.search.total_limit}
              onChange={(e) => set({ search: { ...prefs.search, total_limit: Number(e.target.value) } })}
            />
          </label>
        </div>
      </div>

      <div className="row">
        <button className="primary" onClick={save}>
          保存
        </button>
        {msg && <span className="muted">{msg}</span>}
      </div>
      {error && <p className="error">{error}</p>}
    </>
  );
}
