# Verifying ntfy setup (optional)

Low-time warnings and new-homework alerts are pushed per kid via [ntfy](https://ntfy.sh) once `NTFY_TOPICS` and `NTFY_BASE_URL` are set (see the environment variable table in [deployment.md](deployment.md)). This server is **open access** — no accounts or ACLs — so a topic's only protection is an unguessable name; there's nothing to provision server-side, just topics to configure and confirm.

1. Set `NTFY_TOPICS` to `child_id:topic,child_id:topic` for every kid, keyed by the same Family Link `child_id` used elsewhere in this app.
2. Install the [ntfy Android/iOS app](https://ntfy.sh) on each kid's phone and subscribe it to their topic, pointed at `NTFY_BASE_URL`.
3. Confirm delivery end to end with the included smoke-test script — it opens each topic's live web view in a headless browser, pushes a test message through the real `NtfyNotifier`, and checks it renders:

```bash
pip install playwright && playwright install chromium
python scripts/verify_ntfy_topics.py
```

Expect `OK   <child_id>   topic=<topic>` for every kid and exit code `0`. A `FAIL` line means that kid's topic didn't render a push within 15s — check `NTFY_BASE_URL` is reachable from the machine running the script and that the topic string matches what's subscribed on the kid's phone. This script is a standalone ops tool (not part of `pyproject.toml` or the pytest suite) — install Playwright ad hoc when you need it.
