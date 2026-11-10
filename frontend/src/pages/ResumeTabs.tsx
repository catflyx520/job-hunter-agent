import { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";

export type ResumeTab = "score" | "content" | "versions" | "upload";

const TABS: { tab: ResumeTab; label: string; path: string }[] = [
  { tab: "score", label: "评分", path: "/resumes" },
  { tab: "content", label: "履历内容", path: "/resumes/content" },
  { tab: "versions", label: "版本管理", path: "/resumes/versions" },
  { tab: "upload", label: "上传", path: "/resumes/upload" },
];

/** 履历四个分页共用的切换器：评分、履历内容、版本管理、上传，各自是独立页面。
 * 评分与履历内容会带着目前选的版本（?id=）。 */
export default function ResumeTabs({ tab, left }: { tab: ResumeTab; left?: ReactNode }) {
  const [params] = useSearchParams();
  const id = params.get("id");
  return (
    <section className="row" aria-label="履历">
      <nav className="seg" aria-label="履历页面">
        {TABS.map((t) => (
          <Link
            key={t.tab}
            to={t.path + (id && (t.tab === "score" || t.tab === "content") ? `?id=${id}` : "")}
            className={t.tab === tab ? "on" : ""}
            aria-current={t.tab === tab ? "page" : undefined}
          >
            {t.label}
          </Link>
        ))}
      </nav>
      {left}
    </section>
  );
}
