import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { existsSync } from "node:fs";

// 前端 5173，/api 转给本机后端（预设 8000，可用 API_PORT 修改）
const apiPort = process.env.API_PORT ?? "8000";

export default defineConfig({
  plugins: [react()],
  define: {
    "import.meta.env.DEMO_RESUME_AVAILABLE": JSON.stringify(existsSync(new URL("./public/demo-resume.json", import.meta.url))),
  },
  server: { proxy: { "/api": `http://127.0.0.1:${apiPort}` } },
});
