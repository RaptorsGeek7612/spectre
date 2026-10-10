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
if (REMOTE) document.body.classList.add("remote-device");  // already on the phone
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
const MSTATUS = { queued: "en file", running: "en cours", done: "terminée", failed: "échouée" };
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
      m.report ? h("details", {}, h("summary", {}, "Rapport"), h("pre", {}, m.report)) : null);
  }) : [h("p", { class: "empty-cards" }, "Aucune mission. Demande-en une à Spectre ou lance-la ici.")]));
}

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
  return h("article", { class: "ag-card", "data-agent": a.key },
    h("h3", { class: "ag-name" }, a.name),
    h("p", { class: "ag-engine" }, a.engine),
    a.role ? h("p", { class: "ag-role" }, a.role) : null,
    tags.length ? h("div", { class: "ag-tags" }, tags) : null);
}
async function loadAgents() {
  agentsCache = null;
  const data = await fetchAgents();
  $("#count-agents").textContent = data.assistant.length + data.redaction.length;
  $("#agents").replaceChildren(...data.assistant.map(agentCard));
  $("#agents-redaction").replaceChildren(...data.redaction.map(agentCard));
}
async function fillAgentSelect() {
  const select = $("#mission-agent");
  if (select.options.length > 1) return;
  const data = await fetchAgents();
  select.append(...data.assistant.filter((a) => a.key !== "opus").map((a) => h("option", { value: a.key }, a.name)));
}

/* ---- remote access: Spectre on the phone through Tailscale ---- */
async function loadRemote() {
  const r = await api("GET", "remote");
  $("#remote-hint").textContent = r.hint || "";
  $("#remote-qr").innerHTML = r.qr || "";  // SVG drawn by Spectre itself, from Tailscale's name
  const check = (label, ok, yes, no) => [h("dt", {}, label), h("dd", { class: ok ? "ok" : "ko" }, ok ? yes : no)];
  $("#remote-checks").replaceChildren(
    ...check("Tailscale", r.installed && r.running, "connecté", r.installed ? "arrêté ou déconnecté" : "pas installé"),
    ...check("Mot de passe", r.password, "défini", "absent"),
    ...check("Accès à distance", r.serving, "actif", "inactif"));
  $("#remote-url-row").hidden = !r.url;
  $("#remote-url").textContent = r.url; $("#remote-url").href = r.url || "#";
  $("#remote-enable").hidden = !(r.running && r.password && !r.serving);
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
  ["brain_model", "Spectre, l'agent supérieur", ["opus", "sonnet", "haiku"], "opus = Opus 5.5 : le plus capable ; il planifie aussi les missions et rédige leurs rapports."],
  ["mission_model", "Agents d'exécution des missions", ["sonnet", "opus", "haiku", "chatgpt", "mistral"], "Gétro = Sonnet 5.5 ; Kaïto = Haiku 4.5, plus rapide (il vérifie aussi chaque étape) ; Kyra = ChatGPT via Codex (compte ChatGPT) ; Syfer = Mistral via Vibe (compte Le Chat). Quoi qu'il en soit, Spectre confie d'office le multimédia à Kyra et la cybersécurité à Syfer."],
  ["chatgpt_model", "Modèle ChatGPT", "text", "Vide = le modèle par défaut de Codex pour ton compte ChatGPT (par exemple gpt-5.5)."],
  ["mistral_model", "Modèle Mistral", "text", "Vide = le modèle par défaut de Vibe (mistral-medium-3.5). Vibe utilise ton compte Le Chat, ou une clé MISTRAL_API_KEY dans ~/.spectre/assistant/vibe/.env."],
  ["briefing_hour", "Heure du briefing", "number", "Le briefing du matin apparaît à partir de cette heure."],
  ["auto_max_level", "Autonomie (0 à 2)", "number", "Au-dessus de ce niveau de risque, Spectre demande ta validation. Supprimer, envoyer ou toucher au système demande toujours ton accord."],
  ["tts_voice", "Voix", ["fr_FR-upmc-medium", "fr_FR-gilles-low", "fr_FR-tom-medium"], "Voix d'homme ; pour fr_FR-upmc-medium, mets le locuteur « pierre »."],
  ["tts_speaker", "Locuteur", "text", ""],
  ["tts_pace", "Débit de la voix", ["naturel", "pose", "vif"], "naturel : comme une conversation ; pose : plus lent ; vif : plus rapide."],
  ["tts_effect", "Timbre", ["futuriste", "androide", "hologramme", "vaisseau", "aucun"], "futuriste : IA de bord grave et métallique ; androide : robot vocodé ; hologramme : chœur scintillant ; vaisseau : discret ; aucun : voix naturelle."],
  ["speak_initiatives", "Annoncer les initiatives à voix haute", "checkbox", ""],
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
  if (!document.body.dataset.voice || document.body.dataset.voice === "off") setState(s.voice);
}
const LOADERS = { talk: loadHistory, approvals: loadApprovals, missions: () => Promise.all([loadMissions(), fillAgentSelect()]), agents: loadAgents, memory: loadFacts, initiatives: loadInitiatives, audit: loadAudit, settings: () => Promise.all([loadSettings(), loadFaces()]) };
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
    if ((spoke && now - lastVoice > 1300) || (!spoke && now - started > 7000) || now - started > 25000) finishRecording();
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
  es.addEventListener("arrival", (e) => { const d = JSON.parse(e.data); caption("#said", d.text, 8000); });
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
  try { await api("POST", "chat", { text }); } catch (err) { toast(err.message, "error"); }
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
addEventListener("hashchange", () => { const v = location.hash.slice(1); if (LOADERS[v]) show(v); });
