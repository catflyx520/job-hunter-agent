import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, Provider } from "./api";
import "./styles.css";
import Facts from "./pages/Facts";
import JobDetail from "./pages/JobDetail";
import Jobs from "./pages/Jobs";
import Materials from "./pages/Materials";
import Preferences from "./pages/Preferences";
import ResumeVersions, { ResumeUpload } from "./pages/ResumeManage";
import Resumes from "./pages/Resumes";
import Settings from "./pages/Settings";
import Stats from "./pages/Stats";

const NARROW = ["/resumes", "/preferences", "/facts", "/settings"];

function App() {
  const { pathname } = useLocation();
  const [model, setModel] = useState("模型连接");

  useEffect(() => {
    api
      .get<Provider[]>("/api/providers")
      .then((ps) => setModel(ps.find((p) => p.enabled)?.name ?? "未设置模型"))
      .catch(() => undefined);
  }, [pathname]);

  const narrow = NARROW.includes(pathname) || pathname.startsWith("/jobs/") || pathname.startsWith("/resumes/");
  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <h1 className="brand">Job Hunter</h1>
          <nav className="nav" aria-label="主导航">
            <NavLink to="/jobs" end>
              职位
            </NavLink>
            <NavLink to="/stats">投递统计</NavLink>
            <NavLink to="/materials">申请材料</NavLink>
            <span className="nav-sep" aria-hidden="true" />
            <NavLink to="/resumes">履历与评分</NavLink>
            <NavLink to="/preferences">求职需求</NavLink>
            <NavLink to="/facts">事实库</NavLink>
          </nav>
          <NavLink to="/settings" className="model-link" title="模型连接">
            {model}
          </NavLink>
        </div>
      </header>
      <main className={`page${narrow ? " narrow" : ""}`}>
        <Routes>
          <Route path="/" element={<Navigate to="/jobs" replace />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:id" element={<JobDetail />} />
          <Route path="/stats" element={<Stats />} />
          <Route path="/materials" element={<Materials />} />
          <Route path="/resumes" element={<Resumes view="score" />} />
          <Route path="/resumes/content" element={<Resumes view="content" />} />
          <Route path="/resumes/versions" element={<ResumeVersions />} />
          <Route path="/resumes/upload" element={<ResumeUpload />} />
          <Route path="/resumes/manage" element={<Navigate to="/resumes/versions" replace />} />
          <Route path="/preferences" element={<Preferences />} />
          <Route path="/facts" element={<Facts />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
