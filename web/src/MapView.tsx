import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster";
import { INK, KIND_HEX, KIND_ORDER, KIND_VAR, PIN_EDGE } from "./kinds";
import type { Kind, Opportunity } from "./types";

interface Props {
  items: Opportunity[];
  selectedId: string | null;
  onSelect: (ids: string[]) => void;
  onBounds: (b: L.LatLngBounds) => void;
  dark: boolean;
  /** When this value changes (e.g. a country is picked), zoom to fit the current pins. */
  fitKey?: string;
}

type PinMarker = L.CircleMarker & { options: L.CircleMarkerOptions & { oppId: string; kind: Kind } };

// Esri Canvas basemaps: muted, keyless, and quiet enough for coloured pins to carry the story.
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas";
const BASE = (dark: boolean) => `${ESRI}/World_${dark ? "Dark" : "Light"}_Gray_Base/MapServer/tile/{z}/{y}/{x}`;
const LABELS = (dark: boolean) => `${ESRI}/World_${dark ? "Dark" : "Light"}_Gray_Reference/MapServer/tile/{z}/{y}/{x}`;
const ATTRIBUTION = "Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors";

/** Cluster icon: a ring whose arcs show the mix of opportunity kinds inside. */
function clusterIcon(cluster: L.MarkerCluster): L.DivIcon {
  const counts: Record<string, number> = {};
  const children = cluster.getAllChildMarkers() as unknown as PinMarker[];
  for (const m of children) counts[m.options.kind] = (counts[m.options.kind] ?? 0) + 1;
  const total = children.length;
  let acc = 0;
  const stops: string[] = [];
  for (const k of KIND_ORDER) {
    const c = counts[k];
    if (!c) continue;
    const from = (acc / total) * 360;
    acc += c;
    const to = (acc / total) * 360;
    stops.push(`${KIND_VAR[k]} ${from}deg ${to}deg`);
  }
  const size = total < 10 ? 34 : total < 100 ? 42 : total < 1000 ? 52 : 60;
  const label = total >= 1000 ? `${(total / 1000).toFixed(total >= 10000 ? 0 : 1)}k` : String(total);
  return L.divIcon({
    html: `<div class="cluster" style="--ring: conic-gradient(${stops.join(",")}); width:${size}px; height:${size}px"><span>${label}</span></div>`,
    className: "cluster-wrap",
    iconSize: L.point(size, size),
  });
}

export default function MapView({ items, selectedId, onSelect, onBounds, dark, fitKey }: Props) {
  const theme = dark ? "dark" : "light";
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const tiles = useRef<L.LayerGroup | null>(null);
  const group = useRef<L.MarkerClusterGroup | null>(null);
  const byId = useRef(new Map<string, PinMarker[]>());
  const highlight = useRef<L.CircleMarker | null>(null);
  const cb = useRef({ onSelect, onBounds });
  cb.current = { onSelect, onBounds };

  // Create the map once.
  useEffect(() => {
    if (!el.current || map.current) return;
    const m = L.map(el.current, {
      center: [30, 5],
      zoom: 2,
      minZoom: 2,
      maxZoom: 16,
      worldCopyJump: true,
      zoomControl: false,
    });
    L.control.zoom({ position: "bottomright" }).addTo(m);
    const g = L.markerClusterGroup({
      chunkedLoading: true,
      showCoverageOnHover: false,
      spiderfyOnMaxZoom: false,
      zoomToBoundsOnClick: false,
      maxClusterRadius: 48,
      iconCreateFunction: clusterIcon,
    });
    g.on("clusterclick", (e: L.LeafletEvent) => {
      const c = (e as unknown as { layer: L.MarkerCluster }).layer;
      const kids = c.getAllChildMarkers() as unknown as PinMarker[];
      const first = kids[0].getLatLng();
      const samePlace = kids.every((k) => k.getLatLng().equals(first, 1e-4));
      if (samePlace || m.getZoom() >= m.getMaxZoom() - 1) {
        // One institution / city: list everything there instead of zooming forever.
        cb.current.onSelect(kids.map((k) => k.options.oppId));
      } else {
        c.zoomToBounds({ padding: [40, 40] });
      }
    });
    m.addLayer(g);
    const report = () => cb.current.onBounds(m.getBounds());
    m.on("moveend", report);
    map.current = m;
    group.current = g;
    report();
    return () => {
      m.remove();
      map.current = null;
    };
  }, []);

  // Basemap follows the color scheme.
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    tiles.current?.remove();
    const layer = L.layerGroup([
      L.tileLayer(BASE(dark), { attribution: ATTRIBUTION, maxZoom: 16 }),
      L.tileLayer(LABELS(dark), { maxZoom: 16, pane: "overlayPane" }),
    ]);
    layer.addTo(m);
    tiles.current = layer;
  }, [dark]);

  // Rebuild markers when the filtered set changes.
  useEffect(() => {
    const g = group.current;
    if (!g) return;
    g.clearLayers();
    byId.current.clear();
    const markers: PinMarker[] = [];
    for (const o of items) {
      for (const loc of o.locs ?? []) {
        if (loc.lat == null || loc.lon == null) continue;
        const mk = L.circleMarker([loc.lat, loc.lon], {
          radius: loc.precision === "country" ? 5 : 6,
          weight: 1.5,
          color: PIN_EDGE[theme],
          fillColor: KIND_HEX[theme][o.kind],
          fillOpacity: loc.precision === "country" ? 0.55 : 0.95,
          dashArray: loc.precision === "country" ? "2 2" : undefined,
          oppId: o.id,
          kind: o.kind,
        } as L.CircleMarkerOptions) as PinMarker;
        mk.on("click", () => cb.current.onSelect([o.id]));
        mk.bindTooltip(o.title.length > 80 ? o.title.slice(0, 78) + "…" : o.title, {
          direction: "top",
          offset: [0, -6],
          className: "pin-tip",
        });
        markers.push(mk);
        const list = byId.current.get(o.id) ?? [];
        list.push(mk);
        byId.current.set(o.id, list);
      }
    }
    g.addLayers(markers);
    if (pendingFit.current) {
      pendingFit.current = false;
      fitToPins();
    }
  }, [items, theme]);

  // Zoom to the pins when the fit key changes; back to the world view when it is cleared.
  // Filtering is deferred, so the fit stays pending until the next marker rebuild (or 1.5 s).
  const lastFit = useRef(fitKey);
  const pendingFit = useRef(false);
  const fitToPins = () => {
    const m = map.current;
    const b = group.current?.getBounds();
    if (m && b?.isValid()) m.fitBounds(b, { padding: [40, 40], maxZoom: 8 });
  };
  useEffect(() => {
    const m = map.current;
    if (!m || lastFit.current === fitKey) return;
    lastFit.current = fitKey;
    if (!fitKey) {
      pendingFit.current = false;
      m.setView([30, 5], 2);
      return;
    }
    fitToPins();
    pendingFit.current = true;
    const t = setTimeout(() => (pendingFit.current = false), 1500);
    return () => clearTimeout(t);
  }, [fitKey]);

  // Halo around the selected opportunity, and pan to it if it is off-screen.
  useEffect(() => {
    const m = map.current;
    highlight.current?.remove();
    highlight.current = null;
    if (!m || !selectedId) return;
    const mk = byId.current.get(selectedId)?.[0];
    if (!mk) return;
    const ll = mk.getLatLng();
    highlight.current = L.circleMarker(ll, {
      radius: 14,
      weight: 2.5,
      color: INK[theme],
      fill: false,
      interactive: false,
      className: "halo",
    }).addTo(m);
    if (!m.getBounds().contains(ll)) m.panTo(ll);
  }, [selectedId, items, theme]);

  return <div ref={el} className="map" role="application" aria-label="Map of opportunities" />;
}
