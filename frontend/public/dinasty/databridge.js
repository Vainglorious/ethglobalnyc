// Di-nasty — data bridge: seeds the colonies' stats and the thoughts ticker
// from the REAL harness output (public/data/demo.jsonl). Non-invasive: main.js
// prefers DN.databridge.nextThought() when ready, and we seed DN.colony.list
// stats once the colonies exist. Everything degrades gracefully if the file
// is missing (the app falls back to its synthetic content).
window.DN = window.DN || {};

DN.databridge = (function () {
  const B = { ready: false, source: '/data/demo.jsonl' };
  let thoughts = [];
  let ti = 0;
  let records = [], forecasts = [], summary = null;
  const COL = { debate: '#8E79C4', forecast: '#3FA89F', economy: '#E8A23D', lineage: '#D96E54' };

  const r1 = (n) => Math.round((n || 0) * 10) / 10;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function build(events) {
    records = events.filter((e) => e.event_type === 'agent_record');
    forecasts = events.filter((e) => e.event_type === 'forecast');
    const debates = events.filter((e) => e.event_type === 'debate_claim');
    summary = events.find((e) => e.event_type === 'round_summary') || null;

    const q = [];
    if (summary) {
      q.push([
        'Round resolved — market home probability ' +
          Math.round(summary.market_home_probability * 100) +
          '%, $' + r1(summary.total_staked) + ' staked across ' + summary.population +
          ' agents (' + summary.home_bets + ' home · ' + summary.away_bets + ' away · ' + summary.passes + ' pass).',
        'Forecast', COL.economy,
      ]);
    }
    // real debate transcript lines (already human-readable)
    debates.forEach((d) => {
      if (d.message) q.push([d.message, 'Debate', COL.debate]);
    });
    // strongest real bets
    forecasts
      .filter((f) => f.side && f.side !== 'pass' && f.stake > 0)
      .sort((a, b) => b.stake - a.stake)
      .slice(0, 8)
      .forEach((f) => {
        const nm = (f.agent_id || 'agent').replace('_', '-');
        q.push([
          nm + ' commits ' + r1(f.stake) + ' USDC ' + f.side + ' @ ' +
            Math.round(f.home_probability * 100) + '% (edge ' + r1(f.edge) + ')',
          'Forecast', COL.forecast,
        ]);
      });
    // lineage leader
    const top = records.slice().sort((a, b) => b.bankroll - a.bankroll)[0];
    if (top) {
      q.push([
        (top.name || top.agent_id) + ' leads the gene pool — ' +
          Math.round(top.accuracy * 100) + '% accuracy, ' + r1(top.bankroll) + ' USDC bankroll.',
        'Lineage', COL.lineage,
      ]);
    }
    if (q.length) thoughts = q;
    B.ready = thoughts.length > 0;
  }

  // seed colony stats from the real agents, split across the factions
  function applyStats() {
    if (!DN.colony || !DN.colony.list || !DN.colony.list.length || !records.length) return false;
    const stakeByAgent = {};
    forecasts.forEach((f) => { stakeByAgent[f.agent_id] = f.stake || 0; });
    const n = DN.colony.list.length;
    DN.colony.list.forEach((c, i) => {
      const grp = records.filter((_, idx) => idx % n === i);
      if (!grp.length) return;
      const accAvg = grp.reduce((s, r) => s + r.accuracy, 0) / grp.length;
      const bankAvg = grp.reduce((s, r) => s + r.bankroll, 0) / grp.length;
      const treasury = grp.reduce((s, r) => s + r.bankroll, 0); // ~real USDC held
      const stakedNow = grp.reduce((s, r) => s + (stakeByAgent[r.agent_id] || 0), 0);
      c.stats.population = grp.length;
      c.stats.accuracy = Math.round(accAvg * 100);
      c.stats.rep = clamp(Math.round(accAvg * 100), 5, 99);
      c.stats.staked = treasury + stakedNow * 50; // displayed as $/1000 → ~1.0k
      c.stats.food = clamp(Math.round((bankAvg - 80) * 3.2), 12, 100);
      c.stats.health = clamp(Math.round(40 + (accAvg - 0.4) * 200), 25, 99);
      c.stats.gen = (records[0] && records[0].generation != null ? records[0].generation : 0) + 1;
    });
    return true;
  }

  B.nextThought = function () {
    if (!thoughts.length) return null;
    const t = thoughts[ti % thoughts.length];
    ti++;
    return t;
  };

  function load() {
    fetch(B.source)
      .then((r) => (r.ok ? r.text() : Promise.reject(r.status)))
      .then((txt) => {
        const events = txt
          .split('\n')
          .map((l) => l.trim())
          .filter(Boolean)
          .map((l) => { try { return JSON.parse(l); } catch (e) { return null; } })
          .filter(Boolean);
        build(events);
        // colonies may not exist yet — retry seeding until they do
        let tries = 0;
        const seed = setInterval(() => {
          if (applyStats() || ++tries > 60) clearInterval(seed);
        }, 250);
      })
      .catch(() => { /* no data file — app keeps its synthetic content */ });
  }

  load();
  return B;
})();
