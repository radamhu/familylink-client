# Linux Machines: Persistent SSH Key Pair Generation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Generate Key Pair" button to the add/edit machine form so that the server generates an ed25519 key pair, stores the private key in the DB (persistent Postgres), and shows the public key for one-time deployment to the child machine.

**Architecture:** A new `POST /linux-machines/generate-key` endpoint generates a key pair server-side using `asyncssh` and returns JSON `{private_key, public_key}`. A small `<script>` block in the form calls this endpoint, fills the `ssh_private_key` textarea, and displays the public key in a read-only copy box. The private key is persisted to Postgres via the existing form submit path — no file system or `/tmp` involved.

**Tech Stack:** Python 3.12, FastAPI, asyncssh (already a dependency), Jinja2, vanilla JS (fetch + DOM), pytest + AsyncMock

## Global Constraints

- Python 3.12 (`pyenv`, `.python-version`)
- No `uv` — use `pip` and `python -m pytest`
- `asyncio_mode = "auto"` in pytest — all `async def test_*` are awaited automatically
- Ruff with Google docstring style, single-quoted inline strings
- Do not install new packages — `asyncssh` is already installed
- Run lint after every commit: `ruff check src tests && ruff format --check src tests`

---

### Task 1: Server-side generate-key endpoint

**Files:**
- Modify: `src/familylink_server/routers/linux_machines.py`
- Modify: `tests/server/test_routers_linux_machines.py`

**Interfaces:**
- Produces: `POST /linux-machines/generate-key` → `200 {"private_key": "<PEM string>", "public_key": "<openssh string>"}`
  - Requires auth cookie (`fl_session`); returns `401` without it
  - No request body required

- [ ] **Step 1: Write the failing tests**

Add to `tests/server/test_routers_linux_machines.py`:

```python
def test_generate_key_returns_key_pair():
    """POST /linux-machines/generate-key returns private and public key strings."""
    from familylink_server.main import app

    client = TestClient(app)
    resp = client.post(
        '/linux-machines/generate-key',
        cookies={'fl_session': _cookie()},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['private_key'].startswith('-----BEGIN OPENSSH PRIVATE KEY-----')
    assert 'ssh-ed25519' in data['public_key']


def test_generate_key_requires_auth():
    """POST /linux-machines/generate-key without auth returns 401."""
    from familylink_server.main import app

    client = TestClient(app)
    resp = client.post('/linux-machines/generate-key')
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/server/test_routers_linux_machines.py::test_generate_key_returns_key_pair tests/server/test_routers_linux_machines.py::test_generate_key_requires_auth -v
```

Expected: FAIL — `404 Not Found` (endpoint doesn't exist yet)

- [ ] **Step 3: Add the endpoint**

In `src/familylink_server/routers/linux_machines.py`, add this import at the top alongside existing imports:

```python
import asyncssh
from fastapi.responses import JSONResponse
```

Then add this route **before** the `@router.get("/linux-machines/{machine_id}/edit")` route:

```python
@router.post('/linux-machines/generate-key')
async def generate_key_pair(
    _email: str = require_user,  # type: ignore[assignment]
) -> JSONResponse:
    """Generate an ed25519 SSH key pair and return both halves as strings."""
    key = asyncssh.generate_private_key('ssh-ed25519')
    private_pem = key.export_private_key('pkcs8-pem').decode()
    public_openssh = key.export_public_key('openssh').decode().strip()
    return JSONResponse({'private_key': private_pem, 'public_key': public_openssh})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/server/test_routers_linux_machines.py::test_generate_key_returns_key_pair tests/server/test_routers_linux_machines.py::test_generate_key_requires_auth -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
python -m pytest tests/server/test_routers_linux_machines.py -v
```

Expected: all green

- [ ] **Step 6: Lint**

```bash
ruff check src/familylink_server/routers/linux_machines.py && ruff format --check src/familylink_server/routers/linux_machines.py
```

Fix any issues with `ruff check --fix` and `ruff format`.

- [ ] **Step 7: Commit**

```bash
git add src/familylink_server/routers/linux_machines.py tests/server/test_routers_linux_machines.py
git commit -m "feat: add POST /linux-machines/generate-key endpoint"
```

---

### Task 2: Generate button + public key display in the form

**Files:**
- Modify: `src/familylink_server/templates/linux_machine_form.html`

**Interfaces:**
- Consumes: `POST /linux-machines/generate-key` → `{private_key: str, public_key: str}` (from Task 1)

- [ ] **Step 1: Replace the SSH private key label block**

In `src/familylink_server/templates/linux_machine_form.html`, replace:

```html
  <label>
    SSH private key (PEM){% if machine %} — leave blank to keep existing{% endif %}
    <textarea name="ssh_private_key" rows="8"
      placeholder="-----BEGIN RSA PRIVATE KEY-----&#10;...">{% if not machine %}{% endif %}</textarea>
  </label>
```

with:

```html
  <label>
    SSH private key (PEM){% if machine %} — leave blank to keep existing{% endif %}
    <textarea id="ssh_private_key" name="ssh_private_key" rows="8"
      placeholder="-----BEGIN OPENSSH PRIVATE KEY-----&#10;...">{% if not machine %}{% endif %}</textarea>
  </label>
  <button type="button" id="gen-key-btn">Generate key pair</button>
  <div id="pubkey-box" style="display:none">
    <label>
      Public key — add this to <code>~/.ssh/authorized_keys</code> on the child machine
      <textarea id="pubkey-out" rows="3" readonly onclick="this.select()"></textarea>
    </label>
  </div>
  <script>
    document.getElementById('gen-key-btn').addEventListener('click', async () => {
      const btn = document.getElementById('gen-key-btn');
      btn.disabled = true;
      btn.textContent = 'Generating…';
      try {
        const resp = await fetch('/linux-machines/generate-key', {method: 'POST'});
        if (!resp.ok) { alert('Key generation failed'); return; }
        const data = await resp.json();
        document.getElementById('ssh_private_key').value = data.private_key;
        document.getElementById('pubkey-out').value = data.public_key;
        document.getElementById('pubkey-box').style.display = '';
        btn.textContent = 'Regenerate key pair';
      } finally {
        btn.disabled = false;
      }
    });
  </script>
```

- [ ] **Step 2: Verify the page renders (smoke test)**

```bash
python -m pytest tests/server/test_routers_linux_machines.py::test_linux_machines_new_form_returns_200 -v
```

Expected: PASS. If that test doesn't exist yet, run all router tests:

```bash
python -m pytest tests/server/test_routers_linux_machines.py -v
```

Expected: all green

- [ ] **Step 3: Commit**

```bash
git add src/familylink_server/templates/linux_machine_form.html
git commit -m "feat: add generate-key-pair button to Linux machine form"
```

---

## Self-Review

**Spec coverage:**
- ✅ Key generation is permanent — private key saved to Postgres, not `/tmp`
- ✅ Public key is shown to the user for deployment to the child machine
- ✅ Works inside Docker — `asyncssh` runs server-side, no host tools needed
- ✅ Auth-gated endpoint — requires `fl_session` cookie
- ✅ No new dependencies — `asyncssh` already installed

**Placeholder scan:** None found — all code blocks are complete and executable.

**Type consistency:** `generate_private_key`, `export_private_key`, `export_public_key` are standard `asyncssh` API. `JSONResponse` is already used elsewhere in FastAPI projects. `id="ssh_private_key"` matches `name="ssh_private_key"` (the JS targets by `id`, the form submits by `name`).
