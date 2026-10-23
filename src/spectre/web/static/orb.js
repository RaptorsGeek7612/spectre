// Spectre's voice orb: a rotating 3-D sphere of light points (its "mind"), wrapped in tilted
// electron orbits, a plasma core, a circular oscilloscope that reacts to the live voice level,
// and a HUD of rotating arcs and corner brackets. It breathes, listens, thinks and speaks; on
// boot and on every wake the points peel off the sphere to spell SPECTRE, then stream back.
//
// Public API (unchanged): new Orb(canvas); orb.setState(state); orb.setLevel(0..1);
// orb.spellWord(holdSeconds). States: off, sleeping, listening, thinking, speaking.
// Honors prefers-reduced-motion (one calm frame) and the theme colors
// --l486 (main) / --l589 (accent) / --font-mark.

const TAU = Math.PI * 2;
const COUNT = 1700; // points on the mind-sphere
const WAVE = 180; // oscilloscope samples around the ring
const ORBITS = 2; // tilted electron orbits (kept few so the globe stays readable)
const WORD = "SPECTRE";

const MOODS = {
  //          wobble, level gain, scale, alpha, spin,  spectrum, sweep, tilt (3-D lean), glow
  off:       { wobble: 0.002, gain: 0,     scale: 0.92, alpha: 0.45, spin: 0.05, spectrum: 0.0,  sweep: 0, tilt: 0.20, glow: 0.15 },
  sleeping:  { wobble: 0.004, gain: 0,     scale: 0.96, alpha: 0.85, spin: 0.10, spectrum: 0.10, sweep: 0, tilt: 0.28, glow: 0.3 },
  listening: { wobble: 0.007, gain: 0.07,  scale: 1.06, alpha: 1.0,  spin: 0.30, spectrum: 0.85, sweep: 0, tilt: 0.36, glow: 0.75 },
  thinking:  { wobble: 0.014, gain: 0,     scale: 1.0,  alpha: 0.98, spin: 1.15, spectrum: 0.3,  sweep: 1, tilt: 0.5,  glow: 0.55 },
  speaking:  { wobble: 0.008, gain: 0.09,  scale: 1.04, alpha: 1.0,  spin: 0.44, spectrum: 1.0,  sweep: 0, tilt: 0.4,  glow: 1.0 },
};

function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function rgb(hex) {
  const m = hex.replace("#", "").match(/.{2}/g) || ["4f", "c3", "f7"];
  return m.map((x) => parseInt(x, 16));
}

const mix = (a, b, t) => [
  Math.round(a[0] + (b[0] - a[0]) * t),
  Math.round(a[1] + (b[1] - a[1]) * t),
  Math.round(a[2] + (b[2] - a[2]) * t),
];

// a cool futuristic spread the sphere points are tinted across: cyan, teal, blue, violet, magenta
const PALETTE = [
  [79, 195, 247], [45, 224, 192], [58, 134, 255], [138, 125, 255], [255, 106, 213],
];

export class Orb {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.state = "sleeping";
    this.level = 0;
    this.smooth = 0;
    this.beat = 0; // decaying kick on every loudness surge
    this.rot = 0; // accumulated sphere rotation (so spin speed changes stay smooth)
    this.mood = { ...MOODS.sleeping };
    this.spell = 0;
    this.spellUntil = 0;
    this.reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.readColors();
    let seed = 486;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    this.rnd = rnd;
    // evenly distributed points on a unit sphere (spiral), each with a shimmer phase and size
    this.points = Array.from({ length: COUNT }, (_, i) => {
      const y = 1 - (i / (COUNT - 1)) * 2; // -1..1
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const phi = i * 2.399963; // golden-angle spiral
      // tint most points along the palette by their height; sprinkle a few vivid random ones
      const base = PALETTE[Math.min(PALETTE.length - 1, Math.floor(((y + 1) / 2) * PALETTE.length))];
      const col = rnd() < 0.18 ? PALETTE[Math.floor(rnd() * PALETTE.length)] : base;
      return {
        x: Math.cos(phi) * r, y, z: Math.sin(phi) * r,
        phase: rnd() * TAU,
        size: 0.8 + rnd() * 1.4,
        band: rnd(),
        col,
        tx: 0, ty: 0, // home inside the wordmark
      };
    });
    this.wave = new Array(WAVE).fill(0);
    this.ripples = []; // expanding rings that burst out when the voice surges
    this.orbits = Array.from({ length: ORBITS }, (_, i) => ({
      tilt: 0.5 + i * 0.55, // radians, each orbit leans differently
      yaw: (i / ORBITS) * Math.PI,
      speed: (i % 2 ? -1 : 1) * (0.4 + i * 0.25),
      rad: 1.02 + i * 0.14,
      bead: rnd() * TAU, // the bright electron riding the orbit
    }));
    this.resize();
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    document.fonts?.ready.then(() => this.layoutWord());
    this.frame = this.frame.bind(this);
    this.last = performance.now();
    requestAnimationFrame(this.frame);
  }

  readColors() {
    this.colors = {
      main: rgb(cssVar("--l486", "#4fc3f7")),
      accent: rgb(cssVar("--l589", "#ffd23f")),
    };
  }

  resize() {
    const box = this.canvas.parentElement.getBoundingClientRect();
    const size = Math.max(160, Math.min(box.width, box.height));
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    this.canvas.style.width = this.canvas.style.height = `${size}px`;
    this.canvas.width = this.canvas.height = Math.round(size * dpr);
    this.size = size;
    this.dpr = dpr;
    this.readColors();
    this.layoutWord();
    if (this.reduced) this.draw(performance.now() / 1000);
  }

  layoutWord() {
    const w = 600, h = 160;
    const off = document.createElement("canvas");
    off.width = w; off.height = h;
    const g = off.getContext("2d");
    g.fillStyle = "#fff";
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.font = `300 120px ${cssVar("--font-mark", "sans-serif")}`;
    g.fillText(WORD, w / 2, h / 2 + 6);
    const data = g.getImageData(0, 0, w, h).data;
    const spots = [];
    for (let y = 0; y < h; y += 3) for (let x = 0; x < w; x += 3) if (data[(y * w + x) * 4 + 3] > 128) spots.push([x, y]);
    if (!spots.length) return;
    const span = 0.66;
    this.points.forEach((p, i) => {
      const [x, y] = spots[Math.floor((i / COUNT) * spots.length)];
      p.tx = ((x - w / 2) / w) * span;
      p.ty = ((y - h / 2) / w) * span;
    });
  }

  setState(state) {
    const waking = (this.state === "sleeping" || this.state === "off") && state === "listening";
    this.state = MOODS[state] ? state : "sleeping";
    if (waking) this.spellWord(1.1);
    if (this.reduced) this.draw(performance.now() / 1000);
  }

  setLevel(v) {
    const next = Math.max(0, Math.min(1, Number(v) || 0));
    // a surge in loudness kicks the core and sends a ring rippling outward — you SEE the voice
    if (next > this.level + 0.1 && (this.state === "speaking" || this.state === "listening")) {
      this.beat = Math.min(1, this.beat + (next - this.level) * 1.4);
      if (this.ripples.length < 3) this.ripples.push({ t: 0, power: 0.5 + next * 0.5 });
    }
    this.level = next;
  }

  spellWord(hold = 1.6) {
    this.spellUntil = performance.now() + hold * 1000 + 700;
  }

  frame(now) {
    const dt = Math.min(0.05, (now - this.last) / 1000);
    this.last = now;
    if (!this.reduced) {
      const target = MOODS[this.state];
      for (const key of Object.keys(target)) this.mood[key] += (target[key] - this.mood[key]) * Math.min(1, dt * 4);
      this.smooth += (this.level - this.smooth) * Math.min(1, dt * (this.level > this.smooth ? 18 : 6));
      this.beat += (0 - this.beat) * Math.min(1, dt * 3.5);
      this.rot += dt * (this.mood.spin + this.smooth * 0.6);
      // push a new sample into the oscilloscope ring buffer
      this.wave.push(this.smooth * (0.6 + Math.random() * 0.4));
      this.wave.shift();
      // advance voice ripples and drop the finished ones
      for (const rp of this.ripples) rp.t += dt;
      this.ripples = this.ripples.filter((rp) => rp.t < 1.2);
      const wantSpell = now < this.spellUntil ? 1 : 0;
      this.spell += (wantSpell - this.spell) * Math.min(1, dt * 3.2);
      this.draw(now / 1000);
    }
    requestAnimationFrame(this.frame);
  }

  // rotate a unit-sphere point by the current yaw/tilt and return screen x,y plus depth z (-1..1)
  project(px, py, pz, R, c, extraYaw = 0) {
    const yaw = this.rot + extraYaw;
    const cy = Math.cos(yaw), sy = Math.sin(yaw);
    let x = px * cy - pz * sy;
    let z = px * sy + pz * cy;
    const tilt = this.mood.tilt;
    const ct = Math.cos(tilt), st = Math.sin(tilt);
    let y = py * ct - z * st;
    z = py * st + z * ct;
    const fov = 3.2;
    const proj = fov / (fov - z); // perspective
    return { x: c + x * R * proj, y: c + y * R * proj, z, proj };
  }

  draw(t) {
    const { ctx, size, dpr, mood } = this;
    const c = (size * dpr) / 2;
    const energy = this.smooth;
    const pulse = 1 + this.beat * 0.07 + Math.sin(t * 2.2) * 0.012;
    const R = c * 0.6 * mood.scale * pulse; // sphere radius
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, c * 2, c * 2);
    const main = this.colors.main;
    const acc = this.colors.accent;
    const warm = Math.min(1, (mood.spin - 0.2) / 0.8); // thinking leans amber
    const col = mix(main, acc, warm * 0.8);

    this.drawHalo(ctx, c, R, col, mood, energy);

    ctx.globalCompositeOperation = "lighter";
    this.drawHud(ctx, c, R, t, col, mood, energy);
    this.drawOscilloscope(ctx, c, R, col, mood, energy, pulse);
    if (this.state === "thinking" || mood.sweep > 0.3) this.drawSweep(ctx, c, R, t, acc, mood);
    this.drawSphere(ctx, c, R, t, col, mood, energy);
    this.drawOrbits(ctx, c, R, t, col, acc, mood, energy);
    this.drawCore(ctx, c, R, t, col, mood, energy, pulse);
    this.drawVoiceRipples(ctx, c, R, col);
    ctx.globalCompositeOperation = "source-over";
  }

  // Rings that burst out of the core on every voice surge — the clearest "it's alive" signal.
  drawVoiceRipples(ctx, c, R, [r, g, b]) {
    for (const rp of this.ripples) {
      const f = rp.t / 1.2; // 0..1
      const rad = R * (0.3 + f * 1.35);
      const a = (1 - f) * 0.5 * rp.power;
      ctx.strokeStyle = `rgba(${r},${g},${b},${a})`;
      ctx.lineWidth = this.dpr * (2.5 * (1 - f) + 0.5);
      ctx.beginPath();
      ctx.arc(c, c, rad, 0, TAU);
      ctx.stroke();
    }
  }

  drawHalo(ctx, c, R, [r, g, b], mood, energy) {
    const glow = R * (1.9 + energy * 0.4);
    const grad = ctx.createRadialGradient(c, c, R * 0.3, c, c, glow);
    const a = (0.12 + energy * 0.3 + (mood.glow || 0) * 0.14) * mood.alpha;
    grad.addColorStop(0, `rgba(${r},${g},${b},${a})`);
    grad.addColorStop(0.55, `rgba(${r},${g},${b},${a * 0.3})`);
    grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(c, c, glow, 0, TAU);
    ctx.fill();
  }

  // The rotating mind-sphere: depth-sorted light points, drawn back-to-front so the globe reads
  // as solid. Near points are bigger, brighter and tinted toward white; far points sink to a
  // cool dim cyan. While spelling, every point streams toward its home in the SPECTRE wordmark.
  drawSphere(ctx, c, R, t, [r, g, b], mood, energy) {
    const spell = this.spell;
    const ease = spell * spell * (3 - 2 * spell);
    const amp = mood.wobble + energy * mood.gain;
    const warmBias = Math.min(1, Math.max(0, (mood.spin - 0.2) / 0.8)); // thinking warms the swarm
    const drawn = this._drawn || (this._drawn = []);
    drawn.length = 0;
    for (const p of this.points) {
      const breathe = 1 + amp * Math.sin(p.phase + t * 1.6) * 3 + energy * 0.05 * Math.sin(p.phase * 40 + t * 20);
      const pr = this.project(p.x, p.y, p.z, R * breathe, c);
      const wx = c + p.tx * c * 2;
      const wy = c + p.ty * c * 2;
      drawn.push({
        x: pr.x + (wx - pr.x) * ease,
        y: pr.y + (wy - pr.y) * ease,
        depth: (pr.z + 1) / 2, // 0 back .. 1 front
        p,
      });
    }
    drawn.sort((a, b2) => a.depth - b2.depth); // painter's order: far first
    for (const d of drawn) {
      const depth = d.depth;
      const p = d.p;
      const twinkle = 0.62 + 0.38 * Math.sin(t * 2 + p.phase * 3);
      const front = ease + (1 - ease) * (0.34 + 0.66 * depth); // livelier, back points stay visible
      const alpha = Math.min(1, mood.alpha * front * twinkle * (0.85 + energy * 0.5));
      // each point keeps its own vivid hue: colourful even at the back, only a touch of white in front
      const [pr0, pg0, pb0] = p.col;
      let cr, cg, cb;
      if (depth < 0.5) { const k = 0.6 + depth * 0.8; cr = pr0 * k; cg = pg0 * k; cb = pb0 * k; }
      else { const k = (depth - 0.5) * 2 * (0.25 + energy * 0.35); cr = pr0 + (255 - pr0) * k; cg = pg0 + (255 - pg0) * k; cb = pb0 + (255 - pb0) * k; }
      // while thinking, nudge the whole swarm a touch toward the warm accent
      if (warmBias > 0.01) { cr += (r - cr) * warmBias * 0.4; cg += (g - cg) * warmBias * 0.4; cb += (b - cb) * warmBias * 0.4; }
      ctx.fillStyle = `rgba(${cr | 0},${cg | 0},${cb | 0},${alpha})`;
      const s = p.size * this.dpr * (0.55 + 0.95 * (ease + (1 - ease) * depth)) * (1 + energy * 0.5);
      ctx.fillRect(d.x - s / 2, d.y - s / 2, s, s);
    }
    // energy filaments: a few bright arcs leaping from the core to the sphere's surface
    if (ease < 0.4 && energy > 0.22) this.drawFilaments(ctx, c, R, t, [r, g, b], mood, energy);
  }

  drawFilaments(ctx, c, R, t, [r, g, b], mood, energy) {
    const n = 2;
    ctx.lineCap = "round";
    for (let i = 0; i < n; i++) {
      const seed = Math.floor(t * 6) + i * 97; // re-roll a few times a second
      const sr = (s) => ((Math.sin(s * 127.1) * 43758.5453) % 1 + 1) % 1;
      const a = sr(seed) * TAU;
      const pr = this.project(Math.cos(a), sr(seed + 1) * 2 - 1, Math.sin(a), R, c);
      const steps = 6;
      ctx.strokeStyle = `rgba(${r},${g},${b},${(0.12 + energy * 0.35) * mood.alpha})`;
      ctx.lineWidth = this.dpr;
      ctx.beginPath();
      ctx.moveTo(c, c);
      for (let k = 1; k <= steps; k++) {
        const f = k / steps;
        const jx = (sr(seed + k * 3) - 0.5) * R * 0.18 * (1 - f);
        const jy = (sr(seed + k * 3 + 1) - 0.5) * R * 0.18 * (1 - f);
        ctx.lineTo(c + (pr.x - c) * f + jx, c + (pr.y - c) * f + jy);
      }
      ctx.stroke();
    }
  }

  // Tilted electron orbits, each with a bright bead. Segments that pass behind the sphere fade
  // out, so the rings read as wrapping a solid globe. Beads bloom when they come round the front.
  drawOrbits(ctx, c, R, t, [r, g, b], [ar, ag, ab], mood, energy) {
    const { dpr } = this;
    const steps = 140;
    for (const o of this.orbits) {
      ctx.lineWidth = dpr;
      let prev = null;
      for (let i = 0; i <= steps; i++) {
        const a = (i / steps) * TAU;
        const cx = Math.cos(a) * o.rad;
        const cz = Math.sin(a) * o.rad;
        const ct = Math.cos(o.tilt), st = Math.sin(o.tilt);
        const pr = this.project(cx, cz * st, cz * ct, R, c, o.yaw);
        if (prev) {
          const depth = (pr.z + 1) / 2; // behind sphere (0) .. in front (1)
          const occl = pr.z < -0.15 ? 0.28 : 1; // dim the back half (occluded by the globe)
          ctx.strokeStyle = `rgba(${r},${g},${b},${(0.12 + 0.3 * depth) * occl * mood.alpha})`;
          ctx.beginPath();
          ctx.moveTo(prev.x, prev.y);
          ctx.lineTo(pr.x, pr.y);
          ctx.stroke();
        }
        prev = pr;
      }
      // the electron bead
      const ba = o.bead + t * o.speed;
      const cx = Math.cos(ba) * o.rad, cz = Math.sin(ba) * o.rad;
      const ct = Math.cos(o.tilt), st = Math.sin(o.tilt);
      const pr = this.project(cx, cz * st, cz * ct, R, c, o.yaw);
      const depth = (pr.z + 1) / 2;
      const sz = dpr * (1.6 + energy * 2) * pr.proj * (0.6 + 0.6 * depth);
      ctx.save();
      ctx.shadowColor = `rgba(${ar},${ag},${ab},0.9)`;
      ctx.shadowBlur = dpr * (4 + energy * 8) * depth;
      ctx.fillStyle = `rgba(${ar},${ag},${ab},${(0.5 + 0.5 * depth) * mood.alpha})`;
      ctx.beginPath();
      ctx.arc(pr.x, pr.y, sz, 0, TAU);
      ctx.fill();
      ctx.restore();
    }
  }

  // Plasma core: layered gradient, flickering, with a crisp containment rim.
  drawCore(ctx, c, R, t, [r, g, b], mood, energy, pulse) {
    const core = R * 0.3 * pulse;
    const flick = 0.8 + 0.2 * Math.sin(t * 7 + Math.sin(t * 3));
    const grad = ctx.createRadialGradient(c, c, 0, c, c, core);
    grad.addColorStop(0, `rgba(255,255,255,${(0.5 + energy * 0.4) * mood.alpha * flick})`);
    grad.addColorStop(0.4, `rgba(${r},${g},${b},${(0.4 + energy * 0.4) * mood.alpha})`);
    grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
    ctx.save();
    ctx.shadowColor = `rgba(${r},${g},${b},0.9)`;
    ctx.shadowBlur = this.dpr * (10 + energy * 20);
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(c, c, core, 0, TAU);
    ctx.fill();
    ctx.restore();
    // containment rim
    ctx.strokeStyle = `rgba(${r},${g},${b},${(0.4 + energy * 0.3) * mood.alpha})`;
    ctx.lineWidth = this.dpr * 1.2;
    ctx.beginPath();
    ctx.arc(c, c, core, 0, TAU);
    ctx.stroke();
  }

  // Circular oscilloscope: the voice waveform wrapped around the sphere, closing into a ring.
  drawOscilloscope(ctx, c, R, [r, g, b], mood, energy, pulse) {
    const base = R * 1.28 * pulse;
    const span = R * 0.32;
    ctx.lineWidth = this.dpr * 1.6;
    ctx.lineJoin = "round";
    ctx.beginPath();
    for (let i = 0; i <= WAVE; i++) {
      const w = this.wave[i % WAVE];
      const a = (i / WAVE) * TAU + this.rot * 0.3;
      const rad = base + (w - 0.3) * span * (0.3 + mood.spectrum);
      const x = c + Math.cos(a) * rad;
      const y = c + Math.sin(a) * rad;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.save();
    // a multi-hue gradient sweep so the waveform shimmers through the palette
    const a = (0.3 + energy * 0.55) * mood.alpha;
    const grad = ctx.createLinearGradient(c - base, c - base, c + base, c + base);
    const stops = [PALETTE[0], PALETTE[1], PALETTE[3], PALETTE[4], PALETTE[0]];
    stops.forEach((s, i) => grad.addColorStop(i / (stops.length - 1), `rgba(${s[0]},${s[1]},${s[2]},${a})`));
    ctx.shadowColor = `rgba(${r},${g},${b},0.7)`;
    ctx.shadowBlur = this.dpr * (3 + energy * 6);
    ctx.strokeStyle = grad;
    ctx.stroke();
    ctx.restore();
  }

  // HUD: one quiet bezel ring, a single slow progress arc, and four corner brackets.
  // Deliberately spare — the light (halo, core, orbits) carries the orb, not the chrome.
  drawHud(ctx, c, R, t, [r, g, b], mood, energy) {
    const { dpr } = this;
    const bezel = R * 1.55;
    // a single thin bezel ring (no graduations)
    ctx.strokeStyle = `rgba(${r},${g},${b},${0.22 * mood.alpha})`;
    ctx.lineWidth = dpr;
    ctx.beginPath();
    ctx.arc(c, c, bezel, 0, TAU);
    ctx.stroke();

    // one slow progress arc riding just outside the ring
    ctx.save();
    ctx.translate(c, c);
    ctx.rotate(t * (0.4 + mood.spin * 0.5));
    ctx.strokeStyle = `rgba(${r},${g},${b},${(0.4 + energy * 0.4) * mood.alpha})`;
    ctx.lineWidth = dpr * 2;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.arc(0, 0, bezel * 1.1, 0, TAU * 0.28);
    ctx.stroke();
    ctx.restore();

    // corner brackets, framing the orb like a targeting reticle (subtle)
    const m = R * 1.75;
    const len = R * 0.2;
    ctx.strokeStyle = `rgba(${r},${g},${b},${0.32 * mood.alpha})`;
    ctx.lineWidth = dpr * 1.2;
    for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
      const x = c + sx * m, y = c + sy * m;
      ctx.beginPath();
      ctx.moveTo(x - sx * len, y);
      ctx.lineTo(x, y);
      ctx.lineTo(x, y - sy * len);
      ctx.stroke();
    }
  }

  // Thinking: a radar sweep with a fading trail.
  drawSweep(ctx, c, R, t, [r, g, b], mood) {
    const k = Math.min(1, (mood.spin - 0.2) / 0.8);
    const head = t * 2.6;
    for (let i = 0; i < 12; i++) {
      const a0 = head - (1.0 * i) / 12;
      ctx.strokeStyle = `rgba(${r},${g},${b},${(0.5 * k) * (1 - i / 12)})`;
      ctx.lineWidth = this.dpr * 2;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.arc(c, c, R * 1.3, a0, a0 + 0.08);
      ctx.stroke();
    }
  }
}
