import type { ReactNode } from "react";

const repository = "https://github.com/Elijahpeters/peters-elijah-portfolio/blob/main/";

export function readmeLink(value: string): string | undefined {
  if (/^(https?:|mailto:)/i.test(value) || value.startsWith("#")) return value;
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  if (/^[\w.-]+(?:\/[\w./-]+)*(?:#[\w-]+)?$/.test(value)) {
    return value.startsWith("public/") ? value.slice(6) : repository + value;
  }
}

export function headingAnchor(value: string) {
  return value.toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s/g, "-");
}

function inline(value: string): ReactNode[] {
  // A bounded Markdown subset for this repository's README. React escapes text;
  // raw HTML, embedded scripts and arbitrary Markdown extensions are not run.
  const tokens = /\[([^\]]+)\]\(([^\s)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`/g;
  const result: ReactNode[] = [];
  let start = 0;
  for (const match of value.matchAll(tokens)) {
    result.push(value.slice(start, match.index));
    if (match[1]) {
      const href = readmeLink(match[2]);
      result.push(href ? <a key={match.index} href={href}>{inline(match[1])}</a> : match[1]);
    } else if (match[3]) result.push(<strong key={match.index}>{match[3]}</strong>);
    else result.push(<code key={match.index}>{match[4]}</code>);
    start = match.index! + match[0].length;
  }
  result.push(value.slice(start));
  return result;
}

export default function ReadmeContent({ source }: { source: string }) {
  const lines = source.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  const isBlock = (line: string) => /^(#{1,3} |[-*] |```|\||---\s*$)/.test(line);
  for (let i = 0; i < lines.length;) {
    const line = lines[i].trim();
    const key = i;
    if (!line) { i++; continue; }
    if (line.startsWith("```")) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) code.push(lines[i++]);
      i++;
      blocks.push(<pre key={key}><code>{code.join("\n")}</code></pre>);
    } else if (/^#{1,3} /.test(line)) {
      const level = line.indexOf(" ");
      const text = line.slice(level + 1);
      const id = headingAnchor(text);
      blocks.push(level === 1 ? <h1 key={key} id={id}>{inline(text)}</h1> : level === 2 ? <h2 key={key} id={id}>{inline(text)}</h2> : <h3 key={key} id={id}>{inline(text)}</h3>);
      i++;
    } else if (/^---\s*$/.test(line)) {
      blocks.push(<hr key={key} />); i++;
    } else if (line.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const row = lines[i++].trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());
        if (!row.every(cell => /^:?-+:?$/.test(cell))) rows.push(row);
      }
      blocks.push(<div key={key} className="readme-table" tabIndex={0} role="region" aria-label="Project overview table"><table><thead><tr>{rows[0]?.map((cell, n) => <th key={n} scope="col">{inline(cell)}</th>)}</tr></thead><tbody>{rows.slice(1).map((row, n) => <tr key={n}>{row.map((cell, c) => <td key={c}>{inline(cell)}</td>)}</tr>)}</tbody></table></div>);
    } else if (/^[-*] /.test(line)) {
      const items: ReactNode[] = [];
      while (i < lines.length && /^[-*] /.test(lines[i].trim())) {
        let text = lines[i++].trim().slice(2);
        while (i < lines.length && lines[i].trim() && /^\s/.test(lines[i]) && !isBlock(lines[i].trim())) text += " " + lines[i++].trim();
        items.push(<li key={i}>{inline(text)}</li>);
      }
      blocks.push(<ul key={key}>{items}</ul>);
    } else {
      let text = lines[i++].trim();
      while (i < lines.length && lines[i].trim() && !isBlock(lines[i].trim())) text += " " + lines[i++].trim();
      blocks.push(<p key={key}>{inline(text)}</p>);
    }
  }
  return <>{blocks}</>;
}
