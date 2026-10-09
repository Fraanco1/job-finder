import { useEffect, useRef, useState } from "react";
import { KIND_LABEL } from "./kinds";
import { deadlineLabel, daysUntil, placesLabel, startLabel } from "./format";
import type { Filters } from "./filters";
import type { Opportunity } from "./types";

interface Props {
  items: Opportunity[];
  total: number;
  inViewOnly: boolean;
  setInViewOnly: (v: boolean) => void;
  sort: Filters["sort"];
  setSort: (s: Filters["sort"]) => void;
  pinned: string[] | null; // ids picked from a map cluster
  clearPinned: () => void;
  onOpen: (id: string) => void;
  selectedId: string | null;
  today: string;
  unmapped: number;
}

const PAGE = 60;

export default function Results(p: Props) {
  const [shown, setShown] = useState(PAGE);
  const listRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    setShown(PAGE);
    listRef.current?.scrollTo({ top: 0 });
  }, [p.items]);

  return (
    <section className="results" aria-label="Results">
      <header className="results-head">
        <p className="count" aria-live="polite">
          <strong>{p.items.length.toLocaleString("en")}</strong>{" "}
          {p.pinned ? "at this place" : p.inViewOnly ? "in the map view" : "matching"}
          {!p.pinned && p.inViewOnly && p.total !== p.items.length && (
            <span className="muted"> of {p.total.toLocaleString("en")}</span>
          )}
        </p>
        <div className="results-tools">
          {p.pinned ? (
            <button type="button" className="link" onClick={p.clearPinned}>
              Show all results
            </button>
          ) : (
            <label className="check small">
              <input type="checkbox" checked={p.inViewOnly} onChange={(e) => p.setInViewOnly(e.target.checked)} />
              <span>Only in map view</span>
            </label>
          )}
          <label className="field small">
            <span className="sr-only">Sort by</span>
            <select value={p.sort} onChange={(e) => p.setSort(e.target.value as Filters["sort"])}>
              <option value="deadline">Closing soonest</option>
              <option value="posted">Newest</option>
              <option value="start">Starting soonest</option>
            </select>
          </label>
        </div>
      </header>

      {p.items.length === 0 ? (
        <div className="empty">
          <p>Nothing matches these filters.</p>
          <p className="muted">
            Widen the start-date leeway, pick another field, or choose "any background". Zoom out or turn off "Only in
            map view" to include other regions.
          </p>
        </div>
      ) : (
        <ol className="list" ref={listRef}>
          {p.items.slice(0, shown).map((o) => (
            <li key={o.id}>
              <button
                type="button"
                className={`row${o.id === p.selectedId ? " active" : ""}`}
                onClick={() => p.onOpen(o.id)}
              >
                <span className={`kind k-${o.kind}`}>{KIND_LABEL[o.kind]}</span>
                <span className="row-title">{o.title}</span>
                <span className="row-org">{o.org}</span>
                <span className="row-meta">
                  <span>{placesLabel(o)}</span>
                  <span className={urgency(o, p.today)}>{deadlineLabel(o, p.today)}</span>
                  {startLabel(o) && <span>{startLabel(o)}</span>}
                </span>
              </button>
            </li>
          ))}
          {shown < p.items.length && (
            <li className="more">
              <button type="button" className="link" onClick={() => setShown((n) => n + PAGE * 2)}>
                Show {Math.min(PAGE * 2, p.items.length - shown)} more
              </button>
            </li>
          )}
        </ol>
      )}
      {p.unmapped > 0 && !p.pinned && (
        <p className="foot-note muted">
          {p.unmapped.toLocaleString("en")} matching postings have no mappable location (remote or unspecified) and
          appear only when "Only in map view" is off.
        </p>
      )}
    </section>
  );
}

function urgency(o: Opportunity, today: string): string {
  if (!o.deadline) return "dl none";
  const n = daysUntil(o.deadline, today);
  return n <= 7 ? "dl soon" : "dl";
}
