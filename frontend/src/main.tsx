import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Navigate, Route, Routes } from "react-router-dom";
import "./styles.css";
import Facts from "./pages/Facts";
import JobDetail from "./pages/JobDetail";
import Jobs from "./pages/Jobs";
import Materials from "./pages/Materials";
import Preferences from "./pages/Preferences";
import Resumes from "./pages/Resumes";
import Settings from "./pages/Settings";

function App() {
  return (
    <div className="layout">
      <nav className="sidebar">
        <h1>Job Hunter</h1>
        <NavLink to="/jobs">职位搜索</NavLink>
        <NavLink to="/materials">Cover letter / 问答</NavLink>
        <NavLink to="/resumes">履历与评分</NavLink>
        <NavLink to="/preferences">求职需求</NavLink>
        <NavLink to="/facts">个人事实库</NavLink>
        <NavLink to="/settings">模型设置</NavLink>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/resumes" replace />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:id" element={<JobDetail />} />
          <Route path="/materials" element={<Materials />} />
          <Route path="/resumes" element={<Resumes />} />
          <Route path="/preferences" element={<Preferences />} />
          <Route path="/facts" element={<Facts />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
