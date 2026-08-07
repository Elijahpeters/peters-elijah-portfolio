import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  focusFirstInvalidContactField,
  getFirstInvalidContactField,
} from "../app/components/contact-form-accessibility.ts";
import sitemap from "../app/sitemap.ts";

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
    assert.deepEqual(sitemap(), [
      {
        url: "https://peterselijah.name.ng/",
        changeFrequency: "monthly",
        priority: 1,
      },
      {
        url: "https://peterselijah.name.ng/skyeta",
        changeFrequency: "monthly",
        priority: 0.8,
      },
      {
        url: "https://peterselijah.name.ng/skyeta/help",
        changeFrequency: "monthly",
        priority: 0.5,
      },
      {
        url: "https://peterselijah.name.ng/skyeta/privacy",
        changeFrequency: "yearly",
        priority: 0.4,
      },
      {
        url: "https://peterselijah.name.ng/skyeta/terms",
        changeFrequency: "yearly",
        priority: 0.4,
      },
      {
        url: "https://peterselijah.name.ng/projects/aurapass",
        changeFrequency: "monthly",
        priority: 0.8,
      },
    ]);
  } finally {
    if (previousSiteUrl === undefined) {
      delete process.env.NEXT_PUBLIC_SITE_URL;
    } else {
      process.env.NEXT_PUBLIC_SITE_URL = previousSiteUrl;
    }
  }
});
