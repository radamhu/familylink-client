"""Admin endpoints — protected, for operational management."""

import logging

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from familylink_server.auth.oauth import require_user
from familylink_server.services.family_link import get_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/admin', tags=['admin'])


class RefreshCookiesRequest(BaseModel):
    """Request body for the refresh-cookies endpoint."""

    sapisid: str


@router.get('/reconnect', response_class=HTMLResponse)
async def reconnect_page(
    _email: str = require_user,  # type: ignore[assignment]
) -> HTMLResponse:
    """Reconnect page — shows the SAPISID paste form."""
    return HTMLResponse(
        content="""<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reconnect — Family Link</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
</head>
<body>
  <main class="container" style="max-width:600px;margin-top:4rem">
    <article>
      <header><strong>Reconnect Google session</strong></header>
      <p>Paste a fresh <code>SAPISID</code> cookie below to restore access — works from any browser, no restart needed.</p>

      <form id="reconnect-form" onsubmit="submitForm(event)">
        <label for="sapisid">SAPISID cookie value</label>
        <input id="sapisid" name="sapisid" type="password"
               placeholder="Paste SAPISID here" required autocomplete="off">
        <button type="submit">Reconnect</button>
      </form>
      <p id="error" style="color:red"></p>
      <script>
      async function submitForm(e) {
        e.preventDefault();
        const sapisid = document.getElementById('sapisid').value;
        const resp = await fetch('/admin/refresh-cookies', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({sapisid})
        });
        if (resp.ok) window.location.href = '/';
        else document.getElementById('error').textContent = 'Failed: ' + resp.status;
      }
      </script>

      <details style="margin-top:1rem">
        <summary>How to get your SAPISID on mobile</summary>
        <ol>
          <li>Open <strong>google.com</strong> in your phone browser (logged into your Google account)</li>
          <li>Tap the address bar and type:<br>
              <code>javascript:alert(document.cookie.match(/SAPISID=([^;]+)/)[1])</code></li>
          <li>Press Go — an alert shows your SAPISID</li>
          <li>Copy it and paste above, then tap Reconnect</li>
        </ol>
      </details>
    </article>
  </main>
</body>
</html>"""
    )


@router.post('/refresh-cookies', status_code=204, dependencies=[require_user])
async def refresh_cookies(body: RefreshCookiesRequest) -> None:
    """Hot-swap the FamilyLink client with fresh cookies. No server restart needed."""
    get_service().reinit_with_cookies(body.sapisid)
    logger.info('Cookies hot-reloaded via /admin/refresh-cookies')
