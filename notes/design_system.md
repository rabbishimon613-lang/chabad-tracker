# Design system — Chabad Tracker (Layer 4)

Project codename: **THE WIRE**. Anti-vibecoded surveillance-console aesthetic.
Reference: Liveuamap × Palantir Gotham × US federal-government (USWDS) typography.

This is the canonical reference. Every component, every fleet call, must conform.
Do not invent new colors, fonts, sizes, or border styles outside these tables.

## Palette — 6 colors only

| Token       | Hex      | Use |
|-------------|----------|-----|
| `--bg`      | `#0A0B0D` | Page background. Near-black with a 1-2pt cold blue tint. |
| `--surface` | `#14161A` | Panel / card backgrounds. |
| `--line`    | `#1F232A` | Borders, dividers, table rules. 1px solid. |
| `--text`    | `#E6E4DC` | Primary text. Bone, slightly warm — avoids clinical pure white. |
| `--mute`    | `#6E737A` | Secondary text, IDs, meta. |
| `--accent`  | `#E03E3E` | Single accent. Severity-red. Selected state. Active filter. |

### Severity ramp (uses 3 named tokens, NOT opacity)

| Band     | Token            | Hex      |
|----------|------------------|----------|
| black    | `--sev-clean`    | `--surface` (#14161A) — invisible against bg |
| yellow   | `--sev-low`      | `#C8A93E` (muted amber, not cheerful yellow) |
| orange   | `--sev-mid`      | `#D26C2B` |
| red      | `--sev-high`     | `--accent` (#E03E3E) |

No other colors. No gradients. No semi-transparent overlays beyond 4–8% black/white tints when strictly needed for hover states.

## Typography — 2 families

| Role | Family | Source | Use |
|------|--------|--------|-----|
| Mono | **IBM Plex Mono** | Google Fonts (free) | ALL labels, IDs, navigation, filters, status bar, numbers, code. |
| Sans | **Public Sans** | Google Fonts / USWDS (free) | Dossier body copy, long-form incident summaries. |

Public Sans is chosen for its US-government / official-system register. It signals "system of record," not "consumer app."

**Never** use: Inter, Manrope, Geist, system-ui, Helvetica, Arial.

### Scale (px)

| Token | Px | Use |
|-------|----|-----|
| `--fs-xs`  | 11 | Status bar, IDs, source URLs |
| `--fs-sm`  | 13 | Filter labels, table cells, meta lines |
| `--fs-base`| 15 | Default body. Dossier summary. |
| `--fs-lg`  | 18 | Entity name, section headings |
| `--fs-xl`  | 24 | Map title overlay, dossier hero |
| `--fs-xxl` | 40 | Splash numbers if any (counters in status bar) |

Line-height: 1.25 for mono, 1.45 for sans.

Font-weight: only **400** and **500** for sans; only **400** and **600** for mono. No 700+.

Letter-spacing: 0 for sans; `0.02em` for mono labels.

## Spacing — 4px base unit

`4 / 8 / 12 / 16 / 24 / 32 / 48`. Every margin/padding/gap MUST come from this scale.
No `gap: 13px`. No `margin-top: 7px`. Period.

## Borders

- 1px solid `--line`. That's it.
- **No border-radius.** Anywhere. Sharp corners on every element.
- Inset elements use `border-top` only (separator pattern).

## Components — visual rules

- **Hover state**: subtle inversion or 1px `--accent` border. NO lift, NO shadow, NO scale.
- **Active/selected**: 1px `--accent` border + accent-tinted background `rgba(224,62,62,0.05)`.
- **Focus**: 1px `--accent` outline, offset 0.
- **Loading**: monospace block-character progress (`▓▓▓▒░░`) or a static cursor `█`. NEVER spinners.
- **Empty states**: monospace placeholder text in `--mute`. Optional ASCII frame.

## Animation

- Default: instant. No animation.
- When needed (sheet slide, filter toggle): `100ms` duration, `cubic-bezier(0.2, 0, 0.2, 1)`, transform-only.
- No fade-in. No stagger. No spring physics.

## Anti-vibecode hard rules

The following are banned on sight:

1. `border-radius` > 0 anywhere
2. `backdrop-filter`, `filter: blur()`
3. Any `linear-gradient`, `radial-gradient`
4. Tailwind utility classes (we're hand-writing CSS)
5. shadcn/ui components, Radix UI default styling
6. Inter, system-ui, Helvetica, Arial in any font-stack
7. Emoji anywhere in the UI
8. Heroicons / Lucide / Feather icons — all custom SVG glyphs
9. "Hero" sections with centered marketing text
10. Gradient backgrounds
11. `box-shadow` other than 0 or for keyboard focus
12. Carousels, accordions with bounce, stagger animations

## Anti-vibecode positive rules

These tells should be visible at first paint:

1. **Numeric entity IDs visible always.** `#4172488` next to the name.
2. **Monospace dominates** the chrome — only the dossier body breathes in sans.
3. **Density on first paint** — 4 panels visible (map, filters, dossier, status). No splash.
4. **Status bar persistent** along bottom: `4173 entities · 126 incidents · 837 families · UTC 2026-06-06 14:23Z`
5. **Source URLs shown raw, inline.** No "Read more" buttons. No expand-collapse.
6. **5-bar meter** for severity. Not a colored pill.
7. **Pixel grid alignment.** 4px units. Visible discipline.
8. **No splash, no marketing, no "About"** — landing screen IS the tool.

## Cursor

`cursor: crosshair` over the map. `cursor: pointer` for clickable rows. Default elsewhere.

## Reference snapshots to mimic the feel of

- Palantir Gotham product walkthrough screencaps
- Liveuamap.com after dark — its top bar discipline
- TweetDeck classic column dividers
- Linear's monospace mix (but not its rounded corners)
- White House USWDS components (the type, not the color)
- **Citizen app dark mode** — bottom sheet motion + incident card density
- **Apple Maps bottom sheet** — multi-detent (peek / half / full) sheet behavior

## Mobile-first — most users are on phones

Mobile is the primary surface. Desktop is the same shell with extra panels exposed.

### Breakpoints

| Token         | Min width | Behavior |
|---------------|-----------|----------|
| `--bp-phone`  | 0         | Default. Single column. Bottom-sheet pattern. |
| `--bp-tablet` | 768px     | Bottom sheet becomes a right rail (320px). |
| `--bp-desk`   | 1200px    | Full Wire workstation — left filter rail + right dossier + bottom timeline strip. |

### Mobile layout — Citizen-style

```
┌──────────────────────────────────┐
│ ◀ search · filters · status (≡)  │  44pt height. Mono. Sticky.
├──────────────────────────────────┤
│                                  │
│             MAP                  │  fills the rest minus sheet
│         (4173 dots)              │  pinch-zoom, pan, tap a dot
│                                  │
│                                  │
├──────────────────────────────────┤
│ ━━━━━━ (drag handle)             │  bottom sheet, 3 detents:
│ 126 incidents · 837 families     │   peek (88pt) / half (40%) / full (88%)
│ … list scroll …                  │  peek = status counter only
└──────────────────────────────────┘     half = incident list
                                         full = entity dossier
```

### Touch targets

- Minimum tap area: **44 × 44 pt** (iOS HIG). Pad small icons up to this.
- Drag handles: 36pt wide, 4pt tall, `--mute` color, centered above sheet content.
- Map dots: minimum visible radius 6pt; hit target 12pt expanded around small dots.

### Typography — mobile overrides

Scale up by ~2px on phone to maintain legibility:

| Token       | Phone | Tablet+ |
|-------------|-------|---------|
| `--fs-xs`   | 12    | 11      |
| `--fs-sm`   | 14    | 13      |
| `--fs-base` | 16    | 15      |
| `--fs-lg`   | 20    | 18      |

Mono labels stay legible — never under 12px on phone.

### Gestures

- Bottom sheet: drag handle or anywhere on the sheet header zone → drag to resize between detents. Use CSS `touch-action: pan-y`.
- Map: native MapLibre pinch / pan. No custom gestures interfering.
- No long-press menus, no double-tap actions (collide with map zoom).
- Sheet dismiss: drag to bottom edge OR tap on the map area.

### Safe areas

- Respect `env(safe-area-inset-bottom)` for the persistent status row.
- Top bar respects `env(safe-area-inset-top)` for notched devices.

### Performance notes (mobile-critical)

- DB ships at 4.7 MB — acceptable for one-time load. Show monospace progress bar during fetch.
- All 4,173 dots render via MapLibre's `circle` layer in WebGL. Never DOM.
- Bottom-sheet list virtualized — only render rows in view.
- Network arc overlay (deck.gl) is **opt-in** on mobile (battery / GPU cost).
