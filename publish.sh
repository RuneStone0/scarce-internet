#!/usr/bin/env bash
# Monthly publish: collect -> rebuild -> commit -> push. Used by the Hermes cron routine.
#
# Contract (this runs unattended):
#   * On success prints NOTHING. Empty stdout is what keeps the routine silent, so the
#     artifact (the live page) is the delivery and there is no completion notice.
#   * On a partial failure it prints a short line and still exits 0 — the run completed,
#     the lane is just partly blind. Silence must mean "checked everything", never
#     "failed to check". The line goes to the cron output file (deliver=local), not to
#     Rune's inbox.
#   * Non-zero is reserved for a genuine crash, and the failure is recorded to
#     LAST_FAILURE.txt so the weekly review has something durable to read.
set -uo pipefail
cd "$(dirname "$0")"
REPO="$PWD"
PY="/opt/hermes/.venv/bin/python"
FAILFILE="$REPO/LAST_FAILURE.txt"
NOTES=""

fail() { NOTES="${NOTES}${NOTES:+; }$1"; }

# --- 1. collect ---------------------------------------------------------------
if ! out=$("$PY" collect.py 2>&1); then
  printf '%s\n' "$out" > "$FAILFILE"
  echo "scarce-internet: COLLECT FAILED — see $FAILFILE"
  exit 0
fi

degraded=$(printf '%s\n' "$out" | grep -c 'DEGRADED' || true)
if [ "$degraded" -gt 0 ]; then
  fail "$degraded source(s) degraded"
  printf '%s\n' "$out" > "$FAILFILE"
fi

# --- 2. rebuild ---------------------------------------------------------------
if ! out=$("$PY" build_site.py 2>&1); then
  printf '%s\n' "$out" > "$FAILFILE"
  echo "scarce-internet: SITE BUILD FAILED — see $FAILFILE"
  exit 0
fi

# --- 3. publish ---------------------------------------------------------------
# Credentials come from /opt/data/.env; the token is passed as a transient auth header
# so nothing is persisted into .git/config. Never echo the token.
set -a
. /opt/data/.env
set +a
export GH_TOKEN

git add -A   # whole repo is agent-owned: no human WIP to sweep
if git diff --cached --quiet; then
  [ -n "$NOTES" ] && echo "scarce-internet: no data change; $NOTES"
  [ -z "$NOTES" ] && exit 0
  exit 0
fi

git commit -q -m "Monthly update $(date -u +%Y-%m)" || true

if ! out=$(git -c http.extraheader="AUTHORIZATION: basic $(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)" \
        push -q origin main 2>&1); then
  fail "push failed: $(printf '%s' "$out" | head -1)"
  printf '%s\n' "$out" > "$FAILFILE"
  echo "scarce-internet: PUSH FAILED — $NOTES"
  exit 0
fi

# verify the remote actually moved rather than trusting the push exit code
head_sha=$(git rev-parse HEAD)
remote_sha=$(git ls-remote origin refs/heads/main 2>/dev/null | cut -f1 || true)
if [ "$head_sha" != "$remote_sha" ]; then
  fail "remote head ${remote_sha:0:8} != local ${head_sha:0:8}"
  printf '%s\n' "remote/local mismatch: $remote_sha vs $head_sha" > "$FAILFILE"
  echo "scarce-internet: PUSH UNVERIFIED — $NOTES"
  exit 0
fi

rm -f "$FAILFILE"
if [ -n "$NOTES" ]; then
  echo "scarce-internet: published ${head_sha:0:8} with $NOTES"
fi
exit 0
