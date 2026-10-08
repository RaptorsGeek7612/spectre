// Spectre assistant UI. Plain ES module: live events over SSE, everything else over JSON.

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
  sleeping: ["En veille", "Dis « Spectre » pour me parler."],
  listening: ["J'écoute…", ""],
  thinking: ["Je réfléchis…", ""],
  speaking: ["Je parle", ""],
};
let voiceAvailable = false;

function setState(state, detail = "") {
  if (state === "heard") { $("#presence-detail").textContent = `« ${detail} »`; return; }
  document.body.dataset.voice = state;
  const [label, hint] = STATES[state] || [state, ""];
  $("#presence-state").textContent = label;
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
const MSTATUS = { queued: "en file", running: "en cours", done: "terminée", failed: "échouée" };
async function loadMissions() {
  const rows = await api("GET", "missions");
  $("#count-missions").textContent = rows.filter((m) => m.status === "running" || m.status === "queued").length || "";
  $("#missions").replaceChildren(...(rows.length ? rows.map((m) => {
    let steps = []; try { steps = JSON.parse(m.steps); } catch { /* none */ }
    return h("article", { class: "card", "data-status": m.status },
      h("h3", {}, m.goal),
      h("span", { class: "meta" }, `#${m.id} · ${MSTATUS[m.status] || m.status} · ${date(m.updated_at)}`),
      steps.length ? h("p", {}, steps.map((s, i) => `${s.ok ? "✓" : "✗"} ${i + 1}. ${s.step}`).join("\n")) : null,
      m.error ? h("p", {}, `Erreur : ${m.error}`) : null,
      m.report ? h("details", {}, h("summary", {}, "Rapport"), h("pre", {}, m.report)) : null);
  }) : [h("p", { class: "empty-cards" }, "Aucune mission. Demande-en une à Spectre ou lance-la ici.")]));
}

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
const FIELDS = [
  ["user_name", "Ton prénom", "text", "Spectre l'utilise pour s'adresser à toi."],
  ["city", "Ta ville", "text", "Pour la météo du briefing."],
  ["brain_model", "Modèle de conversation", ["haiku", "sonnet", "opus"], "haiku répond plus vite, opus réfléchit plus."],
  ["mission_model", "Modèle des missions", ["haiku", "sonnet", "opus"], ""],
  ["briefing_hour", "Heure du briefing", "number", "Le briefing du matin apparaît à partir de cette heure."],
  ["auto_max_level", "Autonomie (0 à 2)", "number", "Au-dessus de ce niveau de risque, Spectre demande ta validation. Supprimer, envoyer ou toucher au système demande toujours ton accord."],
  ["tts_voice", "Voix", ["fr_FR-upmc-medium", "fr_FR-gilles-low", "fr_FR-tom-medium"], "Voix d'homme ; pour fr_FR-upmc-medium, mets le locuteur « pierre »."],
  ["tts_speaker", "Locuteur", "text", ""],
  ["tts_effect", "Timbre", ["futuriste", "androide", "hologramme", "vaisseau", "aucun"], "futuriste : IA de bord grave et métallique ; androide : robot vocodé ; hologramme : chœur scintillant ; vaisseau : discret ; aucun : voix naturelle."],
  ["speak_initiatives", "Annoncer les initiatives à voix haute", "checkbox", ""],
];
async function loadSettings() {
  const cfg = await api("GET", "config");
  const form = $("#settings-form");
  form.replaceChildren(...FIELDS.map(([key, label, type, help]) => {
    let input;
    if (Array.isArray(type)) input = h("select", { name: key }, ...type.map((o) => h("option", { value: o, selected: cfg[key] === o }, o)));
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
  $("#brain-model").textContent = `cerveau : ${s.brain_model}`;
  $("#talk-btn").hidden = !voiceAvailable;
  $("#count-approvals").textContent = s.pending_approvals || "";
  $("#count-initiatives").textContent = s.pending_initiatives || "";
  $("#count-facts").textContent = s.facts || "";
  $("#count-missions").textContent = s.missions_running || "";
  if (!document.body.dataset.voice || document.body.dataset.voice === "off") setState(s.voice);
}
const LOADERS = { talk: loadHistory, approvals: loadApprovals, missions: loadMissions, memory: loadFacts, initiatives: loadInitiatives, audit: loadAudit, settings: loadSettings };
function show(view) {
  $$(".as-nav button").forEach((b) => b.setAttribute("aria-current", String(b.dataset.view === view)));
  $$(".as-view").forEach((v) => { v.hidden = v.dataset.view !== view; });
  closeDrawers();
  LOADERS[view]?.().catch((e) => toast(e.message, "error"));
  history.replaceState(null, "", `#${view}`);
}
function closeDrawers() { document.body.classList.remove("rail-open", "inspector-open"); $(".scrim").hidden = true; }

/* ---- live events ---- */
function connect() {
  const es = new EventSource("/api/assistant/events");
  es.addEventListener("state", (e) => { const d = JSON.parse(e.data); setState(d.state, d.detail); });
  es.addEventListener("message", (e) => { const d = JSON.parse(e.data); addLine(d.role, d.text, d.error); });
  es.addEventListener("approval", () => { loadApprovals(); toast("Spectre attend ta validation pour une action.", "warn", 6000); });
  es.addEventListener("approval_done", () => loadApprovals());
  es.addEventListener("initiative", (e) => { const d = JSON.parse(e.data); toast(`${d.title}${d.body ? ` — ${d.body}` : ""}`, "ok", 8000); loadInitiatives(); loadMissions(); });
  es.addEventListener("initiative_row", () => loadInitiatives());
  es.onerror = () => setState("off", "Connexion perdue, reconnexion…");
}

/* ---- wiring ---- */
$("#as-nav").addEventListener("click", (e) => { const b = e.target.closest("[data-view]"); if (b) show(b.dataset.view); });
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-action]")?.dataset.action;
  if (a === "close-drawers") closeDrawers();
  if (a === "open-rail") { document.body.classList.add("rail-open"); $(".scrim").hidden = false; }
  if (a === "open-inspector") { document.body.classList.add("inspector-open"); $(".scrim").hidden = false; }
  if (a === "talk") api("POST", "talk", {}).catch((err) => toast(err.message, "error"));
});
$("#say-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#say"); const text = input.value.trim();
  if (!text) return;
  input.value = ""; $("#send").disabled = true;
  try { await api("POST", "chat", { text }); } catch (err) { toast(err.message, "error"); }
  finally { $("#send").disabled = false; input.focus(); loadStatus(); }
});
$("#say").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !matchMedia("(pointer: coarse)").matches) { e.preventDefault(); $("#say-form").requestSubmit(); } });
$("#mission-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const goal = $("#mission-goal").value.trim(); if (!goal) return;
  try { const r = await api("POST", "missions", { goal, kind: $("#mission-kind").value }); toast(r.result); $("#mission-goal").value = ""; loadMissions(); }
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
  try {
    await loadStatus();
    await Promise.all([loadApprovals(), loadInitiatives()]);
    show(LOADERS[location.hash.slice(1)] ? location.hash.slice(1) : "talk");
    connect();
  } catch (err) {
    setState("off", `L'assistant n'est pas lancé ici (${err.message}). Démarre-le avec : uv run python -m spectre.assistant`);
  }
})();
addEventListener("hashchange", () => { const v = location.hash.slice(1); if (LOADERS[v]) show(v); });
