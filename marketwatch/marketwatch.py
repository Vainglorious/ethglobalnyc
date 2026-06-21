#!/usr/bin/env python3
"""
matchwatch — tiny localhost:3000 dashboard for a live match.

Shows, auto-refreshing:
  - SCORE        (live, from ESPN's public scoreboard API)
  - MATCH CLOCK  (counts up; goes into +stoppage)
  - TIME LEFT    (streaming countdown to 90:00, goes NEGATIVE in stoppage)
  - PRICES       (Belgium / IR Iran / Draw, live from Polymarket CLOB)

Stdlib only (+ certifi for TLS). No build step. Run:
  polymarket/.venv/bin/python3 polymarket/matchwatch.py
then open  http://localhost:3000

Defaults to Belgium vs. IR Iran (2026-06-21 19:00 UTC). Edit the CONFIG block to
point it at another game.
"""
import datetime, http.server, json, socketserver, ssl, urllib.request
import certifi

# ----------------------------- CONFIG ------------------------------------
PORT = 3000
KICKOFF_UTC = datetime.datetime(2026, 6, 21, 19, 0, tzinfo=datetime.timezone.utc)
TEAM_A, TEAM_B = "Belgium", "Iran"          # substrings to match in ESPN feed
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
TOKENS = {  # CLOB YES tokens for the price strip
    "Belgium": "73247571006255574285385183553023235681702880602976519365262465179094676130340",
    "IR Iran": "107259278816298402654822103861927486042412499982187590917424237525323082866574",
    "Draw":    "65206879169809471684171181962606426355936771076631263853333189016369249957120",
}
# -------------------------------------------------------------------------

CTX = ssl.create_default_context(cafile=certifi.where())


def _get(url):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), context=CTX, timeout=12))


def fetch_score():
    """Find our match in ESPN's scoreboard. Returns dict or None."""
    try:
        data = _get(ESPN)
    except Exception:
        return None
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        cs = comp.get("competitors", [])
        names = " ".join(c.get("team", {}).get("displayName", "") for c in cs).lower()
        if TEAM_A.lower() in names and TEAM_B.lower() in names:
            st = (comp.get("status") or ev.get("status") or {})
            t = st.get("type", {})
            out = {"state": t.get("state"), "detail": t.get("shortDetail") or t.get("detail"),
                   "displayClock": st.get("displayClock"), "period": st.get("period"),
                   "clock": st.get("clock"), "teams": []}
            for c in cs:
                out["teams"].append({"name": c.get("team", {}).get("displayName"),
                                     "score": c.get("score"), "home": c.get("homeAway") == "home"})
            return out
    return None


def fetch_prices():
    out = {}
    for side, tok in TOKENS.items():
        try:
            b = _get(f"https://clob.polymarket.com/book?token_id={tok}")
            asks = sorted(b.get("asks", []), key=lambda x: float(x["price"]))
            bids = sorted(b.get("bids", []), key=lambda x: float(x["price"]), reverse=True)
            out[side] = {"ask": asks[0]["price"] if asks else None,
                         "bid": bids[0]["price"] if bids else None}
        except Exception:
            out[side] = {"ask": None, "bid": None}
    return out


def build_state():
    now = datetime.datetime.now(datetime.timezone.utc)
    sc = fetch_score()
    # match-clock seconds from ESPN displayClock ("67:23" or "45'") when live;
    # else estimate from kickoff (with a ~15min halftime hold).
    elapsed = None
    state = "pre"
    if sc and sc.get("state") == "in":
        state = "in"
        dc = (sc.get("displayClock") or "").replace("'", "").strip()
        try:
            if ":" in dc:
                m, s = dc.split(":"); elapsed = int(m) * 60 + int(s)
            elif dc:
                elapsed = int(float(dc)) * 60
        except Exception:
            elapsed = None
        if (sc.get("detail") or "").upper().startswith("HT") or sc.get("period") == 0:
            state = "ht"
    elif sc and sc.get("state") == "post":
        state = "post"
    if elapsed is None and now >= KICKOFF_UTC:
        w = (now - KICKOFF_UTC).total_seconds()
        if w < 45 * 60:
            elapsed = w
        elif w < 60 * 60:
            elapsed = 45 * 60; state = "ht" if state == "pre" else state
        else:
            elapsed = w - 15 * 60       # subtract one 15-min halftime
        if state == "pre":
            state = "in"
    return {
        "now": now.timestamp(),
        "kickoff": KICKOFF_UTC.timestamp(),
        "state": state,
        "elapsed_sec": elapsed,           # match clock in seconds (None if pre)
        "detail": sc.get("detail") if sc else None,
        "score": sc.get("teams") if sc else None,
        "score_source": "espn" if sc else None,
        "prices": fetch_prices(),
        "teamA": TEAM_A, "teamB": TEAM_B,
    }


PAGE = """<!doctype html><html><head><meta charset=utf-8>
<title>matchwatch</title><style>
 body{margin:0;background:#0d0f14;color:#e8e6df;font:16px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;
      display:flex;flex-direction:column;align-items:center;gap:18px;padding:34px}
 .card{background:#161a22;border:1px solid #232a36;border-radius:14px;padding:18px 26px;min-width:460px;text-align:center}
 .big{font-size:64px;font-weight:800;letter-spacing:1px;font-variant-numeric:tabular-nums}
 .lbl{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:#8a93a6}
 .score{font-size:40px;font-weight:700}
 .neg{color:#ff6b6b}.pos{color:#5ad17a}.ht{color:#ffcf5a}
 table{width:100%;border-collapse:collapse;margin-top:4px}
 td{padding:6px 8px;font-variant-numeric:tabular-nums}.side{text-align:left;color:#b9c0cf}
 .ask{font-weight:700}.dim{color:#6a7280}.tag{font-size:12px;color:#8a93a6;margin-top:6px}
</style></head><body>
 <div class=card><div class=lbl id=stateLbl>—</div><div class=score id=score>— : —</div>
   <div class=tag id=detail></div></div>
 <div class=card><div class=lbl>Time left to 90:00 (negative = stoppage)</div>
   <div class="big" id=countdown>--:--</div><div class=tag id=clock></div></div>
 <div class=card><div class=lbl>Live price — Buy Yes (ask)</div>
   <table id=prices></table></div>
 <div class=tag id=foot></div>
<script>
let S=null, fetchedAt=0;
function fmt(sec){const n=Math.abs(sec);const m=Math.floor(n/60),s=Math.floor(n%60);
  return (sec<0?'+':'')+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');}
async function poll(){try{const r=await fetch('/state');S=await r.json();fetchedAt=performance.now()/1000;render();}catch(e){}}
function render(){
  if(!S)return;
  const sl=document.getElementById('stateLbl');
  const lbls={pre:'PRE-MATCH',in:'LIVE',ht:'HALF-TIME',post:'FULL TIME'};
  sl.textContent=lbls[S.state]||S.state;
  // score
  if(S.score){const t=S.score;document.getElementById('score').textContent=
     `${t[0].name} ${t[0].score} : ${t[1].score} ${t[1].name}`;}
  else document.getElementById('score').textContent=`${S.teamA} vs ${S.teamB} (no score feed yet)`;
  document.getElementById('detail').textContent=S.detail||'';
  // prices
  const tb=document.getElementById('prices');tb.innerHTML='';
  for(const k in S.prices){const p=S.prices[k];const tr=document.createElement('tr');
    tr.innerHTML=`<td class=side>${k}</td><td class=ask>${p.ask??'—'}</td><td class=dim>bid ${p.bid??'—'}</td>`;
    tb.appendChild(tr);}
  document.getElementById('foot').textContent='updated '+new Date().toLocaleTimeString();
}
function tick(){
  if(!S){return;}
  const cd=document.getElementById('countdown'),ck=document.getElementById('clock');
  if(S.state==='pre'){
    const left=S.kickoff-(Date.now()/1000);
    const h=Math.floor(left/3600),m=Math.floor(left%3600/60),s=Math.floor(left%60);
    cd.textContent=left>0?`${h}h ${String(m).padStart(2,'0')}m ${String(s).padStart(2,'0')}s`:'kicking off…';
    cd.className='big';ck.textContent='kickoff '+new Date(S.kickoff*1000).toUTCString().slice(17,22)+' UTC';
    return;}
  if(S.state==='ht'){cd.textContent='HT';cd.className='big ht';ck.textContent='half-time';return;}
  if(S.state==='post'){cd.textContent='FT';cd.className='big';ck.textContent='full time';return;}
  // live: extrapolate seconds since last poll
  let el=(S.elapsed_sec||0)+(performance.now()/1000-fetchedAt);
  const left=90*60-el;                       // negative once past 90:00
  cd.textContent=fmt(left);cd.className='big '+(left<0?'neg':'pos');
  ck.textContent='match clock '+fmt(-el).replace('+','')+`  (~${Math.floor(el/60)}' )`;
}
poll();setInterval(poll,4000);setInterval(tick,250);
</script></body></html>"""


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        if self.path.startswith("/state"):
            body = json.dumps(build_state()).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        else:
            body = PAGE.encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


if __name__ == "__main__":
    import argparse, sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args()
    socketserver.TCPServer.allow_reuse_address = True
    srv = None
    for p in range(a.port, a.port + 8):           # fall back if 3000 is taken (e.g. your frontend)
        try:
            srv = socketserver.TCPServer(("", p), H); bound = p; break
        except OSError:
            continue
    if not srv:
        print(f"no free port in {a.port}..{a.port+7}"); sys.exit(1)
    if bound != a.port:
        print(f"(port {a.port} busy — using {bound})")
    print(f"matchwatch -> http://localhost:{bound}   ({TEAM_A} vs {TEAM_B})")
    with srv:
        srv.serve_forever()
