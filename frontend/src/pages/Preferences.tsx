import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, JobPreferences, VisaStatus } from "../api";
import RoleTags from "./RoleTags";
import { Loading, Seg } from "./ui";

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

function Pills({ options, selected, onChange }: { options: Record<string, string>; selected: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="chips">
      {Object.entries(options).map(([k, v]) => (
        <button key={k} type="button" aria-pressed={selected.includes(k)} className={`pill${selected.includes(k) ? " on" : ""}`} onClick={() => onChange(toggle(selected, k))}>
          {v}
        </button>
      ))}
    </div>
  );
}

const VISA_OPTIONS: [VisaStatus, string][] = [
  ["us_citizen", "美国公民"],
  ["green_card", "绿卡"],
  ["h1b", "H-1B"],
  ["opt", "OPT / STEM OPT"],
  ["other", "其他"],
];
// 与后端 STATUS_FLAGS 一致：(已可工作, 现在需要 sponsorship, 未来需要 sponsorship)
const STATUS_FLAGS: Partial<Record<VisaStatus, [boolean, boolean, boolean]>> = {
  us_citizen: [true, false, false],
  green_card: [true, false, false],
  h1b: [true, true, true],
  opt: [true, false, true],
};
const STATUS_NOTE: Record<VisaStatus, string> = {
  us_citizen: "不需要 sponsorship，不会因签证条件排除职位。",
  green_card: "不需要 sponsorship。只写「公民」的职位和写「公民或绿卡」的职位目前分不开，都会保留，请自己看 JD。",
  h1b: "换雇主需要新雇主递 H-1B transfer：会排除写明不提供 sponsorship 的职位，和只收公民 / 绿卡的职位。",
  opt: "现在可以工作，之后需要 H-1B：会排除写明不提供 sponsorship 的职位，和只收公民 / 绿卡的职位。",
  other: "请在下面手动填写三项，排除规则按这三项判断。",
};

function TriState({ label, value, onChange }: { label: string; value: boolean | null; onChange: (v: boolean | null) => void }) {
  const options: [boolean | null, string][] = [
    [null, "未填写"],
    [true, "是"],
    [false, "否"],
  ];
  return (
    <div className="auth-row">
      <span>{label}</span>
      <div className="seg" role="radiogroup" aria-label={label}>
        {options.map(([v, text]) => (
          <button key={text} type="button" role="radio" aria-checked={value === v} className={value === v ? "on" : ""} onClick={() => onChange(v)}>
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function Preferences() {
  const [prefs, setPrefs] = useState<JobPreferences | null>(null);
  const [saved, setSaved] = useState("");
  const [version, setVersion] = useState(0);
  const [justSaved, setJustSaved] = useState(false);
  const [error, setError] = useState("");
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "blacklist" ? "blacklist" : "prefs";

  useEffect(() => {
    api
      .get<{ data: JobPreferences; version: number }>("/api/preferences")
      .then((r) => {
        setPrefs(r.data);
        setSaved(JSON.stringify(r.data));
        setVersion(r.version);
      })
      .catch((e) => setError(e.message));
  }, []);

  if (!prefs) return error ? <p className="error">{error}</p> : <Loading />;

  const set = (patch: Partial<JobPreferences>) => {
    setJustSaved(false);
    setPrefs({ ...prefs, ...patch });
  };
  const auth = prefs.work_authorization;
  const dirty = JSON.stringify(prefs) !== saved;

  const save = async () => {
    setError("");
    try {
      const r = await api.put<{ data: JobPreferences; version: number }>("/api/preferences", prefs);
      setPrefs(r.data);
      setSaved(JSON.stringify(r.data));
      setVersion(r.version);
      setJustSaved(true);
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
    <form className="card flush" onSubmit={(e) => e.preventDefault()}>
      <div className="form-head">
        <span className="muted">{version ? `第 ${version} 版` : "尚未保存"} · 每次保存新增一版，匹配评分会记录用了哪一版</span>
        <button type="button" className="primary" onClick={save} disabled={!dirty}>
          {justSaved ? "已保存" : dirty ? `保存为第 ${version + 1} 版` : "保存"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <div style={{ padding: "12px 24px 0" }}>
        <Seg<"prefs" | "blacklist">
          label="求职需求分页"
          value={tab}
          onChange={(t) => setParams(t === "blacklist" ? { tab: t } : {})}
          options={[
            { value: "prefs", label: "求职条件" },
            { value: "blacklist", label: `黑名单 ${prefs.blacklist.companies.length + prefs.blacklist.titles.length}` },
          ]}
        />
      </div>

      {tab === "blacklist" ? (
        <BlacklistTab value={prefs.blacklist} onChange={(blacklist) => set({ blacklist })} />
      ) : (
      <>
      <div className="form-group">
        <div className="form-name">目标职位</div>
        <div>
          <RoleTags roles={prefs.target_roles} paused={prefs.paused_roles} onChange={(target_roles, paused_roles) => set({ target_roles, paused_roles })} />
          <p className="muted small" style={{ margin: "6px 0 0" }}>
            点 tag 切换启用 / 停用：停用的职位保留在清单里，但搜索和评分不会用。
          </p>
        </div>
        <div className="form-name">资历</div>
        <Pills options={SENIORITY} selected={prefs.seniority} onChange={(v) => set({ seniority: v })} />
      </div>

      <div className="form-group">
        <div className="form-name">
          地点优先顺序
          <div className="muted small" style={{ fontWeight: 400 }}>
            上面的先看
          </div>
        </div>
        <div>
          {prefs.locations.map((loc, i) => (
            <div key={i} className="list-item" style={{ alignItems: "center" }}>
              <span className="muted" style={{ width: 20, textAlign: "center" }}>
                {i + 1}
              </span>
              <input aria-label={`第 ${i + 1} 优先地点`} value={loc} onChange={(e) => set({ locations: prefs.locations.map((x, j) => (j === i ? e.target.value : x)) })} />
              <button type="button" aria-label="上移" disabled={i === 0} onClick={() => moveLocation(i, -1)} style={{ padding: 0, width: 44 }}>
                ↑
              </button>
              <button type="button" aria-label="下移" disabled={i === prefs.locations.length - 1} onClick={() => moveLocation(i, 1)} style={{ padding: 0, width: 44 }}>
                ↓
              </button>
              <button type="button" aria-label="删除地点" onClick={() => set({ locations: prefs.locations.filter((_, j) => j !== i) })} style={{ padding: 0, width: 44 }}>
                ×
              </button>
            </div>
          ))}
          <button type="button" className="link" onClick={() => set({ locations: [...prefs.locations, ""] })}>
            + 新增地点
          </button>
        </div>
        <div className="form-name">工作方式</div>
        <Pills options={WORK_MODES} selected={prefs.work_modes} onChange={(v) => set({ work_modes: v })} />
      </div>

      <div className="form-group">
        <div className="form-name">雇佣类型</div>
        <Pills options={EMPLOYMENT} selected={prefs.employment_types} onChange={(v) => set({ employment_types: v })} />
        <div className="form-name">薪资</div>
        <div className="grid">
          <label>
            最低年薪（USD）
            <input type="number" value={prefs.min_salary ?? ""} onChange={(e) => set({ min_salary: e.target.value === "" ? null : Number(e.target.value) })} />
          </label>
          <label>
            薪资期望规则
            <input value={prefs.salary_rule} placeholder="例如：取职位区间下段" onChange={(e) => set({ salary_rule: e.target.value })} />
          </label>
        </div>
        <div className="form-name">New Grad</div>
        <label className="inline">
          <input type="checkbox" checked={prefs.exclude_new_grad_only} onChange={(e) => set({ exclude_new_grad_only: e.target.checked })} />
          <span>排除明确写 New Grad / 毕业年份限制的职位（只看职位内文，不单凭 Junior 等字样判断）</span>
        </label>
      </div>

      <div className="form-group">
        <div className="form-name">身份与工作授权</div>
        <div>
          <div className="auth-row">
            <span>目前身份</span>
            <div className="seg" role="radiogroup" aria-label="目前身份">
              {VISA_OPTIONS.map(([v, text]) => (
                <button
                  key={v}
                  type="button"
                  role="radio"
                  aria-checked={auth.status === v}
                  className={auth.status === v ? "on" : ""}
                  onClick={() => {
                    const f = STATUS_FLAGS[v];
                    set({
                      work_authorization: f
                        ? { ...auth, status: v, authorized_in_us: f[0], needs_sponsorship_now: f[1], needs_sponsorship_future: f[2] }
                        : { ...auth, status: v },
                    });
                  }}
                >
                  {text}
                </button>
              ))}
            </div>
          </div>
          <p className="muted small" style={{ margin: "4px 0 8px" }}>
            {auth.status ? STATUS_NOTE[auth.status] : "选了身份，搜索时会自动排除和你身份不合的职位（被排除的仍保留在「被排除」分组，附原因）。"}
          </p>
          {(() => {
            const locked = !!auth.status && auth.status !== "other";
            const hint = locked ? "由身份自动决定；要手动调整请选「其他」" : undefined;
            return (
              <div title={hint} style={locked ? { opacity: 0.6, pointerEvents: "none" } : undefined}>
                <TriState label="已可在美国工作" value={auth.authorized_in_us} onChange={(v) => set({ work_authorization: { ...auth, authorized_in_us: v } })} />
                <TriState label="现在需要 sponsorship" value={auth.needs_sponsorship_now} onChange={(v) => set({ work_authorization: { ...auth, needs_sponsorship_now: v } })} />
                <TriState label="未来需要 sponsorship" value={auth.needs_sponsorship_future} onChange={(v) => set({ work_authorization: { ...auth, needs_sponsorship_future: v } })} />
              </div>
            );
          })()}
          <input aria-label="工作授权备注" placeholder="备注（选填）" value={auth.note} onChange={(e) => set({ work_authorization: { ...auth, note: e.target.value } })} style={{ width: "100%" }} />
        </div>
      </div>

      <div className="form-group">
        <div className="form-name">搜索总上限</div>
        <div className="row">
          <input aria-label="搜索总上限" type="number" value={prefs.search.total_limit} onChange={(e) => set({ search: { ...prefs.search, total_limit: Number(e.target.value) } })} style={{ width: 96 }} />
          <span className="muted">
            每次搜索最多处理几个职位，每个约 20–40 秒。网站与单站上限在<Link to="/jobs">职位页</Link>的“来源”里设定。
          </span>
        </div>
      </div>
      </>
      )}
    </form>
  );
}

/** 黑名单分页：公司、职位两张清单，改完按上面的「保存」。 */
function BlacklistTab({ value, onChange }: { value: JobPreferences["blacklist"]; onChange: (v: JobPreferences["blacklist"]) => void }) {
  return (
    <>
      <p className="muted small" style={{ margin: "12px 24px 0" }}>
        黑名单里的公司和职位：搜索时直接排除（放进「被排除」并写明原因，不花时间评分）。在职位卡上按「拉黑」加入时，已存的相符职位会一起移到「已删除」。
      </p>
      <BlacklistList
        name="公司"
        hint="按公司名称比对，Inc.、LLC 等后缀和大小写不影响。"
        placeholder="例如 Acme Staffing，按 Enter 添加"
        items={value.companies}
        onChange={(companies) => onChange({ ...value, companies })}
      />
      <BlacklistList
        name="职位"
        hint="职称里含这组词就算，例如「Sales Engineer」会挡掉「Senior Sales Engineer, West」。"
        placeholder="例如 Sales Engineer，按 Enter 添加"
        items={value.titles}
        onChange={(titles) => onChange({ ...value, titles })}
      />
    </>
  );
}

function BlacklistList({ name, hint, placeholder, items, onChange }: { name: string; hint: string; placeholder: string; items: string[]; onChange: (v: string[]) => void }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim();
    if (v && !items.some((x) => x.toLowerCase() === v.toLowerCase())) onChange([...items, v]);
    setDraft("");
  };
  return (
    <div className="form-group">
      <div className="form-name">{name}</div>
      <div>
        <div className="chips">
          {items.map((x) => (
            <span className="chip blocked" key={x}>
              {x}
              <button type="button" aria-label={`从黑名单移除 ${x}`} title="从黑名单移除（已删除的职位不会自动还原）" onClick={() => onChange(items.filter((y) => y !== x))}>
                ×
              </button>
            </span>
          ))}
          {items.length === 0 && <span className="muted">还没有。</span>}
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <input
            aria-label={`新增黑名单${name}`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
            placeholder={placeholder}
            style={{ flex: "1 1 240px", minWidth: 0 }}
          />
          <button type="button" onClick={add} disabled={!draft.trim()}>
            添加
          </button>
        </div>
        <p className="muted small" style={{ margin: "6px 0 0" }}>{hint}</p>
      </div>
    </div>
  );
}
