// Brain Dashboard frontend v0.5.0
const ICONS = {
  ollama: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3c-2 0-3 2-3 4 0 1 0 2 1 3-1 1-1 2-1 3 0 3 2 5 5 5h6c3 0 5-2 5-5 0-1 0-2-1-3 1-1 1-2 1-3 0-2-1-4-3-4-1 0-2 0-3 1-1-1-2-1-3-1s-2 0-3 1c-1-1-2-1-3-1z"/><circle cx="9" cy="11" r="1" fill="currentColor"/><circle cx="15" cy="11" r="1" fill="currentColor"/></svg>',
  gpu:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="12" rx="2"/><circle cx="9" cy="12" r="2"/><circle cx="16" cy="12" r="2"/><path d="M3 10h2M3 14h2M19 10h2M19 14h2"/></svg>',
  cpu:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="1"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"/></svg>',
  vault:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h12l4 4v12H4z"/><path d="M14 4v4h6"/><path d="M8 13h8M8 17h5"/></svg>',
  db:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>',
  graph:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="5" cy="7" r="2"/><circle cx="19" cy="7" r="2"/><circle cx="12" cy="17" r="2"/><circle cx="5" cy="17" r="2"/><path d="M7 7h10M6 9l5 7M18 9l-5 7M7 17h3"/></svg>',
  book:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4v16h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v14"/></svg>',
  claude: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M5.3 18l5.5-13h2.4l5.5 13h-2.6l-1.2-2.9H9l-1.2 2.9H5.3zm4.4-4.9h4.5L12 7.8l-2.3 5.3z"/></svg>',
};

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
const OLLAMA = 'http://127.0.0.1:11434';

// ============================================================================
// TAB ROUTING
// ============================================================================
const VIEW_HANDLERS = {
  brain:    () => { renderVault(); renderDedup(); renderGraph(); renderLibrary(); renderUserProfile(); },
  pipeline: () => { renderTranscripts(); renderCodeIndex(); },
  tools:    () => { renderAgents(); renderSkills(); renderCliSkills(); renderSchedule(); renderMCP(); renderLogs(); renderBackups(); renderIdleGuard(); },
  options:  () => renderOptions(),
  instrukcja: () => initInstrukcjaScrollSpy(),
};
function showView(name) {
  $$('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + name));
  $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === name));
  (VIEW_HANDLERS[name] || (() => {}))();
}
$$('.tab').forEach(t => t.onclick = () => showView(t.dataset.view));

// ============================================================================
// HELPERS
// ============================================================================
function fmtUptime(s) {
  if (!s) return '-';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60), sec = s%60;
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
}
function fmtTime() { return new Date().toLocaleTimeString('en-GB'); }
function fmtAgo(mtime) {
  const d = Date.now()/1000 - mtime;
  if (d < 60) return Math.floor(d)+'s';
  if (d < 3600) return Math.floor(d/60)+'m';
  if (d < 86400) return Math.floor(d/3600)+'h';
  return Math.floor(d/86400)+'d';
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

// ============================================================================
// DASHBOARD
// ============================================================================
function tile(opts) {
  const el = document.createElement('div');
  el.className = 'tile' + (opts.url ? '' : ' no-link') + (opts.wide ? ' wide' : '');
  if (opts.url) el.onclick = () => {
    if (opts.url.startsWith('http')) window.open(opts.url, '_blank');
    else location.href = opts.url;
  };
  el.innerHTML = `
    <div class="tile-head">
      <div class="tile-title-row">
        <span class="tile-icon">${ICONS[opts.icon] || ICONS.db}</span>
        <span class="tile-title">${opts.title}</span>
      </div>
      <div class="status-dot ${opts.status || 'idle'}"></div>
    </div>
    ${opts.body}
  `;
  return el;
}

function bar(label, used, total, unit, warnAt=0.85) {
  const pct = total > 0 ? Math.min(100, (used/total)*100) : 0;
  const cls = pct/100 >= warnAt ? 'warn' : '';
  return `<div class="bar">
    <div class="bar-label"><span>${label}</span><span>${used}/${total} ${unit}</span></div>
    <div class="bar-track"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div>
  </div>`;
}

let lastStatus = null;

async function refresh() {
  let data;
  try {
    const r = await fetch('/api/status');
    data = await r.json();
    lastStatus = data;
  } catch (e) {
    $('#last-update').textContent = 'unreachable';
    return;
  }

  // Build new grid OFF-DOM, then atomic swap. Eliminates flicker that occurred
  // when innerHTML='' showed an empty frame between refresh cycles.
  const oldGrid = $('#grid');
  const grid = document.createElement('div');
  grid.id = 'grid';
  grid.className = oldGrid.className;
  $('#meta-model').textContent = activeModel() || data.config.model || '-';
  $('#meta-uptime').textContent = fmtUptime(data.system.uptime_sec);
  $('#meta-time').textContent = fmtTime();

  // OLLAMA (with model picker + pull form + VRAM monitor)
  const o = data.ollama;
  const active = activeModel();
  const modelsOpts = o.models.map(m => `<option value="${m.name}" ${m.name===active?'selected':''}>${m.name} (${m.size_gb}G)</option>`).join('');
  const loaded = o.loaded || [];
  const vramUsed = o.vram_used_gb || 0;

  let loadedHtml = '';
  if (loaded.length) {
    loadedHtml = `<div class="oc-loaded">
      <div class="oc-loaded-head">
        <span>IN VRAM · ${vramUsed} GB</span>
        <button id="oc-unload" title="unload all from VRAM">UNLOAD</button>
      </div>
      ${loaded.map(m => `<div class="oc-loaded-row">
        <span class="oc-loaded-name">${escapeHtml(m.name)}</span>
        <span class="oc-loaded-meta">${m.size_vram_gb}G · expires ${m.expires_at ? new Date(m.expires_at).toLocaleTimeString('en-GB').slice(0,5) : '∞'}</span>
      </div>`).join('')}
    </div>`;
  } else if (o.running) {
    loadedHtml = `<div class="oc-loaded-empty">no models in VRAM (idle)</div>`;
  }

  const ollamaTile = tile({
    icon: 'ollama', title: 'OLLAMA',
    status: o.running ? 'ok' : 'err',
    body: `<div class="tile-main">${o.count} <span style="font-size:14px;color:var(--text-dim)">models</span></div>
           <div class="tile-sub">${o.running ? 'running' : 'stopped'} · ${o.url.replace('http://','')}</div>
           ${loadedHtml}
           <div class="ollama-controls">
             <div class="oc-row">
               <select id="oc-active" title="active model for chat">${modelsOpts || '<option>no models</option>'}</select>
             </div>
             <div class="oc-row">
               <input id="oc-pull-name" placeholder="pull model… eg qwen2.5-coder:7b">
               <button id="oc-pull-btn">PULL</button>
             </div>
             <div id="oc-progress" class="oc-progress"></div>
           </div>`,
  });
  grid.appendChild(ollamaTile);
  const sel = ollamaTile.querySelector('#oc-active');
  if (sel) sel.onchange = () => { localStorage.setItem('brain.activeModel', sel.value); $('#meta-model').textContent = sel.value; syncChatModel(); };
  const pullBtn = ollamaTile.querySelector('#oc-pull-btn');
  const pullInput = ollamaTile.querySelector('#oc-pull-name');
  if (pullBtn) pullBtn.onclick = () => doPull(pullInput.value.trim(), ollamaTile.querySelector('#oc-progress'));
  if (pullInput) pullInput.addEventListener('keypress', e => { if (e.key === 'Enter') pullBtn.click(); });
  const unloadBtn = ollamaTile.querySelector('#oc-unload');
  if (unloadBtn) unloadBtn.onclick = async (e) => {
    e.stopPropagation();
    unloadBtn.textContent = '...'; unloadBtn.disabled = true;
    try {
      const r = await fetch('/api/ollama/unload', {method: 'POST'});
      const d = await r.json();
      unloadBtn.textContent = `OK -${d.count||0}`;
      setTimeout(refresh, 600);
    } catch (e) {
      unloadBtn.textContent = 'ERR';
    }
    setTimeout(() => { unloadBtn.textContent = 'UNLOAD'; unloadBtn.disabled = false; }, 1500);
  };

  // GPU — only show real metrics available from current telemetry source
  const g = data.gpu;
  const hasTemp = (g.telemetry === 'rocm-smi' || g.telemetry === 'nvidia-smi') && g.temp_c > 0;
  grid.appendChild(tile({
    icon: 'gpu', title: 'GPU', wide: true,
    status: g.available ? 'ok' : 'warn',
    body: g.available ? `
      <div class="tile-main" style="font-size:18px">${g.name || g.vendor.toUpperCase()}</div>
      ${bar('VRAM', g.vram_used_mb, g.vram_total_mb, 'MB')}
      ${bar('UTIL', Math.round(g.util_pct), 100, '%', 0.9)}
      ${hasTemp ? bar('TEMP', Math.round(g.temp_c), 100, 'C', 0.85) : ''}
      <div class="tile-foot"><span>${g.vendor}</span><span>${g.telemetry}</span></div>
    ` : `
      <div class="tile-main" style="font-size:18px">${g.name || g.vendor.toUpperCase() || 'NO GPU'}</div>
      <div class="tile-sub">no live telemetry</div>
      <div class="tile-foot"><span>${g.vendor}</span><span>${g.vram_total_mb} MB</span></div>
    `,
  }));

  // SYSTEM
  const s = data.system;
  const brainCpu = s.brain_cpu_pct != null ? s.brain_cpu_pct : 0;
  const brainRam = s.brain_ram_mb != null ? s.brain_ram_mb : 0;
  const brainShare = `<div class="tile-foot" style="border-top:1px solid var(--panel-border); padding-top:6px; margin-top:6px">
    <span title="ile CPU/RAM zużywa Brain (dashboard + ollama + tray + MCP)">brain: <b style="color:var(--cyan)">${brainCpu}%</b> CPU · <b style="color:var(--cyan)">${brainRam}</b> MB</span>
    <span style="color:var(--text-dim);font-size:10px">reszta to twoje apki</span>
  </div>`;
  grid.appendChild(tile({
    icon: 'cpu', title: 'SYSTEM', status: 'ok',
    body: `
      ${bar('CPU',  Math.round(s.cpu_pct), 100, '%')}
      ${bar('RAM',  s.ram_used_gb, s.ram_total_gb, 'GB')}
      ${bar('DISK', s.disk_used_gb, s.disk_total_gb, 'GB')}
      ${brainShare}
      <div class="tile-foot"><span>uptime</span><span>${fmtUptime(s.uptime_sec)}</span></div>
    `,
  }));

  // VAULT
  const v = data.vault;
  grid.appendChild(tile({
    icon: 'vault', title: 'VAULT',
    status: v.notes > 0 ? 'ok' : 'idle',
    url: '#',  // we'll override
    body: `<div class="tile-main">${v.notes} <span style="font-size:14px;color:var(--text-dim)">notes</span></div>
           <div class="tile-sub">${v.size_kb} KB</div>
           <div class="tile-foot"><span>obsidian</span><span>see BRAIN tab</span></div>`,
  }));
  // override click → BRAIN tab
  grid.lastElementChild.onclick = () => showView('brain');

  // VECTOR DB
  const vd = data.vectordb;
  grid.appendChild(tile({
    icon: 'db', title: 'VECTOR DB',
    status: vd.files > 0 ? 'ok' : 'idle',
    body: `<div class="tile-main">${vd.files} <span style="font-size:14px;color:var(--text-dim)">indexes</span></div>
           <div class="tile-sub">${vd.size_mb} MB</div>
           <div class="tile-foot"><span>sqlite-vec</span><span>pending</span></div>`,
  }));

  // EMBEDDINGS
  const embeds = data.ollama.embed_models || [];
  grid.appendChild(tile({
    icon: 'db', title: 'EMBEDDINGS',
    status: embeds.length ? 'ok' : 'idle',
    body: `<div class="tile-main">${embeds.length} <span style="font-size:14px;color:var(--text-dim)">models</span></div>
           <div class="tile-sub">${embeds.length ? embeds.join(', ') : 'pull nomic-embed-text or bge-m3'}</div>
           <div class="tile-foot"><span>for RAG</span><span>ollama</span></div>`,
  }));

  // LIBRARY
  const lib = data.library;
  const libTile = tile({
    icon: 'book', title: 'LIBRARY',
    status: lib.pdfs > 0 ? 'ok' : 'idle',
    body: `<div class="tile-main">${lib.pdfs} <span style="font-size:14px;color:var(--text-dim)">pdfs</span></div>
           <div class="tile-sub">${lib.size_mb} MB</div>
           <div class="tile-foot"><span>drop PDFs in folder</span><span>see BRAIN</span></div>`,
  });
  libTile.onclick = () => showView('brain');
  grid.appendChild(libTile);

  // GRAPH placeholder
  const graphTile = tile({
    icon: 'graph', title: 'KNOWLEDGE GRAPH',
    status: v.notes > 0 ? 'ok' : 'idle',
    body: `<div class="tile-main">${v.notes ? v.notes : '-'} <span style="font-size:14px;color:var(--text-dim)">nodes</span></div>
           <div class="tile-sub">${v.notes ? 'open in BRAIN tab' : 'empty graph'}</div>
           <div class="tile-foot"><span>d3 force</span><span>→</span></div>`,
  });
  graphTile.onclick = () => showView('brain');
  grid.appendChild(graphTile);

  // DISTILL PROGRESS tile — show live progress when distill is running
  try {
    const jobsR = await fetch('/api/jobs/active');
    const jobsD = await jobsR.json();
    const distillJob = (jobsD.jobs || []).find(j => j.kind === 'distill' || j.id === 'distill');
    if (distillJob && distillJob.progress) {
      const p = distillJob.progress;
      const pct = p.total > 0 ? Math.round((p.done / p.total) * 100) : 0;
      // Detect provider from label (model name)
      const lbl = distillJob.label || '';
      const isCloud = /claude|haiku|gpt|openai/i.test(lbl);
      const providerBadge = isCloud
        ? `<span style="background:rgba(255,43,214,0.15);color:var(--magenta);padding:2px 8px;border-radius:10px;font-size:10px;letter-spacing:1px">☁ CLOUD API</span>`
        : `<span style="background:rgba(0,225,255,0.10);color:var(--cyan);padding:2px 8px;border-radius:10px;font-size:10px;letter-spacing:1px">▣ LOCAL OLLAMA</span>`;
      const distillTile = tile({
        icon: 'db', title: 'DISTILL · LIVE',
        status: 'ok',
        body: `<div class="tile-main">${p.done}/${p.total} <span style="font-size:14px;color:var(--text-dim)">${pct}%</span></div>
               <div class="tile-sub">${providerBadge} ${escapeHtml(lbl.replace(/^Distill[^:]*:\s*/, ''))}</div>
               <div style="background:rgba(0,0,0,0.4);height:6px;border-radius:3px;overflow:hidden;margin:6px 0">
                 <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,var(--cyan),var(--magenta));transition:width 0.5s"></div>
               </div>
               <div class="tile-foot"><span>${escapeHtml((p.label || '').slice(0, 28))}</span><span>→ PIPELINE</span></div>`,
      });
      distillTile.onclick = () => showView('pipeline');
      grid.appendChild(distillTile);
    }
  } catch (e) {/* optional */}

  // QUALITY tile — vault distillation quality breakdown
  try {
    const qr = await fetch('/api/vault/quality');
    const q = await qr.json();
    if (q.total > 0) {
      const pct = q.solid_pct || 0;
      const status = pct >= 70 ? 'ok' : pct >= 50 ? 'warn' : 'down';
      const tile_q = tile({
        icon: 'vault', title: 'NOTE QUALITY',
        status,
        body: `<div class="tile-main">${pct}<span style="font-size:18px">%</span> <span style="font-size:13px;color:var(--text-dim)">solid</span></div>
               <div class="tile-sub" style="font-family:var(--mono);font-size:10px">
                 <span style="color:var(--green)">✓ ${q.solid}</span> ·
                 <span style="color:var(--amber)">⚠ ${q.weak}</span> ·
                 <span style="color:var(--red)">✗ ${q.tiny + q.stub}</span>
               </div>
               <div style="background:rgba(0,0,0,0.4);height:6px;border-radius:3px;overflow:hidden;margin:6px 0;display:flex">
                 <div style="height:100%;width:${(q.solid/q.total)*100}%;background:var(--green)"></div>
                 <div style="height:100%;width:${(q.weak/q.total)*100}%;background:var(--amber)"></div>
                 <div style="height:100%;width:${((q.tiny+q.stub)/q.total)*100}%;background:var(--red)"></div>
               </div>
               <div class="tile-foot">
                 <span>${q.needs_redistill} do poprawy</span>
                 <span>  RE-DISTILL</span>
               </div>`,
      });
      tile_q.onclick = () => {
        showView('pipeline');
        setTimeout(() => document.getElementById('redistill-panel')?.scrollIntoView({behavior: 'smooth'}), 50);
      };
      grid.appendChild(tile_q);
      
      // Update dynamic strings in UI
      const n = q.needs_redistill || 0;
      const elInfo = document.getElementById('redistill-info-count');
      if (elInfo) elInfo.textContent = n;
      document.querySelectorAll('.sched-redistill-dyn-count').forEach(el => el.textContent = n);
      const elHours = document.getElementById('sched-redistill-dyn-hours');
      if (elHours) elHours.textContent = Math.max(1, Math.ceil(n / 20));
      const elNights = document.getElementById('sched-redistill-dyn-nights');
      if (elNights) elNights.textContent = Math.max(1, Math.ceil(n / 120));
    }
  } catch (e) {/* optional */}

  // DEEP QUALITY tile — merytoryczny scoring (note_quality.py)
  try {
    const qr2 = await fetch('/api/vault/quality');
    const q2 = await qr2.json();
    const deep = q2.deep;
    if (deep && deep.avg_score != null) {
      const score = deep.avg_score;
      const sStatus = score >= 6.5 ? 'ok' : score >= 5.0 ? 'warn' : 'down';
      // top source by score
      const sources = Object.entries(deep.by_source || {});
      const top = sources[0];
      const topLabel = top ? `${top[0]} ${top[1].avg_score}` : '—';
      const verds = deep.verdicts || {};
      const auditAge = deep.audit_mtime
        ? Math.round((Date.now()/1000 - deep.audit_mtime) / 3600) + 'h temu'
        : '—';
      const tileDeep = tile({
        icon: 'vault', title: 'DEEP QUALITY',
        status: sStatus,
        body: `<div class="tile-main">${score}<span style="font-size:18px;color:var(--text-dim)">/10</span></div>
               <div class="tile-sub" style="font-family:var(--mono);font-size:10px">
                 <span style="color:var(--green)">✓ ${verds.solid||0}</span> ·
                 <span style="color:var(--cyan)">~ ${verds.ok||0}</span> ·
                 <span style="color:var(--amber)">⚠ ${verds.weak||0}</span> ·
                 <span style="color:var(--red)">✗ ${verds.garbage||0}</span>
               </div>
               <div style="font-size:10px;color:var(--text-dim);margin-top:4px">
                 top: <b style="color:var(--cyan)">${escapeHtml(topLabel)}</b> · ${deep.analyzed} not. · ${auditAge}
               </div>
               <div class="tile-foot">
                 <span>↻ RE-AUDIT</span>
                 <span>→ RAPORT</span>
               </div>`,
      });
      tileDeep.onclick = async (ev) => {
        // Right side click → open report file
        if (ev.target.textContent && ev.target.textContent.includes('RAPORT')) {
          await fetch('/api/vault/open', {method:'POST', headers:{'content-type':'application/json'},
                                          body: JSON.stringify({rel: 'notes/2026-05-25_note-quality-audit.md'})});
          return;
        }
        // Otherwise trigger re-audit
        const r = await fetch('/api/vault/quality/deep-audit', {method: 'POST'});
        const d = await r.json();
        _showToast(d.msg || (d.error || 'Audyt uruchomiony'), d.ok ? 'ok' : 'error', 6000);
      };
      grid.appendChild(tileDeep);
    } else {
      // No deep audit yet — show "Run audit" placeholder
      const tilePlaceholder = tile({
        icon: 'vault', title: 'DEEP QUALITY',
        status: 'warn',
        body: `<div class="tile-main" style="font-size:22px;color:var(--text-dim)">—</div>
               <div class="tile-sub">Audyt jakości jeszcze nie uruchamiany</div>
               <div class="tile-foot"><span></span><span>▶ URUCHOM AUDYT</span></div>`,
      });
      tilePlaceholder.onclick = async () => {
        const r = await fetch('/api/vault/quality/deep-audit', {method: 'POST'});
        const d = await r.json();
        _showToast(d.msg || (d.error || '?'), d.ok ? 'ok' : 'error', 6000);
      };
      grid.appendChild(tilePlaceholder);
    }
  } catch (e) {/* optional */}

  // LLM PROVIDERS tile — local Ollama vs cloud API status
  try {
    const localOk = data.ollama && data.ollama.running;
    const apis = data.apis || {};
    const anthOk = apis.anthropic && apis.anthropic.enabled;
    const cloudOpts = [
      anthOk && '<span style="color:var(--green)">●</span> Claude',
    ].filter(Boolean);
    const provTile = tile({
      icon: 'mcp', title: 'LLM PROVIDERS',
      status: localOk ? 'ok' : 'warn',
      body: `<div class="tile-main">
              <span style="color:${localOk?'var(--cyan)':'var(--text-dim)'}">${localOk?'▣':'○'} Local</span>
              ${cloudOpts.length ? '<span style="font-size:14px;color:var(--text-dim);margin-left:8px">+ ${cloudOpts.length} cloud</span>' : ''}
            </div>
            <div class="tile-sub">
              ${localOk ? 'Ollama ' + (data.ollama.count || 0) + ' models' : 'Ollama OFF'}
              ${cloudOpts.length ? '<br>' + cloudOpts.join(' · ') : ''}
            </div>
            <div class="tile-foot"><span>Wybór per task</span><span>→ TOOLS</span></div>`,
    });
    provTile.onclick = () => { showView('tools'); setTimeout(() =>
      document.querySelector('#sched-list')?.scrollIntoView({behavior:'smooth'}), 200); };
    grid.appendChild(provTile);
  } catch (e) {/* optional */}

  // CHEAT SHEET tile — opens modal with top 10 magic prompts
  const cheatTile = tile({
    icon: 'mcp', title: 'MCP CHEAT SHEET', status: 'ok',
    body: `<div class="tile-main">10 <span style="font-size:14px;color:var(--text-dim)">promptów</span></div>
           <div class="tile-sub">copy-paste do dowolnego agenta z brain MCP</div>
           <div class="tile-foot"><span>search · save · skill · code</span><span>→ open</span></div>`,
  });
  cheatTile.onclick = () => _openCheatSheet();
  grid.appendChild(cheatTile);

  // AGENTS tile — shows MCP deployment status
  try {
    const ar = await fetch('/api/agents');
    const ad = await ar.json();
    const ags = ad.agents || [];
    const installed = ags.filter(a => a.installed);
    const wired = installed.filter(a => a.brain_status === 'wired');
    const partial = installed.filter(a => a.brain_status === 'partial');
    const status = installed.length === 0 ? 'idle'
                 : wired.length === installed.length ? 'ok'
                 : partial.length > 0 ? 'warn' : 'down';
    const labels = installed.map(a => {
      const dot = a.brain_status === 'wired' ? '●' : (a.brain_status === 'partial' ? '◐' : '○');
      const cls = a.brain_status === 'wired' ? 'green' : (a.brain_status === 'partial' ? 'amber' : 'dim');
      return `<span class="agent-dot ${cls}" title="${escapeHtml(a.label)} · ${a.brain_status}">${dot} ${escapeHtml(a.label.split(' ')[0])}</span>`;
    }).join(' ');
    const agentsTile = tile({
      icon: 'mcp', title: 'AGENTS · MCP DEPLOY',
      status,
      body: `<div class="tile-main">${wired.length}/${installed.length} <span style="font-size:14px;color:var(--text-dim)">wired</span></div>
             <div class="tile-sub agent-list">${labels || 'no agents detected'}</div>
             <div class="tile-foot"><span>brain MCP in apps</span><span>→ TOOLS</span></div>`,
    });
    agentsTile.onclick = () => { showView('tools'); setTimeout(() => {
      document.querySelector('#agents-panel')?.scrollIntoView({behavior: 'smooth', block: 'start'});
    }, 200); };
    grid.appendChild(agentsTile);
  } catch (e) { /* tile optional */ }

  // API tiles — slim cluster in one container (compact, info-dense)
  const enabledApis = Object.entries(data.apis).filter(([_, p]) => p.enabled);
  if (enabledApis.length) {
    const apiCluster = document.createElement('div');
    apiCluster.className = 'tile api-cluster wide';
    apiCluster.innerHTML = `
      <div class="tile-head">
        <div class="tile-title-row">
          <span class="tile-icon">${ICONS.openai}</span>
          <span class="tile-title">API PROVIDERS (${enabledApis.length})</span>
        </div>
        <div class="status-dot ok"></div>
      </div>
      <div class="api-mini-grid">
        ${enabledApis.map(([pid, p]) => {
          const src = p.source === 'env' ? `env` : 'file';
          return `<a class="api-mini" href="${p.url}" target="_blank" title="${escapeHtml(pid)} — ${escapeHtml(p.masked)} (${src})">
            <span class="api-mini-icon" style="color:${p.has_key?'var(--green)':'var(--amber)'}">${ICONS[p.icon] || ''}</span>
            <span class="api-mini-name">${escapeHtml(p.title)}</span>
            <span class="api-mini-status ${p.has_key?'ok':'warn'}">${p.has_key ? 'KEY' : 'NO KEY'}</span>
          </a>`;
        }).join('')}
      </div>
      <div class="tile-foot"><span>${enabledApis.length} of 6 configured</span><span>edit in OPTIONS</span></div>
    `;
    apiCluster.onclick = (e) => { if (e.target.tagName !== 'A' && !e.target.closest('a')) showView('options'); };
    grid.appendChild(apiCluster);
  }

  if (!Object.values(data.apis).some(p => p.enabled)) {
    const h = document.createElement('div');
    h.className = 'tile';
    h.onclick = () => showView('options');
    h.innerHTML = `<div class="tile-head"><div class="tile-title-row"><span class="tile-title" style="color:var(--magenta)">CLOUD APIs</span></div></div>
      <div class="tile-main" style="font-size:16px">none enabled</div>
      <div class="tile-sub">Open <strong style="color:var(--cyan)">OPTIONS</strong> → enable Claude (optional — for Haiku distillation)</div>
      <div class="tile-foot"><span>click to configure</span><span>→</span></div>`;
    grid.appendChild(h);
  }

  // Atomic swap — replace old grid with new one in single DOM operation (no flicker)
  oldGrid.replaceWith(grid);

  $('#last-update').textContent = `updated ${fmtTime()}`;
  { const fv = $('#footer-version'); if (fv) fv.textContent = `brain v${data.config.version || '?'}`; }
  syncChatModelOptions();
}

// ============================================================================
// OLLAMA pull (streaming progress from Ollama API)
// ============================================================================
async function doPull(name, progressEl) {
  if (!name) { progressEl.textContent = '(name required)'; return; }
  progressEl.innerHTML = `<div>starting ${escapeHtml(name)}…</div><div class="oc-bar"><div class="oc-fill" style="width:0%"></div></div>`;
  try {
    const r = await fetch(OLLAMA + '/api/pull', {
      method: 'POST',
      body: JSON.stringify({name, stream: true}),
    });
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      const lines = buf.split('\n'); buf = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const j = JSON.parse(line);
          const status = j.status || '';
          const total = j.total || 0;
          const done = j.completed || 0;
          const pct = total ? (done/total*100) : 0;
          progressEl.innerHTML = `<div>${escapeHtml(status)} ${total?`${(done/1e9).toFixed(2)}/${(total/1e9).toFixed(2)} GB`:''}</div><div class="oc-bar"><div class="oc-fill" style="width:${pct}%"></div></div>`;
          if (j.error) { progressEl.innerHTML = `<div style="color:var(--red)">${escapeHtml(j.error)}</div>`; return; }
        } catch {}
      }
    }
    progressEl.innerHTML = `<div style="color:var(--green)">pulled ${escapeHtml(name)} ✓</div>`;
    setTimeout(refresh, 500);
  } catch (e) {
    progressEl.innerHTML = `<div style="color:var(--red)">pull failed: ${escapeHtml(e.message)}</div>`;
  }
}

// ============================================================================
// CHAT WIDGET (talks to local Ollama)
// ============================================================================
function activeModel() { return localStorage.getItem('brain.activeModel') || (lastStatus?.ollama?.models?.[0]?.name); }
function syncChatModel() {
  const sel = $('#chat-model'); if (sel) sel.value = activeModel() || '';
}
function syncChatModelOptions() {
  const sel = $('#chat-model'); if (!sel || !lastStatus) return;
  const cur = sel.value || activeModel();
  sel.innerHTML = lastStatus.ollama.models.map(m => `<option value="${m.name}" ${m.name===cur?'selected':''}>${m.name}</option>`).join('') || '<option>no models</option>';
}

const chatHistory = [];
let chatAbortController = null;
let chatLastResponse = '';

function appendChat(role, text) {
  const el = document.createElement('div');
  el.className = 'chat-msg ' + role;
  el.innerHTML = `<div class="role">${role.toUpperCase()}</div><div class="content"></div>`;
  const content = el.querySelector('.content');
  if (text) {
    content.textContent = text;
  } else if (role === 'assistant') {
    // Show braille spinner until first token arrives
    content.classList.add('thinking');
    content.innerHTML = '<span class="think-label">thinking…</span>';
  }
  $('#chat-msgs').appendChild(el);
  $('#chat-msgs').scrollTop = $('#chat-msgs').scrollHeight;
  return content;
}

async function chatNewConversation() {
  // Auto-save before clearing — never lose a conversation accidentally
  if (chatHistory.length >= 2) {
    try { await chatSaveToVault(/*silent=*/ true); } catch {}
  }
  chatHistory.length = 0;
  chatLastResponse = '';
  _chatExchangesSinceSave = 0;
  $('#chat-msgs').innerHTML = '';
  appendChat('system', 'new conversation started');
}

// Auto-save state — silent save every N exchanges so chat never gets lost
let _chatExchangesSinceSave = 0;
let _chatAutoSaveTimer = null;
const CHAT_AUTOSAVE_EVERY = 8;            // exchanges between auto-saves
const CHAT_AUTOSAVE_DELAY_MS = 8000;      // debounce window

function _scheduleChatAutoSave() {
  _chatExchangesSinceSave++;
  if (_chatExchangesSinceSave < CHAT_AUTOSAVE_EVERY) return;
  if (_chatAutoSaveTimer) clearTimeout(_chatAutoSaveTimer);
  _chatAutoSaveTimer = setTimeout(async () => {
    try {
      await chatSaveToVault(/*silent=*/ true);
      _chatExchangesSinceSave = 0;
    } catch {}
  }, CHAT_AUTOSAVE_DELAY_MS);
}

async function chatSaveToVault(silent = false) {
  if (!chatHistory.length) {
    if (!silent) appendChat('system', 'nothing to save');
    return;
  }
  const firstUser = chatHistory.find(m => m.role === 'user')?.content || '';
  const title = firstUser.slice(0, 60).replace(/\n/g, ' ').trim() || 'chat session';
  const model = $('#chat-model').value || activeModel() || 'unknown';
  try {
    const r = await fetch('/api/vault/save-chat', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({title, model, messages: chatHistory}),
    });
    const d = await r.json();
    if (r.ok) {
      if (!silent) appendChat('system', `✓ saved to vault: ${d.rel}`);
    } else if (!silent) {
      appendChat('system', `✗ save failed: ${d.detail || 'unknown error'}`);
    }
  } catch (e) {
    if (!silent) appendChat('system', `✗ network error: ${e.message}`);
  }
}

async function chatCopyLast() {
  if (!chatLastResponse) { appendChat('system', 'no response to copy yet'); return; }
  try {
    await navigator.clipboard.writeText(chatLastResponse);
    const btn = $('#chat-copy');
    const orig = btn.innerHTML;
    btn.classList.add('active');
    setTimeout(() => btn.classList.remove('active'), 800);
  } catch (e) {
    appendChat('system', '✗ clipboard blocked');
  }
}

function chatStop() {
  if (chatAbortController) {
    try { chatAbortController.abort(); } catch {}
    chatAbortController = null;
  }
  _chatToggleSendStop(false);
}

function _chatToggleSendStop(generating) {
  $('#chat-send').classList.toggle('hidden', generating);
  $('#chat-stop').classList.toggle('hidden', !generating);
}

async function sendChat() {
  const raw = $('#chat-input').value;
  const txt = raw.trim();
  if (!txt) return;

  // Slash commands
  if (txt === '/clear' || txt === '/new') {
    $('#chat-input').value = ''; chatNewConversation(); return;
  }
  if (txt === '/save') {
    $('#chat-input').value = ''; chatSaveToVault(); return;
  }

  const model = $('#chat-model').value || activeModel();
  if (!model) { appendChat('system', 'no model selected'); return; }

  $('#chat-input').value = '';
  appendChat('user', txt);
  chatHistory.push({role: 'user', content: txt});
  const respEl = appendChat('assistant', '');

  const recent = chatHistory.slice(-12);
  const messages = recent.map(m => ({role: m.role, content: m.content}));

  chatAbortController = new AbortController();
  _chatToggleSendStop(true);
  let acc = '';

  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({model, messages, stream: true}),
      signal: chatAbortController.signal,
    });
    if (!r.ok) {
      respEl.textContent = '[error] ' + r.status + ' ' + await r.text();
      _chatToggleSendStop(false); chatAbortController = null; return;
    }
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let gotFirstToken = false;
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      const lines = buf.split('\n'); buf = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const j = JSON.parse(line);
          if (j.error) { respEl.classList.remove('thinking'); respEl.textContent = '[error] ' + j.error; break; }
          if (j.message?.content) {
            if (!gotFirstToken) {
              // Clear spinner on first real token
              gotFirstToken = true;
              respEl.classList.remove('thinking');
              respEl.textContent = '';
            }
            acc += j.message.content;
            respEl.textContent = acc;
            $('#chat-msgs').scrollTop = $('#chat-msgs').scrollHeight;
          }
        } catch {}
      }
    }
    // If we never got a token, show an error hint
    if (!gotFirstToken) {
      respEl.classList.remove('thinking');
      respEl.textContent = '[no response — check model or try qwen2.5:14b]';
    }
    chatHistory.push({role: 'assistant', content: acc});
    chatLastResponse = acc;
    _scheduleChatAutoSave();
  } catch (e) {
    if (e.name === 'AbortError') {
      if (acc) {
        chatHistory.push({role: 'assistant', content: acc + ' [stopped]'});
        chatLastResponse = acc;
      } else {
        // remove empty assistant placeholder
        respEl.parentElement?.remove();
        chatHistory.pop();
      }
      appendChat('system', '⏹ generation stopped');
    } else {
      respEl.textContent = '[network error] ' + e.message;
    }
  } finally {
    chatAbortController = null;
    _chatToggleSendStop(false);
  }
}

function initChat() {
  $('#chat-toggle').onclick = () => { $('#chat').classList.remove('collapsed'); syncChatModelOptions(); $('#chat-input').focus(); };
  $('#chat-close').onclick = () => $('#chat').classList.add('collapsed');
  $('#chat-send').onclick  = sendChat;
  $('#chat-stop').onclick  = chatStop;
  $('#chat-new').onclick   = chatNewConversation;
  $('#chat-save').onclick  = chatSaveToVault;
  $('#chat-copy').onclick  = chatCopyLast;
  $('#chat-expand').onclick = () => {
    $('#chat').classList.toggle('expanded');
    // Restore saved msgs height when entering expand
    const saved = parseInt(localStorage.getItem('brain.chat.msgsHeight') || '0', 10);
    if (saved > 50 && $('#chat').classList.contains('expanded')) {
      $('#chat-msgs').style.flex = '0 0 ' + saved + 'px';
    } else {
      $('#chat-msgs').style.flex = '';
    }
  };

  // Resizer drag — drag UP = bigger input textarea (shrinks msgs).
  // Drag DOWN = smaller input, bigger msgs area. Keeps both usable.
  const resizer = $('#chat-resizer');
  if (resizer) {
    let dragging = false, startY = 0, startMsgsH = 0, startInputH = 0;
    const msgsEl  = $('#chat-msgs');
    const inputEl = $('#chat-input');
    // Restore saved textarea height
    const savedInput = parseInt(localStorage.getItem('brain.chat.inputHeight') || '0', 10);
    if (savedInput && savedInput >= 40) inputEl.style.height = savedInput + 'px';
    resizer.addEventListener('mousedown', (e) => {
      dragging = true;
      startY = e.clientY;
      startMsgsH  = msgsEl.getBoundingClientRect().height;
      startInputH = inputEl.getBoundingClientRect().height;
      resizer.classList.add('dragging');
      document.body.style.cursor = 'ns-resize';
      document.body.style.userSelect = 'none';
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      // Drag UP (negative delta) → grow input by |delta|, shrink msgs by |delta|.
      // Drag DOWN (positive delta) → opposite.
      const delta = e.clientY - startY;
      const newInputH = Math.max(40, Math.min(500, startInputH - delta));
      const newMsgsH  = Math.max(60, Math.min(800, startMsgsH + delta));
      inputEl.style.height = newInputH + 'px';
      msgsEl.style.flex = '0 0 ' + newMsgsH + 'px';
    });
    window.addEventListener('mouseup', () => {
      if (!dragging) return;
      dragging = false;
      resizer.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      localStorage.setItem('brain.chat.msgsHeight',
        String(Math.round(msgsEl.getBoundingClientRect().height)));
      localStorage.setItem('brain.chat.inputHeight',
        String(Math.round(inputEl.getBoundingClientRect().height)));
    });
  }

  // Wire brain integration toolbar (visible only in expand mode)
  document.querySelectorAll('.chat-brain-btn').forEach(btn => {
    btn.onclick = async () => {
      const action = btn.dataset.action;
      if (action === 'cheat') {
        _openCheatSheet();
        return;
      }
      if (action === 'recent') {
        // Fetch recent vault notes, show as list, click = paste filename
        try {
          const r = await fetch('/api/vault/notes?limit=20');
          const d = await r.json();
          const list = (d.notes || []).map(n =>
            `- ${n.name} (${n.size_kb} KB)`).join('\n');
          const inp = $('#chat-input');
          inp.value = `# Ostatnie 20 notatek z vault:\n${list}\n\n# Pytanie: <wpisz co chcesz wiedzieć>`;
          inp.focus();
        } catch (e) {}
        return;
      }
      // data-prefill: insert ready prompt into chat input
      const prefill = btn.dataset.prefill;
      if (prefill) {
        const inp = $('#chat-input');
        inp.value = prefill;
        inp.focus();
        // Place cursor at first empty value (between "")
        const idx = prefill.indexOf('""');
        if (idx > 0) inp.setSelectionRange(idx + 1, idx + 1);
      }
    };
  });
  $('#chat-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    else if (e.key === 'Escape' && chatAbortController) { e.preventDefault(); chatStop(); }
  });
  $('#chat-model').onchange = e => { localStorage.setItem('brain.activeModel', e.target.value); refresh(); };
}

// ============================================================================
// BRAIN: VAULT
// ============================================================================
function _vaultSource(rel) {
  // Infer source from filename: 2026-MM-DD_<source>_<title>_<id>.md
  const m = rel.match(/_(claude-ai|claude-code|grok|chatgpt|inbox-\w+)_/);
  return m ? m[1] : 'unknown';
}

let _vaultCache = null;       // raw notes from /api/vault/notes
let _vaultCacheTs = 0;
let _vaultSearchDebounce = null;

async function renderVault() {
  const body = $('#vault-body');
  const meta = $('#vault-meta');
  body.textContent = 'loading…';
  try {
    // Cache 30s — list comes from filesystem scan, rebuilds when stale
    if (!_vaultCache || (Date.now() - _vaultCacheTs) > 30000) {
      const r = await fetch('/api/vault/notes?limit=2000');
      const d = await r.json();
      _vaultCache = d;
      _vaultCacheTs = Date.now();
    }
    _renderVaultList();
  } catch (e) {
    body.innerHTML = `<div class="vault-empty">load failed: ${escapeHtml(e.message)}</div>`;
  }
}

function _renderVaultList() {
  const body = $('#vault-body');
  const meta = $('#vault-meta');
  const d = _vaultCache;
  if (!d || !d.notes) return;
  if (!d.notes.length) {
    body.innerHTML = `<div class="vault-empty">vault is empty — run TRANSCRIPT DISTILLATION below to populate it</div>`;
    return;
  }

  const q = ($('#vault-search')?.value || '').trim().toLowerCase();
  const srcFilter = $('#vault-source')?.value || '';
  const sort = $('#vault-sort')?.value || 'mtime';

  let filtered = d.notes;
  if (q) {
    const tokens = q.split(/\s+/).filter(Boolean);
    filtered = filtered.filter(n => {
      const hay = (n.rel + ' ' + (n.name || '')).toLowerCase();
      return tokens.every(t => hay.includes(t));
    });
  }
  if (srcFilter) {
    filtered = filtered.filter(n => _vaultSource(n.rel) === srcFilter);
  }
  if (sort === 'size')       filtered.sort((a,b) => b.size_kb - a.size_kb);
  else if (sort === 'name')  filtered.sort((a,b) => a.rel.localeCompare(b.rel));
  else                       filtered.sort((a,b) => b.mtime - a.mtime);  // mtime desc

  const total = d.notes.length;
  const shown = filtered.length;
  if (meta) meta.textContent = q || srcFilter
    ? `${shown}/${total} (filter aktywny)`
    : `${total} notatek`;

  // Count by source for footer stats
  const counts = {};
  for (const n of filtered) { const s = _vaultSource(n.rel); counts[s] = (counts[s]||0)+1; }
  const breakdown = Object.entries(counts).map(([s,n]) => `${s}: ${n}`).join(' · ');

  body.innerHTML = `
    <div class="vault-header">
      <span></span><span>FILE</span><span style="text-align:right">SIZE</span><span style="text-align:right">AGO</span>
    </div>
    <div class="vault-list">
      ${filtered.slice(0, 500).map(n => {
        const src = _vaultSource(n.rel);
        const color = SOURCE_COLORS[src] || '#7a8aa3';
        return `<div class="vault-row clickable" title="${escapeHtml(n.path)}\n${src} — kliknij żeby zobaczyć"
          data-rel="${escapeHtml(n.rel)}" data-name="${escapeHtml(n.name)}" data-src="${escapeHtml(src)}">
          <div class="v-src" style="background:${color};box-shadow:0 0 6px ${color}"></div>
          <div class="v-rel">${escapeHtml(n.rel.replace(/^distilled[\\\/]/,''))}</div>
          <div class="v-size">${n.size_kb} KB</div>
          <div class="v-when">${fmtAgo(n.mtime)}</div>
        </div>`;
      }).join('')}
    </div>
    <div class="vault-footer">
      <span>${shown === total ? `${total} notes` : `${shown} / ${total}`}</span>
      <span>${breakdown}</span>
    </div>`;

  // Wire click → reuse graph node panel
  body.querySelectorAll('.vault-row.clickable').forEach(row => {
    row.onclick = () => {
      _showNodePanel({
        id:     row.dataset.name,
        label:  row.dataset.name,
        source: row.dataset.src,
        is_hub: false,
        msgs:   0,
      });
    };
  });
}

function initVault() {
  $('#vault-open').onclick = async () => {
    await fetch('/api/vault/open', {method: 'POST'});
  };
  // Wire filter/search/sort — debounce search input
  $('#vault-search')?.addEventListener('input', () => {
    clearTimeout(_vaultSearchDebounce);
    _vaultSearchDebounce = setTimeout(_renderVaultList, 150);
  });
  $('#vault-source')?.addEventListener('change', _renderVaultList);
  $('#vault-sort')?.addEventListener('change', _renderVaultList);
}

// ============================================================================
// BRAIN: DEDUP (Knowledge Lifecycle)
// ============================================================================
let _dedupBusy = false;
async function renderDedup() {
  const body = $('#dedup-body');
  const meta = $('#dedup-meta');
  if (!body || !meta) return;
  try {
    const r = await fetch('/api/vault/dedupe/candidates');
    const d = await r.json();
    _renderDedupResults(d, body, meta);
  } catch (e) {
    body.innerHTML = `<div class="dedup-empty">błąd: ${escapeHtml(e.message)}</div>`;
  }
}

function _renderDedupResults(d, body, meta) {
  const pairs = d.pairs || [];
  if (!pairs.length) {
    meta.textContent = d.scanned ? `${d.scanned} notatek · 0 par` : '—';
    body.innerHTML = `<div class="dedup-empty">Brak kandydatów. Kliknij SCAN żeby przeskanować vault.</div>`;
    return;
  }
  meta.textContent = `${d.scanned} notatek · ${pairs.length} par`;
  body.innerHTML = pairs.map((p, i) => {
    const aIsKept = (p.a >= p.b);   // newer date wins (string compare on YYYY-MM-DD prefix)
    const keptName = aIsKept ? p.a : p.b;
    const lostName = aIsKept ? p.b : p.a;
    const keptPrev = aIsKept ? p.preview_a : p.preview_b;
    const lostPrev = aIsKept ? p.preview_b : p.preview_a;
    const keptSize = aIsKept ? p.size_a : p.size_b;
    const lostSize = aIsKept ? p.size_b : p.size_a;
    return `
      <div class="dedup-pair" data-idx="${i}">
        <div class="dedup-pair-head">
          <div class="scores">
            <span>cos <b>${p.cosine}</b></span>
            <span>jac <b>${p.jaccard}</b></span>
            <span>tytuł <b>${p.title_jac}</b></span>
            <span>score <b>${p.score}</b></span>
          </div>
          <div class="dedup-pair-actions">
            <button class="opt-btn" data-action="merge"
              data-a="${escapeHtml(p.a)}" data-b="${escapeHtml(p.b)}">MERGE</button>
            <button class="opt-btn test" data-action="dismiss"
              data-a="${escapeHtml(p.a)}" data-b="${escapeHtml(p.b)}">NOT DUPE</button>
          </div>
        </div>
        <table class="dedup-pair-body"><tbody><tr>
          <td class="kept">
            <span class="dedup-name" title="${escapeHtml(keptName)}">✓ KEEP · ${escapeHtml(keptName)}</span>
            <span class="dedup-meta-row">${keptSize} B</span>
            <span class="dedup-preview">${escapeHtml(keptPrev)}</span>
          </td>
          <td class="lost">
            <span class="dedup-name" title="${escapeHtml(lostName)}">✗ ARCHIVE · ${escapeHtml(lostName)}</span>
            <span class="dedup-meta-row">${lostSize} B</span>
            <span class="dedup-preview">${escapeHtml(lostPrev)}</span>
          </td>
        </tr></tbody></table>
      </div>`;
  }).join('');

  body.querySelectorAll('button[data-action]').forEach(btn => {
    btn.onclick = async () => {
      if (_dedupBusy) return;
      _dedupBusy = true;
      const action = btn.dataset.action;
      const a = btn.dataset.a, b = btn.dataset.b;
      const url = action === 'merge' ? '/api/vault/dedupe/merge' : '/api/vault/dedupe/dismiss';
      try {
        const r = await fetch(url, {
          method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify({a, b, strategy: 'newer'}),
        });
        await r.json();
      } catch (e) { console.error(e); }
      _dedupBusy = false;
      renderDedup();
    };
  });
}

function initDedup() {
  const scan = $('#dedup-scan');
  const refresh = $('#dedup-refresh');
  if (scan) {
    scan.onclick = async () => {
      if (_dedupBusy) return;
      _dedupBusy = true;
      scan.disabled = true;
      const orig = scan.textContent;
      scan.textContent = 'SCANNING…';
      $('#dedup-body').innerHTML = `<div class="dedup-empty">Skanuję ~5-10s (mean-cosine + Jaccard 5-gram + tytuł)…</div>`;
      try {
        const r = await fetch('/api/vault/dedupe/scan', {method: 'POST'});
        const d = await r.json();
        _renderDedupResults(d, $('#dedup-body'), $('#dedup-meta'));
      } catch (e) {
        $('#dedup-body').innerHTML = `<div class="dedup-empty">błąd: ${escapeHtml(e.message)}</div>`;
      }
      scan.textContent = orig;
      scan.disabled = false;
      _dedupBusy = false;
    };
  }
  if (refresh) refresh.onclick = () => renderDedup();
}

// ============================================================================
// BRAIN: GRAPH
// ============================================================================
let currentGraph2D = null;
let currentGraph3D = null;
let lastGraphData = null;
let graphState = {
  selectedSource: null,
  selectedNodeId: null,
  hoverNode: null
};
// Color palette per source — distinct, vibrant, dark-bg friendly
const SOURCE_COLORS = {
  'claude-ai':      '#d97757',   // Claude orange
  'claude-code':    '#a855f7',   // Distinct purple
  'claude-desktop': '#cc6644',   // Claude darker
  'grok':           '#1da1f2',   // X blue
  'chatgpt':        '#10a37f',   // OpenAI green
  'openai':         '#10a37f',
  'gemini':         '#4285f4',   // Google blue
  'antigravity':    '#34a853',   // Google green (Gemini IDE)
  'cursor':         '#ffcc00',   // Cursor yellow
  'vscode':         '#007acc',   // VS Code blue
  'windsurf':       '#06b6d4',   // Codeium cyan
  'inbox-jsonl':    '#9b59b6',   // purple
  'inbox-json':     '#9b59b6',
  'inbox-text':     '#9b59b6',
  'link':           '#7a8aa3',   // gray for unresolved wikilinks
  'unknown':        '#7a8aa3',
};
function _srcColor(s) { return SOURCE_COLORS[s] || '#00e1ff'; }

function renderLegendHTML(data) {
  const legend = $('#graph-legend');
  if (!legend) return;
  legend.innerHTML = '';
  if (!data || !data.stats || !data.stats.sources) return;
  
  const showHubs = $('#graph-show-hubs')?.checked ?? false;
  legend.style.display = showHubs ? 'flex' : 'none';
  
  for (const [src, count] of Object.entries(data.stats.sources)) {
    const color = _srcColor(src);
    const item = document.createElement('div');
    item.className = 'graph-legend-item';
    item.innerHTML = `
      <span class="graph-legend-dot" style="background: ${color}; box-shadow: 0 0 6px ${color};"></span>
      <span>${src} (${count})</span>
    `;
    legend.appendChild(item);
  }
}

async function renderGraph() {
  try {
    const r = await fetch('/api/graph');
    const d = await r.json();
    lastGraphData = d;
    $('#graph-stats').textContent = `${d.stats.notes} nodes · ${d.stats.links} links`;
    
    // Always render legend in HTML overlay
    renderLegendHTML(d);
    
    if (!d.nodes.length) {
      $('#graph-canvas').innerHTML = `<div class="graph-empty"><div>empty graph</div><div>add notes with [[wikilinks]] or run distillation</div></div>`;
      $('#graph-canvas-3d').innerHTML = '';
      return;
    }
    
    _toggleGraphTheme();
  } catch (e) {
    $('#graph-canvas').innerHTML = `<div class="graph-empty">graph load failed: ${escapeHtml(e.message)}</div>`;
  }
}

function _toggleGraphTheme() {
  const theme = $('#graph-theme')?.value || '2d';
  const c2d = $('#graph-canvas');
  const c3d = $('#graph-canvas-3d');

  const is3D = theme === '3d' || theme === 'cosmos' || theme === 'mycelium';
  if (is3D) {
    c2d.style.display = 'none';
    c3d.style.display = 'block';
    if (currentGraph2D && currentGraph2D.sim) currentGraph2D.sim.stop();
    if (currentGraph3D) {  // tear down previous 3D to swap renderer
      currentGraph3D.element.innerHTML = '';
      currentGraph3D = null;
    }
    if (lastGraphData) {
      if (theme === 'cosmos')    drawForceGraphCosmos(c3d, lastGraphData);
      else if (theme === 'mycelium') drawForceGraphMycelium(c3d, lastGraphData);
      else                       drawForceGraph3D(c3d, lastGraphData);
    }
  } else {
    c3d.style.display = 'none';
    c2d.style.display = 'block';
    if (currentGraph3D) {
      currentGraph3D.element.innerHTML = '';
      currentGraph3D = null;
    }
    if (lastGraphData) drawForceGraph2D(c2d, lastGraphData);
  }
}

function drawForceGraph2D(container, data) {
  if (currentGraph2D && currentGraph2D.sim) {
    currentGraph2D.sim.stop();
  }
  container.innerHTML = '';
  const w = container.clientWidth, h = container.clientHeight;
  const dpr = window.devicePixelRatio || 1;

  // Canvas
  const canvas = document.createElement('canvas');
  canvas.width = w * dpr; canvas.height = h * dpr;
  canvas.style.width = w + 'px'; canvas.style.height = h + 'px';
  canvas.style.cursor = 'grab';
  canvas.style.display = 'block';
  container.appendChild(canvas);
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  // Zoom/pan transform we maintain ourselves
  let tx = 0, ty = 0, scale = 1;

  // Tooltip (DOM, positioned over canvas)
  let tooltip = container.querySelector('.graph-tip');
  if (!tooltip) {
    tooltip = document.createElement('div');
    tooltip.className = 'graph-tip';
    container.appendChild(tooltip);
  }

  const nodes = data.nodes;
  const edges = data.edges;
  graphState.nodes2d = nodes;  // accessible from initGraph for unpin-all

  function screenToWorld(sx, sy) {
    return { x: (sx - tx) / scale, y: (sy - ty) / scale };
  }
  function pickNode(sx, sy) {
    const p = screenToWorld(sx, sy);
    let best = null, bestD = Infinity;
    for (const n of nodes) {
      if (n.x == null) continue;
      const r = (n.size || 4) + 3;
      const dx = n.x - p.x, dy = n.y - p.y;
      const d2 = dx*dx + dy*dy;
      if (d2 < r*r && d2 < bestD) { best = n; bestD = d2; }
    }
    return best;
  }

  let showLabels = $('#graph-show-labels')?.checked ?? false;
  let showHubs   = $('#graph-show-hubs')?.checked ?? false;

  function draw() {
    showLabels = $('#graph-show-labels')?.checked ?? false;
    showHubs   = $('#graph-show-hubs')?.checked ?? false;
    
    ctx.save();
    ctx.clearRect(0, 0, w, h);
    ctx.translate(tx, ty);
    ctx.scale(scale, scale);

    // Edges
    for (const e of edges) {
      const s = e.source, t = e.target;
      if (s.x == null || t.x == null) continue;
      const isCluster = e.is_cluster;
      const sourceMatch = graphState.selectedSource &&
        ((s.source || s) === graphState.selectedSource || (t.source || t) === graphState.selectedSource);
      const nodeMatch = graphState.selectedNodeId &&
        (s.id === graphState.selectedNodeId || t.id === graphState.selectedNodeId);
      let alpha = isCluster ? 0.07 : 0.35;
      if (graphState.selectedSource && !sourceMatch) alpha *= 0.15;
      if (graphState.selectedNodeId && !nodeMatch)   alpha *= 0.10;
      if (graphState.selectedNodeId && nodeMatch)    alpha = 0.85;
      ctx.strokeStyle = isCluster
        ? `rgba(0,225,255,${alpha})`
        : `rgba(255,43,214,${alpha})`;
      ctx.lineWidth = (isCluster ? 0.6 : 1.2) / scale;
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(t.x, t.y);
      ctx.stroke();
    }

    // Nodes
    for (const n of nodes) {
      if (n.x == null) continue;
      const r = n.size || 4;
      const isHub = n.is_hub;
      let alpha = isHub ? 1 : 0.85;
      if (graphState.selectedSource && !isHub && n.source !== graphState.selectedSource) alpha = 0.15;
      if (graphState.selectedNodeId && !isHub && n.id !== graphState.selectedNodeId) alpha = 0.35;
      if (n.id === graphState.selectedNodeId) alpha = 1;

      const color = isHub ? 'rgba(255,255,255,0.95)' : _srcColor(n.source);
      if (isHub) {
        ctx.shadowColor = _srcColor(n.source);
        ctx.shadowBlur = 18 / scale;
      } else {
        ctx.shadowBlur = 0;
      }
      ctx.globalAlpha = alpha;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      if (isHub) {
        ctx.strokeStyle = _srcColor(n.source);
        ctx.lineWidth = 3 / scale;
      } else {
        ctx.strokeStyle = (n === graphState.hoverNode || n.id === graphState.selectedNodeId)
          ? 'rgba(0,225,255,0.9)'
          : 'rgba(255,255,255,0.15)';
        ctx.lineWidth = (n === graphState.hoverNode || n.id === graphState.selectedNodeId ? 2.5 : 1) / scale;
      }
      ctx.stroke();

      // Pin indicator — small red dot on pinned nodes
      if (n.fx != null) {
        ctx.globalAlpha = 1;
        ctx.shadowBlur = 0;
        ctx.fillStyle = '#ff4466';
        ctx.beginPath();
        ctx.arc(n.x + r * 0.7, n.y - r * 0.7, Math.max(2, 3.5 / scale), 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;

    // Labels
    if ((showLabels || showHubs) && scale > 0.35) {
      ctx.textBaseline = 'middle';
      for (const n of nodes) {
        if (n.x == null) continue;
        const isHub = n.is_hub;
        if (isHub && !showHubs) continue;
        if (!isHub && !showLabels) continue;
        if (!isHub && (n.size || 0) < 8) continue;

        const text = isHub
          ? (n.label || n.id).toUpperCase()
          : (n.label || n.id).slice(0, 35);
        const fontSize = (isHub ? 18 : 11) / scale;
        ctx.font = `${isHub ? 800 : 500} ${fontSize}px ui-monospace, "JetBrains Mono", Consolas, monospace`;
        ctx.lineWidth = (isHub ? 5 : 3.5) / scale;
        ctx.strokeStyle = '#0a0e1a';
        ctx.lineJoin = 'round';
        const x = n.x + (n.size || 4) + 6;
        const y = n.y + (isHub ? 1 : 0);
        ctx.strokeText(text, x, y);
        ctx.fillStyle = isHub ? '#ffffff' : 'rgba(240,245,255,0.92)';
        ctx.fillText(text, x, y);
      }
    }

    ctx.restore();
  }

  let dragging = false, dragStart = null;
  let dragNode = null;
  let downX = 0, downY = 0, moved = false;

  canvas.addEventListener('mousedown', (e) => {
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    downX = sx; downY = sy; moved = false;
    const n = pickNode(sx, sy);
    if (n) {
      dragNode = n;
      n.fx = n.x; n.fy = n.y;
      _simStopped = false;
      sim.alphaTarget(0.3).restart();
    } else {
      dragging = true;
      dragStart = { x: sx - tx, y: sy - ty };
      canvas.style.cursor = 'grabbing';
    }
  });
  canvas.addEventListener('mousemove', (e) => {
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    if (Math.abs(sx - downX) + Math.abs(sy - downY) > 4) moved = true;

    if (dragNode) {
      const p = screenToWorld(sx, sy);
      dragNode.x = p.x; dragNode.y = p.y;
      dragNode.fx = p.x; dragNode.fy = p.y;
      draw();
      return;
    }
    if (dragging) {
      tx = sx - dragStart.x;
      ty = sy - dragStart.y;
      draw();
      return;
    }
    const n = pickNode(sx, sy);
    if (n !== graphState.hoverNode) {
      graphState.hoverNode = n;
      canvas.style.cursor = n ? 'pointer' : 'grab';
      draw();
    }
    if (n) {
      tooltip.innerHTML = `
        <div class="gt-title">${escapeHtml(n.label || n.id)}</div>
        <div class="gt-meta"><span class="gt-pill" style="background:${_srcColor(n.source)}">${escapeHtml(n.source)}</span> ${n.is_hub ? '<strong>(cluster hub)</strong>' : '· ' + (n.msgs || 0) + ' msgs'}</div>
        ${n.date ? `<div class="gt-meta">📅 ${escapeHtml(n.date)}</div>` : ''}`;
      tooltip.style.left = (sx + 12) + 'px';
      tooltip.style.top  = (sy + 12) + 'px';
      tooltip.style.display = 'block';
    } else {
      tooltip.style.display = 'none';
    }
  });
  function _updateUnpinBtn() {
    const btn = $('#graph-unpin-all');
    if (!btn) return;
    const hasPinned = nodes.some(n => n.fx !== null && n.fx !== undefined);
    btn.style.display = hasPinned ? '' : 'none';
  }

  window.addEventListener('mouseup', () => {
    if (dragNode) {
      const pinMode = $('#graph-pin-mode')?.checked ?? false;
      if (!pinMode) {
        dragNode.fx = null; dragNode.fy = null;  // release — physics takes over
        sim.alphaTarget(0);
      } else {
        // Sync x/y to pinned position, then kick sim so neighbours react
        dragNode.x = dragNode.fx;
        dragNode.y = dragNode.fy;
        sim.alpha(0.3).alphaTarget(0).restart();
      }
      dragNode = null;
      _updateUnpinBtn();
      draw();
    }
    dragging = false;
    canvas.style.cursor = graphState.hoverNode ? 'pointer' : 'grab';
  });

  // Right-click on a pinned node → unpin it
  canvas.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    const n = pickNode(sx, sy);
    if (n && n.fx != null) {
      n.fx = null; n.fy = null;
      if (!_simStopped) sim.alpha(0.15).restart();
      _updateUnpinBtn();
      draw();
    }
  });
  canvas.addEventListener('click', (e) => {
    if (moved) return;
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    const n = pickNode(sx, sy);
    if (n) {
      if (n.is_hub) {
        graphState.selectedSource = (graphState.selectedSource === n.source) ? null : n.source;
        graphState.selectedNodeId = null;
        _hideNodePanel();
      } else {
        graphState.selectedSource = null;
        graphState.selectedNodeId = n.id;
        _showNodePanel(n);
      }
    } else {
      graphState.selectedSource = null;
      graphState.selectedNodeId = null;
      _hideNodePanel();
    }
    draw();
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    const delta = -e.deltaY * 0.001;
    const newScale = Math.max(0.15, Math.min(6, scale * (1 + delta)));
    const wx = (sx - tx) / scale;
    const wy = (sy - ty) / scale;
    scale = newScale;
    tx = sx - wx * scale;
    ty = sy - wy * scale;
    draw();
  }, { passive: false });

  const N = nodes.length;
  const chargeScale = N > 500 ? 0.5 : 1;
  const sim = d3.forceSimulation(nodes)
    .force('link',    d3.forceLink(edges).id(d => d.id)
             .distance(d => d.is_cluster ? 60 : 30)
             .strength(d => d.is_cluster ? 0.25 : 0.6))
    .force('charge',  d3.forceManyBody().strength(d => (d.is_hub ? -500 : -50) * chargeScale))
    .force('center',  d3.forceCenter(w/2, h/2).strength(0.05))
    .force('x',       d3.forceX(w/2).strength(0.04))
    .force('y',       d3.forceY(h/2).strength(0.04))
    .force('collide', d3.forceCollide().radius(d => (d.size || 4) + 1))
    .alpha(1).alphaDecay(0.05);

  sim.on('tick', draw);

  let _simStopped = false;
  setTimeout(() => {
    if (_simStopped) return;
    sim.stop();
    _simStopped = true;
    const padding = 40;
    const xs = nodes.map(n => n.x).filter(v => v !== undefined);
    const ys = nodes.map(n => n.y).filter(v => v !== undefined);
    if (xs.length) {
      const minX = Math.min(...xs), maxX = Math.max(...xs);
      const minY = Math.min(...ys), maxY = Math.max(...ys);
      const dx = maxX - minX || 1, dy = maxY - minY || 1;
      scale = Math.min(0.95, Math.min(w / (dx + 2*padding), h / (dy + 2*padding)));
      tx = (w - scale * (minX + maxX)) / 2;
      ty = (h - scale * (minY + maxY)) / 2;
      draw();
    }
  }, 5000);

  currentGraph2D = { sim, draw };
  draw();
}

function drawForceGraph3D(container, data) {
  container.innerHTML = '';
  const THREE = window.THREE;

  const nodesCopy = data.nodes.map(n => ({...n}));
  const linksCopy = data.edges.map(e => ({
    source: typeof e.source === 'object' ? e.source.id : e.source,
    target: typeof e.target === 'object' ? e.target.id : e.target,
    is_cluster: e.is_cluster
  }));

  // ── Synaptic palette — warm gold + deep blue + violet, brain-cell vibe ──
  const PAL = {
    bg:       '#04060d',        // near-black ink with hint of blue
    halo:     0x6b8cff,         // outer glow ring
    syn:      0xffd166,          // synapse particle gold
    spark:    0xa78bff,          // secondary spark (violet)
    edge:     'rgba(120,160,255,0.18)',
    edgeHub:  'rgba(255,209,102,0.28)',
    edgeHi:   'rgba(255,255,255,0.85)',
    nodeDim:  'rgba(40,55,90,0.20)',
  };

  const Graph = ForceGraph3D()(container)
    .graphData({ nodes: nodesCopy, links: linksCopy })
    .backgroundColor(PAL.bg)
    .showNavInfo(false)
    .nodeId('id')
    // Stronger repulsion + slower decay → nodes spread out instead of clumping
    .d3VelocityDecay(0.35)
    .d3AlphaDecay(0.012)
    .nodeVal(node => node.is_hub ? 25 : (node.size || 5))
    .nodeColor(node => node.is_hub ? '#ffffff' : _srcColor(node.source))
    .nodeLabel(node => {
      const label = node.label || node.id;
      const msgs = node.msgs || 0;
      const isHub = node.is_hub;
      return `<div style="background: rgba(6,8,18,0.96); border: 1px solid ${_srcColor(node.source) || PAL.edgeHub}; padding: 10px 12px; border-radius: 8px; font-family: ui-monospace, monospace; box-shadow: 0 0 24px ${_srcColor(node.source)}44">
        <div style="font-weight: 700; color: #fff; letter-spacing:0.02em;">${escapeHtml(label)}</div>
        <div style="color: var(--text-dim); margin-top: 5px;">
          <span style="background:${_srcColor(node.source)}; padding: 2px 7px; border-radius: 4px; color:#000; font-size:9px; font-weight:700;">${escapeHtml(node.source)}</span>
          ${isHub ? '<strong style="color:#ffd166"> · synapse hub</strong>' : `<span style="color:#9aa3b8"> · ${msgs} msgs</span>`}
        </div>
        ${node.date ? `<div style="margin-top: 5px; font-size:10px; color:#9aa3b8;">📅 ${escapeHtml(node.date)}</div>` : ''}
      </div>`;
    })
    // Bezier curves — links arc like axons instead of straight lines
    .linkCurvature(link => link.is_cluster ? 0.25 : 0.10)
    .linkColor(link => link.is_cluster ? PAL.edgeHub : PAL.edge)
    .linkWidth(link => link.is_cluster ? 0.8 : 1.2)
    .linkOpacity(0.55)
    // Synaptic activity — particles pulse along each axon
    .linkDirectionalParticles(link => link.is_cluster ? 3 : 2)
    .linkDirectionalParticleSpeed(0.0045)
    .linkDirectionalParticleWidth(link => link.is_cluster ? 2.2 : 1.6)
    .linkDirectionalParticleColor(link => link.is_cluster ? '#ffd166' : '#a78bff')
    .onNodeClick(node => {
      if (node.is_hub) {
        graphState.selectedSource = (graphState.selectedSource === node.source) ? null : node.source;
        graphState.selectedNodeId = null;
        _hideNodePanel();
      } else {
        graphState.selectedSource = null;
        graphState.selectedNodeId = node.id;
        _showNodePanel(node);
      }
      update3DHighlight();
    });

  // Push nodes apart so they don't form one tight ball
  setTimeout(() => {
    try {
      const charge = Graph.d3Force('charge');
      if (charge) charge.strength(-120).distanceMax(380);
      const link = Graph.d3Force('link');
      if (link)   link.distance(50);
    } catch (_) {}
  }, 30);

  // ── Three.js scene tuning — add ambient + point lights + bloom-ish fog ──
  setTimeout(() => {
    try {
      const scene = Graph.scene();
      // Soft ambient so glowing nodes have lift
      scene.add(new THREE.AmbientLight(0x303450, 0.55));
      // Two warm directional sweeps simulate "neural depth"
      const l1 = new THREE.PointLight(0xffd166, 0.9, 1800);
      l1.position.set(400, 300, 400);
      scene.add(l1);
      const l2 = new THREE.PointLight(0xa78bff, 0.8, 1800);
      l2.position.set(-400, -200, -400);
      scene.add(l2);
      // Subtle fog — depth cue without killing the deep nodes
      scene.fog = new THREE.Fog(PAL.bg, 600, 2200);
    } catch (_) { /* ignore — Graph may not be ready */ }
  }, 50);

  Graph.nodeThreeObject(node => {
    if (!THREE) return null;
    const isHub = node.is_hub;
    const showL = $('#graph-show-labels')?.checked ?? false;
    const showH = $('#graph-show-hubs')?.checked ?? false;
    const size  = node.size || 4;
    // Smaller bubbles overall — user feedback "za duze"
    const radius = isHub ? 9 : Math.max(1.6, size * 0.45);
    const color  = isHub ? '#ffd166' : _srcColor(node.source);

    const group = new THREE.Group();

    // Inner core — small dense sphere that drives the eye
    const coreMat = new THREE.MeshBasicMaterial({
      color: color, transparent: true, opacity: isHub ? 1.0 : 0.85
    });
    const core = new THREE.Mesh(new THREE.SphereGeometry(radius * 0.55, 12, 12), coreMat);
    group.add(core);

    // Outer halo — much subtler now to avoid the "clump of bubbles" look
    const haloMat = new THREE.MeshBasicMaterial({
      color: color, transparent: true,
      opacity: isHub ? 0.30 : 0.10,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const halo = new THREE.Mesh(new THREE.SphereGeometry(radius * 1.4, 10, 10), haloMat);
    group.add(halo);

    // Hub-only: outer ring (axon corona) — makes hubs pop
    if (isHub) {
      const ringGeo = new THREE.RingGeometry(radius * 2.2, radius * 2.55, 32);
      const ringMat = new THREE.MeshBasicMaterial({
        color: 0xfff0c2, transparent: true, opacity: 0.4,
        side: THREE.DoubleSide, depthWrite: false,
      });
      const ring = new THREE.Mesh(ringGeo, ringMat);
      // Random axis = each hub has its own ring orientation
      ring.rotation.x = Math.random() * Math.PI;
      ring.rotation.y = Math.random() * Math.PI;
      group.add(ring);
      // Slow pulsing — animate via userData read in animation loop
      group.userData.pulse = { phase: Math.random() * Math.PI * 2, ring };
    }

    // Labels — kept lightweight (only big nodes or all if user opts in)
    const shouldLabel = isHub ? showH : (showL && size >= 8);
    if (shouldLabel) {
      const text = isHub ? (node.label || node.id).toUpperCase() : (node.label || node.id).slice(0, 35);
      const sprite = createTextSprite(text, isHub ? 22 : 13, '#ffffff',
                                       isHub ? '#ffd166' : null);
      if (sprite) {
        sprite.position.set(radius + 6, 0, 0);
        group.add(sprite);
      }
    }
    return group;
  });

  // Per-frame pulse on hub rings — gentle breathing
  Graph.onEngineTick(() => {
    const t = performance.now() / 1000;
    Graph.graphData().nodes.forEach(n => {
      const obj = n.__threeObj;
      if (obj && obj.userData && obj.userData.pulse) {
        const { phase, ring } = obj.userData.pulse;
        const s = 1 + Math.sin(t * 1.4 + phase) * 0.08;
        ring.scale.set(s, s, s);
        ring.rotation.z += 0.004;
      }
    });
  });

  // Slow camera orbit — subtle but adds liveness when idle
  let lastInteract = performance.now();
  container.addEventListener('mousedown', () => { lastInteract = performance.now(); });
  container.addEventListener('wheel',     () => { lastInteract = performance.now(); });
  (function autoOrbit() {
    requestAnimationFrame(autoOrbit);
    if (performance.now() - lastInteract < 5000) return;
    try {
      const cam = Graph.cameraPosition();
      const angle = 0.0008; // radians per frame
      const r = Math.hypot(cam.x, cam.z);
      const a = Math.atan2(cam.z, cam.x) + angle;
      Graph.cameraPosition({ x: r * Math.cos(a), y: cam.y, z: r * Math.sin(a) },
                            null, 0);
    } catch (_) {}
  })();

  function update3DHighlight() {
    const selSrc = graphState.selectedSource;
    const selNodeId = graphState.selectedNodeId;
    
    Graph.nodeColor(node => {
      const isHub = node.is_hub;
      if (selSrc) {
        if (isHub && node.source === selSrc) return '#ffffff';
        if (node.source === selSrc) return _srcColor(node.source);
        return 'rgba(50, 60, 80, 0.15)';
      }
      if (selNodeId) {
        if (node.id === selNodeId) return '#ffffff';
        const isConnected = linksCopy.some(e => 
          (e.source === selNodeId || e.source.id === selNodeId) && (e.target === node.id || e.target.id === node.id) ||
          (e.target === selNodeId || e.target.id === selNodeId) && (e.source === node.id || e.source.id === node.id)
        );
        if (isConnected) return _srcColor(node.source);
        return 'rgba(50, 60, 80, 0.15)';
      }
      return isHub ? '#ffffff' : _srcColor(node.source);
    });
    
    Graph.linkColor(link => {
      const s = link.source.id || link.source;
      const t = link.target.id || link.target;
      const color = link.is_cluster ? 'rgba(0, 225, 255, 0.25)' : 'rgba(255, 43, 214, 0.45)';
      
      if (selSrc) {
        const sourceMatch = (link.source.source || link.source) === selSrc || (link.target.source || link.target) === selSrc;
        return sourceMatch ? color : 'rgba(255, 255, 255, 0.02)';
      }
      if (selNodeId) {
        const nodeMatch = s === selNodeId || t === selNodeId;
        return nodeMatch ? color : 'rgba(255, 255, 255, 0.02)';
      }
      return color;
    });
    
    Graph.linkDirectionalParticles(link => {
      if (selSrc || selNodeId) return 0;
      return 2;
    });
  }

  update3DHighlight();

  currentGraph3D = {
    graph: Graph,
    element: container,
    updateHighlight: update3DHighlight
  };
}


// ============================================================================
// drawForceGraphCosmos — fundamentally different look from 3D Synapse:
//   - Notes rendered as ONE THREE.Points cloud (1 draw call, no per-node mesh).
//     Looks like a starfield, not balls of dots clumped into spheres.
//   - Hubs become bright "suns" with corona, anchored to ring positions per
//     source (each source = its own constellation orbiting its own axis).
//   - Background: dim starfield (2000 random stars in deep space).
//   - Connections rendered as thin glowing lines (not bezier — straight ray)
//     with low opacity so the cloud reads as constellations not spaghetti.
//   - Auto-rotate camera around Y axis (galactic plane).
// ============================================================================
function drawForceGraphCosmos(container, data) {
  container.innerHTML = '';
  const THREE = window.THREE;
  if (!THREE) {
    container.innerHTML = '<div style="padding:40px;color:#888">three.js not loaded</div>';
    return;
  }

  // -- Setup scene/camera/renderer --
  const W = container.clientWidth || 1200;
  const H = container.clientHeight || 700;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x02030a);
  scene.fog = new THREE.FogExp2(0x02030a, 0.0009);

  const camera = new THREE.PerspectiveCamera(55, W / H, 1, 3000);
  camera.position.set(0, 80, 380);
  camera.lookAt(0, 0, 0);

  const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(W, H);
  container.appendChild(renderer.domElement);

  // Lights — minimal, points are self-luminous via vertex colors
  scene.add(new THREE.AmbientLight(0x202840, 0.6));

  // -- Background starfield --
  const STAR_COUNT = 1800;
  const starGeo = new THREE.BufferGeometry();
  const starPos = new Float32Array(STAR_COUNT * 3);
  for (let i = 0; i < STAR_COUNT; i++) {
    // sphere shell of radius ~1500
    const r = 1100 + Math.random() * 700;
    const t = Math.random() * Math.PI * 2;
    const f = Math.acos(2 * Math.random() - 1);
    starPos[i*3]   = r * Math.sin(f) * Math.cos(t);
    starPos[i*3+1] = r * Math.sin(f) * Math.sin(t);
    starPos[i*3+2] = r * Math.cos(f);
  }
  starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
  const starMat = new THREE.PointsMaterial({
    color: 0xb8c5e8, size: 1.5, sizeAttenuation: false,
    transparent: true, opacity: 0.55, depthWrite: false,
  });
  scene.add(new THREE.Points(starGeo, starMat));

  // -- Group notes by source, lay out as "constellations" --
  // Each source gets its own anchor on a horizontal ring; notes scatter around
  // their anchor like stars around a galactic core.
  const sources = {};
  data.nodes.forEach(n => {
    const s = n.source || 'unknown';
    if (!sources[s]) sources[s] = {hubs: [], notes: []};
    if (n.is_hub) sources[s].hubs.push(n);
    else          sources[s].notes.push(n);
  });
  const sourceList = Object.keys(sources);
  const ANCHOR_R = 220;
  const anchors = {};   // source → {x,y,z} anchor pos
  sourceList.forEach((s, i) => {
    const a = (i / sourceList.length) * Math.PI * 2;
    anchors[s] = {
      x: ANCHOR_R * Math.cos(a),
      y: (i % 2 === 0 ? 1 : -1) * 25 * Math.random(),  // tilt
      z: ANCHOR_R * Math.sin(a),
      angle: a,
    };
  });

  // -- Notes as Points cloud (single draw call for ~1600 stars) --
  const allNotes = data.nodes.filter(n => !n.is_hub);
  const notesGeo = new THREE.BufferGeometry();
  const notePos  = new Float32Array(allNotes.length * 3);
  const noteCol  = new Float32Array(allNotes.length * 3);
  const noteSize = new Float32Array(allNotes.length);
  const nodeIndex = new Map();      // node.id → index in points buffer
  allNotes.forEach((n, i) => {
    nodeIndex.set(n.id, i);
    const anc = anchors[n.source] || {x: 0, y: 0, z: 0};
    // scatter around anchor: spherical normal-ish dist
    const r  = 40 + Math.pow(Math.random(), 0.5) * 90;
    const t  = Math.random() * Math.PI * 2;
    const f  = Math.acos(2 * Math.random() - 1);
    notePos[i*3]   = anc.x + r * Math.sin(f) * Math.cos(t);
    notePos[i*3+1] = anc.y + r * Math.sin(f) * Math.sin(t) * 0.5;  // flatter Y
    notePos[i*3+2] = anc.z + r * Math.cos(f);
    const c = new THREE.Color(_srcColor(n.source));
    noteCol[i*3]   = c.r;
    noteCol[i*3+1] = c.g;
    noteCol[i*3+2] = c.b;
    noteSize[i] = Math.max(1.5, Math.min(6, (n.size || 4) * 0.6));
  });
  notesGeo.setAttribute('position', new THREE.BufferAttribute(notePos, 3));
  notesGeo.setAttribute('color',    new THREE.BufferAttribute(noteCol, 3));
  // Custom shader so we get per-point size + circular (not square) sprite
  const noteMat = new THREE.ShaderMaterial({
    uniforms: { uTime: {value: 0} },
    vertexShader: `
      attribute float size;
      varying vec3 vColor;
      void main() {
        vColor = color;
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = size * (300.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      varying vec3 vColor;
      void main() {
        // soft circular sprite with bloom-ish edge
        vec2 c = gl_PointCoord - 0.5;
        float d = length(c);
        if (d > 0.5) discard;
        float alpha = smoothstep(0.5, 0.0, d) * 0.95;
        // brighter core
        float core = smoothstep(0.3, 0.0, d);
        vec3 col = mix(vColor, vec3(1.0), core * 0.55);
        gl_FragColor = vec4(col, alpha);
      }`,
    vertexColors: true,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  // ShaderMaterial doesn't auto-pick up the 'size' attribute name unless declared
  notesGeo.setAttribute('size', new THREE.BufferAttribute(noteSize, 1));
  const notesCloud = new THREE.Points(notesGeo, noteMat);
  scene.add(notesCloud);

  // -- Hubs as glowing "suns" with corona --
  const hubMeshes = {};
  Object.entries(sources).forEach(([src, grp]) => {
    grp.hubs.forEach(h => {
      const anc = anchors[src] || {x:0,y:0,z:0};
      const g = new THREE.Group();
      g.position.set(anc.x, anc.y, anc.z);
      const color = _srcColor(src);
      // bright core
      const core = new THREE.Mesh(
        new THREE.SphereGeometry(7, 24, 24),
        new THREE.MeshBasicMaterial({color: color}),
      );
      g.add(core);
      // corona — outer additive sphere
      const corona = new THREE.Mesh(
        new THREE.SphereGeometry(18, 16, 16),
        new THREE.MeshBasicMaterial({
          color: color, transparent: true, opacity: 0.25,
          blending: THREE.AdditiveBlending, depthWrite: false,
        }),
      );
      g.add(corona);
      // accretion ring (galaxy disk style)
      const ringGeo = new THREE.RingGeometry(28, 32, 64);
      const ringMat = new THREE.MeshBasicMaterial({
        color: color, transparent: true, opacity: 0.35,
        side: THREE.DoubleSide, depthWrite: false,
      });
      const ring = new THREE.Mesh(ringGeo, ringMat);
      ring.rotation.x = Math.PI / 2 + (Math.random() - 0.5) * 0.6;
      g.add(ring);
      g.userData = { srcAngle: anc.angle, ring, corona, src, hubNode: h };
      scene.add(g);
      hubMeshes[h.id] = g;
    });
  });

  // -- Connections — only render top 600 links by importance to keep clean --
  const linkLimit = Math.min(600, data.edges.length);
  const linkSubset = data.edges.slice(0, linkLimit);
  const linkPos = new Float32Array(linkSubset.length * 6);  // 2 verts per link
  const linkCol = new Float32Array(linkSubset.length * 6);
  let li = 0;
  linkSubset.forEach(e => {
    const sId = typeof e.source === 'object' ? e.source.id : e.source;
    const tId = typeof e.target === 'object' ? e.target.id : e.target;
    const sIdx = nodeIndex.get(sId);
    const tIdx = nodeIndex.get(tId);
    let sx, sy, sz, tx, ty, tz;
    if (sIdx != null) { sx = notePos[sIdx*3]; sy = notePos[sIdx*3+1]; sz = notePos[sIdx*3+2]; }
    else if (hubMeshes[sId]) { const p = hubMeshes[sId].position; sx=p.x; sy=p.y; sz=p.z; }
    else return;
    if (tIdx != null) { tx = notePos[tIdx*3]; ty = notePos[tIdx*3+1]; tz = notePos[tIdx*3+2]; }
    else if (hubMeshes[tId]) { const p = hubMeshes[tId].position; tx=p.x; ty=p.y; tz=p.z; }
    else return;
    linkPos[li*6]   = sx; linkPos[li*6+1] = sy; linkPos[li*6+2] = sz;
    linkPos[li*6+3] = tx; linkPos[li*6+4] = ty; linkPos[li*6+5] = tz;
    const c = e.is_cluster ? new THREE.Color('#fff5d6') : new THREE.Color('#7a9bff');
    linkCol[li*6]   = c.r; linkCol[li*6+1] = c.g; linkCol[li*6+2] = c.b;
    linkCol[li*6+3] = c.r; linkCol[li*6+4] = c.g; linkCol[li*6+5] = c.b;
    li++;
  });
  const linkGeo = new THREE.BufferGeometry();
  linkGeo.setAttribute('position', new THREE.BufferAttribute(linkPos.subarray(0, li*6), 3));
  linkGeo.setAttribute('color',    new THREE.BufferAttribute(linkCol.subarray(0, li*6), 3));
  const linkMat = new THREE.LineBasicMaterial({
    vertexColors: true, transparent: true, opacity: 0.10,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });
  scene.add(new THREE.LineSegments(linkGeo, linkMat));

  // -- Camera controls (light orbit + zoom on wheel + drag pan) --
  let camAngle = 0, camY = 80, camR = 380, camTarget = new THREE.Vector3(0,0,0);
  let dragging = false, lastX = 0, lastY = 0, lastInteract = performance.now();
  container.addEventListener('mousedown', (e) => {
    dragging = true; lastX = e.clientX; lastY = e.clientY;
    lastInteract = performance.now();
  });
  window.addEventListener('mouseup', () => { dragging = false; });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    camAngle += (e.clientX - lastX) * 0.01;
    camY = Math.max(-300, Math.min(400, camY - (e.clientY - lastY) * 0.8));
    lastX = e.clientX; lastY = e.clientY;
    lastInteract = performance.now();
  });
  container.addEventListener('wheel', (e) => {
    e.preventDefault();
    camR = Math.max(60, Math.min(1000, camR + e.deltaY * 0.6));
    lastInteract = performance.now();
  }, { passive: false });

  // -- Animate --
  function tick() {
    if (!container.isConnected) return;   // panel torn down
    requestAnimationFrame(tick);
    // Auto-orbit slowly when user hasn't touched it for 4s
    if (performance.now() - lastInteract > 4000) {
      camAngle += 0.0015;
    }
    camera.position.set(camR * Math.cos(camAngle), camY, camR * Math.sin(camAngle));
    camera.lookAt(camTarget);
    // Pulse hubs (gentle breathing) + slowly rotate corona ring
    const t = performance.now() / 1000;
    Object.values(hubMeshes).forEach((g, i) => {
      const breathe = 1 + Math.sin(t * 1.0 + i * 0.7) * 0.06;
      g.userData.corona.scale.setScalar(breathe);
      g.userData.ring.rotation.z += 0.003;
    });
    // Slowly drift the entire notes cloud (galactic rotation)
    notesCloud.rotation.y += 0.0005;
    renderer.render(scene, camera);
  }
  tick();

  // -- Resize handling --
  const ro = new ResizeObserver(() => {
    const w = container.clientWidth, h = container.clientHeight;
    if (w && h) {
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }
  });
  ro.observe(container);

  currentGraph3D = {
    element: container,
    cleanup: () => { ro.disconnect(); renderer.dispose(); },
  };
}


// ============================================================================
// drawForceGraphMycelium — Bioluminescent underground fungal network
//   - Dark near-black underground atmosphere, dense fog
//   - Nodes as multi-layer glowing bioluminescent cells
//   - Hub nodes with radial filament tendrils + pulsing ring
//   - Hyphae links: organic curves, glowing green particles (nutrient flow)
//   - 2500 floating spore particles drifting upward in the dark
//   - Slow auto-orbit for living feel
// ============================================================================
function drawForceGraphMycelium(container, data) {
  container.innerHTML = '';
  const THREE = window.THREE;
  if (!THREE) {
    container.innerHTML = '<div style="padding:40px;color:#888">three.js not loaded</div>';
    return;
  }

  const nodesCopy = data.nodes.map(n => ({...n}));
  const linksCopy = data.edges.map(e => ({
    source: typeof e.source === 'object' ? e.source.id : e.source,
    target: typeof e.target === 'object' ? e.target.id : e.target,
    is_cluster: e.is_cluster
  }));

  // Bioluminescent color palette — override _srcColor for vivid mycelium hues
  const MYCEL_PAL = {
    'claude-ai':   '#00ff88',
    'claude-code': '#00e5cc',
    'chatgpt':     '#44ddff',
    'grok':        '#aaff33',
    'antigravity': '#ffcc00',
    'manual':      '#ff88cc',
  };
  function mColor(source) {
    return MYCEL_PAL[source] || _srcColor(source) || '#00bb77';
  }
  function mColorHex(source) {
    return parseInt(mColor(source).replace('#',''), 16);
  }

  const BG       = '#040e08';
  const FOG_HEX  = 0x040e08;
  const HUB_COL  = 0x00ffaa;
  const SPORE_C  = 0x006633;
  const PART_COL = '#66ffbb';
  const EDGE_REG = 'rgba(0,200,100,0.55)';   // hyphae threads — main visual
  const EDGE_HUB = 'rgba(0,255,160,0.85)';   // cluster hyphae — bright

  const Graph = ForceGraph3D()(container)
    .graphData({ nodes: nodesCopy, links: linksCopy })
    .backgroundColor(BG)
    .showNavInfo(false)
    .nodeId('id')
    .d3VelocityDecay(0.55)   // more damping = settle faster
    .d3AlphaDecay(0.022)
    // Hub nodeVal=6 not 30 — prevents galaxy clusters dominated by one hub
    .nodeVal(n => n.is_hub ? 6 : Math.max(1, (n.size || 3) * 0.4))
    .nodeColor(n => n.is_hub ? '#00ffaa' : mColor(n.source))
    .nodeLabel(node => {
      const c = mColor(node.source);
      return `<div style="background:rgba(3,12,7,0.97);border:1px solid ${c}66;padding:10px 12px;border-radius:8px;font-family:ui-monospace,monospace;box-shadow:0 0 20px ${c}44">
        <div style="font-weight:700;color:#d0ffe8;">${escapeHtml(node.label||node.id)}</div>
        <div style="margin-top:5px;">
          <span style="background:${c};padding:2px 7px;border-radius:4px;color:#000;font-size:9px;font-weight:700;">${escapeHtml(node.source)}</span>
          ${node.is_hub ? '<strong style="color:#00ff88"> · mycelium hub</strong>' : `<span style="color:#55aa77"> · ${node.msgs||0} msgs</span>`}
        </div>
        ${node.date?`<div style="margin-top:5px;font-size:10px;color:#448855;">📅 ${escapeHtml(node.date)}</div>`:''}
      </div>`;
    })
    // Hyphae: fat, nearly straight, high opacity — the THREAD is the visual star
    .linkCurvature(l => l.is_cluster ? 0.08 : 0.04)
    .linkColor(l => l.is_cluster ? EDGE_HUB : EDGE_REG)
    .linkWidth(l => l.is_cluster ? 3.5 : 1.8)   // thick hyphae threads
    .linkOpacity(0.88)
    // Nutrient flow — reduced count for performance
    .linkDirectionalParticles(l => l.is_cluster ? 2 : 1)
    .linkDirectionalParticleSpeed(0.006)
    .linkDirectionalParticleWidth(l => l.is_cluster ? 2.5 : 1.8)
    .linkDirectionalParticleColor(() => PART_COL)
    .onNodeClick(node => {
      if (node.is_hub) {
        graphState.selectedSource = (graphState.selectedSource === node.source) ? null : node.source;
        graphState.selectedNodeId = null;
        _hideNodePanel();
      } else {
        graphState.selectedSource = null;
        graphState.selectedNodeId = node.id;
        _showNodePanel(node);
      }
      _updateMycelHighlight();
    });

  // d3 force — weak repulsion = even spread, no galaxy clusters
  setTimeout(() => {
    try {
      const ch = Graph.d3Force('charge');
      if (ch) ch.strength(-45).distanceMax(300);
      const lk = Graph.d3Force('link');
      if (lk) lk.distance(32);
      // Z-compression: pull all nodes toward z=0 → flat mycelium mat on substrate
      Graph.d3Force('z-compress', () => {
        nodesCopy.forEach(n => { if (n.z) n.vz = (n.vz || 0) - n.z * 0.04; });
      });
    } catch(_) {}
  }, 50);

  // Scene: underground bioluminescent lighting + dense fog
  // 300ms — ForceGraph3D needs a render tick before scene() is stable on large graphs
  setTimeout(() => {
    try {
      const scene = Graph.scene();
      if (!scene) return;
      scene.fog = new THREE.FogExp2(FOG_HEX, 0.0004);
      scene.add(new THREE.AmbientLight(0x062010, 0.9));
      const l1 = new THREE.PointLight(0x00ff88, 0.55, 1100);
      l1.position.set(200, 120, 200);
      scene.add(l1);
      const l2 = new THREE.PointLight(0x00ccff, 0.40, 900);
      l2.position.set(-180, -100, -180);
      scene.add(l2);
      const l3 = new THREE.PointLight(0x88ff44, 0.25, 700);
      l3.position.set(0, 280, 0);
      scene.add(l3);
    } catch(_) {}
  }, 300);

  // Floating spore particles — reduced for performance
  setTimeout(() => {
    try {
      const scene = Graph.scene();
      if (!scene) return;
      const SPORE_N = 600;
      const sgeo = new THREE.BufferGeometry();
      const spos = new Float32Array(SPORE_N * 3);
      const svel = new Float32Array(SPORE_N * 3);
      for (let i = 0; i < SPORE_N; i++) {
        const r = 80 + Math.random() * 380;
        const th = Math.random() * Math.PI * 2;
        const ph = Math.acos(2 * Math.random() - 1);
        spos[i*3]   = r * Math.sin(ph) * Math.cos(th);
        spos[i*3+1] = r * Math.sin(ph) * Math.sin(th);
        spos[i*3+2] = r * Math.cos(ph);
        svel[i*3]   = (Math.random() - 0.5) * 0.018;
        svel[i*3+1] = Math.random() * 0.022;      // drift upward
        svel[i*3+2] = (Math.random() - 0.5) * 0.018;
      }
      sgeo.setAttribute('position', new THREE.BufferAttribute(spos, 3));
      const smat = new THREE.PointsMaterial({
        color: SPORE_C, size: 1.1, sizeAttenuation: false,
        transparent: true, opacity: 0.55, depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      const spores = new THREE.Points(sgeo, smat);
      spores.userData = { vel: svel, count: SPORE_N };
      scene.add(spores);
      scene.userData.mycelSpores = spores;
    } catch(_) {}
  }, 400);

  // PERFORMANCE: return null for regular nodes → ForceGraph uses fast GPU-instanced spheres
  // Custom objects ONLY for hub nodes (~7 total)
  Graph.nodeThreeObject(node => {
    if (!THREE) return null;
    if (!node.is_hub) return null;  // ← default instanced sphere, 10× faster

    const radius = 9;
    const chex   = HUB_COL;
    const cstr   = '#00ffaa';
    const phase  = Math.random() * Math.PI * 2;

    const group = new THREE.Group();

    // Core sphere
    group.add(new THREE.Mesh(
      new THREE.SphereGeometry(radius * 0.55, 12, 12),
      new THREE.MeshBasicMaterial({ color: chex })
    ));
    // Inner glow
    group.add(new THREE.Mesh(
      new THREE.SphereGeometry(radius, 10, 10),
      new THREE.MeshBasicMaterial({
        color: chex, transparent: true, opacity: 0.55,
        blending: THREE.AdditiveBlending, depthWrite: false,
      })
    ));
    // Outer diffuse corona
    group.add(new THREE.Mesh(
      new THREE.SphereGeometry(radius * 2.4, 8, 8),
      new THREE.MeshBasicMaterial({
        color: chex, transparent: true, opacity: 0.12,
        blending: THREE.AdditiveBlending, depthWrite: false,
      })
    ));
    // Slow-pulsing ring
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(radius * 1.7, radius * 2.0, 32),
      new THREE.MeshBasicMaterial({
        color: chex, transparent: true, opacity: 0.25,
        side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending,
      })
    );
    ring.rotation.x = Math.random() * Math.PI;
    group.add(ring);

    // Label
    const showH = $('#graph-show-hubs')?.checked ?? false;
    if (showH) {
      const sprite = createTextSprite((node.label||node.id).toUpperCase(), 22, '#d0ffe8', cstr);
      if (sprite) { sprite.position.set(radius + 6, 0, 0); group.add(sprite); }
    }

    group.userData.mycelHub = { ring, phase };
    return group;
  });

  // Per-frame: only animate hub rings + drift spores (NOT all 1655 nodes)
  Graph.onEngineTick(() => {
    const t = performance.now() / 1000;

    // Hub ring pulse — only ~7 nodes, negligible cost
    Graph.graphData().nodes.forEach(n => {
      const obj = n.__threeObj;
      if (!obj || !obj.userData || !obj.userData.mycelHub) return;
      const { ring, phase } = obj.userData.mycelHub;
      const s = 1 + Math.sin(t * 1.2 + phase) * 0.12;
      ring.scale.set(s, s, s);
      ring.rotation.z += 0.003;
    });

    // Drift spores
    try {
      const spores = Graph.scene().userData.mycelSpores;
      if (spores) {
        const pos = spores.geometry.attributes.position.array;
        const vel = spores.userData.vel;
        const N   = spores.userData.count;
        for (let i = 0; i < N; i++) {
          pos[i*3]   += vel[i*3];
          pos[i*3+1] += vel[i*3+1];
          pos[i*3+2] += vel[i*3+2];
          const d2 = pos[i*3]**2 + pos[i*3+1]**2 + pos[i*3+2]**2;
          if (d2 > 400*400) {
            const sc = (60 + Math.random() * 60) / Math.sqrt(d2);
            pos[i*3] *= sc; pos[i*3+1] *= sc; pos[i*3+2] *= sc;
          }
        }
        spores.geometry.attributes.position.needsUpdate = true;
      }
    } catch(_) {}
  });

  // Slow auto-orbit (5s after last interaction)
  let lastInteract = performance.now();
  container.addEventListener('mousedown', () => { lastInteract = performance.now(); });
  container.addEventListener('wheel',     () => { lastInteract = performance.now(); });
  (function autoOrbit() {
    requestAnimationFrame(autoOrbit);
    if (performance.now() - lastInteract < 5000) return;
    try {
      const cam = Graph.cameraPosition();
      const r = Math.hypot(cam.x, cam.z);
      const a = Math.atan2(cam.z, cam.x) + 0.0006;
      Graph.cameraPosition({ x: r*Math.cos(a), y: cam.y, z: r*Math.sin(a) }, null, 0);
    } catch(_) {}
  })();

  function _updateMycelHighlight() {
    const selSrc = graphState.selectedSource;
    const selId  = graphState.selectedNodeId;

    Graph.nodeColor(node => {
      const c = node.is_hub ? '#ffffff' : mColor(node.source);
      if (selSrc) {
        if (node.is_hub && node.source === selSrc) return '#ffffff';
        return node.source === selSrc ? c : 'rgba(5,20,10,0.12)';
      }
      if (selId) {
        if (node.id === selId) return '#ffffff';
        const conn = linksCopy.some(e =>
          (e.source===selId||e.source?.id===selId) && (e.target===node.id||e.target?.id===node.id) ||
          (e.target===selId||e.target?.id===selId) && (e.source===node.id||e.source?.id===node.id)
        );
        return conn ? c : 'rgba(5,20,10,0.12)';
      }
      return c;
    });

    Graph.linkColor(l => {
      const color = l.is_cluster ? EDGE_HUB : EDGE_REG;
      if (selSrc) {
        const m = (l.source?.source||l.source)===selSrc||(l.target?.source||l.target)===selSrc;
        return m ? color : 'rgba(0,255,100,0.008)';
      }
      if (selId) {
        const s=l.source?.id||l.source, t=l.target?.id||l.target;
        return (s===selId||t===selId) ? color : 'rgba(0,255,100,0.008)';
      }
      return color;
    });

    Graph.linkDirectionalParticles(l => (selSrc||selId) ? 0 : (l.is_cluster ? 4 : 2));
  }

  _updateMycelHighlight();

  currentGraph3D = {
    graph: Graph,
    element: container,
    updateHighlight: _updateMycelHighlight,
  };
}


function createTextSprite(text, fontSize, textColor, outlineColor) {
  const THREE = window.THREE;
  if (!THREE) return null;
  
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  
  ctx.font = `bold ${fontSize}px ui-monospace, monospace`;
  const textWidth = ctx.measureText(text).width;
  
  canvas.width = textWidth + 24;
  canvas.height = fontSize + 12;
  
  ctx.font = `bold ${fontSize}px ui-monospace, monospace`;
  ctx.textBaseline = 'middle';
  
  if (outlineColor) {
    ctx.strokeStyle = outlineColor;
    ctx.lineWidth = 4;
    ctx.lineJoin = 'round';
    ctx.strokeText(text, 12, canvas.height / 2);
  } else {
    ctx.strokeStyle = '#0a0e1a';
    ctx.lineWidth = 3;
    ctx.lineJoin = 'round';
    ctx.strokeText(text, 12, canvas.height / 2);
  }
  
  ctx.fillStyle = textColor;
  ctx.fillText(text, 12, canvas.height / 2);
  
  const texture = new THREE.CanvasTexture(canvas);
  const spriteMaterial = new THREE.SpriteMaterial({ map: texture, transparent: true });
  const sprite = new THREE.Sprite(spriteMaterial);
  
  sprite.scale.set(canvas.width / 4, canvas.height / 4, 1);
  return sprite;
}
// Floating side-panel triggered by clicking a graph node
async function _showNodePanel(d) {
  let panel = $('#graph-node-panel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'graph-node-panel';
    panel.className = 'graph-node-panel';
    document.body.appendChild(panel);
  }
  // Loading skeleton
  panel.innerHTML = `
    <div class="gnp-head">
      <span class="gnp-source" style="background:${_srcColor(d.source) + '33'};color:${_srcColor(d.source)}">${escapeHtml(d.source || '?')}</span>
      <button class="gnp-close" title="close">✕</button>
    </div>
    <div class="gnp-title">${escapeHtml(d.label || d.id)}</div>
    <div class="gnp-meta">${d.msgs || 0} msgs · ${escapeHtml(d.id)}</div>
    <div class="gnp-preview" id="gnp-preview">ładuję treść…</div>
    <div class="gnp-actions">
      <button class="opt-btn" data-action="open-vault">📂 OPEN VAULT FOLDER</button>
      <button class="opt-btn" data-action="copy-path">⎘ COPY PATH</button>
      <button class="opt-btn" data-action="search-related">🔍 RAG: related notes</button>
    </div>`;
  panel.style.display = 'block';

  // Fetch preview content via vault filesystem MCP-like endpoint
  try {
    const r = await fetch('/api/vault/notes?limit=1000');
    const j = await r.json();
    const match = (j.notes || []).find(n => n.name === d.id || n.rel?.endsWith(d.id));
    const previewEl = $('#gnp-preview');
    if (match && match.rel) {
      // Use a generic read — we don't have direct read endpoint, so try fetch-like via path
      try {
        const r2 = await fetch('/api/vault/read?path=' + encodeURIComponent(match.rel));
        if (r2.ok) {
          const txt = await r2.text();
          previewEl.textContent = txt.length > 2000 ? txt.slice(0, 2000) + '\n…(skrócono)' : txt;
        } else {
          previewEl.innerHTML = `<em>${match.name} · ${match.size_kb} KB</em><br><span style="color:var(--text-dim)">Nie udało się załadować treści.</span>`;
        }
      } catch {
        previewEl.innerHTML = `<em>${match.name}</em>`;
      }
    } else {
      previewEl.innerHTML = `<span style="color:var(--text-dim)">Nie znalazłem ${escapeHtml(d.id)} w vault.</span>`;
    }
  } catch (e) {
    $('#gnp-preview').textContent = 'błąd ładowania: ' + e.message;
  }

  // Wire actions
  panel.querySelector('.gnp-close').onclick = () => _hideNodePanel();
  panel.querySelector('[data-action="open-vault"]').onclick = () => fetch('/api/vault/open', {method: 'POST'});
  panel.querySelector('[data-action="copy-path"]').onclick = async () => {
    try { await navigator.clipboard.writeText(d.id || ''); _showToast('Skopiowano nazwę pliku', 'ok'); } catch {}
  };
  panel.querySelector('[data-action="search-related"]').onclick = async () => {
    // Use the note title (without date prefix) as query
    const q = (d.label || d.id || '').replace(/^\d{4}-\d{2}-\d{2}_[a-z-]+_/i, '').replace(/_[0-9a-f]{8}$/i, '').replace(/_/g, ' ');
    const r = await fetch('/api/library/search', {
      method: 'POST', headers: {'content-type': 'application/json'},
      body: JSON.stringify({query: q, top_k: 8}),
    });
    const j = await r.json();
    const previewEl = $('#gnp-preview');
    previewEl.innerHTML = `<div style="color:var(--cyan);font-size:11px;margin-bottom:8px">RAG: "${escapeHtml(q)}"</div>` +
      (j.hits || []).map(h => `<div style="margin-bottom:8px;padding:6px;background:rgba(0,0,0,0.3);border-radius:4px;border-left:2px solid var(--cyan)">
        <div style="font-family:var(--mono);font-size:10px;color:var(--cyan)">${escapeHtml(h.pdf)} · p${h.page} · ${h.score}</div>
        <div style="font-size:11px;color:var(--text-dim);margin-top:4px">${escapeHtml(h.text.slice(0, 200))}…</div>
      </div>`).join('');
  };
}

function _hideNodePanel() {
  const panel = $('#graph-node-panel');
  if (panel) panel.style.display = 'none';
}

function _applyGraphLabelToggles() {
  const showHubs = $('#graph-show-hubs')?.checked ?? false;
  const legend = $('#graph-legend');
  if (legend) {
    legend.style.display = showHubs ? 'flex' : 'none';
  }

  const theme = $('#graph-theme')?.value || '2d';
  if (theme === '2d') {
    if (currentGraph2D && currentGraph2D.draw) {
      currentGraph2D.draw();
    }
  } else if (theme === '3d') {
    if (currentGraph3D && currentGraph3D.graph) {
      currentGraph3D.graph.nodeThreeObject(currentGraph3D.graph.nodeThreeObject());
    }
  }
}

function initGraph() {
  $('#graph-refresh').onclick = renderGraph;
  $('#graph-show-labels').onchange = _applyGraphLabelToggles;
  $('#graph-show-hubs').onchange = _applyGraphLabelToggles;

  // Pin mode toggle
  const pinCb = $('#graph-pin-mode');
  if (pinCb) {
    const saved = localStorage.getItem('brain.graphPinMode') === 'true';
    pinCb.checked = saved;
    pinCb.onchange = () => {
      localStorage.setItem('brain.graphPinMode', pinCb.checked);
      if (!pinCb.checked) {
        // Turning off pin mode — release all pinned nodes
        const ns = graphState.nodes2d;
        if (ns) ns.forEach(n => { n.fx = null; n.fy = null; });
        const btn = $('#graph-unpin-all');
        if (btn) btn.style.display = 'none';
      }
    };
  }

  // Unpin all button
  const unpinBtn = $('#graph-unpin-all');
  if (unpinBtn) {
    unpinBtn.onclick = () => {
      const ns = graphState.nodes2d;
      if (ns) {
        ns.forEach(n => { n.fx = null; n.fy = null; });
        unpinBtn.style.display = 'none';
      }
    };
  }
  
  const themeSel = $('#graph-theme');
  if (themeSel) {
    themeSel.onchange = () => {
      localStorage.setItem('brain.graphTheme', themeSel.value);
      _toggleGraphTheme();
    };
    const savedTheme = localStorage.getItem('brain.graphTheme') || '2d';
    themeSel.value = savedTheme;
  }
}

// ============================================================================
// BRAIN: LIBRARY
// ============================================================================
let libPollTimer = null;

async function renderLibrary() {
  const body = $('#lib-body');
  try {
    const [d, ragS] = await Promise.all([
      fetch('/api/library').then(r => r.json()),
      fetch('/api/library/status').then(r => r.json()).catch(() => ({})),
    ]);

    let banner = '';
    if (ragS.state === 'indexing') {
      const pct = ragS.total_pdfs ? Math.round(100 * (ragS.done_pdfs || 0) / ragS.total_pdfs) : 0;
      banner = `<div class="lib-banner indexing">
        ⏳ indexing ${ragS.done_pdfs}/${ragS.total_pdfs} files · current: <code>${escapeHtml((ragS.current||'').slice(0,40))}</code> · ${ragS.indexed_chunks||0} chunks so far
        <div class="dp-bar" style="margin-top:6px"><div class="dp-fill" style="width:${pct}%"></div></div>
      </div>`;
      if (!libPollTimer) libPollTimer = setInterval(renderLibrary, 2000);
    } else {
      if (libPollTimer) { clearInterval(libPollTimer); libPollTimer = null; }
      if (d.needs_reindex) {
        banner = `<div class="lib-banner needs">
          ⚠ ${d.files_count} files in library but index is out of date — auto-reindex will start in &lt;30s, or click REINDEX now
        </div>`;
      }
    }

    const reindexBtn = $('#lib-reindex');
    if (reindexBtn) { reindexBtn.disabled = false; reindexBtn.title = 'rebuild semantic index'; }

    if (!d.files_count) {
      body.innerHTML = `${banner}<div class="lib-empty">drop PDFs / EPUB / MOBI / DOCX / TXT into <code>${escapeHtml(d.path || 'data/library')}</code><br><small>auto-reindex co 30s · supported: pdf, epub, mobi, azw3, docx, txt, md, html</small></div>`;
      return;
    }

    body.innerHTML = `
      ${banner}
      <div class="lib-head-row">
        <div class="lib-stat"><span class="lib-stat-label">FILES</span><span>${d.files_count}</span></div>
        <div class="lib-stat"><span class="lib-stat-label">SIZE</span><span>${d.size_mb} MB</span></div>
        <div class="lib-stat"><span class="lib-stat-label">INDEXED</span><span>${ragS.indexed_chunks||0} chunks</span></div>
        <div class="lib-stat"><span class="lib-stat-label">EMBED MODEL</span><span style="font-size:11px">${escapeHtml(ragS.model || 'nomic-embed-text')}</span></div>
      </div>
      <div class="lib-files">
        ${d.files.map(f => `<div class="lib-file"><div>${escapeHtml(f.rel)} <span style="color:var(--cyan);font-size:9px">${(f.ext||'').toUpperCase()}</span></div><div>${f.size_mb} MB</div></div>`).join('')}
      </div>`;
  } catch (e) {
    body.innerHTML = `<div class="lib-empty">load failed: ${escapeHtml(e.message)}</div>`;
  }
}
function _setupDropZone(elementId, uploadUrl, onSuccess) {
  const zone = document.getElementById(elementId);
  if (!zone) return;
  ['dragenter', 'dragover'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); e.stopPropagation();
    zone.classList.add('drop-active');
  }));
  ['dragleave', 'drop'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault(); e.stopPropagation();
    if (ev === 'dragleave' && zone.contains(e.relatedTarget)) return;
    zone.classList.remove('drop-active');
  }));
  zone.addEventListener('drop', async e => {
    const files = [...(e.dataTransfer?.files || [])];
    if (!files.length) return;
    for (const f of files) {
      const fd = new FormData();
      fd.append('file', f, f.name);
      // Show progress indicator
      const toast = _showToast(`uploading ${f.name}...`, 'info');
      try {
        const r = await fetch(uploadUrl, { method: 'POST', body: fd });
        const d = await r.json();
        if (r.ok) {
          _updateToast(toast, `✓ uploaded ${d.name} (${d.size_mb} MB)`, 'ok');
        } else {
          _updateToast(toast, `✗ ${d.detail || 'upload failed'}`, 'err');
        }
      } catch (err) {
        _updateToast(toast, `✗ ${err.message}`, 'err');
      }
    }
    if (onSuccess) onSuccess();
  });
}

function _showToast(msg, kind = 'info', autoDismissMs = 0) {
  let cont = document.getElementById('toast-cont');
  if (!cont) {
    cont = document.createElement('div');
    cont.id = 'toast-cont';
    document.body.appendChild(cont);
  }
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  // Support both plain text and trusted HTML (caller-supplied). To stay safe,
  // we use innerHTML only when msg contains '<' (caller knows what it does).
  if (typeof msg === 'string' && msg.includes('<')) t.innerHTML = msg;
  else t.textContent = msg;
  cont.appendChild(t);
  if (autoDismissMs > 0) {
    setTimeout(() => {
      t.style.transition = 'opacity .4s, transform .4s';
      t.style.opacity = '0';
      t.style.transform = 'translateX(40px)';
      setTimeout(() => t.remove(), 400);
    }, autoDismissMs);
  }
  return t;
}
function _updateToast(t, msg, kind) {
  t.className = 'toast ' + kind;
  t.textContent = msg;
  setTimeout(() => t.remove(), 4000);
}

function initLibrary() {
  $('#lib-open').onclick = async () => { await fetch('/api/library/open', {method: 'POST'}); };
  _setupDropZone('lib-body', '/api/library/upload', () => setTimeout(renderLibrary, 500));
  $('#lib-reindex').onclick = async () => {
    const btn = $('#lib-reindex');
    btn.disabled = true; btn.textContent = '...';
    try {
      const r = await fetch('/api/library/reindex', {method: 'POST'});
      const d = await r.json();
      if (!d.ok) {
        btn.textContent = 'ERR';
        setTimeout(() => { btn.textContent = 'REINDEX'; btn.disabled = false; }, 2000);
      } else {
        btn.textContent = 'STARTED';
        setTimeout(() => { btn.textContent = 'REINDEX'; btn.disabled = false; }, 1500);
        renderLibrary();
      }
    } catch (e) {
      btn.textContent = 'ERR'; setTimeout(() => { btn.textContent = 'REINDEX'; btn.disabled = false; }, 2000);
    }
  };
}

// ============================================================================
// PIPELINE: TRANSCRIPTS
// ============================================================================
let distillPollTimer = null;

async function renderTranscripts() {
  // Sources
  try {
    const r = await fetch('/api/transcripts/sources');
    const d = await r.json();
    const sources = d.sources || {};
    let html = '';
    for (const [id, s] of Object.entries(sources)) {
      // Special-case INBOX: show per-file validation
      if (id === 'inbox') {
        const validated = s.validated || [];
        const filesHtml = validated.length ? validated.map(v => {
          const dot = v.status === 'ok' ? 'ok' : v.status === 'warn' ? 'warn' : 'err';
          return `<div class="ibx-file ${dot}">
            <div class="ibx-status status-dot ${dot}"></div>
            <div class="ibx-name">${escapeHtml(v.rel)} <span class="ibx-ext">${v.ext}</span></div>
            <div class="ibx-meta">${escapeHtml(v.detected)} · ${v.sessions || 0} sess · ${v.size_mb} MB</div>
            <div class="ibx-msg">${escapeHtml(v.message)}</div>
          </div>`;
        }).join('') : '<div class="ibx-empty">drop files here (ZIP/JSON/JSONL/MD/TXT) — patrz tabela poniżej</div>';

        html += `<div class="dsource supported" style="grid-column:1/-1">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <div class="ds-title">INBOX (manual drop zone)</div>
            <button class="opt-btn" id="inbox-open">OPEN FOLDER</button>
          </div>
          <div class="ds-note" style="margin-bottom:8px">${escapeHtml(s.path)}</div>
          <div class="ds-note">${s.valid_files || 0} of ${s.files} files valid · ~${s.estimated_sessions || 0} sessions to distill</div>
          <div class="ibx-list">${filesHtml}</div>
        </div>`;
      } else {
        html += `<div class="dsource ${s.supported ? 'supported' : 'unsupported'}">
          <div class="ds-title">${escapeHtml(id)}</div>
          <div class="ds-count">${s.sessions ?? s.workspaces ?? s.found ?? '?'}</div>
          <div class="ds-note">${s.supported ? 'supported' : (s.note || 'detection only')}</div>
          <div class="ds-note" style="font-size:9px">${escapeHtml((s.path||'').slice(-40))}</div>
        </div>`;
      }
    }
    $('#distill-sources').innerHTML = html || '<div class="lib-empty">no sources detected</div>';
    const inboxBtn = $('#inbox-open');
    if (inboxBtn) inboxBtn.onclick = async () => {
      await fetch('/api/transcripts/inbox/open', {method: 'POST'});
    };
  } catch (e) {
    $('#distill-sources').innerHTML = `<div class="lib-empty">sources load failed: ${escapeHtml(e.message)}</div>`;
  }

  // Model picker
  const sel = $('#distill-model');
  if (lastStatus && sel) {
    const cur = sel.value;
    const localModels = lastStatus.ollama.models.map(m => `<option value="${m.name}" ${m.name===cur?'selected':''}>${m.name} (Lokalny)</option>`).join('');
    const cloudModels = `
      <option value="claude-haiku" ${'claude-haiku'===cur?'selected':''}>Claude Haiku (Cloud API)</option>
    `;
    sel.innerHTML = localModels + cloudModels;
    if (!cur && sel.options.length) sel.value = sel.options[0].value;
  }

  // Status
  pollDistill();
  if (!distillPollTimer) distillPollTimer = setInterval(pollDistill, 2500);
}

// Per-model time estimate (seconds per session, empirical)
const MODEL_SEC_PER_SESSION = {
  'qwen2.5:3b':       18,
  'qwen2.5:14b':      85,
  'qwen2.5-coder:14b': 85,
  'gemma3:12b':       70,
  'gemma2:9b':        45,
  'llama3.2:3b':      18,
};
function _modelSpeed(name) {
  if (!name) return 60;
  for (const [k, v] of Object.entries(MODEL_SEC_PER_SESSION)) {
    if (name.startsWith(k)) return v;
  }
  // Heuristic by size suffix
  if (name.match(/:1b/)) return 8;
  if (name.match(/:3b/)) return 18;
  if (name.match(/:7b/)) return 35;
  if (name.match(/:14b/)) return 85;
  if (name.match(/:27b/)) return 180;
  return 60;
}
function _fmtDuration(sec) {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec/60)}m ${sec%60}s`;
  const h = Math.floor(sec/3600);
  const m = Math.floor((sec%3600)/60);
  return `${h}h ${m}m`;
}

async function pollDistill() {
  try {
    const [statusR, sourcesR] = await Promise.all([
      fetch('/api/transcripts/status').then(r => r.json()),
      fetch('/api/transcripts/sources').then(r => r.json()).catch(() => ({sources:{}})),
    ]);
    const s = statusR;
    const sources = sourcesR.sources || {};
    const state = s.state || 'idle';

    // Build session totals breakdown
    const breakdown = [];
    let totalToDistill = 0;
    for (const [id, src] of Object.entries(sources)) {
      if (id === 'inbox') {
        for (const v of (src.validated || [])) {
          if (v.status === 'ok' && v.sessions > 0) {
            breakdown.push({src: v.detected || id, count: v.sessions});
            totalToDistill += v.sessions;
          }
        }
      } else if (src.supported && (src.sessions || 0) > 0) {
        breakdown.push({src: id, count: src.sessions});
        totalToDistill += src.sessions;
      }
    }

    // Estimate time for chosen model
    const model = $('#distill-model').value || s.model || 'qwen2.5:14b';
    const speed = _modelSpeed(model);
    const estTotal = totalToDistill * speed;

    $('#distill-state').innerHTML = `<span style="color:${state==='idle'?'var(--text-dim)':'var(--cyan)'}">${state}</span>`
      + (s.proc_running ? ' <span style="color:var(--green)">●</span>' : '');

    let body = '';
    let progressDetails = '';

    // ---- Header: sessions to distill + ETA ----
    if (totalToDistill > 0 && state !== 'distilling') {
      const breakdownStr = breakdown.map(b => `${b.src}: ${b.count}`).join(' · ');
      progressDetails = `<div class="dp-summary">
        <div class="dp-summary-row">
          <span class="dp-lbl">TOTAL SESSIONS IN INBOX</span>
          <span class="dp-big">${totalToDistill}</span>
          <span class="dp-lbl">sessions</span>
        </div>
        <div class="dp-summary-row">
          <span class="dp-lbl">ESTIMATED TIME (${escapeHtml(model)})</span>
          <span class="dp-big">${_fmtDuration(estTotal)}</span>
        </div>
        <div class="dp-breakdown">${breakdownStr}</div>
      </div>`;
    }

    // ---- State-specific body ----
    if (state === 'collecting') {
      body = `<div class="dp-status">📥 collecting transcripts from all sources…</div>`;
    } else if (state === 'distilling') {
      const pct = s.total ? (s.done / s.total * 100) : 0;
      const eta = s.total && s.done > 0 ? Math.round((s.total - s.done) * speed) : 0;
      body = `<div class="dp-status">
        ⏳ distilling <strong>${s.done}/${s.total}</strong> · written <strong>${s.written ?? 0}</strong>
        · current: <code>${escapeHtml((s.current || '').slice(0, 50))}</code>
        · model: <code>${escapeHtml(s.model || '')}</code>
      </div>
      <div class="dp-bar"><div class="dp-fill" style="width:${pct}%"></div></div>
      <div class="dp-eta">${pct.toFixed(1)}% · ETA: ${_fmtDuration(eta)}</div>`;
    } else if (state === 'idle' && s.finished_at) {
      const ago = fmtAgo(s.finished_at);
      body = `<div class="dp-status">
        ✓ last run: <strong>${s.written ?? 0}</strong> of ${s.total ?? 0} sessions distilled
        in ${_fmtDuration(s.duration_sec ?? 0)} (model: <code>${escapeHtml(s.model || '')}</code>) · ${ago} ago
      </div>`;
    } else if (state === 'idle' && s.collected_count != null) {
      body = `<div class="dp-status">collected ${s.collected_count} new sessions. Click RUN ALL to distill.</div>`;
    } else if (state === 'error') {
      body = `<div class="dp-status" style="color:var(--red)">❌ Zatrzymano z błędem: <strong>${escapeHtml(s.error || 'nieznany')}</strong></div>`;
    } else {
      body = `<div class="dp-status">idle. Pick model + RUN ALL to start.</div>`;
    }

    $('#distill-progress').innerHTML = progressDetails + body;
  } catch (e) {
    $('#distill-progress').textContent = 'status fetch failed';
  }
}

function initTranscripts() {
  $('#distill-collect').onclick = () => runDistill('collect');
  $('#distill-run').onclick = () => runDistill('run');
  $('#distill-stop').onclick = async () => { await fetch('/api/transcripts/stop', {method: 'POST'}); pollDistill(); };
  _setupDropZone('distill-sources', '/api/transcripts/inbox/upload', () => setTimeout(renderTranscripts, 500));
}

async function runDistill(mode) {
  const model = $('#distill-model').value;
  const limit = parseInt($('#distill-limit').value) || null;
  const body = {mode, model};
  if (limit) body.limit = limit;
  const r = await fetch('/api/transcripts/run', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (!d.ok) {
    alert('Błąd uruchamiania: ' + (d.error || 'nieznany'));
    return;
  }
  setTimeout(pollDistill, 800);
}

// ============================================================================
// TOOLS: REDISTILL
// ============================================================================
function initRedistill() {
  $('#redistill-run').onclick = async () => {
    const model = $('#redistill-model').value;
    const limit = parseInt($('#redistill-limit').value) || 50;
    const body = {model, limit};
    const r = await fetch('/api/vault/redistill/run', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (!d.ok) {
      alert('Błąd uruchamiania: ' + (d.error || 'nieznany'));
      return;
    }
    setTimeout(pollRedistill, 800);
  };
  
  $('#redistill-stop').onclick = async () => {
    await fetch('/api/vault/redistill/stop', {method: 'POST'});
    pollRedistill();
  };
  
  pollRedistill();
  setInterval(pollRedistill, 2500);
}


async function pollRedistill() {
  const panel = $('#redistill-panel');
  if (!panel || panel.closest('.view:not(.active)')) return;
  
  try {
    const r = await fetch('/api/vault/redistill/status');
    const d = await r.json();
    const st = d.state || 'idle';
    
    $('#redistill-state').innerText = st === 'running' ? `running (${d.model || ''})` : st;
    $('#redistill-state').style.color = st === 'running' ? 'var(--magenta)' : 'var(--text-dim)';
    
    if (st === 'running') {
      const done = d.done || 0;
      const total = d.total || 0;
      const pct = total ? (done/total)*100 : 0;
      let html = `<div style="margin-bottom:5px;font-family:var(--mono);font-size:11px">Progress: ${done}/${total}</div>`;
      html += `<div style="background:rgba(0,0,0,0.3);height:4px;width:100%">
                 <div style="background:var(--magenta);height:100%;width:${pct}%"></div>
               </div>`;
      if (d.last_file) html += `<div style="margin-top:5px;font-family:var(--mono);font-size:10px;color:var(--text-dim)">${escapeHtml(d.last_file)}</div>`;
      $('#redistill-progress').innerHTML = html;
      
      $('#redistill-run').disabled = true;
      $('#redistill-stop').disabled = false;
    } else {
      let msg = '';
      if (st === 'stopped' && d.done !== undefined) {
        msg = `<div style="color:var(--text-dim)">Finished. Processed: ${d.done}, Grew: ${d.grew||0}, Errors: ${d.errors||0}. ${Math.round((d.bytes_after||0)/(max(1,d.bytes_before||1))*100)}% size delta.</div>`;
      }
      $('#redistill-progress').innerHTML = msg;
      
      $('#redistill-run').disabled = false;
      $('#redistill-stop').disabled = true;
    }
  } catch (e) { /* ignore */ }
}

// ============================================================================
// TOOLS: MCP
// ============================================================================
async function renderMCP() {
  try {
    const r = await fetch('/api/mcp/list');
    const d = await r.json();
    const list = $('#mcp-list');
    if (!d.servers.length) {
      list.innerHTML = `<div class="mcp-empty">no MCP servers configured.<br>Click ADD SERVER. Common examples:<br><code style="font-size:10px">npx -y @modelcontextprotocol/server-filesystem &lt;path&gt;</code></div>`;
      return;
    }
    list.innerHTML = d.servers.map(s => `
      <div class="mcp-row ${s.running ? 'running' : ''}">
        <div class="mcp-dot"></div>
        <div class="mcp-info">
          <div class="mcp-title">${escapeHtml(s.title || s.id)}</div>
          <div class="mcp-cmd">${escapeHtml(s.command + ' ' + (s.args||[]).join(' '))}</div>
        </div>
        <span style="font-size:10px;color:var(--text-dim);font-family:var(--mono)">${s.running ? 'PID '+s.pid : 'stopped'}</span>
        <button class="opt-btn" data-act="${s.running?'stop':'start'}" data-sid="${s.id}">${s.running?'STOP':'START'}</button>
        <button class="opt-btn test" data-act="logs" data-sid="${s.id}">LOGS</button>
        <button class="opt-btn test" data-act="delete" data-sid="${s.id}">DEL</button>
      </div>`).join('');
    list.querySelectorAll('button').forEach(b => b.onclick = () => mcpAction(b.dataset.act, b.dataset.sid));
  } catch (e) {
    $('#mcp-list').innerHTML = `<div class="mcp-empty">load failed: ${escapeHtml(e.message)}</div>`;
  }
}

async function mcpAction(act, sid) {
  if (act === 'start' || act === 'stop') {
    await fetch(`/api/mcp/${act}/${sid}`, {method: 'POST'});
    renderMCP();
  } else if (act === 'delete') {
    if (!confirm(`Delete MCP server "${sid}"?`)) return;
    await fetch(`/api/mcp/delete/${sid}`, {method: 'POST'});
    renderMCP();
  } else if (act === 'logs') {
    // jump to logs tab and set picker
    const opt = Array.from($('#logs-picker').options).find(o => o.value === `mcp-${sid}`);
    if (opt) $('#logs-picker').value = opt.value;
    else {
      const o = document.createElement('option');
      o.value = `mcp-${sid}`; o.textContent = `mcp-${sid}`;
      $('#logs-picker').appendChild(o);
      $('#logs-picker').value = o.value;
    }
    showView('tools');
    refreshLog();
  }
}

function initMCP() {
  $('#mcp-add').onclick = () => $('#mcp-form').classList.toggle('hidden');
  $('#mcp-f-cancel').onclick = () => $('#mcp-form').classList.add('hidden');
  $('#mcp-f-save').onclick = async () => {
    const id = $('#mcp-f-id').value.trim();
    if (!id) { alert('id required'); return; }
    const args = $('#mcp-f-args').value.split('\n').map(l => l.trim()).filter(Boolean);
    const envLines = $('#mcp-f-env').value.split('\n').map(l => l.trim()).filter(Boolean);
    const env = {};
    envLines.forEach(l => { const i = l.indexOf('='); if (i > 0) env[l.slice(0,i)] = l.slice(i+1); });
    const body = {
      id, title: $('#mcp-f-title').value.trim() || id,
      command: $('#mcp-f-cmd').value.trim(),
      args, env, enabled: true,
    };
    const r = await fetch('/api/mcp/save', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (r.ok) {
      ['mcp-f-id','mcp-f-title','mcp-f-cmd','mcp-f-args','mcp-f-env'].forEach(id => $('#'+id).value = '');
      $('#mcp-form').classList.add('hidden');
      renderMCP();
    } else { alert('save failed'); }
  };
}

// ============================================================================
// TOOLS: LOGS
// ============================================================================
let logsAutoTimer = null;
async function renderLogs() {
  try {
    const r = await fetch('/api/logs/list');
    const d = await r.json();
    const picker = $('#logs-picker');
    const cur = picker.value;
    picker.innerHTML = d.logs.map(l => `<option value="${l.name}">${l.filename} (${l.size_kb} KB)</option>`).join('');
    if (cur && Array.from(picker.options).some(o => o.value === cur)) picker.value = cur;
    refreshLog();
  } catch (e) {
    $('#logs-body').textContent = 'list failed: ' + e.message;
  }
}

async function refreshLog() {
  const name = $('#logs-picker').value;
  if (!name) { $('#logs-body').textContent = 'pick a log…'; return; }
  try {
    const r = await fetch(`/api/logs/tail?name=${encodeURIComponent(name)}&lines=400`);
    const d = await r.json();
    $('#logs-body').textContent = d.lines.join('\n');
    $('#logs-body').scrollTop = $('#logs-body').scrollHeight;
  } catch (e) {
    $('#logs-body').textContent = 'tail failed: ' + e.message;
  }
}

function initLogs() {
  $('#logs-picker').onchange = refreshLog;
  $('#logs-refresh').onclick = refreshLog;
  $('#logs-clear').onclick = async () => {
    const name = $('#logs-picker').value;
    if (!name) return;
    if (!confirm(`Clear log "${name}"?`)) return;
    await fetch(`/api/logs/clear?name=${encodeURIComponent(name)}`, {method: 'POST'});
    refreshLog();
  };
  $('#logs-auto').onchange = e => {
    if (e.target.checked) { logsAutoTimer = setInterval(refreshLog, 3000); }
    else { clearInterval(logsAutoTimer); logsAutoTimer = null; }
  };
  // start auto
  logsAutoTimer = setInterval(() => { if ($('#view-tools').classList.contains('active') && $('#logs-auto').checked) refreshLog(); }, 3000);
}

// ============================================================================
// INSTRUKCJA: scroll-spy + smooth scroll
// ============================================================================
let _insScrollBound = false;
function initInstrukcjaScrollSpy() {
  if (!_insScrollBound) {
    document.querySelectorAll('.ins-nav a').forEach(a => {
      a.addEventListener('click', e => {
        e.preventDefault();
        const id = a.dataset.anchor;
        const el = document.getElementById(id);
        if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'});
      });
    });
    window.addEventListener('scroll', _updateInsActive, {passive: true});
    // back-to-top click
    const topBtn = $('#ins-top');
    if (topBtn) {
      topBtn.addEventListener('click', () => {
        window.scrollTo({top: 0, behavior: 'smooth'});
      });
    }
    _insScrollBound = true;
  }
  _updateInsActive();
}

function _updateInsActive() {
  if (!document.getElementById('view-instrukcja')?.classList.contains('active')) return;
  const sections = Array.from(document.querySelectorAll('.ins-section'));
  const fromTop = window.scrollY + 140;
  let active = sections[0]?.id;
  for (const s of sections) {
    if (s.offsetTop <= fromTop) active = s.id;
    else break;
  }
  document.querySelectorAll('.ins-nav a').forEach(a => {
    a.classList.toggle('active', a.dataset.anchor === active);
  });
  // back-to-top: show only after scrolling 300px
  const topBtn = $('#ins-top');
  if (topBtn) topBtn.classList.toggle('hidden', window.scrollY < 300);
}

// ============================================================================
// TOOLS: IDLE GUARD
// ============================================================================
async function renderIdleGuard() {
  try {
    const r = await fetch('/api/idle/config');
    const d = await r.json();
    const tg = $('#idle-toggle');
    if (tg) tg.classList.toggle('on', !!d.auto_unload_enabled);
    $('#idle-min').value = d.idle_minutes || 10;
    const idleM = Math.floor((d.idle_sec || 0) / 60);
    const idleS = (d.idle_sec || 0) % 60;
    $('#idle-state').textContent = d.auto_unload_enabled
      ? `enabled · idle ${idleM}m ${idleS}s (unloads at ${d.idle_minutes}m)`
      : `disabled · idle ${idleM}m ${idleS}s`;
  } catch (e) {
    $('#idle-state').textContent = 'load failed';
  }
}

function initIdleGuard() {
  $('#idle-toggle').onclick = () => $('#idle-toggle').classList.toggle('on');
  $('#idle-save').onclick = async () => {
    const btn = $('#idle-save');
    const orig = btn.textContent;
    btn.textContent = '...';
    try {
      const body = {
        auto_unload_enabled: $('#idle-toggle').classList.contains('on'),
        idle_minutes: parseInt($('#idle-min').value) || 10,
      };
      const r = await fetch('/api/idle/config', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      btn.textContent = r.ok ? 'OK' : 'ERR';
    } catch { btn.textContent = 'ERR'; }
    setTimeout(() => { btn.textContent = orig; renderIdleGuard(); }, 1000);
  };
  $('#idle-unload-now').onclick = async () => {
    const btn = $('#idle-unload-now');
    btn.textContent = '...'; btn.disabled = true;
    try {
      const r = await fetch('/api/ollama/unload', {method: 'POST'});
      const d = await r.json();
      btn.textContent = `OK -${d.count||0}`;
    } catch { btn.textContent = 'ERR'; }
    setTimeout(() => { btn.textContent = 'UNLOAD NOW'; btn.disabled = false; refresh(); }, 1500);
  };
}

// ============================================================================
// TOOLS: BACKUP
// ============================================================================
async function renderBackups() {
  try {
    const r = await fetch('/api/backup/list');
    const d = await r.json();
    const list = $('#bk-list');
    if (!d.backups.length) {
      list.innerHTML = `<div class="mcp-empty">no backups yet — click CREATE BACKUP</div>`;
      return;
    }
    list.innerHTML = d.backups.map(b => `
      <div class="mcp-row">
        <div class="mcp-dot" style="background:var(--cyan);box-shadow:0 0 8px var(--cyan)"></div>
        <div class="mcp-info">
          <div class="mcp-title">${escapeHtml(b.name)}</div>
          <div class="mcp-cmd">${b.size_mb} MB · ${new Date(b.created*1000).toLocaleString('en-GB')}</div>
        </div>
        <span></span>
        <a class="opt-btn" href="${b.download_url}" download>DOWNLOAD</a>
        <span></span>
        <button class="opt-btn test" data-name="${b.name}">DEL</button>
      </div>`).join('');
    list.querySelectorAll('button[data-name]').forEach(btn => btn.onclick = async () => {
      if (!confirm(`Delete ${btn.dataset.name}?`)) return;
      await fetch(`/api/backup/delete/${btn.dataset.name}`, {method: 'POST'});
      renderBackups();
    });
  } catch (e) {
    $('#bk-list').innerHTML = `<div class="mcp-empty">load failed: ${escapeHtml(e.message)}</div>`;
  }
}

function initBackups() {
  $('#bk-create').onclick = async () => {
    const btn = $('#bk-create'); const orig = btn.textContent;
    btn.textContent = 'CREATING...'; btn.disabled = true;
    try {
      const body = {
        include_keys: $('#bk-include-keys').checked,
        include_distilled: $('#bk-include-distilled').checked,
      };
      const r = await fetch('/api/backup', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      const d = await r.json();
      btn.textContent = `OK ${d.size_mb} MB`;
      setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
      renderBackups();
    } catch (e) {
      btn.textContent = 'ERR'; setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
    }
  };
}

// ============================================================================
// OPTIONS (API keys)
// ============================================================================
async function renderOptions() {
  let data;
  try { data = await (await fetch('/api/keys')).json(); }
  catch (e) { return; }
  $('#keys-file-path').textContent = data.keys_file || 'data/api-keys.json';
  const list = $('#opt-list'); list.innerHTML = '';
  for (const [pid, p] of Object.entries(data.providers)) {
    const row = document.createElement('div');
    row.className = 'opt-row' + (p.enabled ? ' enabled' : '');
    const stateHtml = p.has_env
      ? `<span class="ok">env var: ${p.env_name}</span><span>${p.masked}</span>`
      : p.has_file_key
      ? `<span class="ok">file</span><span>${p.masked}</span>`
      : `<span class="warn">no key</span><span>&nbsp;</span>`;
    row.innerHTML = `
      <div class="opt-icon">${ICONS[p.icon] || ICONS.db}</div>
      <div class="opt-title">${p.title}</div>
      <div class="opt-state">${stateHtml}</div>
      <input type="password" placeholder="${p.has_env ? '(env var in use; leave blank or override)' : p.hint || 'paste API key…'}" data-role="key">
      <div class="opt-toggle ${p.enabled ? 'on' : ''}" data-role="toggle" title="enable / disable"></div>
      <button class="opt-btn" data-role="save">SAVE</button>
      <button class="opt-btn test" data-role="test" ${p.has_key ? '' : 'disabled style="opacity:0.4;cursor:not-allowed"'}>TEST</button>
    `;
    const toggle = row.querySelector('[data-role="toggle"]');
    toggle.onclick = () => toggle.classList.toggle('on');
    const saveBtn = row.querySelector('[data-role="save"]');
    saveBtn.onclick = async () => {
      const enabled = toggle.classList.contains('on');
      const keyInput = row.querySelector('[data-role="key"]');
      const payload = {enabled};
      if (keyInput.value) payload.key = keyInput.value;
      saveBtn.classList.add('saving'); saveBtn.textContent = '...';
      try {
        const res = await fetch(`/api/keys/${pid}`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
        if (res.ok) { keyInput.value = ''; await renderOptions(); refresh(); }
        else { saveBtn.textContent = 'ERR'; setTimeout(() => { saveBtn.textContent = 'SAVE'; saveBtn.classList.remove('saving'); }, 1500); }
      } catch { saveBtn.textContent = 'ERR'; setTimeout(() => { saveBtn.textContent = 'SAVE'; saveBtn.classList.remove('saving'); }, 1500); }
    };
    const testBtn = row.querySelector('[data-role="test"]');
    if (!testBtn.disabled) {
      testBtn.onclick = async () => {
        testBtn.classList.add('saving'); testBtn.textContent = '...';
        try {
          const r = await (await fetch(`/api/keys/${pid}/test`, {method: 'POST'})).json();
          testBtn.textContent = r.ok ? 'OK ' + (r.status || '') : 'FAIL ' + (r.status || '');
          testBtn.style.color = r.ok ? 'var(--green)' : 'var(--red)';
          setTimeout(() => { testBtn.textContent = 'TEST'; testBtn.classList.remove('saving'); testBtn.style.color = ''; }, 3000);
        } catch { testBtn.textContent = 'ERR'; setTimeout(() => { testBtn.textContent = 'TEST'; testBtn.classList.remove('saving'); }, 2000); }
      };
    }
    list.appendChild(row);
  }
}

// ============================================================================
// TOOLS: SKILLS (Agentic workflows)
// ============================================================================
const _skillRunning = new Set();

async function renderSkills() {
  const list = $('#skills-list');
  const meta = $('#skills-meta');
  if (!list) return;
  try {
    const r = await fetch('/api/skills/list');
    const d = await r.json();
    const skills = d.skills || [];
    if (meta) meta.textContent = `${skills.length} skill${skills.length === 1 ? '' : 's'}`;
    if (!skills.length) {
      list.innerHTML = `<div class="dedup-empty">Brak skilli. Dodaj plik .md w brain/skills/</div>`;
      return;
    }
    list.innerHTML = skills.map(s => {
      const inputs = s.inputs || {};
      const inputKeys = Object.keys(inputs);
      const inputFields = inputKeys.length
        ? inputKeys.map(k => `<label style="font-size:10px;color:var(--text-dim);font-family:var(--mono)">
              ${escapeHtml(k)} <input data-skill="${escapeHtml(s.name)}" data-input="${escapeHtml(k)}"
                value="${escapeHtml(String(inputs[k] ?? ''))}" style="width:100%;font-size:11px;padding:3px 6px"></label>`).join('')
        : '';
      return `
        <div class="skill-card" data-name="${escapeHtml(s.name)}">
          <div class="skill-name">${escapeHtml(s.name)}</div>
          <div class="skill-desc">${escapeHtml(s.description || '')}</div>
          ${inputFields}
          <div class="skill-meta">
            <span>${escapeHtml(s.model || '')}</span>
            <span>${escapeHtml(s.file || '')}</span>
          </div>
          <div class="skill-actions">
            <button class="opt-btn" data-action="run-skill">▶ RUN</button>
            <button class="opt-btn test" data-action="view-skill">VIEW</button>
          </div>
        </div>`;
    }).join('');

    list.querySelectorAll('button[data-action="run-skill"]').forEach(btn => {
      btn.onclick = async () => {
        const card = btn.closest('.skill-card');
        const name = card.dataset.name;
        if (_skillRunning.has(name)) return;
        _skillRunning.add(name);
        const orig = btn.textContent;
        btn.textContent = '⏳ RUNNING';
        btn.classList.add('skill-running');
        btn.disabled = true;

        // Collect input fields for this skill
        const inputs = {};
        card.querySelectorAll('input[data-skill]').forEach(inp => {
          if (inp.dataset.skill === name && inp.value !== '') {
            inputs[inp.dataset.input] = inp.value;
          }
        });

        const out = $('#skills-output');
        out.classList.remove('hidden');
        out.innerHTML = `<div class="skills-output-head">
          <span>${escapeHtml(name)} — running…</span><span>—</span>
        </div><div>czekam na model…</div>`;

        try {
          const r = await fetch('/api/skills/run', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify({name, inputs}),
          });
          const d = await r.json();
          if (d.ok) {
            out.innerHTML = `<div class="skills-output-head">
                <span>${escapeHtml(d.skill)} · ${escapeHtml(d.model)} · ${d.duration}s</span>
                <span>${d.saved_to ? '💾 saved: ' + escapeHtml(d.saved_to.split(/[\\\/]/).pop()) : ''}</span>
              </div>${escapeHtml(d.output || '(empty)')}`;
          } else {
            out.innerHTML = `<div class="skills-output-head">
              <span>${escapeHtml(name)} — error</span></div>${escapeHtml(d.error || 'unknown')}`;
          }
        } catch (e) {
          out.innerHTML = `<div class="skills-output-head"><span>error</span></div>${escapeHtml(e.message)}`;
        }
        btn.textContent = orig;
        btn.classList.remove('skill-running');
        btn.disabled = false;
        _skillRunning.delete(name);
      };
    });

    list.querySelectorAll('button[data-action="view-skill"]').forEach(btn => {
      btn.onclick = () => {
        const name = btn.closest('.skill-card').dataset.name;
        // For now just open folder — Edit button could later open in-place editor
        fetch('/api/skills/open', {method: 'POST'});
      };
    });
  } catch (e) {
    list.innerHTML = `<div class="dedup-empty">błąd: ${escapeHtml(e.message)}</div>`;
  }
}

function initSkills() {
  const refresh = $('#skills-refresh');
  const open = $('#skills-open');
  if (refresh) refresh.onclick = (e) => { e.stopPropagation(); renderSkills(); };
  if (open) open.onclick = (e) => { e.stopPropagation(); fetch('/api/skills/open', {method: 'POST'}); };
}

// ============================================================================
// USER PROFILE — Hermes-style vault/USER.md
// ============================================================================
const USER_MAX = 2200;
let _profileDirty = false;

async function renderUserProfile() {
  const editor = $('#profile-editor');
  const meta   = $('#profile-meta');
  const bar    = $('#profile-bar-fill');
  const status = $('#profile-status');
  if (!editor) return;

  try {
    const r = await fetch('/api/user-profile');
    const d = await r.json();
    editor.value = d.content || '';
    _updateProfileBar(d.chars || 0);
    if (meta) meta.textContent = `${d.chars || 0}/${USER_MAX} chars (${d.pct || 0}%)`;
    if (status) { status.textContent = ''; status.className = ''; }
    _profileDirty = false;
    editor.classList.remove('dirty');
  } catch(e) {
    if (status) { status.textContent = 'błąd ładowania'; status.className = 'err'; }
  }

  // Wire buttons (idempotent)
  const refreshBtn = $('#profile-refresh');
  const updateBtn  = $('#profile-update-btn');
  const saveBtn    = $('#profile-save-btn');

  if (refreshBtn && !refreshBtn._wired) {
    refreshBtn._wired = true;
    refreshBtn.onclick = () => renderUserProfile();
  }

  if (editor && !editor._wired) {
    editor._wired = true;
    editor.addEventListener('input', () => {
      _profileDirty = true;
      editor.classList.add('dirty');
      _updateProfileBar(editor.value.length);
      if (saveBtn) saveBtn.style.display = '';
      if (meta) meta.textContent = `${editor.value.length}/${USER_MAX} chars`;
    });
  }

  if (saveBtn && !saveBtn._wired) {
    saveBtn._wired = true;
    saveBtn.onclick = async () => {
      const content = editor.value;
      if (content.length > USER_MAX) {
        status.textContent = `Zbyt długi! Max ${USER_MAX} znaków.`; status.className = 'err'; return;
      }
      saveBtn.disabled = true;
      try {
        const r = await fetch('/api/user-profile/save', {
          method: 'POST', headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ content })
        });
        const d = await r.json();
        if (d.ok) {
          status.textContent = `✓ Zapisano (${d.chars} chars, ${d.pct}%)`; status.className = 'ok';
          _profileDirty = false; editor.classList.remove('dirty');
          saveBtn.style.display = 'none';
        } else {
          status.textContent = `błąd: ${d.error}`; status.className = 'err';
        }
      } finally { saveBtn.disabled = false; }
    };
  }

  if (updateBtn && !updateBtn._wired) {
    updateBtn._wired = true;
    updateBtn.onclick = async () => {
      if (!confirm('Aktualizować profil z ostatnich sesji przez Ollama? (zajmie ~30-60s)')) return;
      updateBtn.disabled = true;
      if (status) { status.textContent = '⏳ Analizuję sesje przez Ollama…'; status.className = 'spin'; }
      try {
        const r = await fetch('/api/user-profile/update-from-sessions', { method: 'POST' });
        const d = await r.json();
        if (d.ok) {
          status.textContent = `✓ Profil zaktualizowany (${d.chars} chars)`; status.className = 'ok';
          await renderUserProfile();
        } else {
          status.textContent = `błąd: ${d.error}`; status.className = 'err';
        }
      } finally { updateBtn.disabled = false; }
    };
  }
}

function _updateProfileBar(chars) {
  const bar = $('#profile-bar-fill');
  if (!bar) return;
  const pct = Math.min(100, Math.round(chars / USER_MAX * 100));
  bar.style.width = pct + '%';
  bar.style.background = pct > 90 ? 'var(--red)' : pct > 70 ? 'var(--magenta)' : 'var(--accent)';
}

let _cliSkills = [];

function _skillCat(id, name) {
  const s = (id + ' ' + name).toLowerCase();
  if (/^\d\d-|recon|osint|exploit|malware|threat|incident|forensic|vulnerab|web.?sec|cloud.?sec|red.?team|blue.?team|csoc|siem|log.?analysis|crypto.?analysis|yara|bug.?bounty|owasp|pentest|reverse.?eng|\bbinary\b/.test(s)) return 'Security';
  if (/cisco|mikrotik|netmiko|\bbgp\b|\bvlan\b|wireguard|pihole|unifi|homelab|network|interface|routing|\bdns\b/.test(s)) return 'Network';
  if (/trade|trading|backtest|screener|canslim|finviz|dividend|earnings|market|sector|technical.?anal|breadth|forex|pinescript|algorithmic|druckenmiller|bubble|exposure|edge-|breakout|\bstock|invest|portfolio/.test(s)) return 'Trading';
  return 'Dev / inne';
}

const _SKILL_CAT_ORDER = ['Security', 'Network', 'Trading', 'Dev / inne'];

async function renderCliSkills() {
  const list = $('#cli-skills-list');
  const meta = $('#cli-skills-meta');
  if (!list) return;
  try {
    const d = await (await fetch('/api/cli-skills/list')).json();
    _cliSkills = d.skills || [];
    if (meta) meta.textContent = `${_cliSkills.length} skilli`;
    _renderCliSkillsFiltered();
  } catch (e) {
    list.innerHTML = `<div class="dedup-empty">błąd: ${escapeHtml(e.message)}</div>`;
  }
}

function _renderCliSkillsFiltered() {
  const list = $('#cli-skills-list');
  if (!list) return;
  list.className = 'cli-skills-compact';
  if (!_cliSkills.length) {
    list.innerHTML = `<div class="dedup-empty">Brak skilli. Wrzuć foldery ze SKILL.md do ~/.claude/skills/</div>`;
    return;
  }
  const q = ($('#cli-skills-search')?.value || '').trim().toLowerCase();
  const filtered = q
    ? _cliSkills.filter(s => (s.id + ' ' + s.name + ' ' + (s.description || '')).toLowerCase().includes(q))
    : _cliSkills;
  if (!filtered.length) {
    list.innerHTML = `<div class="dedup-empty">nic nie pasuje do „${escapeHtml(q)}"</div>`;
    return;
  }
  const groups = {};
  for (const s of filtered) (groups[_skillCat(s.id, s.name)] ||= []).push(s);
  list.innerHTML = _SKILL_CAT_ORDER.filter(c => groups[c]).map(cat => {
    const rows = groups[cat].sort((a, b) => a.name.localeCompare(b.name)).map(s => `
      <div class="skill-row" title="${escapeHtml(s.description || '')}">
        <span class="skill-row-name">${escapeHtml(s.name)}</span>
        <span class="skill-row-desc">${escapeHtml(s.description || '')}</span>
      </div>`).join('');
    return `<div class="skill-group"><div class="skill-group-head">${cat} <span>${groups[cat].length}</span></div>${rows}</div>`;
  }).join('');
}

function initCliSkills() {
  const refresh = $('#cli-skills-refresh');
  const open = $('#cli-skills-open');
  const search = $('#cli-skills-search');
  if (refresh) refresh.onclick = () => renderCliSkills();
  if (open) open.onclick = () => fetch('/api/cli-skills/open', {method: 'POST'});
  if (search) search.oninput = () => _renderCliSkillsFiltered();
}

// ============================================================================
// PIPELINE: CODE INDEX (RAG over user's source code)
// ============================================================================
async function renderCodeIndex() {
  const meta = $('#code-meta');
  const list = $('#code-watches-list');
  if (!list || !meta) return;
  try {
    const r = await fetch('/api/code/status');
    const d = await r.json();
    const langStr = Object.entries(d.langs || {})
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([l, c]) => `${l || '?'}:${c}`)
      .join(' ');
    const running = d.scan_running ? ' · SCANNING' : '';
    meta.textContent = `${d.files || 0} plików · ${d.chunks || 0} chunków${langStr ? ' · ' + langStr : ''}${running}`;

    const watches = d.watches || [];
    if (!watches.length) {
      list.innerHTML = `<div class="dedup-empty">Brak watched paths. Wklej ścieżkę do swojego projektu (np. C:\\Users\\you\\projects\\my-repo) i kliknij ADD PATH.</div>`;
      return;
    }
    list.innerHTML = watches.map(p => `
      <div class="code-watch-row" data-path="${escapeHtml(p)}">
        <div class="code-watch-path">${escapeHtml(p)}</div>
        <span class="code-watch-meta">${(d.langs && Object.keys(d.langs).length) ? '' : ''}</span>
        <button class="code-watch-remove" data-action="remove" title="Remove from watch list">✕</button>
      </div>`).join('');
    list.querySelectorAll('button[data-action="remove"]').forEach(btn => {
      btn.onclick = async () => {
        const path = btn.closest('.code-watch-row').dataset.path;
        await fetch('/api/code/watch/remove', {
          method: 'POST', headers: {'content-type': 'application/json'},
          body: JSON.stringify({path}),
        });
        renderCodeIndex();
      };
    });
  } catch (e) {
    list.innerHTML = `<div class="dedup-empty">błąd: ${escapeHtml(e.message)}</div>`;
  }
}

function initCodeIndex() {
  const add = $('#code-watch-add');
  const input = $('#code-watch-input');
  const scan = $('#code-scan');
  const refresh = $('#code-refresh');
  const sBtn = $('#code-search-btn');
  const sInput = $('#code-search-input');
  const results = $('#code-results');

  const doAdd = async () => {
    const v = (input.value || '').trim();
    if (!v) return;
    const r = await fetch('/api/code/watch/add', {
      method: 'POST', headers: {'content-type': 'application/json'},
      body: JSON.stringify({path: v}),
    });
    const d = await r.json();
    if (!d.ok) alert('Błąd dodawania: ' + (d.error || 'unknown'));
    input.value = '';
    renderCodeIndex();
  };

  if (add) add.onclick = doAdd;
  if (input) input.addEventListener('keydown', e => { if (e.key === 'Enter') doAdd(); });

  if (scan) scan.onclick = async () => {
    scan.disabled = true; scan.textContent = 'STARTING…';
    try {
      const r = await fetch('/api/code/scan', {method: 'POST'});
      const d = await r.json();
      if (!d.ok) alert('Błąd: ' + (d.error || 'nieznany'));
    } catch (e) {
      alert('Błąd uruchamiania: ' + e);
    }
    scan.textContent = 'SCAN ALL'; scan.disabled = false;
    // Poll for finish
    let i = 0;
    const t = setInterval(async () => {
      const r = await fetch('/api/code/status');
      const d = await r.json();
      renderCodeIndex();
      if (!d.scan_running || ++i > 600) clearInterval(t);
    }, 2000);
  };

  if (refresh) refresh.onclick = () => renderCodeIndex();

  const doSearch = async () => {
    const q = (sInput.value || '').trim();
    if (!q) return;
    results.classList.remove('hidden');
    results.innerHTML = `<div class="dedup-empty">searching…</div>`;
    try {
      const r = await fetch('/api/code/search', {
        method: 'POST', headers: {'content-type': 'application/json'},
        body: JSON.stringify({query: q, top_k: 10}),
      });
      const d = await r.json();
      const hits = d.hits || [];
      if (!hits.length) {
        results.innerHTML = `<div class="dedup-empty">Brak wyników. Dodaj path + SCAN ALL.</div>`;
        return;
      }
      results.innerHTML = hits.map(h => `
        <div class="code-result">
          <div class="code-result-head">
            <span>${escapeHtml(h.file)} <span class="lang">L${escapeHtml(h.lines)}</span></span>
            <span class="lang">${escapeHtml(h.lang || '')} · score ${h.score}</span>
          </div>
          ${(h.symbols && h.symbols.length) ? `<div class="code-result-symbols">symbols: ${h.symbols.map(escapeHtml).join(', ')}</div>` : ''}
          <div class="code-result-text">${escapeHtml(h.text || '')}</div>
        </div>`).join('');
    } catch (e) {
      results.innerHTML = `<div class="dedup-empty">błąd: ${escapeHtml(e.message)}</div>`;
    }
  };
  if (sBtn) sBtn.onclick = doSearch;
  if (sInput) sInput.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
}

// ============================================================================
// TOOLS: AGENTS · MCP DEPLOY (claude desktop / antigravity / claude code / cursor / windsurf)
// ============================================================================
const _recentlyDeployed = new Set();

async function renderAgents() {
  const list = $('#agents-list');
  const meta = $('#agents-meta');
  if (!list) return;
  try {
    const r = await fetch('/api/agents');
    const d = await r.json();
    const agents = d.agents || [];
    const installed = agents.filter(a => a.installed);
    const wired = installed.filter(a => a.brain_status === 'wired');
    if (meta) meta.textContent = `${wired.length}/${installed.length} wpięte · ${agents.length - installed.length} nie zainstalowane`;
    if (!agents.length) {
      list.innerHTML = `<div class="dedup-empty">Brak danych — sprawdź logi.</div>`;
      return;
    }
    list.innerHTML = agents.map(a => {
      const klass = !a.installed ? 'not_installed' : a.brain_status;
      const badge = !a.installed ? 'NOT INSTALLED'
                   : a.brain_status === 'wired' ? '✓ WIRED'
                   : a.brain_status === 'partial' ? '◐ PARTIAL'
                   : '○ NOT WIRED';
      const brainKeys = ['brain-vault', 'brain-library', 'brain-rag'];
      const serversList = (a.all_servers || []).map(s => {
        if (brainKeys.includes(s)) return `<span class="brain">${escapeHtml(s)}</span>`;
        return `<span class="other">${escapeHtml(s)}</span>`;
      }).join('  ·  ') || '(brak)';
      const recent = _recentlyDeployed.has(a.id) ? ' recent-deploy' : '';
      // Agents that support system-prompt injection
      const SUPPORTS_PROMPT = new Set(['claude-code', 'cursor', 'antigravity-cli', 'vscode', 'antigravity', 'windsurf']);
      const promptBtn = SUPPORTS_PROMPT.has(a.id)
        ? `<button class="opt-btn" data-action="inject-prompt" data-id="${escapeHtml(a.id)}"
                   title="wstrzyknij stałe instrukcje brain MCP do system-prompt agenta (CLAUDE.md / .cursorrules)">🧠 AUTO-PROMPT</button>`
        : '';



      const actions = !a.installed
        ? '<span style="color:var(--text-dim);font-size:11px">— pomijam</span>'
        : a.brain_status === 'wired'
          ? `<button class="opt-btn test" data-action="undeploy" data-id="${escapeHtml(a.id)}">⏏ UNDEPLOY</button>
             <button class="opt-btn"      data-action="redeploy" data-id="${escapeHtml(a.id)}">↻ RE-DEPLOY</button>
             ${promptBtn}`
          : `<button class="opt-btn"      data-action="deploy"   data-id="${escapeHtml(a.id)}">▶ DEPLOY</button>`;
      return `
        <div class="agent-card ${klass}${recent}" data-id="${escapeHtml(a.id)}">
          <div class="agent-head">
            <span class="agent-icon">${a.icon}</span>
            <span class="agent-label">${escapeHtml(a.label)}</span>
            <span class="agent-badge ${klass}">${badge}</span>
          </div>
          ${a.installed ? `
          <div class="agent-config" title="${escapeHtml(a.config_path)}">${escapeHtml(a.config_path)}</div>
          <div class="agent-servers">${serversList}</div>
          ${a.restart_hint ? `<div class="agent-restart-hint">⚠ ${escapeHtml(a.restart_hint)}</div>` : ''}
          <div class="agent-actions">${actions}</div>
          ` : ''}
        </div>`;
    }).join('');


    list.querySelectorAll('button[data-action]').forEach(btn => {
      btn.onclick = async () => {
        const action = btn.dataset.action;
        const id = btn.dataset.id;
        btn.disabled = true; const orig = btn.textContent; btn.textContent = '…';
        let url;
        if (action === 'inject-prompt') url = '/api/agents/inject-prompt';
        else if (action === 'deploy' || action === 'redeploy') url = '/api/agents/deploy';
        else url = '/api/agents/undeploy';
        try {
          const rr = await fetch(url, {
            method: 'POST', headers: {'content-type': 'application/json'},
            body: JSON.stringify({agent_id: id}),
          });
          const dd = await rr.json();
          if (dd.ok && (action === 'deploy' || action === 'redeploy')) {
            _recentlyDeployed.add(id);
            setTimeout(() => { _recentlyDeployed.delete(id); renderAgents(); }, 30000);
          }
        } catch (e) { /* swallow */ }
        btn.textContent = orig; btn.disabled = false;
        renderAgents();
      };
    });
  } catch (e) {
    list.innerHTML = `<div class="dedup-empty">błąd: ${escapeHtml(e.message)}</div>`;
  }
}

function initAgents() {
  const refresh = $('#agents-refresh');
  if (refresh) refresh.onclick = () => renderAgents();
  const all = $('#agents-deploy-all');
  if (all) all.onclick = async () => {
    all.disabled = true; const orig = all.textContent; all.textContent = '… DEPLOYING …';
    try {
      const r = await fetch('/api/agents/deploy-all', {method: 'POST'});
      const d = await r.json();
      (d.agents || []).forEach(id => _recentlyDeployed.add(id));
      setTimeout(() => { _recentlyDeployed.clear(); renderAgents(); }, 30000);
    } catch (e) {}
    all.textContent = orig; all.disabled = false;
    renderAgents();
  };
}
// ============================================================================
// ============================================================================
// TOOLS: AUTO SCHEDULE (background tasks)
// ============================================================================

function _fmt_dur(sec) {
  if (!sec || sec <= 0) return '—';
  if (sec < 60) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.round(sec/60)}min`;
  return `${(sec/3600).toFixed(1)}h`;
}

function _fmt_ts(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});
}

let _availableModels = [];

async function _loadAvailableModels() {
  if (_availableModels.length) return _availableModels;
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    _availableModels = (d.ollama?.models || [])
      .filter(m => !m.is_embed)
      .map(m => m.name);
  } catch (e) { /* ignore */ }
  // Fallback: standard set
  if (!_availableModels.length) {
    _availableModels = ['qwen2.5:14b', 'qwen2.5:7b', 'qwen2.5:3b', 'gemma3:4b', 'llama3.2:3b'];
  }
  // Always offer Claude Haiku as a cloud option (requires API key in OPTIONS)
  if (!_availableModels.includes('claude-haiku')) {
    _availableModels.push('claude-haiku');
  }
  return _availableModels;
}

async function renderSchedule() {
  const info = $('#sched-info');
  const list = $('#sched-list');
  const log  = $('#sched-log');
  const meta = $('#sched-meta');
  const advice = $('#sched-advice');
  if (!list) return;
  try {
    // Self-aware advisor — brain suggestions
    if (advice) {
      try {
        const sr = await fetch('/api/schedule/self-aware');
        const sd = await sr.json();
        const items = sd.advice || [];
        if (items.length) {
          advice.innerHTML = `<div style="font-size:10px; color:var(--text-dim); margin-bottom:4px; font-family:var(--mono); letter-spacing:1px">💡 BRAIN SUGGESTS</div>` +
            items.map(a => `
              <div class="sched-advice-row ${a.severity}">
                <span class="msg">${escapeHtml(a.msg)}</span>
                <button class="opt-btn" data-suggest-run="${escapeHtml(a.task_id)}">▶ RUN NOW</button>
                <button class="opt-btn test" data-suggest-enable="${escapeHtml(a.task_id)}">enable</button>
              </div>`).join('');
          advice.querySelectorAll('button[data-suggest-run]').forEach(btn => {
            btn.onclick = async () => {
              btn.disabled = true; btn.textContent = '…';
              await fetch('/api/schedule/run', {method:'POST', headers:{'content-type':'application/json'},
                body: JSON.stringify({task_id: btn.dataset.suggestRun})});
              setTimeout(renderSchedule, 1500);
            };
          });
          advice.querySelectorAll('button[data-suggest-enable]').forEach(btn => {
            btn.onclick = async () => {
              btn.disabled = true;
              await fetch('/api/schedule/toggle', {method:'POST', headers:{'content-type':'application/json'},
                body: JSON.stringify({task_id: btn.dataset.suggestEnable, enabled: true})});
              renderSchedule();
            };
          });
        } else {
          advice.innerHTML = '';
        }
      } catch (e) {/* ignore */}
    }
    await _loadAvailableModels();
    const r = await fetch('/api/schedule/status');
    const d = await r.json();
    const tasks = d.tasks || [];
    const eligibleCount = tasks.filter(t => t.eligible_now).length;
    const enabledCount = tasks.filter(t => t.enabled).length;
    if (meta) meta.textContent = `${enabledCount}/${tasks.length} aktywne · ${eligibleCount} gotowe`;

    // Info bar with STOP button when something runs
    const cpu = d.system_cpu_pct;
    const idle = d.user_idle_sec || 0;
    const running = d.currently_running;
    const runFor = running ? Math.max(0, (d.now - (d.currently_started || 0))) : 0;
    const prog = d.currently_progress || {};
    const stopRequested = d.stop_requested;
    let runBlock = '<span>scheduler: idle</span>';
    if (running) {
      const progStr = prog.total > 0
        ? ` ${prog.done}/${prog.total}${prog.label ? ' · ' + escapeHtml(prog.label.substr(0, 40)) : ''}`
        : '';
      runBlock = `<span class="running">▶ <b>${escapeHtml(running)}</b> (${_fmt_dur(runFor)})${progStr}</span>
                  <button class="opt-btn test sched-stop-btn"
                          ${stopRequested ? 'disabled' : ''}>
                    ${stopRequested ? '⏹ STOPPING…' : '⏹ STOP'}
                  </button>`;
    }
    info.innerHTML = `
      <span>system: <b>CPU ${cpu == null ? '?' : Math.round(cpu)}%</b></span>
      <span>ty: <b>idle ${_fmt_dur(idle)}</b></span>
      ${runBlock}
    `;
    const stopBtn = info.querySelector('.sched-stop-btn');
    if (stopBtn) stopBtn.onclick = async () => {
      stopBtn.disabled = true;
      await fetch('/api/schedule/stop', {method: 'POST'});
      renderSchedule();
    };

    // Per-task cards
    if (!tasks.length) {
      list.innerHTML = `<div class="dedup-empty">Brak skonfigurowanych zadań.</div>`;
    } else {
      list.innerHTML = tasks.map(t => {
        const badges = [];
        if (t.window === 'night') badges.push('<span class="sched-badge night">NOC 22-06</span>');
        else if (t.window === 'day') badges.push('<span class="sched-badge day">DZIEŃ 6-22</span>');
        if (t.require_idle_sec > 0) badges.push(`<span class="sched-badge idle">IDLE ${_fmt_dur(t.require_idle_sec)}</span>`);
        if (t.require_cpu_below < 100) badges.push(`<span class="sched-badge">CPU&lt;${t.require_cpu_below}%</span>`);
        badges.push(`<span class="sched-badge">co ${_fmt_dur(t.interval_sec)}</span>`);

        // ETA panel
        let etaPanel = '';
        const est = t.estimate || {};
        if (est.pending != null) {
          const eta_dur = est.eta_sec ? _fmt_dur(est.eta_sec) : '—';
          const modelPart = est.model
            ? `na <b>${escapeHtml(est.model)}</b> (~${est.rate_sec_per_unit}s/notatka)`
            : '';
          if (est.pending === 0) {
            etaPanel = '<div class="sched-eta done">✓ wszystko zrobione, nic w kolejce</div>';
          } else {
            const batchInfo = est.batch_size ? ` · batch ${est.batch_size}` : '';
            etaPanel = `<div class="sched-eta">
              <b>${est.pending}</b> do zrobienia · ETA <b>${eta_dur}</b> ${modelPart}${batchInfo}
            </div>`;
          }
        }

        // Model dropdown (only for redistill_thin variants)
        let modelDropdown = '';
        if (t.action === 'redistill_thin' || t.action === 'distill_missing') {
          const current = (t.action_args || {}).model || 'qwen2.5:14b';
          const opts = _availableModels.map(m =>
            `<option value="${escapeHtml(m)}" ${m === current ? 'selected' : ''}>${escapeHtml(m)}</option>`
          ).join('');
          modelDropdown = `
            <label class="sched-model">
              model:
              <select data-set-model="${escapeHtml(t.id)}">${opts}</select>
            </label>`;
        }

        const statusLine = t.eligible_now
          ? '<div class="sched-task-status ok">✓ gotowe do uruchomienia w następnym tick (max 60s)</div>'
          : `<div class="sched-task-status">⏸ blokery: ${t.block_reasons.map(escapeHtml).join(' · ')}</div>`;

        const lastRunLine = t.last_run
          ? `<div class="sched-task-status ${t.last_status === 'ok' ? 'ok' : (t.last_status === 'error' ? 'error' : '')}">ostatnio: ${_fmt_ts(t.last_run)} · ${escapeHtml(t.last_status || '?')}</div>`
          : '';
        // Cooldown indicator if last_stop_at set within 1h
        let cooldownLine = '';
        if (t.last_stop_at) {
          const now2 = Math.floor(Date.now() / 1000);
          const elapsed = now2 - t.last_stop_at;
          if (elapsed < 3600) {
            const mins = Math.ceil((3600 - elapsed) / 60);
            cooldownLine = `<div class="sched-task-status" style="color:var(--magenta)">
              ⏸ stop cooldown: ${mins} min do możliwego restartu
              <button class="opt-btn" data-clear-cooldown="${escapeHtml(t.id)}" style="padding:2px 8px;font-size:9px;margin-left:8px">CLEAR</button>
            </div>`;
          }
        }

        const isRunning = running === t.id;
        const taskClass = (t.eligible_now ? 'eligible ' : '') + (!t.enabled ? 'disabled ' : '') + (isRunning ? 'running ' : '');
        return `
          <div class="sched-task ${taskClass}" data-id="${escapeHtml(t.id)}">
            <div class="sched-task-head">
              <div class="sched-task-title">${escapeHtml(t.name)}</div>
              <div class="sched-badges">${badges.join('')}</div>
            </div>
            <div class="sched-task-desc">${escapeHtml(t.description || '')}</div>
            ${etaPanel}
            ${statusLine}
            ${lastRunLine}
            ${cooldownLine}
            <div class="sched-task-actions">
              <label class="sched-switch">
                <input type="checkbox" data-toggle="${escapeHtml(t.id)}" ${t.enabled ? 'checked' : ''}>
                enabled
              </label>
              ${modelDropdown}
              ${isRunning
                ? '<button class="opt-btn test sched-stop-btn">⏹ STOP</button>'
                : `<button class="opt-btn" data-run="${escapeHtml(t.id)}">▶ RUN NOW</button>`}
            </div>
          </div>`;
      }).join('');

      // Wire toggles
      list.querySelectorAll('input[data-toggle]').forEach(cb => {
        cb.onchange = async () => {
          await fetch('/api/schedule/toggle', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify({task_id: cb.dataset.toggle, enabled: cb.checked}),
          });
          renderSchedule();
        };
      });
      // Wire model selects
      list.querySelectorAll('select[data-set-model]').forEach(sel => {
        sel.onchange = async () => {
          await fetch('/api/schedule/set_model', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify({task_id: sel.dataset.setModel, model: sel.value}),
          });
          renderSchedule();
        };
      });
      // Wire RUN NOW
      list.querySelectorAll('button[data-run]').forEach(btn => {
        btn.onclick = async () => {
          btn.disabled = true; const orig = btn.textContent; btn.textContent = '…';
          await fetch('/api/schedule/run', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify({task_id: btn.dataset.run}),
          });
          setTimeout(() => { btn.textContent = orig; btn.disabled = false; renderSchedule(); }, 1500);
        };
      });
      // Wire CLEAR cooldown
      list.querySelectorAll('button[data-clear-cooldown]').forEach(btn => {
        btn.onclick = async () => {
          btn.disabled = true;
          await fetch('/api/schedule/clear-cooldown', {
            method: 'POST', headers: {'content-type': 'application/json'},
            body: JSON.stringify({task_id: btn.dataset.clearCooldown}),
          });
          renderSchedule();
        };
      });
      // Wire STOP (per-task)
      list.querySelectorAll('.sched-task .sched-stop-btn').forEach(btn => {
        btn.onclick = async () => {
          btn.disabled = true; btn.textContent = '⏹ STOPPING…';
          await fetch('/api/schedule/stop', {method: 'POST'});
          renderSchedule();
        };
      });
    }

    // Log
    const logs = d.log || [];
    if (!logs.length) {
      log.innerHTML = '<div class="sched-empty">brak historii</div>';
    } else {
      log.innerHTML = logs.map(e => {
        const ts = _fmt_ts(e.ts);
        const ok = e.ok ? 'ok' : 'err';
        let summary = '';
        if (e.ok && e.result) {
          summary = Object.entries(e.result).map(([k, v]) => `${k}=${v}`).join(' ');
        } else if (!e.ok) {
          summary = e.error || '';
        }
        return `<div class="sched-log-row">
          <span class="ts">${ts}</span>
          <span class="${ok}">${e.ok ? '✓' : '✗'}</span>
          <span>${escapeHtml(e.task_id)}</span>
          <span style="flex:1; color: var(--text-dim)">${escapeHtml(summary)}</span>
          <span style="color: var(--text-dim)">${e.duration || 0}s</span>
        </div>`;
      }).join('');
    }
  } catch (e) {
    info.innerHTML = `<span style="color: var(--red)">błąd: ${escapeHtml(e.message)}</span>`;
  }
}

let _schedTimer = null;
let _schedFastMode = false;

function initSchedule() {
  const refresh = $('#sched-refresh');
  if (refresh) refresh.onclick = () => renderSchedule();
  // Adaptive refresh: 5s while a task is running, 30s when idle
  const tick = async () => {
    if (!document.querySelector('#view-tools.active')) return;
    try {
      const r = await fetch('/api/schedule/status');
      const d = await r.json();
      const shouldBeFast = !!d.currently_running;
      if (shouldBeFast !== _schedFastMode) {
        _schedFastMode = shouldBeFast;
        clearInterval(_schedTimer);
        _schedTimer = setInterval(tick, _schedFastMode ? 5000 : 30000);
      }
      renderSchedule();
    } catch (e) { /* ignore */ }
  };
  _schedTimer = setInterval(tick, 30000);
}

// ============================================================================
// BOOTSTRAP
// ============================================================================
// ============================================================================
// CHEAT SHEET modal — top 10 magic prompts for ANY agent with brain MCP
// ============================================================================
const CHEAT_PROMPTS = [
  { cat: 'SEARCH', title: 'Recall — vault + library razem', code:
    `brain-rag.search_library query="<TWÓJ TEMAT>" top_k=5\nPokaż top wyniki z cytatami + nazwy plików źródłowych.\nUwaga: ranking promuje nowsze + większe notatki (recency boost) — najnowsze wnioski na górze.` },
  { cat: 'SEARCH', title: 'Tylko vault (rozmowy AI)', code:
    `brain-rag.search_library query="<TEMAT>" top_k=8 source="vault"\nTylko moje notatki z rozmów. Zignoruj książki.` },
  { cat: 'SEARCH', title: 'Tylko library (PDF/EPUB)', code:
    `brain-rag.search_library query="<TEMAT>" top_k=8 source="library"\nTylko z moich książek/PDFów. Cytuj page number.` },
  { cat: 'SEARCH', title: 'Cross-reference vault + library', code:
    `Najpierw brain-rag.search_library "<temat>" source="vault" — moje wnioski.\nPotem to samo z source="library" — co mówią książki.\nPorównaj i pokaż różnice / pokrycie.` },
  { cat: 'SEARCH', title: 'Wymień co jest w library', code:
    `brain-library: wymień wszystkie pliki, ich rozmiary i daty.\nGrupuj po typach: PDF / EPUB / DOCX.` },
  { cat: 'SAVE',   title: 'Zapisz tę rozmowę do brain', code:
    `Zapisz tę rozmowę używając brain-rag.save_conversation:\n- source: "<antigravity / claude-desktop / claude-code / cursor / vscode / windsurf / antigravity-cli>"\n- topic: krótki tytuł\n- summary: 2-3 zdania\n- decisions: lista decyzji\n- solutions: kod / komendy\n- facts: rzeczy nauczone\n- open_questions: pytania do follow-up\n- msg_count: liczba wymian\nPodaj ścieżkę pliku.` },
  { cat: 'SAVE',   title: 'Luźna notatka do vault', code:
    `Stwórz markdown notatkę o <TEMAT> i zapisz przez brain-vault.write_file w\n"notes/<data>_<temat-slug>.md" z YAML frontmatter (source: manual, date: ...).` },
  { cat: 'CASES',  title: 'Co jest w sprawach (lista)', code:
    `Pokaż listę spraw z brain. Otwórz w przeglądarce http://127.0.0.1:7860/#brain → sekcja SPRAWY · CASES.\nWypisz tytuły, kategorie, ile plików w każdej, ostatnia aktualizacja.\nLub czytaj prosto: brain-vault.list_directory path="../cases/" — sprawy są poza vault.` },
  { cat: 'CASES',  title: 'Przeczytaj analizę konkretnej sprawy', code:
    `brain-vault.read_text_file path="../cases/<kategoria>/<nazwa>/_summary.md"\nNotatka: cases są OBOK vault. Path zaczyna się od "../cases/".\nW _summary.md masz: streszczenie, kluczowe punkty, osoby, miejsca, akcje, deadliney, ryzyka.\nW _entities.json są kwoty, daty, NIPy, maile, telefony (regex).` },
  { cat: 'CASES',  title: 'Rozmawiaj o sprawie', code:
    `Przeczytaj _summary.md sprawy <KATEGORIA>/<NAZWA> przez brain-vault.read_text_file.\nPotem czytaj listę plików w pliki/ przez brain-vault.list_directory.\nOdpowiedz na moje pytania bazując na entities + summary, nie na surowych PDFach.` },
  { cat: 'SKILL',  title: 'Wymień skille', code:
    `brain-rag.list_skills\nPokaż mi co jest dostępne, do czego każdy służy.` },
  { cat: 'SKILL',  title: 'Trading digest', code:
    `brain-rag.run_skill name="trading-digest"\nPokaż wynik + jakie pliki zostały zacytowane.` },
  { cat: 'SKILL',  title: 'Session handoff (next agent)', code:
    `brain-rag.run_skill name="session-handoff"\nDaj mi wynikowy prompt do wklejenia w innym agencie.` },
  { cat: 'CODE',   title: 'Szukaj funkcji w moim kodzie', code:
    `brain-rag.search_code query="<co szukam>" top_k=8\nPokaż top wyniki z plikiem + numerami linii.` },
  { cat: 'CODE',   title: 'Status code index', code:
    `brain-rag.code_status\nPokaż które katalogi są zaindeksowane, ile plików w każdym języku.` },
  { cat: 'FILE',   title: 'Czytaj konkretną notatkę z vault', code:
    `brain-vault.read_text_file path="distilled/<nazwa-pliku.md>"\nPotem zrób mi z tego punktową listę kluczowych wniosków.` },
];

function _openCheatSheet() {
  let modal = $('#cheat-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'cheat-modal';
    modal.className = 'cheat-modal-backdrop';
    document.body.appendChild(modal);
  }
  const groups = {};
  CHEAT_PROMPTS.forEach((p, i) => {
    if (!groups[p.cat]) groups[p.cat] = [];
    groups[p.cat].push({...p, idx: i});
  });
  const catColors = {SEARCH: 'cyan', SAVE: 'magenta', CASES: 'amber', SKILL: 'amber', CODE: 'green', FILE: 'dim'};
  modal.innerHTML = `
    <div class="cheat-modal">
      <div class="cheat-head">
        <span class="cheat-title">🧠 MCP CHEAT SHEET</span>
        <span class="cheat-sub">działa w każdym agencie z brain MCP (Claude Desktop, Antigravity, Claude Code, Cursor, VS Code, Windsurf, antigravity-cli)</span>
        <button class="cheat-close" title="zamknij">✕</button>
      </div>
      <div class="cheat-body">
        ${Object.entries(groups).map(([cat, items]) => `
          <div class="cheat-group">
            <div class="cheat-cat cheat-cat-${catColors[cat] || 'dim'}">${cat}</div>
            ${items.map(p => `
              <div class="cheat-card">
                <div class="cheat-name">${escapeHtml(p.title)}</div>
                <pre class="cheat-code" id="cheat-code-${p.idx}">${escapeHtml(p.code)}</pre>
                <button class="opt-btn cheat-copy" data-target="cheat-code-${p.idx}">📋 COPY</button>
              </div>
            `).join('')}
          </div>
        `).join('')}
      </div>
    </div>`;
  modal.style.display = 'flex';
  modal.querySelector('.cheat-close').onclick = () => modal.style.display = 'none';
  modal.onclick = (e) => { if (e.target === modal) modal.style.display = 'none'; };
  modal.querySelectorAll('.cheat-copy').forEach(btn => {
    btn.onclick = async () => {
      const txt = $(`#${btn.dataset.target}`)?.textContent || '';
      try {
        await navigator.clipboard.writeText(txt);
        btn.textContent = '✓ COPIED';
        btn.classList.add('copied');
        setTimeout(() => { btn.textContent = '📋 COPY'; btn.classList.remove('copied'); }, 2000);
      } catch { btn.textContent = '✗ failed'; }
    };
  });
}

// ============================================================================
// DASHBOARD: Workflow ribbon (top of dashboard) — copy magic prompts
// ============================================================================
function initWorkflowRibbon() {
  const ribbon = $('#workflow-ribbon');
  if (!ribbon) return;
  // Restore collapsed state
  if (localStorage.getItem('brain.workflow.collapsed') === '1') {
    ribbon.classList.add('collapsed');
  }
  const toggle = $('#workflow-toggle');
  if (toggle) toggle.onclick = () => {
    ribbon.classList.toggle('collapsed');
    localStorage.setItem('brain.workflow.collapsed',
      ribbon.classList.contains('collapsed') ? '1' : '0');
  };
  // PANIC button — STOP ALL + GPU UNLOAD
  const panic = $('#panic-btn');
  if (panic) panic.onclick = async () => {
    if (!confirm('🚨 PANIC MODE\n\nStop wszystkich zadań (distill, redistill, RAG, code index) + unload modeli z VRAM + pauza schedulera 1h.\n\nKontynuować?')) return;
    panic.disabled = true;
    const orig = panic.textContent;
    panic.textContent = '🚨 STOPPING…';
    try {
      const r = await fetch('/api/panic', {method: 'POST'});
      const d = await r.json();
      if (d.ok) {
        const stopped = (d.stopped || []).join(', ') || '(nic nie biegało)';
        _showToast(`✓ ${d.msg}<br>Zatrzymane: ${stopped}`, 'ok', 8000);
        // Trigger poll refresh
        if (typeof _pollActiveJobs === 'function') _pollActiveJobs();
      } else {
        _showToast(`✗ Błąd: ${(d.errors || []).join('; ')}`, 'error', 8000);
      }
    } catch (e) { _showToast(`✗ ${e.message}`, 'error', 5000); }
    panic.textContent = orig; panic.disabled = false;
  };

  ribbon.querySelectorAll('.workflow-copy').forEach(btn => {
    btn.onclick = async () => {
      const target = btn.dataset.target;
      const text = $(`#${target}`)?.textContent || '';
      try {
        await navigator.clipboard.writeText(text);
        btn.textContent = '✓ COPIED';
        btn.classList.add('copied');
        setTimeout(() => {
          btn.textContent = '📋 COPY';
          btn.classList.remove('copied');
        }, 2000);
      } catch (e) {
        btn.textContent = '✗ failed';
        setTimeout(() => { btn.textContent = '📋 COPY'; }, 2000);
      }
    };
  });
}

// ============================================================================
// Notifications — auto-watch for new vault/sessions/ saves from agents
// ============================================================================
const _seenNotifs = new Set(JSON.parse(localStorage.getItem('brain.seenNotifs') || '[]'));

async function _pollNotifications() {
  try {
    const r = await fetch('/api/notifications');
    const d = await r.json();
    for (const n of (d.recent || [])) {
      if (_seenNotifs.has(n.name)) continue;
      if (n.age_sec > 60) { _seenNotifs.add(n.name); continue; }
      _seenNotifs.add(n.name);
      const srcColor = _srcColor ? _srcColor(n.source) : 'var(--cyan)';
      _showToast(
        `<b style="color:${srcColor}">💾 ${escapeHtml(n.source)}</b> zapisał notatkę: ${escapeHtml(n.name.slice(0, 60))}`,
        'ok', 6000
      );
    }
    // Persist seen names (cap 500) so reload doesn't re-fire
    const arr = Array.from(_seenNotifs).slice(-500);
    localStorage.setItem('brain.seenNotifs', JSON.stringify(arr));
  } catch (e) { /* swallow */ }
}

setInterval(_pollNotifications, 8000);

// ============================================================================
// Active Jobs floating panel — universal STOP for any long-running task
// ============================================================================
let _wasDistillRunning = false;
let _lastDistillProgress = null;

// Cache schedule status separately — refresh every 12s, not every 4s
let _scheduleStatusCache = {pausedUntil: 0, ts: 0};
async function _getScheduleStatus() {
  const now = Date.now();
  if (now - _scheduleStatusCache.ts < 12000) return _scheduleStatusCache.pausedUntil;
  try {
    const sr = await fetch('/api/schedule/status');
    const sd = await sr.json();
    _scheduleStatusCache = {
      pausedUntil: sd.global_paused ? (sd.paused_until || 0) : 0,
      ts: now,
    };
  } catch {}
  return _scheduleStatusCache.pausedUntil;
}

// Cache last rendered jobs signature — skip re-render if unchanged
let _lastJobsSig = '';

async function _pollActiveJobs() {
  try {
    const r = await fetch('/api/jobs/active');
    const d = await r.json();
    const jobs = d.jobs || [];

    // Detect distill task transition: running → finished
    const distillNow = jobs.find(j => j.kind === 'distill');
    if (distillNow && distillNow.progress) {
      _lastDistillProgress = distillNow.progress;
      _wasDistillRunning = true;
    } else if (_wasDistillRunning && !distillNow) {
      // Just finished — show celebration toast
      const p = _lastDistillProgress || {};
      _showToast(
        `<b style="color:var(--green)">✓ Destylacja zakończona</b><br>` +
        `${p.done || '?'}/${p.total || '?'} sesji przerobione · sprawdź <b>VAULT</b>`,
        'ok', 12000
      );
      _wasDistillRunning = false;
      _lastDistillProgress = null;
    }

    // Cached pause state (refresh every 12s instead of 4s)
    const pausedUntil = await _getScheduleStatus();

    let panel = $('#active-jobs');
    if (!jobs.length && !pausedUntil) {
      if (panel) panel.style.display = 'none';
      return;
    }
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'active-jobs';
      panel.className = 'active-jobs-panel';
      document.body.appendChild(panel);
    }
    panel.style.display = 'block';
    const now = d.now || (Date.now() / 1000);

    // Skip re-render if nothing changed — preserves DOM, avoids flicker
    const sig = JSON.stringify({
      // Note: deliberately DON'T include progress.done — that updates in-place
      // every tick. Including label change (file currently processing) so structure
      // refreshes when warnings appear/disappear.
      jobs: jobs.map(j => `${j.kind}:${j.pid || ''}:${j.stop_requested || ''}:${!!j.warning}:${j.progress?.total || 0}`),
      pause: pausedUntil > now ? Math.ceil(pausedUntil) : 0,
      collapsed: localStorage.getItem('brain.aj.collapsed') === '1',
    });
    if (sig === _lastJobsSig) {
      // Just update elapsed + progress in-place, no DOM rebuild
      jobs.forEach((j, i) => {
        const row = panel.querySelectorAll('.aj-row')[i];
        if (!row) return;
        const dur = j.started_at ? Math.max(0, Math.round(now - j.started_at)) : 0;
        const durStr = dur >= 3600 ? `${(dur/3600).toFixed(1)}h`
                     : dur >= 60 ? `${Math.round(dur/60)}min`
                     : `${dur}s`;
        const meta = row.querySelector('.aj-meta');
        if (meta) meta.textContent = `${j.kind} · ${durStr}${j.pid ? ' · PID '+j.pid : ''}`;
        // Live-update progress bar
        if (j.progress && j.progress.total) {
          const pct = Math.min(100, Math.round((j.progress.done / j.progress.total) * 100));
          const fill = row.querySelector('.aj-prog-fill');
          const txt  = row.querySelector('.aj-prog-text');
          if (fill) fill.style.width = pct + '%';
          if (txt) {
            const errPart = j.progress.errors ? ` · ${j.progress.errors} err` : '';
            const labelPart = j.progress.label ? ` · ${j.progress.label}` : '';
            txt.textContent = `${j.progress.done}/${j.progress.total} (${pct}%)${errPart}${labelPart}`;
          }
        }
      });
      return;
    }
    _lastJobsSig = sig;

    // Global pause banner
    let pauseBanner = '';
    if (pausedUntil > now) {
      const minsLeft = Math.ceil((pausedUntil - now) / 60);
      pauseBanner = `
        <div class="aj-pause-banner">
          ⏸ Scheduler wstrzymany na <b>${minsLeft} min</b>
          <button class="opt-btn aj-resume">▶ RESUME</button>
        </div>`;
    }

    const collapsed = localStorage.getItem('brain.aj.collapsed') === '1';
    panel.classList.toggle('collapsed', collapsed);
    const pauseFlag = pausedUntil > now ? ' ⏸' : '';
    panel.innerHTML = `
      <div class="aj-head">
        <span class="aj-title">⚙ ${jobs.length}${pauseFlag} ${collapsed ? '' : '· AKTYWNE ZADANIA'}</span>
        <div class="aj-head-actions">
          ${!pausedUntil && !collapsed ? '<button class="opt-btn test aj-pause-all" title="Wstrzymaj scheduler na 1h">⏸ PAUSE 1h</button>' : ''}
          <button class="aj-toggle" title="${collapsed ? 'rozwiń' : 'zwiń'}">${collapsed ? '▴' : '▾'}</button>
        </div>
      </div>
      ${pauseBanner}
      ${jobs.map(j => {
        const dur = j.started_at ? Math.max(0, Math.round(now - j.started_at)) : 0;
        const durStr = dur >= 3600 ? `${(dur/3600).toFixed(1)}h`
                     : dur >= 60 ? `${Math.round(dur/60)}min`
                     : `${dur}s`;
        const stopped = j.stop_requested;
        const isScheduler = j.kind === 'scheduler';
        // Progress bar — only if we have done/total
        let progressHtml = '';
        if (j.progress && j.progress.total) {
          const pct = Math.min(100, Math.round((j.progress.done / j.progress.total) * 100));
          const errPart = j.progress.errors ? ` <span class="aj-err">· ${j.progress.errors} err</span>` : '';
          const labelPart = j.progress.label
            ? `<span class="aj-prog-label" title="${escapeHtml(j.progress.label)}">${escapeHtml(j.progress.label)}</span>`
            : '';
          progressHtml = `
            <div class="aj-progress">
              <div class="aj-prog-bar"><div class="aj-prog-fill" style="width:${pct}%"></div></div>
              <div class="aj-prog-text">${j.progress.done}/${j.progress.total} (${pct}%)${errPart} ${labelPart}</div>
            </div>`;
        }
        // Warning banner — show last error if any (e.g. "Anthropic billing: brak kredytów")
        const warnHtml = j.warning
          ? `<div class="aj-warning" title="${escapeHtml(j.warning)}">⚠ ${escapeHtml(j.warning.slice(0, 90))}</div>`
          : '';
        return `
          <div class="aj-row" data-stop-url="${escapeHtml(j.stop_url)}" data-kind="${escapeHtml(j.kind)}">
            <div class="aj-info">
              <div class="aj-label">${escapeHtml(j.label)}</div>
              <div class="aj-meta">${escapeHtml(j.kind)} · ${durStr}${j.pid ? ' · PID '+j.pid : ''}</div>
              ${progressHtml}
              ${warnHtml}
            </div>
            <button class="opt-btn test aj-stop" ${stopped ? 'disabled' : ''}
              title="${isScheduler ? 'Stop + 1h cooldown na ten task' : 'Stop'}">
              ${stopped ? '⏹ STOPPING…' : '⏹ STOP'}
            </button>
          </div>`;
      }).join('')}`;

    panel.querySelectorAll('.aj-stop').forEach(btn => {
      btn.onclick = async () => {
        const url = btn.closest('.aj-row').dataset.stopUrl;
        const kind = btn.closest('.aj-row').dataset.kind;
        btn.disabled = true; btn.textContent = '⏹ STOPPING…';
        try {
          await fetch(url, {method: 'POST'});
          const cooldownMsg = kind === 'scheduler'
            ? 'Zatrzymano · cooldown 1h (task nie odpali się przez godzinę)'
            : 'Zatrzymano zadanie';
          _showToast(cooldownMsg, 'ok', 5000);
        } catch (e) { _showToast('Błąd: ' + e.message, 'error', 5000); }
        setTimeout(_pollActiveJobs, 1000);
      };
    });

    const pauseBtn = panel.querySelector('.aj-pause-all');
    if (pauseBtn) pauseBtn.onclick = async () => {
      pauseBtn.disabled = true; pauseBtn.textContent = '…';
      try {
        await fetch('/api/schedule/pause-all', {
          method: 'POST', headers: {'content-type': 'application/json'},
          body: JSON.stringify({seconds: 3600}),
        });
        _showToast('Scheduler wstrzymany na 1h. Możesz wznowić wcześniej.', 'ok', 6000);
      } catch (e) { _showToast('Błąd: ' + e.message, 'error', 5000); }
      setTimeout(_pollActiveJobs, 1000);
    };

    const toggleBtn = panel.querySelector('.aj-toggle');
    if (toggleBtn) toggleBtn.onclick = () => {
      // Instant CSS-only toggle — no network roundtrip, no re-render.
      // Next 4s poll will rebuild the title with proper "collapsed" state.
      const wasCollapsed = panel.classList.contains('collapsed');
      panel.classList.toggle('collapsed', !wasCollapsed);
      localStorage.setItem('brain.aj.collapsed', wasCollapsed ? '0' : '1');
      // Update the arrow + title text in-place so we don't wait for poll
      const titleEl = panel.querySelector('.aj-title');
      if (titleEl) {
        const arrow = wasCollapsed ? '▾' : '▴';
        toggleBtn.textContent = arrow;
        toggleBtn.title = wasCollapsed ? 'zwiń' : 'rozwiń';
        // Toggle "· AKTYWNE ZADANIA" suffix
        const t = titleEl.textContent;
        if (wasCollapsed && !t.includes('AKTYWNE')) {
          titleEl.textContent = t + ' · AKTYWNE ZADANIA';
        } else if (!wasCollapsed) {
          titleEl.textContent = t.replace(/\s*·\s*AKTYWNE ZADANIA\s*$/, '');
        }
      }
    };

    const resumeBtn = panel.querySelector('.aj-resume');
    if (resumeBtn) resumeBtn.onclick = async () => {
      resumeBtn.disabled = true;
      try {
        await fetch('/api/schedule/resume', {method: 'POST'});
        _showToast('Scheduler wznowiony', 'ok', 3000);
      } catch (e) { _showToast('Błąd: ' + e.message, 'error', 5000); }
      setTimeout(_pollActiveJobs, 1000);
    };
  } catch (e) { /* swallow */ }
}

setInterval(_pollActiveJobs, 4000);
_pollActiveJobs();

// ============================================================================
// OPTIONS: CONNECTIVITY (Ollama URL + SMB mount)
// ============================================================================
async function initConnectivity() {
  const url = $('#opt-ollama-url');
  if (!url) return;
  // Load existing
  try {
    const r = await fetch('/api/options');
    const o = await r.json();
    url.value = o.ollama_url || '';
    const cb = $('#opt-stats-api');
    if (cb) {
      cb.classList.toggle('on', o.stats_api_enabled !== false);
      if (!cb._wired) { cb._wired = true; cb.onclick = () => cb.classList.toggle('on'); }
    }
  } catch (e) { /* ignore */ }

  $('#opt-conn-save').onclick = async () => {
    const cb = $('#opt-stats-api');
    const body = {
      ollama_url: url.value,
      stats_api_enabled: cb ? cb.classList.contains('on') : true
    };
    const r = await fetch('/api/options', {method:'POST', headers:{'content-type':'application/json'},
                                           body: JSON.stringify(body)});
    const d = await r.json();
    if (d.ok) {
      _showToast('Zapisano. Restart dashboardu by zastosować ollama_url.', 'ok', 5000);
    } else _showToast('Błąd zapisu', 'error', 4000);
  };

  $('#opt-ollama-test').onclick = async () => {
    const st = $('#opt-ollama-status');
    st.textContent = '…';
    const r = await fetch('/api/options/ollama/test', {method:'POST'});
    const d = await r.json();
    st.textContent = d.ok ? `✓ OK · ${d.models} modeli @ ${d.url}` : `✗ ${d.error}`;
    st.style.color = d.ok ? 'var(--green)' : 'var(--red,#f55)';
  };
}

initWorkflowRibbon();
initChat();
initVault();
initAgents();
initSkills();
initCliSkills();
initCodeIndex();
initSchedule();
initLogs();
initGraph();
initLibrary();
initTranscripts();
initRedistill();
initMCP();
initBackups();
initIdleGuard();
initConnectivity();

refresh();
setInterval(refresh, 3000);
setInterval(() => $('#meta-time').textContent = fmtTime(), 1000);
