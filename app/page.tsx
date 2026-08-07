import Image from "next/image";
import ContactForm from "./components/ContactForm";
import ExperienceSection from "./components/ExperienceSection";
import HashAnchorRestorer from "./components/HashAnchorRestorer";
import SiteHeader from "./components/SiteHeader";

const circuitProjects = [
  {
    title: "Antoniou GIC",
    type: "Analog simulation",
    image: "/assets/gic-schematic.webp",
    mobileImage: "/assets/gic-schematic-mobile.webp",
    href: "/assets/gic-schematic.webp",
    alt: "Antoniou generalized impedance converter schematic",
    result: "10 H target equivalent",
    description:
      "A TL072-based grounded-inductor model studied from 10 Hz to 100 kHz, including the model’s self-resonant boundary.",
  },
  {
    title: "KHN State-Variable Filter",
    type: "Verification & debugging",
    image: "/assets/svf-schematic.webp",
    mobileImage: "/assets/svf-schematic-mobile.webp",
    href: "/assets/svf-schematic.webp",
    alt: "Kerwin-Huelsman-Newcomb state-variable filter schematic",
    result: "HP · BP · LP outputs",
    description:
      "A three-output filter study that pairs frequency-response verification with an honest diagnosis of a negative-damping sign issue.",
  },
  {
    title: "Instrumentation Amplifier",
    type: "Precision analog design",
    image: "/assets/instrumentation-amplifier.webp",
    mobileImage: "/assets/instrumentation-amplifier-mobile.webp",
    href: "/assets/instrumentation-amplifier.webp",
    alt: "Three op-amp instrumentation amplifier simulation",
    result: "Three-op-amp topology",
    description:
      "A Qucs-S implementation used to study differential amplification, gain structure and signal integrity.",
  },
  {
    title: "PFD + Charge Pump",
    type: "Mixed-signal building block",
    image: "/assets/pfd-charge-pump.webp",
    mobileImage: "/assets/pfd-charge-pump-mobile.webp",
    href: "/assets/pfd-charge-pump.webp",
    alt: "Phase-frequency detector and charge pump schematic",
    result: "100 μA charge pump",
    description:
      "A sectioned phase-frequency detector and charge-pump design for PLL-oriented logic-to-analog analysis.",
  },
  {
    title: "Boost Converter",
    type: "Power electronics",
    image: "/assets/boost-converter-qucs.webp",
    mobileImage: "/assets/boost-converter-qucs-mobile.webp",
    href: "/assets/boost-converter-qucs.webp",
    alt: "Open-loop boost converter with inductor, switch, Schottky diode, capacitor and resistive load",
    result: "12 V-input open-loop stage",
    description:
      "An open-loop boost-converter topology with a Schottky rectifier and resistive output stage, used to study switching behaviour and component stress.",
  },
];

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
            Thoughtful engineering for an <em>intelligent</em> world.
          </h1>
          <p className="hero-summary">
            I build dependable systems across embedded electronics, circuit
            simulation and applied machine learning—moving carefully from first
            principles to a working prototype.
          </p>
          <p className="target-roles">
            Embedded systems · Circuit design · AI evaluation ·
            Hardware/software integration
          </p>
          <div className="hero-actions">
            <a className="text-link" href="#projects">
              <span aria-hidden="true" /> View projects
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
          <h2>Engineering ideas that hold up beyond the first impression.</h2>
          <p className="section-intro">
            Projects spanning intelligent access systems, analog simulation and
            hardware–software co-design.
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
              organised view. Verified routes receive a late-arrival outlook;
              every other route still receives useful journey facts without an
              invented prediction.
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
                  <small>See verified delay insight or a clear journey summary.</small>
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
                <dd>Provider-backed fares · 5.15M U.S. model records</dd>
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
                href="https://github.com/Elijahpeters/SkyETA"
                target="_blank"
                rel="noreferrer"
                aria-label="View SkyETA code on GitHub in a new tab"
              >
                View SkyETA code <span aria-hidden="true">↗</span>
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
          <p className="section-label">03 / Circuit laboratory</p>
          <h2>Designed, simulated and interrogated.</h2>
          <p className="section-intro">
            The schematic is only the beginning; the useful work is understanding
            what the response says and where the model stops being trustworthy.
          </p>
        </header>

        <div className="circuit-grid">
          {circuitProjects.map((project, index) => (
            <a
              className={`circuit-card ${index === 0 ? "circuit-card-featured" : ""}`}
              href={project.href}
              key={project.title}
              target="_blank"
              rel="noreferrer"
              aria-label={`Open the ${project.title} schematic in a new tab`}
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
                  Open schematic <span aria-hidden="true">↗</span>
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
            current role at Micro1, I evaluate circuit designs and AI-generated
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
