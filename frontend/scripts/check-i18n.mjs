// 列出程式里 t("...") 用到、但 en.ts 字典里没有的中文句子。
// 用法（在 frontend/）：node scripts/check-i18n.mjs        列出缺的
//                      node scripts/check-i18n.mjs --json  输出 JSON 阵列
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const CJK = /[一-鿿]/;
const files = [];
const walk = (d) => {
  for (const f of readdirSync(d)) {
    const p = join(d, f);
    if (statSync(p).isDirectory()) walk(p);
    else if (/\.tsx?$/.test(f) && f !== "en.ts") files.push(p);
  }
};
walk(SRC);

const unquote = (s) => JSON.parse(`"${s}"`);
const keys = new Set();
const call = /\bt\(\s*"((?:[^"\\]|\\.)*)"/g;
for (const f of files) {
  const s = readFileSync(f, "utf8");
  for (const m of s.matchAll(call)) if (CJK.test(m[1])) keys.add(unquote(m[1]));
}

const en = readFileSync(join(SRC, "en.ts"), "utf8");
const entry = /^\s*"((?:[^"\\]|\\.)*)":/gm;
const have = new Set([...en.matchAll(entry)].map((m) => unquote(m[1])));
const missing = [...keys].filter((k) => !have.has(k)).sort();
const unused = [...have].filter((k) => !keys.has(k) && !k.startsWith("@"));

if (process.argv.includes("--json")) console.log(JSON.stringify(missing, null, 1));
else {
  for (const k of missing) console.log(k);
  console.log(`\n${keys.size} 个句子，缺 ${missing.length} 个英文翻译；字典里 ${unused.length} 个没被程式直接用到（可能是后端传来的文字）。`);
}
process.exitCode = missing.length ? 1 : 0;
