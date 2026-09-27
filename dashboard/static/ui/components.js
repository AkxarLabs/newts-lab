/* Newts' Lab — shared UI pieces: buttons, pills, cards, sheets, dialogs, fields, tabs, markdown. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, useRef, useMemo, cls } = NL;

  NL.Btn = ({ children, onClick, kind, small, disabled, title, type, busy, icon }) => {
    const [working, setWorking] = useState(false);
    const click = async e => {
      if (!onClick || working) return;
      const r = onClick(e);
      if (r && typeof r.then === 'function') { setWorking(true); try { await r; } finally { setWorking(false); } }
    };
    return html`<button type=${type || 'button'} class=${cls('btn', kind && 'btn-' + kind, small && 'btn-sm', (busy || working) && 'is-busy')}
      disabled=${disabled || busy || working} title=${title} onClick=${click}>${icon ? html`<span class="btn-ico" aria-hidden="true">${icon}</span>` : null}${children}</button>`;
  };
  NL.Link = ({ to, children, title }) => html`<a class="link" href=${'#/' + to} title=${title}>${children}</a>`;

  NL.Pill = ({ tone, children, title }) => html`<span class=${cls('pill', tone && 'pill-' + tone)} title=${title}>${children}</span>`;
  NL.RunPill = ({ r }) => r ? html`<${NL.Pill} tone=${NL.RUN_TONE[r.status] || 'muted'}>${NL.RUN_TONE[r.status] === 'live' ? html`<i class="dot-live"></i>` : null}${NL.RUN_WORD[r.status] || r.status}</${NL.Pill}>` : null;
  NL.StatePill = ({ state }) => html`<${NL.Pill} tone=${state === 'killed' ? 'bad' : state === 'parked' ? 'muted' : state === 'final' ? 'ok' : 'state'}>${NL.STATE_LABEL[state] || state || '—'}</${NL.Pill}>`;
  NL.RoleDot = ({ role }) => html`<i class="role-dot" style=${{ background: NL.roleOf(role).color }} title=${NL.roleOf(role).label}></i>`;

  NL.Card = ({ children, tone, onClick, className }) => html`<div class=${cls('card', tone && 'card-' + tone, onClick && 'card-click', className)} onClick=${onClick} role=${onClick ? 'button' : null} tabIndex=${onClick ? 0 : null}
    onKeyDown=${onClick ? (e => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onClick(e))) : null}>${children}</div>`;
  NL.Section = ({ title, children, action, count, className }) => html`<section class=${cls('section', className)}>
    ${title ? html`<header class="section-head"><h3>${title}${count != null ? html` <span class="count">${count}</span>` : null}</h3>${action || null}</header>` : null}
    ${children}</section>`;
  NL.Empty = ({ icon, title, children }) => html`<div class="empty">${icon ? html`<div class="empty-ico" aria-hidden="true">${icon}</div>` : null}
    ${title ? html`<div class="empty-title">${title}</div>` : null}<div class="empty-body">${children}</div></div>`;
  NL.Spinner = () => html`<span class="spinner" aria-label="loading"></span>`;
  NL.Bar = ({ value, max, tone }) => { const p = max ? Math.max(0, Math.min(1, value / max)) : 0; return html`<span class=${cls('bar', tone && 'bar-' + tone)}><i style=${{ width: (p * 100).toFixed(1) + '%' }}></i></span>`; };
  NL.Kbd = ({ children }) => html`<kbd class="kbd">${children}</kbd>`;
  NL.Detail = ({ children }) => html`<div class="detail-line">${children}</div>`;

  /* ── fields ─────────────────────────────────────────────────────────────── */
  NL.Field = ({ label, hint, children, error }) => html`<label class=${cls('field', error && 'field-error')}><span class="field-label">${label}</span>${children}${hint ? html`<span class="field-hint">${hint}</span>` : null}${error ? html`<span class="field-err">${error}</span>` : null}</label>`;
  NL.Input = ({ value, onInput, placeholder, type, autofocus, onEnter, mono, min, max, disabled }) => {
    const ref = useRef();
    useEffect(() => { if (autofocus && ref.current) ref.current.focus(); }, []);
    return html`<input ref=${ref} class=${cls('input', mono && 'mono')} type=${type || 'text'} value=${value ?? ''} placeholder=${placeholder} min=${min} max=${max} disabled=${disabled}
      onInput=${e => onInput && onInput(e.target.value)} onKeyDown=${e => { if (e.key === 'Enter' && onEnter) { e.preventDefault(); onEnter(); } }} />`;
  };
  NL.Textarea = ({ value, onInput, placeholder, rows, autofocus, onSubmit, mono }) => {
    const ref = useRef();
    useEffect(() => { if (autofocus && ref.current) ref.current.focus(); }, []);
    return html`<textarea ref=${ref} class=${cls('input', 'textarea', mono && 'mono')} rows=${rows || 4} value=${value ?? ''} placeholder=${placeholder}
      onInput=${e => onInput && onInput(e.target.value)} onKeyDown=${e => { if (onSubmit && e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); onSubmit(); } }}></textarea>`;
  };
  NL.Select = ({ value, onChange, options, disabled }) => html`<select class="input select" value=${value} disabled=${disabled} onChange=${e => onChange(e.target.value)}>
    ${options.map(o => typeof o === 'string' ? html`<option value=${o}>${o}</option>` : html`<option value=${o.value} disabled=${o.disabled}>${o.label}</option>`)}</select>`;
  NL.Seg = ({ value, onChange, options }) => html`<div class="seg" role="radiogroup">${options.map(o => html`<button type="button" role="radio" aria-checked=${value === o.value}
    class=${cls('seg-btn', value === o.value && 'on')} onClick=${() => onChange(o.value)}>${o.label}</button>`)}</div>`;
  NL.Toggle = ({ on, onChange, label, sub }) => html`<button type="button" class=${cls('toggle-row')} role="switch" aria-checked=${!!on} onClick=${() => onChange(!on)}>
    <span class="toggle-text"><b>${label}</b>${sub ? html`<small>${sub}</small>` : null}</span><span class=${cls('toggle', on && 'on')}><i></i></span></button>`;

  NL.Tabs = ({ tabs, value, onChange }) => html`<nav class="tabs" role="tablist">${tabs.map(t => html`<button type="button" role="tab" aria-selected=${value === t.id}
    class=${cls('tab', value === t.id && 'on')} onClick=${() => onChange(t.id)}>${t.label}${t.count ? html` <span class="count">${t.count}</span>` : null}</button>`)}</nav>`;

  /* ── layers ─────────────────────────────────────────────────────────────── */
  /** A side sheet (right) — or a centered dialog. Rendered by the OverlayHost from NL.open(). */
  NL.Sheet = ({ title, sub, onClose, children, wide, footer, icon }) => html`<aside class=${cls('sheet', wide && 'sheet-wide')} role="dialog" aria-modal="true" aria-label=${typeof title === 'string' ? title : null}>
    <header class="sheet-head">${icon ? html`<span class="sheet-ico" aria-hidden="true">${icon}</span>` : null}<div class="sheet-titles"><h2>${title}</h2>${sub ? html`<div class="sheet-sub">${sub}</div>` : null}</div>
      <button class="x" aria-label="close" onClick=${onClose}>✕</button></header>
    <div class="sheet-body">${children}</div>${footer ? html`<footer class="sheet-foot">${footer}</footer>` : null}</aside>`;

  NL.ConfirmDialog = ({ title, body, ok, cancel, danger, typed, resolve, input, placeholder, detail }) => {
    const [txt, setTxt] = useState('');
    const good = typed ? txt.trim() === typed : input ? !!txt.trim() : true;
    const done = () => good && resolve(input ? txt.trim() : true);
    return html`<div class="dialog" role="alertdialog" aria-modal="true">
      <h3>${title}</h3>
      ${body ? html`<div class="dialog-body">${typeof body === 'string' ? html`<p>${body}</p>` : body}</div>` : null}
      ${detail ? html`<div class="dialog-detail">${detail}</div>` : null}
      ${typed ? html`<${NL.Field} label=${html`Type <b class="mono">${typed}</b> to confirm`}><${NL.Input} value=${txt} onInput=${setTxt} autofocus mono onEnter=${done} /></${NL.Field}>` : null}
      ${input ? html`<${NL.Field} label=${input}><${NL.Input} value=${txt} onInput=${setTxt} autofocus placeholder=${placeholder} onEnter=${done} /></${NL.Field}>` : null}
      <div class="dialog-actions"><${NL.Btn} onClick=${() => resolve(false)}>${cancel || 'Cancel'}</${NL.Btn}>
        <${NL.Btn} kind=${danger ? 'danger' : 'primary'} disabled=${!good} onClick=${done}>${ok || 'Confirm'}</${NL.Btn}></div></div>`;
  };

  NL.OverlayHost = () => {
    const list = NL.useLayers();
    if (!list.length) return null;
    return html`${list.map((l, i) => html`<div class=${cls('layer', 'layer-' + l.kind)} style=${{ zIndex: 100 + i * 2 }} key=${l.id}>
      <div class="scrim" onClick=${() => NL.close(l.id)}></div>
      <${l.Comp} ...${l.props} onClose=${() => NL.close(l.id)} layerId=${l.id} /></div>`)}`;
  };

  NL.Toasts = () => {
    const list = NL.useToasts();
    return html`<div class="toasts" role="status" aria-live="polite">${list.map(t => html`<div class=${cls('toast', 'toast-' + t.tone)} key=${t.id}>${t.msg}</div>`)}</div>`;
  };

  /* ── markdown (marked + DOMPurify + KaTeX; offline) ─────────────────────── */
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  NL.esc = esc;
  function mathHtml(src) {
    if (!window.katex) return esc(src);
    let body = src, display = false;
    if (/^\$\$/.test(src)) { body = src.slice(2, -2); display = true; }
    else if (/^\\\[/.test(src)) { body = src.slice(2, -2); display = true; }
    else if (/^\\\(/.test(src)) { body = src.slice(2, -2); }
    else if (/^\$/.test(src)) { body = src.slice(1, -1); }
    try { return window.katex.renderToString(body, { displayMode: display, throwOnError: false }); } catch (e) { return esc(src); }
  }
  function assetUrl(sel, src) {
    if (!sel || sel.rel == null || /^(https?:|data:|\/)/i.test(src)) return null;
    const dir = sel.rel.split('/').slice(0, -1);
    for (const seg of src.split('/')) { if (seg === '' || seg === '.') continue; if (seg === '..') dir.pop(); else dir.push(seg); }
    return `/api/libfile?${NL.qs({ scope: sel.scope, slug: sel.slug || '', rel: dir.join('/') })}`;
  }
  /** markdown → sanitized HTML (+ front-matter chips). Math is stashed before marked so `$a_i$` survives. */
  NL.mdToHtml = (mdText, sel) => {
    let text = String(mdText || '').replace(/^﻿/, '');
    let front = '';
    const fm = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(text);
    if (fm) {
      text = text.slice(fm[0].length);
      const chips = fm[1].split(/\r?\n/).map(ln => /^([A-Za-z_][\w .-]*):\s*(.*)$/.exec(ln.trim())).filter(Boolean)
        .map(m => `<span class="fm-chip"><b>${esc(m[1])}</b>${m[2] ? ' ' + esc(m[2]) : ''}</span>`);
      if (chips.length) front = `<div class="md-frontmatter">${chips.join('')}</div>`;
    }
    if (!(window.marked && window.DOMPurify)) return front + `<pre class="plain">${esc(text)}</pre>`;
    const stash = [];
    const put = m => { stash.push(m); return `${stash.length - 1}`; };
    text = text.split(/(```[\s\S]*?```|~~~[\s\S]*?~~~)/).map((seg, i) => i % 2 ? seg : seg
      .replace(/\$\$[\s\S]+?\$\$/g, put).replace(/\\\[[\s\S]+?\\\]/g, put).replace(/\\\([\s\S]+?\\\)/g, put)
      .replace(/\$(?!\s)((?:\\.|[^$\\\n])+?)(?<![\s\\])\$(?!\d)/g, put)).join('');
    let out;
    try { out = window.marked.parse(text, { gfm: true, breaks: false, async: false }); } catch (e) { return front + `<pre class="plain">${esc(mdText)}</pre>`; }
    out = window.DOMPurify.sanitize(out).replace(/(\d+)/g, (m, i) => mathHtml(stash[+i]));
    if (sel) out = out.replace(/<img([^>]*?)src="([^"]+)"/g, (m, a, src) => { const u = assetUrl(sel, src.replace(/&amp;/g, '&')); return `<img${a}loading="lazy" src="${u ? esc(u) : src}"`; });
    return front + out;
  };
  NL.Markdown = ({ text, sel, className }) => {
    const ref = useRef();
    const markup = useMemo(() => NL.mdToHtml(text, sel), [text, sel && sel.rel, sel && sel.slug]);
    useEffect(() => {
      const host = ref.current; if (!host) return;
      host.querySelectorAll('a[href]').forEach(a => {
        const href = a.getAttribute('href') || '';
        if (/^https?:/i.test(href)) { a.target = '_blank'; a.rel = 'noopener'; }
        else if (!href.startsWith('#')) a.onclick = ev => { ev.preventDefault(); NL.toast('A link to another file — open it from the Library shelf'); };
      });
    }, [markup]);
    return html`<div ref=${ref} class=${cls('md', className)} dangerouslySetInnerHTML=${{ __html: markup }}></div>`;
  };

  /* ── editor deep links (the dashboard is local: vscode://file/… etc.) ───── */
  NL.editorUri = (abs, line) => {
    const s = NL.getState(); const ed = (s && s.editor) || 'vscode';
    if (!abs || ed === 'none') return null;
    const scheme = /^[a-z][a-z0-9+.-]*$/.test(ed) ? ed : 'vscode';
    let p = String(abs).replace(/\\/g, '/'); if (!p.startsWith('/')) p = '/' + p;
    return `${scheme}://file${p}${line ? ':' + line : ''}`;
  };
  NL.EditorLink = ({ path, children }) => { const u = NL.editorUri(path); return u ? html`<a class="link small" href=${u}>${children || 'open in editor ↗'}</a>` : null; };
})();
