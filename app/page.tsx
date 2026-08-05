import Image from "next/image";
import ContactForm from "./components/ContactForm";
import SkyetaDemo from "./components/SkyetaDemo";

const circuitProjects = [
  {
    title: "Antoniou GIC",
    type: "Analog simulation",
    image: "/assets/gic-schematic.webp",
    alt: "Antoniou generalized impedance converter schematic",
    result: "10 H target equivalent",
    description:
      "A TL072-based grounded-inductor model studied from 10 Hz to 100 kHz, including the model’s self-resonant boundary.",
  },
  {
    title: "KHN State-Variable Filter",
    type: "Verification & debugging",
    image: "/assets/svf-schematic.webp",
    alt: "Kerwin-Huelsman-Newcomb state-variable filter schematic",
    result: "HP · BP · LP outputs",
    description:
      "A three-output filter study that pairs frequency-response verification with an honest diagnosis of a negative-damping sign issue.",
  },
  {
    title: "Instrumentation Amplifier",
    type: "Precision analog design",
    image: "/assets/instrumentation-amplifier.webp",
    alt: "Three op-amp instrumentation amplifier simulation",
    result: "Three-op-amp topology",
    description:
      "A Qucs-S implementation used to study differential amplification, gain structure and signal integrity.",
  },
  {
    title: "PFD + Charge Pump",
    type: "Mixed-signal building block",
    image: "/assets/pfd-charge-pump.webp",
    alt: "Phase-frequency detector and charge pump schematic",
    result: "100 μA charge pump",
    description:
      "A sectioned phase-frequency detector and charge-pump design for PLL-oriented logic-to-analog analysis.",
  },
  {
    title: "Boost Converter",
    type: "Power electronics",
    image: "/assets/boost-converter-qucs.webp",
    alt: "Open-loop boost converter with inductor, switch, Schottky diode, capacitor and resistive load",
    result: "12 V-input open-loop stage",
    description:
      "An open-loop boost-converter topology with a Schottky rectifier and resistive output stage, used to study switching behaviour and component stress.",
  },
];

const experience = [
  {
    period: "May 2026 — Present",
    role: "Electronics Circuit Design Expert",
    company: "Micro1",
    summary:
      "Validating schematics, PCB layouts, netlists and AI-generated engineering work across LTspice, KiCad and DesignSpark PCB.",
  },
  {
    period: "Nov 2025 — Feb 2026",
    role: "AI Technical Trainer & Data Specialist",
    company: "Micro1",
    summary:
      "Built and reviewed technical datasets for model reasoning, with emphasis on edge cases, execution quality and reliable evaluation.",
  },
  {
    period: "Aug — Sep 2024",
    role: "Data Science Intern",
    company: "Codsoft",
    summary:
      "Developed practical machine-learning workflows spanning data preparation, exploratory analysis, feature engineering and modelling.",
  },
  {
    period: "Mar — May 2024",
    role: "Data Science Intern",
    company: "DSN-OOU",
    summary:
      "Applied Python-based analysis and machine-learning methods in a collaborative learning and project environment.",
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
    <main id="top">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>

      <header className="site-header">
        <a className="brand" href="#top" aria-label="Peters Elijah, home">
          Peters Elijah<span>.</span>
        </a>
        <nav aria-label="Primary navigation">
          <a href="#projects">Projects</a>
          <a href="#circuits">Circuit Lab</a>
          <a href="#about">Profile</a>
          <a href="#experience">Experience</a>
          <a className="header-contact" href="#contact">
            Get in Touch <span aria-hidden="true">↗</span>
          </a>
        </nav>
      </header>

      <section className="hero" id="main-content">
        <div className="hero-copy">
          <p className="eyebrow">Electrical engineer / AI systems</p>
          <h1>
            Thoughtful engineering for an <em>intelligent</em> world.
          </h1>
          <p className="hero-summary">
            I build dependable systems across embedded electronics, circuit
            simulation and applied machine learning—moving carefully from first
            principles to working prototype.
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
            <Image
              src="/assets/portrait-web.jpg"
              alt="Peters Elijah wearing a navy suit and tie"
              fill
              unoptimized
              priority
              sizes="(max-width: 760px) 92vw, 42vw"
              className="portrait-image"
            />
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

      <section className="section selected-work" id="projects">
        <header className="section-heading">
          <p className="section-label">01 / Projects</p>
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
              record. AuraPass then settles identity, eligibility, repeat entry
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
              <Image
                src="/assets/aurapass-flowchart.png"
                alt="AuraPass process from course-form enrollment to access decision"
                fill
                unoptimized
                sizes="(max-width: 900px) 92vw, 52vw"
                className="contain-image"
              />
            </div>
            <figcaption>
              <span>01</span> System architecture and decision workflow
            </figcaption>
          </figure>
        </article>

        <div className="evidence-row" aria-label="AuraPass system highlights">
          <div>
            <strong>5,000</strong>
            <span>unknown-face presentations tested</span>
          </div>
          <div>
            <strong>0</strong>
            <span>false grants in the controlled test set</span>
          </div>
          <div>
            <strong>6 / 6</strong>
            <span>complete system cases passed</span>
          </div>
        </div>

        <div className="project-process">
          <figure className="process-diagram">
            <Image
              src="/assets/aurapass-proteus.png"
              alt="AuraPass Proteus hardware simulation"
              fill
              unoptimized
              sizes="(max-width: 900px) 92vw, 48vw"
              className="contain-image"
            />
          </figure>
          <div className="process-copy">
            <p className="section-label">The system logic</p>
            <h3>One decision path, clearly accounted for.</h3>
            <p>
              A face match cannot bypass the course, repeat-entry, capacity or
              seat rules. The grant is committed before the gate command is sent.
            </p>
            <ol>
              <li><span>01</span> Parse the course form and store guided face samples.</li>
              <li><span>02</span> Verify identity, eligibility, repeat entry and capacity.</li>
              <li><span>03</span> Reserve a seat, log the result and drive the LCD, LEDs, buzzer and servo.</li>
            </ol>
            <p className="scope-note">
              Validated at simulation level; physical gate hardware, liveness
              detection and live university integration remain future work.
            </p>
          </div>
        </div>

        <div className="state-gallery">
          <figure>
            <Image
              src="/assets/aurapass-locked.png"
              alt="AuraPass simulated gate in denied state"
              fill
              unoptimized
              sizes="(max-width: 760px) 92vw, 23vw"
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
              sizes="(max-width: 760px) 92vw, 23vw"
              className="project-image"
            />
            <figcaption>Granted state</figcaption>
          </figure>
        </div>

        <article className="skyeta-project" id="skyeta">
          <div className="skyeta-copy">
            <p className="project-type">Machine learning · Systems engineering</p>
            <h3>SkyETA</h3>
            <p className="skyeta-lead">
              A browser-based flight-delay risk instrument for exploring how
              route, carrier and schedule context affect a journey.
            </p>
            <p>
              SkyETA checks each input, evaluates the selected route and
              schedule locally, and presents the result through an
              instrumentation-inspired interface.
            </p>

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
                <dd>5.15M source records · 150,000-flight chronological test</dd>
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

          <SkyetaDemo />
        </article>
      </section>

      <section className="section circuit-work" id="circuits">
        <header className="section-heading compact-heading">
          <p className="section-label">02 / Circuit laboratory</p>
          <h2>Designed, simulated and interrogated.</h2>
          <p className="section-intro">
            The schematic is only the beginning; the useful work is understanding
            what the response says and where the model stops being trustworthy.
          </p>
        </header>

        <div className="circuit-grid">
          {circuitProjects.map((project, index) => (
            <article
              className={`circuit-card ${index === 0 ? "circuit-card-featured" : ""}`}
              key={project.title}
            >
              <div className="circuit-image">
                <Image
                  src={project.image}
                  alt={project.alt}
                  fill
                  unoptimized
                  sizes={index === 0 ? "(max-width: 760px) 92vw, 60vw" : "(max-width: 760px) 92vw, 40vw"}
                  className="contain-image"
                />
              </div>
              <div className="circuit-copy">
                <div>
                  <p className="project-type">{project.type}</p>
                  <h3>{project.title}</h3>
                </div>
                <p>{project.description}</p>
                <span>{project.result}</span>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="section profile" id="about">
        <figure className="profile-portrait">
          <div>
            <Image
              src="/assets/portrait-secondary-web.jpg"
              alt="Peters Elijah in a navy suit"
              fill
              unoptimized
              sizes="(max-width: 800px) 92vw, 40vw"
              className="portrait-image secondary-portrait"
            />
          </div>
          <figcaption>Curious by design / rigorous by practice</figcaption>
        </figure>

        <div className="profile-copy">
          <p className="section-label">03 / Profile</p>
          <h2>
            Engineering systems across circuit design, simulation and applied
            intelligence.
          </h2>
          <p className="profile-lead">
            My name is Peters Elijah Temidayo, an Electrical &amp; Electronics
            Engineer working at the intersection of electronics and intelligent
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

      <section className="section experience" id="experience">
        <header className="section-heading compact-heading">
          <p className="section-label">04 / Experience</p>
          <h2>
            Electronics design, AI evaluation and data science—in professional
            practice.
          </h2>
          <p className="section-intro">
            My experience spans circuit-design review, validation of
            AI-generated engineering work, technical AI training and applied
            data science—with a consistent focus on technical accuracy.
          </p>
        </header>

        <div className="experience-list">
          {experience.map((item, index) => (
            <article key={`${item.company}-${item.role}`}>
              <span className="experience-number">0{index + 1}</span>
              <p className="experience-period">{item.period}</p>
              <div>
                <h3>{item.role}</h3>
                <p className="experience-company">{item.company}</p>
              </div>
              <p className="experience-summary">{item.summary}</p>
            </article>
          ))}
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

      <footer>
        <a className="brand footer-brand" href="#top">
          Peters Elijah<span>.</span>
        </a>
        <p>Electrical & Electronics Engineer · Ogun State, Nigeria</p>
        <a href="#top">Back to top ↑</a>
      </footer>
    </main>
  );
}
