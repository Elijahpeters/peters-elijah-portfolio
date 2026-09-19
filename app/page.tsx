import Image from "next/image";
import ContactForm from "./components/ContactForm";
import ExperienceSection from "./components/ExperienceSection";
import HashAnchorRestorer from "./components/HashAnchorRestorer";
import SiteHeader from "./components/SiteHeader";
import engineering from "./projects/engineering.module.css";
import { circuitStudies } from "./lib/circuit-studies";

const capabilities = [
  {
    number: "01",
    title: "Circuit & simulation",
    text: "LTspice, KiCad, Qucs-S, DesignSpark PCB, Proteus and MATLAB/Simulink.",
  },
  {
    number: "02",
    title: "AI & computer vision",
    text: "Python, OpenCV, MediaPipe, DeepFace, scikit-learn, Pandas and NumPy.",
  },
  {
    number: "03",
    title: "Engineering software",
    text: "C++, SQL, HTML/CSS, Bash, Ansys SpaceClaim and Ansys Fluent.",
  },
];

export default function Home() {
  return (
    <>
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
            Circuit design. PCB layout. <em>Working software.</em>
          </h1>
          <p className="hero-summary">
            I’m Peters Elijah, an Electrical &amp; Electronics Engineer working
            with KiCad, circuit simulation and Python. Explore my board layouts,
            circuit studies and hardware–software prototypes, with the evidence
            and limitations behind each project.
          </p>
          <p className="target-roles">
            Embedded systems · Circuit design · AI evaluation ·
            Hardware/software integration
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
          <div className="portrait-orbit" aria-hidden="true" />
          <figcaption>Peters Elijah / Ogun State, Nigeria</figcaption>
        </figure>

        <dl className="hero-facts" aria-label="Professional highlights">
          <div>
            <dt>Education</dt>
            <dd>B.Eng Electrical &amp; Electronics Engineering</dd>
          </div>
          <div>
            <dt>Focus</dt>
            <dd>AI × Electronics</dd>
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

      <ExperienceSection />

      <section className="section selected-work" id="projects">
        <header className="section-heading">
          <p className="section-label">02 / Projects</p>
          <h2>Software that connects models, data and hardware.</h2>
          <p className="section-intro">
            From a locally verified access decision to a flight-data workspace:
            the problem, my contribution and the evidence behind each result.
          </p>
        </header>

        <article className="feature-project" id="aurapass">
          <div className="feature-copy">
            <p className="project-type">Flagship project · 2026</p>
            <h3>AuraPass</h3>
            <p className="feature-lead">
              An offline biometric examination-access prototype connecting
              identity, course eligibility, seat allocation and a simulated gate.
            </p>
            <p>
              Course-form data and guided face samples create a local student
              record. AuraPass then verifies identity, eligibility, repeat entry
              and capacity before reserving a seat and moving the Proteus gate.
            </p>

            <dl className="project-details">
              <div>
                <dt>Role</dt>
                <dd>System design, software, simulation & validation</dd>
              </div>
              <div>
                <dt>Stack</dt>
                <dd>Python, OpenCV, SQLite, Proteus &amp; UDP/serial integration</dd>
              </div>
              <div>
                <dt>Scope</dt>
                <dd>Offline software and hardware-simulation prototype</dd>
              </div>
            </dl>

            <div className="project-actions">
              <a
                className="project-action"
                href="/projects/aurapass"
                aria-label="Read the AuraPass engineering case study"
              >
                Read case study <span aria-hidden="true">→</span>
              </a>
              <a
                className="project-action"
                href="https://github.com/Elijahpeters/AuraPass"
                target="_blank"
                rel="noreferrer"
                aria-label="View AuraPass code on GitHub in a new tab"
              >
                View AuraPass code <span aria-hidden="true">↗</span>
              </a>
            </div>
          </div>

          <figure className="feature-visual">
            <div className="feature-image">
              <picture>
                <source
                  media="(max-width: 760px)"
                  srcSet="/assets/aurapass-flowchart-mobile.webp"
                  type="image/webp"
                />
                <Image
                  src="/assets/aurapass-flowchart.png"
                  alt="AuraPass process from course-form enrollment to access decision"
                  fill
                  unoptimized
                  sizes="(max-width: 900px) 92vw, 52vw"
                  className="contain-image"
                />
              </picture>
            </div>
            <figcaption>
              <span>01</span> System architecture and decision workflow
            </figcaption>
          </figure>
        </article>

        <div className="evidence-row" aria-label="AuraPass system highlights">
          <div>
            <strong>5,000</strong>
            <span>non-enrolled face attempts tested</span>
          </div>
          <div>
            <strong>0</strong>
            <span>false grants in the controlled test set</span>
          </div>
          <div>
            <strong>10</strong>
            <span>image variants per source face</span>
          </div>
        </div>

        <p className="evidence-method">
          Controlled negative-face evaluation: 500 LFW source faces across 10
          original, lighting, contrast, rotation, blur and shadow variants.
          All 5,000 attempts were denied or quality-rejected; none were granted.
          This measures false grants, not overall biometric accuracy.
        </p>

        <article className="skyeta-project" id="skyeta">
          <div className="skyeta-copy">
            <p className="project-type">Machine learning · Systems engineering</p>
            <h3>SkyETA</h3>
            <p className="skyeta-lead">
              A flight-intelligence workspace for comparing provider-backed
              fares worldwide and understanding the evidence available for a
              journey.
            </p>
            <p>
              SkyETA brings fare, schedule and operational sources into one
              organised view. It checks route-matched 15+, 30+ and 60+ minute
              delay history worldwide when records exist, while its trained
              schedule model remains limited to verified U.S. routes.
            </p>

            <div className="skyeta-workflow" aria-labelledby="skyeta-workflow-title">
              <p id="skyeta-workflow-title">How SkyETA works</p>
              <ol>
                <li>
                  <span>01</span>
                  <strong>Search the journey</strong>
                  <small>Choose a route, date, cabin and passenger count.</small>
                </li>
                <li>
                  <span>02</span>
                  <strong>Compare real options</strong>
                  <small>Review current fares, schedules, stops and baggage.</small>
                </li>
                <li>
                  <span>03</span>
                  <strong>Understand the evidence</strong>
                  <small>See flight-specific history, sample confidence and U.S. model coverage.</small>
                </li>
              </ol>
              <small>
                SkyETA labels provider fares, observed AirLabs information and
                historical model estimates separately so visitors know what each
                result means.
              </small>
            </div>

            <dl className="project-details">
              <div>
                <dt>Role</dt>
                <dd>Systems engineering, machine learning &amp; instrumentation UI</dd>
              </div>
              <div>
                <dt>Stack</dt>
                <dd>Python, machine learning, Pandas &amp; TypeScript</dd>
              </div>
              <div>
                <dt>Evidence</dt>
                <dd>5.15M U.S. records profiled · 750k model-fit sample · 643k Brazilian schedules matched to outcomes</dd>
              </div>
            </dl>

            <div className="project-actions">
              <a
                className="project-action"
                href="/skyeta"
                target="_blank"
                rel="noreferrer"
                aria-label="Open SkyETA in a new tab"
              >
                Open SkyETA <span aria-hidden="true">↗</span>
              </a>
              <a
                className="project-action"
                href="https://github.com/Elijahpeters/peters-elijah-portfolio"
                target="_blank"
                rel="noreferrer"
                aria-label="View the integrated SkyETA source on GitHub in a new tab"
              >
                View SkyETA source <span aria-hidden="true">↗</span>
              </a>
              <a
                className="project-action"
                href="https://github.com/Elijahpeters/peters-elijah-portfolio/blob/main/skyeta-ml/global/ANAC_2023_ANNUAL_MODEL_GATE_REVIEW.md"
                target="_blank"
                rel="noreferrer"
                aria-label="Read the SkyETA annual model gate review on GitHub in a new tab"
              >
                Read model audit <span aria-hidden="true">↗</span>
              </a>
            </div>
          </div>

          <aside className="skyeta-portfolio-preview" aria-label="SkyETA information layers">
            <p className="project-type">What each result separates</p>
            <h4>One journey, three clearly labelled evidence layers.</h4>
            <dl>
              <div>
                <dt>01 / Fare</dt>
                <dd>Current provider price, schedule, stops and baggage.</dd>
              </div>
              <div>
                <dt>02 / Delay outlook</dt>
                <dd>A plain-language percentage only where model coverage is verified.</dd>
              </div>
              <div>
                <dt>03 / Recent history</dt>
                <dd>Route-matched completed-flight evidence when available.</dd>
              </div>
            </dl>
            <a className="project-action" href="/skyeta" target="_blank" rel="noreferrer">
              Explore SkyETA <span aria-hidden="true">↗</span>
            </a>
          </aside>
        </article>
      </section>

      <section className="section circuit-work" id="circuits">
        <header className="section-heading compact-heading">
          <p className="section-label">03 / Circuits &amp; PCB design</p>
          <h2>From circuit intent to board layout.</h2>
          <p className="section-intro">
            A KiCad carrier-board project and five circuit studies. Each explains
            the design goal, the evidence available and the work still needed
            before a physical implementation can be trusted.
          </p>
        </header>

        <article className={engineering.feature} id="incubator-carrier">
          <div className={engineering.featureCopy}>
            <p className={engineering.eyebrow}>PCB layout · KiCad · Rev C</p>
            <h3>Incubator interface carrier</h3>
            <p>A two-layer board bringing sensor connections, relay-control
              signals and status indicators into one organised interface for an
              Arduino Mega-based incubator controller.</p>
            <dl className={engineering.featureFacts}>
              <div><dt>Board</dt><dd>96 × 76 mm · 2 copper layers</dd></div>
              <div><dt>My focus</dt><dd>Placement, routing and layout checks</dd></div>
              <div><dt>Status</dt><dd>Design checked · not bench-tested</dd></div>
            </dl>
            <a className={engineering.action} href="/projects/incubator-carrier">
              Explore the PCB case study <span aria-hidden="true">→</span>
            </a>
          </div>
          <figure className={engineering.featureImage}>
            <Image src="/assets/incubator-pcb-angled.png"
              alt="KiCad 3D render of the green two-layer incubator carrier board, with sensor terminals, ribbon header and status LEDs"
              width={4200} height={2367} unoptimized
              sizes="(max-width: 820px) 92vw, 55vw" />
            <figcaption>KiCad 3D render—not a photograph of assembled hardware.</figcaption>
          </figure>
        </article>

        <div className="circuit-grid">
          {circuitStudies.map((project, index) => (
            <a
              className={`circuit-card ${index === 0 ? "circuit-card-featured" : ""}`}
              href={project.href}
              key={project.title}
              aria-label={`Read the ${project.title} circuit study`}
            >
              <div className="circuit-image">
                <picture>
                  <source
                    media="(max-width: 760px)"
                    srcSet={project.mobileImage}
                    type="image/webp"
                  />
                  <Image
                    src={project.image}
                    alt={project.alt}
                    fill
                    unoptimized
                    sizes={index === 0 ? "(max-width: 760px) 92vw, 60vw" : "(max-width: 760px) 92vw, 40vw"}
                    className="contain-image"
                  />
                </picture>
              </div>
              <div className="circuit-copy">
                <div>
                  <p className="project-type">{project.type}</p>
                  <h3>{project.title}</h3>
                </div>
                <p>{project.description}</p>
                <span>{project.result}</span>
                <span className="circuit-evidence-link" aria-hidden="true">
                  Read circuit study <span aria-hidden="true">→</span>
                </span>
              </div>
            </a>
          ))}
        </div>
      </section>

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
          <figcaption>Curious by design / rigorous by practice</figcaption>
        </figure>

        <div className="profile-copy">
          <p className="section-label">04 / Profile</p>
          <h2>
            Engineering systems across circuit design, simulation and applied
            intelligence.
          </h2>
          <p className="profile-lead">
            I am an Electrical &amp; Electronics Engineer working at the
            intersection of electronics and intelligent
            software. I translate technical requirements into testable
            systems—from analysing circuit behaviour and validating schematics
            to developing computer-vision and data-driven applications.
          </p>
          <p>
            I earned my B.Eng in Electrical &amp; Electronics Engineering from
            Olabisi Onabanjo University with Second Class Upper honours. In my
            work with Micro1, I have evaluated circuit designs and AI-generated
            engineering work, paying close attention to the edge cases and
            verification details that separate a plausible result from a
            dependable one.
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
        <p className="section-label">05 / Contact</p>
        <h2>Let’s build something that works beautifully.</h2>
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
    </>
  );
}
