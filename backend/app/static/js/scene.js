// Rain overlay canvas + background crossfade + polaroid flow
const canvas = document.getElementById('rain-canvas');
const ctx = canvas.getContext('2d');
let drops = [];
let raining = true;
let raf = 0;

function resize() {
  canvas.width = innerWidth;
  canvas.height = innerHeight;
  const n = Math.floor(innerWidth / 6);
  drops = Array.from({ length: n }, () => newDrop());
}
function newDrop() {
  return { x: Math.random() * canvas.width, y: Math.random() * canvas.height,
    len: 12 + Math.random() * 22, v: 520 + Math.random() * 480, drift: 40 + Math.random() * 40 };
}
function tick(t) {
  const dt = Math.min(0.05, (t - (tick.last || t)) / 1000);
  tick.last = t;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (raining) {
    ctx.strokeStyle = 'rgba(190,210,255,0.35)';
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    for (const d of drops) {
      d.y += d.v * dt; d.x += d.drift * dt;
      if (d.y > canvas.height) { Object.assign(d, newDrop()); d.y = -30; }
      ctx.moveTo(d.x, d.y);
      ctx.lineTo(d.x + d.drift * 0.03, d.y + d.len);
    }
    ctx.stroke();
  }
  raf = requestAnimationFrame(tick);
}
addEventListener('resize', resize);
resize();
requestAnimationFrame(tick);

export function rainStop() {
  raining = false;
  canvas.style.opacity = '0';
  document.getElementById('bg-rain').classList.remove('active');
  document.getElementById('bg-clear').classList.add('active');
  fadeRainAudio(0);                          // ambience follows the visuals
}

// ---- rain ambience (WebAudio-synthesized, zero assets) ----
// Brown-ish noise through a lowpass filter reads as distant rain.
// Starts on the first user gesture (mobile autoplay policy), fades in.
let rainGain = null;
let rainCtx = null;

export function startAmbience() {
  if (rainGain) return;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    rainCtx = new AC();
    const seconds = 2 * rainCtx.sampleRate;
    const buf = rainCtx.createBuffer(1, seconds, rainCtx.sampleRate);
    const data = buf.getChannelData(0);
    let last = 0;
    for (let i = 0; i < data.length; i++) {
      const white = Math.random() * 2 - 1;
      last = (last + 0.02 * white) / 1.02;
      data[i] = last * 3.5;
    }
    const src = rainCtx.createBufferSource();
    src.buffer = buf;
    src.loop = true;
    const lp = rainCtx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = 850;
    rainGain = rainCtx.createGain();
    rainGain.gain.value = 0;
    src.connect(lp).connect(rainGain).connect(rainCtx.destination);
    src.start();
    rainGain.gain.linearRampToValueAtTime(0.055, rainCtx.currentTime + 2.8);
  } catch { /* audio unavailable: scene still works silently */ }
}

function fadeRainAudio(target) {
  if (!rainGain || !rainCtx) return;
  try {
    rainGain.gain.cancelScheduledValues(rainCtx.currentTime);
    rainGain.gain.setValueAtTime(rainGain.gain.value, rainCtx.currentTime);
    rainGain.gain.linearRampToValueAtTime(target, rainCtx.currentTime + 3);
  } catch { /* ignore */ }
}

// ---- polaroid flow ----
const po = document.getElementById('polaroid');
const phImg = document.getElementById('ph-img');
const phCap = document.getElementById('ph-caption');
let pollTimer = 0;

export function showPolaroid(jobId) {
  clearTimeout(pollTimer);
  po.classList.add('show');
  phImg.classList.remove('developed');
  phImg.src = '';
  phCap.textContent = '（她正在挑照片……）';
  poll(jobId, 0);
}
function poll(jobId, n) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    try {
      const r = await fetch(`/api/image/${jobId}`);
      const j = await r.json();
      if (j.status === 'done' && j.url) {
        phImg.src = j.url;
        phImg.onload = () => {
          requestAnimationFrame(() => phImg.classList.add('developed'));
          phCap.textContent = j.degraded ? '（她翻出了一张旧照片）' : 'Mira · 某个雨夜';
        };
        return;
      }
      if (j.status === 'failed' || n > 50) {
        toast('照片没找到……她有点不好意思');
        po.classList.remove('show');
        return;
      }
    } catch { /* network hiccup, keep polling */ }
    poll(jobId, n + 1);
  }, 800);
}

export function toast(msg, ms = 3200) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.add('hidden'), ms);
}
