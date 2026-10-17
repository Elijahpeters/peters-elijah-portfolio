# Elijah Peters — engineering portfolio & content studio

A new portfolio presentation for **Peters Elijah Temidayo**, professionally known as **Elijah Peters**. The public experience leads with electrical/electronics engineering, then selected work, supporting technical evidence, experience, skills and contact.

The replacement is developed on `rebuild/portfolio-cms`. It does **not** replace the current production site until a separately verified release. The existing project evidence, source links, assets, contact integration and SkyETA application are retained. The public homepage, editable project pages, design system and admin dashboard are new.

## What is included

- A responsive portfolio using the owner's new navy-suit portrait.
- Editable projects and circuit studies at `/work/[slug]`.
- A content studio at `/admin`, backed by a separate Cloudflare D1 database.
- Draft → preview → publish, without rebuilding application code.
- Published-version history, restore-to-draft, and JSON export/import.
- Image and CV uploads stored in the dedicated CMS database; R2 is optional.
- A visual designer: palettes, individual colours, typography, section spacing, corner rounding, content width, introduction layout and project layout.
- Reorder or hide sections; add text, image-left, image-right and callout sections. Ordering changes the DOM reading order as well as the visual order.
- Live draft preview at mobile (390px) and desktop (1100px) widths inside the dashboard.
- Published content drives homepage metadata, Person JSON-LD, editable project metadata and sitemap URLs.
- Original `/projects/*` evidence routes and `/skyeta` remain available.

**No-code scope:** supported content, design controls, page sections and editable case studies need no code or redeployment. A new block *type*, a new integration, a new application feature, changes to archived evidence templates, or SkyETA provider/model logic still require development. This is a portfolio-focused editor, not an unrestricted HTML/CSS/code execution system. Original `/projects/*` pages are retained evidence archives; their new editable counterparts are under `/work/*`.

## Reading the portfolio

The default homepage follows this sequence:

1. Professional introduction, photograph, work link and CV.
2. Selected work: AuraPass, SkyETA and Incubator Carrier PCB.
3. Three areas of practice: circuits/PCB, embedded systems, applied AI/ML.
4. Circuit studies.
5. Professional experience.
6. About and grouped technical skills.
7. Contact and professional profiles.

AuraPass remains labelled as an offline prototype with simulated gate hardware. The PCB has passed recorded design checks but **has not been physically bench-tested**. SkyETA coverage and provider availability are not represented as unlimited.

## Identity and SEO contract

- Header/footer brand: **Elijah Peters**.
- Visible identity: **Peters Elijah Temidayo, professionally known as Elijah Peters.**
- Homepage title: **Peters Elijah Temidayo (Elijah Peters) | Electrical & Electronics Engineer**.
- Homepage description: **Portfolio of Peters Elijah Temidayo (Elijah Peters), an Electrical & Electronics Engineer focused on embedded systems, circuit/PCB design and applied AI/ML.**
- Person JSON-LD retains the full name, alternate name, engineering role, OOU affiliation, expertise and only the verified LinkedIn/GitHub profiles.
- Each original project page retains independent metadata. Editable `/work/*` pages use their own title, summary, canonical and project image for Open Graph/Twitter, falling back to the homepage image when absent.
- Canonicals and sitemap default to `https://peterselijah.name.ng`. `NEXT_PUBLIC_SITE_URL` must match the final approved production origin.
- The sitemap includes `/projects/skyeta`, the other original project pages, editable case studies and public SkyETA pages.
- `robots.txt` allows public crawling and references the sitemap; admin and CMS API paths are excluded.
- **Staging intentionally uses `noindex`.** Public launch requires `PORTFOLIO_PUBLIC=true` and verification of the rendered response. Allowing crawling in robots.txt alone does not enable indexing.

### Current delivery status

Source implementation and automated validation are separate from a deployed product. The static HTML preview demonstrates the homepage design only: internal project/CV navigation, contact submission and the admin backend cannot be tested from that file. The running application contains these routes, but hosted login, storage, uploads, publishing, provider integrations and desktop/mobile browser QA still need verification before release. Do not describe them as live or verified based on the static file.

## Architecture

| Layer | Implementation |
| --- | --- |
| UI | React 19, TypeScript, scoped CSS modules |
| Application framework | Existing Vinext / Vite stack with Next.js app conventions |
| Runtime | Cloudflare Worker, separately named `elijah-portfolio-next` |
| Portfolio content | `CMS_DB` — dedicated D1 database |
| Uploads | `CMS_DB` by default; optional `CMS_MEDIA` R2 bucket |
| Existing SkyETA data | `DB` — separate SkyETA D1 binding |
| Admin authentication | High-entropy access key in a runtime secret; signed, expiring, HttpOnly cookie |
| Contact delivery | Existing server integration; configured independently from displayed contact details |

`app/cms/content.ts` contains the typed initial content and validation rules. Public pages read the published database snapshot, while the dashboard reads the draft. Publishing performs a transactional database update and stores a version. It does not invoke Git or a deployment.

There is no client-side database credential, no admin key in JavaScript bundles, and no browser-localStorage content store. Public dynamic portfolio pages and private previews use `Cache-Control: no-store`.

## Local development

Use Node.js 22.13+ (validated with Node 24) and npm. Keep package versions pinned to `package-lock.json`.

```bash
npm ci
```

Create a **local-only** `.dev.vars` file. Generate a unique access key with a password manager or `openssl rand -hex 32`, then put it in this ignored file:

```dotenv
CMS_ADMIN_KEY=<your-generated-64-character-hex-key>
```

Never commit the key or paste it into an issue, PR, chat message or README. The dashboard rejects keys shorter than 32 characters; use the recommended random 64-character value, not a memorable password. Keep it in your password manager.

Generate the local Worker configuration and initialise the **CMS** schema:

```bash
npm run build
npx wrangler d1 execute CMS_DB --local --config dist/server/wrangler.json --file db/migrations/portfolio-cms.sql
npm run dev
```

Use the printed local URL. The session cookie is Secure; localhost is treated as a secure context by modern browsers. For remote/LAN development, serve HTTPS instead of weakening cookie settings. Local Wrangler state stays in the ignored `.wrangler/` directory. The zero UUIDs in the development configuration are placeholders, **not deployment database IDs**.

The existing SkyETA database schema is in `db/schema.ts` and its original migration directory. The CMS SQL must only be applied to `CMS_DB`, never to a live SkyETA database. The homepage requires the CMS tables when `CMS_DB` is bound. A missing migration produces a storage error; it never overwrites existing content with defaults.

## Everyday editing — no terminal required

1. Open `/admin` and enter your admin access key.
2. Choose **Profile & contact**, **Projects**, **Circuit studies**, **Experience**, **Technical skills**, or **Search & sharing**.
3. Edit fields, add/reorder items and upload images or a CV.
4. Choose **Save draft**. The public site remains unchanged.
5. Use **Preview**, or the live design preview while editing.
6. Choose **Publish changes** and confirm. Refresh the public site to see the published version.

The first visit displays the initial content from source. Save it once to initialise the draft record. Saving also checks URLs, required fields, unique project slugs, content bounds and design values. If another session changes content, the editor rejects your stale save instead of silently overwriting newer edits. Export unsaved work before reloading after a conflict.

### Redesigning without code

Open **Design & structure**:

- Start with Sage & graphite, Navy & ivory, Warm editorial, or Midnight.
- Adjust page, text, card, border, accent and button-text colours.
- Choose modern sans serif, editorial serif or technical monospace typography.
- Adjust content width, section spacing and corner rounding.
- Choose split, portrait-left, stacked or text-only introductions.
- Switch project rows to a two-column card layout.
- Move sections up/down, hide/show them, change labels/headings, and add custom sections.
- Use the 390px and 1100px live preview before publishing.

The main introduction remains visible to maintain a primary heading. Text contrast is validated before publishing. Unsupported or incomplete changes show the last valid design in the preview with an explanation. Hidden sections keep their data. Standard anchor addresses remain stable; custom section addresses must be unique.

This is an actual viewport preview, not a claimed completed browser QA test. The design controls are intentionally bounded to prevent arbitrary scripts or broken CSS from being published.

### Project pages and evidence

Projects and circuit studies share an editable case-study model: title, summary, status, image, tools, evidence link, source link, application link and an ordered list of text/image sections. Upload evidence images in the section image fields. Keep published slugs stable; changing a slug changes its URL and does not create an automatic redirect.

Existing diagrams, evaluation CSVs and original case studies remain in the repository and under `/projects/*`. Never change design targets into measured performance claims. Adding a new project updates the generated sitemap after publishing.

### Media

Uploads accept PNG, JPEG, WebP and PDF, with MIME/signature checks and a 1 MB (1,048,576 byte) per-file limit by default. Database uploads have a 100 MiB aggregate raw-file cap enforced atomically. R2 is not required for this mode. If `PORTFOLIO_R2_BUCKET` is configured, new uploads use that bucket with an 8 MiB limit; existing database file URLs continue working. The bundled portrait is not subject to the dashboard upload limit. Use a meaningful image description. Files get immutable, random URLs. Uploaded files are public to anyone with their URL, including before a draft is published; do not upload private documents. Deleting a content item does not delete its files, so older versions keep working. There is no destructive media-delete button in this release.

### Backups and recovery

**Backups & history** can export the current editor content as JSON, import a JSON backup into the draft, or restore a published version into a draft. Restoring does not publish automatically. Export before large changes. JSON backups contain file URLs, not the media files themselves: separately back up the D1 database (which includes database-backed uploads) and any optional R2 bucket before migration or decommissioning.

Sessions expire after eight hours. Sign-out clears the browser cookie. Rotate `CMS_ADMIN_KEY` in the Worker secret store to invalidate all outstanding sessions. Sign-in is rate limited per Cloudflare client address to ten attempts per fifteen-minute window. This is a single-owner dashboard; multi-user roles, individual session revocation and audit attribution are not implemented.

## Release checklist — do not skip

The release is deliberately separate from the existing `peters-elijah-portfolio` Worker. Do not change the live domain or delete the original site just to test this replacement.

1. Review the design and test results. Complete actual desktop and mobile browser QA.
2. Provision a new D1 content database in the chosen Cloudflare account. No R2 subscription is required. For larger files later, optionally create a dedicated R2 bucket and set `PORTFOLIO_R2_BUCKET` to its name before rebuilding/deploying.
3. Provision a separate SkyETA database and apply its reviewed schema. Do not silently connect to the current production database or copy bookings/personal data.
4. Set build variables `PORTFOLIO_CMS_D1_ID`, `PORTFOLIO_SKYETA_D1_ID`, and `NEXT_PUBLIC_SITE_URL` to the verified resources and intended origin.
5. Keep `PORTFOLIO_PUBLIC=false` while reviewing. Use a private/staging access policy if confidentiality is required: `noindex` is not access control.
6. Build, then apply `db/migrations/portfolio-cms.sql` remotely to **CMS_DB** using the generated config. Take a backup before future schema changes.
7. Set the **runtime secret** `CMS_ADMIN_KEY` on the new Worker. Keep provider/payment/contact secrets server-side and configure only the ones actually used. Follow the existing SkyETA provider documentation; the CMS does not configure providers.
8. Deploy the replacement to its own Worker URL. `npm run deploy` guards against missing resource IDs; it never performs migrations or changes DNS for you.
9. Verify login, draft save, preview, image/PDF upload, publish, logout, version restore, contact configuration and SkyETA behaviour on the hosted runtime.
10. Only after approval, connect the intended domain using its verified authoritative DNS provider. Preserve verification records and a rollback path. A new codebase does not itself fix DNS.
11. Set `PORTFOLIO_PUBLIC=true` for the approved public launch; verify metadata and crawling rules. Preserve/redirect old project URLs appropriately.
12. Confirm the custom domain serves the new build before retiring the old deployment.

No Cloudflare resources, DNS records or production deployments are created by `npm run build`. The deploy script refuses to run without the replacement resource configuration. Do not bypass this guard by deploying a previously built bundle with stale settings.

The displayed email is content-editable, including the mailto fallback. Server-side contact delivery recipients/provider credentials remain deployment settings; changing the visible email alone does not change those secrets. Keep them consistent.

## Validation

```bash
npm run lint
npm run typecheck
npm test
# npm test runs the production build before the automated test suite
git diff --check
```

Additional commands:

```bash
npm run test:unit
node scripts/export-design-preview.mjs
```

The latter writes `docs/portfolio-design-preview.html`, a self-contained static design review made from the actual homepage component. It has no admin backend and cannot submit contact messages; it is clearly labelled as a design preview.

CMS tests exercise authentication, expiry/tamper rejection, origin checks, sign-in limits, upload validation, draft isolation, publish/version restore and stale-write conflicts against SQLite. Existing SkyETA/provider/model tests remain. Source assertions tied to the previous homepage were updated to check the new CMS-rendered portfolio. Automated checks do not substitute for real browser testing or live provider verification.

The original project documentation is preserved in [docs/LEGACY-README.md](docs/LEGACY-README.md) for technical reference. Its old deployment instructions do not govern this replacement.

## Important files

| Path | Purpose |
| --- | --- |
| `app/cms/content.ts` | Content model, seed data and validation |
| `app/cms/Portfolio.tsx` | Public homepage and ordered section renderer |
| `app/cms/portfolio.module.css` | Responsive design and theme-driven presentation |
| `app/cms/design.ts` | Safe design-token mapping |
| `app/cms/storage.ts` | D1 draft, publish and version operations |
| `app/cms/auth.ts` | Signed admin sessions and secure cookie handling |
| `app/cms/api.ts` | Authorised CMS API, upload limits and origin checks |
| `app/admin/` | Dashboard, visual designer and private previews |
| `app/work/[slug]/page.tsx` | Editable project/circuit case studies |
| `app/projects/` | Retained original technical evidence pages |
| `app/skyeta/`, `app/api/skyeta/` | Existing SkyETA experience and backend |
| `db/migrations/portfolio-cms.sql` | Separate CMS database schema |
| `vite.config.ts` | Replacement Worker and resource bindings |
| `scripts/deploy-next.mjs` | Guarded deployment entry point |
| `tests/cms.test.mjs` | CMS behaviour/security regressions |

## Search Console after launch

Verify the final domain property, submit its `/sitemap.xml`, inspect the homepage and the primary project URLs, and request indexing. Check that the homepage includes both names and that Person JSON-LD keeps the verified LinkedIn and GitHub URLs. If the domain changes, plan permanent redirects and the relevant Search Console migration steps before retiring the old domain. Do not submit the private review URL as the production sitemap.
