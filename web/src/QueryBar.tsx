import { useMemo } from "react";
import { KIND_ORDER, KIND_PHRASE } from "./kinds";
import type { Filters } from "./filters";
import { todayISO } from "./filters";
import { fmtDate } from "./format";
import type { Discipline, Kind } from "./types";

interface Props {
  f: Filters;
  set: (patch: Partial<Filters>) => void;
  taxonomy: Discipline[];
  countries: { code: string; name: string; n: number }[];
}

/**
 * The query reads as a sentence:
 *   Show [PhD positions] in [Physics] › [Quantum computing], open to [physicists],
 *   for someone available from [date].
 * Each bracket is an inline control.
 */
export default function QueryBar({ f, set, taxonomy, countries }: Props) {
  const disc = taxonomy.find((d) => d.id === f.discipline);
  const kindValue = f.kinds.length === 1 ? f.kinds[0] : f.kinds.length === 0 ? "" : "__many";
  const today = useMemo(todayISO, []);

  return (
    <form className="query" onSubmit={(e) => e.preventDefault()} aria-label="Filter opportunities">
      <p className="sentence">
        <span>Show</span>{" "}
        <Inline
          label="Opportunity type"
          value={kindValue}
          onChange={(v) => set({ kinds: v ? [v as Kind] : [] })}
          options={[
            ["", "all opportunities"],
            ...KIND_ORDER.map((k) => [k, KIND_PHRASE[k]] as [string, string]),
            ...(kindValue === "__many" ? [["__many", `${f.kinds.length} selected types`] as [string, string]] : []),
          ]}
        />{" "}
        <span>in</span>{" "}
        <Inline
          label="Field"
          value={f.discipline}
          onChange={(v) => set({ discipline: v, subfields: [] })}
          options={[["", "any STEM field"], ...taxonomy.map((d) => [d.id, d.label] as [string, string])]}
        />
        {disc && (
          <>
            <span className="crumb" aria-hidden="true">›</span>
            <Inline
              label="Subfield"
              value={f.subfields[0] ?? ""}
              onChange={(v) => set({ subfields: v ? [v] : [] })}
              options={[["", "all areas"], ...disc.subfields.map((s) => [s.id, s.label] as [string, string])]}
            />
          </>
        )}
        <span>,</span>{" "}
        <span>asking for</span>{" "}
        <Inline
          label="Required background"
          value={f.background}
          onChange={(v) => set({ background: v })}
          options={[
            ["", "any background"],
            ...taxonomy.map((d) => [d.id, `a ${d.label.toLowerCase()} degree`] as [string, string]),
          ]}
        />
        <span>,</span>{" "}
        <span>that I can start from</span>{" "}
        <label className="inline date set">
          <span className="sr-only">Available from</span>
          <span className="inline-text" aria-hidden="true">
            {f.available === today ? "today" : fmtDate(f.available)}
          </span>
          <input
            type="date"
            value={f.available}
            min={today}
            onClick={(e) => (e.currentTarget as HTMLInputElement & { showPicker?: () => void }).showPicker?.()}
            onChange={(e) => set({ available: e.target.value && e.target.value >= today ? e.target.value : today })}
          />
        </label>
        <span>.</span>
      </p>

      <div className="refine">
        <label className="search">
          <span className="sr-only">Search titles, institutions and places</span>
          <input
            type="search"
            placeholder="Search title, institution, city…"
            value={f.q}
            onChange={(e) => set({ q: e.target.value })}
          />
        </label>
        <label className="field">
          <span>Country</span>
          <select value={f.country} onChange={(e) => set({ country: e.target.value })}>
            <option value="">Anywhere</option>
            {countries.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name} ({c.n})
              </option>
            ))}
          </select>
        </label>
        <label className="field" title="Keep postings whose start date is up to this much earlier than your availability">
          <span>Start-date leeway</span>
          <select value={f.flex} onChange={(e) => set({ flex: Number(e.target.value) })}>
            <option value={0}>None</option>
            <option value={30}>1 month</option>
            <option value={90}>3 months</option>
            <option value={180}>6 months</option>
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={f.requireDeadline} onChange={(e) => set({ requireDeadline: e.target.checked })} />
          <span>Only with a deadline</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={f.remoteOnly} onChange={(e) => set({ remoteOnly: e.target.checked })} />
          <span>Remote</span>
        </label>
      </div>
    </form>
  );
}

function Inline({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
}) {
  const current = options.find(([v]) => v === value)?.[1] ?? options[0][1];
  return (
    <label className={`inline${value ? " set" : ""}`}>
      <span className="sr-only">{label}</span>
      {/* The visible text sizes the control; the transparent select on top handles input. */}
      <span className="inline-text" aria-hidden="true">
        {current}
      </span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, l]) => (
          <option key={v} value={v} disabled={v === "__many"}>
            {l}
          </option>
        ))}
      </select>
    </label>
  );
}
