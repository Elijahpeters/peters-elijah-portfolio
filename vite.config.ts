import vinext from "vinext";
import { defineConfig } from "vite";

const workerConfig = {
  name: "elijah-portfolio-next",
  main: "./worker/index.ts",
  r2_buckets: process.env.PORTFOLIO_R2_BUCKET ? [{ binding: "CMS_MEDIA", bucket_name: process.env.PORTFOLIO_R2_BUCKET }] : [],
  compatibility_flags: ["nodejs_compat"],
  assets: { binding: "ASSETS" },
  images: { binding: "IMAGES" },
  d1_databases: [
    { binding: "CMS_DB", database_name: "elijah-portfolio-next-content", database_id: process.env.PORTFOLIO_CMS_D1_ID ?? "00000000-0000-0000-0000-000000000000" },
    {
      binding: "DB",
      database_name: "peters-elijah-portfolio",
      database_id: process.env.PORTFOLIO_SKYETA_D1_ID ?? "00000000-0000-0000-0000-000000000001",
    },
  ],
};

export default defineConfig(async () => {
  // Keep Wrangler and Miniflare state project-local. These are non-secret tool
  // settings; application environment belongs in ignored `.env*` files.
  process.env.WRANGLER_WRITE_LOGS ??= "false";
  process.env.WRANGLER_LOG_PATH ??= ".wrangler/logs";
  process.env.MINIFLARE_REGISTRY_PATH ??= ".wrangler/registry";

  // Wrangler snapshots its log path while the Cloudflare plugin is imported.
  const { cloudflare } = await import("@cloudflare/vite-plugin");

  return {
    plugins: [
      vinext(),
      cloudflare({
        viteEnvironment: { name: "rsc", childEnvironments: ["ssr"] },
        config: workerConfig,
      }),
    ],
  };
});
