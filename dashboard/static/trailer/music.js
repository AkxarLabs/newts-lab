/* The trailer's soundtrack, synthesized live with Web Audio: 124 BPM in A minor (Am, F, C, G), 36 bars.
   Intro (bars 0-3) pad and a filtered arpeggio · build (4-7) kick, hats, a riser · drop (8-31) the full groove,
   one scene every two bars · outro (32-35) the pad again and a last hit.
   TrailerMusic.create(ctx) → { bpm, bars, spb, start(at, fromBar), stop(), out, onStep } */
(function () {
  const BPM = 124, BARS = 36, SPB = 60 / BPM, S16 = SPB / 4;
  const CHORDS = [[57, 60, 64], [53, 57, 60], [55, 60, 64], [55, 59, 62]];   // Am F C G (close voicings)
  const ROOTS = [33, 29, 36, 31];
  const hz = m => 440 * Math.pow(2, (m - 69) / 12);
  const ARP = [0, 1, 2, 3, 4, 3, 2, 1, 0, 1, 2, 4, 5, 4, 2, 1];                // indexes into the chord, up two octaves

  function create(ctx) {
    const master = ctx.createGain(); master.gain.value = 0.6;
    const comp = ctx.createDynamicsCompressor(); comp.threshold.value = -16; comp.ratio.value = 4; comp.attack.value = 0.004; comp.release.value = 0.18;
    const limit = ctx.createDynamicsCompressor(); limit.threshold.value = -3; limit.knee.value = 0; limit.ratio.value = 20; limit.attack.value = 0.001; limit.release.value = 0.08;
    const out = ctx.createGain(); out.gain.value = 0.92;
    master.connect(comp); comp.connect(limit); limit.connect(out); out.connect(ctx.destination);
    const record = ctx.createMediaStreamDestination ? ctx.createMediaStreamDestination() : null; if (record) out.connect(record);
    // shared: noise, reverb, a dotted-eighth delay, the sidechain duck
    const noise = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate); { const d = noise.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1; }
    const verb = ctx.createConvolver(); {
      const len = ctx.sampleRate * 2.6, ir = ctx.createBuffer(2, len, ctx.sampleRate);
      for (let c = 0; c < 2; c++) { const d = ir.getChannelData(c); for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 2.6); }
      verb.buffer = ir;
    }
    const verbIn = ctx.createGain(); verbIn.gain.value = 0.32; verbIn.connect(verb); verb.connect(master);
    const delay = ctx.createDelay(1); delay.delayTime.value = S16 * 3; const fb = ctx.createGain(); fb.gain.value = 0.34;
    const dlp = ctx.createBiquadFilter(); dlp.type = 'lowpass'; dlp.frequency.value = 3200;
    delay.connect(dlp); dlp.connect(fb); fb.connect(delay); const delayIn = ctx.createGain(); delayIn.gain.value = 0.28; delayIn.connect(delay); dlp.connect(master);
    const duck = ctx.createGain(); duck.connect(master);                         // pad and bass breathe with the kick
    const env = (g, t, a, peak, d, end = 0.0001) => { g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + a); g.gain.exponentialRampToValueAtTime(end, t + a + d); };
    const src = (t, dur) => { const s = ctx.createBufferSource(); s.buffer = noise; s.start(t, Math.random() * 1.5); s.stop(t + dur); return s; };
    const filt = (type, f, q) => { const b = ctx.createBiquadFilter(); b.type = type; b.frequency.value = f; if (q) b.Q.value = q; return b; };
    const chain = (...n) => { for (let i = 0; i < n.length - 1; i++) n[i].connect(n[i + 1]); return n[n.length - 1]; };

    const V = {
      kick(t, v = 1) {
        const o = ctx.createOscillator(), g = ctx.createGain(); o.frequency.setValueAtTime(165, t); o.frequency.exponentialRampToValueAtTime(42, t + 0.13);
        env(g, t, 0.003, 1.0 * v, 0.42); chain(o, g, master); o.start(t); o.stop(t + 0.5);
        const c = ctx.createGain(); env(c, t, 0.001, 0.25 * v, 0.012); chain(src(t, 0.03), filt('highpass', 2500), c, master);
        duck.gain.cancelScheduledValues(t); duck.gain.setValueAtTime(0.32, t); duck.gain.linearRampToValueAtTime(1, t + SPB * 0.85);
      },
      clap(t, v = 1) {
        const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, t);
        [0, 0.011, 0.022].forEach((d, i) => { g.gain.setValueAtTime(0.5 * v, t + d); g.gain.exponentialRampToValueAtTime(i === 2 ? 0.0001 : 0.08, t + d + (i === 2 ? 0.22 : 0.01)); });
        const out = chain(src(t, 0.3), filt('bandpass', 1300, 0.9), g); out.connect(master); out.connect(verbIn);
      },
      hat(t, open, v = 1) { const g = ctx.createGain(); env(g, t, 0.002, (open ? 0.16 : 0.1) * v, open ? 0.24 : 0.035); chain(src(t, open ? 0.3 : 0.06), filt('highpass', 7600), g, master); },
      crash(t) { const g = ctx.createGain(); env(g, t, 0.004, 0.22, 1.9); const o = chain(src(t, 2), filt('highpass', 4200), g); o.connect(master); o.connect(verbIn); },
      bass(t, m, dur, open = 1) {
        const g = ctx.createGain(), f = filt('lowpass', 200, 7);
        f.frequency.setValueAtTime(220, t); f.frequency.exponentialRampToValueAtTime(380 + 1100 * open, t + 0.02); f.frequency.exponentialRampToValueAtTime(260, t + dur);
        env(g, t, 0.006, 0.42, dur);
        [-6, 6].forEach(c => { const o = ctx.createOscillator(); o.type = 'sawtooth'; o.frequency.value = hz(m); o.detune.value = c; o.connect(f); o.start(t); o.stop(t + dur + 0.05); });
        const sub = ctx.createOscillator(); sub.frequency.value = hz(m); const sg = ctx.createGain(); env(sg, t, 0.006, 0.5, dur); chain(sub, sg, duck); sub.start(t); sub.stop(t + dur + 0.05);
        chain(f, g, duck);
      },
      pad(t, notes, dur, v = 1, cutoff = 1500) {
        const g = ctx.createGain(), f = filt('lowpass', cutoff, 0.4);
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.06 * v, t + 0.35); g.gain.setValueAtTime(0.06 * v, t + dur - 0.1); g.gain.exponentialRampToValueAtTime(0.0001, t + dur + 0.5);
        notes.forEach(m => [-9, 0, 9].forEach(c => { const o = ctx.createOscillator(); o.type = 'sawtooth'; o.frequency.value = hz(m); o.detune.value = c; o.connect(f); o.start(t); o.stop(t + dur + 0.6); }));
        const o = chain(f, g); o.connect(duck); o.connect(verbIn);
      },
      pluck(t, m, v = 1, cutoff = 2600) {
        const o = ctx.createOscillator(), o2 = ctx.createOscillator(), g = ctx.createGain(), f = filt('lowpass', cutoff, 2);
        o.type = 'square'; o2.type = 'triangle'; o.frequency.value = hz(m); o2.frequency.value = hz(m + 12);
        f.frequency.setValueAtTime(cutoff, t); f.frequency.exponentialRampToValueAtTime(Math.max(300, cutoff * 0.25), t + 0.18);
        env(g, t, 0.003, 0.085 * v, 0.2); o.connect(f); o2.connect(f); const out = chain(f, g); out.connect(master); out.connect(delayIn); out.connect(verbIn);
        o.start(t); o2.start(t); o.stop(t + 0.3); o2.stop(t + 0.3);
      },
      riser(t, dur) {
        const g = ctx.createGain(), f = filt('bandpass', 400, 2.5);
        f.frequency.setValueAtTime(350, t); f.frequency.exponentialRampToValueAtTime(7000, t + dur);
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.32, t + dur); g.gain.exponentialRampToValueAtTime(0.0001, t + dur + 0.05);
        const o = chain(src(t, dur + 0.1), f, g); o.connect(master); o.connect(verbIn);
      },
      impact(t, v = 1) {
        const o = ctx.createOscillator(), g = ctx.createGain(); o.frequency.setValueAtTime(90, t); o.frequency.exponentialRampToValueAtTime(28, t + 1.2);
        env(g, t, 0.004, 0.9 * v, 1.6); chain(o, g, master); o.start(t); o.stop(t + 1.8);
        const n = ctx.createGain(); env(n, t, 0.002, 0.3 * v, 0.9); const x = chain(src(t, 1), filt('lowpass', 900), n); x.connect(master); x.connect(verbIn);
      },
      whoosh(t, dur = SPB) {                      // into a scene cut
        const g = ctx.createGain(), f = filt('bandpass', 800, 1.2);
        f.frequency.setValueAtTime(600, t); f.frequency.exponentialRampToValueAtTime(5000, t + dur);
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.1, t + dur * 0.9); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
        chain(src(t, dur + 0.05), f, g, master);
      },
      blip(t, m) { const o = ctx.createOscillator(), g = ctx.createGain(); o.type = 'sine'; o.frequency.value = hz(m); env(g, t, 0.002, 0.16, 0.14); const x = chain(o, g); x.connect(master); x.connect(delayIn); o.start(t); o.stop(t + 0.2); },
      key(t) { const g = ctx.createGain(); env(g, t, 0.001, 0.12, 0.018); chain(src(t, 0.03), filt('bandpass', 3800, 1.5), g, master); },
    };

    // ── the arrangement, one 16th at a time ──────────────────────────────────────────────────────
    const SCENE_CUTS = new Set([8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30]);
    function step(s, t) {
      const bar = Math.floor(s / 16), i = s % 16, beat = i % 4 === 0, ch = bar % 4;
      const intro = bar < 4, build = bar >= 4 && bar < 8, drop = bar >= 8 && bar < 32, outro = bar >= 32;
      const notes = CHORDS[ch];
      // pad: every bar, softer under the drop's arp
      if (i === 0 && bar < BARS - 1) V.pad(t, notes, SPB * 4, drop ? 0.7 : 1, intro ? 600 + bar * 300 : outro ? 900 : 1600);
      // arpeggio: filtered in the intro, open in the drop, sparse in the outro
      if (!outro || (bar < 34 && i % 2 === 0)) {
        if (intro && i % 2) { /* eighths only in the intro */ }
        else { const k = ARP[i], m = notes[k % 3] + 12 * Math.floor(k / 3) + (drop ? 12 : 0); V.pluck(t, m, intro ? 0.6 + bar * 0.12 : 1, intro ? 700 + bar * 450 : build ? 1800 + (bar - 4) * 300 : outro ? 1400 : 3000); }
      }
      // drums
      if (build) {
        if (beat) V.kick(t, 0.85);
        if (i % 4 === 2) V.hat(t, false, 0.7);
        if (bar === 7 && i >= 8) V.clap(t, 0.25 + (i - 8) * 0.08);                          // the roll into the drop
        if (bar === 6 && i === 0) V.riser(t, SPB * 8);
      }
      if (drop) {
        const breakBar = bar === 23 || bar === 31;                                         // half-bar breaks before the 2nd half and the outro
        if (beat && !(breakBar && i >= 8)) V.kick(t);
        if ((i === 4 || i === 12) && !(breakBar && i >= 8)) V.clap(t);
        if (i % 4 === 2) V.hat(t, true, 0.8); else if (i % 2 === 1) V.hat(t, false, 0.55);
        if (i === 0 && (bar - 8) % 4 === 0) V.crash(t);
        if (i % 2 === 0 && !(breakBar && i >= 8)) V.bass(t, ROOTS[ch] + (i % 8 === 6 ? 12 : 0), S16 * 1.7, (bar - 8) / 24);
        if (breakBar && i === 8) V.riser(t, SPB * 2);
        if (SCENE_CUTS.has(bar + 1) && i === 12) V.whoosh(t, SPB);
      }
      if (build && i % 8 === 0) V.bass(t, ROOTS[ch], S16 * 6, 0.1);
      if (s === 8 * 16 || s === 32 * 16) V.impact(t, s === 8 * 16 ? 1 : 0.8);
      // the "Day or night" scene: a blip on every theme flip; the "ask" scene: a key click per typed letter
      if ((bar === 22 || bar === 23) && i % 8 === 0) V.blip(t, i ? 76 : 81);
      if ((bar === 26 || bar === 27) && i % 2 === 1 && !(bar === 27 && i > 10)) V.key(t);
      if (outro && bar === 35 && i === 0) V.pad(t, [45, 57, 60, 64, 69], SPB * 4, 1.1, 1100);
      if (api.onStep) api.onStep(s, t);
    }

    let timer = null, next = 0, t0 = 0, endStep = BARS * 16;
    const api = {
      bpm: BPM, bars: BARS, spb: SPB, out: record ? record.stream : null, onStep: null,
      get t0() { return t0; },
      start(at, fromBar = 0) {
        t0 = at - fromBar * 4 * SPB; next = fromBar * 16;
        timer = setInterval(() => {
          const horizon = ctx.currentTime + 0.14;
          while (next < endStep && t0 + next * S16 < horizon) { const t = t0 + next * S16; if (t >= ctx.currentTime - 0.01) step(next, t); next++; }
          if (next >= endStep) { clearInterval(timer); timer = null; }
        }, 25);
      },
      scheduleAll(at, fromBar = 0, toBar = BARS) { t0 = at - fromBar * 4 * SPB; for (let i = fromBar * 16; i < Math.min(endStep, toBar * 16); i++) step(i, t0 + i * S16); },   // an OfflineAudioContext renders it in one go
      stop() { if (timer) clearInterval(timer); timer = null; master.gain.setTargetAtTime(0, ctx.currentTime, 0.08); },
    };
    return api;
  }
  window.TrailerMusic = { create, BPM, BARS, SPB };
})();
