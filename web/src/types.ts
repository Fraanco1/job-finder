// Shape of web/public/data/opportunities.json, produced by scraper/jobfinder/pipeline.py.

export type Kind = "job" | "phd" | "postdoc" | "masters" | "internship";

export interface Loc {
  city?: string;
  country?: string;
  country_code?: string;
  lat?: number;
  lon?: number;
  remote?: boolean;
  precision?: "city" | "country";
}

export interface Opportunity {
  id: string;
  source: string;
  url: string;
  title: string;
  org?: string;
  kind: Kind;
  summary?: string;
  locs?: Loc[];
  posted?: string; // ISO dates
  deadline?: string;
  start?: string;
  startText?: string;
  disc: string[]; // discipline ids
  sub?: string[]; // subfield ids
  req?: string[]; // discipline ids whose degree is explicitly required
  edu?: "bachelor" | "masters" | "phd";
  salary?: string;
  contract?: string;
}

export interface Subfield {
  id: string;
  label: string;
}

export interface Discipline {
  id: string;
  label: string;
  subfields: Subfield[];
}

export interface SourceStatus {
  id: string;
  name: string;
  homepage: string;
  ok: boolean;
  count?: number;
  stale?: boolean;
  error?: string;
}

export interface Dataset {
  generated: string;
  taxonomy: Discipline[];
  kinds: { id: Kind; label: string }[];
  sources: SourceStatus[];
  items: Opportunity[];
}
