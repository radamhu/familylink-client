#!/bin/sh
set -eu

CRON_SCHEDULE="${CRON_SCHEDULE:-0 6 * * 1-5}"

# Snapshot the container's env so cron's non-login shell (which gets a
# minimal environment of its own, not this process's) can see it later.
# Values (e.g. CRON_SCHEDULE's "0 6 * * 1-5", or a password/institution code
# with shell-special characters) can't be sourced as bare `KEY=value` lines —
# unquoted spaces/globs/`$`/backticks would be mis-parsed or executed. Quote
# each value with shlex.quote and emit `export` lines so sourcing is both
# correct and safe.
python3 -c '
import os
import shlex

for key, value in os.environ.items():
    print(f"export {key}={shlex.quote(value)}")
' > /app/env.sh
chmod 600 /app/env.sh

echo "${CRON_SCHEDULE} root . /app/env.sh; cd /app/src && python3 main.py >> /proc/1/fd/1 2>> /proc/1/fd/2" > /etc/cron.d/scraper-cron
chmod 0644 /etc/cron.d/scraper-cron

echo "[entrypoint] running initial fetch now..."
(cd /app/src && python3 main.py) || echo "[entrypoint] initial run failed (see above); cron will retry on schedule."

echo "[entrypoint] starting cron in foreground, schedule: ${CRON_SCHEDULE}"
exec cron -f
