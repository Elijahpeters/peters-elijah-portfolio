# Portfolio restructuring and identity SEO — review package

Date: 13 October 2026

Revision: homepage description shortened to the owner’s exact wording. The shared homepage Open Graph/Twitter descriptions follow the same value. Header/footer branding, visible identity copy and Person schema are unchanged. All validation checks rerun successfully.

## Release status and scope

**Local review only. No new push, PR update, merge or deployment was performed for this SEO pass.**
Local branch: `seo/identity-review`. SEO comparison baseline: `461d1e921fdff6da6b8fab2e529e15352be452c5` (the previously completed restructuring).
The earlier restructuring already has draft PR #2, created before this no-push instruction: https://github.com/Elijahpeters/peters-elijah-portfolio/pull/2. It was not updated by this pass. Its branch tree matches the local SEO baseline. Do not merge that PR expecting these new SEO changes.
The cumulative patch compares the original source baseline `06e33216c78d3f73a23cad549c261d6bfff23abc` with the full local result. The incremental patch compares the restructuring baseline with this SEO pass. Apply only the patch appropriate to the checkout; do not apply both.

## Summary

- Preserves the existing restructuring: introduction → What I Build → featured projects → circuit/PCB work → experience → profile/skills → contact.
- Establishes Peters Elijah Temidayo as the formal name and Elijah Peters as the professional name in visible copy, metadata and Person schema.
- Gives all four engineering case studies independent titles, descriptions, canonicals, Open Graph and Twitter metadata. SkyETA product metadata is aligned separately.
- Keeps the existing portraits and sharing artwork, technical evidence, source links, CV, analytics, accessibility features, responsive CSS, providers and database behavior.
- Fixes the public origin for SEO and adds the sitemap reference to robots. No dependency changes.

## Every file changed in this SEO pass

| File | Change |
|---|---|
| `app/layout.tsx` | Connects both names in title/description; fixes the public metadata base; updates site name and portrait OG/Twitter alt text. Analytics and icons preserved. |
| `app/page.tsx` | Adds homepage Person JSON-LD; connects full and professional names; uses Elijah Peters for short labels and portrait alt text; makes power electronics and hardware/software integration explicit. |
| `app/components/SiteHeader.tsx` | Changes short brand and accessible home label from Peters Elijah to Elijah Peters. Navigation behavior is unchanged. |
| `app/lib/person-schema.ts` | New public Person schema with verified identity, university, expertise and only the supplied LinkedIn/GitHub profiles. |
| `app/projects/aurapass/page.tsx` | Unique biometric-prototype title, description, canonical and complete OG/Twitter metadata. Case-study evidence unchanged. |
| `app/projects/incubator-carrier/page.tsx` | Unique KiCad PCB metadata and explicit passed-design-checks/not-bench-tested limitation. Evidence unchanged. |
| `app/projects/circuits/page.tsx` | Unique circuit-design/simulation metadata, with all five study subjects and professional name. Studies unchanged. |
| `app/projects/skyeta/page.tsx` | Unique flight-intelligence case-study metadata and route-specific SkyETA sharing image. Model coverage and case-study evidence preserved. |
| `app/skyeta/layout.tsx` | Updates inherited product sharing title/description and name-aware image alt text; preserves product canonical and image route. |
| `app/skyeta/page.tsx` | Aligns product page title/description with sharing metadata. No provider, search, prediction or checkout logic changes. |
| `app/skyeta/opengraph-image.tsx` | Updates exported image alt text to connect both names. Image artwork and formal-name attribution unchanged. |
| `app/sitemap.ts` | Uses the fixed production domain instead of an environment-dependent domain; all nine public pages retained. |
| `public/robots.txt` | Adds absolute Sitemap directive, retaining unrestricted crawling. |
| `tests/portfolio-source.test.mjs` | Updates the existing title expectation to the requested full/professional-name title. |
| `tests/portfolio-seo.test.mjs` | Adds four regression tests for identity/schema, complete project metadata, SkyETA metadata consistency and preview-independent sitemap/robots. |
| `docs/SEO-IDENTITY-REVIEW.md` | This review package: exact metadata, copy, schema, sitemap, validation results and manual release checklist. |

## Earlier restructuring included in the cumulative patch

These changes predate this SEO pass. See `docs/PORTFOLIO-RESTRUCTURE.md` and the cumulative diff for the full audit.

| File | Earlier change |
|---|---|
| `app/page.tsx` | Reordered and shortened homepage; featured project cards; preserved photos, contact and links. |
| `app/home.module.css` | Scoped homepage typography, spacing, cards and mobile breakpoint fixes. |
| `app/components/ExperienceSection.tsx` | Experience section label/heading. |
| `app/components/SiteHeader.tsx` | Recruiter-oriented navigation order and labels. |
| `app/components/ProjectBrief.tsx` | Corrected technical brief heading level to h2. |
| `app/globals.css` | Adjusted brief heading selector for h2. |
| `app/projects/aurapass/page.tsx` | Moved technical brief after the main introduction/evidence. |
| `app/projects/incubator-carrier/page.tsx` | Moved technical brief after the main introduction/evidence. |
| `app/projects/skyeta/page.tsx` | New case-study route containing the detailed SkyETA material moved off the homepage. |
| `app/projects/skyeta/case-study.module.css` | Scoped presentation for the SkyETA case study. |
| `app/sitemap.ts` | Added the SkyETA case-study URL. |
| `tests/portfolio-source.test.mjs` | Updated source regression assertions for the structure and preserved content. |
| `tests/contact-accessibility-and-sitemap.test.mjs` | Added SkyETA case-study sitemap expectation. |
| `docs/PORTFOLIO-RESTRUCTURE.md` | Audit findings, changes, preservation and QA limitations. |

## Exact before-and-after SEO metadata

The following JSON is evaluated from the static metadata declarations, not paraphrased. “Before” means the restructuring baseline. Fields absent from a page were inherited or filled by the framework; they were not independently defined. Previously, project pages inherited the homepage Twitter title/description. The new explicit project Twitter metadata fixes this.
Before: root `metadataBase` was undefined when `NEXT_PUBLIC_SITE_URL` was absent, or equal to that environment value when configured. No environment values or secrets were read into this report. After: the root base is always `https://peterselijah.name.ng/`.
All relative canonical/image paths below resolve against that public origin. The supplied `metadata-rendered.json` additionally contains framework-merged metadata and rendered head tags for six reviewed routes; its BEFORE comparison explicitly assumes the public origin because the old production environment value is not known.
File-based SkyETA image metadata may be normalized by the framework at runtime; the image route remains `/skyeta/opengraph-image`. The image module’s exact alt change is listed below. No deployed HTTP response or social crawler cache was tested.

### `app/layout.tsx`

**Before**
```json
{
  "title": "Peters Elijah Temidayo",
  "description": "Portfolio of Peters Elijah Temidayo—an Electrical & Electronics Engineer working across circuit design, AI/ML and hardware co-simulation.",
  "alternates": {
    "canonical": "/"
  },
  "icons": {
    "icon": "/favicon.png",
    "shortcut": "/favicon.png"
  },
  "openGraph": {
    "type": "website",
    "url": "/",
    "siteName": "Peters Elijah Temidayo",
    "title": "Peters Elijah Temidayo",
    "description": "Portfolio of Peters Elijah Temidayo—an Electrical & Electronics Engineer working across circuit design, AI/ML and hardware co-simulation.",
    "images": [
      {
        "url": "/og-v2.jpg",
        "secureUrl": "/og-v2.jpg",
        "type": "image/jpeg",
        "width": 1200,
        "height": 630,
        "alt": "Peters Elijah Temidayo, Electrical and Electronics Engineer"
      }
    ]
  },
  "twitter": {
    "card": "summary_large_image",
    "title": "Peters Elijah Temidayo",
    "description": "Portfolio of Peters Elijah Temidayo—an Electrical & Electronics Engineer working across circuit design, AI/ML and hardware co-simulation.",
    "images": [
      "/og-v2.jpg"
    ]
  }
}
```

**After**
```json
{
  "metadataBase": "https://peterselijah.name.ng/",
  "title": "Peters Elijah Temidayo (Elijah Peters) | Electrical & Electronics Engineer",
  "description": "Portfolio of Peters Elijah Temidayo (Elijah Peters), an Electrical & Electronics Engineer focused on embedded systems, circuit/PCB design and applied AI/ML.",
  "alternates": {
    "canonical": "/"
  },
  "icons": {
    "icon": "/favicon.png",
    "shortcut": "/favicon.png"
  },
  "openGraph": {
    "type": "website",
    "url": "/",
    "siteName": "Elijah Peters | Engineering Portfolio",
    "title": "Peters Elijah Temidayo (Elijah Peters) | Electrical & Electronics Engineer",
    "description": "Portfolio of Peters Elijah Temidayo (Elijah Peters), an Electrical & Electronics Engineer focused on embedded systems, circuit/PCB design and applied AI/ML.",
    "images": [
      {
        "url": "/og-v2.jpg",
        "secureUrl": "/og-v2.jpg",
        "type": "image/jpeg",
        "width": 1200,
        "height": 630,
        "alt": "Peters Elijah Temidayo (Elijah Peters), Electrical & Electronics Engineer"
      }
    ]
  },
  "twitter": {
    "card": "summary_large_image",
    "title": "Peters Elijah Temidayo (Elijah Peters) | Electrical & Electronics Engineer",
    "description": "Portfolio of Peters Elijah Temidayo (Elijah Peters), an Electrical & Electronics Engineer focused on embedded systems, circuit/PCB design and applied AI/ML.",
    "images": [
      {
        "url": "/og-v2.jpg",
        "alt": "Peters Elijah Temidayo (Elijah Peters), Electrical & Electronics Engineer"
      }
    ]
  }
}
```

### `app/skyeta/layout.tsx`

**Before**
```json
{
  "metadataBase": "https://peterselijah.name.ng/",
  "alternates": {
    "canonical": "/skyeta"
  },
  "openGraph": {
    "type": "website",
    "url": "/skyeta",
    "siteName": "SkyETA",
    "title": "SkyETA — Compare flights and reliability evidence",
    "description": "Compare current flights worldwide. Review historical reliability where records exist, with a separate trained model for selected U.S. domestic routes.",
    "images": [
      {
        "url": "/skyeta/opengraph-image",
        "secureUrl": "/skyeta/opengraph-image",
        "type": "image/png",
        "width": 1200,
        "height": 630,
        "alt": "SkyETA by Peters Elijah Temidayo"
      }
    ]
  },
  "twitter": {
    "card": "summary_large_image",
    "title": "SkyETA — Compare flights and reliability evidence",
    "description": "Compare current flights worldwide. Review historical reliability where records exist, with a separate trained model for selected U.S. domestic routes.",
    "images": [
      "/skyeta/opengraph-image"
    ]
  }
}
```

**After**
```json
{
  "metadataBase": "https://peterselijah.name.ng/",
  "alternates": {
    "canonical": "/skyeta"
  },
  "openGraph": {
    "type": "website",
    "url": "/skyeta",
    "siteName": "SkyETA",
    "title": "SkyETA | Flight Search & Reliability by Elijah Peters",
    "description": "Compare flights worldwide with SkyETA by Elijah Peters. Explore historical reliability where records exist and delay predictions for selected U.S. domestic routes.",
    "images": [
      {
        "url": "/skyeta/opengraph-image",
        "secureUrl": "/skyeta/opengraph-image",
        "type": "image/png",
        "width": 1200,
        "height": 630,
        "alt": "SkyETA by Elijah Peters (Peters Elijah Temidayo)"
      }
    ]
  },
  "twitter": {
    "card": "summary_large_image",
    "title": "SkyETA | Flight Search & Reliability by Elijah Peters",
    "description": "Compare flights worldwide with SkyETA by Elijah Peters. Explore historical reliability where records exist and delay predictions for selected U.S. domestic routes.",
    "images": [
      {
        "url": "/skyeta/opengraph-image",
        "alt": "SkyETA by Elijah Peters (Peters Elijah Temidayo)"
      }
    ]
  }
}
```

### `app/skyeta/page.tsx`

**Before**
```json
{
  "title": "SkyETA — Compare flights and reliability evidence",
  "description": "Compare current flights worldwide. Review historical reliability where records exist, with a separate trained model for selected U.S. domestic routes."
}
```

**After**
```json
{
  "title": "SkyETA | Flight Search & Reliability by Elijah Peters",
  "description": "Compare flights worldwide with SkyETA by Elijah Peters. Explore historical reliability where records exist and delay predictions for selected U.S. domestic routes."
}
```

### `app/projects/aurapass/page.tsx`

**Before**
```json
{
  "title": "AuraPass engineering case study",
  "description": "Architecture, validation method and simulation evidence for Peters Elijah's AuraPass access-control prototype.",
  "alternates": {
    "canonical": "/projects/aurapass"
  },
  "openGraph": {
    "url": "/projects/aurapass",
    "title": "AuraPass engineering case study",
    "description": "Architecture, validation method and simulation evidence for Peters Elijah's AuraPass access-control prototype."
  }
}
```

**After**
```json
{
  "title": "AuraPass | Biometric Access Control by Elijah Peters",
  "description": "An offline examination-access prototype by Elijah Peters combining computer vision, student eligibility, seat allocation and simulated gate control.",
  "alternates": {
    "canonical": "/projects/aurapass"
  },
  "openGraph": {
    "type": "website",
    "siteName": "Elijah Peters | Engineering Portfolio",
    "url": "/projects/aurapass",
    "title": "AuraPass | Biometric Access Control by Elijah Peters",
    "description": "An offline examination-access prototype by Elijah Peters combining computer vision, student eligibility, seat allocation and simulated gate control.",
    "images": [
      {
        "url": "/og-v2.jpg",
        "width": 1200,
        "height": 630,
        "alt": "Peters Elijah Temidayo (Elijah Peters), Electrical & Electronics Engineer"
      }
    ]
  },
  "twitter": {
    "card": "summary_large_image",
    "title": "AuraPass | Biometric Access Control by Elijah Peters",
    "description": "An offline examination-access prototype by Elijah Peters combining computer vision, student eligibility, seat allocation and simulated gate control.",
    "images": [
      {
        "url": "/og-v2.jpg",
        "alt": "Peters Elijah Temidayo (Elijah Peters), Electrical & Electronics Engineer"
      }
    ]
  }
}
```

### `app/projects/skyeta/page.tsx`

**Before**
```json
{
  "title": "SkyETA engineering case study | Peters Elijah",
  "description": "Flight-data analysis, model validation and fare-search integration behind SkyETA, including coverage and limitations.",
  "alternates": {
    "canonical": "/projects/skyeta"
  },
  "openGraph": {
    "title": "SkyETA engineering case study",
    "url": "/projects/skyeta"
  }
}
```

**After**
```json
{
  "title": "SkyETA | Flight Intelligence Case Study by Elijah Peters",
  "description": "Flight-data analysis, delay modelling and fare-search integration by Elijah Peters, with model validation, coverage limits and engineering evidence.",
  "alternates": {
    "canonical": "/projects/skyeta"
  },
  "openGraph": {
    "type": "website",
    "siteName": "Elijah Peters | Engineering Portfolio",
    "url": "/projects/skyeta",
    "title": "SkyETA | Flight Intelligence Case Study by Elijah Peters",
    "description": "Flight-data analysis, delay modelling and fare-search integration by Elijah Peters, with model validation, coverage limits and engineering evidence.",
    "images": [
      {
        "url": "/skyeta/opengraph-image",
        "width": 1200,
        "height": 630,
        "alt": "SkyETA by Elijah Peters (Peters Elijah Temidayo)"
      }
    ]
  },
  "twitter": {
    "card": "summary_large_image",
    "title": "SkyETA | Flight Intelligence Case Study by Elijah Peters",
    "description": "Flight-data analysis, delay modelling and fare-search integration by Elijah Peters, with model validation, coverage limits and engineering evidence.",
    "images": [
      {
        "url": "/skyeta/opengraph-image",
        "alt": "SkyETA by Elijah Peters (Peters Elijah Temidayo)"
      }
    ]
  }
}
```

### `app/projects/incubator-carrier/page.tsx`

**Before**
```json
{
  "title": "Incubator carrier PCB | Peters Elijah",
  "description": "A KiCad two-layer carrier-board case study: schematic organisation, component placement, routing, design checks and the boundary between CAD verification and hardware testing.",
  "alternates": {
    "canonical": "/projects/incubator-carrier"
  },
  "openGraph": {
    "title": "Incubator carrier PCB | Peters Elijah",
    "description": "Schematic, layout and recorded CAD checks for a two-layer incubator interface carrier. Not yet bench-tested.",
    "url": "/projects/incubator-carrier"
  }
}
```

**After**
```json
{
  "title": "Incubator Carrier PCB | KiCad Design by Elijah Peters",
  "description": "A two-layer KiCad incubator carrier PCB by Elijah Peters: schematic, layout and passed design checks. The board has not been physically bench-tested.",
  "alternates": {
    "canonical": "/projects/incubator-carrier"
  },
  "openGraph": {
    "type": "website",
    "siteName": "Elijah Peters | Engineering Portfolio",
    "url": "/projects/incubator-carrier",
    "title": "Incubator Carrier PCB | KiCad Design by Elijah Peters",
    "description": "A two-layer KiCad incubator carrier PCB by Elijah Peters: schematic, layout and passed design checks. The board has not been physically bench-tested.",
    "images": [
      {
        "url": "/og-v2.jpg",
        "width": 1200,
        "height": 630,
        "alt": "Peters Elijah Temidayo (Elijah Peters), Electrical & Electronics Engineer"
      }
    ]
  },
  "twitter": {
    "card": "summary_large_image",
    "title": "Incubator Carrier PCB | KiCad Design by Elijah Peters",
    "description": "A two-layer KiCad incubator carrier PCB by Elijah Peters: schematic, layout and passed design checks. The board has not been physically bench-tested.",
    "images": [
      {
        "url": "/og-v2.jpg",
        "alt": "Peters Elijah Temidayo (Elijah Peters), Electrical & Electronics Engineer"
      }
    ]
  }
}
```

### `app/projects/circuits/page.tsx`

**Before**
```json
{
  "title": "Circuit studies | Peters Elijah",
  "description": "Five circuit studies covering an active inductor, KHN filter, instrumentation amplifier, phase-frequency detector and boost power stage, with their evidence and limitations.",
  "alternates": {
    "canonical": "/projects/circuits"
  },
  "openGraph": {
    "title": "Circuit studies | Peters Elijah",
    "description": "Design goals, annotated schematics and clearly bounded findings across five circuit studies.",
    "url": "/projects/circuits"
  }
}
```

**After**
```json
{
  "title": "Circuit Design & Simulation Studies | Elijah Peters",
  "description": "Five circuit studies by Elijah Peters covering active inductors, filters, instrumentation amplifiers, phase-frequency detection and a boost power stage.",
  "alternates": {
    "canonical": "/projects/circuits"
  },
  "openGraph": {
    "type": "website",
    "siteName": "Elijah Peters | Engineering Portfolio",
    "url": "/projects/circuits",
    "title": "Circuit Design & Simulation Studies | Elijah Peters",
    "description": "Five circuit studies by Elijah Peters covering active inductors, filters, instrumentation amplifiers, phase-frequency detection and a boost power stage.",
    "images": [
      {
        "url": "/og-v2.jpg",
        "width": 1200,
        "height": 630,
        "alt": "Peters Elijah Temidayo (Elijah Peters), Electrical & Electronics Engineer"
      }
    ]
  },
  "twitter": {
    "card": "summary_large_image",
    "title": "Circuit Design & Simulation Studies | Elijah Peters",
    "description": "Five circuit studies by Elijah Peters covering active inductors, filters, instrumentation amplifiers, phase-frequency detection and a boost power stage.",
    "images": [
      {
        "url": "/og-v2.jpg",
        "alt": "Peters Elijah Temidayo (Elijah Peters), Electrical & Electronics Engineer"
      }
    ]
  }
}
```

### Resolved canonical URLs

| Page | Before path | After absolute canonical |
|---|---|---|
| `/` | `/` | `https://peterselijah.name.ng/` |
| `/skyeta` | `/skyeta` | `https://peterselijah.name.ng/skyeta` |
| `/projects/aurapass` | `/projects/aurapass` | `https://peterselijah.name.ng/projects/aurapass` |
| `/projects/skyeta` | `/projects/skyeta` | `https://peterselijah.name.ng/projects/skyeta` |
| `/projects/incubator-carrier` | `/projects/incubator-carrier` | `https://peterselijah.name.ng/projects/incubator-carrier` |
| `/projects/circuits` | `/projects/circuits` | `https://peterselijah.name.ng/projects/circuits` |

Canonical paths are unchanged from the restructuring baseline. The earlier restructuring introduced `/projects/skyeta`; that route did not exist at the original source baseline.

### Social-image verification

- `/og-v2.jpg`: existing JPEG, visually inspected at 1200 × 630. Shows the existing portrait, formal name and engineering positioning. No artwork replacement.
- `/skyeta/opengraph-image`: existing generated 1200 × 630 PNG route; production build succeeds. No rendered-image browser inspection performed.
- SkyETA exported alt BEFORE: `SkyETA — compare worldwide flights and understand reliability evidence`.
- SkyETA exported alt AFTER: `SkyETA by Elijah Peters (Peters Elijah Temidayo) — flight search and reliability evidence`.
- The image’s visible “Built by Peters Elijah Temidayo” attribution stays unchanged.

## Complete homepage Person JSON-LD

Before: no Person JSON-LD on the homepage. After:
```json
{
  "@context": "https://schema.org",
  "@type": "Person",
  "@id": "https://peterselijah.name.ng/#person",
  "name": "Peters Elijah Temidayo",
  "alternateName": "Elijah Peters",
  "url": "https://peterselijah.name.ng",
  "image": "https://peterselijah.name.ng/assets/portrait-web.jpg",
  "jobTitle": "Electrical & Electronics Engineer",
  "description": "Peters Elijah Temidayo, professionally known as Elijah Peters, is an Electrical & Electronics Engineer working across embedded systems, circuit and PCB design, power electronics, hardware/software integration and applied AI/ML.",
  "alumniOf": {
    "@type": "CollegeOrUniversity",
    "name": "Olabisi Onabanjo University"
  },
  "knowsAbout": [
    "Electrical and Electronics Engineering",
    "Circuit design and simulation",
    "PCB design",
    "Embedded systems",
    "Power electronics",
    "Hardware/software integration",
    "Computer vision",
    "Applied machine learning",
    "AI model evaluation"
  ],
  "sameAs": [
    "https://www.linkedin.com/in/elijahpeters01",
    "https://github.com/Elijahpeters"
  ]
}
```

The homepage emits this as `application/ld+json`, using JSON serialization and escaping `<` as `\u003c`. No private contact details or unverified profiles are included. The degree/university claim is already present in the biography; this schema does not assert professional registration, awards, project performance or completed hardware.

## Exact visible homepage identity text

### Introduction identity line

Before:
> Peters Elijah · Electronics, embedded systems & applied AI

After:
> Peters Elijah Temidayo, professionally known as Elijah Peters.

The adjacent engineering eyebrow and introduction remain:
> Electrical & Electronics Engineer

> I design electronic circuits, develop embedded systems, and apply machine learning to engineering problems. My work spans circuit simulation, PCB design, intelligent automation, and predictive software.

### About paragraph

Before:
> My work connects circuit design and simulation with embedded interfaces and applied machine learning. At Micro1, I review circuit designs and AI-generated engineering work for technical accuracy.

After:
> My work connects circuit design and power electronics with embedded systems, hardware/software integration and applied machine learning. At Micro1, I review circuit designs and AI-generated engineering work for technical accuracy.

### Other short labels and accessibility text

| Surface | Before | After |
|---|---|
| Header/footer brand | Peters Elijah. | Elijah Peters. |
| Header home label | Peters Elijah, home | Elijah Peters, home |
| Hero portrait alt | Peters Elijah wearing a navy suit and tie | Elijah Peters wearing a navy suit and tie |
| Secondary portrait alt | Peters Elijah in a navy suit | Elijah Peters in a navy suit |
| Hero caption | Peters Elijah / Ogun State, Nigeria | Elijah Peters / Ogun State, Nigeria |
| Profile caption | Peters Elijah / Electrical & Electronics Engineer | Elijah Peters / Electrical & Electronics Engineer |
| GitHub accessible label | Open Peters Elijah's GitHub profile in a new tab | Open Elijah Peters' GitHub profile in a new tab |
| LinkedIn accessible label | Open Peters Elijah's LinkedIn profile in a new tab | Open Elijah Peters' LinkedIn profile in a new tab |

### Heading and project text review

Homepage retains one h1: “Circuit design. PCB layout. Intelligent systems.” Section h2 headings and card h3 headings remain logical; no extra heading was added for SEO. Project pages retain their technical introductions, evidence and headings. Their SEO changes in this pass are metadata-only. Prototype, selected-U.S.-model and not-bench-tested caveats remain intact. No performance figures were invented.

## robots.txt — complete content

**Before**
```text
User-agent: *
Allow: /
```

**After**
```text
User-agent: *
Allow: /

Sitemap: https://peterselijah.name.ng/sitemap.xml
```

## Sitemap — complete configuration

Before: the same nine entries used `NEXT_PUBLIC_SITE_URL` if accepted, otherwise the production origin. After: all entries always use the canonical public domain. No invented last-modified dates are emitted. Checkout, payment return and API routes remain excluded. Circuit studies are sections on one public route, not separate pages.

```ts
import type { MetadataRoute } from "next";

const PRODUCTION_SITE_URL = "https://peterselijah.name.ng";

export default function sitemap(): MetadataRoute.Sitemap {
  const origin = PRODUCTION_SITE_URL;

  return [
    {
      url: `${origin}/`,
      changeFrequency: "monthly",
      priority: 1,
    },
    {
      url: `${origin}/skyeta`,
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${origin}/skyeta/help`,
      changeFrequency: "monthly",
      priority: 0.5,
    },
    {
      url: `${origin}/skyeta/privacy`,
      changeFrequency: "yearly",
      priority: 0.4,
    },
    {
      url: `${origin}/skyeta/terms`,
      changeFrequency: "yearly",
      priority: 0.4,
    },
    {
      url: `${origin}/projects/skyeta`,
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${origin}/projects/aurapass`,
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${origin}/projects/incubator-carrier`,
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${origin}/projects/circuits`,
      changeFrequency: "monthly",
      priority: 0.8,
    },
  ];
}
```

## Validation results

| Check | Result |
|---|---|
| `npm run lint` | PASS, exit 0; no ESLint errors or warnings |
| `npx tsc --noEmit` | PASS, exit 0 |
| `npm test` | PASS, exit 0; runs `vinext build` then all test files |
| Production build | PASS, all five build phases completed |
| Automated tests | 207 passed; 0 failed, skipped or cancelled |
| Metadata inspection | Six route metadata sets merged/rendered with installed Vinext MetadataHead; absolute canonical and social tags verified |
| Person JSON | Successfully serialized/parsed; name, alternateName, alumni and exact two sameAs profiles asserted |
| `git diff --check` | PASS |
| Mobile layout | Responsive CSS reviewed; new identity text wraps in existing containers. No new CSS changes in this SEO pass. Browser visual QA unavailable |

### Warnings, assumptions and remaining limits

- npm prints an environment warning about the `http-proxy` config becoming unsupported in a future major version. The build also reports that proxy environment variables are detected. Neither is a lint/build/test failure; no dependency/config change was made for these environment warnings.
- Installed production framework is Vinext/Vite using Next.js conventions. Validation used the repository’s actual build command, not an unrelated `next build`.
- The managed environment does not expose the required browser-preview tooling. No desktop/mobile screenshot, keyboard-interaction run or deployed social scraper test was performed. Review locally at narrow phone widths and desktop before approval.
- Metadata head inspection executes static declarations and the installed renderer; it is not a complete running Worker HTTP test and does not reproduce every file-based image normalization step.
- No real contact submissions, fare-provider calls, payments or emails were sent. Tests do not prove production credential validity or provider availability.
- Public production origin is intentionally fixed for SEO. If the domain changes, update root metadata, SkyETA origin, schema URLs, sitemap and robots together.
- Existing trust-page metadata, historical source attribution and CV content are retained. Both names are not forced into every heading or historical artifact.
- Google may rewrite titles/descriptions and does not guarantee indexing, rankings or recognition of the name relationship.

## Diff package and reproduction

- `seo-identity.patch`: every new change relative to the restructuring baseline, including this report and new tests/schema.
- `portfolio-complete.patch`: earlier restructuring plus this SEO pass relative to the original source baseline.
- `metadata-before.json` / `metadata-after.json`: exact evaluated declaration snapshots.
- `metadata-rendered.json`: merged metadata and head HTML from the installed renderer.
- `lint.log`, `typecheck.log`, `test.log`: complete validation output.

```sh
npm run lint
npx tsc --noEmit
npm test
git diff --check
```

## Manual checklist after explicit approval and deployment

- [ ] First approve the reviewed code. Push/PR update, merge and deployment remain separate actions requiring your explicit authorization. Nothing in this checklist authorizes them.
- [ ] Check the live homepage and five project/product routes at phone and desktop widths, with keyboard navigation; verify CV, contact and external links.
- [ ] Inspect live HTML for title, description, canonical, OG/Twitter tags and the Person JSON-LD. Confirm image URLs, robots and sitemap return successful public responses.
- [ ] Verify ownership of `peterselijah.name.ng` in Google Search Console if not already verified.
- [ ] Submit `https://peterselijah.name.ng/sitemap.xml` in Search Console.
- [ ] Use URL Inspection to inspect the homepage and changed project pages; request indexing after successful live checks. Repeated requests do not speed crawling.
- [ ] Monitor Page Indexing, Google-selected canonical and Performance queries for both names over the following weeks.
- [ ] Check LinkedIn/social sharing previews; refresh cached previews where those platforms offer that facility.
- [ ] Keep LinkedIn/GitHub bios and their portfolio links consistent with your chosen professional name. No profile was changed by this work.

References: [Google: request recrawling](https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl); [Google: build and submit a sitemap](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap). Crawling can take days to weeks and requests do not guarantee indexing.

**STOP: await the owner’s explicit approval. Do not push, merge or deploy this review package.**
