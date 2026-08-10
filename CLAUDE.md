# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This is the source/build folder for **The Tribulation Times** (catholicprophecy.info), a daily Catholic prophecy/commentary email-and-web bulletin. It is not a software application — it's a single Python conversion script plus the HTML pages it reads and writes. There is no package manager, build system, test suite, or linter configured.

## Git workflow

After making changes to this project, always commit and push to GitHub — unless the user explicitly says not to for that change.

## Commands

Run the converter from this directory:

```
py -3 tribulation_times_convert.py
```

- On Windows, plain `python` / `python3` may resolve to the Microsoft Store stub instead of a real interpreter — use `py -3` (or the full path to a real Python) if that happens.
- Requires `beautifulsoup4` (`pip install beautifulsoup4`); everything else is stdlib.
- `ConvertUpdate.bat` is the double-click entry point for the non-technical user who maintains this site (`cd` to the script's folder, run it, `pause` so the console stays open).
- There is no test suite. The de facto way to verify a change to the parser is to re-run the script and inspect the diff between `news.html` (source) and `news4.html` (output) — check word counts, `<p>` tag balance, and grep for known landmark strings (link URLs, source labels, the Ladder of Divine Ascent excerpt) to confirm nothing was dropped, duplicated, or leaked across item boundaries. The script's own `fidelity_check()` (see below) does a lightweight version of this automatically on every run but is advisory only — it never fails the build.

## The pipeline

1. **`news.html`** is the raw daily bulletin, hand-edited by the site owner in an old WYSIWYG editor (SeaMonkey/KompoZer-style output: inconsistent nesting, stray `<font>` tags, anchor text split across lines with extra whitespace, quotes and dashes typed as plain ASCII in some places and smart/curly elsewhere). **This irregularity is the whole reason the script is complicated** — when something parses wrong, the fix is almost always "the raw HTML has a shape the extractor doesn't handle yet," not a logic bug in isolation. Read the actual bytes of `news.html` around the failure before changing extraction code.
2. `extract_entries()` splits the raw HTML into one block per dated entry (`"July 28, 2026"` etc.), using the underlined date heading as the split point. Also pulls out an optional subtitle (e.g. a feast name on the date line) and an optional bold-italic "feast day invocation" line.
3. `get_news_items()` is the actual parsing engine. For each entry block it walks every `<a>` tag with BeautifulSoup and classifies it, using a long chain of shape-specific detectors:
   - `get_source_for_link()` — finds the crimson source label (`POPE PIUS XII`, `BLOG`, etc.) that precedes a link, handling both "label and link in the same `<small>`" and "label in a sibling `<small>`" shapes.
   - `get_scripture()` — the opening `(Book Chapter:Verse)` epigraph.
   - `get_collect()` / `get_social_report()` — sets apart Pope/Saint pull-quotes (`QUOTE_TITLES`) and self-labeling X/Twitter report blocks as small-bold boxes instead of normal news cards.
   - `get_pull_quote()`, `get_ladder()` / `get_ladder_step()` — the parchment pull-quote box and the weekly "Ladder of Divine Ascent" excerpt + step number/title.
   - `get_following_excerpts()` / `get_following_features()` — the body paragraph(s) and `✦`-bullet feature list that follow a headline link.
   - `_detect_inline_and_clusters()` + `_capture_cluster_excerpt()` — distinguishes a genuine new news item from an **inline continuation link** (e.g. individual hyperlinked words inside a quoted excerpt, or a parenthetical citation after a headline). Anchors within 2 consecutive `<br>` tags of the previous anchor are treated as inline continuations of a "cluster," not separate cards; the cluster's full prose (primary link + interstitial text + inline links) is captured as a list of paragraph-level fragments — one per source `<p>` — so `h_news()` renders one real `<p>` per source paragraph instead of flattening the whole article into a single block. Bold-italic `<p>` subheadings and `margin-left` indented block-quotes inside a cluster are also detected and re-styled rather than silently flattened.
   - A pre-pass groups bare consecutive headline links under a bold(+italic) `<small>` heading into one compact "headline list" card instead of one card each.
   - `SKIP_URL_FRAGMENTS` (module top) and `CLUSTER_STOP_PHRASES` (near the cluster code) are the two lists that decide what's boilerplate (subscribe/unsubscribe, mailto, the Bible-in-a-Year links, the Ladder link, the archive link) vs. real content vs. a hard section boundary. **Most "content leaked into the wrong card" or "boilerplate got rendered as a news item" bugs trace back to one of these two lists not covering a new markup shape** — check them first.
4. `build_entry_html()` assembles one entry's extracted pieces (scripture, pull-quote, collect box, each news item via `h_news()`, the Ladder box) into styled HTML using the `h_*()` builder functions. All styling is inline (`style="..."` attributes), deliberately — the output must render correctly in email clients (Gmail/Outlook strip `<style>` blocks and don't support Grid/Flexbox), so layout uses tables and every layout-critical style is duplicated inline even though there's also a `<style>` block for browser viewing.
5. `repair_entry()` / `REPAIR_LOG` is a safety net: after building the entry HTML, it re-scans the raw block for any link or ALL-CAPS label that didn't make it into the output and force-appends a card for it, logging what it had to patch. If you see repair-log lines in the console output, that means the primary extraction missed something — worth checking why rather than trusting the patched-up card's formatting.
6. `fidelity_check()` prints a link/label carry-over count for the newest entry as a final advisory sanity check (never blocks the build).
7. `build_news4()` wraps the entry HTML in the full page template (masthead, nav bar, Bible-in-a-Year button, sidebar Vatican News widget, footer) to produce `news4.html`, written atomically (write to `.tmp`, then replace).
8. `prepend_to_archive()` updates `news2.html`, the running monthly archive:
   - **Re-run protection**: an entry is skipped if its date heading already appears in the archive, so re-running the script (or feeding it a multi-day `news.html`) can't create duplicate days.
   - Writes a timestamped backup (`news2_backup_YYYYMMDD_HHMMSS.html`) before modifying, and rotates old backups down to the newest 10.
   - Finds the insertion point via `INJECT_MARKER` (`<!-- !!NEW_ENTRY_INJECT_POINT!! -->`) if present, else falls back to just-after-the-banner-image or just-before-the-first-existing-date-heading heuristics.
   - Also opportunistically fixes W3C-invalid `<meta>` tags and injects a responsive-image CSS rule into the archive's `<head>` if missing.
   - Writes atomically like `news4.html`.

## Settings vs. scraped content

The `SETTINGS` block at the top of the file (`SUBSCRIBE_URL`, `ARCHIVES_URL`, `LADDER_URL`, `GA_ACCOUNT`, `COLORS`, etc.) holds the **modernized site's own fixed values**, which in some cases deliberately differ from what's hardcoded in the raw `news.html` (e.g. `ARCHIVES_URL` points at `tribtimes.com`, not `catholicprophecy.info`; `LADDER_URL` is `http://`, not `https://`). Don't "fix" these to match `news.html` under the assumption it's a scraping bug — that's intentional site configuration and should only change if the user asks. The one exception is `BIBLE_YEAR_URL`/`BIBLE_YEAR_LABEL`, which `main()` deliberately re-derives from the *current* month's link in `news.html` on every run (the hardcoded constant is only a fallback).

## Typo correction

`news.html` is hand-typed by a non-technical site owner and periodically contains obvious single-word typos in source labels or headlines (e.g. `CHURH` instead of `CHURCH`). When working on this repo — running the converter, reviewing generated output, or otherwise touching a day's entry — proactively catch and fix these rather than silently carrying them through the pipeline: correct the typo in `news.html` itself (the source of truth) and regenerate `news4.html`/`news2.html` from it, rather than patching only the generated output.

Use judgment about what counts as "obvious":
- Fix: plain misspellings of ordinary/common words (`CHURH` → `CHURCH`, `recieve` → `receive`).
- Don't "fix": archaic or period-accurate spelling in quoted historical/devotional text (e.g. the weekly Ladder of Divine Ascent excerpt, which is a translated centuries-old text and may contain unusual wording that looks off but is faithful to the source translation), direct quotations, proper nouns, foreign names, or anything you're not confident is actually a typo rather than the source's intended wording. When in doubt, ask rather than silently "correcting" someone's words.

## Output files

- `news4.html` — generated daily page; this is what gets uploaded to the live site as the new `news.html`.
- `news2.html` — the running monthly archive; entries are prepended newest-first.
- `news2_backup_*.html` — automatic pre-write backups of the archive (safe to delete older ones; the script keeps the newest 10 itself).
