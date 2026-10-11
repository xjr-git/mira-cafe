// Layered SVG character: emotion / action / talking / blink / listening
const chara = document.getElementById('chara');
const wrap = document.getElementById('chara-wrap');

let blinkTimer = 0;
function scheduleBlink() {
  clearTimeout(blinkTimer);
  blinkTimer = setTimeout(() => {
    if (chara.dataset.emo === 'neutral') {
      chara.classList.add('blink');
      setTimeout(() => chara.classList.remove('blink'), 130);
    }
    scheduleBlink();
  }, 2600 + Math.random() * 2600);
}
scheduleBlink();

let actionTimer = 0;
const ACTION_MS = { stir_coffee: 3200, look_camera: 3600, gaze_window: 2600 };

export function setEmotion(name) {
  if (['neutral', 'happy', 'shy', 'sad', 'surprised'].includes(name)) {
    chara.dataset.emo = name;
  }
}

export function setAction(name) {
  clearTimeout(actionTimer);
  delete chara.dataset.action;
  // force reflow so repeat actions re-animate
  void chara.getBoundingClientRect();
  if (ACTION_MS[name]) {
    chara.dataset.action = name;
    actionTimer = setTimeout(() => delete chara.dataset.action, ACTION_MS[name]);
  }
}

export function setTalk(on) {
  chara.classList.toggle('talking', !!on);
  wrap.classList.toggle('talking', !!on);   // drives the voice-ring ripple
}

export function setUIState(state) {
  wrap.classList.remove('listening', 'thinking');
  if (state === 'listening') wrap.classList.add('listening');
  if (state === 'thinking') { wrap.classList.add('thinking'); setAction('stir_coffee'); }
  const badge = document.getElementById('state-badge');
  badge.dataset.state = state;
  const text = { idle: '待机中', listening: '正在倾听…', thinking: '思考中…', speaking: '说话中…' };
  document.getElementById('state-text').textContent = text[state] || state;
  if (state === 'idle') setTalk(false);
}

// ---- audio-driven lip sync: mouth follows the real waveform ----
let voiceCtx = null, srcNode = null, analyser = null, rafId = 0;
const mouthTalk = document.getElementById('mouth-talk');
const headEl = document.getElementById('head');

export function startLipSync(audio) {
  try {
    if (!mouthTalk || !headEl) return;
    if (!voiceCtx) voiceCtx = new (window.AudioContext || window.webkitAudioContext)();
    const ready = voiceCtx.state === 'suspended' ? voiceCtx.resume() : Promise.resolve();
    Promise.resolve(ready).then(() => {
      // if the context could not start (no gesture yet), fall back to CSS flap
      if (voiceCtx.state !== 'running') return;
      if (srcNode) { try { srcNode.disconnect(); } catch {} srcNode = null; }
      srcNode = voiceCtx.createMediaElementSource(audio);
      analyser = voiceCtx.createAnalyser();
      analyser.fftSize = 256;
      srcNode.connect(analyser);
      analyser.connect(voiceCtx.destination);
      chara.classList.add('lipsync');
      headEl.style.transition = 'transform .13s ease';
      const buf = new Uint8Array(analyser.frequencyBinCount);
      let smooth = 0, lastBob = 0;
      const tick = (t) => {
        if (!analyser) return;
        analyser.getByteFrequencyData(buf);
        let sum = 0;
        for (let i = 2; i < 40; i++) sum += buf[i];
        const v = Math.min(1, (sum / (38 * 255)) * 2.2);
        smooth = smooth * 0.55 + v * 0.45;
        mouthTalk.style.transform = `scaleY(${(0.18 + smooth * 0.95).toFixed(3)})`;
        if (t - lastBob > 160) {
          lastBob = t;
          headEl.style.transform = `rotate(${(smooth * 2.2 - 0.5).toFixed(2)}deg)`;
        }
        rafId = requestAnimationFrame(tick);
      };
      rafId = requestAnimationFrame(tick);
    }).catch(() => {});
  } catch { /* older browsers keep the CSS flap animation */ }
}

export function stopLipSync() {
  cancelAnimationFrame(rafId);
  chara.classList.remove('lipsync');
  if (mouthTalk) mouthTalk.style.transform = '';
  if (headEl) { headEl.style.transform = ''; headEl.style.transition = ''; }
  if (srcNode) { try { srcNode.disconnect(); } catch {} srcNode = null; }
  analyser = null;
}

// ---- idle life: random micro glance / tilt / nod so she never freezes ----
function idleLife() {
  setTimeout(() => {
    const busy = wrap.classList.contains('listening') ||
                 wrap.classList.contains('thinking') ||
                 chara.classList.contains('talking');
    if (!busy) {
      const pick = ['glance-l', 'glance-r', 'tilt-l', 'tilt-r', 'nod'][Math.floor(Math.random() * 5)];
      chara.classList.add(pick);
      setTimeout(() => chara.classList.remove(pick),
        pick === 'nod' ? 950 : 800 + Math.random() * 1500);
    }
    idleLife();
  }, 2600 + Math.random() * 4200);
}
idleLife();
