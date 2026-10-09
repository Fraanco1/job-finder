import type { Kind } from "./types";

// Order used everywhere: legend, cluster rings, selects.
export const KIND_ORDER: Kind[] = ["phd", "postdoc", "masters", "internship", "job"];

export const KIND_LABEL: Record<Kind, string> = {
  phd: "PhD",
  postdoc: "Postdoc",
  masters: "Master's",
  internship: "Internship",
  job: "Job",
};

// Plural noun phrases for the query sentence.
export const KIND_PHRASE: Record<Kind, string> = {
  phd: "PhD positions",
  postdoc: "postdocs",
  masters: "master's programmes",
  internship: "internships",
  job: "jobs",
};

// CSS custom properties defined in styles.css (light + dark variants).
export const KIND_VAR: Record<Kind, string> = {
  phd: "var(--k-phd)",
  postdoc: "var(--k-postdoc)",
  masters: "var(--k-masters)",
  internship: "var(--k-internship)",
  job: "var(--k-job)",
};

// Concrete colors for map pins (SVG attributes cannot resolve CSS variables).
// Kept in sync with --k-* in styles.css.
export const KIND_HEX: Record<"light" | "dark", Record<Kind, string>> = {
  light: { phd: "#6b3fd4", postdoc: "#0f7c8c", masters: "#b8730c", internship: "#c7366f", job: "#2457c5" },
  dark: { phd: "#a58bff", postdoc: "#3cc3d3", masters: "#f0b13e", internship: "#f06a9e", job: "#6e9bff" },
};
export const PIN_EDGE = { light: "#ffffff", dark: "#0d1626" };
export const INK = { light: "#14213d", dark: "#e6ecf5" };
