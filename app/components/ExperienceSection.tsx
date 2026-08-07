const experience = [
  {
    period: "May 2026 - Present",
    role: "Electronics Circuit Design Expert",
    company: "Micro1",
    summary:
      "Validating schematics, PCB layouts, netlists and AI-generated engineering work across LTspice, KiCad and DesignSpark PCB.",
  },
  {
    period: "Nov 2025 - Feb 2026",
    role: "AI Technical Trainer & Data Specialist",
    company: "Micro1",
    summary:
      "Built and reviewed technical datasets for model reasoning, with emphasis on edge cases, execution quality and reliable evaluation.",
  },
  {
    period: "Aug - Sep 2024",
    role: "Data Science Intern",
    company: "Codsoft",
    summary:
      "Developed practical machine-learning workflows spanning data preparation, exploratory analysis, feature engineering and modelling.",
  },
  {
    period: "Mar - May 2024",
    role: "Data Science Intern",
    company: "DSN-OOU",
    summary:
      "Applied Python-based analysis and machine-learning methods in a collaborative learning and project environment.",
  },
];

export default function ExperienceSection() {
  return (
    <section className="section experience" id="experience">
      <header className="section-heading compact-heading">
        <p className="section-label">01 / Experience</p>
        <h2>Engineering judgement, sharpened through professional practice.</h2>
        <p className="section-intro">
          Circuit-design review, AI evaluation and applied data science, with a
          consistent focus on technical accuracy and dependable execution.
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
  );
}
