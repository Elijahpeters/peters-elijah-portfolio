import type { ProjectBrief as ProjectBriefData } from "../lib/project-briefs";

export default function ProjectBrief({
  brief,
  tone = "light",
}: {
  brief: ProjectBriefData;
  tone?: "light" | "dark";
}) {
  const headingId = `${brief.id}-title`;

  return (
    <section
      className={`project-brief project-brief--${tone}`}
      id={brief.id}
      aria-labelledby={headingId}
    >
      <h4 id={headingId}>{brief.project} in six questions</h4>
      <dl>
        <div>
          <dt><span>01</span> What problem does it solve?</dt>
          <dd>{brief.problem}</dd>
        </div>
        <div>
          <dt><span>02</span> Why does it matter?</dt>
          <dd>{brief.why}</dd>
        </div>
        <div>
          <dt><span>03</span> What did I build?</dt>
          <dd>{brief.built}</dd>
        </div>
        <div>
          <dt><span>04</span> What did I find?</dt>
          <dd>
            <ul>
              {brief.found.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </dd>
        </div>
        <div>
          <dt><span>05</span> What should happen next?</dt>
          <dd>
            <ul>
              {brief.next.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </dd>
        </div>
        <div>
          <dt><span>06</span> What trade-off did I make?</dt>
          <dd>{brief.tradeoff}</dd>
        </div>
      </dl>
    </section>
  );
}
