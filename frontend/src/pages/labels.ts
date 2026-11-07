// 显示用的中文标签；未知一律明确写「未知」。

export const UNKNOWN = "未知";

export const WORK_MODE: Record<string, string> = { onsite: "Onsite", hybrid: "Hybrid", remote: "Remote", unknown: UNKNOWN };
export const EMPLOYMENT: Record<string, string> = {
  full_time: "Full-time",
  part_time: "Part-time",
  contract: "Contract",
  contract_to_hire: "Contract-to-hire",
  internship: "Internship",
  unknown: UNKNOWN,
};
export const SPONSORSHIP: Record<string, { text: string; cls: string }> = {
  explicit_yes: { text: "JD 写明提供 sponsorship", cls: "pass" },
  explicit_no: { text: "JD 写明不提供 sponsorship", cls: "fail" },
  unclear: { text: "JD 没写 sponsorship（不明）", cls: "warn" },
};
export const RECOMMENDATION: Record<string, { text: string; cls: string }> = {
  apply: { text: "Apply", cls: "pass" },
  maybe: { text: "Maybe", cls: "warn" },
  skip: { text: "Skip", cls: "fail" },
};
export const SPONSOR_STATUS: Record<string, { text: string; cls: string; desc: string }> = {
  records_found: { text: "有记录", cls: "pass", desc: "已确认的实体在资料范围内有记录" },
  no_match_in_scope: { text: "范围内查无", cls: "warn", desc: "在已导入的资料年份里没有记录" },
  not_checked: { text: "未查", cls: "warn", desc: "资料未导入或查询失败" },
  employer_unknown: { text: "雇主不明", cls: "warn", desc: "无法确认实际的法律雇主" },
};
export const PROGRAM: Record<string, string> = {
  lca: "H-1B LCA（DOL）",
  perm: "PERM 绿卡劳工证（DOL）",
  uscis_h1b: "H-1B 批准 / 拒绝（USCIS）",
};
export const VERIFICATION: Record<string, string> = {
  employer_site: "雇主官网",
  ats_api: "ATS 官方页面",
  job_board: "求职网站页面",
  search_snippet: "搜索摘要",
  pasted: "你贴上的 JD（未在官网核实）",
};

export function salary(min: number | null, max: number | null, period: string | null): string {
  if (min == null && max == null) return `薪资${UNKNOWN}`;
  const f = (n: number) => (period === "hour" ? `$${n}` : `$${Math.round(n / 1000)}k`);
  const range = min != null && max != null ? `${f(min)} – ${f(max)}` : f((min ?? max)!);
  return `${range}${period === "hour" ? " / 小时" : period === "year" ? " / 年" : ""}`;
}

export const show = (v: string | null | undefined) => (v && v.trim() ? v : UNKNOWN);
export const yesNo = (v: boolean | null | undefined, yes = "是", no = "否") => (v == null ? UNKNOWN : v ? yes : no);

export const RUN_STATUS: Record<string, { text: string; cls: string }> = {
  pending: { text: "准备中", cls: "warn" },
  running: { text: "搜索中", cls: "warn" },
  completed: { text: "已完成", cls: "pass" },
  failed: { text: "失败", cls: "fail" },
  cancelled: { text: "已取消", cls: "warn" },
};
export const RUN_SITE_STATUS: Record<string, { text: string; cls: string }> = {
  searching: { text: "搜索中", cls: "" },
  ok: { text: "正常", cls: "pass" },
  partial: { text: "部分完成", cls: "warn" },
  blocked: { text: "被挡住", cls: "fail" },
  failed: { text: "失败", cls: "fail" },
  skipped: { text: "略过", cls: "" },
};
