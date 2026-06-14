// WorldColony — bottom log terminal. Streams every ant action as a
// timestamped, color-coded console row. Multi-line scrollback, clickable
// ant IDs that re-select via DN.app.selectAnt.
window.DN = window.DN || {};

// Version marker — visible in the browser console as the new build loads.
// If you don't see this on refresh, the page is serving cached old JS.
console.log('[worldcolony] logTerm.js loaded · build 2026-06-14');

DN.logTerm = (function () {
  const T = {};
  const MAX_ROWS = 200;
  let root, scroller, toggleBtn, visible = true;
  let initialized = false;

  // tag → CSS color
  const TAG_COLORS = {
    SPEAK:     '#FFD988',
    DISPUTE:   '#FF8B6B',
    INFLUENCE: '#B47EE0',
    FORECAST:  '#66E0FF',
    SCOUT:     '#8E79C4',
    KG:        '#3FA89F',
    STAKE:     '#6DD68A',
    CHAIN:     '#8BE9FD',
    X402:      '#E8A23D',
    SETTLE:    '#C8F7A1',
    BIRTH:     '#FFE9A0',
    DEATH:     '#8C7E60',
    FOUND:     '#E8A23D',
    MIGRATE:   '#5DB0E8',
    SYSTEM:    '#A8A09A',
    SCOUT:     '#8E79C4',
    KG:        '#3FA89F'
  };

  // simple inline CSS injection — no edits to styles.css
  const CSS = `
    #ant-log {
      position: fixed; left: 14px; right: 290px; bottom: 14px; height: 188px;
      background: rgba(12, 8, 4, 0.86);
      border: 1px solid rgba(196, 142, 68, 0.35);
      border-radius: 10px; padding: 8px 12px;
      font-family: var(--mono, ui-monospace), monospace; font-size: 11px;
      color: rgba(241, 216, 168, 0.82);
      overflow: hidden; backdrop-filter: blur(8px) saturate(1.05);
      -webkit-backdrop-filter: blur(8px) saturate(1.05);
      z-index: 4; pointer-events: auto;
      display: flex; flex-direction: column;
    }
    #ant-log .log-head {
      display: flex; align-items: center; gap: 8px;
      padding-bottom: 6px; border-bottom: 1px solid rgba(196, 142, 68, 0.18);
      font-size: 10px; letter-spacing: 2px; text-transform: uppercase;
      color: rgba(241, 216, 168, 0.55); font-weight: 700;
    }
    #ant-log .log-head .dot {
      width: 7px; height: 7px; border-radius: 999px;
      background: #6DD68A; box-shadow: 0 0 6px #6DD68A;
    }
    #ant-log .log-clear {
      margin-left: auto; cursor: pointer; padding: 2px 8px;
      color: rgba(241, 216, 168, 0.55);
      border: 1px solid rgba(196, 142, 68, 0.25); border-radius: 4px;
    }
    #ant-log .log-clear:hover { color: #FFD988; }
    #ant-log .log-scroll {
      flex: 1; overflow-y: auto; padding: 4px 4px 4px 0;
      scroll-behavior: smooth;
    }
    #ant-log .log-scroll::-webkit-scrollbar { width: 6px; }
    #ant-log .log-scroll::-webkit-scrollbar-thumb {
      background: rgba(196, 142, 68, 0.3); border-radius: 4px;
    }
    #ant-log .log-row {
      display: flex; gap: 10px; padding: 2px 0;
      line-height: 1.45; opacity: 0; animation: log-in 240ms ease forwards;
    }
    @keyframes log-in {
      from { opacity: 0; transform: translateX(-4px); }
      to   { opacity: 1; transform: translateX(0); }
    }
    #ant-log .log-ts {
      flex: none; width: 56px; color: rgba(241, 216, 168, 0.4);
      font-variant-numeric: tabular-nums;
    }
    #ant-log .log-tag {
      flex: none; width: 76px; font-weight: 700; letter-spacing: 1px;
    }
    #ant-log .log-msg { flex: 1; word-break: break-word; }
    #ant-log .log-msg .ant-ref {
      color: #FFD988; cursor: pointer;
      text-decoration: underline dotted rgba(255, 217, 136, 0.45);
    }
    #ant-log .log-msg .ant-ref:hover { color: #FFE9A0; }
    #log-toggle {
      position: fixed; top: 30px; right: 470px;
      padding: 8px 14px; border-radius: 8px;
      background: rgba(12, 8, 4, 0.7);
      border: 1px solid rgba(196, 142, 68, 0.3);
      color: rgba(241, 216, 168, 0.78);
      font-family: var(--mono, ui-monospace), monospace;
      font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase;
      cursor: pointer; z-index: 5; pointer-events: auto;
      transition: background 120ms ease, color 120ms ease;
    }
    #log-toggle:hover { color: #FFD988; }
    #log-toggle.on {
      background: rgba(232, 184, 90, 0.18);
      border-color: rgba(232, 184, 90, 0.55); color: #FFD988;
    }
  `;

  function fmtTime(d) {
    d = d || new Date();
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    const s = String(d.getSeconds()).padStart(2, '0');
    return h + ':' + m + ':' + s;
  }

  // escape user-controlled text before injecting into the DOM
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  // wrap any ant_NNNN or ant-NNNN or ENS-style "<name>.eth" tokens in
  // clickable spans. Called after escapeHtml so we know the input is safe.
  function linkifyAntIds(html) {
    return html.replace(/\b(ant[_-]\d{3,5})\b/g, (m) => {
      const id = m.replace('-', '_');
      return `<span class="ant-ref" data-agent="${id}">${m}</span>`;
    }).replace(/\b([a-z0-9-]+\.colonny\.eth)\b/g, (m) => {
      return `<span class="ant-ref" data-agent="${m}">${m}</span>`;
    });
  }

  function onAntRefClick(ev) {
    const span = ev.target && ev.target.closest && ev.target.closest('.ant-ref');
    if (!span) return;
    const id = span.getAttribute('data-agent');
    if (!id || !DN.ants || !DN.ants.list) return;
    // Find an ant whose agentRecord matches the id (by agent_id or ens_name).
    const ant = DN.ants.list.find(a => a.agentRecord && (
      a.agentRecord.agent_id === id ||
      a.agentRecord.ens_name === id ||
      a.agentRecord.name === id
    )) || DN.ants.heroes.find(a => a.id === id) || null;
    if (ant && DN.app && DN.app.selectAnt) DN.app.selectAnt(ant);
  }

  function ensureUI() {
    if (initialized) return;
    initialized = true;
    const style = document.createElement('style');
    style.id = 'ant-log-css';
    style.textContent = CSS;
    document.head.appendChild(style);

    root = document.createElement('div');
    root.id = 'ant-log';
    root.innerHTML =
      '<div class="log-head">' +
        '<span class="dot"></span><span>Colony Log · live</span>' +
        '<span class="log-clear" id="ant-log-clear">clear</span>' +
      '</div>' +
      '<div class="log-scroll" id="ant-log-scroll"></div>';
    document.body.appendChild(root);
    scroller = document.getElementById('ant-log-scroll');
    scroller.addEventListener('click', onAntRefClick);
    // Autoscroll = true by default. User pauses it by scrolling up
    // (wheel/touch/keyboard); resumes it by scrolling back to the
    // bottom. Programmatic scrollTop writes from flush() are excluded
    // via the _ignoreScroll flag.
    T._autoscroll = true;
    T._ignoreScroll = false;
    scroller.addEventListener('scroll', () => {
      if (T._ignoreScroll) return;
      const atBottom = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 4;
      T._autoscroll = atBottom;
    }, { passive: true });
    document.getElementById('ant-log-clear').addEventListener('click', () => T.clear());

    toggleBtn = document.createElement('button');
    toggleBtn.id = 'log-toggle';
    toggleBtn.textContent = 'Logs';
    toggleBtn.classList.add('on');
    toggleBtn.addEventListener('click', () => T.setVisible(!visible));
    document.body.appendChild(toggleBtn);

    // restore preference
    try {
      const saved = localStorage.getItem('ant-log-visible');
      if (saved === '0') T.setVisible(false);
    } catch (_) { /* ignore */ }

    // welcome row
    T.push('SYSTEM', 'Colony log initialised. Streaming live agent activity.');
  }

  T.init = function () { ensureUI(); return T; };

  // Buffered queue: pushes synchronously enqueue, then a single rAF flush
  // appends everything as one DocumentFragment so 60 push() calls in a row
  // cause one reflow, not 60. Drops the cost of bulk log streams from
  // ~120ms to ~5ms on a typical laptop.
  const _queue = [];
  let _flushScheduled = false;
  function scheduleFlush() {
    if (_flushScheduled) return;
    _flushScheduled = true;
    (typeof requestAnimationFrame === 'function' ? requestAnimationFrame : (cb => setTimeout(cb, 16)))(flush);
  }
  function flush() {
    _flushScheduled = false;
    if (!_queue.length || !scroller) return;
    const frag = document.createDocumentFragment();
    for (let i = 0; i < _queue.length; i++) {
      const item = _queue[i];
      const row = document.createElement('div');
      row.className = 'log-row';
      row.innerHTML =
        `<span class="log-ts">${item.ts}</span>` +
        `<span class="log-tag" style="color:${item.color}">${escapeHtml(item.level)}</span>` +
        `<span class="log-msg">${item.safe}</span>`;
      frag.appendChild(row);
    }
    _queue.length = 0;
    scroller.appendChild(frag);
    let overflow = scroller.children.length - MAX_ROWS;
    while (overflow-- > 0) scroller.removeChild(scroller.firstChild);
    if (T._autoscroll) {
      T._ignoreScroll = true;
      scroller.scrollTop = scroller.scrollHeight;
      // clear flag on next tick — the scroll event fires async
      setTimeout(() => { T._ignoreScroll = false; }, 0);
    }
  }

  // Append a row. opts can include { color, ts, antIds }.
  T.push = function (level, message, opts) {
    ensureUI();
    opts = opts || {};
    const ts = opts.ts ? fmtTime(new Date(opts.ts)) : fmtTime();
    const color = opts.color || TAG_COLORS[level] || '#FFD988';
    const safe = linkifyAntIds(escapeHtml(message));
    _queue.push({ ts, color, level, safe });
    scheduleFlush();
  };

  T.clear = function () { if (scroller) scroller.innerHTML = ''; };

  T.setVisible = function (on) {
    visible = !!on;
    if (root) root.style.display = visible ? 'flex' : 'none';
    if (toggleBtn) toggleBtn.classList.toggle('on', visible);
    try { localStorage.setItem('ant-log-visible', visible ? '1' : '0'); } catch (_) { /* ignore */ }
  };

  return T;
})();
