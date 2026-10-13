# FastAccounts brand system

- [brand-book.md](brand-book.md): colour, typography, shape, logo and voice rules.
- [tokens.json](tokens.json): canonical palette, semantic light/dark values,
  fonts, spacing, radii and shadows, with usage notes.
- [components-reference.css](components-reference.css): exact component values
  for implementation reference. Do not load this file as an application stylesheet.
- [static/brand](../../static/brand): primary, dark and single-colour marks,
  plus ink and white glyphs. `static/favicon.svg` matches the primary mark.

Runtime tokens live in `web/design.py` (`DESIGN_CSS`) and `static/app.css`.
Keep both aligned with `tokens.json`. Public components live in `web/design.py`
and `web/public.py`; portal components live in `static/app.css` and `static/app.js`.
Both shells load the self-hosted faces through `/static/fonts/fonts.css`.
Sibling products set their accents and mark path through `Product` and `accent_style()`.

Bare `:root` supplies light values. System dark mode uses
`@media (prefers-color-scheme: dark)` with `:root:not([data-theme="light"])`.
An explicit `:root[data-theme="dark"]` supplies the same dark values;
`data-theme="light"` overrides system dark mode. Ink sections keep their
ink ground and on-ink foreground in both themes.

The canonical design system lives in [Claude Design](https://claude.ai/artifact/SmN1YDB3mhQpo9byF2B1sM).
