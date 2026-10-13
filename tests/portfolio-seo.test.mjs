import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import test from "node:test";
import ts from "typescript";
import { personJsonLd } from "../app/lib/person-schema.ts";
import sitemap from "../app/sitemap.ts";

const root = new URL("../", import.meta.url);
// Evaluate static metadata declarations without executing page components or providers.
async function metadata(path) {
  const source = await readFile(new URL(path, root), "utf8");
  const ast = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const declarations = ast.statements.filter(ts.isVariableStatement)
    .map((statement) => statement.getText(ast)).join("\n");
  const { outputText } = ts.transpileModule(declarations, {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  });
  const context = { exports: {}, URL, process: { env: {} } };
  vm.runInNewContext(outputText, context);
  return context.exports.metadata;
}

test("homepage connects both names in metadata, visible copy and valid Person JSON-LD", async () => {
  const meta = await metadata("app/layout.tsx");
  assert.equal(meta.metadataBase.href, "https://peterselijah.name.ng/");
  assert.equal(meta.title, "Peters Elijah Temidayo (Elijah Peters) | Electrical & Electronics Engineer");
  assert.equal(meta.description, "Portfolio of Peters Elijah Temidayo (Elijah Peters), an Electrical & Electronics Engineer focused on embedded systems, circuit/PCB design and applied AI/ML.");
  assert.equal(meta.openGraph.title, meta.title);
  assert.equal(meta.twitter.description, meta.description);
  const schema = JSON.parse(JSON.stringify(personJsonLd));
  assert.equal(schema["@type"], "Person");
  assert.equal(schema.name, "Peters Elijah Temidayo");
  assert.equal(schema.alternateName, "Elijah Peters");
  assert.deepEqual(schema.sameAs, ["https://www.linkedin.com/in/elijahpeters01", "https://github.com/Elijahpeters"]);
  assert.equal(schema.alumniOf.name, "Olabisi Onabanjo University");
  const home = await readFile(new URL("app/page.tsx", root), "utf8");
  assert.equal((home.match(/<h1\b/g) ?? []).length, 1);
  assert.match(home, /Peters Elijah Temidayo, professionally known as Elijah Peters/);
  assert.match(home, /type="application\/ld\+json"/);
});

test("project canonicals are unique, indexable and have complete independent social metadata", async () => {
  const titles = new Set();
  for (const slug of ["aurapass", "skyeta", "incubator-carrier", "circuits"]) {
    const meta = await metadata(`app/projects/${slug}/page.tsx`);
    assert.ok(!titles.has(meta.title));
    titles.add(meta.title);
    assert.match(meta.title, /Elijah Peters/);
    assert.ok(meta.description.length > 80);
    assert.equal(meta.alternates.canonical, `/projects/${slug}`);
    assert.equal(meta.openGraph.url, meta.alternates.canonical);
    for (const social of [meta.openGraph, meta.twitter]) {
      assert.equal(social.title, meta.title);
      assert.equal(social.description, meta.description);
      assert.ok(social.images[0].alt.includes("Elijah Peters"));
      const image = social.images[0].url;
      const file = image === "/skyeta/opengraph-image" ? "app/skyeta/opengraph-image.tsx" : `public${image}`;
      assert.ok((await readFile(new URL(file, root))).length > 0);
    }
  }
  const pcb = await metadata("app/projects/incubator-carrier/page.tsx");
  assert.match(pcb.description, /not been physically bench-tested/);
});

test("SkyETA page and inherited sharing metadata agree without changing provider behavior", async () => {
  const page = await metadata("app/skyeta/page.tsx");
  const layout = await metadata("app/skyeta/layout.tsx");
  assert.equal(page.title, layout.openGraph.title);
  assert.equal(page.description, layout.twitter.description);
  assert.equal(layout.alternates.canonical, "/skyeta");
});

test("robots advertises a public sitemap that never picks up a preview domain", async () => {
  const previous = process.env.NEXT_PUBLIC_SITE_URL;
  process.env.NEXT_PUBLIC_SITE_URL = "https://preview.example";
  try {
    for (const entry of sitemap()) {
      assert.equal(new URL(entry.url).origin, "https://peterselijah.name.ng");
      assert.doesNotMatch(entry.url, /checkout|payment|api\//);
    }
  } finally {
    if (previous === undefined) delete process.env.NEXT_PUBLIC_SITE_URL;
    else process.env.NEXT_PUBLIC_SITE_URL = previous;
  }
  const robots = await readFile(new URL("public/robots.txt", root), "utf8");
  assert.match(robots, /User-agent: \*\nAllow: \/\n/);
  assert.match(robots, /Sitemap: https:\/\/peterselijah\.name\.ng\/sitemap\.xml/);
  assert.doesNotMatch(robots, /Disallow:\s*\//);
});
