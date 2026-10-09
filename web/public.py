"""Public FastAccounts landing, sign-in, and integration catalogue pages."""
from __future__ import annotations

import json
from urllib.parse import quote
from dataclasses import replace

from fasthtml.common import *

import integrations
import version
from . import google_auth, i18n
from .design import (DESIGN_CSS, FONT_LINKS, FASTPRODUCT, MOBILE_NAV_JS,
                     accent_style, fs_button, fs_eyebrow, fs_nav, fs_footer, fs_logo_strip)


PUBLIC_CSS = """
/* ---------- violet hero ---------- */
.lh-hero{background:linear-gradient(135deg,#6d28d9 0%,#7c3aed 45%,#4f46e5 100%);
  color:var(--on-ink);position:relative;overflow:visible}
.lh-hero::after{content:"";position:absolute;inset:0;pointer-events:none;
  background:radial-gradient(60% 40% at 50% 6%,rgba(221,208,255,.16),transparent 70%)}
.lh-hero-inner{position:relative;z-index:1;text-align:center;padding-block:clamp(56px,9vw,104px) 0;max-width:920px;margin:0 auto}
.lh-hero h1{font-size:clamp(40px,6.4vw,74px);font-weight:800;line-height:1.04;margin:22px auto 0;max-width:16ch}
.lh-hi{color:#e9dcff;text-decoration:underline;text-decoration-color:rgba(255,255,255,.35);text-decoration-thickness:3px;text-underline-offset:.12em}
.lh-sub{color:var(--on-ink);font-size:clamp(16px,2vw,20px);line-height:1.6;max-width:60ch;margin:22px auto 0}
.lh-actions{display:flex;gap:12px;justify-content:center;flex-wrap:wrap;margin:32px 0 16px}
.lh-trust{color:var(--on-ink);font-size:13px;font-weight:600;letter-spacing:.02em}
.lh-hero-inner .fs-eyebrow{justify-content:center}

/* ---------- dashboard mockup ---------- */
.lh-mock-wrap{max-width:1060px;margin:0 auto;padding:0 clamp(18px,4vw,40px);position:relative;z-index:2}
.lh-mock{background:var(--card);border:1px solid var(--line);border-radius:16px;
  box-shadow:var(--shadow-lg);overflow:hidden;color:var(--text);text-align:left}
.lh-mock-bar{display:flex;align-items:center;gap:7px;padding:12px 16px;border-bottom:1px solid var(--line);background:var(--paper)}
.lh-dot{width:11px;height:11px;border-radius:50%;background:#d7cfe5}
.lh-mock-url{margin-left:12px;font-size:12px;color:var(--muted);font-weight:600}
.lh-mock-body{display:grid;grid-template-columns:190px minmax(0,1fr);min-height:430px}
.lh-appbar{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 14px;border-bottom:1px solid var(--line);background:#fff}
.lh-app-brand{display:flex;align-items:center;gap:6px;font-family:var(--font-display);font-size:13px;font-weight:800}
.lh-app-dot{width:7px;height:7px;border-radius:50%;background:var(--accent)}
.lh-app-brand-fast{color:var(--accent-strong)}
.lh-app-meta{display:flex;align-items:center;gap:7px;font-size:9px;font-weight:750;white-space:nowrap}
.lh-version{padding:4px 7px;border-radius:999px;background:var(--paper-2);color:var(--muted)}
.lh-logout{padding:4px 8px;border:1px solid var(--line);border-radius:5px;background:#fff;color:var(--muted);font:inherit}
.lh-side{background:color-mix(in srgb,var(--paper) 72%,var(--card));border-right:1px solid var(--line);padding:13px 10px;overflow:hidden}
.lh-side-group{margin-bottom:9px}
.lh-side-label{display:block;padding:0 8px 4px;color:var(--muted);font-size:7px;font-weight:800;letter-spacing:.13em}
.lh-side-item{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:9px;font-weight:650;padding:4px 8px;border-left:3px solid transparent;text-decoration:none;white-space:nowrap}
.lh-side-item span{font-size:11px;line-height:1}
.lh-side-item.on{background:var(--paper-2);color:var(--accent-strong);border-left-color:var(--accent)}
.lh-main{padding:17px 18px;background:#fff;min-width:0}
.lh-hello{font-family:var(--font-display);font-weight:800;font-size:17px}
.lh-hello-sub{color:var(--muted);font-family:var(--font-body);font-weight:500;font-size:10px;display:block;margin-top:2px}
.lh-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:15px 0}
.lh-kpi{border:1px solid var(--line);padding:9px 10px;min-width:0}
.lh-kpi.green{border-right-color:var(--accent)}.lh-kpi.red{border-right-color:#d46b67}
.lh-kpi small{display:block;color:var(--muted);font-size:7px;font-weight:800;letter-spacing:.07em}
.lh-kpi b{font-family:var(--font-display);font-weight:800;font-size:20px;display:block;margin-top:4px}
.lh-kpi em{font-style:normal;color:var(--muted);font-size:8px;white-space:nowrap}
.lh-panels{display:grid;grid-template-columns:1.08fr 1fr;gap:10px}
.lh-panel{border:1px solid var(--line);padding:11px;min-width:0}
.lh-panel-title{font-family:var(--font-display);font-size:11px;font-weight:700;line-height:1.04;margin:0 0 10px}
.lh-bar{display:grid;grid-template-columns:74px 1fr 16px;align-items:center;gap:6px;margin:7px 0;font-size:8px;color:var(--muted)}
.lh-bar i{height:5px;background:var(--accent);border-radius:0 4px 4px 0;display:block}
.lh-bar b{font-size:8px;color:var(--ink);text-align:right}
.lh-row{display:flex;align-items:center;gap:6px;padding:7px 0;border-top:1px solid var(--line);font-size:8px;white-space:nowrap}
.lh-row:first-of-type{border-top:0}
.lh-row-txt{min-width:0;overflow:hidden;text-overflow:ellipsis}
.lh-row-txt b{display:block;font-weight:700;overflow:hidden;text-overflow:ellipsis}
.lh-row-txt small{display:block;color:var(--muted);font-size:8px}
.lh-tag{margin-left:auto;flex:none;font-size:7px;font-weight:800;padding:3px 5px;border-radius:999px;background:var(--paper-2);color:var(--accent-strong)}
.lh-tag.sick{background:#fff0ef;color:#ba5b58}
/* ---------- light sections ---------- */
.lh-sec{padding:clamp(70px,9vw,120px) 0}
.lh-sec.pad-top{padding-top:clamp(72px,9vw,110px)}
.lh-alt{background:var(--paper-2)}
.lh-head{max-width:640px;margin-bottom:clamp(30px,4vw,48px)}
.lh-head h2{font-size:clamp(28px,4vw,40px);margin:14px 0 12px}
.lh-head p{color:var(--muted);font-size:clamp(16px,1.6vw,18px)}
.lh-features-head{display:grid;grid-template-columns:.85fr 1.15fr;gap:clamp(30px,5vw,64px);align-items:end;max-width:none}
.lh-features-head .lh-head{margin-bottom:0}
.lh-features-head>p{margin:0 0 12px;max-width:58ch}
.lh-head.center{max-width:680px;margin-left:auto;margin-right:auto;text-align:center}
.lh-head.center .fs-eyebrow{justify-content:center}
.lh-real-demo-frame{max-width:980px;margin:0 auto;border:1px solid var(--line);border-radius:var(--radius-lg);
  background:var(--card);box-shadow:var(--shadow-md);overflow:hidden}
.lh-real-demo-frame .lh-mock-bar{padding:12px 16px}
.lh-real-demo-body{padding:10px;background:var(--paper-2);border-top:1px solid var(--line)}
.lh-real-demo-body img{width:100%;height:auto;border:1px solid var(--line);border-radius:var(--radius);background:var(--card)}
.lh-suite{background:var(--paper-2);border-block:1px solid var(--line);padding:27px 0}
.lh-suite-inner{display:flex;align-items:center;justify-content:space-between;gap:24px}
.lh-suite-label{color:var(--muted);font-size:12px;font-weight:800;letter-spacing:normal;max-width:34ch;text-align:center}
.lh-suite-logos{display:flex;align-items:center;justify-content:flex-end;gap:10px 18px;flex-wrap:wrap;color:var(--muted);font-family:var(--font-display);font-size:15px;font-weight:700;letter-spacing:-.02em}
.lh-suite-logos span{font-size:15px}

.lh-feats{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.lh-feat{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:26px 24px;
  transition:transform var(--step-fast),box-shadow var(--step-fast)}
.lh-feat:hover{transform:translateY(-3px);box-shadow:var(--shadow-md)}
.lh-feat h3{margin-bottom:8px}
.lh-feat p{color:var(--muted);font-size:15px}
.lh-feat i{display:grid;place-items:center;width:40px;height:40px;border-radius:11px;margin-bottom:16px;
  background:var(--paper-2);color:var(--accent-strong);font-style:normal;font-weight:800;font-size:14px;
  letter-spacing:.02em;font-family:var(--font-display)}

/* statutory, asymmetric split */
.lh-stat{display:grid;grid-template-columns:.85fr 1.15fr;gap:clamp(30px,5vw,64px);align-items:start}
.lh-stat-list{display:grid;grid-template-columns:1fr 1fr;gap:2px 28px}
.lh-stat-item{padding:18px 0;border-top:1px solid var(--line)}
.lh-stat-item b{font-family:var(--font-display);font-size:16px;display:flex;align-items:center;gap:9px}
.lh-stat-item b::before{content:"";width:9px;height:9px;border-radius:2px;background:var(--accent-strong)}
.lh-stat-item p{color:var(--muted);font-size:14px;margin-top:6px}

/* pricing */
.lh-prices{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.lh-price{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:30px}
.lh-price.feature{background:var(--ink);color:var(--on-ink);border-color:var(--ink)}
.lh-price .fs-eyebrow{color:var(--accent-strong)}
.lh-price.feature .fs-eyebrow{color:#ddd0ff}
.lh-price h3{margin:12px 0 4px}
.lh-price .amt{font-family:var(--font-display);font-weight:800;font-size:40px;letter-spacing:-.03em;margin:8px 0 14px}
.lh-price.feature .amt .per{color:var(--accent)}
.lh-price p{color:var(--muted);font-size:15px}
.lh-price.feature p{color:var(--on-ink-muted)}

/* faq */
.lh-faqs{max-width:820px}
.lh-faq{border-top:1px solid var(--line);padding:0}
.lh-faq summary{cursor:pointer;padding:24px 4px;font-family:var(--font-display);font-size:20px;font-weight:700;line-height:1.35}
.lh-faq summary::marker{color:var(--accent)}
.lh-faq[open] summary{color:var(--accent-strong)}
.lh-faq p{padding:0 4px 24px}
.lh-faq:last-child{border-bottom:1px solid var(--line)}
.lh-faq h3{margin-bottom:8px}
.lh-faq p{color:var(--muted);font-size:16px;max-width:70ch}

/* cta band */
.lh-ctaband{background:var(--ink);color:var(--on-ink);border-radius:24px;
  padding:clamp(44px,7vw,80px) clamp(24px,5vw,64px);text-align:center;position:relative;overflow:hidden}
.lh-ctaband::before{content:"";position:absolute;inset:0;
  background:radial-gradient(70% 120% at 50% 0%,color-mix(in srgb,var(--accent) 18%,transparent),transparent 60%)}
.lh-ctaband>*{position:relative}
.lh-ctaband h2{font-size:clamp(28px,4vw,40px)}
.lh-ctaband p{color:var(--on-ink-muted);font-size:18px;margin:16px auto 30px;max-width:52ch}
.lh-ctaband .lh-actions{margin-bottom:0}

@media(max-width:900px){
  .lh-feats{grid-template-columns:1fr 1fr}
  .lh-stat,.lh-cmp,.lh-features-head{grid-template-columns:1fr}
  .lh-suite-inner{flex-direction:column;align-items:center;gap:14px;text-align:center}
  .lh-suite-label{max-width:none;text-align:center}
  .lh-suite-logos{justify-content:center}
  .lh-mock-body{grid-template-columns:190px minmax(0,1fr)}
  .lh-ai{display:none}
}
@media(max-width:680px){
  .lh-feats,.lh-prices,.lh-stat-list{grid-template-columns:1fr}

  .lh-mock-wrap{display:none}
}
@media(max-width:560px){
  /* Estonia / Global comparison toggle: full-width segmented control */
  .lh-compare-tabs{display:flex;width:100%;margin-bottom:18px}
  .lh-compare-tabs button{flex:1 1 0;padding:10px 8px;text-align:center}
}
@media(max-width:760px){
.lh-hero-inner .fs-eyebrow,.lh-head .fs-eyebrow{font-size:12px}
  .lh-trust,.lh-suite-label,.ct-foot{font-size:14px}
  .lh-mock-wrap{padding-inline:12px}
  .lh-mock-bar{padding:10px 12px}
  .lh-mock-url{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .lh-appbar{min-width:0;padding:10px}
  .lh-app-meta{min-width:0;overflow:hidden}
  .lh-mock-secondary{display:none}
  .lh-main{padding:16px 12px}
  .lh-hello{font-size:20px}
  .lh-hello-sub{font-size:12px}
  .lh-kpi{padding:11px 10px}
  .lh-kpi small{font-size:10px}
  .lh-kpi b{font-size:22px}
  .lh-kpi em{font-size:10px;white-space:normal}
  .lh-panel{padding:12px}
  .lh-panel-title{font-size:14px}
  .lh-bar{grid-template-columns:68px minmax(0,1fr) 18px;font-size:11px;gap:5px}
  .lh-bar b{font-size:11px}
  .lh-row{font-size:11px;white-space:normal;align-items:flex-start}
  .lh-row-txt small{font-size:10px}
  .lh-tag{font-size:9px}
  .lh-actions .fs-btn{min-height:44px}
}
.lh-hero{padding-bottom:clamp(110px,12vw,160px)}
.lh-suite{position:relative}
.lh-hero h1{max-width:20ch;text-wrap:balance}
.lh-side-label{font-size:9px}.lh-side-item{font-size:11px}
.lh-kpi small{font-size:11px;letter-spacing:0}.lh-kpi b{font-size:26px}
.lh-panel-title{font-size:14px}.lh-row{font-size:11px}.lh-tag{font-size:10px}
.lh-bar{font-size:11px;grid-template-columns:100px 1fr 24px}.lh-bar b{font-size:11px}
.lh-hello-sub{font-size:12px}.lh-app-meta{font-size:11px}
.lh-stat-item b::before{flex:none}.lh-stat .fs-btn{margin-top:24px}
.lh-feat-label{display:block;color:var(--accent-strong);font-size:12px;font-weight:700;margin-bottom:12px}
.lh-price .amt{color:var(--text)}.lh-price.feature .amt{color:var(--on-accent)}
.fs-footer-top{grid-template-columns:1.4fr 1fr 1fr}
.fs-nav.on-ink .fs-btn-primary,.fs-nav.on-ink .fs-btn-lime{color:var(--on-accent)}
.fs-nav :focus-visible,.fs-footer :focus-visible,.lh-hero :focus-visible,.lh-ctaband :focus-visible{outline-color:#ddd0ff}
section[id]{scroll-margin-top:90px}
.language-picker{position:relative}.language-trigger{width:44px;height:44px;border:1px solid var(--ink-line);border-radius:999px;background:transparent;color:var(--on-ink);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;letter-spacing:0.02em;line-height:1;cursor:pointer}
.language-menu{display:none;position:absolute;right:0;top:calc(100% + 8px);z-index:60;min-width:170px;padding:6px;border:1px solid var(--ink-line);border-radius:14px;background:var(--ink-2);box-shadow:var(--shadow-md)}
.language-menu.open{display:flex;flex-direction:column}.language-option{display:flex;align-items:center;gap:10px;min-height:44px;padding:8px 12px;text-decoration:none;border-radius:8px}
.language-option:hover,.language-option.active{background:var(--ink-3)}.language-flag{display:inline-flex;align-items:center;justify-content:center;min-width:26px;height:18px;padding:0 6px;border:1px solid var(--ink-line);border-radius:6px;font-size:11px;font-weight:700;letter-spacing:0.02em;line-height:1;color:var(--on-ink)}
@media(max-width:1100px){.fs-nav-actions-mobile .language-menu{position:static;margin-top:8px}.fs-nav-actions-mobile{align-items:flex-start}}
@media(max-width:680px){.lh-hero{padding-bottom:56px;margin-bottom:0}.fs-footer-top{grid-template-columns:1fr}}
.page-hero{max-width:1180px;margin:auto;padding:76px 24px 42px}.page-hero .lede{font-size:18px}.summary{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}.chip{border:1px solid var(--line);border-radius:999px;padding:8px 13px;font-size:12px;font-weight:700;color:var(--muted)}
.catalogue{max-width:1180px;margin:auto;padding:14px 24px 74px}.integration-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.integration{border:1px solid var(--line);border-radius:22px;padding:24px;background:#fff;display:flex;flex-direction:column;min-height:350px}.integration-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.integration-logo-wrap{height:58px;min-width:140px;display:flex;align-items:center}.integration-logo{display:block;max-width:142px;max-height:50px;object-fit:contain}.provider-meta{text-align:right}.markets{display:block;margin-top:8px;color:var(--muted);font-size:11px;font-weight:750}.integration h2{font-size:23px;margin:24px 0 4px}.category{font-size:12px;color:var(--accent-strong);font-weight:750}.integration>p{color:var(--muted);line-height:1.6}.capabilities{display:flex;gap:7px;flex-wrap:wrap;margin:8px 0 18px}.capability{background:var(--paper);border:1px solid var(--line);border-radius:999px;padding:6px 9px;font-size:11px;color:var(--muted)}.ownership{border-top:1px solid var(--line);padding-top:16px;display:grid;grid-template-columns:1fr 1fr;gap:14px;font-size:12px}.ownership span{display:block;color:var(--muted);margin-bottom:3px}.ownership strong{font-size:13px}.docs{color:var(--accent-strong);text-decoration:none;font-size:13px;font-weight:750;margin-top:auto;padding-top:20px}
.notice{max-width:1180px;margin:0 auto 70px;padding:0 24px}.notice>div{border:1px solid var(--line);background:var(--paper-2);border-radius:18px;padding:22px;color:var(--muted);line-height:1.6}.notice strong{color:var(--ink)}
.auth-wrap{min-height:calc(100vh - 150px);display:grid;place-items:center;padding:60px 24px}.auth-card{width:min(470px,100%);border:1px solid var(--line);border-radius:24px;padding:34px;box-shadow:0 22px 70px rgba(20,6,43,.08)}.auth-card h1{font-size:32px;letter-spacing:-.035em;margin:8px 0}.auth-card p{color:var(--muted);line-height:1.6}.google{width:100%;margin-top:18px}.error{border-radius:12px;background:#fff1f0;color:#a61b1b;padding:12px 14px;font-size:13px}.workspace{max-width:900px;margin:auto;padding:80px 24px}.workspace h1{font-size:44px;letter-spacing:-.04em}.workspace p{color:var(--muted);line-height:1.65}

.page-hero h1{font-size:clamp(36px,5vw,64px);margin:20px 0;max-width:22ch}
.lede{color:var(--muted);max-width:70ch}.kicker{color:var(--accent-strong);font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}
.auth-card{background:var(--card)}.auth-card p{margin:16px 0}.auth-card .error{margin-top:16px}
@media(max-width:820px){.integration-grid{grid-template-columns:1fr}}
@media(max-width:500px){.integration{padding:19px}.integration-logo-wrap{min-width:110px}.integration-logo{max-width:110px}.ownership{grid-template-columns:1fr}.page-hero,.catalogue{padding-inline:18px}}
/* ---------- demo stage and decorative glass ---------- */
.lh-demo{position:relative;padding-bottom:64px;background:radial-gradient(ellipse at 50% 0%,#e9dfff,transparent 72%)}
.lh-demo .lh-mock-wrap{top:-72px;margin-bottom:-72px;max-width:1120px;padding-inline:70px}
.lh-glass{position:absolute;z-index:3;width:205px;padding:18px 20px;border:1px solid rgba(255,255,255,.6);border-radius:18px;background:rgba(255,255,255,.55);backdrop-filter:blur(14px);box-shadow:0 16px 40px rgba(20,6,43,.12);color:var(--text)}
.lh-glass small,.lh-glass strong{display:block}
.lh-glass small{font-size:12px;color:var(--accent-strong);font-weight:700}
.lh-glass strong{font-family:var(--font-display);font-size:26px;line-height:1.2;margin-block:8px}
.lh-glass span{font-size:12px}
.lh-glass-bank{left:0;top:100px}.lh-glass-invoice{right:0;top:190px}.lh-glass-tax{right:65px;bottom:-28px}
.lh-hero .fs-btn-ghost{border-color:rgba(255,255,255,.6)}
.lh-hero :focus-visible,.lh-ctaband :focus-visible{outline-color:#e9dcff}
/* ---------- bureau workflow ---------- */
.lh-process{background:var(--ink);color:var(--on-ink)}
.lh-process .lh-head p{color:var(--on-ink-muted)}
.lh-steps{list-style:none;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:30px;padding:0;margin:0}
.lh-step-number{display:block;font-family:var(--font-display);font-size:52px;line-height:1;color:var(--accent);margin-bottom:24px}
.lh-steps h3{font-size:22px;line-height:1.2;margin-bottom:14px}
.lh-steps p{font-size:15px;color:var(--on-ink-muted)}
/* ---------- old and new comparison ---------- */
.lh-comparison{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.lh-compare-panel{padding:clamp(24px,4vw,40px);border:1px solid var(--line);border-radius:18px;background:var(--card)}
.lh-compare-panel.new{background:var(--paper-2);border-color:#d8c7f6}
.lh-compare-panel h3{font-size:26px;margin-bottom:24px}
.lh-compare-panel ul{list-style:none;padding:0;margin:0}
.lh-compare-panel li{display:flex;align-items:baseline;gap:14px;padding-block:16px;border-top:1px solid var(--line)}
.lh-compare-panel li span{color:var(--muted);font-weight:700}
.lh-compare-panel.new li span{color:var(--accent-strong)}
/* ---------- factual product stats ---------- */
.lh-facts{background:var(--paper-2);border-block:1px solid var(--line);padding-block:40px}
.lh-facts dl{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:28px;margin:0}
.lh-facts dt{font-size:14px;color:var(--muted)}
.lh-facts dd{margin:8px 0 0;font-family:var(--font-display);font-size:clamp(24px,3vw,36px);font-weight:700;color:var(--accent-strong);line-height:1.2}
.lh-close{background:var(--ink);padding-block:30px}
.auth-wrap{background:radial-gradient(ellipse at 50% 15%,#e9dcff,transparent 65%)}
.auth-card{border-radius:18px;border-color:#ded4ef;box-shadow:0 24px 64px rgba(20,6,43,.1)}
.auth-card .google{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.auth-card .google:hover{background:var(--accent-strong);border-color:var(--accent-strong)}
@media(max-width:1000px){.lh-glass{width:170px;padding:14px}.lh-glass strong{font-size:22px}.lh-steps{grid-template-columns:repeat(2,minmax(0,1fr));gap:36px}}
@media(max-width:680px){
  .lh-hero{padding-bottom:56px}.lh-demo{display:none}
  .lh-comparison,.lh-steps{grid-template-columns:1fr}
  .lh-facts dl{grid-template-columns:1fr 1fr;gap:32px 20px}
  .lh-faq summary{font-size:18px}.auth-card{padding:26px}
}

"""


def _language_switcher(lang: str, current: str):
    selected = i18n.LANGUAGES.get(lang, i18n.LANGUAGES[i18n.DEFAULT_LANG])
    return Div(
        Button(
            Span(selected["code"]),
            type="button",
            id="language-menu-button",
            aria_label=i18n.t("language.choose", lang),
            aria_haspopup="true",
            aria_expanded="false",
            onclick="toggleLanguageMenu(event)",
            cls="language-trigger",
        ),
        Div(
            *[
                A(
                    Span(info["code"], cls="language-flag"),
                    Span(info["native"]),
                    href=f"/set-lang/{code}?next={quote(current, safe='/')}",
                    lang=code,
                    role="menuitem",
                    aria_current="true" if code == lang else None,
                    cls=f"language-option{' active' if code == lang else ''}",
                )
                for code, info in i18n.LANGUAGES.items()
            ],
            id="language-menu",
            role="menu",
            cls="language-menu",
        ),
        cls="language-picker",
    )


def _nav(lang: str, current: str):
    T = lambda key: i18n.t(key, lang)
    return fs_nav(
        FASTPRODUCT,
        [(T("nav.pricing"), "/#pricing"), (T("nav.why"), "/#why"),
         (T("bureau.title"), "/#bureaus"), (T("nav.integrations"), "/integrations"),
         (T("nav.roadmap"), FASTPRODUCT.github_url)],
        [_language_switcher(lang, current), fs_button(T("nav.sign_in"), "/login", "primary")],
        menu_label=T("nav.open_navigation"),
    )


def _footer(lang: str):
    T = lambda key: i18n.t(key, lang)
    return fs_footer(
        replace(FASTPRODUCT, tagline=T("footer.tagline")),
        [(T("footer.product"), [(T("nav.pricing"), "/#pricing"),
                                (T("footer.integrations"), "/integrations")]),
         (T("footer.resources"), [(T("footer.github"), FASTPRODUCT.github_url),
                                  (T("footer.health"), "/healthz")])],
        T("footer.tagline"), [A(version.label(), href="/healthz", title=version.detail(), data_testid="app-version")],
    )


def public_page(*content, title: str, current: str, lang: str):
    return Html(
        Head(
            Title(f"{title} · FastAccounts"),
            Meta(charset="utf-8"),
            Meta(name="viewport", content="width=device-width, initial-scale=1"),
            Meta(name="description", content=i18n.t("meta.description", lang)),
            Link(rel="icon", type="image/svg+xml", href="/static/favicon.svg"),
            *FONT_LINKS,
            Style(DESIGN_CSS + PUBLIC_CSS),
            accent_style(FASTPRODUCT),
            Script(NotStr(MOBILE_NAV_JS)),
            Script(NotStr("""
                function closeLanguageMenu() {
                    const menu = document.getElementById('language-menu');
                    const button = document.getElementById('language-menu-button');
                    if (menu) menu.classList.remove('open');
                    if (button) button.setAttribute('aria-expanded', 'false');
                }
                function toggleLanguageMenu(event) {
                    event.stopPropagation();
                    const menu = document.getElementById('language-menu');
                    const button = document.getElementById('language-menu-button');
                    const opening = !menu.classList.contains('open');
                    menu.classList.toggle('open');
                    button.setAttribute('aria-expanded', opening ? 'true' : 'false');
                    if (opening) menu.querySelector('a').focus();
                }
                document.addEventListener('click', closeLanguageMenu);
                document.addEventListener('keydown', function(event) {
                    if (event.key === 'Escape') {
                        const wasOpen = document.getElementById('language-menu').classList.contains('open');
                        closeLanguageMenu();
                        const button = document.getElementById('language-menu-button');
                        if (button && wasOpen) {
                            event.stopPropagation();
                            button.focus();
                        }
                    }
                }, true);
            """)),
        ),
        Body(A(i18n.t("nav.skip_content", lang), href="#main-content", cls="fs-skip"),
             _nav(lang, current), Main(*content, id="main-content", tabindex="-1"), _footer(lang)),
        lang=lang,
    )



def _pricing_section(lang: str):
    T = lambda key: i18n.t(key, lang)
    return Section(Div(
        Div(fs_eyebrow(T("pricing.kicker")), H2(T("pricing.title")),
            P(T("pricing.lede")), cls="lh-head center"),
        Div(*[Article(
            fs_eyebrow(T(f"pricing.{kind}_eyebrow")), H3(T(f"pricing.{kind}_title")),
            P(T(f"pricing.{kind}_price"), cls="amt"), P(T(f"pricing.{kind}_body")),
            cls="lh-price feature" if kind == "hosted" else "lh-price",
        ) for kind in ("byoc", "hosted")], cls="lh-prices"),
        cls="fs-wrap"), id="pricing", cls="lh-sec")


def _dashboard_mock(lang: str):
    T = lambda key: i18n.t(key, lang)
    M = lambda key: T(f"landing.mock_{key}")
    groups = [
        ("bureau", ("overview",)),
        ("documents", ("invoices", "bills", "contacts")),
        ("money", ("banking",)),
        ("accounting", ("accounting", "tax")),
        ("payroll", ("payroll",)),
        ("settings", ("integrations",)),
    ]
    return Div(Div(
        Div(Span(cls="lh-dot"), Span(cls="lh-dot"), Span(cls="lh-dot"),
            Span(M("browser"), cls="lh-mock-url"), cls="lh-mock-bar"),
        Div(
            Div(Div(Span(cls="lh-app-dot"), Span(FASTPRODUCT.name, cls="lh-app-brand-fast"),
                    cls="lh-app-brand"),
                Span(M("sample"), cls="lh-app-meta"), cls="lh-appbar"),
            Div(*[Div(Span(T(f"nav.{group}"), cls="lh-side-label"),
                      *[Span(T(f"nav.{item}") if item != "accounting" else M("ledger"),
                             cls="lh-side-item on" if item == "overview" else "lh-side-item")
                        for item in items], cls="lh-side-group")
                  for group, items in groups], cls="lh-side"),
            Div(
                Div(M("title"), Span(M("subtitle"), cls="lh-hello-sub"), cls="lh-hello"),
                Div(*[Div(Small(M(key)), B(M(f"{key}_value")), cls="lh-kpi")
                      for key in ("open_invoices", "bank_lines", "vat_due")], cls="lh-kpis"),
                Div(
                    Div(Div(M("recent_invoices"), cls="lh-panel-title"),
                        *[Div(Div(B(M(f"invoice{n}")), Small(M(f"invoice{n}_amount")), cls="lh-row-txt"),
                              Span(M(status), cls="lh-tag"), cls="lh-row")
                          for n, status in ((1, "paid"), (2, "sent"), (3, "draft"))], cls="lh-panel"),
                    Div(Div(M("reconciliation"), cls="lh-panel-title"),
                        *[Div(Span(M(key)), I(style=f"width:{width}%"), B(M(f"{key}_value")), cls="lh-bar")
                          for key, width in (("matched", 90), ("review", 36), ("unmatched", 18))],
                        cls="lh-panel"),
                    cls="lh-panels"), cls="lh-main"),
            cls="lh-mock-body"),
        cls="lh-mock", inert=True, aria_hidden="true"),
        *[Div(Small(T(f"landing.float_{kind}")), Strong(M(value)), Span(M(detail)),
              cls=f"lh-glass lh-glass-{kind}", inert=True, aria_hidden="true")
          for kind, value, detail in (("bank", "invoice1_amount", "sample"),
                                      ("invoice", "paid", "invoice1"),
                                      ("tax", "vat_due_value", "vat_due"))],
        cls="lh-mock-wrap")


def landing_page(lang: str = i18n.DEFAULT_LANG):
    T = lambda key: i18n.t(key, lang)

    def actions(variant="primary"):
        return Div(fs_button(T("landing.hero_cta"), "/login", variant, "lg"),
                   fs_button(T("landing.view_source"), FASTPRODUCT.github_url, "ghost", "lg"),
                   cls="lh-actions")

    return public_page(
        Section(
            Div(fs_eyebrow(T("landing.hero_eyebrow"), on_ink=True),
                H1(T("landing.hero_h1"), " ", Span(T("landing.hero_highlight"), cls="lh-hi")),
                P(T("landing.hero_sub"), cls="lh-sub"), actions("ink"),
                P(T("landing.hero_trust"), cls="lh-trust"), cls="lh-hero-inner fs-wrap"),
            id="hero", cls="lh-hero"),
        Section(_dashboard_mock(lang), id="dashboard", cls="lh-demo", aria_hidden="true", inert=True),
        Section(fs_logo_strip(T("landing.suite_label"),
                             ["FastMail", "FastOffice", "FastDrive", "FastMeet", "FastHR", "FastBooks"]),
                cls="lh-suite"),
        Section(Div(Div(*[Article(
            I(f"{index:02d}", aria_hidden="true"),
            Span(T(f"landing.{key}_label"), cls="lh-feat-label"),
            H3(T(f"landing.{key}_title")), P(T(f"landing.{key}_body")), cls="lh-feat")
            for index, key in enumerate(("invoice", "reconcile", "review"), 1)],
            cls="lh-feats"), cls="fs-wrap"), id="why", cls="lh-sec"),
        Section(Div(
            Div(H2(T("landing.process_title")), P(T("landing.process_body")), cls="lh-head"),
            Ol(*[Li(Span(f"{n:02d}", cls="lh-step-number", aria_hidden="true"),
                    H3(T(f"landing.step{n}_title")), P(T(f"landing.step{n}_body")))
                 for n in range(1, 5)], cls="lh-steps"),
            cls="fs-wrap"), id="process", cls="lh-sec lh-process"),
        Section(Div(
            Div(H2(T("landing.comparison_title")), cls="lh-head"),
            Div(*[Article(H3(T(f"landing.{way}_title")),
                          Ul(*[Li(Span(symbol, aria_hidden="true"), T(f"landing.{way}{n}"))
                               for n in range(1, 5)]), cls=f"lh-compare-panel {way}")
                  for way, symbol in (("old", "✗"), ("new", "✓"))], cls="lh-comparison"),
            cls="fs-wrap"), id="comparison", cls="lh-sec"),
        Section(Div(Div(
            Div(H2(T("bureau.title")), P(T("bureau.body")),
                fs_button(T("bureau.cta"), "/login"), cls="lh-head"),
            Div(*[Article(B(T(f"bureau.{key}_title")), P(T(f"bureau.{key}_body")), cls="lh-stat-item")
                  for key in ("clients", "payroll", "matches", "tax")], cls="lh-stat-list"),
            cls="lh-stat"), cls="fs-wrap"), id="bureaus", cls="lh-sec lh-alt"),
        _pricing_section(lang),
        Section(Div(Dl(
            Div(Dt(T("landing.stats_languages")), Dd(T("landing.stats_languages_value"))),
            Div(Dt(T("landing.stats_markets")), Dd(T("landing.stats_markets_value"))),
            Div(Dt(T("pricing.byoc_eyebrow")), Dd(T("pricing.byoc_price"))),
            Div(Dt(T("pricing.hosted_eyebrow")), Dd(T("pricing.hosted_price"))),
        ), cls="fs-wrap"), id="product-facts", cls="lh-facts", aria_label=T("landing.stats_label")),
        Section(Div(
            Div(fs_eyebrow(T("landing.faq_eyebrow")), H2(T("landing.faq_title")), cls="lh-head"),
            Div(*[Details(Summary(T(f"landing.faq{n}_q")), P(T(f"landing.faq{n}_a")), cls="lh-faq", name="faq")
                  for n in range(1, 6)], cls="lh-faqs"),
            cls="fs-wrap"), id="faq", cls="lh-sec lh-alt"),
        Section(Div(Div(H2(T("landing.cta_title")), P(T("landing.cta_body")), actions(),
                        cls="lh-ctaband"), cls="fs-wrap"), id="get-started", cls="lh-close"),
        title=T("landing.title"), current="/", lang=lang,
    )


def _integration_card(item: integrations.Integration, lang: str):
    T = lambda key: i18n.t(key, lang)
    copy = i18n.integration_copy(lang, item.key)
    return Article(
        Div(
            Div(Img(src=item.logo, alt=copy.get("logo_alt", item.logo_alt), loading="lazy", cls="integration-logo"), cls="integration-logo-wrap"),
            Div(Span(" · ".join(item.markets), cls="markets"), cls="provider-meta"),
            cls="integration-head",
        ),
        H2(copy.get("name", item.name)),
        Span(copy.get("category", item.category), cls="category"),
        P(copy.get("description", item.description)),
        Div(*[Span(capability, cls="capability") for capability in copy.get("capabilities", item.capabilities)], cls="capabilities"),
        Div(
            Div(Span(T("integrations.direction")), Strong(copy.get("direction", item.direction))),
            Div(Span(T("integrations.ownership")), Strong(copy.get("ownership", item.ownership))),
            cls="ownership",
        ),
        A(T("integrations.docs"), href=item.docs_url, target="_blank", rel="noopener noreferrer", cls="docs"),
        id=item.key,
        cls="integration",
    )


def integrations_page(lang: str = i18n.DEFAULT_LANG):
    T = lambda key: i18n.t(key, lang)
    return public_page(
        Section(
            Span(T("integrations.kicker"), cls="kicker"),
            H1(T("integrations.headline")),
            P(T("integrations.lede"), cls="lede"),
            Div(
                Span(T("integrations.accounting_adapters"), cls="chip"),
                Span(T("integrations.filing_gates"), cls="chip"),
                Span(T("integrations.banking_candidate"), cls="chip"),
                cls="summary",
            ),
            cls="page-hero",
        ),
        Section(Div(*[_integration_card(item, lang) for item in integrations.CATALOGUE], cls="integration-grid"), cls="catalogue"),
        Section(Div(Strong(T("integrations.review_gate")), T("integrations.review_notice")), cls="notice"),
        title=T("integrations.title"),
        current="/integrations",
        lang=lang,
    )


def login_page(error: str = "", lang: str = i18n.DEFAULT_LANG):
    T = lambda key: i18n.t(key, lang)
    message = error.strip()[:240]
    return public_page(
        Section(
            Div(
                Span(T("login.kicker"), cls="kicker"),
                H1(T("login.headline")),
                P(T("login.body")),
                Div(message, cls="error") if message else None,
                A(T("login.continue_google") if google_auth.enabled() else T("login.not_configured"), href="/auth/google", cls="fs-btn fs-btn-ink google"),
                P(T("login.configuration_hint")) if not google_auth.enabled() else None,
                cls="auth-card",
            ),
            cls="auth-wrap",
        ),
        title=T("login.title"),
        current="/login",
        lang=lang,
    )


def workspace_page(user: dict, lang: str = "en"):
    T = lambda key: i18n.t(key, lang)
    display_name = user.get("name") or user.get("email") or ""
    groups = [
        ("bureau", [("overview", "overview")]),
        ("documents", [("invoices", "invoices"), ("bills", "bills"), ("contacts", "contacts")]),
        ("automation", [("recurring", "recurring")]),
        ("money", [("banking", "banking")]),
        ("accounting", [("accounting", "accounting"), ("tax", "tax")]),
        ("payroll", [("payroll", "payroll")]),
        ("settings", [("integrations", "integrations")]),
    ]
    # Escape script delimiters even when catalogue copy contains HTML punctuation.
    dictionary = {**i18n.catalog("en"), **i18n.catalog(lang)}
    dictionary["workspace"] = {**i18n.catalog("en").get("workspace", {}), **i18n.catalog(lang).get("workspace", {})}
    payload = json.dumps(dictionary, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return (
        Title(f"{T('nav.workspace')} · FastAccounts"),
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Link(rel="icon", type="image/svg+xml", href="/static/favicon.svg"),
        Link(rel="stylesheet", href="/static/app.css"),
        Div(
            Aside(
                A(Span("F", cls="app-mark"), Span("FastAccounts"), href="/app", cls="app-brand"),
                A(version.label(), href="/healthz", title=version.detail(), cls="app-version", data_testid="app-version"),
                Div(
                    Button(T("actions.create_organisation"), id="org-trigger", cls="org-trigger", type="button", aria_haspopup="menu", aria_expanded="false", aria_controls="org-menu"),
                    Div(id="org-menu", cls="org-menu", role="menu", hidden=True),
                    cls="org-switcher",
                ),
                Nav(*[
                    Div(Span(T(f"nav.{group}"), cls="nav-group"), *[
                        A(T(f"nav.{label}"), href=f"#{view}", data_view=view, cls="app-nav")
                        for view, label in items
                    ]) for group, items in groups
                ], cls="app-nav-list", aria_label=T("nav.workspace")),
                Div(
                    A(T("nav.public_site"), href="/"),
                    Div(Span(display_name[:1].upper(), cls="user-avatar"), Div(Strong(display_name), A(T("nav.sign_out"), href="/logout")), cls="user-card"),
                    cls="app-side-links",
                ), cls="app-sidebar",
            ),
            Div(
                Header(
                    Div(Button("☰", id="menu-toggle", aria_label=T("nav.open_navigation"), cls="menu-toggle"), Span(T("nav.workspace"), cls="workspace-label"), Strong(id="current-org")),
                    Div(*[A(info["native"], href=f"/set-lang/{code}?next=/app", lang=code, aria_current="true" if code == lang else "false") for code, info in i18n.LANGUAGES.items() if code in ("en", "et")], cls="workspace-languages", aria_label=T("language.choose")),
                    cls="app-topbar",
                ),
                Main(Div(Div(cls="skeleton rows-skeleton"), id="app-content", aria_live="polite"), cls="app-main"),
                cls="app-body",
            ),
            id="workspace-app", data_user_email=user.get("email", ""), data_lang=lang, lang=lang, cls="app-shell",
        ),
        Div(id="toasts", cls="toasts", aria_live="polite"),
        Script(NotStr(f"window.FASTACCOUNTS_I18N = {payload};")),
        Script(src="/static/app.js"),
    )
