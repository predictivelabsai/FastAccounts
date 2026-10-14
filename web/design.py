"""FastSME design system - tokens, fonts and reusable public-page primitives."""
from __future__ import annotations

from dataclasses import dataclass

from fasthtml.common import *

from .assets import STATIC_DIR, asset_url
from . import i18n


@dataclass(frozen=True)
class Product:
    """One FastSME product's identity for public pages."""
    name: str = "FastAccounts"
    accent: str = "#7c3aed"          # violet - primary actions and highlights
    accent_strong: str = "#6526d6"   # deep violet - links/hover on light grounds
    tagline: str = ""
    suite_url: str = "https://fastsme.com/products"
    github_url: str = "https://github.com/predictivelabsai/FastAccounts"
    mark_src: str = "/static/brand/fastaccounts-mark.svg"
    mark: str = "F"                  # short brand mark glyph


FASTPRODUCT = Product(tagline=i18n.t("footer.tagline"))


# Bricolage Grotesque (display) + Hanken Grotesk (body). Both carry the Estonian
# glyph set (õ ä ö ü š ž) via Google's latin-ext unicode ranges.
FONT_LINKS = (
    Link(rel="preload", href="/static/fonts/bricolagegrotesque-latin.woff2",
         **{"as": "font"}, type="font/woff2", crossorigin=""),
    Link(rel="preload", href="/static/fonts/hankengrotesk-latin.woff2",
         **{"as": "font"}, type="font/woff2", crossorigin=""),
    Link(rel="stylesheet", href=asset_url("fonts/fonts.css")),
)


DESIGN_CSS = (STATIC_DIR / "design.css").read_text(encoding="utf-8")


def accent_style(product: Product) -> Style:
    """Per-product accent override - the only thing that changes between products."""
    if product.accent == "#7c3aed" and product.accent_strong == "#6526d6":
        return Style("")  # The canonical theme already supplies both accent pairs.
    return Style(
        f':root,:root:not([data-theme="light"]),:root[data-theme="dark"]'
        f"{{--accent:{product.accent};--accent-hover:{product.accent_strong};"
        f"--accent-text:{product.accent_strong};--on-accent:#ffffff;}}"
    )


# Server-rendered subset of the FastAccounts line icons (static/app.js ICONS holds the
# full set): 24px grid, 1.75 stroke, round caps and joins, drawn in currentColor.
ICON_PATHS = {
    "check": "M5 12.5l4.5 4.5L19 7.5",
    "close": "M6 6l12 12 M18 6 6 18",
    "menu": "M4 7h16 M4 12h16 M4 17h16",
    "external": "M13.5 4H20v6.5 M20 4l-9 9 M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
}


def fs_icon(name: str, cls: str = "fs-icon"):
    """Decorative inline icon; pair it with visible text or an aria-label on the parent."""
    return NotStr(
        f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
        f'<path d="{ICON_PATHS[name]}"/></svg>'
    )


def fs_eyebrow(text: str, on_ink: bool = False):
    return Span(text, cls="fs-eyebrow on-ink" if on_ink else "fs-eyebrow")


def fs_button(label, href=None, variant="ink", size="", onclick=None, **kw):
    cls = f"fs-btn fs-btn-{variant}" + (f" fs-btn-{size}" if size else "")
    if href is not None:
        return A(label, href=href, cls=cls, **kw)
    return Button(label, type="button", cls=cls, onclick=onclick, **kw)


def fs_nav(product: Product, links, right, *, on_ink=True, home="/", menu_label="Menu"):
    """Shared public top nav. `links` = [(label, href)], `right` = components."""
    right = list(right)
    return Nav(
        Div(
            A(Img(src=product.mark_src, alt="", width=32, height=32, cls="fs-mark"), Span(product.name), href=home, cls="fs-brand"),
            Div(*[A(label, href=href, cls="fs-nav-link") for label, href in links],
                # On mobile the language switch + sign-in live inside the menu so the
                # top bar stays a single compact row (brand + hamburger).
                Div(cls="fs-nav-actions-mobile"),
                id="fs-mobile-nav", cls="fs-nav-links"),
            Button(Span(), type="button", aria_expanded="false",
                   aria_controls="fs-mobile-nav", aria_label=menu_label, cls="fs-menu-toggle"),
            Div(*right, cls="fs-nav-right"),
            cls="fs-nav-inner fs-wrap",
        ),
        cls="fs-nav on-ink" if on_ink else "fs-nav",
    )


MOBILE_NAV_JS = """
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.fs-nav').forEach(function (nav) {
    var toggle = nav.querySelector('.fs-menu-toggle');
    var panel = nav.querySelector('.fs-nav-links');
    if (!toggle || !panel) return;
    var lockedScrollY = 0;
    function setBodyLock(locked) {
      if (locked) {
        lockedScrollY = window.scrollY;
        var scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
        document.body.style.paddingRight = scrollbarWidth ? scrollbarWidth + 'px' : '';
        document.body.style.position = 'fixed';
        document.body.style.top = -lockedScrollY + 'px';
        document.body.style.left = '0';
        document.body.style.right = '0';
      } else {
        document.body.style.position = '';
        document.body.style.top = '';
        document.body.style.left = '';
        document.body.style.right = '';
        document.body.style.paddingRight = '';
        window.scrollTo(0, lockedScrollY);
      }
    }
    function closeMenu() {
      if (toggle.getAttribute('aria-expanded') !== 'true') return;
      toggle.setAttribute('aria-expanded', 'false');
      panel.classList.remove('is-open');
      setBodyLock(false);
    }
    var desktop = nav.querySelector('.fs-nav-right');
    var mobile = nav.querySelector('.fs-nav-actions-mobile');
    var breakpoint = window.matchMedia('(max-width:1100px)');
    function placeActions() {
      closeMenu();
      var target = breakpoint.matches ? mobile : desktop;
      var source = breakpoint.matches ? desktop : mobile;
      while (source.firstChild) target.appendChild(source.firstChild);
    }
    placeActions();
    breakpoint.addEventListener('change', placeActions);
    toggle.addEventListener('click', function () {
      var open = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!open));
      panel.classList.toggle('is-open', !open);
      setBodyLock(!open);
      if (!open) {
        var firstLink = panel.querySelector('a');
        if (firstLink) firstLink.focus();
      }
    });
    panel.addEventListener('click', function (event) {
      if (event.target.closest('a')) closeMenu();
    });
    nav.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
        closeMenu();
        toggle.focus();
      }
    });
  });
});
"""


def fs_logo_strip(label, names):
    return Div(
        P(label, style="text-align:center;color:var(--muted);font-size:13px;font-weight:600;"
                       "letter-spacing:.06em;text-transform:uppercase;margin-bottom:24px"),
        Div(*[Span(n) for n in names], cls="fs-logos"),
        cls="fs-wrap", style="padding-top:44px;padding-bottom:44px",
    )


def fs_footer(product: Product, columns, bottom_left, bottom_right, *, legal=""):
    """columns = [(heading, [(label, href), ...]), ...]."""
    return Footer(
        Div(
            Div(
                Div(A(Img(src=product.mark_src, alt="", width=32, height=32, cls="fs-mark"), Span(product.name), href="/", cls="fs-brand"),
                    P(product.tagline), cls="fs-footer-brand"),
                *[Div(Span(h, cls="fs-foot-h"),
                      *[A(label, href=href) for label, href in items], cls="fs-foot-col")
                  for h, items in columns],
                cls="fs-footer-top fs-wrap",
            ),
            Div(Span(bottom_left), Div(*bottom_right),
                P(legal, cls="fs-footer-legal") if legal else None,
                cls="fs-footer-bottom fs-wrap"),
        ),
        cls="fs-footer",
    )
