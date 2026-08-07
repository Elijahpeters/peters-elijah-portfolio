import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import {
  configuredFlightProviderEnvironment,
  selectedFlightProvider,
} from "../lib/flight-provider/config";
import SkyetaToolTabs from "./components/SkyetaToolTabs";
import styles from "./skyeta.module.css";

export const metadata: Metadata = {
  title: "SkyETA — Compare flights and reliability evidence",
  description:
    "Compare current flights worldwide. Review historical reliability where records exist, with a separate trained model for selected U.S. domestic routes.",
};

export const dynamic = "force-dynamic";

export default function SkyetaPage() {
  const providerMode = configuredFlightProviderEnvironment() ?? "unconfigured";
  const providerName = selectedFlightProvider();

  return (
    <main className={styles.page}>
      <a className={styles.skipLink} href="#flight-search-title">
        Skip to SkyETA
      </a>

      <div className={styles.ambient} aria-hidden="true">
        <span className={`${styles.lightField} ${styles.lightFieldOne}`} />
        <span className={`${styles.lightField} ${styles.lightFieldTwo}`} />
        <span className={styles.ambientGrid} />

        <div className={styles.radar}>
          <span className={styles.radarSweep} />
          <span className={`${styles.radarBlip} ${styles.radarBlipOne}`} />
          <span className={`${styles.radarBlip} ${styles.radarBlipTwo}`} />
          <span className={`${styles.radarBlip} ${styles.radarBlipThree}`} />
        </div>

        <div className={styles.flightPath}>
          <svg viewBox="0 0 1000 320" preserveAspectRatio="none">
            <path
              className={styles.routeTrace}
              d="M20 230C235 32 735 42 980 220"
            />
            <path
              className={styles.routeFlow}
              d="M20 230C235 32 735 42 980 220"
            />
            <circle className={styles.routeNode} cx="20" cy="230" r="5" />
            <circle
              className={`${styles.routeNode} ${styles.routeNodeTwo}`}
              cx="365"
              cy="88"
              r="5"
            />
            <circle
              className={`${styles.routeNode} ${styles.routeNodeThree}`}
              cx="700"
              cy="80"
              r="5"
            />
            <circle
              className={`${styles.routeNode} ${styles.routeNodeFour}`}
              cx="980"
              cy="220"
              r="5"
            />
          </svg>

          <span className={styles.flightTraveler}>
            <svg viewBox="0 0 32 32">
              <path d="M29.2 14.1 18.8 9.4 18 2.8c-.1-.8-.7-1.4-1.5-1.4s-1.4.6-1.5 1.4l-.8 6.6-10.4 4.7c-.7.3-1.1 1-1 1.8.1.7.7 1.3 1.5 1.4l10.1.8.6 7.2-3.4 2.2c-.5.3-.7.9-.5 1.5.2.5.7.9 1.3.8l4.1-.8 4.1.8c.6.1 1.1-.3 1.3-.8.2-.6 0-1.2-.5-1.5L18 25.3l.6-7.2 10.1-.8c.8-.1 1.4-.7 1.5-1.4.1-.8-.3-1.5-1-1.8Z" />
            </svg>
          </span>
        </div>
      </div>

      <header className={styles.header}>
        <Link className={styles.backLink} href="/">
          <span aria-hidden="true">&larr;</span> Back to portfolio
        </Link>

        <div className={styles.productMark} aria-label="SkyETA">
          <Image
            src="/assets/skyeta-logo-clean.png"
            alt=""
            width={34}
            height={34}
            unoptimized
          />
          <span>SkyETA</span>
        </div>

        <span className={styles.systemState}>
          <i aria-hidden="true" /> Interactive system
        </span>
      </header>

      <section className={styles.intro} aria-labelledby="skyeta-title">
        <p className={styles.eyebrow}>Flight search + reliability evidence</p>
        <h1 id="skyeta-title">SkyETA</h1>
        <p className={styles.subtitle}>
          Compare current flights worldwide, then understand the reliability
          evidence available for each journey.
        </p>
      </section>

      <SkyetaToolTabs
        initialProviderMode={providerMode}
        initialProviderName={providerName}
      />

      <section className={styles.toolGuide} aria-label="How SkyETA works">
        <h2 className={styles.toolGuideHeading}>
          One search, three layers of information.
        </h2>
        <article>
          <span>01 / Search</span>
          <h3>Choose your journey</h3>
          <p>
            Enter the route, date, cabin and passengers for a domestic or
            international trip.
          </p>
        </article>
        <article>
          <span>02 / Compare</span>
          <h3>Review real journey facts</h3>
          <p>
            Compare provider fares, schedules, stops, baggage information and
            approximate currency equivalents.
          </p>
        </article>
        <article>
          <span>03 / Understand</span>
          <h3>See the evidence available</h3>
          <p>
            Get a verified late-arrival outlook where coverage exists, or a clear
            journey summary without an invented percentage.
          </p>
        </article>
        <p className={styles.toolGuideNote}>
          Worldwide search and the U.S. trained model are separate. A flight without
          enough verified history receives no invented score.
        </p>
      </section>

      <footer className={styles.footer}>
        <div>
          <p>
            SkyETA is a beta comparison product. It does not collect payment or
            issue tickets.
          </p>
          <nav aria-label="SkyETA information">
            <Link href="/skyeta/help">Help</Link>
            <Link href="/skyeta/privacy">Privacy</Link>
            <Link href="/skyeta/terms">Terms</Link>
          </nav>
        </div>
        <Link href="/">Peters Elijah Temidayo / Portfolio</Link>
      </footer>
    </main>
  );
}
