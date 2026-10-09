import type { Kind, Opportunity } from "./types";

export interface Filters {
  kinds: Kind[]; // empty = all
  discipline: string; // "" = any
  subfields: string[]; // within discipline; empty = any
  background: string; // discipline id the posting must explicitly ask for; "" = any
  available: string; // ISO date the user can start from
  flex: number; // days of tolerance for start dates earlier than `available`
  requireDeadline: boolean; // hide postings without a known deadline
  remoteOnly: boolean;
  q: string;
  country: string; // ISO code, "" = any
  sort: "deadline" | "posted" | "start";
}

export const todayISO = (): string => {
  const d = new Date();
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - off).toISOString().slice(0, 10);
};

export const defaultFilters = (): Filters => ({
  kinds: [],
  discipline: "",
  subfields: [],
  background: "",
  available: todayISO(),
  flex: 30,
  requireDeadline: false,
  remoteOnly: false,
  q: "",
  country: "",
  sort: "deadline",
});

const addDays = (iso: string, days: number): string => {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};

/**
 * Date rules (from the project brief):
 *  - the application deadline must be on or after the date the user is available from
 *    (and never in the past);
 *  - a known start date must not be earlier than the availability date, minus the chosen
 *    flexibility. Unknown or "as soon as possible" start dates are kept: the posting can
 *    still be negotiated.
 */
export function dateCompatible(o: Opportunity, f: Filters, today = todayISO()): boolean {
  const from = f.available > today ? f.available : today;
  if (o.deadline) {
    if (o.deadline < from) return false;
  } else if (f.requireDeadline) {
    return false;
  }
  if (o.start && o.start < addDays(f.available, -f.flex)) return false;
  return true;
}

const norm = (s: string) =>
  s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();

export function matches(o: Opportunity, f: Filters, today = todayISO()): boolean {
  if (f.kinds.length && !f.kinds.includes(o.kind)) return false;
  if (f.discipline && !o.disc.includes(f.discipline)) return false;
  if (f.subfields.length && !f.subfields.some((s) => o.sub?.includes(s))) return false;
  if (f.background && !o.req?.includes(f.background)) return false;
  if (f.remoteOnly && !o.locs?.some((l) => l.remote)) return false;
  if (f.country && !o.locs?.some((l) => l.country_code === f.country)) return false;
  if (!dateCompatible(o, f, today)) return false;
  if (f.q) {
    const hay = norm(
      [o.title, o.org, o.summary, ...(o.locs ?? []).map((l) => `${l.city ?? ""} ${l.country ?? ""}`)].join(" "),
    );
    if (!norm(f.q).split(/\s+/).filter(Boolean).every((w) => hay.includes(w))) return false;
  }
  return true;
}

export function sortItems(items: Opportunity[], sort: Filters["sort"]): Opportunity[] {
  const key = (o: Opportunity): string => {
    if (sort === "posted") return o.posted ? invert(o.posted) : "~";
    if (sort === "start") return o.start ?? "~";
    return o.deadline ?? "~";
  };
  return [...items].sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0));
}

// Lexicographic inversion so the newest ISO date sorts first.
const invert = (iso: string) => iso.replace(/\d/g, (d) => String(9 - Number(d)));

// ---------------------------------------------------------------- URL state

export function filtersToQuery(f: Filters): string {
  const d = defaultFilters();
  const p = new URLSearchParams();
  if (f.kinds.length) p.set("type", f.kinds.join(","));
  if (f.discipline) p.set("field", f.discipline);
  if (f.subfields.length) p.set("sub", f.subfields.join(","));
  if (f.background) p.set("bg", f.background);
  if (f.available !== d.available) p.set("from", f.available);
  if (f.flex !== d.flex) p.set("flex", String(f.flex));
  if (f.requireDeadline) p.set("dl", "1");
  if (f.remoteOnly) p.set("remote", "1");
  if (f.q) p.set("q", f.q);
  if (f.country) p.set("country", f.country);
  if (f.sort !== d.sort) p.set("sort", f.sort);
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function filtersFromQuery(search: string): Filters {
  const f = defaultFilters();
  const p = new URLSearchParams(search);
  const list = (k: string) => (p.get(k) ?? "").split(",").filter(Boolean);
  f.kinds = list("type") as Kind[];
  f.discipline = p.get("field") ?? "";
  f.subfields = list("sub");
  f.background = p.get("bg") ?? "";
  const from = p.get("from");
  if (from && /^\d{4}-\d{2}-\d{2}$/.test(from) && from >= f.available) f.available = from;
  const flex = Number(p.get("flex"));
  if (Number.isFinite(flex) && p.has("flex")) f.flex = Math.max(0, Math.min(365, flex));
  f.requireDeadline = p.get("dl") === "1";
  f.remoteOnly = p.get("remote") === "1";
  f.q = p.get("q") ?? "";
  f.country = p.get("country") ?? "";
  const sort = p.get("sort");
  if (sort === "posted" || sort === "start") f.sort = sort;
  return f;
}
