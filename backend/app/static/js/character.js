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
}

export function setUIState(state) {
  wrap.classList.remove('listening', 'thinking');
  if (state === 'listening') wrap.classList.add('listening');
  if (state === 'thinking') wrap.classList.add('thinking');
  const badge = document.getElementById('state-badge');
  badge.dataset.state = state;
  const text = { idle: '待机中', listening: '正在倾听…', thinking: '思考中…', speaking: '说话中…' };
  document.getElementById('state-text').textContent = text[state] || state;
  if (state === 'idle') setTalk(false);
}
