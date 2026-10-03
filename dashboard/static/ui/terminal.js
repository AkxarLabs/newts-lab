/* Newts' Lab — the in-browser terminal: a CLI's own sign-in, an installer, or a shell, running on the
   machine the lab lives on (remote or headless included). xterm.js is loaded only when one opens. The
   server picks the command from a fixed table (dashboard/term.py); the page never sends a command line. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useEffect, useRef, useState } = NL;

  let loading = null;
  function loadXterm() {
    if (window.Terminal && window.FitAddon) return Promise.resolve();
    if (loading) return loading;
    const css = document.createElement('link');
    css.rel = 'stylesheet'; css.href = 'static/vendor/xterm/xterm.css';
    document.head.appendChild(css);
    const js = src => new Promise((res, rej) => { const s = document.createElement('script'); s.src = src; s.onload = res; s.onerror = rej; document.head.appendChild(s); });
    loading = js('static/vendor/xterm/xterm.js').then(() => js('static/vendor/xterm/addon-fit.js'));
    return loading;
  }
  const b64 = s => { const bin = atob(s); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u; };

  NL.TerminalSheet = ({ purpose, backend, onClose }) => {
    const host = useRef();
    const [info, setInfo] = useState(null);
    const [err, setErr] = useState(null);
    const [done, setDone] = useState(false);
    useEffect(() => {
      let alive = true, term = null, fit = null, id = null, offset = 0, timer = null, ro = null;
      (async () => {
        try { await loadXterm(); } catch (e) { setErr('could not load the terminal'); return; }
        if (!alive) return;
        const dark = document.documentElement.dataset.lamp !== 'day';
        term = new window.Terminal({ cursorBlink: true, convertEol: false, fontFamily: getComputedStyle(document.body).getPropertyValue('--mono') || 'monospace', fontSize: 13,
          theme: dark ? { background: '#081a1f', foreground: '#dcf3ed', cursor: '#5ff0d8', selectionBackground: '#1b3f48' } : { background: '#fbf6ea', foreground: '#33251a', cursor: '#2d8a7c', selectionBackground: '#eadab4' } });
        fit = new window.FitAddon.FitAddon();
        term.loadAddon(fit);
        term.open(host.current);
        try { fit.fit(); } catch (e) { /* hidden */ }
        const r = await NL.api('/api/term/open', { purpose, backend, cols: term.cols, rows: term.rows });
        if (!alive) return;
        if (!r.ok) { setErr(r.error || 'could not start it'); return; }
        id = r.id; setInfo(r);
        term.focus();
        term.onData(d => NL.api('/api/term/write', { id, data: d }));
        term.onResize(({ cols, rows }) => NL.api('/api/term/resize', { id, cols, rows }));
        ro = new ResizeObserver(() => { try { fit.fit(); } catch (e) { /* ignore */ } });
        ro.observe(host.current);
        const poll = async () => {
          if (!alive) return;
          const x = await NL.get(`/api/term/read?${NL.qs({ id, offset })}`);
          if (!alive) return;
          if (x.ok) {
            if (x.data) term.write(b64(x.data));
            offset = x.offset;
            if (x.exited) { setDone(true); NL.refresh(); return; }
          }
          timer = setTimeout(poll, x.data ? 60 : 200);
        };
        poll();
      })();
      return () => { alive = false; clearTimeout(timer); ro && ro.disconnect(); if (id) NL.api('/api/term/close', { id }); term && term.dispose(); };
    }, [purpose, backend]);
    const title = (info && info.title) || ({ login: `Sign in to ${backend}`, install: `Install ${backend}`, shell: 'Terminal' }[purpose]);
    const s = NL.getState() || {};
    const where = s.remote ? `on ${s.remote.name || s.remote.host}` : 'on this machine';
    return html`<${NL.Sheet} wide title=${title} onClose=${onClose}
      sub=${html`<span class="row-wrap"><span>Running ${where}</span>${info ? html`<span class="mono small muted">${info.command}</span>` : null}${done ? html`<${NL.Pill} tone="ok">finished</${NL.Pill}>` : null}</span>`}
      footer=${html`<div class="row"><span class="muted small">${purpose === 'login' ? 'Type into the terminal as you would in any shell. Credentials go to the CLI only — this page never stores them.' : 'Everything typed here goes to this process only.'}</span><span class="grow"></span>
        <${NL.Btn} onClick=${onClose}>${done ? 'Close' : 'Close (stops it)'}</${NL.Btn}></div>`}>
      ${err ? html`<div class="note note-warn">${err}</div>` : null}
      <div class="xterm-host" ref=${host}></div></${NL.Sheet}>`;
  };
  NL.openTerminal = (purpose, backend) => NL.open(NL.TerminalSheet, { purpose, backend }, { key: 'term:' + purpose + ':' + (backend || '') });

  /** Sign in / install / shell: a window on this machine's desktop when there is one (and the lab is
      local); otherwise — a remote lab, or a machine with no desktop — the in-browser terminal. */
  NL.runOnLabMachine = async (purpose, backend) => {
    const s = NL.getState() || {};
    const li = s.lab_info || {};
    const inBrowser = !!s.remote || li.desktop === false;
    if (!inBrowser) {
      const r = await NL.act('/api/terminal', { purpose, backend });
      return r.ok ? 'window' : null;
    }
    NL.openTerminal(purpose, backend);
    return 'browser';
  };
})();
