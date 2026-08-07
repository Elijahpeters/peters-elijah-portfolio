import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

export const metadata: Metadata = {
  title: "AuraPass engineering case study",
  description:
    "Architecture, validation method and simulation evidence for Peters Elijah's AuraPass access-control prototype.",
  alternates: {
    canonical: "/projects/aurapass",
  },
  openGraph: {
    url: "/projects/aurapass",
    title: "AuraPass engineering case study",
    description:
      "Architecture, validation method and simulation evidence for Peters Elijah's AuraPass access-control prototype.",
  },
};

export default function AuraPassCaseStudy() {
  return (
    <main className="case-study-page">
      <nav className="case-study-nav" aria-label="Case study navigation">
        <Link href="/#projects">← Back to portfolio</Link>
        <a href="https://github.com/Elijahpeters/AuraPass" target="_blank" rel="noreferrer">
          View source code ↗
        </a>
      </nav>

      <header className="case-study-hero">
        <p className="section-label">AuraPass / Engineering case study</p>
        <h1>Offline identity and exam-access decisions, engineered as one accountable path.</h1>
        <p>
          AuraPass is a final-year software-hardware co-simulation prototype. It
          combines guided face enrollment, local eligibility data, seat
          allocation and a Proteus-simulated gate without depending on cloud
          services during an examination.
        </p>
      </header>

      <section className="case-study-evidence" aria-labelledby="validation-title">
        <div>
          <p className="section-label">Controlled negative-face evaluation</p>
          <h2 id="validation-title">The published numbers and what they actually prove.</h2>
          <p>
            The evaluation used 500 non-enrolled LFW source faces. Each was
            tested in 10 variants covering the original image, blur, brighter
            and darker exposure, high and low contrast, left and right rotation,
            and left and right shadow.
          </p>
          <p>
            This is a false-grant stress test. It does not represent overall
            biometric accuracy, liveness performance or real campus deployment.
          </p>
          <a href="/assets/aurapass-negative-face-evaluation-summary.csv" download>
            Download validation summary ↓
          </a>
        </div>
        <dl>
          <div>
            <dt>5,000</dt>
            <dd>Total non-enrolled face attempts</dd>
          </div>
          <div>
            <dt>3,793</dt>
            <dd>Denied after comparison</dd>
          </div>
          <div>
            <dt>1,207</dt>
            <dd>Rejected by image-quality checks</dd>
          </div>
          <div>
            <dt>0</dt>
            <dd>False grants in this controlled set</dd>
          </div>
        </dl>
      </section>

      <section className="case-study-split" aria-labelledby="architecture-title">
        <div>
          <p className="section-label">System architecture</p>
          <h2 id="architecture-title">A face match is necessary, but never sufficient.</h2>
          <p>
            AuraPass verifies identity, course eligibility, repeat entry,
            capacity and seat availability before it records the decision and
            sends the gate command.
          </p>
          <ol>
            <li><span>01</span> Parse the course form and store guided face samples.</li>
            <li><span>02</span> Verify identity, eligibility, repeat entry and capacity.</li>
            <li><span>03</span> Reserve a seat and commit the decision.</li>
            <li><span>04</span> Drive the LCD, LEDs, buzzer and simulated servo gate.</li>
          </ol>
        </div>
        <figure className="case-study-figure case-study-flowchart">
          <Image
            src="/assets/aurapass-flowchart.png"
            alt="AuraPass process from enrollment to access decision"
            fill
            unoptimized
            sizes="(max-width: 900px) 92vw, 48vw"
            className="contain-image"
          />
        </figure>
      </section>

      <section className="case-study-hardware" aria-labelledby="hardware-title">
        <header>
          <p className="section-label">Hardware co-simulation</p>
          <h2 id="hardware-title">The decision reaches a visible, testable gate state.</h2>
          <p>
            A local bridge carries the committed access decision to the Proteus
            model, where the display, indicators, buzzer and servo response can
            be inspected in both grant and denial paths.
          </p>
        </header>
        <div className="case-study-gallery">
          <figure>
            <Image
              src="/assets/aurapass-proteus.png"
              alt="AuraPass Proteus hardware simulation"
              fill
              unoptimized
              sizes="(max-width: 900px) 92vw, 52vw"
              className="contain-image"
            />
            <figcaption>Proteus system model</figcaption>
          </figure>
          <figure>
            <Image
              src="/assets/aurapass-locked.png"
              alt="AuraPass simulated gate in denied state"
              fill
              unoptimized
              sizes="(max-width: 760px) 92vw, 24vw"
              className="project-image"
            />
            <figcaption>Denied state</figcaption>
          </figure>
          <figure>
            <Image
              src="/assets/aurapass-granted.png"
              alt="AuraPass simulated gate in access-granted state"
              fill
              unoptimized
              sizes="(max-width: 760px) 92vw, 24vw"
              className="project-image"
            />
            <figcaption>Granted state</figcaption>
          </figure>
        </div>
      </section>

      <aside className="case-study-limitations">
        <p className="section-label">Scope and limitations</p>
        <h2>Prototype evidence, stated without overclaiming.</h2>
        <p>
          AuraPass has been validated as an offline software and hardware-
          simulation prototype. Physical gate hardware, anti-spoof liveness,
          privacy governance and live university integration remain future work.
        </p>
      </aside>
    </main>
  );
}
