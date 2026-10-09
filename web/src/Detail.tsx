import { useEffect, useRef } from "react";
import { KIND_LABEL } from "./kinds";
import { EDU_LABEL, deadlineLabel, fmtDate, placeLabel, startLabel } from "./format";
import type { Discipline, Opportunity, SourceStatus } from "./types";

interface Props {
  o: Opportunity;
  taxonomy: Discipline[];
  sources: SourceStatus[];
  today: string;
  onClose: () => void;
}

export default function Detail({ o, taxonomy, sources, today, onClose }: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), [o.id]);

  const discLabel = (id: string) => taxonomy.find((d) => d.id === id)?.label ?? id;
  const subLabel = (id: string) => {
    for (const d of taxonomy) {
      const s = d.subfields.find((x) => x.id === id);
      if (s) return s.label;
    }
    return id;
  };
  const source = sources.find((s) => s.id === o.source);
  const start = startLabel(o);

  return (
    <article className="detail" aria-labelledby="detail-title">
      <button type="button" className="back" onClick={onClose}>
        Back to results
      </button>
      <p className={`kind k-${o.kind}`}>{KIND_LABEL[o.kind]}</p>
      <h2 id="detail-title" tabIndex={-1} ref={heading}>
        {o.title}
      </h2>
      {o.org && <p className="detail-org">{o.org}</p>}

      <dl className="facts">
        <div>
          <dt>Deadline</dt>
          <dd>{o.deadline ? `${fmtDate(o.deadline)} (${deadlineLabel(o, today).toLowerCase()})` : "Not stated"}</dd>
        </div>
        <div>
          <dt>Start</dt>
          <dd>{start ?? "Not stated"}</dd>
        </div>
        <div>
          <dt>Where</dt>
          <dd>
            {(o.locs ?? []).length ? (
              <ul className="plain">
                {o.locs!.map((l, i) => (
                  <li key={i}>
                    {placeLabel(l)}
                    {l.remote && l.city ? " (remote possible)" : ""}
                  </li>
                ))}
              </ul>
            ) : (
              "Not stated"
            )}
          </dd>
        </div>
        {(o.req?.length || o.edu) && (
          <div>
            <dt>Asks for</dt>
            <dd>
              {[o.edu ? EDU_LABEL[o.edu] : null, o.req?.length ? `background in ${o.req.map(discLabel).join(", ")}` : null]
                .filter(Boolean)
                .join(", ")}
            </dd>
          </div>
        )}
        {o.salary && (
          <div>
            <dt>Pay</dt>
            <dd>{o.salary}</dd>
          </div>
        )}
        {o.contract && (
          <div>
            <dt>Contract</dt>
            <dd>{o.contract}</dd>
          </div>
        )}
        {o.posted && (
          <div>
            <dt>Posted</dt>
            <dd>{fmtDate(o.posted)}</dd>
          </div>
        )}
      </dl>

      {o.summary && <p className="summary">{o.summary}</p>}

      <ul className="tags" aria-label="Fields">
        {o.disc.map((d) => (
          <li key={d} className="tag strong">
            {discLabel(d)}
          </li>
        ))}
        {(o.sub ?? []).map((s) => (
          <li key={s} className="tag">
            {subLabel(s)}
          </li>
        ))}
      </ul>

      <a className="apply" href={o.url} target="_blank" rel="noopener noreferrer">
        Open the full posting{source ? ` on ${source.name}` : ""}
      </a>
      <p className="muted small">
        Details above are extracted automatically. Check the original posting before applying.
      </p>
    </article>
  );
}
