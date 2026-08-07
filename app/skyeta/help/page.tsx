import type { Metadata } from "next";
import Link from "next/link";

import styles from "../info.module.css";

export const metadata: Metadata = {
  title: "SkyETA Help",
  description:
    "Learn how SkyETA compares flights, explains worldwide historical reliability and hands bookings to external providers.",
  alternates: { canonical: "/skyeta/help" },
  openGraph: { url: "/skyeta/help" },
};

export default function SkyetaHelpPage() {
  return (
    <main className={styles.page}>
      <a className={styles.skipLink} href="#help-content">
        Skip to help
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

      <section className={styles.hero} aria-labelledby="help-title">
        <p className={styles.eyebrow}>SkyETA support</p>
        <h1 id="help-title">Help &amp; guidance</h1>
        <p className={styles.lead}>
          A clear guide to searching, comparing and understanding what happens
          when you continue to a flight provider.
        </p>
      </section>

      <nav className={styles.pageNav} aria-label="SkyETA information">
        <Link className={styles.current} aria-current="page" href="/skyeta/help">
          Help
        </Link>
        <Link href="/skyeta/privacy">Privacy</Link>
        <Link href="/skyeta/terms">Terms</Link>
      </nav>

      <article className={styles.content} id="help-content">
        <section className={styles.notice}>
          <p className={styles.sectionLabel}>The important part</p>
          <h2>SkyETA compares flights; it does not sell tickets.</h2>
          <p>
            SkyETA is a beta comparison product, not an airline or travel
            agency. The airline or booking site you choose handles payment,
            ticketing, changes, cancellations, refunds and booking support.
            SkyETA does not collect card data.
          </p>
        </section>

        <div className={styles.sectionGrid}>
          <section className={styles.section}>
            <p className={styles.sectionLabel}>01 / Search</p>
            <h2>How flight search works</h2>
            <ol>
              <li>Choose airports or cities, dates, cabin and passengers.</li>
              <li>
                SkyETA sends those search details to its connected flight
                provider, currently iGNav.
              </li>
              <li>
                Compare the current schedules and prices returned by the
                provider.
              </li>
              <li>
                Recheck the selected offer, then continue to the named external
                provider if it is still available.
              </li>
            </ol>
          </section>

          <section className={styles.section}>
            <p className={styles.sectionLabel}>02 / Price</p>
            <h2>Before you continue</h2>
            <p>
              Fares and seats can change between search and checkout. Review
              the final currency, baggage, fare conditions, passenger details
              and total on the provider&apos;s site before paying.
            </p>
            <p>
              The provider—not SkyETA—is responsible for issuing the ticket and
              helping with any later change, cancellation or refund. No
              affiliate payment is currently configured for SkyETA.
            </p>
          </section>

          <section className={styles.section}>
            <p className={styles.sectionLabel}>03 / Reliability</p>
            <h2>What the historical percentages mean</h2>
            <p>
              On worldwide fare results, you can check route-matched completed
              flights for 15+, 30+ and 60+ minute late-arrival history. SkyETA
              shows the number and date range of usable records, an uncertainty
              range and a confidence label. When too few records exist, it shows
              no percentage.
            </p>
            <p>
              That worldwide historical outlook is separate from the Delay Lab,
              which uses a trained model of U.S. domestic carrier, route and
              schedule patterns from U.S. Bureau of Transportation Statistics
              records for supported U.S. journeys.
            </p>
            <p>
              It is not live flight status, a guarantee or travel advice. Check
              the airline or airport for current operational information.
            </p>
          </section>

          <section className={styles.section}>
            <p className={styles.sectionLabel}>04 / Troubleshooting</p>
            <h2>If search does not return results</h2>
            <ul>
              <li>Confirm that the origin, destination and date are valid.</li>
              <li>Try a nearby date or fewer search constraints.</li>
              <li>
                If the provider is temporarily unavailable, wait briefly and
                use Retry.
              </li>
              <li>
                An empty result means no matching provider offer was returned;
                SkyETA does not invent a fare.
              </li>
            </ul>
          </section>

          <section className={styles.wideSection}>
            <p className={styles.sectionLabel}>Contact</p>
            <h2>Need help with SkyETA itself?</h2>
            <p>
              Email the operator at{" "}
              <a className={styles.inlineLink} href="mailto:peterselijah11@gmail.com">
                peterselijah11@gmail.com
              </a>
              . For a payment, ticket, refund or itinerary change, contact the
              airline or booking provider shown during the handoff.
            </p>
          </section>
        </div>

        <div className={styles.operator}>
          <p>
            Operated as a beta engineering project by{" "}
            <strong>Peters Elijah Temidayo</strong>, Nigeria.
          </p>
          <span className={styles.updated}>Updated 07 August 2026</span>
        </div>
      </article>
    </main>
  );
}
