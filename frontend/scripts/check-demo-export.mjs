import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve("dist-demo");
const base = process.argv[2] ?? "/job-hunter/";
assert(base.startsWith("/") && base.endsWith("/"));
const html = readFileSync(resolve(root, "index.html"), "utf8");
assert.match(html, /<title>Job Hunter Agent<\/title>/);
for (const [, url] of html.matchAll(/(?:src|href)="([^"]+)"/g)) {
  if (url.startsWith("https://")) continue;
  assert(url.startsWith(base), `Asset escapes demo prefix: ${url}`);
  assert(existsSync(resolve(root, url.slice(base.length))), `Missing asset: ${url}`);
}
const manifest = JSON.parse(readFileSync(resolve(root, "site.webmanifest")));
assert.equal(manifest.start_url, "./");
for (const icon of manifest.icons) {
  assert(!icon.src.startsWith("/"));
  assert(existsSync(resolve(root, icon.src)));
}
// The shared public deployment must use the synthetic fixture, never an exported personal resume.
assert(!existsSync(resolve(root, "demo-resume.json")), "Personal resume export cannot be published by CI");
console.log(`PASS: demo HTML, prefixed assets, manifest and synthetic-only export (${base})`);
