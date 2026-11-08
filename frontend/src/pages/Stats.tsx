import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, JobSummary } from "../api";
import { StatusSelect } from "./ApplicationControl";
import { APP_STATUS, RECOMMENDATION, SPONSOR_STATUS, WORK_MODE, salary, show } from "./labels";

interface StatsData {
  totals: Record<string, number | null>;
  funnel: { stage: string; label: string; count: number }[];
  application_status: Record<string, number>;
  sponsorship_policy: Record<string, number>;
  sponsor_status: Record<string, number>;
  location_tier: Record<string, number>;
  work_mode: Record<string, number>;
  exclusions: { code: string; label: string; count: number }[];
  sources: { site: string; name: string; found: number; kept: number; applied: number; interviews: number }[];
  easy_apply: Record<string, number>;
  salary: Record<string, number>;
  score: Record<string, number>;
  recommendation: Record<string, number>;
  trend: Record<"day" | "week", { date: string; applied: number; interviewing: number; other: number }[]>;
  backlog: { saved_not_applied: number; applied_no_update: number; stale_days: number };
}

interface Options {
  companies: { id: string; name: string }[];
  sites: { id: string; name: string }[];
  runs: string[];
}

type FilterKey = "company" | "site" | "run" | "location_tier" | "work_mode" | "status" | "date_from" | "date_to";
type Filters = Partial<Record<FilterKey, string>>;

interface Bar {
  key: string;
  label: string;
  count: number;
}

const POLICY: Record<string, string> = { explicit_yes: "写明提供", unclear: "没写（不明）", explicit_no: "写明不提供" };
const SALARY_ORDER = ["< $80k", "$80k–100k", "$100k–130k", "$130k–160k", "$160k–200k", "≥ $200k", "unknown"];
const SCORE_ORDER = ["75–100", "55–74", "40–54", "0–39", "none"];

function qs(f: Filters, extra: Record<string, string> = {}) {
  const p = new URLSearchParams();
  Object.entries({ ...f, ...extra }).forEach(([k, v]) => v && p.set(k, v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

function bars(rec: Record<string, number>, label: (k: string) => string, order?: string[]): Bar[] {
  const keys = order ? order.filter((k) => k in rec) : Object.keys(rec);
  return keys.map((k) => ({ key: k, label: label(k), count: rec[k] }));
}

export default function Stats() {
  const [filters, setFilters] = useState<Filters>({});
  const [data, setData] = useState<StatsData | null>(null);
  const [opts, setOpts] = useState<Options | null>(null);
  const [locations, setLocations] = useState<string[]>([]);
  const [unit, setUnit] = useState<"day" | "week">("day");
  const [drill, setDrill] = useState<{ title: string; dim: string; value: string } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Options>("/api/stats/options").then(setOpts).catch(() => undefined);
    api
      .get<{ data: { locations: string[] } }>("/api/preferences")
      .then((p) => setLocations(p.data.locations))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    setError("");
    api
      .get<StatsData>(`/api/stats${qs(filters)}`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [filters]);

  const tierLabel = useCallback(
    (k: string) => (k === "none" ? "不在你的地点清单" : `第 ${k} 优先${locations[Number(k) - 1] ? `（${locations[Number(k) - 1]}）` : ""}`),
    [locations],
  );

  const pick = (title: string, dim: string, value: string) => setDrill({ title, dim, value });
  const setF = (k: FilterKey, v: string) => {
    setDrill(null);
    setFilters((f) => ({ ...f, [k]: v || undefined }));
  };

  return (
    <>
      <h2>投递统计</h2>
      <p className="muted">
        数字来自你在职位上标记的状态，以及搜索批次的结果。分数是契合度估计，不是录取机率。点任一长条可以看到对应的职位。
      </p>
      {error && <p className="error">{error}</p>}

      <div className="card">
        <div className="row">
          <select value={filters.company ?? ""} onChange={(e) => setF("company", e.target.value)} aria-label="公司">
            <option value="">所有公司</option>
            {opts?.companies.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <select value={filters.site ?? ""} onChange={(e) => setF("site", e.target.value)} aria-label="来源网站">
            <option value="">所有来源</option>
            {opts?.sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <select value={filters.run ?? ""} onChange={(e) => setF("run", e.target.value)} aria-label="搜索批次">
            <option value="">所有批次</option>
            {opts?.runs.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <select value={filters.location_tier ?? ""} onChange={(e) => setF("location_tier", e.target.value)} aria-label="地点">
            <option value="">所有地点</option>
            {locations.map((_, i) => (
              <option key={i} value={String(i + 1)}>
                {tierLabel(String(i + 1))}
              </option>
            ))}
            <option value="none">不在你的地点清单</option>
          </select>
          <select value={filters.work_mode ?? ""} onChange={(e) => setF("work_mode", e.target.value)} aria-label="工作方式">
            <option value="">所有工作方式</option>
            {Object.entries(WORK_MODE).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <select value={filters.status ?? ""} onChange={(e) => setF("status", e.target.value)} aria-label="投递状态">
            <option value="">所有状态</option>
            <option value="none">未标记</option>
            {Object.entries(APP_STATUS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.text}
              </option>
            ))}
          </select>
          <label className="inline">
            从
            <input type="date" value={filters.date_from ?? ""} onChange={(e) => setF("date_from", e.target.value)} />
          </label>
          <label className="inline">
            到
            <input type="date" value={filters.date_to ?? ""} onChange={(e) => setF("date_to", e.target.value)} />
          </label>
          {Object.values(filters).some(Boolean) && <button onClick={() => setFilters({})}>清除筛选</button>}
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>
          日期区间是职位加入的日期。
        </p>
      </div>

      {data && (
        <>
          <div className="tiles">
            <Tile label="搜索到 / 加入" value={data.totals.found} onClick={() => pick("所有职位", "all", "")} />
            <Tile label="收藏" value={data.totals.saved} onClick={() => pick("收藏", "application_status", "saved")} />
            <Tile label="已投递（含之后的状态）" value={data.totals.submitted} onClick={() => pick("已投递", "stage", "applied")} />
            <Tile label="面试中" value={data.totals.interviewing} onClick={() => pick("面试中", "application_status", "interviewing")} />
            <Tile label="Offer" value={data.totals.offer} onClick={() => pick("Offer", "application_status", "offer")} />
            <Tile
              label="回复率"
              value={data.totals.reply_rate == null ? "—" : `${Math.round((data.totals.reply_rate as number) * 100)}%`}
              hint="面试、Offer、被拒 ÷ 已投递"
            />
          </div>

          <div className="card">
            <h3>漏斗</h3>
            <BarList
              items={data.funnel.map((f) => ({ key: f.stage, label: f.label, count: f.count }))}
              onPick={(b) => pick(`漏斗：${b.label}`, "stage", b.key)}
            />
          </div>

          <div className="chart-grid">
            <Chart title="投递状态" empty="还没有标记任何状态">
              <BarList
                items={bars(data.application_status, (k) => (k === "none" ? "未标记" : APP_STATUS[k]?.text ?? k))}
                onPick={(b) => pick(`投递状态：${b.label}`, "application_status", b.key)}
              />
            </Chart>
            <Chart title="待处理">
              <BarList
                items={[
                  { key: "saved_not_applied", label: "收藏了还没投", count: data.backlog.saved_not_applied },
                  { key: "applied_no_update", label: `投递后 ${data.backlog.stale_days} 天没更新`, count: data.backlog.applied_no_update },
                ]}
                onPick={(b) => pick(`待处理：${b.label}`, "backlog", b.key)}
              />
            </Chart>
            <Chart title="JD 的 sponsorship 政策">
              <BarList
                items={bars(data.sponsorship_policy, (k) => POLICY[k] ?? k, ["explicit_yes", "unclear", "explicit_no"])}
                onPick={(b) => pick(`Sponsorship：${b.label}`, "sponsorship_policy", b.key)}
              />
            </Chart>
            <Chart title="公司的 H-1B / 绿卡历史">
              <BarList
                items={bars(data.sponsor_status, (k) => SPONSOR_STATUS[k]?.text ?? k)}
                onPick={(b) => pick(`签证历史：${b.label}`, "sponsor_status", b.key)}
              />
            </Chart>
            <Chart title="地点">
              <BarList
                items={bars(data.location_tier, tierLabel, [...locations.map((_, i) => String(i + 1)), "none"])}
                onPick={(b) => pick(`地点：${b.label}`, "location_tier", b.key)}
              />
            </Chart>
            <Chart title="工作方式">
              <BarList
                items={bars(data.work_mode, (k) => WORK_MODE[k] ?? k)}
                onPick={(b) => pick(`工作方式：${b.label}`, "work_mode", b.key)}
              />
            </Chart>
            <Chart title="被排除的原因" empty="没有被排除的职位">
              <BarList
                items={data.exclusions.map((x) => ({ key: x.code, label: x.label, count: x.count }))}
                onPick={(b) => pick(`排除：${b.label}`, "exclusion", b.key)}
              />
            </Chart>
            <Chart title="Easy Apply">
              <BarList
                items={bars(data.easy_apply, (k) => ({ yes: "有", no: "没有", unknown: "未知" })[k] ?? k)}
                onPick={(b) => pick(`Easy Apply：${b.label}`, "easy_apply", b.key)}
              />
            </Chart>
            <Chart title="薪资（年薪上限，时薪 × 2080）">
              <BarList
                items={bars(data.salary, (k) => (k === "unknown" ? "未列出" : k), SALARY_ORDER)}
                onPick={(b) => pick(`薪资：${b.label}`, "salary", b.key)}
              />
            </Chart>
            <Chart title="匹配分数">
              <BarList
                items={bars(data.score, (k) => (k === "none" ? "未评分（含被排除）" : k), SCORE_ORDER)}
                onPick={(b) => pick(`分数：${b.label}`, "score", b.key)}
              />
            </Chart>
            <Chart title="建议">
              <BarList
                items={bars(data.recommendation, (k) => (k === "none" ? "未评分" : RECOMMENDATION[k]?.text ?? k), [
                  "apply",
                  "maybe",
                  "skip",
                  "none",
                ])}
                onPick={(b) => pick(`建议：${b.label}`, "recommendation", b.key)}
              />
            </Chart>
          </div>

          <div className="card">
            <h3>来源网站</h3>
            {data.sources.length === 0 ? (
              <p className="muted">还没有资料。</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>网站</th>
                    <th>找到</th>
                    <th>搜索时保留</th>
                    <th>已投递</th>
                    <th>面试</th>
                    <th style={{ width: "35%" }}>找到的数量</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sources.map((s) => (
                    <tr key={s.site} className="clickable" onClick={() => s.site !== "(无来源链接)" && pick(`来源：${s.name}`, "site", s.site)}>
                      <td>{s.name === "(无来源链接)" ? "手动贴的 JD（无网址）" : s.name}</td>
                      <td>{s.found}</td>
                      <td>{s.kept}</td>
                      <td>{s.applied}</td>
                      <td>{s.interviews}</td>
                      <td>
                        <span
                          className="bar"
                          style={{ width: `${(s.found / Math.max(...data.sources.map((x) => x.found), 1)) * 100}%` }}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h3 style={{ margin: 0 }}>投递趋势</h3>
              <div className="row">
                <label className="inline">
                  <input type="radio" checked={unit === "day"} onChange={() => setUnit("day")} />
                  每日
                </label>
                <label className="inline">
                  <input type="radio" checked={unit === "week"} onChange={() => setUnit("week")} />
                  每周
                </label>
              </div>
            </div>
            <Trend points={data.trend[unit]} unit={unit} />
          </div>
        </>
      )}

      {drill && <DrillDown filters={filters} {...drill} onClose={() => setDrill(null)} />}
    </>
  );
}

function Tile({ label, value, hint, onClick }: { label: string; value: number | string | null; hint?: string; onClick?: () => void }) {
  return (
    <div className={`card tile${onClick ? " clickable" : ""}`} onClick={onClick} title={hint}>
      <div className="muted">{label}</div>
      <b>{value ?? 0}</b>
    </div>
  );
}

function Chart({ title, empty, children }: { title: string; empty?: string; children: React.ReactElement<{ items: Bar[] }> }) {
  const isEmpty = children.props.items.every((b) => b.count === 0);
  return (
    <div className="card">
      <h3>{title}</h3>
      {isEmpty ? <p className="muted">{empty ?? "还没有资料。"}</p> : children}
    </div>
  );
}

/** 横向长条：单一色相表示数量；数值直接标在旁边；滑过有提示，点击下钻。 */
function BarList({ items, onPick }: { items: Bar[]; onPick: (b: Bar) => void }) {
  const max = Math.max(...items.map((b) => b.count), 1);
  const total = items.reduce((n, b) => n + b.count, 0);
  return (
    <div className="barlist" role="table">
      {items.map((b) => (
        <button
          key={b.key}
          className="barrow"
          role="row"
          onClick={() => onPick(b)}
          disabled={b.count === 0}
          title={`${b.label}：${b.count}${total ? `（${Math.round((b.count / total) * 100)}%）` : ""}，点击查看职位`}
        >
          <span className="barlabel" role="cell">
            {b.label}
          </span>
          <span className="bartrack" role="cell">
            <span className="bar" style={{ width: `${(b.count / max) * 100}%` }} />
          </span>
          <span className="barvalue" role="cell">
            {b.count}
          </span>
        </button>
      ))}
    </div>
  );
}

function Trend({ points, unit }: { points: { date: string; applied: number; interviewing: number; other: number }[]; unit: string }) {
  const [hover, setHover] = useState<number | null>(null);
  if (points.length === 0) return <p className="muted">还没有状态变更记录。在职位上标记「已投递」后会出现在这里。</p>;
  const max = Math.max(...points.map((p) => p.applied), 1);
  const h = hover != null ? points[hover] : null;
  return (
    <>
      <p className="muted" style={{ minHeight: 20 }}>
        {h
          ? `${h.date}${unit === "week" ? " 那一周" : ""}：投递 ${h.applied}、进入面试 ${h.interviewing}、其他状态变更 ${h.other}`
          : `「已投递」的数量（滑过长条看细节）`}
      </p>
      <div className="trend" onMouseLeave={() => setHover(null)}>
        {points.map((p, i) => (
          <div key={p.date} className="trendcol" onMouseEnter={() => setHover(i)}>
            <span className="trendbar" style={{ height: `${(p.applied / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="muted">{points[0].date}</span>
        <span className="muted">{points[points.length - 1].date}</span>
      </div>
      <details>
        <summary className="muted">表格</summary>
        <table>
          <thead>
            <tr>
              <th>{unit === "week" ? "周（起始日）" : "日期"}</th>
              <th>投递</th>
              <th>面试</th>
              <th>其他</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.date}>
                <td>{p.date}</td>
                <td>{p.applied}</td>
                <td>{p.interviewing}</td>
                <td>{p.other}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}

function DrillDown({ filters, title, dim, value, onClose }: { filters: Filters; title: string; dim: string; value: string; onClose: () => void }) {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const url = useMemo(() => `/api/stats/jobs${qs(filters, { dim, value })}`, [filters, dim, value]);
  useEffect(() => {
    setJobs(null);
    api.get<JobSummary[]>(url).then(setJobs).catch(() => setJobs([]));
  }, [url]);
  useEffect(() => {
    document.getElementById("drilldown")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [title]);
  return (
    <div className="card" id="drilldown">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>
          {title}（{jobs?.length ?? "…"}）
        </h3>
        <button onClick={onClose}>关闭</button>
      </div>
      {jobs && jobs.length === 0 && <p className="muted">没有职位。</p>}
      <table>
        <tbody>
          {jobs?.map((j) => (
            <tr key={j.id}>
              <td>
                <Link to={`/jobs/${j.id}`}>
                  <b>{j.title}</b>
                </Link>
                <div className="muted">
                  {j.company.display_name} · {show(j.location_text)} · {WORK_MODE[j.work_mode]} ·{" "}
                  {salary(j.salary_min, j.salary_max, j.salary_period)}
                </div>
              </td>
              <td style={{ width: 110 }}>
                {j.score != null ? (
                  <>
                    <b>{j.score}</b> <span className={`badge ${RECOMMENDATION[j.recommendation!].cls}`}>{RECOMMENDATION[j.recommendation!].text}</span>
                  </>
                ) : (
                  <span className="muted">未评分</span>
                )}
              </td>
              <td style={{ width: 100 }}>
                <StatusSelect jobId={j.id} status={j.application_status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
