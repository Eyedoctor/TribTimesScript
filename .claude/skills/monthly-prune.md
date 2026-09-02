---
name: monthly-prune
description: Run the end-of-month Prune Month workflow -- prune the completed month's daily entries from the Prune Month/news2.html staging archive, add its old-format monthly-archive link, and optionally refresh template.html for the next month's dates and Ladder of Divine Ascent quotes. Use when the user asks to "prune the month", "run the monthly prune", "refresh the template", or mentions end-of-month archive maintenance.
---

# Monthly Prune

Wraps `Prune Month/prune_month.py`, the companion script to `tribulation_times_convert.py` that runs
once at the end of each month (or start of the next, before that month's first daily conversion).
See CLAUDE.md's "Prune Month folder" section for the background — this skill is the step-by-step
checklist for actually running it well.

**Important: this operates on `Prune Month/news2.html`**, a separate staging copy — NOT the repo
root `news2.html` that `tribulation_times_convert.py` maintains day to day. Don't confuse the two.

## 0. Pre-flight — confirm dependencies are present

Per `Prune Month/Files necessary to run monthly prune.txt`, before running you need all four of these
sitting in the `Prune Month/` folder:

1. `news2.html` — the staging copy (already tracked in git; should already be there).
2. The previous month's old-format archive, e.g. `august26.html` (for pruning August in September).
3. A Ladder-of-Divine-Ascent source file with enough upcoming quotes, e.g. `oct08.html` (only needed
   if also refreshing the template — see step 3).
4. `template.html` (already tracked; should already be there).

If (2) or (3) are missing, ask the user for them or where to fetch them from — don't guess an archive
URL. `oct08.html`/`nov08.html` already in the folder are examples of this file shape, not universal
dependencies — the actual file needed changes every month.

## 1. Dry run first

From inside `Prune Month/`:

```
py -3 prune_month.py --dry-run YYYY-MM
```

`YYYY-MM` is the month being archived (e.g. `2026-08` at the start of September). Omitting it defaults
to the previous calendar month. Read the dry-run output: it reports whether daily cards would be
removed and whether the archive-table link would be added, without writing anything. If it reports
"already-present" for the archive link or "nothing to remove" for the cards, the month may already be
pruned — confirm with the user before proceeding rather than re-running blind.

## 2. Run for real

```
py -3 prune_month.py --yes YYYY-MM
```

This writes a timestamped backup (`news2_backup_YYYYMMDD_HHMMSS_prune.html`) before overwriting
`Prune Month/news2.html`. Verify after:
- The daily entry cards between `<!-- !!NEW_ENTRY_INJECT_POINT!! -->` and the LAMPLINE.GIF separator
  are gone (replaced by the empty `<br><br>` spacer).
- The year/month table has a new link cell for the pruned month pointing at the right
  `<prefix><yy>.html` (see the `MONTHS` dict in `prune_month.py` for the prefix convention — most are
  3-letter, a few are full words).

## 3. Refresh template.html for next month (usually wanted, but ask if unclear)

Either answer `y` to the script's own prompt at the end of step 2, or run explicitly:

```
py -3 prune_month.py --yes --refresh-template --ladder-source oct08.html YYYY-MM
```

(list multiple `--ladder-source` files if the first one runs out of quotes — the script prompts for
more if needed). This overwrites each standing entry in `template.html`: the date span becomes
`<NextMonth>&nbsp; , <NextYear>` (a placeholder gap for the day, filled in by hand as each day is
posted — see the `_TEMPLATE_DATE_RE` fix from 2026-09-02 if this ever stops matching entries again),
the Step title updates, and the Ladder quote text advances to the next quote in reading order. It
writes its own timestamped backup (`template_backup_YYYYMMDD_HHMMSS.html`) first.

Verify: spot-check 2-3 entries in the refreshed `template.html` — does the month/year read correctly,
does the Step number/title match the quote text below it, and does the quote text read as a
continuation of what was in the archive (not a repeat or a skip)?

## 4. Hand off to the daily cycle (manual, tell the user — don't do this yourself unless asked)

Per the user's workflow: the refreshed `template.html` becomes the new month's `news2.html` (repo
root), which then gets copied to `news3.html` to start that month's daily update cycle
(`news3.html` → `news2.html` → `news.html`, see the `news3.html` project memory). This handoff is a
manual copy the site owner does — flag that the refresh is ready for it, but don't overwrite the
repo-root `news2.html` or `news3.html` yourself without being asked, since `news3.html` in particular
must never be touched without explicit instruction (it's untracked, personal, and never `git add`ed).

## 5. Validate and commit

- Run `/validate` against the refreshed `Prune Month/news2.html` and `Prune Month/template.html` if
  it's been a while since the last check, or if you hand-edited anything.
- Commit `Prune Month/news2.html` and `Prune Month/template.html` (both tracked in git) per CLAUDE.md's
  git workflow. **Do not commit the timestamped backup files** (`news2_backup_*_prune.html`,
  `template_backup_*.html`) — same convention as the repo root's own backups, which stay untracked
  local safety copies, not repo history.
