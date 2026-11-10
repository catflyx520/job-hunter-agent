/** 介面语言：英文（预设）与中文。
 *
 * 用法：t("中文原文") 或 t("已处理 {done} 个", { done })。原文就是中文，英文在 en.ts 的字典里。
 * 语言在页面载入时决定（存在浏览器），切换时重新载入页面，所以模块层级的常数也能用 t()。
 * 字典里找不到的句子显示中文原文；scripts/check-i18n.mjs 会列出缺的翻译。 */
import { EN } from "./en";

export type Lang = "en" | "zh";
const KEY = "jh.lang";

function readLang(): Lang {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "zh" || v === "en") return v;
  } catch {
    // 无痕模式或封锁储存时用预设
  }
  return "en";
}

export const lang: Lang = readLang();
document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";

/** 存下语言并重新载入页面。 */
export function setLang(next: Lang) {
  if (next === lang) return;
  try {
    localStorage.setItem(KEY, next);
  } catch {
    // 存不了就只能维持预设
  }
  window.location.reload();
}

export function t(zh: string, vars?: Record<string, string | number | null | undefined>): string {
  let s = lang === "en" ? (EN[zh] ?? zh) : zh;
  if (vars) s = s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k] ?? "") : m));
  return s;
}

/** 日期、数字显示跟着语言走。 */
export const locale = lang === "zh" ? "zh-CN" : "en-US";
