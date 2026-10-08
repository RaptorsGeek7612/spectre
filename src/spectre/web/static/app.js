// Spectre web interface. Plain ES module, no build step.
// Two backends: HttpBackend (the `spectre-web` server) and LocalBackend (showcase mode: no
// server, demo answers, history kept in this browser).

const AGENTS = ["scout", "scribe", "warden"];
const OUTPUT = { scout: "brief", scribe: "draft", warden: "final_text" };
const TAB_OF = { scout: "brief", scribe: "draft", warden: "final" };
const NAME = { scout: "Scout", scribe: "Scribe", warden: "Warden" };

/* ============================== i18n ================================================== */
const I18N = {
  fr: {
    "login.password": "Mot de passe", "login.submit": "Entrer",
    "rail.new": "Nouvelle plaque", "rail.search": "Rechercher, #tag…", "rail.allProjects": "Tous les projets",
    "rail.archives": "Archives", "rail.settings": "Réglages",
    "composer.placeholder": "Décris le texte à produire…  ( / pour les commandes )",
    "composer.preset": "Préréglage", "composer.demo": "Démo", "composer.send": "Exposer", "composer.stop": "Arrêter",
    "state.idle": "en attente", "state.live": "expose…", "state.done": "terminé", "state.error": "échec",
    "state.cancelled": "arrêté", "state.truncated": "tronqué", "state.fallback": "repli",
    "empty.lede": "Trois agents Claude en chaîne. Scout cadre la demande, Scribe rédige, Warden relit et corrige.",
    "tab.final": "Texte final", "tab.draft": "Brouillon", "tab.brief": "Brief", "tab.diff": "Corrections",
    "tab.request": "Demande", "tab.raw": "Brut",
    "insp.title": "Mesures", "set.title": "Réglages", "set.prefs": "Préférences", "set.presets": "Préréglages",
    "set.history": "Historique", "set.system": "Système", "palette.placeholder": "Commande ou plaque…",
    "group.pinned": "Épinglées", "group.today": "Aujourd'hui", "group.yesterday": "Hier",
    "group.week": "Cette semaine", "group.older": "Plus ancien", "runs.empty": "Aucune plaque pour l'instant.",
    "runs.noMatch": "Aucune plaque ne correspond.",
  },
  en: {
    "login.password": "Password", "login.submit": "Enter",
    "rail.new": "New plate", "rail.search": "Search, #tag…", "rail.allProjects": "All projects",
    "rail.archives": "Archive", "rail.settings": "Settings",
    "composer.placeholder": "Describe the text to produce…  ( / for commands )",
    "composer.preset": "Preset", "composer.demo": "Demo", "composer.send": "Expose", "composer.stop": "Stop",
    "state.idle": "waiting", "state.live": "exposing…", "state.done": "done", "state.error": "failed",
    "state.cancelled": "stopped", "state.truncated": "truncated", "state.fallback": "fallback",
    "empty.lede": "Three Claude agents in a chain. Scout frames the request, Scribe writes, Warden reviews and corrects.",
    "tab.final": "Final text", "tab.draft": "Draft", "tab.brief": "Brief", "tab.diff": "Corrections",
    "tab.request": "Request", "tab.raw": "Raw",
    "insp.title": "Readings", "set.title": "Settings", "set.prefs": "Preferences", "set.presets": "Presets",
    "set.history": "History", "set.system": "System", "palette.placeholder": "Command or plate…",
    "group.pinned": "Pinned", "group.today": "Today", "group.yesterday": "Yesterday",
    "group.week": "This week", "group.older": "Older", "runs.empty": "No plates yet.",
    "runs.noMatch": "No plate matches.",
  },
};
let lang = "fr";
const t = (key) => (I18N[lang] && I18N[lang][key]) || I18N.fr[key] || key;
function applyI18n() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((n) => { n.placeholder = t(n.dataset.i18nPlaceholder); });
}

/* ============================== utils ================================================= */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
function h(tag, attrs = {}, ...children) {
  const node = tag === "svg" ? document.createElementNS("http://www.w3.org/2000/svg", "svg") : document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value === null || value === undefined) continue;
    if (key === "class") node.setAttribute("class", value);
    else if (key === "style") node.setAttribute("style", value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "html") node.innerHTML = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const plateNo = (n) => `N° ${String(n ?? 0).padStart(4, "0")}`;
const fmtInt = (n) => (n ?? 0).toLocaleString(lang === "fr" ? "fr-FR" : "en-US");
const fmtCost = (c) => (c === null || c === undefined ? "n/d" : `${c.toLocaleString(lang === "fr" ? "fr-FR" : "en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 })} $`);
const fmtSec = (s) => (s === undefined || s === null ? "—" : `${s.toLocaleString(lang === "fr" ? "fr-FR" : "en-US", { maximumFractionDigits: 1 })} s`);
const store = {
  get(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
};
/* ============================== voice button (when the assistant runs) =================== */
const VOICE_LABELS = { sleeping: "Parler à Spectre", listening: "J'écoute…", thinking: "Je réfléchis…", speaking: "Spectre parle", off: "Ouvrir l'assistant" };
let voiceEvents = null;
function voiceFab() {
  const fab = $("#voice-fab");
  if (voiceEvents) return;
  fab.hidden = false;
  const show = (state) => {
    fab.dataset.voice = state;
    $("#voice-label").textContent = VOICE_LABELS[state] || VOICE_LABELS.sleeping;
    if (state !== "listening" && state !== "speaking") fab.style.setProperty("--lvl", "0");
  };
  fetch("/api/assistant/status", { credentials: "same-origin" })
    .then((r) => r.json()).then((s) => show(s.voice_available ? s.voice : "off")).catch(() => show("off"));
  voiceEvents = new EventSource("/api/assistant/events");
  voiceEvents.addEventListener("state", (e) => { const d = JSON.parse(e.data); if (d.state !== "heard") show(d.state); });
  voiceEvents.addEventListener("level", (e) => fab.style.setProperty("--lvl", String(JSON.parse(e.data).v)));
  fab.addEventListener("click", async () => {
    if (fab.dataset.voice === "off") { location.href = "assistant.html"; return; }
    try {
      const r = await fetch("/api/assistant/talk", { method: "POST", credentials: "same-origin", headers: { "X-Spectre": "1", "Content-Type": "application/json" }, body: "{}" });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`);
    } catch (err) { toast(err.message, "error"); }
  });
}

function toast(message, kind = "ok", ms = 3800) {
  const node = h("div", { class: "toast", "data-kind": kind, role: kind === "error" ? "alert" : "status" }, message);
  $("#toasts").append(node);
  setTimeout(() => node.remove(), ms);
}
async function download(name, text, type) {
  if (state.backend?.kind === "local") {
    // Showcase pages run in a sandbox that blocks downloads: hand the content over by clipboard.
    const ok = await copyText(text);
    toast(ok ? `${name} : contenu copié dans le presse-papiers (téléchargement indisponible dans la vitrine).` : "Copie impossible dans ce navigateur.", ok ? "ok" : "error", 6000);
    return;
  }
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = h("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch {
    const area = h("textarea", { style: "position:fixed;opacity:0" }); area.value = text;
    document.body.append(area); area.select();
    const ok = document.execCommand("copy"); area.remove(); return ok;
  }
}

/* ============================== markdown (safe subset) ================================ */
function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}
function markdown(src) {
  const lines = String(src ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let para = [], list = null, code = null;
  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`<${list.type}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.type}>`); list = null; } };
  for (const line of lines) {
    if (code) {
      if (/^```/.test(line)) { out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`); code = null; } else code.push(line);
      continue;
    }
    if (/^```/.test(line)) { flushPara(); flushList(); code = []; continue; }
    const head = line.match(/^(#{1,3})\s+(.*)$/);
    if (head) { flushPara(); flushList(); out.push(`<h${head[1].length}>${inline(head[2])}</h${head[1].length}>`); continue; }
    const ul = line.match(/^\s*[-*•]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      flushPara();
      const type = ul ? "ul" : "ol";
      if (!list || list.type !== type) { flushList(); list = { type, items: [] }; }
      list.items.push((ul || ol)[1]);
      continue;
    }
    if (/^>\s?/.test(line)) { flushPara(); flushList(); out.push(`<blockquote>${inline(line.replace(/^>\s?/, ""))}</blockquote>`); continue; }
    if (!line.trim()) { flushPara(); flushList(); continue; }
    if (list) flushList();
    para.push(line.trim());
  }
  if (code) out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
  flushPara(); flushList();
  return out.join("\n");
}

/* ============================== word diff (Warden's errata) =========================== */
function wordDiff(a, b) {
  const A = String(a).split(/(\s+)/), B = String(b).split(/(\s+)/);
  if (A.length * B.length > 9e6) return null;
  const n = A.length, m = B.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const parts = []; let i = 0, j = 0;
  const push = (kind, s) => { const last = parts[parts.length - 1]; if (last && last.kind === kind) last.s += s; else parts.push({ kind, s }); };
  while (i < n && j < m) {
    if (A[i] === B[j]) { push("same", A[i]); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) { push("del", A[i]); i++; } else { push("ins", B[j]); j++; }
  }
  while (i < n) push("del", A[i++]);
  while (j < m) push("ins", B[j++]);
  // Read each correction as one erratum: everything removed, then everything added, even when the
  // LCS interleaves words of a rewritten phrase (only whitespace may sit between its pieces).
  const grouped = [];
  for (let k = 0; k < parts.length;) {
    if (parts[k].kind === "same") { grouped.push(parts[k]); k++; continue; }
    let del = "", ins = "", end = k;
    for (let x = k; x < parts.length; x++) {
      const p = parts[x];
      if (p.kind === "same") {
        // A kept stretch joins the erratum only if it is whitespace or one word between two changes.
        const next = parts[x + 1];
        const bridge = next && next.kind !== "same" && !p.s.includes("\n") && (!p.s.trim() || /^\s*\S+\s*$/.test(p.s));
        if (!bridge) break;
      }
      if (p.kind === "del") del += p.s; else if (p.kind === "ins") ins += p.s; else { del += p.s; ins += p.s; }
      end = x + 1;
    }
    if (del.trim()) grouped.push({ kind: "del", s: del.trim() });
    if (del.trim() && ins.trim()) grouped.push({ kind: "same", s: " " });
    if (ins.trim()) grouped.push({ kind: "ins", s: ins.trim() });
    const tail = (del + ins).match(/\s+$/);
    if (tail && parts[end] && !/^\s/.test(parts[end].s)) grouped.push({ kind: "same", s: tail[0].includes("\n") ? tail[0] : " " });
    k = end;
  }
  return grouped;
}

// Render diff parts with the text's block structure: headings, list items and paragraphs.
function diffHtml(parts) {
  const marked = parts.map((p) => (p.kind === "same" ? esc(p.s) : `<${p.kind}>${esc(p.s)}</${p.kind}>`)).join("");
  const blocks = [];
  let para = [];
  const flush = () => { if (para.length) { blocks.push(`<p>${para.join(" ")}</p>`); para = []; } };
  for (const line of marked.split("\n")) {
    const plain = line.replace(/<\/?(del|ins)>/g, "");
    const head = plain.match(/^\s{0,3}(#{1,3})\s/);
    if (head) { flush(); const n = head[1].length; blocks.push(`<h${n}>${line.replace(/#{1,3}\s+/, "")}</h${n}>`); continue; }
    if (/^\s*[-*•]\s/.test(plain)) { flush(); blocks.push(`<p class="diff-li">· ${line.replace(/[-*•]\s+/, "")}</p>`); continue; }
    if (!plain.trim()) { flush(); continue; }
    para.push(line.trim());
  }
  flush();
  return blocks.join("");
}

/* ============================== backends ============================================== */
class HttpBackend {
  constructor() { this.kind = "http"; }
  async call(method, path, body) {
    const opts = { method, headers: { "X-Spectre": "1" }, credentials: "same-origin" };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { const err = new Error(data.error || `HTTP ${res.status}`); err.status = res.status; throw err; }
    return data;
  }
  status() { return this.call("GET", "/api/status"); }
  login(password) { return this.call("POST", "/api/login", { password }); }
  logout() { return this.call("POST", "/api/logout", {}); }
  listRuns(q, archived) { return this.call("GET", `/api/runs?q=${encodeURIComponent(q)}&archived=${archived ? 1 : 0}`); }
  getRun(id) { return this.call("GET", `/api/runs/${id}`); }
  updateRun(id, changes) { return this.call("POST", `/api/runs/${id}`, changes); }
  deleteRun(id) { return this.call("DELETE", `/api/runs/${id}`); }
  duplicateRun(id) { return this.call("POST", `/api/runs/${id}/duplicate`, {}); }
  cancelRun(id) { return this.call("POST", `/api/runs/${id}/cancel`, {}); }
  getSettings() { return this.call("GET", "/api/settings"); }
  saveSettings(changes) { return this.call("POST", "/api/settings", changes); }
  getPresets() { return this.call("GET", "/api/presets"); }
  savePreset(name, overrides) { return this.call("POST", "/api/presets", { name, overrides }); }
  deletePreset(name) { return this.call("DELETE", `/api/presets/${encodeURIComponent(name)}`); }
  importRuns(runs) { return this.call("POST", "/api/import", { runs }); }
  clearRuns() { return this.call("POST", "/api/clear", {}); }
  async exportAll() { const res = await fetch("/api/export", { credentials: "same-origin" }); return res.text(); }
  async exportRun(run, fmt) { const res = await fetch(`/api/runs/${run.id}/export?format=${fmt}`, { credentials: "same-origin" }); return res.text(); }
  async run(body, onEvent, signal) {
    const res = await fetch("/api/run", {
      method: "POST", credentials: "same-origin", signal,
      headers: { "Content-Type": "application/json", "X-Spectre": "1" }, body: JSON.stringify(body),
    });
    if (!res.ok || !res.body) { const data = await res.json().catch(() => ({})); throw new Error(data.error || `HTTP ${res.status}`); }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut); buffer = buffer.slice(cut + 2);
        const data = block.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
        if (data) onEvent(JSON.parse(data));
      }
    }
  }
}

class LocalBackend {
  // Showcase mode: everything in this browser, demo answers only.
  constructor(demo) {
    this.kind = "local";
    this.demo = demo;
    this.runs = store.get("spectre.runs", []);
    this.settings = { theme: "dark", font_size: "medium", send_key: "ctrl-enter", show_costs: true, notifications: false, language: "fr", preset: "Standard", demo: true, ...store.get("spectre.settings", {}) };
    this.userPresets = store.get("spectre.presets", {});
    this.cancelled = new Set();
  }
  persist() { store.set("spectre.runs", this.runs); }
  async status() {
    return { version: "vitrine", auth_required: false, authenticated: true, has_api_key: false, workspace_configured: false, agents: this.demo.agents, effort_levels: ["low", "medium", "high", "xhigh", "max"], builtin_presets: Object.keys(this.demo.presets), state_dir: "navigateur (localStorage)", showcase: true };
  }
  summary(r) { const { id, number, title, created_at, status, demo, pinned, archived, project, tags, total_cost_usd } = r; return { id, number, title, created_at, status, demo, pinned, archived, project, tags, total_cost_usd }; }
  async listRuns(q, archived) {
    const needle = q.trim().toLowerCase().replace(/^#/, "");
    const rows = this.runs.filter((r) => !!r.archived === !!archived).filter((r) => !needle || `${r.title} ${r.request} ${r.final_text} ${r.project} ${(r.tags || []).join(" ")}`.toLowerCase().includes(needle));
    rows.sort((a, b) => (b.pinned - a.pinned) || b.created_at.localeCompare(a.created_at));
    return rows.map((r) => this.summary(r));
  }
  find(id) { const r = this.runs.find((x) => x.id === id); if (!r) throw new Error("introuvable"); return r; }
  async getRun(id) { return structuredClone(this.find(id)); }
  async updateRun(id, changes) {
    const r = this.find(id);
    for (const [k, v] of Object.entries(changes)) {
      if (k === "tags") r.tags = [...new Set(v.map((x) => String(x).trim().replace(/^#/, "")).filter(Boolean))].sort();
      else if (k === "pinned" || k === "archived") r[k] = !!v;
      else r[k] = String(v).trim().slice(0, 120);
    }
    r.updated_at = new Date().toISOString(); this.persist(); return structuredClone(r);
  }
  async deleteRun(id) { this.runs = this.runs.filter((r) => r.id !== id); this.persist(); return { ok: true }; }
  nextNumber() { const n = store.get("spectre.counter", 1); store.set("spectre.counter", n + 1); return n; }
  newId() { return [...crypto.getRandomValues(new Uint8Array(8))].map((b) => b.toString(16).padStart(2, "0")).join(""); }
  async duplicateRun(id) { const r = structuredClone(this.find(id)); r.id = this.newId(); r.number = this.nextNumber(); r.title = `${r.title} (copie)`; r.pinned = false; r.created_at = new Date().toISOString(); this.runs.push(r); this.persist(); return r; }
  async cancelRun(id) { this.cancelled.add(id); return { ok: true }; }
  async getSettings() { return { ...this.settings }; }
  async saveSettings(changes) { Object.assign(this.settings, changes); store.set("spectre.settings", this.settings); return { ...this.settings }; }
  async getPresets() { return { ...this.demo.presets, ...this.userPresets }; }
  async savePreset(name, overrides) { if (!name.trim()) throw new Error("nom requis"); this.userPresets[name.trim()] = overrides; store.set("spectre.presets", this.userPresets); return this.getPresets(); }
  async deletePreset(name) { delete this.userPresets[name]; store.set("spectre.presets", this.userPresets); return this.getPresets(); }
  async importRuns(runs) { let n = 0; for (const item of runs) { if (!item || !item.request) continue; this.runs.push({ ...item, id: this.newId(), number: this.nextNumber() }); n++; } this.persist(); return { imported: n }; }
  async clearRuns() { const n = this.runs.length; this.runs = []; this.persist(); return { deleted: n }; }
  async exportAll() { return JSON.stringify({ spectre: "vitrine", runs: this.runs }, null, 2); }
  async exportRun(run, fmt) { return fmt === "json" ? JSON.stringify(run, null, 2) : fmt === "html" ? shareHtml(run) : runMarkdown(run); }
  cost(model, inp, out) { const p = this.demo.prices[model]; return p ? Math.round((inp * p[0] + out * p[1]) / 1e6 * 1e6) / 1e6 : null; }
  async run(body, onEvent, signal) {
    const now = new Date().toISOString();
    const run = { id: this.newId(), number: this.nextNumber(), title: body.request.trim().split("\n")[0].slice(0, 60), request: body.request.trim(), created_at: now, updated_at: now, status: "running", demo: true, preset: body.preset, overrides: body.overrides || {}, pinned: false, archived: false, project: "", tags: [], brief: "", draft: "", final_text: "", usage: [], total_cost_usd: null, durations: {}, error: null, error_agent: null };
    this.runs.push(run); this.persist();
    onEvent({ type: "run", run: structuredClone(run) });
    let draft = this.demo.final; for (const [right, wrong] of this.demo.draft_slips) draft = draft.replace(right, wrong);
    const texts = { scout: this.demo.brief.replace("{request}", run.request), scribe: draft, warden: this.demo.final };
    const models = Object.fromEntries(this.demo.agents.map((a) => [a.name, (body.overrides || {})[`SPECTRE_${a.name.toUpperCase()}_MODEL`] || a.model]));
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    let promptTokens = Math.ceil(run.request.length / 4) + 180;
    const finish = (type, extra = {}) => {
      run.status = type === "done" ? "done" : type;
      run.total_cost_usd = run.usage.reduce((s, u) => s + (u.cost_usd || 0), 0) || null;
      Object.assign(run, extra); this.persist();
      onEvent({ type, ...structuredClone(run), run: structuredClone(run), agent: extra.error_agent });
    };
    for (const agent of AGENTS) {
      onEvent({ type: "agent_start", agent });
      const started = performance.now();
      const words = texts[agent].split(" ");
      for (let i = 0; i < words.length; i++) {
        if (signal?.aborted || this.cancelled.has(run.id)) { finish("cancelled", { error: "arrêtée par l'utilisateur", error_agent: agent }); return; }
        const piece = i ? ` ${words[i]}` : words[i];
        run[OUTPUT[agent]] += piece;
        onEvent({ type: "token", agent, text: piece });
        if (i % 3 === 0) await sleep(agent === "scout" ? 14 : 9);
      }
      const out = Math.ceil(texts[agent].length / 4);
      const usage = { agent, model: models[agent], input_tokens: promptTokens, output_tokens: out, cost_usd: this.cost(models[agent], promptTokens, out), truncated: false };
      promptTokens += out;
      run.usage.push(usage);
      run.durations[agent] = Math.round(performance.now() - started) / 1000;
      onEvent({ type: "agent_done", agent, text: run[OUTPUT[agent]], usage, seconds: run.durations[agent] });
    }
    finish("done");
  }
}

function runMarkdown(run) {
  const usage = (run.usage || []).map((u) => `| ${u.agent} | ${u.model} | ${u.input_tokens} | ${u.output_tokens} | ${u.cost_usd ?? "n/d"} |`).join("\n");
  return `# Spectre — plaque ${plateNo(run.number)}${run.demo ? " (démo)" : ""}\n\n*${run.created_at}* · statut : ${run.status}\n\n## Demande\n\n${run.request}\n\n## Texte final (Warden)\n\n${run.final_text || "_(aucun)_"}\n\n## Brouillon (Scribe)\n\n${run.draft || "_(aucun)_"}\n\n## Brief (Scout)\n\n${run.brief || "_(aucun)_"}\n\n## Coûts\n\n| Agent | Modèle | Entrée | Sortie | Coût ($) |\n|---|---|---|---|---|\n${usage}\n`;
}
function shareHtml(run) {
  return `<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Spectre — ${plateNo(run.number)}</title><style>body{margin:0;background:#121315;color:#e9e4d8;font:16px/1.7 system-ui,sans-serif}main{max-width:72ch;margin:0 auto;padding:48px 20px}h1{font-size:14px;letter-spacing:.3em;text-transform:uppercase;color:#b3aea2}.final{background:#1b1c1f;border:1px solid #34363b;padding:28px;white-space:pre-wrap}pre{white-space:pre-wrap;color:#b3aea2}</style></head><body><main><h1>Spectre · ${plateNo(run.number)}</h1><p>${esc(run.request)}</p><div class="final">${esc(run.final_text)}</div><details><summary>Brouillon</summary><pre>${esc(run.draft)}</pre></details><details><summary>Brief</summary><pre>${esc(run.brief)}</pre></details></main></body></html>`;
}

/* ============================== state ================================================= */
const state = {
  backend: null, status: null, settings: null, presets: {}, runs: [], projects: [],
  current: null, tab: "final", tabPinned: false, running: null, archived: false, query: "", project: "",
};

/* ============================== theme, continuum ====================================== */
function applySettings() {
  const s = state.settings;
  lang = s.language === "en" ? "en" : "fr";
  const dark = s.theme === "system" ? !matchMedia("(prefers-color-scheme: light)").matches : s.theme !== "light";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.dataset.font = s.font_size;
  $('meta[name="theme-color"]').content = dark ? "#121315" : "#e9e5da";
  applyI18n();
  drawContinuum();
}
function drawContinuum() {
  // Procedurally banded charcoal continuum with faint absorption lines (seeded: stable per load).
  const host = $(".continuum");
  let canvas = host.querySelector("canvas");
  if (!canvas) { canvas = h("canvas"); host.append(canvas); }
  const w = host.clientWidth || 1200, hgt = host.clientHeight || 188;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.round(w * dpr); canvas.height = Math.round(hgt * dpr);
  const ctx = canvas.getContext("2d");
  const light = document.documentElement.dataset.theme === "light";
  let seed = 7;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const base = light ? [226, 221, 208] : [23, 24, 27];
  for (let x = 0; x < canvas.width; x += Math.max(1, Math.round(dpr))) {
    const band = (rnd() - 0.5) * (light ? 10 : 9) + Math.sin(x / (canvas.width / 9)) * 3;
    const centre = 1 - Math.abs(x / canvas.width - 0.55) * 0.9;
    const k = light ? band - centre * 4 : band + centre * 10;
    ctx.fillStyle = `rgb(${base.map((c) => Math.max(0, Math.min(255, Math.round(c + k)))).join(",")})`;
    ctx.fillRect(x, 0, Math.max(1, Math.round(dpr)), canvas.height);
  }
  ctx.globalAlpha = light ? 0.12 : 0.18;
  ctx.fillStyle = light ? "#000" : "#fff";
  for (let i = 0; i < 26; i++) ctx.fillRect(Math.round(rnd() * canvas.width), 0, 1, canvas.height);
  ctx.globalAlpha = 1;
}

/* ============================== spectrogram + inspector =============================== */
function configuredModel(agent, run) {
  const spec = (state.status?.agents || []).find((a) => a.name === agent);
  const over = run?.overrides?.[`SPECTRE_${agent.toUpperCase()}_MODEL`];
  return over || spec?.model || "";
}
function shortModel(id) {
  const m = String(id).match(/^claude-(\w+)-(\d+)(?:-(\d+))?/);
  return m ? `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}${m[3] ? `.${m[3]}` : ""}` : id;
}
function agentStates(run) {
  const states = {};
  for (const agent of AGENTS) {
    const usage = (run?.usage || []).find((u) => u.agent === agent);
    let st = "idle";
    if (usage) st = usage.truncated ? "truncated" : usage.model !== configuredModel(agent, run) ? "fallback" : "done";
    if (run && run.error_agent === agent) st = run.status === "cancelled" ? "cancelled" : "error";
    if (state.running && state.running.live === agent) st = "live";
    states[agent] = st;
  }
  return states;
}
function renderAgents() {
  const run = state.current;
  const states = agentStates(run);
  for (const node of $$(".agent")) {
    const agent = node.dataset.agent;
    node.dataset.state = states[agent];
    $(".agent-model", node).textContent = shortModel(configuredModel(agent, run));
    const usage = (run?.usage || []).find((u) => u.agent === agent);
    const sec = run?.durations?.[agent];
    $(".agent-status", node).textContent = states[agent] === "done" || states[agent] === "fallback" || states[agent] === "truncated"
      ? `${t(`state.${states[agent]}`)} · ${fmtSec(sec)}${state.settings.show_costs ? ` · ${fmtCost(usage?.cost_usd)}` : ""}`
      : t(`state.${states[agent]}`);
  }
  document.body.dataset.done = AGENTS.filter((a) => ["done", "fallback", "truncated"].includes(states[a])).join(" ");
}
function magnitude(cost) {
  const size = cost ? Math.max(4, Math.min(16, 4 + 4 * Math.log10(1 + cost * 1000))) : 3;
  return h("i", { class: "mag", style: `width:${size}px;height:${size}px`, "aria-hidden": "true" });
}
function renderInspector() {
  const body = $("#inspector-body");
  body.replaceChildren();
  const run = state.current;
  const states = agentStates(run);
  for (const agent of AGENTS) {
    const usage = (run?.usage || []).find((u) => u.agent === agent);
    const conf = configuredModel(agent, run);
    const fallback = usage && usage.model !== conf;
    body.append(h("section", { class: "m-agent", "data-agent": agent, "data-state": usage ? "done" : "idle", "data-fallback": fallback ? "true" : null, "data-truncated": usage?.truncated ? "true" : null },
      h("div", { class: "m-name" }, h("b", {}, NAME[agent]), h("span", { class: "m-model" }, shortModel(usage?.model || conf))),
      fallback ? h("div", { class: "m-note" }, `repli : ${shortModel(usage.model)} a répondu à la place de ${shortModel(conf)}`) : null,
      usage?.truncated ? h("div", { class: "m-note" }, "réponse tronquée (max_tokens)") : null,
      h("dl", { class: "m-grid" },
        h("div", {}, h("dt", {}, "Entrée"), h("dd", {}, usage ? fmtInt(usage.input_tokens) : "—")),
        h("div", {}, h("dt", {}, "Sortie"), h("dd", {}, usage ? fmtInt(usage.output_tokens) : "—")),
        h("div", {}, h("dt", {}, "Durée"), h("dd", {}, fmtSec(run?.durations?.[agent]))),
      ),
      state.settings.show_costs ? h("div", { class: "meta", style: "margin-top:8px" }, magnitude(usage?.cost_usd), usage ? fmtCost(usage.cost_usd) : t(`state.${states[agent]}`)) : null,
    ));
  }
  if (state.settings.show_costs) {
    body.append(h("div", { class: "m-total" }, h("span", { class: "label" }, "Total"), h("strong", {}, run ? fmtCost(run.total_cost_usd) : "—")));
  }
  const tokens = (run?.usage || []).reduce((s, u) => s + u.input_tokens + u.output_tokens, 0);
  body.append(h("dl", { class: "m-facts" },
    h("dt", {}, "Plaque"), h("dd", {}, run ? plateNo(run.number) : "—"),
    h("dt", {}, "Tokens"), h("dd", {}, run ? fmtInt(tokens) : "—"),
    h("dt", {}, "Préréglage"), h("dd", {}, run?.preset || state.settings.preset),
    h("dt", {}, "Mode"), h("dd", {}, run ? (run.demo ? "démo (non facturé)" : "réel") : "—"),
  ));
  body.append(h("p", { class: "m-explain" }, "La taille du point suit le coût sur une échelle fixe. Une raie doublée signale un modèle de repli, une raie à mi-hauteur une réponse tronquée."));
}

/* ============================== run list ============================================== */
function groupOf(iso) {
  const d = new Date(iso), now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = (day(now) - day(d)) / 864e5;
  return diff < 1 ? "today" : diff < 2 ? "yesterday" : diff < 7 ? "week" : "older";
}
async function loadRuns() {
  state.runs = await state.backend.listRuns(state.query, state.archived);
  const projects = [...new Set(state.runs.map((r) => r.project).filter(Boolean))].sort();
  const select = $("#project-filter");
  const keep = state.project;
  select.replaceChildren(h("option", { value: "" }, t("rail.allProjects")), ...projects.map((p) => h("option", { value: p }, p)));
  select.value = projects.includes(keep) ? keep : "";
  state.project = select.value;
  renderRuns();
}
function renderRuns() {
  const list = $("#run-list");
  list.replaceChildren();
  const rows = state.runs.filter((r) => !state.project || r.project === state.project);
  if (!rows.length) { list.append(h("p", { class: "run-empty" }, state.query || state.project ? t("runs.noMatch") : t("runs.empty"))); return; }
  let last = null;
  for (const r of rows) {
    const group = r.pinned ? "pinned" : groupOf(r.created_at);
    if (group !== last) { list.append(h("div", { class: "run-group label" }, t(`group.${group}`))); last = group; }
    const current = state.current?.id === r.id;
    const item = h("div", { class: "run", role: "link", tabindex: "0", "data-id": r.id, "data-status": r.status, "aria-current": current ? "true" : "false" },
      h("span", { class: "run-no" }, plateNo(r.number).replace("N° ", "")),
      h("span", { class: "run-title" }, r.pinned ? h("svg", { class: "ic run-pin", role: "img", "aria-label": "épinglée", html: '<use href="#i-pin"/>' }) : null, r.title),
      h("span", { class: "run-cost" }, state.settings.show_costs && r.total_cost_usd ? [magnitude(r.total_cost_usd), fmtCost(r.total_cost_usd)] : r.demo ? "démo" : ""),
      (r.project || (r.tags || []).length) ? h("span", { class: "run-sub" }, r.project ? h("span", {}, r.project) : null, ...(r.tags || []).map((tag) => h("span", { class: "tag" }, `#${tag}`))) : null,
      h("button", { class: "icon-btn run-more", type: "button", "aria-label": "Actions de la plaque", "data-run-menu": r.id }, h("svg", { class: "ic", html: '<use href="#i-more"/>' })),
    );
    list.append(item);
  }
}

/* ============================== plate ================================================= */
function setTab(tab, byUser = false) {
  state.tab = tab;
  if (byUser && state.running) state.tabPinned = true;
  $$("#tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  renderBody();
}
let frame = 0;
function scheduleBody() { if (!frame) frame = requestAnimationFrame(() => { frame = 0; renderBody(); }); }
function renderBody() {
  const run = state.current;
  const body = $("#plate-body");
  if (!run) return;
  const liveTab = state.running ? TAB_OF[state.running.live] : null;
  $$("#tabs [role=tab]").forEach((b) => (b.dataset.live = String(b.dataset.tab === liveTab)));
  const caret = state.running && liveTab === state.tab;
  const empty = (msg) => h("p", { class: "placeholder-note" }, msg);
  body.classList.toggle("caret", false);
  switch (state.tab) {
    case "final": case "draft": case "brief": {
      const key = state.tab === "final" ? "final_text" : state.tab;
      const text = run[key];
      if (!text) { body.replaceChildren(empty(state.running ? "En attente de l'agent…" : "Rien ici pour cette plaque.")); return; }
      body.innerHTML = markdown(text);
      if (caret) (body.lastElementChild || body).classList.add("caret");
      return;
    }
    case "diff": {
      if (!run.draft || !run.final_text) { body.replaceChildren(empty("Les corrections apparaissent quand Warden a rendu le texte final.")); return; }
      // Diff the words, keep the blocks: inline emphasis is stripped, heading and list markers stay so
      // the errata render with the plate's own structure (see diffHtml).
      const prose = (s) => String(s).replace(/\*\*([^*]+)\*\*/g, "$1").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1$2").replace(/`([^`]+)`/g, "$1");
      const parts = wordDiff(prose(run.draft), prose(run.final_text));
      if (!parts) { body.replaceChildren(empty("Textes trop longs pour la comparaison mot à mot.")); return; }
      // One correction = a run of deletions/insertions not separated by unchanged words.
      let changes = 0, inChange = false;
      for (const p of parts) {
        if (p.kind !== "same") { if (!inChange) changes++; inChange = true; } else if (p.s.trim()) inChange = false;
      }
      body.replaceChildren(
        h("div", { class: "diff-legend" }, h("span", {}, h("del", {}, "barré"), " : retiré par Warden"), h("span", {}, h("ins", {}, "souligné"), " : ajouté"), h("span", {}, `${changes} modification${changes > 1 ? "s" : ""}`)),
        h("div", { html: diffHtml(parts) }),
      );
      return;
    }
    case "request": body.replaceChildren(h("div", { style: "white-space:pre-wrap" }, run.request)); return;
    case "raw": body.replaceChildren(h("pre", { class: "raw" }, JSON.stringify(run, null, 2))); return;
    default: break;
  }
}
function renderPlate() {
  const run = state.current;
  $("#empty").hidden = !!run;
  $("#plate-view").hidden = !run;
  const top = $("#topbar-title");
  top.textContent = run ? `${plateNo(run.number)} · ${run.title}` : "SPECTRE";
  top.classList.toggle("wordmark", !run);
  top.classList.toggle("wordmark-sm", !run);
  if (!run) { renderAgents(); renderInspector(); return; }
  $("#plate-title").textContent = run.title;
  const date = new Date(run.created_at);
  $("#plate-meta").textContent = `${plateNo(run.number)}${run.demo ? " · démo" : ""} · ${date.toLocaleString(lang === "fr" ? "fr-FR" : "en-US", { dateStyle: "medium", timeStyle: "short" })}${run.project ? ` · ${run.project}` : ""}${(run.tags || []).length ? ` · ${run.tags.map((x) => `#${x}`).join(" ")}` : ""}`;
  const alert = $("#plate-alert");
  const truncated = (run.usage || []).filter((u) => u.truncated).map((u) => NAME[u.agent]);
  if (run.status === "error") { alert.hidden = false; alert.dataset.kind = "error"; alert.textContent = `${NAME[run.error_agent] || "Spectre"} a échoué : ${run.error}`; }
  else if (run.status === "cancelled" && !state.running) { alert.hidden = false; alert.dataset.kind = "warn"; alert.textContent = `Plaque arrêtée pendant ${NAME[run.error_agent] || "l'exécution"}.`; }
  else if (truncated.length) { alert.hidden = false; alert.dataset.kind = "warn"; alert.textContent = `Réponse tronquée (${truncated.join(", ")}) : augmentez max_tokens dans un préréglage.`; }
  else alert.hidden = true;
  renderAgents(); renderInspector(); renderBody();
}
async function openRun(id) {
  if (state.running && state.running.id === id) return;
  try {
    state.current = await state.backend.getRun(id);
    state.tab = state.current.final_text ? "final" : state.current.draft ? "draft" : "brief";
    $$("#tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
    renderPlate(); renderRuns(); closeDrawers();
    history.replaceState(null, "", `#${id}`);
  } catch (err) { toast(`Impossible d'ouvrir la plaque : ${err.message}`, "error"); }
}
function newPlate() {
  if (state.running) { toast("Une plaque est en cours : arrêtez-la ou attendez la fin.", "warn"); return; }
  state.current = null; history.replaceState(null, "", location.pathname);
  renderPlate(); renderRuns(); closeDrawers();
  $("#composer-input").focus();
}

/* ============================== running a request ===================================== */
function presetOverrides() { return { ...(state.presets[$("#preset-select").value] || {}) }; }
async function send(requestText) {
  const input = $("#composer-input");
  const request = (requestText ?? input.value).trim();
  if (!request) { input.focus(); return; }
  if (request.startsWith("/") && runSlash(request)) { input.value = ""; autosize(); return; }
  if (state.running) { toast("Une plaque est déjà en cours.", "warn"); return; }
  const demo = $("#demo-switch").checked;
  if (!demo && state.status && !state.status.has_api_key) {
    toast("Aucune clé API détectée : activez la démo ou ajoutez ANTHROPIC_API_KEY dans .env.", "error", 6000);
    return;
  }
  const controller = new AbortController();
  state.running = { id: null, live: "scout", controller };
  state.tabPinned = false;
  document.body.classList.add("running");
  document.body.dataset.live = "scout";
  $("#send-btn").hidden = true; $("#stop-btn").hidden = false;
  input.value = ""; autosize();
  const body = { request, demo, preset: $("#preset-select").value, overrides: presetOverrides() };
  try {
    await state.backend.run(body, onEvent, controller.signal);
  } catch (err) {
    if (err.name !== "AbortError") toast(`Échec : ${err.message}`, "error", 6000);
    if (state.current && state.current.status === "running") state.current.status = "cancelled";
  } finally {
    state.running = null;
    document.body.classList.remove("running");
    delete document.body.dataset.live;
    $("#send-btn").hidden = false; $("#stop-btn").hidden = true;
    document.title = "Spectre";
    renderPlate(); loadRuns();
  }
}
function onEvent(ev) {
  const run = state.current;
  switch (ev.type) {
    case "run":
      state.current = ev.run; state.running.id = ev.run.id; state.tab = "brief";
      $$("#tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === "brief")));
      history.replaceState(null, "", `#${ev.run.id}`);
      renderPlate(); loadRuns();
      return;
    case "agent_start":
      state.running.live = ev.agent;
      document.body.dataset.live = ev.agent;
      document.title = `● ${NAME[ev.agent]} · Spectre`;
      if (!state.tabPinned) setTab(TAB_OF[ev.agent]);
      renderAgents(); renderInspector();
      return;
    case "token":
      if (!run) return;
      run[OUTPUT[ev.agent]] = (run[OUTPUT[ev.agent]] || "") + ev.text;
      scheduleBody();
      return;
    case "agent_done":
      if (!run) return;
      run[OUTPUT[ev.agent]] = ev.text;
      if (ev.usage) run.usage = [...(run.usage || []).filter((u) => u.agent !== ev.agent), ev.usage];
      run.durations = { ...(run.durations || {}), [ev.agent]: ev.seconds };
      run.total_cost_usd = run.usage.reduce((s, u) => s + (u.cost_usd || 0), 0) || null;
      state.running.live = null;
      renderAgents(); renderInspector(); scheduleBody();
      return;
    case "done": case "error": case "cancelled":
      state.current = ev.run || { ...run, ...ev };
      state.running.live = null;
      if (ev.type === "done" && !state.tabPinned) state.tab = "final";
      $$("#tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
      if (ev.type === "error") toast(ev.message || "Échec de l'exécution", "error", 7000);
      if (ev.type === "done") notifyDone(state.current);
      return;
    default:
  }
}
async function stop() {
  const running = state.running;
  if (!running) return;
  try { if (running.id) await state.backend.cancelRun(running.id); } catch { /* already finished */ }
  setTimeout(() => running.controller.abort(), 1500);
}
function notifyDone(run) {
  if (!document.hidden || !state.settings.notifications || !("Notification" in window)) return;
  if (Notification.permission === "granted") new Notification(`Spectre · ${plateNo(run.number)}`, { body: `${run.title} — texte final prêt.`, icon: "icons/icon-192.png" });
}

/* ============================== composer: autosize, slash, voice, attach ============== */
function autosize() {
  const input = $("#composer-input");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight + 2, innerHeight * 0.42)}px`;
  const n = input.value.length;
  $("#char-count").textContent = n ? `${fmtInt(n)} car.` : "";
}
const SLASH = [
  { cmd: "/nouveau", help: "Nouvelle plaque", run: () => newPlate() },
  { cmd: "/demo", help: "Basculer le mode démo", run: () => { const s = $("#demo-switch"); s.checked = !s.checked; s.dispatchEvent(new Event("change")); } },
  { cmd: "/theme", help: "sombre · clair · système", arg: true, run: (a) => saveSetting("theme", { sombre: "dark", dark: "dark", clair: "light", light: "light", systeme: "system", système: "system", system: "system" }[a] || (state.settings.theme === "dark" ? "light" : "dark")) },
  { cmd: "/couts", help: "Afficher ou masquer les coûts", run: () => saveSetting("show_costs", !state.settings.show_costs) },
  { cmd: "/preset", help: "Choisir un préréglage", arg: true, run: (a) => { const name = Object.keys(state.presets).find((p) => p.toLowerCase() === a.toLowerCase()); if (name) { $("#preset-select").value = name; saveSetting("preset", name); } else toast(`Préréglage inconnu : ${a}`, "warn"); } },
  { cmd: "/export", help: "Exporter la plaque en Markdown", run: () => exportRun("md") },
  { cmd: "/palette", help: "Ouvrir la palette (Ctrl+K)", run: () => openPalette() },
  { cmd: "/reglages", help: "Ouvrir les réglages", run: () => openSettings() },
  { cmd: "/aide", help: "Raccourcis clavier", run: () => toast("Ctrl+Entrée : exposer · Ctrl+K : palette · N : nouvelle plaque · / : saisie · J/K : plaque suivante/précédente · Échap : fermer", "ok", 9000) },
];
function runSlash(text) {
  const [cmd, ...rest] = text.trim().split(/\s+/);
  const entry = SLASH.find((s) => s.cmd === cmd.toLowerCase());
  if (!entry) return false;
  entry.run(rest.join(" "));
  return true;
}
let slashIndex = 0;
function updateSlash() {
  const input = $("#composer-input");
  const menu = $("#slash-menu");
  const v = input.value;
  if (!v.startsWith("/") || v.includes("\n")) { menu.hidden = true; return; }
  const word = v.split(/\s/)[0].toLowerCase();
  const hits = SLASH.filter((s) => s.cmd.startsWith(word));
  if (!hits.length || (hits.length === 1 && hits[0].cmd === word && v.length > word.length)) { menu.hidden = true; return; }
  slashIndex = Math.min(slashIndex, hits.length - 1);
  menu.replaceChildren(...hits.map((s, i) => h("li", { role: "option", "aria-selected": String(i === slashIndex), "data-cmd": s.cmd }, h("b", {}, s.cmd), h("span", {}, s.help))));
  menu.hidden = false;
}
function pickSlash(cmd) {
  const input = $("#composer-input");
  const entry = SLASH.find((s) => s.cmd === cmd);
  if (entry.arg) { input.value = `${cmd} `; $("#slash-menu").hidden = true; input.focus(); return; }
  input.value = ""; $("#slash-menu").hidden = true; autosize(); entry.run("");
}
function setupVoice() {
  const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  const btn = $("#mic-btn");
  if (!Rec) return;
  btn.hidden = false;
  let rec = null;
  btn.addEventListener("click", () => {
    if (rec) { rec.stop(); return; }
    rec = new Rec();
    rec.lang = lang === "en" ? "en-US" : "fr-FR";
    rec.interimResults = true;
    rec.continuous = false;
    const input = $("#composer-input");
    const before = input.value ? `${input.value.trimEnd()} ` : "";
    rec.onresult = (e) => { input.value = before + [...e.results].map((r) => r[0].transcript).join(""); autosize(); };
    rec.onend = () => { rec = null; btn.setAttribute("aria-pressed", "false"); };
    rec.onerror = (e) => toast(`Dictée indisponible : ${e.error}`, "warn");
    btn.setAttribute("aria-pressed", "true");
    rec.start();
  });
}
function attachFile(file) {
  if (!file) return;
  if (file.size > 400_000) { toast("Fichier trop gros (400 Ko maximum).", "error"); return; }
  const reader = new FileReader();
  reader.onload = () => {
    const input = $("#composer-input");
    input.value = `${input.value ? `${input.value.trimEnd()}\n\n` : ""}--- ${file.name} ---\n${reader.result}`;
    autosize(); input.focus();
    toast(`${file.name} ajouté à la demande.`);
  };
  reader.onerror = () => toast("Lecture du fichier impossible.", "error");
  reader.readAsText(file);
}

/* ============================== menus ================================================= */
function closeMenu() { const m = $("#menu"); m.hidden = true; m.replaceChildren(); }
function openMenu(anchor, items) {
  const menu = $("#menu");
  menu.replaceChildren(...items.map((item) => item === "-" ? h("hr") : h("button", { type: "button", role: "menuitem", class: item.danger ? "danger" : null, onclick: async (e) => { e.stopPropagation(); if (item.keepOpen) { item.run(menu); return; } closeMenu(); await item.run(); } }, item.icon ? h("svg", { class: "ic", html: `<use href="#${item.icon}"/>` }) : null, item.label)));
  menu.hidden = false;
  const r = anchor.getBoundingClientRect();
  const mw = menu.offsetWidth, mh = menu.offsetHeight;
  menu.style.left = `${Math.max(8, Math.min(r.right - mw, innerWidth - mw - 8))}px`;
  menu.style.top = `${r.bottom + mh + 8 > innerHeight ? Math.max(8, r.top - mh - 6) : r.bottom + 6}px`;
  menu.querySelector("button")?.focus();
}
function askInMenu(menu, label, value, onOk) {
  const input = h("input", { type: "text", value: value || "", "aria-label": label, style: "width:100%;min-height:38px;padding:0 10px" });
  const form = h("form", { style: "display:grid;gap:8px;padding:8px", onsubmit: async (e) => { e.preventDefault(); closeMenu(); await onOk(input.value); } },
    h("span", { class: "label" }, label), input, h("button", { class: "btn btn-primary", type: "submit" }, "Valider"));
  menu.replaceChildren(form); input.focus(); input.select();
}
async function runAction(id, fn, okMsg) {
  try { const res = await fn(); if (okMsg) toast(okMsg); await loadRuns(); if (state.current?.id === id && res && res.id === id) { state.current = await state.backend.getRun(id); renderPlate(); } return res; }
  catch (err) { toast(err.message, "error"); return null; }
}
function runMenu(anchor, summary) {
  const id = summary.id;
  const b = state.backend;
  let armed = false;
  openMenu(anchor, [
    { label: summary.pinned ? "Désépingler" : "Épingler", icon: "i-pin", run: () => runAction(id, () => b.updateRun(id, { pinned: !summary.pinned })) },
    { label: "Renommer…", icon: "i-edit", keepOpen: true, run: (m) => askInMenu(m, "Nouveau titre", summary.title, (v) => runAction(id, () => b.updateRun(id, { title: v }))) },
    { label: "Projet…", icon: "i-archive", keepOpen: true, run: (m) => askInMenu(m, "Projet (vide pour retirer)", summary.project, (v) => runAction(id, () => b.updateRun(id, { project: v }))) },
    { label: "Tags…", icon: "i-search", keepOpen: true, run: (m) => askInMenu(m, "Tags séparés par des espaces", (summary.tags || []).map((x) => `#${x}`).join(" "), (v) => runAction(id, () => b.updateRun(id, { tags: v.split(/[\s,]+/).filter(Boolean) }))) },
    { label: "Dupliquer", icon: "i-dup", run: () => runAction(id, () => b.duplicateRun(id), "Plaque dupliquée.") },
    { label: summary.archived ? "Désarchiver" : "Archiver", icon: "i-archive", run: () => runAction(id, () => b.updateRun(id, { archived: !summary.archived }), summary.archived ? "Plaque désarchivée." : "Plaque archivée.") },
    "-",
    { label: "Exporter en Markdown", icon: "i-down", run: async () => exportRun("md", await b.getRun(id)) },
    { label: "Exporter en JSON", icon: "i-down", run: async () => exportRun("json", await b.getRun(id)) },
    { label: "Page de partage (HTML)", icon: "i-share", run: async () => exportRun("html", await b.getRun(id)) },
    "-",
    { label: "Supprimer…", icon: "i-trash", danger: true, keepOpen: true, run: async (m) => {
      if (!armed) { armed = true; const btn = [...m.querySelectorAll("button")].pop(); btn.lastChild.textContent = "Confirmer la suppression"; return; }
      closeMenu();
      await runAction(id, () => b.deleteRun(id), "Plaque supprimée.");
      if (state.current?.id === id) newPlate();
    } },
  ]);
}
async function exportRun(fmt, run = state.current) {
  if (!run) { toast("Aucune plaque ouverte.", "warn"); return; }
  const text = await state.backend.exportRun(run, fmt);
  const ext = { md: "md", json: "json", html: "html" }[fmt];
  const type = { md: "text/markdown", json: "application/json", html: "text/html" }[fmt];
  download(`spectre-${String(run.number).padStart(4, "0")}.${ext}`, text, `${type};charset=utf-8`);
}

/* ============================== settings sheet ======================================== */
async function saveSetting(key, value) {
  try { state.settings = await state.backend.saveSettings({ [key]: value }); applySettings(); renderPlate(); renderRuns(); if ($("#settings").open) renderSettings(); }
  catch (err) { toast(err.message, "error"); }
}
function seg(key, options) {
  return h("div", { class: "seg", role: "group" }, ...options.map(([value, label]) => h("button", { type: "button", "aria-pressed": String(state.settings[key] === value), onclick: () => saveSetting(key, value) }, label)));
}
function toggleRow(key, label, help) {
  const input = h("input", { type: "checkbox", checked: state.settings[key], onchange: async (e) => {
    if (key === "notifications" && e.target.checked && "Notification" in window && Notification.permission !== "granted") {
      const p = await Notification.requestPermission();
      if (p !== "granted") { e.target.checked = false; toast("Notifications refusées par le navigateur.", "warn"); return; }
    }
    saveSetting(key, e.target.checked);
  } });
  return h("div", { class: "set-row" }, h("span", { class: "set-label" }, label), h("label", { class: "switch" }, input, h("span", { class: "switch-track", "aria-hidden": "true" })), h("p", {}, help));
}
let settingsTab = "prefs";
function renderSettings() {
  const body = $("#settings-body");
  $$("#settings-tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.stab === settingsTab)));
  const s = state.settings;
  if (settingsTab === "prefs") {
    body.replaceChildren(
      h("div", { class: "set-row" }, h("span", { class: "set-label" }, "Thème"), seg("theme", [["dark", "Sombre"], ["light", "Clair"], ["system", "Système"]]), h("p", {}, "Sombre : plaque de spectrogramme. Clair : table lumineuse.")),
      h("div", { class: "set-row" }, h("span", { class: "set-label" }, "Taille du texte"), seg("font_size", [["small", "Petit"], ["medium", "Moyen"], ["large", "Grand"]])),
      h("div", { class: "set-row" }, h("span", { class: "set-label" }, "Touche d'envoi"), seg("send_key", [["ctrl-enter", "Ctrl+Entrée"], ["enter", "Entrée"]]), h("p", {}, "Avec « Entrée », Maj+Entrée insère un retour à la ligne. Sur téléphone, Entrée insère toujours un retour.")),
      h("div", { class: "set-row" }, h("span", { class: "set-label" }, "Langue"), seg("language", [["fr", "Français"], ["en", "English"]])),
      toggleRow("show_costs", "Afficher les coûts", "Coût par agent et total, en dollars, au tarif du modèle qui a répondu."),
      toggleRow("notifications", "Notification de fin", "Prévenir quand le texte final est prêt et que l'onglet n'est pas au premier plan."),
    );
  } else if (settingsTab === "presets") {
    const levels = state.status?.effort_levels || ["low", "medium", "high", "xhigh", "max"];
    const cards = Object.entries(state.presets).map(([name, over]) => presetCard(name, over, levels, false));
    body.replaceChildren(h("p", { class: "meta" }, "Un préréglage fixe, pour chaque agent, le modèle, l'effort et la limite de tokens. Laisser vide garde la valeur par défaut."), ...cards, presetCard("", {}, levels, true));
  } else if (settingsTab === "history") {
    body.replaceChildren(
      h("div", { class: "set-row" }, h("span", { class: "set-label" }, "Exporter tout l'historique"), h("button", { class: "btn", type: "button", onclick: async () => download("spectre-historique.json", await state.backend.exportAll(), "application/json") }, "Exporter"), h("p", {}, "Toutes les plaques, archives comprises, dans un fichier JSON réimportable.")),
      h("div", { class: "set-row" }, h("span", { class: "set-label" }, "Importer"), h("button", { class: "btn", type: "button", onclick: () => $("#import-input").click() }, "Choisir un fichier"), h("p", {}, "Fichier JSON exporté par Spectre. Les plaques importées reçoivent de nouveaux numéros.")),
      h("div", { class: "set-row" }, h("span", { class: "set-label" }, "Tout effacer"), h("button", { class: "btn btn-danger", type: "button", onclick: (e) => {
        const btn = e.currentTarget;
        if (btn.dataset.armed !== "1") { btn.dataset.armed = "1"; btn.textContent = "Confirmer l'effacement"; return; }
        state.backend.clearRuns().then((r) => { toast(`${r.deleted} plaque(s) effacée(s).`); newPlate(); loadRuns(); renderSettings(); });
      } }, "Effacer"), h("p", {}, "Supprime définitivement toutes les plaques. Exportez d'abord si besoin.")),
    );
  } else {
    const st = state.status || {};
    const yes = (ok, a = "oui", b = "non") => h("dd", { class: ok ? "ok" : "ko" }, ok ? a : b);
    body.replaceChildren(
      h("dl", { class: "sys-list" },
        h("dt", {}, "Version"), h("dd", {}, st.version || "?"),
        h("dt", {}, "Moteur"), h("dd", {}, state.backend.kind === "http" ? "serveur spectre-web" : "vitrine dans le navigateur (démo seulement)"),
        h("dt", {}, "Clé API détectée"), yes(st.has_api_key),
        h("dt", {}, "Workspace configuré"), h("dd", {}, st.workspace_configured ? "oui" : "non (inutile pour une clé de workspace)"),
        h("dt", {}, "Agents"), h("dd", {}, (st.agents || []).map((a) => `${NAME[a.name]} : ${a.model}${a.effort ? ` (effort ${a.effort})` : ""}, ${fmtInt(a.max_tokens)} tokens`).join(" · ")),
        h("dt", {}, "Historique"), h("dd", {}, st.state_dir || "—"),
        h("dt", {}, "Mot de passe"), h("dd", {}, st.auth_required ? "activé" : "désactivé (accès local uniquement)"),
      ),
      st.auth_required ? h("button", { class: "btn", type: "button", onclick: async () => { await state.backend.logout(); location.reload(); } }, "Se déconnecter") : null,
      h("p", { class: "meta" }, "La clé API n'est jamais affichée ni envoyée au navigateur. Pour un usage sur téléphone ou tablette : définissez SPECTRE_WEBUI_PASSWORD puis lancez spectre-web --host 0.0.0.0."),
    );
  }
}
function presetCard(name, over, levels, isNew) {
  const fields = {};
  const nameInput = isNew ? h("input", { type: "text", placeholder: "Nom du nouveau préréglage", "aria-label": "Nom du préréglage", style: "min-height:36px;padding:0 10px;flex:1" }) : null;
  const grid = h("div", { class: "preset-grid" }, ...AGENTS.map((agent) => {
    const up = agent.toUpperCase();
    const model = h("input", { type: "text", value: over[`SPECTRE_${up}_MODEL`] || "", placeholder: configuredModel(agent, null), "aria-label": `Modèle ${NAME[agent]}` });
    const effort = h("select", { "aria-label": `Effort ${NAME[agent]}` }, h("option", { value: "" }, "effort par défaut"), ...levels.map((l) => h("option", { value: l, selected: over[`SPECTRE_${up}_EFFORT`] === l }, l)));
    const tokens = h("input", { type: "number", min: "1", value: over[`SPECTRE_${up}_MAX_TOKENS`] || "", placeholder: "max tokens", "aria-label": `Max tokens ${NAME[agent]}` });
    fields[up] = { model, effort, tokens };
    return h("div", { class: "preset-agent", style: `--c:var(--${agent})` }, h("span", { class: "label" }, NAME[agent]), model, agent === "scout" ? h("span", { class: "meta", style: "min-height:34px;display:flex;align-items:center" }, "Haiku : pas d'effort") : effort, tokens);
  }));
  const collect = () => {
    const out = {};
    for (const [up, f] of Object.entries(fields)) {
      if (f.model.value.trim()) out[`SPECTRE_${up}_MODEL`] = f.model.value.trim();
      if (up !== "SCOUT" && f.effort.value) out[`SPECTRE_${up}_EFFORT`] = f.effort.value;
      if (f.tokens.value) out[`SPECTRE_${up}_MAX_TOKENS`] = String(f.tokens.value);
    }
    return out;
  };
  const save = async () => {
    const finalName = isNew ? nameInput.value.trim() : name;
    if (!finalName) { toast("Donnez un nom au préréglage.", "warn"); return; }
    try { state.presets = await state.backend.savePreset(finalName, collect()); fillPresets(); renderSettings(); toast(`Préréglage « ${finalName} » enregistré.`); }
    catch (err) { toast(err.message, "error"); }
  };
  const del = async () => { try { state.presets = await state.backend.deletePreset(name); fillPresets(); renderSettings(); } catch { toast("Les préréglages intégrés ne peuvent pas être supprimés.", "warn"); } };
  return h("section", { class: "preset-card" },
    h("h3", {}, isNew ? nameInput : name, h("span", {}, !isNew && !(state.status?.builtin_presets || ["Standard"]).includes(name) ? h("button", { class: "icon-btn", type: "button", "aria-label": `Supprimer ${name}`, onclick: del }, h("svg", { class: "ic", html: '<use href="#i-trash"/>' })) : null)),
    grid,
    h("div", {}, h("button", { class: "btn btn-primary", type: "button", onclick: save }, isNew ? "Créer" : "Enregistrer")),
  );
}
function openSettings() { closeMenu(); renderSettings(); $("#settings").showModal(); }
function fillPresets() {
  const select = $("#preset-select");
  const keep = select.value || state.settings.preset;
  select.replaceChildren(...Object.keys(state.presets).map((n) => h("option", { value: n }, n)));
  select.value = state.presets[keep] ? keep : "Standard";
}

/* ============================== command palette ======================================= */
let paletteItems = [], paletteIndex = 0;
function openPalette() {
  closeMenu();
  $("#palette").showModal();
  const input = $("#palette-input");
  input.value = ""; renderPalette(); input.focus();
}
function renderPalette() {
  const q = $("#palette-input").value.trim().toLowerCase();
  const actions = [
    { label: "Nouvelle plaque", hint: "N", run: newPlate },
    { label: "Réglages", hint: "", run: openSettings },
    { label: `Thème : ${state.settings.theme === "dark" ? "passer en clair" : "passer en sombre"}`, hint: "/theme", run: () => saveSetting("theme", state.settings.theme === "dark" ? "light" : "dark") },
    { label: `Mode démo : ${$("#demo-switch").checked ? "désactiver" : "activer"}`, hint: "/demo", run: () => runSlash("/demo") },
    { label: "Exporter la plaque (Markdown)", hint: "/export", run: () => exportRun("md") },
    { label: state.archived ? "Voir les plaques actives" : "Voir les archives", hint: "", run: () => $("#archive-toggle").click() },
  ];
  const runs = state.runs.map((r) => ({ label: `${plateNo(r.number)} · ${r.title}`, hint: r.project || "", run: () => openRun(r.id) }));
  paletteItems = [...actions, ...runs].filter((i) => !q || i.label.toLowerCase().includes(q)).slice(0, 40);
  paletteIndex = Math.min(paletteIndex, Math.max(0, paletteItems.length - 1));
  $("#palette-list").replaceChildren(...paletteItems.map((item, i) => h("li", { role: "option", "aria-selected": String(i === paletteIndex), onclick: () => { $("#palette").close(); item.run(); } }, h("span", {}, item.label), h("small", {}, item.hint))));
}

/* ============================== drawers =============================================== */
function closeDrawers() { document.body.classList.remove("rail-open", "inspector-open"); $(".scrim").hidden = true; }
function openDrawer(which) { closeDrawers(); document.body.classList.add(`${which}-open`); $(".scrim").hidden = false; }

/* ============================== wiring ================================================ */
const SUGGESTIONS = [
  "Explique la relativité restreinte simplement",
  "Écris un mail pour décaler une réunion de lundi à jeudi, ton cordial",
  "Rédige la page « À propos » d'un atelier de reliure à Lyon",
  "Résume les avantages et limites du télétravail en 300 mots",
];
function wire() {
  document.addEventListener("click", (e) => {
    const menuBtn = e.target.closest("[data-run-menu]");
    if (menuBtn) { e.stopPropagation(); const summary = state.runs.find((r) => r.id === menuBtn.dataset.runMenu); if (summary) runMenu(menuBtn, summary); return; }
    const runItem = e.target.closest(".run[data-id]");
    if (runItem) { openRun(runItem.dataset.id); return; }
    if (!e.target.closest("#menu")) closeMenu();
    const actionEl = e.target.closest("[data-action]");
    if (!actionEl) return;
    const action = actionEl.dataset.action;
    const actions = {
      new: newPlate, settings: openSettings, palette: openPalette, stop,
      attach: () => $("#file-input").click(),
      "open-rail": () => openDrawer("rail"), "open-inspector": () => openDrawer("inspector"), "close-drawers": closeDrawers,
      copy: async () => { if (!state.current) return; const key = { final: "final_text", draft: "draft", brief: "brief", request: "request" }[state.tab] || "final_text"; toast((await copyText(state.current[key] || "")) ? "Texte copié." : "Copie impossible.", "ok", 2000); },
      rerun: () => { if (state.current) send(state.current.request); },
      "edit-request": () => { if (!state.current) return; const input = $("#composer-input"); input.value = state.current.request; autosize(); input.focus(); input.setSelectionRange(input.value.length, input.value.length); toast("Modifiez la demande puis exposez une nouvelle plaque."); },
      "export-menu": () => openMenu(actionEl, [
        { label: "Markdown (.md)", icon: "i-down", run: () => exportRun("md") },
        { label: "JSON (.json)", icon: "i-down", run: () => exportRun("json") },
        { label: "Page de partage (.html)", icon: "i-share", run: () => exportRun("html") },
      ]),
      share: () => exportRun("html"),
    };
    if (actions[action]) { e.stopPropagation(); actions[action](); }
  });
  $("#run-list").addEventListener("keydown", (e) => { const item = e.target.closest(".run[data-id]"); if (item && (e.key === "Enter" || e.key === " ") && e.target === item) { e.preventDefault(); openRun(item.dataset.id); } });
  $("#composer").addEventListener("submit", (e) => { e.preventDefault(); send(); });
  const input = $("#composer-input");
  input.addEventListener("input", () => { autosize(); slashIndex = 0; updateSlash(); });
  input.addEventListener("keydown", (e) => {
    const menu = $("#slash-menu");
    if (!menu.hidden) {
      const items = $$("li", menu);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); slashIndex = (slashIndex + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length; updateSlash(); return; }
      if (e.key === "Tab" || (e.key === "Enter" && !e.ctrlKey && !e.metaKey)) { e.preventDefault(); pickSlash(items[slashIndex].dataset.cmd); return; }
      if (e.key === "Escape") { menu.hidden = true; return; }
    }
    if (e.key !== "Enter") return;
    const touch = matchMedia("(pointer: coarse)").matches;
    if (e.ctrlKey || e.metaKey) { e.preventDefault(); send(); return; }
    if (state.settings.send_key === "enter" && !e.shiftKey && !touch) { e.preventDefault(); send(); }
  });
  $("#slash-menu").addEventListener("mousedown", (e) => { const li = e.target.closest("li"); if (li) { e.preventDefault(); pickSlash(li.dataset.cmd); } });
  $("#file-input").addEventListener("change", (e) => { attachFile(e.target.files[0]); e.target.value = ""; });
  $("#import-input").addEventListener("change", async (e) => {
    const file = e.target.files[0]; e.target.value = "";
    if (!file) return;
    try { const data = JSON.parse(await file.text()); const r = await state.backend.importRuns(Array.isArray(data) ? data : data.runs); toast(`${r.imported} plaque(s) importée(s).`); loadRuns(); }
    catch (err) { toast(`Import impossible : ${err.message}`, "error"); }
  });
  $("#demo-switch").addEventListener("change", (e) => saveSetting("demo", e.target.checked));
  $("#preset-select").addEventListener("change", (e) => saveSetting("preset", e.target.value));
  let searchTimer = 0;
  $("#search").addEventListener("input", (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.query = e.target.value; loadRuns(); }, 160); });
  $("#project-filter").addEventListener("change", (e) => { state.project = e.target.value; renderRuns(); });
  $("#archive-toggle").addEventListener("click", (e) => { state.archived = !state.archived; e.currentTarget.setAttribute("aria-pressed", String(state.archived)); loadRuns(); });
  $("#tabs").addEventListener("click", (e) => { const tab = e.target.closest("[role=tab]"); if (tab) setTab(tab.dataset.tab, true); });
  $("#tabs").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const tabs = $$("#tabs [role=tab]"); const i = tabs.findIndex((x) => x.dataset.tab === state.tab);
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length]; next.focus(); setTab(next.dataset.tab, true);
  });
  $("#settings-tabs").addEventListener("click", (e) => { const tab = e.target.closest("[data-stab]"); if (tab) { settingsTab = tab.dataset.stab; renderSettings(); } });
  const title = $("#plate-title");
  const commitTitle = async () => {
    title.contentEditable = "false";
    const value = title.textContent.trim();
    if (state.current && value && value !== state.current.title) { await runAction(state.current.id, () => state.backend.updateRun(state.current.id, { title: value })); }
    else if (state.current) title.textContent = state.current.title;
  };
  title.addEventListener("click", () => { if (!state.current || state.running) return; title.contentEditable = "true"; title.focus(); });
  title.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); title.blur(); } if (e.key === "Escape") { title.textContent = state.current.title; title.blur(); } });
  title.addEventListener("blur", commitTitle);
  $("#palette-input").addEventListener("input", () => { paletteIndex = 0; renderPalette(); });
  $("#palette-input").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); paletteIndex = (paletteIndex + (e.key === "ArrowDown" ? 1 : -1) + paletteItems.length) % Math.max(1, paletteItems.length); renderPalette(); }
    if (e.key === "Enter" && paletteItems[paletteIndex]) { e.preventDefault(); const item = paletteItems[paletteIndex]; $("#palette").close(); item.run(); }
  });
  $("#palette").addEventListener("click", (e) => { if (e.target.id === "palette") $("#palette").close(); });
  $("#settings").addEventListener("click", (e) => { if (e.target.id === "settings") $("#settings").close(); });
  document.addEventListener("keydown", (e) => {
    const typing = e.target.closest("input, textarea, select, [contenteditable=true]");
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
    if (e.key === "Escape") { closeMenu(); closeDrawers(); return; }
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "n" || e.key === "N") { e.preventDefault(); newPlate(); }
    else if (e.key === "/") { e.preventDefault(); $("#composer-input").focus(); }
    else if (e.key === "j" || e.key === "k") {
      const i = state.runs.findIndex((r) => r.id === state.current?.id);
      const next = state.runs[Math.max(0, Math.min(state.runs.length - 1, i + (e.key === "j" ? 1 : -1)))];
      if (next) openRun(next.id);
    }
  });
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => { if (state.settings.theme === "system") applySettings(); });
  let resizeTimer = 0;
  addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(drawContinuum, 150); });
  $("#suggestions").replaceChildren(...SUGGESTIONS.map((s) => h("button", { class: "suggestion", type: "button", onclick: () => { const i = $("#composer-input"); i.value = s; autosize(); i.focus(); } }, s)));
  setupVoice();
}

/* ============================== boot ================================================== */
async function enterApp() {
  $("#login").hidden = true;
  $("#app").hidden = false;
  const b = state.backend;
  [state.settings, state.presets] = await Promise.all([b.getSettings(), b.getPresets()]);
  if (b.kind === "local") state.settings.demo = true;
  applySettings();
  fillPresets();
  $("#demo-switch").checked = !!state.settings.demo || !state.status.has_api_key;
  if (b.kind === "local") { $("#mic-btn").remove(); $("#demo-switch").disabled = true; const badge = $("#mode-badge"); badge.hidden = false; badge.textContent = "Vitrine · démo"; }
  $("#version").textContent = b.kind === "local" ? "vitrine" : `v${state.status.version}`;
  await loadRuns();
  const hashId = location.hash.slice(1);
  if (hashId && /^[0-9a-f]+$/.test(hashId)) await openRun(hashId); else renderPlate();
  autosize();
  if (b.kind === "http" && "serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}
async function boot() {
  wire();
  let backend = new HttpBackend();
  let status = null;
  try { status = await backend.status(); } catch { status = null; }
  if (!status || typeof status.version !== "string") {
    const demo = await fetch("demo.json").then((r) => r.json());
    backend = new LocalBackend(demo);
    status = await backend.status();
  }
  state.backend = backend;
  state.status = status;
  $("#assistant-link").hidden = !status.assistant;
  if (status.assistant) voiceFab();
  if (status.auth_required && !status.authenticated) {
    $("#login").hidden = false;
    $("#login-password").focus();
    $("#login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await backend.login($("#login-password").value); state.status = await backend.status(); await enterApp(); }
      catch (err) { $("#login-error").textContent = err.message; }
    });
    return;
  }
  await enterApp();
}
boot().catch((err) => { document.body.prepend(h("p", { class: "alert", role: "alert" }, `Spectre n'a pas pu démarrer : ${err.message}`)); });
