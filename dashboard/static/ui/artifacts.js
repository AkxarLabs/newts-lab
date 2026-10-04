/* Newts' Lab — Artifacts: what agents made for you to look at (tools/artifact.py publish) — plans, reports,
   figures, tables, HTML pages — each rendered in place, with the agent's question when it asked one and your
   reply, which goes back to the run that made it. Also "What it wrote" on a run's sheet: every file the run's
   own transcript says it wrote, openable here (Markdown rendered).

   An HTML artifact is shown in a sandboxed frame (and served with a CSP sandbox), so a page an agent wrote can
   never act as the dashboard. */
(function () {
  'use strict';
  const NL = window.NL;
  const { html, useState, useEffect, cls } = NL;

  const KIND = { md: ['Document', '¶'], html: ['Page', '◫'], image: ['Figure', '◩'], pdf: ['PDF', '▤'], table: ['Table', '▦'], text: ['Text', '≡'], choice: ['Question', '?'] };
  const fileUrl = a => `/api/artifact/file?${NL.qs({ id: a.id })}`;
  NL.artifactsOf = s => (s && s.artifacts) || [];
  NL.artifactsUnseen = s => NL.artifactsOf(s).filter(a => !a.seen && !a.answered);
  NL.artifactsAsking = s => NL.artifactsOf(s).filter(a => a.question && !a.answered);

  const fetchOne = async id => (NL.DEMO && NL.demoArtifact) ? NL.demoArtifact(id) : NL.get(`/api/artifact?${NL.qs({ id })}`);
  const markSeen = ids => { if (ids.length && !NL.DEMO) NL.api('/api/artifact/seen', { ids }); };

  /* the content, by kind */
  const Body = ({ a, d }) => {
    if (a.kind === 'md') return html`<${NL.Markdown} text=${d.text || '(empty)'} className="md-doc" />`;
    if (a.kind === 'text') return html`<pre class="plain">${d.text || '(empty)'}</pre>`;
    if (a.kind === 'image') return html`<figure class="art-fig"><img src=${NL.DEMO && d.src ? d.src : fileUrl(a)} alt=${a.title} /></figure>`;
    if (a.kind === 'pdf') return html`<iframe class="art-frame tall" src=${fileUrl(a)} title=${a.title}></iframe>`;
    if (a.kind === 'html') return html`<iframe class="art-frame" sandbox="allow-scripts" src=${NL.DEMO ? undefined : fileUrl(a)} srcdoc=${NL.DEMO ? d.html || '' : undefined} title=${a.title}></iframe>`;
    if (a.kind === 'table') {
      const rows = (d.table && d.table.rows) || [];
      if (!rows.length) return html`<div class="muted">An empty table.</div>`;
      return html`<div class="art-table"><table><thead><tr>${rows[0].map(c => html`<th>${c}</th>`)}</tr></thead>
        <tbody>${rows.slice(1).map(r => html`<tr>${r.map(c => html`<td>${c}</td>`)}</tr>`)}</tbody></table>
        ${d.table.more ? html`<div class="muted small">… and ${d.table.more} more rows</div>` : null}</div>`;
    }
    return null;
  };

  /* the agent's question, and your answer (it goes back to the run that asked) */
  const Reply = ({ a }) => {
    const [text, setText] = useState('');
    const [busy, setBusy] = useState(false);
    const [local, setLocal] = useState(null);
    const r = a.reply || local;
    if (r) return html`<div class="art-replied"><b>You replied</b> ${r.choice ? html`<span class="pill pill-ok">${r.choice}</span>` : null} ${r.text ? html`<span>${r.text}</span>` : null}
      <small class="muted">${NL.ago(r.ts)}${r.delivered ? ' · went to ' + r.delivered : r.delivered_error ? ' · not delivered: ' + r.delivered_error : ''}</small></div>`;
    const send = async (choice) => {
      if (!choice && !text.trim()) return;
      setBusy(true);
      const x = NL.DEMO && NL.demoReply ? NL.demoReply(a.id, choice || null, text.trim())
        : await NL.act('/api/artifact/reply', { id: a.id, choice: choice || null, text: text.trim() }, 'Sent to the agent');
      setBusy(false); if (x.ok) { setText(''); setLocal(x.reply); }
    };
    return html`<div class="art-ask">
      ${a.question ? html`<div class="art-q"><span class="art-q-ico">?</span><b>${a.question}</b></div>` : null}
      ${(a.choices || []).length ? html`<div class="art-choices">${a.choices.map(c => html`<${NL.Btn} disabled=${busy} onClick=${() => send(c)}>${c}</${NL.Btn}>`)}</div>` : null}
      <div class="reply"><${NL.Textarea} rows="2" value=${text} onInput=${setText} onSubmit=${() => send(null)}
        placeholder=${a.question ? ((a.choices || []).length ? 'Or answer in your own words (Ctrl+Enter)' : 'Your answer (Ctrl+Enter)') : 'A note back to the agent about this (Ctrl+Enter)'} />
        <${NL.Btn} kind="primary" disabled=${busy || !text.trim()} onClick=${() => send(null)}>Send</${NL.Btn}></div></div>`;
  };

  /** one artifact, whole: where it came from, what it is, what it asks */
  const Viewer = ({ id, onLoaded }) => {
    const [d, setD] = useState(null);
    const s = NL.useLab();
    const stamp = (NL.artifactsOf(s).find(x => x.id === id) || {}).answered;
    useEffect(() => { let on = true; setD(null); fetchOne(id).then(x => { if (on) { setD(x); if (x && x.ok) { markSeen([id]); onLoaded && onLoaded(x.artifact); } } }); return () => { on = false; }; }, [id, stamp]);
    if (!d) return html`<${NL.Spinner} />`;
    if (!d.ok) return html`<${NL.Empty} icon="❏">${d.error || 'It could not be read.'}</${NL.Empty}>`;
    const a = d.artifact, it = a.study && NL.item(s, a.study);
    return html`<article class="artifact">
      <header class="art-head"><div class="kicker">${(KIND[a.kind] || ['Artifact'])[0]} · ${NL.ago(a.created)}</div><h2>${a.title}</h2>
        <div class="row-wrap">${it ? html`<a class="chip" href=${'#/study/' + it.id}>${NL.clip(it.title || it.id, 40)}</a>` : a.study ? html`<span class="chip">${a.study}</span>` : html`<span class="chip">the lab</span>`}
          ${a.run_id ? html`<button type="button" class="chip" onClick=${() => NL.openRun(a.run_id)}>from ${a.skill ? '/' + a.skill : 'a run'} ↗</button>` : null}
          ${a.source_path ? html`<${NL.EditorLink} path=${a.source_path}>the original ↗</${NL.EditorLink}>` : null}
          ${a.file && !NL.DEMO ? html`<a class="link small" href=${fileUrl(a)} target="_blank" rel="noopener">open alone ↗</a>` : null}</div></header>
      ${a.note ? html`<p class="art-note">${a.note}</p>` : null}
      ${a.kind !== 'choice' ? html`<div class=${cls('art-body', 'k-' + a.kind)}><${Body} a=${a} d=${d} /></div>` : null}
      <${Reply} a=${a} />
    </article>`;
  };

  NL.ArtifactSheet = ({ id, onClose }) => {
    const [a, setA] = useState(null);
    return html`<${NL.Sheet} title=${a ? a.title : 'Artifact'} sub=${a ? (KIND[a.kind] || ['Artifact'])[0] : ''} wide onClose=${onClose}>
      <${Viewer} id=${id} onLoaded=${setA} />
      <div class="row end"><a class="link small" href=${'#/artifacts/' + id} onClick=${onClose}>All artifacts →</a></div></${NL.Sheet}>`;
  };
  NL.openArtifact = id => { if (id) NL.open(NL.ArtifactSheet, { id }, { key: 'artifact:' + id }); };

  /* ── the page: a list on the left (asking first, then new, then the rest), the artifact on the right ── */
  const FILTERS = [['all', 'All'], ['asking', 'Asking you'], ['new', 'New'], ['answered', 'Answered']];
  const Row = ({ a, on, s }) => {
    const it = a.study && NL.item(s, a.study);
    const state = a.question && !a.answered ? ['asks', 'warn'] : !a.seen ? ['new', 'info'] : a.answered ? ['answered', 'ok'] : null;
    return html`<a class=${cls('art-row', on && 'on', !a.seen && 'unseen')} href=${'#/artifacts/' + a.id}>
      <span class="art-ico" aria-hidden="true">${(KIND[a.kind] || ['', '•'])[1]}</span>
      <span class="grow clip"><b>${a.title}</b><small class="muted">${it ? NL.clip(it.title || it.id, 26) : a.study || 'the lab'} · ${a.skill ? '/' + a.skill + ' · ' : ''}${NL.ago(a.created)}</small></span>
      ${state ? html`<${NL.Pill} tone=${state[1]}>${state[0]}</${NL.Pill}>` : null}</a>`;
  };
  NL.ArtifactsPage = ({ args, query }) => {
    const s = NL.useLab();
    const [f, setF] = useState((query && query.f) || 'all');
    const [study, setStudy] = useState((query && query.study) || '');
    const all = NL.artifactsOf(s);
    const rank = a => (a.question && !a.answered ? 0 : !a.seen ? 1 : 2);
    const list = all.filter(a => (!study || a.study === study) && (f === 'all' || (f === 'asking' && a.question && !a.answered) || (f === 'new' && !a.seen) || (f === 'answered' && a.answered)))
      .sort((a, b) => rank(a) - rank(b) || String(b.created).localeCompare(String(a.created)));
    const sel = (args && args[0]) || null;
    const studies = [...new Set(all.map(a => a.study).filter(Boolean))];
    return html`<div class="page page-split">
      <aside class="split-left"><div class="split-head"><h1>Artifacts</h1>
        <p class="muted small">What agents made for you to look at — and the questions they left with it. Your reply goes back to the agent.</p></div>
        <div class="art-filters">${FILTERS.map(([v, t]) => html`<button type="button" class=${cls('lens', f === v && 'on')} onClick=${() => setF(v)}>${t}${v === 'asking' && NL.artifactsAsking(s).length ? ' · ' + NL.artifactsAsking(s).length : ''}</button>`)}</div>
        ${studies.length > 1 ? html`<${NL.Select} value=${study} onChange=${setStudy} options=${[{ value: '', label: 'Every study' }, ...studies.map(x => ({ value: x, label: (NL.item(s, x) || {}).title || x }))]} />` : null}
        <nav class="art-list">${list.length ? list.map(a => html`<${Row} key=${a.id} a=${a} on=${a.id === sel} s=${s} />`)
          : html`<div class="muted small pad">${all.length ? 'Nothing here with this filter.' : 'Nothing yet.'}</div>`}</nav></aside>
      <main class="split-right">${sel ? html`<${Viewer} key=${sel} id=${sel} />` : html`<${NL.Empty} icon="❏" title=${all.length ? 'Pick one' : 'Nothing to look at yet'}>
        When an agent wants you to see something — a plan, results, a figure, a page it built — it publishes it here
        (<span class="mono">tools/artifact.py publish</span>), and a sheet is pinned in its room on Home.</${NL.Empty}>`}</main>
    </div>`;
  };

  /* ── a run's sheet: what it wrote ─────────────────────────────────────────────────────────────── */
  NL.FileSheet = ({ run, f, onClose }) => {
    const [d, setD] = useState(null);
    useEffect(() => { if (f.kind === 'md' || f.kind === 'text') NL.get(`/api/run/file?${NL.qs({ run_id: run, path: f.path })}`).then(setD); }, [f.path]);
    const raw = `/api/run/rawfile?${NL.qs({ run_id: run, path: f.path })}`;
    return html`<${NL.Sheet} title=${f.name} sub=${html`<span class="mono small">${f.path}</span>`} wide onClose=${onClose}>
      <div class="row end"><${NL.EditorLink} path=${f.path} /></div>
      ${f.kind === 'image' ? html`<figure class="art-fig"><img src=${raw} alt=${f.name} /></figure>`
        : f.kind === 'pdf' ? html`<iframe class="art-frame tall" src=${raw} title=${f.name}></iframe>`
        : !d ? html`<${NL.Spinner} />` : !d.ok ? html`<${NL.Empty}>${d.error}</${NL.Empty}>`
        : d.kind === 'md' ? html`<${NL.Markdown} text=${d.text || '(empty)'} className="md-doc" />` : html`<pre class="plain">${d.text}</pre>`}
    </${NL.Sheet}>`;
  };
  NL.RunFiles = ({ r }) => {
    const [files, setFiles] = useState(null);
    const n = r.n_actions || 0;
    useEffect(() => { if (NL.DEMO) { setFiles(NL.demoRunFiles ? NL.demoRunFiles(r) : []); return; } NL.get(`/api/run/files?${NL.qs({ run_id: r.run_id })}`).then(x => setFiles(x && x.ok ? x.files : [])); }, [r.run_id, Math.floor(n / 5), r.status]);
    const arts = NL.artifactsOf(NL.useLab()).filter(a => a.run_id === r.run_id);
    if (!(files && files.length) && !arts.length) return null;
    const ico = k => ({ md: '¶', text: '≡', image: '◩', pdf: '▤' }[k] || '·');
    return html`<details class="runfiles" open=${arts.length > 0}><summary>${arts.length ? NL.plural(arts.length, 'artifact') + ' for you' + ((files || []).length ? ' · ' : '') : ''}${(files || []).length ? 'what it wrote (' + files.length + ')' : ''}</summary>
      ${arts.map(a => html`<button type="button" class="runfile art" onClick=${() => NL.openArtifact(a.id)}><span>${(KIND[a.kind] || ['', '•'])[1]}</span><b class="grow clip">${a.title}</b>${a.question && !a.answered ? html`<${NL.Pill} tone="warn">asks you</${NL.Pill}>` : null}</button>`)}
      ${(files || []).map(f => html`<button type="button" class="runfile" disabled=${!f.exists || f.kind === 'other'} onClick=${() => NL.open(NL.FileSheet, { run: r.run_id, f })}>
        <span>${ico(f.kind)}</span><span class="grow clip mono small">${f.name}</span><span class="muted small clip">${f.exists ? f.path.replace(/\\/g, '/').split('/').slice(-3, -1).join('/') : 'deleted since'}</span></button>`)}</details>`;
  };
})();
