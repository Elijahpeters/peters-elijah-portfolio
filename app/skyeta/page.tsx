import type { Metadata } from "next";
import Link from "next/link";

import SkyetaDemo from "../components/SkyetaDemo";
import styles from "./skyeta.module.css";

export const metadata: Metadata = {
  title: "SkyETA",
  description:
    "Explore SkyETA's local flight-delay model and server-backed live route board.",
};

export default function SkyetaPage() {
  return (
    <main className={styles.page}>
      <a className={styles.skipLink} href="#skyeta-demo">
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
          <img src="/assets/skyeta-logo-clean.png" alt="" />
          <span>SkyETA</span>
        </div>

        <span className={styles.systemState}>
          <i aria-hidden="true" /> Interactive system
        </span>
      </header>

      <section className={styles.intro} aria-labelledby="skyeta-title">
        <p className={styles.eyebrow}>Flight intelligence / Local ML + live routes</p>
        <h1 id="skyeta-title">SkyETA</h1>
        <p className={styles.subtitle}>
          Explore flight-delay risk through historical carrier, airport, route
          and schedule patterns. The model estimate runs privately in your
          browser; the optional live route board uses current AirLabs data
          through the server.
        </p>

        <dl className={styles.systemSummary}>
          <div>
            <dt>Model</dt>
            <dd>LightGBM</dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>U.S. BTS records</dd>
          </div>
          <div>
            <dt>Estimate</dt>
            <dd>Local browser</dd>
          </div>
          <div>
            <dt>Live routes</dt>
            <dd>AirLabs via server</dd>
          </div>
        </dl>
      </section>

      <section
        className={styles.demoShell}
        id="skyeta-demo"
        aria-label="Interactive SkyETA flight-delay estimator"
      >
        <SkyetaDemo />
      </section>

      <footer className={styles.footer}>
        <p>
          Historical delay estimates run locally in your browser. The optional
          live route board uses current AirLabs data through the server; neither
          output is travel advice.
        </p>
        <Link href="/">Peters Elijah Temidayo / Portfolio</Link>
      </footer>
    </main>
  );
}
