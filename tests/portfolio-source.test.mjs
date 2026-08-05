import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("portfolio source exposes the complete recruiter path", async () => {
  const [page, layout, demo, deferredDemo, styles] = await Promise.all([
    readFile(new URL("app/page.tsx", root), "utf8"),
    readFile(new URL("app/layout.tsx", root), "utf8"),
    readFile(new URL("app/components/SkyetaDemo.tsx", root), "utf8"),
    readFile(new URL("app/components/DeferredSkyetaDemo.tsx", root), "utf8"),
    readFile(new URL("app/globals.css", root), "utf8"),
  ]);

  assert.match(layout, /const title = "Peters Elijah Temidayo"/);
  assert.match(layout, /const socialImage = "\/og-v2\.jpg"/);
  assert.match(layout, /secureUrl: socialImage/);
  assert.match(layout, /type: "image\/jpeg"/);
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
  assert.match(
    page,
    /href="https:\/\/github\.com\/Elijahpeters\/AuraPass"/,
  );
  assert.match(
    page,
    /href="\/skyeta"\s+target="_blank"\s+rel="noreferrer"\s+aria-label="Open SkyETA in a new tab"/,
  );
  assert.match(
    page,
    /href="https:\/\/github\.com\/Elijahpeters\/SkyETA"/,
  );
  assert.doesNotMatch(page, /AuraPass_V2|AuraPass V2/);
  assert.match(page, /View SkyETA code/);
  assert.match(page, /href="https:\/\/www\.linkedin\.com\/in\/elijahpeters01"/);
  assert.match(page, /href="\/assets\/Peters-Elijah-CV\.pdf"/);
  assert.match(
    page,
    /import DeferredSkyetaDemo from "\.\/components\/DeferredSkyetaDemo"/,
  );
  assert.match(page, /<DeferredSkyetaDemo \/>/);
  assert.match(deferredDemo, /lazy\(\(\) => import\("\.\/SkyetaDemo"\)\)/);
  assert.match(deferredDemo, /new IntersectionObserver/);
  assert.match(deferredDemo, /isSmallScreen \? "160px 0px" : "700px 0px"/);
  assert.match(page, /How SkyETA works/);
  assert.match(page, /Add flight details/);
  assert.match(page, /Compare flight patterns/);
  assert.match(page, /Read a clear estimate/);
  assert.match(page, /Current AirLabs departures are shown separately/);
  assert.match(page, /AuraPass system highlights/);
  assert.match(page, /5,000/);
  assert.match(page, /false grants in the controlled test set/);
  assert.match(page, /6 \/ 6/);
  assert.match(page, /LCD, LEDs, buzzer and servo/);
  assert.doesNotMatch(page, /relay-driven gate response|relay and DC motor|weather context/i);
  assert.match(demo, /fetch\("\/assets\/skyeta-model\.json"/);
  assert.match(demo, /\/api\/skyeta\/live-flights/);
  assert.match(
    demo,
    /new URLSearchParams\(\{\s*origin: preset\.origin,\s*destination: preset\.destination,\s*\}\)/s,
  );
  assert.doesNotMatch(demo, /airline: preset\.carrier/);
  assert.match(
    demo,
    /setPrediction\(nextPrediction\);\s*setWhatIfOffset\(0\);\s*void loadLiveFlights\(selectedPreset\);/s,
  );
  assert.match(demo, /Other current departures on this route/);
  assert.match(demo, /checks all airlines currently listed/);
  assert.match(demo, /no fares, seats or booking availability/);
  assert.match(demo, /No flight has been invented/);
  assert.match(demo, /Would another departure time look better\?/);
  assert.match(demo, /SkyETA ready/);
  assert.match(demo, /Lower-risk range/);
  assert.match(demo, /Chance of arriving 15\+ minutes late/);
  assert.match(demo, /About \{comparableFlightCount\} in 100 similar flights/);
  assert.match(demo, /SkyETA flight review/);
  assert.match(demo, /What this result means/);
  assert.match(demo, /Advanced schedule details/);
  assert.match(demo, /Choose an airline and route/);
  assert.match(demo, /Check late-arrival chance/);
  assert.match(demo, /probabilityPercent\.toFixed\(1\)/);
  assert.doesNotMatch(
    demo,
    /SkyETA-generated summary|customer review|testimonial|createFlightReview|Weather observations included/i,
  );
  assert.doesNotMatch(
    demo,
    /SkyETA engineering review|createEngineeringReview|customer review|generative AI/i,
  );
  assert.doesNotMatch(demo, /AIRLABS_API_KEY|api_key/);
  assert.doesNotMatch(
    demo,
    /Jan-Sep 2025 training baseline|2025 train|training-period baseline|Training-baseline comparison|Temporal validation ROC-AUC|Held-out test ROC-AUC|Probability output:|validation gain vs core/i,
  );
  assert.doesNotMatch(
    demo,
    /LightGBM model loaded and verified|loaded LightGBM model|historical evidence only|no testimonials or invented live data|Shown as a continuous model estimate/i,
  );
  assert.doesNotMatch(
    demo,
    /About this estimate|Calculation stays in this browser|Data source: U\.S\. BTS flight records/i,
  );
  assert.doesNotMatch(
    demo,
    /Flight intelligence \/ SkyETA \+ live routes|Processed on device|Calculate Delay Risk|Comparable patterns/i,
  );
  assert.match(demo, /skyeta-demo__network" aria-hidden="true"/);
  assert.match(demo, /skyeta-demo__radar/);
  assert.match(demo, /skyeta-demo__flight-path/);
  assert.match(demo, /skyeta-demo__flight-path--secondary/);
  assert.match(styles, /@keyframes skyeta-radar-blip/);
  assert.match(styles, /@keyframes skyeta-radar-sweep/);
  assert.match(styles, /@keyframes skyeta-flight-track/);
  assert.match(styles, /@keyframes skyeta-route-packet/);
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
    access(new URL("public/assets/portrait-web-mobile.webp", root)),
    access(new URL("public/assets/portrait-secondary-web.jpg", root)),
    access(new URL("public/assets/portrait-secondary-web-mobile.webp", root)),
    access(new URL("public/assets/skyeta-logo-clean.png", root)),
    access(new URL("public/assets/boost-converter-qucs.webp", root)),
    access(new URL("public/assets/gic-schematic.webp", root)),
    access(new URL("public/assets/instrumentation-amplifier.webp", root)),
    access(new URL("public/assets/pfd-charge-pump.webp", root)),
    access(new URL("public/assets/svf-schematic.webp", root)),
    access(new URL("public/favicon.png", root)),
    access(new URL("public/og-v2.jpg", root)),
  ]);
});

test("SkyETA is also available as a standalone product route", async () => {
  const [page, styles] = await Promise.all([
    readFile(new URL("app/skyeta/page.tsx", root), "utf8"),
    readFile(new URL("app/skyeta/skyeta.module.css", root), "utf8"),
  ]);

  assert.match(
    page,
    /import DeferredSkyetaDemo from "\.\.\/components\/DeferredSkyetaDemo"/,
  );
  assert.match(page, /href="\/"/);
  assert.match(page, /id="skyeta-demo"/);
  assert.match(page, /<DeferredSkyetaDemo headingLevel="h2" \/>/);
  assert.match(page, /<dt>Source<\/dt>\s*<dd>U\.S\. BTS records<\/dd>/);
  assert.match(page, /<dd>SkyETA<\/dd>/);
  assert.match(page, /<dt>Delay means<\/dt>\s*<dd>15\+ minutes late<\/dd>/);
  assert.match(page, /<dt>Current flights<\/dt>\s*<dd>AirLabs<\/dd>/);
  assert.match(page, /Smart flight delay outlook/);
  assert.doesNotMatch(page, /<dt>Training data<\/dt>/);
  assert.doesNotMatch(page, /On device|Flight intelligence \/ SkyETA \+ live routes/);
  assert.doesNotMatch(page, /weather context/i);
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

test("analytics stays deployment-gated and privacy scoped", async () => {
  const [layout, analytics] = await Promise.all([
    readFile(new URL("app/layout.tsx", root), "utf8"),
    readFile(new URL("app/components/SectionAnalytics.tsx", root), "utf8"),
  ]);

  assert.match(layout, /NEXT_PUBLIC_UMAMI_WEBSITE_ID/);
  assert.match(layout, /NEXT_PUBLIC_UMAMI_DOMAIN/);
  assert.match(layout, /NODE_ENV === "production"/);
  assert.match(layout, /data-do-not-track="true"/);
  assert.match(layout, /data-domains=\{umamiDomain\}/);
  assert.match(analytics, /navigator\.doNotTrack === "1"/);
  assert.match(analytics, /"section-view"/);
  assert.doesNotMatch(analytics, /\.identify\s*\(/);
  assert.doesNotMatch(
    analytics,
    /localStorage|sessionStorage|document\.cookie/,
  );
});
