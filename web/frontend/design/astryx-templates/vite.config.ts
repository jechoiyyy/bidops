// 시안 전용 Vite 설정. 운영 번들(web/frontend/vite.config.ts)과 분리돼 있고 API를 부르지 않는다.
import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const dir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  root: dir,
  base: "./",
  publicDir: path.resolve(dir, "../../public"),
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5195, strictPort: true, fs: { allow: [path.resolve(dir, "../..")] } },
  preview: { host: "127.0.0.1", port: 5195, strictPort: true, allowedHosts: [".ts.net"] },
  // web/frontend/.gitignore의 dist-*/ 규칙에 걸리는 위치라 빌드 결과가 추적되지 않는다.
  build: { outDir: path.resolve(dir, "../../dist-astryx-templates"), emptyOutDir: true },
});
