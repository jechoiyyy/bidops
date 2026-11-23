import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { WikiEntry } from "../../lib/companyWikiApi";

export function wikiUrl(view: string, selection: Record<string, string> = {}) {
  return `/company?${new URLSearchParams({ view, ...selection })}`;
}

function target(entry: WikiEntry) {
  if (entry.kind === "portfolio") return wikiUrl("portfolio", { project: entry.slug });
  if (entry.kind === "capability" && entry.slug.startsWith("work-")) {
    return wikiUrl("work-units", entry.slug === "work-units" ? {} : { topic: entry.slug.slice(5) });
  }
  return wikiUrl("pages", { page: `${entry.kind}/${entry.slug}` });
}

export function WikiBody({ body, pages }: { body: string; pages: WikiEntry[] }) {
  const entries = new Map(pages.map(entry => [entry.slug, entry]));
  function inline(line: string) {
    return line.split(/(\[\[[A-Za-z0-9][A-Za-z0-9-]*\]\])/g).map((part, i) => {
      const entry = part.startsWith("[[") && entries.get(part.slice(2, -2));
      return entry ? <Link key={i} to={target(entry)}>{entry.slug}</Link> : part;
    });
  }
  const blocks: ReactNode[] = [];
  const lines = body.split(/\r?\n/);
  for (let i = 0; i < lines.length;) {
    const line = lines[i++];
    if (!line.trim()) continue;
    if (line.startsWith("### ")) blocks.push(<h3>{inline(line.slice(4))}</h3>);
    else if (line.startsWith("## ")) blocks.push(<h2>{inline(line.slice(3))}</h2>);
    else if (line.startsWith("- ")) {
      const items = [line];
      while (lines[i]?.startsWith("- ")) items.push(lines[i++]);
      blocks.push(<ul>{items.map((item, j) => <li key={j}>{inline(item.slice(2))}</li>)}</ul>);
    } else {
      const paragraph = [line];
      while (lines[i]?.trim() && !/^(#{2,3} |- )/.test(lines[i])) paragraph.push(lines[i++]);
      blocks.push(<p>{inline(paragraph.join("\n"))}</p>);
    }
  }
  return <div className="wiki-body">{blocks.map((block, i) => <Fragment key={i}>{block}</Fragment>)}</div>;
}
