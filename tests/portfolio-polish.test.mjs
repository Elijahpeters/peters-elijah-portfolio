import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("experience descriptions include defensible, measurable scope", async () => {
  const source = await readFile(
    new URL("app/components/ExperienceSection.tsx", root),
    "utf8",
  );

  assert.match(source, /four engineering deliverable types/);
  assert.match(source, /across three design tools/);
  assert.match(source, /against three quality checks/);
  assert.match(source, /four-stage machine-learning workflows/);
  assert.match(source, /three-month, project-based internship/);
  assert.doesNotMatch(source, /\b(?:percent|%|revenue|saved|increased|reduced)\b/i);
});

test("mobile portfolio spacing and the AuraPass title remain compact", async () => {
  const css = await readFile(new URL("app/globals.css", root), "utf8");

  const phoneRules = css.match(
    /@media \(max-width: 560px\) \{([\s\S]*?)(?=\n@media|\s*$)/,
  )?.[1];
  assert.ok(phoneRules, "phone rules should remain present");
  assert.match(phoneRules, /\.hero \{[\s\S]*?padding: 3rem 0 1\.3rem;[\s\S]*?gap: 2\.5rem;/);
  assert.match(phoneRules, /\.section \{[\s\S]*?padding: 4\.5rem 1rem;/);
  assert.match(phoneRules, /\.section-heading \{[\s\S]*?margin-bottom: 2\.75rem;/);
  assert.match(phoneRules, /\.contact \{[\s\S]*?padding: 4\.5rem 1rem;/);

  assert.match(
    css,
    /@media \(max-width: 820px\) \{[\s\S]*?\.case-study-hero h1 \{[\s\S]*?font-size: clamp\(2\.45rem, 10vw, 3\.5rem\);[\s\S]*?line-height: 0\.94;/,
  );
});
