"""Placeholder HTML pages for the routes the frontend will own.

They exist so sign-in, magic links and invites can be exercised before the
dashboard is built. Point FRONTEND_URL at this server to use them; point it at
the real frontend to bypass them entirely.

    GET /auth/callback     shows the session token from the URL fragment
    GET /auth/magic        verifies a magic-link token and shows the session token
    GET /invite/{token}    previews an invite and accepts it with a pasted session token
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dev pages"], include_in_schema=False)

_STYLE = """
<style>
 body{font-family:system-ui,sans-serif;max-width:720px;margin:3rem auto;padding:0 1rem;color:#222}
 code,textarea{font-family:ui-monospace,monospace;font-size:.9rem}
 textarea{width:100%;height:6rem}
 button{padding:.5rem 1rem;font-size:1rem;cursor:pointer}
 .muted{color:#666} .ok{color:#0a7} .err{color:#c33}
 pre{background:#f5f5f5;padding:1rem;overflow:auto}
</style>
"""


@router.get("/auth/callback", response_class=HTMLResponse)
async def auth_callback_page() -> str:
    return f"""<!doctype html><title>Consensus – signed in</title>{_STYLE}
<h1>Signed in</h1>
<p class="muted">This placeholder page stands in for the frontend. Your session token is below.
Keep it private; it is your login.</p>
<textarea id="tok" readonly></textarea>
<p><button onclick="navigator.clipboard.writeText(document.getElementById('tok').value)">Copy token</button></p>
<h2>Account</h2><pre id="me">loading…</pre>
<script>
 const h = new URLSearchParams(location.hash.slice(1));
 const token = h.get('token') || '';
 document.getElementById('tok').value = token;
 fetch('/api/auth/me', {{headers: {{Authorization: 'Bearer ' + token}}}})
   .then(r => r.json()).then(j => document.getElementById('me').textContent = JSON.stringify(j, null, 2))
   .catch(e => document.getElementById('me').textContent = String(e));
</script>"""


@router.get("/auth/magic", response_class=HTMLResponse)
async def magic_page() -> str:
    return f"""<!doctype html><title>Consensus – magic link</title>{_STYLE}
<h1>Magic link</h1><p id="status">verifying…</p>
<textarea id="tok" readonly></textarea>
<p><button onclick="navigator.clipboard.writeText(document.getElementById('tok').value)">Copy token</button></p>
<pre id="me"></pre>
<script>
 const token = new URLSearchParams(location.search).get('token');
 fetch('/api/auth/magic-link/verify', {{method:'POST', headers:{{'content-type':'application/json'}}, body: JSON.stringify({{token}})}})
   .then(async r => {{ const j = await r.json(); if (!r.ok) throw new Error(j.detail || r.status);
     document.getElementById('status').innerHTML = '<span class="ok">Signed in as ' + j.me.user.email + '</span>';
     document.getElementById('tok').value = j.token; document.getElementById('me').textContent = JSON.stringify(j.me, null, 2); }})
   .catch(e => document.getElementById('status').innerHTML = '<span class="err">' + e.message + '</span>');
</script>"""


@router.get("/invite/{token}", response_class=HTMLResponse)
async def invite_page(token: str) -> str:
    return f"""<!doctype html><title>Consensus – invite</title>{_STYLE}
<h1>You're invited</h1><pre id="inv">loading…</pre>
<p>Paste your session token (from <a href="/api/auth/providers">signing in</a>) and accept:</p>
<textarea id="tok" placeholder="session token"></textarea>
<p><button id="go">Accept invite</button> <span id="status"></span></p>
<script>
 const token = {token!r};
 fetch('/api/invites/' + token).then(r => r.json()).then(j => document.getElementById('inv').textContent = JSON.stringify(j, null, 2));
 document.getElementById('go').onclick = () =>
   fetch('/api/invites/' + token + '/accept', {{method:'POST', headers:{{Authorization:'Bearer ' + document.getElementById('tok').value.trim()}}}})
     .then(async r => {{ const j = await r.json(); document.getElementById('status').innerHTML = r.ok ? '<span class="ok">Joined ' + j.name + ' as ' + j.role + '</span>' : '<span class="err">' + (j.detail || r.status) + '</span>'; }});
</script>"""
