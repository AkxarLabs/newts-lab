/* Newts' Lab — the Library: every document the lab writes (the lab layer, then one shelf per study
   with its project repo's ledgers), rendered with real typography, tables, code and KaTeX math. The
   same reader is reused by the Study page's Documents tab. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, useMemo, cls } = NL;

  const cache = { tree: null, at: 0, wait: null };
  NL.loadLibTree = async (force) => {
    if (!force && cache.tree && Date.now() - cache.at < 20000) return cache.tree;
    if (cache.wait) return cache.wait;
    cache.wait = NL.get('/api/library').then(t => { cache.wait = null; if (t && t.ok) { cache.tree = t; cache.at = Date.now(); } return cache.tree || t; });
    return cache.wait;
  };
  NL.useLibTree = () => {
    const [t, setT] = useState(cache.tree);
    useEffect(() => { let on = true; NL.loadLibTree().then(x => on && setT(x)); return () => { on = false; }; }, []);
    return t;
  };
  /** a readable name from any file name: "EXPERIMENT_LOG.md" → "Experiment log", "lit-review.md" → "Lit review",
   *  "2026-10-01-weekly.md" → "Weekly · 2026-10-01" (generic: no list of known files) */
  NL.docLabel = name => {
    const base = String(name || '').split('/').pop().replace(/\.[A-Za-z0-9]+$/, '');
    const m = base.match(/^(\d{4}-\d{2}-\d{2}(?:[T_-]\d{2}[-:]?\d{2}(?:[-:]?\d{2})?)?)(?:[-_ ]+(.*))?$/);
    const date = m ? m[1] : '', rest = m ? (m[2] || '') : base;
    let words = rest.replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').trim();
    if (words && words === words.toUpperCase()) words = words.toLowerCase();
    words = words ? words[0].toUpperCase() + words.slice(1) : '';
    return words && date ? `${words} · ${date}` : words || date || base;
  };
  /** a shelf entry: its readable name, with the file name as small secondary text */
  NL.DocName = ({ d }) => {
    const file = String(d.title || d.rel || '').split('/').pop(), label = NL.docLabel(file);
    return html`<span class="doc-name">${label}${label !== file ? html`<small class="doc-file mono">${file}</small>` : null}</span>`;
  };
  const docHref = d => `#/library/${encodeURIComponent(d.scope)}/${encodeURIComponent(d.slug || '_')}/${d.rel.split('/').map(encodeURIComponent).join('/')}`;
  NL.openDoc = (scope, slug, rel) => { location.hash = docHref({ scope, slug, rel }); };

  NL.DocReader = ({ scope, slug, rel, bare, fallback }) => {
    const [d, setD] = useState(null);
    useEffect(() => { let on = true; setD(null); NL.api('/api/libdoc', { scope, slug: slug || null, rel }).then(x => on && setD(x)); return () => { on = false; }; }, [scope, slug, rel]);
    if (!d) return html`<div class="reader"><${NL.Spinner} /></div>`;
    if (!d.ok) return html`<div class="reader">${fallback || html`<${NL.Empty} icon="📄">${d.error}</${NL.Empty}>`}</div>`;
    return html`<article class=${cls('reader', bare && 'bare')}>
      ${bare ? null : html`<header class="reader-head"><div class="crumbs">${scope === 'lab' ? 'The Lab' : slug}${scope === 'project' ? ' · project repo' : ''} › <span class="mono">${rel}</span></div>
        <div class="row">${d.mtime ? html`<span class="muted small">updated ${new Date(d.mtime * 1000).toLocaleString()}</span>` : null}<${NL.EditorLink} path=${d.path} /></div></header>`}
      ${d.format === 'markdown' ? html`<${NL.Markdown} text=${d.text || '(empty)'} sel=${{ scope, slug, rel }} className="md-doc" />` : html`<pre class="plain">${d.text || '(empty)'}</pre>`}
      ${d.clipped ? html`<p class="muted small">… clipped — open it in your editor for the rest.</p>` : null}</article>`;
  };

  const Shelf = ({ groups, sel, filter }) => {
    const q = (filter || '').toLowerCase();
    return html`<nav class="shelf">${groups.map(g => {
      const secs = g.sections.map(sec => ({ ...sec, docs: sec.docs.filter(d => !q || (NL.docLabel(d.title) + ' ' + d.title + ' ' + d.rel + ' ' + g.title).toLowerCase().includes(q)) })).filter(sec => sec.docs.length);
      if (!secs.length) return null;
      const open = !q && sel ? (sel.slug || null) === (g.slug || null) || (g.kind === 'lab' && sel.scope === 'lab') : true;
      return html`<details class="shelf-group" open=${open || !!q}><summary><span class="clip">${g.title}</span>${g.state ? html`<${NL.StatePill} state=${g.state} />` : null}</summary>
        ${secs.map(sec => html`<div class="shelf-sec"><div class="shelf-sec-h">${sec.icon || ''} ${sec.title}</div>
          ${sec.docs.map(d => html`<a class=${cls('shelf-doc', sel && sel.scope === d.scope && (sel.slug || null) === (d.slug || null) && sel.rel === d.rel && 'on')} href=${docHref(d)}><${NL.DocName} d=${d} /></a>`)}</div>`)}</details>`;
    })}</nav>`;
  };

  NL.LibraryPage = ({ args }) => {
    const tree = NL.useLibTree();
    const [filter, setFilter] = useState('');
    const sel = args && args.length >= 3 ? { scope: args[0], slug: args[1] === '_' ? null : args[1], rel: args.slice(2).join('/') } : null;
    const groups = (tree && tree.groups) || [];
    return html`<div class="page page-split">
      <aside class="split-left"><div class="split-head"><h1>Library</h1>
        <p class="muted small">Everything the lab writes, study by study. What agents picked out for you is also under <a class="link" href="#/artifacts">Results</a>.</p>
        <input class="input search" placeholder="Find a document…" value=${filter} onInput=${e => setFilter(e.target.value)} /></div>
        ${tree ? html`<${Shelf} groups=${groups} sel=${sel} filter=${filter} />` : html`<${NL.Spinner} />`}
        ${tree && filter && !groups.some(g => (g.sections || []).some(sec => sec.docs.some(d => `${g.title} ${NL.docLabel(d.title)} ${d.title} ${d.rel}`.toLowerCase().includes(filter.toLowerCase())))) ? html`<div class="muted small pad">No documents match “${filter}”.</div>` : null}
        <div class="shelf-foot"><button class="link small" onClick=${() => NL.open(NL.DocEditSheet, { which: 'open-questions' })}>Add an open question for the lab</button></div></aside>
      <main class="split-right">${sel ? html`<${NL.DocReader} ...${sel} />` : html`<${NL.Empty} icon="📖" title="Pick a document">Ideation worksheets, proposals, critiques, experiment logs, papers — everything the lab writes, rendered here.</${NL.Empty}>`}</main>
    </div>`;
  };

  /* PI-authored documents, edited in place (lab/SYSTEM.md, lab/knowledge/OPEN-QUESTIONS.md) */
  NL.DocEditSheet = ({ which, onClose }) => {
    const [d, setD] = useState(null);
    const [text, setText] = useState('');
    const [preview, setPreview] = useState(false);
    useEffect(() => { NL.get(`/api/doc?${NL.qs({ which })}`).then(x => { setD(x); setText(x.text || ''); }); }, [which]);
    const save = async () => { const r = await NL.act('/api/doc/save', { doc: which, text }, 'Saved'); if (r.ok) { cache.at = 0; onClose(); } };
    const title = which === 'system' ? 'This machine (SYSTEM.md)' : 'Open questions';
    const sub = which === 'system' ? 'Agents read this before running anything: hardware, GPUs, quirks, what not to touch.' : '/ideate reads these first — add the questions you want the lab to chase.';
    return html`<${NL.Sheet} wide title=${title} sub=${sub} onClose=${onClose} footer=${html`<div class="row"><${NL.Seg} value=${preview ? 'p' : 'e'} onChange=${v => setPreview(v === 'p')} options=${[{ value: 'e', label: 'Edit' }, { value: 'p', label: 'Preview' }]} /><span class="grow"></span>
      <${NL.Btn} onClick=${onClose}>Cancel</${NL.Btn}><${NL.Btn} kind="primary" onClick=${save} disabled=${!d}>Save</${NL.Btn}></div>`}>
      ${!d ? html`<${NL.Spinner} />` : preview ? html`<${NL.Markdown} text=${text} className="md-doc" />` : html`<textarea class="input textarea mono editor" value=${text} onInput=${e => setText(e.target.value)}></textarea>`}
    </${NL.Sheet}>`;
  };
})();
