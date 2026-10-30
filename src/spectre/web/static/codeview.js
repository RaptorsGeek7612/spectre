// The live code viewer: the files an agent writes, read again every two seconds, newest first,
// with line numbers, light syntax colours, the changed lines lit, and « Ouvrir dans VS Code ».
// Used by the « View » button of the team cards and by the task cards of the board.

import { $, api, clock, h } from "./kit.js";

const KEYWORDS = new Set(("fn let mut pub impl struct enum trait use mod crate self Self match if else for while loop return break continue async await move ref where type const static unsafe extern dyn as in "
  + "def class import from with try except finally raise lambda yield pass None True False and or not is global nonlocal elif "
  + "function var new this typeof instanceof export default extends super null undefined true false switch case do throw catch delete void of interface implements package private protected public "
  + "SELECT FROM WHERE INSERT INTO UPDATE DELETE CREATE TABLE JOIN ON AND OR NOT NULL PRIMARY KEY VALUES ORDER BY GROUP").split(" "));
const TOKEN = /(\/\/[^\n]*|#(?![\[!])[^\n]*|\/\*[\s\S]*?\*\/|<!--[\s\S]*?-->|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`|\b\d[\d_.]*\b|\b[A-Za-z_][A-Za-z0-9_]*\b)/g;
const HASH_COMMENT = new Set(["python", "bash", "powershell", "toml", "yaml", "text"]);

function colour(text, lang) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    const t = m[0];
    let cls = "";
    if (t.startsWith("#")) { if (!HASH_COMMENT.has(lang)) continue; cls = "cv-com"; }
    else if (t.startsWith("//") || t.startsWith("/*") || t.startsWith("<!--")) cls = lang === "python" && t.startsWith("//") ? "" : "cv-com";
    else if (/^["'`]/.test(t)) cls = "cv-str";
    else if (/^\d/.test(t)) cls = "cv-num";
    else if (KEYWORDS.has(t)) cls = "cv-kw";
    else if (/^[A-Z][a-z]/.test(t)) cls = "cv-type";
    if (!cls) continue;
    if (m.index > last) out.push(document.createTextNode(text.slice(last, m.index)));
    out.push(h("span", { class: cls }, t));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(document.createTextNode(text.slice(last)));
  return out;
}

// The code with line numbers; lines that differ from `before` are lit (what just changed).
export function codeBlock(text, lang, before = null) {
  const tidy = (t) => t.replace(/\r\n?/g, "\n").replace(/\n$/, "");
  const old = before === null ? null : tidy(before).split("\n");
  const lines = tidy(text).split("\n");
  const body = h("code", { class: `cv-code lang-${lang}` });
  let firstChange = -1;
  lines.forEach((line, i) => {
    const changed = old !== null && old[i] !== line;
    if (changed && firstChange < 0) firstChange = i;
    body.append(h("span", { class: `cv-line${changed ? " cv-new" : ""}` }, h("span", { class: "cv-n", "aria-hidden": "true" }, String(i + 1)), ...colour(line, lang), "\n"));
  });
  const pre = h("pre", { class: "cv-pre", tabindex: "0" }, body);
  pre.dataset.firstChange = String(firstChange);
  return pre;
}

export function vscodeLink(path, line = 1) {
  return `vscode://file/${path.replace(/\\/g, "/")}:${line}`;
}

// A viewer in `dialog`: `poll()` -> { files: [{path, name, lang, ts, writing, edits}], doing, dev },
// `read(path)` -> { text, lang, size, cut, missing }. Follows the newest file unless one is picked.
export function openCodeView(dialog, { title, subtitle = "", poll, read }) {
  let timer = null, chosen = null, follow = true, known = new Map(), lastSig = "";
  const list = h("nav", { class: "cv-files", "aria-label": "Fichiers écrits" });
  const head = h("div", { class: "cv-filehead" });
  const pane = h("div", { class: "cv-pane" }, h("p", { class: "meta" }, "En attente du premier fichier…"));
  const doing = h("p", { class: "cv-doing meta", "aria-live": "polite" });
  const followBox = h("input", { type: "checkbox", checked: true, onchange: (e) => { follow = e.target.checked; if (follow) chosen = null; tick(); } });
  const dev = h("div", { class: "cv-dev" });
  const close = () => { clearTimeout(timer); timer = null; dialog.close(); };
  dialog.replaceChildren(h("div", { class: "tm-detail cv" },
    h("header", { class: "cv-top" },
      h("div", {}, h("h3", { class: "tm-name" }, title), subtitle ? h("p", { class: "tm-dept" }, subtitle) : null),
      h("label", { class: "cv-follow" }, followBox, h("span", {}, "Suivre en direct")),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Fermer", onclick: close }, "✕")),
    doing,
    h("div", { class: "cv-body" }, list, h("section", { class: "cv-main" }, head, pane)),
    dev));
  dialog.addEventListener("close", () => { clearTimeout(timer); timer = null; }, { once: true });

  async function showFile(file) {
    const data = await read(file.path);
    const before = known.get(file.path);
    const sig = `${file.path}|${data.size}|${data.mtime || ""}`;
    if (sig === lastSig) return;
    const block = data.missing ? h("p", { class: "meta" }, "Ce fichier n'existe plus (déplacé ou supprimé).") : codeBlock(data.text, data.lang, lastSig.startsWith(`${file.path}|`) ? before : null);
    known.set(file.path, data.text);
    lastSig = sig;
    head.replaceChildren(
      h("strong", {}, file.name), h("span", { class: "meta" }, ` ${file.path}`),
      h("span", { class: "meta" }, ` · ${data.lang} · ${Math.round((data.size || 0) / 102.4) / 10} ko${data.cut ? " (tronqué)" : ""} · ${clock(file.ts)}`),
      h("a", { class: "btn btn-ghost", href: vscodeLink(file.path, Math.max(1, Number(block.dataset?.firstChange || 0) + 1)) }, h("span", {}, "Ouvrir dans VS Code")));
    pane.replaceChildren(block);
    const first = Number(block.dataset?.firstChange || -1);
    if (first > 0) block.querySelectorAll(".cv-line")[first]?.scrollIntoView({ block: "center" });
  }

  async function tick() {
    try {
      const data = await poll();
      doing.textContent = data.doing ? `${data.doing_status === "running" ? "● En train de : " : "Dernière action : "}${data.doing}${data.doing_ts ? ` (${clock(data.doing_ts)})` : ""}` : "Aucune activité pour l'instant.";
      const files = data.files || [];
      list.replaceChildren(...(files.length ? files.map((f) => h("button", {
        type: "button", class: "cv-file", "aria-current": String(f.path === (chosen || files[0].path)),
        title: f.path, onclick: () => { chosen = f.path; follow = false; followBox.checked = false; lastSig = ""; tick(); },
      }, h("span", { class: "cv-fname" }, f.writing ? `● ${f.name}` : f.name), h("span", { class: "meta" }, `${clock(f.ts)}${f.edits > 1 ? ` · ×${f.edits}` : ""}`))) : [h("p", { class: "meta" }, "Aucun fichier écrit ces 30 derniers jours.")]));
      const target = files.find((f) => f.path === (follow ? files[0]?.path : chosen)) || files[0];
      if (target) await showFile(target);
      dev.replaceChildren(...(data.dev || []).map((j) => h("details", { class: "cv-devjob", open: j.status === "working" },
        h("summary", {}, `Département technique · #${j.id} ${j.request} · ${j.status} · branche ${j.branch}`),
        h("p", { class: "meta" }, j.changed.length ? `Fichiers modifiés : ${j.changed.join(", ")}` : "Aucun fichier modifié pour l'instant."),
        j.diff ? codeBlock(j.diff, "diff") : null)));
    } catch (err) { doing.textContent = `Lecture impossible : ${err.message}`; }
    if (dialog.open) timer = setTimeout(tick, 2000);
  }
  dialog.showModal();
  tick();
}

// « View » on a team card
export function viewAgent(agent) {
  const key = encodeURIComponent(agent.key);
  openCodeView($("#team-detail"), {
    title: `${agent.name} — code en direct`,
    subtitle: agent.department,
    poll: () => api("GET", `team/${key}/code`),
    read: (path) => api("GET", `team/${key}/code/file?path=${encodeURIComponent(path)}`),
  });
}

export function viewTask(task, dialog) {
  openCodeView(dialog, {
    title: `Tâche #${task.id} — code`,
    subtitle: task.title,
    poll: async () => {
      const card = await api("GET", `tasks/${task.id}`);
      const step = (card.mission.steps || []).slice(-1)[0];
      return { files: card.files, doing: step ? `${step.agent} : ${step.title}` : card.mission.status || "", doing_status: card.mission.status === "running" ? "running" : "", dev: [] };
    },
    read: (path) => api("GET", `tasks/${task.id}/file?path=${encodeURIComponent(path)}`),
  });
}
