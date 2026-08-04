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

    return year, month, args.dry_run, args.yes


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

    # Preserve any valign="top" attribute on the existing cell (used on
    # the last column of the last year for visual consistency).
    valign_match = re.search(r'valign="[^"]+"', target_cell_raw)
    valign_attr = " " + valign_match.group(0) if valign_match else ""

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
    year, month, dry_run, skip_confirm = _parse_args()
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


if __name__ == "__main__":
    main()
