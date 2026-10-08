"""FastSME design system — tokens, fonts and reusable public-page primitives."""
from __future__ import annotations

from dataclasses import dataclass

from fasthtml.common import *

from . import i18n


@dataclass(frozen=True)
class Product:
    """One FastSME product's identity for public pages."""
    name: str = "FastAccounts"
    accent: str = "#7c3aed"          # violet — primary actions and highlights
    accent_strong: str = "#5b21b6"   # deep violet — links/hover on light grounds
    tagline: str = ""
    suite_url: str = "https://fastsme.com/products"
    github_url: str = "https://github.com/predictivelabsai/FastAccounts"
    mark: str = "F"                  # short brand mark glyph


FASTPRODUCT = Product(tagline=i18n.t("footer.tagline"))


# Bricolage Grotesque (display) + Hanken Grotesk (body). Both carry the Estonian
# glyph set (õ ä ö ü š ž) via Google's latin-ext unicode ranges.
FONT_LINKS = (
    Link(rel="preload", href="/static/fonts/bricolagegrotesque-latin.woff2",
         **{"as": "font"}, type="font/woff2", crossorigin=""),
    Link(rel="preload", href="/static/fonts/hankengrotesk-latin.woff2",
         **{"as": "font"}, type="font/woff2", crossorigin=""),
    Link(rel="stylesheet", href="/static/fonts/fonts.css"),
)


DESIGN_CSS = """
:root{
  --accent:#7c3aed; --accent-strong:#5b21b6; --on-accent:#ffffff;
  --ink:#14062b; --ink-2:#21103e; --ink-3:#321651;
  --paper:#faf9fc; --paper-2:#f0ecf8; --card:#ffffff;
  --text:#1c1333; --muted:#6b6580; --line:#e8e5f0;
  --on-ink:#f6f2ff; --on-ink-muted:#c9bddc; --ink-line:rgba(246,242,255,.12);
  --radius:14px; --radius-lg:24px; --radius-pill:999px;
  --maxw:1200px;
  --shadow-sm:0 1px 2px rgba(20,6,43,.06),0 2px 6px rgba(20,6,43,.05);
  --shadow-md:0 10px 30px rgba(20,6,43,.10);
  --shadow-lg:0 30px 80px rgba(20,6,43,.22);
  --step-fast:.16s cubic-bezier(.2,.7,.3,1);
  --font-display:"Bricolage Grotesque",ui-sans-serif,system-ui,"Segoe UI",sans-serif;
  --font-body:"Hanken Grotesk",ui-sans-serif,system-ui,"Segoe UI",sans-serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--text);font-family:var(--font-body);
  font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
h1,h2,h3,h4{font-family:var(--font-display);font-weight:700;line-height:1.04;letter-spacing:-.02em;margin:0}
h2{font-size:clamp(28px,4vw,40px)}
h3{font-size:20px}
p{margin:0;overflow-wrap:break-word}
a{color:inherit}
img{max-width:100%;display:block}
::selection{background:var(--accent);color:var(--on-accent)}
:focus-visible{outline:3px solid var(--accent-strong);outline-offset:3px;border-radius:6px}
.fs-nav.on-ink :focus-visible,.fs-footer :focus-visible{outline-color:#ddd0ff}
.fs-wrap{max-width:var(--maxw);margin:0 auto;padding:0 clamp(18px,4vw,40px)}
.fs-skip{position:absolute;top:12px;left:12px;z-index:100;transform:translateY(-180%);background:var(--accent-strong);color:var(--on-ink);padding:10px 16px;border-radius:var(--radius-pill);font-weight:700;text-decoration:none;transition:transform var(--step-fast)}
.fs-skip:focus,.fs-skip:focus-within{transform:translateY(0)}

/* ---------- buttons ---------- */
.fs-btn{display:inline-flex;align-items:center;justify-content:center;gap:.5em;
  font-family:var(--font-body);font-weight:600;font-size:15px;line-height:1;cursor:pointer;
  text-decoration:none;border:1.5px solid transparent;border-radius:var(--radius-pill);
  padding:13px 22px;transition:transform var(--step-fast),background var(--step-fast),border-color var(--step-fast),color var(--step-fast)}
.fs-btn:active{transform:translateY(1px)}
.fs-btn-primary,.fs-btn-lime{background:var(--accent);color:var(--on-accent);border-color:var(--accent)}
.fs-btn-primary:hover,.fs-btn-lime:hover{background:var(--accent-strong);border-color:var(--accent-strong)}
.fs-btn-ink{background:var(--ink);color:var(--on-ink);border-color:var(--ink)}
.fs-btn-ink:hover{background:var(--ink-3)}
.fs-btn-ghost{background:transparent;color:var(--on-ink);border-color:var(--ink-line)}
.fs-btn-ghost:hover{border-color:var(--on-ink);background:rgba(246,242,255,.06)}
.fs-btn-outline{background:transparent;color:var(--ink);border-color:var(--line)}
.fs-btn-outline:hover{border-color:var(--ink)}
.fs-btn-lg{padding:16px 28px;font-size:16px}

/* ---------- eyebrow ---------- */
.fs-eyebrow{display:inline-flex;align-items:center;gap:8px;font-family:var(--font-body);
  font-weight:600;font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent-strong)}
.fs-eyebrow.on-ink{color:#ddd0ff}
.fs-eyebrow::before{content:"";width:22px;height:1.5px;background:currentColor;opacity:.6}

/* ---------- nav ---------- */
.fs-nav{position:sticky;top:0;z-index:50}
.fs-nav-inner{display:flex;align-items:center;justify-content:space-between;gap:20px;height:70px}
.fs-brand{display:flex;align-items:center;gap:10px;font-family:var(--font-display);font-weight:800;
  font-size:20px;letter-spacing:-.02em;color:inherit;text-decoration:none}
.fs-mark{width:32px;height:32px;border-radius:9px;display:grid;place-items:center;overflow:hidden;
  background:var(--accent);color:var(--on-accent);font-weight:800;font-family:var(--font-display)}
.fs-mark svg{display:block;width:100%;height:100%}
.fs-nav-links{display:flex;align-items:center;gap:26px}
.fs-nav-link{font-weight:500;font-size:15px;text-decoration:none;opacity:.82;transition:opacity var(--step-fast)}
.fs-nav-link:hover{opacity:1}
.fs-nav-right{display:flex;align-items:center;gap:14px}
.fs-lang{display:inline-flex;border:1.5px solid var(--ink-line);border-radius:var(--radius-pill);overflow:hidden}
.fs-lang a{padding:6px 11px;font-size:12px;font-weight:700;letter-spacing:.03em;text-decoration:none;color:#e6ddf5;opacity:1}
.fs-lang a.active{background:var(--accent);color:var(--on-accent);opacity:1}
.fs-nav.on-ink{background:color-mix(in srgb,var(--ink) 86%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--ink-line)}
.fs-nav.on-ink,.fs-nav.on-ink a{color:var(--on-ink)}
.fs-nav.on-ink .fs-lang{border-color:var(--ink-line)}
.fs-nav.on-ink .fs-lang a.active{background:var(--accent);color:var(--on-accent)}
.fs-menu-toggle{display:none}
.fs-nav-actions-mobile{display:none}

/* ---------- footer ---------- */
.fs-footer{background:var(--ink);color:var(--on-ink)}
.fs-footer a{color:var(--on-ink);text-decoration:none;opacity:.8}
.fs-footer a:hover{opacity:1;color:#ddd0ff}
.fs-footer-top{display:grid;grid-template-columns:1.4fr 1fr 1fr 1fr;gap:36px;padding-block:64px 48px}
.fs-footer-brand .fs-brand{color:var(--on-ink);margin-bottom:14px}
.fs-footer-brand p{color:var(--on-ink-muted);max-width:34ch}
.fs-foot-h{display:block;font-weight:700;font-size:13px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--on-ink-muted);margin-bottom:16px}
.fs-foot-col a{display:flex;align-items:center;min-height:40px;padding:6px 0;font-size:15px}
.fs-footer-bottom{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;
  padding-block:22px 40px;border-top:1px solid var(--ink-line);color:var(--on-ink-muted);font-size:13px}
.fs-footer-bottom a{opacity:.75}
.fs-footer-legal{flex-basis:100%;max-width:72ch;font-size:13px;line-height:1.5;color:var(--on-ink-muted);}

/* ---------- logo strip ---------- */
.fs-logos{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:clamp(20px,5vw,54px)}
.fs-logos span{font-family:var(--font-display);font-weight:700;font-size:19px;opacity:.42;letter-spacing:-.01em}

@media(max-width:900px){
  .fs-footer-top{grid-template-columns:1fr 1fr;gap:28px}
}
@media(max-width:1100px){
  .fs-nav-inner{position:relative;gap:8px}
  .fs-brand{min-width:0;flex:0 0 auto;gap:7px;font-size:18px;white-space:nowrap}
  .fs-mark{width:28px;height:28px}
  .fs-menu-toggle{display:inline-flex;align-items:center;justify-content:center;flex:0 0 44px;
    width:44px;height:44px;padding:0;border:1px solid var(--accent);border-radius:var(--radius-pill);
    background:var(--ink);color:var(--paper);font:inherit;cursor:pointer}
  .fs-menu-toggle::before,.fs-menu-toggle::after,.fs-menu-toggle span{content:"";display:block;width:18px;height:2px;
    border-radius:2px;background:currentColor;transition:transform var(--step-fast),opacity var(--step-fast)}
  .fs-menu-toggle{flex-direction:column;gap:4px;margin-left:auto}
  .fs-menu-toggle[aria-expanded="true"]::before{transform:translateY(6px) rotate(45deg)}
  .fs-menu-toggle[aria-expanded="true"] span{opacity:0}
  .fs-menu-toggle[aria-expanded="true"]::after{transform:translateY(-6px) rotate(-45deg)}
  .fs-nav-links{position:absolute;top:100%;left:0;right:0;display:none;flex-direction:column;align-items:stretch;
    gap:0;padding:8px 18px 12px;background:var(--ink);color:var(--paper);
    border-top:1px solid var(--line);border-bottom:1px solid var(--line);box-shadow:0 14px 28px rgba(20,6,43,.18)}
  .fs-nav-links{max-height:calc(100dvh - 70px);overflow-y:auto}
  .fs-nav-links.is-open{display:flex;background:color-mix(in srgb,var(--accent) 6%,var(--ink))}
  .fs-nav-link{display:flex;align-items:center;min-height:44px;padding:10px 0;font-size:16px}
  /* keep the top bar a single compact row: brand + hamburger only */
  .fs-nav-right{display:none}
  /* language + sign-in move into the dropdown menu */
  .fs-nav-actions-mobile{display:flex;align-items:center;justify-content:space-between;gap:12px;
    flex-wrap:wrap;margin-top:6px;padding-top:14px;border-top:1px solid var(--ink-line)}
  .fs-nav-actions-mobile .fs-btn{min-height:44px;padding-inline:16px;white-space:nowrap}
  .fs-lang{flex:0 0 auto;overflow:visible}
  .fs-lang a{display:inline-flex;align-items:center;min-height:40px;padding-inline:18px}
  .fs-footer-top{grid-template-columns:1fr 1fr}
}
@media(max-width:600px){.fs-footer-top{grid-template-columns:1fr}}
@media(prefers-reduced-motion:reduce){
  *{animation-duration:.001ms!important;transition-duration:.001ms!important}
}
@media(pointer:coarse){
  .fs-brand{min-height:44px;padding-inline:6px}
  .fs-nav-links:not(.is-open) .fs-nav-link{display:inline-flex;align-items:center;min-height:44px;padding-inline:6px}
  .fs-lang a{display:inline-flex;align-items:center;min-height:44px;padding-inline:18px}
  .fs-foot-col a{min-height:44px;padding-inline:4px}
  .fs-btn{min-height:44px;padding-inline:14px}
  .fs-nav-right .fs-btn-ghost,.fs-nav-right .fs-btn:not(.fs-btn-lg){min-height:44px;padding-inline:12px}
  .ct-cta{min-height:44px;padding-inline:8px}
  .pg-name{min-height:44px;padding-inline:4px}
}
"""


def accent_style(product: Product) -> Style:
    """Per-product accent override — the only thing that changes between products."""
    return Style(
        f":root{{--accent:{product.accent};--accent-strong:{product.accent_strong};}}"
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
            A(Span(product.mark, cls="fs-mark"), Span(product.name), href=home, cls="fs-brand"),
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
                Div(A(Span(product.mark, cls="fs-mark"), Span(product.name), href="/", cls="fs-brand"),
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
