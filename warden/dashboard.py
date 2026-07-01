"""Warden dashboard — a self-contained live page served at '/'.

Polls /warden/status and /warden/calls and renders tool status badges, the
plain-language breaking diff, and the recent call log. No template engine: one
HTML document with vanilla JS, sized to read on a demo recording.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Warden — MCP Contract Firewall</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; background: #0b0e14; color: #e6e6e6;
         font: 15px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  header { padding: 20px 28px; border-bottom: 1px solid #1c2130;
           display: flex; align-items: baseline; gap: 16px; }
  header h1 { margin: 0; font-size: 22px; letter-spacing: .5px; }
  header .sub { color: #7d8797; font-size: 13px; }
  header .live { margin-left: auto; color: #3ddc84; font-size: 12px; }
  main { padding: 24px 28px; max-width: 1100px; margin: 0 auto; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 1.5px;
       color: #7d8797; margin: 28px 0 12px; }
  .tools { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
  .card { background: #121722; border: 1px solid #1c2130; border-radius: 10px; padding: 16px 18px; }
  .card.bad { border-color: #7f1d1d; background: #1a1113; }
  .card .name { font-size: 17px; font-weight: 600; display: flex; align-items: center; gap: 10px; }
  .badge { font-size: 11px; font-weight: 700; letter-spacing: 1px; padding: 3px 9px;
           border-radius: 999px; }
  .badge.ok { background: #10331f; color: #3ddc84; }
  .badge.bad { background: #4a1113; color: #ff6b6b; }
  .diff { margin-top: 12px; font-size: 13px; color: #ff9a9a; }
  .diff .line::before { content: "▸ "; color: #ff6b6b; }
  .muted { color: #566072; font-size: 13px; margin-top: 10px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #161b27; font-size: 13px; }
  th { color: #7d8797; font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 1px; }
  .pill { font-weight: 700; font-size: 11px; padding: 2px 8px; border-radius: 6px; }
  .pill.ok { background: #10331f; color: #3ddc84; }
  .pill.err { background: #3a2410; color: #ffb454; }
  .pill.blk { background: #4a1113; color: #ff6b6b; }
</style>
</head>
<body>
<header>
  <h1>🛡 Warden</h1>
  <span class="sub">MCP contract-and-drift firewall</span>
  <span class="live">● live</span>
</header>
<main>
  <h2>Tool contracts</h2>
  <div id="tools" class="tools"></div>
  <h2>Recent calls</h2>
  <table>
    <thead><tr><th>Time</th><th>Tool</th><th>Method</th><th>Latency</th><th>Result</th></tr></thead>
    <tbody id="calls"></tbody>
  </table>
</main>
<script>
function esc(s){ return (s==null?'':String(s)).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

function renderTools(tools){
  const el = document.getElementById('tools');
  el.innerHTML = tools.sort((a,b)=>a.tool.localeCompare(b.tool)).map(t => {
    const bad = t.status === 'quarantined';
    const breaking = (t.changes||[]).filter(c => c.breaking);
    const diff = bad && breaking.length
      ? '<div class="diff">' + breaking.map(c => '<div class="line">'+esc(c.message)+'</div>').join('') + '</div>'
      : '<div class="muted">no drift — contract matches baseline</div>';
    return `<div class="card ${bad?'bad':''}">
      <div class="name">${esc(t.tool)}
        <span class="badge ${bad?'bad':'ok'}">${bad?'QUARANTINED':'OK'}</span></div>
      ${diff}</div>`;
  }).join('');
}

function renderCalls(calls){
  const el = document.getElementById('calls');
  el.innerHTML = calls.map(c => {
    let pill = '<span class="pill ok">OK</span>';
    if (c.blocked) pill = '<span class="pill blk">BLOCKED</span>';
    else if (c.is_error) pill = '<span class="pill err">ERROR</span>';
    const lat = c.latency_ms==null ? '-' : c.latency_ms+' ms';
    return `<tr><td>${esc((c.ts||'').slice(11,19))}</td><td>${esc(c.tool||'-')}</td>
      <td>${esc(c.method||'-')}</td><td>${lat}</td><td>${pill}</td></tr>`;
  }).join('');
}

async function tick(){
  try {
    const [s, c] = await Promise.all([
      fetch('/warden/status').then(r=>r.json()),
      fetch('/warden/calls?limit=12').then(r=>r.json()),
    ]);
    renderTools(s.tools||[]);
    renderCalls(c.calls||[]);
  } catch(e) { /* transient; next tick */ }
}
tick();
setInterval(tick, 1000);
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return _PAGE
