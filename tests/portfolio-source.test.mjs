import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("portfolio source exposes the complete recruiter path", async () => {
  const [page, layout, demo, styles] = await Promise.all([
    readFile(new URL("app/page.tsx", root), "utf8"),
    readFile(new URL("app/layout.tsx", root), "utf8"),
    readFile(new URL("app/components/SkyetaDemo.tsx", root), "utf8"),
    readFile(new URL("app/globals.css", root), "utf8"),
  ]);

  assert.match(layout, /const title = "Peters Elijah Temidayo"/);
  assert.match(layout, /images:\s*\["\/og\.png"\]/);
  assert.match(page, /import ContactForm from "\.\/components\/ContactForm"/);
  assert.match(page, /<ContactForm \/>/);
  assert.match(page, /My name is Peters Elijah Temidayo/);
  assert.match(page, /Electronics Circuit Design Expert/);
  assert.match(page, /B\.Eng Electrical &amp; Electronics Engineering/);
  assert.doesNotMatch(page, /Selected work across/);

  const primaryNav = page.match(
    /<nav aria-label="Primary navigation">([\s\S]*?)<\/nav>/,
  )?.[1];
  assert.ok(primaryNav, "primary navigation should be present");
  assert.equal(
    primaryNav.match(/<a\b/g)?.length,
    5,
    "primary navigation should contain exactly five links",
  );
  assert.match(primaryNav, /<a href="#projects">Projects<\/a>/);
  assert.match(primaryNav, /<a href="#circuits">Circuit Lab<\/a>/);
  assert.match(primaryNav, /<a href="#about">Profile<\/a>/);
  assert.match(primaryNav, /<a href="#experience">Experience<\/a>/);
  assert.match(
    primaryNav,
    /<a className="header-contact" href="#contact">[\s\S]*?Get in Touch/,
  );
  assert.match(page, /<section className="section selected-work" id="projects">/);
  assert.match(page, /<section className="section circuit-work" id="circuits">/);
  assert.match(page, /<section className="section profile" id="about">/);
  assert.match(page, /<section className="section experience" id="experience">/);
  assert.match(page, /<section className="contact" id="contact">/);
  assert.match(page, /href="tel:\+2349021985375"/);
  assert.match(page, /href="https:\/\/github\.com\/Elijahpeters"/);
  assert.match(page, /View SkyETA code/);
  assert.match(page, /href="https:\/\/www\.linkedin\.com\/in\/elijahpeters01"/);
  assert.match(page, /href="\/assets\/Peters-Elijah-CV\.pdf"/);
  assert.match(page, /<SkyetaDemo \/>/);
  assert.match(demo, /fetch\("\/assets\/skyeta-model\.json"/);
  assert.match(demo, /\/api\/skyeta\/live-flights/);
  assert.match(
    demo,
    /new URLSearchParams\(\{\s*origin: preset\.origin,\s*destination: preset\.destination,\s*airline: preset\.carrier,/s,
  );
  assert.match(
    demo,
    /setPrediction\(nextPrediction\);\s*setWhatIfOffset\(0\);\s*void loadLiveFlights\(selectedPreset\);/s,
  );
  assert.match(demo, /Real current schedule\/status data/);
  assert.match(demo, /up to about 10\s*hours/);
  assert.match(demo, /not fares, seats, or\s*booking availability/);
  assert.match(demo, /No substitute or hypothetical flights are shown/);
  assert.match(demo, /Model-only schedule sensitivity/);
  assert.match(demo, /Deterministic model-generated summary/);
  assert.match(demo, /SkyETA flight review/);
  assert.match(demo, /Source: U\.S\. BTS records/);
  assert.match(demo, /LightGBM model loaded and verified/);
  assert.match(demo, /Below typical pattern/);
  assert.match(demo, /Typical historical pattern/);
  assert.match(demo, /skyeta-flight-review-preview-title/);
  assert.match(demo, /Awaiting calculation/);
  assert.match(demo, /no\s+testimonials or invented live data/i);
  assert.match(demo, /createFlightReview\(prediction, liveFlightsState\)/);
  assert.doesNotMatch(
    demo,
    /SkyETA engineering review|createEngineeringReview|customer review|generative AI/i,
  );
  assert.doesNotMatch(demo, /AIRLABS_API_KEY|api_key/);
  assert.doesNotMatch(
    demo,
    /Jan-Sep 2025 training baseline|2025 train|training-period baseline|Training-baseline comparison|Temporal validation ROC-AUC|Held-out test ROC-AUC|Probability output:|validation gain vs core/i,
  );
  assert.match(demo, /skyeta-demo__network" aria-hidden="true"/);
  assert.match(demo, /skyeta-demo__radar/);
  assert.match(demo, /skyeta-demo__flight-path/);
  assert.match(demo, /skyeta-demo__flight-path--secondary/);
  assert.match(styles, /@keyframes skyeta-radar-blip/);
  assert.match(styles, /@keyframes skyeta-radar-sweep/);
  assert.match(styles, /@keyframes skyeta-flight-track/);
  assert.match(styles, /@keyframes skyeta-route-packet/);
  assert.match(styles, /@keyframes skyeta-review-scan/);
  assert.match(styles, /@keyframes skyeta-review-awaiting/);
  assert.match(styles, /@keyframes skyeta-ready-pulse/);
  assert.match(styles, /@keyframes skyeta-signal-pulse/);
  assert.match(styles, /@keyframes skyeta-button-sheen/);
  assert.match(styles, /@keyframes skyeta-card-reveal/);
  assert.match(styles, /@keyframes skyeta-estimate-emphasis/);
  assert.match(styles, /@keyframes skyeta-live-ready/);
  assert.match(
    styles,
    /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.skyeta-demo \*::after \{[\s\S]*?animation: none !important;[\s\S]*?transition: none !important;/,
  );
  assert.match(demo, /Math\.fround/);
  assert.doesNotMatch(page, /Google Sites|Remote Electronics Expert/);

  await Promise.all([
    access(new URL("public/assets/Peters-Elijah-CV.pdf", root)),
    access(new URL("public/assets/portrait-web.jpg", root)),
    access(new URL("public/assets/portrait-secondary-web.jpg", root)),
    access(new URL("public/assets/skyeta-logo-clean.png", root)),
    access(new URL("public/favicon.png", root)),
  ]);
});

test("SkyETA is also available as a standalone product route", async () => {
  const [page, styles] = await Promise.all([
    readFile(new URL("app/skyeta/page.tsx", root), "utf8"),
    readFile(new URL("app/skyeta/skyeta.module.css", root), "utf8"),
  ]);

  assert.match(page, /import SkyetaDemo from "\.\.\/components\/SkyetaDemo"/);
  assert.match(page, /<SkyetaDemo \/>/);
  assert.match(page, /href="\/"/);
  assert.match(page, /id="skyeta-demo"/);
  assert.match(page, /<dt>Source<\/dt>\s*<dd>U\.S\. BTS records<\/dd>/);
  assert.match(page, /<dd>LightGBM<\/dd>/);
  assert.doesNotMatch(page, /<dt>Training data<\/dt>/);
  assert.match(page, /className=\{styles\.radarSweep\}/);
  assert.match(page, /className=\{styles\.flightTraveler\}/);
  assert.match(styles, /:global\(\.skyeta-demo\)/);
  assert.match(styles, /@keyframes radar-sweep/);
  assert.match(styles, /@keyframes radar-blip/);
  assert.match(styles, /@keyframes route-flow/);
  assert.match(styles, /@keyframes flight-travel/);
  assert.match(styles, /@keyframes system-state-pulse/);
  assert.match(styles, /@keyframes demo-shell-breathe/);
  assert.match(
    styles,
    /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.page \*::after \{[\s\S]*?animation: none !important;[\s\S]*?transition: none !important;/,
  );
});
