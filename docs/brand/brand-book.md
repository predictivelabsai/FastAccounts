FastAccounts is open bookkeeping for UK companies and sole traders, Estonian OÜs and FIEs, and the accounting bureaus that keep books for many clients. The brand has one idea: **books that balance**. Accountants draw a double rule under a figure once it is final and checked. The FastAccounts mark is an F standing on that double rule, and the same rule closes every total in the product.

Use this system for the public site (`web/public.py`, `web/design.py`) and the signed-in portal (`static/app.css`, `static/app.js`). Both read the same tokens; the portal adds a dark theme.

## Brand idea

- **Balanced, not flashy.** Confidence comes from exact figures, clear states and calm surfaces. One accent, used where a decision is made.
- **Ledger precision.** Hairlines, aligned numerals and square-ish controls. The double rule (`line-strong`, two 2px rules 3px apart) marks totals, the hero headline and the mark.
- **Two markets, one book.** Copy and examples always cover both the UK (VAT, HMRC, £) and Estonia (KMD, TSD, EMTA, €). Never show one market as the default for the other.

## Voice and copy

- British English: organisation, authorise, colour, licence (noun). Dates as `13 Oct 2026`; money as `€15,613.57` or `£1,240.00`, always two decimals in the portal.
- Plain and specific. Say what the user gets: "Reconcile the bank in one pass", not "Supercharge your finance workflow".
- Address the reader as **you**; FastAccounts speaks as **we** only on trust pages (security, privacy, about).
- Sentence case for headings, buttons and menu items. Uppercase only for `eyebrow` labels.
- Buttons are verbs: "New invoice", "Confirm match", "Export KMD". Toasts confirm in the past tense: "Invoice sent".
- No em dashes, no exclamation marks, no emoji. No invented customers, counts or ratings.
- Estonian copy is first-class, not a translation afterthought: check spelling and compounds before shipping.

## Colour

- **Ledger Violet** (`violet-500`, served as `accent`) is the only brand hue. It fills primary buttons, the active sidebar row and the mark tile. Never use it for status.
- **Ledger Ink** (`ink-950`, served as `ink`) is the brand dark: public nav, footer, dark story sections, portal sidebar and top bar. Text on it is `on-ink` and `on-ink-muted`; accent text on it is `violet-200`.
- Light grounds are `bg` (page) and `surface` (cards). Sunken bands and table heads use `surface-sunken`. Borders are `line`; form controls and the double rule use `line-strong`.
- Body text is `text`; secondary text is `text-muted`; links are `accent-text`.
- Status has its own scale, separate from the brand: `positive` (balanced, paid, reconciled), `warning` (draft, due soon, needs review), `danger` (overdue, failed, unbalanced), `info` (sent, scheduled). Each has a `-soft` ground for pills and banners. Status always carries a word as well as a colour.
- No gradients. The old violet-to-indigo hero gradient is retired. Depth comes from ink sections, the ledger ruling and the product frame.
- Dark theme (portal, and public pages that honour `prefers-color-scheme`): the accent lifts to `violet-400` with `on-accent` turning dark ink. Every pair above holds 4.5:1 in both themes.

## Typography

- **Bricolage Grotesque** (`display`) for headlines, page titles, card headings and headline figures. Weights 700 to 800, tight tracking (`-0.02em` to `-0.035em`), `text-wrap: balance`.
- **Hanken Grotesk** (`body`) for everything else: running text, UI, tables, forms. The portal sets `ui` (14px) as its default; public pages use `body` (16px) and `lead` (19px).
- `mono` (system monospace) only for IBANs, reference numbers and codes.
- Every amount, date column and count uses `font-variant-numeric: tabular-nums`. Amounts align right.
- Both faces are self-hosted from `static/fonts/` with latin and latin-ext subsets, so õ ä ö ü š ž render in the brand face.

## Layout and spacing

- Spacing steps: `space-1` to `space-24`. Portal content padding is `space-8`; cards pad `space-5`; grids gap `space-6`.
- Public content width 1200px with a gutter of `clamp(16px, 4vw, 40px)`; sections pad `space-24` on desktop, `space-16` on phones.
- Portal: 248px ink sidebar, 64px top bar, content on `bg`. Below 900px the sidebar becomes a drawer.
- Text measure 60 to 70 characters.

## Shape, borders and elevation

- One control shape everywhere: `radius-sm` (8px) for buttons, inputs and sidebar rows, on the site and in the portal.
- Cards, tables and empty states: `radius-md` (12px) with a 1px `line` border and no shadow.
- Dialogs, the public product frame and pricing panels: `radius-lg`.
- Pills (`radius-pill`) are reserved for status and the language switch, so a pill always means state.
- Shadows only for things that float: `shadow-md` for menus, `shadow-lg` for dialogs.

## Focus, motion and states

- Focus is a solid 2px ring in `focus` with a 2px offset; on ink surfaces it switches to `on-ink-focus`.
- Hover darkens fills (`accent-hover`) or raises a border to `line-strong`; it never moves layout.
- Motion is 160ms `cubic-bezier(.2,.7,.3,1)` for colour and transform only. Respect `prefers-reduced-motion`.
- Disabled controls drop to 45% opacity and keep their shape.
- Empty states use a 1px dashed `line-strong` border, a heading, one sentence and one action.

## Iconography

- Line icons at 20px, 1.75px stroke, round caps, drawn in `currentColor` inline in `static/app.js`. Keep new icons on the same grid.
- Third-party logos in `static/integrations/` stay as their owners publish them; see `static/integrations/NOTICE.md`.
- No emoji anywhere in the product.

## Logo

- The mark is the F on a double rule inside an 8px-radius tile (`assets/Logos/fastaccounts-mark.svg`). Minimum size 16px; clear space equals the tile radius on all sides.
- Lockup: mark plus "FastAccounts" set live in `display` at weight 800, tracking `-0.03em`, cap height roughly half the mark, gap 10px. Never retype the name in another face or split it ("Fast Accounts").
- On light grounds use the violet mark. On `ink` use the violet mark (it holds 3:1 on ink); use `fastaccounts-mark-dark.svg` in the dark portal theme. One-colour contexts (invoice PDFs, fax-grade prints) use the glyph alone in `ink-950`.
- Do not recolour the tile outside these variants, add effects, or place the mark on photographs.

## Applying it in code

- Public pages: `web/design.py` `DESIGN_CSS` declares the tokens; `web/public.py` builds on them. The per-product override in `accent_style()` stays the single place a sibling FastSME product changes its accent.
- Portal: `static/app.css` declares the same token names on `:root`, a dark block under `@media (prefers-color-scheme: dark)` for `:root:not([data-theme="light"])`, and `:root[data-theme="dark"]` for an explicit choice.
- Favicon and app icons: `static/favicon.svg` is the violet mark.
