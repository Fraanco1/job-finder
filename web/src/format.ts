import type { Loc, Opportunity } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function fmtDate(iso?: string): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export function daysUntil(iso: string, today: string): number {
  return Math.round((Date.parse(iso + "T00:00:00Z") - Date.parse(today + "T00:00:00Z")) / 86400000);
}

export function deadlineLabel(o: Opportunity, today: string): string {
  if (!o.deadline) return "No deadline listed";
  const n = daysUntil(o.deadline, today);
  if (n === 0) return "Closes today";
  if (n === 1) return "Closes tomorrow";
  if (n < 21) return `Closes in ${n} days`;
  return `Closes ${fmtDate(o.deadline)}`;
}

export function startLabel(o: Opportunity): string | null {
  if (o.start) return `Starts ${fmtDate(o.start)}`;
  if (o.startText) return o.startText;
  return null;
}

export function placeLabel(l: Loc): string {
  if (l.city) return l.country ? `${l.city}, ${l.country}` : l.city;
  if (l.country) return l.country;
  return l.remote ? "Remote" : "Location not given";
}

export function placesLabel(o: Opportunity): string {
  const locs = o.locs ?? [];
  if (!locs.length) return "Location not given";
  const first = placeLabel(locs[0]);
  const remote = locs.some((l) => l.remote) && !first.startsWith("Remote") ? " · remote possible" : "";
  return locs.length > 1 ? `${first} +${locs.length - 1} more${remote}` : first + remote;
}

export function relativeTime(iso: string): string {
  const mins = Math.round((Date.now() - Date.parse(iso)) / 60000);
  if (mins < 2) return "just now";
  if (mins < 60) return `${mins} minutes ago`;
  const h = Math.round(mins / 60);
  if (h < 48) return `${h} hour${h === 1 ? "" : "s"} ago`;
  return `${Math.round(h / 24)} days ago`;
}

export const EDU_LABEL = { bachelor: "Bachelor's degree", masters: "Master's degree", phd: "PhD" } as const;
