import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, HashRouter, Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, DEMO, JobPreferences, Provider, Resume } from "./api";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { InkProvider } from "@/lib/ink/react";
import { Loading } from "./pages/ui";
import "./looseleaf.css";
import JobDetail from "./pages/JobDetail";
import Jobs from "./pages/Jobs";
import Materials from "./pages/Materials";
import Preferences from "./pages/Preferences";
import ResumeVersions, { ResumeUpload } from "./pages/ResumeManage";
import Resumes from "./pages/Resumes";
import Settings from "./pages/Settings";
import Stats from "./pages/Stats";
import Outreach from "./pages/Outreach";
import { lang, setLang, t } from "./i18n";

const NARROW = ["/resumes", "/preferences", "/settings"];

// 还没放资料时也要能进的页面：设定这三样本身就在这里
const OPEN_PATHS = ["/settings", "/resumes", "/preferences"];

interface Setup {
  model: boolean;
  resume: boolean;
  preferences: boolean;
}

/** 模型连接、已确认的履历、目标职位都有了才能用其他页面。 */
function SetupRequired({ setup }: { setup: Setup }) {
  const steps = [
    { done: setup.model, to: "/settings", title: t("连接模型"), hint: t("评分和写材料都要用模型。") },
    { done: setup.resume, to: "/resumes/upload", title: t("上传并确认履历"), hint: t("上传后到「履历内容」按「确认并保存」。") },
    { done: setup.preferences, to: "/preferences", title: t("填写求职需求"), hint: t("至少填一个目标职位。") },
  ];
  return (
    <section className="card stack">
      <h2 style={{ margin: 0 }}>{t("先完成这三步才能开始")}</h2>
      {steps.map((s, i) => (
        <div className="row between" key={s.to}>
          <span>
            <b>
              {s.done ? "✓" : `${i + 1}.`} {s.title}
            </b>
            <span className="muted small" style={{ display: "block" }}>
              {s.hint}
            </span>
          </span>
          {s.done ? <span className="badge pass">{t("已完成")}</span> : <Link className="btn accent" to={s.to}>{t("去设定 →")}</Link>}
        </div>
      ))}
    </section>
  );
}

/** 导航项：当前页用荧光笔底色（secondary），其他是 ghost。 */
function NavItem({ to, end, title, children }: { to: string; end?: boolean; title?: string; children: React.ReactNode }) {
  const { pathname } = useLocation();
  const on = end ? pathname === to : pathname === to || pathname.startsWith(`${to}/`);
  return (
    <Button asChild variant={on ? "secondary" : "ghost"} size="sm">
      <NavLink to={to} end={end} title={title}>
        {children}
      </NavLink>
    </Button>
  );
}

function App() {
  const { pathname } = useLocation();
  const [model, setModel] = useState(t("模型连接"));
  const [setup, setSetup] = useState<Setup | null>(null);

  useEffect(() => {
    Promise.all([
      api.get<Provider[]>("/api/providers"),
      api.get<Resume[]>("/api/resumes"),
      api.get<{ data: JobPreferences }>("/api/preferences"),
    ])
      .then(([ps, resumes, prefs]) => {
        const active = ps.find((p) => p.enabled);
        setModel(active?.name ?? t("未设置模型"));
        setSetup({
          model: !!active,
          resume: resumes.some((r) => r.is_active && r.parsed_confirmed_at),
          preferences: prefs.data.target_roles.length > 0,
        });
      })
      .catch(() => setSetup({ model: true, resume: true, preferences: true })); // 后端没回应时让各页面自己显示错误
  }, [pathname]);

  const blocked = !OPEN_PATHS.some((p) => pathname.startsWith(p)) && !(setup && setup.model && setup.resume && setup.preferences);

  const narrow = NARROW.includes(pathname) || pathname.startsWith("/jobs/") || pathname.startsWith("/resumes/");
  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <h1 className="brand">
            <img src={`${import.meta.env.BASE_URL}icon.svg`} width="30" height="30" alt="" />
            Job Hunter
          </h1>
          <nav className="nav" aria-label={t("主导航")}>
            <NavItem to="/jobs" end>{t("职位")}</NavItem>
            <NavItem to="/outreach">{t("内推")}</NavItem>
            <NavItem to="/stats">{t("投递统计")}</NavItem>
            <NavItem to="/materials">{t("材料历史")}</NavItem>
            <span className="nav-sep" aria-hidden="true" />
            <NavItem to="/resumes">{t("履历与评分")}</NavItem>
            <NavItem to="/preferences">{t("求职需求")}</NavItem>
          </nav>
          <NavItem to="/settings" title={t("模型连接")}>{t(model)}</NavItem>
          <Button asChild variant="ghost" size="sm">
            <a href="https://github.com/catflyx520" target="_blank" rel="noreferrer noopener">
              GitHub · catflyx520
            </a>
          </Button>
          <ToggleGroup type="single" variant="outline" tone="hi" size="sm" aria-label="Language / 语言" value={lang} onValueChange={(v) => v && setLang(v as "en" | "zh")}>
            <ToggleGroupItem value="en">EN</ToggleGroupItem>
            <ToggleGroupItem value="zh">中文</ToggleGroupItem>
          </ToggleGroup>
        </div>
      </header>
      <main className={`page${narrow ? " narrow" : ""}`}>
        {DEMO && (
          <p className="notice" style={{ marginBottom: 16 }}>
            {t("演示模式：职位、公司和统计都是虚构的样本，只能查看，不能修改。")}{" "}
            <a href="https://github.com/catflyx520/job-hunter-agent" target="_blank" rel="noreferrer noopener">{t("下载完整版，在自己电脑上运行 ↗")}</a>
          </p>
        )}
        {blocked ? setup ? <SetupRequired setup={setup} /> : <Loading /> : <Routes>
          <Route path="/" element={<Navigate to="/jobs" replace />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:id" element={<JobDetail />} />
          <Route path="/stats" element={<Stats />} />
          <Route path="/outreach" element={<Outreach />} />
          <Route path="/outreach/:contactId" element={<Outreach />} />
          <Route path="/materials" element={<Materials />} />
          <Route path="/resumes" element={DEMO ? <Navigate to="/resumes/content" replace /> : <Resumes view="score" />} />
          <Route path="/resumes/content" element={<Resumes view="content" />} />
          <Route path="/resumes/versions" element={<ResumeVersions />} />
          <Route path="/resumes/upload" element={<ResumeUpload />} />
          <Route path="/resumes/manage" element={<Navigate to="/resumes/versions" replace />} />
          <Route path="/preferences" element={<Preferences />} />
          <Route path="/facts" element={<Navigate to="/jobs" replace />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>}
      </main>
    </>
  );
}

// Static demo navigation stays in the fragment so refresh needs no backend rewrite.
const Router = DEMO ? HashRouter : BrowserRouter;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <InkProvider>
      <Router>
        <App />
      </Router>
    </InkProvider>
  </React.StrictMode>,
);
