# Engineering portfolio restructure

## Audit and decisions

The existing application uses Next.js App Router conventions, React 19 and
TypeScript, with vinext/Vite building a Cloudflare Worker. It is not a plain
static portfolio: SkyETA has provider adapters, server routes, booking/payment
logic and D1 state. Those application boundaries and deployment settings are
retained.

| Finding | Change |
| --- | --- |
| Experience appeared before project evidence. | Homepage now follows introduction, capabilities, projects, circuits/PCB, experience, profile/skills and contact. Navigation follows that reading order. |
| Three long six-question briefs duplicated the case-study presentation. | Full briefs are preserved on the relevant project pages. SkyETA receives `/projects/skyeta`; its application stays at `/skyeta`. |
| The PCB was separated from the featured projects. | AuraPass, SkyETA and the Incubator Carrier PCB share one consistent project-card group. |
| Oversized display text and large section gaps made the homepage slow to scan. | Smaller headings, tighter spacing, readable body copy and explicit project status labels. |
| Global CSS contains successive redesign overrides and shared product rules. | New homepage styling is isolated in `app/home.module.css`; the new SkyETA case study has its own small module. Existing product styles are retained to limit regression risk. |
| Earlier mobile experience rules explicitly placed content in column 2. | Scoped column resets prevent those rules from creating unintended columns in the new phone layout. |
| Technical drawings require more space than a homepage thumbnail. | All five studies remain directly linked; the complete diagrams and caveats remain on `/projects/circuits`. The PCB section links to full layout and verification evidence. |

## Accuracy and preservation

- AuraPass is an offline prototype with a simulated gate. Its full evaluation,
  source link, architecture, screenshots and CSV remain available.
- SkyETA's provider-backed fares, historical records and trained U.S. model
  estimates remain distinct. No new performance results are claimed.
- The two-layer PCB passed its saved design checks but is not bench-tested.
  Its card labels the image as a KiCad render; the case study retains the
  saved-check configuration and physical/safety limitations.
- Both portraits, CV, email, telephone, GitHub and LinkedIn links are retained.
- The contact form, analytics controls, mobile menu behavior, API handlers,
  provider logic, model data, secrets configuration and database are unchanged.
- No dependencies were added. No merge, deployment or database operation was run.

## Verification

Run from the repository root:

```sh
npm ci --no-audit --no-fund
npm run lint
npx tsc --noEmit
npm run build
node --test tests/*.test.mjs
```

The existing source-level tests now verify the new homepage sequence, the
PCB/prototype status labels, the relocated SkyETA explanation and the new
sitemap entry. Existing product and contact regression checks are retained.

Responsive rules were reviewed at the 1000px, 820px and 560px breakpoints,
including grid minimum widths, image sizing, long text, navigation targets
and contact controls. Browser-based visual verification could not be performed:
the managed environment did not expose the required browser-preview tooling.
No live fare searches, payments or contact messages were submitted. Automated
checks do not establish production provider availability or email delivery.

Before merging, visually review the branch at phone and desktop widths,
including keyboard navigation and project-page return links. Production
publication remains subject to the owner's approval.
