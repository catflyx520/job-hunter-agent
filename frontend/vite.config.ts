import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 前端 5173，/api 转给本机后端（预设 8000，可用 API_PORT 修改）
const apiPort = process.env.API_PORT ?? "8000";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": `http://127.0.0.1:${apiPort}` } },
});
