# eKRÉTA homework scraping (optional)

An `ekreta-scraper` sidecar (see `docker-compose.yml`) can log into the Hungarian eKRÉTA school system on a cron schedule and post each kid's homework to the dashboard.

| Variable                 | Description                                                                                                                                      |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `EKRETA_INGEST_TOKEN`  | Shared secret sent as`X-Api-Key` by the scraper — must be set to the **same value** on both the `web` and `ekreta-scraper` services |
| `EKRETA_CRON_SCHEDULE` | Cron expression for scrape runs (default`0 6 * * 1-5` — weekday mornings)                                                                     |

This feature is entirely optional: if `EKRETA_INGEST_TOKEN` is left unset, the internal ingest endpoints reject every request with `401` and the dashboard simply shows no homework.

There is no admin UI yet for enabling a kid's scraping — add a row directly to the `ekreta_credentials` table:

```sql
INSERT INTO ekreta_credentials (child_id, username, password, institution_code)
VALUES ('<google-family-link-child-id>', '<ekreta-username>', '<ekreta-password>', '<institution-code>');
```

`child_id` must match the same Google Family Link member id used elsewhere in the dashboard (the same id shown against that child's other data). Look up the institution code at https://intezmenykereso.e-kreta.hu/.
