/* Newts' Lab — sound: gentle notification chimes and a soft generative ambient score.
   Everything is synthesised live with the Web Audio API — no audio files, nothing downloaded.
   Both are OFF by default; prefs persist in localStorage 'nl-sound'. The app hands every lab snapshot
   to NL.Sound.observe(); it diffs against the previous one and chimes for what needs the scientist.
   Key: D major, pentatonic melody — chimes and music share it so a chime never clashes with the pad.
   If the browser has no AudioContext, every call is a harmless no-op. */
(function () {
  'use strict';
  const NL = (window.NL = window.NL || {});
  const AC = window.AudioContext || window.webkitAudioContext;
  const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;

  /* ── prefs ─────────────────────────────────────────────────────────────── */
  const KEY = 'nl-sound';
  const DEFAULTS = { chimes: false, music: false, volume: 0.6, musicVolume: 0.35 };
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
  const unit = (x, d) => { x = Number(x); return isFinite(x) ? clamp(x, 0, 1) : d; };
  const norm = p => ({ chimes: !!p.chimes, music: !!p.music,
    volume: unit(p.volume, DEFAULTS.volume), musicVolume: unit(p.musicVolume, DEFAULTS.musicVolume) });
  let P = (() => {
    try { const raw = localStorage.getItem(KEY); return norm(Object.assign({}, DEFAULTS, raw ? JSON.parse(raw) : null)); }
    catch (e) { return Object.assign({}, DEFAULTS); }
  })();
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(P)); } catch (e) { /* private mode */ } };
  const subs = new Set();
  const notify = () => { const p = api.prefs(), s = api.state(); subs.forEach(fn => { try { fn(p, s); } catch (e) { /* ignore */ } }); };

  /* ── little music helpers ──────────────────────────────────────────────── */
  const mtof = m => 440 * Math.pow(2, (m - 69) / 12);
  const rand = (a, b) => a + Math.random() * (b - a);
  const pick = xs => xs[Math.floor(Math.random() * xs.length)];
  const lerp = (a, b, t) => a + (b - a) * t;
  const disc = n => { try { n.disconnect(); } catch (e) { /* already gone */ } };
  const gainNode = (c, v) => { const g = c.createGain(); g.gain.value = v; return g; };
  const CHIME_TRIM = 1.6;                           // chimes sit a little above the music at equal settings

  /* ── the audio graph (built per context, so an OfflineAudioContext can render the same thing) ──
     voices → chimeBus / music filter → limiter → out → speakers, with a shared generated reverb. */
  function makeIR(c, secs, decay) {
    // impulse response = low-passed noise under a power-law decay; darker as it fades
    const rate = c.sampleRate, len = Math.max(2, Math.floor(rate * secs)), pre = Math.floor(rate * 0.018);
    const buf = c.createBuffer(2, len, rate);
    for (let ch = 0; ch < 2; ch++) {
      const d = buf.getChannelData(ch); let lp = 0;
      for (let i = pre; i < len; i++) {
        const x = (i - pre) / (len - pre);
        lp += (Math.random() * 2 - 1 - lp) * (0.55 - 0.42 * x);
        d[i] = lp * Math.pow(1 - x, decay);
      }
    }
    return buf;
  }
  function buildGraph(c) {
    const g = { c };
    g.limiter = c.createDynamicsCompressor();
    try { g.limiter.threshold.value = -4; g.limiter.knee.value = 2; g.limiter.ratio.value = 12;
      g.limiter.attack.value = 0.003; g.limiter.release.value = 0.3; } catch (e) { /* defaults are fine */ }
    g.out = gainNode(c, 0.8);                      // a safety limiter only; 0.8 offsets the compressor's automatic make-up gain
    g.limiter.connect(g.out); g.out.connect(c.destination);
    g.verb = c.createConvolver(); g.verb.buffer = makeIR(c, 3.4, 2.6);
    g.verbIn = gainNode(c, 1); g.verbOut = gainNode(c, 0.55);
    g.verbIn.connect(g.verb); g.verb.connect(g.verbOut); g.verbOut.connect(g.limiter);
    g.chimeBus = gainNode(c, P.volume * CHIME_TRIM); g.chimeBus.connect(g.limiter);
    g.chimeSend = gainNode(c, 0.3); g.chimeBus.connect(g.chimeSend); g.chimeSend.connect(g.verbIn);
    return g;
  }

  // one enveloped sine/triangle partial; cleans itself up when it stops
  function tone(g, dest, f, t, amp, attack, dur, type, pan) {
    const c = g.c, o = c.createOscillator(), e = c.createGain();
    o.type = type || 'sine'; o.frequency.value = f;
    e.gain.setValueAtTime(0, t);
    e.gain.linearRampToValueAtTime(Math.max(amp, 0.0002), t + attack);
    e.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(e);
    const nodes = [o, e];
    if (pan && c.createStereoPanner) {
      const p = c.createStereoPanner(); p.pan.value = clamp(pan, -1, 1);
      e.connect(p); p.connect(dest); nodes.push(p);
    } else e.connect(dest);
    o.onended = () => nodes.forEach(disc);
    o.start(t); o.stop(t + dur + 0.05);
  }
  // a bell/pluck = a few partials [ratio, relative amp, relative decay]
  function bell(g, dest, f, t, amp, dur, partials, pan, attack) {
    partials.forEach(([r, a, d]) => tone(g, dest, f * r, t, amp * a, attack || 0.008, Math.max(0.08, dur * d), 'sine', pan));
  }

  /* ── chimes ─────────────────────────────────────────────────────────────── */
  const WARM = [[1, 1, 1], [2, 0.3, 0.55], [3, 0.09, 0.35], [4.01, 0.03, 0.22]];
  const LIGHT = [[1, 1, 1], [2, 0.25, 0.5], [3, 0.06, 0.3]];
  const MARIMBA = [[1, 1, 1], [3.98, 0.12, 0.15], [2, 0.08, 0.3]];
  const SOFT = [[1, 1, 1], [2, 0.18, 0.5]];
  const GLASS = [[1, 1, 1], [2.76, 0.3, 0.45], [5.4, 0.08, 0.25]];
  const CHIMES = {
    // an agent needs you: warm rising fourth A4 → D5 (the most noticeable, still gentle)
    ask(g, t) { bell(g, g.chimeBus, mtof(69), t, 0.18, 1.1, WARM, -0.12, 0.008);
      bell(g, g.chimeBus, mtof(74), t + 0.18, 0.2, 1.25, WARM, 0.12, 0.008); },
    // a run finished well: one light marimba-ish F#5
    done(g, t) { bell(g, g.chimeBus, mtof(78), t, 0.17, 0.6, MARIMBA, 0.1, 0.004); },
    // something failed: soft D4+G#4 (tritone) easing into D3+D4+A4 (open fifth) — never alarming
    fail(g, t) { const B = g.chimeBus;
      bell(g, B, mtof(62), t, 0.1, 0.75, SOFT, -0.15, 0.03); bell(g, B, mtof(68), t, 0.075, 0.7, SOFT, 0.15, 0.03);
      const u = t + 0.36;
      bell(g, B, mtof(50), u, 0.07, 1.05, SOFT, 0, 0.04); bell(g, B, mtof(62), u, 0.1, 1.05, SOFT, -0.1, 0.04);
      bell(g, B, mtof(69), u, 0.085, 1.05, SOFT, 0.1, 0.04); },
    // a gate waits for your signature: D5 F#5 A5
    gate(g, t) { [74, 78, 81].forEach((m, i) => bell(g, g.chimeBus, mtof(m), t + i * 0.14, 0.12, 1.0, LIGHT, (i - 1) * 0.2, 0.006)); },
    // a new artifact for you: a tiny glassy A6 ping
    new(g, t) { bell(g, g.chimeBus, mtof(93), t, 0.06, 0.5, GLASS, 0.25, 0.003); },
  };
  const KINDS = Object.keys(CHIMES);

  /* ── the context: created lazily; resumed on the first gesture when autoplay blocks it ── */
  let ctx = null, G = null, armed = false;
  function ensureCtx() {
    if (ctx) return ctx;
    if (!AC) return null;
    try { ctx = new AC({ latencyHint: 'playback' }); } catch (e) { try { ctx = new AC(); } catch (e2) { return null; } }
    try { G = buildGraph(ctx); } catch (e) { try { ctx.close(); } catch (e2) { /* ignore */ } ctx = null; return null; }
    ctx.onstatechange = () => { if (ctx && ctx.state === 'running' && musicOn) startScheduler(); notify(); };
    return ctx;
  }
  function arm() {
    if (armed || !AC) return;
    armed = true;
    const go = () => {
      window.removeEventListener('pointerdown', go, true); window.removeEventListener('keydown', go, true);
      armed = false;
      if (!(P.music || P.chimes)) return;
      const c = ensureCtx(); if (!c) return;
      if (P.music && !musicOn) startMusic();
      if (c.state !== 'running') { try { c.resume().then(notify, () => {}); } catch (e) { /* ignore */ } }
    };
    window.addEventListener('pointerdown', go, true); window.addEventListener('keydown', go, true);
  }
  function wake() {
    if (!ctx || ctx.state === 'running' || ctx.state === 'closed') return;
    try { const r = ctx.resume(); if (r && r.catch) r.catch(() => {}); } catch (e) { /* ignore */ }
    arm();
  }
  const noGestureYet = () => !!(navigator.userActivation && !navigator.userActivation.hasBeenActive);
  function ramp(param, v, secs) {
    if (!ctx) return;
    const t = ctx.currentTime;
    try {
      if (param.cancelAndHoldAtTime) param.cancelAndHoldAtTime(t);
      else { const cur = param.value; param.cancelScheduledValues(t); param.setValueAtTime(cur, t); }
      param.linearRampToValueAtTime(v, t + secs);
    } catch (e) { param.value = v; }
  }

  /* rate limit: one per kind per 4 s, three per 10 s overall */
  const lastKind = {}; let recent = [];
  function allowed(kind) {
    const now = Date.now();
    if (now - (lastKind[kind] || 0) < 4000) return false;
    recent = recent.filter(x => now - x < 10000);
    if (recent.length >= 3) return false;
    lastKind[kind] = now; recent.push(now);
    return true;
  }
  function chimeAt(kind, delay) {
    if (!P.chimes || !CHIMES[kind] || document.hidden) return false;
    if (!ctx && noGestureYet()) { arm(); return false; }   // don't create a context the browser will block
    const c = ensureCtx(); if (!c) return false;
    if (c.state !== 'running') { wake(); return false; }  // drop rather than play stale later
    if (!allowed(kind)) return false;
    try { CHIMES[kind](G, c.currentTime + 0.03 + (delay || 0)); return true; } catch (e) { return false; }
  }

  /* ── generative ambient music ─────────────────────────────────────────────
     Pad: 4-note D-major-family chords (soft detuned triangle+sine), 8–14 s each, ~5 s crossfades,
     drifting through a gentle modal walk. Melody: sparse "felt piano" notes from D major pentatonic,
     weighted to chord tones and small steps. All through a lowpass whose cutoff an LFO slowly moves;
     busier lab → slightly more notes and a slightly brighter filter. */
  const CHORDS = [
    [50, 57, 61, 64],   // Dmaj9   D3 A3 C#4 E4
    [47, 54, 57, 62],   // Bm7     B2 F#3 A3 D4
    [43, 54, 57, 59],   // Gmaj9   G2 F#3 A3 B3
    [52, 59, 62, 66],   // Em9     E3 B3 D4 F#4
    [45, 52, 59, 64],   // Asus2   A2 E3 B3 E4
    [54, 57, 61, 64],   // F#m7    F#3 A3 C#4 E4
  ];
  const NEXT = { 0: [1, 2, 4, 3], 1: [2, 3, 0], 2: [0, 3, 4, 5], 3: [4, 2, 0], 4: [0, 1, 2], 5: [2, 1, 3] };
  const SCALE = [62, 64, 66, 69, 71, 74, 76, 78, 81];   // D4 … A5, D major pentatonic
  const FELT = [[1, 1, 1], [2, 0.22, 0.45], [3, 0.06, 0.25]];
  const CAP = 12, LOOK = 0.7, TICK = 200;

  function newMusic(g) {
    const c = g.c, m = { g, ends: [], chord: -1, nextChordAt: 0, nextNoteAt: 0, act: 0, fBase: 850, lastNote: 69 };
    m.bus = gainNode(c, 0); m.bus.connect(g.limiter);
    m.send = gainNode(c, 0.45); m.bus.connect(m.send); m.send.connect(g.verbIn);
    m.filter = c.createBiquadFilter(); m.filter.type = 'lowpass'; m.filter.frequency.value = m.fBase; m.filter.Q.value = 0.6;
    m.filter.connect(m.bus);
    m.lfo = c.createOscillator(); m.lfo.frequency.value = 0.021;       // one sweep every ~48 s
    m.lfoAmt = gainNode(c, 260); m.lfo.connect(m.lfoAmt); m.lfoAmt.connect(m.filter.frequency);
    m.lfo.start();
    return m;
  }
  function dropMusic(m) {
    try { m.lfo.stop(); } catch (e) { /* ignore */ }
    [m.lfo, m.lfoAmt, m.filter, m.bus, m.send].forEach(disc);
  }
  const active = (m, t) => m.ends.reduce((n, e) => n + (e > t ? 1 : 0), 0);

  function padVoice(m, midi, t, hold) {
    const c = m.g.c, f = mtof(midi), att = rand(3.5, 5), end = t + hold + rand(5, 6.5);
    const e = c.createGain(), a = c.createOscillator(), b = c.createOscillator(), ga = gainNode(c, 0.55), gb = gainNode(c, 0.45);
    a.type = 'triangle'; b.type = 'sine'; a.frequency.value = f; b.frequency.value = f;
    a.detune.value = rand(-8, -3); b.detune.value = rand(3, 8);          // slow beating = chorus warmth
    const peak = 0.07 * (midi < 48 ? 1.15 : midi > 62 ? 0.8 : 1);
    e.gain.setValueAtTime(0, t); e.gain.linearRampToValueAtTime(peak, t + att);
    e.gain.setValueAtTime(peak, t + hold); e.gain.linearRampToValueAtTime(0, end);
    a.connect(ga); b.connect(gb); ga.connect(e); gb.connect(e);
    const nodes = [a, b, ga, gb, e]; let out = e;
    if (c.createStereoPanner) {                                          // each voice drifts across the field
      const p = c.createStereoPanner(), p0 = rand(-0.55, 0.55);
      p.pan.setValueAtTime(p0, t); p.pan.linearRampToValueAtTime(clamp(p0 + rand(-0.4, 0.4), -0.8, 0.8), end);
      e.connect(p); out = p; nodes.push(p);
    }
    out.connect(m.filter);
    b.onended = () => nodes.forEach(disc);
    a.start(t); b.start(t); a.stop(end + 0.05); b.stop(end + 0.05);
    m.ends.push(end);
  }
  function feltNote(m, midi, t, vel) {
    const dur = rand(2.4, 4);
    bell(m.g, m.filter, mtof(midi), t, vel, dur, FELT, rand(-0.6, 0.6), 0.018);
    m.ends.push(t + dur);
  }
  function chooseNote(m) {
    const tones = CHORDS[Math.max(0, m.chord)].map(n => n % 12), opts = []; let tot = 0;
    for (const n of SCALE) {
      if (n === m.lastNote) continue;
      const d = Math.abs(n - m.lastNote);
      const w = (tones.includes(n % 12) ? 3 : 1) * (d <= 5 ? 2.2 : d <= 9 ? 1 : 0.35);
      opts.push([n, w]); tot += w;
    }
    let r = Math.random() * tot;
    for (const [n, w] of opts) if ((r -= w) <= 0) return (m.lastNote = n);
    return (m.lastNote = opts[opts.length - 1][0]);
  }
  function schedule(m, until) {
    while (m.nextChordAt < until) {
      const t = m.nextChordAt, dur = rand(8, 14);
      m.chord = m.chord < 0 ? 0 : pick(NEXT[m.chord]);
      CHORDS[m.chord].forEach((n, i) => { if (active(m, t) < CAP) padVoice(m, n, t + i * rand(0.05, 0.35), dur); });
      m.nextChordAt = t + dur;
    }
    while (m.nextNoteAt < until) {
      const t = m.nextNoteAt, n = active(m, t);
      if (n < CAP) {
        const v = rand(0.05, 0.085) * (0.85 + 0.3 * m.act);
        feltNote(m, chooseNote(m), t, v);
        if (n < CAP - 1 && Math.random() < 0.22 + 0.2 * m.act) feltNote(m, chooseNote(m), t + rand(0.35, 0.8), v * 0.75);
      }
      m.nextNoteAt = t + lerp(7.5, 2.6, m.act) * rand(0.6, 1.4);
    }
  }
  function setBrightness(m, t, now) {
    const base = 850 + 1000 * m.act;
    if (Math.abs(base - m.fBase) < 25) return;
    m.fBase = base;
    if (now) m.filter.frequency.setTargetAtTime(base, t, 2.5); else m.filter.frequency.value = base;
  }

  let M = null, musicOn = false, timer = null, stopT = null, actTarget = 0;
  function tick() {
    if (!ctx || !M || !musicOn || ctx.state !== 'running') return;
    const now = ctx.currentTime;
    if (M.nextChordAt < now) M.nextChordAt = now + 0.05;                 // first tick, or back from a pause
    if (M.nextNoteAt < now) M.nextNoteAt = now + rand(1.5, 3);
    M.act += (actTarget - M.act) * 0.05;
    setBrightness(M, now, true);
    M.ends = M.ends.filter(e => e > now);
    schedule(M, now + LOOK);
  }
  function startScheduler() {
    if (timer || document.hidden || !musicOn) return;
    timer = setInterval(tick, TICK); tick();
  }
  function stopScheduler() { if (timer) { clearInterval(timer); timer = null; } }
  function startMusic() {
    const c = ensureCtx(); if (!c) return;
    musicOn = true;
    if (stopT) { clearTimeout(stopT); stopT = null; }
    if (!M) M = newMusic(G);
    ramp(M.bus.gain, P.musicVolume, 4);
    if (c.state !== 'running') wake();
    startScheduler(); notify();
  }
  function stopMusic() {
    musicOn = false; stopScheduler();
    if (M && ctx) {
      ramp(M.bus.gain, 0, 2);
      const m = M;
      if (stopT) clearTimeout(stopT);
      stopT = setTimeout(() => { stopT = null; if (!musicOn && M === m) { dropMusic(m); M = null; } }, 2400);
    }
    notify();
  }
  // hidden tab: stop scheduling (the pad already playing fades out on its own); resume when visible
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopScheduler(); else startScheduler(); });

  /* ── snapshot diffing ──────────────────────────────────────────────────── */
  const ACTIVE = new Set(['starting', 'running', 'resuming']), FAILED = new Set(['failed', 'timeout', 'killed']);
  const ORDER = ['ask', 'gate', 'fail', 'done', 'new'];
  let prev = null;

  /* ── public API ────────────────────────────────────────────────────────── */
  const api = {
    KINDS,
    prefs: () => Object.assign({}, P),
    set(partial) {
      P = norm(Object.assign({}, P, partial || {})); save();
      if (G && ctx) { try { G.chimeBus.gain.setTargetAtTime(P.volume * CHIME_TRIM, ctx.currentTime, 0.08); } catch (e) { /* ignore */ } }
      if (P.music && !musicOn) startMusic();
      else if (!P.music && musicOn) stopMusic();
      else if (musicOn && M) ramp(M.bus.gain, P.musicVolume, 0.6);
      if (P.chimes) { const c = ensureCtx(); if (c && c.state !== 'running') wake(); }
      notify();
      return api.prefs();
    },
    subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },
    chime: kind => chimeAt(kind, 0),
    test(kind) {
      if (!CHIMES[kind]) kind = 'ask';
      const c = ensureCtx(); if (!c) return false;
      const go = () => { try { CHIMES[kind](G, c.currentTime + 0.03); } catch (e) { /* ignore */ } };
      if (c.state === 'running') go();
      else { try { c.resume().then(() => { go(); notify(); }, () => {}); } catch (e) { return false; } }
      return true;
    },
    observe(s) {
      if (!s || typeof s !== 'object') return [];
      const att = Array.isArray(s.attention) ? s.attention : [], runs = Array.isArray(s.runs) ? s.runs : [];
      const arts = Array.isArray(s.artifacts) ? s.artifacts : null;
      const cur = {
        att: new Set(att.filter(a => a && a.id != null).map(a => a.id)),
        runs: new Map(runs.filter(r => r && r.run_id != null).map(r => [r.run_id, r.status])),
        arts: arts ? new Set(arts.filter(a => a && a.id != null).map(a => a.id)) : null,
      };
      let busy = 0; cur.runs.forEach(st => { if (ACTIVE.has(st)) busy++; });
      actTarget = Math.min(1, busy / 6);
      const fire = new Set();
      if (prev) {                                                     // the first snapshot only primes
        att.forEach(a => {
          if (!a || a.id == null || prev.att.has(a.id)) return;
          if (a.kind === 'question') fire.add('ask'); else if (a.kind === 'gate') fire.add('gate');
        });
        cur.runs.forEach((st, id) => {
          const was = prev.runs.get(id);
          if (st === 'waiting_input' && was !== 'waiting_input') fire.add('ask');
          else if (ACTIVE.has(was)) { if (st === 'completed') fire.add('done'); else if (FAILED.has(st)) fire.add('fail'); }
        });
        if (arts && prev.arts) arts.forEach(a => { if (a && a.id != null && !a.seen && !prev.arts.has(a.id)) fire.add('new'); });
      }
      prev = cur;
      const played = [];
      if (P.chimes) { let d = 0; ORDER.forEach(k => { if (fire.has(k) && chimeAt(k, d)) { played.push(k); d += 0.45; } }); }
      return played;
    },
    state: () => ({ ctx: !ctx ? 'none' : ctx.state === 'running' ? 'running' : 'suspended',
      playing: !!(musicOn && ctx && ctx.state === 'running') }),
    /* debug: render chimes and/or music offline → Promise<{peak, rms, seconds}> (null if unsupported) */
    _render(opts) {
      if (!OAC) return Promise.resolve(null);
      const o = Object.assign({ seconds: 10, chimes: KINDS, music: true, activity: 0 }, opts || {});
      const rate = 44100, oc = new OAC(2, Math.ceil(rate * o.seconds), rate), g = buildGraph(oc);
      (o.chimes || []).forEach((k, i) => CHIMES[k] && CHIMES[k](g, 0.2 + i * 1.6));
      if (o.music) {
        const m = newMusic(g); m.act = clamp(o.activity, 0, 1); setBrightness(m, 0, false);
        m.bus.gain.setValueAtTime(0, 0); m.bus.gain.linearRampToValueAtTime(P.musicVolume, 4);
        m.nextNoteAt = 1.5; schedule(m, o.seconds);
      }
      return oc.startRendering().then(buf => {
        let peak = 0, sum = 0, n = 0;
        for (let ch = 0; ch < buf.numberOfChannels; ch++) {
          const d = buf.getChannelData(ch);
          for (let i = 0; i < d.length; i++) { const v = Math.abs(d[i]); if (v > peak) peak = v; sum += d[i] * d[i]; n++; }
        }
        return { peak: +peak.toFixed(4), rms: +Math.sqrt(sum / n).toFixed(4), seconds: o.seconds };
      });
    },
  };
  NL.Sound = api;

  // prefs say on from a previous visit: wait for the first gesture rather than trip the autoplay block
  if (AC && (P.music || P.chimes)) arm();
})();
