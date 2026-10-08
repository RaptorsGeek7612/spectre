// Spectre's voice orb: a ring of particles around a hexagonal core that breathes, listens,
// thinks and speaks. The ring deforms with the live loudness sent by the voice engine; on boot
// and on every wake the particles leave the ring to spell SPECTRE, then fall back into place.

const TAU = Math.PI * 2;
const COUNT = 1500;
const WORD = "SPECTRE";

const MOODS = {
  //          slow wobble, level gain, ring scale, alpha, spin speed
  off:       { wobble: 0.002, gain: 0,     scale: 0.96, alpha: 0.4,  spin: 0.02 },
  sleeping:  { wobble: 0.004, gain: 0,     scale: 0.97, alpha: 0.75, spin: 0.05 },
  listening: { wobble: 0.006, gain: 0.022, scale: 1.02, alpha: 0.9,  spin: 0.12 },
  thinking:  { wobble: 0.01,  gain: 0,     scale: 1.0,  alpha: 0.85, spin: 0.6 },
  speaking:  { wobble: 0.006, gain: 0.028, scale: 1.0,  alpha: 0.95, spin: 0.16 },
};

function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function rgb(hex) {
  const m = hex.replace("#", "").match(/.{2}/g) || ["4f", "c3", "f7"];
  return m.map((x) => parseInt(x, 16));
}

export class Orb {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.state = "sleeping";
    this.level = 0; // target loudness 0..1 from the server
    this.smooth = 0; // eased loudness actually drawn
    this.mood = { ...MOODS.sleeping };
    this.spell = 0; // 0 = ring, 1 = word fully formed
    this.spellUntil = 0;
    this.reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.colors = { main: rgb(cssVar("--l486", "#4fc3f7")), think: rgb(cssVar("--l589", "#ffd23f")) };
    let seed = 486;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    this.points = Array.from({ length: COUNT }, (_, i) => ({
      a: (i / COUNT) * TAU + rnd() * 0.01,
      band: Math.pow(rnd(), 1.8), // most particles hug the outer edge, like a rim of light
      phase: rnd() * TAU,
      size: 0.9 + rnd() * 1.3,
      tx: 0, ty: 0, // target in the word (set by layoutWord)
    }));
    this.harmonics = [2, 3, 5, 7, 11].map((k) => ({ k, phase: rnd() * TAU, speed: 0.3 + rnd() * 0.9 }));
    this.resize();
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    document.fonts?.ready.then(() => this.layoutWord());
    this.frame = this.frame.bind(this);
    this.last = performance.now();
    requestAnimationFrame(this.frame);
  }

  resize() {
    const box = this.canvas.parentElement.getBoundingClientRect();
    const size = Math.max(160, Math.min(box.width, box.height));
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    this.canvas.style.width = this.canvas.style.height = `${size}px`;
    this.canvas.width = this.canvas.height = Math.round(size * dpr);
    this.size = size;
    this.dpr = dpr;
    this.layoutWord();
    if (this.reduced) this.draw(performance.now() / 1000);
  }

  layoutWord() {
    // Sample the wordmark's pixels and give every particle a home inside the letters.
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
    const span = 0.62; // word width as a share of the orb
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
    this.level = Math.max(0, Math.min(1, Number(v) || 0));
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
      const wantSpell = now < this.spellUntil ? 1 : 0;
      this.spell += (wantSpell - this.spell) * Math.min(1, dt * 3.2);
      this.draw(now / 1000);
    }
    requestAnimationFrame(this.frame);
  }

  draw(t) {
    const { ctx, size, dpr, mood } = this;
    const c = (size * dpr) / 2;
    const R = c * 0.78 * mood.scale;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, c * 2, c * 2);
    ctx.globalCompositeOperation = "lighter";
    const [r, g, b] = this.colors.main;

    // core: faint hexagonal mesh inside a thin circle
    const core = R * 0.36;
    ctx.save();
    ctx.beginPath();
    ctx.arc(c, c, core, 0, TAU);
    ctx.clip();
    ctx.strokeStyle = `rgba(${r},${g},${b},${0.1 * mood.alpha})`;
    ctx.lineWidth = dpr * 0.8;
    const hex = core / 5;
    for (let row = -6; row <= 6; row++) {
      for (let col = -6; col <= 6; col++) {
        const x = c + col * hex * 1.5;
        const y = c + row * hex * Math.sqrt(3) + (col % 2 ? (hex * Math.sqrt(3)) / 2 : 0);
        ctx.beginPath();
        for (let k = 0; k < 6; k++) {
          const ang = (k / 6) * TAU;
          ctx.lineTo(x + Math.cos(ang) * hex * 0.92, y + Math.sin(ang) * hex * 0.92);
        }
        ctx.closePath();
        ctx.stroke();
      }
    }
    ctx.restore();
    ctx.strokeStyle = `rgba(${r},${g},${b},${0.35 * mood.alpha})`;
    ctx.lineWidth = dpr;
    ctx.beginPath();
    ctx.arc(c, c, core, 0, TAU);
    ctx.stroke();

    // inner dashed ring, slowly turning
    ctx.save();
    ctx.translate(c, c);
    ctx.rotate(t * mood.spin * 0.5);
    ctx.setLineDash([dpr * 2, dpr * 7]);
    ctx.strokeStyle = `rgba(${r},${g},${b},${0.3 * mood.alpha})`;
    ctx.beginPath();
    ctx.arc(0, 0, R * 0.62, 0, TAU);
    ctx.stroke();
    ctx.restore();

    // thinking: two amber arcs orbiting the core
    if (this.state === "thinking" || mood.spin > 0.3) {
      const [tr, tg, tb] = this.colors.think;
      const k = Math.min(1, (mood.spin - 0.1) / 0.5);
      ctx.lineWidth = dpr * 2;
      ctx.lineCap = "round";
      for (let i = 0; i < 2; i++) {
        const start = t * 2.4 + i * Math.PI;
        ctx.strokeStyle = `rgba(${tr},${tg},${tb},${0.75 * k})`;
        ctx.beginPath();
        ctx.arc(c, c, R * 0.5, start, start + 0.9);
        ctx.stroke();
      }
    }

    // the particle ring (or the word)
    const amp = mood.wobble + this.smooth * mood.gain;
    const spell = this.spell;
    const ease = spell * spell * (3 - 2 * spell);
    for (const p of this.points) {
      let wob = 0;
      for (const h of this.harmonics) wob += Math.sin(h.k * p.a + h.phase + t * h.speed * (1 + this.smooth * 3)) / h.k;
      const spray = Math.sin(p.phase * 53 + t * 23) * this.smooth * (mood.gain > 0 ? 0.045 : 0); // energetic fuzz
      const radius = R * (0.9 + 0.1 * p.band) * (1 + amp * wob * 2.2 + spray * (0.4 + p.band)) + Math.sin(t * 1.3 + p.phase) * R * 0.004;
      const angle = p.a + t * mood.spin * 0.08;
      const rx = c + Math.cos(angle) * radius;
      const ry = c + Math.sin(angle) * radius;
      const x = rx + (c + p.tx * c * 2 - rx) * ease;
      const y = ry + (c + p.ty * c * 2 - ry) * ease;
      const twinkle = 0.55 + 0.45 * Math.sin(t * 2 + p.phase * 3);
      const alpha = Math.min(1, (mood.alpha + ease * 0.5) * (0.35 + 0.65 * (1 - p.band)) * twinkle);
      ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
      const s = p.size * dpr * (1 + this.smooth * 0.6);
      ctx.fillRect(x - s / 2, y - s / 2, s, s);
    }
    ctx.globalCompositeOperation = "source-over";
  }
}
