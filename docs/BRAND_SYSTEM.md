# BRAND_SYSTEM — PROSPERYA CRM

Design tokens and component specifications for the Prosperya design system. Canonical implementation: `frontend/src/design-system/tokens.css`. Token names here are the contract — implementations must use them verbatim.

## 1. Source findings (prosperya.it)

| Element | Value |
|---|---|
| Heading font | **Playfair Display** (serif) |
| Body font | **DM Sans** |
| Dark surfaces | `#090d0e` `#111a1c` `#172326` `#1d2c2f` `#213236` |
| Petrol accent | `#315f67` |
| Champagne | `#c9b991` |
| Ivory | `#eee9df` / `#e7e1d7` |
| Logo | Ring of 10 colored nodes around a "P" — *"10 leve · una regia"* |
| Node colors | `#F6C515` amber · `#55B57A` green · `#2C83C7` blue · `#D42375` magenta · `#FF7A1A` orange |

The marketing site is dark and cinematic. **A CRM is an all-day tool** — we translate, not copy: light warm-ivory working surfaces, the site's darkest petrol tone (`#172326`) as the persistent sidebar, petrol as the primary action color, champagne reserved for accents and highlights.

## 2. Color tokens

### Surfaces & ink

```css
--pys-surface-0:       #faf7f0;  /* page background — warm ivory            */
--pys-surface-1:       #fffdf8;  /* cards, panels                           */
--pys-surface-2:       #f1ede4;  /* subtle fill, table striping, wells      */
--pys-surface-3:       #e7e1d7;  /* borders-strong, disabled fill (ivory dk)*/
--pys-surface-inverse: #172326;  /* sidebar, dark overlays                  */
--pys-surface-inverse-2:#1d2c2f; /* sidebar hover/active                    */

--pys-ink-0:    #eee9df;         /* text on dark surfaces                   */
--pys-ink-300:  #9aa5a3;         /* disabled, placeholders                  */
--pys-ink-500:  #5d6b69;         /* secondary text                          */
--pys-ink-700:  #37444a;         /* body-strong                             */
--pys-ink-900:  #172326;         /* headings, primary text                  */

--pys-border:   #ddd6c8;         /* default 1px borders                     */
--pys-border-strong: #c9c1af;
```

### Primary — petrol scale (brand anchor `#315f67` at 600)

```css
--pys-primary-50:  #eef4f4;
--pys-primary-100: #d8e6e6;
--pys-primary-200: #b3ccce;
--pys-primary-300: #84abae;
--pys-primary-400: #578488;
--pys-primary-500: #3d6e72;
--pys-primary-600: #315f67;   /* DEFAULT primary — buttons, links-strong */
--pys-primary-700: #274d54;
--pys-primary-800: #1d3a40;
--pys-primary-900: #172326;   /* = surface-inverse                         */
```

### Accent — champagne scale (`#c9b991` at 500)

```css
--pys-accent-50:  #f8f5ec;
--pys-accent-100: #f0e9d7;
--pys-accent-200: #e4d9bc;
--pys-accent-300: #d8caa4;
--pys-accent-400: #cfc09a;
--pys-accent-500: #c9b991;   /* DEFAULT accent — highlights, badges, focus-alt */
--pys-accent-600: #a5956f;
--pys-accent-700: #7e7050;   /* min. champagne tone for text on ivory (AA)    */
--pys-accent-800: #5d513a;
--pys-accent-900: #40382a;
```

Rule: champagne is an **accent**, never a text-on-light color below 700, never a primary action.

### Semantic (all verified ≥ 4.5:1 on `--pys-surface-0` for text roles)

```css
--pys-success-600: #2e7d52;  --pys-success-50: #e9f4ee;  /* ok / won       */
--pys-warning-600: #9a6b08;  --pys-warning-50: #faf1dc;  /* risk / due-soon*/
--pys-danger-600:  #b3382e;  --pys-danger-50:  #fbeae8;  /* error / lost   */
--pys-info-600:    #2c6fa8;  --pys-info-50:    #e8f1f8;  /* info / open    */
```

Status-color semantics are fixed (`UX_RULES.md` §5): success=won/done, warning=at-risk/due-soon, danger=overdue/lost/error, info=open/neutral.

### Chart / categorical palette (from the 10 logo nodes)

```css
--pys-chart-1: #F6C515;  --pys-chart-2: #55B57A;  --pys-chart-3: #2C83C7;
--pys-chart-4: #D42375;  --pys-chart-5: #FF7A1A;  --pys-chart-6: #315f67;
--pys-chart-7: #8a7a4e;  --pys-chart-8: #5d6b69;  --pys-chart-9: #a35ba0;
--pys-chart-10: #4d8a96;
```

Use for pipeline stages, service-line charts, dashboard series. Charts only — never for semantic status.

## 3. Typography

```css
--pys-font-display: 'Playfair Display', Georgia, serif;
--pys-font-body:    'DM Sans', system-ui, sans-serif;

--pys-text-xs:   12px;   /* meta, table secondary          */
--pys-text-sm:   13px;   /* dense table body               */
--pys-text-base: 14px;   /* default UI text                */
--pys-text-md:   16px;   /* emphasized body                */
--pys-text-lg:   18px;   /* section titles                 */
--pys-text-xl:   20px;   /* card headers                   */
--pys-text-2xl:  24px;   /* page titles                    */
--pys-text-3xl:  30px;   /* page titles (display font)     */
--pys-text-4xl:  36px;   /* hero only — rare in CRM        */
```

Rules: **Playfair Display for page titles only** (`--pys-text-2xl`+ on record/list pages). Everything else — including all component labels, table headers, buttons — is DM Sans. Base density is 14px; 13px in dense tables.

## 4. Spacing, radius, shadow, focus

```css
/* 4px base scale */
--pys-space-1: 4px;  --pys-space-2: 8px;   --pys-space-3: 12px;
--pys-space-4: 16px; --pys-space-5: 20px;  --pys-space-6: 24px;
--pys-space-8: 32px; --pys-space-10: 40px; --pys-space-12: 48px;

--pys-radius-sm: 4px;    /* inputs, small chips   */
--pys-radius-md: 8px;    /* buttons, cards        */
--pys-radius-lg: 12px;   /* modals, panels        */
--pys-radius-pill: 999px;/* badges, status chips  */

--pys-shadow-sm: 0 1px 2px rgba(23,35,38,.08);
--pys-shadow-md: 0 4px 12px rgba(23,35,38,.10);
--pys-shadow-lg: 0 12px 32px rgba(23,35,38,.16);

--pys-focus-ring: 0 0 0 3px rgba(49,95,103,.35);   /* visible on every surface */
```

## 5. Component specs

| Component | Spec |
|---|---|
| **Button/primary** | bg `--pys-primary-600`, hover `-700`, active `-800`, text `--pys-ink-0`, radius-md, height 36px (32px `dense` variant in tables), focus `--pys-focus-ring` |
| **Button/secondary** | bg `--pys-surface-1`, 1px `--pys-border`, text `--pys-ink-900`, hover surface-2 |
| **Button/ghost** | transparent, text `--pys-primary-600`, hover primary-50 |
| **Button/danger** | bg `--pys-danger-600`; destructive actions always confirm |
| **Input/select/textarea** | surface-1, 1px `--pys-border`, radius-sm, height 36px, focus: border primary-600 + focus-ring; invalid: danger-600 border + `--pys-danger-600` helper text |
| **Table** | header surface-2, text-sm uppercase-eyebrow ink-500; rows 40px default / 32px dense; zebra striping surface-2 on hover only; row border `--pys-border`; selected row primary-50 |
| **Card / record section** | surface-1, radius-md, shadow-sm, padding `--pys-space-5`; section title text-lg DM Sans (not Playfair) |
| **Alert** | surface = semantic-50, left border 3px semantic-600, icon + text semantic-600 (≥AA); dismissible unless `critical` |
| **Badge/status chip** | radius-pill, semantic-50 bg + semantic-600 text; never color-only — always icon or text label |
| **Sidebar** | `--pys-surface-inverse` bg, ink-0 text at 70% opacity, active item primary-400 left-bar + inverse-2 bg; logo mark top |
| **Page title** | Playfair Display `--pys-text-3xl`, ink-900, optional champagne keyline under — only on top-level pages |

## 6. Do / Don't

**Do** — use ivory surfaces for warmth; keep petrol for one primary action per view; use champagne to highlight (totals, key dates, active nav); respect semantic status colors everywhere; hit ≥ 4.5:1 contrast (AA) for all text.

**Don't** — put Playfair Display on buttons/labels/body; use champagne as primary CTA or as light-surface text below accent-700; use node/chart colors for status semantics; mix radius scales in one component; introduce any hex not registered in `tokens.css`; build a dark-mode theme for Phase 0–5 (the dark sidebar is the only dark surface).
