import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import styles from "../engineering.module.css";

export const metadata: Metadata = {
  title: "Incubator carrier PCB | Peters Elijah",
  description: "A KiCad two-layer carrier-board case study: schematic organisation, component placement, routing, design checks and the boundary between CAD verification and hardware testing.",
  alternates: { canonical: "/projects/incubator-carrier" },
  openGraph: {
    title: "Incubator carrier PCB | Peters Elijah",
    description: "Schematic, layout and recorded CAD checks for a two-layer incubator interface carrier. Not yet bench-tested.",
    url: "/projects/incubator-carrier",
  },
};

export default function IncubatorCarrierCaseStudy() {
  return (
    <main className={styles.page}>
      <nav className={styles.nav} aria-label="Case study navigation">
        <Link href="/#circuits">← Back to circuits &amp; PCB</Link>
        <Link href="/#contact">Discuss my work →</Link>
      </nav>
      <header className={styles.hero}>
        <p className={styles.eyebrow}>Hardware case study / KiCad 10 / Rev C</p>
        <h1>An organised interface between controller, sensors and relays.</h1>
        <p>This carrier board brings the low-voltage connections for an Arduino
          Mega-based incubator controller onto a compact PCB. My PCB work focuses
          on component placement, routing, connector access and layout verification.</p>
        <span className={styles.status}>CAD design checked · not assembled or bench-tested</span>
      </header>
      <dl className={styles.overview}>
        <div><dt>Board outline</dt><dd>96 × 76 mm</dd></div>
        <div><dt>Construction</dt><dd>2 copper layers</dd></div>
        <div><dt>Layout scope</dt><dd>30 footprints · 4 mounting holes</dd></div>
        <div><dt>Recorded review</dt><dd>12 September 2026</dd></div>
      </dl>
      <figure className={styles.figure}>
        <a href="/assets/incubator-pcb-angled.png" target="_blank" rel="noreferrer" aria-label="Open the incubator PCB 3D render at full size in a new tab">
          <Image src="/assets/incubator-pcb-angled.png" alt="Angled KiCad 3D render showing the incubator carrier board and its connectors" width={4200} height={2367} priority unoptimized />
        </a>
        <figcaption>A KiCad 3D render, not an assembled prototype. Select any drawing to inspect it at full size.</figcaption>
      </figure>
      <section className={styles.section} aria-labelledby="brief-title">
        <p className={styles.eyebrow}>The design brief</p>
        <h2 id="brief-title">Make the interface clear, accessible and checkable.</h2>
        <p>The board groups three temperature-sensor connections, four relay-control
          signals, status LEDs and an acknowledgement button. A keyed ribbon
          connector provides the controller interface; separate terminals handle
          the relay-coil supply. This is an interface carrier, not a complete
          incubator controller or a standalone safety system.</p>
      </section>
      <section className={styles.section} aria-labelledby="layout-title">
        <p className={styles.eyebrow}>PCB decisions</p>
        <h2 id="layout-title">Placement and routing with a reason behind them.</h2>
        <div className={styles.split}>
          <ul className={styles.decisions}>
            <li><h3>Connectors at the board edges</h3><p>Sensor terminals sit along the lower edge; coil-supply terminals sit on the right. Placement leaves room for wiring and keeps the four mounting holes accessible.</p></li>
            <li><h3>Different routes for different jobs</h3><p>Signal traces use a 0.30 mm width. The coil-positive route uses 1.50 mm and the main coil return uses 1.20 mm. These are design choices, not measured current-capacity guarantees.</p></li>
            <li><h3>A deliberate ground connection</h3><p>The logic and coil ground regions meet at the NT1 copper net tie. The actual relay module must be checked for additional internal ground connections before the complete system can be validated.</p></li>
            <li><h3>Mechanical checks alongside electrical checks</h3><p>The layout accounts for terminal-body setbacks, mounting-hole keepouts, courtyards and connector orientation. Physical fit still needs confirmation with the purchased parts.</p></li>
          </ul>
          <figure className={styles.figure}>
            <a href="/assets/incubator-pcb-layout.png" target="_blank" rel="noreferrer" aria-label="Open the routed PCB layout at full size in a new tab">
              <Image src="/assets/incubator-pcb-layout.png" alt="Routed PCB layer view showing front copper routes, back copper pours and four mounting holes" width={1600} height={2000} unoptimized />
            </a>
            <figcaption>Routed-board view from the Rev C design record. No claim of manufactured-board performance is implied.</figcaption>
          </figure>
        </div>
      </section>
      <section className={styles.section} aria-labelledby="schematic-title">
        <p className={styles.eyebrow}>Schematic organisation</p>
        <h2 id="schematic-title">Trace each interface before following the copper.</h2>
        <p>The schematic separates the controller header, three sensor interfaces,
          relay-control connections, coil-power path, indicators and acknowledgement
          button. This makes the relationship between the intended connections
          and the board easier to review.</p>
        <figure className={styles.figure}>
          <a href="/assets/incubator-schematic.png" target="_blank" rel="noreferrer" aria-label="Open the incubator carrier schematic at full size in a new tab">
            <Image src="/assets/incubator-schematic.png" alt="Rev C carrier schematic arranged into labelled controller, sensor, relay, power, indicator and button sections" width={9921} height={7016} unoptimized />
          </a>
          <figcaption>Rev C schematic export. Open the full-size drawing to read component values and connection labels.</figcaption>
        </figure>
      </section>
      <section className={styles.section} aria-labelledby="checks-title">
        <p className={styles.eyebrow}>Verification record</p>
        <h2 id="checks-title">What was checked—and what those checks mean.</h2>
        <p>These results come from the saved KiCad 10.0.3 reports dated
          12 September 2026. They are CAD checks, not physical test results.</p>
        <dl className={styles.checks}>
          <div><dt>Schematic electrical-rule check (ERC)</dt><dd>0 errors and 0 warnings reported under the saved check configuration.</dd></div>
          <div><dt>PCB design-rule check (DRC)</dt><dd>0 violations and 0 unconnected pads reported under the saved check configuration.</dd></div>
          <div><dt>Schematic-to-PCB agreement</dt><dd>The verification record reports 0 parity issues and 71 matching electrical pin assignments in a separate pin-map audit.</dd></div>
          <div><dt>Mechanical review</dt><dd>Board outline, mounting-hole clearances and terminal-body positions documented. A 3D view checks model placement, not actual part fit.</dd></div>
        </dl>
        <p className={styles.scopeNote}>The reports retain KiCad’s listed default ignored checks. A clean ERC/DRC result is not proof of functional performance, safe operation or certification.</p>
      </section>
      <aside className={styles.limitation} aria-labelledby="limits-title">
        <h2 id="limits-title">The next evidence must come from hardware.</h2>
        <p>No populated prototype has been tested, and firmware is not included
          in this design deliverable. Assembly, component fit, relay-interface
          currents, sensor faults, power-loss behaviour and thermal response
          remain to be verified.</p>
        <p>The carrier handles low-voltage interfaces only. It has no independent
          temperature-trip circuit and is not a sole safety device; the complete
          system requires separately designed protection and qualified review.</p>
      </aside>
      <Link className={styles.action} href="/#circuits">← Return to the engineering portfolio</Link>
    </main>
  );
}
