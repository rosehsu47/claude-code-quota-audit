#!/usr/bin/env bash
# scripts/gen-changelog.sh — mechanically regenerates CHANGELOG.md from git
# history in Conventional Commits format. No manual editing needed: this
# script rewrites the whole file every time, so it's always in sync with
# whatever `git log` says. Zero external dependencies (plain git + bash,
# bash 3.2 compatible — this machine's default /bin/bash).
#
# Precondition: commit subjects follow Conventional Commits
# (`type(scope): summary`). Merge commits are skipped (--no-merges); a
# subject that doesn't match the format is skipped too, rather than dumped
# into the changelog as noise.
#
# Usage: scripts/gen-changelog.sh
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="CHANGELOG.md"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

{
  echo "# Changelog"
  echo
  echo "Generated from git history (one line per commit whose subject follows"
  echo "[Conventional Commits](https://www.conventionalcommits.org/)). **Don't"
  echo "hand-edit this file** — rerun \`scripts/gen-changelog.sh\` instead; it's"
  echo "idempotent and safe to run any time, it just overwrites the whole file."

  last_date=""
  # The trailing `echo` guarantees a final newline: git log's output never
  # ends in one, and `while read` silently drops a last line with no
  # newline — which would drop the oldest commit in history every time.
  { git log --no-merges --date=short --pretty=format:'%ad%x09%s'; echo; } \
    | while IFS="$(printf '\t')" read -r date subject; do
    # Skip subjects that don't look like Conventional Commits — keeps stray
    # non-conforming history out of the changelog instead of forcing it in.
    if ! printf '%s\n' "$subject" | grep -qE '^[a-z]+(\([A-Za-z0-9_./-]+\))?!?: '; then
      continue
    fi
    if [ "$date" != "$last_date" ]; then
      echo
      echo "## $date"
      echo
      last_date="$date"
    fi
    echo "- $subject"
  done
} > "$TMP"

mv "$TMP" "$OUT"
trap - EXIT
n=$(git log --no-merges --oneline | wc -l | tr -d ' ')
echo "Regenerated ${OUT} (scanned $n non-merge commits)"
