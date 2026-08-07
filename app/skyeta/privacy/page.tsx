import type { Metadata } from "next";
import Link from "next/link";

import styles from "../info.module.css";

export const metadata: Metadata = {
  title: "SkyETA Privacy",
  description:
    "How SkyETA handles flight-search details, short-lived offer data, aggregate analytics and external provider links.",
  alternates: { canonical: "/skyeta/privacy" },
  openGraph: { url: "/skyeta/privacy" },
};

export default function SkyetaPrivacyPage() {
  return (
    <main className={styles.page}>
      <a className={styles.skipLink} href="#privacy-content">
        Skip to privacy information
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

      <section className={styles.hero} aria-labelledby="privacy-title">
        <p className={styles.eyebrow}>SkyETA privacy</p>
        <h1 id="privacy-title">Privacy notice</h1>
        <p className={styles.lead}>
          What SkyETA processes during a search, what leaves the site and what
          it deliberately does not collect.
        </p>
      </section>

      <nav className={styles.pageNav} aria-label="SkyETA information">
        <Link href="/skyeta/help">Help</Link>
        <Link
          className={styles.current}
          aria-current="page"
          href="/skyeta/privacy"
        >
          Privacy
        </Link>
        <Link href="/skyeta/terms">Terms</Link>
      </nav>

      <article className={styles.content} id="privacy-content">
        <section className={styles.notice}>
          <p className={styles.sectionLabel}>Plain-language summary</p>
          <h2>No account or card details are required to search.</h2>
          <p>
            SkyETA uses journey details to request flight offers from a
            connected provider. It does not collect card data. If you continue
            to book, you leave SkyETA and deal directly with the external
            provider under that provider&apos;s privacy terms.
          </p>
        </section>

        <div className={styles.sectionGrid}>
          <section className={styles.section}>
            <p className={styles.sectionLabel}>01 / Search data</p>
            <h2>Information used for a flight search</h2>
            <p>
              SkyETA processes the origin, destination, travel dates, passenger
              counts, cabin and search preferences you choose. Its server sends
              the details needed for the request to the connected flight
              provider, currently iGNav, so that provider can return matching
              offers.
            </p>
            <p>
              Do not enter card, passport or other sensitive information into
              the search fields.
            </p>
            <p>
              If you open a worldwide historical outlook, SkyETA sends only the
              flight number, origin and destination needed for a route-matched
              completed-flight lookup to AirLabs. It does not send passenger names
              or contact details for that lookup.
            </p>
          </section>

          <section className={styles.section}>
            <p className={styles.sectionLabel}>02 / Short storage</p>
            <h2>Offers are held briefly</h2>
            <p>
              Provider offer details are kept in a short-lived server cache so
              SkyETA can display and recheck the result you selected. With the
              current iGNav integration, that offer cache is available for
              approximately ten minutes; a price recheck can extend it, but never
              beyond thirty minutes from the original search.
            </p>
            <p>
              SkyETA does not create a traveler profile from these searches.
            </p>
          </section>

          <section className={styles.section}>
            <p className={styles.sectionLabel}>03 / Analytics</p>
            <h2>Aggregate site measurement</h2>
            <p>
              SkyETA uses Umami for aggregate information such as page visits,
              broad location, device and referrer summaries, plus simple
              section-view events. Analytics is configured to respect a
              browser&apos;s Do Not Track setting.
            </p>
            <p>
              Flight-search contents and card data are not sent as SkyETA
              analytics events.
            </p>
          </section>

          <section className={styles.section}>
            <p className={styles.sectionLabel}>04 / Abuse prevention</p>
            <h2>Rate limits use short-lived pseudonymous records</h2>
            <p>
              Cloudflare supplies the visitor IP address to the server. SkyETA
              converts it to a one-way SHA-256 quota key and writes only that hash,
              a request count and expiry time to Cloudflare D1; the raw IP address
              is not written to the quota table.
            </p>
            <p>
              Visitor-specific flight-search and history limits normally expire
              after ten minutes and are deleted after expiry during periodic
              cleanup. Global provider-protection counters can last up to 24 hours
              and do not identify an individual visitor.
            </p>
          </section>

          <section className={styles.section}>
            <p className={styles.sectionLabel}>05 / External providers</p>
            <h2>What happens when you leave SkyETA</h2>
            <p>
              Booking links open an external airline or booking-provider site.
              That provider may collect identity, passport, contact and payment
              information under its own privacy notice. SkyETA does not control
              the provider&apos;s forms, storage or support process.
            </p>
            <p>
              Review the destination address and the provider&apos;s privacy notice
              before submitting information.
            </p>
          </section>

          <section className={styles.wideSection}>
            <p className={styles.sectionLabel}>Questions and corrections</p>
            <h2>Contact the operator</h2>
            <p>
              SkyETA is operated by Peters Elijah Temidayo in Nigeria. For a
              privacy question or correction request, email{" "}
              <a className={styles.inlineLink} href="mailto:peterselijah11@gmail.com">
                peterselijah11@gmail.com
              </a>
              . Requests about data entered on an external booking site must be
              directed to that provider.
            </p>
          </section>
        </div>

        <div className={styles.operator}>
          <p>
            This notice covers the <strong>SkyETA beta product</strong> operated
            by Peters Elijah Temidayo, Nigeria.
          </p>
          <span className={styles.updated}>Effective 07 August 2026</span>
        </div>
      </article>
    </main>
  );
}
