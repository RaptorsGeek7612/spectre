// The team page: every agent with its portrait, department, engine and model (both can be
// changed), its voice on the call, its record, costs and recent work.

import { $, api, clock, h, money, toast, tokens } from "./kit.js";
import { artStyle, createAvatar, createPhoto, setArtStyle } from "./avatars.js";
import { openLookEditor } from "./looks.js";
import * as voice from "./voice.js";

const LEVEL = { apprenti: "○ apprenti", "confirmé": "◐ confirmé", expert: "● expert" };
const CLAUDE = [["opus", "Opus 5.5 · Claude"], ["sonnet", "Sonnet 5.5 · Claude"], ["haiku", "Haiku 4.5 · Claude"]];
const INSTALL = {
  kimi: "Kimi Code n'est pas installé : demande à Spectre de l'installer, ou passe Simon sur un autre moteur (DeepSeek par exemple).",
  cursor: "Cursor CLI introuvable sur ce PC.",
  antigravity: "Antigravity CLI (agy) introuvable sur ce PC.",
};

let groups = null;
async function engineGroups() {
  if (groups) return groups;
  const data = await api("GET", "models");
  const ready = data.providers.filter((p) => p.ready);
  const lists = await Promise.all(ready.map((p) => api("GET", `models/${encodeURIComponent(p.id)}`).catch(() => ({ models: [] }))));
  groups = [
    { label: "Claude, sur ton abonnement", items: CLAUDE.map(([value, text]) => ({ value, text })) },
    ...ready.map((p, i) => ({ label: p.label, items: lists[i].models.filter((m) => !/embed/i.test(m)).map((m) => ({ value: `${p.id}:${m}`, text: m })) }))
      .filter((g) => g.items.length),
  ];
  return groups;
}

function select(name, value, options, first) {
  const known = options.some((g) => g.items.some((i) => i.value === value)) || (first && first.value === value);
  return h("select", { name },
    first ? h("option", { value: first.value, selected: value === first.value }, first.text) : null,
    value && !known ? h("option", { value, selected: true }, `${value} (actuel)`) : null,
    ...options.map((g) => h("optgroup", { label: g.label }, ...g.items.map((i) => h("option", { value: i.value, selected: i.value === value }, i.text)))));
}

async function change(agent, data, label) {
  try {
    await api("POST", `team/${encodeURIComponent(agent.key)}`, data);
    toast(`${agent.name} : ${label}.`);
    groups = null;
    loadTeam();
  } catch (err) { toast(err.message, "error", 8000); }
}

function portrait(agent, size = "") {
  const face = agent.portrait
    ? createPhoto(`/api/assistant/team/${encodeURIComponent(agent.key)}/portrait?t=${Date.now()}`, agent.name)
    : createAvatar(agent.key, agent.gender, { title: agent.name, look: agent.look });
  face.el.classList.add("tm-face");
  if (size) face.el.classList.add(size);
  return face;
}

function card(agent, engines, voices) {
  const face = portrait(agent);
  const tags = [h("span", { class: "tm-tool" }, agent.moved ? `${agent.engine} (au lieu de ${agent.tool})` : agent.tool)];
  if (!agent.available) tags.push(h("span", { class: "off" }, "outil introuvable"));
  if (agent.created) tags.push(h("span", {}, "créé par toi"));

  const engineField = (() => {
    if (agent.role_setting) {
      return h("label", {}, h("span", { class: "label" }, "Moteur (LLM)"),
        select("engine", agent.engine, engines, null));
    }
    if (agent.own_tool) {
      return h("label", {}, h("span", { class: "label" }, "Moteur (LLM)"),
        select("engine", agent.moved ? agent.engine : agent.key, engines, { value: agent.key, text: `Son outil : ${agent.tool}` }));
    }
    return h("label", {}, h("span", { class: "label" }, "Moteur (LLM)"), select("engine", agent.engine, engines, null));
  })();
  engineField.querySelector("select").addEventListener("change", (e) => change(agent, { engine: e.target.value }, "moteur changé"));

  const fields = [engineField];
  if (agent.own_tool && !agent.moved) {
    const model = h("select", { name: "model", disabled: true }, h("option", { value: agent.model }, agent.model || "Le modèle par défaut de l'outil"));
    fields.push(h("label", {}, h("span", { class: "label" }, `Modèle dans ${agent.tool}`), model));
    api("GET", `team/${encodeURIComponent(agent.key)}/models`).then(({ models }) => {
      model.replaceChildren(
        h("option", { value: "", selected: !agent.model }, "Le modèle par défaut de l'outil"),
        agent.model && !models.some((m) => m.id === agent.model) ? h("option", { value: agent.model, selected: true }, `${agent.model} (actuel)`) : null,
        ...models.map((m) => h("option", { value: m.id, selected: m.id === agent.model }, m.label === m.id ? m.id : `${m.label} — ${m.id}`)));
      model.disabled = false;
    }).catch(() => {});
    model.addEventListener("change", (e) => change(agent, { model: e.target.value }, "modèle changé"));
  }
  const voiceSelect = h("select", { name: "voice" }, ...Object.entries(voices).map(([id, v]) =>
    h("option", { value: id, selected: id === agent.voice }, `${v[2]}${v[3] === "f" ? " (femme)" : " (homme)"}`)));
  voiceSelect.addEventListener("change", (e) => change(agent, { voice: e.target.value }, "voix changée"));
  const listen = h("button", { class: "btn btn-ghost", type: "button", onclick: async () => {
    await voice.unlock().catch(() => {});
    voice.stop();
    const text = `Bonjour, je suis ${agent.name}. ${agent.department}. Je suis prêt${agent.gender === "f" ? "e" : ""} à travailler.`;
    voice.speak(agent.key, agent.gender, text, (v) => face.mouth(v));
  } }, h("span", {}, "Écouter"));
  fields.push(h("label", {}, h("span", { class: "label" }, voice.useBrowser() ? "Voix (locale, si le navigateur n'en a pas)" : "Voix"), h("div", { class: "tm-row" }, voiceSelect, listen)));

  const upload = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", hidden: true, onchange: async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try { await api("POST", `team/${encodeURIComponent(agent.key)}/portrait`, undefined, file); toast(`Photo de ${agent.name} enregistrée.`); loadTeam(); }
    catch (err) { toast(err.message, "error", 7000); }
  } });
  const actions = h("div", { class: "tm-actions" },
    h("button", { class: "btn", type: "button", onclick: () => details(agent) }, h("span", {}, "Détails")),
    h("button", { class: "btn btn-ghost", type: "button", onclick: () => openLookEditor($("#team-detail"), { key: agent.key, gender: agent.gender, name: agent.name, look: agent.look,
      onSave: (look) => change(agent, { look }, "apparence enregistrée") }) }, h("span", {}, "Apparence")),
    h("button", { class: "btn btn-ghost", type: "button", onclick: () => upload.click() }, h("span", {}, agent.portrait ? "Changer la photo" : "Mettre une photo")),
    agent.portrait ? h("button", { class: "btn btn-ghost", type: "button", onclick: async () => { await api("POST", `team/${encodeURIComponent(agent.key)}/portrait/delete`, {}); loadTeam(); } }, h("span", {}, "Portrait dessiné")) : null,
    upload);

  return h("article", { class: "tm-card", "data-agent": agent.key },
    h("div", { class: "tm-head" }, face.el,
      h("div", {},
        h("h3", { class: "tm-name" }, agent.name),
        h("p", { class: "tm-dept" }, agent.department),
        h("div", { class: "ag-tags" }, tags))),
    h("p", { class: "tm-role" }, agent.role),
    !agent.available && INSTALL[agent.key] ? h("p", { class: "tm-warn" }, INSTALL[agent.key]) : null,
    h("dl", { class: "tm-stats" },
      h("div", {}, h("dt", {}, "Dossier"), h("dd", {}, `${LEVEL[agent.level] || agent.level} · ${String(agent.reliability).replace(".", ",")} %`)),
      h("div", {}, h("dt", {}, "Étapes (30 j)"), h("dd", {}, `${agent.steps_ok} ✓ / ${agent.steps}`)),
      h("div", {}, h("dt", {}, "Appels · jetons"), h("dd", {}, `${agent.calls} · ${tokens(agent.tokens)}`)),
      h("div", {}, h("dt", {}, "Coût (30 j)"), h("dd", {}, money(agent.cost)))),
    h("div", { class: "tm-fields" }, fields),
    actions);
}

async function details(agent) {
  const dialog = $("#team-detail");
  const data = await api("GET", `team/${encodeURIComponent(agent.key)}`);
  const face = portrait(agent, "tm-face-lg");
  const recent = data.recent.length ? data.recent.map((r) => {
    let detail = {};
    try { detail = JSON.parse(r.detail || "{}"); } catch { detail = { text: r.detail }; }
    const label = r.kind === "tool" ? `${r.title} ${detail.target || ""}` : `${KIND[r.kind] || r.kind} : ${r.title}`;
    const body = detail.result || detail.text || detail.note || (detail.args ? JSON.stringify(detail.args, null, 1) : "");
    return h("details", { class: "tm-act", "data-status": r.status },
      h("summary", {}, h("span", { class: "tm-act-time" }, clock(r.ts)), h("span", { class: "tm-act-label" }, label),
        h("span", { class: "tm-act-meta" }, `${r.status === "ok" ? "✓" : r.status === "fail" ? "✗" : r.status === "running" ? "…" : ""} ${r.seconds ? `${r.seconds} s` : ""}`)),
      detail.args ? h("pre", {}, JSON.stringify(detail.args, null, 1)) : null,
      body ? h("pre", {}, String(body).slice(0, 2000)) : null);
  }) : [h("p", { class: "meta" }, "Rien encore : son activité apparaîtra ici dès sa première mission.")];
  const counts = Object.entries(data.tools).map(([k, n]) => `${k} ${n}`).join(" · ") || "aucun outil utilisé";
  dialog.replaceChildren(h("div", { class: "tm-detail" },
    h("header", { class: "tm-head" }, face.el, h("div", {}, h("h3", { class: "tm-name" }, agent.name), h("p", { class: "tm-dept" }, `${agent.department} · ${agent.moved ? agent.engine : agent.tool}`)),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Fermer", onclick: () => dialog.close() }, "✕")),
    h("h4", {}, "Consignes et spécialité"), h("pre", { class: "tm-prompt" }, data.prompt || agent.role),
    h("h4", {}, "Outils utilisés"), h("p", { class: "meta" }, counts),
    h("h4", {}, "Dernières actions"), h("div", { class: "tm-acts" }, recent)));
  dialog.showModal();
}
const KIND = { step_start: "étape", step_done: "étape finie", mission_start: "mission", mission_done: "mission finie", approval: "demande d'accord" };

export async function loadTeam() {
  const [{ agents, voices }, engines] = await Promise.all([api("GET", "team"), engineGroups()]);
  const box = $("#team");
  box.replaceChildren(...agents.map((a) => card(a, engines, voices)));
  const count = $("#count-team");
  if (count) count.textContent = agents.length;
  const style = $("#team-art");
  if (style && !style.dataset.ready) {
    style.dataset.ready = "1";
    style.value = artStyle();
    style.addEventListener("change", () => { setArtStyle(style.value); loadTeam(); });
  }
  const mode = $("#team-voice-mode");
  if (mode && !mode.dataset.ready) {
    mode.dataset.ready = "1";
    mode.value = voice.mode();
    mode.addEventListener("change", () => { voice.setMode(mode.value); toast("Voix de la visio changée."); loadTeam(); });
  }
}
