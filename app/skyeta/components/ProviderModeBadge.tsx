import type { FlightProviderMode } from "./flight-ui-types";
import styles from "../booking.module.css";

const modeCopy: Record<
  FlightProviderMode,
  { label: string; detail: string }
> = {
  live: {
    label: "Current prices",
    detail: "Current prices are supplied by the connected flight provider.",
  },
  test: {
    label: "Test data",
    detail: "Provider sandbox results are not real prices.",
  },
  unconfigured: {
    label: "Search not connected",
    detail: "A flight provider has not been connected yet.",
  },
};

export interface ProviderModeBadgeProps {
  mode: FlightProviderMode;
  compact?: boolean;
}

export default function ProviderModeBadge({
  mode,
  compact = false,
}: ProviderModeBadgeProps) {
  const copy = modeCopy[mode];

  return (
    <span
      className={`${styles.modeBadge} ${styles[`mode_${mode}`]} ${
        compact ? styles.modeBadgeCompact : ""
      }`}
      title={copy.detail}
      data-provider-mode={mode}
    >
      <span className={styles.modeDot} aria-hidden="true" />
      {copy.label}
    </span>
  );
}
