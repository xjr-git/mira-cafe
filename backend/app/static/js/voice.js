// Voice input: Web Speech API + press-and-talk (PTT).
// PTT is the primary interruption gesture: pressing it while Mira speaks
// means "stop and listen to me" - see README for why not auto-VAD.
//
// Recognition guard-rails (all client-side, no server round-trip):
// - MAX_HOLD_MS    single press cannot listen longer than 20s (auto stop)
// - MIN_HOLD_MS    shorter than 0.4s = accidental tap -> cancel & drop text
// - FINAL_WAIT_MS  released with no final result? wait 1.2s, then submit the
//                  best interim transcript (>=2 chars) or fall back to idle
const pttBtn = document.getElementById('ptt');

const MAX_HOLD_MS = 20000;
const MIN_HOLD_MS = 400;
const FINAL_WAIT_MS = 1200;

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null;
let onFinalText = null;    // injected by main.js
let onInterrupt = null;    // injected by main.js
let onListenEnd = null;    // injected by main.js
let holding = false;
let holdStart = 0;
let maxTimer = null;       // 20s hard cap
let finalTimer = null;     // grace period for a final result after release
let lastInterim = '';
let gotFinal = false;
let suppress = false;      // accidental tap: drop every pending result

if (SR) {
  rec = new SR();
  rec.lang = 'zh-CN';
  rec.interimResults = true;
  rec.maxAlternatives = 1;

  rec.onresult = (e) => {
    const r = e.results[e.results.length - 1];
    const text = (r[0] && r[0].transcript.trim()) || '';
    if (r.isFinal) {
      gotFinal = true;
      if (finalTimer) { clearTimeout(finalTimer); finalTimer = null; }
      if (!suppress && text && onFinalText) onFinalText(text);
    } else {
      lastInterim = text;
    }
  };
  rec.onerror = (e) => {
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
      import('./scene.js').then(m => m.toast('麦克风权限被拒绝，可用文字交流'));
      pttBtn.disabled = true;
      pttBtn.title = '麦克风不可用';
    } else if (e.error === 'no-speech' && holding === false && onListenEnd) {
      onListenEnd(false);              // released, nothing said -> back to idle
    }
  };
  rec.onend = () => {
    // engine stopped by itself (no-speech / auto stop after final) while the
    // user already released: make sure we never hang in a dead listening state
    if (!holding && finalTimer === null && onListenEnd) onListenEnd(false);
  };
} else {
  pttBtn.disabled = true;
  pttBtn.title = '当前浏览器不支持语音识别，请用 Chrome / Edge';
  import('./scene.js').then(m => m.toast('此浏览器不支持语音识别，可用文字交流'));
}

async function startHold() {
  if (rec && !holding) {
    holding = true;
    holdStart = Date.now();
    gotFinal = false;
    suppress = false;
    lastInterim = '';
    pttBtn.classList.add('recording');
    if (onInterrupt) onInterrupt('ptt');   // PTT = interrupt + listen
    try { rec.start(); } catch { /* already started */ }
    maxTimer = setTimeout(() => {          // hard cap: auto stop
      if (holding) {
        endHold();
        import('./scene.js').then(m => m.toast('单次说话最长 20 秒，已自动停止'));
      }
    }, MAX_HOLD_MS);
  }
}

function endHold() {
  if (rec && holding) {
    holding = false;
    if (maxTimer) { clearTimeout(maxTimer); maxTimer = null; }
    pttBtn.classList.remove('recording');
    try { rec.stop(); } catch { /* ignore */ }

    const heldMs = Date.now() - holdStart;
    if (heldMs < MIN_HOLD_MS) {
      suppress = true;                     // accidental tap: cancel everything
      if (onListenEnd) onListenEnd(false);
      return;
    }
    if (gotFinal) {
      if (onListenEnd) onListenEnd(true);  // final already handled a result
      return;
    }
    // no final yet: give the engine a short grace period, then either
    // submit the best interim text or fall back to idle
    finalTimer = setTimeout(() => {
      finalTimer = null;
      if (!suppress && lastInterim && lastInterim.length >= 2) {
        if (onFinalText) onFinalText(lastInterim);
        if (onListenEnd) onListenEnd(true);
      } else if (onListenEnd) {
        onListenEnd(false);
      }
    }, FINAL_WAIT_MS);
  }
}

pttBtn.addEventListener('pointerdown', (e) => { e.preventDefault(); startHold(); });
pttBtn.addEventListener('pointerup', endHold);
pttBtn.addEventListener('pointerleave', endHold);
pttBtn.addEventListener('pointercancel', endHold);

export function bindVoice(finalHandler, interruptHandler, listenEndHandler) {
  onFinalText = finalHandler;
  onInterrupt = interruptHandler;
  onListenEnd = listenEndHandler;
}
