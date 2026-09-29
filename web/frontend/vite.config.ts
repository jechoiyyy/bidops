import path from "node:path";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const configDirectory = path.dirname(fileURLToPath(import.meta.url));

/**
 * 개발 편의 전용 mock API (`npm run dev:mock`).
 *
 * `BIDOPS_MOCK_API`가 없으면 아무것도 하지 않는다 — 운영 번들과 기본 개발
 * 서버는 그대로 백엔드를 부른다. 응답은 Playwright fixture 그대로이며
 * 운영 데이터도 회사 역량 사실도 아니다.
 */
function mockApiPlugin(): Plugin {
  return {
    name: "bidops-mock-api",
    apply: "serve",
    configureServer(server) {
      if (!process.env.BIDOPS_MOCK_API) return;
      server.config.logger.info("  \u001b[33m➜\u001b[0m  API: Playwright fixture mock (운영 데이터 아님)");
      // configureServer에서 바로 등록하면 Vite 내부 proxy보다 먼저 실행된다.
      // /api 요청이 프록시로 나가지 않고 여기서 끝난다.
      server.middlewares.use(async (req, res, next) => {
        if (req.url === "/__mock-review/approved") {
          try {
            const html = await readFile(path.resolve(configDirectory, "../../docs/0922_deep-review-improvement/prototype/index.html"), "utf8");
            res.setHeader("content-type", "text/html; charset=utf-8");
            res.end(html);
          } catch {
            res.statusCode = 503;
            res.end("Approved prototype unavailable");
          }
          return;
        }
        if (!req.url?.startsWith("/api/")) return next();
        const { resolveMockApi } = await server.ssrLoadModule("/scripts/mock-api.ts") as typeof import("./scripts/mock-api");
        const chunks: Buffer[] = [];
        try {
          for await (const chunk of req) chunks.push(chunk as Buffer);
        } catch {
          // 브라우저가 요청을 중간에 끊으면(ECONNRESET) 본문 읽기가 reject 된다. 처리되지
          // 않은 거부는 dev 서버 프로세스 전체를 죽이므로 그 요청만 버린다.
          return;
        }
        const body = chunks.length > 0 ? Buffer.concat(chunks).toString("utf8") : null;
        try {
          const result = await resolveMockApi({
            method: req.method ?? "GET",
            url: `http://127.0.0.1${req.url}`,
            headers: req.headers as Record<string, string>,
            body,
          });
          res.statusCode = result.status;
          for (const [key, value] of Object.entries(result.headers)) res.setHeader(key, value);
          res.end(result.body);
        } catch (error) {
          server.config.logger.error(`mock API 실패: ${String(error)}`);
          res.statusCode = 500;
          res.setHeader("content-type", "application/json");
          res.end(JSON.stringify({ detail: "mock API가 응답을 만들지 못했습니다." }));
        }
      });
    },
  };
}

export default defineConfig(({ command }) => ({
  define: { "import.meta.env.BIDOPS_REVIEW_MOCK": JSON.stringify(command === "serve" && Boolean(process.env.BIDOPS_MOCK_API)) },
  plugins: [react(), tailwindcss(), mockApiPlugin()],
  resolve: {
    alias: {
      "@": path.resolve(configDirectory, "src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8787",
        changeOrigin: true,
      },
    },
  },
}));
