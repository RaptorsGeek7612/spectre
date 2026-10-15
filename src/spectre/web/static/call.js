// The team's video call (the idea of Agent Standup, for Spectre's own team and for the Claude
// Code, Codex and Mistral Vibe sessions on this PC): each agent at its desk with its status,
// what it is doing and for how long; the one who speaks gets the spotlight and subtitles; the
// shared screen shows the last command and its real output. Stand-up round, tree of who asked
// whom, board of sessions, replay with speeds and highlights, Markdown recap, video recording.
// Nothing here calls a model: lines come from the records.

import { $, api, clock, h, since, toast, tokens } from "./kit.js";
import { createAvatar, createPhoto } from "./avatars.js";
import * as voice from "./voice.js";

const STATUS = {
  needs_you: "a besoin de toi", stalled: "bloqué ?", working: "au travail", waiting: "attend",
  done: "a fini", available: "disponible", your_turn: "à toi de jouer", idle: "inactif",
};
const FILLERS = ["Vous m'entendez bien ?", "Tout le monde voit mon écran ?", "Je reste en ligne, appelez-moi si besoin.", "Petite pause café, je reviens vite."];

const state = {
  open: false, joined: false, view: "call", source: { kind: "team" }, since: 0, ev: 0,
  agents: [], faces: new Map(), queue: [], speaking: null, timer: 0, lastLine: Date.now(),
  fillers: 0, chatter: true, screen: null, pinnedScreen: false, transcript: [], replay: null,
  recorder: null, wasWorking: 0, workSince: 0, titleBase: document.title, sessionKnown: 0,
};

/* ---------------------------------------------------------------- markup */

function build() {
  const root = $("#call");
  if (root.dataset.built) return;
  root.dataset.built = "1";
  root.append(
    h("header", { class: "cl-top" },
      h("div", { class: "cl-title" }, h("h2", { class: "as-h" }, "Visio de l'équipe"), h("p", { class: "meta", id: "cl-summary" }, "")),
      h("nav", { class: "cl-tabs", role: "tablist" },
        ...[["call", "Appel"], ["tree", "Arbre"], ["sessions", "Sessions"]].map(([v, t]) =>
          h("button", { type: "button", role: "tab", "data-cv": v, "aria-selected": v === "call" ? "true" : "false", onclick: () => switchView(v) }, t))),
      h("div", { class: "cl-actions" },
        h("button", { class: "btn btn-primary", type: "button", id: "cl-join", onclick: join }, h("span", {}, "Rejoindre (son)")),
        h("button", { class: "btn", type: "button", onclick: standup }, h("span", {}, "Tour de table")),
        h("button", { class: "btn", type: "button", "data-action": "talk" }, h("span", {}, "Parler")),
        h("button", { class: "btn btn-ghost", type: "button", onclick: recap }, h("span", {}, "Compte rendu")),
        h("button", { class: "btn btn-ghost", type: "button", id: "cl-rec", onclick: () => record(0) }, h("span", {}, "Enregistrer")),
        h("button", { class: "btn btn-ghost", type: "button", onclick: () => record(25) }, h("span", {}, "Clip 25 s")),
        h("label", { class: "cl-toggle" }, h("input", { type: "checkbox", checked: true, onchange: (e) => { state.chatter = e.target.checked; } }), "Petites phrases"))),
    h("p", { class: "cl-source", id: "cl-source", hidden: true }),
    h("div", { class: "cl-body", "data-cv": "call" },
      h("aside", { class: "cl-list", id: "cl-list", "aria-label": "Participants" }),
      h("div", { class: "cl-stage" },
        h("div", { class: "cl-grid", id: "cl-grid" }),
        h("p", { class: "cl-sub", id: "cl-sub", "aria-live": "polite" }),
        h("div", { class: "cl-replay", id: "cl-replay", hidden: true }),
        h("form", { class: "cl-say", id: "cl-say", autocomplete: "off" },
          h("input", { type: "text", name: "text", placeholder: "Écrire à l'équipe (Spectre répond dans l'appel)…", maxlength: "2000" }),
          h("button", { class: "btn", type: "submit" }, h("span", {}, "Envoyer")))),
      h("section", { class: "cl-screen", id: "cl-screen", hidden: true, "aria-label": "Écran partagé" }),
      h("details", { class: "cl-transcript" }, h("summary", {}, "Transcription"), h("ol", { id: "cl-lines" }))),
    h("div", { class: "cl-body", "data-cv": "tree", hidden: true }, h("div", { id: "cl-tree", class: "cl-tree" })),
    h("div", { class: "cl-body", "data-cv": "sessions", hidden: true }, h("div", { id: "cl-board", class: "cl-board" })));
  $("#cl-say").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = e.target.elements.text;
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    try { await api("POST", "chat", { text }); } catch (err) { toast(err.message, "error"); }
  });
}

function switchView(view) {
  state.view = view;
  document.querySelectorAll("#call .cl-tabs [data-cv]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.cv === view)));
  document.querySelectorAll("#call .cl-body").forEach((b) => { b.hidden = b.dataset.cv !== view; });
  if (view === "tree") loadTree();
  if (view === "sessions") loadBoard();
}

/* ---------------------------------------------------------------- tiles */

function faceFor(agent) {
  let face = state.faces.get(agent.key);
  if (!face && agent.key === "you") {
    face = { el: h("div", { class: "cl-you" }, "TOI"), mouth() {}, look() {}, stop() {} };
    state.faces.set(agent.key, face);
  }
  if (!face) {
    face = agent.portrait
      ? createPhoto(`/api/assistant/team/${encodeURIComponent(agent.key)}/portrait`, agent.name)
      : createAvatar(agent.lookKey || agent.key, agent.gender, { title: agent.name, look: agent.look });
    state.faces.set(agent.key, face);
  }
  return face;
}

function badges(a) {
  const out = [];
  if (a.tokens) out.push(h("span", { title: "jetons (24 h)" }, `⚡ ${tokens(a.tokens)}`));
  if (a.fails) out.push(h("span", { class: "bad", title: "appels d'outils en échec" }, `✗ ${a.fails}`));
  if (a.long_tool) out.push(h("span", { class: "warn", title: "commande de plus d'une minute" }, "⏳"));
  if (a.quiet) out.push(h("span", { title: "silencieux depuis 3 min" }, "💤"));
  if (a.repeat) out.push(h("span", { class: "warn", title: "répète le même appel" }, "🔁"));
  return out;
}

function renderTiles(agents) {
  const grid = $("#cl-grid");
  const list = $("#cl-list");
  const seen = new Set();
  for (const a of agents) {
    seen.add(a.key);
    let tile = grid.querySelector(`[data-key="${CSS.escape(a.key)}"]`);
    if (!tile) {
      const face = faceFor(a);
      tile = h("article", { class: "cl-tile", "data-key": a.key, tabindex: "0", onclick: () => spotlight(a.key, 25000), ondblclick: () => document.querySelector(`[data-view="team"]`)?.click() },
        h("div", { class: "cl-face" }, face.el),
        h("p", { class: "cl-tag" }),
        h("div", { class: "cl-badges" }),
        h("footer", { class: "cl-foot" },
          h("span", { class: "cl-name" }, a.name, h("small", {}, a.department || "")),
          h("span", { class: "cl-ticker" })));
      grid.append(tile);
    }
    tile.dataset.status = a.status;
    tile.querySelector(".cl-tag").textContent = a.activity ? (a.status === "working" || a.status === "stalled" ? a.activity : `${STATUS[a.status] || a.status} · ${a.activity}`) : STATUS[a.status] || a.status;
    tile.querySelector(".cl-badges").replaceChildren(...badges(a));
    const ticker = tile.querySelector(".cl-ticker");
    ticker.replaceChildren(...(a.status === "working" || a.status === "stalled"
      ? [h("i", { class: "spin", "aria-hidden": "true" }), `${STATUS[a.status]} · ${since(a.since || a.last)}`]
      : [STATUS[a.status] || a.status]));
  }
  grid.querySelectorAll(".cl-tile").forEach((t) => { if (!seen.has(t.dataset.key)) t.remove(); });
  const order = { needs_you: 0, stalled: 1, working: 2, waiting: 3, your_turn: 4, done: 5, available: 6, idle: 7 };
  const sorted = [...agents].sort((x, y) => (order[x.status] ?? 9) - (order[y.status] ?? 9));
  list.replaceChildren(...sorted.map((a) => h("button", { type: "button", class: "cl-row", "data-status": a.status, onclick: () => spotlight(a.key, 25000) },
    h("i", { class: "dot", "aria-hidden": "true" }),
    h("span", { class: "cl-row-name" }, a.name, h("small", {}, a.activity || STATUS[a.status] || "")),
    a.tokens ? h("span", { class: "cl-row-tok" }, `⚡ ${tokens(a.tokens)}`) : null)));
}

let pinned = { key: "", until: 0 };
function spotlight(key, ms = 0) {
  if (ms) pinned = { key, until: Date.now() + ms };
  const target = pinned.until > Date.now() ? pinned.key : key;
  document.querySelectorAll("#cl-grid .cl-tile").forEach((t) => t.classList.toggle("spot", t.dataset.key === target));
}

/* ---------------------------------------------------------------- lines and voices */

function nameOf(key) {
  if (key === "you") return "Toi";
  return state.agents.find((a) => a.key === key)?.name || key;
}

function addLines(lines) {
  for (const line of lines) {
    state.transcript.push(line);
    $("#cl-lines").append(h("li", { "data-agent": line.agent }, h("time", {}, clock(line.ts)), h("b", {}, nameOf(line.agent)), " ", line.text));
    if (state.queue.length > 14) state.queue.shift();  // far behind: skip ahead
    state.queue.push(line);
  }
  if (state.transcript.length > 400) { state.transcript.splice(0, 100); const ol = $("#cl-lines"); while (ol.children.length > 300) ol.firstChild.remove(); }
  next();
}

function sentences(text) {
  return text.match(/[^.!?…]+[.!?…]*\s*/g)?.map((s) => s.trim()).filter(Boolean) || [text];
}

async function next() {
  if (state.speaking || !state.queue.length) return;
  const line = state.queue.shift();
  state.speaking = line;
  state.lastLine = Date.now();
  state.fillers = 0;
  const agent = state.agents.find((a) => a.key === line.agent);
  const face = agent ? faceFor(agent) : null;
  spotlight(line.agent);
  const tile = $(`#cl-grid [data-key="${CSS.escape(line.agent)}"]`);
  tile?.classList.add("talking");
  const sub = $("#cl-sub");
  const parts = line.agent === "you" ? [line.text] : sentences(line.text);
  for (const part of parts) {
    if (!state.open) break;
    sub.replaceChildren(h("b", {}, `${nameOf(line.agent)} : `), part);
    if (state.joined && line.agent !== "you") {
      await voice.speak(line.agent, agent?.gender || "m", part, (v) => face?.mouth(v));
    } else {
      face?.mouth(0.5);
      await new Promise((r) => setTimeout(r, Math.min(6000, 1400 + part.length * 45)));
      face?.mouth(0);
    }
  }
  tile?.classList.remove("talking");
  state.speaking = null;
  setTimeout(() => { if (!state.speaking) sub.replaceChildren(); }, 2500);
  next();
}

function filler() {  // the call is silent: now and then, a little line (at most three)
  if (!state.chatter || state.speaking || state.queue.length || state.replay) return;
  if (Date.now() - state.lastLine < 45000 || state.fillers >= 3) return;
  const pool = state.agents.filter((a) => ["working", "waiting", "stalled"].includes(a.status));
  if (!pool.length) return;
  const who = pool[Math.floor(Math.random() * pool.length)];
  state.fillers += 1;
  state.lastLine = Date.now();
  addLines([{ id: `f${Date.now()}`, ts: new Date().toISOString(), agent: who.key, text: FILLERS[(state.fillers + who.name.length) % FILLERS.length], kind: "filler" }]);
}

/* ---------------------------------------------------------------- shared screen */

function showScreen(s) {
  const box = $("#cl-screen");
  if (!s) { box.hidden = true; return; }
  const fresh = Date.now() - new Date(s.ts).getTime() < 8000 || s.status === "running";
  if (!fresh && !state.pinnedScreen) { box.hidden = true; return; }
  const args = s.args && Object.keys(s.args).length ? JSON.stringify(s.args, null, 1) : "";
  const result = String(s.result || "");
  const lines = result.split("\n");
  const shown = lines.slice(0, 18).join("\n") + (lines.length > 18 ? `\n… +${lines.length - 18} lignes` : "");
  box.hidden = false;
  box.replaceChildren(
    h("header", {}, h("b", {}, nameOf(s.agent)), " partage son écran",
      h("button", { class: "icon-btn", type: "button", "aria-pressed": String(state.pinnedScreen), title: "Garder l'écran affiché", onclick: () => { state.pinnedScreen = !state.pinnedScreen; showScreen(s); } }, state.pinnedScreen ? "📌" : "📍")),
    h("pre", { class: "cl-term" },
      h("span", { class: "cmd" }, `> ${s.tool} ${s.target || ""}\n`),
      args ? h("span", { class: "args" }, `${args}\n`) : null,
      h("span", { class: s.status === "fail" ? "err" : "out" }, shown)),
    h("footer", {}, s.status === "running" ? h("span", {}, h("i", { class: "spin" }), ` ${s.tool} · en cours ${since(s.ts)}`) : `${s.status === "fail" ? "✗" : "✓"} ${s.tool} · ${String(s.seconds || 0).replace(".", ",")} s`));
}

/* ---------------------------------------------------------------- live polling */

async function poll() {
  if (!state.open) return;
  try {
    if (state.source.kind === "team" && !state.replay) await pollTeam();
    else if (state.source.kind === "session") await pollSession();
  } catch { /* the PC is busy or asleep: try again */ }
  filler();
  state.timer = setTimeout(poll, 1500);
}

async function pollTeam() {
  const data = await api("GET", `call?since=${state.since}&ev=${state.ev}`);
  const first = !state.since;
  state.agents = [...data.agents, { key: "you", name: "Toi", department: "", status: "available", activity: "", gender: "m" }];
  renderTiles(state.agents);
  state.since = data.last_id;
  state.ev = data.last_event;
  if (!first) addLines(data.lines);
  showScreen(data.screen);
  summary(data.needs_you, data.working);
}

function summary(needs, working) {
  $("#cl-summary").textContent = `${working} au travail${needs ? ` · ${needs} attend${needs > 1 ? "ent" : ""} ton accord` : ""}`;
  document.title = needs ? `(${needs} ✋) ${state.titleBase}` : working ? `(${working} ⚙) ${state.titleBase}` : state.titleBase;
  if (state.wasWorking && !working && Date.now() - state.workSince > 60000) chime();
  if (working && !state.wasWorking) state.workSince = Date.now();
  state.wasWorking = working;
}

function chime() {  // the team has worked a while and gone quiet
  try {
    const ctx = new AudioContext();
    [660, 880].forEach((f, i) => {
      const o = ctx.createOscillator(); const g = ctx.createGain();
      o.frequency.value = f; g.gain.setValueAtTime(0.0001, ctx.currentTime + i * 0.18);
      g.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + i * 0.18 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + i * 0.18 + 0.5);
      o.connect(g).connect(ctx.destination); o.start(ctx.currentTime + i * 0.18); o.stop(ctx.currentTime + i * 0.18 + 0.55);
    });
  } catch { /* no sound */ }
}

/* ---------------------------------------------------------------- other tools' sessions */

const SESSION_STATE = { needs_you: "needs_you", working: "working", waiting: "waiting", your_turn: "your_turn", done: "done", idle: "idle" };

function sessionAgents(s) {
  return s.agents.map((a, i) => ({
    key: `${s.tool}:${a.id}`, name: a.name, department: a.lead ? `${s.label} · chef` : `${s.label} · sous-agent`,
    status: SESSION_STATE[a.status] || "idle", activity: a.activity, since: a.last, last: a.last,
    tokens: a.tokens, fails: a.fails, gender: i % 3 === 1 ? "f" : "m", lookKey: `${s.tool}-${a.lead ? "lead" : a.id}`,
  }));
}

async function pollSession() {
  const { tool, id } = state.source;
  const s = await api("GET", `call/session/${tool}/${encodeURIComponent(id)}`);
  state.agents = sessionAgents(s);
  renderTiles(state.agents);
  const events = s.events;
  if (state.sessionKnown && events.length > state.sessionKnown) {
    const fresh = events.slice(state.sessionKnown);
    addLines(fresh.filter((e) => ["say", "report", "order", "user"].includes(e.kind)).map((e, i) => ({
      id: `x${state.sessionKnown + i}`, ts: e.ts, agent: e.kind === "user" ? "you" : `${tool}:${e.agent}`,
      text: e.kind === "order" ? e.text.slice(0, 200) : sentences(e.text).slice(0, 2).join(" ").slice(0, 260), kind: e.kind,
    })));
    const lastTool = [...fresh].reverse().find((e) => e.kind === "tool");
    if (lastTool) showScreen({ agent: `${tool}:${lastTool.agent}`, tool: lastTool.tool, target: lastTool.text, args: {}, result: "", status: lastTool.done ? "ok" : "running", ts: lastTool.ts, seconds: 0 });
  }
  state.sessionKnown = events.length;
  const needs = state.agents.filter((a) => a.status === "needs_you").length;
  summary(needs, state.agents.filter((a) => a.status === "working").length);
}

function follow(source) {
  state.source = source;
  state.since = 0; state.ev = 0; state.sessionKnown = 0; state.queue = []; state.replay = null;
  state.faces.clear();
  $("#cl-grid").replaceChildren();
  $("#cl-replay").hidden = true;
  const banner = $("#cl-source");
  if (source.kind === "session") {
    banner.hidden = false;
    banner.replaceChildren(`Tu suis la session ${source.label} « ${source.title} ». `,
      h("button", { class: "btn btn-ghost", type: "button", onclick: () => follow({ kind: "team" }) }, h("span", {}, "Revenir à l'équipe de Spectre")));
  } else banner.hidden = true;
  switchView("call");
}

/* ---------------------------------------------------------------- stand-up, recap, tree, board */

async function standup() {
  try {
    const { lines } = await api("POST", "call/standup", {});
    if (!state.joined) toast("Rejoins l'appel pour entendre le tour de table ; les sous-titres s'affichent.", "warn", 6000);
    addLines(lines);
  } catch (err) { toast(err.message, "error"); }
}

async function recap(mission) {
  try {
    const q = typeof mission === "number" ? `?mission=${mission}` : "";
    const { markdown } = await api("GET", `call/recap${q}`);
    const dialog = $("#call-recap");
    dialog.replaceChildren(h("div", { class: "tm-detail" },
      h("header", { class: "tm-head" }, h("h3", { class: "tm-name" }, "Compte rendu"),
        h("button", { class: "icon-btn", type: "button", "aria-label": "Fermer", onclick: () => dialog.close() }, "✕")),
      h("pre", { class: "tm-prompt" }, markdown),
      h("div", { class: "tm-actions" },
        h("button", { class: "btn btn-primary", type: "button", onclick: async () => { await navigator.clipboard.writeText(markdown); toast("Compte rendu copié (Markdown)."); } }, h("span", {}, "Copier en Markdown")))));
    dialog.showModal();
  } catch (err) { toast(err.message, "error"); }
}

async function loadTree() {
  const t = await api("GET", "call/tree");
  const node = (name, status, extra, kids = []) => h("li", { "data-status": status || "" },
    h("span", { class: "cl-node" }, h("i", { class: "dot" }), h("b", {}, name), extra ? h("small", {}, extra) : null), kids.length ? h("ul", {}, kids) : null);
  $("#cl-tree").replaceChildren(h("ul", { class: "cl-tree-root" },
    node("Toi", "", "", [node(t.lead.name, t.lead.status, t.lead.activity || STATUS[t.lead.status] || "",
      t.missions.map((m) => node(`Mission #${m.mission}`, m.status === "running" ? "working" : m.status, m.goal.slice(0, 90),
        m.agents.map((a) => node(a.name, a.status, `${a.steps} étape(s) · ${a.tools} outil(s)${a.activity ? ` · ${a.activity}` : ""}`)))))])));
}

const MSTATE = { needs_you: "Attend ton accord", running: "En cours", queued: "En file", failed: "Échouées", done: "Terminées", cancelled: "Arrêtées" };
const SSTATE = { needs_you: "A besoin de toi ?", working: "Au travail", waiting: "Attend ses sous-agents", your_turn: "À toi de jouer", idle: "Inactives" };

async function loadBoard() {
  const { missions, sessions } = await api("GET", "call/board");
  const box = $("#cl-board");
  const group = (title, items) => items.length ? h("section", {}, h("h3", { class: "as-h as-h-sub" }, title), h("div", { class: "cl-cards" }, items)) : null;
  const mcard = (m) => h("article", { class: "cl-card", "data-status": m.state },
    h("h4", {}, `#${m.id} ${m.goal.slice(0, 110)}`),
    h("p", { class: "meta" }, `${m.agents.join(", ") || "Spectre"} · ${clock(m.updated_at)}`),
    h("div", { class: "tm-actions" },
      h("button", { class: "btn", type: "button", onclick: () => startReplay(m.id) }, h("span", {}, m.state === "running" ? "Suivre" : "Rejouer")),
      h("button", { class: "btn btn-ghost", type: "button", onclick: () => recap(m.id) }, h("span", {}, "Compte rendu"))));
  const scard = (s) => h("article", { class: "cl-card", "data-status": s.state },
    h("h4", {}, s.title),
    h("p", { class: "meta" }, `${s.label} · ${s.project.split(/[\\/]/).slice(-2).join("/")} · ${s.agents.length} agent${s.agents.length > 1 ? "s" : ""} · ${clock(s.updated)}`),
    h("div", { class: "tm-actions" }, h("button", { class: "btn", type: "button", onclick: () => follow({ kind: "session", tool: s.tool, id: s.id, label: s.label, title: s.title }) }, h("span", {}, "Suivre dans l'appel"))));
  const byState = (list, key, labels, render) => Object.keys(labels).map((st) => group(labels[st], list.filter((x) => x[key] === st).map(render)));
  box.replaceChildren(
    h("h3", { class: "as-h" }, "Missions de Spectre (12 h)"),
    ...(missions.length ? byState(missions, "state", MSTATE, mcard) : [h("p", { class: "meta" }, "Aucune mission ces 12 dernières heures.")]),
    h("h3", { class: "as-h" }, "Sessions Claude Code, Codex et Mistral Vibe (12 h)"),
    ...(sessions.length ? byState(sessions, "state", SSTATE, scard) : [h("p", { class: "meta" }, "Aucune session ces 12 dernières heures.")]));
}

/* ---------------------------------------------------------------- replay */

async function startReplay(mission) {
  const data = await api("GET", `call/replay/${mission}`);
  follow({ kind: "team" });
  state.replay = { data, index: 0, speed: 1, playing: true, timer: 0 };
  const team = await api("GET", `call?since=0`);
  state.agents = [...team.agents.map((a) => ({ ...a, status: "available", activity: "" })), { key: "you", name: "Toi", status: "available" }];
  renderTiles(state.agents);
  const box = $("#cl-replay");
  box.hidden = false;
  const slider = h("input", { type: "range", min: "0", max: String(Math.max(0, data.lines.length - 1)), value: "0", "aria-label": "Position", oninput: (e) => seek(Number(e.target.value)) });
  const play = h("button", { class: "btn", type: "button", onclick: () => { state.replay.playing = !state.replay.playing; play.firstChild.textContent = state.replay.playing ? "Pause" : "Lecture"; if (state.replay.playing) step(); } }, h("span", {}, "Pause"));
  box.replaceChildren(
    h("b", {}, `Relecture : mission #${mission}`), play, slider,
    ...[1, 2, 4, 8].map((s) => h("button", { class: "chip", type: "button", "aria-pressed": String(s === 1), onclick: (e) => { state.replay.speed = s; box.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c === e.currentTarget))); } }, `${s}×`)),
    ...data.highlights.map((hl) => h("button", { class: "btn btn-ghost", type: "button", onclick: () => seek(Math.max(0, data.lines.findIndex((l) => l.ts >= hl.ts))) }, h("span", {}, hl.label))),
    h("button", { class: "btn btn-ghost", type: "button", onclick: () => { state.replay = null; box.hidden = true; follow({ kind: "team" }); } }, h("span", {}, "Revenir au direct")));
  state.replay.slider = slider;
  $("#cl-lines").replaceChildren();
  step();
}

function seek(i) {
  if (!state.replay) return;
  state.replay.index = i;
  state.queue = [];
  voice.stop();
  state.replay.slider.value = String(i);
}

function step() {
  const r = state.replay;
  if (!r || !r.playing || !state.open) return;
  if (r.index >= r.data.lines.length) { r.playing = false; toast("Fin de la relecture."); return; }
  if (state.speaking || state.queue.length) { r.timer = setTimeout(step, 200); return; }
  const line = r.data.lines[r.index];
  const tool = r.data.tools.filter((t) => t.ts <= line.ts).pop();
  if (tool) showScreen({ ...tool, args: {}, ts: new Date().toISOString() });
  const a = state.agents.find((x) => x.key === line.agent);
  if (a) { state.agents.forEach((x) => { if (x.status === "working") x.status = "available"; }); a.status = line.kind === "step_start" ? "working" : line.kind === "approval" ? "needs_you" : "done"; a.activity = line.text.slice(0, 80); renderTiles(state.agents); }
  addLines([line]);
  r.index += 1;
  r.slider.value = String(r.index);
  const gap = r.index < r.data.lines.length ? Math.min(4000, Math.max(300, new Date(r.data.lines[r.index].ts) - new Date(line.ts))) : 0;
  r.timer = setTimeout(step, gap / r.speed);
}

/* ---------------------------------------------------------------- recording */

async function record(seconds) {
  if (state.recorder) { state.recorder.stop(); return; }
  if (!navigator.mediaDevices?.getDisplayMedia) { toast("Ce navigateur ne sait pas enregistrer l'onglet (essaie Chrome ou Edge sur le PC).", "error", 7000); return; }
  try {
    const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 30, width: 1280, height: 720 }, audio: true, preferCurrentTab: true, selfBrowserSurface: "include" });
    const type = ["video/mp4;codecs=avc1,mp4a.40.2", "video/mp4", "video/webm;codecs=vp9,opus", "video/webm"].find((t) => MediaRecorder.isTypeSupported(t)) || "";
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : {});
    const chunks = [];
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunks, { type: rec.mimeType || "video/webm" });
      const a = h("a", { href: URL.createObjectURL(blob), download: `spectre-visio${seconds ? "-clip" : ""}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.${(rec.mimeType || "").includes("mp4") ? "mp4" : "webm"}` });
      document.body.append(a); a.click(); a.remove();
      state.recorder = null;
      $("#cl-rec").firstChild.textContent = "Enregistrer";
      toast("Vidéo de la visio enregistrée dans tes téléchargements.");
    };
    stream.getVideoTracks()[0].addEventListener("ended", () => rec.state !== "inactive" && rec.stop());
    rec.start(1000);
    state.recorder = rec;
    $("#cl-rec").firstChild.textContent = "Arrêter l'enregistrement";
    if (seconds) setTimeout(() => rec.state !== "inactive" && rec.stop(), seconds * 1000);
  } catch (err) { if (err.name !== "NotAllowedError") toast(err.message, "error"); }
}

/* ---------------------------------------------------------------- open / close */

async function join() {
  try { await voice.unlock(); } catch { /* no audio context */ }
  state.joined = !state.joined;
  if (!state.joined) voice.stop();
  $("#cl-join").firstChild.textContent = state.joined ? "Couper le son" : "Rejoindre (son)";
  if (state.joined) toast(voice.useBrowser() ? "Tu es dans l'appel : les voix naturelles du navigateur parlent." : "Tu es dans l'appel : les voix de Spectre parlent.");
}

export function openCall() {
  build();
  if (state.open) return;
  state.open = true;
  state.titleBase = document.title.replace(/^\([^)]*\)\s*/, "");
  poll();
}

export function closeCall() {
  state.open = false;
  clearTimeout(state.timer);
  voice.stop();
  state.queue = [];
  document.title = state.titleBase;
}
