# Peters Elijah Temidayo — Portfolio

A responsive, single-page engineering portfolio presenting selected work in
electronics, circuit simulation, embedded systems, applied machine learning,
and technical AI evaluation.

## Selected work

- **AuraPass** — offline biometric examination-access prototype connecting
  identity, course eligibility, local records, and a simulated physical gate.
- **SkyETA** — interactive LightGBM flight-delay intelligence application
  trained from official U.S. Bureau of Transportation Statistics records. It
  is available both inside the portfolio and as a standalone product page at
  `/skyeta`.
- **Circuit laboratory** — documented analog, mixed-signal, and power-electronic
  simulations with concise engineering interpretation.

The page also includes Peters Elijah Temidayo's profile, experience, education,
contact details, LinkedIn and GitHub links, and a downloadable CV.

## Technology

- React 19, TypeScript, Vinext, and hand-authored responsive CSS
- Python, pandas, scikit-learn, and LightGBM for the SkyETA model pipeline
- A browser-safe LightGBM tree export for private, cost-free client-side
  predictions—no API key is shipped to visitors

## Local development

Node.js 22.13 or newer is required.

```bash
npm install
npm run dev
```

Open `http://127.0.0.1:3000/` for the portfolio or
`http://127.0.0.1:3000/skyeta` for the standalone SkyETA experience. The local
production launcher included with this workspace serves the same routes on
port `4177`.

Build and verify the site with:

```bash
npm run build
npm test
```

Run the verified production build locally with `npm start`. It listens on
`http://127.0.0.1:4177` by default; set `PORT` to override it.

## SkyETA model

The reproducible data and training workflow lives in [`skyeta-ml`](skyeta-ml).
Raw BTS downloads and Python pickle artifacts are intentionally excluded from
Git. The public site receives only the browser-safe tree dump, model card,
route presets, and held-out evaluation metrics.

## Optional live flight board

SkyETA can add real current route schedules and status from the
[AirLabs v9 Schedules API](https://airlabs.co/docs/schedules) without exposing
the provider key to the browser. Copy
`.env.example` to `.env.local`, add a free `AIRLABS_API_KEY`, then rebuild and
restart the site. Without a key, the interface reports that live lookup is not
configured and never substitutes invented flights.

AirLabs documents the live schedule window as the current service period up to
roughly ten hours ahead. These records are flight status data—not fares, seat
inventory, or booking availability.

## Optional contact-form delivery

The recruiter contact form always provides a prepared-email fallback. To send
directly from the site, configure `RESEND_API_KEY`, `CONTACT_TO_EMAIL`, and
`CONTACT_FROM_EMAIL` on the server. The sender must use a domain verified with
Resend; secrets stay server-side and must never be committed. If delivery is
not configured or cannot be confirmed, the interface does not claim that a
message was sent.

## Repository notes

- Environment files, raw datasets, local build products, and deployment state
  are ignored.
- The public CV and contact details are intentional portfolio content.
- No SkyETA API credentials or AuraPass biometric records belong in
  this repository.

© 2026 Peters Elijah Temidayo. All rights reserved.
