// Spectre assistant UI. Plain ES module: live events over SSE, everything else over JSON.

import { Orb } from "./orb.js";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v === null || v === undefined) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
}
async function api(method, path, body) {
  const opts = { method, credentials: "same-origin", headers: {} };
  if (method !== "GET") opts.headers["X-Spectre"] = "1";
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const res = await fetch(`/api/assistant/${path}`, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}
function toast(msg, kind = "ok", ms = 4200) {
  const n = h("div", { class: "toast", "data-kind": kind, role: kind === "error" ? "alert" : "status" }, msg);
  $("#toasts").append(n); setTimeout(() => n.remove(), ms);
}
const time = (iso) => { try { return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };
const date = (iso) => { try { return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }); } catch { return iso; } };

const STATES = {
  off: ["Voix coupée", "Écris ci-dessous, ou relance Spectre avec la voix activée pour lui parler."],
  sleeping: ["En veille", ""],
  listening: ["J'écoute…", ""],
  thinking: ["Je réfléchis…", ""],
  speaking: ["Je parle", ""],
};
let voiceAvailable = false;
// Opened from another device (the phone, through Tailscale): the microphone button records on
// this device instead of making the PC listen, and Spectre's answer is played here.
const REMOTE = !["127.0.0.1", "localhost", "::1", "[::1]"].includes(location.hostname);
const SLEEP_HINT = REMOTE ? "Touche le micro pour me parler." : "Dis « Spectre » pour me parler.";

const orb = new Orb($("#orb"));
const fadeTimers = {};
function caption(id, text, ms) {
  const el = $(id);
  clearTimeout(fadeTimers[id]);
  el.classList.remove("fading");
  el.textContent = text;
  if (ms) fadeTimers[id] = setTimeout(() => el.classList.add("fading"), ms);
}
function setLevel(v) {
  orb.setLevel(v);
  $("#signal-fill").style.transform = `scaleX(${v.toFixed(3)})`;
  $("#signal-value").textContent = `${(v * 100).toFixed(1).replace(".", ",")} %`;
}

function setState(state, detail = "") {
  if (state === "heard") { $("#presence-detail").textContent = `« ${detail} »`; caption("#heard", detail, 9000); return; }
  document.body.dataset.voice = state;
  orb.setState(state);
  const [label, base] = STATES[state] || [state, ""];
  const hint = state === "sleeping" ? SLEEP_HINT : base;
  $("#presence-state").textContent = label;
  $("#orb-state").textContent = state === "sleeping" && voiceAvailable ? (REMOTE ? "En veille — touche le micro" : "En veille — dis « Spectre »") : label;
  if (state === "listening") caption("#heard", "", 0);
  if (state !== "listening" && state !== "speaking") setLevel(0);
  $("#presence-detail").textContent = state === "speaking" ? detail : (detail || (state === "sleeping" && !voiceAvailable ? STATES.off[1] : hint));
  document.title = state === "thinking" ? "● Spectre réfléchit" : "Spectre · Assistant";
}

/* ---- transcript ---- */
function addLine(role, text, error = false) {
  const list = $("#transcript");
  $(".empty-note", list)?.remove();
  list.append(h("li", { "data-role": role, "data-error": error ? "true" : null },
    h("span", { class: "who" }, role === "spectre" ? "Spectre" : "Toi"),
    h("span", { class: "what" }, text)));
  list.lastElementChild.scrollIntoView({ block: "nearest", behavior: "smooth" });
}
async function loadHistory() {
  const rows = await api("GET", "history");
  const list = $("#transcript");
  list.replaceChildren();
  if (!rows.length) list.append(h("li", { class: "empty-note" }, "Aucune conversation pour l'instant. Essaie : « Quelle heure est-il ? », « Retiens que je fais du vélo le dimanche », « Ouvre YouTube sur l'écran 2 »."));
  rows.forEach((r) => addLine(r.role, r.text));
}

/* ---- approvals ---- */
const LEVELS = ["lecture", "ouverture", "écriture", "destructif", "extérieur", "critique"];
function approvalCard(a) {
  let args = {};
  try { args = JSON.parse(a.args); } catch { /* raw */ }
  return h("article", { class: "card", "data-level": String(a.level) },
    h("h3", {}, a.tool.replaceAll("_", " ")),
    h("span", { class: "meta" }, `#${a.id} · ${LEVELS[a.level] || a.level} · ${a.category} · ${time(a.ts)}`),
    h("p", {}, a.reason),
    h("pre", {}, JSON.stringify(args, null, 2)),
    h("div", { class: "row" },
      h("button", { class: "btn btn-primary", type: "button", onclick: () => decide(a.id, true) }, h("span", {}, "Valider")),
      h("button", { class: "btn btn-danger", type: "button", onclick: () => decide(a.id, false) }, h("span", {}, "Refuser"))));
}
async function decide(id, ok) {
  try {
    const r = await api("POST", `approvals/${id}/${ok ? "approve" : "deny"}`, {});
    toast(ok ? `Fait : ${r.result}` : `Action #${id} refusée.`, ok ? "ok" : "warn");
  } catch (e) { toast(e.message, "error"); }
  loadApprovals(); loadStatus();
}
async function loadApprovals() {
  const rows = await api("GET", "approvals");
  const fill = (el) => el.replaceChildren(...(rows.length ? rows.map(approvalCard) : [h("p", { class: "empty-cards" }, "Rien à valider.")]));
  fill($("#approvals")); fill($("#approvals-full"));
  $("#count-approvals").textContent = rows.length || "";
}

/* ---- missions ---- */
const MSTATUS = { queued: "en file", running: "en cours", done: "terminée", failed: "échouée", cancelled: "arrêtée" };
async function loadMissions() {
  const rows = await api("GET", "missions");
  $("#count-missions").textContent = rows.filter((m) => m.status === "running" || m.status === "queued").length || "";
  $("#missions").replaceChildren(...(rows.length ? rows.map((m) => {
    let steps = []; try { steps = JSON.parse(m.steps); } catch { /* none */ }
    return h("article", { class: "card", "data-status": m.status },
      h("h3", {}, m.goal),
      h("span", { class: "meta" }, `#${m.id} · ${MSTATUS[m.status] || m.status} · ${date(m.updated_at)}`),
      steps.length ? h("p", {}, steps.map((s, i) => `${s.ok ? "✓" : "✗"} ${i + 1}. ${s.step}${s.name ? ` — ${s.name}` : ""}`).join("\n")) : null,
      m.error ? h("p", {}, `Erreur : ${m.error}`) : null,
      m.report ? h("details", {}, h("summary", {}, "Rapport"), h("pre", {}, m.report)) : null,
      m.status === "running" || m.status === "queued" ? missionControls(m) : null,
      m.changes && m.status !== "running" && m.status !== "queued" ? h("div", { class: "row" },
        h("button", { class: "btn btn-ghost", type: "button", onclick: () => rollback(m) }, h("span", {}, `Annuler ses ${m.changes} changement${m.changes > 1 ? "s" : ""} de fichiers`))) : null);
  }) : [h("p", { class: "empty-cards" }, "Aucune mission. Demande-en une à Spectre ou lance-la ici.")]));
}

function missionControls(m) {
  const input = h("input", { type: "text", maxlength: "2000", placeholder: "Une consigne en cours de route, ex. « concentre-toi sur la France »", "aria-label": "Consigne pour la mission" });
  const steer = async (e) => {
    e.preventDefault();
    if (!input.value.trim()) return;
    try { await api("POST", `missions/${m.id}/steer`, { message: input.value }); toast("Consigne transmise : la mission la lira avant sa prochaine étape.", "ok"); input.value = ""; }
    catch (err) { toast(err.message, "error"); }
  };
  const stop = async () => {
    try { toast((await api("POST", `missions/${m.id}/stop`, {})).result, "ok"); }
    catch (err) { toast(err.message, "error"); }
    loadMissions();
  };
  return h("form", { class: "mi-steer", onsubmit: steer }, input,
    h("button", { class: "btn", type: "submit" }, "Orienter"),
    h("button", { class: "btn btn-ghost", type: "button", onclick: stop }, h("span", {}, "Arrêter")));
}

async function rollback(m) {
  if (!confirm(`Ramener les fichiers de la mission #${m.id} à leur état d'avant ? Les versions remplacées restent dans la corbeille de Spectre.`)) return;
  try { toast((await api("POST", `missions/${m.id}/rollback`, {})).result, "ok", 8000); }
  catch (err) { toast(err.message, "error"); }
  loadMissions();
}

/* ---- learning: proposed skills, learned skills, search over past conversations ---- */
async function loadLearning() {
  const data = await api("GET", "learning");
  $("#count-learning").textContent = data.proposals.length || "";
  const decide = (p, decision) => async () => {
    try { await api("POST", `learning/proposals/${p.id}/${decision}`, {}); toast(decision === "approve" ? `Compétence « ${p.name} » apprise.` : "Proposition écartée.", "ok"); }
    catch (err) { toast(err.message, "error"); }
    loadLearning();
  };
  $("#proposals").replaceChildren(...(data.proposals.length ? data.proposals.map((p) => h("article", { class: "card", "data-status": "running" },
    h("h3", {}, p.name),
    h("span", { class: "meta" }, `${p.previous ? "mise à jour · " : ""}${p.source || "conversation"} · ${date(p.ts)}`),
    h("p", {}, p.description),
    h("details", {}, h("summary", {}, "Le guide proposé"), h("pre", {}, p.content)),
    p.previous ? h("details", {}, h("summary", {}, "La version actuelle"), h("pre", {}, p.previous)) : null,
    h("div", { class: "row" },
      h("button", { class: "btn btn-primary", type: "button", onclick: decide(p, "approve") }, h("span", {}, "Apprendre")),
      h("button", { class: "btn btn-ghost", type: "button", onclick: decide(p, "reject") }, h("span", {}, "Écarter"))))) : [h("p", { class: "empty-cards" }, "Rien à valider.")]));
  const act = (s, action) => async () => {
    try { await api("POST", `learning/skills/${encodeURIComponent(s.name)}/${action}`, {}); }
    catch (err) { toast(err.message, "error"); }
    loadLearning();
  };
  const skillCard = (s, archived) => h("article", { class: "card", "data-status": archived ? "done" : s.state === "obsolète" ? "failed" : "running" },
    h("h3", {}, s.name),
    h("span", { class: "meta" }, `${s.state}${s.pinned ? " · épinglée" : ""} · ${s.uses} usage${s.uses > 1 ? "s" : ""}${s.last_used ? ` · dernier : ${date(s.last_used)}` : ""}`),
    h("p", {}, s.description),
    h("div", { class: "row" }, ...(archived
      ? [h("button", { class: "btn", type: "button", onclick: act(s, "restore") }, h("span", {}, "Restaurer"))]
      : [h("button", { class: "btn", type: "button", onclick: act(s, s.pinned ? "unpin" : "pin") }, h("span", {}, s.pinned ? "Désépingler" : "Épingler")),
         h("button", { class: "btn btn-ghost", type: "button", onclick: act(s, "archive") }, h("span", {}, "Archiver"))])));
  $("#skills").replaceChildren(...(data.skills.length ? data.skills.map((s) => skillCard(s, false)) : [h("p", { class: "empty-cards" }, "Aucune compétence apprise pour l'instant.")]));
  $("#skills-archived").replaceChildren(...(data.archived.length ? data.archived.map((s) => skillCard(s, true)) : [h("p", { class: "empty-cards" }, "Aucune.")]));
}
$("#search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = e.target.elements.q.value.trim();
  if (!q) return;
  const rows = await api("GET", `search?q=${encodeURIComponent(q)}`);
  const who = { user: "toi", spectre: "Spectre", mission: "mission" };
  $("#search-results").replaceChildren(...(rows.length ? rows.map((r) => h("article", { class: "card" },
    h("span", { class: "meta" }, `${date(r.ts)} · ${who[r.source] || r.source}${r.kind === "mission" ? ` #${r.id}` : ""}`),
    h("p", {}, r.excerpt))) : [h("p", { class: "empty-cards" }, "Rien trouvé.")]));
});

/* ---- companies: org chart and task board ---- */
const TSTATUS = { todo: "À faire", doing: "En cours", blocked: "Bloquées", review: "À valider", done: "Faites", cancelled: "Annulées" };
let companyId = null;
try { companyId = Number(localStorage.getItem("spectre-company")) || null; } catch { /* private mode */ }
async function loadCompany() {
  const list = await api("GET", "company");
  const select = $("#company-select");
  if (list.length && !list.some((c) => c.id === companyId)) companyId = list[0].id;
  select.replaceChildren(...(list.length ? list.map((c) => h("option", { value: c.id, selected: c.id === companyId }, c.name)) : [h("option", { value: "" }, "Aucune entreprise")]));
  $("#company-body").hidden = !list.length;
  $("#company-autopilot-row").hidden = !list.length;
  if (!list.length) { $("#count-company").textContent = ""; return; }
  const data = await api("GET", `company/${companyId}`);
  $("#company-autopilot").checked = !!data.company.autopilot;
  const open = data.tasks.filter((t) => t.status === "review" || t.status === "blocked").length;
  $("#count-company").textContent = open || "";
  const options = (current) => [h("option", { value: "", selected: !current }, "Selon les réglages"),
    ...data.agents.map((a) => h("option", { value: a.key, selected: a.key === current }, a.name))];
  $("#company-posts").replaceChildren(...data.departments.map((d) => {
    const select = h("select", { "aria-label": `Agent du poste ${d.label}`, onchange: async (e) => {
      try { await api("POST", `company/${companyId}/post`, { department: d.key, agent: e.target.value }); toast(`${d.label} : ${e.target.selectedOptions[0].textContent}`, "ok"); }
      catch (err) { toast(err.message, "error"); loadCompany(); }
    } }, ...options(d.agent));
    return h("label", { class: "co-post", "data-dept": d.key }, h("span", { class: "label" }, d.label), select);
  }));
  const dept = $("#company-task-dept");
  if (!dept.options.length) dept.append(h("option", { value: "" }, "Département"), ...data.departments.map((d) => h("option", { value: d.key }, d.label)));
  $("#company-capacity").textContent = `${data.ready.length} prête${data.ready.length > 1 ? "s" : ""} · ${data.active.length}/${data.parallel} mission${data.parallel > 1 ? "s" : ""} en parallèle`;
  $("#company-start").disabled = !data.ready.length;
  const label = Object.fromEntries(data.departments.map((d) => [d.key, d.label]));
  const columns = ["todo", "doing", "review", "blocked", "done"].map((status) => {
    const tasks = data.tasks.filter((t) => t.status === status);
    return h("section", { class: "co-col", "data-status": status },
      h("h4", {}, TSTATUS[status], h("b", {}, tasks.length || "")),
      ...tasks.map((t) => taskCard(t, label, data.ready.includes(t.id))));
  });
  $("#company-board").replaceChildren(...columns);
  loadSaas().catch((err) => toast(err.message, "error"));
  loadDecisions().catch((err) => toast(err.message, "error"));
  api("GET", `costs?company=${companyId}`).then((c) => {
    const parts = c.calls ? [`Coût de l'IA sur 30 jours : ${c.cost_usd.toFixed(2).replace(".", ",")} $ (équivalent API), ${c.calls} appels`] : [];
    if (c.calls && c.mrr) parts.push(`soit ${String(c.cost_per_mrr).replace(".", ",")} % du MRR`);
    if (c.by_department && c.by_department.length) parts.push(`dont ${c.by_department.slice(0, 3).map((d) => `${d.key} ${d.cost.toFixed(2).replace(".", ",")} $`).join(", ")}`);
    $("#company-costs").textContent = parts.join(" · ");
  }).catch(() => {});
}
/* ---- SaaS dashboard: stat tiles (value, signed change over 7 days, 12-point trend) ---- */
const compact = (v) => Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(1).replace(".", ",")} M` : Math.abs(v) >= 1e4 ? `${(v / 1e3).toFixed(1).replace(".", ",")} k` : Number.isInteger(v) ? String(v) : v.toFixed(2).replace(".", ",");
function sparkline(values, label) {
  if (values.length < 2) return null;
  const w = 120, hgt = 32, pad = 4;
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const pts = values.map((v, i) => [pad + (i * (w - 2 * pad)) / (values.length - 1), hgt - pad - ((v - lo) * (hgt - 2 * pad)) / span]);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${hgt}`); svg.setAttribute("preserveAspectRatio", "xMinYMid meet"); svg.setAttribute("class", "sa-spark"); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${label} : tendance, de ${compact(values[0])} à ${compact(values[values.length - 1])}`);
  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", pts.map((p) => p.join(",")).join(" ")); line.setAttribute("class", "sa-line");
  const dot = document.createElementNS(ns, "circle");
  const [x, y] = pts[pts.length - 1];
  dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("r", "3"); dot.setAttribute("class", "sa-dot");
  const tip = document.createElementNS(ns, "title");
  tip.textContent = values.map(compact).join(" → ");
  svg.append(tip, line, dot);
  return svg;
}
function statTile(t) {
  let delta = null;
  if (t.delta !== null && t.delta !== 0) {
    const better = t.good === null || t.good === undefined ? "flat" : (t.delta > 0) === t.good ? "good" : "bad";
    delta = h("span", { class: `sa-delta ${better}` }, `${t.delta > 0 ? "▲ +" : "▼ −"}${compact(Math.abs(t.delta))} sur 7 j`);
  } else if (t.delta === 0) delta = h("span", { class: "sa-delta flat" }, "= sur 7 j");
  return h("article", { class: "sa-tile", title: t.metric },
    h("span", { class: "sa-label" }, t.label),
    h("span", { class: "sa-value" }, compact(t.value)),
    delta, sparkline(t.trend, t.label));
}
async function loadSaas() {
  const data = await api("GET", `company/${companyId}/saas`);
  const chips = [];
  if ("up" in data.status) chips.push(h("span", { class: `sa-chip ${data.status.up ? "good" : "bad"}` }, data.status.up ? "✓ Site en ligne" : "✗ Site hors ligne"));
  if ("ci_ok" in data.status) chips.push(h("span", { class: `sa-chip ${data.status.ci_ok ? "good" : "bad"}` }, data.status.ci_ok ? "✓ CI au vert" : "✗ CI en échec"));
  const broken = data.sources.filter((s) => s.last_error);
  if (broken.length) chips.push(h("span", { class: "sa-chip bad" }, `! ${broken.length} source${broken.length > 1 ? "s" : ""} en erreur`));
  $("#saas-status").replaceChildren(...chips);
  $("#saas-tiles").replaceChildren(...(data.tiles.length ? data.tiles.map(statTile) : [h("p", { class: "empty-cards" }, data.sources.length ? "Les premiers chiffres arrivent : la collecte est en cours." : "Aucun chiffre encore. Ouvre « Sources, alertes et rapport » pour brancher Stripe, Supabase ou ton site.")]));
  if (!data.sources.length) $("#saas-setup").open = true;
  const KIND = { uptime: "site", stripe: "Stripe", supabase: "Supabase", github: "GitHub", http_json: "API JSON", manual: "saisie" };
  $("#saas-sources").replaceChildren(...data.sources.map((s) => h("article", { class: "card", "data-status": s.last_error ? "failed" : "done" },
    h("h3", {}, s.name),
    h("span", { class: "meta" }, `${KIND[s.kind] || s.kind}${s.config.url ? ` · ${s.config.url}` : ""}${s.config.repo ? ` · ${s.config.repo}` : ""}${s.config.table ? ` · table ${s.config.table}` : ""} · ${s.last_check ? `relevé ${date(s.last_check)}` : "pas encore relevé"}${s.has_key ? " · clé enregistrée" : ""}`),
    s.last_error ? h("p", {}, `Erreur : ${s.last_error}`) : null,
    h("div", { class: "row" },
      h("button", { class: "btn", type: "button", onclick: async () => { try { const r = await api("POST", `saas/sources/${s.id}/check`, {}); toast(r.error ? `Erreur : ${r.error}` : `Relevé : ${Object.keys(r.metrics).length} chiffre(s).`, r.error ? "error" : "ok"); } catch (err) { toast(err.message, "error"); } loadSaas(); } }, h("span", {}, "Relever maintenant")),
      h("button", { class: "btn btn-ghost", type: "button", onclick: async () => { await api("POST", `saas/sources/${s.id}/delete`, {}); loadSaas(); } }, h("span", {}, "Supprimer"))))));
  $("#saas-alerts").replaceChildren(...data.alerts.map((a) => h("span", { class: `sa-rule${a.active ? " on" : ""}` },
    `${a.active ? "! " : ""}${a.label || a.metric} : ${a.metric} ${a.op} ${a.threshold}`,
    h("button", { class: "btn btn-ghost", type: "button", "aria-label": `Supprimer l'alerte ${a.label || a.metric}`, onclick: async () => { await api("POST", `saas/alerts/${a.id}/delete`, {}); loadSaas(); } }, "×"))));
}
function saasKindFields() {
  const kind = $("#saas-kind").value;
  document.querySelectorAll("#saas-source-form [data-for]").forEach((el) => { el.hidden = !el.dataset.for.split(" ").includes(kind); });
}
$("#saas-kind").addEventListener("change", saasKindFields);
saasKindFields();
$("#saas-source-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const kind = $("#saas-kind").value;
  const data = Object.fromEntries([...new FormData(e.target)].filter(([k]) => { const el = e.target.elements[k]; return !el.closest("[data-for]") || !el.closest("[data-for]").hidden; }));
  data.kind = kind;
  try { await api("POST", `company/${companyId}/saas/sources`, data); toast("Source ajoutée : premier relevé en cours.", "ok"); e.target.reset(); saasKindFields(); }
  catch (err) { toast(err.message, "error", 8000); }
  setTimeout(loadSaas, 2500);
});
$("#saas-alert-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try { toast((await api("POST", `company/${companyId}/saas/alerts`, { ...data, threshold: Number(data.threshold) })).result, "ok"); e.target.reset(); }
  catch (err) { toast(err.message, "error"); }
  loadSaas();
});
$("#saas-metric-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try { toast((await api("POST", `company/${companyId}/saas/metric`, { metric: data.metric, value: Number(data.value) })).result, "ok"); e.target.elements.value.value = ""; }
  catch (err) { toast(err.message, "error"); }
  loadSaas();
});
$("#saas-report").addEventListener("click", async () => {
  try { toast((await api("POST", `company/${companyId}/saas/report`, {})).result, "ok", 7000); }
  catch (err) { toast(err.message, "error", 7000); }
});

/* ---- board decisions and measured experiments ---- */
const DSTATUS = { deliberating: "en délibération", decided: "décidée", reviewing: "en réévaluation", reviewed: "réévaluée", failed: "échec" };
async function loadDecisions() {
  const data = await api("GET", `company/${companyId}/decisions`);
  $("#decisions").replaceChildren(...(data.decisions.length ? data.decisions.map((d) => h("article", { class: "card", "data-status": d.outcome === "ratée" ? "failed" : d.status === "reviewed" ? "done" : "running" },
    h("h3", {}, d.question),
    h("span", { class: "meta" }, `#${d.id} · ${DSTATUS[d.status] || d.status}${d.outcome ? ` · ${d.outcome}` : ""}${d.review_at && d.status === "decided" ? ` · réévaluation le ${date(d.review_at)}` : ""}`),
    d.decision ? h("p", {}, d.decision) : null,
    d.lesson ? h("p", { class: "meta" }, `${d.status === "failed" ? "Erreur" : "Leçon"} : ${d.lesson}`) : null,
    d.memo ? h("details", {}, h("summary", {}, "Note de décision"), h("pre", {}, d.memo)) : null,
    d.status === "decided" ? h("div", { class: "row" }, h("button", { class: "btn", type: "button", onclick: async () => { try { toast((await api("POST", `decisions/${d.id}/review`, {})).result, "ok"); } catch (err) { toast(err.message, "error"); } loadDecisions(); } }, h("span", {}, "Réévaluer maintenant"))) : null)) : [h("p", { class: "empty-cards" }, "Aucune décision au journal.")]));
  const metric = $("#experiment-metric");
  metric.replaceChildren(...(data.metrics.length ? data.metrics.map((m) => h("option", { value: m }, m)) : [h("option", { value: "" }, "aucun indicateur : branche une source")]));
  $("#experiments").replaceChildren(...data.experiments.map((e) => h("article", { class: "card", "data-status": e.verdict === "infirmée" ? "failed" : e.status === "done" ? "done" : "running" },
    h("span", { class: "meta" }, `Expérience #${e.id} · ${e.status === "running" ? "en cours" : e.status === "cancelled" ? "arrêtée" : e.verdict}`),
    h("p", {}, e.text),
    e.status === "running" ? h("div", { class: "row" }, h("button", { class: "btn btn-ghost", type: "button", onclick: async () => { await api("POST", `experiments/${e.id}/stop`, {}); loadDecisions(); } }, h("span", {}, "Arrêter"))) : null)));
}
$("#board-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { toast((await api("POST", `company/${companyId}/decisions`, { question: e.target.elements.question.value })).result, "ok", 8000); e.target.reset(); }
  catch (err) { toast(err.message, "error"); }
  loadDecisions();
});
$("#experiment-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try { toast((await api("POST", `company/${companyId}/experiments`, { ...data, min_change: Number(data.min_change), days: Number(data.days) })).result, "ok", 8000); e.target.elements.hypothesis.value = ""; }
  catch (err) { toast(err.message, "error", 8000); }
  loadDecisions();
});

function taskCard(t, label, ready) {
  const act = (status) => async () => {
    try { await api("POST", `tasks/${t.id}`, { status }); } catch (err) { toast(err.message, "error"); }
    loadCompany();
  };
  const start = async () => {
    try { toast((await api("POST", `tasks/${t.id}/start`, {})).result, "ok"); } catch (err) { toast(err.message, "error", 7000); }
    loadCompany();
  };
  const buttons = [];
  if (t.status === "todo" && ready) buttons.push(["Lancer", start, "btn-primary"]);
  if (t.status === "review") buttons.push(["Valider", act("done"), "btn-primary"], ["À refaire", act("todo"), ""]);
  if (t.status === "blocked") buttons.push(["Débloquer", act("todo"), ""]);
  if (t.status === "todo" || t.status === "doing" || t.status === "review" || t.status === "blocked") buttons.push(["Annuler", act("cancelled"), "btn-ghost"]);
  const meta = [`#${t.id}`, label[t.department] || "sans département", ["", "urgent", "", "plus tard"][t.priority] || ""];
  if (t.depends_on.length) meta.push(`après ${t.depends_on.map((d) => `#${d}`).join(", ")}`);
  if (t.mission_id) meta.push(`mission #${t.mission_id}`);
  return h("article", { class: "card co-task", "data-status": t.status },
    h("h3", {}, t.title),
    h("span", { class: "meta" }, meta.filter(Boolean).join(" · ")),
    t.note ? h("p", {}, t.note) : null,
    buttons.length ? h("div", { class: "row" }, ...buttons.map(([text, fn, cls]) => h("button", { class: `btn ${cls}`, type: "button", onclick: fn }, h("span", {}, text)))) : null);
}
$("#company-select").addEventListener("change", (e) => {
  companyId = Number(e.target.value) || null;
  try { localStorage.setItem("spectre-company", String(companyId)); } catch { /* private mode */ }
  loadCompany();
});
$("#company-autopilot").addEventListener("change", async (e) => {
  try { toast((await api("POST", `company/${companyId}/autopilot`, { on: e.target.checked })).result, "ok"); }
  catch (err) { toast(err.message, "error"); }
  loadCompany();
});
$("#company-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try {
    toast((await api("POST", "company", data)).result, "ok", 6000);
    const list = await api("GET", "company");
    companyId = list[list.length - 1].id;
    try { localStorage.setItem("spectre-company", String(companyId)); } catch { /* private mode */ }
    e.target.reset();
  } catch (err) { toast(err.message, "error"); }
  loadCompany();
});
$("#company-plan").addEventListener("submit", async (e) => {
  e.preventDefault();
  const objective = e.target.elements.objective.value.trim();
  if (!objective) return;
  try { toast((await api("POST", `company/${companyId}/plan`, { objective })).result, "ok", 7000); e.target.reset(); }
  catch (err) { toast(err.message, "error"); }
});
$("#company-task").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try { await api("POST", `company/${companyId}/tasks`, { ...data, priority: Number(data.priority) }); e.target.elements.title.value = ""; }
  catch (err) { toast(err.message, "error"); }
  loadCompany();
});
$("#company-start").addEventListener("click", async () => {
  try { toast((await api("POST", `company/${companyId}/start`, {})).result, "ok", 7000); }
  catch (err) { toast(err.message, "error"); }
  loadCompany();
});

/* ---- automation: routines, webhooks, Telegram ---- */
const RKIND = { mission: "mission", question: "question", rappel: "rappel" };
async function loadAutomation() {
  const [routines, hooks, tg, agents] = await Promise.all([api("GET", "routines"), api("GET", "webhooks"), api("GET", "telegram"), fetchAgents()]);
  const failing = routines.filter((r) => r.failures > 0).length;
  $("#count-automation").textContent = failing || "";
  const agentSel = $("#routine-agent");
  if (agentSel.options.length < 2) agentSel.append(...[...agents.assistant.filter((a) => a.key !== "opus"), ...agents.created].map((a) => h("option", { value: a.name }, a.name)));
  $("#routines").replaceChildren(...(routines.length ? routines.map(routineCard) : [h("p", { class: "empty-cards" }, "Aucune routine. Programme-en une ici ou demande-la à Spectre.")]));
  $("#webhooks").replaceChildren(...(hooks.length ? hooks.map(webhookCard) : [h("p", { class: "empty-cards" }, "Aucun webhook.")]));
  renderTelegram(tg);
}
function routineCard(r) {
  const call = (path, body, done) => async () => {
    try { const res = await api("POST", `routines/${r.id}${path}`, body); toast(res.result || done, "ok"); }
    catch (err) { toast(err.message, "error"); }
    loadAutomation();
  };
  const next = r.enabled && r.next_run ? `prochaine : ${date(r.next_run)}` : "en pause";
  return h("article", { class: "card", "data-status": r.enabled ? (r.failures ? "failed" : "running") : "done" },
    h("h3", {}, r.name),
    h("span", { class: "meta" }, `#${r.id} · ${RKIND[r.kind] || r.kind} · ${r.when} · ${next}${r.agent ? ` · ${r.agent}` : ""}`),
    h("p", {}, r.prompt),
    r.last_status ? h("p", { class: "meta" }, `Dernière exécution : ${r.last_status}${r.failures ? ` (${r.failures} échec${r.failures > 1 ? "s" : ""} d'affilée)` : ""}`) : null,
    h("div", { class: "row" },
      h("button", { class: "btn", type: "button", onclick: call("/run", {}, "Lancée.") }, h("span", {}, "Lancer maintenant")),
      h("button", { class: "btn", type: "button", onclick: call("", { enabled: r.enabled ? "non" : "oui" }) }, h("span", {}, r.enabled ? "Mettre en pause" : "Reprendre")),
      h("button", { class: "btn btn-ghost", type: "button", onclick: call("/delete", {}) }, h("span", {}, "Supprimer"))));
}
function webhookCard(w) {
  const remove = async () => {
    try { await api("POST", `webhooks/${encodeURIComponent(w.name)}/delete`, {}); toast(`Webhook ${w.name} supprimé.`, "ok"); }
    catch (err) { toast(err.message, "error"); }
    loadAutomation();
  };
  return h("article", { class: "card" },
    h("h3", {}, w.name),
    h("span", { class: "meta" }, `${w.source} · ${w.action === "mission" ? "lance une mission" : "prévient"} · ${w.received} reçu${w.received > 1 ? "s" : ""}${w.last_at ? ` · dernier : ${date(w.last_at)}` : ""}`),
    h("p", {}, h("code", {}, w.url)),
    w.events.length ? h("p", { class: "meta" }, `Événements : ${w.events.join(", ")}`) : null,
    h("div", { class: "row" }, h("button", { class: "btn btn-ghost", type: "button", onclick: remove }, h("span", {}, "Supprimer"))));
}
function renderTelegram(tg) {
  const box = $("#telegram");
  const rows = [];
  if (!tg.configured) {
    rows.push(h("p", {}, "Crée un bot avec @BotFather dans Telegram (commande /newbot), puis colle ici le jeton qu'il te donne. Il reste sur ce PC, dans ~/.spectre/assistant/.env."));
  } else {
    rows.push(h("p", {}, tg.running ? `Bot actif${tg.username ? ` : @${tg.username}` : ""}.` : "Bot arrêté.", tg.error ? ` Erreur : ${tg.error}` : ""));
    rows.push(h("p", { class: "meta" }, tg.chats.length ? `Conversations reconnues : ${tg.chats.map((c) => c.name || c.id).join(", ")}` : "Aucune conversation jumelée."));
    if (tg.code) rows.push(h("p", { class: "tg-code" }, "Envoie au bot : ", h("code", {}, `/start ${tg.code}`), " (valable 10 minutes)"));
    rows.push(h("div", { class: "row" },
      h("button", { class: "btn btn-primary", type: "button", onclick: async () => { try { renderTelegram(await api("POST", "telegram/pair", {})); } catch (err) { toast(err.message, "error"); } } }, h("span", {}, "Jumeler une conversation")),
      ...tg.chats.map((c) => h("button", { class: "btn btn-ghost", type: "button", onclick: async () => { renderTelegram(await api("POST", "telegram/unlink", { chat_id: c.id })); } }, h("span", {}, `Oublier ${c.name || c.id}`)))));
  }
  const form = h("form", { class: "inline-form", autocomplete: "off", onsubmit: async (e) => {
    e.preventDefault();
    try { renderTelegram(await api("POST", "telegram/token", { token: e.target.elements.token.value })); toast("Bot Telegram connecté.", "ok"); }
    catch (err) { toast(err.message, "error", 7000); }
  } }, h("input", { type: "password", name: "token", placeholder: tg.configured ? "Remplacer le jeton du bot" : "Jeton du bot, ex. 123456789:ABC…", autocomplete: "off", "aria-label": "Jeton du bot Telegram" }),
    h("button", { class: "btn", type: "submit" }, tg.configured ? "Remplacer" : "Connecter"));
  box.replaceChildren(...rows, form);
}
$("#routine-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try { toast((await api("POST", "routines", data)).result, "ok", 7000); e.target.reset(); }
  catch (err) { toast(err.message, "error", 9000); }
  loadAutomation();
});
$("#webhook-form").addEventListener("change", (e) => { if (e.target.name === "source") $("#webhook-secret-row").hidden = e.target.value !== "stripe"; });
$("#webhook-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try {
    const w = await api("POST", "webhooks", data);
    const box = $("#webhook-created");
    box.hidden = false;
    box.replaceChildren(h("h3", {}, `Webhook ${w.name} créé`),
      h("p", {}, "Adresse à donner au service : ", h("code", {}, w.url)),
      w.source === "stripe" ? h("p", {}, "Signature : le secret Stripe que tu as collé.") : h("p", {}, "Secret de signature (affiché une seule fois) : ", h("code", {}, w.secret)),
      h("p", { class: "meta" }, w.source === "github" ? "Dans GitHub : Settings › Webhooks › Add webhook, Content type application/json, Secret ci-dessus." : w.source === "generic" ? "Le service doit envoyer l'en-tête X-Spectre-Signature: sha256=<HMAC-SHA256 du corps avec ce secret>." : "Dans Stripe : Développeurs › Webhooks, cette adresse comme point de terminaison."));
    e.target.reset();
    $("#webhook-secret-row").hidden = true;
  } catch (err) { toast(err.message, "error", 9000); }
  loadAutomation();
});

/* ---- agents ---- */
let agentsCache = null;
async function fetchAgents() {
  agentsCache = agentsCache || await api("GET", "agents");
  return agentsCache;
}
function agentCard(a) {
  const tags = [];
  if (a.key === "opus") tags.push(h("span", {}, "chef"));
  if (a.default) tags.push(h("span", {}, "exécute par défaut"));
  if (a.available === false) tags.push(h("span", { class: "off" }, "outil introuvable"));
  if (a.id) tags.push(h("button", { class: "btn btn-ghost", type: "button", onclick: () => deleteAgent(a) }, h("span", {}, "Supprimer")));
  return h("article", { class: "ag-card", "data-agent": a.key },
    h("h3", { class: "ag-name" }, a.name),
    h("p", { class: "ag-engine" }, a.engine),
    a.role ? h("p", { class: "ag-role" }, a.role) : null,
    tags.length ? h("div", { class: "ag-tags" }, tags) : null);
}
async function loadAgents() {
  agentsCache = null;
  const data = await fetchAgents();
  $("#count-agents").textContent = data.assistant.length + data.created.length + data.redaction.length;
  $("#agents").replaceChildren(...data.assistant.map(agentCard));
  $("#agents-created").replaceChildren(...(data.created.length ? data.created.map(agentCard) : [h("p", { class: "empty-cards" }, "Aucun agent créé pour l'instant.")]));
  const engine = $("#agent-engine");
  if (!engine.options.length) engine.append(...data.assistant.map((a) => h("option", { value: a.key, selected: a.key === "sonnet" }, `${a.name} · ${a.engine}`)));
  $("#agents-redaction").replaceChildren(...data.redaction.map(agentCard));
  loadEngines().catch((err) => toast(err.message, "error"));
  loadTrust().catch((err) => toast(err.message, "error"));
}
/* ---- earned autonomy and what the AI costs ---- */
const LEVEL_MARK = { apprenti: "○ apprenti", "confirmé": "◐ confirmé", expert: "● expert" };
async function loadTrust() {
  const [rows, costs] = await Promise.all([api("GET", "trust"), api("GET", "costs")]);
  const spent = Object.fromEntries(costs.by_agent.map((r) => [r.key, r]));
  $("#trust").replaceChildren(...(rows.length ? rows.map((d) => {
    const c = spent[d.agent];
    const counts = Object.entries(d.counts).map(([k, n]) => `${TRUST_KIND[k] || k} ${n}`).join(" · ");
    return h("article", { class: "ag-card", "data-agent": d.agent.startsWith("agent:") ? "created" : d.agent, "data-level": d.level },
      h("h3", { class: "ag-name" }, d.name),
      h("p", { class: "ag-engine" }, `${LEVEL_MARK[d.level] || d.level} · fiabilité ${String(d.reliability).replace(".", ",")} %`),
      h("p", { class: "ag-role" }, counts || "rien encore"),
      c ? h("p", { class: "meta" }, `30 j : ${c.calls} appels · ${(c.cost || 0).toFixed(2).replace(".", ",")} $ · ${Math.round(c.seconds || 0)} s`) : null);
  }) : [h("p", { class: "empty-cards" }, "Aucun dossier encore : les agents en gagnent un en menant des missions.")]));
  $("#costs-global").textContent = costs.calls ? `Sur 30 jours : ${costs.calls} appels au modèle, ${costs.cost_usd.toFixed(2).replace(".", ",")} $ en équivalent API (l'abonnement Claude est ce que tu paies vraiment), ${Math.round(costs.seconds / 60)} min de calcul.` : "";
}
const TRUST_KIND = { step_ok: "étapes ✓", step_fail: "étapes ✗", task_validated: "tâches validées", task_redo: "à refaire", approval_granted: "accords", approval_denied: "refus", rollback: "annulations" };

/* ---- engines: which LLM serves each role, and the fallback chain ---- */
const CLI_LABELS = { opus: "Opus 5.5 · Claude", sonnet: "Sonnet 5.5 · Claude", haiku: "Haiku 4.5 · Claude", chatgpt: "ChatGPT · Codex (ton compte)", mistral: "Mistral · Vibe (ton compte Le Chat)" };
let engineGroups = [];
function engineSelect(name, value, { empty = "" } = {}) {
  const known = engineGroups.some((g) => g.items.some((i) => i.value === value));
  return h("select", { name },
    empty ? h("option", { value: "", selected: value === "" }, empty) : null,
    value && !known ? h("option", { value, selected: true }, `${value} (actuel, indisponible)`) : null,
    ...engineGroups.map((g) => h("optgroup", { label: g.label },
      ...g.items.map((i) => h("option", { value: i.value, selected: i.value === value }, i.text)))));
}
function fallbackRow(value) {
  const row = h("div", { class: "fb-row" }, engineSelect("fallback", value),
    h("button", { class: "btn btn-ghost", type: "button", onclick: () => row.remove() }, h("span", {}, "Retirer")));
  return row;
}
async function loadEngines() {
  const data = await api("GET", "models");
  const ready = data.providers.filter((p) => p.ready);
  const lists = await Promise.all(ready.map((p) => api("GET", `models/${encodeURIComponent(p.id)}`).catch(() => ({ models: [] }))));
  const chat = (m) => !/embed/i.test(m);  // embedding models cannot chat
  engineGroups = [
    { label: "Claude, sur ton abonnement", items: ["opus", "sonnet", "haiku"].map((v) => ({ value: v, text: CLI_LABELS[v] })) },
    { label: "Tes autres comptes", items: ["chatgpt", "mistral"].map((v) => ({ value: v, text: CLI_LABELS[v] })) },
    ...ready.map((p, i) => ({ label: p.label, items: lists[i].models.filter(chat).map((m) => ({ value: `${p.id}:${m}`, text: m })) }))
      .filter((g) => g.items.length),
  ];
  const label = (text) => h("span", { class: "label" }, text.charAt(0).toUpperCase() + text.slice(1));
  const fallbacks = h("div", { class: "fb-list", id: "fallback-list" }, ...data.fallbacks.map(fallbackRow));
  $("#engine-form").replaceChildren(
    ...data.roles.map((r) => h("label", {}, label(r.label),
      engineSelect(r.role, r.engine, r.role === "planner_model" ? { empty: "Le moteur du cerveau" } : {}))),
    h("div", { class: "ag-wide fb" }, label("Moteurs de secours, dans l'ordre"), fallbacks,
      h("div", {}, h("button", { class: "btn", type: "button", onclick: () => fallbacks.append(fallbackRow("haiku")) }, h("span", {}, "Ajouter un moteur de secours"))),
      h("span", { class: "help" }, "Essayés l'un après l'autre quand un moteur échoue ou atteint sa limite. Aucun = pas de secours.")),
    h("div", { class: "ag-wide" }, h("button", { class: "btn btn-primary", type: "submit" }, "Enregistrer les moteurs")));
  $("#providers").replaceChildren(...data.providers.map((p) => {
    const index = ready.indexOf(p);
    const count = index >= 0 ? lists[index].models.filter(chat).length : 0;
    const state = p.ready ? (p.local && !count ? "serveur éteint" : `${count} modèle${count > 1 ? "s" : ""}`) : `clé ${p.key_env} à ajouter`;
    return h("article", { class: "ag-card", "data-agent": "provider" },
      h("h3", { class: "ag-name" }, p.label),
      h("p", { class: "ag-engine" }, p.id),
      h("div", { class: "ag-tags" }, h("span", { class: p.local && !count ? "off" : "" }, state), p.local ? h("span", {}, "local") : null));
  }));
  const engine = $("#agent-engine");  // creating an agent: the same choices
  const current = engine.value || "sonnet";
  engine.replaceChildren(...engineSelect("engine", current).children);
}
$("#engine-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  try {
    const data = await api("GET", "models");
    for (const r of data.roles) {
      const value = form.elements[r.role].value;
      if (value !== r.engine) await api("POST", "models", { role: r.role, engine: value });
    }
    const chain = [...form.querySelectorAll('select[name="fallback"]')].map((s) => s.value);
    if (chain.join(",") !== data.fallbacks.join(",")) await api("POST", "models", { fallbacks: chain });
    toast("Moteurs enregistrés : ils servent dès le prochain message.", "ok");
    loadStatus();
  } catch (err) { toast(err.message, "error", 7000); }
  loadEngines();
});

async function fillAgentSelect() {
  const select = $("#mission-agent");
  const data = await fetchAgents();
  select.replaceChildren(h("option", { value: "" }, "Agent : selon les réglages"),
    ...[...data.assistant.filter((a) => a.key !== "opus"), ...data.created].map((a) => h("option", { value: a.name }, a.name)));
}
async function deleteAgent(a) {
  try { await api("POST", `agents/${a.id}/delete`, {}); toast(`Agent ${a.name} supprimé.`); }
  catch (err) { toast(err.message, "error"); }
  agentsCache = null; loadAgents();
}
$("#agent-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.target));
  try { await api("POST", "agents", data); toast(`Agent ${data.name.trim()} créé : Spectre peut lui confier des missions.`, "ok", 6000); e.target.reset(); }
  catch (err) { toast(err.message, "error", 7000); }
  agentsCache = null; loadAgents();
});

/* ---- remote access: Spectre on the phone through Tailscale ---- */
async function loadRemote() {
  const r = await api("GET", "remote");
  // on the phone itself: it is already connected, the QR code serves to open Spectre elsewhere
  $("#remote-hint").textContent = REMOTE && r.serving ? "Tu es connecté à Spectre à distance depuis cet appareil. Le QR code ouvre Spectre sur un autre appareil." : (r.hint || "");
  $("#remote-qr").innerHTML = r.qr || "";  // SVG drawn by Spectre itself, from Tailscale's name
  const check = (label, ok, yes, no) => [h("dt", {}, label), h("dd", { class: ok ? "ok" : "ko" }, ok ? yes : no)];
  $("#remote-checks").replaceChildren(
    ...check("Tailscale", r.installed && r.running, "connecté", r.installed ? "arrêté ou déconnecté" : "pas installé"),
    ...check("Mot de passe", r.password, "défini", "absent"),
    ...check("Accès à distance", r.serving, "actif", "inactif"));
  $("#remote-url-row").hidden = !r.url;
  $("#remote-url").textContent = r.url; $("#remote-url").href = r.url || "#";
  $("#remote-enable").hidden = !(r.running && r.password && !r.serving);
  $("#remote-launcher").hidden = !r.launcher_url;
  $("#remote-launcher-url").textContent = r.launcher_url || ""; $("#remote-launcher-url").href = r.launcher_url || "#";
}
function openRemote() {
  closeDrawers();
  $("#remote").showModal();
  loadRemote().catch((e) => { $("#remote-hint").textContent = e.message; });
}
$("#remote-enable").addEventListener("click", async () => {
  const btn = $("#remote-enable"); btn.disabled = true;
  try { await api("POST", "remote", {}); toast("Accès à distance activé : scanne le QR code avec ton téléphone."); }
  catch (err) { toast(err.message, "error", 8000); }
  finally { btn.disabled = false; loadRemote().catch(() => {}); }
});
$("#remote-copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("#remote-url").textContent); toast("Lien copié."); }
  catch { toast("Copie impossible : sélectionne le lien à la main.", "warn"); }
});

/* ---- initiatives ---- */
async function loadInitiatives() {
  const rows = await api("GET", "initiatives");
  $("#count-initiatives").textContent = rows.length || "";
  const card = (i) => h("article", { class: "card", "data-status": "done" },
    h("h3", {}, i.title), h("span", { class: "meta" }, `${i.kind} · ${date(i.ts)}`), i.body ? h("p", {}, i.body) : null,
    h("div", { class: "row" },
      h("button", { class: "btn", type: "button", onclick: async () => { await api("POST", `initiatives/${i.id}`, { status: "done" }); loadInitiatives(); } }, h("span", {}, "Vu")),
      h("button", { class: "btn btn-ghost", type: "button", onclick: async () => { await api("POST", `initiatives/${i.id}`, { status: "dismissed" }); loadInitiatives(); } }, h("span", {}, "Écarter"))));
  const empty = () => [h("p", { class: "empty-cards" }, "Rien de neuf.")];
  $("#initiatives").replaceChildren(...(rows.length ? rows.map(card) : empty()));
  $("#initiatives-side").replaceChildren(...(rows.length ? rows.slice(0, 4).map(card) : empty()));
}

/* ---- memory ---- */
async function loadFacts() {
  const q = $("#memory-q").value.trim();
  const rows = await api("GET", `memory${q ? `?q=${encodeURIComponent(q)}` : ""}`);
  if (!q) $("#count-facts").textContent = rows.length || "";
  $("#facts").replaceChildren(...(rows.length ? rows.map((f) => h("div", { class: "fact" },
    h("span", { class: "cat" }, f.category),
    h("span", { class: "claim" }, `${f.subject} `, h("b", {}, f.predicate), ` ${f.value}`),
    h("span", { class: "acts" },
      h("button", { class: "btn btn-ghost", type: "button", onclick: () => correctFact(f) }, h("span", {}, "Corriger")),
      h("button", { class: "btn btn-ghost", type: "button", onclick: async () => { await api("POST", `memory/${f.id}/forget`, {}); toast("Oublié."); loadFacts(); } }, h("span", {}, "Oublier"))),
    h("span", { class: "sub" }, `#${f.id} · confiance ${Number(f.confidence).toFixed(2)} · vu ${f.observations}× · ${date(f.last_seen_at)}`))) : [h("p", { class: "empty-cards" }, q ? "Rien ne correspond." : "Spectre ne sait encore rien de toi. Parle-lui de tes goûts, tes projets, tes habitudes.")]));
}
function correctFact(f) {
  const row = [...$("#facts").children].find((n) => n.textContent.includes(`#${f.id} `));
  if (!row) return;
  const input = h("input", { type: "text", value: f.value, "aria-label": "Nouvelle valeur", style: "min-height:36px;padding:0 8px" });
  const form = h("form", { class: "inline-form", style: "grid-column:1/-1;margin:6px 0 0", onsubmit: async (e) => {
    e.preventDefault();
    try { await api("POST", `memory/${f.id}/correct`, { value: input.value }); toast("Corrigé."); } catch (err) { toast(err.message, "error"); }
    loadFacts();
  } }, input, h("button", { class: "btn btn-primary", type: "submit" }, "Enregistrer"));
  row.append(form); input.focus();
}

/* ---- audit ---- */
async function loadAudit() {
  const rows = await api("GET", "audit");
  $("#audit").replaceChildren(...(rows.length ? rows.map((a) => h("div", { class: "audit-row" },
    h("span", {}, time(a.ts)), h("span", {}, a.tool), h("span", {}, String(a.level)),
    h("span", {}, h("b", { class: `d-${a.decision}` }, a.decision), " — ", a.result))) : [h("p", { class: "empty-cards" }, "Aucune action pour l'instant.")]));
}

/* ---- settings ---- */
const AGENT_NAMES = { sonnet: "Gétro", haiku: "Kaïto", chatgpt: "Kyra", mistral: "Syfer", opus: "Spectre" };
const FIELDS = [
  ["user_name", "Ton prénom", "text", "Spectre l'utilise pour s'adresser à toi."],
  ["city", "Ta ville", "text", "Pour la météo du briefing."],
  ["chatgpt_model", "Modèle ChatGPT", "text", "Vide = le modèle par défaut de Codex pour ton compte ChatGPT (par exemple gpt-5.5)."],
  ["mistral_model", "Modèle Mistral", "text", "Vide = le modèle par défaut de Vibe (mistral-medium-3.5). Vibe utilise ton compte Le Chat, ou une clé MISTRAL_API_KEY dans ~/.spectre/assistant/vibe/.env."],
  ["briefing_hour", "Heure du briefing", "number", "Le briefing du matin apparaît à partir de cette heure."],
  ["auto_max_level", "Autonomie (0 à 2)", "number", "Au-dessus de ce niveau de risque, Spectre demande ta validation. Supprimer, envoyer ou toucher au système demande toujours ton accord."],
  ["stt_model", "Compréhension de ta voix", ["small", "medium", "large-v3-turbo"], "small : rapide (environ 2 s par phrase sur ce PC) ; medium et large-v3-turbo : un peu plus précis mais 3 à 4 fois plus lents, et 1,5 Go à télécharger au premier lancement. Au prochain lancement."],
  ["tts_voice", "Voix", ["fr_FR-upmc-medium", "fr_FR-gilles-low", "fr_FR-tom-medium"], "Voix d'homme ; pour fr_FR-upmc-medium, mets le locuteur « pierre »."],
  ["tts_speaker", "Locuteur", "text", ""],
  ["tts_pace", "Débit de la voix", ["naturel", "pose", "vif"], "naturel : comme une conversation ; pose : plus lent ; vif : plus rapide."],
  ["tts_effect", "Timbre", ["futuriste", "androide", "hologramme", "vaisseau", "aucun"], "futuriste : IA de bord grave et métallique ; androide : robot vocodé ; hologramme : chœur scintillant ; vaisseau : discret ; aucun : voix naturelle."],
  ["speak_initiatives", "Annoncer les initiatives à voix haute", "checkbox", ""],
  ["befriend_per_day", "Spectre vient te parler (fois par jour, 0 à 4)", "number", "Pour mieux te connaître : une question sincère, ou une suite à ce que tu lui as confié. 0 = jamais. Il ne vient jamais pendant une conversation, espace ses venues et les espace davantage quand tu ne réponds pas."],
  ["befriend_hours", "Heures où il peut venir", "text", "De telle heure à telle heure, par exemple 10-21."],
  ["camera", "Reconnaissance des visages (webcam)", "checkbox", "Au prochain lancement. Ou lance Spectre avec --camera."],
];
async function loadFaces() {
  const data = await api("GET", "faces");
  $("#face-enroll").disabled = !data.camera;
  $("#face-name").placeholder = data.camera ? "Prénom de la personne devant la caméra" : "Caméra inactive : active-la dans les réglages puis relance Spectre";
  $("#faces").replaceChildren(...(data.people.length ? data.people.map((p) => h("div", { class: "fact" },
    h("span", { class: "cat" }, "visage"),
    h("span", { class: "claim" }, h("b", {}, p.name)),
    h("span", { class: "acts" }, h("button", { class: "btn btn-ghost", type: "button", onclick: async () => {
      await api("POST", `faces/${encodeURIComponent(p.name)}/forget`, {}); toast(`Visage de ${p.name} oublié.`); loadFaces();
    } }, h("span", {}, "Oublier"))),
    h("span", { class: "sub" }, `${p.samples} empreintes · depuis ${date(p.since)}`))) : [h("p", { class: "empty-cards" }, "Aucun visage enregistré.")]));
}
$("#face-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("#face-enroll"); btn.disabled = true; btn.textContent = "Regarde la caméra…";
  try { const r = await api("POST", "faces/enroll", { name: $("#face-name").value }); toast(`Visage de ${r.name} enregistré (${r.samples} prises).`); $("#face-name").value = ""; }
  catch (err) { toast(err.message, "error", 7000); }
  finally { btn.textContent = "Enregistrer ce visage"; loadFaces(); }
});
function showPresence(people, unknown, spoof = 0) {
  const parts = [...people];
  if (unknown) parts.push(unknown > 1 ? `${unknown} inconnus` : "1 inconnu");
  if (spoof) parts.push(spoof > 1 ? `${spoof} photos ou écrans` : "1 photo ou écran");
  $("#presence-line").textContent = parts.length ? `Présent : ${parts.join(", ")}` : "";
}

async function loadSettings() {
  const cfg = await api("GET", "config");
  const form = $("#settings-form");
  form.replaceChildren(...FIELDS.map(([key, label, type, help]) => {
    let input;
    if (Array.isArray(type)) input = h("select", { name: key }, ...type.map((o) => h("option", { value: o, selected: cfg[key] === o }, key === "mission_model" && AGENT_NAMES[o] ? `${AGENT_NAMES[o]} (${o})` : o)));
    else if (type === "checkbox") input = h("input", { type: "checkbox", name: key, checked: !!cfg[key] });
    else input = h("input", { type, name: key, value: cfg[key] ?? "" });
    return h("label", {}, h("span", { class: "label" }, label), input, help ? h("span", { class: "help" }, help) : null);
  }), h("div", {}, h("button", { class: "btn btn-primary", type: "submit" }, "Enregistrer")));
}
$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const changes = {};
  for (const [key, , type] of FIELDS) {
    const el = e.target.elements[key];
    changes[key] = type === "checkbox" ? el.checked : type === "number" ? Number(el.value) : el.value;
  }
  try { await api("POST", "config", changes); toast("Réglages enregistrés (la voix change au prochain lancement)."); loadStatus(); }
  catch (err) { toast(err.message, "error"); }
});

/* ---- status + navigation ---- */
async function loadStatus() {
  const s = await api("GET", "status");
  voiceAvailable = s.voice_available;
  $("#brain-model").textContent = `cerveau : ${s.brain_label || s.brain_model}`;
  $("#talk-btn").hidden = !voiceAvailable;
  $("#cam-btn").hidden = !(REMOTE && s.camera);  // the PC's own camera already watches the PC
  $("#count-approvals").textContent = s.pending_approvals || "";
  $("#count-initiatives").textContent = s.pending_initiatives || "";
  $("#count-facts").textContent = s.facts || "";
  $("#count-missions").textContent = s.missions_running || "";
  $("#hud-facts").textContent = s.facts;
  $("#hud-approvals").textContent = s.pending_approvals;
  $("#dock-approvals").textContent = s.pending_approvals || "";
  $("#hud-missions").textContent = s.missions_running;
  if (s.camera) showPresence(s.present || [], 0);
  $("#hud-brain").textContent = String(s.brain_label || s.brain_model).toUpperCase();
  const power = s.power || {};
  $("#power-banner").hidden = !power.on_battery;
  if (power.on_battery) $("#power-banner").textContent = `Le PC est sur batterie${power.percent != null ? ` (${power.percent} %)` : ""} : il peut se mettre en veille, et Spectre ne sera plus joignable. Branche-le pour qu'il reste disponible.`;
  if (!document.body.dataset.voice || document.body.dataset.voice === "off") setState(s.voice);
}
function refreshCompany() {  // the board moves when missions finish: refresh it if shown
  const view = document.querySelector('.as-view[data-view="company"]');
  if (view && !view.hidden) loadCompany().catch(() => {});
}
const LOADERS = { talk: loadHistory, approvals: loadApprovals, missions: () => Promise.all([loadMissions(), fillAgentSelect()]), company: loadCompany, automation: loadAutomation, learning: loadLearning, agents: loadAgents, memory: loadFacts, initiatives: loadInitiatives, audit: loadAudit, settings: () => Promise.all([loadSettings(), loadFaces()]) };
function show(view) {
  $$(".as-nav button").forEach((b) => b.setAttribute("aria-current", String(b.dataset.view === view)));
  $$(".as-view").forEach((v) => { v.hidden = v.dataset.view !== view; });
  document.body.dataset.view = view;
  closeDrawers();
  LOADERS[view]?.().catch((e) => toast(e.message, "error"));
  history.replaceState(null, "", `#${view}`);
}
function closeDrawers() { document.body.classList.remove("rail-open", "inspector-open"); $(".scrim").hidden = true; }

/* ---- voice from this device (phone): record here, Spectre transcribes and answers aloud here ---- */
const rec = { ctx: null, stream: null, node: null, chunks: [], active: false, busy: false };
async function deviceTalk() {
  if (rec.busy) return;
  if (rec.active) { finishRecording(); return; }  // a second tap stops early
  try {
    rec.ctx = rec.ctx || new AudioContext();
    await rec.ctx.resume();  // inside the tap, so the answer may play later
    rec.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch {
    toast("Autorise le micro dans le navigateur pour parler à Spectre depuis cet appareil.", "error", 7000);
    return;
  }
  const source = rec.ctx.createMediaStreamSource(rec.stream);
  rec.node = rec.ctx.createScriptProcessor(4096, 1, 1);
  rec.chunks = [];
  rec.active = true;
  const started = performance.now();
  let spoke = 0, lastVoice = 0;
  rec.node.onaudioprocess = (e) => {
    if (!rec.active) return;
    const data = e.inputBuffer.getChannelData(0);
    rec.chunks.push(new Float32Array(data));
    let sum = 0;
    for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
    const level = Math.sqrt(sum / data.length);
    setLevel(Math.min(1, level * 8));
    const now = performance.now();
    if (level > 0.02) { spoke = spoke || now; lastVoice = now; }
    // stops after a pause, if nothing is said, or after 25 s
    if ((spoke && now - lastVoice > 1800) || (!spoke && now - started > 7000) || now - started > 25000) finishRecording();
  };
  source.connect(rec.node);
  rec.node.connect(rec.ctx.destination);  // outputs silence; needed for the node to run
  setState("listening");
}
function toPcm16(chunks, rate) {
  // downsample to 16 kHz by averaging, then 16-bit: what Spectre's speech recognition expects
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const all = new Float32Array(total);
  let at = 0;
  for (const c of chunks) { all.set(c, at); at += c.length; }
  const ratio = rate / 16000;
  const out = new Int16Array(Math.floor(total / ratio));
  for (let i = 0; i < out.length; i++) {
    const from = Math.floor(i * ratio), to = Math.min(total, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = from; j < to; j++) sum += all[j];
    const v = Math.max(-1, Math.min(1, sum / Math.max(1, to - from)));
    out[i] = v < 0 ? v * 32768 : v * 32767;
  }
  return out;
}
async function finishRecording() {
  if (!rec.active) return;
  rec.active = false;
  rec.node?.disconnect();
  rec.stream?.getTracks().forEach((t) => t.stop());
  const pcm = toPcm16(rec.chunks, rec.ctx.sampleRate);
  if (pcm.length < 8000) { setState("sleeping"); return; }  // under half a second
  rec.busy = true;
  setState("thinking");
  try {
    const res = await fetch("/api/assistant/voice", { method: "POST", credentials: "same-origin", headers: { "X-Spectre": "1", "Content-Type": "application/octet-stream" }, body: pcm.buffer });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    if (!data.heard) toast("Je n'ai rien entendu. Réessaie en parlant près du téléphone.", "warn");
    else if (data.audio) await playWav(data.audio);
  } catch (err) {
    toast(err.message, "error", 7000);
  } finally {
    rec.busy = false;
    setState("sleeping");
  }
}
async function playWav(b64) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const buffer = await rec.ctx.decodeAudioData(bytes.buffer);
  const src = rec.ctx.createBufferSource();
  src.buffer = buffer;
  src.connect(rec.ctx.destination);
  setState("speaking");
  await new Promise((resolve) => { src.onended = resolve; src.start(); });
}
// Spectre's other words (typed replies, initiatives) are spoken here too. The browser only lets
// a page play sound after a tap: the first tap unlocks it, and what came before waits for it.
let pendingSpeech = null;
async function unlockAudio() {
  rec.ctx = rec.ctx || new AudioContext();
  await rec.ctx.resume();
  if (pendingSpeech) { const p = pendingSpeech; pendingSpeech = null; speakHere(p.text, p.listen); }
}
async function speakHere(text, listen = false) {
  if (!REMOTE || !text || rec.active || rec.busy) return;
  if (rec.ctx?.state !== "running") {
    pendingSpeech = { text, listen };
    toast("Touche l'écran pour entendre Spectre.", "warn", 7000);
    return;
  }
  rec.busy = true;
  try {
    const { audio } = await api("POST", "speak", { text });
    if (audio) await playWav(audio);
  } catch (err) {
    toast(err.message, "error");
  } finally {
    rec.busy = false;
    setState("sleeping");
  }
  if (listen && document.visibilityState === "visible") deviceTalk();  // then the user can simply answer
}
// On a touch screen, the browser allows sound when the finger lifts, not when it presses.
if (REMOTE) for (const type of ["pointerup", "keydown"]) document.addEventListener(type, () => unlockAudio().catch(() => {}), true);

/* ---- camera of this device (phone): a picture every 2 s, analysed by Spectre like its own ---- */
const cam = { stream: null, timer: null, canvas: document.createElement("canvas"), sending: false };
async function deviceCamera() {
  if (cam.stream) { stopCamera(); return; }
  try {
    cam.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
  } catch {
    toast("Autorise la caméra dans le navigateur pour que Spectre te reconnaisse depuis cet appareil.", "error", 7000);
    return;
  }
  const video = $("#cam-preview");
  video.srcObject = cam.stream;
  video.hidden = false;
  await video.play().catch(() => {});
  $("#cam-btn").setAttribute("aria-pressed", "true");
  cam.timer = setInterval(sendFrame, 2000);
  toast("Caméra du téléphone active : Spectre regarde qui est là. Retouche le bouton pour l'arrêter.");
}
function stopCamera() {
  clearInterval(cam.timer);
  cam.stream?.getTracks().forEach((t) => t.stop());
  cam.stream = null;
  const video = $("#cam-preview");
  video.srcObject = null;
  video.hidden = true;
  $("#cam-btn").setAttribute("aria-pressed", "false");
}
async function sendFrame() {
  const video = $("#cam-preview");
  if (cam.sending || !video.videoWidth) return;
  cam.sending = true;
  try {
    const scale = Math.min(1, 640 / video.videoWidth);
    cam.canvas.width = Math.round(video.videoWidth * scale);
    cam.canvas.height = Math.round(video.videoHeight * scale);
    cam.canvas.getContext("2d").drawImage(video, 0, 0, cam.canvas.width, cam.canvas.height);
    const blob = await new Promise((resolve) => cam.canvas.toBlob(resolve, "image/jpeg", 0.75));
    const res = await fetch("/api/assistant/frame", { method: "POST", credentials: "same-origin", headers: { "X-Spectre": "1", "Content-Type": "image/jpeg" }, body: blob });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      stopCamera();
      toast(data.error || `HTTP ${res.status}`, "error", 7000);
    }
  } catch { /* a lost picture: the next one follows */ }
  finally { cam.sending = false; }
}
document.addEventListener("visibilitychange", () => { if (document.hidden && cam.stream) stopCamera(); });

/* ---- live events ---- */
function connect() {
  const es = new EventSource("/api/assistant/events");
  es.addEventListener("state", (e) => { const d = JSON.parse(e.data); setState(d.state, d.detail); });
  es.addEventListener("message", (e) => {
    const d = JSON.parse(e.data);
    addLine(d.role, d.text, d.error);
    if (d.role === "spectre") caption("#said", d.text, 14000);
    else caption("#heard", d.text, 14000);
    loadStatus().catch(() => {});
  });
  es.addEventListener("level", (e) => setLevel(JSON.parse(e.data).v));
  es.addEventListener("presence", (e) => { const d = JSON.parse(e.data); showPresence(d.people, d.unknown, d.spoof); });
  es.addEventListener("arrival", (e) => {
    const d = JSON.parse(e.data);
    caption("#said", d.text, 8000);
    if (d.speak) speakHere(d.text, true);
  });
  es.addEventListener("approval", () => { loadApprovals(); toast("Spectre attend ta validation pour une action.", "warn", 6000); });
  es.addEventListener("approval_done", () => loadApprovals());
  es.addEventListener("initiative", (e) => {
    const d = JSON.parse(e.data);
    toast(`${d.title}${d.body ? ` — ${d.body}` : ""}`, "ok", 8000);
    loadInitiatives(); loadMissions();
    if (d.speak) speakHere(d.kind === "lien" ? d.body : `${d.title}. ${d.body}`, d.kind === "lien");
  });
  es.addEventListener("initiative_row", () => { loadInitiatives(); refreshCompany(); });
  es.addEventListener("company", () => refreshCompany());
  es.onopen = () => { $("#offline-banner").hidden = true; };
  es.onerror = () => {
    setState("off", "Connexion perdue, reconnexion…");
    // Spectre closed on the PC: the launcher can start it again (from the phone). Nothing
    // answers at all: the PC sleeps, is off or offline; say so instead of a frozen page.
    fetch("/api/status", { cache: "no-store" })
      .then((r) => { if (REMOTE && r.status >= 502) location.href = "/lanceur/"; })
      .catch(() => { $("#offline-banner").hidden = false; });
  };
}

/* ---- wiring ---- */
$("#as-nav").addEventListener("click", (e) => { const b = e.target.closest("[data-view]"); if (b) show(b.dataset.view); });
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-action]")?.dataset.action;
  if (a === "close-drawers") closeDrawers();
  if (a === "open-rail") { document.body.classList.add("rail-open"); $(".scrim").hidden = false; }
  if (a === "open-inspector") { document.body.classList.add("inspector-open"); $(".scrim").hidden = false; }
  if (a === "camera") deviceCamera();
  if (a === "remote") openRemote();
  if (a === "talk") {
    if (REMOTE) deviceTalk();
    else api("POST", "talk", {}).catch((err) => toast(err.message, "error"));
  }
  if (a === "history") { const panel = $("#history"); panel.hidden = !panel.hidden; if (!panel.hidden) loadHistory(); }
  const goto = e.target.closest("[data-goto]")?.dataset.goto;
  if (goto) show(goto);
});
$("#say-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#say"); const text = input.value.trim();
  if (!text) return;
  input.value = ""; $("#send").disabled = true;
  try { const { reply } = await api("POST", "chat", { text }); speakHere(reply); } catch (err) { toast(err.message, "error"); }
  finally { $("#send").disabled = false; input.focus(); loadStatus(); }
});
$("#say").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !matchMedia("(pointer: coarse)").matches) { e.preventDefault(); $("#say-form").requestSubmit(); } });
$("#mission-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const goal = $("#mission-goal").value.trim(); if (!goal) return;
  try { const r = await api("POST", "missions", { goal, kind: $("#mission-kind").value, agent: $("#mission-agent").value }); toast(r.result); $("#mission-goal").value = ""; loadMissions(); }
  catch (err) { toast(err.message, "error"); }
});
let qTimer = 0;
$("#memory-q").addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(loadFacts, 200); });

function drawContinuum() {
  // Same seeded charcoal continuum as the writing app, behind the presence band.
  const host = $(".continuum");
  let canvas = host.querySelector("canvas");
  if (!canvas) { canvas = h("canvas"); host.append(canvas); }
  const w = host.clientWidth || 1200, hgt = host.clientHeight || 188;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.round(w * dpr); canvas.height = Math.round(hgt * dpr);
  const ctx = canvas.getContext("2d");
  const light = document.documentElement.dataset.theme === "light";
  let seed = 11;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const base = light ? [226, 221, 208] : [23, 24, 27];
  const step = Math.max(1, Math.round(dpr));
  for (let x = 0; x < canvas.width; x += step) {
    const band = (rnd() - 0.5) * (light ? 10 : 9) + Math.sin(x / (canvas.width / 9)) * 3;
    const centre = 1 - Math.abs(x / canvas.width - 0.2) * 0.9;
    const k = light ? band - centre * 4 : band + centre * 10;
    ctx.fillStyle = `rgb(${base.map((c) => Math.max(0, Math.min(255, Math.round(c + k)))).join(",")})`;
    ctx.fillRect(x, 0, step, canvas.height);
  }
  ctx.globalAlpha = light ? 0.12 : 0.18;
  ctx.fillStyle = light ? "#000" : "#fff";
  for (let i = 0; i < 26; i++) ctx.fillRect(Math.round(rnd() * canvas.width), 0, 1, canvas.height);
  ctx.globalAlpha = 1;
}
let resizeTimer = 0;
addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(drawContinuum, 150); });

(async function boot() {
  drawContinuum();
  orb.spellWord(1.8);
  try {
    await loadStatus();
    await Promise.all([loadApprovals(), loadInitiatives()]);
    show(LOADERS[location.hash.slice(1)] ? location.hash.slice(1) : "talk");
    connect();
  } catch (err) {
    setState("off", `L'assistant n'est pas lancé ici (${err.message}). Démarre-le avec : uv run python -m spectre.assistant`);
  }
})();
setInterval(() => loadStatus().catch(() => {}), 60000);  // battery, counters
addEventListener("hashchange", () => { const v = location.hash.slice(1); if (LOADERS[v]) show(v); });
