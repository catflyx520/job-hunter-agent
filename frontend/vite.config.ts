import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 原生模式：前端 5173，/api 转给 uv run 起的后端 8000
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
