// Voice input: Web Speech API + press-and-talk (PTT).
// PTT is the primary interruption gesture: pressing it while Mira speaks
// means "stop and listen to me" - see README for why not auto-VAD.
const pttBtn = document.getElementById('ptt');

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null;
let onFinalText = null;    // injected by main.js
let onInterrupt = null;    // injected by main.js
let holding = false;

if (SR) {
  rec = new SR();
  rec.lang = 'zh-CN';
  rec.interimResults = true;
  rec.maxAlternatives = 1;

  rec.onresult = (e) => {
    const r = e.results[e.results.length - 1];
    if (r.isFinal && r[0] && r[0].transcript.trim()) {
      const text = r[0].transcript.trim();
      if (onFinalText) onFinalText(text);
    }
  };
  rec.onerror = (e) => {
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
      import('./scene.js').then(m => m.toast('麦克风权限被拒绝，可用文字交流'));
      pttBtn.disabled = true;
      pttBtn.title = '麦克风不可用';
    }
  };
} else {
  pttBtn.disabled = true;
  pttBtn.title = '当前浏览器不支持语音识别，请用 Chrome / Edge';
  import('./scene.js').then(m => m.toast('此浏览器不支持语音识别，可用文字交流'));
}

async function startHold() {
  if (rec && !holding) {
    holding = true;
    pttBtn.classList.add('recording');
    if (onInterrupt) onInterrupt('ptt');   // PTT = interrupt + listen
    try { rec.start(); } catch { /* already started */ }
  }
}
function endHold() {
  if (rec && holding) {
    holding = false;
    pttBtn.classList.remove('recording');
    try { rec.stop(); } catch { /* ignore */ }
  }
}

pttBtn.addEventListener('pointerdown', (e) => { e.preventDefault(); startHold(); });
pttBtn.addEventListener('pointerup', endHold);
pttBtn.addEventListener('pointerleave', endHold);
pttBtn.addEventListener('pointercancel', endHold);

export function bindVoice(finalHandler, interruptHandler) {
  onFinalText = finalHandler;
  onInterrupt = interruptHandler;
}
