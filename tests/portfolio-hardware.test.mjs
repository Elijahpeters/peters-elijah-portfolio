import assert from "node:assert/strict";
import { readFile, readdir, stat } from "node:fs/promises";
import test from "node:test";
import { circuitStudies } from "../app/lib/circuit-studies.ts";

const root = new URL("../", import.meta.url);
const source = (file) => readFile(new URL(file, root), "utf8");

test("all five schematic cards resolve to a unique, evidence-labelled study", async () => {
  assert.equal(circuitStudies.length, 5);
  assert.equal(new Set(circuitStudies.map((study) => study.id)).size, 5);
  for (const study of circuitStudies) {
    assert.equal(study.href, `/projects/circuits#${study.id}`);
    for (const field of ["title", "description", "purpose", "approach", "evidence", "limitation", "nextCheck", "alt"]) {
      assert.ok(study[field].trim().length > 10, `${study.id} requires ${field}`);
    }
    assert.ok(study.width > 0 && study.height > 0);
    assert.ok((await stat(new URL(`public${study.image}`, root))).size > 0);
    assert.ok((await stat(new URL(`public${study.mobileImage}`, root))).size > 0);
  }
  const page = await source("app/projects/circuits/page.tsx");
  assert.match(page, /id=\{study\.id\}/);
  assert.match(page, /href=\{study\.image\}/);
  assert.match(page, /width=\{study\.width\} height=\{study\.height\}/);
});

test("schematic descriptions preserve targets, unresolved findings and concept-only scope", () => {
  const find = (id) => circuitStudies.find((study) => study.id === id);
  assert.match(find("antoniou-gic").limitation, /design target, not a measured inductance/);
  assert.match(find("khn-filter").evidence, /negative damping/);
  assert.match(find("khn-filter").limitation, /no corrected implementation is claimed/);
  assert.match(find("instrumentation-amplifier").limitation, /does not establish output headroom/);
  assert.match(find("pfd-charge-pump").evidence, /concept diagram/);
  assert.match(find("boost-converter").limitation, /not a validated power supply/);
});

test("incubator case study distinguishes CAD results from physical and safety validation", async () => {
  const page = await source("app/projects/incubator-carrier/page.tsx");
  assert.match(page, /not assembled or bench-tested/);
  assert.match(page, /12 September 2026/);
  assert.match(page, /0 errors and 0 warnings/);
  assert.match(page, /0 violations and 0 unconnected pads/);
  assert.match(page, /default ignored checks/);
  assert.match(page, /No populated prototype has been tested/);
  assert.match(page, /firmware is not included/);
  assert.match(page, /not a sole safety device/);
  assert.match(page, /schematic organisation/i);
  assert.doesNotMatch(page, /href="[^"]*\.(?:zip|kicad_pcb|kicad_sch|gbr|drl|csv)"/);
});

test("hardware additions include only the selected presentation images", async () => {
  const names = (await readdir(new URL("public/assets/", root)))
    .filter((name) => name.startsWith("incubator-"))
    .sort();
  assert.deepEqual(names, ["incubator-pcb-angled.png", "incubator-pcb-layout.png", "incubator-schematic.png"]);
  for (const name of names) {
    const bytes = await readFile(new URL(`public/assets/${name}`, root));
    assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
    assert.ok(bytes.length < 2_000_000, `${name} should stay below 2 MB`);
  }
});

test("the homepage exposes hardware work and case study routes", async () => {
  const [home, css, nav] = await Promise.all([
    source("app/page.tsx"), source("app/projects/engineering.module.css"), source("app/components/SiteHeader.tsx"),
  ]);
  assert.match(home, /Circuit design\. PCB layout\./);
  assert.match(home, /href="\/projects\/incubator-carrier"/);
  assert.match(home, /circuitStudies\.map/);
  assert.match(home, /Read circuit study/);
  assert.match(nav, /Circuits & PCB/);
  assert.match(css, /font-size: 1rem/);
  assert.match(css, /@media \(max-width: 820px\)/);
  assert.match(css, /\.feature, \.split \{ grid-template-columns: 1fr/);
  assert.match(css, /min-height: 44px/);
  assert.doesNotMatch(home, /solarproof/i);
});

test("circuit images cannot impose a fixed-height aspect-ratio width on their grid column", async () => {
  const css = await source("app/globals.css");
  const imageRules = [...css.matchAll(/\.circuit-image\s*\{([^}]+)\}/g)].map((match) => match[1]);
  assert.ok(imageRules.length > 0);
  assert.match(imageRules[0], /width:\s*100%/);
  assert.match(imageRules[0], /min-width:\s*0/);
  assert.match(imageRules[0], /max-width:\s*100%/);
  assert.match(imageRules[0], /overflow:\s*hidden/);
  for (const rules of imageRules) {
    assert.match(rules, /min-height:\s*0/);
    assert.doesNotMatch(rules, /min-height:\s*[1-9]\d*px/);
  }
  const copyRules = css.match(/\.circuit-copy\s*\{([^}]+)\}/)?.[1];
  assert.match(copyRules, /min-width:\s*0/);
  assert.match(copyRules, /grid-template-columns:\s*minmax\(0, 1fr\)/);
  const badgeRules = [...css.matchAll(/\.circuit-copy > span\s*\{([^}]+)\}/g)];
  for (const [, rules] of badgeRules) assert.doesNotMatch(rules, /grid-row:\s*1|order:\s*-1/);
});
