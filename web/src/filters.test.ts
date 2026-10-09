import { describe, expect, it } from "vitest";
import { dateCompatible, defaultFilters, filtersFromQuery, filtersToQuery, matches } from "./filters";
import type { Opportunity } from "./types";

const TODAY = "2026-10-09";
const base: Opportunity = {
  id: "x",
  source: "test",
  url: "https://example.org",
  title: "PhD position in quantum computing",
  kind: "phd",
  disc: ["physics"],
  sub: ["quantum-computing"],
  req: ["physics"],
};

const f = (over: Partial<ReturnType<typeof defaultFilters>> = {}) => ({
  ...defaultFilters(),
  available: TODAY,
  ...over,
});

describe("dateCompatible", () => {
  it("keeps postings whose deadline is after the availability date", () => {
    expect(dateCompatible({ ...base, deadline: "2027-01-31" }, f({ available: "2027-01-01" }), TODAY)).toBe(true);
  });

  it("drops postings whose deadline is before the availability date", () => {
    expect(dateCompatible({ ...base, deadline: "2026-12-01" }, f({ available: "2027-01-01" }), TODAY)).toBe(false);
  });

  it("never shows expired deadlines", () => {
    expect(dateCompatible({ ...base, deadline: "2026-10-01" }, f(), TODAY)).toBe(false);
  });

  it("keeps unknown deadlines unless a deadline is required", () => {
    expect(dateCompatible(base, f(), TODAY)).toBe(true);
    expect(dateCompatible(base, f({ requireDeadline: true }), TODAY)).toBe(false);
  });

  it("drops start dates before availability minus flexibility", () => {
    const o = { ...base, start: "2027-02-01" };
    expect(dateCompatible(o, f({ available: "2027-03-01", flex: 0 }), TODAY)).toBe(false);
    expect(dateCompatible(o, f({ available: "2027-03-01", flex: 30 }), TODAY)).toBe(true);
    expect(dateCompatible(o, f({ available: "2027-01-15", flex: 0 }), TODAY)).toBe(true);
  });
});

describe("matches", () => {
  it("filters by required background", () => {
    expect(matches(base, f({ background: "physics" }), TODAY)).toBe(true);
    expect(matches(base, f({ background: "chemistry" }), TODAY)).toBe(false);
  });

  it("filters by kind and subfield", () => {
    expect(matches(base, f({ kinds: ["postdoc"] }), TODAY)).toBe(false);
    expect(matches(base, f({ discipline: "physics", subfields: ["condensed-matter"] }), TODAY)).toBe(false);
    expect(matches(base, f({ discipline: "physics", subfields: ["quantum-computing"] }), TODAY)).toBe(true);
  });

  it("searches accent-insensitively across words", () => {
    const o = { ...base, locs: [{ city: "Zürich", country: "Switzerland" }] };
    expect(matches(o, f({ q: "zurich quantum" }), TODAY)).toBe(true);
    expect(matches(o, f({ q: "zurich chemistry" }), TODAY)).toBe(false);
  });
});

describe("url state", () => {
  it("round-trips filters", () => {
    const g = { ...defaultFilters(), kinds: ["phd" as const], discipline: "physics", subfields: ["nanoscience"], background: "physics", flex: 0, q: "graphene" };
    expect(filtersFromQuery(filtersToQuery(g))).toEqual(g);
  });
});
