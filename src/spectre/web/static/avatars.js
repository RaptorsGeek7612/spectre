// Portraits of the team for the video call and the team page: drawn faces with soft light,
// each with its own features, hair and clothes, at a desk. They blink, breathe, and their lips
// follow the loudness of the voice. A picture the user gives an agent replaces the drawing.

const NS = "http://www.w3.org/2000/svg";
let uid = 0;

// skin, shade, hair, brows, eyes, lips, outfit, shirt, accent, style, beard, glasses, jewel, age
export const LOOKS = {
  opus: { g: "m", skin: "#e9c6a9", shade: "#c39373", hair: "#2a221d", eyes: "#3f6f91", lips: "#b77a6b", outfit: "#1d2738", shirt: "#d9dee6", accent: "#ffd23f", style: "short", beard: "stubble", bg: "#2b3a5c" },
  sonnet: { g: "m", skin: "#c5966f", shade: "#9a6c4b", hair: "#17110d", eyes: "#4a2f1e", lips: "#a2634f", outfit: "#2f4030", shirt: "#e8e2d4", accent: "#8bd450", style: "crew", beard: "", bg: "#2c4a34" },
  haiku: { g: "m", skin: "#f1d3b9", shade: "#cfa184", hair: "#cfcac2", eyes: "#56687a", lips: "#b8806f", outfit: "#30363f", shirt: "#f2f2ef", accent: "#4fc3f7", style: "neat", beard: "", glasses: "round", age: 1, bg: "#253e52" },
  chatgpt: { g: "f", skin: "#dcaa83", shade: "#b47e58", hair: "#6a2f17", eyes: "#2f6a4d", lips: "#b4574f", outfit: "#41324f", shirt: "#c9b8d8", accent: "#a084ff", style: "long", beard: "", jewel: true, bg: "#3d2f55" },
  mistral: { g: "m", skin: "#b88964", shade: "#8e6142", hair: "#0e0e11", eyes: "#2f2a26", lips: "#9b5e4a", outfit: "#18191c", shirt: "#2b2d33", accent: "#ff9f43", style: "undercut", beard: "short", hoodie: true, bg: "#4a3020" },
  cursor: { g: "f", skin: "#8b5838", shade: "#663d24", hair: "#18100c", eyes: "#3a2214", lips: "#7a3b35", outfit: "#1f2b4a", shirt: "#f1ece4", accent: "#7d86ff", style: "bun", beard: "", jewel: true, blazer: true, bg: "#26305a" },
  antigravity: { g: "f", skin: "#f0cdb2", shade: "#c99c7d", hair: "#87552d", eyes: "#4a6f92", lips: "#c0656a", outfit: "#3a3f47", shirt: "#eef1f5", accent: "#ef5f6f", style: "bob", beard: "", blazer: true, jewel: true, bg: "#4a2a33" },
  simon: { g: "m", skin: "#e5bd9d", shade: "#bd8f6f", hair: "#3b2c22", eyes: "#4a3826", lips: "#ad7462", outfit: "#5a4632", shirt: "#e9e4d8", accent: "#ffd23f", style: "receding", beard: "", glasses: "square", age: 1, cardigan: true, bg: "#4a4022" },
};
const CREATED = [
  { g: "m", skin: "#d8b08f", shade: "#b0835f", hair: "#3a2a1e", eyes: "#3b5a40", lips: "#a96a58", outfit: "#2c3e50", shirt: "#e6e6e6", accent: "#8bd450", style: "side", beard: "", bg: "#2a3d36" },
  { g: "f", skin: "#efcfb6", shade: "#c99d80", hair: "#c49a5a", eyes: "#4a6a8a", lips: "#c06a64", outfit: "#5b2e3f", shirt: "#f3e7ea", accent: "#ef5f6f", style: "long", beard: "", jewel: true, bg: "#4a2836" },
];

export function lookOf(key, gender) {
  if (LOOKS[key]) return LOOKS[key];
  const n = [...String(key)].reduce((a, c) => a + c.charCodeAt(0), 0);
  return CREATED[gender === "f" ? 1 : (n % 2 === 1 && gender !== "m" ? 1 : 0)];
}

function el(tag, attrs = {}, parent) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.append(n);
  return n;
}
const P = (d, attrs, parent) => el("path", { d, ...attrs }, parent);

const HEAD = {
  m: "M100 42C124 42 139 58 139 86C139 104 136 118 128 129C120 139 110 143 100 143C90 143 80 139 72 129C64 118 61 104 61 86C61 58 76 42 100 42Z",
  f: "M100 44C123 44 137 60 137 86C137 104 133 117 126 127C118 137 109 142 100 142C91 142 82 137 74 127C67 117 63 104 63 86C63 60 77 44 100 44Z",
};
const HAIR_BACK = {
  long: "M57 92C50 130 54 172 70 196L130 196C146 172 150 130 143 92C143 50 123 34 100 34C77 34 57 50 57 92Z",
  bun: "M100 18A15 15 0 1 1 99.9 18Z",
  bob: "M58 92C55 58 78 37 100 37C122 37 145 58 142 92L144 134C128 142 72 142 56 134Z",
};
const HAIR_FRONT = {
  short: "M60 90C57 55 78 33 103 33C128 33 145 52 141 90C138 74 133 62 122 57C108 64 86 61 73 56C66 63 62 74 60 90Z",
  side: "M60 92C56 56 78 33 104 33C129 34 145 54 141 92C137 72 128 60 116 55C100 52 84 58 70 60C64 68 61 78 60 92Z M70 60C86 52 102 47 120 50C108 46 92 46 78 52Z",
  crew: "M62 82C61 52 80 37 100 37C120 37 139 52 138 82C132 65 119 55 100 55C81 55 68 65 62 82Z",
  neat: "M62 86C59 58 78 38 101 38C124 38 142 56 138 86C135 70 128 60 118 57C110 60 92 60 80 56C70 62 64 72 62 86Z",
  long: "M60 96C56 58 80 36 104 37C129 38 143 60 140 96C133 72 120 58 99 55C86 63 72 76 60 96Z",
  bob: "M59 98C55 58 80 36 104 37C129 38 145 60 141 98C134 74 122 60 104 57C92 64 74 74 59 98Z",
  bun: "M62 88C60 57 80 41 100 41C120 41 140 57 138 88C131 67 117 57 100 57C83 57 69 67 62 88Z",
  undercut: "M65 72C64 44 85 31 108 33C129 35 141 52 137 76C127 61 111 55 93 57C80 59 72 64 65 72Z",
  receding: "M60 94C59 70 65 57 74 53C71 64 69 77 70 94Z M140 94C141 70 135 57 126 53C129 64 131 77 130 94Z M82 50C93 45 109 45 120 50C109 48 93 48 82 50Z",
};

const STYLE_KEY = "spectre-avatar-style";
export function artStyle() { try { return localStorage.getItem(STYLE_KEY) || "manga"; } catch { return "manga"; } }
export function setArtStyle(value) { try { localStorage.setItem(STYLE_KEY, value); } catch { /* private window */ } }

// A portrait: the agent's look (or the one the user made for it), in manga or realistic style.
export function createAvatar(key, gender = "m", { title = "", look = null, art = "" } = {}) {
  const L = { ...lookOf(key, gender), ...(look || {}) };
  return (art || artStyle()) === "realiste" ? createRealistic(L, title) : createManga(L, title);
}

function createRealistic(L, title) {
  const id = `av${++uid}`;
  const svg = el("svg", { viewBox: "24 22 152 152", class: "avatar", role: "img", "aria-label": title || "agent" });
  const defs = el("defs", {}, svg);
  const grad = (gid, stops, kind = "linearGradient", attrs = {}) => {
    const g = el(kind, { id: `${id}-${gid}`, ...attrs }, defs);
    stops.forEach(([o, c, op = 1]) => el("stop", { offset: o, "stop-color": c, "stop-opacity": op }, g));
    return `url(#${id}-${gid})`;
  };
  const bg = grad("bg", [[0, L.bg], [1, "#0c0d10"]], "radialGradient", { cx: "0.35", cy: "0.25", r: "0.95" });
  const skin = grad("skin", [[0, lighten(L.skin, 0.12)], [0.55, L.skin], [1, L.shade]], "radialGradient", { cx: "0.4", cy: "0.38", r: "0.7" });
  const hair = grad("hair", [[0, lighten(L.hair, 0.22)], [0.6, L.hair], [1, darken(L.hair, 0.25)]], "linearGradient", { x1: "0.2", y1: "0", x2: "0.8", y2: "1" });
  const outfit = grad("outfit", [[0, lighten(L.outfit, 0.18)], [1, darken(L.outfit, 0.2)]], "linearGradient", { x1: "0", y1: "0", x2: "0", y2: "1" });
  const iris = grad("iris", [[0, lighten(L.eyes, 0.35)], [0.7, L.eyes], [1, darken(L.eyes, 0.4)]], "radialGradient", {});
  const light = grad("light", [[0, "#fff", 0.16], [1, "#fff", 0]], "radialGradient", { cx: "0.3", cy: "0.2", r: "0.8" });
  const blush = grad("blush", [[0, "#e0786a", 0.22], [1, "#e0786a", 0]], "radialGradient", {});

  // room, light from a window, the desk
  el("rect", { width: 200, height: 200, fill: bg }, svg);
  el("rect", { x: 128, y: 14, width: 58, height: 70, rx: 4, fill: "#fff", opacity: 0.05 }, svg);
  el("rect", { x: 130, y: 16, width: 26, height: 66, fill: "#fff", opacity: 0.03 }, svg);
  const body = el("g", { class: "av-body" }, svg);
  if (HAIR_BACK[L.style]) P(HAIR_BACK[L.style], { fill: hair }, body);
  // shoulders and clothes
  P("M18 200C22 168 50 155 79 151L121 151C150 155 178 168 182 200Z", { fill: outfit }, body);
  P("M88 128L88 156C94 161 106 161 112 156L112 128Z", { fill: L.shade }, body);
  el("ellipse", { cx: 100, cy: 142, rx: 15, ry: 6, fill: "#000", opacity: 0.28 }, body);
  if (L.hoodie) {
    P("M64 152C68 139 84 137 100 147C116 137 132 139 136 152C121 163 79 163 64 152Z", { fill: lighten(L.outfit, 0.1) }, body);
    P("M94 158L93 182M106 158L107 182", { stroke: "#9a9a9a", "stroke-width": 1.4, "stroke-linecap": "round", fill: "none" }, body);
  } else {
    P("M84 151L100 178L116 151Z", { fill: L.shirt }, body);
    if (L.tie) P("M97 157L103 157L105.5 186L100 193L94.5 186Z", { fill: L.accent }, body);
    if (L.blazer || L.tie) {
      P("M79 151L100 192L91 200L66 200C70 180 74 162 79 151Z", { fill: lighten(L.outfit, 0.08) }, body);
      P("M121 151L100 192L109 200L134 200C130 180 126 162 121 151Z", { fill: lighten(L.outfit, 0.08) }, body);
    }
    if (L.cardigan) {
      P("M84 151L100 200L80 200C78 180 80 162 84 151Z M116 151L100 200L120 200C122 180 120 162 116 151Z", { fill: darken(L.outfit, 0.12) }, body);
      [168, 182, 194].forEach((y) => el("circle", { cx: 97 - (y - 168) / 8, cy: y, r: 1.6, fill: "#d8c9a8" }, body));
    }
  }
  // head
  const head = el("g", { class: "av-head" }, body);
  el("ellipse", { cx: 60.5, cy: 95, rx: 6, ry: 11, fill: L.shade }, head);
  el("ellipse", { cx: 139.5, cy: 95, rx: 6, ry: 11, fill: L.shade }, head);
  if (L.jewel) {
    el("circle", { cx: 60, cy: 108, r: 2.2, fill: "#e8c56a" }, head);
    el("circle", { cx: 140, cy: 108, r: 2.2, fill: "#e8c56a" }, head);
  }
  P(HEAD[L.g], { fill: skin }, head);
  P("M66 112C70 131 86 144 100 144C114 144 130 131 134 112C128 128 116 138 100 139C84 138 72 128 66 112Z", { fill: L.shade, opacity: 0.35 }, head);
  el("ellipse", { cx: 80, cy: 112, rx: 10, ry: 6, fill: blush }, head);
  el("ellipse", { cx: 120, cy: 112, rx: 10, ry: 6, fill: blush }, head);
  if (L.age) {
    P("M78 104Q82 106 86 104M114 104Q118 106 122 104", { stroke: L.shade, "stroke-width": 0.8, fill: "none", opacity: 0.7 }, head);
    P("M88 70Q100 67 112 70", { stroke: L.shade, "stroke-width": 0.8, fill: "none", opacity: 0.5 }, head);
  }
  // beard
  if (L.beard) {
    const strong = L.beard === "stubble" ? 0.22 : 0.8;
    P("M64 104C66 128 84 147 100 147C116 147 134 128 136 104C131 122 120 134 112 132C106 129 94 129 88 132C80 134 69 122 64 104Z", { fill: L.hair, opacity: strong }, head);
    P("M86 121Q93 116 100 118Q107 116 114 121Q107 120 100 121Q93 120 86 121Z", { fill: L.hair, opacity: Math.min(1, strong + 0.15) }, head);
  }
  for (const cx of [84, 116]) {
    el("ellipse", { cx, cy: 90, rx: 13, ry: 7, fill: L.shade, opacity: 0.22 }, head);
    P(`M${cx - 8} ${99}Q${cx} ${102} ${cx + 8} ${99}`, { stroke: L.shade, "stroke-width": 0.9, fill: "none", opacity: 0.45 }, head);
  }
  // eyes
  const eyes = [];
  for (const cx of [84, 116]) {
    const cy = 93;
    const eye = el("g", {}, head);
    const clip = el("clipPath", { id: `${id}-eye${cx}` }, defs);
    const shape = `M${cx - 10} ${cy}C${cx - 6} ${cy - 6.5} ${cx + 6} ${cy - 6.5} ${cx + 10} ${cy}C${cx + 6} ${cy + 5} ${cx - 6} ${cy + 5} ${cx - 10} ${cy}Z`;
    P(shape, {}, clip);
    P(shape, { fill: "#f7f3ee" }, eye);
    const inner = el("g", { "clip-path": `url(#${id}-eye${cx})` }, eye);
    const pupil = el("g", { class: "av-pupil" }, inner);
    el("circle", { cx, cy: cy + 0.3, r: 4.8, fill: iris }, pupil);
    el("circle", { cx, cy: cy + 0.3, r: 2.2, fill: "#111" }, pupil);
    el("circle", { cx: cx + 1.6, cy: cy - 1.4, r: 1.2, fill: "#fff", opacity: 0.9 }, pupil);
    const lid = el("rect", { x: cx - 11, y: cy - 7, width: 22, height: 0, fill: L.skin }, inner);
    P(`M${cx - 10.5} ${cy}C${cx - 6} ${cy - 7} ${cx + 6} ${cy - 7} ${cx + 10.5} ${cy}`, { stroke: darken(L.hair, 0.1), "stroke-width": L.g === "f" ? 2 : 1.3, fill: "none", "stroke-linecap": "round" }, eye);
    if (L.g === "f") P(`M${cx + (cx < 100 ? -10 : 10)} ${cy - 0.5}l${cx < 100 ? -2.5 : 2.5} -2`, { stroke: "#111", "stroke-width": 1.2, "stroke-linecap": "round" }, eye);
    P(`M${cx - 12} ${cy - 11 - (L.g === "f" ? 1.5 : 0)}Q${cx} ${cy - 16} ${cx + 12} ${cy - 11.5}`, { stroke: darken(L.hair === "#cfcac2" ? "#8a8580" : L.hair, 0.05), "stroke-width": L.g === "f" ? 2.2 : 3.4, fill: "none", "stroke-linecap": "round" }, head);
    eyes.push({ lid, pupil });
  }
  // nose
  P("M100 96Q98.5 105 94.5 110.5Q99.5 114 105.5 110.5", { stroke: L.shade, "stroke-width": 1.4, fill: "none", "stroke-linecap": "round", opacity: 0.8 }, head);
  P("M101 92Q102 100 101.5 104", { stroke: "#fff", "stroke-width": 1, opacity: 0.18, fill: "none" }, head);
  P("M95.5 96Q94 104 95 109", { stroke: L.shade, "stroke-width": 2.4, fill: "none", opacity: 0.25, "stroke-linecap": "round" }, head);
  el("ellipse", { cx: 96.2, cy: 111.3, rx: 1.6, ry: 0.9, fill: darken(L.shade, 0.35), opacity: 0.6 }, head);
  el("ellipse", { cx: 103.8, cy: 111.3, rx: 1.6, ry: 0.9, fill: darken(L.shade, 0.35), opacity: 0.6 }, head);
  // mouth: the inside opens with the voice, the lower lip follows
  const mouth = el("g", { class: "av-mouth" }, head);
  const inside = el("ellipse", { cx: 100, cy: 125.5, rx: 8.5, ry: 0.01, fill: "#3b1513" }, mouth);
  const teeth = el("rect", { x: 93, y: 123.5, width: 14, height: 0, rx: 1.5, fill: "#f4efe8" }, mouth);
  P("M88.5 125Q94.5 121 100 122.6Q105.5 121 111.5 125Q100 126.6 88.5 125Z", { fill: L.lips }, mouth);
  const lower = P("M89 125.4Q100 133.5 111 125.4Q100 127.6 89 125.4Z", { fill: darken(L.lips, 0.06) }, mouth);
  P("M95 129.2Q100 130.6 105 129.2", { stroke: "#fff", "stroke-width": 0.9, opacity: 0.22, fill: "none", "stroke-linecap": "round" }, lower.parentNode);
  // hair over the forehead
  P(HAIR_FRONT[L.style] || HAIR_FRONT.short, { fill: hair }, head);
  const strands = { short: [[70, 60, 100, 40, 128, 52], [76, 56, 104, 38, 134, 60], [66, 70, 92, 46, 120, 46]],
    side: [[72, 58, 98, 44, 124, 50], [68, 66, 96, 40, 132, 56], [80, 54, 106, 42, 138, 70]],
    crew: [[70, 62, 100, 44, 130, 62], [76, 56, 100, 42, 124, 56]],
    neat: [[70, 60, 100, 42, 130, 58], [74, 56, 102, 40, 126, 52]],
    long: [[66, 84, 82, 52, 112, 46], [70, 76, 92, 46, 124, 50], [128, 60, 140, 80, 141, 104], [62, 100, 56, 130, 60, 170], [138, 100, 146, 140, 140, 176]],
    bun: [[68, 74, 86, 50, 100, 44], [132, 74, 114, 50, 100, 44], [92, 22, 100, 18, 108, 22]],
    undercut: [[70, 64, 92, 40, 120, 40], [76, 58, 100, 36, 132, 52]],
    receding: [[64, 70, 66, 60, 74, 55], [136, 70, 134, 60, 126, 55]] }[L.style] || [];
  strands.forEach(([x1, y1, cx, cy, x2, y2]) => P(`M${x1} ${y1}Q${cx} ${cy} ${x2} ${y2}`, { stroke: lighten(L.hair, 0.35), "stroke-width": 0.9, opacity: 0.35, fill: "none", "stroke-linecap": "round" }, head));
  if (L.style === "undercut") {
    P("M62 92C61 80 63 70 66 66L68 92Z M138 92C139 80 137 70 134 66L132 92Z", { fill: L.hair, opacity: 0.45 }, head);
  }
  P("M78 46Q96 38 116 42", { stroke: "#fff", "stroke-width": 1.2, opacity: 0.12, fill: "none" }, head);
  // glasses
  if (L.glasses) {
    const frame = { stroke: "#2b2b2e", "stroke-width": 1.8, fill: "#9ad0ff", "fill-opacity": 0.06 };
    if (L.glasses === "round") {
      el("circle", { cx: 84, cy: 93, r: 10, ...frame }, head);
      el("circle", { cx: 116, cy: 93, r: 10, ...frame }, head);
    } else {
      el("rect", { x: 72, y: 85, width: 24, height: 15, rx: 3, ...frame }, head);
      el("rect", { x: 104, y: 85, width: 24, height: 15, rx: 3, ...frame }, head);
    }
    P("M94 92Q100 89 106 92", { stroke: "#2b2b2e", "stroke-width": 1.6, fill: "none" }, head);
    P("M76 88L82 86M108 88L114 86", { stroke: "#fff", "stroke-width": 1, opacity: 0.4 }, head);
  }
  el("rect", { width: 200, height: 200, fill: light, "pointer-events": "none" }, svg);
  // desk and laptop
  el("rect", { x: 0, y: 184, width: 200, height: 16, fill: "#2a241f" }, svg);
  el("rect", { x: 0, y: 184, width: 200, height: 1.5, fill: "#fff", opacity: 0.08 }, svg);
  el("rect", { x: 0, y: 182, width: 200, height: 2, fill: L.accent, opacity: 0.16, class: "av-screen" }, svg);

  // ---- life: blink, breathe, speak ----
  let open = 0;
  let target = 0;
  let timer = 0;
  function blink() {
    eyes.forEach((e) => e.lid.setAttribute("height", "14"));
    setTimeout(() => eyes.forEach((e) => e.lid.setAttribute("height", "0")), 120);
    timer = setTimeout(blink, 2400 + Math.random() * 3800);
  }
  timer = setTimeout(blink, 600 + Math.random() * 3000);
  function draw() {
    open += (target - open) * 0.45;
    const o = Math.max(0, Math.min(1, open));
    inside.setAttribute("ry", (o * 5.2 + 0.01).toFixed(2));
    teeth.setAttribute("height", (Math.min(o * 2.6, 2.4)).toFixed(2));
    lower.setAttribute("transform", `translate(0 ${(o * 5).toFixed(2)})`);
  }
  return {
    el: svg,
    mouth(level) { target = level; draw(); },
    look(dx = 0, dy = 0) { eyes.forEach((e) => e.pupil.setAttribute("transform", `translate(${dx} ${dy})`)); },
    stop() { clearTimeout(timer); },
  };
}

function hex(c) { const n = parseInt(c.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; }
function rgb([r, g, b]) { return `#${[r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("")}`; }
function lighten(c, k) { return rgb(hex(c).map((v) => v + (255 - v) * k)); }
function darken(c, k) { return rgb(hex(c).map((v) => v * (1 - k))); }

// A picture given by the user, in place of the drawing (no lips to move: the frame glows).
export function createPhoto(url, title = "") {
  const img = document.createElement("img");
  img.className = "avatar avatar-photo";
  img.src = url;
  img.alt = title;
  img.decoding = "async";
  return { el: img, mouth(level) { img.style.setProperty("--talk", level.toFixed(2)); }, look() {}, stop() {} };
}

// ---- manga style: big shining eyes, pointed bangs, flat colours with hard shadows ----------

// Bangs: the hair's outline over the head, then a row of points across the forehead.
function bangs(style) {
  const tips = {
    short: [[66, 78], [74, 66], [82, 74], [90, 62], [99, 72], [108, 60], [117, 70], [126, 62], [134, 76]],
    side: [[64, 84], [70, 70], [80, 76], [88, 64], [100, 70], [112, 58], [124, 64], [134, 60], [138, 80]],
    crew: [[66, 70], [78, 60], [90, 64], [100, 58], [110, 64], [122, 60], [134, 70]],
    neat: [[64, 78], [76, 66], [88, 70], [100, 62], [112, 68], [124, 64], [136, 76]],
    long: [[62, 96], [68, 76], [78, 84], [86, 66], [96, 76], [106, 62], [116, 74], [126, 64], [134, 80], [138, 98]],
    bob: [[62, 92], [70, 74], [80, 82], [90, 66], [100, 76], [110, 66], [120, 80], [130, 70], [138, 92]],
    bun: [[66, 80], [80, 64], [94, 60], [108, 60], [122, 64], [134, 80]],
    undercut: [[68, 66], [80, 50], [94, 56], [106, 46], [120, 54], [132, 62]],
    receding: [[66, 78], [70, 64], [74, 56]],
  }[style] || [[66, 78], [100, 64], [134, 78]];
  const sweep = { side: 6, long: 3, bob: 2, undercut: 5 }[style] || 0;
  let d = "M58 96C54 54 78 30 100 30C122 30 146 54 142 96";
  let [px, py] = [142, 96];
  for (let i = tips.length - 1; i >= 0; i--) {  // curved strands from notch to tip and back
    const [x, y] = tips[i];
    const [nx, ny] = i > 0 ? [(x + tips[i - 1][0]) / 2, Math.min(y, tips[i - 1][1]) - 11] : [58, 96];
    d += `Q${px + (x - px) * 0.15 + sweep} ${py + (y - py) * 0.85} ${x} ${y}`;
    d += `Q${x + (nx - x) * 0.7 + sweep / 2} ${y + (ny - y) * 0.15} ${nx} ${ny}`;
    [px, py] = [nx, ny];
  }
  return `${d}Z`;
}
const MANGA_BACK = {
  long: "M56 90C48 130 52 172 60 196L76 184L84 198L100 186L116 198L124 184L140 196C148 172 152 130 144 90C142 48 122 30 100 30C78 30 58 48 56 90Z",
  bob: "M56 90C52 116 54 132 58 140L70 134L78 142L90 136L100 142L110 136L122 142L130 134L142 140C146 132 148 116 144 90C142 48 122 30 100 30C78 30 58 48 56 90Z",
  bun: "M100 12A17 17 0 1 1 99.9 12Z",
};

function createManga(L, title) {
  const id = `mg${++uid}`;
  const svg = el("svg", { viewBox: "24 14 152 160", class: "avatar avatar-manga", role: "img", "aria-label": title || "agent" });
  const defs = el("defs", {}, svg);
  const grad = (gid, stops, kind = "linearGradient", attrs = {}) => {
    const g = el(kind, { id: `${id}-${gid}`, ...attrs }, defs);
    stops.forEach(([o, c, op = 1]) => el("stop", { offset: o, "stop-color": c, "stop-opacity": op }, g));
    return `url(#${id}-${gid})`;
  };
  const bg = grad("bg", [[0, lighten(L.bg, 0.15)], [1, darken(L.bg, 0.55)]], "linearGradient", { x1: "0", y1: "0", x2: "0.4", y2: "1" });
  const iris = grad("iris", [[0, darken(L.eyes, 0.45)], [0.55, L.eyes], [1, lighten(L.eyes, 0.55)]], "linearGradient", { x1: "0", y1: "0", x2: "0", y2: "1" });
  const shine = grad("shine", [[0, lighten(L.hair, 0.5)], [1, lighten(L.hair, 0.15)]]);
  const ink = darken(L.hair === "#cfcac2" ? "#6d6964" : L.hair, 0.55);
  const line = { stroke: darken(L.shade, 0.45), "stroke-width": 1.2, "stroke-linejoin": "round" };

  // background: soft panel with screen-tone dots
  el("rect", { x: 0, y: 0, width: 200, height: 200, fill: bg }, svg);
  const tone = el("pattern", { id: `${id}-tone`, width: 6, height: 6, patternUnits: "userSpaceOnUse" }, defs);
  el("circle", { cx: 3, cy: 3, r: 0.9, fill: "#fff", opacity: 0.08 }, tone);
  el("rect", { x: 0, y: 0, width: 200, height: 200, fill: `url(#${id}-tone)` }, svg);
  P("M150 14L176 14L176 120Z", { fill: "#fff", opacity: 0.05 }, svg);

  const body = el("g", { class: "av-body" }, svg);
  if (MANGA_BACK[L.style]) P(MANGA_BACK[L.style], { fill: L.hair, ...line }, body);
  // shoulders and clothes, cel-shaded
  P("M18 200C22 170 50 156 80 152L120 152C150 156 178 170 182 200Z", { fill: L.outfit, ...line }, body);
  P("M120 152C150 156 178 170 182 200L150 200C150 180 138 162 120 152Z", { fill: darken(L.outfit, 0.25) }, body);
  P("M89 126L89 156C95 160 105 160 111 156L111 126Z", { fill: L.skin, ...line }, body);
  P("M89 138C96 144 104 144 111 138L111 150C104 154 96 154 89 150Z", { fill: L.shade, opacity: 0.7 }, body);
  if (L.hoodie) {
    P("M64 154C68 140 84 138 100 148C116 138 132 140 136 154C121 164 79 164 64 154Z", { fill: lighten(L.outfit, 0.12), ...line }, body);
    P("M94 160L93 184M106 160L107 184", { stroke: "#cfcfcf", "stroke-width": 1.6, "stroke-linecap": "round" }, body);
  } else {
    P("M85 152L100 177L115 152Z", { fill: L.shirt, ...line }, body);
    if (L.tie) P("M97 158L103 158L105 186L100 192L95 186Z", { fill: L.accent, ...line }, body);
    if (L.blazer || L.tie) {
      P("M80 152L100 192L91 200L66 200C70 180 74 162 80 152Z", { fill: lighten(L.outfit, 0.1), ...line }, body);
      P("M120 152L100 192L109 200L134 200C130 180 126 162 120 152Z", { fill: lighten(L.outfit, 0.04), ...line }, body);
    }
    if (L.cardigan) P("M85 152L100 200L80 200C78 180 80 162 85 152Z M115 152L100 200L120 200C122 180 120 162 115 152Z", { fill: darken(L.outfit, 0.15), ...line }, body);
  }

  const head = el("g", { class: "av-head" }, body);
  // ears and face: a pointed chin, a hard shadow under the bangs and along one cheek
  el("ellipse", { cx: 61, cy: 96, rx: 5.5, ry: 9, fill: L.skin, ...line }, head);
  el("ellipse", { cx: 139, cy: 96, rx: 5.5, ry: 9, fill: L.skin, ...line }, head);
  if (L.jewel) {
    el("circle", { cx: 60.5, cy: 107, r: 2.3, fill: "#f2cf6b", ...line }, head);
    el("circle", { cx: 139.5, cy: 107, r: 2.3, fill: "#f2cf6b", ...line }, head);
  }
  const jaw = L.g === "f"
    ? "M100 40C126 40 139 58 139 84C139 101 135 114 126 126C117 137 108 145 100 146C92 145 83 137 74 126C65 114 61 101 61 84C61 58 74 40 100 40Z"
    : "M100 40C126 40 140 58 140 84C140 102 137 115 129 127C120 138 109 145 100 146C91 145 80 138 71 127C63 115 60 102 60 84C60 58 74 40 100 40Z";
  P(jaw, { fill: L.skin, ...line }, head);
  P("M128 84C136 104 132 122 120 134C112 141 104 145 100 146C112 140 126 124 128 104Z", { fill: L.shade, opacity: 0.55 }, head);
  // eyes: tall irises with two highlights, a thick upper lash line
  const eyes = [];
  for (const cx of [83, 117]) {
    const cy = 96;
    const eye = el("g", {}, head);
    const shape = `M${cx - 12} ${cy - 1}C${cx - 8} ${cy - 10} ${cx + 8} ${cy - 11} ${cx + 12} ${cy - 3}C${cx + 9} ${cy + 8} ${cx - 9} ${cy + 8} ${cx - 12} ${cy - 1}Z`;
    const clip = el("clipPath", { id: `${id}-e${cx}` }, defs);
    P(shape, {}, clip);
    P(shape, { fill: "#fbfaf7" }, eye);
    const inner = el("g", { "clip-path": `url(#${id}-e${cx})` }, eye);
    const pupil = el("g", { class: "av-pupil" }, inner);
    el("ellipse", { cx, cy: cy + 0.5, rx: 6.6, ry: 8.4, fill: iris }, pupil);
    el("ellipse", { cx, cy: cy + 1, rx: 3, ry: 4.4, fill: darken(L.eyes, 0.7) }, pupil);
    el("ellipse", { cx: cx - 2.4, cy: cy - 3.2, rx: 2.4, ry: 2.8, fill: "#fff" }, pupil);
    el("circle", { cx: cx + 2.6, cy: cy + 3.6, r: 1.2, fill: "#fff", opacity: 0.9 }, pupil);
    const lid = el("rect", { x: cx - 13, y: cy - 12, width: 26, height: 0, fill: L.skin }, inner);
    const outer = cx < 100 ? -1 : 1;
    P(`M${cx - 12.5} ${cy - 1}C${cx - 8} ${cy - 11} ${cx + 8} ${cy - 12} ${cx + 12.5} ${cy - 3}l${outer * 3} ${-2.5}`, { stroke: ink, "stroke-width": L.g === "f" ? 3.2 : 2.6, fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round" }, eye);
    P(`M${cx - 7} ${cy + 7.2}Q${cx} ${cy + 8.4} ${cx + 7} ${cy + 6.6}`, { stroke: ink, "stroke-width": 0.9, fill: "none", opacity: 0.7 }, eye);
    P(`M${cx - 11} ${cy - 17}Q${cx} ${cy - 21} ${cx + 11} ${cy - 17.5}`, { stroke: ink, "stroke-width": L.g === "f" ? 1.6 : 2.6, fill: "none", "stroke-linecap": "round" }, head);
    eyes.push({ lid, pupil });
  }
  // blush hatching, a small nose, a small mouth
  for (const cx of [78, 122]) {
    P(`M${cx - 6} ${114}l3 -4M${cx - 1} ${114}l3 -4M${cx + 4} ${114}l3 -4`, { stroke: "#e2706b", "stroke-width": 1.1, opacity: 0.55, "stroke-linecap": "round" }, head);
  }
  P("M101 108L98.5 113.5L101.5 113.5", { stroke: darken(L.shade, 0.3), "stroke-width": 1.1, fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round" }, head);
  const mouth = el("g", { class: "av-mouth" }, head);
  const inside = el("path", { d: "M94 123Q100 123 106 123Q100 123 94 123Z", fill: "#7a2b2b", stroke: darken(L.shade, 0.5), "stroke-width": 1 }, mouth);
  const tongue = el("ellipse", { cx: 100, cy: 126, rx: 3.4, ry: 0, fill: "#e0807b" }, mouth);
  P("M94 123Q100 125 106 123", { stroke: darken(L.shade, 0.5), "stroke-width": 1.3, fill: "none", "stroke-linecap": "round" }, mouth);
  if (L.beard) {
    const strong = L.beard === "stubble" ? 0.25 : 0.85;
    P("M66 108C68 128 84 146 100 147C116 146 132 128 134 108C129 124 118 134 112 133C106 130 94 130 88 133C82 134 71 124 66 108Z", { fill: L.hair, opacity: strong }, head);
    P("M89 120Q95 116 100 118Q105 116 111 120Q105 119.5 100 120Q95 119.5 89 120Z", { fill: L.hair, opacity: Math.min(1, strong + 0.1) }, head);
  }
  if (L.age) P("M74 104l5 1.5M126 104l-5 1.5", { stroke: L.shade, "stroke-width": 1, "stroke-linecap": "round" }, head);
  // hair: pointed bangs, a hard shadow band and the glossy « halo »
  const front = el("g", {}, head);
  if (L.style === "receding") {
    P("M58 98C56 74 62 58 72 52L76 64L70 74L72 98Z M142 98C144 74 138 58 128 52L124 64L130 74L128 98Z", { fill: L.hair, ...line }, front);
    P("M80 46C92 40 108 40 120 46C108 44 92 44 80 46Z", { fill: L.hair, opacity: 0.8 }, front);
  } else {
    P(bangs(L.style), { fill: L.hair, ...line }, front);
    P("M66 70C80 50 120 46 136 66C122 56 82 56 66 70Z", { fill: darken(L.hair, 0.3), opacity: 0.6 }, front);
    P("M74 52C88 40 112 38 128 50L124 54C112 46 92 46 78 56Z", { fill: shine, opacity: 0.55 }, front);
    if (L.style === "undercut") P("M60 96C58 82 60 72 64 66L68 96Z M140 96C142 82 140 72 136 66L132 96Z", { fill: darken(L.hair, 0.2), opacity: 0.55 }, front);
  }
  if (L.glasses) {
    const frame = { stroke: "#26262a", "stroke-width": 2, fill: "#bfe3ff", "fill-opacity": 0.12 };
    if (L.glasses === "round") {
      el("circle", { cx: 83, cy: 96, r: 13, ...frame }, head);
      el("circle", { cx: 117, cy: 96, r: 13, ...frame }, head);
    } else {
      el("rect", { x: 68, y: 86, width: 30, height: 19, rx: 4, ...frame }, head);
      el("rect", { x: 102, y: 86, width: 30, height: 19, rx: 4, ...frame }, head);
    }
    P("M96 94Q100 91 104 94", { stroke: "#26262a", "stroke-width": 1.8, fill: "none" }, head);
    P("M72 90L80 87M106 90L114 87", { stroke: "#fff", "stroke-width": 1.4, opacity: 0.6 }, head);
  }

  let open = 0;
  let target = 0;
  let timer = 0;
  function blink() {
    eyes.forEach((e) => e.lid.setAttribute("height", "22"));
    setTimeout(() => eyes.forEach((e) => e.lid.setAttribute("height", "0")), 110);
    timer = setTimeout(blink, 2200 + Math.random() * 3800);
  }
  timer = setTimeout(blink, 500 + Math.random() * 3000);
  function draw() {
    open += (target - open) * 0.5;
    const o = Math.max(0, Math.min(1, open));
    const h = (o * 8).toFixed(2);
    inside.setAttribute("d", `M94 123Q100 ${(123 - o * 1.5).toFixed(2)} 106 123Q100 ${(123 + Number(h)).toFixed(2)} 94 123Z`);
    tongue.setAttribute("ry", (o * 2.2).toFixed(2));
    tongue.setAttribute("cy", (123 + o * 5).toFixed(2));
  }
  return {
    el: svg,
    mouth(level) { target = level; draw(); },
    look(dx = 0, dy = 0) { eyes.forEach((e) => e.pupil.setAttribute("transform", `translate(${dx} ${dy})`)); },
    stop() { clearTimeout(timer); },
  };
}
