import type { Metadata } from "next";
import Link from "next/link";

import styles from "../info.module.css";

export const metadata: Metadata = {
  title: "SkyETA Terms",
  description:
    "Terms for using the SkyETA beta flight-comparison and historical reliability product.",
  alternates: { canonical: "/skyeta/terms" },
  openGraph: { url: "/skyeta/terms" },
};

export default function SkyetaTermsPage() {
  return (
    <main className={styles.page}>
      <a className={styles.skipLink} href="#terms-content">
        Skip to terms
      </a>

      <header className={styles.header}>
        <Link className={styles.brand} href="/skyeta">
          <span className={styles.brandMark} aria-hidden="true">
            SE
          </span>
          SkyETA
        </Link>
        <Link className={styles.backLink} href="/skyeta">
          <span aria-hidden="true">&larr;</span>
          <span>Back to flight search</span>
        </Link>
      </header>

      <section className={styles.hero} aria-labelledby="terms-title">
        <p className={styles.eyebrow}>SkyETA terms</p>
        <h1 id="terms-title">Terms of use</h1>
        <p className={styles.lead}>
          The roles, limits and responsibilities that apply when using this
          beta flight-comparison product.
        </p>
      </section>

      <nav className={styles.pageNav} aria-label="SkyETA information">
        <Link href="/skyeta/help">Help</Link>
        <Link href="/skyeta/privacy">Privacy</Link>
        <Link className={styles.current} aria-current="page" href="/skyeta/terms">
          Terms
        </Link>
      </nav>

      <article className={styles.content} id="terms-content">
        <section className={styles.notice}>
          <p className={styles.sectionLabel}>Product status</p>
          <h2>SkyETA is a beta comparison service, not a travel agency.</h2>
          <p>
            SkyETA helps users compare provider-supplied flight information and
            understand supported delay-risk estimates. It does not sell or issue
            tickets, accept payment, or enter into the booking contract between
            a traveler and an external provider.
          </p>
        </section>

        <div className={styles.sectionGrid}>
          <section className={styles.section}>
            <p className={styles.sectionLabel}>01 / Flight results</p>
            <h2>Availability and prices can change</h2>
            <p>
              Schedules, seats, baggage information, conditions and prices come
              from a connected provider and may change or contain omissions.
              Reconfirm the final itinerary, passengers, currency, total,
              baggage and fare rules on the provider&apos;s site before paying.
            </p>
            <p>
              A search result is not a reservation, price guarantee or promise
              that an airline will carry you.
            </p>
          </section>

          <section className={styles.section}>
            <p className={styles.sectionLabel}>02 / Booking handoff</p>
            <h2>The external provider handles the booking</h2>
            <p>
              When you follow a booking link, the named airline or booking
              provider—not SkyETA—handles payment, ticketing, schedule changes,
              cancellations, refunds and customer support. SkyETA does not
              collect card data.
            </p>
            <p>
              No affiliate payment or commission is currently configured for
              SkyETA.
            </p>
          </section>

          <section className={styles.section}>
            <p className={styles.sectionLabel}>03 / Delay analysis</p>
            <h2>Historical outlook, not live status</h2>
            <p>
              Worldwide fare results may include route-matched completed-flight
              history supplied by AirLabs. Sample size and coverage vary by flight;
              SkyETA shows no percentage when the available record set is too small.
            </p>
            <p>
              Separately, SkyETA&apos;s Delay Lab uses a trained model of historical
              U.S. domestic carrier, route and schedule patterns from U.S. Bureau
              of Transportation Statistics records. Results apply only where the
              product states that coverage exists.
            </p>
            <p>
              A delay percentage is an estimate, not live flight status, a
              guarantee or travel advice. Always verify current information with
              the airline or airport.
            </p>
          </section>

          <section className={styles.section}>
            <p className={styles.sectionLabel}>04 / Acceptable use</p>
            <h2>Use SkyETA responsibly</h2>
            <ul>
              <li>Use the service only for lawful travel research.</li>
              <li>Do not automate, overload or attempt to bypass usage limits.</li>
              <li>
                Do not interfere with the service, its provider connections or
                another person&apos;s use.
              </li>
              <li>
                You are responsible for checking visas, passports, entry rules
                and all details before travel.
              </li>
            </ul>
          </section>

          <section className={styles.section}>
            <p className={styles.sectionLabel}>05 / Beta availability</p>
            <h2>The service may change</h2>
            <p>
              SkyETA may add, remove or revise features, providers and coverage.
              Access may be interrupted by maintenance, network conditions,
              provider limits or technical faults. The service is provided on a
              reasonable-effort basis during beta.
            </p>
          </section>

          <section className={styles.section}>
            <p className={styles.sectionLabel}>06 / Responsibility</p>
            <h2>Verify before relying on a result</h2>
            <p>
              To the extent permitted by applicable law, the operator is not
              responsible for losses caused by a provider&apos;s price change,
              cancellation, inaccurate external information or a decision made
              without independent verification. Mandatory consumer rights are
              not excluded.
            </p>
          </section>

          <section className={styles.wideSection}>
            <p className={styles.sectionLabel}>Operator and contact</p>
            <h2>Peters Elijah Temidayo, Nigeria</h2>
            <p>
              Questions about these terms or SkyETA itself can be sent to{" "}
              <a className={styles.inlineLink} href="mailto:peterselijah11@gmail.com">
                peterselijah11@gmail.com
              </a>
              . Questions about a ticket, payment, change or refund must be sent
              to the external provider that handled the booking.
            </p>
          </section>
        </div>

        <div className={styles.operator}>
          <p>
            These terms apply to the <strong>SkyETA beta product</strong> operated
            by Peters Elijah Temidayo in Nigeria.
          </p>
          <span className={styles.updated}>Effective 07 August 2026</span>
        </div>
      </article>
    </main>
  );
}
