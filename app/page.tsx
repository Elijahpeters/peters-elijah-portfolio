import Image from "next/image";
import ContactForm from "./components/ContactForm";
import ExperienceSection from "./components/ExperienceSection";
import HashAnchorRestorer from "./components/HashAnchorRestorer";
import SiteHeader from "./components/SiteHeader";
import styles from "./home.module.css";
import { circuitStudies } from "./lib/circuit-studies";

const capabilities = [
  {
    number: "01",
    title: "Circuit design & simulation",
    text: "LTspice, KiCad, Qucs-S, DesignSpark PCB, Proteus and MATLAB/Simulink.",
  },
  {
    number: "02",
    title: "AI & computer vision",
    text: "Python, OpenCV, MediaPipe, DeepFace, scikit-learn, Pandas and NumPy.",
  },
  {
    number: "03",
    title: "Embedded & engineering software",
    text: "Arduino, C++, SQL, HTML/CSS, Bash, Ansys SpaceClaim and Ansys Fluent.",
  },
];

export default function Home() {
  return (
    <div className={styles.home}>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>

      <SiteHeader />
      <HashAnchorRestorer />

      <main>
        <section className="hero" id="main-content">
        <div className="hero-copy">
          <p className="eyebrow">Electrical &amp; Electronics Engineer</p>
          <h1>
            Circuit design. PCB layout. <em>Intelligent systems.</em>
          </h1>
          <p className="hero-summary">
            I design electronic circuits, develop embedded systems, and apply
            machine learning to engineering problems. My work spans circuit
            simulation, PCB design, intelligent automation, and predictive software.
          </p>
          <p className="target-roles">
            Peters Elijah · Electronics, embedded systems &amp; applied AI
          </p>
          <div className="hero-actions">
            <a className="text-link" href="#projects">
              <span aria-hidden="true" /> Explore my work
            </a>
            <a
              className="text-link text-link-muted"
              href="/assets/Peters-Elijah-CV.pdf"
              download
            >
              Download CV <span aria-hidden="true">↓</span>
            </a>
          </div>
        </div>

        <figure className="hero-portrait">
          <div className="portrait-shell">
            <picture>
              <source
                media="(max-width: 760px)"
                srcSet="/assets/portrait-web-mobile.webp"
                type="image/webp"
              />
              <Image
                src="/assets/portrait-web.jpg"
                alt="Peters Elijah wearing a navy suit and tie"
                fill
                unoptimized
                priority
                sizes="(max-width: 760px) 92vw, 42vw"
                className="portrait-image"
              />
            </picture>
          </div>
          <figcaption>Peters Elijah / Ogun State, Nigeria</figcaption>
        </figure>

        <dl className="hero-facts" aria-label="Professional highlights">
          <div>
            <dt>Education</dt>
            <dd>B.Eng Electrical &amp; Electronics Engineering</dd>
          </div>
          <div>
            <dt>Focus</dt>
            <dd>Electronics &amp; applied AI</dd>
          </div>
          <div>
            <dt>Based in</dt>
            <dd>Ogun State, Nigeria</dd>
          </div>
        </dl>

        <div className="hero-footer" aria-hidden="true">
          <span>© 2026 / Portfolio</span>
          <span>Scroll to explore ↓</span>
        </div>
        </section>

      <section className="section" id="what-i-build" aria-labelledby="build-title">
        <header className="section-heading">
          <p className="section-label">01 / What I Build</p>
          <h2 id="build-title">Electronics, from circuit to software.</h2>
          <p className="section-intro">Three connected areas of engineering practice.</p>
        </header>
        <div className={styles.buildGrid}>
          <article><span>01 / CIRCUITS</span><h3>Circuits &amp; PCBs</h3><p>Analogue circuits, power-stage studies and two-layer PCB layouts, supported by simulation and design checks.</p><a href="#circuits">Explore circuit work →</a></article>
          <article><span>02 / CONTROL</span><h3>Embedded systems</h3><p>Sensor interfaces, control logic and hardware–software integration for automation and access-control prototypes.</p><a href="#aurapass">Explore AuraPass →</a></article>
          <article><span>03 / INTELLIGENCE</span><h3>Applied AI &amp; ML</h3><p>Computer vision, data analysis and predictive applications with explicit evaluation methods and limitations.</p><a href="#skyeta">Explore SkyETA →</a></article>
        </div>
      </section>

      <section className="section selected-work" id="projects">
        <header className="section-heading">
          <p className="section-label">02 / Featured Engineering Projects</p>
          <h2>Selected engineering work.</h2>
          <p className="section-intro">The problem, the implementation and the evidence. Full technical details are in each case study.</p>
        </header>
        <div className={styles.projectGrid}>
          <article className={styles.projectCard} id="aurapass">
            <figure className={styles.projectImage}>
              <Image src="/assets/aurapass-proteus.png" alt="AuraPass gate-control circuit in the Proteus simulator" width={1134} height={592} unoptimized sizes="(max-width: 1000px) 92vw, 30vw" />
              <figcaption>Proteus hardware simulation</figcaption>
            </figure>
            <div className={styles.projectBody}>
              <p className={styles.status}>Offline prototype · simulated gate</p>
              <h3>AuraPass</h3>
              <p>Biometric examination access combining computer vision, student eligibility, seat allocation and simulated gate control.</p>
              <p className={styles.stack}>Python / OpenCV / SQLite / Proteus</p>
              <div className={styles.projectLinks}>
                <a href="/projects/aurapass" aria-label="Read the AuraPass engineering case study">Read case study →</a>
                <a href="https://github.com/Elijahpeters/AuraPass" target="_blank" rel="noreferrer" aria-label="View AuraPass code on GitHub in a new tab">Source ↗</a>
              </div>
            </div>
          </article>
          <article className={styles.projectCard} id="skyeta">
            <div className={styles.skyetaPreview} aria-label="SkyETA flight intelligence overview">
              <span>FLIGHT INTELLIGENCE</span>
              <strong>SkyETA<span aria-hidden="true">↗</span></strong>
              <div><span>Fare search</span><span>Flight history</span><span>ML estimates</span></div>
              <small>Provider data and model estimates, clearly separated.</small>
            </div>
            <div className={styles.projectBody}>
              <p className={styles.status}>Live application · limited model coverage</p>
              <h3>SkyETA</h3>
              <p>Flight intelligence combining fare search, flight-data analysis and machine learning. Trained delay estimates cover verified U.S. routes.</p>
              <p className={styles.stack}>Python / LightGBM / TypeScript / React</p>
              <div className={styles.projectLinks}>
                <a href="/projects/skyeta">Read case study →</a>
                <a href="/skyeta" target="_blank" rel="noreferrer" aria-label="Open SkyETA in a new tab">Open SkyETA ↗</a>
                <a href="https://github.com/Elijahpeters/peters-elijah-portfolio" target="_blank" rel="noreferrer">View SkyETA source ↗</a>
              </div>
            </div>
          </article>
          <article className={styles.projectCard} id="incubator-carrier">
            <figure className={styles.projectImage}>
              <Image src="/assets/incubator-pcb-angled.png" alt="KiCad 3D render of the two-layer incubator carrier PCB" width={4200} height={2367} unoptimized sizes="(max-width: 1000px) 92vw, 30vw" />
              <figcaption>KiCad render · not assembled hardware</figcaption>
            </figure>
            <div className={styles.projectBody}>
              <p className={styles.status}>Design checks passed · not bench-tested</p>
              <h3>Incubator Carrier PCB</h3>
              <p>A two-layer interface board for an Arduino Mega incubator controller, connecting sensors, relay-control signals and status indicators.</p>
              <p className={styles.stack}>KiCad / 2 layers / 96 × 76 mm / Rev C</p>
              <div className={styles.projectLinks}>
                <a href="/projects/incubator-carrier">Read PCB case study →</a>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section className="section circuit-work" id="circuits">
        <header className="section-heading">
          <p className="section-label">03 / Circuit Design &amp; PCB Work</p>
          <h2>Schematics, simulation &amp; design decisions.</h2>
          <p className="section-intro">Five circuit studies, with original diagrams, findings and unresolved limitations preserved.</p>
        </header>
        <div className={styles.circuitLayout}>
          <a className={styles.circuitSpotlight} href="/projects/incubator-carrier">
            <Image src="/assets/incubator-pcb-layout.png" alt="Routing and component placement in the incubator PCB layout" width={1600} height={2000} unoptimized sizes="(max-width: 820px) 92vw, 36vw" />
            <div><p className="project-type">PCB development</p><h3>From schematic to routed board.</h3><p>Review the layout, pin-map audit and saved ERC/DRC results.</p><span>Explore PCB evidence →</span></div>
          </a>
          <div className={styles.studyList}>
            {circuitStudies.map((project, index) => (
              <a href={project.href} key={project.id} aria-label={`Read the ${project.title} circuit study`}>
                <span className={styles.studyNumber}>0{index + 1}</span>
                <div><p>{project.type}</p><h3>{project.title}</h3><span>{project.result}</span></div>
                <span aria-hidden="true">↗</span>
              </a>
            ))}
            <a className={styles.allStudies} href="/projects/circuits">Read circuit study collection →</a>
          </div>
        </div>
      </section>

      <ExperienceSection />

      <section className="section profile" id="about">
        <figure className="profile-portrait">
          <div>
            <picture>
              <source
                media="(max-width: 760px)"
                srcSet="/assets/portrait-secondary-web-mobile.webp"
                type="image/webp"
              />
              <Image
                src="/assets/portrait-secondary-web.jpg"
                alt="Peters Elijah in a navy suit"
                fill
                unoptimized
                sizes="(max-width: 800px) 92vw, 40vw"
                className="portrait-image secondary-portrait"
              />
            </picture>
          </div>
          <figcaption>Peters Elijah / Electrical &amp; Electronics Engineer</figcaption>
        </figure>

        <div className="profile-copy">
          <p className="section-label">05 / About Me &amp; Technical Skills</p>
          <h2>Engineering across hardware and software.</h2>
          <p className="profile-lead">
            I am an Electrical &amp; Electronics Engineer based in Ogun State,
            Nigeria, with a B.Eng from Olabisi Onabanjo University
            (Second Class Upper).
          </p>
          <p>
            My work connects circuit design and simulation with embedded
            interfaces and applied machine learning. At Micro1, I review
            circuit designs and AI-generated engineering work for technical accuracy.
          </p>

          <div className="capabilities">
            {capabilities.map((capability) => (
              <article key={capability.number}>
                <span>{capability.number}</span>
                <div>
                  <h3>{capability.title}</h3>
                  <p>{capability.text}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="contact" id="contact">
        <p className="section-label">06 / Contact</p>
        <h2>Let’s discuss your engineering team.</h2>
        <p>
          I’m open to electronics, embedded systems, AI evaluation and
          multidisciplinary engineering opportunities.
        </p>
        <ContactForm />
        <div className="contact-actions">
          <a href="mailto:peterselijah11@gmail.com">
            peterselijah11@gmail.com <span aria-hidden="true">↗</span>
          </a>
          <a href="tel:+2349021985375">
            +234 902 198 5375 <span aria-hidden="true">↗</span>
          </a>
          <a
            href="https://github.com/Elijahpeters"
            target="_blank"
            rel="noreferrer"
            aria-label="Open Peters Elijah's GitHub profile in a new tab"
          >
            GitHub <span aria-hidden="true">↗</span>
          </a>
          <a
            href="https://www.linkedin.com/in/elijahpeters01"
            target="_blank"
            rel="noreferrer"
            aria-label="Open Peters Elijah's LinkedIn profile in a new tab"
          >
            LinkedIn <span aria-hidden="true">↗</span>
          </a>
          <a href="/assets/Peters-Elijah-CV.pdf" download>
            Download CV <span aria-hidden="true">↓</span>
          </a>
        </div>
      </section>
      </main>

      <footer>
        <a className="brand footer-brand" href="#top">
          Peters Elijah<span>.</span>
        </a>
        <p>Electrical & Electronics Engineer · Ogun State, Nigeria</p>
        <a href="#top">Back to top ↑</a>
      </footer>
    </div>
  );
}
