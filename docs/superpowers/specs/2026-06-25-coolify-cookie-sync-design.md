# Design: Coolify cookie sync for `export-cookies`

**Date:** 2026-06-25
**Status:** Approved

## Summary

Extend `familylink export-cookies --base64` with two new flags (`--coolify`, `--restart`) that push the freshly-generated `FAMILYLINK_COOKIES_B64` value to the Coolify-hosted `familylink-client` app via the Coolify REST API, optionally restarting the container afterwards.

## New env vars

Three variables configure the Coolify integration. All three must be present when `--coolify` is passed; if any is missing the CLI errors immediately.

| Variable | Example value | Purpose |
|---|---|---|
| `COOLIFY_URL` | `http://192.168.0.22:8000` | Base URL of the Coolify instance |
| `COOLIFY_TOKEN` | `1|EWfPB7l6...` | Bearer token for the Coolify API |
| `COOLIFY_APP_UUID` | `ou4t4la0sfos78d8z3aytvah` | UUID of the `familylink-client` application |

These are added to `.env.example` (commented, with explanatory text) and `.env`.

## CLI changes

File: `src/familylink/cli.py`, function `_cmd_export_cookies`.

### New flags

```
--coolify      Push FAMILYLINK_COOKIES_B64 to Coolify after updating .env.
               Requires --base64. Reads COOLIFY_URL, COOLIFY_TOKEN, COOLIFY_APP_UUID from env.

--restart      Restart the Coolify app after pushing the env var.
               Requires --coolify.
```

### Execution flow (when `--base64 --coolify [--restart]`)

1. Extract cookies from browser → save to file → print base64 *(existing)*
2. Update local `.env` with `FAMILYLINK_COOKIES_B64=<value>` *(existing)*
3. `PATCH {COOLIFY_URL}/api/v1/applications/{COOLIFY_APP_UUID}/envs`
   - Body: `{"key": "FAMILYLINK_COOKIES_B64", "value": "<base64>", "is_preview": false}`
   - Header: `Authorization: Bearer {COOLIFY_TOKEN}`
   - On non-2xx: print status + body, exit 1
4. Print `[success]Updated FAMILYLINK_COOKIES_B64 in Coolify[/success]`
5. If `--restart`:
   - `GET {COOLIFY_URL}/api/v1/applications/{COOLIFY_APP_UUID}/restart`
   - On non-2xx: print status + body, exit 1
   - Print `[success]Restarted familylink-client in Coolify[/success]`

HTTP calls use `httpx` (already a project dependency).

## Error handling

| Condition | Behaviour |
|---|---|
| `--coolify` without `--base64` | Print error, exit 1 |
| `--restart` without `--coolify` | Print error, exit 1 |
| Any `COOLIFY_*` var missing (with `--coolify`) | Print which var is missing, exit 1 |
| Coolify API non-2xx | Print status code + response body, exit 1 |
| Network error reaching Coolify | Print exception message, exit 1 |

Local `.env` is written before the Coolify API call; it is not rolled back on Coolify failure.

## Out of scope

- Auto-triggering Coolify on every `--base64` run (rejected in favour of explicit `--coolify` flag)
- Auto-restart without an explicit flag (rejected; user chose approach B)
- Any changes to the server-side `Settings` model or `config.py`
