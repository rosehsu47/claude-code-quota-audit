# Changelog

Generated from git history (one line per commit whose subject follows
[Conventional Commits](https://www.conventionalcommits.org/)). **Don't
hand-edit this file** — rerun `scripts/gen-changelog.sh` instead; it's
idempotent and safe to run any time, it just overwrites the whole file.

## 2026-10-06

- chore(plugin): bump version to 1.4.0 for per-session cache rebuilds
- feat(quota-audit): show cache writes and cache rebuilds per session
- docs: regenerate CHANGELOG.md
- docs: fix Chinese typography in the README and stop calling the tool 外掛

## 2026-10-02

- docs: regenerate CHANGELOG.md
- chore: ignore the local drafts folder
- docs: regenerate CHANGELOG.md
- docs: open the README with the questions the plugin answers

## 2026-10-01

- docs: regenerate CHANGELOG.md
- chore(plugin): bump version to 1.3.0 for the key-findings-first report layout
- feat(quota-audit): lead the report with key findings and cut it in half

## 2026-09-10

- docs: regenerate CHANGELOG.md
- chore(plugin): bump version to 1.2.0 for the named large-context-sessions feature
- feat(quota-audit): name the sessions behind the >150k-context count
- docs: regenerate CHANGELOG.md
- chore(plugin): bump version to 1.1.0, drop duplicate version in marketplace.json
- docs: update README example output for limit-bars and % top skill
- feat: add changelog generation script
- feat(quota-audit): show limit-hit counts and per-window quota breakdown
- feat: initial public release of quota-audit Claude Code plugin
