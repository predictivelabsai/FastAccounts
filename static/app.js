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
    tr = (k) => esc(t(k));
  let csrf = "",
    organisations = [],
    org = null,
    generation = 0,
    reportTab = "trial-balance",
    invoiceFilter = "All",
    contactFilter = "All";
  const payrollSupported = (organisation) =>
    organisation?.country_code === "EE" && organisation?.base_currency === "EUR";
  const today = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  const money = (v, c) =>
    v == null
      ? "—"
      : new Intl.NumberFormat(lang === "et" ? "et-EE" : "en-GB", {
          style: "currency",
          currency: c || org?.base_currency || "EUR",
        }).format(Number(v));
  const date = (v) =>
    v
      ? new Intl.DateTimeFormat(lang === "et" ? "et-EE" : "en-GB").format(
          new Date(String(v).slice(0, 10) + "T12:00:00"),
        )
      : "—";
  const num = (v) => new Intl.NumberFormat(lang).format(Number(v || 0)),
    path = (s) => `/organisations/${encodeURIComponent(org.id)}${s}`;
  const icon = (name = "document") => {
    const p = {
      document: "M7 3h7l4 4v14H7z M14 3v5h5 M10 12h5 M10 16h5",
      home: "M3 10l9-7 9 7 M5 9v12h14V9 M9 21v-8h6v8",
      bank: "M3 9h18L12 3z M5 12v6 M12 12v6 M19 12v6 M3 21h18",
      people:
        "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M18 8a3 3 0 0 1 0 6 M20 17a4 4 0 0 1 2 4",
      chart: "M4 3v18h17 M8 17v-5 M13 17V7 M18 17v-8",
      plus: "M12 5v14 M5 12h14",
      close: "M6 6l12 12 M6 18L18 6",
      menu: "M4 6h16 M4 12h16 M4 18h16",
    };
    return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${p[name] || p.document}"/></svg>`;
  };
  const button = (label, action, primary = false, attrs = "") =>
    `<button type="button" class="button${primary ? " primary" : ""}" data-action="${action}" ${attrs}>${tr(label)}</button>`;
  const link = (label, href) =>
    `<a class="button" href="${esc(href)}">${tr(label)}</a>`;
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
          Connected: "success",
          Disconnected: "warning",
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
    row = (cells) => `<tr>${cells.join("")}</tr>`;
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
      e.message = t(e.message);
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
      `<button type="button" role="menuitem" data-create-org>${icon("plus")}${tr("Create organisation")}</button>`;
    document
      .querySelectorAll("[data-org]")
      .forEach((b) => (b.onclick = () => switchOrg(b.dataset.org)));
    document.querySelector("[data-create-org]").onclick = () => {
      document.getElementById("org-menu").hidden = true;
      organisationDialog();
    };
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
    const ticket = ++generation,
      view = location.hash.slice(1) || "overview";
    app.classList.remove("menu-open");
    document.querySelectorAll(".app-nav").forEach((a) => {
      const disabled = a.dataset.view === "payroll" && !payrollSupported(org);
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
  function onboarding() {
    content.innerHTML = `<div class="onboarding"><section><div class="large-mark">F</div><h1>${tr("Every client. One clear workspace.")}</h1><p>${tr("Keep client books, bank reviews and payroll together.")}</p><ul><li>${tr("Separate books for every organisation")}</li><li>${tr("Clear approvals before anything posts")}</li><li>${tr("UK and Estonian accounting in one place")}</li></ul></section><section class="card"><h2>${tr("Create your first organisation")}</h2>${form(organisationFields(), "Create books")}</section></div>`;
    content.querySelector("[data-action=cancel]").remove();
    wireOrganisation(content, () => {});
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
  const views = {
    overview: async (c) => {
      const [invoices, bills, bank, runs, clients] = await Promise.all([
        api(c.url("/invoices")),
        api(c.url("/bills")),
        api(c.url("/bank-transactions")),
        c.payrollSupported ? optionalPayroll(c.url("/pay-runs")) : null,
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
            `<div class="kpis">${kpi("Receivables", money(outstanding(invoices, ["Issued", "Part Paid"])), "Open customer invoices")}${kpi("Payables", money(outstanding(bills, ["Approved", "Part Paid"])), "Approved supplier bills")}${kpi("Bank review", num(review.length), "Transactions awaiting review")}${kpi("Payroll this month", money(runs === null ? null : cost), !c.payrollSupported ? "Available for Estonian EUR books" : runs === null ? "Payroll is not available yet." : "Employer cost · draft and approved")}</div><section class="section"><div class="section-head"><h2>${tr("Client books")}</h2><span class="muted">${num(organisations.length)} ${tr("organisations")}</span></div><div class="client-strip">${clients.map(({ o, rows }) => `<button class="client-book ${o.id === c.oid ? "selected" : ""}" data-client="${esc(o.id)}"><span class="country-badge">${esc(o.country_code)}</span><strong>${esc(o.name)}</strong><small>${tr("Receivables")}</small><b>${esc(money(rows ? outstanding(rows, ["Issued", "Part Paid"]) : null, o.base_currency))}</b></button>`).join("")}</div></section><section class="card section"><div class="section-head"><h2>${tr("Revenue & cash")}</h2><span class="muted">${tr("Last six months")}</span></div>${chart(invoices, bank)}</section><div class="dashboard-lists"><section><div class="section-head"><h2>${tr("Recent invoices")}</h2><a href="#invoices">${tr("View all")}</a></div>${table(["Number", "Customer", "Date", "Status", ["Total"]], invoiceRows([...invoices].sort((a, b) => String(b.issue_date).localeCompare(a.issue_date)).slice(0, 5)), button("New invoice", "newInvoice"))}</section><section><div class="section-head"><h2>${tr("Ready for review")}</h2><a href="#banking">${tr("View all")}</a></div>${table(
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
      const rows = await api(c.url("/invoices"));
      if (
        !c.mount(
          page(
            t("Invoices"),
            t("From first draft to final payment."),
            button("New contact", "newContact") +
              button("New invoice", "newInvoice", true),
            `<div class="chips">${["All", "Draft", "Issued", "Overdue"].map((s) => `<button class="chip ${invoiceFilter === s ? "active" : ""}" data-filter="${s}">${tr(s)}</button>`).join("")}</div><div id="invoice-table"></div>`,
          ),
        )
      )
        return;
      const draw = () => {
        const filtered = rows.filter(
          (x) =>
            invoiceFilter === "All" ||
            (invoiceFilter === "Overdue"
              ? ["Issued", "Part Paid"].includes(x.status) &&
                x.due_date < today()
              : x.status === invoiceFilter),
        );
        document.getElementById("invoice-table").innerHTML = table(
          ["Number", "Customer", "Date", "Status", ["Paid / total"], "Actions"],
          filtered.map((x) =>
            row([
              td(esc(x.number || t("Draft"))),
              td(esc(x.contact_name)),
              td(date(x.issue_date), "numeric"),
              td(pill(x.status)),
              td(
                `${esc(money(x.paid_total || 0, x.currency))}<span class="muted"> / ${esc(money(x.total, x.currency))}</span>`,
                "numeric",
              ),
              td(
                x.status === "Draft"
                  ? button("Issue", "issue", false, `data-id="${esc(x.id)}"`)
                  : link("PDF", `/api${c.url(`/invoices/${x.id}.pdf`)}`) +
                      link("XML", `/api${c.url(`/invoices/${x.id}.xml`)}`),
              ),
            ]),
          ),
          button("New invoice", "newInvoice"),
        );
        bindActions(content, {
          newInvoice: () => documentDialog("invoice"),
          newContact: () => contactDialog("customer"),
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
      };
      draw();
      content.querySelectorAll("[data-filter]").forEach(
        (b) =>
          (b.onclick = () => {
            invoiceFilter = b.dataset.filter;
            content
              .querySelectorAll("[data-filter]")
              .forEach((x) => x.classList.toggle("active", x === b));
            draw();
          }),
      );
    },
    recurring: async (c) => {
      const [schedules, reminders, invoices] = await Promise.all([
        api(c.url("/invoice-schedules")),
        api(c.url("/reminders/due")),
        api(c.url("/invoices")),
      ]);
      const intervals = { weekly: "Weekly", monthly: "Monthly", quarterly: "Quarterly", custom_days: "Custom days" },
        stages = ["3 days before due", "7 days overdue", "14 days overdue"],
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
            td(x.auto_email ? `<span aria-label="${tr("Auto-email")}">✓</span>` : "—"),
            td(pill(x.active ? "Active" : "Paused")),
            td(button(x.active ? "Pause" : "Resume", "toggleSchedule", false, `data-id="${esc(x.id)}"`) +
              button("Run now", "runSchedule", false, `data-id="${esc(x.id)}" ${!x.active || x.next_run_date > today() ? "disabled" : ""}`) +
              button("History", "scheduleHistory", false, `data-id="${esc(x.id)}"`)),
          ]))
        )}</section><section class="section"><div class="section-head"><h2>${tr("Reminders due")}</h2></div>
        ${reminders.email_connected === false ? `<div class="notice" role="status">${tr(emailNotice)}</div>` : ""}
        ${items.length ? table(["Number", "Customer", "Due date", "Stage", "Status", "Skip"], items.map((x, index) => row([
          td(esc(x.number)), td(esc(x.contact_name)), td(date(x.due_date)),
          td(x.stage == null ? "—" : tr(stages[x.stage])),
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
              t("Not due yet — next run {date}").replace("{date}", date(schedule.next_run_date)));
            result.runs.filter((x) => x.status === "Failed").forEach((x) => toast(t(x.error_message || "Failed"), "error"));
            await render();
          } finally { b.disabled = false; }
        },
        scheduleHistory: async (b) => {
          const schedule = await api(c.url(`/invoice-schedules/${b.dataset.id}`));
          if (org?.id !== c.oid || location.hash !== "#recurring") return;
          dialog("History", table(["Date", "Number", "Status", "Error"], schedule.runs.map((x) => row([
            td(date(x.run_date)), td(esc(x.invoice_number || "—")), td(pill(x.status)), td(tr(x.error_message || "—")),
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
      const rows = await api(c.url("/bills"));
      if (
        !c.mount(
          page(
            t("Bills"),
            t("Review supplier documents before posting."),
            button("New supplier", "supplier") +
              button("New bill", "bill", true),
            table(
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
                    x.status === "Draft"
                      ? button("Review", "review", false, `data-id="${x.id}"`)
                      : x.status === "In Review"
                        ? button(
                            "Approve",
                            "approve",
                            true,
                            `data-id="${x.id}"`,
                          )
                        : "",
                  ),
                ]),
              ),
              button("New bill", "bill"),
            ),
          ),
        )
      )
        return;
      bindActions(content, {
        bill: () => documentDialog("bill"),
        supplier: () => contactDialog("supplier"),
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
    },
    contacts: async (c) => {
      const rows = await api(c.url("/contacts"));
      if (
        !c.mount(
          page(
            t("Contacts"),
            t("Customers and suppliers for this organisation."),
            button("New customer", "customer", true) +
              button("New supplier", "supplier"),
            `<div class="chips">${["All", "customer", "supplier", "both"].map((x) => `<button class="chip ${contactFilter === x ? "active" : ""}" data-contact-filter="${x}">${tr(x)}</button>`).join("")}</div><div id="contacts-table"></div>`,
          ),
        )
      )
        return;
      const draw = () => {
        document.getElementById("contacts-table").innerHTML = table(
          ["Name", "Type", "Email", "Country", "VAT number"],
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
                td(esc(x.email || "—")),
                td(esc(x.country_code)),
                td(esc(x.vat_no || "—")),
              ]),
            ),
          button("New customer", "customer"),
        );
        bindActions(content, {
          customer: () => contactDialog("customer"),
          supplier: () => contactDialog("supplier"),
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
              button("Import statement", "import", true),
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
    accounting: async (c) => {
      if (
        !c.mount(
          page(
            t("Accounting"),
            t("Reports from your posted ledger."),
            button("Print / save PDF", "print"),
            `<div class="tabs" role="tablist">${Object.entries(reportNames)
              .map(
                ([key, label]) =>
                  `<button role="tab" aria-selected="${reportTab === key}" class="tab ${reportTab === key ? "active" : ""}" data-report="${key}">${tr(label)}</button>`,
              )
              .join(
                "",
              )}</div><form id="report-dates" class="date-range"><label id="report-start-label">${tr("From")}<input type="date" name="start" required></label><label><span id="report-end-label">${tr("To")}</span><input type="date" name="end" required></label><button class="button primary">${tr("Apply")}</button></form><div id="report-result" class="report-result"></div>`,
          ),
        )
      )
        return;
      bindActions(content, { print: () => window.print() });
      let request = 0;
      const f = document.getElementById("report-dates"),
        asAt = () =>
          ["balance-sheet", "receivables-aging", "payables-aging"].includes(
            reportTab,
          );
      const defaults = () => {
        f.elements.start.value = today().slice(0, 4) + "-01-01";
        f.elements.end.value = today();
        document.getElementById("report-start-label").hidden = asAt();
        document.getElementById("report-end-label").textContent = t(
          asAt() ? "As at" : "To",
        );
      };
      const load = async () => {
        const ticket = ++request;
        if (f.elements.start.value > f.elements.end.value && !asAt()) {
          toast(t("End date must follow start date."), "error");
          return;
        }
        const result = document.getElementById("report-result");
        result.innerHTML = skeleton();
        const tab = reportTab;
        try {
          const q = asAt()
            ? `as_at=${f.elements.end.value}`
            : `start=${f.elements.start.value}&end=${f.elements.end.value}`;
          const data = await api(c.url(`/reports/${tab}?${q}`));
          if (ticket !== request || !result.isConnected) return;
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
        load();
      };
      content.querySelectorAll("[data-report]").forEach(
        (b) =>
          (b.onclick = () => {
            reportTab = b.dataset.report;
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
            )}</section>`,
          ),
        )
      )
        return;
      bindActions(content, {
        prepare: () => taxDialog(false),
        vd: () => taxDialog(true),
      });
    },
    payroll: async (c) => {
      if (!c.payrollSupported) {
        c.mount(page(t("Payroll"), t("People, payslips and postings for this client."), "",
          `<div class="notice" role="status">${tr("Payroll is available only for Estonian organisations with EUR books. Switch to an Estonian EUR organisation to manage payroll.")}</div>`));
        return;
      }
      const [employees, runs] = await Promise.all([
        optionalPayroll(c.url("/employees")),
        optionalPayroll(c.url("/pay-runs")),
      ]);
      const unavailable = employees === null || runs === null;
      if (
        !c.mount(
          page(
            t("Payroll"),
            t("People, payslips and postings for this client."),
            button("Add employee", "employee") +
              button("Run payroll for month", "run", true),
            `${unavailable ? `<div class="notice">${tr("Payroll is not available yet.")}</div>` : ""}<section class="section"><div class="section-head"><h2>${tr("Employees")}</h2><span class="muted">${num(employees?.length)} ${tr("employees")}</span></div>${table(
              [
                "Name",
                ["Gross salary"],
                ["Pension %"],
                "Tax-free minimum",
                "Status",
                "Actions",
              ],
              (employees || []).map((x) =>
                row([
                  td(
                    `<strong>${esc(x.name)}</strong>${x.board_member ? `<small>${pill("Board member")}</small>` : ""}`,
                  ),
                  cash(x.gross_salary, "EUR"),
                  td(num(x.funded_pension_percent) + "%", "numeric"),
                  td(tr(x.apply_tax_free_minimum ? "Yes" : "No")),
                  td(pill(x.active ? "Active" : "Inactive")),
                  td(button("Edit", "edit", false, `data-id="${x.id}"`)),
                ]),
              ),
              button("Add employee", "employee"),
            )}</section><section class="section"><h2>${tr("Pay runs")}</h2>${
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
                    runs.map((r) => renderRun(r, c)),
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
        employee: () => employeeDialog(),
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
      });
    },
    integrations: async (c) => {
      const [rows, email] = await Promise.all([api("/integrations"), api("/email-status")]);
      if (
        !c.mount(
          page(
            t("Integrations"),
            t("Connect your accounting workflow."),
            link("Public catalogue", "/integrations"),
            `<section class="card section"><div class="section-head"><h2>${tr("Email delivery")}</h2>${pill(email.connected ? "Connected" : "Disconnected")}</div><p>Postmark${email.from_email ? ` · ${esc(email.from_email)}` : ""}</p><p class="muted">${tr("Connect email delivery by setting POSTMARK_API_TOKEN and FROM_EMAIL in the deployment environment (.env).")}</p></section><div class="integration-list">${rows
              .map((x) => {
                const copy = catalog.integrations?.items?.[x.key] || {};
                return `<article class="card integration-row"><img src="${esc(x.logo)}" alt="${esc(copy.name || x.name)}"><div><h2>${esc(copy.name || x.name)}</h2>${pill(x.status)}<p>${esc(copy.description || x.description)}</p><small class="muted">${esc(copy.direction || x.direction || "")}</small></div></article>`;
              })
              .join("")}</div>`,
          ),
        )
      )
        return;
    },
  };
  const reportNames = {
    "trial-balance": "Trial balance",
    "profit-and-loss": "Profit & loss",
    "balance-sheet": "Balance sheet",
    "general-ledger": "General ledger",
    "receivables-aging": "Receivables aging",
    "payables-aging": "Payables aging",
    "cash-summary": "Cash summary",
  };
  function renderReport(tab, data) {
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
  async function documentDialog(kind) {
    const base = path("");
    const [contacts, accounts, taxes] = await Promise.all([
      api(base + "/contacts"),
      api(base + "/accounts"),
      api(base + "/tax-codes"),
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
    const d = dialog(
      invoice ? "New invoice" : "New bill",
      form(
        select(
          invoice ? "Customer" : "Supplier",
          "contact_id",
          choices.map((x) => [x.id, x.name]),
        ) +
          (invoice
            ? field("Issue date", "issue_date", today(), "date", "required")
            : field(
                "Supplier number",
                "supplier_number",
                "",
                "text",
                "required",
              ) +
              field("Bill date", "bill_date", today(), "date", "required")) +
          field("Due date", "due_date", today(), "date", "required") +
          field("Description", "description", "", "text", "required") +
          field(
            "Quantity",
            "quantity",
            1,
            "number",
            'required min="0.0001" step="0.0001"',
          ) +
          field(
            "Unit price",
            "unit_price",
            "",
            "number",
            'required min="0" step="0.01"',
          ) +
          select(
            invoice ? "Income account" : "Expense account",
            "account_id",
            accounts
              .filter(
                (x) => x.account_type === (invoice ? "Income" : "Expense"),
              )
              .map((x) => [x.id, `${x.code} ${x.name}`]),
          ) +
          select(
            "Tax code",
            "tax_code_id",
            taxes.map((x) => [x.id, `${x.code} · ${num(x.rate)}%`]),
            taxes.find((x) => x.kind === "standard")?.id,
          ),
        "Create draft",
      ),
    );
    bindForm(d, async (data) => {
      const line = {};
      [
        "description",
        "quantity",
        "unit_price",
        "account_id",
        "tax_code_id",
      ].forEach((k) => {
        line[k] = data[k];
        delete data[k];
      });
      data.lines = [line];
      await post(base + (invoice ? "/invoices" : "/bills"), data);
      await saved(d);
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
          field("IBAN (stored masked)", "iban"),
        "Add account",
      ),
    );
    bindForm(d, async (data) => {
      await post(url, data);
      await saved(d);
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
  function employeeDialog(employee) {
    const url = path("/employees") + (employee ? `/${employee.id}` : "");
    const e = employee || {
      active: true,
      apply_tax_free_minimum: true,
      funded_pension_percent: 2,
    };
    const d = dialog(
      employee ? "Edit employee" : "Add employee",
      form(
        field("Name", "name", e.name || "", "text", "required") +
          field("Email", "email", e.email || "", "email") +
          field("Personal ID", "personal_id", e.personal_id || "") +
          field(
            "Gross salary",
            "gross_salary",
            e.gross_salary ?? "",
            "number",
            'required min="0.01" step="0.01"',
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
          check(
            "Apply tax-free minimum",
            "apply_tax_free_minimum",
            e.apply_tax_free_minimum,
          ) +
          check("Board member", "board_member", e.board_member) +
          check("Active", "active", e.active),
      ),
    );
    const employeeForm = d.querySelector("form");
    const updatePension = () => {
      const pension = employeeForm.elements.funded_pension_percent;
      const board = employeeForm.elements.board_member.checked;
      pension.querySelector('option[value="0"]').disabled = !board;
      if (!board && pension.value === "0") pension.value = "2";
    };
    employeeForm.elements.board_member.onchange = updatePension;
    updatePension();
    bindForm(d, async (data, f) => {
      for (const k of ["apply_tax_free_minimum", "board_member", "active"])
        data[k] = f.elements[k].checked;
      await post(url, data, employee ? "PATCH" : "POST");
      await saved(d);
    });
  }
  function payrollWizard(employees) {
    const url = path("/pay-runs"),
      active = employees.filter((x) => x.active);
    if (!active.length) {
      toast(t("Add an active employee before running payroll."), "info");
      return employeeDialog();
    }
    const d = dialog(
      "Run payroll for month",
      form(
        field("Month", "period", today().slice(0, 7), "month", "required") +
          `<div class="full-width"><h3>${tr("Included employees")}</h3>${table(
            ["Name", ["Gross salary"]],
            active.map((x) =>
              row([td(esc(x.name)), cash(x.gross_salary, "EUR")]),
            ),
          )}<p class="muted">${tr("Employee details are frozen when the draft is created. Review before approval.")}</p></div>`,
        "Create draft",
      ),
    );
    bindForm(d, async (data) => {
      confirmAction(
        "Create payroll draft",
        `${tr("Month")}: ${esc(data.period)}<br>${num(active.length)} ${tr("employees")}`,
        async () => {
          await post(url, { period: data.period });
          await saved(d);
        },
      );
    });
  }
  function renderRun(r, c) {
    const draft = String(r.status).toLowerCase() === "draft",
      items = r.items || [];
    return `${row([
      td(esc(r.period), "numeric"),
      td(pill(r.status)),
      cash(r.total_gross ?? r.gross_total ?? r.gross, "EUR"),
      cash(r.total_net ?? r.net_total ?? r.net, "EUR"),
      cash(r.total_employer_cost ?? r.employer_cost, "EUR"),
      td(
        draft
          ? button("Delete draft", "delete", false, `data-id="${r.id}"`) +
              button("Approve & post", "approve", true, `data-id="${r.id}"`)
          : link(
              "Payslips PDF",
              `/api${c.url(`/pay-runs/${r.id}/payslips.pdf`)}`,
            ),
      ),
    ])}<tr class="run-detail"><td colspan="6"><details ${draft ? "open" : ""}><summary>${tr("Employee breakdown")} (${num(items.length)})</summary>${table(
      [
        "Employee",
        ["Gross"],
        ["Income tax"],
        ["Pension"],
        ["Net"],
        ["Employer cost"],
        "Actions",
      ],
      items.map((x, i) =>
        row([
          td(esc(x.employee_name || x.name || x.employee?.name)),
          cash(x.gross_salary ?? x.gross, "EUR"),
          cash(x.income_tax, "EUR"),
          cash(x.funded_pension ?? x.employee_pension ?? x.pension, "EUR"),
          cash(x.net_salary ?? x.net, "EUR"),
          cash(x.employer_cost, "EUR"),
          td(
            draft
              ? ""
              : link(
                  "Payslip",
                  `/api${c.url(`/pay-runs/${r.id}/payslips.pdf`)}#page=${i + 1}`,
                ),
          ),
        ]),
      ),
    )}</details></td></tr>`;
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
    a.insertAdjacentHTML(
      "afterbegin",
      icon(
        {
          overview: "home",
          banking: "bank",
          contacts: "people",
          payroll: "people",
          recurring: "document",
          accounting: "chart",
        }[a.dataset.view],
      ),
    ),
  );
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
