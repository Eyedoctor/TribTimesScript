#!/usr/bin/env python3
"""
prune_month.py — end-of-month tribtimes.com archive maintenance
================================================================

When a month ends, this script removes that month's daily entry cards
from the modern tribtimes.com ``news2.html`` archive AND adds a link to
the corresponding old-format monthly archive
(e.g. ``august26.html``) in the year/month table at the bottom of the
page.

Companion to ``tribulation_times_convert.py``, which prepends new daily
entries during the month. Run this ONCE at the end of each month (or
start of the next) before the first prepend of the new month.

USAGE
-----
    python prune_month.py                  # prompts for month; default = previous month
    python prune_month.py 2026-07          # prune July 2026 non-interactively
    python prune_month.py 2026 7           # same, space-separated
    python prune_month.py --dry-run 2026-07  # show what would change, don't write

WORKFLOW
--------
1. Reads ``news2.html`` from the working folder (same folder as
   ``tribulation_times_convert.py``).
2. Snips all daily entry cards between the
   ``<!-- !!NEW_ENTRY_INJECT_POINT!! -->`` marker and the LAMPLINE.GIF
   separator (which is where daily entries live). Restores the empty
   ``<br><br>`` spacer that sits between them when the archive is
   between-months.
3. Locates the year/month archive table (comment
   ``<!-- ARCHIVE TABLE 2012-2026 -->``) and inserts a link to
   ``<month><yy>.html`` in the cell for the target month & year.
4. Writes a timestamped backup
   (``news2_backup_YYYYMMDD_HHMMSS_prune.html``) BEFORE overwriting.

DESIGN NOTES
------------
- The pruning is idempotent-friendly: if the archive link is already
  present, the script says so and does not add a duplicate.
- The daily-card snip is a no-op when there are no cards between the
  markers (script prints "no daily entries to remove").
- Both steps happen in the same run; either can be a no-op without
  aborting the other. Nothing is written if BOTH are no-ops.
- The empty-slot placeholder in an "unfilled" 2026 cell is
  ``<td><br></td>`` (or ``<td valign="top"><br></td>`` for the
  rightmost year's right-hand column). The script accepts either.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import shutil
import sys
from pathlib import Path

try:
    from bs4 import BeautifulSoup, NavigableString, Tag
except ImportError:
    print("ERROR: this script requires beautifulsoup4. Install with:")
    print("    pip install beautifulsoup4")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

ARCHIVE_FILE = "news2.html"

INJECT_MARKER  = "<!-- !!NEW_ENTRY_INJECT_POINT!! -->"
LAMPLINE_HREF  = "https://www.tribtimes.com/LAMPLINE.GIF"

# The catholicprophecy.info archive host — the URL each monthly archive
# link points to. Kept as a constant so a future domain change is a
# one-line edit.
ARCHIVE_BASE_URL = "http://www.catholicprophecy.info"

# File-name prefix and short display abbreviation for each month.
# The prefixes match the existing archive's naming convention (some
# months are full-word, some 3-letter — inherited from the legacy site).
MONTHS = {
    1:  ("jan",    "Jan"),
    2:  ("feb",    "Feb"),
    3:  ("march",  "Mar"),
    4:  ("april",  "Apr"),
    5:  ("may",    "May"),
    6:  ("june",   "Jun"),
    7:  ("july",   "Jul"),
    8:  ("august", "Aug"),
    9:  ("sept",   "Sep"),
    10: ("oct",    "Oct"),
    11: ("nov",    "Nov"),
    12: ("dec",    "Dec"),
}

# The archive table's rows are grouped into month-pairs (Jan/Jul,
# Feb/Aug, ...). Row index 0 = header; data rows start at 1.
# Each row: row = ((month_index-1) % 6) + 1
# Side within the row: LEFT for Jan-Jun, RIGHT for Jul-Dec.

# The empty-slot placeholder HTML in an unfilled cell. When an archive
# link is already present in that cell we do nothing; when the cell
# contains only <br> we replace with the archive anchor.
EMPTY_CELL_PATTERNS = [
    "<br>",
    "<br/>",
    "<br />",
]


# ═══════════════════════════════════════════════════════════════════════════
# LADDER-QUOTE HELPERS   (used by --refresh-template)
# ═══════════════════════════════════════════════════════════════════════════

_LADDER_STEP_RE = re.compile(
    # "Step N" — accepts any digit count
    r'Step\s*(\d+)\s*'
    # optional separator: ASCII hyphen, en-dash, em-dash, or their HTML
    # entities, OR a colon (the modern tribtimes format uses "Step 9: …")
    r'(?:[-\u2013\u2014:]|&[mn]dash;)?\s*'
    # opening quote: straight, curly-left, or HTML entities (&quot;, &ldquo;)
    r'(?:["\u201c\u201f]|&(?:quot|ldquo);)\s*'
    # title text — anything up to the closing quote (stopping at newlines
    # so we don't run away if the closing quote is malformed)
    r'([^"\u201c\u201d\u201f\r\n<]{3,120}?)'
    # closing quote: straight, curly-right, or HTML entities (&quot;, &rdquo;)
    r'\s*(?:["\u201d\u201f]|&(?:quot|rdquo);)'
)
# Quote regexes for both known archive formats.
# KompoZer format (catholicprophecy.info archives):
#   <font style="font-family: Verdana;" face="Verdana">N. text …</font>
# The face="Verdana" attribute is inconsistent across entries — some have
# it, some don't — so we only require the Verdana font-family style.
_LADDER_QUOTE_RE_KOMPOZER = re.compile(
    r'<font[^>]*style="[^"]*Verdana[^"]*"[^>]*>\s*(\d{1,3})\.\s+(.*?)</font>',
    re.DOTALL)
# Modernized KompoZer format (template.html, after the obsolete <font>
# elements there were converted to <span> for W3C validity) — identical
# shape to the KOMPOZER pattern above, just with <span>/</span> in place
# of <font>/</font>.
_LADDER_QUOTE_RE_SPAN = re.compile(
    r'<span[^>]*style="[^"]*Verdana[^"]*"[^>]*>\s*(\d{1,3})\.\s+(.*?)</span>',
    re.DOTALL)
# Modern tribtimes.com format (news2.html, script-generated archives):
#   <p style="...font-style:italic;...color:#3d2b0d;...">N. text …</p>
# Identified by the italic + brown-ink combination that no other <p> in
# the file uses.
_LADDER_QUOTE_RE_MODERN = re.compile(
    r'<p[^>]*style="[^"]*font-style:italic[^"]*color:#3d2b0d[^"]*"[^>]*>'
    r'\s*(\d{1,3})\.\s+(.*?)</p>',
    re.DOTALL)
_LADDER_QUOTE_PATTERNS = (_LADDER_QUOTE_RE_KOMPOZER, _LADDER_QUOTE_RE_SPAN,
                           _LADDER_QUOTE_RE_MODERN)


def _parse_ladder_quotes(html):
    """Extract Ladder quotes with their Step context in document order.
    Returns list of dicts:
      {step_num, step_title, quote_num, quote_text, snippet}
    where quote_text is plain-text (HTML tags stripped) with the source's
    own word-wrapping preserved — these archives are hand-maintained and
    wrap each quote across several short lines separated by blank lines,
    and the template should keep that same look rather than flattening
    the quote to one long line. `snippet` is a single-line, whitespace-
    collapsed preview for console/log output only.

    A "quote" is a <font>/<span> face=\"Verdana\" or <p> (modern format)
    tag matching one of _LADDER_QUOTE_PATTERNS above, and it inherits the
    most-recently-seen \"Step N — Title\" header preceding it."""
    events = []
    for m in _LADDER_STEP_RE.finditer(html):
        events.append((m.start(), 'step', int(m.group(1)), m.group(2)))
    for pattern in _LADDER_QUOTE_PATTERNS:
        for m in pattern.finditer(html):
            events.append((m.start(), 'quote', int(m.group(1)), m.group(2)))
    events.sort(key=lambda x: x[0])

    current_step_num = None
    current_step_title = None
    out = []
    for evt in events:
        if evt[1] == 'step':
            current_step_num = evt[2]
            current_step_title = evt[3]
            continue
        if current_step_num is None:
            continue  # quote before any Step header — skip
        _, _, qnum, qraw = evt
        # Strip HTML tags only — keep the source's internal line breaks
        # (its word-wrap) intact; just trim the leading/trailing
        # whitespace the tag-stripping and the </font> boundary leave.
        tags_stripped = re.sub(r'<[^>]+>', ' ', qraw)
        wrapped_text = tags_stripped.strip()
        collapsed_text = re.sub(r'\s+', ' ', tags_stripped).strip()
        out.append({
            'step_num':   current_step_num,
            'step_title': current_step_title,
            'quote_num':  qnum,
            'quote_text': wrapped_text,
            'snippet':    collapsed_text[:80],
        })
    return out


def _get_last_ladder_used(archive_html):
    """Return (step_num, quote_num) for the MOST RECENT Ladder quote used in
    a monthly archive. In these archives new entries are at the top, so the
    quote whose <font> tag appears FIRST in the document is the latest
    posted — which for Ladder-continuation purposes is also the highest
    (step, quote) pair in reading order."""
    quotes = _parse_ladder_quotes(archive_html)
    if not quotes:
        return None, None
    q = quotes[0]
    return q['step_num'], q['quote_num']


def _get_next_ladder_quotes(source_html, after_step, after_num, count):
    """Get the next `count` Ladder quotes from `source_html` that come
    AFTER (after_step, after_num) in reading order — (step ascending,
    then quote_num ascending). Returns list ORDERED FOR TEMPLATE display,
    i.e. top-to-bottom = latest to earliest posting, which is the reverse
    of reading order.

    Handles the common case where a source file contains many overlapping
    quotes (an archive of a whole month): dedup by (step, num), keep the
    first occurrence in doc order (which is the most-recently-authored
    copy), then sort by reading order for continuation.
    """
    seen = set()
    unique = []
    for q in _parse_ladder_quotes(source_html):
        key = (q['step_num'], q['quote_num'])
        if key in seen:
            continue
        seen.add(key)
        unique.append(q)
    # Sort by reading order
    unique.sort(key=lambda q: (q['step_num'], q['quote_num']))
    # Filter to quotes AFTER the last used
    after = [q for q in unique if
             q['step_num'] > after_step
             or (q['step_num'] == after_step and q['quote_num'] > after_num)]
    if len(after) < count:
        return after  # caller will error-check
    # Take first N in reading order, then reverse for template display
    return list(reversed(after[:count]))


# ═══════════════════════════════════════════════════════════════════════════
# TEMPLATE-REFRESH LOGIC   (--refresh-template)
# ═══════════════════════════════════════════════════════════════════════════

# Date span pattern in template — KompoZer's underlined-date convention.
# Matches e.g. "August 12, 2026", "September 3, 2026", etc.
_TEMPLATE_DATE_RE = re.compile(
    r'(<span style="text-decoration: underline; font-family: Verdana;">)'
    r'([A-Z][a-z]+(?:\s+\d+,\s+\d{4})?)'  # month, optionally with " N, YYYY"
    r'(</span>)')

# Month-name normalisation
_MONTH_NAMES = ("January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December")


def _detect_archive_file(year, month, folder):
    """Look for the archive file for this month in `folder`. Returns Path
    or None. Uses the same naming convention as the archive-table links
    (janYY.html, ..., julyYY.html, augustYY.html, etc.)."""
    prefix, _ = MONTHS[month]
    yy = f"{year % 100:02d}"
    p = folder / f"{prefix}{yy}.html"
    return p if p.exists() else None


def refresh_template(target_year, target_month, folder,
                     source_paths=None, skip_confirm=False, dry_run=False):
    """Refresh template.html for the month AFTER target month.

    Steps:
      1. Find template.html, count standing entries by their date spans
      2. Find prev-month archive (e.g. august26.html for 2026-08)
      3. Prompt for one or more Ladder-source files (or use --ladder-source)
      4. Read all files; parse and combine Ladder quotes in reading order;
         if the FIRST source runs short of the needed count, prompt for
         another file
      5. Overwrite each entry: date → "<Month>&nbsp; , YYYY"; Step title
         & Ladder quote (per-entry, so a Step transition mid-template is
         handled naturally)

    Returns True if template.html was written, False otherwise.
    """
    template = folder / "template.html"
    if not template.exists():
        print(f"  template.html not found in {folder} — skipping template refresh.")
        return False

    # Next month name (Sep for Aug, Jan for Dec, etc.)
    next_month_idx = (target_month % 12) + 1
    next_year = target_year + (1 if target_month == 12 else 0)
    next_month_name = _MONTH_NAMES[next_month_idx - 1]
    print(f"\nTemplate refresh (for {next_month_name} {next_year}):")

    # Prev-month archive (auto-detected by naming convention)
    archive_path = _detect_archive_file(target_year, target_month, folder)
    if archive_path is None:
        prefix, _ = MONTHS[target_month]
        yy = f"{target_year % 100:02d}"
        print(f"  ✗ prev-month archive not found: {prefix}{yy}.html")
        print(f"    Place {prefix}{yy}.html in this folder and re-run "
              f"with --refresh-template.")
        return False
    print(f"  Prev-month archive: {archive_path.name}")

    # Load prev-month archive and find last quote used
    archive_html = archive_path.read_bytes().decode('utf-8')
    last_step, last_num = _get_last_ladder_used(archive_html)
    if last_step is None:
        print(f"  ✗ No Ladder quotes found in {archive_path.name}.")
        # Diagnostic: report what WAS found so the user can send a snippet.
        step_hits = _LADDER_STEP_RE.findall(archive_html)
        quote_hits = sum(len(p.findall(archive_html)) for p in _LADDER_QUOTE_PATTERNS)
        step_raw = re.findall(r'Step\s*\d+[^<]{0,80}', archive_html)
        print(f"    Diagnostic: 'Step N' text hits: {len(step_raw)}, "
              f"parsed step headers: {len(step_hits)}, "
              f"quote tags (both formats): {quote_hits}")
        if step_raw and not step_hits:
            print(f"    First raw 'Step' occurrence in file (title regex "
                  f"didn't match this — likely a quote/dash character variant):")
            print(f"      {step_raw[0][:120]!r}")
        return False
    print(f"  Last Ladder quote used: Step {last_step} #{last_num}")

    # Load template first (we need the count for figuring out how many quotes)
    template_html = template.read_bytes().decode('utf-8')
    date_matches = list(_TEMPLATE_DATE_RE.finditer(template_html))
    entry_count = len(date_matches)
    if entry_count == 0:
        print(f"  ✗ No standing entries found in template.html "
              f"(no matching date spans).")
        return False
    print(f"  template.html: {entry_count} standing entries detected")

    # Resolve initial source files
    if not source_paths:
        try:
            reply = input(
                "  Ladder source file(s) — space/comma separated for more than one\n"
                "  (e.g. 'oct08.html' or 'oct08.html nov08.html'): "
            ).strip()
        except EOFError:
            reply = ""
        if not reply:
            print("  ✗ No source file given — skipping template refresh.")
            return False
        source_paths = [folder / s.strip() for s in re.split(r'[,\s]+', reply) if s.strip()]

    # Collect enough quotes across the source list; prompt for more if short
    collected = []
    used_sources = []
    remaining_needed = entry_count
    pool = list(source_paths)
    while remaining_needed > 0:
        if not pool:
            # Ran out of provided files but still short — prompt for another
            print(f"  Only {len(collected)} of {entry_count} quotes so far; "
                  f"need {remaining_needed} more.")
            try:
                reply = input("  Next Ladder source file "
                              "(or ENTER to abort): ").strip()
            except EOFError:
                reply = ""
            if not reply:
                print(f"  ✗ Aborted — need {remaining_needed} more quotes.")
                return False
            pool.append(folder / reply)

        sp = pool.pop(0)
        if not sp.exists():
            print(f"  ✗ source file not found: {sp}")
            return False
        used_sources.append(sp)
        src_html = sp.read_bytes().decode('utf-8')
        # Take next N from THIS file (in reading order)
        got = _get_next_ladder_quotes(src_html, last_step, last_num, remaining_needed)
        # Filter out any (step, num) we've already collected
        seen = {(q['step_num'], q['quote_num']) for q in collected}
        # Note: got is returned reverse-of-reading-order (top→bottom = latest→earliest).
        # Re-sort to reading order for accumulation, then re-reverse at the end.
        got_reading_order = sorted(got, key=lambda q: (q['step_num'], q['quote_num']))
        for q in got_reading_order:
            key = (q['step_num'], q['quote_num'])
            if key in seen:
                continue
            collected.append(q)
            seen.add(key)
        print(f"    {sp.name}: contributed {len(got_reading_order)} usable quotes")
        # Advance the "last used" cursor to the highest quote we've collected
        if collected:
            collected.sort(key=lambda q: (q['step_num'], q['quote_num']))
            last_of = collected[-1]
            last_step, last_num = last_of['step_num'], last_of['quote_num']
        remaining_needed = entry_count - len(collected)

    # Order collected quotes reading-order ascending, take first N, reverse for template
    collected.sort(key=lambda q: (q['step_num'], q['quote_num']))
    next_quotes = list(reversed(collected[:entry_count]))

    print(f"  Ladder source(s) used: {', '.join(sp.name for sp in used_sources)}")
    print(f"  Next {entry_count} quotes for {next_month_name} template "
          f"(top → bottom):")
    for q in next_quotes:
        print(f"    Step {q['step_num']} #{q['quote_num']}: {q['snippet']}")

    if not skip_confirm and not dry_run:
        try:
            reply = input("\n  Apply these changes to template.html? [y/N] ").strip().lower()
        except EOFError:
            reply = ""
        if reply not in ("y", "yes"):
            print("  Template refresh aborted.")
            return False

    # ---- Apply edits ---------------------------------------------------
    #
    # Strategy: split the template into "entries" bounded by date spans.
    # Each entry begins at its date span and ends at the next date span
    # (or end of file). Rewrite entries LAST-to-FIRST so byte positions
    # of earlier entries stay valid.
    entry_starts = [m.start() for m in date_matches]
    entry_ends = entry_starts[1:] + [len(template_html)]
    new_html = template_html

    for idx in reversed(range(entry_count)):
        entry_html = new_html[entry_starts[idx]:entry_ends[idx]]
        q = next_quotes[idx]

        # (a) Date span → "September&nbsp; , 2026" (with a visible gap where
        # the day number goes when you actually post that day — matches the
        # convention used in hand-refreshed templates).
        date_replacement = f"{next_month_name}&nbsp; , {next_year}"
        entry_html = _TEMPLATE_DATE_RE.sub(
            lambda m: m.group(1) + date_replacement + m.group(3),
            entry_html, count=1)

        # (b) Step title → "Step 9- \"On remembrance of wrongs\""
        entry_html = _LADDER_STEP_RE.sub(
            f'Step {q["step_num"]}- "{q["step_title"]}"',
            entry_html, count=1)

        # (c) Quote font/span tag → same wrapper, new "N. text". Template
        # entries may use either shape (see _LADDER_QUOTE_RE_KOMPOZER vs.
        # _LADDER_QUOTE_RE_SPAN above), so try both and keep whichever
        # tag name actually matched for the closing tag / orphan-period scan.
        quote_match = _LADDER_QUOTE_RE_KOMPOZER.search(entry_html)
        close_tag, next_tag_pattern = "</font>", r'<font[^>]*>'
        if quote_match is None:
            quote_match = _LADDER_QUOTE_RE_SPAN.search(entry_html)
            close_tag, next_tag_pattern = "</span>", r'<span[^>]*>'
        if quote_match:
            open_end = quote_match.group(0).index(">") + 1
            open_tag = quote_match.group(0)[:open_end]
            replacement = f'{open_tag}{q["quote_num"]}. {q["quote_text"]}{close_tag}'
            tail = entry_html[quote_match.end():]
            # The Ladder source files write each verse's closing period
            # inside the same wrapper tag as the sentence, so quote_text
            # above already ends with one. Some existing template entries
            # instead carry that period on its own in the very next wrapper
            # tag (a relic of an earlier refresh cycle) — left alone, that
            # would render as a doubled "..". Strip just the stray period,
            # keeping the tag (and any trailing <br>) intact.
            if re.search(r'[.!?]\s*$', q["quote_text"]):
                orphan_period = re.match(r'(\s*' + next_tag_pattern + r'\s*)\.', tail)
                if orphan_period:
                    tail = orphan_period.group(1) + tail[orphan_period.end():]
            entry_html = entry_html[:quote_match.start()] + replacement + tail

        new_html = new_html[:entry_starts[idx]] + entry_html + new_html[entry_ends[idx]:]

    if dry_run:
        print("\n  Dry-run — template.html not written.")
        return False

    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = template.with_name(f"template_backup_{stamp}.html")
    shutil.copy2(template, backup)
    print(f"\n  Backup: {backup.name}")
    template.write_bytes(new_html.encode('utf-8'))
    print(f"  Wrote: {template.name}")
    return True


# ═══════════════════════════════════════════════════════════════════════════
# ARGUMENT PARSING
# ═══════════════════════════════════════════════════════════════════════════

def _default_prev_month():
    """First day of last month (relative to today), as (year, month)."""
    today = _dt.date.today()
    first_of_this = today.replace(day=1)
    prev = first_of_this - _dt.timedelta(days=1)
    return prev.year, prev.month


def _parse_args():
    p = argparse.ArgumentParser(
        description="Prune a completed month's entries from the "
                    "tribtimes.com news2.html archive.")
    p.add_argument("year_or_ym", nargs="?",
                   help="Year (with month as next arg) OR "
                        "'YYYY-MM' / 'YYYY/MM' / 'YYYY MM' combined")
    p.add_argument("month", nargs="?",
                   help="Month (1-12) — required if year given separately")
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would change, without writing")
    p.add_argument("--yes", "-y", action="store_true",
                   help="Skip interactive confirmation")
    p.add_argument("--refresh-template", action="store_true",
                   help="After pruning news2.html, also refresh template.html "
                        "for the following month (updates dates + Ladder quotes)")
    p.add_argument("--no-refresh-template", action="store_true",
                   help="Never refresh template.html (skip the prompt)")
    p.add_argument("--ladder-source", metavar="FILE", nargs="+",
                   help="One or more filenames in current folder containing "
                        "the next set of Ladder quotes (e.g. oct08.html, "
                        "or 'oct08.html nov08.html' if the first runs out). "
                        "Only used with --refresh-template; prompts if omitted.")
    args = p.parse_args()

    year, month = None, None
    if args.year_or_ym:
        if args.month:
            year = int(args.year_or_ym)
            month = int(args.month)
        else:
            s = args.year_or_ym.replace("/", "-").replace(" ", "-")
            parts = s.split("-")
            if len(parts) == 2:
                year, month = int(parts[0]), int(parts[1])
            else:
                raise SystemExit(f"ERROR: cannot parse '{args.year_or_ym}' "
                                 "— expected YYYY-MM or 'YYYY MM'")
    else:
        year, month = _default_prev_month()

    if not (1 <= month <= 12) or year < 2000 or year > 2100:
        raise SystemExit(f"ERROR: invalid year/month {year}-{month:02d}")

    return (year, month, args.dry_run, args.yes,
            args.refresh_template, args.no_refresh_template, args.ladder_source)


# ═══════════════════════════════════════════════════════════════════════════
# STEP 1 — SNIP DAILY ENTRY CARDS
# ═══════════════════════════════════════════════════════════════════════════

def snip_daily_cards(html):
    """Remove everything between the INJECT_POINT marker and the
    LAMPLINE.GIF separator, restoring the empty ``<br><br>`` spacer
    that lives there between months. Returns (new_html, cards_removed_flag).
    Preserves surrounding indentation."""
    inject_pos = html.find(INJECT_MARKER)
    if inject_pos < 0:
        raise SystemExit(f"ERROR: INJECT_POINT marker not found "
                         f"({INJECT_MARKER}). Aborting.")
    inject_end = inject_pos + len(INJECT_MARKER)

    lampline_pos = html.find(LAMPLINE_HREF, inject_end)
    if lampline_pos < 0:
        raise SystemExit(f"ERROR: LAMPLINE.GIF reference not found "
                         f"after the INJECT_POINT. Aborting.")
    # Back up to the opening <img
    lampline_open = html.rfind("<img", inject_end, lampline_pos)
    if lampline_open < 0:
        raise SystemExit("ERROR: could not locate the <img> that opens "
                         "the LAMPLINE separator. Aborting.")

    between = html[inject_end:lampline_open]
    # "Empty" state, as it appears in the freshly-pruned reference file:
    #   <!-- !!NEW_ENTRY_INJECT_POINT!! --><br>\n        <br>\n        <img ...
    empty_between = "<br>\r\n        <br>\r\n        " \
                    if "\r\n" in between else \
                    "<br>\n        <br>\n        "
    # A stricter check: is `between` already the empty spacer?
    stripped = re.sub(r"\s+", " ", between).strip()
    already_empty = stripped in ("<br> <br>", "<br/> <br/>", "<br /> <br />")
    if already_empty:
        return html, False  # nothing to snip

    new_html = html[:inject_end] + empty_between + html[lampline_open:]
    return new_html, True


# ═══════════════════════════════════════════════════════════════════════════
# STEP 2 — ADD LINK TO ARCHIVE TABLE
# ═══════════════════════════════════════════════════════════════════════════

def add_archive_link(html, year, month):
    """Insert a link to <prefix><yy>.html into the correct cell of the
    year/month archive table.

    Uses BeautifulSoup ONLY to locate the target row and cell index —
    the actual edit is a targeted string replacement in the raw HTML,
    so all other formatting (indentation, self-closing tag style, line
    breaks) elsewhere in the file is preserved byte-for-byte.

    Returns (new_html, action) where action is 'added', 'already-present',
    or 'no-slot' (cell missing or table unrecognised)."""
    prefix, abbr = MONTHS[month]
    yy = f"{year % 100:02d}"
    href = f"{ARCHIVE_BASE_URL}/{prefix}{yy}.html"

    # Bail early if this link is already in the file anywhere — avoids
    # duplicate insertions on re-runs.
    if href in html:
        return html, "already-present"

    soup = BeautifulSoup(html, "html.parser")

    # Locate the archive-table comment covering this year (e.g.
    # "ARCHIVE TABLE 2012-2026"). Fall back to any archive-table comment
    # whose year range brackets the target year.
    marker = None
    for c in soup.find_all(string=lambda s: "ARCHIVE TABLE" in str(s)):
        m = re.search(r"(\d{4})\D+(\d{4})", str(c))
        if m and int(m.group(1)) <= year <= int(m.group(2)):
            marker = c
            break
    if marker is None:
        return html, "no-slot"
    table = marker.find_next("table")
    if table is None:
        return html, "no-slot"
    rows = table.find_all("tr")
    if len(rows) < 7:
        return html, "no-slot"

    # Header row (rows[0]) defines the year → column-position mapping.
    header_cells = rows[0].find_all("td")
    year_col_start = None
    col = 0
    for td in header_cells:
        txt = td.get_text(strip=True)
        span = int(td.get("colspan", "1"))
        if txt == str(year):
            year_col_start = col
            break
        col += span
    if year_col_start is None:
        return html, "no-slot"

    # Data row for this month: Jan/Jul → 1, Feb/Aug → 2, ..., Jun/Dec → 6.
    row_idx = ((month - 1) % 6) + 1
    if row_idx >= len(rows):
        return html, "no-slot"
    side_offset = 0 if month <= 6 else 1
    target_cell_index = year_col_start + side_offset

    # Find the target row in the raw HTML. Every row we care about
    # contains at least one <a href=...> anchor (rows for early years
    # are fully populated). Use the FIRST anchor href in this row as a
    # unique locator, since URLs are unique across the archive table.
    target_row_tag = rows[row_idx]
    first_a = target_row_tag.find("a", href=True)
    if first_a is None:
        return html, "no-slot"
    locator = first_a.get("href")
    loc_pos = html.find(locator)
    if loc_pos < 0:
        return html, "no-slot"
    row_start = html.rfind("<tr>", 0, loc_pos)
    row_end = html.find("</tr>", loc_pos) + 5
    if row_start < 0 or row_end < 5:
        return html, "no-slot"
    raw_row = html[row_start:row_end]

    # Find every cell in the raw row and pick the target one by index.
    cell_matches = list(re.finditer(r'<td\b[^>]*>.*?</td>', raw_row, re.DOTALL))
    if target_cell_index >= len(cell_matches):
        return html, "no-slot"
    tc_match = cell_matches[target_cell_index]
    target_cell_raw = tc_match.group(0)

    # Only overwrite if the cell is empty (contains only <br> and whitespace).
    inner = re.sub(r'<br\s*/?>', '', target_cell_raw)
    inner = re.sub(r'<[^>]+>', '', inner).strip()
    if inner:
        # Cell has some content already. Try to identify what — helps the
        # user decide whether to hand-edit (e.g. our target month was archived
        # under a different name like "Lent" for March).
        existing = re.search(r'href="([^"]+)"', target_cell_raw)
        if existing:
            return html, f"other-link:{existing.group(1)}"
        return html, "already-present"

    # Preserve vertical alignment from the existing empty cell (used on
    # the last column of the last year for visual consistency). It may
    # carry either the legacy valign="top" HTML attribute or, after the
    # W3C-validator cleanup in tribulation_times_convert.py converted
    # news2.html's static chrome to CSS, its equivalent
    # style="vertical-align:top;". Detect either and always emit the
    # modern CSS form, so pruning never reintroduces the obsolete
    # attribute that cleanup removed.
    has_valign = bool(re.search(r'valign="top"', target_cell_raw)
                       or re.search(r'vertical-align\s*:\s*top', target_cell_raw))
    valign_attr = ' style="vertical-align:top;"' if has_valign else ""

    # Build the replacement cell in the exact indentation style used by
    # every other filled cell in this archive.
    new_cell = (
        f'<td{valign_attr}><a\n'
        f'                    href="{href}"\n'
        f'                    style="color:#2e5c6e;">{abbr}</a></td>'
    )

    new_raw_row = raw_row[:tc_match.start()] + new_cell + raw_row[tc_match.end():]
    new_html = html[:row_start] + new_raw_row + html[row_end:]
    return new_html, "added"


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    (year, month, dry_run, skip_confirm,
     refresh_flag, no_refresh_flag, ladder_source) = _parse_args()
    prefix, abbr = MONTHS[month]
    yy = f"{year % 100:02d}"
    label = f"{abbr} {year} ({prefix}{yy}.html)"

    path = Path(ARCHIVE_FILE)
    if not path.exists():
        raise SystemExit(f"ERROR: {ARCHIVE_FILE} not found in current folder. "
                         f"Run this script in the same folder as "
                         f"tribulation_times_convert.py.")

    print(f"\nPrune target: {label}")
    if dry_run:
        print("(dry-run — no file will be written)")
    print(f"Archive file: {path.resolve()}")

    if not skip_confirm and not dry_run:
        try:
            reply = input("\nProceed? [y/N] ").strip().lower()
        except EOFError:
            reply = ""
        if reply not in ("y", "yes"):
            print("Aborted.")
            return

    # Use bytes read/write to preserve the original line-ending convention
    # (CRLF on Windows-authored files, LF elsewhere). Path.read_text/write_text
    # normalizes newlines and would touch every line even when the substantive
    # change is a single cell.
    html_bytes = path.read_bytes()
    html = html_bytes.decode("utf-8")

    # Step 1
    print("\nStep 1: removing daily entry cards ...")
    html, cards_removed = snip_daily_cards(html)
    print(f"  {'removed' if cards_removed else 'nothing to remove'}"
          f" between INJECT_POINT and LAMPLINE.")

    # Step 2
    print(f"Step 2: adding link to archive table ...")
    html, action = add_archive_link(html, year, month)
    if action == "added":
        print(f"  added link to {abbr} {year} → {prefix}{yy}.html")
    elif action == "already-present":
        print(f"  link to {abbr} {year} already present — skipping.")
    elif action.startswith("other-link:"):
        other = action.split(":", 1)[1]
        other_name = other.rsplit("/", 1)[-1]
        print(f"  cell for {abbr} {year} already holds a different link "
              f"({other_name}) — leaving it alone. If you'd rather use "
              f"{prefix}{yy}.html, edit news2.html by hand.")
    else:
        print(f"  ✗ could not find slot for {abbr} {year} in archive table.")

    # Nothing changed?
    if not cards_removed and action != "added":
        print("\nNo changes to write.")
        return

    if dry_run:
        print("\nDry-run complete — no file written.")
        return

    # Backup and write
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"news2_backup_{stamp}_prune.html")
    shutil.copy2(path, backup)
    print(f"\nBackup: {backup.name}")
    path.write_bytes(html.encode("utf-8"))
    print(f"Wrote: {path.name}")

    print(f"\n✓ Done. Preview {path.name} in your browser before uploading.")

    # ---- Optional Step 3: refresh template.html for next month ----
    should_refresh = refresh_flag
    if not should_refresh and not no_refresh_flag:
        try:
            reply = input(
                f"\nAlso refresh template.html for next month? [y/N] "
            ).strip().lower()
            should_refresh = reply in ("y", "yes")
        except EOFError:
            should_refresh = False
    if should_refresh:
        source_args = ([Path(s) for s in ladder_source]
                       if ladder_source else None)
        refresh_template(year, month, Path.cwd(),
                         source_paths=source_args,
                         skip_confirm=skip_confirm,
                         dry_run=dry_run)


if __name__ == "__main__":
    main()
