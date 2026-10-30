// The team's voices on the call: clear, natural, one per agent.
// « navigateur »: the browser's own French voices (Edge's « Natural » voices, Google's on
// Android), the most fluid where they exist; « spectre »: Spectre's local voices (Piper, no
// network), rendered by the PC. « auto » takes the browser's when it has a natural French voice.
// While a voice speaks, `onLevel` gets its loudness (0..1) for the lips.

import { api } from "./kit.js";

const KEY = "spectre-call-voice";
const FEMALE = /denise|vivienne|eloise|éloïse|brigitte|hortense|julie|amélie|amelie|sylvie|charline|ariane|audrey|marie|léa|lea\b|céline|celine|chantal|coralie|jacqueline|josephine|yvette|female|femme|virginie|caroline|manon|clara/i;
const MALE = /henri|remy|rémy|paul|claude|antoine|jean|gerard|gérard|fabrice|alain|maurice|jérôme|jerome|thierry|guillaume|thomas|mathieu|nicolas|male|homme|louis|lucien|pierre/i;

let ctx = null;
let current = null;

export function mode() { try { return localStorage.getItem(KEY) || "auto"; } catch { return "auto"; } }
export function setMode(value) { try { localStorage.setItem(KEY, value); } catch { /* private window */ } }

function frenchVoices() {
  if (!("speechSynthesis" in window)) return [];
  const all = speechSynthesis.getVoices().filter((v) => /^fr/i.test(v.lang));
  const rank = (v) => (/natural|neural|online/i.test(v.name) ? 0 : /google/i.test(v.name) ? 1 : 2) + (/fr-FR/i.test(v.lang) ? 0 : 0.5);
  return all.sort((a, b) => rank(a) - rank(b));
}
export function hasNaturalVoice() { return frenchVoices().some((v) => /natural|neural|online|google/i.test(v.name)); }
if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => {};

// Each agent keeps the same browser voice: women on women's voices, men on men's, spread out.
const assigned = new Map();
function browserVoice(key, gender) {
  const voices = frenchVoices();
  if (!voices.length) return null;
  if (assigned.has(key)) return voices.find((v) => v.name === assigned.get(key)) || voices[0];
  const want = gender === "f" ? FEMALE : MALE;
  let pool = voices.filter((v) => want.test(v.name));
  if (!pool.length) pool = voices.filter((v) => !(gender === "f" ? MALE : FEMALE).test(v.name));
  if (!pool.length) pool = voices;
  const used = [...assigned.values()];
  const pick = pool.find((v) => !used.includes(v.name)) || pool[used.length % pool.length];
  assigned.set(key, pick.name);
  return pick;
}

export function useBrowser() {
  const m = mode();
  return m === "navigateur" || (m === "auto" && hasNaturalVoice());
}

export function stop() {
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  if (current) { try { current.stop(); } catch { /* ended */ } current = null; }
}

export async function unlock() {
  ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state !== "running") await ctx.resume();
}

// Say `text` as agent `key`; resolves when the voice has finished.
export async function speak(key, gender, text, onLevel = () => {}) {
  if (!text) return;
  // The browser's own voice is the most fluid when it works, but online « natural » voices often
  // fail without a sound (and without an error): when it never starts, fall back to Spectre's.
  if (useBrowser() && frenchVoices().length && (await speakBrowser(key, gender, text, onLevel))) return;
  try {
    const { audio } = await api("POST", "call/say", { agent: key, text });
    if (audio) return await playWav(audio, onLevel);
  } catch { /* the PC cannot render: the browser speaks */ }
  if (frenchVoices().length) await speakBrowser(key, gender, text, onLevel);
}

// Resolves true if the voice actually spoke, false if it never started (silent failure).
function speakBrowser(key, gender, text, onLevel) {
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(text);
    const v = browserVoice(key, gender);
    if (v) { u.voice = v; u.lang = v.lang; } else u.lang = "fr-FR";
    u.rate = 1.0;
    u.pitch = 1.0;
    let flutter = 0, started = false;
    const tick = () => onLevel(0.25 + Math.random() * 0.6);
    u.onstart = () => { started = true; clearTimeout(watchdog); flutter = setInterval(tick, 90); };
    u.onboundary = () => onLevel(0.9);
    const end = () => { clearTimeout(watchdog); clearInterval(flutter); onLevel(0); resolve(started); };
    u.onend = end;
    u.onerror = end;
    // If nothing has begun within a second, the browser voice is mute: give up so Spectre speaks.
    const watchdog = setTimeout(() => { if (!started) { speechSynthesis.cancel(); resolve(false); } }, 1000);
    speechSynthesis.speak(u);
  });
}

async function playWav(b64, onLevel) {
  await unlock();
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const buffer = await ctx.decodeAudioData(bytes.buffer);
  const src = ctx.createBufferSource();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  src.buffer = buffer;
  src.connect(analyser);
  analyser.connect(ctx.destination);
  const data = new Uint8Array(analyser.fftSize);
  let raf = 0;
  const loop = () => {
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (const v of data) sum += ((v - 128) / 128) ** 2;
    onLevel(Math.min(1, Math.sqrt(sum / data.length) * 5));
    raf = requestAnimationFrame(loop);
  };
  current = src;
  await new Promise((resolve) => {
    src.onended = () => { cancelAnimationFrame(raf); onLevel(0); current = null; resolve(); };
    src.start();
    loop();
  });
}
