"use client";

import { useState } from "react";

import DeferredSkyetaDemo from "../../components/DeferredSkyetaDemo";
import styles from "../skyeta.module.css";

export default function DelayLabDisclosure({
  defaultOpen = false,
}: {
  defaultOpen?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <section
      className={`${styles.delayLab} ${isOpen ? styles.delayLabOpen : ""}`}
      id="skyeta-delay-lab"
      aria-labelledby="delay-lab-title"
    >
      <div className={styles.delayLabIntro}>
        <div className={styles.delayLabCopy}>
          <span>SkyETA Delay Lab</span>
          <h2 id="delay-lab-title">Explore the verified historical model.</h2>
          <p>
            This research feature estimates late-arrival probability for routes
            covered by SkyETA&apos;s U.S. historical dataset. It stays separate from
            worldwide fare search and current route information.
          </p>
        </div>
        <button
          className={styles.delayLabButton}
          type="button"
          aria-expanded={isOpen}
          aria-controls="delay-lab-content"
          onClick={() => setIsOpen((current) => !current)}
        >
          {isOpen ? "Close Delay Lab" : "Open Delay Lab"}
          <span aria-hidden="true">{isOpen ? "−" : "+"}</span>
        </button>
      </div>

      {isOpen ? (
        <div className={styles.demoShell} id="delay-lab-content">
          <DeferredSkyetaDemo headingLevel="h3" />
        </div>
      ) : null}
    </section>
  );
}
