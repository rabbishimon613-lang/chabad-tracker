# Architecture — Chabad Tracker UI (Layer 4)

## Stack

- **Build**: Vite + TypeScript. No framework. Web Components (custom elements).
- **Map**: MapLibre GL JS (free, no Mapbox account).
- **Network graph**: deck.gl `ArcLayer` for house-to-house arcs on map; `react-force-graph` *only* if/when we add a dedicated family graph view.
- **Data**: `sql.js` (SQLite compiled to WASM). The whole `chabad.db` ships as a static asset. Browser queries it directly. **No backend.** This is a load-bearing aesthetic choice — the user can `curl` the DB and own it.
- **Hosting**: any static host (Cloudflare Pages default).

## File tree

```
ui/
├── index.html                   single page, mounts the app
├── package.json
├── vite.config.ts
├── public/
│   ├── chabad.db                ← VACUUMed copy of data/chabad.db
│   └── fonts/                   ← Plex Mono + Public Sans woff2
├── map/
│   └── style.json               ← MapLibre style (fleet-generated)
└── src/
    ├── main.ts                  ← bootstraps app, initializes sql.js, wires events
    ├── style.css                ← CSS variables from design_system.md + global rules
    ├── data/
    │   ├── db.ts                ← sql.js init + query helpers
    │   └── queries.ts           ← named queries against the 4 analytic views
    └── components/              ← Web Components, one file each
        ├── dot-map.ts           ← MapLibre wrapper, emits 'house-selected'
        ├── bottom-sheet.ts      ← mobile-first sheet with 3 detents (peek/half/full)
        ├── dossier-sheet.ts     ← desktop right-slide panel + mobile full-sheet variant
        ├── timeline-density.ts  ← bottom hairline density chart (desktop only; in sheet on mobile)
        ├── entity-search.ts     ← top-bar search
        ├── filter-rail.ts       ← desktop left column / mobile filters sheet
        ├── status-bar.ts        ← persistent bottom strip (desktop) / peek-row of sheet (mobile)
        └── network-arcs.ts      ← deck.gl arc overlay (toggleable; opt-in on mobile)
```

## Data flow

1. On boot, `main.ts` fetches `/chabad.db`, hands to `db.ts` which initializes `sql.js`.
2. Each component receives a reference to the DB via constructor or attribute.
3. Components query via named functions in `queries.ts`:
   - `getHouseSummary()` → all houses for the map dots
   - `getDossier(id, kind)` → for the right sheet
   - `getFamilyNetwork(surname)` → for arc overlay
   - `getIncidentsByYear()` → for timeline
   - `searchEntities(text)` → for top-bar search
4. Cross-component coordination via `CustomEvent` dispatched on `window`:
   - `house-selected` (detail: { house_id })
   - `filter-changed` (detail: { types: [], severity_min, year_range })
   - `entity-search-pick` (detail: { kind, id })
5. No global state library. Just events + targeted DOM updates per component.

## Why Web Components

- Native, no framework lock-in.
- Custom-element naming reinforces the "system of record" register (`<dot-map>` over `<DotMap>`).
- Each component file is self-contained; perfect fleet-implementation unit.
- No build-time JSX, no React hooks, no useEffect spaghetti. Plain DOM.

## Build & run

```
cd ui
npm install
npm run dev      # dev server on localhost:5173
npm run build    # produces ui/dist/ — fully static
```

The DB asset (`public/chabad.db`) is copied as-is. Refresh script:

```
sqlite3 data/chabad.db "VACUUM INTO 'ui/public/chabad.db'"
```

Run this after any incident load to ship a fresh snapshot.

## What we do NOT do

- No SSR. No hydration. No backend API.
- No React, Vue, Svelte, Solid.
- No state management library.
- No routing library — single page, no routes.
- No auth, no users, no accounts.
- No analytics SDK on the user-facing build.

## Browser support

Modern only: Chrome/Firefox/Safari last-2-versions on desktop. **iOS Safari 16+ and Chrome Android 110+ on mobile** are first-class targets — most users are on phones. We use WebAssembly, ES modules, CSS custom properties, Web Components. No polyfills.

## Mobile-first layout — the dominant shell

The single-column phone shell is the canonical layout. Tablets and desktop are progressive enhancements that expose more panels at once via media queries.

- **Phone** (default): map fills viewport, persistent top bar (44pt), `<bottom-sheet>` overlays at 3 detents.
- **Tablet** (≥768px): bottom sheet becomes a right rail (320px); top bar gains filter chips.
- **Desktop** (≥1200px): left filter rail + right dossier rail + bottom timeline strip (the Wire workstation).

All components must be implemented mobile-first. A component is "done" only when it passes inspection on a 375×812 viewport.
