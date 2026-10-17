import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  focusFirstInvalidContactField,
  getFirstInvalidContactField,
} from "../app/components/contact-form-accessibility.ts";
import {publicSitemap} from "../app/cms/sitemap.ts";
import {initialContent} from "../app/cms/content.ts";
const sitemap = () => publicSitemap(initialContent, "https://peterselijah.name.ng");

const root = new URL("../", import.meta.url);

test("contact validation identifies and focuses the first invalid visible field", () => {
  const focused = [];
  const controls = new Map([
    ["name", { focus: () => focused.push("name") }],
    ["email", { focus: () => focused.push("email") }],
    ["reason", { focus: () => focused.push("reason") }],
  ]);
  const form = {
    elements: {
      namedItem: (name) => controls.get(name) ?? null,
    },
  };

  const errors = {
    form: "Check the form.",
    email: "Enter a valid email.",
    reason: "Choose a reason.",
  };

  assert.equal(getFirstInvalidContactField(errors), "email");
  assert.equal(focusFirstInvalidContactField(form, errors), "email");
  assert.deepEqual(focused, ["email"]);
  assert.equal(getFirstInvalidContactField({ form: "Try again." }), null);
});

test("the anti-spam field stays active but outside navigation and accessibility trees", async () => {
  const form = await readFile(
    new URL("app/components/ContactForm.tsx", root),
    "utf8",
  );

  const honeypot = form.match(
    /<div\s+className="contact-form__honeypot"([\s\S]*?)<\/div>/,
  )?.[0];

  assert.ok(honeypot, "contact honeypot should remain present");
  assert.match(honeypot, /aria-hidden="true"/);
  assert.match(honeypot, /\binert\b/);
  assert.match(honeypot, /name="website"/);
  assert.match(honeypot, /tabIndex=\{-1\}/);
  assert.match(honeypot, /value=\{values\.website\}/);
});

test("sitemap publishes the recruiter-facing routes on the public domain", () => {
  const previousSiteUrl = process.env.NEXT_PUBLIC_SITE_URL;
  delete process.env.NEXT_PUBLIC_SITE_URL;

  try {
    const urls = sitemap().map(entry => entry.url);
    for (const path of ['/', '/skyeta', '/skyeta/help', '/skyeta/privacy', '/skyeta/terms', '/projects/skyeta', '/projects/aurapass', '/projects/incubator-carrier', '/projects/circuits', ...initialContent.projects.map(p=>`/work/${p.slug}`), ...initialContent.circuits.map(p=>`/work/${p.slug}`)]) {
      assert.ok(urls.includes(`https://peterselijah.name.ng${path}`));
    }
    assert.ok(urls.every(url=>!url.includes('/admin')&&!url.includes('/api/')));
  } finally {
    if (previousSiteUrl === undefined) {
      delete process.env.NEXT_PUBLIC_SITE_URL;
    } else {
      process.env.NEXT_PUBLIC_SITE_URL = previousSiteUrl;
    }
  }
});
