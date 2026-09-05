"""A minimal built-in live board at GET /board, for demos before the real frontend exists.

Shows counters, open plans, clashes (with resolve buttons), memory, and the live
event stream for one project. Sign in with a session token or an API key.

    http://localhost:8000/board?token=<jwt or csk_...>&project=<project id>

Everything on the page goes through the same public REST and WebSocket API the
real dashboard will use.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dev pages"], include_in_schema=False)

PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Consensus board</title>
<style>
 :root{--bg:#fafafa;--card:#fff;--line:#e5e5e5;--muted:#6b6b6b;--ink:#1c1c1c;--hard:#c0392b;--soft:#b9770e;--ok:#1e8449;--wait:#8e44ad}
 body{font-family:system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink)}
 header{display:flex;gap:1rem;align-items:center;padding:.8rem 1.2rem;background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0}
 header h1{font-size:1.1rem;margin:0}
 header input,header select{padding:.35rem .5rem;font-size:.9rem}
 main{display:grid;grid-template-columns:1.2fr 1fr;gap:1rem;padding:1rem 1.2rem}
 section{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.9rem 1rem}
 h2{font-size:.85rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:0 0 .6rem}
 .counters{display:grid;grid-template-columns:repeat(6,1fr);gap:.6rem;grid-column:1/-1}
 .counter{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.7rem 1rem}
 .counter b{display:block;font-size:1.5rem}
 .counter span{color:var(--muted);font-size:.8rem}
 .item{padding:.55rem 0;border-top:1px solid var(--line);font-size:.92rem}
 .item:first-of-type{border-top:0}
 .who{color:var(--muted);font-size:.8rem}
 .tag{display:inline-block;font-size:.72rem;padding:.1rem .45rem;border-radius:99px;border:1px solid var(--line);margin-right:.3rem}
 .hard{color:var(--hard);border-color:var(--hard)} .soft{color:var(--soft);border-color:var(--soft)}
 .open{color:var(--wait);border-color:var(--wait)} .resolved,.auto_resolved,.in_review{color:var(--ok);border-color:var(--ok)}
 .pos{font-family:ui-monospace,monospace;font-size:.82rem;background:#f3f3f3;padding:.15rem .4rem;border-radius:4px}
 button{padding:.3rem .6rem;font-size:.8rem;cursor:pointer;margin-right:.3rem}
 #events{font-family:ui-monospace,monospace;font-size:.78rem;max-height:40vh;overflow:auto;white-space:pre-wrap}
 #events div{padding:.15rem 0;border-top:1px dashed var(--line)}
 .full{grid-column:1/-1}
 .muted{color:var(--muted)}
 .dot{display:inline-block;width:.6rem;height:.6rem;border-radius:99px;background:#bbb;margin-right:.35rem}
 .dot.live{background:var(--ok)}
</style></head><body>
<header>
 <h1>Consensus</h1>
 <span id="conn"><span class="dot"></span><span class="muted">connecting</span></span>
 <select id="project"></select>
 <span class="muted" id="me"></span>
 <a class="muted" href="/docs" target="_blank" style="margin-left:auto">API docs</a>
</header>
<main>
 <div class="counters" id="counters"></div>
 <section><h2>Open plans</h2><div id="claims" class="muted">…</div></section>
 <section><h2>Clashes</h2><div id="clashes" class="muted">…</div></section>
 <section class="full"><h2>Shared memory</h2><div id="memory" class="muted">…</div></section>
 <section class="full"><h2>Live events</h2><div id="events"></div></section>
</main>
<script>
const qs = new URLSearchParams(location.search);
const token = qs.get('token') || localStorage.getItem('consensus_token') || prompt('Session token or API key (csk_...)');
if (token) localStorage.setItem('consensus_token', token);
const H = {Authorization: 'Bearer ' + token};
const api = (p, o={}) => fetch(p, {...o, headers: {...H, 'content-type': 'application/json', ...(o.headers||{})}}).then(async r => { if (!r.ok) throw new Error((await r.json()).detail || r.status); return r.status === 204 ? null : r.json(); });
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let pid = qs.get('project'); let ws;

async function init() {
  try {
    const me = await api('/api/auth/me');
    document.getElementById('me').textContent = me.user.email;
  } catch (e) { document.getElementById('me').textContent = 'not signed in: ' + e.message; return; }
  const projects = await api('/api/projects');
  const sel = document.getElementById('project');
  sel.innerHTML = projects.map(p => `<option value="${p.id}">${esc(p.name)}${p.repo_full_name ? ' · ' + esc(p.repo_full_name) : ''}</option>`).join('');
  if (!pid || !projects.some(p => p.id === pid)) pid = projects[0]?.id;
  sel.value = pid;
  sel.onchange = () => { pid = sel.value; history.replaceState(null, '', `?project=${pid}`); refresh(); connect(); };
  await refresh(); connect();
}

async function refresh() {
  if (!pid) return;
  const [c, claims, clashes, memory] = await Promise.all([
    api(`/api/projects/${pid}/counters`), api(`/api/projects/${pid}/claims?status=open`),
    api(`/api/projects/${pid}/clashes`), api(`/api/projects/${pid}/memory?limit=12`)]);
  document.getElementById('counters').innerHTML = [
    ['tokens_saved','tokens saved'],['clashes_caught','clashes caught'],['open_clashes','open clashes'],
    ['open_claims','open plans'],['memory_count','memory entries'],['agents','agents']]
    .map(([k,l]) => `<div class="counter"><b>${c[k].toLocaleString()}</b><span>${l}</span></div>`).join('');
  document.getElementById('claims').innerHTML = claims.length ? claims.map(x => `
    <div class="item"><div class="who">${esc(x.agent_name)} · ${esc(x.developer_name)}${x.branch ? ' · ' + esc(x.branch) : ''}${x.task_ref ? ' · ' + esc(x.task_ref) : ''}</div>
    ${esc(x.intent_text)}<div class="who">${(x.concepts||[]).map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div></div>`).join('') : '<span class="muted">none</span>';
  document.getElementById('clashes').innerHTML = clashes.length ? clashes.slice(0, 12).map(x => `
    <div class="item"><span class="tag ${x.severity}">${x.severity}</span><span class="tag ${x.status}">${x.status}</span><span class="tag">${esc(x.axis)}</span>
    <div><b>${esc(x.agent_a)}</b> <span class="pos">${esc(x.position_a || '—')}</span></div>
    <div><b>${esc(x.agent_b)}</b> <span class="pos">${esc(x.position_b || '—')}</span></div>
    <div class="who">shared: ${(x.shared_concepts||[]).join(', ')}${x.resolution ? ' · ' + esc(x.resolution) + (x.resolution_note ? ': ' + esc(x.resolution_note) : '') : ''}</div>
    ${x.status === 'open' ? `<div style="margin-top:.4rem"><button onclick="resolve('${x.id}','a_proceeds')">${esc(x.agent_a)} proceeds</button><button onclick="resolve('${x.id}','b_proceeds')">${esc(x.agent_b)} proceeds</button><button onclick="resolve('${x.id}','both_with_note')">both, with note</button></div>` : ''}
    </div>`).join('') : '<span class="muted">none</span>';
  document.getElementById('memory').innerHTML = memory.length ? memory.map(m => `
    <div class="item"><span class="tag">${esc(m.type)}</span>${esc(m.content)} <span class="who">${m.source_agent ? '· ' + esc(m.source_agent) : ''}</span></div>`).join('') : '<span class="muted">none</span>';
}

async function resolve(id, resolution) {
  const note = prompt('Ruling note (written to shared memory):', ''); if (note === null) return;
  try { await api(`/api/clashes/${id}/resolve`, {method: 'POST', body: JSON.stringify({resolution, note})}); }
  catch (e) { alert(e.message); }
}

function connect() {
  if (ws) ws.close();
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/projects/${pid}?token=${encodeURIComponent(token)}`);
  const conn = document.getElementById('conn');
  ws.onopen = () => conn.innerHTML = '<span class="dot live"></span><span class="muted">live</span>';
  ws.onclose = () => conn.innerHTML = '<span class="dot"></span><span class="muted">disconnected</span>';
  ws.onmessage = ev => {
    const f = JSON.parse(ev.data); if (f.type === 'hello' || f.type === 'pong') return;
    const box = document.getElementById('events');
    const d = f.data || {}; let line = f.type;
    if (f.type === 'claim.created') line += `  ${d.claim.agent_name}: "${d.claim.intent_text.slice(0,90)}"  → ${d.verdict}`;
    if (f.type === 'clash.opened') line += `  ${d.clash.agent_a} vs ${d.clash.agent_b} on ${d.clash.axis} [${d.clash.severity}]`;
    if (f.type === 'clash.resolved') line += `  ${d.clash.agent_a} vs ${d.clash.agent_b}: ${d.auto ? 'auto-resolved by prior ruling' : d.clash.resolution + ' by ' + d.clash.resolved_by}`;
    if (f.type === 'memory.written') line += `  [${d.entry.type}] ${d.entry.content.slice(0,90)}`;
    if (f.type === 'memory.read') line += `  ${d.agent || 'agent'} asked "${d.question}" → ${d.hits} hits, ${d.tokens_used} tokens`;
    if (f.type === 'handoff.filed') line += `  ${d.claim.agent_name}: ${d.changed.length} changed, ${d.untouched.length} untouched`;
    if (f.type === 'pr.opened') line += `  ${d.pr_url}`;
    if (f.type === 'claim.retired') line += `  claim ${d.claim_id.slice(0,8)} (PR #${d.pr_number}${d.merged ? ', merged' : ''})`;
    const row = document.createElement('div'); row.textContent = new Date(f.ts).toLocaleTimeString() + '  ' + line;
    box.prepend(row); refresh();
  };
}
init();
</script></body></html>"""


@router.get("/board", response_class=HTMLResponse)
async def board_page() -> str:
    return PAGE
