# Peters Elijah Temidayo — Portfolio

A responsive, single-page engineering portfolio presenting selected work in
electronics, circuit simulation, embedded systems, applied machine learning,
and technical AI evaluation.

## Selected work

- **AuraPass** — offline biometric examination-access prototype connecting
  identity, course eligibility, local records, and a simulated physical gate.
- **SkyETA** — worldwide provider-backed
  flight comparison with route-matched historical reliability evidence and a
  separate LightGBM research model trained on official U.S. Bureau of
  Transportation Statistics records. It is available both inside the portfolio
  and as a standalone product page at `/skyeta`.
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

## SkyETA source and model

The complete traveler-facing SkyETA product is maintained in this repository:
the interface lives in `app/skyeta`, its server endpoints in `app/api/skyeta`,
and shared fare/risk logic in `app/lib`. The separate
[SkyETA research repository](https://github.com/Elijahpeters/SkyETA) preserves
the reproducible U.S. BTS data-preparation and LightGBM work. Raw BTS downloads
and Python pickle artifacts are intentionally excluded from Git; the deployed
site receives only the browser-safe model tree, route presets and metadata.

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

## Real flight search and ticketing

SkyETA supports genuine provider-backed itinerary search, baggage details,
fare checking and delay-risk enrichment:

- Ignav supplies live fare snapshots and external airline/agency booking links
  for the current self-service integration. Its key stays server-side, searches
  use conservative durable quotas, and selected offers live only in short-lived
  D1 records. SkyETA never handles the travel payment or issues the ticket.
- Unverified price hints, self-transfer itineraries and unsafe external URLs are
  rejected instead of being presented as confirmed options.
- Worldwide results can request exact-flight, route-matched completed-flight
  history from AirLabs v10. SkyETA reports 15+, 30+ and 60+ minute late-arrival
  outlooks, typical late-arrival duration, sample window, uncertainty and
  confidence; fewer than five usable arrivals never produce a percentage.
- The worldwide historical outlook and the selected-U.S.-route LightGBM model
  remain visibly separate. Neither is presented as live status or a guarantee.
- The hardened Amadeus adapter remains in the codebase, but new Self-Service
  signup is no longer available and it is not the default provider.
- Duffel remains available for the separately gated airline-order workflow.
- Paystack Hosted Checkout keeps payment-card details away from this app.
- Passenger details are encrypted with authentication, bound to one
  booking attempt and deleted after a terminal result.
- Payment callbacks never issue tickets. A signed webhook is verified again
  against Paystack before an airline order can be submitted.
- Ambiguous airline responses enter manual review and are never blindly
  retried, preventing duplicate tickets.

Live ticket purchasing remains disabled unless the flight provider, payment
account, encryption key, approved currencies and canonical public origin are
all configured for production. Test inventory is never presented as a live
fare, and SkyETA never manufactures a booking reference.

The required server variables are documented in `.env.example`. Structured
booking state uses Cloudflare D1; credentials and passenger data must never be
committed.

## Optional contact-form delivery

The recruiter contact form always provides a prepared-email fallback. To send
directly from the site, configure `RESEND_API_KEY`, `CONTACT_TO_EMAIL`, and
`CONTACT_FROM_EMAIL` on the server. The sender must use a domain verified with
Resend; secrets stay server-side and must never be committed. If delivery is
not configured or cannot be confirmed, the interface does not claim that a
message was sent.

## Privacy-friendly analytics

The portfolio supports optional Umami Cloud analytics after deployment. Set
`NEXT_PUBLIC_UMAMI_WEBSITE_ID` and `NEXT_PUBLIC_UMAMI_DOMAIN` on the host to
enable page, referrer, country, device/browser and one-time `section-view`
events for `projects`, `circuits`, `about`, `experience` and `contact`.

Tracking is absent when those values are unset, restricted to the configured
public hostname, and respects the browser's Do Not Track setting. The
integration does not use `umami.identify()`, cookies, form contents, contact
details, session replay or heatmaps.

## Repository notes

- Environment files, raw datasets, local build products, and deployment state
  are ignored.
- The public CV and contact details are intentional portfolio content.
- No SkyETA API credentials or AuraPass biometric records belong in
  this repository.

© 2026 Peters Elijah Temidayo. All rights reserved.
