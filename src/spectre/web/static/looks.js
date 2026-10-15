// « Create a Sim » for the team: skin, hair, eyes, beard, glasses, clothes, background, with a
// live portrait (manga or realistic). Used on the team page and when creating an agent.

import { h } from "./kit.js";
import { artStyle, createAvatar, lookOf } from "./avatars.js";

const SKINS = [["#f6dcc6", "#d6ae92"], ["#f0cdb2", "#c99c7d"], ["#e5bd9d", "#bd8f6f"], ["#d7a77f", "#b47e58"], ["#c5966f", "#9a6c4b"], ["#a8754f", "#7f5233"], ["#8b5838", "#663d24"], ["#5e3a24", "#432616"]];
const HAIRS = ["#15110e", "#3b2c22", "#6a2f17", "#87552d", "#c49a5a", "#e3c27a", "#cfcac2", "#8a1f2d", "#2d4f8f", "#6b3fa0"];
const EYES = ["#3f6f91", "#4a6f92", "#2f6a4d", "#4a3826", "#2f2a26", "#6b4a2a", "#7a5aa8", "#3a8a8a"];
const CLOTHES = ["#1d2738", "#2f4030", "#41324f", "#18191c", "#3a3f47", "#5a4632", "#7a2232", "#2a5a7a"];
const BACKS = ["#2b3a5c", "#2c4a34", "#3d2f55", "#4a3020", "#26305a", "#4a2a33", "#4a4022", "#253e52"];
const STYLES = [["short", "Courts"], ["side", "Raie sur le côté"], ["crew", "Très courts"], ["neat", "Soignés"], ["long", "Longs"], ["bob", "Carré"], ["bun", "Chignon"], ["undercut", "Rasés sur les côtés"], ["receding", "Dégarnis"]];
const BEARDS = [["", "Aucune"], ["stubble", "Naissante"], ["short", "Courte"], ["trim", "Taillée"]];
const GLASSES = [["", "Aucune"], ["round", "Rondes"], ["square", "Rectangulaires"]];
const OUTFITS = [["shirt", "Chemise"], ["tie", "Costume et cravate"], ["blazer", "Tailleur, veste"], ["hoodie", "Sweat à capuche"], ["cardigan", "Gilet"]];

function outfitKind(L) { return L.tie ? "tie" : L.blazer ? "blazer" : L.hoodie ? "hoodie" : L.cardigan ? "cardigan" : "shirt"; }

// The editor in `dialog`; `onSave(look)` gets the settings ({} = back to the usual portrait).
export function openLookEditor(dialog, { key, gender, name, look, onSave }) {
  const base = lookOf(key, gender);
  const L = { ...base, ...(look || {}) };
  const state = {
    g: L.g, skin: L.skin, shade: L.shade, hair: L.hair, eyes: L.eyes, style: L.style, beard: L.beard || "",
    glasses: L.glasses || "", outfit_kind: outfitKind(L), outfit: L.outfit, jewel: !!L.jewel, age: !!L.age, bg: L.bg,
  };
  let art = artStyle();
  const preview = h("div", { class: "lk-preview" });
  const draw = () => {
    const kinds = { tie: state.outfit_kind === "tie", blazer: state.outfit_kind === "blazer", hoodie: state.outfit_kind === "hoodie", cardigan: state.outfit_kind === "cardigan" };
    const face = createAvatar(key, state.g, { look: { ...state, ...kinds }, art, title: name });
    preview.replaceChildren(face.el);
  };
  const swatches = (field, colors, pair) => h("div", { class: "lk-swatches", role: "radiogroup" }, colors.map((c) => {
    const value = pair ? c[0] : c;
    return h("button", { type: "button", class: "lk-swatch", style: `--c:${value}`, role: "radio", "aria-checked": String(state[field] === value), "aria-label": value,
      onclick: (e) => { state[field] = value; if (pair) state.shade = c[1]; e.currentTarget.parentNode.querySelectorAll(".lk-swatch").forEach((b) => b.setAttribute("aria-checked", String(b === e.currentTarget))); draw(); } });
  }));
  const chips = (field, options) => h("div", { class: "lk-chips" }, options.map(([value, label]) => h("button", { type: "button", class: "chip", "aria-pressed": String(state[field] === value),
    onclick: (e) => { state[field] = value; e.currentTarget.parentNode.querySelectorAll(".chip").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget))); draw(); } }, label)));
  const toggle = (field, label) => h("label", { class: "cl-toggle" }, h("input", { type: "checkbox", checked: state[field], onchange: (e) => { state[field] = e.target.checked; draw(); } }), label);
  const row = (label, control) => h("div", { class: "lk-row" }, h("span", { class: "label" }, label), control);

  dialog.replaceChildren(h("div", { class: "tm-detail lk" },
    h("header", { class: "tm-head" }, h("h3", { class: "tm-name" }, `Apparence${name ? ` de ${name}` : ""}`),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Fermer", onclick: () => dialog.close() }, "✕")),
    h("div", { class: "lk-body" },
      h("div", { class: "lk-side" }, preview,
        h("div", { class: "lk-chips" }, [["manga", "Manga"], ["realiste", "Réaliste"]].map(([v, t]) => h("button", { type: "button", class: "chip", "aria-pressed": String(v === art),
          onclick: (e) => { art = v; e.currentTarget.parentNode.querySelectorAll(".chip").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget))); draw(); } }, t)))),
      h("div", { class: "lk-controls" },
        row("Traits", chips("g", [["f", "Féminins"], ["m", "Masculins"]])),
        row("Peau", swatches("skin", SKINS, true)),
        row("Coiffure", chips("style", STYLES)),
        row("Cheveux", swatches("hair", HAIRS)),
        row("Yeux", swatches("eyes", EYES)),
        row("Barbe", chips("beard", BEARDS)),
        row("Lunettes", chips("glasses", GLASSES)),
        row("Tenue", chips("outfit_kind", OUTFITS)),
        row("Couleur de la tenue", swatches("outfit", CLOTHES)),
        row("Fond", swatches("bg", BACKS)),
        h("div", { class: "lk-row" }, toggle("jewel", "Boucles d'oreilles"), toggle("age", "Plus âgé·e")))),
    h("div", { class: "tm-actions" },
      h("button", { class: "btn btn-primary", type: "button", onclick: () => { onSave({ ...state }); dialog.close(); } }, h("span", {}, "Enregistrer l'apparence")),
      look && Object.keys(look).length ? h("button", { class: "btn btn-ghost", type: "button", onclick: () => { onSave({}); dialog.close(); } }, h("span", {}, "Revenir au portrait d'origine")) : null)));
  draw();
  dialog.showModal();
}
