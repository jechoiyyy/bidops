import { Link } from "react-router-dom";

interface SectionNavGroup {
  title: string;
  items: readonly { id: string; label: string; path: string }[];
}

export function SectionNav({ label, groups, current, search }: {
  label: string;
  groups: readonly SectionNavGroup[];
  current: string;
  search: string;
}) {
  return (
    <nav aria-label={label} className="workbench-section-nav">
      {groups.map(({ title, items }) => (
        <div key={title} role="group" aria-label={title} className="workbench-section-group">
          <div className="workbench-section-label" aria-hidden="true">{title}</div>
          {items.map(({ id, label: itemLabel, path }) => (
            <Link key={id} to={{ pathname: path, search }} aria-current={id === current ? "page" : undefined}>
              {itemLabel}
            </Link>
          ))}
        </div>
      ))}
    </nav>
  );
}
