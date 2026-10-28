/* FastAccounts workspace: the server owns all accounting calculations and postings. */
(() => {
  "use strict";
  const app = document.getElementById("workspace-app"),
    content = document.getElementById("app-content");
  const catalog = window.FASTACCOUNTS_I18N || {},
    lang = app.dataset.lang || "en";
  const t = (k) =>
      catalog.workspace?.[k] ||
      (typeof k === "string" && k.endsWith(" is missing an EU VAT number")
        ? k.slice(0, -" is missing an EU VAT number".length) +
          (catalog.workspace?.[" is missing an EU VAT number"] ||
            " is missing an EU VAT number")
        : k),
    esc = (v) =>
      String(v ?? "").replace(
        /[&<>"']/g,
        (c) =>
          ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
          })[c],
      ),
    tr = (k) => esc(t(k)),
    // Server errors may be "<employee>: <catalogue message>< EUR figures>".
    translateError = (message) => {
      if (catalog.workspace?.[message]) return t(message);
      const named = /^(.+?): (.+)$/.exec(String(message ?? ""));
      if (!named) return message;
      const [, key, figures = ""] = /^(.*?)((?: EUR | \().*)?$/.exec(named[2]);
      return catalog.workspace?.[key]
        ? `${named[1]}: ${t(key)}${figures}`
        : message;
    };
  let csrf = "",
    organisations = [],
    org = null,
    generation = 0,
    reportTab = "trial-balance",
    contactFilter = "All";
  const documentFilters = new Map();
  const listFilters = (c, kind) => documentFilters.get(`${c.oid}:${kind}`) || {};
  const listQuery = (c, kind) => {
    const query = new URLSearchParams(Object.entries(listFilters(c, kind)).filter(([, v]) => v));
    return query.size ? `?${query}` : "";
  };
  function documentFilterControls(c, kind, contacts) {
    const values = listFilters(c, kind), sales = kind === "invoices";
    const choice = (label, name, options) => `<label>${tr(label)}<select data-document-filter="${name}"><option value="">${tr("All")}</option>${options.map(([value, text]) => `<option value="${esc(value)}" ${values[name] === value ? "selected" : ""}>${esc(text)}</option>`).join("")}</select></label>`;
    const input = (label, name, type) => `<label>${tr(label)}<input type="${type}" data-document-filter="${name}" value="${esc(values[name] || "")}"></label>`;
    const statuses = sales ? ["Draft", "Issued", "Overdue", "Part Paid", "Paid", "Voided", "Credited"] : ["Draft", "In Review", "Approved", "Part Paid", "Paid", "Rejected", "Voided"];
    return `<div class="form-grid document-list-filters">` +
      choice("Status", "status", statuses.map((v) => [v, t(v)])) +
      choice(sales ? "Customer" : "Supplier", "contact_id", contacts.filter((v) => [sales ? "customer" : "supplier", "both"].includes(v.contact_type)).map((v) => [v.id, v.name])) +
      input("Date from", "date_from", "date") + input("Date to", "date_to", "date") +
      input("Search", "q", "search") + input("Currency", "currency", "text") +
      `</div><div class="actions">${link("Export CSV", `/api${c.url(`/${kind}/export.csv`)}${listQuery(c, kind)}`)}${link("Export Excel", `/api${c.url(`/${kind}/export.xlsx`)}${listQuery(c, kind)}`)}</div>`;
  }
  function bindDocumentFilters(c, kind) {
    content.querySelectorAll("[data-document-filter]").forEach((control) => {
      control.onchange = async () => {
        const values = { ...listFilters(c, kind), [control.dataset.documentFilter]: control.value };
        documentFilters.set(`${c.oid}:${kind}`, values);
        await render();
      };
    });
  }
  const payBases = [
      ["monthly", "Monthly salary"],
      ["hourly", "Hourly pay"],
      ["board_fee", "Board member fee"],
      ["income_line", "Income lines"],
    ],
    // Codes match payroll.SOCIAL_TAX_MINIMUM_EXEMPTIONS (EMTA, SMS § 2 lg 3–4).
    socialTaxExemptions = [
      ["", "None – minimum obligation applies"],
      ["state_pension", "State pension recipient"],
      ["reduced_work_ability", "Partial or no work ability"],
      ["child_care", "Raising a child under 3 or three or more children under 19"],
      ["student", "Pupil or student"],
      ["previously_unemployed", "Registered unemployed for 6+ months before hiring"],
      ["shortened_working_time", "Shortened working time (minors aged 7–17, teachers)"],
      ["local_council_member", "Local council member"],
      ["ship_crew", "Ship crew member"],
      ["foreign_service_spouse", "Foreign-service spouse allowance"],
      ["long_term_sick_leave_work", "Working on long-term sick leave"],
      ["absent_whole_month", "Absent for the whole month (leave, sickness, strike, service)"],
      ["multiple_employers", "Another employer applies the basic exemption"],
      ["board_member", "Board member – no minimum obligation"],
    ],
    exemptionLabel = (code) =>
      t(code === "income_line" ? "Income lines" : (socialTaxExemptions.find(([v]) => v === code) || [, code])[1]),
    partTime = (x) =>
      x.fte && Number(x.fte) < 1
        ? `<small>${tr("Part-time")} ${esc(num(x.fte))}</small>`
        : "",
    hoursNote = (x) =>
      x.pay_basis === "hourly" && x.hours != null
        ? `<small>${esc(money(x.hourly_rate, "EUR"))} × ${esc(num(x.hours))} ${tr("Hours").toLowerCase()}</small>`
        : x.pay_basis === "monthly" && x.worked_days != null
          ? `<small>${tr("Worked days / norm days")}: ${num(x.worked_days)} / ${num(x.norm_days)}</small>`
          : "";
  const payrollSupported = (organisation) =>
    organisation?.country_code === "EE" && organisation?.base_currency === "EUR";
  const today = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  const money = (v, c) =>
    v == null
      ? "–"
      : new Intl.NumberFormat(lang === "et" ? "et-EE" : "en-GB", {
          style: "currency",
          currency: c || org?.base_currency || "EUR",
        }).format(Number(v));
  const date = (v) =>
    v
      ? new Intl.DateTimeFormat(lang === "et" ? "et-EE" : "en-GB").format(
          new Date(String(v).slice(0, 10) + "T12:00:00"),
        )
      : "–";
  const num = (v) => new Intl.NumberFormat(lang).format(Number(v || 0)),
    path = (s) => `/organisations/${encodeURIComponent(org.id)}${s}`;
  // FastAccounts line icons: 24px grid, 1.75 stroke, round caps and joins (docs/brand/icons.md).
  const ICONS = {
    calendar: "M4 6h16v14H4z M4 10h16 M8 3.5V7 M16 3.5V7",
    wrench: "M14.5 6.5a4.5 4.5 0 0 0-6 6L4 17l3 3 4.5-4.5a4.5 4.5 0 0 0 6-6L14 12l-2.5-2.5z",
    team: "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M2.5 20v-1a5 5 0 0 1 8-4 M17 13.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M13.5 20v-1a5 5 0 0 1 8-4",
    home: "M4 10.5 12 4l8 6.5V20H4z M10 20v-5h4v5",
    invoice: "M6 3h8l4 4v14H6z M14 3v4h4 M9 11h6 M9 14.5h6 M9 18h3",
    quote: "M4 5h16v11H10l-4.5 3.5V16H4z M8 9h8 M8 12.5h5",
    bill: "M6 3h12v18l-2-1.5-2 1.5-2-1.5-2 1.5-2-1.5L6 21z M9 8h6 M9 11.5h6 M9 15h3",
    periodised: "M4 6h16v14H4z M4 10h16 M8 3.5V7 M16 3.5V7 M8 15h7.5 M13.5 13l2 2-2 2",
    contacts:
      "M15.5 20v-1.5a4 4 0 0 0-4-4h-5a4 4 0 0 0-4 4V20 M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7 M16 4.3a3.5 3.5 0 0 1 0 6.4 M21.5 20v-1.5a4 4 0 0 0-3-3.9",
    recurring:
      "M4.5 12a7.5 7.5 0 0 1 13-5.1L19.5 9 M19.5 4.5V9H15 M19.5 12a7.5 7.5 0 0 1-13 5.1L4.5 15 M4.5 19.5V15H9",
    bank: "M3.5 9.5 12 4l8.5 5.5z M5.5 12.5v5 M10 12.5v5 M14 12.5v5 M18.5 12.5v5 M3.5 20.5h17",
    ledger: "M12 4v16 M8.5 20h7 M5 7h14 M7 7l-3 6a3 3 0 0 0 6 0z M17 7l-3 6a3 3 0 0 0 6 0z",
    "cash-flow": "M7.5 20V4 M4 7.5 7.5 4 11 7.5 M16.5 4v16 M13 16.5l3.5 3.5 3.5-3.5",
    asset: "M12 3 20 7.5v9L12 21l-8-4.5v-9z M4 7.5l8 4.5 8-4.5 M12 12v9",
    tax: "M6 3h8l4 4v14H6z M14 3v4h4 M9 17.5l6-7 M9.5 11h.01 M14.5 17h.01",
    payroll: "M3 7h18v10H3z M12 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5 M6.5 10v4 M17.5 10v4",
    link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1 M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
    import: "M12 4v10 M8 10.5l4 4 4-4 M4 14v4.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V14",
    card: "M3 6h18v12H3z M3 10h18 M7 14.5h3",
    bell: "M6 16v-5a6 6 0 0 1 12 0v5l1.5 2h-15z M10 20.5a2 2 0 0 0 4 0",
    exchange: "M4 8h14 M14.5 4.5 18 8l-3.5 3.5 M20 16H6 M9.5 12.5 6 16l3.5 3.5",
    tag: "M3.5 11.5V4h7.5l9 9-7.5 7.5z M8 8.5h.01",
    appearance: "M4 7h9 M17 7h3 M4 17h3 M11 17h9 M15 4.5v5 M9 14.5v5",
    assistant: "M11 3.5c.6 3.9 2.6 5.9 6.5 6.5-3.9.6-5.9 2.6-6.5 6.5-.6-3.9-2.6-5.9-6.5-6.5 3.9-.6 5.9-2.6 6.5-6.5z M18.5 15.5v5 M16 18h5",
    send: "M12 19V5 M5 12l7-7 7 7",
    gear: "M9 3h6l.5 3 2 .9 2.5-1.4 3 5-2.5 1.5v2L23 15.5l-3 5-2.5-1.4-2 .9-.5 3H9l-.5-3-2-.9L4 20.5l-3-5L3.5 14v-2L1 10.5l3-5L6.5 7l2-.9z M15 13a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
    paperclip: "M8 12l6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l8-8 M6 14l8-8",
    document: "M6 3h8l4 4v14H6z M14 3v4h4",
    plus: "M12 5v14 M5 12h14",
    "pay-types": "M4 4h16v16H4z M8 8h.01 M11 8h5 M8 12h.01 M11 12h5 M8 16h.01 M11 16h5",
    close: "M6 6l12 12 M18 6 6 18",
    menu: "M4 7h16 M4 12h16 M4 17h16",
    external: "M13.5 4H20v6.5 M20 4l-9 9 M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
    shield: "M12 3.5 19 6v5.5c0 4.5-3 7.6-7 9-4-1.4-7-4.5-7-9V6z M9 12l2 2 4-4",
    check: "M5 12.5l4.5 4.5L19 7.5",
    "chevron-down": "M6 9l6 6 6-6",
  };
  const NAV_ICONS = {
    overview: "home", invoices: "invoice", quotes: "quote", bills: "bill",
    periodised: "periodised", contacts: "contacts", recurring: "recurring",
    banking: "bank", accounting: "ledger", "cash-flow": "cash-flow",
    "fixed-assets": "asset", tax: "tax", payroll: "payroll", integrations: "link",
    imports: "import", "payment-methods": "card", "reminder-rules": "bell",
    "exchange-rates": "exchange", objects: "tag", documents: "appearance",
    periods: "calendar", "payment-types": "pay-types",
    maintenance: "wrench",
    groups: "team",
  };
  const icon = (name = "document") =>
    `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${ICONS[name] || ICONS.document}"/></svg>`;
  const button = (label, action, primary = false, attrs = "") =>
    `<button type="button" class="button${primary ? " primary" : ""}" data-action="${action}" ${attrs}>${tr(label)}</button>`;
  const link = (label, href, attrs = "") =>
    `<a class="button" href="${esc(href)}" ${attrs}>${tr(label)}</a>`;
  const pill = (v) => {
    const s = String(v || ""),
      tone =
        {
          Draft: "neutral",
          Issued: "info",
          "In Review": "warning",
          Approved: "success",
          "Approved & posted": "success",
          Paid: "success",
          "Part Paid": "warning",
          Reconciled: "success",
          "In bank": "info",
          Overdue: "danger",
          Active: "success",
          Configured: "info",
          Connected: "success",
          Disconnected: "warning",
          "Reauth Required": "warning",
          Pending: "warning",
          Rejected: "neutral",
          Applied: "success",
          "Review Required": "warning",
          Completed: "success",
          Sent: "success",
          Failed: "danger",
          Posted: "success",
          Reviewed: "success",
          Suggested: "info",
        }[s] || "neutral";
    return `<span class="status-pill ${tone}">${tr(s)}</span>`;
  };
  const td = (v, cls = "") => `<td class="${cls}">${v}</td>`,
    cash = (v, c) => td(esc(money(v, c)), "numeric"),
    row = (cells, cls = "") => `<tr${cls ? ` class="${cls}"` : ""}>${cells.join("")}</tr>`;
  const empty = (title = "Nothing here yet", action = "") =>
    `<div class="empty">${icon()}<h3>${tr(title)}</h3><p>${tr("Your records will appear here as you work.")}</p>${action}</div>`;
  const table = (heads, rows, action = "") =>
    rows.length
      ? `<div class="table-wrap"><table><thead><tr>${heads.map((h) => `<th class="${Array.isArray(h) ? "numeric" : ""}">${tr(Array.isArray(h) ? h[0] : h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`
      : empty("Nothing here yet", action);
  const page = (title, subtitle, actions = "", body = "") =>
    `<div class="page-title"><div><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="actions">${actions}</div></div>${body}`;
  const skeleton = () =>
    `<div class="skeleton title-skeleton"></div><div class="kpis">${Array.from({ length: 4 }, () => '<div class="skeleton card-skeleton"></div>').join("")}</div><div class="skeleton rows-skeleton"></div>`;
  const kpi = (label, value, sub = "") =>
    `<article class="kpi"><span>${tr(label)}</span><strong>${esc(value)}</strong><small>${tr(sub)}</small></article>`;
  function toast(message, variant = "success") {
    const el = document.createElement("div");
    el.className = `toast ${variant}`;
    el.setAttribute("role", variant === "error" ? "alert" : "status");
    el.textContent = message;
    document.getElementById("toasts").append(el);
    setTimeout(() => el.remove(), 4000);
  }
  async function api(url, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData))
      headers["Content-Type"] = "application/json";
    if ((options.method || "GET") !== "GET") headers["X-CSRF-Token"] = csrf;
    const r = await fetch("/api" + url, { ...options, headers });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      const e = new Error(
        Array.isArray(d.detail)
          ? d.detail
              .map((x) => `${x.loc?.slice(1).join(".")}: ${x.msg}`)
              .join("; ")
          : d.detail || t("Request failed. Please try again."),
      );
      e.message = translateError(e.message);
      e.status = r.status;
      e.detail = d.detail;
      throw e;
    }
    if (r.status === 204) return null;
    return r.headers.get("content-type")?.includes("json") ? r.json() : r;
  }
  const post = (url, data, method = "POST") =>
    api(url, {
      method,
      ...(data === undefined ? {} : { body: JSON.stringify(data) }),
    });
  async function optionalPayroll(url) {
    try {
      return await api(url);
    } catch (e) {
      if (e.status !== 404) throw e;
      return null;
    }
  }
  function closeDialog(el) {
    if (el.dataset.pending === "true") return;
    el.remove();
    if (!document.querySelector(".dialog"))
      document.body.classList.remove("dialog-open");
    el._returnFocus?.focus();
  }
  function dialog(title, body) {
    const el = document.createElement("div"),
      id = `dialog-${Date.now()}`;
    el.className = "dialog";
    el._originOrg = org?.id;
    el._originView = location.hash;
    el._returnFocus = document.activeElement;
    el.innerHTML = `<section class="dialog-card" role="dialog" aria-modal="true" aria-labelledby="${id}"><div class="dialog-head"><h2 id="${id}">${tr(title)}</h2><button type="button" class="icon-button" data-close aria-label="${tr("Close")}">${icon("close")}</button></div>${body}</section>`;
    el.addEventListener("click", (e) => {
      if (e.target === el || e.target.closest("[data-close]")) closeDialog(el);
    });
    document.body.append(el);
    document.body.classList.add("dialog-open");
    el.querySelector("input,select,button")?.focus();
    return el;
  }
  function confirmAction(title, body, action) {
    const d = dialog(
      title,
      `<p class="confirm-copy">${body}</p><div class="dialog-actions">${button("Cancel", "cancel")}${button("Confirm", "confirm", true)}</div>`,
    );
    d.querySelector("[data-action=cancel]").onclick = () => closeDialog(d);
    d.querySelector("[data-action=confirm]").onclick = async (e) => {
      e.target.disabled = true;
      d.dataset.pending = "true";
      try {
        await action();
        d.dataset.pending = "false";
        closeDialog(d);
      } catch (x) {
        toast(x.message, "error");
        d.dataset.pending = "false";
        e.target.disabled = false;
      }
    };
  }
  const field = (label, name, value = "", type = "text", attrs = "") =>
    `<label>${tr(label)}<input name="${name}" type="${type}" value="${esc(value)}" ${attrs}><span class="field-error" data-error="${name}"></span></label>`;
  const select = (label, name, items, value = "") =>
    `<label>${tr(label)}<select name="${name}">${items.map(([v, l]) => `<option value="${esc(v)}" ${String(value) === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select><span class="field-error" data-error="${name}"></span></label>`;
  const check = (label, name, v) =>
    `<label class="check"><input type="checkbox" name="${name}" ${v ? "checked" : ""}>${tr(label)}</label>`;
  const form = (fields, label = "Save") =>
    `<form novalidate><div class="form-grid">${fields}</div><p class="form-error" role="alert"></p><div class="dialog-actions">${button("Cancel", "cancel")}<button class="button primary" type="submit">${tr(label)}</button></div></form>`;
  function bindForm(d, submit) {
    const f = d.querySelector("form");
    f.querySelector("[data-action=cancel]")?.addEventListener("click", () =>
      closeDialog(d),
    );
    f.onsubmit = async (e) => {
      e.preventDefault();
      f.querySelectorAll(".field-error").forEach((x) => (x.textContent = ""));
      f.querySelector(".form-error").textContent = "";
      let valid = true;
      for (const input of f.elements) {
        if (input.willValidate && !input.validity.valid) {
          valid = false;
          const help = f.querySelector(`[data-error="${input.name}"]`);
          if (help)
            help.textContent = t(
              input.validity.valueMissing
                ? "This field is required."
                : "Enter a valid value.",
            );
          input.setAttribute("aria-invalid", "true");
        } else input.removeAttribute("aria-invalid");
      }
      if (!valid) {
        f.querySelector("[aria-invalid]")?.focus();
        return;
      }
      const b = f.querySelector("[type=submit]");
      b.disabled = true;
      try {
        await submit(Object.fromEntries(new FormData(f)), f);
      } catch (x) {
        f.querySelector(".form-error").textContent = x.message;
        toast(x.message, "error");
        if (Array.isArray(x.detail))
          for (const item of x.detail) {
            const help = f.querySelector(`[data-error="${item.loc?.at(-1)}"]`);
            if (help) help.textContent = item.msg;
          }
      } finally {
        b.disabled = false;
        if (d.classList.contains("dialog") && d._originView !== undefined) {
          d.dataset.pending = "false";
          if (d._originView !== location.hash || d._originOrg !== org?.id) closeDialog(d);
        }
      }
    };
  }
  async function saved(d) {
    closeDialog(d);
    toast(t("Saved successfully"));
    if (d._originOrg === org?.id && d._originView === location.hash)
      await render();
  }
  function bindActions(root, handlers) {
    root.querySelectorAll("[data-action]").forEach((b) => {
      if (handlers[b.dataset.action])
        b.onclick = async () => {
          try {
            await handlers[b.dataset.action](b);
          } catch (e) {
            toast(e.message, "error");
          }
        };
    });
  }
  function switchOrg(id) {
    const selected = organisations.find((o) => String(o.id) === String(id));
    if (!selected) return;
    generation++;
    document.querySelectorAll(".dialog").forEach(closeDialog);
    org = selected;
    localStorage.setItem("fastaccounts_org", org.id);
    document.getElementById("org-menu").hidden = true;
    document
      .getElementById("org-trigger")
      .setAttribute("aria-expanded", "false");
    drawOrgSwitcher();
    render();
  }
  function drawOrgSwitcher() {
    document.getElementById("org-trigger").innerHTML =
      `<span class="org-avatar">${esc(org?.name?.slice(0, 1) || "F")}</span><span class="org-label">${esc(org?.name || t("Create organisation"))}<small>${tr("Client workspace")}</small></span><span aria-hidden="true">⌃</span>`;
    document.getElementById("org-menu").innerHTML =
      organisations
        .map(
          (o) =>
            `<button type="button" role="menuitem" data-org="${esc(o.id)}"><span>${esc(o.name)}</span><span class="country-badge">${esc(o.country_code)}</span></button>`,
        )
        .join("") +
      `<button type="button" role="menuitem" data-create-org>${icon("plus")}${tr("Create organisation")}</button>` +
      `<button type="button" role="menuitem" data-demo-org>${icon("plus")}${tr("Load demo company")}</button>`;
    document
      .querySelectorAll("[data-org]")
      .forEach((b) => (b.onclick = () => switchOrg(b.dataset.org)));
    document.querySelector("[data-create-org]").onclick = () => {
      document.getElementById("org-menu").hidden = true;
      organisationDialog();
    };
    document.querySelector("[data-demo-org]").onclick = loadDemoCompany;
    document.getElementById("current-org").textContent =
      org?.name || t("Workspace");
  }
  async function boot() {
    ({ csrf_token: csrf } = await api("/csrf"));
    organisations = await api("/organisations");
    org =
      organisations.find(
        (o) => String(o.id) === localStorage.getItem("fastaccounts_org"),
      ) || organisations[0];
    drawOrgSwitcher();
    await render();
  }
  async function render() {
    syncCopilot();
    const ticket = ++generation,
      route = location.hash.slice(1) || "overview",
      routeParts = route.split("/").filter(Boolean),
      view = routeParts[0] || "overview";
    document.querySelectorAll('.dialog').forEach((d) => {
      if (d._originView === undefined || d.dataset.pending === "true") return;
      if (d._originView !== location.hash || d._originOrg !== org?.id) closeDialog(d);
    });
    app.classList.remove("menu-open");
    document.querySelectorAll(".app-nav").forEach((a) => {
      const disabled = ["payroll", "payment-types"].includes(a.dataset.view) && !payrollSupported(org);
      a.setAttribute("aria-disabled", String(disabled));
      a.style.opacity = disabled ? "0.45" : "";
      a.title = disabled ? t("Payroll is currently available for Estonian books.") : "";
      a.classList.toggle("active", a.dataset.view === view);
      a.setAttribute(
        "aria-current",
        a.dataset.view === view ? "page" : "false",
      );
    });
    content.setAttribute("aria-busy", "true");
    content.innerHTML = skeleton();
    if (!org) {
      onboarding();
      content.removeAttribute("aria-busy");
      return;
    }
    const oid = org.id,
      c = {
        oid,
        payrollSupported: payrollSupported(org),
        route: routeParts.slice(1).map((part) => {
          try {
            return decodeURIComponent(part);
          } catch (_) {
            return part;
          }
        }),
        url: (s) => `/organisations/${encodeURIComponent(oid)}${s}`,
        mount: (html) => {
          if (ticket !== generation) return false;
          content.innerHTML = html;
          return true;
        },
      };
    try {
      await (views[view] || views.overview)(c);
    } catch (e) {
      if (ticket === generation) {
        toast(e.message, "error");
        content.innerHTML = page(
          t("Unable to load this view"),
          e.message,
          button("Try again", "retry"),
        );
        bindActions(content, { retry: render });
      }
    } finally {
      if (ticket === generation) content.removeAttribute("aria-busy");
    }
  }
  function organisationFields() {
    return (
      field(
        "Organisation name",
        "name",
        "",
        "text",
        'required maxlength="180"',
      ) +
      select(
        "Country",
        "country_code",
        [
          ["EE", t("Estonia")],
          ["UK", t("United Kingdom")],
        ],
        lang === "et" ? "EE" : "UK",
      ) +
      select("Entity type", "entity_type", []) +
      field("Registration number", "registration_no")
    );
  }
  function wireOrganisation(d, onComplete) {
    const f = d.querySelector("form");
    const update = () => {
      f.elements.entity_type.innerHTML = (
        f.elements.country_code.value === "EE"
          ? [
              ["EE_OU", t("Estonian OÜ")],
              ["EE_FIE", t("Estonian FIE")],
            ]
          : [
              ["UK_COMPANY", t("UK company")],
              ["UK_SOLE_TRADER", t("UK sole trader")],
            ]
      )
        .map(([v, l]) => `<option value="${v}">${esc(l)}</option>`)
        .join("");
    };
    update();
    f.elements.country_code.onchange = update;
    bindForm(d, async (data) => {
      const created = await post("/organisations", data);
      localStorage.setItem("fastaccounts_org", created.id);
      onComplete();
      await boot();
    });
  }
  function organisationDialog() {
    const d = dialog(
      "Create organisation",
      form(organisationFields(), "Create books"),
    );
    wireOrganisation(d, () => closeDialog(d));
  }
  function loadDemoCompany() {
    document.getElementById("org-menu").hidden = true;
    confirmAction(
      "Load demo company",
      tr("Creates a clearly labelled demo company with synthetic invoices, bills, bank transactions and payroll in your account. Your other companies are not changed."),
      async () => {
        const created = await post("/demo-organisation", {});
        localStorage.setItem("fastaccounts_org", created.id);
        toast(t("Demo company ready"));
        await boot();
      },
    );
  }
  function onboarding() {
    content.innerHTML = `<div class="onboarding"><section><img class="large-mark" src="/static/brand/fastaccounts-mark.svg" alt="" width="48" height="48"><h1>${tr("Every client. One clear workspace.")}</h1><p>${tr("Keep client books, bank reviews and payroll together.")}</p><ul><li>${tr("Separate books for every organisation")}</li><li>${tr("Clear approvals before anything posts")}</li><li>${tr("UK and Estonian accounting in one place")}</li></ul></section><section class="card"><h2>${tr("Create your first organisation")}</h2>${form(organisationFields(), "Create books")}<p class="muted">${tr("Prefer to look around first?")}</p>${button("Load demo company", "loadDemoCompany")}</section></div>`;
    content.querySelector("[data-action=cancel]").remove();
    wireOrganisation(content, () => {});
    bindActions(content, { loadDemoCompany });
  }
  // Aggregate displayed monetary values in integer cents; the API owns all postings.
  const cents = (value) => {
    const text = String(value ?? 0),
      negative = text.startsWith("-");
    const [whole, fraction = ""] = text.replace("-", "").split(".");
    return (
      (BigInt(whole || 0) * 100n +
        BigInt(fraction.padEnd(2, "0").slice(0, 2))) *
      (negative ? -1n : 1n)
    );
  };
  const decimal = (value) =>
    `${value < 0n ? "-" : ""}${(value < 0n ? -value : value) / 100n}.${String((value < 0n ? -value : value) % 100n).padStart(2, "0")}`;
  const outstanding = (rows, statuses) =>
    decimal(
      rows
        .filter((x) => statuses.includes(x.status))
        .reduce((sum, x) => sum + cents(x.total) - cents(x.paid_total), 0n),
    );
  const invoiceRows = (rows) =>
    rows.map((x) =>
      row([
        td(esc(x.number || t("Draft"))),
        td(esc(x.contact_name)),
        td(date(x.issue_date), "numeric"),
        td(pill(x.status)),
        cash(x.total, x.currency),
      ]),
    );
  function chart(invoices, bank) {
    const months = Array.from({ length: 6 }, (_, i) => {
      const d = new Date();
      d.setDate(1);
      d.setMonth(d.getMonth() - 5 + i);
      return {
        key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`,
        label: new Intl.DateTimeFormat(lang, { month: "short" }).format(d),
      };
    });
    const series = months.map((m) => ({
      ...m,
      revenue: invoices
        .filter(
          (x) =>
            ["Issued", "Part Paid", "Paid", "Credited"].includes(x.status) &&
            x.issue_date?.startsWith(m.key),
        )
        .reduce(
          (s, x) =>
            s +
            (x.document_type === "credit_note" ? -1 : 1) *
              Number(x.subtotal ?? x.total ?? 0),
          0,
        ),
      cash: bank
        .filter((x) => x.booking_date?.startsWith(m.key))
        .reduce((s, x) => s + Number(x.amount || 0), 0),
    }));
    if (!series.some((x) => x.revenue || x.cash))
      return `<p class="chart-empty">${tr("No activity in the last six months.")}</p>`;
    const max = Math.max(
      1,
      ...series.flatMap((x) => [Math.abs(x.revenue), Math.abs(x.cash)]),
    );
    return `<div class="chart-legend"><span>${tr("Invoiced revenue")}</span><span>${tr("Net bank movement")}</span></div><svg class="bar-chart" viewBox="0 0 680 230" role="img" aria-label="${tr("Last six months")}"><text x="4" y="18">${esc(money(max))}</text><text x="4" y="208">${esc(money(-max))}</text><line x1="90" y1="115" x2="665" y2="115" stroke="var(--neutral-200)"/><text x="4" y="119">0</text>${series
      .map((x, i) => {
        const bx = 110 + i * 92;
        return `<g><title>${esc(x.label)}: ${tr("Invoiced revenue")} ${esc(money(x.revenue))}; ${tr("Net bank movement")} ${esc(money(x.cash))}</title><rect x="${bx}" y="${115 - (Math.max(x.revenue, 0) / max) * 90}" width="24" height="${(Math.abs(x.revenue) / max) * 90}" rx="3" fill="var(--accent)"/><rect x="${bx + 28}" y="${x.cash >= 0 ? 115 - (x.cash / max) * 90 : 115}" width="24" height="${(Math.abs(x.cash) / max) * 90}" rx="3" fill="var(--accent)" opacity=".3"/><text x="${bx + 26}" y="218" text-anchor="middle">${esc(x.label)}</text></g>`;
      })
      .join("")}</svg>`;
  }
  let copilotDrawer, copilotBody, copilotToggle, copilotOrg, copilotTicket = 0, copilotReturnFocus;
  const copilotMac = /mac/i.test(navigator.userAgentData?.platform || navigator.platform);
  const copilotShortcut = copilotMac ? '⌘/' : 'Ctrl+/';
  const copilotHintKey = 'fastaccounts_copilot_shortcut_hint_seen';
  let copilotHintSeen = false;
  const currentPage = () => {
    const key = location.hash.slice(1).split('/')[0] || 'overview';
    return Object.hasOwn(views, key) ? key : 'overview';
  };
  function closeCopilot() {
    if (!copilotDrawer || copilotDrawer.hidden) return;
    copilotDrawer.hidden = true;
    copilotToggle.setAttribute('aria-expanded', 'false');
    (copilotReturnFocus?.isConnected ? copilotReturnFocus : copilotToggle).focus();
  }
  function openCopilot() {
    if (!org || copilotToggle.hidden || !copilotDrawer.hidden) return;
    copilotReturnFocus = document.activeElement;
    copilotDrawer.hidden = false;
    copilotToggle.setAttribute('aria-expanded', 'true');
    if (!copilotHintSeen) {
      try { copilotHintSeen = !!localStorage.getItem(copilotHintKey); } catch {}
      if (!copilotHintSeen) {
        const hint = document.createElement('div');
        hint.className = 'copilot-shortcut-hint';
        hint.innerHTML = `<p>${tr('Tip: press {shortcut} to open or close the copilot from any page.').replace('{shortcut}', `<kbd>${copilotShortcut}</kbd>`)}</p><button type="button" class="button" data-copilot-hint-dismiss>${tr('Got it')}</button>`;
        copilotDrawer.querySelector('.copilot-description').after(hint);
        hint.querySelector('button').onclick = () => hint.remove();
        copilotHintSeen = true;
        try { localStorage.setItem(copilotHintKey, 'true'); } catch {}
      }
    }
    copilotDrawer.querySelector('[data-copilot-close]').focus();
    if (!copilotBody.childElementCount) loadCopilot();
    else scrollCopilot();
  }
  function toggleCopilot() {
    if (copilotDrawer.hidden) openCopilot();
    else closeCopilot();
  }
  function syncCopilot() {
    if (!copilotDrawer) {
      const shell = document.createElement('div');
      shell.innerHTML = `<button type="button" class="button primary copilot-toggle" aria-label="${tr('Open AI copilot')}" aria-controls="copilot-drawer" aria-expanded="false">${icon('assistant')}${tr('AI copilot')}</button>` +
        `<aside id="copilot-drawer" class="copilot-drawer" role="dialog" aria-labelledby="copilot-title" hidden><header class="copilot-header"><h2 id="copilot-title">${tr('AI copilot')}</h2><button type="button" class="button" data-copilot-gear hidden aria-label="${tr('Copilot administration')}" aria-controls="copilot-admin" aria-expanded="false">${icon('gear')}</button><button type="button" class="button" data-copilot-close aria-label="${tr('Close AI copilot')}">&times;</button></header>` +
        `<p class="muted copilot-description">${tr('Ask about your books, scan documents and draft staged imports. The copilot never changes records on its own.')}</p><div class="copilot-body"></div></aside>`;
      app.append(shell);
      copilotDrawer = shell.querySelector('#copilot-drawer');
      copilotBody = shell.querySelector('.copilot-body');
      copilotToggle = shell.querySelector('.copilot-toggle');
      copilotToggle.setAttribute('aria-keyshortcuts', copilotMac ? 'Meta+/' : 'Control+/');
      copilotToggle.title = t('Open AI copilot ({shortcut})').replace('{shortcut}', copilotShortcut);
      shell.querySelector('[data-copilot-close]').title = t('Close AI copilot ({shortcut})').replace('{shortcut}', copilotShortcut);
      copilotToggle.onclick = toggleCopilot;
      shell.querySelector('[data-copilot-close]').onclick = closeCopilot;
      shell.querySelector('[data-copilot-gear]').onclick = () => {
        const panel = copilotBody.querySelector('[data-copilot-admin]');
        if (panel) panel.open = !panel.open;
      };
      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !document.querySelector('.dialog')) closeCopilot();
        if (event.key === '/' && (copilotMac ? event.metaKey : event.ctrlKey) &&
            !event.altKey && org && !copilotToggle.hidden &&
            !document.querySelector('.dialog')) {
          event.preventDefault();
          toggleCopilot();
        }
      });
    }
    copilotToggle.hidden = !org;
    if (copilotOrg !== org?.id) {
      closeCopilot();
      copilotOrg = org?.id;
      copilotTicket++;
      copilotBody.replaceChildren();
    }
  }
  async function loadCopilot() {
    const oid = org?.id, ticket = ++copilotTicket;
    if (!oid) return;
    const focused = copilotDrawer.contains(document.activeElement);
    const adminOpen = copilotBody.querySelector('[data-copilot-admin]')?.open;
    copilotBody.setAttribute('aria-busy', 'true');
    try {
      await renderCopilot({
        url: (suffix) => `/organisations/${encodeURIComponent(oid)}${suffix}`,
        mount: (html) => {
          if (ticket !== copilotTicket || oid !== org?.id) return false;
          copilotBody.innerHTML = html;
          const admin = copilotBody.querySelector('[data-copilot-admin]');
          if (admin) admin.open = !!adminOpen;
          if (focused && !copilotDrawer.hidden) copilotDrawer.querySelector('[data-copilot-close]').focus();
          return true;
        },
      });
    } catch (error) {
      if (ticket === copilotTicket && oid === org?.id) {
        copilotBody.innerHTML = `<p role="alert">${esc(error.message)}</p>${button('Try again', 'retryCopilot')}`;
        bindActions(copilotBody, {retryCopilot: loadCopilot});
      }
    } finally {
      if (ticket === copilotTicket) copilotBody.removeAttribute('aria-busy');
    }
  }
  function scrollCopilot() {
    const list = copilotBody.querySelector('#copilot-transcript');
    if (list) list.scrollTop = list.scrollHeight;
  }
  function copilotMarkdown(source) {
    // Escape every provider character before adding our small, fixed tag allowlist.
    const translated = String(source).split('\n').map((line) => t(line)).join('\n');
    const clean = translated.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, '')
      .replace(/<!--[\s\S]*?-->/g, '').replace(/<[^>]*>/g, '');
    function inline(text) {
      const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|\[[^\]\n]+\]\([^\s)]+\))/g;
      let result = '', offset = 0;
      for (const match of text.matchAll(pattern)) {
        result += esc(text.slice(offset, match.index));
        const token = match[0];
        if (token.startsWith('`')) result += `<code>${esc(token.slice(1, -1))}</code>`;
        else if (token.startsWith('**')) result += `<strong>${esc(token.slice(2, -2))}</strong>`;
        else if (token.startsWith('*')) result += `<em>${esc(token.slice(1, -1))}</em>`;
        else {
          const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
          const safe = /^https?:\/\//i.test(link[2]);
          result += safe ? `<a href="${esc(link[2])}" target="_blank" rel="noreferrer">${esc(link[1])}</a>` : esc(link[1]);
        }
        offset = match.index + token.length;
      }
      return result + esc(text.slice(offset));
    }
    const blocks = clean.split(/(```[^\n]*\n[\s\S]*?(?:```|$))/g);
    return blocks.map((block) => {
      if (block.startsWith('```')) {
        const code = block.slice(block.indexOf('\n') + 1).replace(/```$/, '');
        return `<pre><code>${esc(code)}</code></pre>`;
      }
      let html = '', paragraph = [], list = null;
      const flush = () => { if (paragraph.length) html += `<p>${inline(paragraph.join('\n'))}</p>`; paragraph = []; };
      const close = () => { if (list) html += `</${list}>`; list = null; };
      for (const line of block.split('\n')) {
        const bullet = /^\s*(?:([-*])|\d+\.)\s+(.+)$/.exec(line);
        if (bullet) {
          flush();
          const tag = bullet[1] ? 'ul' : 'ol';
          if (list !== tag) { close(); html += `<${tag}>`; list = tag; }
          html += `<li>${inline(bullet[2])}</li>`;
        } else {
          close();
          if (!line.trim()) flush();
          else paragraph.push(line);
        }
      }
      flush(); close();
      return html;
    }).join('');
  }
  async function copilotSend(url, payload, onDelta) {
    if (typeof ReadableStream === 'undefined' || typeof TextDecoder === 'undefined') return post(url, payload);
    let response;
    try {
      response = await api(url, {method: 'POST', body: JSON.stringify(payload), headers: {Accept: 'text/event-stream'}});
    } catch (error) {
      // Only negotiate again when the server rejected streaming before accepting a send.
      if ([404, 405, 406, 415, 501].includes(error.status)) return post(url, payload);
      throw error;
    }
    // Older servers ignore Accept and return the existing JSON result. Do not send twice.
    if (!(response instanceof Response)) return response;
    if (!response.body?.getReader || !response.headers.get('content-type')?.includes('text/event-stream')) {
      throw new Error(t('The reply was interrupted. Please retry.'));
    }
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = '', result = null;
    try {
      while (true) {
        const {value, done} = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
        buffer = buffer.replace(/\r\n/g, '\n');
        let end;
        while ((end = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, end); buffer = buffer.slice(end + 2);
          const kind = /^event: *([^\n]+)/m.exec(frame)?.[1];
          const raw = frame.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n');
          if (!raw) continue;
          const data = JSON.parse(raw);
          if (kind === 'delta') onDelta(data.text);
          if (kind === 'done') result = data;
        }
        if (done) break;
      }
      if (!result) throw new Error(t('The reply was interrupted. Please retry.'));
      return result;
    } finally { reader.releaseLock(); }
  }
  function copilotTranscript(messages) {
    return messages.map((x) => {
      const stage = x.stage_proposal_json ? JSON.parse(x.stage_proposal_json) : null;
      return `<article class="copilot-message copilot-${esc(x.role)}" title="${esc(x.created_at)}">` +
        (x.role === 'assistant' ? `<span class="copilot-author">${icon('assistant')}${tr('AI copilot')}</span>` : '') +
        (x.role === 'assistant' ? `<div class="copilot-markdown">${copilotMarkdown(x.content)}</div><button type="button" class="button copilot-copy" data-copy="${esc(x.content)}" aria-label="${tr('Copy reply')}">${tr('Copy reply')}</button>` : `<p>${esc(x.content)}</p>`) +
        (x.retryable ? `<button type="button" class="button" data-retry="${esc(x.id)}">${tr('Retry')}</button>` : '') +
        (stage ? button(tr('Stage {rows} rows for import').replace('{rows}', stage.rows ?? '?'), 'stageImport', false, `data-id="${esc(x.id)}" ${canEditMappings() ? '' : 'disabled'}`) : '') +
        `</article>`;
    }).join('');
  }
  async function renderCopilot(c) {
    const admins = canEditMappings();
    const [status, history, usage, docs] = await Promise.all([
      api(c.url('/copilot/status')),
      api(c.url('/copilot/messages')),
      admins ? api(c.url('/copilot/usage')) : Promise.resolve(null),
      api(c.url('/copilot/documents')),
    ]);
    const active = status.available && status.enabled && status.access?.granted !== false;
    const quotaLine = `${num(status.quotas.user_messages)} / ${num(status.quotas.messages_per_user_day)}`;
    const accessLine = status.access && !status.access.granted
      ? t('AI copilot access has not been granted to this account.')
      : null;
    const notice = !status.available ? t('AI copilot is not configured on this service.')
      : !status.enabled ? t('AI copilot is off for this organisation. An owner or administrator can enable it here.')
      : accessLine || `${tr('Used today')}: ${quotaLine}`;
    const stages = Object.fromEntries((history || []).filter((x) => x.stage_proposal_json)
      .map((x) => [x.id, JSON.parse(x.stage_proposal_json)]));
    const suggestions = ['Summarise overdue invoices', 'What needs my attention this week?', 'Explain my VAT position'];
    const empty = `<div class="copilot-empty"><p>${esc(active ? t('How can I help with your books?') : notice)}</p>` +
      (active ? `<div class="copilot-suggestions">${suggestions.map((text) => `<button type="button" class="button" data-suggestion="${tr(text)}">${tr(text)}</button>`).join('')}</div>` : '') + `</div>`;
    const composer = `<form class="copilot-composer"><div data-copilot-attachment hidden></div><div class="copilot-compose-row">` +
      `<button type="button" class="button copilot-attach" aria-label="${tr('Attach document')}" aria-expanded="false" aria-controls="copilot-documents">${icon('paperclip')}</button>` +
      `<textarea name="content" rows="1" maxlength="8000" aria-label="${tr('Message')}" placeholder="${tr('Ask about your books')}" required></textarea>` +
      `<button type="submit" class="button primary copilot-send" aria-label="${tr('Send message')}" disabled>${icon('send')}</button></div>` +
      `<div class="copilot-attachments" hidden><select id="copilot-documents" aria-label="${tr('Attach document')}"><option value="">${tr('No attachment')}</option>${docs.map((d) => `<option value="${esc(d.id)}">${esc(d.filename)}</option>`).join('')}</select></div></form>`;
    const usageUsage = usage
      ? `<section class="section" data-copilot-usage><h2>${tr('Copilot usage')}</h2><p class="muted">${tr('Per-user daily usage counts every message, scan and token billed to this organisation.')}</p>` +
        table(['Day', 'User', 'Messages', 'Scans', 'Input tokens', 'Output tokens'],
          usage.map((u) => row([
            td(esc(u.day)),
            td(esc(u.user_email)),
            td(esc(num(u.messages)), 'numeric'),
            td(esc(num(u.scans)), 'numeric'),
            td(esc(num(u.tokens_in)), 'numeric'),
            td(esc(num(u.tokens_out)), 'numeric'),
          ]))) +
        `</section>`
      : '';
    const grantsPanel = admins && status.grants
      ? `<section class="section" data-copilot-access><h2>${tr('Copilot access')}</h2><p class="muted">${tr('Owners and administrators always have access. Grant members of this organisation individually; grants are audited.')}</p>` +
        table(['Account', 'Granted by', 'Actions'],
          (status.grants || []).map((g) => row([
            td(esc(g.email)), td(esc(g.granted_by)),
            td(admins ? button('Revoke', 'revokeCopilotAccess', false, `data-email="${esc(g.email)}"`) : ''),
          ]))) +
        form(field('Grant member email', 'grant_email', '', 'email', 'required maxlength="320"'), 'Grant access') +
      `</section>` : '';
    const body = `<p class="muted" data-copilot-notice aria-live="polite">${esc(notice)}</p>` +
      (admins ? `<details id="copilot-admin" data-copilot-admin><summary>${tr('Copilot administration')}</summary><section class="section" data-copilot-settings>` +
        form(check('Enable AI copilot for this organisation', 'copilot_enabled', !!status.enabled)) + `</section><section class="section" data-copilot-provider>` +
        `<p class="muted">${tr(status.settings?.configured ? 'Organisation API key configured' : 'Using the service API key when available')}</p>` +
        form(field('Organisation xAI API key', 'api_key', '', 'password', 'autocomplete="new-password" maxlength="4096"') +
          `<p class="muted">${tr('Leave blank to keep the saved key.')}</p>` +
          check('Clear the organisation API key', 'clear_key', false) +
          field('Copilot model (optional)', 'model', status.settings?.model || '', 'text', 'maxlength="128"'), 'Save') +
        `</section>` + grantsPanel + usageUsage + `</details>` : '') +
      `<section data-copilot-chat><div id="copilot-transcript" role="log" aria-live="polite" aria-relevant="additions text">${history?.length ? copilotTranscript([...history].reverse()) : empty}</div>` + composer + `</section>`;
    if (!c.mount(body)) return;
    copilotBody.querySelectorAll('[data-action=cancel]').forEach((x) => x.remove());
    if (!active) copilotBody.querySelectorAll('[data-copilot-chat] textarea, [data-copilot-chat] select, [data-copilot-chat] button').forEach((x) => { x.disabled = true; });
    const enabledCheck = copilotBody.querySelector('[name=copilot_enabled]');
    if (enabledCheck) bindForm(copilotBody.querySelector('[data-copilot-settings]'), async () => {
      await post(c.url('/copilot/settings'), {enabled: !!enabledCheck.checked});
      toast(t('Saved successfully'));
      await loadCopilot();
    });
    const providerPanel = copilotBody.querySelector('[data-copilot-provider]');
    if (providerPanel) bindForm(providerPanel, async (values) => {
      const payload = {model: values.model || ''};
      if (providerPanel.querySelector('[name=clear_key]').checked) payload.api_key = '';
      else if (values.api_key?.trim()) payload.api_key = values.api_key.trim();
      await post(c.url('/copilot/settings'), payload);
      providerPanel.querySelector('[name=api_key]').value = '';
      toast(t('Saved successfully'));
      await loadCopilot();
    });
    const accessPanel = copilotBody.querySelector('[data-copilot-access]');
    if (accessPanel) {
      bindForm(accessPanel, async (values) => {
        await post(c.url('/copilot/access'), {email: values.grant_email});
        toast(t('Saved successfully'));
        await loadCopilot();
      });
      bindActions(copilotBody, {revokeCopilotAccess: (b) => confirmAction(tr('Revoke copilot access'), tr('{email} loses copilot access immediately. Revoke?').replace('{email}', b.dataset.email), async () => {
        await post(c.url('/copilot/access/' + encodeURIComponent(b.dataset.email)), {}, 'DELETE');
        toast(t('Saved successfully'));
        await loadCopilot();
      })});
    }
    const panel = copilotBody.querySelector('[data-copilot-admin]');
    const gear = copilotDrawer.querySelector('[data-copilot-gear]');
    gear.hidden = !admins;
    if (panel) {
      const syncGear = () => gear.setAttribute('aria-expanded', String(panel.open));
      panel.addEventListener('toggle', syncGear);
      syncGear();
    }
    const chat = copilotBody.querySelector('[data-copilot-chat]');
    const list = chat.querySelector('#copilot-transcript');
    list.addEventListener('click', async (event) => {
      const copy = event.target.closest('[data-copy]');
      if (!copy) return;
      try {
        await navigator.clipboard.writeText(copy.dataset.copy);
        copy.textContent = t('Reply copied');
        copy.setAttribute('aria-label', t('Reply copied'));
      } catch (_) { toast(t('Could not copy the reply. Please select and copy the text.'), 'error'); }
    });
    const chatForm = chat.querySelector('form');
    const textarea = chatForm.querySelector('textarea');
    const send = chatForm.querySelector('[type=submit]');
    const attach = chatForm.querySelector('.copilot-attach');
    const picker = chatForm.querySelector('select');
    const menu = chatForm.querySelector('.copilot-attachments');
    const chip = chatForm.querySelector('[data-copilot-attachment]');
    let sending = false;
    const resize = () => {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 192)}px`;
      send.disabled = !active || sending || !textarea.value.trim();
    };
    textarea.oninput = resize;
    attach.onclick = () => {
      menu.hidden = !menu.hidden;
      attach.setAttribute('aria-expanded', String(!menu.hidden));
      if (!menu.hidden) picker.focus();
    };
    const chooseAttachment = () => {
      chip.hidden = !picker.value;
      chip.innerHTML = picker.value ? `<span>${esc(picker.selectedOptions[0].textContent)}</span><button type="button" class="button" aria-label="${tr('Remove attachment')}">${icon('close')}</button>` : '';
      const remove = chip.querySelector('button');
      if (remove) remove.onclick = () => { picker.value = ''; chooseAttachment(); textarea.focus(); };
      menu.hidden = true;
      attach.setAttribute('aria-expanded', 'false');
    };
    picker.onchange = () => { chooseAttachment(); textarea.focus(); };
    const sendMessage = async (draft = textarea.value, attachment = picker.value) => {
      if (!active || sending || !draft.trim()) return;
      sending = true;
      list.querySelector('.copilot-empty')?.remove();
      list.insertAdjacentHTML('beforeend', copilotTranscript([{role: 'user', content: draft, created_at: new Date().toISOString()}]));
      const userBubble = list.lastElementChild;
      list.insertAdjacentHTML('beforeend', `<article class="copilot-message copilot-assistant"><span class="copilot-author">${icon('assistant')}${tr('AI copilot')}</span><div class="copilot-typing" aria-label="${tr('Thinking')}"><span></span><span></span><span></span></div></article>`);
      const pending = list.lastElementChild;
      textarea.value = '';
      picker.value = '';
      chooseAttachment();
      chatForm.querySelectorAll('textarea, button, select').forEach((x) => { x.disabled = true; });
      resize();
      scrollCopilot();
      let streamedText = '';
      try {
        const reply = await copilotSend(c.url('/copilot/messages'), {page: currentPage(), content: draft, attachment_ids: attachment ? [attachment] : []}, (delta) => {
          streamedText += delta;
          if (!chat.isConnected) return;
          let text = pending.querySelector('.copilot-markdown');
          if (!text) {
            pending.querySelector('.copilot-typing')?.remove();
            text = document.createElement('div'); text.className = 'copilot-markdown'; pending.append(text);
          }
          text.innerHTML = copilotMarkdown(streamedText);
          scrollCopilot();
        });
        if (!chat.isConnected) return;
        if (reply.quota_consumed ?? !reply.retryable) {
          status.quotas.user_messages++;
          copilotBody.querySelector('[data-copilot-notice]').textContent = `${t('Used today')}: ${num(status.quotas.user_messages)} / ${num(status.quotas.messages_per_user_day)}`;
        }
        if (reply.retryable) {
          streamedText = reply.assistant.content;
          const failure = new Error(translateError(reply.error));
          failure.partial = true;
          throw failure;
        }
        if (!chat.isConnected) return;
        userBubble.outerHTML = copilotTranscript([reply.user_message]);
        if (reply.stage) {
          stages[reply.assistant.id] = reply.stage;
          reply.assistant.stage_proposal_json = JSON.stringify(reply.stage);
        }
        pending.outerHTML = copilotTranscript([reply.assistant]);
        bindStages();
      } catch (error) {
        if (!chat.isConnected) return;
        pending.classList.add('copilot-error');
        pending.innerHTML = `<span class="copilot-author">${icon('assistant')}${tr('AI copilot')}</span><p>${esc(error.message)}</p><button type="button" class="button">${tr('Retry')}</button>`;
        if (streamedText) {
          pending.querySelector('p').outerHTML = `<div class="copilot-markdown">${copilotMarkdown(streamedText)}</div>` +
            (error.partial ? '' : `<p role="alert">${esc(error.message)}</p>`);
          pending.insertAdjacentHTML('beforeend', `<button type="button" class="button copilot-copy" data-copy="${esc(streamedText)}" aria-label="${tr('Copy reply')}">${tr('Copy reply')}</button>`);
        }
        pending.querySelector('button').onclick = () => {
          if (sending) return;
          pending.querySelector('button').disabled = true;
          sendMessage(draft, attachment);
        };
        textarea.value = draft;
        picker.value = attachment;
        chooseAttachment();
      } finally {
        sending = false;
        if (chat.isConnected) {
          chatForm.querySelectorAll('textarea, button, select').forEach((x) => { x.disabled = !active; });
          resize();
          scrollCopilot();
          if (!copilotDrawer.hidden) textarea.focus();
        }
      }
    };
    list.addEventListener('click', (event) => {
      const retry = event.target.closest('[data-retry]');
      if (!retry || sending) return;
      const ordered = [...history].reverse();
      const index = ordered.findIndex((message) => message.id === retry.dataset.retry);
      const question = ordered.slice(0, index).reverse().find((message) => message.role === 'user');
      if (question) sendMessage(question.content, JSON.parse(question.attachment_ids_json || '[]')[0] || '');
    });
    chatForm.onsubmit = (event) => { event.preventDefault(); sendMessage(); };
    textarea.onkeydown = (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        sendMessage();
      }
    };
    chat.querySelectorAll('[data-suggestion]').forEach((b) => { b.onclick = () => sendMessage(b.dataset.suggestion); });
    resize();
    scrollCopilot();
    function bindStages() {
      bindActions(copilotBody, {stageImport: (b) => confirmAction(tr('Stage import rows'), tr('Review these rows in Data import before they touch your books. Stage them now?'), async () => {
        const proposal = stages[b.dataset.id] || {};
        await post(c.url('/copilot/stage'), {kind: proposal.kind, csv_content: proposal.csv, message_id: b.dataset.id});
        toast(t('Import batch staged. Review it under Data import.'));
      })});
    }
    bindStages();
  }
  const views = {
    overview: async (c) => {
      const [invoices, bills, bank, runs, absences, clients] = await Promise.all([
        api(c.url("/invoices")),
        api(c.url("/bills")),
        api(c.url("/bank-transactions")),
        c.payrollSupported ? optionalPayroll(c.url("/pay-runs")) : null,
        c.payrollSupported ? optionalPayroll(c.url(`/payroll/absences?month=${today().slice(0, 7)}`)) : null,
        Promise.all(
          organisations.map(async (o) => {
            try {
              return { o, rows: await api(`/organisations/${o.id}/invoices`) };
            } catch (e) {
              toast(`${o.name}: ${e.message}`, "error");
              return { o, rows: null };
            }
          }),
        ),
      ]);
      const review = bank.filter((x) => x.status !== "Reconciled"),
        absentToday = (absences || []).filter((x) => x.start_date <= today() && x.end_date >= today()),
        monthly = runs?.filter((x) =>
          (x.period || "").startsWith(today().slice(0, 7)),
        ),
        cost = monthly
          ? decimal(
              monthly.reduce(
                (sum, x) =>
                  sum + cents(x.total_employer_cost ?? x.employer_cost),
                0n,
              ),
            )
          : null;
      if (
        !c.mount(
          page(
            t("Overview"),
            t("A clear view of your client’s books."),
            button("New invoice", "newInvoice", true),
            `<div class="kpis">${kpi("Receivables", money(outstanding(invoices, ["Issued", "Part Paid"])), "Open customer invoices")}${kpi("Payables", money(outstanding(bills, ["Approved", "Part Paid"])), "Approved supplier bills")}${kpi("Bank review", num(review.length), "Transactions awaiting review")}${kpi("Payroll this month", money(runs === null ? null : cost), !c.payrollSupported ? "Available for Estonian EUR books" : runs === null ? "Payroll is not available yet." : "Employer cost · draft and approved")}${c.payrollSupported ? kpi("Employees on leave today", num(absentToday.filter((x) => x.absence_type === "annual_leave" || x.absence_type === "extended_leave").length), "Current annual leave") + kpi("Sick leave today", num(absentToday.filter((x) => x.absence_type === "sick_leave").length), "Current sick leave") : ""}</div>${runs?.some((r) => r.declaration_overdue) ? `<p class="notice declaration-overdue"><a href="#payroll">${tr("Overdue payroll declarations")}: ${num(runs.filter((r) => r.declaration_overdue).length)}</a></p>` : ""}<section class="section"><div class="section-head"><h2>${tr("Client books")}</h2><span class="muted">${num(organisations.length)} ${tr("organisations")}</span></div><div class="client-strip">${clients.map(({ o, rows }) => `<button class="client-book ${o.id === c.oid ? "selected" : ""}" data-client="${esc(o.id)}"><span class="country-badge">${esc(o.country_code)}</span><strong>${esc(o.name)}</strong><small>${tr("Receivables")}</small><b>${esc(money(rows ? outstanding(rows, ["Issued", "Part Paid"]) : null, o.base_currency))}</b></button>`).join("")}</div></section><section class="card section"><div class="section-head"><h2>${tr("Revenue & cash")}</h2><span class="muted">${tr("Last six months")}</span></div>${chart(invoices, bank)}</section><div class="dashboard-lists"><section><div class="section-head"><h2>${tr("Recent invoices")}</h2><a href="#invoices">${tr("View all")}</a></div>${table(["Number", "Customer", "Date", "Status", ["Total"]], invoiceRows([...invoices].sort((a, b) => String(b.issue_date).localeCompare(a.issue_date)).slice(0, 5)), button("New invoice", "newInvoice"))}</section><section><div class="section-head"><h2>${tr("Ready for review")}</h2><a href="#banking">${tr("View all")}</a></div>${table(
              ["Counterparty", ["Amount"]],
              review
                .slice(0, 5)
                .map((x) =>
                  row([
                    td(
                      `<a href="#banking">${esc(x.counterparty || x.reference)}</a>`,
                    ),
                    cash(x.amount, x.currency),
                  ]),
                ),
            )}</section></div>`,
          ),
        )
      )
        return;
      bindActions(content, { newInvoice: () => documentDialog("invoice") });
      content
        .querySelectorAll("[data-client]")
        .forEach((b) => (b.onclick = () => switchOrg(b.dataset.client)));
    },
    invoices: async (c) => {
      const [rows, prepayments, contacts] = await Promise.all([
        api(c.url("/invoices") + listQuery(c, "invoices")), api(c.url("/prepayments?side=customer")), api(c.url("/contacts")),
      ]);
      const selected = new Set();
      if (
        !c.mount(
          page(
            t("Invoices"),
            t("From first draft to final payment."),
            button("New contact", "newContact") +
              button("Send emails", "sendBulk", false, "disabled") +
              button("Record customer prepayment", "newPrepayment", false, canExecutePush() ? "" : "disabled") +
              button("New invoice", "newInvoice", true),
            documentFilterControls(c, "invoices", contacts) + `<div id="invoice-table"></div>${prepaymentSection(prepayments, "customer")}`,
          ),
        )
      )
        return;
      const draw = () => {
        document.getElementById("invoice-table").innerHTML = table(
          ["", "Number", "Customer", "Date", "Status", ["Paid / total"], "Actions"],
          rows.map((x) =>
            row([
              td(`<input type="checkbox" data-select-invoice="${esc(x.id)}" aria-label="${esc(t('Select invoice {number}').replace('{number}', x.number || t('Draft')))}" ${canExecutePush() && x.document_type === 'invoice' && ['Issued', 'Part Paid'].includes(x.status) ? '' : 'disabled'}>`),
              td(esc(x.number || t("Draft"))),
              td(esc(x.contact_name)),
              td(date(x.issue_date), "numeric"),
              td(pill(x.status)),
              td(
                `${esc(money(x.paid_total || 0, x.currency))}<span class="muted"> / ${esc(money(x.total, x.currency))}</span>`,
                "numeric",
              ),
              td(
                button("Details", "invoiceAttachments", false, `data-id="${esc(x.id)}" aria-label="${esc(t("Details: {number}").replace("{number}", x.number || t("Draft")))}"`) + (x.status === "Draft"
                  ? button("Issue", "issue", false, `data-id="${esc(x.id)}"`)
                  : link("PDF", `/api${c.url(`/invoices/${x.id}.pdf`)}`) +
                      link("XML", `/api${c.url(`/invoices/${x.id}.xml`)}`)),
              ),
            ]),
          ),
          button("New invoice", "newInvoice"),
        );
        bindActions(content, {
          ...prepaymentActions(prepayments, "customer"),
          newInvoice: () => documentDialog("invoice"),
          newContact: () => contactDialog("customer"),
          invoiceAttachments: (b) => documentDialog("invoice", b.dataset.id),
          sendBulk: () => {
            const ids = [...selected], requestKey = Array.from(crypto.getRandomValues(new Uint32Array(4)), (n) => n.toString(16)).join('-');
            confirmAction('Send emails', esc(t('Send invoice PDFs to {count} customers?').replace('{count}', num(ids.length))), async () => {
              const outcome = await api(c.url('/invoices/send-bulk'), {
                method: 'POST', body: JSON.stringify({invoice_ids: ids}),
                headers: {'Idempotency-Key': requestKey},
              });
              if (org?.id !== c.oid) return;
              selected.clear();
              content.querySelectorAll('[data-select-invoice]').forEach((input) => { input.checked = false; });
              syncSelection();
              dialog('Email results', table(['Number', 'Status', 'Reason'], outcome.results.map((item) => row([
                td(esc(rows.find((invoice) => invoice.id === item.invoice_id)?.number || item.invoice_id)),
                td(pill(item.status === 'sent' ? 'Sent' : 'Failed')),
                td(item.reason ? tr(item.reason) : ''),
              ]))));
            });
          },
          issue: (b) =>
            confirmAction(
              "Issue invoice",
              tr(
                "This creates an immutable ledger posting. Corrections require a credit note.",
              ),
              async () => {
                await post(c.url(`/invoices/${b.dataset.id}/issue`));
                toast(t("Invoice issued"));
                await render();
              },
            ),
        });
        const header = content.querySelector('#invoice-table thead th');
        if (header) header.innerHTML = `<input type="checkbox" data-select-all-invoices aria-label="${esc(t('Select invoices'))}">`;
        const all = content.querySelector('[data-select-all-invoices]');
        const enabled = [...content.querySelectorAll('[data-select-invoice]:not(:disabled)')];
        const syncSelection = () => {
          const count = enabled.filter((input) => input.checked).length;
          if (all) {
            all.checked = enabled.length > 0 && count === enabled.length;
            all.indeterminate = count > 0 && count < enabled.length;
            all.disabled = !enabled.length;
          }
          content.querySelector('[data-action=sendBulk]').disabled = !selected.size || selected.size > 50;
        };
        enabled.forEach((input) => {
          input.onchange = () => {
            if (input.checked) selected.add(input.dataset.selectInvoice);
            else selected.delete(input.dataset.selectInvoice);
            syncSelection();
          };
        });
        if (all) all.onchange = () => {
          enabled.forEach((input) => {
            input.checked = all.checked;
            if (input.checked) selected.add(input.dataset.selectInvoice);
            else selected.delete(input.dataset.selectInvoice);
          });
          syncSelection();
        };
        syncSelection();
      };
      draw();
      bindDocumentFilters(c, "invoices");
    },
    quotes: async (c) => {
      const rows = await api(c.url("/quotes"));
      const actions = (x) => {
        const attrs = `data-id="${esc(x.id)}"`;
        const stale = x.valid_until < today();
        return button("Quote", "viewQuote", false, attrs) +
          (x.status === "Draft" ? button("Edit", "editQuote", false, attrs) +
            (!stale ? button("Mark sent", "sendQuote", false, attrs) : "") : "") +
          (x.status === "Sent" ? (!stale ? button("Accept", "acceptQuote", false, attrs) : "") +
            button("Decline", "declineQuote", false, attrs) : "") +
          (["Draft", "Sent"].includes(x.status) && stale ? button("Expire", "expireQuote", false, attrs) : "") +
          (x.status === "Accepted" ? button("Convert", "convertQuote", false, attrs) : "") +
          (x.status === "Converted" ? link("Invoice", "#invoices") : "");
      };
      if (!c.mount(page(t("Quotes"), t("Customer offers before invoicing."),
        button("New quote", "newQuote", true) + link("Export CSV", `/api${c.url('/quotes/export.csv')}`), table(
          ["Number", "Customer", "Quote date", "Valid until", "Status", ["Total"], "Actions"],
          rows.map((x) => row([td(esc(x.quote_number)), td(esc(x.contact_name)), td(date(x.quote_date)),
            td(date(x.valid_until)), td(pill(x.status)), td(esc(money(x.total, x.currency)), "numeric"), td(actions(x))])),
          button("New quote", "newQuote"))))) return;
      const transition = async (b, action) => {
        await post(c.url(`/quotes/${b.dataset.id}/${action}`));
        await render();
      };
      bindActions(content, {
        newQuote: () => quoteDialog(),
        editQuote: (b) => quoteDialog(b.dataset.id),
        viewQuote: (b) => quoteDialog(b.dataset.id, true),
        sendQuote: (b) => confirmAction("Mark sent", tr("Mark this quote as sent. Email delivery is not available yet."), () => transition(b, "send")),
        acceptQuote: (b) => transition(b, "accept"),
        declineQuote: (b) => transition(b, "decline"),
        expireQuote: (b) => transition(b, "expire-status"),
        convertQuote: (b) => confirmAction("Convert to invoice", tr("This creates and issues a sales invoice with an immutable ledger posting."), async () => {
          const invoice = await post(c.url(`/quotes/${b.dataset.id}/convert`));
          toast(`${t("Invoice issued")}: ${invoice.number}`);
          await render();
        }),
      });
    },
    objects: async (c) => {
      const rows = await api(c.url('/objects'));
      if (!c.mount(page(t('Objects'), t('Tag income and costs by project, location, person or object.'),
        button('Add object', 'newObject', true, canEditMappings() ? '' : 'disabled') +
          link('Export CSV', `/api${c.url('/objects/export.csv')}`),
        table(['Code', 'Name', 'Object type', 'Status', 'Actions'], rows.map((x) => row([
          td(esc(x.code)), td(esc(x.name)), td(tr(objectTypeLabel(x.object_type))), td(tr(x.active ? 'Active' : 'Inactive')),
          td(button('Edit object', 'editObject', false, `data-id="${esc(x.id)}" ${canEditMappings() ? '' : 'disabled'}`) +
            button('Delete object', 'deleteObject', false, `data-id="${esc(x.id)}" ${canEditMappings() ? '' : 'disabled'}`))])))))) return;
      bindActions(content, {
        newObject: () => objectDialog(),
        editObject: (b) => objectDialog(rows.find((x) => x.id === b.dataset.id)),
        deleteObject: (b) => confirmAction('Delete object', tr('Delete this object? Objects in use must be deactivated instead.'), async () => {
          await post(c.url(`/objects/${b.dataset.id}`), {}, 'DELETE');
          await render();
        }),
      });
    },
    "payment-types": async (c) => {
      if (!c.payrollSupported) {
        c.mount(page(t("Payment types"), t("Payroll is available only for Estonian organisations with EUR books. Switch to an Estonian EUR organisation to manage payroll."), "", ""));
        return;
      }
      const types = await api(c.url("/payroll/component-types"));
      if (!c.mount(page(t("Payment types"), t("Manage payroll payment types and their default levy flags."),
        button("Payroll accounts", "payrollAccounts", false, canExecutePush() ? "" : "disabled"), paymentTypesContent(types)))) return;
      bindPaymentTypeActions(c, types, content);
      bindActions(content, {payrollAccounts: () => payrollAccountsDialog(c)});
    },
    documents: async (c) => {
      const settings = await api(c.url('/document-settings'));
      const editable = canEditMappings();
      if (!c.mount(page(t('Document appearance'), t('Customise sales invoice and credit note PDFs for this organisation.'), '',
        `<section class="section" data-document-appearance><h2>${tr('Appearance settings')}</h2>` +
        form(check('Use an accent colour', 'use_accent_colour', settings.accent_colour != null) +
          field('Accent colour', 'accent_colour', settings.accent_colour || '#000000', 'color') +
          `<label class="full-width">${tr('Invoice footer')}<textarea name="footer_text" rows="4" maxlength="500">${esc(settings.footer_text || '')}</textarea><span class="field-error" data-error="footer_text"></span></label>`) +
        `</section><section class="section" data-document-logo><h2>${tr('Organisation logo')}</h2>` +
        (settings.logo_attachment_id ? `<p><img src="/api${esc(c.url('/document-settings/logo'))}?v=${esc(settings.logo_attachment_id)}" alt="${tr('Organisation logo')}" style="max-width:280px;max-height:80px"></p>` : `<p class="muted">${tr('No logo uploaded.')}</p>`) +
        `<p class="muted">${tr('Upload a PNG or JPEG image, up to 512 KB.')}</p>` +
        form(field('Logo file', 'file', '', 'file', 'required accept=".png,.jpg,.jpeg,image/png,image/jpeg"'), 'Upload logo') +
        (settings.logo_attachment_id ? button('Remove logo', 'removeDocumentLogo', false, editable ? '' : 'disabled') : '') + `</section>`))) return;
      content.querySelectorAll('[data-action=cancel]').forEach((x) => x.remove());
      if (!editable) content.querySelectorAll('input, textarea, button').forEach((x) => { x.disabled = true; });
      const appearance = content.querySelector('[data-document-appearance]');
      const accentEnabled = appearance.querySelector('[name=use_accent_colour]');
      const accent = appearance.querySelector('[name=accent_colour]');
      accent.disabled = !editable || !accentEnabled.checked;
      accentEnabled.onchange = () => { accent.disabled = !editable || !accentEnabled.checked; };
      bindForm(appearance, async (data) => {
        await post(c.url('/document-settings'), {accent_colour: accentEnabled.checked ? data.accent_colour : null,
          footer_text: data.footer_text || null}, 'PUT');
        toast(t('Saved successfully'));
        await render();
      });
      bindForm(content.querySelector('[data-document-logo]'), async (_, formElement) => {
        const file = formElement.elements.file.files[0];
        if (file.size > 512 * 1024) throw new Error(t('Logo must be no larger than 512 KB.'));
        const payload = new FormData();
        payload.append('file', file);
        await api(c.url('/document-settings/logo'), {method: 'POST', body: payload});
        toast(t('Saved successfully'));
        await render();
      });
      bindActions(content, {removeDocumentLogo: () => confirmAction('Remove logo', tr('Remove the logo from sales invoice and credit note PDFs?'), async () => {
        await post(c.url('/document-settings/logo'), {}, 'DELETE');
        toast(t('Saved successfully'));
        await render();
      })});
    },
    periods: async (c) => {
      const editable = canEditMappings();
      const rows = await api(c.url('/periods'));
      if (!c.mount(page(t('Fiscal periods'), t('Lock a period to stop changes to its postings. Reopening needs a note and is audited.'), '',
        `<section class="section"><h2>${tr('Periods')}</h2>${table(
          ['Period', 'From', 'To', 'Status', 'Locked at', 'Actions'],
          rows.map((x) => row([
            td(esc(x.code)),
            td(date(x.starts_on)),
            td(date(x.ends_on)),
            td(pill(tr(x.status))),
            td(x.locked_at ? `${esc(date(x.locked_at))} · ${esc(x.locked_by || '')}${x.lock_reason ? ` · ${esc(x.lock_reason)}` : ''}` : ''),
            td(editable ? (x.status === 'Locked'
              ? button('Reopen period', 'reopenPeriod', false, `data-id="${esc(x.id)}"`)
              : button('Close period', 'closePeriod', true, `data-id="${esc(x.id)}"`)) : ''),
          ])))}</section>`))) return;
      content.querySelector('[data-action=cancel]')?.remove();
      const reasonDialog = (title, submit, path) => {
        const d = dialog(title, form(`<label class="full-width">${tr('Reason')}<textarea name="reason" rows="2" maxlength="500" required></textarea><span class="field-error" data-error="reason"></span></label>`, submit));
        d.querySelector('[data-action=cancel]').remove();
        bindForm(d, async (v) => {
          await post(path, {reason: v.reason}, 'PUT');
          await saved(d);
        });
      };
      bindActions(content, {
        closePeriod: (b) => reasonDialog(tr('Close period'), 'Close period', c.url(`/periods/${b.dataset.id}/close`)),
        reopenPeriod: (b) => reasonDialog(tr('Reopen period'), 'Reopen period', c.url(`/periods/${b.dataset.id}/reopen`)),
      });
    },
    maintenance: async (c) => {
      const editable = canEditMappings();
      const data = await api(c.url('/master-data/maintenance'));
      if (!c.mount(page(t('Data maintenance'), t('Find loose master data: contacts without documents, duplicates, missing identifiers and reused supplier numbers. Deleting needs a contact with no documents at all.'), '',
        `<section class="section"><h2>${tr('Unused contacts')}</h2>${table(
          ['Name', 'Type', 'Status', 'Actions'],
          data.unused_contacts.map((x) => row([
            td(esc(x.name)), td(tr(x.contact_type)), td(pill(tr(x.active ? 'Active' : 'Inactive'))),
            td(editable ? actionButtons(x) : ''),
          ])))}</section>` +
        `<section class="section"><h2>${tr('Duplicate contacts')}</h2>${table(
          ['Name', 'Type', 'VAT number', 'Registration number', 'Status'],
          data.duplicate_contacts.map((x) => row([
            td(esc(x.name)), td(tr(x.contact_type)), td(esc(x.vat_no || '')), td(esc(x.registration_no || '')),
            td(pill(tr(x.active ? 'Active' : 'Inactive'))),
          ])))}</section>` +
        `<section class="section"><h2>${tr('Contacts missing identifiers')}</h2>${table(
          ['Name', 'Type', 'Tax point hint'],
          data.contacts_missing_identifiers.map((x) => row([
            td(esc(x.name)), td(tr(x.contact_type)), td(tr('Missing VAT number and registration number')),
          ])))}</section>` +
        `<section class="section"><h2>${tr('Reused supplier numbers')}</h2>${table(
          ['Supplier number', 'Suppliers'],
          data.reused_supplier_numbers.map((x) => row([
            td(esc(x.supplier_number)), td(num(x.suppliers)),
          ])))}</section>`))) return;
      function actionButtons(x) {
        const base = `data-id="${esc(x.id)}"`;
        const remove = button('Delete contact', 'deleteContact', false, base);
        return x.active ? `<span class="actions">${remove}${button('Deactivate', 'deactivateContact', false, base)}</span>` : `<span class="actions">${button('Reactivate', 'reactivateContact', false, base)}</span>`;
      }
      bindActions(content, {
        deactivateContact: (b) => confirmAction(tr('Deactivate contact'), tr('The contact disappears from pickers while keeping its history. Deactivate it?'), async () => {
          await post(c.url(`/master-data/contacts/${b.dataset.id}/deactivate`), {});
          toast(t('Saved successfully'));
          await render();
        }),
        reactivateContact: (b) => confirmAction(tr('Reactivate contact'), tr('The contact becomes selectable again. Reactivate it?'), async () => {
          await post(c.url(`/master-data/contacts/${b.dataset.id}/reactivate`), {});
          toast(t('Saved successfully'));
          await render();
        }),
        deleteContact: (b) => confirmAction(tr('Delete contact'), tr('Only contacts without any documents or payments can be deleted. This cannot be undone. Delete it?'), async () => {
          await post(c.url(`/master-data/contacts/${b.dataset.id}/delete`), {});
          toast(t('Deleted successfully'));
          await render();
        }),
      });
    },
    groups: async (c) => {
      const editable = canEditMappings();
      const [contactGroups, userGroups, contacts] = await Promise.all([
        api(c.url('/contact-groups')),
        api(c.url('/user-groups')),
        api(c.url('/contacts')),
      ]);
      const groupActions = (kind, g) => {
        if (!editable) return '';
        const attrs = `data-kind="${kind}" data-id="${esc(g.id)}" data-name="${esc(g.name)}"`;
        return `<span class="actions">${button('Manage members', 'manageMembers', false, attrs) +
          button('Delete group', 'deleteGroup', false, attrs)}</span>`;
      };
      const section = (kind, label, intro, groups) => {
        const rows = table(['Name', 'Members', 'Actions'],
          groups.map((g) => row([
            td(esc(g.name)),
            td(num(g.members), 'numeric'),
            td(groupActions(kind, g)),
          ])));
        const create = editable ? form(field('New group name', 'name', '', 'text', 'required maxlength="100"'), 'Create group') : '';
        return `<section class="section" data-groups="${kind}"><h2>${tr(label)}</h2><p class="muted">${esc(intro)}</p>${rows}${create}</section>`;
      };
      if (!c.mount(page(t('Groups'), t('Group clients, suppliers and workspace users for filtering and reporting. Groups are labels and do not change access controls.'), '',
        section('contact', 'Contact groups', tr('Tag customers and suppliers into groups such as retail or wholesale.'), contactGroups) +
        section('user', 'User groups', tr('Tag workspace users into teams. Access roles stay separate.'), userGroups)))) return;
      content.querySelectorAll('[data-action=cancel]').forEach((x) => x.remove());
      if (!editable) content.querySelectorAll('input, button').forEach((x) => { x.disabled = true; });
      const memberDialog = async (kind, group) => {
        const payload = await api(c.url(`/${kind}-groups/${group.id}/members`));
        const options = [['', t('Choose a member')], ...contacts.filter((x) => !payload.members.includes(x.id))
          .map((x) => [x.id, x.name])];
        const memberField = kind === 'contact'
          ? select('Add member', 'member', options)
          : field('Add member email', 'member', '', 'email', 'required maxlength="320"');
        const membersTable = payload.members.length
          ? table([tr('Member'), tr('Actions')], payload.members.map((m) => row([
              td(kind === 'contact' ? esc((contacts.find((x) => x.id === m) || {}).name || m) : esc(m)),
              td(editable ? button('Remove', 'removeMember', false, `data-member="${esc(m)}"`) : ''),
            ])))
          : `<p class="muted">${tr('No members yet.')}</p>`;
        const d = dialog(tr('Members of {name}').replace('{name}', group.name),
          membersTable + form(memberField, tr('Add member')));
        d.querySelectorAll('[data-action=cancel]').forEach((x) => x.remove());
        bindForm(d, async (values) => {
          await post(c.url(`/${kind}-groups/${group.id}/members`), {member: values.member});
          toast(t('Saved successfully'));
          closeDialog(d);
          await render();
        });
        d.querySelectorAll('[data-action=removeMember]').forEach((b) => (b.onclick = async () => {
          await post(c.url(`/${kind}-groups/${group.id}/members/${encodeURIComponent(b.dataset.member)}`), {}, 'DELETE');
          toast(t('Saved successfully'));
          closeDialog(d);
          await render();
        }));
      };
      const createForm = (kind) => {
        const holder = content.querySelector(`[data-groups="${kind}"]`);
        if (!editable) return;
        bindForm(holder, async (values) => {
          await post(c.url(`/${kind}-groups`), {name: values.name});
          toast(t('Saved successfully'));
          await render();
        });
      };
      createForm('contact');
      createForm('user');
      bindActions(content, {
        manageMembers: (b) => memberDialog(b.dataset.kind, { id: b.dataset.id, name: b.dataset.name }),
        deleteGroup: (b) => confirmAction(tr('Delete group'), tr('Memberships go with the group; contacts and users stay. Delete {name}?').replace('{name}', b.dataset.name), async () => {
          await post(c.url(`/${b.dataset.kind}-groups/${b.dataset.id}`), {}, 'DELETE');
          toast(t('Deleted successfully'));
          await render();
        }),
      });
    },
    "reminder-rules": async (c) => {
      const rules = await api(c.url('/reminder-rules'));
      const preview = rules.enabled ? rules.effective_stages.map((x) =>
        x.stage === 0 ? t('3 days before due') : t('{days} days overdue').replace('{days}', x.days)).join(' · ') : t('Automatic reminders are disabled.');
      if (!c.mount(page(t('Reminders'), t('Configure automatic invoice reminders for this organisation.'), '',
        `<section class="section"><h2>${tr('Reminder rules')}</h2><p>${tr('Stage 0 stays three days before due. Overdue stages must increase within 1 to 14 days.')}</p>
        <p id="reminder-preview" aria-live="polite">${tr('Current effective reminders')}: ${esc(preview)}</p>
        ${form(check('Enable automatic reminders', 'enabled', rules.enabled) +
          field('Stage 1: days after due', 'stage_1_days', rules.stages['1'], 'number', 'min="1" max="13" step="1" required') +
          field('Stage 2: days after due', 'stage_2_days', rules.stages['2'], 'number', 'min="2" max="14" step="1" required') +
          select('Stop after', 'stop_stage', [['', t('All stages')], ['0', t('Stage 0')], ['1', t('Stage 1')], ['2', t('Stage 2')]], rules.stop_stage ?? ''))}</section>`))) return;
      content.querySelector('[data-action=cancel]').remove();
      if (!canEditMappings()) content.querySelectorAll('input, select, button[type=submit]').forEach((x) => { x.disabled = true; });
      bindForm(content, async (data) => {
        await post(c.url('/reminder-rules'), {enabled: content.querySelector('[name=enabled]').checked,
          stages: {'1': Number(data.stage_1_days), '2': Number(data.stage_2_days)},
          stop_stage: data.stop_stage === '' ? null : Number(data.stop_stage)}, 'PUT');
        toast(t('Saved successfully'));
        await render();
      });
    },
    "exchange-rates": async (c) => {
      const [rows, runs] = await Promise.all([api(c.url('/exchange-rates')), api(c.url('/fx-revaluations'))]);
      const resultTable = (run) => table(['Document', 'Currency', 'Open portion', 'Booked base', 'Target base', 'Delta'],
        (run?.documents || []).map((x) => row([td(esc(x.document)), td(esc(x.currency)), td(esc(x.portion)),
          td(esc(x.booked_base)), td(esc(x.target)), td(esc(x.delta))])));
      const historyTable = (history) => table(['Date', 'Status', 'Posting batch'], history.map((x) => row([
        td(esc(x.revaluation_date)), td(tr(x.status)), td(esc(x.posting_batch_id || t('No posting')))])));
      if (!c.mount(page(t('Exchange rates'), t('Rates are units of the to currency per one unit of the from currency.'), '',
        table(['Date', 'From currency', 'To currency', 'Exchange rate', 'Source', 'Actions'], rows.map((x) => row([
          td(esc(x.rate_date)), td(esc(x.from_currency)), td(esc(x.to_currency)), td(esc(x.rate)), td(esc(x.source)),
          td(button('Delete rate', 'deleteRate', false, `data-id="${esc(x.id)}" ${canEditMappings() ? '' : 'disabled'}`))]))) +
        form(field('Date', 'rate_date', today(), 'date', 'required') +
          field('From currency', 'from_currency', '', 'text', 'pattern="[A-Z]{3}" maxlength="3" required') +
          field('To currency', 'to_currency', org.base_currency, 'text', 'pattern="[A-Z]{3}" maxlength="3" required') +
          field('Exchange rate', 'rate', '', 'text', 'inputmode="decimal" required'), 'Add rate') +
        `<section data-fx-revaluation><h2>${tr('Revalue balances')}</h2><p>${tr('Revalue current open foreign balances at the selected date rate.')}</p>` +
        form(field('Revaluation date', 'revaluation_date', today(), 'date', 'required'), 'Run revaluation') +
        `<div data-fx-result>${resultTable(runs[0])}</div><h3>${tr('Revaluation history')}</h3>` +
        `<div data-fx-history>${historyTable(runs)}</div></section>`))) return;
      content.querySelectorAll('[data-action=cancel]').forEach((x) => x.remove());
      if (!canEditMappings()) content.querySelectorAll('input, button[type=submit]').forEach((x) => { x.disabled = true; });
      bindForm(content, async (data) => {
        await post(c.url('/exchange-rates'), data);
        toast(t('Saved successfully'));
        await render();
      });
      const revaluation = content.querySelector('[data-fx-revaluation]');
      bindForm(revaluation, async (data) => {
        const result = await post(c.url('/fx-revaluations'), data);
        revaluation.querySelector('[data-fx-result]').innerHTML = resultTable(result);
        revaluation.querySelector('[data-fx-history]').innerHTML = historyTable(await api(c.url('/fx-revaluations')));
      });
      bindActions(content, {deleteRate: async (b) => {
        await post(c.url(`/exchange-rates/${b.dataset.id}`), {}, 'DELETE');
        await render();
      }});
    },
    "payment-methods": async (c) => {
      const rows = await api(c.url('/payment-methods'));
      if (!c.mount(page(t('Payment methods'), t('Configure payment URLs without a provider connection.'),
        button('Add payment method', 'newPaymentMethod', true, canEditMappings() ? '' : 'disabled'),
        table(['Name', 'Provider', 'Currency', 'Enabled', 'Actions'], rows.map((x) => row([
          td(esc(x.name)), td(esc(x.provider)), td(esc(x.currency || t('Any currency'))),
          td(tr(x.enabled ? 'Yes' : 'No')),
          td(button('Edit payment method', 'editPaymentMethod', false, `data-id="${esc(x.id)}" ${canEditMappings() ? '' : 'disabled'}`))])))))) return;
      bindActions(content, {
        newPaymentMethod: () => paymentMethodDialog(),
        editPaymentMethod: (b) => paymentMethodDialog(rows.find((x) => x.id === b.dataset.id)),
      });
    },
    periodised: async (c) => {
      const rows = await api(c.url('/purchase-schedules'));
      const actions = (x) => {
        const attrs = `data-id="${esc(x.id)}"`;
        return button('Purchase periods', 'viewPurchaseSchedule', false, attrs) +
          (x.status === 'Draft' ? button('Activate schedule', 'activatePurchaseSchedule', false, attrs) : '') +
          (x.status === 'Active' ? button('Post due portions', 'postPurchaseSchedule', false, attrs) : '') +
          (['Draft', 'Active'].includes(x.status) ? button('Cancel future portions', 'cancelPurchaseSchedule', false, attrs) : '');
      };
      if (!c.mount(page(t('Periodised'), t('Spread purchase expenses across accounting periods.'),
        button('New purchase schedule', 'newPurchaseSchedule', true), table(
          ['Bill', 'Supplier', 'Start period', 'Status', 'Progress', ['Net amount'], 'Actions'],
          rows.map((x) => row([td(esc(x.supplier_number)), td(esc(x.contact_name)), td(date(x.start_period)),
            td(pill(x.status)), td(`${esc(x.posted_periods)} / ${esc(x.number_of_periods)}`),
            td(esc(money(x.net_amount, x.currency)), 'numeric'), td(actions(x))])), button('New purchase schedule', 'newPurchaseSchedule'))))) return;
      const action = async (b, suffix, data) => {
        await post(c.url(`/purchase-schedules/${b.dataset.id}${suffix}`), data, suffix ? 'POST' : 'PATCH');
        await render();
      };
      bindActions(content, {
        newPurchaseSchedule: () => purchaseScheduleDialog(),
        viewPurchaseSchedule: (b) => purchaseScheduleDialog(b.dataset.id),
        activatePurchaseSchedule: (b) => action(b, '', {status: 'Active'}),
        postPurchaseSchedule: (b) => confirmAction('Post due portions', tr('Post balanced net expense transfers for all due portions. VAT stays on the original bill.'), () => action(b, '/post')),
        cancelPurchaseSchedule: (b) => confirmAction('Cancel future portions', tr('Future portions stop. Any remaining deferred cost needs accountant review.'), () => action(b, '/cancel')),
      });
    },
    recurring: async (c) => {
      const [schedules, reminders, invoices] = await Promise.all([
        api(c.url("/invoice-schedules")),
        api(c.url("/reminders/due")),
        api(c.url("/invoices")),
      ]);
      const intervals = { weekly: "Weekly", monthly: "Monthly", quarterly: "Quarterly", custom_days: "Custom days" },
        emailNotice = "Email delivery is not connected. Set POSTMARK_API_TOKEN and FROM_EMAIL to send reminders.";
      // The due endpoint excludes opted-out invoices; keep them reachable for opting back in.
      const items = [...reminders.items, ...invoices.filter((x) =>
        x.reminders_disabled && ["Issued", "Part Paid"].includes(x.status) &&
        !reminders.items.some((r) => r.invoice_id === x.id)
      ).map((x) => ({ ...x, invoice_id: x.id, stage: null }))];
      if (!c.mount(page(t("Recurring invoices"), t("Recurring & reminders"),
        button("New schedule", "newSchedule", true),
        `<section class="section">${table(
          ["Customer", "Name", "Interval", "Next run", "End date", "Auto-email", "Status", "Actions"],
          schedules.map((x) => row([
            td(esc(x.contact_name)), td(esc(x.name)),
            td(esc(x.interval_kind === "custom_days" ? t("Every {days} days").replace("{days}", num(x.interval_days)) : t(intervals[x.interval_kind]))),
            td(date(x.next_run_date)), td(date(x.end_date)),
            td(x.auto_email ? `<span class="cell-check" role="img" aria-label="${tr("Auto-email")}">${icon("check")}</span>` : "–"),
            td(pill(x.active ? "Active" : "Paused")),
            td(button(x.active ? "Pause" : "Resume", "toggleSchedule", false, `data-id="${esc(x.id)}"`) +
              button("Run now", "runSchedule", false, `data-id="${esc(x.id)}" ${!x.active || x.next_run_date > today() ? "disabled" : ""}`) +
              button("History", "scheduleHistory", false, `data-id="${esc(x.id)}"`)),
          ]))
        )}</section><section class="section"><div class="section-head"><h2>${tr("Reminders due")}</h2></div>
        ${reminders.email_connected === false ? `<div class="notice" role="status">${tr(emailNotice)}</div>` : ""}
        ${items.length ? table(["Number", "Customer", "Due date", "Stage", "Status", "Skip"], items.map((x, index) => row([
          td(esc(x.number)), td(esc(x.contact_name)), td(date(x.due_date)),
          td(x.stage == null ? "" : x.stage === 0 ? tr('3 days before due') : esc(t('{days} days overdue').replace('{days}',
            Math.round((Date.parse(x.target_date) - Date.parse(x.due_date)) / 86400000)))),
          td(x.sent ? pill("Sent") : x.reminders_disabled ? pill("Skipped") : button("Send reminder", "sendReminder", false, `data-index="${index}"`)),
          td(button("Skip", "skipReminder", false, `data-index="${index}" aria-pressed="${Boolean(x.reminders_disabled)}"`)),
        ]))) : empty("No reminders due")}</section>`))) return;
      bindActions(content, {
        newSchedule: () => {
          const d = dialog("New schedule", form(
            field("Name", "name") +
            select("Template invoice", "template_invoice_id", invoices.filter((x) => !x.document_type || x.document_type === "invoice").map((x) => [x.id, `${x.number || t("Draft")} · ${x.contact_name}`])) +
            select("Interval", "interval_kind", Object.entries(intervals).map(([k, v]) => [k, t(v)]), "monthly") +
            field("Days", "interval_days", "1", "number", 'min="1" max="365" step="1" required') +
            field("Next run", "next_run_date", today(), "date", "required") +
            field("End date", "end_date", "", "date") + check("Auto-email", "auto_email", false), "Create schedule"));
          d.querySelector('[name="template_invoice_id"]').required = true;
          const interval = d.querySelector('[name="interval_kind"]'), days = d.querySelector('[name="interval_days"]');
          const updateDays = () => {
            days.disabled = interval.value !== "custom_days";
            days.closest("label").hidden = days.disabled;
          };
          interval.onchange = updateDays;
          updateDays();
          bindForm(d, async (v) => {
            await post(c.url("/invoice-schedules"), {
              ...v, interval_days: v.interval_kind === "custom_days" ? Number(v.interval_days) : null,
              end_date: v.end_date || null, auto_email: v.auto_email === "on",
            });
            await saved(d);
          });
        },
        toggleSchedule: async (b) => {
          b.disabled = true;
          try {
            const schedule = schedules.find((x) => String(x.id) === b.dataset.id);
            await post(c.url(`/invoice-schedules/${b.dataset.id}`), { active: !schedule.active }, "PATCH");
            await render();
          } finally { b.disabled = false; }
        },
        runSchedule: async (b) => {
          b.disabled = true;
          try {
            const result = await post(c.url(`/invoice-schedules/${b.dataset.id}/run-now`));
            const count = result.runs.filter((x) => x.status === "Issued").length;
            const schedule = schedules.find((x) => String(x.id) === b.dataset.id);
            toast(count > 0 ? t("Invoices created: {count}").replace("{count}", num(count)) :
              t("Not due yet \u2014 next run {date}").replace("{date}", date(schedule.next_run_date)));
            result.runs.filter((x) => x.status === "Failed").forEach((x) => toast(t(x.error_message || "Failed"), "error"));
            await render();
          } finally { b.disabled = false; }
        },
        scheduleHistory: async (b) => {
          const schedule = await api(c.url(`/invoice-schedules/${b.dataset.id}`));
          if (org?.id !== c.oid || location.hash !== "#recurring") return;
          dialog("History", table(["Date", "Number", "Status", "Error"], schedule.runs.map((x) => row([
            td(date(x.run_date)), td(esc(x.invoice_number || "–")), td(pill(x.status)), td(tr(x.error_message || "–")),
          ]))));
        },
        sendReminder: async (b) => {
          b.disabled = true;
          try {
            const x = items[Number(b.dataset.index)];
            const result = await post(c.url(`/invoices/${x.invoice_id}/reminders/${x.stage}/send`));
            if (result.status === "Failed") toast(t(result.error_message || "Failed"), "error");
            else toast(t("Reminder sent"));
            await render();
          } finally { b.disabled = false; }
        },
        skipReminder: async (b) => {
          b.disabled = true;
          try {
            const x = items[Number(b.dataset.index)];
            await post(c.url(`/invoices/${x.invoice_id}/reminders/opt-out`), { reminders_disabled: !x.reminders_disabled });
            await render();
          } finally { b.disabled = false; }
        },
      });
    },
    bills: async (c) => {
      const [rows, orders, prepayments, contacts] = await Promise.all([
        api(c.url("/bills") + listQuery(c, "bills")), api(c.url("/payment-orders")), api(c.url("/prepayments?side=supplier")), api(c.url("/contacts")),
      ]);
      if (
        !c.mount(
          page(
            t("Bills"),
            t("Review supplier documents before posting."),
            button("New supplier", "supplier") +
              button("Record supplier prepayment", "newPrepayment", false, canExecutePush() ? "" : "disabled") +
              button("Import e-invoice", "importEInvoice") +
              button("Create payment order", "paymentOrder") +
              button("New bill", "bill", true),
            documentFilterControls(c, "bills", contacts) + table(
              [
                "Supplier no.",
                "Supplier",
                "Date",
                "Status",
                ["Total"],
                "Actions",
              ],
              rows.map((x) =>
                row([
                  td(esc(x.supplier_number)),
                  td(esc(x.contact_name)),
                  td(date(x.bill_date), "numeric"),
                  td(pill(x.status)),
                  cash(x.total, x.currency),
                  td(
                    button("Attachments", "billAttachments", false, `data-id="${esc(x.id)}"`) + (x.status === "Draft"
                      ? button("Review", "review", false, `data-id="${x.id}"`)
                      : x.status === "In Review"
                        ? button(
                            "Approve",
                            "approve",
                            true,
                            `data-id="${x.id}"`,
                          )
                        : ""),
                  ),
                ]),
              ),
              button("New bill", "bill"),
            ) + `<section class="section"><h2>${tr("Payment orders")}</h2>${table(
              ["Execution date", "Bills", ["Total"], "Actions"],
              orders.map((order) => row([td(date(order.execution_date)), td(esc(order.bill_count)),
                cash(order.total, order.lines[0]?.currency),
                td(link("Download XML", `/api${c.url(`/payment-orders/${order.id}.xml`)}`))])),
            )}</section>${prepaymentSection(prepayments, "supplier")}`,
          ),
        )
      )
        return;
      bindActions(content, {
        ...prepaymentActions(prepayments, "supplier"),
        bill: () => documentDialog("bill"),
        importEInvoice: () => eInvoiceImportDialog(),
        supplier: () => contactDialog("supplier"),
        paymentOrder: () => paymentOrderDialog(),
        billAttachments: (b) => documentDialog("bill", b.dataset.id),
        review: (b) =>
          confirmAction(
            "Review bill",
            tr("Send this bill for approval?"),
            async () => {
              await post(c.url(`/bills/${b.dataset.id}/review`));
              toast(t("Saved successfully"));
              await render();
            },
          ),
        approve: (b) =>
          confirmAction(
            "Approve bill",
            tr(
              "This creates an immutable ledger posting. Corrections require a credit note.",
            ),
            async () => {
              await post(c.url(`/bills/${b.dataset.id}/approve`));
              toast(t("Bill approved"));
              await render();
            },
          ),
      });
      bindDocumentFilters(c, "bills");
    },
    imports: async (c) => {
      if (!c.route[0]) {
        if (c.mount(page(t("Data import"), t("Upload CSV, review each row, then import valid rows."),
          button("Import", "masterImport", true) + (canEditMappings() ? button("Import journal workbook", "journalImport") + link("Import runs", "#integrations/runs/file_import") : ""), "")))
          bindActions(content, { masterImport: () => masterDataImportDialog(), journalImport: () => journalImportDialog(c) });
        return;
      }
      const base = c.url(`/imports/${encodeURIComponent(c.route[0])}`);
      const batch = await api(`${base}?limit=10000`);
      const issue = (value) => value.split("; ").map((x) => tr(x)).join("; ");
      if (!c.mount(page(t("Data import"), t("Upload CSV, review each row, then import valid rows."),
        batch.status === "staged" ? button("Import valid rows", "commitImport", true) + button("Discard import", "discardImport") : "",
        `<p>${tr("Status")}: ${tr({staged: "Staged import", committed: "Import committed", discarded: "Import discarded"}[batch.status])}</p>
        <p>${tr("Errors")}: ${num(batch.error_count)} · ${tr("Warnings")}: ${num(batch.warning_count)} · ${tr("Rows")}: ${num(batch.total_rows)}</p>
        <p class="muted">${tr("Existing records are skipped. Discarded rows are retained for audit.")}</p>` + table(
          ["Row", "Name", "Errors", "Warnings", "Created record"], batch.rows.map((x) => row([
            td(num(x.row_number)), td(esc(x.parsed.name || "")), td(issue(x.error)), td(issue(x.warning)), td(esc(x.entity_id || ""))])))))) return;
      bindActions(content, {
        commitImport: async (b) => {
          b.disabled = true;
          try { await post(`${base}/commit`); await render(); } finally { b.disabled = false; }
        },
        discardImport: async (b) => {
          b.disabled = true;
          try { await post(`${base}/discard`); await render(); } finally { b.disabled = false; }
        },
      });
    },
    contacts: async (c) => {
      const rows = await api(c.url("/contacts"));
      if (
        !c.mount(
          page(
            t("Contacts"),
            t("Customers and suppliers for this organisation."),
            button("New customer", "customer", true) +
              button("New supplier", "supplier") + button("Data import", "masterImport") +
              link("Export CSV", `/api${c.url('/contacts/export.csv')}`),
            `<div class="chips">${["All", "customer", "supplier", "both"].map((x) => `<button class="chip ${contactFilter === x ? "active" : ""}" data-contact-filter="${x}">${tr(x)}</button>`).join("")}</div><div id="contacts-table"></div>`,
          ),
        )
      )
        return;
      const draw = () => {
        document.getElementById("contacts-table").innerHTML = table(
          ["Name", "Type", "Email", "Country", "VAT number", "Actions"],
          rows
            .filter(
              (x) =>
                contactFilter === "All" ||
                x.contact_type === contactFilter ||
                (x.contact_type === "both" && contactFilter !== "both"),
            )
            .map((x) =>
              row([
                td(esc(x.name)),
                td(pill(x.contact_type)),
                td(esc(x.email || "–")),
                td(esc(x.country_code)),
                td(esc(x.vat_no || "–")),
                td(button("Statement of account", "statement", false, `data-id="${x.id}"`) +
                   button("Outstanding prepayments", "contactPrepayments", false, `data-id="${esc(x.id)}"`)),
              ]),
            ),
          button("New customer", "customer"),
        );
        bindActions(content, {
          customer: () => contactDialog("customer"),
          supplier: () => contactDialog("supplier"),
          masterImport: () => masterDataImportDialog("contacts"),
          statement: (b) => statementDialog(rows.find((x) => x.id === b.dataset.id)),
          contactPrepayments: (b) => contactPrepaymentsDialog(rows.find((x) => x.id === b.dataset.id)),
        });
      };
      draw();
      content.querySelectorAll("[data-contact-filter]").forEach(
        (b) =>
          (b.onclick = () => {
            contactFilter = b.dataset.contactFilter;
            content
              .querySelectorAll("[data-contact-filter]")
              .forEach((x) => x.classList.toggle("active", x === b));
            draw();
          }),
      );
    },
    banking: async (c) => {
      const [accounts, rows] = await Promise.all([
        api(c.url("/bank-accounts")),
        api(c.url("/bank-transactions")),
      ]);
      if (
        !c.mount(
          page(
            t("Banking"),
            t("Explainable matches. Every posting reviewed."),
            button("Add account", "account") +
              button("Import statement", "import", true) +
              link("Export CSV", `/api${c.url('/bank-transactions/export.csv')}`),
            `<div class="account-cards">${accounts.map((x) => `<article class="card"><div class="section-head">${icon("bank")}<span class="country-badge">${esc(x.currency)}</span></div><h2>${esc(x.name)}</h2><p class="muted">${esc(x.iban_masked || x.masked_iban || "")}</p></article>`).join("")}</div>${table(
              [
                "Date",
                "Counterparty",
                "Reference",
                ["Amount"],
                "Status",
                "Actions",
              ],
              rows.map((x) =>
                row([
                  td(date(x.booking_date), "numeric"),
                  td(esc(x.counterparty)),
                  td(esc(x.reference)),
                  cash(x.amount, x.currency),
                  td(pill(x.status)),
                  td(
                    x.status !== "Reconciled"
                      ? button("Review", "review", false, `data-id="${x.id}"`)
                      : "",
                  ),
                ]),
              ),
              button("Import statement", "import"),
            )}`,
          ),
        )
      )
        return;
      bindActions(content, {
        account: bankDialog,
        import: () => importDialog(accounts),
        review: (b) =>
          reviewTransaction(rows.find((x) => String(x.id) === b.dataset.id)),
      });
    },
    "fixed-assets": async (c) => {
      const groups = await api(c.url(`/asset-groups?locale=${encodeURIComponent(lang)}`));
      const [register, schedule, runs] = await Promise.all([
        api(c.url("/fixed-assets")), api(c.url("/fixed-assets/schedule")), api(c.url("/fixed-assets/runs")),
      ]);
      const totals = register.totals || {}, assets = register.assets || [];
      const financialCells = (x) => [cash(x.acquisition_cost ?? x.cost), cash(x.accumulated_depreciation), cash(x.carrying_value)];
      const groupName = (x) => x.group_name || groups.find((g) => g.id === x.group_id)?.name || "";
      if (!c.mount(page(t("Fixed assets"), t("Track asset cost, depreciation and carrying value."),
        button("Record asset acquisition", "acquireAsset", true, canExecutePush() ? "" : "disabled") +
        button("Add asset group", "addAssetGroup", false, canExecutePush() ? "" : "disabled") +
        button("Run depreciation", "runDepreciation", false, canExecutePush() ? "" : "disabled"),
        `<section class="section"><h2>${tr("Fixed assets register")}</h2>${table(
          ["Asset", "Asset group", "Acquisition date", "Acquisition cost", "Accumulated depreciation", "Carrying value", "Status", "Actions"],
          assets.map((x) => row([td(esc(x.name)), td(esc(groupName(x))), td(date(x.acquisition_date)),
            ...financialCells(x), td(pill(x.status)), td(x.status === "Active" ? button("Dispose asset", "disposeAsset", false,
              `data-id="${esc(x.id)}" ${canExecutePush() ? "" : "disabled"}`) : "")])),
          tr("Record an acquisition to start tracking depreciation."))}</section>` +
        `<section class="section"><h2>${tr("Asset group totals")}</h2><p class="muted">${tr("Disposed assets retain historical cost and depreciation. Group totals include this history; carrying value is zero after disposal.")}</p>${table(
          ["Asset group", "Annual depreciation percentage", "Frequency", "Acquisition cost", "Accumulated depreciation", "Carrying value"],
          [...(register.groups || []).map((x) => row([td(esc(x.name || x.group_name)), td(esc(num(x.annual_percentage)) + "%"), td(tr(assetFrequencyLabel(x.frequency))), ...financialCells(x)])),
            row([td(`<strong>${tr("Total")}</strong>`), td(""), td(""), ...financialCells(totals)], "total")])}</section>` +
        `<section class="section"><h2>${tr("Depreciation schedule")}</h2>${table(
          ["Asset", "Frequency", "Next depreciation date", "Depreciation amount"],
          schedule.map((x) => row([td(esc(x.name || x.asset_name)), td(tr(assetFrequencyLabel(x.frequency))),
            td(date(x.next_due_date || x.next_due)), cash(x.amount ?? x.next_amount)])))}</section>` +
        `<section class="section"><h2>${tr("Depreciation runs")}</h2>${table(
          ["Period date", "Frequency", "Status", "Posting batch"],
          runs.map((x) => row([td(date(x.period_date)), td(tr(assetFrequencyLabel(x.kind))), td(pill(x.status)),
            td(esc(x.posting_batch_id || ""))])))}</section>`))) return;
      bindActions(content, {
        acquireAsset: () => fixedAssetAcquisitionDialog(groups), addAssetGroup: assetGroupDialog,
        runDepreciation: depreciationRunDialog,
        disposeAsset: (b) => assetDisposalDialog(assets.find((x) => String(x.id) === b.dataset.id)),
      });
    },
    "cash-flow": async (c) => {
      reportTab = "cash-flow";
      await views.accounting(c);
    },
    accounting: async (c) => {
      const objects = await api(c.url('/objects'));
      if (
        !c.mount(
          page(
            t(reportTab === "cash-flow" ? "Cash-flow statement" : "Accounting"),
            t("Reports from your posted ledger."),
            button("Opening balances", "openingBalances") +
              button("Opening receivables/payables", "openingItems") +
              button("Print / save PDF", "print") + '<span id="report-exports" class="actions"></span>',
            `<div class="tabs" role="tablist">${Object.entries(reportNames)
              .map(
                ([key, label]) =>
                  `<button role="tab" aria-selected="${reportTab === key}" class="tab ${reportTab === key ? "active" : ""}" data-report="${key}">${tr(label)}</button>`,
              )
              .join(
                "",
              )}</div><form id="report-dates" class="date-range"><label id="report-start-label">${tr("From")}<input type="date" name="start" required></label><label><span id="report-end-label">${tr("To")}</span><input type="date" name="end" required></label><span id="report-period">${select("Report period", "period", [["range", t("Date range")], ["month", t("Month")], ["quarter", t("Quarter")], ["year", t("Year")]], "range")}</span><span id="report-comparison">${select("Comparison", "compare", [["none", t("No comparison")], ["previous", t("Previous period")], ["prior_year", t("Prior year")], ["ytd", t("Year to date (prior year)")]], "none")}</span><button class="button primary">${tr("Apply")}</button></form><div id="report-result" class="report-result"></div>`,
          ),
        )
      )
        return;
      bindActions(content, {
        print: () => window.print(),
        openingBalances: openingBalancesDialog,
        openingItems: openingItemsDialog,
      });
      const objectControl = document.createElement('span');
      objectControl.id = 'report-object';
      objectControl.innerHTML = select('Object filter', 'object_id', [['', t('All objects')],
        ...objects.map((x) => [x.id, `${t(objectTypeLabel(x.object_type))}: ${x.code} ${x.name}`])]);
      document.getElementById('report-dates').querySelector('button').before(objectControl);
      let request = 0;
      const f = document.getElementById("report-dates"),
        asAt = () =>
          ["balance-sheet", "receivables-aging", "payables-aging"].includes(
            reportTab,
          );
      const defaults = () => {
        f.elements.start.value = today().slice(0, 4) + "-01-01";
        f.elements.end.value = today();
        f.elements.period.value = "range";
        updateControls();
        document.getElementById("report-end-label").textContent = t(
          asAt() ? "As at" : "To",
        );
      };
      const comparative = () => ["profit-and-loss", "balance-sheet"].includes(reportTab);
      const updateControls = () => {
        objectControl.hidden = !['trial-balance', 'general-ledger', 'profit-and-loss'].includes(reportTab);
        document.getElementById("report-comparison").hidden = !comparative();
        document.getElementById("report-period").hidden = !comparative();
        document.getElementById("report-start-label").hidden = asAt() &&
          !(comparative() && f.elements.compare.value === "previous");
      };
      const applyPeriod = () => {
        const [year, month] = f.elements.end.value.split("-").map(Number);
        const period = f.elements.period.value;
        if (period === "range") return;
        const firstMonth = period === "year" ? 1 : period === "quarter" ? Math.floor((month - 1) / 3) * 3 + 1 : month;
        const lastMonth = period === "year" ? 12 : period === "quarter" ? firstMonth + 2 : month;
        f.elements.start.value = `${year}-${String(firstMonth).padStart(2, "0")}-01`;
        f.elements.end.value = `${year}-${String(lastMonth).padStart(2, "0")}-${new Date(year, lastMonth, 0).getDate()}`;
      };
      const load = async () => {
        const ticket = ++request;
        if (f.elements.start.value > f.elements.end.value && !asAt()) {
          toast(t("End date must follow start date."), "error");
          return;
        }
        const result = document.getElementById("report-result");
        const exports = document.getElementById('report-exports');
        exports.innerHTML = '';
        result.innerHTML = skeleton();
        const tab = reportTab;
        try {
          const q = new URLSearchParams(tab === "cash-flow"
            ? {date_from: f.elements.start.value, date_to: f.elements.end.value}
            : asAt() ? {as_at: f.elements.end.value}
            : {start: f.elements.start.value, end: f.elements.end.value});
          if (comparative()) {
            q.set("compare", f.elements.compare.value);
            if (asAt()) q.set("start", f.elements.start.value);
          }
          if (!objectControl.hidden && f.elements.object_id.value) q.set('object_id', f.elements.object_id.value);
          const data = await api(c.url(`/reports/${tab}?${q}`));
          if (ticket !== request || !result.isConnected) return;
          if (tab !== 'cash-summary') {
            exports.innerHTML = link('Export CSV', `/api${c.url(`/reports/${tab}.csv?${q}`)}`);
            if (tab === 'general-ledger') {
              const bounds = new URLSearchParams({date_from: q.get('start'), date_to: q.get('end')});
              exports.innerHTML += link('Export Excel', `/api${c.url(`/reports/general_ledger.xlsx?${bounds}`)}`);
            }
          }
          result.innerHTML = `<div class="report-heading"><h2>${tr(reportNames[tab])}</h2><p>${esc(org.name)} · ${date(f.elements.end.value)}</p></div>${renderReport(tab, data)}`;
        } catch (e) {
          if (ticket === request && result.isConnected) {
            result.innerHTML = empty("Unable to load this view");
            toast(e.message, "error");
          }
        }
      };
      defaults();
      await load();
      f.onsubmit = (e) => {
        e.preventDefault();
        if (comparative()) applyPeriod();
        load();
      };
      f.elements.compare.onchange = updateControls;
      f.elements.period.onchange = applyPeriod;
      content.querySelectorAll("[data-report]").forEach(
        (b) =>
          (b.onclick = () => {
            reportTab = b.dataset.report;
            content.querySelector(".page-title h1").textContent = t(
              reportTab === "cash-flow" ? "Cash-flow statement" : "Accounting");
            content.querySelectorAll("[data-report]").forEach((x) => {
              x.classList.toggle("active", x === b);
              x.setAttribute("aria-selected", String(x === b));
            });
            defaults();
            load();
          }),
      );
    },
    tax: async (c) => {
      const codes = await api(c.url("/tax-codes"));
      const editable = canEditMappings();
      if (
        !c.mount(
          page(
            t(org.country_code === "EE" ? "Estonian KMD" : "UK VAT"),
            t("Prepare, review, then export your workpaper."),
            button("Prepare workpaper", "prepare", true) +
              (org.country_code === "EE" ? button("Prepare VD", "vd") : ""),
            `<div class="notice">${tr("Exports require accountant review. No direct filing takes place.")}</div><section class="section"><h2>${tr("Tax codes")}</h2>${table(
              ["Code", "Description", ["Rate"]],
              codes.map((x) =>
                row([
                  td(esc(x.code)),
                  td(esc(x.name || x.description || "")),
                  td(num(x.rate) + "%", "numeric"),
                ]),
              ),
            )}</section><section class="section" data-vat-replacement><h2>${tr("VAT replacement")}</h2><p class="muted">${tr(
              "Replace a tax code across this organisation's draft invoices and bills. Posted documents are never changed.",
            )}</p><div id="vat-replacement-result" class="report-result"></div>${form(
              select("From tax code", "from_code_id", [["", t("Choose a tax code")], ...codes.map((x) => [x.id, `${x.code} · ${num(x.rate)}%`])]) +
                select("To tax code", "to_code_id", [["", t("Choose a tax code")], ...codes.map((x) => [x.id, `${x.code} · ${num(x.rate)}%`])]),
              "Preview",
            )}</section>`,
          ),
        )
      )
        return;
      const result = content.querySelector("#vat-replacement-result");
      let selection = null;
      const replacementForm = content.querySelector("[data-vat-replacement] form");
      bindForm(content.querySelector("[data-vat-replacement]"), async (values) => {
        if (values.from_code_id === values.to_code_id || !values.from_code_id)
          throw new Error(t("Choose two different tax codes."));
        selection = {from_code_id: values.from_code_id, to_code_id: values.to_code_id};
        const data = await post(c.url("/tax/replacement/preview"), selection);
        result.innerHTML =
        result.innerHTML =
          (data.documents.length
            ? `<p>${tr("{documents} draft documents would change; {lines} lines would be recalculated.")
                .replace("{documents}", num(data.documents.length))
                .replace("{lines}", num(data.documents.reduce((sum, x) => sum + x.affected_lines, 0)))}</p>` +
              table(
                ["Kind", "Document", "Status", "Lines", ["Old VAT"], ["New VAT"]],
                data.documents.map((x) =>
                  row([
                    td(tr(x.kind === "invoice" ? "Invoice" : "Bill")),
                    td(esc(x.label)),
                    td(pill(tr(x.status))),
                    td(`${num(x.affected_lines)} / ${num(x.total_lines)}`),
                    td(esc(money(x.old_tax_total, x.currency)), "numeric"),
                    td(esc(money(x.new_tax_total, x.currency)), "numeric"),
                  ]),
                ),
              ) +
              (editable ? button("Apply replacement", "applyReplacement", true) : "")
            : `<p class="notice">${t("Nothing to replace: no draft documents use the source tax code.")}</p>`) +
          `<p class="muted">${tr("Posted documents are skipped: {invoices} invoices and {bills} bills use the source code and must be reversed deliberately.")
            .replace("{invoices}", num(data.skipped_posted.invoice))
            .replace("{bills}", num(data.skipped_posted.bill))}</p>`;
        content.querySelectorAll("[data-action=applyReplacement]").forEach((x) => (x.disabled = !editable));
      });
      bindActions(content, {
        prepare: () => taxDialog(false),
        vd: () => taxDialog(true),
        applyReplacement: () =>
          confirmAction(
            tr("Apply VAT replacement"),
            tr("Draft lines with the source code switch to the target code and totals recalculate. Applied documents are audited. Continue?"),
            async () => {
              const summary = await post(c.url("/tax/replacement"), selection);
              toast(
                tr("Replacement applied: {documents} documents, {lines} lines.")
                  .replace("{documents}", num(summary.replaced_documents))
                  .replace("{lines}", num(summary.replaced_lines)),
              );
              await render();
            },
          ),
      });
    },
    payroll: async (c) => {
      if (!c.payrollSupported) {
        c.mount(page(t("Payroll"), t("People, payslips and postings for this client."), "",
          `<div class="notice" role="status">${tr("Payroll is available only for Estonian organisations with EUR books. Switch to an Estonian EUR organisation to manage payroll.")}</div>`));
        return;
      }
      const [employees, runs, connections, tsdPreparations, componentTypes, payouts, bankAccounts, payoutSummary] = await Promise.all([
        optionalPayroll(c.url("/employees")),
        optionalPayroll(c.url("/pay-runs")),
        api(c.url("/integrations")),
        optionalPayroll(c.url("/payroll/tsd-preparations")),
        optionalPayroll(c.url("/payroll/component-types")),
        optionalPayroll(c.url("/payroll/payouts")),
        optionalPayroll(c.url("/bank-accounts")),
        optionalPayroll(c.url("/payroll/payouts/summary")),
      ]);
      const accountingProviders = connections.filter((entry) => ["merit", "smartaccounts"].includes(entry.provider) && entry.status !== "Disconnected");
      await Promise.all((runs || []).map(async (run) => {
        run.pushes = await api(c.url(`/pay-runs/${run.id}/pushes`));
      }));
      const unavailable = employees === null || runs === null;
      (runs || []).forEach((run) => run.payouts = (payouts || []).filter((payout) => payout.pay_run_id === run.id));
      const tsdByRun = Object.fromEntries(
        [...(tsdPreparations || [])].reverse().map((preparation) => [
          String(preparation.pay_run_id),
          preparation,
        ]),
      );
      if (
        !c.mount(
          page(
            t("Payroll"),
            t("People, payslips and postings for this client."),
            button("Add employee", "employee") + button("Payout summary", "payoutSummary") +
              button("Absences", "absences") + button("Leave liability", "leaveLiability") +
              (['owner','administrator'].includes(org?.role) ? button("Leave settings", "leaveSettings") : "") +
              button("Payment types", "paymentTypes") + button("Payroll accounts", "payrollAccounts") + button("Payday settings", "paydaySettings") +
              button("Run payroll for month", "run", true),
            `${unavailable ? `<div class="notice">${tr("Payroll is not available yet.")}</div>` : ""}<section class="section"><div class="section-head"><h2>${tr("Employees")}</h2><span class="muted">${num(employees?.filter((x) => x.active).length)} ${tr("employees")}</span>${employees === null ? '' : link('Export Excel', `/api${c.url('/reports/employees.xlsx')}`)}</div>${table(
              [
                "Name",
                ["Gross salary"],
                ["Pension %"],
                "Tax-free minimum",
                "Status",
                "Actions",
              ],
              (employees || []).filter((x) => x.active).map((x) =>
                row([
                  td(
                    `<strong>${esc(x.name)}</strong>${x.board_member ? `<small>${pill("Board member")}</small>` : ""}${partTime(x)}${x.social_tax_minimum_exemption ? `<small>${tr("Social tax minimum exemption")}: ${esc(exemptionLabel(x.social_tax_minimum_exemption))}</small>` : ""}`,
                  ),
                  x.pay_basis === "hourly"
                    ? td(
                        `${esc(money(x.hourly_rate, "EUR"))} ${tr("per hour")}`,
                        "numeric",
                      )
                    : cash(x.gross_salary, "EUR"),
                  td(num(x.funded_pension_percent) + "%", "numeric"),
                  td(tr(x.apply_tax_free_minimum ? "Yes" : "No")),
                  td(pill(x.active ? "Active" : "Inactive")),
                  td(button("Edit", "edit", false, `data-id="${x.id}"`) + button("Archive", "archiveEmployee", false, `data-id="${esc(x.id)}"`) + button("Delete", "deleteEmployee", false, `data-id="${esc(x.id)}"`)),
                ]),
              ),
              button("Add employee", "employee"),
            )}</section>${(employees || []).some((x) => !x.active) ? `<section class="section archived-employees"><h2>${tr("Archived employees")}</h2>${table(["Name", "Actions"], employees.filter((x) => !x.active).map((x) => row([td(esc(x.name)), td(button("Unarchive", "unarchiveEmployee", false, `data-id="${esc(x.id)}"`) + button("Delete", "deleteEmployee", false, `data-id="${esc(x.id)}"`))])))}</section>` : ""}${declarationPanel(runs || [])}<section class="section"><h2>${tr("Pay runs")}</h2>${
              (runs || []).length
                ? table(
                    [
                      "Period",
                      "Status",
                      ["Gross"],
                      ["Net"],
                      ["Employer cost"],
                      "Actions",
                    ],
                    runs.map((r) =>
                      renderRun(
                        { ...r, tsd_preparation: tsdByRun[String(r.id)] },
                        c,
                        accountingProviders,
                      ),
                    ),
                  )
                : empty(
                    "No pay runs yet",
                    button("Run payroll for month", "run", true),
                  )
            }</section>`,
          ),
        )
      )
        return;
      bindActions(content, {
        ...pushActions(c),
        preparePush: async (b) => {
          await post(integrationUrl(c, b.dataset.provider, `/push/pay-runs/${encodeURIComponent(b.dataset.id)}/prepare`), {});
          await render();
        },
        employee: () => employeeDialog(),
        paymentTypes: () => paymentTypesDialog(c, componentTypes || []),
        absences: () => payrollAbsencesDialog(c, employees || []),
        leaveLiability: () => payrollLeaveLiabilityDialog(c),
        leaveSettings: () => payrollLeaveSettingsDialog(c),
        payrollAccounts: () => payrollAccountsDialog(c),
        paydaySettings: () => paydaySettingsDialog(c),
        managePayouts: (b) => payrollPayoutsDialog(c, runs.find((run) => run.id === b.dataset.id), bankAccounts || []),
        payoutSummary: () => payrollPayoutSummaryDialog(payoutSummary || []),
        archiveEmployee: async (b) => { await post(c.url(`/employees/${b.dataset.id}`), {active: false}, "PATCH"); await render(); },
        unarchiveEmployee: async (b) => { await post(c.url(`/employees/${b.dataset.id}`), {active: true}, "PATCH"); await render(); },
        deleteEmployee: (b) => confirmAction("Delete employee", tr("Delete this employee permanently? Employees with pay run history must be archived instead."), async () => {
          await post(c.url(`/employees/${b.dataset.id}`), undefined, "DELETE"); await render();
        }),
        editRunItem: (b) => {
          const run = runs.find((r) => r.id === b.dataset.run);
          payrollItemDialog(c, run, run.items.find((i) => i.id === b.dataset.id), componentTypes || []);
        },
        settleDeclaration: (b) => confirmAction("Reclassify TSD liabilities", tr("Post the TSD liability reclassification dated the 10th of the following month? This does not record a bank payment or submit a declaration."), async () => {
          await post(c.url(`/pay-runs/${b.dataset.id}/tsd/settle`)); await render();
        }),
        edit: (b) =>
          employeeDialog(employees.find((x) => String(x.id) === b.dataset.id)),
        run: () => payrollWizard(employees || []),
        approve: (b) => {
          const r = runs.find((x) => String(x.id) === b.dataset.id);
          confirmAction(
            "Approve & post",
            `${tr("This payroll will be posted to the ledger and cannot be edited.")}<br><strong>${tr("Employer cost")}: ${esc(money(r.total_employer_cost ?? r.employer_cost, "EUR"))}</strong>`,
            async () => {
              await post(c.url(`/pay-runs/${r.id}/approve`));
              toast(t("Payroll approved"));
              await render();
            },
          );
        },
        delete: (b) =>
          confirmAction(
            "Delete draft",
            tr("Delete this draft pay run?"),
            async () => {
              await post(
                c.url(`/pay-runs/${b.dataset.id}`),
                undefined,
                "DELETE",
              );
              toast(t("Draft deleted"));
              await render();
            },
          ),
        tsd_prepare: async (b) => {
          const r = runs.find((x) => String(x.id) === b.dataset.id);
          const preparation = await post(
            c.url(`/pay-runs/${r.id}/tsd/prepare`),
          );
          await render();
          tsdPreparationDialog(c, r, preparation);
        },
        tsd_review: async (b) => {
          const r = runs.find((x) => String(x.id) === b.dataset.id);
          const preparation = await api(
            c.url(`/pay-runs/${r.id}/tsd/${b.dataset.preparationId}`),
          );
          tsdPreparationDialog(c, r, preparation);
        },
      });
    },
    integrations: async (c) => {
      await integrationWorkspace(c);
    },
  };

  const integrationName = (item) =>
      catalog.integrations?.items?.[item.key]?.name || item.name,
    integrationDescription = (item) =>
      catalog.integrations?.items?.[item.key]?.description || item.description,
    integrationDirection = (item) =>
      catalog.integrations?.items?.[item.key]?.direction || item.direction || "",
    integrationUrl = (c, provider, suffix = "") =>
      c.url(`/integrations/${encodeURIComponent(provider)}${suffix}`),
    readyProviderOrder = ["file_import", "fasthr", "quickbooks", "xero", "merit", "merit_palk", "smartaccounts", "open_banking"];

  const importTypeLabel = (objectType) => t({
    employee: "Employees", employees: "Employees", account: "Chart of accounts",
    contact: "Contacts", sales_invoice: "Sales invoices", purchase_invoice: "Purchase invoices",
    payment: "Payments", gl_entry: "General ledger entries", journal: "Bookkeeping journal",
    salary_agreement: "Merit Palk salary agreements", salary_hours: "Merit Palk salary and hours",
    vacation_balance: "Merit Palk vacation balances",
  }[objectType] || objectType);

  function integrationCard(c, item, connection) {
    const provider = item.key,
      name = integrationName(item),
      fileImport = provider === "file_import",
      status = fileImport ? "No connection needed" : connection?.status || "Not configured",
      accountingImport = ["merit", "smartaccounts", "merit_palk"].includes(provider),
      canImport = status === "Connected",
      actions = fileImport
        ? button("Recent runs", "integrationRuns", false, `data-provider="${esc(provider)}"`) +
          button("Import file", "importEmployeeFile", true, `data-provider="${esc(provider)}"`)
        : button("Configure", "configureIntegration", false, `data-provider="${esc(provider)}"`) +
          button("Test connection", "testIntegration", false, `data-provider="${esc(provider)}"`) +
          (connection ? button("Disconnect", "disconnectIntegration", false, `data-provider="${esc(provider)}"`) : "") +
          (provider === "fasthr"
            ? button("Recent runs", "integrationRuns", false, `data-provider="${esc(provider)}"`) +
              button("Run employee import", "runEmployeeImport", true, `data-provider="${esc(provider)}" ${canImport ? "" : `disabled title="${tr("Test the connection before importing.")}"`}`)
            : accountingImport
              ? button("Recent runs", "integrationRuns", false, `data-provider="${esc(provider)}"`) +
                button("Import data", "importIntegrationData", true, `data-provider="${esc(provider)}" ${canImport ? "" : `disabled title="${tr("Test the connection before importing.")}"`}`)
              : "");
    const bankActions = provider === "open_banking"
      ? button("Configure", "configureIntegration", false, `data-provider="open_banking"`) +
        (connection ? button("Disconnect", "disconnectIntegration", false, `data-provider="open_banking"`) : "") +
        button("Connect bank", "connectBank", true, connection && status !== "Disconnected" ? "" : "disabled") +
        (connection?.config?.requisition_id && status !== "Disconnected" ? button("I've approved at the bank", "completeBankLink") : "")
      : actions;
    return `<article class="card integration-provider" data-provider="${esc(provider)}"><div class="integration-provider-head"><img src="${esc(item.logo)}" alt="${esc(name)}"><div><h2>${esc(name)}</h2><div class="integration-statuses"><span>${tr("Registry status")}: ${pill(item.registry_status)}</span><span class="connection-status">${tr("Connection status")}: ${pill(status)}</span></div></div></div><p>${esc(integrationDescription(item))}</p><p class="integration-direction">${esc(integrationDirection(item))}</p><div class="integration-actions">${bankActions}</div>${provider === "open_banking" && connection ? `<div class="bank-feed-status" aria-live="polite"></div>` : ""}${provider === "open_banking" && status === "Connected" ? `<div class="bank-feed-accounts" aria-live="polite"><p>${tr("Loading bank accounts")}</p></div>` : ""}</article>`;
  }

  function plannedIntegration(item) {
    const name = integrationName(item);
    return `<article class="planned-integration"><img src="${esc(item.logo)}" alt="${esc(name)}"><div><h3>${esc(name)}</h3><p>${esc(integrationDescription(item))}</p></div>${pill(item.registry_status)}</article>`;
  }

  async function integrationWorkspace(c) {
    const catalogue = await api("/integrations"),
      [subview, provider, syncRunId] = c.route,
      item = provider && catalogue.find((entry) => entry.key === provider);
    if (subview && (!item || !["review", "runs", "accounting"].includes(subview))) {
      c.mount(
        page(
          t("Integration not found"),
          t("This integration or review link is not available."),
          link("Back to integrations", "#integrations"),
        ),
      );
      return;
    }
    if (subview === "review") {
      if (!syncRunId) {
        c.mount(
          page(
            t("Integration not found"),
            t("This integration or review link is not available."),
            link("Back to integrations", "#integrations"),
          ),
        );
        return;
      }
      await integrationReview(c, item, provider, syncRunId);
      return;
    }
    if (subview === "accounting") {
      await accountingIntegration(c, item, provider);
      return;
    }
    if (subview === "runs") {
      await integrationRuns(c, item, provider);
      return;
    }

    const [connections, email] = await Promise.all([
        api(c.url("/integrations")),
        api("/email-status"),
      ]),
      byProvider = new Map(connections.map((connection) => [connection.provider, connection])),
      ready = catalogue
        .filter((entry) => entry.registry_status === "Adapter ready" || ["merit", "smartaccounts", "merit_palk"].includes(entry.key))
        .sort((left, right) => {
          const leftIndex = readyProviderOrder.indexOf(left.key),
            rightIndex = readyProviderOrder.indexOf(right.key);
          return (leftIndex < 0 ? 999 : leftIndex) - (rightIndex < 0 ? 999 : rightIndex);
        }),
      planned = catalogue.filter((entry) => entry.registry_status !== "Adapter ready" && !["merit", "smartaccounts", "merit_palk"].includes(entry.key));
    if (
      !c.mount(
        page(
          t("Integrations"),
          t("Configure, test and review data for this client."),
          link("Public catalogue", "/integrations"),
          `<section class="integration-ready"><div class="section-head"><h2>${tr("Ready to connect")}</h2><span class="muted">${num(ready.length)} ${tr("providers")}</span></div><div class="integration-grid">${ready.map((entry) => integrationCard(c, entry, byProvider.get(entry.key))).join("")}</div></section><details class="planned-integrations section"><summary><span>${tr("Planned integrations")}</span><small>${num(planned.length)} ${tr("providers")}</small></summary><div class="planned-integration-list">${planned.map(plannedIntegration).join("")}</div></details><section class="card section email-integration"><div class="section-head"><h2>${tr("Email delivery")}</h2>${pill(email.connected ? "Connected" : "Disconnected")}</div><p>Postmark${email.from_email ? ` · ${esc(email.from_email)}` : ""}</p><p class="muted">${tr("Connect email delivery by setting POSTMARK_API_TOKEN and FROM_EMAIL in the deployment environment (.env).")}</p></section>`,
        ),
      )
    )
      return;
    content.querySelectorAll('.integration-provider').forEach((card) => {
      if (["merit", "smartaccounts"].includes(card.dataset.provider))
        card.querySelector('.integration-actions').insertAdjacentHTML('beforeend', link("Journal pushes and mappings", `#integrations/accounting/${encodeURIComponent(card.dataset.provider)}`));
    });
    const findItem = (button) =>
        catalogue.find((entry) => entry.key === button.dataset.provider),
      findConnection = (button) => byProvider.get(button.dataset.provider);
    bindActions(content, {
      connectBank: () => bankConsentDialog(c),
      completeBankLink: async () => {
        const connection = await post(integrationUrl(c, "open_banking", "/complete-link"));
        toast(t(connection.status === "Connected" ? "Bank consent completed" : "Bank consent is not complete. Approve at the bank and try again."));
        await render();
      },
      configureIntegration: (button) =>
        integrationDialog(c, findItem(button), findConnection(button)),
      testIntegration: (button) =>
        integrationDialog(c, findItem(button), findConnection(button), true),
      disconnectIntegration: (button) => {
        const selectedProvider = button.dataset.provider;
        confirmAction(
          "Disconnect integration",
          tr("Disconnect this integration? Stored credentials remain encrypted until a new configuration replaces them."),
          async () => {
            await post(integrationUrl(c, selectedProvider, "/disconnect"));
            toast(t("Integration disconnected"));
            await render();
          },
        );
      },
      runEmployeeImport: async (button) => {
        const summary = await post(integrationUrl(c, button.dataset.provider, "/sync"), {
          object_type: "employee",
        });
        toast(
          t("Employee records staged: {count}").replace(
            "{count}",
            num(summary.read_count),
          ),
        );
        location.hash = `integrations/review/${encodeURIComponent(button.dataset.provider)}/${encodeURIComponent(summary.id)}`;
      },
      importEmployeeFile: (button) =>
        fileImportDialog(c, findItem(button)),
      importIntegrationData: (button) =>
        integrationImportDialog(c, findItem(button)),
      integrationRuns: (button) => {
        location.hash = `integrations/runs/${encodeURIComponent(button.dataset.provider)}`;
      },
    });
    const statusTarget = content.querySelector(".bank-feed-status");
    if (statusTarget) await bankFeedStatus(c, statusTarget);
    const target = content.querySelector(".bank-feed-accounts");
    if (target) await bankFeedAccounts(c, target);
  }

  function integrationImportDialog(c, item) {
    const palk = item.key === "merit_palk";
    const d = dialog("Import data", form(
      select("Object type", "object_type", (item.pull_object_types || []).map((type) =>
        [type, palk && type === "employee" ? t("Merit Palk employees") : importTypeLabel(type)])) +
      (palk ? `<label>${tr("Accounting month")}<input type="month" name="month" required value="${new Date().toISOString().slice(0, 7)}"></label>` +
        field("Personal code", "personal_code", "", "text", `title="${tr("Employee lists are limited to 100 results. For larger companies, import each PersonalCode separately; ranges and pagination are not supported.")}"`) + field("Contract import code (vacation balance)", "contract_code") +
        `<label>${tr("Balance date")}<input type="date" name="balance_date" value="${new Date().toISOString().slice(0, 10)}"></label>` +
        `<label class="check full-width"><input type="checkbox" name="monthly_amounts">${tr("I confirm the selected salary agreement rates are monthly amounts")}</label>` +
        `<p class="full-width">${tr("Salary and hours fill draft pay runs. Review employee names and salary types; unpaid salaries may affect the report.")}</p>` : "") +
      `<p class="full-width">${tr("Records are staged for review. Nothing changes until decisions are applied.")}</p>`,
      "Import data",
    ));
    d.querySelector('[name="object_type"]').required = true;
    bindForm(d, async (data) => {
      d.dataset.pending = "true";
      let summary;
      try {
        summary = await post(integrationUrl(c, item.key, "/sync"), {
          object_type: data.object_type,
          ...(palk ? {config: {month: data.month.replace("-", ""), personal_code: data.personal_code,
            contract_code: data.contract_code, balance_date: data.balance_date,
            salary_amount_basis: d.querySelector('[name="monthly_amounts"]').checked ? "monthly" : ""}} : {}),
        });
      } finally {
        d.dataset.pending = "false";
      }
      if (d._originOrg !== org?.id || d._originView !== location.hash) return closeDialog(d);
      closeDialog(d);
      const stagedCount = Object.values(summary.staged_counts || {}).reduce(
        (sum, value) => sum + Number(value || 0), 0,
      );
      toast(t("Records staged: {count}").replace("{count}", num(stagedCount)));
      location.hash = `integrations/review/${encodeURIComponent(item.key)}/${encodeURIComponent(summary.id)}`;
    });
  }

  async function bankConsentDialog(c) {
    const country = org.country_code === "EE" ? "EE" : "GB",
      institutions = await api(integrationUrl(c, "open_banking", `/institutions?country=${country}`)),
      d = dialog("Connect bank", form(
        select("Bank institution", "institution_id", [["", t("Choose a bank")], ...institutions.map((bank) => [bank.id, bank.name])]),
        "Connect bank"));
    d.querySelector('[name="institution_id"]').required = true;
    bindForm(d, async (data) => {
      // Open during the submit gesture so the bank consent tab is not blocked.
      const bankTab = window.open("about:blank", "_blank");
      if (bankTab) bankTab.opener = null;
      try {
        const result = await post(integrationUrl(c, "open_banking", "/link"), {
          institution_id: data.institution_id,
          redirect_url: `${location.origin}${location.pathname}#integrations`,
        });
        const url = new URL(result.link);
        if (url.protocol !== "https:") throw new Error(t("Invalid bank consent link"));
        closeDialog(d);
        await render();
        const card = content.querySelector('.integration-provider[data-provider="open_banking"] .integration-actions');
        if (card) card.insertAdjacentHTML("beforeend", `<a class="button" href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${tr("Open bank consent")}</a>`);
        if (bankTab) bankTab.location.href = url.href;
      } catch (error) {
        bankTab?.close();
        throw error;
      }
    });
  }

  async function bankFeedStatus(c, target) {
    try {
      const state = await api(integrationUrl(c, "open_banking", "/pull-status"));
      if (!target.isConnected) return;
      const reauth = state.connection_status === "Reauth Required";
      target.innerHTML = `<h3>${tr("Daily bank feed")}</h3><p class="muted">${tr(state.worker_enabled ? "Mapped bank accounts are pulled once daily." : "Daily bank feed worker is disabled.")}</p>` +
        (reauth ? `<p class="notice" role="alert">${tr("Bank consent has expired. Re-link the bank to resume daily pulls.")}</p>` : "") +
        (state.schedules.length ? state.schedules.map((schedule) =>
          `<div class="section"><p>${esc(schedule.gocardless_account_id)} · ${tr(schedule.active ? "Active" : "Inactive")}</p><p>${tr("Last scheduled pull")}: ${esc(schedule.last_pull_at || t("Not yet pulled"))}</p><p>${tr("Last pull result")}: ${tr(schedule.last_result || "Not yet pulled")}</p>${schedule.last_error_message ? `<p class="notice">${tr(schedule.last_error_message)}</p>` : ""}</div>`).join("") : `<p>${tr("Link a bank account to enable daily pulls.")}</p>`);
    } catch (error) {
      if (target.isConnected) target.innerHTML = `<p class="notice" role="alert">${esc(error.message)}</p>`;
    }
  }

  async function bankFeedAccounts(c, target) {
    try {
      const [accounts, banks] = await Promise.all([
        api(integrationUrl(c, "open_banking", "/accounts")), api(c.url("/bank-accounts")),
      ]);
      if (!target.isConnected) return;
      target.innerHTML = `<h3>${tr("Linked bank accounts")}</h3>` + (accounts.length ? accounts.map((account) =>
        `<div class="section"><p>${esc(account.iban || account.gocardless_account_id)}</p><p class="muted">${tr("Balances")}: ${account.balances.map((balance) => esc(`${balance.balanceAmount?.amount || ""} ${balance.balanceAmount?.currency || ""} (${balance.balanceType || ""})`)).join(" · ")}</p>${account.bank_account_id
          ? `<p>${esc(banks.find((bank) => bank.id === account.bank_account_id)?.name || "")}</p>${button("Pull now", "pullBankTransactions", true, `data-account="${esc(account.gocardless_account_id)}"`)}`
          : `${button("Link bank account", "mapBankAccount", false, `data-account="${esc(account.gocardless_account_id)}"`)}<p class="muted">${tr("Link an existing bank account before pulling transactions.")}</p>`}</div>`).join("")
        : `<p>${tr("No bank accounts returned. Complete bank consent first.")}</p>`);
      bindActions(target, {
        mapBankAccount: (button) => {
          const d = dialog("Link bank account", form(select("Bank account", "bank_account_id",
            [["", t("Choose a bank account")], ...banks.map((bank) => [bank.id, `${bank.name} (${bank.currency})`])])));
          d.querySelector('[name="bank_account_id"]').required = true;
          bindForm(d, async (data) => {
            await post(integrationUrl(c, "open_banking", "/link-account"), {
              gocardless_account_id: button.dataset.account, bank_account_id: data.bank_account_id,
            });
            closeDialog(d);
            await bankFeedAccounts(c, target);
            const statusTarget = content.querySelector(".bank-feed-status");
            if (statusTarget) await bankFeedStatus(c, statusTarget);
          });
        },
        pullBankTransactions: async (button) => {
          button.disabled = true;
          try {
            const summary = await post(integrationUrl(c, "open_banking", "/pull"), {gocardless_account_id: button.dataset.account});
            toast(t("Bank transactions imported: {imported}; skipped: {skipped}")
              .replace("{imported}", num(summary.imported)).replace("{skipped}", num(summary.skipped)));
          } finally {
            button.disabled = false;
            const statusTarget = content.querySelector(".bank-feed-status");
            if (statusTarget) await bankFeedStatus(c, statusTarget);
          }
        },
      });
    } catch (error) {
      if (target.isConnected) target.innerHTML = `<p class="notice" role="alert">${esc(error.message)}</p>`;
      const statusTarget = content.querySelector(".bank-feed-status");
      if (statusTarget) await bankFeedStatus(c, statusTarget);
    }
  }

  function fileImportDialog(c, item) {
    if (!item) return;
    const d = dialog(
      "Import employee file",
      `<div class="file-import-intro"><strong>${esc(integrationName(item))}</strong><p>${tr("Upload a CSV or TSV export, or paste its contents below. Your browser reads the selected file; the raw contents are not retained after staging.")}</p><p class="muted">${tr("Only CSV and TSV files are supported. Export Excel workbooks as CSV first.")}</p></div><form novalidate><div class="form-grid file-import-form"><label>${tr("CSV or TSV file")}<input name="employee_file" type="file" accept=".csv,.tsv,text/csv,text/tab-separated-values"><span class="field-error" data-error="employee_file"></span></label><label>${tr("CSV or TSV contents")}<textarea name="csv_content" rows="9" maxlength="2000000" placeholder="${tr("Paste CSV or TSV contents")}"></textarea><span class="field-error" data-error="csv_content"></span></label></div><p class="form-error" role="alert"></p><div class="dialog-actions">${button("Cancel", "cancel")}<button class="button primary" type="submit">${tr("Stage employees")}</button></div></form>`,
    );
    bindForm(d, async (data, formElement) => {
      const file = formElement.elements.employee_file.files[0],
        csvContent = file
          ? await file.text()
          : String(data.csv_content || "");
      if (!csvContent.trim())
        throw new Error(t("Choose a CSV or TSV file, or paste its contents."));
      if (csvContent.length > 2000000)
        throw new Error(t("File is too large. The limit is 2,000,000 characters."));
      const summary = await post(
        integrationUrl(c, "file_import", "/import"),
        { object_type: "employee", csv_content: csvContent },
      );
      closeDialog(d);
      toast(
        t("Employee records staged: {count}").replace(
          "{count}",
          num(summary.read_count),
        ),
      );
      location.hash = `integrations/review/file_import/${encodeURIComponent(summary.id)}`;
    });
  }

  function integrationCredentialField(meta, connection) {
    const value =
        meta.input_type === "secret"
          ? ""
          : connection?.config?.[meta.name] ?? meta.default ?? "",
      required = meta.required && !connection ? "required" : "",
      note = meta.note ? `<small class="field-help">${tr(meta.note)}</small>` : "";
    if (meta.input_type === "boolean")
      return `<label class="check integration-check"><input type="checkbox" name="${esc(meta.name)}" ${value ? "checked" : ""}>${tr(meta.label)}${note}</label>`;
    const secret = meta.input_type === "secret";
    return `<label>${tr(meta.label)}<input name="${esc(meta.name)}" type="${secret ? "password" : "text"}" value="${esc(value)}" ${required} ${secret ? `autocomplete="new-password" placeholder="${tr("Enter secret")}"` : ""}><span class="field-error" data-error="${esc(meta.name)}"></span>${note}</label>`;
  }

  function integrationPayload(item, connection, data) {
    const credentials = {};
    for (const meta of item.credential_fields || [])
      credentials[meta.name] =
        meta.input_type === "boolean"
          ? data[meta.name] === "on"
          : String(data[meta.name] ?? "").trim();
    return {
      credentials,
      config: connection?.config || {},
      external_tenant_id: String(data.external_tenant_id || "").trim(),
    };
  }

  function integrationDialog(c, item, connection, focusTest = false) {
    if (!item) return;
    const name = integrationName(item),
      hasSecret = (item.credential_fields || []).some(
        (meta) => meta.input_type === "secret",
      ),
      d = dialog(
        "Configure integration",
        `<div class="integration-dialog-intro"><strong>${esc(name)}</strong>${item.credential_note ? `<p>${tr(item.credential_note)}</p>` : ""}${hasSecret && connection ? `<p class="notice">${tr("Saved secrets are never shown. Leave secret fields blank to keep and test the saved values, or enter new ones to replace them.")}</p>` : ""}</div><form novalidate><div class="form-grid integration-form">${(item.credential_fields || []).map((meta) => integrationCredentialField(meta, connection)).join("")}${field("External tenant ID", "external_tenant_id", connection?.external_tenant_id || "")}</div><div class="connection-test-result" role="status" aria-live="polite"></div><p class="form-error" role="alert"></p><div class="dialog-actions">${button("Cancel", "cancel")}${button("Test connection", "testConnection")}<button class="button primary" type="submit">${tr("Save configuration")}</button></div></form>`,
      ),
      testButton = d.querySelector("[data-action=testConnection]"),
      result = d.querySelector(".connection-test-result");
    bindForm(d, async (data, formElement) => {
      const intent = formElement.dataset.intent || "save";
      formElement.dataset.intent = "save";
      const payload = integrationPayload(item, connection, data);
      if (intent === "test") {
        testButton.disabled = true;
        try {
          const checked = await post(
            integrationUrl(c, item.key, "/test"),
            { credentials: payload.credentials, config: payload.config },
          );
          const status = checked.ok && checked.live ? (item.key === "open_banking" ? "Configured" : "Connected") : "Error";
          result.innerHTML = `<div class="test-result ${checked.ok && checked.live ? "success" : "danger"}"><div>${pill(status)}<strong>${tr(checked.live ? "Live connection" : "Configuration check")}</strong></div><p>${esc(translateError(checked.message))}</p></div>`;
          await refreshIntegrationStatus(c, item.key, connection);
        } catch (error) {
          result.innerHTML = `<div class="test-result danger"><div>${pill("Error")}<strong>${tr("Connection failed")}</strong></div><p>${esc(error.message)}</p></div>`;
          await refreshIntegrationStatus(c, item.key, connection);
          throw error;
        } finally {
          testButton.disabled = false;
        }
        return;
      }
      await post(integrationUrl(c, item.key), payload);
      closeDialog(d);
      toast(t("Integration saved"));
      await render();
    });
    testButton.onclick = () => {
      const formElement = d.querySelector("form");
      formElement.dataset.intent = "test";
      formElement.requestSubmit();
    };
    if (focusTest) testButton.focus();
  }

  async function refreshIntegrationStatus(c, provider, existingConnection) {
    if (!existingConnection) return;
    const connections = await api(c.url("/integrations")),
      current = connections.find((entry) => entry.provider === provider),
      card = content.querySelector(
        `.integration-provider[data-provider="${CSS.escape(provider)}"]`,
      ),
      target = card?.querySelector(".connection-status"),
      importButton = card?.querySelector('[data-action="runEmployeeImport"], [data-action="importIntegrationData"]');
    if (target)
      target.innerHTML = `${tr("Connection status")}: ${pill(current?.status || "Not configured")}`;
    if (importButton) {
      importButton.disabled = current?.status !== "Connected";
      importButton.title = importButton.disabled
        ? t("Test the connection before importing.")
        : "";
    }
  }

  const stagedDecisionEligible = (record) =>
    !record.display_only && ["Pending", "Failed"].includes(record.status);

  function stagedRecordRow(record, objectType) {
    const payload = record.external_payload || {};
    if (objectType === "journal") {
      const review = record.journal_review || {}, eligible = stagedDecisionEligible(record);
      return row([
        td(`<strong>${esc(payload.name)}</strong><small>${esc(payload.sheet)} · ${esc(payload.date || t("Posting date required"))}</small>` +
          `<p>${tr("Debit total")}: ${esc(review.debit_total)} · ${tr("Credit total")}: ${esc(review.credit_total)} · ${tr(review.balanced ? "Balanced" : "Unbalanced")}</p>` +
          table(["Account", "Description", "Debit", "Credit", "Account mapping"], (review.lines || []).map((line) => row([
            td(esc(line.account_code)), td(esc(line.description)), td(esc(line.debit ?? "")), td(esc(line.credit ?? "")),
            td(line.account_id ? esc(line.local_account_code) : tr("Journal account is unmapped") + button("Map journal account", "mapJournalAccount", false, `data-code="${esc(line.account_code)}"`)),
          ])))),
        td(pill(record.status)), td(esc(record.matched_local_id || t("No local match"))),
        td(review.warning ? tr(review.warning) : "–"),
        td(eligible ? `<div class="decision-options"><label class="check"><input type="checkbox" data-decision="apply" data-id="${esc(record.id)}" ${review.valid ? "" : "disabled"}>${tr("Approve")}</label><label class="check"><input type="checkbox" data-decision="reject" data-id="${esc(record.id)}">${tr("Reject")}</label></div>` : tr("Decision recorded")),
      ]);
    }
    let displayName =
        payload.name ||
        [payload.first_name, payload.last_name].filter(Boolean).join(" ") ||
        record.external_id ||
        "–",
      details = [payload.email, payload.personal_id];
    if (objectType === "vacation_balance") {
      details = [payload.date, `${t("Unused vacation days")}: ${payload.DaysUnused}`];
    } else if (objectType === "salary_hours") {
      details = [payload.period, `${t("Gross")}: ${payload.gross_pay}`, `${t("Hours worked")}: ${payload.hours}`];
    } else if (objectType === "contact") {
      details = [payload.registration_no || payload.registry_code, payload.email];
    } else if (["sales_invoice", "purchase_invoice"].includes(objectType)) {
      displayName = payload.external_number || payload.number || payload.supplier_number || record.external_id;
      details = [payload.buyer_name || payload.supplier_name, payload.total, payload.currency];
    } else if (objectType === "payment") {
      displayName = payload.reference || record.external_id;
      details = [payload.amount, payload.currency];
    } else if (objectType === "account") {
      displayName = [payload.code, payload.name].filter(Boolean).join(" · ") || record.external_id;
      details = [];
    } else if (objectType === "gl_entry") {
      displayName = payload.document || payload.document_number || record.external_id;
      details = [payload.external_account_code,
        payload.debit != null ? `${t("Debit")}: ${payload.debit}` : null,
        payload.credit != null ? `${t("Credit")}: ${payload.credit}` : null];
    }
    const detail = details.filter((value) => value != null && value !== "").map(esc).join(" · "),
      eligible = stagedDecisionEligible(record);
    return row([
      td(`<strong>${esc(displayName)}</strong>${detail ? `<small>${detail}</small>` : ""}<details class="payload-details"><summary>${tr("View source record")}</summary><pre>${esc(JSON.stringify(payload, null, 2))}</pre></details>`),
      td(pill(record.status)),
      td(esc(record.matched_local_name || record.matched_local_employee_name || t("No local match"))),
      td(record.review_note ? esc(translateError(record.review_note)) : "–"),
      td(
        eligible
          ? `<div class="decision-options" role="group" aria-label="${tr("Decision")}"><label class="check"><input type="checkbox" data-decision="apply" data-id="${esc(record.id)}">${tr(record.status === "Failed" ? "Retry apply" : "Approve")}</label><label class="check"><input type="checkbox" data-decision="reject" data-id="${esc(record.id)}">${tr("Reject")}</label></div>`
          : `<span class="muted">${tr(record.display_only ? "Display-only snapshot" : "Decision recorded")}</span>`,
      ),
    ]);
  }

  function integrationOutcomeSummary(outcome) {
    if (!outcome) return "";
    const reasons = outcome.outcomes.filter((entry) => entry.reason);
    return `<section class="section outcome-summary" aria-live="polite"><div class="section-head"><h2>${tr("Import outcomes")}</h2><span>${pill(outcome.failed ? "Failed" : "Completed")}</span></div><div class="kpis compact-kpis">${[
      ["Applied", outcome.applied],
      ["Updated", outcome.updated],
      ["Unchanged", outcome.unchanged],
      ["Rejected", outcome.rejected],
      ["Failed", outcome.failed],
    ].map(([label, value]) => kpi(label, num(value))).join("")}</div>${reasons.length ? `<div class="notice danger-notice"><strong>${tr("Outcome reasons")}</strong><ul>${reasons.map((entry) => `<li>${esc(translateError(entry.reason))}</li>`).join("")}</ul></div>` : ""}</section>`;
  }

  async function integrationReview(c, item, provider, syncRunId, outcome = null) {
    const review = await api(
        integrationUrl(
          c,
          provider,
          `/sync/${encodeURIComponent(syncRunId)}`,
        ),
      ),
      records = review.records || [],
      objectType = provider === "merit_palk" && review.summary.object_type === "gl_entry" ? "journal" : review.summary.object_type || "employee",
      employeeRun = ["employee", "employees", "salary_agreement"].includes(objectType),
      eligible = records.filter(stagedDecisionEligible),
      stagedBody = records.length
        ? table(
            ["Source record", "Status", employeeRun ? "Matched employee" : "Matched record", "Review note", "Decision"],
            records.map((record) => stagedRecordRow(record, objectType)),
          )
        : `<div class="empty integration-empty">${icon()}<h3>${tr("No records were staged")}</h3><p>${tr(employeeRun ? "The sync completed without new employee records." : "The sync completed without new records.")}</p></div>`,
      noDecisions =
        records.length && !eligible.length
          ? `<div class="notice" role="status">${tr("No records are awaiting a decision.")}</div>`
          : "";
    if (
      !c.mount(
        page(
          employeeRun ? t("Review employee import") : t("Review import: {type label}").replace("{type label}", importTypeLabel(objectType)),
          `${integrationName(item)} · ${t(employeeRun ? "Review staged records before payroll data changes." : "Review staged records before applying changes.")}`,
          link("Back to integrations", "#integrations") +
            link(
              "Recent runs",
              `#integrations/runs/${encodeURIComponent(provider)}`,
            ),
          `${integrationOutcomeSummary(outcome)}<div class="review-summary">${kpi("Records read", num(review.summary.read_count))}${kpi("Pending", num(review.summary.staged_counts?.Pending))}${kpi("Failed", num(review.summary.staged_counts?.Failed))}</div>${noDecisions}<section class="section"><div class="section-head"><h2>${tr(employeeRun ? "Staged employees" : "Staged records")}</h2>${button("Apply decisions", "applyImportDecisions", true, "disabled")}</div>${stagedBody}</section>`,
        ),
      )
    )
      return;
    const applyButton = content.querySelector(
      '[data-action="applyImportDecisions"]',
    );
    if (objectType === "journal") {
      applyButton.closest("section").insertAdjacentHTML("afterbegin",
        `<div class="form-grid"><label>${tr("Posting date for undated blocks")}<input type="date" name="journal_posting_date"></label></div>`);
    }
    content.querySelectorAll("[data-decision]").forEach((input) => {
      input.onchange = () => {
        if (input.checked)
          content
            .querySelectorAll(
              `[data-decision][data-id="${CSS.escape(input.dataset.id)}"]`,
            )
            .forEach((other) => {
              if (other !== input) other.checked = false;
            });
        applyButton.disabled = !content.querySelector(
          "[data-decision]:checked",
        );
      };
    });
    bindActions(content, {
      mapJournalAccount: async (button) => {
        const accounts = await api(c.url('/accounts'));
        const d = dialog("Map journal account", form(
          select("Local account", "local_account_code", accounts.filter((a) => a.active).map((a) => [a.code, `${a.code} ${a.name}`])), "Confirm mapping"));
        bindForm(d, async (data) => {
          await post(integrationUrl(c, provider, '/account-mappings'), {
            local_account_code: data.local_account_code, external_account_code: button.dataset.code, status: "Confirmed",
          });
          closeDialog(d);
          await integrationReview(c, item, provider, syncRunId);
        });
      },
      applyImportDecisions: async () => {
        const decisions = Object.fromEntries(
          [...content.querySelectorAll("[data-decision]:checked")].map(
            (input) => [input.dataset.id, input.dataset.decision],
          ),
        );
        if (!Object.keys(decisions).length) {
          toast(t("Choose approve or reject for at least one record."), "info");
          return;
        }
        applyButton.disabled = true;
        try {
          const applied = await post(
            integrationUrl(
              c,
              provider,
              `/sync/${encodeURIComponent(syncRunId)}/apply`,
            ),
            { decisions, ...(objectType === "journal" ? {posting_date: content.querySelector('[name=journal_posting_date]').value || null} : {}) },
          );
          toast(t("Import decisions applied"));
          await integrationReview(c, item, provider, syncRunId, applied);
        } finally {
          if (applyButton.isConnected) applyButton.disabled = false;
        }
      },
    });
  }

  async function integrationRuns(c, item, provider) {
    const runs = await api(integrationUrl(c, provider, "/syncs")),
      employeeOnly = ["fasthr", "personio", "bamboohr"].includes(provider);
    if (
      !c.mount(
        page(
          t(employeeOnly ? "Employee import runs" : "Import runs"),
          `${integrationName(item)} · ${t(employeeOnly ? "Open a run to review staged employee records." : "Open a run to review staged records.")}`,
          link("Back to integrations", "#integrations"),
          table(
            ["Started", "Object type", "Status", "Records read", "Staged", "Actions"],
            runs.map((run) =>
              row([
                td(date(run.started_at), "numeric"),
                td(esc(importTypeLabel(run.object_type || "employee"))),
                td(pill(run.status)),
                td(num(run.read_count), "numeric"),
                td(
                  num(
                    Object.values(run.staged_counts || {}).reduce(
                      (sum, value) => sum + Number(value || 0),
                      0,
                    ),
                  ),
                  "numeric",
                ),
                td(
                  button(
                    "Open review",
                    "openIntegrationReview",
                    false,
                    `data-id="${esc(run.id)}"`,
                  ),
                ),
              ]),
            ),
            link("Back to integrations", "#integrations"),
          ),
        ),
      )
    )
      return;
    bindActions(content, {
      openIntegrationReview: (button) => {
        location.hash = `integrations/review/${encodeURIComponent(provider)}/${encodeURIComponent(button.dataset.id)}`;
      },
    });
  }
  const canReviewPush = () => ["owner", "administrator", "accountant", "approver"].includes(org?.role),
    canExecutePush = () => ["owner", "administrator", "accountant"].includes(org?.role),
    canEditMappings = () => ["owner", "administrator"].includes(org?.role);

  function pushTable(pushes) {
    return table(["Provider", "Source document", "Status", "Actions"], pushes.map((push) => {
      const pending = ["Review Required", "Failed"].includes(push.status),
        payload = JSON.parse(push.payload_json || "{}");
      return row([
        td(esc(push.provider)),
        td(`<strong>${esc(payload.doc_no || push.local_ref)}</strong><details><summary>${tr("View prepared journal")}</summary><p>${esc(payload.posting_date)} · ${esc(payload.currency)}</p>${table(["Local account", "External account", ["Debit"], ["Credit"], "Memo"], (payload.lines || []).map((line) => row([td(esc(line.account_code)), td(esc(line.external_account_code)), cash(line.debit, "EUR"), cash(line.credit, "EUR"), td(esc(line.memo))])))}</details>`),
        td(`${pill(push.status)}${push.reviewed_at ? `<small>${pill("Reviewed")} ${esc(push.reviewed_by)} · ${date(push.reviewed_at)}</small>` : ""}${push.error_message ? `<small>${esc(translateError(push.error_message))}</small>` : ""}`),
        td(pending ? button("Review push", "reviewPush", false, `data-id="${esc(push.id)}" ${canReviewPush() ? "" : "disabled"}`) + button("Execute push", "executePush", true, `data-id="${esc(push.id)}" ${push.reviewed_at && canExecutePush() ? "" : "disabled"}`) : ""),
      ]);
    }));
  }

  function pushActions(c) {
    return {
      reviewPush: async (b) => {
        await post(c.url(`/pushes/${encodeURIComponent(b.dataset.id)}/review`));
        await render();
      },
      executePush: (b) => confirmAction("Execute push", tr("Send this reviewed journal to the accounting provider? Inspect provider records before retrying a failed send."), async () => {
        await post(c.url(`/pushes/${encodeURIComponent(b.dataset.id)}/execute`));
        await render();
      }),
    };
  }

  async function accountingIntegration(c, item, provider) {
    const [pushes, mappings] = await Promise.all([
      api(integrationUrl(c, provider, "/pushes")),
      canEditMappings() ? api(integrationUrl(c, provider, "/account-mappings")) : Promise.resolve([]),
    ]);
    if (!c.mount(page(integrationName(item), t("Journal pushes and mappings"), link("Back to integrations", "#integrations"),
      `<section class="section"><div class="section-head"><h2>${tr("Journal pushes")}</h2>${button("Prepare journal push", "prepareJournal", false, canReviewPush() ? "" : "disabled")}</div><p class="muted">${tr("Review the journal and confirmed account mappings before sending.")}</p>${pushTable(pushes)}</section><section class="section"><div class="section-head"><h2>${tr("Account mappings")}</h2><div>${button("Suggest mappings", "suggestMappings", false, canEditMappings() ? "" : "disabled")}${button("Add mapping", "addMapping", false, canEditMappings() ? "" : "disabled")}${button("GL reconciliation", "glReconciliation")}</div></div>${canEditMappings() ? table(["Local account", "External account", "Name", "Status", "Actions"], mappings.map((mapping) => row([td(esc(mapping.local_account_code)), td(esc(mapping.external_account_code)), td(esc(mapping.external_account_name)), td(pill(mapping.status)), td(button("Edit", "editMapping", false, `data-id="${esc(mapping.id)}"`) + button("Confirm mapping", "confirmMapping", false, `data-id="${esc(mapping.id)}" ${mapping.status === "Confirmed" ? "disabled" : ""}`))]))) : `<p>${tr("Account mappings are managed by organisation administrators.")}</p>`}<div id="mapping-suggestions" aria-live="polite"></div><div id="gl-reconciliation" aria-live="polite"></div></section>`))) return;
    const saveMapping = async (mapping, status = "Confirmed") => {
      if (mapping.id) await post(integrationUrl(c, provider, `/account-mappings/${encodeURIComponent(mapping.id)}`), {status, is_default: Boolean(mapping.is_default)}, "PUT");
      else await post(integrationUrl(c, provider, "/account-mappings"), {local_account_code: mapping.local_account_code, external_account_code: mapping.external_account_code, external_account_name: mapping.external_account_name || "", status, is_default: Boolean(mapping.is_default)});
      await render();
    };
    const mappingDialog = (mapping = {}) => {
      const d = dialog("Account mapping", form(field("Local account", "local_account_code", mapping.local_account_code || "", "text", "required") + field("External account", "external_account_code", mapping.external_account_code || "", "text", "required") + field("Name", "external_account_name", mapping.external_account_name || "") + select("Status", "status", ["Suggested", "Confirmed", "Disabled"].map((status) => [status, t(status)]), mapping.status || "Suggested"), "Save"));
      bindForm(d, async (data) => {
        await post(integrationUrl(c, provider, "/account-mappings"), {...data, is_default: Boolean(mapping.is_default)});
        closeDialog(d);
        await render();
      });
    };
    let suggestions = [];
    bindActions(content, {
      ...pushActions(c),
      prepareJournal: () => {
        const d = dialog("Prepare journal push", form(field("Batch ID or voucher reference", "batch", "", "text", "required"), "Prepare push"));
        bindForm(d, async (data) => {
          await post(integrationUrl(c, provider, `/push/journals/${encodeURIComponent(data.batch)}/prepare`), {});
          closeDialog(d);
          await render();
        });
      },
      addMapping: () => mappingDialog(),
      editMapping: (b) => mappingDialog(mappings.find((entry) => entry.id === b.dataset.id)),
      confirmMapping: (b) => saveMapping(mappings.find((entry) => entry.id === b.dataset.id)),
      suggestMappings: async () => {
        suggestions = await api(integrationUrl(c, provider, "/account-mappings/suggest"));
        const target = content.querySelector('#mapping-suggestions');
        target.innerHTML = `<h3>${tr("Suggested mappings")}</h3>${suggestions.length ? table(["Local account", "External account", "Name", "Actions"], suggestions.map((mapping, index) => row([td(esc(mapping.local_account_code)), td(esc(mapping.external_account_code)), td(esc(mapping.external_account_name)), td(button("Confirm mapping", "confirmSuggestion", false, `data-index="${index}"`))]))) : `<p>${tr("No account suggestions. Import accounts first or add a mapping.")}</p>`}`;
        bindActions(target, {confirmSuggestion: (b) => saveMapping(suggestions[Number(b.dataset.index)])});
      },
      glReconciliation: async () => {
        const result = await api(integrationUrl(c, provider, "/gl-reconciliation"));
        content.querySelector('#gl-reconciliation').innerHTML = `<h3>${tr("GL reconciliation")}</h3>${table(["Local account", "External account", ["Local total"], ["External total"], ["Difference"]], result.rows.map((entry) => row([td(esc(entry.local_account_code)), td(esc(entry.external_account_code)), cash(entry.local_total, "EUR"), cash(entry.external_total, "EUR"), cash(entry.delta, "EUR")])))}`;
      },
    });
  }

  const reportNames = {
    "trial-balance": "Trial balance",
    "profit-and-loss": "Profit & loss",
    "balance-sheet": "Balance sheet",
    "general-ledger": "General ledger",
    "receivables-aging": "Receivables aging",
    "payables-aging": "Payables aging",
    "cash-summary": "Cash summary",
    "cash-flow": "Cash-flow statement",
  };
  const cashFlowNames = {receipts: "Trade receivable receipts", supplier_payments: "Supplier payments",
    payroll: "Payroll", vat: "VAT settlements", revenue: "Revenue", expenses: "Expenses",
    financing: "Financing and capital", internal: "Internal transfers", other: "Other"};
  function renderReport(tab, data) {
    if (tab === "cash-flow") {
      const currency = data.base_currency;
      return `<p class="muted">${tr("Liquid accounts with the BANK role only. Internal transfers are excluded from totals.")}</p>` +
        table(["Description", ["Inflows"], ["Outflows"], ["Balance"]], [
          row([td(tr("Opening balance")), td(""), td(""), cash(data.opening_balance, currency)]),
          ...Object.entries(data.buckets).map(([key, x]) => row([td(tr(cashFlowNames[key])),
            cash(x.inflows, currency), cash(x.outflows, currency), cash(x.net, currency)])),
          row([td(tr("Total")), cash(data.inflows, currency), cash(data.outflows, currency), td("")], "total"),
          row([td(tr("Closing balance")), td(""), td(""), cash(data.closing_balance, currency)], "total")]) +
        `<h3>${tr("Liquid account detail")}</h3>` + data.accounts.map((a) =>
          `<section class="section"><h4>${esc(a.code)} ${esc(a.name)}</h4><p>${tr("Opening balance")}: ${esc(money(a.opening_balance, currency))} · ${tr("Closing balance")}: ${esc(money(a.closing_balance, currency))}</p>` +
          table(["Date", "Reference", "Memo", "Contact", "Classification", ["Amount"]], a.movements.map((x) =>
            row([td(date(x.date)), td(esc(x.document_number)), td(esc(x.memo)), td(esc(x.contact_id || "")),
              td(Object.entries(x.allocations).map(([key, value]) => `${tr(cashFlowNames[key])}: ${esc(money(value, currency))}`).join("<br>")),
              cash(x.amount, currency)]))) + `</section>`).join("");
    }
    if (data.comparative) {
      const keys = tab === "profit-and-loss" ? {income: "Income", expenses: "Expenses", profit: "Profit"}
        : {assets: "Assets", liabilities: "Liabilities", equity: "Equity", current_earnings: "Current earnings", liabilities_and_equity: "Liabilities and equity"};
      const period = (r) => r.as_at ? date(r.as_at) : `${date(r.start)} / ${date(r.end)}`;
      return `<p>${tr("Current period")}: ${esc(period(data))} · ${tr("Comparative period")}: ${esc(period(data.comparative))}</p>` +
        table(["Description", ["Current period"], ["Comparative period"]], Object.entries(keys).map(([key, label]) =>
          row([td(tr(label)), cash(data[key]), cash(data.comparative[key])]))) +
        table(["Code", "Account", ["Current period"], ["Comparative period"]], data.accounts.map((x) =>
          row([td(esc(x.code)), td(esc(x.name)), cash(x.balance), cash(x.comparative_balance)])));
    }
    if (tab === "general-ledger")
      return table(
        [
          "Date",
          "Code",
          "Account",
          "Reference",
          "Description",
          ["Debit"],
          ["Credit"],
        ],
        data.map((x) =>
          row([
            td(date(x.entry_date), "numeric"),
            td(esc(x.account_code)),
            td(esc(x.account_name)),
            td(esc(x.voucher_code)),
            td(esc(x.memo)),
            cash(x.debit, x.currency),
            cash(x.credit, x.currency),
          ]),
        ),
      );
    if (tab.endsWith("-aging"))
      return `<div class="kpis aging-kpis">${Object.entries(data.buckets)
        .map(([k, v]) =>
          kpi(
            {
              current: "Current",
              "1_30": "1–30 days",
              "31_60": "31–60 days",
              "61_90": "61–90 days",
              over_90: "Over 90 days",
            }[k],
            money(v),
          ),
        )
        .join("")}${kpi("Total", money(data.total))}</div>${table(
        ["Number", "Contact", "Due date", ["Days overdue"], ["Outstanding"]],
        data.items.map((x) =>
          row([
            td(esc(x.number)),
            td(esc(x.contact_name)),
            td(date(x.due_date), "numeric"),
            td(num(x.days_overdue), "numeric"),
            cash(x.outstanding, x.currency),
          ]),
        ),
      )}`;
    if (tab === "cash-summary")
      return `<div class="kpis">${kpi("Net cash movement", money(data.net_cash_movement))}</div>${table(
        ["Code", "Account", ["Movement"]],
        data.accounts.map((x) =>
          row([td(esc(x.code)), td(esc(x.name)), cash(x.movement)]),
        ),
      )}`;
    const accounts = Array.isArray(data) ? data : data.accounts,
      summary =
        tab === "profit-and-loss"
          ? [
              ["Income", data.income],
              ["Expenses", data.expenses],
              ["Profit", data.profit],
            ]
          : tab === "balance-sheet"
            ? [
                ["Assets", data.assets],
                ["Liabilities", data.liabilities],
                ["Equity", data.equity],
                ["Current earnings", data.current_earnings],
                ["Liabilities and equity", data.liabilities_and_equity],
              ]
            : [];
    const rows = [];
    let group = "";
    [...accounts]
      .sort(
        (a, b) =>
          String(a.account_type).localeCompare(b.account_type) ||
          String(a.code).localeCompare(b.code),
      )
      .forEach((x) => {
        if (x.account_type !== group) {
          group = x.account_type;
          rows.push(
            `<tr class="group-row"><th colspan="5">${tr(group)}</th></tr>`,
          );
        }
        rows.push(
          row([
            td(esc(x.code)),
            td(esc(x.name)),
            cash(x.debit),
            cash(x.credit),
            cash(x.balance),
          ]),
        );
      });
    return `<div class="kpis">${summary.map(([k, v]) => kpi(k, money(v))).join("")}</div>${table(["Code", "Account", ["Debit"], ["Credit"], ["Balance"]], rows)}`;
  }
  async function statementDialog(contact) {
    const base = path("");
    const today = new Date().toISOString().slice(0, 10);
    const d = dialog("Statement of account", `<p>${esc(contact.name)}</p>` + form(
      field("Statement start date", "date_from", today.slice(0, 4) + "-01-01", "date", "required") +
      field("Statement end date", "date_to", today, "date", "required") +
      select("Type", "side", [["customer", t("Customer")], ["supplier", t("Supplier")]],
        contact.contact_type === "supplier" ? "supplier" : "customer") +
      (org.base_currency === "EUR" ? "" : field("EUR per unit of base currency", "eur_rate", "", "number", 'required min="0.0000000001" step="any"')),
      "Download statement PDF"));
    bindForm(d, async (data) => {
      const query = new URLSearchParams(data).toString();
      // Validate through the same service before navigating to the PDF download.
      await api(`${base}/contacts/${contact.id}/statement?${query}`);
      if (base !== path("")) return;
      window.location.assign(`/api${base}/contacts/${contact.id}/statement.pdf?${query}`);
      closeDialog(d);
    });
  }
  async function contactDialog(type) {
    const url = path("/contacts");
    const d = dialog(
      "New contact",
      form(
        field("Name", "name", "", "text", "required") +
          select(
            "Type",
            "contact_type",
            [
              ["customer", t("customer")],
              ["supplier", t("supplier")],
              ["both", t("both")],
            ],
            type,
          ) +
          field(
            "Country",
            "country_code",
            org.country_code === "UK" ? "GB" : "EE",
            "text",
            'required maxlength="2"',
          ) +
          field("Email", "email", "", "email") +
          field("VAT number", "vat_no") +
          field("Registration number", "registration_no") +
          field("Address", "address") +
          field("Supplier IBAN", "iban") +
          field(
            "Payment terms (days)",
            "payment_terms_days",
            14,
            "number",
            'min="0" max="365"',
          ),
        "Save contact",
      ),
    );
    bindForm(d, async (data) => {
      await post(url, data);
      await saved(d);
    });
  }
  async function documentDialog(kind, documentId = null) {
    const base = path("");
    if (documentId) {
      const rows = kind === 'invoice' ? [await api(base + `/invoices/${documentId}`)] : await api(base + '/bills');
      if (base !== path("")) return;
      const record = rows.find((x) => x.id === documentId);
      if (!record) return;
      const d = dialog(kind === "invoice" ? "Invoice" : "Bill",
        `<p>${esc(record.number || record.supplier_number || t("Draft"))} · ${esc(record.contact_name)}</p>`);
      if (kind === 'invoice') {
        const history = document.createElement('section');
        history.innerHTML = `<h3>${tr('Email history')}</h3>` + ((record.deliveries || []).length
          ? table(['Date', 'Email', 'Status', 'Reason', 'PDF'], record.deliveries.map((item) => row([
              td(esc(item.created_at)), td(esc(item.recipient)), td(pill(item.status)),
              td(item.error_message ? esc(translateError(item.error_message)) : ''),
              td(item.attachment_id ? link('PDF', `/api${base}/attachments/${item.attachment_id}/download`) : ''),
            ]))) : `<p>${tr('No emails sent yet.')}</p>`);
        d.querySelector('.dialog-card').append(history);
        const section = document.createElement('section');
        const links = record.payment_links || [];
        section.innerHTML = `<h3>${tr('Payment links')}</h3>` + (links.length ? links.map((x, i) =>
          `<p><a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.name)}</a></p>` +
          field('Payment link', `payment_link_${i}`, x.url, 'text', 'readonly') +
          button('Copy link', 'copyPaymentLink', false, `data-index="${i}"`)).join('') :
          `<p>${tr('No payment links are available for this invoice.')}</p>${button('Copy link', 'copyPaymentLink', false, 'disabled')}`);
        d.querySelector('.dialog-card').append(section);
        bindActions(section, {copyPaymentLink: async (b) => {
          const input = section.querySelector(`[name=payment_link_${b.dataset.index}]`);
          input.focus(); input.select();
          try {
            await navigator.clipboard.writeText(input.value);
            toast(t('Link copied'));
          } catch (_) {
            toast(t('Select and copy the payment link.'), 'info');
          }
        }});
      }
      await attachmentsSection(d, base, kind, documentId);
      return;
    }
    const [contacts, accounts, taxes, objects] = await Promise.all([
      api(base + "/contacts"),
      api(base + "/accounts"),
      api(base + "/tax-codes"),
      api(base + '/objects'),
    ]);
    if (base !== path("")) return;
    const invoice = kind === "invoice",
      choices = contacts.filter(
        (x) => x.contact_type !== (invoice ? "supplier" : "customer"),
      );
    if (!choices.length) {
      toast(t("Add a contact before creating a document."), "info");
      return contactDialog(invoice ? "customer" : "supplier");
    }
    const lineFields = (index) => {
      const suffix = index ? `_${index}` : '';
      const fields = field("Description", "description", "", "text", "required") +
        field("Quantity", "quantity", 1, "number", 'required min="0.0001" step="0.0001"') +
        field("Unit price", "unit_price", "", "number", 'required min="0" step="0.01"') +
        select(invoice ? "Income account" : "Expense account", "account_id",
          accounts.filter((x) => x.account_type === (invoice ? "Income" : "Expense"))
            .map((x) => [x.id, `${x.code} ${x.name}`])) +
        select("Tax code", "tax_code_id", taxes.map((x) => [x.id, `${x.code} · ${num(x.rate)}%`]),
          taxes.find((x) => x.kind === "standard")?.id) + objectSelectors(objects);
      return `<fieldset class="document-line full-width" data-line-index="${index}"><legend>${esc(t('Line {number}').replace('{number}', num(index + 1)))}</legend><div class="form-grid">${fields.replace(/(name|data-error)="([^"]+)"/g, (_, attr, name) => `${attr}="${name}${suffix}"`)}${index ? button('Remove line', 'removeLine', false, `aria-label="${esc(t('Remove line {number}').replace('{number}', num(index + 1)))}"`) : ''}</div></fieldset>`;
    };
    const dueDate = (value) => {
      if (!value) return '';
      const day = new Date(`${value}T12:00:00Z`);
      day.setUTCDate(day.getUTCDate() + 14);
      return day.toISOString().slice(0, 10);
    };
    const d = dialog(
      invoice ? "New invoice" : "New bill",
      form(
        select(invoice ? "Customer" : "Supplier", "contact_id", choices.map((x) => [x.id, x.name])) +
          (invoice ? field("Issue date", "issue_date", today(), "date", "required") :
            field("Supplier number", "supplier_number", "", "text", "required") +
            field("Bill date", "bill_date", today(), "date", "required")) +
          field("Due date", "due_date", dueDate(today()), "date", "required") +
          `<div class="document-lines full-width">${lineFields(0)}</div>` +
          button('Add line', 'addLine') + `<p class="full-width" data-net-total role="status"></p>`,
        "Create draft",
      ),
    );
    const issue = d.querySelector(invoice ? '[name=issue_date]' : '[name=bill_date]');
    const due = d.querySelector('[name=due_date]');
    let dueEdited = false, nextLine = 1;
    due.addEventListener('input', () => { dueEdited = true; });
    due.addEventListener('change', () => { dueEdited = true; });
    const followIssue = () => { if (!dueEdited) due.value = dueDate(issue.value); };
    issue.addEventListener('input', followIssue);
    issue.addEventListener('change', followIssue);
    // Keep the display estimate in scaled integers. The API remains authoritative.
    const updateTotal = () => {
      const scaled = (value, places) => {
        const parts = (value || '0').match(/^(\d*)(?:\.(\d*))?(?:e([+-]?\d+))?$/i);
        if (!parts) return 0n;
        const fraction = parts[2] || '', digits = BigInt((parts[1] + fraction) || '0');
        const shift = places + Number(parts[3] || 0) - fraction.length;
        if (Math.abs(shift) > 100) return 0n;
        return shift >= 0 ? digits * 10n ** BigInt(shift) : digits / 10n ** BigInt(-shift);
      };
      const total = [...d.querySelectorAll('[data-line-index]')].reduce((sum, group) =>
        sum + (scaled(group.querySelector('[name^=quantity]').value, 4) *
          scaled(group.querySelector('[name^=unit_price]').value, 2) + 5000n) / 10000n, 0n);
      const amount = `${total / 100n}.${String(total % 100n).padStart(2, '0')}`;
      d.querySelector('[data-net-total]').textContent = `${t('Net total')}: ${money(amount, org.base_currency)}`;
    };
    d.querySelector('.document-lines').addEventListener('input', updateTotal);
    d.querySelector('[data-action=addLine]').onclick = () => {
      const lines = d.querySelector('.document-lines');
      lines.insertAdjacentHTML('beforeend', lineFields(nextLine++));
      const group = lines.lastElementChild;
      group.querySelector('[data-action=removeLine]').onclick = () => { group.remove(); updateTotal(); };
      group.querySelector('input').focus();
      updateTotal();
    };
    updateTotal();
    bindForm(d, async (data) => {
      const keys = ['description', 'quantity', 'unit_price', 'account_id', 'tax_code_id',
        'projects_project_id', 'projects_location_id', 'projects_person_id', 'projects_object_id'];
      data.lines = [...d.querySelectorAll('[data-line-index]')].map((group) => {
        const line = {}, suffix = group.dataset.lineIndex === '0' ? '' : `_${group.dataset.lineIndex}`;
        keys.forEach((key) => {
          line[key] = key.startsWith('projects_') ? data[key + suffix] || null : data[key + suffix];
          delete data[key + suffix];
        });
        return line;
      });
      d.dataset.pending = "true";
      let record;
      try {
        record = await post(base + (invoice ? "/invoices" : "/bills"), data);
      } finally {
        d.dataset.pending = "false";
      }
      if (d._originOrg !== org?.id || d._originView !== location.hash) return closeDialog(d);
      d.querySelector("form").remove();
      await attachmentsSection(d, base, kind, record.id);
      toast(t("Saved successfully"));
      await render();
    });
  }

  const objectTypeLabel = (kind) => ({project: 'Project', location: 'Location', person: 'Person', object: 'Object'})[kind];
  const objectSelectors = (objects) => ['project', 'location', 'person', 'object'].map((kind) =>
    select(objectTypeLabel(kind), `projects_${kind}_id`, [['', t('No object')],
      ...objects.filter((x) => x.active && x.object_type === kind).map((x) => [x.id, `${x.code} ${x.name}`])])).join('');

  async function objectDialog(record = null) {
    const base = path('');
    const d = dialog(record ? 'Edit object' : 'Add object', form(
      select('Object type', 'object_type', ['project', 'location', 'person', 'object'].map((kind) => [kind, t(objectTypeLabel(kind))]), record?.object_type || 'project') +
      field('Code', 'code', record?.code || '', 'text', 'required maxlength="40"') +
      field('Name', 'name', record?.name || '', 'text', 'required maxlength="180"') +
      field('Notes', 'notes', record?.notes || '', 'text', 'maxlength="2000"') + check('Active', 'active', record ? !!record.active : true)));
    bindForm(d, async (data) => {
      await post(base + '/objects' + (record ? `/${record.id}` : ''),
        {...data, active: d.querySelector('[name=active]').checked}, record ? 'PATCH' : 'POST');
      await saved(d);
    });
  }

  async function paymentMethodDialog(record = null) {
    const base = path('');
    const d = dialog(record ? 'Edit payment method' : 'Add payment method', form(
      `<p class="full-width">${tr('Use an HTTPS URL. Placeholders: {invoice_total}, {invoice_due}, {invoice_number}, {invoice_id}, {token}, {currency}.')}</p>` +
      select('Provider', 'provider', [['everypay', 'EveryPay'], ['linkpay', 'LinkPay'], ['custom', t('Custom')]], record?.provider || 'custom') +
      field('Name', 'name', record?.name || '', 'text', 'required maxlength="120"') +
      field('URL template', 'url_template', record?.url_template || '', 'text', 'required maxlength="2000"') +
      field('Currency (blank for any)', 'currency', record?.currency || '', 'text', 'maxlength="3"') +
      check('Enabled', 'enabled', record?.enabled || false)));
    bindForm(d, async (data) => {
      await post(base + '/payment-methods' + (record ? `/${record.id}` : ''),
        {...data, enabled: d.querySelector('[name=enabled]').checked}, record ? 'PATCH' : 'POST');
      await saved(d);
    });
  }
  async function purchaseScheduleDialog(scheduleId = null) {
    const base = path('');
    if (scheduleId) {
      const record = await api(base + `/purchase-schedules/${scheduleId}`);
      if (base !== path('')) return;
      dialog('Purchase periods', `<p>${esc(record.supplier_number)} · ${esc(record.contact_name)} · ${pill(record.status)}</p>` +
        `<p>${tr('VAT stays on the original bill. Portions transfer net expense only.')}</p>` +
        table(['Period date', ['Net amount'], 'Status'], record.periods.map((x) => row([
          td(date(x.period_date)), td(esc(money(x.net_amount, record.currency)), 'numeric'), td(pill(x.status))]))) +
        `<p>${tr('Deferred cost awaiting review')}: ${esc(money(record.funding_batch_id ? record.cancelled_amount : '0.00', record.currency))}</p>`);
      return;
    }
    const [bills, accounts, schedules] = await Promise.all([api(base + '/bills'), api(base + '/accounts'), api(base + '/purchase-schedules')]);
    if (base !== path('')) return;
    const available = bills.filter((b) => b.document_type === 'bill' && !schedules.some((s) => s.bill_id === b.id));
    if (!available.length) return toast(t('Create a purchase bill before adding a schedule.'), 'info');
    const d = dialog('New purchase schedule', form(
      `<p class="full-width">${tr('VAT stays on the original bill. Portions transfer net expense only.')}</p>` +
      select('Bill', 'bill_id', available.map((b) => [b.id, `${b.supplier_number} · ${b.contact_name}`])) +
      select('Expense account', 'expense_account_id', accounts.filter((a) => a.active && a.account_type === 'Expense').map((a) => [a.id, `${a.code} ${a.name}`])) +
      field('Start period', 'start_period', today(), 'date', 'required') +
      field('Number of periods', 'number_of_periods', 12, 'number', 'required min="1" max="120" step="1"') +
      select('Cent remainder', 'split_rule', [['equal_first', t('First period')], ['equal_last', t('Last period')]]) +
      field('Notes', 'notes', ''), 'Create schedule'));
    ['bill_id', 'expense_account_id'].forEach((key) => { d.querySelector(`[name=${key}]`).required = true; });
    bindForm(d, async (data) => {
      await post(base + '/purchase-schedules', {...data, number_of_periods: Number(data.number_of_periods)});
      await saved(d);
    });
  }
  async function quoteDialog(quoteId = null, readOnly = false) {
    const base = path("");
    const [contacts, accounts, taxes, record] = await Promise.all([
      api(base + "/contacts"), api(base + "/accounts"), api(base + "/tax-codes"),
      quoteId ? api(base + `/quotes/${quoteId}`) : Promise.resolve(null),
    ]);
    if (base !== path("")) return;
    if (readOnly || (record && record.status !== "Draft")) {
      dialog("Quote", `<p>${esc(record.quote_number)} · ${esc(record.contact_name)} · ${pill(record.status)}</p>` +
        `<p>${tr("Quote date")}: ${esc(date(record.quote_date))} · ${tr("Valid until")}: ${esc(date(record.valid_until))}</p>` +
        `<h3>${tr("Quote lines")}</h3>` + table(["Description", "Quantity", "Unit price", ["Total"]], record.lines.map((x) =>
          row([td(esc(x.description)), td(esc(num(x.quantity))), td(esc(money(x.unit_price, record.currency))), td(esc(money(x.gross_amount, record.currency)))]))) +
        `<p>${tr("Total")}: ${esc(money(record.total, record.currency))}</p><p>${esc(record.notes)}</p>`);
      return;
    }
    const customers = contacts.filter((x) => ["customer", "both"].includes(x.contact_type));
    if (!customers.length) {
      toast(t("Add a contact before creating a document."), "info");
      return contactDialog("customer");
    }
    const d = dialog(record ? "Edit quote" : "New quote", form(
      select("Customer", "contact_id", customers.map((x) => [x.id, x.name]), record?.contact_id) +
      field("Quote date", "quote_date", record?.quote_date || today(), "date", "required") +
      field("Valid until", "valid_until", record?.valid_until || today(), "date", "required") +
      select("Amount type", "amount_type", [["exclusive", t("Exclusive")], ["inclusive", t("Inclusive")], ["no_tax", t("No tax")]], record?.line_amount_type || "exclusive") +
      field("Notes", "notes", record?.notes || "") +
      `<div class="full-width"><h3>${tr("Quote lines")}</h3><div data-quote-lines></div>${button("Add line", "addQuoteLine")}</div>`,
      record ? "Save" : "Create draft"));
    let nextLine = 0;
    const addLine = (line = {}) => {
      const index = nextLine++;
      const fields = document.createElement("fieldset");
      fields.className = "form-grid";
      fields.dataset.quoteLine = index;
      fields.innerHTML = `<legend>${tr("Quote line")}</legend>` +
        field("Description", `description_${index}`, line.description || "", "text", "required") +
        field("Quantity", `quantity_${index}`, line.quantity ?? 1, "number", 'required min="0.0001" step="0.0001"') +
        field("Unit price", `unit_price_${index}`, line.unit_price ?? "", "number", 'required min="0" step="0.0001"') +
        select("Income account", `account_id_${index}`, accounts.filter((x) => x.active && x.account_type === "Income").map((x) => [x.id, `${x.code} ${x.name}`]), line.account_id) +
        select("Tax code", `tax_code_id_${index}`, [["", t("No tax")], ...taxes.filter((x) => x.active).map((x) => [x.id, `${x.code} · ${num(x.rate)}%`])], line.tax_code_id || "") +
        button("Remove line", "removeQuoteLine");
      d.querySelector("[data-quote-lines]").append(fields);
      fields.querySelector(`[name=account_id_${index}]`).required = true;
      fields.querySelector("[data-action=removeQuoteLine]").onclick = () => {
        if (d.querySelectorAll("[data-quote-line]").length > 1) fields.remove();
      };
    };
    (record?.lines || [{}]).forEach(addLine);
    d.querySelector("[data-action=addQuoteLine]").onclick = () => addLine();
    d.querySelector('[name=contact_id]').required = true;
    bindForm(d, async (data) => {
      const lines = [...d.querySelectorAll("[data-quote-line]")].map((fields) => {
        const line = {}, index = fields.dataset.quoteLine;
        ["description", "quantity", "unit_price", "account_id", "tax_code_id"].forEach((key) => {
          line[key] = data[`${key}_${index}`];
          delete data[`${key}_${index}`];
        });
        line.tax_code_id ||= null;
        return line;
      });
      await post(base + (quoteId ? `/quotes/${quoteId}` : "/quotes"), { ...data, lines }, quoteId ? "PATCH" : "POST");
      await saved(d);
    });
  }
  function eInvoiceImportDialog() {
    const base = path("");
    const d = dialog(
      "Import e-invoice",
      form(
        `<p class="muted full-width">${tr("Choose an Estonian e-arve XML file. The bill is saved as a draft for review, with the source file attached.")}</p>` +
          field("E-invoice XML file", "file", "", "file", 'required accept=".xml,application/xml,text/xml"'),
        "Import draft bill",
      ),
    );
    bindForm(d, async (_, formElement) => {
      const file = formElement.elements.file.files[0];
      if (!(await file.text()).trim())
        throw new Error(t("Choose a non-empty e-invoice XML file."));
      const payload = new FormData();
      payload.append("file", file);
      const result = await api(`${base}/e-invoices/import`, { method: "POST", body: payload });
      closeDialog(d);
      toast(t("E-invoice imported as a draft bill."));
      if (base !== path("")) return;
      await render();
      await documentDialog("bill", result.bill_id);
    });
  }
  function bankDialog() {
    const url = path("/bank-accounts");
    const d = dialog(
      "Add bank account",
      form(
        field("Name", "name", "", "text", "required") +
          field(
            "Currency",
            "currency",
            org.base_currency,
            "text",
            'required pattern="[A-Z]{3}"',
          ) +
          field("IBAN", "iban"),
          field("BIC", "bic"),
        "Add account",
      ),
    );
    bindForm(d, async (data) => {
      await post(url, data);
      await saved(d);
    });
  }
  async function attachmentsSection(d, base, kind, documentId) {
    d.classList.add("document-evidence-dialog");
    const section = document.createElement("section");
    section.className = "section";
    section.innerHTML = `<h3>${tr("Attachments")}</h3><div data-attachments></div><form novalidate>${field("File", "file", "", "file", "required")}<p class="form-error" role="alert"></p><div class="dialog-actions"><button class="button primary" type="submit">${tr("Upload attachment")}</button></div></form>`;
    d.querySelector(".dialog-card").append(section);
    const refresh = async () => {
      const rows = await api(`${base}/attachments?owner_type=${kind}&owner_id=${encodeURIComponent(documentId)}`);
      if (!d.isConnected || base !== path("")) return;
      section.querySelector("[data-attachments]").innerHTML = rows.length
        ? rows.map((item) => `<p>${esc(item.filename)} ${link("Download", `/api${base}/attachments/${item.id}/download`)}</p>`).join("")
        : `<p class="muted">${tr("No attachments yet.")}</p>`;
    };
    bindForm(section, async (_, f) => {
      const payload = new FormData();
      payload.append("file", f.elements.file.files[0]);
      await api(`${base}/attachments/${kind}/${documentId}`, { method: "POST", body: payload });
      f.reset();
      await refresh();
    });
    await refresh();
  }

  async function openingBalancesDialog() {
    const base = path("/opening-balance"), currency = org.base_currency;
    let snapshot = await api(`${base}?opening_date=${today()}`), request = 0;
    if (base !== path("/opening-balance")) return;
    const d = dialog("Opening balances", form(
      field("Posting date", "posting_date", today(), "date", "required") +
      `<p class="muted full-width">${tr("Enter balance sheet accounts only. Any difference posts to retained earnings.")}</p>` +
      `<p class="muted full-width">${tr("Importing open items adds to receivables and payables. Exclude those amounts from this opening journal to avoid counting them twice.")}</p>` +
      `<p class="full-width" data-opening-status></p><div class="full-width" data-opening-accounts></div>` +
      `<div class="full-width" data-opening-totals role="status" aria-live="polite"></div>`, "Post opening balances"));
    d.classList.add("opening-balance-dialog");
    const f = d.querySelector("form"), submit = f.querySelector("[type=submit]");
    d.querySelector("[data-opening-accounts]").innerHTML = table(
      ["Account", ["Current balance"], ["Debit"], ["Credit"]],
      snapshot.accounts.map((a) => row([
        td(`${esc(a.code)} ${esc(a.name)}`),
        td(`<span data-balance="${esc(a.id)}">${esc(money(a.balance, currency))}</span>`, "numeric"),
        td(field("Debit", `debit_${a.id}`, "", "number", `min="0" step="0.01" ${a.active ? "" : "disabled"} aria-label="${tr("Debit")} ${esc(a.code)} ${esc(a.name)}"`)),
        td(field("Credit", `credit_${a.id}`, "", "number", `min="0" step="0.01" ${a.active ? "" : "disabled"} aria-label="${tr("Credit")} ${esc(a.code)} ${esc(a.name)}"`)),
      ])));
    // Integer cents keep the running preview exact; the server validates and posts.
    const cents = (value) => {
      if (!value) return 0n;
      if (!/^\d+(\.\d{1,2})?$/.test(value)) throw new Error(t("Enter a valid value."));
      const [whole, fraction = ""] = value.split(".");
      return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
    };
    const fixed = (value) => `${value < 0n ? "-" : ""}${(value < 0n ? -value : value) / 100n}.${String((value < 0n ? -value : value) % 100n).padStart(2, "0")}`;
    const totals = () => {
      try {
        let debit = 0n, credit = 0n;
        for (const a of snapshot.accounts) {
          debit += cents(f.elements[`debit_${a.id}`].value);
          credit += cents(f.elements[`credit_${a.id}`].value);
        }
        const remainder = debit - credit;
        d.querySelector("[data-opening-totals]").textContent =
          `${t("Debit")}: ${fixed(debit)} ${currency} · ${t("Credit")}: ${fixed(credit)} ${currency} · ` +
          `${t("Retained earnings offset")}: ${t(remainder < 0n ? "Debit" : "Credit")} ${fixed(remainder < 0n ? -remainder : remainder)} ${currency}`;
      } catch (error) { d.querySelector("[data-opening-totals]").textContent = error.message; }
    };
    const drawSnapshot = () => {
      d.querySelector("[data-opening-status]").textContent = snapshot.opening_batch
        ? t("Opening balances already posted; add a correcting journal instead") : "";
      for (const a of snapshot.accounts) {
        d.querySelector(`[data-balance="${a.id}"]`).textContent = money(a.balance, currency);
        f.elements[`debit_${a.id}`].disabled = !!snapshot.opening_batch || !a.active;
        f.elements[`credit_${a.id}`].disabled = !!snapshot.opening_batch || !a.active;
      }
      submit.disabled = !!snapshot.opening_batch;
      totals();
    };
    f.oninput = totals;
    f.elements.posting_date.onchange = async () => {
      const current = ++request;
      submit.disabled = true;
      try {
        const result = await api(`${base}?opening_date=${encodeURIComponent(f.elements.posting_date.value)}`);
        if (current !== request || !d.isConnected || base !== path("/opening-balance")) return;
        snapshot = result;
        f.querySelector(".form-error").textContent = "";
        drawSnapshot();
      } catch (error) { if (current === request) f.querySelector(".form-error").textContent = error.message; }
    };
    drawSnapshot();
    bindForm(d, async (data) => {
      const lines = snapshot.accounts.filter((a) => a.active).map((a) => ({
        account_id: a.id, debit: data[`debit_${a.id}`] || "0", credit: data[`credit_${a.id}`] || "0",
      }));
      await post(base, { posting_date: data.posting_date, lines });
      await saved(d);
    });
  }

  function openingItemsDialog() {
    const base = path("/opening-balance/open-items"), currency = org.base_currency;
    const d = dialog("Opening receivables/payables", form(
      field("Posting date", "posting_date", today(), "date", "required") +
      field("CSV file", "opening_file", "", "file", 'required accept=".csv,text/csv"') +
      `<p class="muted full-width">${tr("CSV columns: type,name,original_number,original_date,due_date,amount. Use customer or supplier, ISO dates and positive amounts in the organisation currency.")}</p>` +
      `<p class="muted full-width">${tr("Importing open items adds to receivables and payables. Exclude those amounts from this opening journal to avoid counting them twice.")}</p>` +
      `<p class="muted full-width">${tr("This posts ledger entries only, with retained earnings offsets. No invoices or bills are created.")}</p>` +
      `<div class="full-width">${button("Preview opening items", "previewOpeningItems")}</div>` +
      `<div class="full-width" data-opening-items-preview aria-live="polite"></div>`, "Post opening items"));
    d.classList.add("opening-balance-dialog");
    const f = d.querySelector("form"), submit = f.querySelector("[type=submit]");
    let reviewedContent = null, previewRequest = 0;
    submit.disabled = true;
    f.elements.opening_file.onchange = () => {
      previewRequest++;
      reviewedContent = null;
      submit.disabled = true;
      d.querySelector("[data-opening-items-preview]").innerHTML = "";
    };
    bindActions(d, { previewOpeningItems: async (b) => {
      const current = ++previewRequest;
      reviewedContent = null;
      submit.disabled = true;
      b.disabled = true;
      try {
        const file = f.elements.opening_file.files[0];
        if (!file) throw new Error(t("Choose a CSV file to preview."));
        const csvContent = await file.text();
        const preview = await post(base + "/preview", { csv_content: csvContent });
        if (current !== previewRequest || !d.isConnected || base !== path("/opening-balance/open-items")) return;
        d.querySelector("[data-opening-items-preview]").innerHTML =
          `<p>${tr("Customer total")}: ${esc(money(preview.totals.customer, currency))} · ${tr("Supplier total")}: ${esc(money(preview.totals.supplier, currency))}</p>` +
          table(["Type", "Name", "Original number", "Original date", "Due date", ["Amount"]], preview.rows.map((item) => row([
            td(tr(item.type === "customer" ? "Customer" : "Supplier")), td(esc(item.name)), td(esc(item.original_number)),
            td(esc(item.original_date)), td(esc(item.due_date)), cash(item.amount, currency),
          ])));
        reviewedContent = csvContent;
        f.querySelector(".form-error").textContent = "";
        submit.disabled = false;
      } catch (error) {
        if (current === previewRequest) {
          d.querySelector("[data-opening-items-preview]").innerHTML = "";
          f.querySelector(".form-error").textContent = error.message;
        }
      } finally { b.disabled = false; }
    }});
    bindForm(d, async (data) => {
      if (reviewedContent === null) throw new Error(t("Choose a CSV file to preview."));
      if (await f.elements.opening_file.files[0].text() !== reviewedContent)
        throw new Error(t("The file changed. Preview it again before posting."));
      await post(base, { posting_date: data.posting_date, csv_content: reviewedContent });
      await saved(d);
    });
  }

  const assetFrequencyLabel = (value) => ({monthly: "Monthly", quarterly: "Quarterly", yearly: "Yearly"}[value] || value || "");
  const assetFrequencyOptions = () => ["monthly", "quarterly", "yearly"].map((v) => [v, t(assetFrequencyLabel(v))]);

  async function fixedAssetBanks(base) {
    const banks = (await api(base + "/bank-accounts")).filter((x) => x.currency === org.base_currency);
    if (!banks.length) toast(t("Add a bank account in the organisation base currency first."), "info");
    return banks;
  }

  async function fixedAssetAcquisitionDialog(groups) {
    const base = path(""), oid = org.id, key = prepaymentKey();
    const banks = await fixedAssetBanks(base);
    if (oid !== org.id || !banks.length) return;
    const d = dialog("Record asset acquisition", form(
      field("Asset name", "name", "", "text", 'required maxlength="240"') +
      select("Asset group", "group_id", groups.map((x) => [x.id, x.name])) +
      field("Acquisition date", "acquisition_date", today(), "date", "required") +
      field("Acquisition cost", "acquisition_cost", "", "number", 'required min="0.01" step="0.01"') +
      select("Bank account", "bank_account_id", banks.map((x) => [x.id, x.name])) +
      `<p class="full-width muted">${tr("The acquisition is paid from the selected bank account and posted immediately.")}</p>`, "Record asset acquisition"));
    bindForm(d, async (data) => {
      await post(base + "/fixed-assets", {...data, idempotency_key: key});
      await saved(d);
    });
  }

  function assetGroupDialog() {
    const base = path(""), d = dialog("Add asset group", form(
      field("Asset group", "name", "", "text", 'required maxlength="240"') +
      field("Annual depreciation percentage", "annual_percentage", "20", "number", 'required min="0.01" max="100" step="0.01"') +
      select("Frequency", "frequency", assetFrequencyOptions(), "monthly"), "Add asset group"));
    bindForm(d, async (data) => { await post(base + "/asset-groups", data); await saved(d); });
  }

  function depreciationRunDialog() {
    const previousEnd = new Date(Number(today().slice(0, 4)), Number(today().slice(5, 7)) - 1, 0);
    const periodDate = `${previousEnd.getFullYear()}-${String(previousEnd.getMonth() + 1).padStart(2, "0")}-${String(previousEnd.getDate()).padStart(2, "0")}`;
    const base = path(""), d = dialog("Run depreciation", form(
      field("Period date", "period_date", periodDate, "date", "required") +
      select("Frequency", "kind", assetFrequencyOptions(), "monthly") +
      `<p class="full-width muted">${tr("Use the last day of the month, quarter or year.")}</p>` +
      `<p class="full-width muted">${tr("Each period is calculated once. Running it again returns the existing calculation.")}</p>`, "Run depreciation"));
    d.querySelector('[name="kind"]').onchange = (event) => {
      const year = Number(today().slice(0, 4)), month = Number(today().slice(5, 7)) - 1;
      const boundaryMonth = event.target.value === "yearly" ? 0 : event.target.value === "quarterly" ? Math.floor(month / 3) * 3 : month;
      const end = new Date(year, boundaryMonth, 0);
      d.querySelector('[name="period_date"]').value = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, "0")}-${String(end.getDate()).padStart(2, "0")}`;
    };
    bindForm(d, async (data) => { await post(base + "/fixed-assets/runs", data); await saved(d); });
  }

  async function assetDisposalDialog(asset) {
    if (!asset) return;
    const base = path(""), oid = org.id, banks = await fixedAssetBanks(base);
    if (oid !== org.id || !banks.length) return;
    const d = dialog("Dispose asset", form(
      `<p class="full-width">${esc(asset.name)} · ${tr("Carrying value")}: ${esc(money(asset.carrying_value))}</p>` +
      field("Disposal date", "disposal_date", today(), "date", `required min="${esc(asset.acquisition_date)}"`) +
      field("Disposal proceeds", "disposal_amount", "0", "number", 'required min="0" step="0.01"') +
      select("Bank account", "bank_account_id", banks.map((x) => [x.id, x.name])) +
      `<p class="full-width muted">${tr("Disposal removes the asset cost and accumulated depreciation and posts any gain or loss.")}</p>`, "Dispose asset"));
    bindForm(d, async (data) => {
      await post(base + `/fixed-assets/${encodeURIComponent(asset.id)}/dispose`, data);
      await saved(d);
    });
  }

  const prepaymentKey = () => Array.from(crypto.getRandomValues(new Uint32Array(4)), (x) => x.toString(16)).join("-");

  function prepaymentSection(rows, side) {
    return `<section class="section"><h2>${tr(side === "customer" ? "Customer prepayments" : "Supplier prepayments")}</h2>${table(
      [side === "customer" ? "Customer" : "Supplier", "Date", "Reference", ["Amount"], ["Unallocated balance"], "Actions"],
      rows.map((x) => row([
        td(esc(x.contact_name)), td(date(x.document_date), "numeric"), td(esc(x.reference)),
        cash(x.amount, x.currency), cash(x.unallocated_balance, x.currency),
        td(Number(x.unallocated_balance) > 0 ?
          button("Allocate prepayment", "allocatePrepayment", false, `data-id="${esc(x.id)}" ${canExecutePush() ? "" : "disabled"}`) +
          button("Refund prepayment", "refundPrepayment", false, `data-id="${esc(x.id)}" ${canExecutePush() ? "" : "disabled"}`) : ""),
      ])),
    )}</section>`;
  }

  function prepaymentActions(rows, side) {
    return {
      newPrepayment: () => prepaymentDialog(side),
      allocatePrepayment: (b) => allocatePrepaymentDialog(rows.find((x) => x.id === b.dataset.id)),
      refundPrepayment: (b) => refundPrepaymentDialog(rows.find((x) => x.id === b.dataset.id)),
    };
  }

  async function contactPrepaymentsDialog(contact) {
    const base = path(`/contacts/${encodeURIComponent(contact.id)}/prepayments/outstanding`), oid = org.id;
    const result = await api(base);
    if (oid !== org.id) return;
    const d = dialog("Outstanding prepayments", `<p>${esc(contact.name)}</p>` +
      ["customer", "supplier"].map((side) => prepaymentSection(result.items.filter((x) => x.side === side), side)).join(""));
    bindActions(d, {
      allocatePrepayment: (b) => {
        closeDialog(d);
        return allocatePrepaymentDialog(result.items.find((x) => x.id === b.dataset.id));
      },
      refundPrepayment: (b) => {
        closeDialog(d);
        return refundPrepaymentDialog(result.items.find((x) => x.id === b.dataset.id));
      },
    });
  }

  async function prepaymentDialog(side) {
    const base = path(""), oid = org.id, currency = org.base_currency;
    const [contacts, banks] = await Promise.all([api(base + "/contacts"), api(base + "/bank-accounts")]);
    if (oid !== org.id) return;
    const eligible = contacts.filter((x) => [side, "both"].includes(x.contact_type));
    const bankAccounts = banks.filter((x) => x.currency === currency);
    if (!eligible.length) return toast(t("Add a contact before recording a prepayment."), "info");
    if (!bankAccounts.length) return toast(t("Add a bank account in the organisation base currency first."), "info");
    const key = prepaymentKey();
    const d = dialog(side === "customer" ? "Record customer prepayment" : "Record supplier prepayment", form(
      select(side === "customer" ? "Customer" : "Supplier", "contact_id", eligible.map((x) => [x.id, x.name])) +
      select("Bank account", "bank_account_id", bankAccounts.map((x) => [x.id, x.name])) +
      field("Date", "document_date", today(), "date", "required") +
      field("Amount", "amount", "", "number", 'required min="0.01" step="0.01"') +
      field("Reference", "reference", "", "text", 'maxlength="240"') +
      `<p class="full-width muted">${tr("The bank movement is posted now. Allocate this prepayment when the invoice or bill is ready.")}</p>`,
      "Record prepayment"));
    bindForm(d, async (data) => {
      await post(base + "/prepayments", {...data, side, currency, idempotency_key: key});
      await saved(d);
    });
  }

  async function allocatePrepaymentDialog(prepayment) {
    const base = path(""), oid = org.id, customer = prepayment.side === "customer";
    const documents = await api(base + (customer ? "/invoices" : "/bills"));
    if (oid !== org.id) return;
    const candidates = documents.filter((x) => x.contact_id === prepayment.contact_id &&
      x.currency === prepayment.currency && x.document_type === (customer ? "invoice" : "bill") &&
      (customer ? ["Issued", "Part Paid"] : ["Approved", "Part Paid"]).includes(x.status));
    if (!candidates.length) return toast(t("No open documents for this prepayment contact and currency."), "info");
    const key = prepaymentKey();
    const d = dialog("Allocate prepayment", form(
      `<p class="full-width">${esc(prepayment.contact_name)} · ${tr("Unallocated balance")}: ${esc(money(prepayment.unallocated_balance, prepayment.currency))}</p>` +
      select(customer ? "Invoice" : "Bill", "document_id", candidates.map((x) =>
        [x.id, `${x.number || x.supplier_number} · ${money(Number(x.total) - Number(x.paid_total), x.currency)}`])) +
      field("Allocation date", "allocation_date", today(), "date", `required min="${esc(prepayment.document_date)}"`) +
      field("Amount", "amount", "", "number", `required min="0.01" step="0.01" max="${esc(prepayment.unallocated_balance)}"`) +
      `<p class="full-width muted">${tr("This reduces the document balance without another bank movement.")}</p>`, "Allocate prepayment"));
    bindForm(d, async (data) => {
      await post(base + `/prepayments/${encodeURIComponent(prepayment.id)}/allocate`, {
        ...data, document_type: customer ? "invoice" : "bill", idempotency_key: key,
      });
      await saved(d);
    });
  }

  function refundPrepaymentDialog(prepayment) {
    const base = path(`/prepayments/${encodeURIComponent(prepayment.id)}`), key = prepaymentKey();
    const d = dialog("Refund prepayment", form(
      `<p class="full-width">${esc(prepayment.contact_name)} · ${tr("Unallocated balance")}: ${esc(money(prepayment.unallocated_balance, prepayment.currency))}</p>` +
      field("Refund date", "refund_date", today(), "date", `required min="${esc(prepayment.document_date)}"`) +
      field("Amount", "amount", prepayment.unallocated_balance, "number", `required min="0.01" step="0.01" max="${esc(prepayment.unallocated_balance)}"`) +
      field("Reference", "reference", "", "text", 'maxlength="240"') +
      `<p class="full-width muted">${tr("Refund only the unallocated balance through the original bank account.")}</p>`, "Refund prepayment"));
    bindForm(d, async (data) => {
      await post(base + "/refund", {...data, idempotency_key: key});
      await saved(d);
    });
  }

  async function paymentOrderDialog() {
    const base = path("");
    const [accounts, preview] = await Promise.all([
      api(base + "/bank-accounts"), api(base + "/payment-orders/candidates"),
    ]);
    if (base !== path("")) return;
    const banks = accounts.filter((x) => x.active && x.iban);
    if (!banks.length) {
      toast(t("Add a bank account with an IBAN before creating a payment order."), "info");
      return bankDialog();
    }
    const d = dialog("Create payment order", form(
      select("Bank account", "bank_account_id", banks.map((x) => [x.id, `${x.name} · ${x.currency}`])) +
      field("Execution date", "execution_date", today(), "date", "required") +
      field("Due on or before", "due_before", "", "date") +
      `<div class="full-width" data-payment-preview></div><p class="muted">${tr("This creates payment instructions only. Bills remain unpaid until a payment is recorded.")}</p>`,
      "Create payment order"));
    d.classList.add("payment-order-dialog");
    let current = preview, previewGeneration = 0;
    const f = d.querySelector("form");
    const draw = () => {
      const bank = banks.find((x) => x.id === f.elements.bank_account_id.value);
      d.querySelector("[data-payment-preview]").innerHTML =
        `<h3>${tr("Currency totals")}</h3><p>${Object.entries(current.totals).map(([currency, total]) => esc(money(total, currency))).join(" · ") || tr("No eligible bills.")}</p>` +
        table(["Supplier no.", "Supplier", "Currency", ["Outstanding"], "Select"],
          current.candidates.map((bill) => row([
            td(esc(bill.supplier_number)), td(esc(bill.contact_name)), td(esc(bill.currency)), cash(bill.outstanding, bill.currency),
            td(`<input type="checkbox" name="bill_ids" value="${esc(bill.id)}" aria-label="${esc(bill.supplier_number)}" ${bill.currency === bank.currency ? "checked" : "disabled"}>`),
          ]))) + `<h3>${tr("Excluded bills")}</h3>` +
        table(["Supplier no.", "Supplier", "Reason"], current.excluded.map((bill) => row([
          td(esc(bill.supplier_number)), td(esc(bill.contact_name)), td(tr(bill.reason)),
        ])));
    };
    f.elements.bank_account_id.onchange = draw;
    f.elements.due_before.onchange = async () => {
      const request = ++previewGeneration;
      f.querySelector("[type=submit]").disabled = true;
      try {
        const result = await api(`${base}/payment-orders/candidates${f.elements.due_before.value ? `?due_before=${f.elements.due_before.value}` : ""}`);
        if (request !== previewGeneration || !d.isConnected || base !== path("")) return;
        current = result;
        draw();
        f.querySelector("[type=submit]").disabled = false;
      } catch (error) { f.querySelector(".form-error").textContent = error.message; }
    };
    draw();
    bindForm(d, async (data, formElement) => {
      data.bill_ids = new FormData(formElement).getAll("bill_ids");
      data.due_before ||= null;
      await post(base + "/payment-orders", data);
      await saved(d);
    });
  }

  function journalImportDialog(c) {
    const oid = org.id, url = integrationUrl(c, "file_import", "/import");
    const d = dialog("Import journal workbook", form(
      `<p class="full-width">${tr("Upload titled journal blocks, then review accounts, totals and posting dates before applying.")}</p><label>${tr("Bookkeeping journal")}<input name="journal_file" type="file" accept=".xlsx" required></label>`, "Stage import"));
    bindForm(d, async () => {
      const file = d.querySelector('[name=journal_file]').files[0];
      if (!file || !file.name.toLowerCase().endsWith('.xlsx') || file.size > 2000000)
        throw new Error(t("Journal workbook must be an XLSX file under 2 MB"));
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      const result = await post(url, {object_type: "journal", xlsx_base64: btoa(binary)});
      closeDialog(d);
      if (org?.id === oid) location.hash = `integrations/review/file_import/${encodeURIComponent(result.id)}`;
    });
  }

  function masterDataImportDialog(kind = "contacts") {
    const base = path("/imports"), oid = org.id;
    const d = dialog("Data import", form(
      select("Import kind", "kind", [["contacts", t("Contacts")], ["items", t("Items")]], kind) +
      `<p class="full-width muted">${tr("Prices use the organisation's base currency.")}</p>
      <p class="full-width muted">${tr("Required columns: contacts need name and contact_type; items need code and name. Other columns are optional. Use account codes or leave blank for standard accounts.")}</p>
      <p class="full-width" data-import-columns></p>
      <label>${tr("CSV file")}<input name="csv_file" type="file" accept=".csv,text/csv"></label>
      <label>${tr("CSV contents")}<textarea name="csv_content" rows="8" maxlength="2000000"></textarea></label>`, "Stage import"));
    const columns = () => {
      d.querySelector("[data-import-columns]").textContent = t("CSV columns") + ": " +
        (d.querySelector("[name=kind]").value === "contacts"
          ? "name, contact_type, email, phone, address, registry_code, vat_number, bank_account"
          : "code, name, sale_account, purchase_account, unit, sale_price, purchase_price");
    };
    columns();
    d.querySelector("[name=kind]").onchange = columns;
    bindForm(d, async (data) => {
      const file = d.querySelector("[name=csv_file]").files[0];
      if (file && file.size > 2000000) throw new Error(t("CSV file is too large"));
      const csv_content = file ? await file.text() : data.csv_content;
      const batch = await post(base, {kind: data.kind, csv_content});
      closeDialog(d);
      if (org?.id === oid) location.hash = `imports/${encodeURIComponent(batch.id)}`;
    });
  }

  function importDialog(accounts) {
    if (!accounts.length) return bankDialog();
    const base = path("/bank-accounts");
    const d = dialog(
      "Import statement",
      form(
        select(
          "Bank account",
          "bank_account_id",
          accounts.map((x) => [x.id, x.name]),
        ) +
          select("Format", "format", [
            ["csv", "CSV"],
            ["camt053", "CAMT.053 XML"],
          ]) +
          field("File", "file", "", "file", 'required accept=".csv,.xml"'),
        "Import for review",
      ),
    );
    bindForm(d, async (data, f) => {
      const payload = new FormData();
      payload.append("file", f.elements.file.files[0]);
      await api(`${base}/${data.bank_account_id}/imports/${data.format}`, {
        method: "POST",
        body: payload,
      });
      await saved(d);
    });
  }
  async function reviewTransaction(tx) {
    const base = path(`/bank-transactions/${tx.id}`),
      oid = org.id;
    const [suggestions, documents] = await Promise.all([
      post(base + "/suggest"),
      api(path(Number(tx.amount) >= 0 ? "/invoices" : "/bills")),
    ]);
    if (oid !== org.id) return;
    const candidates = documents.filter(
      (x) =>
        ["Issued", "Approved", "Part Paid"].includes(x.status) &&
        Number(x.total) > Number(x.paid_total || 0),
    );
    const d = dialog(
      "Review transaction",
      `<div class="review-summary"><strong>${esc(tx.counterparty || tx.reference)}</strong><b>${esc(money(tx.amount, tx.currency))}</b></div><h3>${tr("Suggested matches")}</h3>${suggestions.length ? suggestions.map((s, i) => `<div class="suggestion"><div><strong>${esc(s.document_number)}</strong><p>${(s.reasons || []).map(tr).join(" · ")}</p><small>${tr("Confidence")}: ${num(Number(s.confidence) * 100)}%</small></div><div><b>${esc(money(s.amount, tx.currency))}</b>${button("Confirm match", "match", true, `data-index="${i}"`)}</div></div>`).join("") : empty("No suggested matches")}<details class="split-details"><summary>${tr("Split across documents")}</summary>${candidates.length >= 2 ? form(candidates.map((x) => field(`${x.number || x.supplier_number} · ${money(Number(x.total) - Number(x.paid_total || 0), tx.currency)}`, x.id, "", "number", 'min="0" step="0.01"')).join(""), "Reconcile split") : `<p>${tr("At least two open documents are needed for a split.")}</p>`}</details>`,
    );
    bindActions(d, {
      match: (b) => {
        const s = suggestions[Number(b.dataset.index)];
        confirmAction(
          "Confirm match",
          tr("Post this payment against the selected document?"),
          async () => {
            await post(base + "/reconcile", {
              target_type: s.target_type,
              target_id: s.target_id,
            });
            await saved(d);
          },
        );
      },
    });
    if (d.querySelector("form"))
      bindForm(d, async (data) => {
        const allocations = Object.entries(data)
          .filter(([, v]) => Number(v) > 0)
          .map(([id, amount]) => ({
            target_type: Number(tx.amount) >= 0 ? "invoice" : "bill",
            target_id: id,
            amount,
          }));
        if (allocations.length < 2)
          throw new Error(t("Choose at least two amounts."));
        const cents = (s) => {
          const [whole, frac = ""] = String(s).replace("-", "").split(".");
          return BigInt(whole) * 100n + BigInt(frac.padEnd(2, "0").slice(0, 2));
        };
        if (
          allocations.reduce((s, x) => s + cents(x.amount), 0n) !==
          cents(tx.amount)
        )
          throw new Error(
            t("Split amounts must equal the transaction amount."),
          );
        confirmAction(
          "Reconcile split",
          tr("Post these payment allocations?"),
          async () => {
            await post(base + "/reconcile-split", { allocations });
            await saved(d);
          },
        );
      });
  }
  function taxDialog(vd) {
    const base = path("/tax");
    const d = dialog(
      vd ? "Prepare VD" : "Prepare workpaper",
      form(
        field(
          "From",
          "period_start",
          today().slice(0, 7) + "-01",
          "date",
          "required",
        ) +
          field("To", "period_end", today(), "date", "required") +
          select("Basis", "basis", [
            ["accrual", t("Accrual")],
            ["cash", t("Cash (review warning)")],
          ]),
        "Prepare draft",
      ),
    );
    bindForm(d, async (data) => {
      if (data.period_start > data.period_end)
        throw new Error(t("End date must follow start date."));
      const r = await post(base + (vd ? "/estonia/vd" : "/prepare"), data);
      closeDialog(d);
      const result = dialog(
        vd ? "VD workpaper" : "Draft workpaper",
        `<div class="notice">${tr("Exports require accountant review. No direct filing takes place.")}</div>${data.basis === "cash" ? `<p class="warning-text">${tr("Cash-basis values require additional accountant review.")}</p>` : ""}${
          vd
            ? table(
                ["Customer", "VAT number", "Number", ["Amount"]],
                (r.rows || []).map((x) =>
                  row([
                    td(esc(x.name)),
                    td(esc(x.vat_no)),
                    td(esc(x.number)),
                    cash(x.amount ?? x.net_amount ?? x.total),
                  ]),
                ),
              )
            : table(
                ["Box", ["Amount"]],
                Object.entries(r.boxes || {}).map(([k, v]) =>
                  row([td(tr(k)), cash(v)]),
                ),
              )
        }${(r.warnings || []).length ? `<p class="warning-text">${r.warnings.map(tr).join("<br>")}</p>` : ""}<div class="dialog-actions">${vd ? "" : button("Mark accountant reviewed", "review", true)}</div>`,
      );
      bindActions(result, {
        review: () =>
          confirmAction(
            "Mark accountant reviewed",
            tr("Confirm that you have reviewed these figures."),
            async () => {
              await post(`${base}/${r.id}/review`);
              result.querySelector(".dialog-actions").innerHTML =
                pill("Reviewed") +
                link("Export CSV", `/api${base}/${r.id}/export.csv`);
              toast(t("Workpaper reviewed"));
            },
          ),
      });
    });
  }
  async function employeeDialog(employee) {
    const url = path("/employees") + (employee ? `/${employee.id}` : "");
    const writable = ["owner", "administrator", "accountant"].includes(org?.role);
    let histories = employee ? await api(url + "/tax-settings") : [];
    const e = employee || {
      active: true,
      apply_tax_free_minimum: true,
      funded_pension_percent: 2,
      pay_basis: "monthly",
      fte: "1",
    };
    const d = dialog(
      employee ? (writable ? "Edit employee" : "Employee details") : "Add employee",
      form(
        field("Name", "name", e.name || "", "text", "required") +
          field("Email", "email", e.email || "", "email") +
          field("Personal ID", "personal_id", e.personal_id || "") +
          field("Phone", "phone", e.phone || "", "tel", 'maxlength="50"') +
          field("Date of birth", "date_of_birth", e.date_of_birth || "", "date") +
          field("Address", "address", e.address || "", "text", 'maxlength="2000"') +
          field("IBAN", "iban", e.iban || "", "text", 'maxlength="80"') +
          field("Bank account owner", "bank_account_owner", e.bank_account_owner || "", "text", 'maxlength="180"') +
          select(
            "Pay basis",
            "pay_basis",
            payBases.map(([v, l]) => [v, t(l)]),
            e.pay_basis || (e.board_member ? "board_fee" : "monthly"),
          ) +
          field(
            "Monthly salary or board fee",
            "gross_salary",
            e.gross_salary ?? "",
            "number",
            'min="0.01" step="0.01"',
          ) +
          field(
            "Hourly rate",
            "hourly_rate",
            e.hourly_rate ?? "",
            "number",
            'min="0.01" step="0.0001"',
          ) +
          field(
            "Work-time fraction (FTE)",
            "fte",
            e.fte ?? "1",
            "number",
            'required min="0.0001" max="1" step="0.0001"',
          ) +
          select(
            "Pension %",
            "funded_pension_percent",
            [
              ["0", "0%"],
              ["2", "2%"],
              ["4", "4%"],
              ["6", "6%"],
            ],
            Number(e.funded_pension_percent),
          ) +
          select(
            "Social tax minimum exemption",
            "social_tax_minimum_exemption",
            socialTaxExemptions
              .filter(([v]) => v !== "board_member")
              .map(([v, l]) => [v, t(l)]),
            e.social_tax_minimum_exemption || "",
          ) +
          field(
            "Employment start date",
            "employment_start_date",
            e.employment_start_date || "",
            "date",
          ) +
          field(
            "Employment end date",
            "employment_end_date",
            e.employment_end_date || "",
            "date",
          ) +
          check(
            "Apply tax-free minimum",
            "apply_tax_free_minimum",
            e.apply_tax_free_minimum,
          ) +
          check("Active", "active", e.active),
      ) + (employee ? `<section class="employee-tax-settings"><h3>${tr("Tax settings")}</h3><p class="muted">${tr("Changes apply to new pay runs using month-end settings.")}</p><div data-tax-histories></div><div data-tax-editor></div></section>` : ""),
    );
    const employeeForm = d.querySelector("form");
    const updateBasis = () => {
      const basis = employeeForm.elements.pay_basis.value,
        hourly = basis === "hourly",
        board = basis === "board_fee";
      const show = (name, visible) => {
        const input = employeeForm.elements[name];
        input.closest("label").style.display = visible ? "" : "none";
        input.disabled = !visible;
        input.required = visible && name !== "social_tax_minimum_exemption";
      };
      show("gross_salary", !hourly && basis !== "income_line");
      show("hourly_rate", hourly);
      show("social_tax_minimum_exemption", !board && basis !== "income_line");
    };
    employeeForm.elements.pay_basis.onchange = updateBasis;
    updateBasis();
    bindForm(d, async (data, f) => {
      for (const k of ["apply_tax_free_minimum", "active"])
        data[k] = f.elements[k].checked;
      data.board_member = data.pay_basis === "board_fee";
      for (const k of ["gross_salary", "hourly_rate"])
        if (!data[k]) delete data[k];
      for (const k of [
        "social_tax_minimum_exemption",
        "employment_start_date",
        "employment_end_date",
      ])
        if (!data[k]) data[k] = null;
      await post(url, data, employee ? "PATCH" : "POST");
      await saved(d);
    });
    if (!writable) {
      employeeForm.querySelectorAll("input,select,[type=submit]").forEach((input) => { input.disabled = true; });
      employeeForm.querySelector("[type=submit]").hidden = true;
    }
    if (!employee) return;
    const labels = {tax_free: "Tax-free income application", pension: "Funded pension", unemployment: "Unemployment insurance contribution"};
    const modes = {maximum: "Maximum", limited: "Limited amount", none: "Not applied"};
    const panel = d.querySelector("[data-tax-histories]"), editor = d.querySelector("[data-tax-editor]");
    const renderHistories = () => {
      panel.innerHTML = Object.entries(labels).map(([kind, label]) => `<div class="tax-history"><h4>${tr(label)}</h4>${table(
        ["Effective from", "Setting", "Actions"],
        histories.filter((r) => r.kind === kind).map((r) => row([
          td(esc(r.start_date)),
          td(kind === "tax_free" ? `${tr(modes[r.mode])}${r.mode === "limited" ? ` (${esc(money(r.amount, "EUR"))})` : ""}` : kind === "pension" ? `${esc(r.rate)}%` : tr(r.applies ? "Yes" : "Not applied")),
          td(r.frozen ? `<span class="muted">${tr("Used in approved payroll")}</span>` : writable ? button("Edit", "taxEdit", false, `data-id="${esc(r.id)}"`) + button("Delete", "taxDelete", false, `data-id="${esc(r.id)}"`) : ""),
        ])),
      )}${writable ? button("Add tax setting", "taxAdd", false, `data-kind="${kind}"`) : ""}</div>`).join("");
    };
    const refreshHistories = async () => {
      histories = await api(url + "/tax-settings");
      renderHistories();
    };
    const editSetting = (kind, existing) => {
      const r = existing || {start_date: today(), mode: "maximum", rate: 2, applies: true};
      editor.innerHTML = `<h4>${tr(labels[kind])}</h4>` + form(
        field("Effective from", "start_date", r.start_date, "date", "required") +
        (kind === "tax_free" ? select("Tax-free income application", "mode", Object.entries(modes).map(([v, l]) => [v, t(l)]), r.mode) + field("Monthly limit", "amount", r.amount ?? "", "number", 'min="0" step="0.01"') :
          kind === "pension" ? select("Pension %", "rate", [0, 2, 4, 6].map((v) => [v, `${v}%`]), r.rate) : check("Employee unemployment insurance applies", "applies", r.applies)),
        "Save tax setting",
      );
      const f = editor.querySelector("form"), cancel = f.querySelector("[data-action=cancel]");
      cancel.dataset.action = "taxCancel";
      cancel.onclick = () => { editor.innerHTML = ""; panel.querySelector("button")?.focus(); };
      if (kind === "tax_free") {
        const toggleLimit = () => {
          const limited = f.elements.mode.value === "limited";
          f.elements.amount.disabled = !limited;
          f.elements.amount.required = limited;
          f.elements.amount.closest("label").hidden = !limited;
        };
        f.elements.mode.onchange = toggleLimit;
        toggleLimit();
      }
      bindForm(editor, async (data) => {
        const payload = {kind, start_date: data.start_date};
        if (kind === "tax_free") Object.assign(payload, {mode: data.mode, amount: data.mode === "limited" ? data.amount : null});
        if (kind === "pension") payload.rate = data.rate;
        if (kind === "unemployment") payload.applies = f.elements.applies.checked;
        await post(url + "/tax-settings" + (existing ? `/${existing.id}` : ""), payload, existing ? "PUT" : "POST");
        await refreshHistories();
        editor.innerHTML = "";
        panel.querySelector("button")?.focus();
      });
      f.elements.start_date.focus();
    };
    panel.onclick = async (event) => {
      const b = event.target.closest("button[data-action]");
      if (!b || !writable) return;
      const r = histories.find((r) => r.id === b.dataset.id);
      if (b.dataset.action === "taxAdd") return editSetting(b.dataset.kind);
      if (b.dataset.action === "taxEdit") return editSetting(r.kind, r);
      if (b.dataset.action === "taxDelete") {
        b.disabled = true;
        try {
          await post(url + `/tax-settings/${r.id}`, undefined, "DELETE");
          editor.innerHTML = "";
          await refreshHistories();
        } catch (error) { toast(error.message, "error"); b.disabled = false; }
      }
    };
    renderHistories();
  }
  function payrollWizard(employees) {
    const url = path("/pay-runs"),
      active = employees.filter((x) => x.active),
      hourly = active.some((x) => x.pay_basis === "hourly");
    if (!active.length) {
      toast(t("Add an active employee before running payroll."), "info");
      return employeeDialog();
    }
    const d = dialog(
      "Run payroll for month",
      form(
        field("Month", "period", today().slice(0, 7), "month", "required") +
          `<label class="check"><input type="checkbox" name="show_leave_balance"><span>${tr("Show remaining leave days on payslips")}</span></label>` +
          `<div class="full-width"><h3>${tr("Included employees")}</h3>${table(
            ["Name", ["Gross salary"], ["Hours worked"]],
            active.map((x) =>
              row([
                td(`${esc(x.name)}${partTime(x)}`),
                x.pay_basis === "hourly"
                  ? td(
                      `${esc(money(x.hourly_rate, "EUR"))} ${tr("per hour")}`,
                      "numeric",
                    )
                  : cash(x.gross_salary, "EUR"),
                td(
                  x.pay_basis === "hourly"
                    ? `<input name="hours:${esc(x.id)}" type="number" min="0.01" max="744" step="0.01" required aria-label="${tr("Hours worked")}: ${esc(x.name)}"><span class="field-error" data-error="hours:${esc(x.id)}"></span>`
                    : "",
                  "numeric",
                ),
              ]),
            ),
          )}${hourly ? `<p class="muted">${tr("Enter hours worked for each hourly employee.")}</p>` : ""}<p class="muted">${tr("Employee details are frozen when the draft is created. Review before approval.")}</p></div>`,
        "Create draft",
      ),
    );
    bindForm(d, async (data) => {
      const hours = Object.fromEntries(
        Object.entries(data)
          .filter(([k]) => k.startsWith("hours:"))
          .map(([k, v]) => [k.slice(6), v]),
      );
      confirmAction(
        "Create payroll draft",
        `${tr("Month")}: ${esc(data.period)}<br>${num(active.length)} ${tr("employees")}`,
        async () => {
          await post(url, { period: data.period, hours, show_leave_balance: Boolean(d.querySelector('[name="show_leave_balance"]')?.checked) });
          await saved(d);
        },
      );
    });
  }
  const componentFlags = [
    ["income_tax", "Income tax"], ["social_tax", "Social tax"],
    ["ui_employee", "Employee unemployment insurance"], ["ui_employer", "Employer unemployment insurance"],
    ["funded_pension", "Funded pension"], ["social_minimum", "Counts towards social tax minimum"],
  ];
  const payrollRoleLabels = {
    PAYROLL_SALARY: "Salary expense", PAYROLL_SOCIAL: "Social tax expense", PAYROLL_UI: "Employer unemployment expense",
    PAYROLL_VACATION_RESERVE_EXPENSE: "Vacation reserve expense", PAYROLL_VACATION_RESERVE_LIABILITY: "Vacation reserve liability",
    PAYROLL_SALARY_PAYABLE: "Salary payable", PAYROLL_BAILIFF: "Bailiff withholding liability", PAYROLL_DEDUCTION: "Other deduction liability",
    PAYROLL_SOCIAL_ACCRUED: "Social tax accrued", PAYROLL_INCOME_WITHHELD: "Income tax withheld", PAYROLL_PENSION_WITHHELD: "Funded pension withheld",
    PAYROLL_UI_ACCRUED: "Unemployment insurance accrued", PAYROLL_SOCIAL_PAYABLE: "Social tax and pension payable",
    PAYROLL_INCOME_PAYABLE: "Income tax payable", PAYROLL_UI_PAYABLE: "Unemployment insurance payable",
  };
  function declarationPanel(runs) {
    const approved = runs.filter((r) => r.status === "Approved");
    if (!approved.length) return "";
    const labels = {none: "Not prepared", prepared: "Prepared", settled: "Settled"};
    return `<section class="section payroll-declarations"><h2>${tr("Month-end declarations")}</h2>${table(["Period", "Declaration state", "Due date", "Actions"], approved.map((r) => row([
      td(esc(r.period)), td(tr(labels[r.declaration_state] || "Not prepared")),
      td(`${esc(r.declaration_due_date || "")}${r.declaration_overdue ? `<small class="declaration-overdue">${tr("Overdue declaration")}</small>` : ""}`),
      td(r.declaration_state === "settled" ? "" : (r.declaration_state === "prepared" ? "" : button("Prepare TSD", "tsd_prepare", false, `data-id="${esc(r.id)}"`)) + button("Reclassify TSD liabilities", "settleDeclaration", false, `data-id="${esc(r.id)}"`)),
    ])))}</section>`;
  }
  function componentFlagFields(values) {
    return componentFlags.map(([key, label]) => check(label, key, values[key])).join("");
  }
  function paymentTypesContent(types) {
    return `${button("Add payment type", "newType", true, canExecutePush() ? "" : "disabled")}${table(["Name", "Description", "Direction", "Actions"], types.map((x) => row([
      td(esc(t(x.name))), td(esc(t(x.description || ""))), td(tr(x.direction === "income" ? "Income" : "Deduction")), td(button("Edit", "editType", false, `data-id="${esc(x.id)}" ${canExecutePush() ? "" : "disabled"}`)),
    ])))}`;
  }
  function paymentTypesDialog(c, types) {
    const d = dialog("Payment types", paymentTypesContent(types));
    bindPaymentTypeActions(c, types, d, true);
  }
  const absenceKinds = [
    ["annual_leave", "Annual leave"], ["extended_leave", "Extended leave"],
    ["child_leave", "Child leave"], ["paternity_leave", "Paternity leave"],
    ["maternity_leave", "Maternity leave"], ["parental_leave", "Parental leave"],
    ["study_leave", "Study leave"], ["care_leave", "Care leave"],
    ["sick_leave", "Sick leave"], ["permitted_absence", "Permitted absence"],
    ["truancy", "Unauthorised absence"], ["unpaid_leave", "Unpaid leave"],
    ["alternative_service", "Alternative service"], ["other", "Other absence"],
  ];
  async function payrollAbsencesDialog(c, employees) {
    const base = c.url("/payroll/absences");
    const canWriteAbsences = ["owner", "administrator", "accountant"].includes(org?.role);
    const monthNow = new Date().toISOString().slice(0, 7);
    const renderList = async (month = monthNow, kind = "") => {
      document.querySelectorAll(".dialog").forEach(closeDialog);
      const query = new URLSearchParams();
      if (month) query.set("month", month);
      if (kind) query.set("absence_type", kind);
      const [rows, typeSettings] = await Promise.all([api(base + (query.size ? `?${query}` : "")), api(c.url("/payroll/absence-types"))]);
      const writableLeave = (absence) => ["annual_leave", "extended_leave", "study_leave"].includes(absence.absence_type);
      const payPanel = (absence) => {
        if (!writableLeave(absence)) return "";
        const pay = absence.absence_pay, breakdown = pay?.breakdown || {}, average = breakdown.average || {};
        const methods = [["average", "Average"], ["unchanged_salary", "Unchanged salary"], ["best_of", "Best of"], ["fixed_sum", "Fixed sum"]];
        const statusLabel = pay?.status ? ({pending: "Pending", in_payout: "In payout", paid: "Paid"}[pay.status] || pay.status) : "Not calculated";
        return `<div class="absence-pay"><strong>${tr("Vacation pay")}</strong><p>${tr("Status")}: ${tr(statusLabel)}${pay ? ` · ${esc(money(pay.gross, "EUR"))}` : ""}</p>${canWriteAbsences ? `<div class="absence-pay-controls">${select("Vacation pay method", `method-${absence.id}`, methods.map(([v,l]) => [v,tr(l)]), pay?.method || "average")}${field("Fixed amount", `fixed-${absence.id}`, pay?.fixed_amount || "", "number")}${button("Calculate vacation pay", "calculateAbsencePay", false, `data-id="${esc(absence.id)}"`)}</div>` : ""}<table><thead><tr><th>${tr("Calculation")}</th><th>${tr("Amount")}</th></tr></thead><tbody><tr><td>${tr("Six-month wages")}</td><td>${esc(money(average.wage_total || 0, "EUR"))}</td></tr><tr><td>${tr("Divisor days")}</td><td>${num(average.daily_denominator || 0)}</td></tr><tr><td>${tr("Daily rate")}</td><td>${esc(money(average.average_daily_pay || 0, "EUR"))}</td></tr><tr><td>${tr("Days")}</td><td>${num(breakdown.leave_days ?? absence.leave_days)}</td></tr><tr><td>${tr("Total")}</td><td>${esc(money(pay?.gross || 0, "EUR"))}</td></tr></tbody></table>${canWriteAbsences && pay?.status === "pending" ? button("Add to payout", "addAbsencePay", true, `data-id="${esc(absence.id)}"`) : ""}</div>`;
      };
      const d = dialog("Absences", `<div class="section-head">${field("Month", "month", month, "month")} ${select("Absence type", "absence_type", [["", "All types"], ...absenceKinds.map(([v, label]) => [v, tr(label)])], kind)}</div>${canWriteAbsences ? `${button("Add absence", "addAbsence", true)} ${button("Collective annual leave", "collectiveLeave")} ${button("Absence pay settings", "absenceSettings")} ${button("Opening balances and historical earnings", "payrollHistoryImports")}` : ""}${rows.length ? table(["Employee", "Type", "Start date", "End date", "Calendar days", "Leave days", "Working days", "Vacation pay", "Actions"], rows.map((absence) => row([td(esc(absence.employee_name)), td(tr(absenceKinds.find(([key]) => key === absence.absence_type)?.[1] || "Other absence")), td(esc(absence.start_date)), td(esc(absence.end_date)), td(num(absence.calendar_days)), td(num(absence.leave_days)), td(num(absence.working_days)), td(payPanel(absence)), td(canWriteAbsences ? (absence.frozen ? tr("Used in approved payroll") : button("Edit", "editAbsence", false, `data-id="${esc(absence.id)}"`) + button("Delete", "deleteAbsence", false, `data-id="${esc(absence.id)}"`)) : "" )]))) : empty("No absences", "")}`);
      d.querySelector('[name="month"]').onchange = () => { const nextMonth = d.querySelector('[name="month"]').value; const nextKind = d.querySelector('[name="absence_type"]').value; closeDialog(d); renderList(nextMonth, nextKind); };
      d.querySelector('[name="absence_type"]').onchange = () => { const nextMonth = d.querySelector('[name="month"]').value; const nextKind = d.querySelector('[name="absence_type"]').value; closeDialog(d); renderList(nextMonth, nextKind); };
      bindActions(d, {
        addAbsence: () => absenceEditDialog(c, employees, null, () => renderList(month, kind)),
        collectiveLeave: () => collectiveLeaveDialog(c, employees, () => renderList(month, kind)),
        absenceSettings: () => absenceSettingsDialog(c, typeSettings, () => renderList(month, kind)),
        payrollHistoryImports: () => payrollHistoryImportDialog(c),
        calculateAbsencePay: async (buttonEl) => {
          const id = buttonEl.dataset.id, method = d.querySelector(`[name="method-${CSS.escape(id)}"]`).value;
          const fixed = d.querySelector(`[name="fixed-${CSS.escape(id)}"]`).value;
          await post(`${base}/${id}/pay`, {method, fixed_amount: method === "fixed_sum" ? fixed : null});
          await renderList(month, kind);
        },
        addAbsencePay: async (buttonEl) => addAbsencePayToPayout(c, rows.find((x) => x.id === buttonEl.dataset.id), () => renderList(month, kind)),
        editAbsence: (buttonEl) => absenceEditDialog(c, employees, rows.find((row) => row.id === buttonEl.dataset.id), () => renderList(month, kind)),
        deleteAbsence: (buttonEl) => confirmAction("Delete absence", tr("Delete this absence?"), async () => {
          await post(`${base}/${buttonEl.dataset.id}`, undefined, "DELETE");
          closeDialog(d); await renderList(month, kind);
        }),
      });
    };
    await renderList();
  }
  async function payrollHistoryImportDialog(c) {
    document.querySelectorAll(".dialog").forEach(closeDialog);
    const upload = (type, label, description) => `<form class="payroll-history-upload" data-upload-type="${type}"><h3>${tr(label)}</h3><p class="muted">${tr(description)}</p><label>${tr("CSV or XLSX file")}<input name="file" type="file" accept=".csv,.xlsx" required></label><button class="fs-btn fs-btn-outline" type="submit">${tr("Upload for review")}</button></form>`;
    const d = dialog("Opening balances and historical earnings", `<div class="payroll-history-imports">${upload("payroll_opening_leave", "Leave entitlement and opening balance", "Upload employee personal code, days per year, effective date, cutover date, basic unused days and extended unused days.")}${upload("historical_earnings", "Historical earnings", "Upload employee personal code, YYYY-MM, wage total and unpaid absence calendar days.")}</div>`);
    d.querySelectorAll("form[data-upload-type]").forEach((formEl) => {
      formEl.addEventListener("submit", async (event) => {
        event.preventDefault();
        const file = formEl.elements.file.files[0];
        if (!file) return;
        const body = new FormData(); body.append("file", file);
        try {
          const summary = await api(c.url(`/payroll/history-imports/${formEl.dataset.uploadType}`), {method: "POST", body});
          await payrollHistoryImportReview(c, summary.id);
        } catch (error) { toast(error.message, "error"); }
      });
    });
  }
  async function payrollHistoryImportReview(c, syncId, outcome = null) {
    const review = await api(c.url(`/payroll/history-imports/${encodeURIComponent(syncId)}`));
    const records = review.records || [];
    const body = records.length ? table(
      ["File row", "Employee", "Imported values", "Review note", "Decision"],
      records.map((record) => {
        const payload = record.external_payload || {};
        return row([
          td(num(payload.file_row)),
          td(record.matched_local_id ? esc(record.matched_local_id) : tr("No employee matched")),
          td(esc(JSON.stringify(payload))),
          td(esc(record.review_note || "")),
          td(`<select name="decision-${esc(record.id)}"><option value="apply">${tr("Apply")}</option><option value="reject">${tr("Reject")}</option></select>`),
        ]);
      }),
    ) : empty("No records were staged", "");
    const d = dialog("Review payroll import", `${outcome ? integrationOutcomeSummary(outcome) : ""}<p class="muted">${tr("Review matched employees and row errors before applying.")}</p>${body}<button class="fs-btn fs-btn-ink" data-action="applyPayrollHistoryImport">${tr("Apply reviewed rows")}</button>`);
    d.querySelector('[data-action="applyPayrollHistoryImport"]').onclick = async () => {
      const decisions = Object.fromEntries(records.map((record) => [record.id, d.querySelector(`[name="decision-${CSS.escape(record.id)}"]`).value]));
      try {
        const result = await post(c.url(`/payroll/history-imports/${encodeURIComponent(syncId)}/apply`), {decisions});
        await payrollHistoryImportReview(c, syncId, result);
      } catch (error) { toast(error.message, "error"); }
    };
  }
  async function addAbsencePayToPayout(c, absence, refresh) {
    if (!absence?.absence_pay || absence.absence_pay.status !== "pending") return;
    const payoutBase = c.url("/payroll/absence-payouts"), drafts = await api(payoutBase);
    document.querySelectorAll(".dialog").forEach(closeDialog);
    const d = dialog("Add to payout", form(
      select("Draft payout", "payout_id", [["new", tr("Create a new draft payout")], ...drafts.map((x) => [x.id, `${x.payout_date} · ${x.id.slice(0, 8)}`])], "new") +
      field("Payout date", "payout_date", absence.absence_pay.payment_date || absence.start_date, "date", "required"),
      "Add to payout"));
    bindForm(d, async (data) => {
      if (data.payout_id === "new") {
        await post(payoutBase, {absence_pay_ids: [absence.absence_pay.id], payout_date: data.payout_date});
      } else {
        await post(`${payoutBase}/${data.payout_id}/records`, {absence_pay_ids: [absence.absence_pay.id]});
      }
      closeDialog(d); await refresh();
    });
  }
  function absenceEditDialog(c, employees, existing, refresh) {
    const employeeOptions = employees.filter((e) => e.active || e.id === existing?.employee_id).map((e) => [e.id, e.name]);
    const d = dialog(existing ? "Edit absence" : "Add absence", form(
      select("Employee", "employee_id", employeeOptions, existing?.employee_id || "") +
      select("Absence type", "absence_type", absenceKinds.map(([v, label]) => [v, tr(label)]), existing?.absence_type || "annual_leave") +
      field("Start date", "start_date", existing?.start_date || "", "date", "required") +
      field("End date", "end_date", existing?.end_date || "", "date", "required") +
      field("Document reference", "document_reference", existing?.document_reference || "") +
      `<label class="full-width">${tr("Comment")}<textarea name="comment" maxlength="2000">${esc(existing?.comment || "")}</textarea></label>`
    ));
    bindForm(d, async (data) => {
      await post(c.url(`/payroll/absences${existing ? `/${existing.id}` : ""}`), data, existing ? "PUT" : "POST");
      closeDialog(d); await refresh();
    });
  }
  function collectiveLeaveDialog(c, employees, refresh) {
    const d = dialog("Collective annual leave", form(
      `<label class="full-width">${tr("Employees")}<select name="employee_ids" multiple size="7" required>${employees.filter((e) => e.active).map((e) => `<option value="${esc(e.id)}">${esc(e.name)}</option>`).join("")}</select></label>` +
      field("Start date", "start_date", "", "date", "required") + field("End date", "end_date", "", "date", "required") +
      field("Document reference", "document_reference") + `<label class="full-width">${tr("Comment")}<textarea name="comment" maxlength="2000"></textarea></label>`
    ));
    bindForm(d, async (_data, f) => {
      const data = Object.fromEntries(new FormData(f));
      data.employee_ids = [...f.elements.employee_ids.selectedOptions].map((option) => option.value);
      await post(c.url("/payroll/absences/collective"), data);
      closeDialog(d); await refresh();
    });
  }
  function absenceSettingsDialog(c, typeSettings, refresh) {
    const permitted = typeSettings.find((setting) => setting.absence_type === "permitted_absence");
    const d = dialog("Absence pay settings", form(check("Continue salary during permitted absence", "paid_salary", permitted?.paid_salary)));
    bindForm(d, async (_data, f) => {
      await post(c.url("/payroll/absence-types/permitted_absence"), {paid_salary: f.elements.paid_salary.checked}, "PUT");
      closeDialog(d); await refresh();
    });
  }
  function bindPaymentTypeActions(c, types, target, modal = false) {
    const edit = (type) => {
      if (modal) closeDialog(target);
      const values = type || {direction: "income", liability_role: "PAYROLL_DEDUCTION", is_wage: true, active: true, ...Object.fromEntries(componentFlags.map(([key]) => [key, true]))};
      const editor = dialog(type ? "Edit payment type" : "Add payment type", form(
        field("Name", "name", values.name || "", "text", 'required maxlength="180"') +
        (values.description ? `<p class="full-width muted">${tr(values.description)}</p>` : "") +
        select("Direction", "direction", [["income", t("Income")], ["deduction", t("Deduction")]], values.direction) +
        select("TSD payment type", "tsd_payment_type", [[10, "10 palgatulu"], [13, "13 kõrgete ametiisikute palgatulu"], [14, "14 sünnitoetus"], [15, "15 seaduse alusel tasu"], [16, "16 muu maksustatav väljamakse"], [17, "17 VÕS lepingutasu"], [21, "21 juhtorgani liikme tasu"], [24, "24 tööandja haigushüvitis"], [32, "32 tööõnnetuse hüvitis"], [33, "33 lõpetamise hüvitis"], [120, "120 mitteresidendi palgatulu"]], values.tsd_payment_type || 10) +
        select("Deduction liability", "liability_role", [["PAYROLL_DEDUCTION", t("Other deduction liability")], ["PAYROLL_BAILIFF", t("Bailiff withholding liability")]], values.liability_role) +
        check("Counts towards average and vacation pay", "is_wage", values.is_wage) + check("Active for new payment lines", "active", values.active) +
        `<div class="full-width component-flags">${componentFlagFields(values)}</div><p class="full-width muted">${tr("Levy flags apply to income lines. Deduction lines reduce net pay.")}</p>` + `<p class="full-width muted">${tr("Defaults can be overridden on each draft payment line. Confirm tax treatment before approval.")}</p>`,
      ));
      bindForm(editor, async (data, f) => {
        componentFlags.forEach(([key]) => data[key] = f.elements[key].checked);
        data.is_wage = f.elements.is_wage.checked;
        data.active = f.elements.active.checked;
        data.tsd_payment_type = Number(f.elements.tsd_payment_type.value);
        await post(c.url(`/payroll/component-types${type ? `/${type.id}` : ""}`), data, type ? "PUT" : "POST");
        await saved(editor);
      });
    };
    bindActions(target, {newType: () => edit(), editType: (b) => edit(types.find((x) => x.id === b.dataset.id))});
  }
  async function payrollAccountsDialog(c) {
    const [mappings, accounts] = await Promise.all([api(c.url('/payroll/posting-mappings')), api(c.url('/accounts'))]);
    const d = dialog("Payroll accounts", form(mappings.map((mapping) => {
      const expense = ["PAYROLL_SALARY", "PAYROLL_SOCIAL", "PAYROLL_UI", "PAYROLL_VACATION_RESERVE_EXPENSE"].includes(mapping.role);
      return select(payrollRoleLabels[mapping.role], mapping.role, accounts.filter((a) => a.active && a.account_type === (expense ? "Expense" : "Liability")).map((a) => [a.code, `${a.code} ${a.name}`]), mapping.account_code);
    }).join("")));
    bindForm(d, async (data) => {
      for (const mapping of mappings) {
        if (data[mapping.role] !== mapping.account_code)
          await post(c.url(`/payroll/posting-mappings/${mapping.role}`), {account_code: data[mapping.role]}, "PUT");
      }
      await saved(d);
    });
  }
  async function payrollLeaveSettingsDialog(c) {
    const url = c.url('/payroll/leave-settings'), settings = await api(url);
    const policy = [['none', 'No expiry'], ['1_january_year_plus_2', '1 January of year +2'], ['31_december_year_plus_1', '31 December of year +1']];
    const d = dialog('Leave settings', form(select('Basic leave expiry', 'basic_expiry_policy', policy.map(([v,l]) => [v,tr(l)]), settings.basic_expiry_policy) +
      select('Extended leave expiry', 'extended_expiry_policy', policy.map(([v,l]) => [v,tr(l)]), settings.extended_expiry_policy) +
      `<label class="check"><input type="checkbox" name="reserve_posting_enabled" ${settings.reserve_posting_enabled ? 'checked' : ''}><span>${tr('Post monthly vacation reserve')}</span></label>`));
    bindForm(d, async (data) => { data.reserve_posting_enabled = Boolean(d.querySelector('[name="reserve_posting_enabled"]')?.checked); await post(url, data, 'PUT'); await saved(d); });
  }
  async function payrollLeaveLiabilityDialog(c) {
    const asAt = today();
    const load = async (dateValue) => api(c.url('/payroll/leave-liability') + `?as_at=${encodeURIComponent(dateValue)}`);
    let report = await load(asAt), settings = await api(c.url('/payroll/leave-settings'));
    const renderReport = (result) => { const rows = result.employees.map((item) => row([td(esc(item.employee_name)), td(item.remaining_days), cash(item.average_daily_pay,'EUR'), cash(item.wage_liability,'EUR'), cash(item.social_tax,'EUR'), cash(item.employer_unemployment,'EUR'), cash(item.total_liability,'EUR')])); rows.push(row([td(tr('Total')),td(result.totals.remaining_days),td(''),cash(result.totals.wage_liability,'EUR'),cash(result.totals.social_tax,'EUR'),cash(result.totals.employer_unemployment,'EUR'),cash(result.totals.total_liability,'EUR')])); return `<p>${tr('As at')} ${esc(result.as_at)}</p>${settings.reserve_posting_enabled ? button('Post monthly vacation reserve', 'postLeaveReserve', true, `data-period="${esc(result.as_at.slice(0,7))}"`) : ''}${table(['Employee','Remaining days','Average daily pay','Wage liability','Social tax','Employer unemployment','Total liability'], rows)}${result.employees.map((item) => `<details><summary>${esc(item.employee_name)} · ${tr('Leave liability details')}</summary>${table(['Movement','Date','Kind','Days','Expiry date'], item.movements.map((move) => row([td(tr(move.type === 'expired' ? 'Expired' : move.type[0].toUpperCase() + move.type.slice(1))),td(esc(move.date)),td(tr(move.kind)),td(esc(move.days)),td(esc(move.expires_on || ''))])))}</details>`).join('')}`; };
    const d = dialog('Detailed leave liability report', `<div>${field('As at','as_at',asAt,'date')}<a data-liability-xlsx href="/api${c.url('/payroll/leave-liability.xlsx')}?as_at=${encodeURIComponent(asAt)}">${tr('Export Excel')}</a></div><div data-liability-report>${renderReport(report)}</div>`);
    const input = d.querySelector('[name="as_at"]');
    input.addEventListener('change', async () => { try { report = await load(input.value); d.querySelector('[data-liability-report]').innerHTML = renderReport(report); d.querySelector('[data-liability-xlsx]').href = `/api${c.url('/payroll/leave-liability.xlsx')}?as_at=${encodeURIComponent(input.value)}`; } catch(error) { toast(error.message,'error'); } });
    d.addEventListener('click', async (event) => { const b = event.target.closest('[data-action="postLeaveReserve"]'); if (!b) return; confirmAction('Post vacation reserve', `${tr('Period')}: ${esc(b.dataset.period)}`, async () => { await post(c.url('/payroll/leave-reserve-postings'), {period:b.dataset.period}); toast(tr('Vacation reserve posted'),'success'); }); });
  }
  async function payrollPayoutsDialog(c, run, bankAccounts) {
    if (!run) return;
    const refresh = async () => api(c.url('/payroll/payouts') + `?run_id=${encodeURIComponent(run.id)}`);
    const renderBatches = (batches) => batches.length ? table(['Payout date', 'Status', 'Employees', 'Actions'], batches.map((batch) => row([
      td(esc(batch.payout_date)), td(pill(batch.status)), td(num(batch.lines.length)),
      td((batch.status === 'Draft' ? button('Mark paid', 'payPayout', false, `data-id="${batch.id}"`) : '') + (batch.status !== 'Cancelled' ? button('Cancel payout', 'cancelPayout', false, `data-id="${batch.id}"`) : '') + (['Draft','Paid'].includes(batch.status) ? link('Download SEPA file', `/api${c.url(`/payroll/payouts/${batch.id}/pain001.xml`)}`) : '')),
    ]))) : `<p class="muted">${tr('No payouts for this run.')}</p>`;
    let batches = await refresh();
    const bankOptions = bankAccounts.filter((bank) => bank.active).map((bank) => [bank.id, bank.name]);
    const renderEmployeeSummary = (summary) => table(['Employee', 'Net', 'Paid', 'Pending', 'Unpaid'], (summary?.employees || []).map((item) => row([
      td(esc(item.name)), cash(item.net, 'EUR'), cash(item.paid, 'EUR'), cash(item.pending, 'EUR'), cash(item.unpaid, 'EUR'),
    ])));
    const refreshSummary = async () => (await api(c.url('/payroll/payouts/summary') + `?run_id=${encodeURIComponent(run.id)}`))[0];
    const employeeSummary = renderEmployeeSummary(await refreshSummary());
    const d = dialog('Payroll payouts', `<p>${tr('Pay run')} ${esc(run.period)}</p><div data-payout-summary>${employeeSummary}</div><div data-payout-list>${renderBatches(batches)}</div>${button('Create salary payout', 'createPayout', true)}<div data-payout-bank>${bankOptions.length ? select('Bank account', 'bank_account_id', bankOptions, bankOptions[0][0]) : `<p class="notice">${tr('Add an active bank account first.')}</p>`}</div>`);
    d.querySelector('[data-action="createPayout"]').onclick = async () => {
      await post(c.url(`/pay-runs/${run.id}/payouts`), {payout_type: 'salary', bank_account_id: d.querySelector('[name="bank_account_id"]')?.value || null});
      batches = await refresh(); d.querySelector('[data-payout-list]').innerHTML = renderBatches(batches);
      d.querySelector('[data-payout-summary]').innerHTML = renderEmployeeSummary(await refreshSummary());
      bindPayoutActions();
    };
    const bindPayoutActions = () => {
      d.querySelectorAll('[data-action="payPayout"]').forEach((buttonEl) => buttonEl.onclick = async () => {
        if (!bankOptions.length) { toast(t('Add an active bank account first.'), 'info'); return; }
        await post(c.url(`/payroll/payouts/${buttonEl.dataset.id}/paid`), {bank_account_id: d.querySelector('[name="bank_account_id"]').value});
        batches = await refresh(); d.querySelector('[data-payout-list]').innerHTML = renderBatches(batches); bindPayoutActions();
        d.querySelector('[data-payout-summary]').innerHTML = renderEmployeeSummary(await refreshSummary());
      });
      d.querySelectorAll('[data-action="cancelPayout"]').forEach((buttonEl) => buttonEl.onclick = async () => {
        await post(c.url(`/payroll/payouts/${buttonEl.dataset.id}/cancel`));
        batches = await refresh(); d.querySelector('[data-payout-list]').innerHTML = renderBatches(batches); bindPayoutActions();
        d.querySelector('[data-payout-summary]').innerHTML = renderEmployeeSummary(await refreshSummary());
      });
    };
    bindPayoutActions();
  }
  function payrollPayoutSummaryDialog(summary) {
    dialog('Payout summary', table(['Period', 'Net', 'Paid', 'Pending', 'Unpaid'], summary.map((item) => row([
      td(esc(item.period)), cash(item.net, 'EUR'), cash(item.paid, 'EUR'), cash(item.pending, 'EUR'), cash(item.unpaid, 'EUR'),
    ]))));
  }
  async function paydaySettingsDialog(c) {
    const settings = await api(c.url('/payroll/payday-settings'));
    const latest = settings.rules.at(-1) || {};
    const history = settings.rules.length ? `<ul>${settings.rules.map((r) => `<li>${esc(r.start_date)}: ${tr(r.rule)}${r.day ? ` ${r.day}` : ''}</li>`).join('')}</ul>` : `<p class="muted">${tr('No payday rules have been saved.')}</p>`;
    const d = dialog('Payday settings', form(
      `<div class="full-width"><h3>${tr('Palgaarvestuse algus')}</h3>${history}</div>` +
      field('Palgaarvestuse algus', 'start_date', settings.payroll_start_date || '', 'date') +
      select('Organisation language', 'language', [['en', 'English'], ['et', 'Eesti'], ['lv', 'Latviešu'], ['lt', 'Lietuvių']], settings.language || 'en') +
      field('Rule effective from', 'rule_start_date', latest.start_date || new Date().toISOString().slice(0, 10), 'date', 'required') +
      select('Payday rule', 'rule', [['next_month_day', tr('Järgmisel kuul')], ['current_month_day', tr('Jooksval kuul')], ['next_month_first_working_day', tr('Järgmise kuu esimesel tööpäeval')]], latest.rule || 'next_month_day') +
      field('Payday day', 'day', latest.day || '10', 'number', 'min="1" max="31"')
    ));
    const ruleSelect = d.querySelector('[name="rule"]'), dayInput = d.querySelector('[name="day"]');
    const updateDay = () => { dayInput.disabled = ruleSelect.value === 'next_month_first_working_day'; dayInput.required = !dayInput.disabled; };
    ruleSelect.addEventListener('change', updateDay); updateDay();
    if (!canEditMappings()) {
      d.querySelectorAll('input,select,button[type="submit"]').forEach((control) => control.disabled = true);
    }
    bindForm(d, async (data) => {
      data.start_date = data.start_date || null;
      data.day = data.rule === 'next_month_first_working_day' ? null : Number(data.day);
      await post(c.url('/payroll/payday-settings'), data, 'PUT');
      await saved(d);
    });
  }
  function payrollItemDialog(c, run, item, types) {
    const d = dialog("Edit draft pay", form(
      `<p class="full-width"><strong>${esc(item.employee_name)}</strong> · ${esc(run.period)}</p>` +
      (item.pay_basis === "hourly" ? field("Hours worked", "hours", item.hours, "number", 'required min="0.01" max="744" step="0.01"') : `<p class="full-width">${tr("Base gross salary")}: ${esc(money(item.gross_salary, "EUR"))}</p>`) +
      `<div class="full-width"><h3>${tr("Payment components")}</h3><p class="muted">${tr("Levy flags apply to income lines. Deduction lines reduce net pay.")}</p><p class="muted">${tr("Use an income component to adjust gross pay. Negative income amounts reduce gross pay.")}</p><div class="payment-lines"></div>${button("Add payment line", "addPayment")}</div>`, "Save draft pay",
    ));
    const container = d.querySelector('.payment-lines');
    const add = (line) => {
      if (!types.length) { toast(t("Add a payment type first."), "info"); return; }
      const value = line || {...types[0], type_id: types[0].id};
      const el = document.createElement('fieldset'); el.className = 'payment-line';
      const availableTypes = types.filter((x) => x.active || x.id === value.type_id);
      el.innerHTML = `<legend>${tr("Payment line")}</legend><div class="form-grid">${select("Payment type", "type_id", availableTypes.map((x) => [x.id, t(x.name)]), value.type_id)}${field("Amount", "amount", value.amount || "", "number", 'required step="0.01"')}${select("Direction", "direction", [["income", t("Income")], ["deduction", t("Deduction")]], value.direction)}${field("Name", "name", value.name, "text", 'required maxlength="180"')}<div class="full-width component-flags">${componentFlagFields(value)}</div></div>${button("Remove payment line", "removePayment")}`;
      container.append(el);
      const direction = el.querySelector('[name="direction"]');
      const liability = document.createElement('div');
      liability.innerHTML = select("Deduction liability", "liability_role", [["PAYROLL_DEDUCTION", t("Other deduction liability")], ["PAYROLL_BAILIFF", t("Bailiff withholding liability")]], value.liability_role);
      el.querySelector('.form-grid').append(liability.firstElementChild);
      el.querySelector('[name="type_id"]').onchange = (e) => {
        const type = types.find((x) => x.id === e.target.value);
        el.querySelector('[name="name"]').value = type.name;
        direction.value = type.direction;
        el.querySelector('[name="liability_role"]').value = type.liability_role;
        componentFlags.forEach(([key]) => el.querySelector(`[name="${key}"]`).checked = type[key]);
      };
      el.querySelector('[data-action="removePayment"]').onclick = () => el.remove();
    };
    (item.components || []).forEach(add);
    d.querySelector('[data-action="addPayment"]').onclick = () => add();
    bindForm(d, async () => {
      const components = [...container.children].map((el) => {
        const value = {};
        for (const key of ['type_id', 'name', 'amount', 'direction', 'liability_role']) value[key] = el.querySelector(`[name="${key}"]`).value;
        for (const [key] of componentFlags) value[key] = el.querySelector(`[name="${key}"]`).checked;
        return value;
      });
      const data = {components};
      if (item.pay_basis === 'hourly') data.hours = d.querySelector('[name="hours"]').value;
      await post(c.url(`/pay-runs/${run.id}/items/${item.id}`), data, 'PATCH');
      await saved(d);
    });
  }
  function componentSummary(item) {
    return (item.components || []).map((line) => `<small class="component-summary">${esc(t(line.name))}: ${esc(money(line.amount, 'EUR'))} · ${tr(line.direction === 'income' ? 'Income' : 'Deduction')}<br>${esc(componentFlags.filter(([key]) => line[key]).map(([, label]) => t(label)).join(', ') || t('No levies'))}</small>`).join('');
  }
  function tsdPreparationDialog(c, run, preparation) {
    const reviewed = preparation.status === "Completed",
      base = c.url(`/pay-runs/${run.id}/tsd/${preparation.id}`),
      d = dialog(
        "TSD preparation for accountant",
        `<div class="notice" role="status">${tr("NOT live-verified against e-MTA. Review the payment records before manual upload.")} ${tr("Direct e-MTA submission is disabled.")}</div><dl class="detail-grid"><div><dt>${tr("Payment date")}</dt><dd>${esc(preparation.payment_date)}</dd></div><div><dt>${tr("Filing deadline")}</dt><dd>${esc(preparation.filing_deadline)}</dd></div><div><dt>${tr("Status")}</dt><dd>${pill(preparation.status)}</dd></div></dl>${table(
          ["Employee", "Annex", ["Gross"], ["Income tax"], ["Social tax"], ["Net"]],
          preparation.records.map((record) =>
            row([
              td(`<strong>${esc(record.recipient_name)}</strong><small>${esc(record.recipient_personal_id)}</small>`),
              td(esc(record.annex), "numeric"),
              cash(record.gross_amount, "EUR"),
              cash(record.income_tax, "EUR"),
              cash(record.social_tax, "EUR"),
              cash(record.net_amount, "EUR"),
            ]),
          ),
        )}<div class="dialog-actions">${
          reviewed
            ? link("TSD XBRL GL XML", `/api${base}/export.xbrl.xml`) +
              link("TSD CSV (through 2027)", `/api${base}/export.csv`)
            : button("Mark TSD reviewed", "tsd_confirm_review", true)
        }</div>`,
      );
    bindActions(d, {
      tsd_confirm_review: () =>
        confirmAction(
          "Mark TSD reviewed",
          tr(
            "Confirm that you reviewed the per-payment records. This unlocks file downloads; it does not submit anything.",
          ),
          async () => {
            await post(`${base}/review`);
            closeDialog(d);
            toast(t("TSD preparation reviewed"));
            await render();
          },
        ),
    });
  }
  function renderRun(r, c, providers = []) {
    const draft = String(r.status).toLowerCase() === "draft",
      items = r.items || [],
      preparation = r.tsd_preparation,
      tsdActions = preparation
        ? preparation.status === "Completed"
          ? `${pill("Reviewed")}${link("TSD XBRL GL XML", `/api${c.url(`/pay-runs/${r.id}/tsd/${preparation.id}/export.xbrl.xml`)}`)}${link("TSD CSV (through 2027)", `/api${c.url(`/pay-runs/${r.id}/tsd/${preparation.id}/export.csv`)}`)}`
          : `${pill("Review Required")}${button("Review TSD preparation", "tsd_review", false, `data-id="${r.id}" data-preparation-id="${preparation.id}"`)}`
        : button("Prepare TSD", "tsd_prepare", false, `data-id="${r.id}"`);
    return `${row([
      td(esc(r.period), "numeric"),
      td(pill(r.status)),
      cash(r.total_gross ?? r.gross_total ?? r.gross, "EUR"),
      cash(r.total_net ?? r.net_total ?? r.net, "EUR"),
      cash(r.total_employer_cost ?? r.employer_cost, "EUR"),
      td(
        (draft
          ? button("Delete draft", "delete", false, `data-id="${r.id}"`) +
              button("Approve & post", "approve", true, `data-id="${r.id}"`)
          : button("Payroll payouts", "managePayouts", false, `data-id="${r.id}"`) + link(
              "Payslips PDF",
              `/api${c.url(`/pay-runs/${r.id}/payslips.pdf`)}`,
            ) + tsdActions) +
          link(
            "Export workbook",
            `/api${c.url(`/pay-runs/${r.id}/workbook.xlsx`)}`,
          ),
      ),
    ])}<tr class="run-detail"><td colspan="6"><details ${draft ? "open" : ""}><summary>${tr("Employee breakdown")} (${num(items.length)})</summary>${table(
      [
        "Employee",
        ["Gross"],
        ["Income tax"],
        ["Pension"],
        ["Net"],
        ["Social tax"],
        ["Employer cost"],
        "Actions",
      ],
      items.map((x, i) =>
        row([
          td(
            `${esc(x.employee_name || x.name || x.employee?.name)}${hoursNote(x)}${partTime(x)}${componentSummary(x)}`,
          ),
          cash(x.gross ?? x.gross_salary, "EUR"),
          cash(x.income_tax, "EUR"),
          cash(x.funded_pension ?? x.employee_pension ?? x.pension, "EUR"),
          cash(x.net_salary ?? x.net, "EUR"),
          td(
            `${esc(money(x.social_tax, "EUR"))}${Number(x.social_tax_minimum_topup) > 0 ? `<small>${tr("Social tax minimum top-up")}: ${esc(money(x.social_tax_minimum_topup, "EUR"))}</small>` : ""}`,
            "numeric",
          ),
          cash(x.employer_cost, "EUR"),
          td(
            draft
              ? button("Edit draft pay", "editRunItem", false, `data-run="${esc(r.id)}" data-id="${esc(x.id)}"`)
              : link(
                  "Payslip",
                  `/api${c.url(`/pay-runs/${r.id}/payslips.pdf`)}#page=${i + 1}`,
                  `aria-label="${esc(t('Payslip: {name}').replace('{name}', x.employee_name || x.name || x.employee?.name || ''))}"`,
                ),
          ),
        ]),
      ),
    )}</details>${r.status === "Approved" ? `<section class="section"><div class="section-head"><h3>${tr("Journal pushes")}</h3><div class="integration-actions">${providers.map((entry) => button("Prepare push", "preparePush", false, `data-id="${esc(r.id)}" data-provider="${esc(entry.provider)}" ${canReviewPush() ? "" : "disabled"}`) + `<span>${esc(entry.provider)}</span>`).join("")}</div></div><p class="muted">${tr("Review the journal and confirmed account mappings before sending.")}</p>${pushTable(r.pushes || [])}</section>` : ""}</td></tr>`;
  }
  window.addEventListener("hashchange", render);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const dialogs = document.querySelectorAll(".dialog");
      if (dialogs.length) closeDialog(dialogs[dialogs.length - 1]);
      document.getElementById("org-menu").hidden = true;
      document
        .getElementById("org-trigger")
        .setAttribute("aria-expanded", "false");
      app.classList.remove("menu-open");
    }
  });
  document.getElementById("menu-toggle").innerHTML = icon("menu");
  document.getElementById("menu-toggle").onclick = () =>
    app.classList.toggle("menu-open");
  document.getElementById("org-trigger").onclick = (e) => {
    e.stopPropagation();
    const menu = document.getElementById("org-menu");
    menu.style.maxHeight =
      Math.max(60, e.currentTarget.getBoundingClientRect().top - 12) + "px";
    menu.hidden = !menu.hidden;
    e.currentTarget.setAttribute("aria-expanded", String(!menu.hidden));
  };
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".org-switcher")) {
      document.getElementById("org-menu").hidden = true;
      document
        .getElementById("org-trigger")
        .setAttribute("aria-expanded", "false");
    }
  });
  document.querySelectorAll(".app-nav").forEach((a) =>
    a.insertAdjacentHTML("afterbegin", icon(NAV_ICONS[a.dataset.view])),
  );
  document.querySelectorAll(".app-side-link[data-icon]").forEach((a) =>
    a.insertAdjacentHTML("afterbegin", icon(a.dataset.icon)),
  );
  document.querySelectorAll(".app-nav-list > div").forEach((group) => {
    const hasVisibleItems = [...group.querySelectorAll(".app-nav")].some(
      (a) => !a.hidden && getComputedStyle(a).display !== "none",
    );
    group.querySelector(".nav-group").hidden = !hasVisibleItems;
  });
  boot().catch((e) => {
    toast(e.message, "error");
    content.innerHTML = page(
      t("Unable to load this view"),
      e.message,
      button("Try again", "retry"),
    );
    bindActions(content, { retry: boot });
  });
})();
