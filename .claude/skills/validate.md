---
name: validate
description: Triage a W3C Nu Html Checker (validator.w3.org/nu) report for this project's HTML files and fix genuine errors while leaving Gmail/Outlook-required legacy markup alone. Use when the user shares a validator.pdf/validator report, or asks to "fix validator errors/warnings" on news.html, news2.html, news3.html, news4.html, or Prune Month/template.html.
---

# Validate

This project's HTML is deliberately non-standard in specific, load-bearing ways: `news4.html`'s
entry cards get emailed, and Gmail/Outlook strip `<style>` blocks and mis-render CSS on tables, so
some "obsolete" markup is there on purpose (see CLAUDE.md's pipeline section, step 4). A validator
report always mixes real defects in with markup that must stay exactly as-is. The job here is
sorting one from the other, not blindly "fixing" everything the checker flags.

## Which files this applies to

- `news2.html` (repo root) — the live monthly archive, tracked in git, never emailed itself.
- `news3.html` (repo root) — the site owner's personal WYSIWYG working draft, **stays untracked,
  never `git add`/commit it** even though everything else here gets committed per CLAUDE.md's git
  workflow.
- `Prune Month/template.html` — the root template that `news3.html`/`news2.html` ultimately derive
  from each month; tracked in git like the rest of the `Prune Month/` folder.
- `news4.html` — **generated output, never hand-edit it.** If it has a validator error, the fix
  belongs in `tribulation_times_convert.py`'s generation code (the `h_*()` builder functions), not
  in the file itself — it gets overwritten on the next run anyway.
- `news.html` — the raw hand-typed daily bulletin. Its stray `<font>`/whitespace irregularities are
  expected KompoZer/SeaMonkey artifacts the extractor is built to tolerate (see CLAUDE.md). Don't
  "clean up" its markup shape without checking with the user first — the extractor's tolerance for
  this exact irregularity is the whole reason the script exists in its current form.

## Triage rule: errors vs. warnings

**Fix these (real defects, safe everywhere):**
- `The font element is obsolete` — convert `<font ...>` to `<span style="...">` with the equivalent
  inline style (e.g. `face="Verdana"` / `style="font-family: Verdana;"` → `style="font-family:
  Verdana;"`; `size="-2"`/`"-1"` → `style="font-size:smaller;"`; `size="+1"` → `style="font-size:
  larger;"`). This is always safe for email rendering too — the Gmail/Outlook constraint is about
  *tables* and inline styles surviving `<style>`-stripping, not about which inline element wraps
  text. `<span>` with the same inline style renders identically to `<font>` everywhere `<font>` did.
- `The center element is obsolete` — convert `<center ...>` to `<div style="text-align:center;
  ...">` (fold any other attributes on the `<center>` into the `style`).
- `An img element must have an alt attribute` — add `alt=""` for purely decorative images (dividers,
  nav icons whose meaning is carried by adjacent link text) and real descriptive `alt` text for
  meaningful images. Check `news2.html` first for the established convention for that exact image
  (same `src` filenames — `pict10.jpg`, `line.gif`, `LAMPLINE.GIF`, `links17.jpg`, `email9c.gif`,
  `home.gif`, `jubilaeum.jpg`, `paper.gif` — recur across all these files); it already carries the
  canonical alt text for each (e.g. `jubilaeum.jpg` → `alt="Jubilee 2000"`, everything else →
  `alt=""`).

**Leave these alone (Gmail/Outlook compatibility, per CLAUDE.md step 4 and
`_SHARED_ENTRY_TABLE_SIGNATURES` in `tribulation_times_convert.py`):**
- `The align attribute on the img element is obsolete`
- `The border/cellpadding/cellspacing attribute on the table element is obsolete`
- Legacy `width`/`valign`/`align` HTML attributes on `<table>`/`<td>` — these matter most on the
  shared `h_news()`-generated entry-card tables (also used by `news4.html`), where Outlook's
  Word-based rendering engine ignores the CSS equivalents. A page's *own* static chrome (masthead,
  footer, year-index tables) that never reaches `news4.html` has no such constraint and *can* be
  modernized to CSS — see `fix_year_index_tables`/`fix_static_chrome_table_attrs` in
  `tribulation_times_convert.py` for the already-applied reference pattern on `news2.html` — but
  only do that if the user explicitly asks; default to leaving these warnings untouched.

## Workflow

1. Read the validator report (PDF or pasted text) and classify every finding using the rule above.
2. For a small number of fixes, use `Edit` directly. For dozens/hundreds of repetitive `<font>`/
   `<img>` fixes (the common case here — these files can have 300+ instances), write a short Python
   script that does string/regex substitution, run it, then delete the script. Preserve the file's
   existing line-ending convention (check with `data.count(b'\r\n')` vs `b'\n'` before choosing
   `newline=""` vs `newline="\n"` on write).
3. **Verify before reporting done:**
   - Strip all tags from before/after and confirm the visible text is byte-identical (only markup
     changed): `re.sub(r'<[^>]+>', '', html)` on both, compare.
   - Confirm tag balance: count of each opening pattern converted equals the count of closing tags
     replaced.
   - Parse with BeautifulSoup (`BeautifulSoup(html, 'html.parser')`) and confirm zero `<font>`/
     `<center>` remain and zero `<img>` lack `alt`.
4. **Check whether `Prune Month/prune_month.py` reads the file you just changed.** It has regexes
   (`_LADDER_QUOTE_RE_KOMPOZER`, `_LADDER_STEP_RE`, `_TEMPLATE_DATE_RE`) that expect specific tag
   shapes (literally `<font>`, specific date-span text) inside `template.html` and hardcode the
   closing tag when writing quotes back in `refresh_template()`. If you convert `<font>` to `<span>`
   anywhere `prune_month.py` parses, grep the script for `font` and update/extend the matching
   regex (see `_LADDER_QUOTE_RE_SPAN` for the precedent) rather than leaving it silently broken —
   a regex that stops matching fails quietly (skips the rewrite step) rather than erroring.
5. Commit and push per CLAUDE.md's git workflow — except `news3.html`, which never gets committed.
