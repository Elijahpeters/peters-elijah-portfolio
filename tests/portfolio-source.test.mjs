import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("portfolio source exposes the complete recruiter path", async () => {
  const [page, demo, deferredDemo, caseStudy, styles, skyetaCaseStudy] = await Promise.all([
    readFile(new URL("app/page.tsx", root), "utf8"),
    readFile(new URL("app/components/SkyetaDemo.tsx", root), "utf8"),
    readFile(new URL("app/components/DeferredSkyetaDemo.tsx", root), "utf8"),
    readFile(new URL("app/projects/aurapass/page.tsx", root), "utf8"),
    readFile(new URL("app/globals.css", root), "utf8"),
    readFile(new URL("app/projects/skyeta/page.tsx", root), "utf8"),
  ]);

  const content = await readFile(new URL("app/cms/content.ts", root), "utf8");
  const portfolio = await readFile(new URL("app/cms/Portfolio.tsx", root), "utf8");
  const navigation = await readFile(new URL("app/cms/Navigation.tsx", root), "utf8");
  assert.match(page, /getPublished/);
  assert.match(page, /<Portfolio content=/);
  assert.equal((portfolio.match(/<h1\b/g) ?? []).length, 1);
  for (const id of ['projects','circuits','experience','about','contact']) assert.ok(portfolio.includes(`id="${id}"`));
  assert.match(portfolio, /<ContactForm contactEmail=/);
  assert.match(content, /Design checks passed · not bench-tested/);
  assert.match(content, /Offline prototype · simulated gate/);
  assert.match(content, /Peters Elijah Temidayo/);
  assert.match(content, /elijah-portrait-2026.png/);
  assert.match(navigation, /aria-expanded=\{open\}/);
  assert.match(navigation, /Escape/);
  assert.match(portfolio, /c.design.sections.filter/);
  assert.match(skyetaCaseStudy, /skyeta-portfolio-preview/);
  assert.match(deferredDemo, /lazy\(\(\) => import\("\.\/SkyetaDemo"\)\)/);
  assert.match(deferredDemo, /new IntersectionObserver/);
  assert.match(deferredDemo, /isSmallScreen \? "160px 0px" : "700px 0px"/);
  assert.match(skyetaCaseStudy, /How SkyETA works/);
  assert.match(skyetaCaseStudy, /Search the journey/);
  assert.match(skyetaCaseStudy, /Compare real options/);
  assert.match(skyetaCaseStudy, /Understand the evidence/);
  assert.match(skyetaCaseStudy, /labels provider fares, observed AirLabs information and/);
  // Technical evidence lives on the case study, not repeated on the homepage.
  assert.match(caseStudy, /5,000/);
  assert.match(caseStudy, /Total non-enrolled face attempts/);
  assert.match(caseStudy, /False grants in this controlled set/);
  assert.match(caseStudy, /10 variants/);
  assert.match(caseStudy, /does not represent overall/);
  assert.match(caseStudy, /3,793/);
  assert.match(caseStudy, /1,207/);
  assert.match(caseStudy, /aurapass-negative-face-evaluation-summary\.csv/);
  assert.match(caseStudy, /LCD, LEDs, buzzer and simulated servo gate/);
  assert.match(caseStudy, /anti-spoof liveness/);
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
  assert.match(demo, /Chance of arriving 15\+ minutes late/);
  assert.match(demo, /About \{comparableFlightCount\} in 100 similar flights/);
  assert.match(demo, /Plain-language explanation/);
  assert.match(demo, /What this means for you/);
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
  assert.doesNotMatch(demo, /Higher than usual|Lower than usual|Similar to usual|usual reference pattern/);
  assert.doesNotMatch(
    demo,
    /Similar flights with these details (?:arrived|were)/,
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
    access(new URL("public/assets/aurapass-negative-face-evaluation-summary.csv", root)),
    access(new URL("app/projects/aurapass/page.tsx", root)),
  ]);
});

test("SkyETA is also available as a standalone product route", async () => {
  const [page, styles, disclosure, tabs] = await Promise.all([
    readFile(new URL("app/skyeta/page.tsx", root), "utf8"),
    readFile(new URL("app/skyeta/skyeta.module.css", root), "utf8"),
    readFile(
      new URL("app/skyeta/components/DelayLabDisclosure.tsx", root),
      "utf8",
    ),
    readFile(new URL("app/skyeta/components/SkyetaToolTabs.tsx", root), "utf8"),
  ]);

  assert.match(page, /import SkyetaToolTabs from "\.\/components\/SkyetaToolTabs"/);
  assert.match(page, /href="\/"/);
  assert.match(page, /<SkyetaToolTabs/);
  assert.match(tabs, /<DelayLabDisclosure defaultOpen \/>/);
  assert.match(disclosure, /id="skyeta-delay-lab"/);
  assert.match(disclosure, /<DeferredSkyetaDemo headingLevel="h3" \/>/);
  assert.match(tabs, /Find flights worldwide/);
  assert.match(tabs, /U\.S\. delay research lab/);
  assert.match(page, /Flight search \+ reliability evidence/);
  assert.match(page, /One search, three layers of information/);
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
