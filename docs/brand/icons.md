# FastAccounts icons

One line icon set for the site and the portal. The canonical paths live in
`static/app.js` (`ICONS`, with `NAV_ICONS` mapping each sidebar view to its icon).
`web/design.py` (`ICON_PATHS`, `fs_icon()`) carries the subset the server renders;
`tests/test_icons.py` keeps the two in step.

## Drawing rules

- 24px grid, live area 3 to 21px. Stroke 1.75px, round caps, round joins, no fills.
- Draw in `currentColor`, so an icon takes the colour of its text: `on-ink` in the
  sidebar, `text-muted` for neutral marks, `accent-text` for positive brand marks,
  `positive` for a tick in a table cell.
- Render at 18px in the sidebar, 20px inline, 30px in empty states. Never below 16px.
- Icons are decorative (`aria-hidden="true"`). The label next to them, or an
  `aria-label` on the parent, carries the meaning.
- No emoji or text characters (☰ ✓ ✗ ↗) as icons.
- Every sidebar destination has its own drawing; two destinations never share one.

## The set

| Icon | Used for |
| --- | --- |
| `home` | Overview |
| `invoice` | Invoices |
| `quote` | Quotes |
| `bill` | Bills (receipt edge) |
| `periodised` | Periodised (calendar with a spread arrow) |
| `contacts` | Contacts |
| `recurring` | Recurring and reminders |
| `bank` | Banking, open banking |
| `ledger` | Accounting: a balance scale, the brand idea of books that balance |
| `cash-flow` | Cash-flow statement |
| `asset` | Fixed assets |
| `tax` | Tax |
| `payroll` | Payroll (banknote) |
| `link` | Integrations |
| `import` | Data import, employee file import |
| `card` | Payment methods |
| `bell` | Reminder rules |
| `exchange` | Exchange rates |
| `tag` | Objects (analytical dimensions) |
| `appearance` | Document appearance |
| `document` | Generic record, empty states |
| `plus`, `close`, `menu`, `chevron-down` | Interface controls |
| `external` | Links that open another site |
| `shield` | Two-factor authentication |
| `check` | Confirmed or enabled values |

## Integration tiles

`static/integrations/` holds 64px tiles. Official logos (QuickBooks, Xero, Merit Aktiva)
keep their artwork and are only minified; Merit gets a light plate in dark mode.
Every other tile is FastAccounts-made:

- Third-party placeholders: neutral `surface-sunken` tile, `line` border, initials in
  `ink-950`. They never use the brand violet.
- FastHR (sibling product): ink tile with light initials.
- FastAccounts connectors (file import, open banking, e-invoice): `accent-soft` tile with
  the matching line icon in `violet-600`.
- Lettering is Bricolage Grotesque Bold converted to outlines, so it renders the same
  in every browser. See `static/integrations/NOTICE.md` for sources.

## App icons

`static/favicon.svg` is the primary mark. `static/brand/apple-touch-icon.png` (180px,
full-bleed violet so iOS can round it) is linked from public and portal pages.
