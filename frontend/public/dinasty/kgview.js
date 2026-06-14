// Di-nasty — KG view: lightweight live graph overlay for scouting/KG events.
window.DN = window.DN || {};

DN.kgview = (function () {
  const K = {};
  let root = null;
  let svg = null;
  let statusEl = null;
  let detailEl = null;
  let legendEl = null;
  let nodes = new Map();
  let edges = [];
  let selectedId = null;
  let renderQueued = false;
  const colors = {
    match: '#3FA89F',
    team: '#E8A23D',
    scout: '#8E79C4',
    finding: '#D96E54',
    evidence_claim: '#4E7E2A',
    source: '#5E5440',
    player: '#B07E1C',
    default: '#2C2820',
  };
  const groupDefs = [
    { id: 'matches', label: 'Matches', types: ['match', 'match_result'], x: 470, y: 220, color: '#3FA89F' },
    { id: 'teams', label: 'Teams', types: ['team', 'team_match_profile', 'player', 'player_match_profile'], x: 250, y: 255, color: '#E8A23D' },
    { id: 'scouts', label: 'Scouts', types: ['scout', 'scout_match_profile', 'prediction', 'predictor', 'genome'], x: 690, y: 255, color: '#8E79C4' },
    { id: 'evidence', label: 'Evidence', types: ['finding', 'evidence_claim', 'debate_claim', 'scouting_topic', 'team_scouting_topic', 'scouting_gap'], x: 470, y: 360, color: '#D96E54' },
    { id: 'sources', label: 'Sources', types: ['source', 'source_domain', 'source_domain_profile', 'source_kind', 'source_quality', 'source_recency'], x: 790, y: 125, color: '#5E5440' },
    { id: 'context', label: 'Context', types: ['venue', 'group', 'stage', 'claim_type', 'claim_impact', 'claim_quality', 'metric', 'formation', 'position', 'club'], x: 150, y: 125, color: '#4E7E2A' },
  ];
  const groupByType = {};
  groupDefs.forEach((group) => group.types.forEach((type) => { groupByType[type] = group; }));

  function ensure() {
    if (root) return;
    root = document.createElement('div');
    root.id = 'kg-overlay';
    root.className = 'panel';
    root.innerHTML =
      '<div class="kg-head">' +
        '<div><div class="kg-k">Knowledge Graph</div><div class="kg-title" id="kg-title">KG stream</div></div>' +
        '<button class="kg-close" id="kg-close">×</button>' +
      '</div>' +
      '<div class="kg-status" id="kg-status">Waiting for graph events...</div>' +
      '<div class="kg-legend" id="kg-legend"></div>' +
      '<svg id="kg-svg" viewBox="0 0 940 460" preserveAspectRatio="xMidYMid meet"></svg>' +
      '<div class="kg-detail" id="kg-detail">Click a node for details.</div>';
    document.body.appendChild(root);
    svg = root.querySelector('#kg-svg');
    statusEl = root.querySelector('#kg-status');
    detailEl = root.querySelector('#kg-detail');
    legendEl = root.querySelector('#kg-legend');
    root.querySelector('#kg-close').addEventListener('click', () => root.classList.remove('show'));
    svg.addEventListener('click', (event) => {
      const nodeEl = event.target.closest && event.target.closest('.kg-node');
      if (!nodeEl) return;
      selectNode(decodeURIComponent(nodeEl.getAttribute('data-node')));
    });
    svg.addEventListener('keydown', (event) => {
      const nodeEl = event.target.closest && event.target.closest('.kg-node');
      if (!nodeEl || (event.key !== 'Enter' && event.key !== ' ')) return;
      event.preventDefault();
      selectNode(decodeURIComponent(nodeEl.getAttribute('data-node')));
    });
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function labelFor(entity) {
    return entity.name || entity.entity_id || entity.id || 'node';
  }

  function typeFor(entity) {
    return entity.entity_type || entity.type || 'default';
  }

  function groupFor(entity) {
    return groupByType[typeFor(entity)] || { id: 'other', label: 'Other', x: 470, y: 95, color: colors.default };
  }

  function shortLabel(value) {
    const label = String(value || '');
    return label.length > 30 ? label.slice(0, 28) + '...' : label;
  }

  function relationLabel(value) {
    return String(value || 'related_to').replace(/_/g, ' ');
  }

  function compactValue(value) {
    if (value == null || value === '') return 'n/a';
    if (Array.isArray(value)) return value.join(' - ');
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  function nodeUrl(id) {
    return '#kg/' + encodeURIComponent(id);
  }

  function attributesFor(node) {
    const attrs = node.attributes || {};
    return Object.keys(attrs)
      .filter((key) => attrs[key] != null && attrs[key] !== '')
      .slice(0, 8)
      .map((key) => ({ key, value: compactValue(attrs[key]) }));
  }

  function relatedFor(id) {
    return edges
      .map((edge) => {
        const sourceId = edge.source_id || edge.source;
        const targetId = edge.target_id || edge.target;
        if (sourceId !== id && targetId !== id) return null;
        const neighborId = sourceId === id ? targetId : sourceId;
        const node = nodes.get(neighborId);
        if (!node) return null;
        return {
          edge,
          node,
          id: neighborId,
          outgoing: sourceId === id,
          relation: relationLabel(edge.relation_type),
        };
      })
      .filter(Boolean)
      .sort((a, b) => {
        const aMatch = typeFor(a.node) === 'match' ? 0 : 1;
        const bMatch = typeFor(b.node) === 'match' ? 0 : 1;
        if (aMatch !== bMatch) return aMatch - bMatch;
        return labelFor(a.node).localeCompare(labelFor(b.node));
      });
  }

  function describeNode(node, related) {
    const type = typeFor(node);
    if (type === 'team') {
      const matches = related.filter((item) => typeFor(item.node) === 'match');
      const home = related.filter((item) => item.edge.relation_type === 'plays_home_in').length;
      const away = related.filter((item) => item.edge.relation_type === 'plays_away_in').length;
      return matches.length + ' linked matches · ' + home + ' home · ' + away + ' away';
    }
    if (type === 'match') {
      const attrs = node.attributes || {};
      const teams = related.filter((item) => typeFor(item.node) === 'team').map((item) => labelFor(item.node));
      return [teams.join(' vs '), attrs.date, attrs.time, attrs.ground].filter(Boolean).join(' · ');
    }
    if (type === 'evidence_claim' || type === 'finding') {
      return related.length + ' linked KG nodes';
    }
    return related.length + ' connected nodes';
  }

  function renderDetail(id) {
    const node = nodes.get(id);
    if (!node || !detailEl) return;
    const attrs = attributesFor(node);
    const related = relatedFor(id);
    const visibleRelated = related.slice(0, 14);
    const hiddenCount = Math.max(0, related.length - visibleRelated.length);
    const attrMarkup = attrs.length
      ? '<div class="kg-attrs">' + attrs.map((item) =>
        '<div><span>' + escapeHtml(item.key.replace(/_/g, ' ')) + '</span><b>' + escapeHtml(item.value) + '</b></div>'
      ).join('') + '</div>'
      : '';
    const linksMarkup = visibleRelated.length
      ? '<div class="kg-links">' + visibleRelated.map((item) =>
        '<a href="' + nodeUrl(item.id) + '" data-kg-jump="' + encodeURIComponent(item.id) + '">' +
          '<i>' + escapeHtml(typeFor(item.node).replace(/_/g, ' ')) + '</i>' +
          '<span>' + escapeHtml(shortLabel(labelFor(item.node))) + '</span>' +
          '<em>' + escapeHtml((item.outgoing ? '-> ' : '<- ') + item.relation) + '</em>' +
        '</a>'
      ).join('') + (hiddenCount ? '<div class="kg-more">+' + hiddenCount + ' more linked nodes</div>' : '') + '</div>'
      : '<div class="kg-more">No loaded links yet.</div>';

    detailEl.innerHTML =
      '<div class="kg-detail-head">' +
        '<div><b>' + escapeHtml(typeFor(node).replace(/_/g, ' ')) + '</b><strong>' + escapeHtml(labelFor(node)) + '</strong></div>' +
        '<a class="kg-url" href="' + nodeUrl(id) + '" data-kg-jump="' + encodeURIComponent(id) + '">' + escapeHtml('kg://' + id) + '</a>' +
      '</div>' +
      '<p>' + escapeHtml(describeNode(node, related)) + '</p>' +
      attrMarkup +
      '<div class="kg-subhead">Linked nodes</div>' +
      linksMarkup;

    detailEl.querySelectorAll('[data-kg-jump]').forEach((link) => {
      link.addEventListener('click', (event) => {
        event.preventDefault();
        selectNode(decodeURIComponent(link.getAttribute('data-kg-jump')));
      });
    });
  }

  function selectNode(id) {
    if (!nodes.has(id)) return;
    selectedId = id;
    renderDetail(id);
    requestRender();
  }

  function requestRender() {
    if (renderQueued) return;
    renderQueued = true;
    const frame = window.requestAnimationFrame || ((fn) => setTimeout(fn, 16));
    frame(() => {
      renderQueued = false;
      render();
    });
  }

  function addNode(entity, silent) {
    if (!entity) return;
    const id = entity.entity_id || entity.id;
    if (!id) return;
    nodes.set(id, entity);
    if (!silent) requestRender();
  }

  function addEdge(relationship, silent) {
    if (!relationship) return;
    edges.push(relationship);
    if (!silent) requestRender();
  }

  function positionedNodes() {
    const values = Array.from(nodes.values());
    const grouped = {};
    values.forEach((node) => {
      const group = groupFor(node);
      grouped[group.id] = grouped[group.id] || [];
      grouped[group.id].push(node);
    });
    const placed = [];
    Object.keys(grouped).forEach((groupId) => {
      const groupNodes = grouped[groupId];
      const group = groupFor(groupNodes[0]);
      const count = Math.max(groupNodes.length, 1);
      groupNodes.forEach((node, index) => {
        const angle = index * 2.399963229728653;
        const radius = count < 2 ? 0 : 12 + Math.sqrt(index / count) * Math.min(96, 18 + count * 2.1);
        placed.push({
          node,
          group,
          groupIndex: index,
          x: group.x + Math.cos(angle) * radius,
          y: group.y + Math.sin(angle) * radius,
        });
      });
    });
    return placed;
  }

  function renderLegend() {
    if (!legendEl) return;
    const counts = {};
    Array.from(nodes.values()).forEach((node) => {
      const group = groupFor(node);
      counts[group.id] = (counts[group.id] || 0) + 1;
    });
    legendEl.innerHTML = groupDefs
      .filter((group) => counts[group.id])
      .map((group) =>
        '<span class="kg-chip"><i style="background:' + group.color + '"></i>' +
        escapeHtml(group.label) + ' <b>' + counts[group.id] + '</b></span>'
      )
      .join('');
  }

  function relationBands(byId) {
    const bands = new Map();
    edges.forEach((edge) => {
      const source = byId.get(edge.source_id || edge.source);
      const target = byId.get(edge.target_id || edge.target);
      if (!source || !target || source.group.id === target.group.id) return;
      const ids = [source.group.id, target.group.id].sort();
      const key = ids.join(':');
      const existing = bands.get(key) || { a: source.group, b: target.group, count: 0 };
      existing.count += 1;
      bands.set(key, existing);
    });
    return Array.from(bands.values()).sort((a, b) => b.count - a.count).slice(0, 14);
  }

  function groupBackgrounds() {
    return groupDefs.map((group) => {
      const count = Array.from(nodes.values()).filter((node) => groupFor(node).id === group.id).length;
      if (!count) return '';
      const radius = Math.min(124, 46 + Math.sqrt(count) * 8);
      return '<g class="kg-group">' +
        '<circle cx="' + group.x + '" cy="' + group.y + '" r="' + radius + '" style="--kg-color:' + group.color + '"></circle>' +
        '<text x="' + group.x + '" y="' + (group.y - radius - 11) + '">' + escapeHtml(group.label) + ' · ' + count + '</text>' +
      '</g>';
    }).join('');
  }

  function render() {
    if (!svg) return;
    renderLegend();
    const placed = positionedNodes();
    const byId = new Map(placed.map((item) => [item.node.entity_id || item.node.id, item]));
    const selectedRelatedIds = selectedId ? new Set(relatedFor(selectedId).map((item) => item.id).concat(selectedId)) : null;
    const selectedLines = selectedId ? relatedFor(selectedId).slice(0, 28).map((item) => {
      const a = byId.get(selectedId);
      const b = byId.get(item.id);
      if (!a || !b) return '';
      return '<line class="kg-selected-edge" x1="' + a.x + '" y1="' + a.y + '" x2="' + b.x + '" y2="' + b.y + '"></line>';
    }).join('') : '';
    const bandMarkup = relationBands(byId).map((band) => {
      const mx = (band.a.x + band.b.x) / 2;
      const my = (band.a.y + band.b.y) / 2 - 48;
      const width = Math.min(14, 2 + Math.sqrt(band.count));
      return '<path class="kg-band" d="M ' + band.a.x + ' ' + band.a.y + ' Q ' + mx + ' ' + my + ' ' + band.b.x + ' ' + band.b.y + '" stroke-width="' + width + '"></path>';
    }).join('');
    const nodeMarkup = placed.map((item) => {
      const node = item.node;
      const id = node.entity_id || node.id;
      const type = typeFor(node);
      const color = colors[type] || item.group.color || colors.default;
      const radius = type === 'match' ? 8 : type === 'team' ? 7 : 5;
      const label = item.groupIndex < 3 && (type === 'match' || type === 'team') ? '<text y="' + (radius + 13) + '">' + escapeHtml(shortLabel(labelFor(node))) + '</text>' : '';
      const classes = 'kg-node' +
        (id === selectedId ? ' selected' : '') +
        (selectedRelatedIds && !selectedRelatedIds.has(id) ? ' dim' : '');
      return '<g class="' + classes + '" data-node="' + encodeURIComponent(id) + '" tabindex="0" role="button" transform="translate(' + item.x + ' ' + item.y + ')">' +
        '<circle r="' + radius + '" fill="' + color + '"></circle>' +
        label +
      '</g>';
    }).join('');
    svg.innerHTML = groupBackgrounds() + bandMarkup + selectedLines + nodeMarkup;
  }

  K.reset = function (title) {
    ensure();
    nodes = new Map();
    edges = [];
    selectedId = null;
    root.querySelector('#kg-title').textContent = title || 'KG stream';
    statusEl.textContent = 'Waiting for graph events...';
    legendEl.innerHTML = '';
    detailEl.innerHTML = '<span>Click a node for details.</span>';
    svg.innerHTML = '';
    root.classList.add('show');
  };

  K.status = function (text) {
    ensure();
    statusEl.textContent = text;
    root.classList.add('show');
  };

  K.ingest = function (event) {
    ensure();
    if (!event || !event.event_type) return;
    if (event.event_type === 'kg_stage') {
      const entities = event.entity_count != null ? ' · ' + event.entity_count + ' entities' : '';
      const links = event.relationship_count != null ? ' · ' + event.relationship_count + ' links' : '';
      K.status(String(event.stage || 'kg_stage').replace(/_/g, ' ') + entities + links);
    } else if (event.event_type === 'kg_entity') {
      addNode(event.entity);
      K.status(nodes.size + ' entities streamed · ' + edges.length + ' links');
    } else if (event.event_type === 'kg_relationship') {
      addEdge(event.relationship);
      K.status(nodes.size + ' entities streamed · ' + edges.length + ' links');
    } else if (event.event_type === 'kg_manifest') {
      const manifest = event.manifest || {};
      K.status('Manifest ready · ' + (manifest.entity_count || nodes.size) + ' entities · ' + (manifest.relationship_count || edges.length) + ' links');
    } else if (event.event_type === 'scouting_audit') {
      K.status('Scouting audit ready · backlog ' + (event.backlog_count == null ? 'n/a' : event.backlog_count));
    }
  };

  K.showGraph = function (graph, title) {
    K.reset(title || 'World Cup KG');
    (graph.entities || []).forEach((entity) => addNode(entity, true));
    (graph.relationships || []).forEach((relationship) => addEdge(relationship, true));
    render();
    K.status((graph.entity_count || nodes.size) + ' KG entities · ' + (graph.relationship_count || edges.length) + ' links');
  };

  return K;
})();
