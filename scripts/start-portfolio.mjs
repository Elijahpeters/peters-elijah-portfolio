import path from "node:path";
import { loadEnvFile } from "node:process";
import { fileURLToPath } from "node:url";

import { startProdServer } from "vinext/server/prod-server";
import { StaticFileCache } from "../node_modules/vinext/dist/server/static-file-cache.js";

// vinext 0.0.50 stores Windows cache keys with backslashes while requests use
// URL slashes. Keep the upstream lookup first, then retry with a Windows key.
const upstreamLookup = StaticFileCache.prototype.lookup;
StaticFileCache.prototype.lookup = function lookupPortable(pathname) {
  const direct = upstreamLookup.call(this, pathname);
  if (direct || path.sep === "/" || !pathname.startsWith("/")) return direct;

  const windowsKey = `/${pathname.slice(1).replaceAll("/", path.sep)}`;
  return upstreamLookup.call(this, windowsKey);
};

const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

try {
  loadEnvFile(path.join(projectRoot, ".env.local"));
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}

const port = Number.parseInt(process.env.PORT ?? "4177", 10);

if (!Number.isInteger(port) || port < 1 || port > 65_535) {
  throw new Error(`Invalid portfolio port: ${process.env.PORT}`);
}

await startProdServer({
  host: "127.0.0.1",
  outDir: path.join(projectRoot, "dist"),
  port,
});
