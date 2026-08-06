import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import DeferredSkyetaDemo from "../components/DeferredSkyetaDemo";
import { configuredFlightProviderEnvironment } from "../lib/flight-provider/config";
import FlightSearchExperience from "./components/FlightSearchExperience";
import styles from "./skyeta.module.css";

export const metadata: Metadata = {
  title: "SkyETA",
  description:
    "Check a flight's estimated chance of arriving at least 15 minutes late with SkyETA.",
};

export const dynamic = "force-dynamic";

export default function SkyetaPage() {
  const providerMode = configuredFlightProviderEnvironment() ?? "unconfigured";

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
        <p className={styles.eyebrow}>Smart flight delay outlook</p>
        <h1 id="skyeta-title">SkyETA</h1>
        <p className={styles.subtitle}>
          SkyETA combines two tools: provider-backed live-flight comparison and a
          historical late-arrival estimator for supported U.S. domestic routes.
        </p>

        <dl className={styles.systemSummary}>
          <div>
            <dt>Engine</dt>
            <dd>SkyETA</dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>U.S. BTS records</dd>
          </div>
          <div>
            <dt>Delay means</dt>
            <dd>15+ minutes late</dd>
          </div>
          <div>
            <dt>Current flights</dt>
            <dd>AirLabs</dd>
          </div>
        </dl>
      </section>

      <section className={styles.toolGuide} aria-label="How SkyETA works">
        <h2 className={styles.toolGuideHeading}>SkyETA has two tools.</h2>
        <article>
          <span>01 / Live fares</span>
          <h3>Search live flights and fares</h3>
          <p>
            Enter a route, date and passengers. SkyETA retrieves current itinerary
            and fare snapshots, then lets you recheck an option before opening the
            airline or booking partner.
          </p>
        </article>
        <article>
          <span>02 / Supported U.S. routes</span>
          <h3>Check the chance of arriving late</h3>
          <p>
            The separate estimator uses historical U.S. flight patterns to estimate
            the chance of arriving at least 15 minutes late. It is not live flight
            status or a guarantee.
          </p>
        </article>
        <p className={styles.toolGuideNote}>
          AirLabs current departures appear separately after an estimate and do not
          change the prediction.
        </p>
      </section>

      <FlightSearchExperience initialProviderMode={providerMode} />

      <section
        className={styles.demoShell}
        id="skyeta-demo"
        aria-label="Interactive SkyETA flight-delay estimator"
      >
        <DeferredSkyetaDemo headingLevel="h2" />
      </section>

      <footer className={styles.footer}>
        <p>
          SkyETA gives a probability estimate from historical flight patterns.
          Current AirLabs information is shown separately and does not change
          that estimate.
        </p>
        <Link href="/">Peters Elijah Temidayo / Portfolio</Link>
      </footer>
    </main>
  );
}
