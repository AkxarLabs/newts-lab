/* The trailer: the real dashboard (its demo lab, in a frame) cut to the soundtrack in music.js.
   The audio clock is the master: every frame reads the beat from it, so cuts, captions and the camera land on
   the beat however slow the machine is. Scenes are data; each one says what to do to the lab and when. */
(function () {
  const $ = s => document.querySelector(s);
  const stage = $('#stage'), cam = $('#cam'), frame = $('#lab'), spot = $('#spot'), flash = $('#flash'), black = $('#black');
  const cap = $('#cap'), capIdx = cap.querySelector('.idx'), capH = cap.querySelector('h1'), capP = cap.querySelector('p');
  const title = $('#title'), logo = title.querySelector('.logo'), tH = title.querySelector('h2'), tSub = title.querySelector('.sub'), tCode = title.querySelector('code');
  const scrim = $('#scrim'), hud = $('#hud'), barEl = $('#bar'), seq = $('#seq'), meter = $('#meter i');
  const { BPM, BARS, SPB } = window.TrailerMusic;
  for (let i = 0; i < 16; i++) { const c = document.createElement('i'); if (i % 4 === 0) c.className = 'k'; seq.appendChild(c); }
  const cells = [...seq.children];

  // fit the 1600×900 stage to the window
  const fit = () => { const k = Math.min(innerWidth / 1600, innerHeight / 900); stage.style.transform = `translate(-50%, -50%) scale(${k})`; };
  addEventListener('resize', fit); fit();

  // the frame's own preferences are this browser's dashboard preferences: keep them, put them back after
  const KEEP = ['nl-prefs', 'nl-lens'], saved = {};
  KEEP.forEach(k => { try { saved[k] = localStorage.getItem(k); } catch (e) { /* storage off */ } });
  const restore = () => KEEP.forEach(k => { try { if (saved[k] == null) localStorage.removeItem(k); else localStorage.setItem(k, saved[k]); } catch (e) { /* storage off */ } });
  addEventListener('beforeunload', restore);

  // ── driving the lab ───────────────────────────────────────────────────────────────────────────
  const F = () => frame.contentWindow, NL = () => F().NL, D = () => F().document;
  const shown = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.right > 0 && r.left < 1600; };
  const byText = (sel, text) => [...D().querySelectorAll(sel)].reverse().find(e => (e.textContent || '').trim().startsWith(text) && shown(e));
  const clearLayers = () => { let n = 0; try { while (NL().closeTop() && n++ < 8); } catch (e) { /* not ready */ } };
  const go = hash => { clearLayers(); F().location.hash = hash; };
  const theme = t => NL().setPref('theme', t);
  // scroll the sheet (never this page) so an element sits in the middle of it
  const reveal = el => {
    if (!el) return;
    for (let p = el.parentElement; p; p = p.parentElement) {
      const oy = F().getComputedStyle(p).overflowY;
      if ((oy === 'auto' || oy === 'scroll') && p.scrollHeight > p.clientHeight) {
        const top = el.getBoundingClientRect().top - p.getBoundingClientRect().top + p.scrollTop - p.clientHeight / 2;
        p.scrollTo({ top, behavior: document.hidden ? 'auto' : 'smooth' }); return;
      }
    }
  };
  const lensChip = name => { const b = byText('.lenses button', name); if (b) b.click(); };
  let typing = null;
  const typeInto = (text, from, to) => { typing = { text, from, to }; };
  const setAsk = v => { const el = D().querySelector('.askbar-in'); if (!el) return; const set = Object.getOwnPropertyDescriptor(F().HTMLInputElement.prototype, 'value').set; set.call(el, v); const W = F(); el.dispatchEvent(new W.Event('input', { bubbles: true })); };

  // ── the scenes (bars) ─────────────────────────────────────────────────────────────────────────
  // at: the bar it starts · idx: the chapter mark · h: the headline (*word* = highlighted) · p: the line under it
  // act(): at the cut · ev: [beat in the scene, fn] · spot: what to ring, and from which beat · cam: [scale from, to, origin]
  const SCENES = [
    { at: 0, kind: 'title', cam: [1.12, 1.06, '50% 50%'] },
    { at: 4, h: 'Agents run the *research.*', cam: [1.06, 1.1, '40% 55%'], act: () => go('#/') },
    { at: 6, h: 'You make the *calls.*', cam: [1.1, 1.02, '85% 40%'], spot: [() => byText('.rail .rail-sec', 'Needs you'), 2, 'warm'] },
    { at: 8, idx: '01', h: 'The whole lab, live in *3D.*', p: 'Each room is a stage of the research. Each newt is an agent at work.', cam: [1.0, 1.08, '42% 52%'],
      act: () => { go('#/'); lensChip('Work'); }, ev: [[4, () => NL().Scene.focusProject('moe')]] },
    { at: 10, idx: '02', h: 'Every run, *traced.*', p: 'Open any agent and read what it did, step by step.', cam: [1.0, 1.05, '50% 40%'],
      act: () => { NL().Scene.back(); go('#/runs'); }, ev: [[3, () => NL().openRun('r-moe')]] },
    { at: 12, idx: '03', h: 'Three gates. *You* approve each one.', p: 'The proposal, full-scale runs, the final paper. Nothing passes without you.', cam: [1.0, 1.06, '75% 60%'],
      act: () => go('#/study/prop-1?gate=1'), spot: [() => byText('button', 'Approve Gate'), 3] },
    { at: 14, idx: '04', h: 'Studies move *left to right.*', p: 'Idea, literature, proposal, experiments, analysis, paper.', cam: [1.04, 1.0, '30% 40%'], act: () => go('#/studies') },
    { at: 16, idx: '05', h: 'Results come *to you.*', p: 'Figures, notes and questions from every agent, in one place.', cam: [1.0, 1.05, '50% 35%'], act: () => go('#/artifacts'), ev: [[1.5, () => { const r = D().querySelector('.art-row'); if (r) r.click(); }]] },
    { at: 18, idx: '06', h: 'Change how *any step* works.', p: 'Add your own instructions to a stage, or replace its method.', cam: [1.05, 1.0, '50% 50%'], act: () => go('#/compose') },
    { at: 20, idx: '07', h: 'Approve a campaign. *Walk away.*', p: 'Set the hours, the budget and a spending cap. It stops when they run out.', cam: [1.0, 1.05, '60% 50%'],
      act: () => go('#/'), ev: [[1, () => NL().openStart({ intent: 'campaign' })], [2, () => reveal(byText('button', 'Approve and start'))]], spot: [() => byText('button', 'Approve and start'), 3.5] },
    { at: 22, idx: '08', h: 'Day or *night.*', p: 'One button.', cam: [1.02, 1.08, '45% 50%'],
      act: () => go('#/'), spot: ['.topright button[aria-label^="Theme"]', 0], ev: [[0, () => theme('day')], [2, () => theme('night')], [4, () => theme('day')], [6, () => theme('night')]] },
    { at: 24, idx: '09', h: 'One dashboard. *Every machine.*', p: 'Your laptop, a workstation, a cluster. Each lab shows what needs you.', cam: [1.0, 1.05, '50% 45%'], act: () => { theme('night'); go('#/labs'); } },
    { at: 26, idx: '10', top: true, h: 'Ask in *plain words.*', p: 'Or give an instruction. An agent picks it up.', cam: [1.0, 1.12, '35% 96%'],
      act: () => { go('#/'); setAsk(''); typeInto('Compare the last three trial runs of moe and say which setting mattered', 0.5, 6.6); }, spot: ['.askbar', 0] },
    { at: 28, idx: '11', h: '*Pause* everything, any time.', p: 'One button stops every agent. Resume when you are ready.', cam: [1.0, 1.06, '70% 20%'],
      act: () => { typing = null; setAsk(''); }, spot: ['.topright .topbtn', 1, 'warm'], ev: [[4, () => NL().pauseLab(true)]] },
    { at: 30, idx: '12', h: 'See cost, risk and *what waits on you.*', p: '', cam: [1.04, 1.0, '45% 50%'],
      act: () => clearLayers(), spot: ['.lenses', 0], ev: [[0, () => lensChip('Cost')], [2, () => lensChip('Risk')], [4, () => lensChip('Waiting')], [6, () => lensChip('Work')]] },
    { at: 32, kind: 'outro', cam: [1.0, 1.1, '50% 50%'] },
  ];
  const sceneAt = bar => { let s = SCENES[0]; for (const x of SCENES) if (x.at <= bar) s = x; return s; };

  // ── captions and titles ───────────────────────────────────────────────────────────────────────
  // *…* highlights words, possibly several in a row
  const markup = h => { let on = false; return h.split(' ').map(w => { const start = w.startsWith('*'), end = w.endsWith('*'); if (start) on = true; const hl = on; if (end) on = false; return `<span class="w${hl ? ' hl' : ''}">${w.replace(/\*/g, '')}</span>`; }).join(' '); };
  function setCaption(sc) {
    cap.classList.toggle('top', !!sc.top); scrim.classList.toggle('top', !!sc.top);
    capIdx.textContent = sc.idx ? `${sc.idx} / 12` : ''; capIdx.style.opacity = sc.idx ? 1 : 0;
    capH.innerHTML = sc.h ? markup(sc.h) : ''; capP.textContent = sc.p || ''; capP.classList.remove('in');
    cap.classList.add('glitch'); setTimeout(() => cap.classList.remove('glitch'), 140);
  }
  function setTitle(kind) {
    title.style.display = kind ? 'grid' : 'none';
    [logo, tSub, tCode].forEach(e => e.classList.remove('in'));
    tH.innerHTML = kind ? `<span class="w">Newts'</span> <span class="w">Lab</span>` : '';
    tSub.textContent = kind === 'outro' ? 'Runs on your machine. You stay in charge.' : 'A research lab run by AI agents.';
    tCode.textContent = kind === 'outro' ? 'uv run --with pyyaml python newts.py' : '';
    tCode.style.display = kind === 'outro' ? '' : 'none';
  }

  // ── the clock ─────────────────────────────────────────────────────────────────────────────────
  let ctx = null, music = null, cur = null, fired = new Set(), raf = 0, recorder = null, playing = false;
  const flashNow = (k = 0.55) => { flash.style.transition = 'none'; flash.style.opacity = k; requestAnimationFrame(() => { flash.style.transition = 'opacity .22s ease-out'; flash.style.opacity = 0; }); };
  const lerp = (a, b, k) => a + (b - a) * Math.max(0, Math.min(1, k));
  function tick() {
    raf = requestAnimationFrame(tick);
    const lat = ctx.outputLatency || ctx.baseLatency || 0;
    render((ctx.currentTime - lat - music.t0) / SPB);              // beats since bar 0
  }
  function render(pos) {
    if (pos < 0) return;
    const bar = pos / 4;
    if (bar >= BARS) return finish();
    const sc = sceneAt(Math.floor(bar)), inBeats = pos - sc.at * 4, len = ((SCENES[SCENES.indexOf(sc) + 1] || { at: BARS }).at - sc.at) * 4;
    if (sc !== cur) {
      cur = sc; fired = new Set();
      try { if (sc.act) sc.act(); } catch (e) { console.warn('scene', sc.at, e); }
      if (sc.kind) { setTitle(sc.kind); capH.innerHTML = ''; capP.textContent = ''; capIdx.style.opacity = 0; } else { setTitle(null); setCaption(sc); }
      if (sc.at >= 8 && sc.at < 32) flashNow(sc.at === 8 ? 0.95 : 0.5); else if (sc.at === 32) flashNow(0.8);
      spot.style.opacity = 0;
    }
    for (const [b, fn] of sc.ev || []) if (inBeats >= b && !fired.has(b)) { fired.add(b); try { fn(); } catch (e) { console.warn('event', sc.at, b, e); } }
    // headline words land on eighth notes; the line under it on beat 3
    capH.querySelectorAll('.w').forEach((w, i) => w.classList.toggle('in', inBeats >= i * 0.5));
    if (sc.p && inBeats >= 2.5) capP.classList.add('in');
    if (sc.kind) {
      const intro = sc.kind === 'title';
      logo.classList.toggle('in', inBeats >= (intro ? 2 : 0));
      tH.querySelectorAll('.w').forEach((w, i) => w.classList.toggle('in', inBeats >= (intro ? 4 : 1) + i));
      tSub.classList.toggle('in', inBeats >= (intro ? 8 : 4));
      tCode.classList.toggle('in', inBeats >= 8);
      if (intro && inBeats > 14) title.style.opacity = Math.max(0, 1 - (inBeats - 14) / 2); else title.style.opacity = 1;
    }
    // typing into the ask bar, a few letters every sixteenth
    if (typing && sc.at === 26) { const k = (inBeats - typing.from) / (typing.to - typing.from); if (k > 0) setAsk(typing.text.slice(0, Math.round(typing.text.length * Math.min(1, k)))); }
    // the ring around what the scene is about
    if (sc.spot && inBeats >= sc.spot[1]) {
      let el = null; try { el = typeof sc.spot[0] === 'function' ? sc.spot[0]() : D().querySelector(sc.spot[0]); } catch (e) { el = null; }
      if (el) { const r = el.getBoundingClientRect(), pad = 8; Object.assign(spot.style, { left: r.left - pad + 'px', top: r.top - pad + 'px', width: r.width + pad * 2 + 'px', height: r.height + pad * 2 + 'px', opacity: 1 }); spot.classList.toggle('warm', sc.spot[2] === 'warm'); }
    } else spot.style.opacity = 0;
    // the camera: a slow push through the scene, a punch on every kick while the drums play
    const [s0, s1, origin] = sc.cam || [1, 1, '50% 50%'], drums = bar >= 4 && bar < 32 && !((Math.floor(bar) === 23 || Math.floor(bar) === 31) && (bar % 1) >= 0.5);
    const frac = pos % 1, punch = drums ? 0.012 * Math.exp(-frac * 7) : 0;
    cam.style.transformOrigin = origin; cam.style.transform = `scale(${lerp(s0, s1, inBeats / len) * (1 + punch)})`;
    // the world comes into focus over the build, and goes soft again for the end card
    const blur = bar < 4 ? 16 : bar < 8 ? lerp(16, 0, (bar - 4) / 3.5) : bar >= 32 ? lerp(0, 14, (bar - 32) / 1.5) : 0;
    const dim = bar < 4 ? 0.42 : bar < 8 ? lerp(0.42, 1, (bar - 4) / 3.5) : bar >= 32 ? lerp(1, 0.4, (bar - 32) / 1.5) : 1;
    cam.style.filter = blur > 0.1 || dim < 0.99 ? `blur(${blur.toFixed(1)}px) brightness(${dim.toFixed(2)})` : 'none';
    black.style.opacity = bar < 2 ? lerp(1, 0, bar / 2) : bar > BARS - 1 ? lerp(0, 1, bar - (BARS - 1)) : 0;
    // HUD
    hud.classList.toggle('in', bar >= 8 && bar < 32); scrim.classList.toggle('in', bar >= 4 && bar < 32); seq.classList.toggle('in', bar >= 4 && bar < 32);
    const s16 = Math.floor(pos * 4) % 16; cells.forEach((c, i) => c.classList.toggle('on', i === s16));
    barEl.innerHTML = `BAR ${String(Math.floor(bar) + 1).padStart(2, '0')} / ${BARS} <b>·</b> ${BPM} BPM`;
    meter.style.width = (100 * bar / BARS).toFixed(2) + '%';
  }

  // ── play, record, finish ──────────────────────────────────────────────────────────────────────
  const playBtn = $('#play'), recBtn = $('#rec'), load = $('#load'), start = $('#start');
  function prep() {
    const nl = NL();
    nl.setPref('strapline', false); nl.setPref('theme', 'night'); nl.setPref('rail', true);
    if (nl.Sound) nl.Sound.set({ music: false, chimes: false });
    go('#/'); lensChip('Work');
  }
  async function play(fromBar = 0) {
    prep();
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    await ctx.resume();
    music = window.TrailerMusic.create(ctx);
    music.start(ctx.currentTime + 0.25, fromBar);
    cur = null; playing = true; start.classList.add('hide'); title.style.opacity = 1;
    cancelAnimationFrame(raf); raf = requestAnimationFrame(tick);
    return music;
  }
  function finish() {
    if (!playing) return;
    playing = false; cancelAnimationFrame(raf); typing = null;
    try { clearLayers(); setAsk(''); lensChip('Work'); NL().Scene.back(); } catch (e) { /* frame gone */ }
    restore();
    if (music) music.stop();
    if (recorder && recorder.state === 'recording') recorder.stop();
    setTimeout(() => { start.classList.remove('hide'); playBtn.textContent = '▶ Play again'; black.style.opacity = 0; }, recorder ? 400 : 0);
  }
  addEventListener('keydown', e => { if (e.key === 'Escape' && playing) finish(); });
  playBtn.onclick = () => play(+(new URLSearchParams(location.search).get('bar') || 0));
  recBtn.onclick = async () => {
    let screen;
    try { screen = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 60, displaySurface: 'browser' }, audio: false, preferCurrentTab: true, selfBrowserSurface: 'include' }); }
    catch (e) { load.textContent = 'Recording was not allowed. You can still play it and record with your own screen recorder.'; return; }
    const m = await play(0);
    const stream = new MediaStream([...screen.getVideoTracks(), ...m.out.getAudioTracks()]);
    const type = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm'].find(t => MediaRecorder.isTypeSupported(t));
    const chunks = []; recorder = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: 12e6 });
    recorder.ondataavailable = e => e.data.size && chunks.push(e.data);
    recorder.onstop = () => {
      screen.getTracks().forEach(t => t.stop());
      const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob(chunks, { type: 'video/webm' })); a.download = 'newts-lab-trailer.webm'; a.click();
      load.textContent = 'Saved newts-lab-trailer.webm to your downloads.'; recorder = null;
    };
    recorder.start(250);
  };
  // ready when the lab in the frame has drawn its world
  const ready = () => { try { return NL() && NL().Scene && D().querySelector('.home'); } catch (e) { return false; } };
  const wait = setInterval(() => { if (!ready()) return; clearInterval(wait); setTimeout(() => { playBtn.disabled = false; recBtn.disabled = !(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia && window.MediaRecorder); load.textContent = 'Ready. Sound on.'; }, 1200); }, 200);
  // for checking a moment without sound: __trailer.at(bar) draws the timeline there (scene actions included)
  window.__trailer = { play, finish, scenes: SCENES, at: bar => { if (!playing) { prep(); playing = true; start.classList.add('hide'); } render(bar * 4); } };
})();
