"use client";

import { useId, useRef, useState } from "react";

import type { FlightProviderName } from "../../lib/flight-provider/config";
import type { FlightProviderMode } from "./flight-ui-types";
import DelayLabDisclosure from "./DelayLabDisclosure";
import FlightSearchExperience from "./FlightSearchExperience";
import styles from "../skyeta.module.css";

type ToolTab = "flights" | "delay";

export default function SkyetaToolTabs({
  initialProviderMode,
  initialProviderName,
}: {
  initialProviderMode: FlightProviderMode;
  initialProviderName: FlightProviderName;
}) {
  const [activeTab, setActiveTab] = useState<ToolTab>("flights");
  const flightTabRef = useRef<HTMLButtonElement>(null);
  const delayTabRef = useRef<HTMLButtonElement>(null);
  const id = useId();
  const flightTabId = `${id}-flight-tab`;
  const delayTabId = `${id}-delay-tab`;
  const flightPanelId = `${id}-flight-panel`;
  const delayPanelId = `${id}-delay-panel`;

  function handleTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    let nextTab: ToolTab | null = null;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp" || event.key === "Home") {
      nextTab = "flights";
    }
    if (event.key === "ArrowRight" || event.key === "ArrowDown" || event.key === "End") {
      nextTab = "delay";
    }
    if (!nextTab) return;
    event.preventDefault();
    setActiveTab(nextTab);
    (nextTab === "flights" ? flightTabRef : delayTabRef).current?.focus();
  }

  return (
    <section className={styles.toolWorkspace} aria-label="SkyETA tools">
      <div className={styles.toolTabs} role="tablist" aria-label="Choose a SkyETA tool">
        <button
          ref={flightTabRef}
          id={flightTabId}
          className={activeTab === "flights" ? styles.toolTabActive : undefined}
          type="button"
          role="tab"
          aria-selected={activeTab === "flights"}
          aria-controls={flightPanelId}
          tabIndex={activeTab === "flights" ? 0 : -1}
          onClick={() => setActiveTab("flights")}
          onKeyDown={handleTabKeyDown}
        >
          <span>01</span>
          Find flights worldwide
        </button>
        <button
          ref={delayTabRef}
          id={delayTabId}
          className={activeTab === "delay" ? styles.toolTabActive : undefined}
          type="button"
          role="tab"
          aria-selected={activeTab === "delay"}
          aria-controls={delayPanelId}
          tabIndex={activeTab === "delay" ? 0 : -1}
          onClick={() => setActiveTab("delay")}
          onKeyDown={handleTabKeyDown}
        >
          <span>02</span>
          U.S. delay research lab
        </button>
      </div>

      <div
        id={flightPanelId}
        role="tabpanel"
        aria-labelledby={flightTabId}
        hidden={activeTab !== "flights"}
      >
        <p className={styles.coverageNotice} role="note">
          <strong>Worldwide flight search.</strong> The separate trained delay model
          currently covers selected U.S. domestic routes. International results show
          recent observed reliability only when verified flight history is available;
          SkyETA never invents a delay percentage.
        </p>
        <FlightSearchExperience
          initialProviderMode={initialProviderMode}
          initialProviderName={initialProviderName}
        />
      </div>

      <div
        id={delayPanelId}
        role="tabpanel"
        aria-labelledby={delayTabId}
        hidden={activeTab !== "delay"}
      >
        {activeTab === "delay" ? <DelayLabDisclosure defaultOpen /> : null}
      </div>
    </section>
  );
}
