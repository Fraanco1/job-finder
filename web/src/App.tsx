import { useCallback, useDeferredValue, useEffect, useMemo, useState } from "react";
import type { LatLngBounds } from "leaflet";
import MapView from "./MapView";
import QueryBar from "./QueryBar";
import Results from "./Results";
import Detail from "./Detail";
import { KIND_LABEL, KIND_ORDER } from "./kinds";
import { relativeTime } from "./format";
import { type Filters, filtersFromQuery, filtersToQuery, matches, sortItems, todayISO } from "./filters";
import type { Dataset, Kind, Opportunity } from "./types";

type Load = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; data: Dataset };

function useDarkMode(): boolean {
  const q = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia?.(q).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(q);
    if (!mq) return;
    const fn = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);
  return dark;
}

async function fetchData(): Promise<Dataset> {
  const r = await fetch(`data/opportunities.json?t=${Date.now()}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export default function App() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [filters, setFilters] = useState<Filters>(() => filtersFromQuery(window.location.search));
  const [bounds, setBounds] = useState<LatLngBounds | null>(null);
  const [inViewOnly, setInViewOnly] = useState(true);
  const [pinned, setPinned] = useState<string[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const dark = useDarkMode();
  const today = useMemo(todayISO, []);

  const reload = useCallback(() => {
    fetchData()
      .then((data) => setLoad({ state: "ready", data }))
      .catch((e) => setLoad({ state: "error", message: String(e.message ?? e) }));
  }, []);
  useEffect(reload, [reload]);

  useEffect(() => {
    const qs = filtersToQuery(filters);
    window.history.replaceState(null, "", `${window.location.pathname}${qs}`);
  }, [filters]);

  const set = useCallback((patch: Partial<Filters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPinned(null);
  }, []);

  const deferred = useDeferredValue(filters);
  const data = load.state === "ready" ? load.data : null;

  // Everything except the kind filter, so the legend can show counts per kind.
  const preKind = useMemo(() => {
    if (!data) return [];
    const f = { ...deferred, kinds: [] };
    return data.items.filter((o) => matches(o, f, today));
  }, [data, deferred, today]);

  const filtered = useMemo(
    () => sortItems(deferred.kinds.length ? preKind.filter((o) => deferred.kinds.includes(o.kind)) : preKind, deferred.sort),
    [preKind, deferred.kinds, deferred.sort],
  );

  const kindCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const o of preKind) c[o.kind] = (c[o.kind] ?? 0) + 1;
    return c;
  }, [preKind]);

  const countries = useMemo(() => {
    if (!data) return [];
    const m = new Map<string, { code: string; name: string; n: number }>();
    for (const o of data.items)
      for (const l of o.locs ?? [])
        if (l.country_code && l.country) {
          const e = m.get(l.country_code) ?? { code: l.country_code, name: l.country, n: 0 };
          e.n++;
          m.set(l.country_code, e);
        }
    return [...m.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [data]);

  const mappable = (o: Opportunity) => (o.locs ?? []).some((l) => l.lat != null);
  const unmapped = useMemo(() => filtered.filter((o) => !mappable(o)).length, [filtered]);

  const listed = useMemo(() => {
    if (pinned) {
      const ids = new Set(pinned);
      return filtered.filter((o) => ids.has(o.id));
    }
    if (!inViewOnly || !bounds) return filtered;
    return filtered.filter((o) => (o.locs ?? []).some((l) => l.lat != null && bounds.contains([l.lat, l.lon!])));
  }, [filtered, pinned, inViewOnly, bounds]);

  const selected = data && selectedId ? data.items.find((o) => o.id === selectedId) ?? null : null;

  const onMapSelect = useCallback((ids: string[]) => {
    if (ids.length === 1) {
      setSelectedId(ids[0]);
    } else {
      setPinned(ids);
      setSelectedId(null);
    }
  }, []);

  const toggleKind = (k: Kind) => {
    const has = filters.kinds.includes(k);
    set({ kinds: has ? filters.kinds.filter((x) => x !== k) : [...filters.kinds, k] });
  };

  if (load.state === "loading") {
    return <div className="splash">Loading opportunities…</div>;
  }
  if (load.state === "error" || !data) {
    return (
      <div className="splash">
        <h1>No data yet</h1>
        <p>
          The opportunity file could not be loaded ({load.state === "error" ? load.message : "empty"}). Run the scrapers
          first:
        </p>
        <pre>cd scraper && python -m jobfinder scrape</pre>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="top">
        <h1 className="brand">
          <svg viewBox="0 0 32 32" aria-hidden="true">
            <circle cx="16" cy="16" r="12" />
            <circle cx="16" cy="16" r="4" className="dot" />
          </svg>
          Fieldwork
        </h1>
        <QueryBar f={filters} set={set} taxonomy={data.taxonomy} countries={countries} />
      </header>

      <main className="body">
        <div className="map-wrap">
          <MapView items={filtered} selectedId={selectedId} onSelect={onMapSelect} onBounds={setBounds} dark={dark} />
          <fieldset className="legend">
            <legend className="sr-only">Opportunity types</legend>
            {KIND_ORDER.map((k) => {
              const on = filters.kinds.length === 0 || filters.kinds.includes(k);
              return (
                <button
                  key={k}
                  type="button"
                  className={`chip k-${k}${on ? "" : " off"}`}
                  aria-pressed={filters.kinds.includes(k)}
                  onClick={() => toggleKind(k)}
                >
                  <i aria-hidden="true" />
                  {KIND_LABEL[k]}
                  <span className="n">{(kindCounts[k] ?? 0).toLocaleString("en")}</span>
                </button>
              );
            })}
          </fieldset>
        </div>

        <aside className="panel">
          {selected ? (
            <Detail
              o={selected}
              taxonomy={data.taxonomy}
              sources={data.sources}
              today={today}
              onClose={() => setSelectedId(null)}
            />
          ) : (
            <Results
              items={listed}
              total={filtered.length}
              inViewOnly={inViewOnly}
              setInViewOnly={setInViewOnly}
              sort={filters.sort}
              setSort={(sort) => set({ sort })}
              pinned={pinned}
              clearPinned={() => setPinned(null)}
              onOpen={setSelectedId}
              selectedId={selectedId}
              today={today}
              unmapped={inViewOnly ? unmapped : 0}
            />
          )}
          <DataStatus data={data} onRefreshed={reload} />
        </aside>
      </main>
    </div>
  );
}

/** Freshness line, plus a refresh button when served by `python -m jobfinder serve`. */
function DataStatus({ data, onRefreshed }: { data: Dataset; onRefreshed: () => void }) {
  const [api, setApi] = useState<"none" | "idle" | "running">("none");
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    fetch("api/status")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((s) => setApi(s.running ? "running" : "idle"))
      .catch(() => setApi("none"));
  }, []);

  useEffect(() => {
    if (api !== "running") return;
    const t = setInterval(async () => {
      try {
        const s = await (await fetch("api/status")).json();
        if (!s.running) {
          setApi("idle");
          setMsg(s.error ? `Refresh failed: ${s.error}` : "Data refreshed.");
          onRefreshed();
        }
      } catch {
        /* keep polling */
      }
    }, 4000);
    return () => clearInterval(t);
  }, [api, onRefreshed]);

  const refresh = async () => {
    setMsg(null);
    const r = await fetch("api/refresh", { method: "POST" });
    if (r.ok) setApi("running");
    else setMsg(`Refresh could not start (HTTP ${r.status}).`);
  };

  const failing = data.sources.filter((s) => !s.ok || s.stale);
  return (
    <footer className="status">
      <details>
        <summary>
          Updated {relativeTime(data.generated)} from {data.sources.length} source{data.sources.length === 1 ? "" : "s"}
          {failing.length > 0 && <span className="warn"> · {failing.length} using older data</span>}
        </summary>
        <ul className="plain sources">
          {data.sources.map((s) => (
            <li key={s.id}>
              <a href={s.homepage} target="_blank" rel="noopener noreferrer">
                {s.name}
              </a>{" "}
              <span className="muted">
                {(s.count ?? 0).toLocaleString("en")}
                {s.stale ? ", from an earlier run" : ""}
              </span>
            </li>
          ))}
        </ul>
      </details>
      {api !== "none" && (
        <button type="button" className="refresh" disabled={api === "running"} onClick={refresh}>
          {api === "running" ? "Refreshing… this takes a few minutes" : "Refresh data"}
        </button>
      )}
      {msg && <p className="small">{msg}</p>}
    </footer>
  );
}
