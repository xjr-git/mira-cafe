// main.js — client orchestrator: state machine, SSE protocol with round
// filtering (stale-response protection), audio queue, interruption.
import { setEmotion, setAction, setTalk, setUIState } from './character.js';
import { rainStop, showPolaroid, toast, startAmbience } from './scene.js';
import { bindVoice } from './voice.js';

const $ = (id) => document.getElementById(id);
const input = $('text-input'), sendBtn = $('send'), pttBtn = $('ptt'), stopBtn = $('interrupt');
const subtitleEl = $('subtitle'), hudMode = $('hud-mode'), hudLatency = $('hud-latency');

// ---- session state ----
let state = 'idle';            // idle | listening | thinking | speaking
let latestRound = -1;          // newest accepted round_id
let barredRound = -1;          // everything <= this is stale, drop it
let abortCtrl = null;          // AbortController for the in-flight chat
let playQueue = [];            // pending audio events [{seq,url,round}]
let curAudio = null;
let curSubSeq = -1;
let tSend = 0;

function setState(s) {
  state = s;
  setUIState(s);
  stopBtn.classList.toggle('hidden', s !== 'speaking');
  if (s === 'idle') { subtitleEl.textContent = ''; }
  if (s === 'listening') { subtitleEl.textContent = '正在倾听…（松开结束，最长 20 秒）'; }
}

// ---- audio queue ----
function enqueueAudio(ev) {
  playQueue.push(ev);
  playQueue.sort((a, b) => a.seq - b.seq);
  if (!curAudio) playNext();
}
function playNext() {
  if (!playQueue.length) {
    setTalk(false);
    if (state === 'speaking') setState('idle');
    return;
  }
  const ev = playQueue.shift();
  const audio = new Audio(ev.url);
  curAudio = audio;
  setTalk(true);
  audio.play().catch(() => { nextAfter(audio); });
  audio.onended = () => nextAfter(audio);
  audio.onerror = () => { toast('语音播放失败，仅显示字幕'); nextAfter(audio); };
}
function nextAfter(audio) {
  if (curAudio === audio) { curAudio = null; playNext(); }
}
function stopPlayback() {
  playQueue = [];
  if (curAudio) { try { curAudio.pause(); } catch {} curAudio = null; }
  setTalk(false);
}

// ---- interruption ----
async function interrupt(source) {
  const hadVoice = !!curAudio || playQueue.length > 0;
  if (abortCtrl) { abortCtrl.abort(); abortCtrl = null; }
  stopPlayback();
  if (latestRound > barredRound) {
    barredRound = latestRound;                     // everything older is dead
    fetch('/api/interrupt', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ round_id: latestRound }),
      keepalive: true,
    }).catch(() => {});
  }
  curSubSeq = -1;
  setState('listening');
  if (hadVoice && source === 'button') toast('已打断，请说');
}

// ---- chat over SSE ----
async function chat(text) {
  if (!text || abortCtrl) return;
  abortCtrl = new AbortController();
  tSend = performance.now();
  setState('thinking');
  subtitleEl.textContent = '…';

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
      signal: abortCtrl.signal,
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
        handleSSE(chunk);
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') {
      toast('连接中断，请检查网络后重试');
      setState('idle');
    }
  } finally {
    if (abortCtrl && abortCtrl.signal.aborted) abortCtrl = null;
  }
}

function alive(round) { return round != null && round > barredRound; }

function handleSSE(chunk) {
  let event = 'message', data = null;
  for (const line of chunk.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) { try { data = JSON.parse(line.slice(5)); } catch { return; } }
  }
  if (!data) return;
  if (!alive(data.round_id)) return;          // stale round -> drop silently
  if (event === 'round') { latestRound = data.round_id; return; }

  switch (event) {
    case 'state':
      if (data.state === 'speaking') setState('speaking');
      else if (data.state === 'thinking' && state !== 'speaking') setState('thinking');
      break;
    case 'subtitle':
      curSubSeq = data.seq;
      subtitleEl.textContent = data.text;
      break;
    case 'audio':
      if (tSend) { hudLatency.textContent = Math.round(performance.now() - tSend) + ' ms'; tSend = 0; }
      enqueueAudio(data);
      break;
    case 'directive': applyDirective(data); break;
    case 'notice': toast(data.message); break;
    case 'error': toast('出错了：' + data.message); setState('idle'); break;
    case 'done':
      if (!curAudio && !playQueue.length) setState('idle');
      break;
  }
}

function applyDirective(d) {
  switch (d.t) {
    case 'emotion': setEmotion(d.v); break;
    case 'action': setAction(d.v); break;
    case 'scene': if (d.v === 'rain_stop') rainStop(); break;
    case 'media': if (d.kind === 'polaroid' && d.job_id) showPolaroid(d.job_id); break;
    case 'goto': break; // server-side story node; nothing to render
  }
}

// ---- UI bindings ----
sendBtn.addEventListener('click', () => { const t = input.value.trim(); if (t) { input.value = ''; chat(t); } });
input.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendBtn.click(); });
stopBtn.addEventListener('click', () => interrupt('button'));
bindVoice((text) => { input.value = ''; chat(text); }, (src) => interrupt(src), (submitted) => {
  // released with nothing recognized -> leave the dead listening state
  if (!submitted && state === 'listening' && !curAudio && !playQueue.length) setState('idle');
});

// unlock audio on first gesture (mobile autoplay policy) + rain ambience
const unlock = () => {
  startAmbience();                            // synthesized rain, fades in
  const a = new Audio(); a.play().then(() => a.pause()).catch(() => {});
  removeEventListener('pointerdown', unlock);
};
addEventListener('pointerdown', unlock);

// ---- boot ----
(async function boot() {
  try {
    const s = await (await fetch('/api/state')).json();
    hudMode.textContent = s.mock_mode ? 'MOCK 模式' : 'DashScope';
    if (s.mock_mode) hudMode.classList.add('mock');
  } catch { hudMode.textContent = '离线?'; }
  setState('idle');
  setTimeout(() => toast('欢迎来到雨夜咖啡馆。按住 🎤 或输入文字和 Mira 聊聊吧', 4200), 600);
})();
