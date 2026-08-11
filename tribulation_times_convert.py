#!/usr/bin/env python3
"""
tribulation_times_convert.py
============================
Converts a raw Tribulation Times news.html into a modernized,
email-safe, mobile-friendly news4.html — matching the hand-crafted
"revamped.html" layout exactly.

ALSO: prepends the new entry to the top of your modern news2.html
(the monthly archive), keeping it current automatically.

USAGE:
    python3 tribulation_times_convert.py

INPUT:
    news.html   — your raw daily update (same folder as this script)
    news2.html  — your modern monthly archive (same folder) [optional]

OUTPUT:
    news4.html  — modernized daily page, ready to upload as news.html
    news2.html  — updated in-place with the new entry prepended [optional]

REQUIREMENTS:
    Python 3.7+  |  pip install beautifulsoup4
"""

import re
import sys
import shutil
from pathlib import Path
from datetime import datetime

try:
    from bs4 import BeautifulSoup, NavigableString
except ImportError:
    print("\nERROR: BeautifulSoup4 is not installed.")
    print("Please run:  pip install beautifulsoup4\n")
    sys.exit(1)

# WINDOWS CONSOLE GUARD: this script prints Unicode marks (✓ ⚠ •). On a
# Windows console using the legacy cp1252 code page, print() would raise
# UnicodeEncodeError and kill the run partway through (after news4.html is
# written but possibly before the archive updates). Reconfigure stdout to
# UTF-8 with safe replacement so output never crashes the conversion.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════
# SETTINGS  —  edit these to match your site
# ══════════════════════════════════════════════════════════════════════════

INPUT_FILE   = "news.html"
OUTPUT_FILE  = "news4.html"
ARCHIVE_FILE = "news2.html"

AUTO_APPEND_TO_ARCHIVE = True   # Set False to skip touching news2.html
BACKUP_ARCHIVE         = True   # Set False to skip backup copies

COLORS = {
    "bg_dark":    "#3a2a10",
    "gold":       "#b8860b",
    "gold_light": "#d4a72c",
    "crimson":    "#7a1c1c",
    "parchment":  "#f8f4ec",
    "ink":        "#1a1208",
    "ink_mid":    "#3d2b0d",
    "rule":       "#c8b080",
    "link":       "#2e5c6e",
    "ladder_bg":  "#f0e8e8",
    "ladder_bdr": "#c8a0a0",
}

SUBSCRIBE_URL    = "http://groups.google.com/group/tribulaton-times/subscribe"
ARCHIVES_URL     = "http://www.tribtimes.com/news2.html"
LADDER_URL       = "http://www.catholicprophecy.info/ladder.html"
LOGO_SRC         = "catholicprophecy.jpg"
LINE_GIF         = "http://www.catholicprophecy.info/line.gif"
BIBLE_YEAR_URL   = "https://bibleinayearonline.com/may-oyb/?version=63&startmmdd=0101"
BIBLE_YEAR_LABEL = "May Readings"
GA_ACCOUNT       = "G-BDP3WZGYC4"

# Link destinations that should never become news items
SKIP_URL_FRAGMENTS = [
    "subscribe", "ladder.html", "news2.html", "news.html", "news4.html",
    "bibleinayear", "magisterium.com/widgets", "catholicprophecy.info/links",
    "catholicprophecy.info/index", "catholicprophecy.info/Catholic",
    "groups.google.com", "mailto:",
    "docsbot.ai",  # NOTE: x.com/twitter handled per-item (labeled links allowed)
]
# Marker placed in news2.html so the script knows where to insert new entries
INJECT_MARKER = "<!-- !!NEW_ENTRY_INJECT_POINT!! -->"

C = COLORS  # shorthand


# ══════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════

def clean(node):
    """Return stripped plain text of a tag or string."""
    if isinstance(node, str):
        return node.strip()
    return node.get_text(" ", strip=True)


def skip_url(url):
    if url.startswith("#"):
        return True
    return any(f in url for f in SKIP_URL_FRAGMENTS)


def is_domain_only(text):
    """True if text looks like a bare domain, e.g. MAGISTERIUM.COM"""
    return bool(re.match(r'^[A-Z0-9.\-]+\.(COM|ORG|NET|INFO|GOV|EDU)$', text.strip()))


# ══════════════════════════════════════════════════════════════════════════
# ENTRY EXTRACTION
# ══════════════════════════════════════════════════════════════════════════

def extract_entries(html):
    """Split raw HTML into dated entry blocks."""
    html = html.replace("\r\n", "\n").replace("\r", "\n")

    date_re = re.compile(
        r'(?:text-decoration:\s*underline[^>]*>|<u>)\s*'
        r'((?:January|February|March|April|May|June|July|August|'
        r'September|October|November|December)\s+\d{1,2},\s+\d{4})',
        re.IGNORECASE
    )
    matches = list(date_re.finditer(html))
    if not matches:
        # Fallback: bare dates
        date_re2 = re.compile(
            r'((?:January|February|March|April|May|June|July|August|'
            r'September|October|November|December)\s+\d{1,2},\s+\d{4})',
            re.IGNORECASE
        )
        matches = list(date_re2.finditer(html))

    entries = []
    for i, m in enumerate(matches):
        date_str = " ".join(m.group(1).split())
        start    = m.start()
        end      = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        block    = html[start:end]

        # Subtitle on the same line (e.g. DIVINE MERCY SUNDAY)
        subtitle = ""
        sub_m = re.search(r'text-decoration:\s*underline[^>]*>([^<]{5,60})</span>', block)
        if sub_m:
            cand = " ".join(sub_m.group(1).split())
            if cand != date_str and not re.match(r'\d', cand):
                subtitle = cand

        # Feast-day invocation on the date line, e.g.
        #   <small><span style="font-weight: bold; font-style: italic;">
        #     <a href="...">OUR LADY OF MOUNT CARMEL</a>, PRAY FOR US!</span></small>
        # Captured for inline rendering next to the date heading, and STRIPPED
        # from the block so it can't be mistaken for a news item / source label.
        feast = None
        fm = re.search(r'<small>\s*<span([^>]*)>(.*?)</span>\s*</small>',
                       block[:1500], re.IGNORECASE | re.DOTALL)
        if fm and "bold" in fm.group(1).lower() and "italic" in fm.group(1).lower():
            inner = fm.group(2)
            plain = " ".join(re.sub(r"<[^>]+>", " ", inner).split()).strip()
            if plain and len(plain) <= 120:
                am = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                               inner, re.IGNORECASE | re.DOTALL)
                if am:
                    l_url  = am.group(1).strip()
                    l_text = " ".join(re.sub(r"<[^>]+>", " ", am.group(2)).split())
                    tail   = " ".join(re.sub(
                        r"<[^>]+>", " ",
                        inner[:am.start()] + " " + inner[am.end():]).split()).strip()
                    feast = {"url": l_url, "link_text": l_text, "tail": tail}
                else:
                    feast = {"url": "", "link_text": plain, "tail": ""}
                block = block.replace(fm.group(0), "", 1)

        entries.append({"date": date_str, "subtitle": subtitle,
                        "feast": feast, "block": block})

    return entries


def get_scripture(block):
    """Return (reference, verse_text) for the opening scripture, or ('','').

    Combines consecutive verses (e.g. Rev 11:19 + Rev 12:1) into one block:
    the first verse's reference is returned separately (h_scripture renders it as
    the leading label) and any further verses are appended inline with their own
    references and <br> separators.
    """
    start_m = re.search(
        r'font-style:\s*italic[^>]*>\s*'
        r'\(\s*(?:[1-3]\s*)?[A-Za-z][A-Za-z]{0,5}\.?\s+\d+:\d+',
        block
    )
    if not start_m:
        # Fallback: the epigraph isn't always italicized (the raw HTML is
        # hand-edited and this styling sometimes gets dropped). Accept a
        # bare "(Book Ch:V)" match only if it occurs before the first REAL
        # (non-empty) bold source label in the block -- i.e. it's still
        # positioned as the lead-in epigraph, not a scripture citation
        # quoted inside a later news item's body (which always follows
        # that first label).
        bare_m = re.search(
            r'\(\s*(?:[1-3]\s*)?[A-Za-z][A-Za-z]{0,5}\.?\s+\d+:\d+',
            block
        )
        if bare_m:
            _label_pos = len(block)
            for _lm in re.finditer(r'font-weight:\s*bold[^"]*"[^>]*>([^<]*)', block):
                if _lm.group(1).strip():
                    _label_pos = _lm.start()
                    break
            if bare_m.start() < _label_pos:
                start_m = bare_m
    if not start_m:
        return "", ""
    start = start_m.start()
    # Scripture ends at the first bold source label / quote that follows it.
    end_m = re.search(r'font-weight:\s*bold', block[start:])
    if end_m:
        end = start + end_m.start()
        lt = block.rfind('<', start, end)   # cut at the tag boundary, not mid-tag
        if lt != -1:
            end = lt
    else:
        end = len(block)
    region = block[start:end]
    txt = re.sub(r'<[^>]+>', ' ', region)
    txt = re.sub(r'[\s\u00a0]+', ' ', txt).strip()

    ref_re = re.compile(
        r'\(\s*(?:[1-3]\s*)?[A-Za-z][A-Za-z]{0,5}\.?\s+\d+:\d+[\d:,\-\s]*\)'
    )
    matches = list(ref_re.finditer(txt))
    verses = []
    for i, mm in enumerate(matches):
        ref = mm.group(0).strip("() ").strip()
        b0 = mm.end()
        b1 = matches[i + 1].start() if i + 1 < len(matches) else len(txt)
        body = txt[b0:b1].strip()
        if body:
            verses.append((ref, body))

    if not verses:
        ref_m = re.match(r'\(([^)]+)\)\s*(.+)$', txt, re.DOTALL)
        if ref_m:
            return ref_m.group(1).strip(), ref_m.group(2).strip()
        return ("", txt) if txt else ("", "")

    first_ref, first_body = verses[0]
    if len(verses) == 1:
        return first_ref, first_body
    rest = "".join(f'<br>({r})&nbsp; {b}' for r, b in verses[1:])
    return first_ref, first_body + rest


# Honorific titles that mark an attributed pull-quote (e.g. "POPE LEO XIV: ...").
# A label containing any of these, followed by quoted text, is rendered as a
# parchment pull-quote rather than a plain news item. Order/spacing matters for
# multi-word titles so "POPE" still matches "POPE LEO XIV".
QUOTE_TITLES = (
    "POPE", "SAINT", "ST.", "BLESSED", "VENERABLE", "SERVANT OF GOD",
    "CARDINAL", "CARD.", "ARCHBISHOP", "BISHOP", "FATHER", "FR.", "MONSIGNOR", "MSGR.",
    "SISTER", "MOTHER", "DEACON", "ABBOT", "POPE EMERITUS",
)


def _is_quote_label(label_upper):
    # "CHURCH FATHERS" is a source name (like a publication), not an
    # individual honorific -- it must not match "FATHER" and get boxed like
    # a Pope/Saint/Cardinal pull-quote. The grey box is reserved for those
    # individually-attributed quotes (and the Ladder excerpt), never for it.
    if "CHURCH FATHERS" in label_upper:
        return False
    return any(w in label_upper for w in QUOTE_TITLES)


def get_collect(block):
    """Return (label, url, text) for a COLLECT-style prayer/quote block, or ('','','').
    Handles two patterns:
    1. <small><span bold><a href="skip_url">LABEL</a>: prayer text</span></small>
       (tweet-linked collects, e.g. x.com/Pontifex)
    2. <small><span bold><a href="any">POPE/SAINT NAME</a>: "quoted text"...</span></small>
       (papal/saint quotes with a full URL, e.g. vatican.va link)
    """
    soup = BeautifulSoup(block, "html.parser")
    for sm in soup.find_all("small"):
        # Find the <a> tag directly — there may be multiple bold spans,
        # the first of which can be empty
        a = sm.find("a", href=True)
        if not a:
            continue
        # The <a> must be inside a bold span
        span = a.find_parent("span", style=lambda s: s and "font-weight" in (s or ""))
        if not span:
            continue
        href = a.get("href", "")
        label = a.get_text(strip=True)
        # A leading label word before the link inside the same bold span
        # (e.g. <span>EXCERPT<a>HOMILY CARD. JOSEPH RATZINGER</a></span>)
        # belongs on the label, not the quote body.
        prefix_parts = []
        for sib in span.contents:
            if sib is a:
                break
            if isinstance(sib, NavigableString):
                t = str(sib).strip()
                if t:
                    prefix_parts.append(t)
        if prefix_parts:
            label = " ".join(prefix_parts + [label])
        if not label or len(label) > 40:
            continue
        # Pattern 1: skip_url href (tweet-linked collect)
        is_collect_url = skip_url(href)
        # Pattern 2: label contains POPE or SAINT (papal/saint quote)
        label_upper = label.upper()
        is_papal_quote = _is_quote_label(label_upper)
        if not is_collect_url and not is_papal_quote:
            continue
        # Collect the text after the link within the span
        # Stop when we hit text that looks like a source label (ALL CAPS, no quotes, short)
        parts = []
        for child in span.children:
            if child is a:
                continue
            if isinstance(child, NavigableString):
                t = str(child).strip(" :\n\xa0")
                if not t:
                    continue
                # Stop at source label text: short, no quote chars, ALL CAPS words
                # (may contain digits like "2026 ANNUAL REPORT")
                t_norm = " ".join(t.split())
                words = t_norm.split()
                all_caps_words = all(w == w.upper() and (w.isalpha() or w.isdigit()) for w in words if w)
                if (t_norm and all_caps_words and len(t_norm) <= 40
                        and '"' not in t_norm and '\u201c' not in t_norm):
                    break
                parts.append(t)
            elif hasattr(child, "get_text"):
                t = child.get_text(" ", strip=True).strip(" :\n\xa0")
                if not t:
                    continue
                t_norm = " ".join(t.split())
                words = t_norm.split()
                all_caps_words = all(w == w.upper() and (w.isalpha() or w.isdigit()) for w in words if w)
                if (t_norm and all_caps_words and len(t_norm) <= 40
                        and '"' not in t_norm and '\u201c' not in t_norm):
                    break
                parts.append(t)
        text = " ".join(parts).strip()
        if not text:
            # Some raw HTML shapes put the label and the quote body in two
            # sibling <span> elements within the same <small> instead of one
            # shared span (e.g. <small><span>EXCERPT<a>Title</a></span>
            # <span>body text...</span></small>) -- fall back to the label
            # span's siblings within <small> so the body isn't lost.
            for sib in span.next_siblings:
                if isinstance(sib, NavigableString):
                    t = str(sib).strip(" :\n\xa0")
                    if t:
                        parts.append(t)
                elif hasattr(sib, "get_text"):
                    t = sib.get_text(" ", strip=True).strip(" :\n\xa0")
                    if t:
                        parts.append(t)
            text = " ".join(parts).strip()
        if len(text) > 20:
            # Honorific pull-quotes (BISHOP/CARDINAL/POPE...) must actually quote
            # something — guards against a normal "BISHOP: Headline" link being
            # mistaken for a quote. Tweet-linked collects are exempt (no quote marks).
            if is_papal_quote and not is_collect_url:
                if not ('"' in text or '\u201c' in text or '\u201d' in text):
                    continue
            return label, href, text
    return "", "", ""


def get_social_report(block):
    """Return (label, url, text) for an X/Twitter self-labeling bold report
    block, or ('','','').

    These are secular news posts where the bold label is itself the link to an
    x.com / twitter.com post, followed by a report body. They are not
    Church-figure quotes, so they never match the honorific pull-quote path —
    but the author still wants them set apart (small + bold) like a quote.
    Two hand-authored shapes occur:

      A) <small><span bold><a href="x.com">LABEL</a>: body ...</span></small>
         (link INSIDE the bold span; body trails inside the span)
      B) <a href="x.com"><small><span bold>LABEL</span></small></a>: body ... <br>
         (link WRAPS the bold label; body trails after </a> up to the next <br>,
          and may itself contain an inline link, e.g. a photo)

    Any inline link inside the body is preserved. Returns ('','','',False) if none.
    """
    soup = BeautifulSoup(block, "html.parser")

    def _norm(s):
        return re.sub(r'[\s\u00a0]+', ' ', s)

    # ---- Structure A: <a> inside the bold span -------------------------------
    for sm in soup.find_all("small"):
        a = sm.find("a", href=True)
        if not a:
            continue
        span = a.find_parent("span", style=lambda s: s and "font-weight" in (s or ""))
        if not span:
            continue
        href = a.get("href", "")
        if not ("x.com/" in href or "twitter.com/" in href):
            continue
        label = a.get_text(strip=True)
        if not label or len(label) > 40:
            continue
        if _is_quote_label(label.upper()):      # Church-figure quote -> get_collect
            continue
        parts = []
        for child in span.children:
            if child is a:
                continue
            if isinstance(child, NavigableString):
                t = str(child).strip(" :\n\xa0")
            elif hasattr(child, "get_text"):
                t = child.get_text(" ", strip=True).strip(" :\n\xa0")
            else:
                t = ""
            if t:
                parts.append(t)
        text = _norm(" ".join(parts)).strip()
        if len(text) > 20:
            return label, href, text, True      # body inside bold span -> bold

    # ---- Structure B: <a> wraps the bold label; body follows after </a> ------
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not ("x.com/" in href or "twitter.com/" in href):
            continue
        # Must WRAP a bold/small label (and not itself sit inside a bold span,
        # which is Structure A handled above).
        if a.find_parent("span", style=lambda s: s and "font-weight" in (s or "")):
            continue
        has_label = (a.find("span", style=lambda s: s and "font-weight" in (s or ""))
                     or a.find("small") or a.find("b"))
        if not has_label:
            continue
        label = a.get_text(" ", strip=True)
        if not label or len(label) > 40:
            continue
        if _is_quote_label(label.upper()):
            continue
        # Body = siblings after </a>, up to the first <br>. Inline links kept.
        parts, node, steps = [], a.next_sibling, 0
        while node is not None and steps < 80:
            steps += 1
            nm = getattr(node, "name", None)
            if nm == "br":
                break
            if isinstance(node, NavigableString):
                parts.append(_norm(str(node)))
            elif nm == "a" and node.get("href"):
                parts.append(str(node))            # preserve inline link verbatim
            elif hasattr(node, "get_text"):
                parts.append(_norm(node.get_text(" ", strip=True)))
            node = node.next_sibling
        text = "".join(parts).strip()
        text = text.lstrip(":").strip()
        if len(re.sub(r'<[^>]+>', '', text)) > 20:
            return label, href, text, False     # only the label is bold -> plain body

    return "", "", "", False


def get_pull_quote(block):
    """Return (text, attribution) for a #f0ecd8 background pull-quote, or ('','')."""
    m = re.search(
        r'background-color:#f0ecd8[^>]*>(.+?)(?:</blockquote>|</div>)',
        block, re.DOTALL
    )
    if not m:
        return "", ""
    inner = m.group(1)
    attr_m = re.search(r'[—\-]\s*<strong>(.+?)</strong>', inner, re.DOTALL)
    attr = clean(BeautifulSoup(attr_m.group(1), "html.parser")) if attr_m else ""
    text = re.sub(r'<[^>]+>', ' ', inner)
    text = re.sub(r'\s+', ' ', text).strip()
    if attr:
        text = re.split(r'\s*[—\-]\s*' + re.escape(attr), text)[0].strip()
    return text, attr


def _clean_ladder_text(raw):
    """Strip tags to spaces, collapse whitespace, and drop any space that
    ends up sitting before punctuation — the source often splits the excerpt
    across several adjacent <font> tags (e.g. "...winds</font><font></font>
    <font>.</font>"), and replacing each tag with a space leaves a stray
    space before the trailing period once whitespace is collapsed."""
    text = re.sub(r'<[^>]+>', ' ', raw)
    text = re.sub(r'\s+', ' ', text).strip()
    return re.sub(r'\s+([,.;:!?])', r'\1', text)


def get_ladder(block):
    """Return the Ladder of Divine Ascent numbered excerpt."""
    # Primary: numbered sentence AFTER the "Ladder of Divine Ascent excerpt: Step N - ..."
    # anchor. Works for any Step (previously anchored to "Joy-Making Mourning",
    # which was the Step 7 title and broke on every other week).
    # "Ladder of Divine Ascent" is matched with \s+ (not literal spaces)
    # because the source sometimes wraps the anchor's own text across lines
    # (e.g. "Ladder of\n        Divine\n        Ascent"), which would
    # otherwise fail this primary pattern and silently drop to the looser
    # fallback below.
    # The end boundary intentionally excludes </font>: the source often
    # splits the excerpt's trailing punctuation into its own near-empty
    # <font>.</font> sibling, and stopping at the first </font> would cut
    # the sentence off before that final period.
    m = re.search(
        r'Ladder\s+of\s+Divine\s+Ascent[^<]*(?:<[^>]+>\s*)*'
        r'(?:excerpt|Excerpt)[^<]*(?:<[^>]+>\s*)*'
        r'(?:Step\s*\d+[^<]*)?(?:<[^>]+>\s*)*'
        r'([0-9]+\.\s+.+?)(?:<br|</p>|</div>|<hr|$)',
        block, re.DOTALL
    )
    if m:
        return _clean_ladder_text(m.group(1))
    # Fallback: find any numbered sentence near end of block
    sentences = re.findall(r'[0-9]+\.\s+[A-Z][^.]+\.', block)
    if sentences:
        return _clean_ladder_text(sentences[-1])
    return ""


def get_ladder_step(block):
    """Extract the current week's Ladder Step header — number and title.
    Returns (step_num, step_title) or (None, None). Reads the source line
    "Ladder of Divine Ascent excerpt: Step 8- \"On Freedom from Anger and
    on Meekness\"", which changes weekly."""
    # Strip tags and collapse whitespace first — the anchor text may be
    # broken across lines with <br>/</a> in the middle, and the title may
    # wrap mid-word. Working on flat text simplifies both.
    plain = re.sub(r'<[^>]+>', ' ', block)
    plain = re.sub(r'\s+', ' ', plain).strip()
    m = re.search(
        r'Ladder of Divine Ascent\s+excerpt:\s*Step\s*(\d+)\s*[-\u2013\u2014]\s*'
        r'["\u201c]([^"\u201d]{3,120})["\u201d]',
        plain
    )
    if not m:
        return (None, None)
    step_num = m.group(1).strip()
    step_title = " ".join(m.group(2).split()).strip()
    return (step_num, step_title)


def _preceding_section_heading(small_tag):
    """If `small_tag` (a source-label <small>, e.g. "VIA") is immediately
    preceded — skipping only whitespace/<br> — by another bare <small>
    heading with its own bold text and no link of its own (e.g. a
    standalone "FROM THE MAILBAG" line ahead of a "VIA <name>" byline),
    return that heading text. Otherwise ''. Lets a compound label like
    "FROM THE MAILBAG — VIA" be built instead of silently losing the
    section heading, which sits outside the label small itself.

    `small_tag` itself is often the very first child of an enclosing
    <span> wrapper (e.g. "<span><small>VIA</small> <a>...</a>...</span>"),
    in which case its own previous_sibling is None even though a heading
    precedes the whole span — so when that's the case, climb out to the
    wrapper and check ITS previous sibling chain too.
    """
    def _scan(start):
        prev = start
        steps = 0
        while prev is not None and steps < 4:
            steps += 1
            if isinstance(prev, NavigableString):
                if str(prev).strip():
                    return None
                prev = prev.previous_sibling
                continue
            if getattr(prev, "name", None) == "br":
                prev = prev.previous_sibling
                continue
            if getattr(prev, "name", None) == "small":
                if prev.find("a", href=True) is not None:
                    return None
                t = " ".join(prev.get_text(" ", strip=True).strip(" :").split())
                letters = "".join(ch for ch in t if ch.isalpha())
                if t and letters and len(t) <= 40 and letters == letters.upper():
                    return t
                return None
            return None
        return None

    heading = _scan(small_tag.previous_sibling)
    if heading is None and small_tag.previous_sibling is None:
        parent = small_tag.parent
        if parent is not None and parent.name in ("span", "font", "b"):
            heading = _scan(parent.previous_sibling)
    return heading or ""


def get_source_for_link(link):
    """
    Extract the source label for a news link using pattern-aware logic.

    Handles two patterns found in Tribulation Times raw HTML:

    Pattern A — label and link are INSIDE the same <small> tag:
      <small><span style="font-weight:bold;">PAULINE.ORG: </span>
             <big><a href="...">Title</a></big></small>

    Pattern B — label is in a standalone <small> tag, link is a sibling:
      <small><span style="font-weight:bold;">DICASTERY...</span></small>:
      <a href="...">Title</a>
    """
    # Pattern A: link is inside <small>
    small_parent = link.find_parent("small")
    if small_parent:
        # Source = text of the LAST <span>/<b> before the link (reset on intermediate links)
        for child in small_parent.children:
            # Stop when we reach the child that contains the link
            if hasattr(child, "find") and child.find("a") == link:
                break
            if child is link:
                break
            # If another link appears, reset — its preceding label isn't ours
            if hasattr(child, "name") and child.name == "a" and child is not link:
                _last_source = None
                continue
            if hasattr(child, "name") and child.name in ("span", "b"):
                t = child.get_text(" ", strip=True).strip(" :")
                if t and len(t) > 2:
                    _last_source = t
        if "_last_source" in dir() and _last_source and len(_last_source) > 2:
            return _last_source
        # Fallback: collect bold/span text that appears BEFORE the link in document order
        # Reset if another <a> link is encountered first (means we've passed a prior item)
        pre_text_parts = []
        _skip_a = None  # track an <a> tag whose children to skip
        for child in small_parent.descendants:
            if child is link:
                break
            if hasattr(child, 'name') and child.name == 'a' and child is not link:
                # Another link precedes ours — its source label is not ours
                pre_text_parts = []
                _skip_a = child  # skip this link's text children
                continue
            if isinstance(child, NavigableString):
                # Skip text that belongs to a prior <a> tag (check full ancestor chain)
                if _skip_a is not None:
                    p = child.parent
                    in_skip = False
                    while p and p is not small_parent:
                        if p is _skip_a:
                            in_skip = True
                            break
                        p = p.parent
                    if in_skip:
                        continue
                t = str(child).strip(" :\n\xa0")
                if t and len(t) > 1:
                    pre_text_parts.append(t)
        source = " ".join(pre_text_parts).strip(" :()")
        # Strip any inner link text (non-main links inside the small)
        for inner_a in small_parent.find_all("a"):
            if inner_a is not link:
                source = source.replace(inner_a.get_text(strip=True), "").strip(" :()")
        source = re.sub(r'\(\s*\)', '', source).strip(" :()")
        if source and len(source) > 2:
            return source

    # Pattern B: link is NOT inside <small> — walk backward through siblings
    prev = link.previous_sibling
    # Also walk up one level if link is inside <big>
    container = link.parent
    if container and container.name == "big":
        prev = container.previous_sibling

    for _ in range(8):
        if prev is None:
            break
        if isinstance(prev, NavigableString):
            # Usually just ": " — but may be a bare-text label like
            # "RELATED (X): " directly preceding the link.
            _pt = " ".join(str(prev).split()).strip(" :\xa0")
            if _pt:
                _pletters = "".join(ch for ch in _pt if ch.isalpha())
                if (_pletters and len(_pt) <= 40
                        and _pletters == _pletters.upper()
                        and not _pt.startswith("(")
                        and '"' not in _pt and '\u201c' not in _pt):
                    return _pt
                if len(_pt) > 30:
                    break  # substantial body text precedes — no label
        elif hasattr(prev, "name"):
            if prev.name == "small":
                # First check: is there a TRAILING bold span in this <small>?
                # This handles: <small>...NOTRE DAME...<span>VATICAN.VA:</span></small>
                spans = list(prev.find_all(["span", "b"]))
                if spans:
                    last_span = spans[-1]
                    t = last_span.get_text(" ", strip=True).strip(" :\n\xa0")
                    # Strip embedded link text (e.g. MAGISTERIUM.COM inside the span)
                    for inner_a in last_span.find_all("a"):
                        t = t.replace(inner_a.get_text(), "").strip(" :()")
                    # Clean remaining bracket fragments: "( )" -> ""
                    t = re.sub(r'\(\s*\)', '', t).strip(" :()")
                    # Reject if too long (> 80 chars) or contains quotes — it's content, not a label
                    if (t and len(t) > 2 and not t.startswith("(")
                            and len(t) <= 160 and '"' not in t and '“' not in t):
                        _heading = _preceding_section_heading(prev)
                        return f"{_heading} — {t}" if _heading else t
                    # If span too long, scan its trailing children for a short ALL-CAPS label
                    for _child in reversed(list(last_span.children)):
                        if isinstance(_child, NavigableString):
                            _ct = str(_child).strip(" :\n\xa0")
                            _ct_norm = " ".join(_ct.split())
                            _ct_words = _ct_norm.split()
                            _all_caps = all(w == w.upper() and (w.isalpha() or w.isdigit())
                                           for w in _ct_words if w)
                            if (_ct_norm and _all_caps and len(_ct_norm) <= 40
                                    and '"' not in _ct_norm):
                                return _ct_norm
                            elif _ct_norm:
                                break
                # Fallback: check NavigableString children for a short label
                # (handles case where label text like "2026 ANNUAL REPORT" follows
                # a long quoted span inside the same <small>)
                for _ns in prev.children:
                    if isinstance(_ns, NavigableString):
                        _ns_t = str(_ns).strip(" :\n\xa0")
                        _ns_norm = " ".join(_ns_t.split())
                        _ns_words = _ns_norm.split()
                        _all_caps = all(w == w.upper() and (w.isalpha() or w.isdigit())
                                       for w in _ns_words if w)
                        if (_ns_norm and _all_caps and len(_ns_norm) <= 40
                                and '"' not in _ns_norm):
                            return _ns_norm
                # Final fallback: whole <small> text minus embedded link text
                t = prev.get_text(" ", strip=True).strip(" :")
                for inner_a in prev.find_all("a"):
                    t = t.replace(inner_a.get_text(), "").strip(" :()")
                t = re.sub(r'\(\s*\)', '', t).strip(" :()")
                # Reject if too long or contains quotes
                if (t and len(t) > 2 and len(t) <= 160
                        and '"' not in t and '\u201c' not in t):
                    return t
            elif prev.name in ("span", "b"):
                # A <span> that itself just wraps a <small> label (e.g.
                # <span><small><span bold>X</span></small>: </span><a>...)
                # — pull the label out of that nested <small> first, with
                # the same short ALL-CAPS fallback the `small` branch above
                # uses. Needed for single-letter/short labels like "X"
                # (this site's marker for an X/Twitter item): the generic
                # len(t) > 2 check below would otherwise silently reject them.
                _nested_small = prev.find("small")
                if _nested_small is not None:
                    _ns_norm = " ".join(
                        _nested_small.get_text(" ", strip=True).strip(" :\n\xa0").split())
                    _ns_all_caps = bool(_ns_norm) and all(
                        w == w.upper() and (w.isalpha() or w.isdigit())
                        for w in _ns_norm.split())
                    if (_ns_norm and _ns_all_caps and len(_ns_norm) <= 40
                            and '"' not in _ns_norm):
                        return _ns_norm
                t = prev.get_text(" ", strip=True).strip(" :")
                # Reject if too long or contains quotes — it's content, not a label
                if (t and len(t) > 2 and not t.startswith("(")
                        and len(t) <= 160 and '"' not in t and '“' not in t):
                    return t
        prev = getattr(prev, "previous_sibling", None)

    return ""


def _li_html(li, link_color):
    """Serialize a <li>'s content to HTML text, preserving any inner
    <a href> as a real clickable link instead of flattening it away via
    get_text(). Needed for feature/bullet lists whose items are themselves
    headline links (e.g. a "RELATED NEWS REPORTS" list of article titles)
    rather than plain summary text."""
    def _walk(node):
        if isinstance(node, NavigableString):
            return str(node)
        if not hasattr(node, "name"):
            return ""
        if node.name == "a":
            href = (node.get("href") or "").strip()
            text = node.get_text(strip=False)
            if href and text and not skip_url(href):
                return (f'<a href="{href}" target="_blank" '
                        f'style="color:{link_color};text-decoration:none;">'
                        f'{text}</a>')
            return node.get_text(strip=False)
        if node.name == "br":
            return " "
        return "".join(_walk(c) for c in node.children)
    return " ".join("".join(_walk(c) for c in li.children).split()).strip()


def get_following_features(link, soup, doc_order=None, inline_ids=None):
    """
    Collect <ul> or <ol> list items that follow a link.
    Uses document-position logic: finds every <ul>/<ol> in the block,
    then determines which link immediately precedes each list by finding
    the last <a> tag before the list in document order.
    Only returns items if THIS link is that immediately preceding link.

    inline_ids (if given) excludes inline-continuation anchors — the same
    ones get_news_items skips over — from ownership consideration, so a
    list's ownership resolves to the CLUSTER PRIMARY (the anchor that
    actually becomes its own item) rather than to an inline member that
    never surfaces as its own item and would otherwise strand the list
    with no owner at all.
    """
    inline_ids = inline_ids or set()
    feature_items = []
    _owner_href = (link.get("href") or "").strip()

    # Level 1: direct siblings of the link (simple case)
    nxt = link.next_sibling
    for _ in range(8):
        if nxt is None:
            break
        if hasattr(nxt, "name"):
            if nxt.name in ("ul", "ol"):
                for li in nxt.find_all("li"):
                    lt = _li_html(li, C["link"])
                    if lt:
                        feature_items.append(lt)
                return feature_items
            elif nxt.name == "small":
                break
        nxt = getattr(nxt, "next_sibling", None)

    # Level 2: check every <ul>/<ol> in the block to see if THIS link
    # is the last <a> before it in document order.
    # Exclude <li> links — they sit inside lists and would steal ownership
    # of subsequent sibling lists.
    all_links = [a for a in soup.find_all("a", href=True)
                 if not a.find_parent("li") and id(a) not in inline_ids]
    post_list_text = []  # text that appears AFTER the last list

    # Document-order index: one tree traversal instead of serializing the
    # whole block and substring-searching for every link/list pair (which was
    # quadratic in document size, and — because two identical <a> tags
    # compare equal in BeautifulSoup and str.find returns the FIRST
    # occurrence — could let a duplicated link steal ownership of a list).
    # Identity comparison ("is") makes ownership unambiguous.
    if doc_order is None:
        doc_order = {id(el): i for i, el in enumerate(soup.descendants)}

    # Find all lists that belong to this link (this link is the last <a> before them)
    owned_lists = []
    for list_tag in soup.find_all(["ul", "ol"]):
        l_idx = doc_order.get(id(list_tag), -1)
        last_link_before, best = None, -1
        for a in all_links:
            a_idx = doc_order.get(id(a), -1)
            if 0 <= a_idx < l_idx and a_idx > best:
                best, last_link_before = a_idx, a
        if last_link_before is link:
            owned_lists.append(list_tag)

    # Add a section separator between lists from different subheadings
    existing_labels = set()
    for idx_list, list_tag in enumerate(owned_lists):
        # Check for a <small> subheading before this list
        # It could be a direct sibling OR inside a <span> sibling
        # Walk back further to skip over other lists
        prev = list_tag.previous_sibling
        label_found = None
        for _ in range(10):
            if prev is None: break
            if hasattr(prev, "name"):
                if prev.name == "small":
                    # Get the LAST bold/italic span text inside — that's the label
                    spans = prev.find_all(["span", "b"])
                    label_text = ""
                    for sp in reversed(spans):
                        t = sp.get_text(" ", strip=True)
                        if t and len(t) > 1:
                            label_text = t
                            break
                    if not label_text:
                        label_text = prev.get_text(" ", strip=True)
                    label_found = label_text
                    break
                elif prev.name == "p":
                    # <p><small>LABEL</small></p> pattern
                    sm = prev.find("small")
                    if sm and not prev.find("a"):
                        label_found = sm.get_text(" ", strip=True)
                    # Whether or not this <p> matched, it's the paragraph
                    # immediately before the list — stop here either way.
                    # Skipping past it (e.g. because it has both a <small>
                    # AND its own link, like a citation paragraph) would let
                    # the search walk arbitrarily far back and misattribute
                    # some unrelated earlier heading as this list's label.
                    break
                elif prev.name in ("ul", "ol"):
                    break  # a different list's territory — stop, no label
                elif prev.name == "span":
                    # Look for the LAST <small> inside the span
                    smalls = prev.find_all("small")
                    if smalls:
                        last_sm = smalls[-1]
                        spans2 = last_sm.find_all(["span", "b"])
                        label_text = ""
                        for sp in reversed(spans2):
                            t = sp.get_text(" ", strip=True)
                            if t and len(t) > 1:
                                label_text = t
                                break
                        if not label_text:
                            label_text = last_sm.get_text(" ", strip=True)
                        if label_text:
                            label_found = label_text
                            break
                elif prev.name == "br": pass
                # Don't break on other <ul> — keep walking back
            prev = getattr(prev, "previous_sibling", None)
        if label_found:
            # The source often line-wraps a label's text across several
            # lines (e.g. "Key\nPredictions on Timelines..."); get_text()
            # preserves those raw newlines since they sit inside a single
            # text node with nothing to insert a separator between —
            # collapse them to single spaces before use.
            label_found = " ".join(label_found.split())
        if label_found and label_found not in existing_labels:
            existing_labels.add(label_found)
            feature_items.append(f"__LABEL__{label_found}")
        for li in list_tag.find_all("li"):
            lt = _li_html(li, C["link"])
            if lt:
                feature_items.append(lt)

    # Collect text after the LAST owned list. An article can continue for
    # SEVERAL more paragraphs after its bulleted list — some plain body
    # paragraphs, some bold-italic subheadings, some paragraphs with only a
    # bare/parenthetical citation link — before the next genuinely new,
    # separately-labeled news item begins (or the entry ends). Sweep through
    # all of them instead of stopping at the first one, so a bold-italic
    # subheading like "Overall Framing" doesn't silently truncate the rest
    # of the article.
    def _p_starts_new_item(p_tag):
        """True if this <p> looks like a genuinely new labeled news item
        (a <small> source label together with a link) rather than prose
        that merely continues with a bare/parenthetical citation link."""
        return p_tag.find("a", href=True) is not None and p_tag.find("small") is not None

    if owned_lists:
        last_list = owned_lists[-1]
        nxt = last_list.next_sibling
        STOP = ("Ladder of Divine Ascent", "Prayer request",
                "Have ANY Catholic Question", "This month")
        for _ in range(40):
            if nxt is None: break
            if isinstance(nxt, NavigableString):
                t = " ".join(str(nxt).split()).strip()
                if t and len(t) > 10 and not any(s in t for s in STOP):
                    post_list_text.append(t)
            elif hasattr(nxt, "name"):
                if nxt.name in ("span", "font"):
                    if nxt.name == "span" and _span_precedes_new_item(nxt, _owner_href):
                        break  # next item's own label+link — stop, don't flatten it here
                    t = " ".join(nxt.get_text(" ", strip=True).split())
                    if any(s in t for s in STOP):
                        break
                    if t and len(t) > 10:
                        post_list_text.append(t)
                elif nxt.name == "p":
                    if _p_starts_new_item(nxt):
                        break  # a genuine new labeled item — stop
                    t = " ".join(nxt.get_text(" ", strip=True).split())
                    if any(s in t for s in STOP):
                        break
                    sm = nxt.find("small")
                    if sm and not nxt.find("a", href=True) and t and len(t) <= 100:
                        # Bold-italic (sub)heading paragraph with no body
                        # text of its own — render as a section label and
                        # keep sweeping past it rather than stopping.
                        post_list_text.append("__LABEL__" + t)
                    elif nxt.find("a", href=True):
                        # Preserve any bare/parenthetical citation link(s)
                        # as clickable text instead of flattening them away.
                        post_list_text.append(_li_html(nxt, C["link"]))
                    elif t and len(t) > 10:
                        # Split on internal <br><br> so a bold-italic
                        # subheading or an indented block-quote embedded
                        # mid-paragraph keeps its own styling/indent instead
                        # of being flattened by the get_text() above.
                        for _frag in _p_subheading_fragments(nxt, label_marker="__LABEL__"):
                            post_list_text.append(_frag)
                elif nxt.name in ("ul", "ol"):
                    break  # a list not owned by this link — stop
                elif nxt.name not in ("br", "small"):
                    break
            nxt = getattr(nxt, "next_sibling", None)

    # Store post-list text so h_news can render it after the bullets —
    # attached to feature_items via sentinel markers, one per fragment (a
    # fragment may itself carry an inner __LABEL__ prefix for a subheading).
    for _t in post_list_text:
        feature_items.append("__POST_LIST__" + _t)

    return feature_items


def _looks_like_new_item_anchor(a, current_url=""):
    """True if this <a> looks like the start of a distinct new item — it
    carries (or is itself) a source label — rather than an inline
    continuation link embedded in the current item's own flowing prose
    (e.g. a hyperlinked word near the end of a sentence, such as the
    "found here in English and here in Spanish" citation links). Used by
    get_following_excerpts to decide whether to stop excerpt collection at
    a bare <a> tag or absorb it as part of the ongoing paragraph.

    Deliberately stricter than get_source_for_link(): that function is
    tuned to find a plausible label for a link already known to head its
    own item, so a loose match is harmless there. Here a loose match would
    misclassify an innocuous run of prose (e.g. "and here in") right
    before an inline citation link as a source label, so a candidate only
    counts if it's short and ALL-CAPS (this document's actual label shape)
    or sits inside a <small> tag.
    """
    href = (a.get("href") or "").strip()
    if not href or skip_url(href):
        return False
    if current_url and href == current_url:
        return False
    text = a.get_text(strip=True)
    if not text:
        return False
    # Self-labeling ALL-CAPS link: its own text IS a short source label
    _t = text.rstrip(":").strip()
    if (_t and len(_t) <= 40 and _t.upper() == _t
            and any(ch.isalpha() for ch in _t)
            and all(ch.isalpha() or ch in " .'-" for ch in _t)):
        return True
    # Link itself sits inside a <small> — this document's standard
    # label+link container (Pattern A in get_source_for_link).
    if a.find_parent("small") is not None:
        return True

    def _is_caps_label(s):
        _s = " ".join(s.split()).strip(" :\xa0")
        letters = "".join(ch for ch in _s if ch.isalpha())
        return bool(_s and letters and len(_s) <= 40 and letters == letters.upper()
                    and '"' not in _s and '“' not in _s)

    prev = a.previous_sibling
    container = a.parent
    if container and container.name == "big":
        prev = container.previous_sibling
    for _ in range(4):
        if prev is None:
            break
        if isinstance(prev, NavigableString):
            _pt = " ".join(str(prev).split()).strip(" :\xa0")
            if _pt:
                return _is_caps_label(_pt)
        elif hasattr(prev, "name"):
            if prev.name == "small":
                return True
            if prev.name in ("span", "b"):
                return _is_caps_label(prev.get_text(" ", strip=True))
            break  # some other tag directly before — not a recognized label shape
        prev = getattr(prev, "previous_sibling", None)
    return False


def _p_subheading_fragments(p_tag, label_marker=None):
    """Split a <p>'s children on internal <br><br> boundaries into
    excerpt-ready fragments, instead of flattening the whole paragraph to
    plain text with get_text(). Needed for two source shapes a flat
    get_text() call silently destroys:

    1. A bold(+italic) <small><span> subheading sitting mid-paragraph after
       a <br><br> break (e.g. "...but acts in the real world.<br><br>
       <small><span style="font-weight:bold;font-style:italic;">What Is
       Physical AI</span></small><br>") — get_text() merges its text into
       the surrounding prose with no styling at all. A detected subheading
       segment is returned styled like every other subheading in this
       file: <strong style="...">label</strong> by default, or, when
       label_marker is given (get_following_features' post-list-text
       convention), f"{label_marker}{label}".
    2. A paragraph indented with the source's own margin-left (a
       block-quote in the raw HTML) — plain-text segments are wrapped in a
       matching inline-block span when the <p>'s own style has one.
    """
    style = (p_tag.get("style") or "").replace(" ", "")
    ml_m = re.search(r'margin-left:(\d+)px', style)

    segments, current, br_run = [], [], 0
    for child in p_tag.children:
        if getattr(child, "name", None) == "br":
            br_run += 1
            if br_run >= 2:
                segments.append(current)
                current = []
                br_run = 0
            continue
        if isinstance(child, NavigableString) and not str(child).strip():
            continue  # whitespace between <br> tags doesn't break the run
        br_run = 0
        current.append(child)
    if current:
        segments.append(current)

    fragments = []
    for seg in segments:
        if len(seg) == 1 and getattr(seg[0], "name", None) == "small":
            sm = seg[0]
            sp = sm.find("span", style=True)
            sst = (sp.get("style") or "").replace(" ", "") if sp else ""
            label = " ".join(sm.get_text(" ", strip=True).split())
            if ("font-weight:bold" in sst and label and len(label) <= 80
                    and '"' not in label and '“' not in label):
                if label_marker is not None:
                    fragments.append(f'{label_marker}{label}')
                else:
                    fragments.append(
                        f'<strong style="font-family:Verdana,Arial,sans-serif;'
                        f'font-size:10px;letter-spacing:2px;text-transform:uppercase;'
                        f'color:#7a1c1c;">{label}</strong>')
                continue
        text = " ".join(
            "".join(str(c) if isinstance(c, NavigableString)
                    else c.get_text(" ", strip=True) for c in seg).split()
        ).strip()
        if not text:
            continue
        if ml_m:
            text = (f'<span style="display:inline-block;'
                    f'margin-left:{ml_m.group(1)}px;">{text}</span>')
        fragments.append(text)
    if not fragments:
        fallback = " ".join(p_tag.get_text(" ", strip=True).split())
        if fallback:
            fragments = [fallback]
    return fragments


def _span_precedes_new_item(span_or_font, current_url=""):
    """True if this <span>/<font> node is itself the header of a new,
    separately-labeled news item (e.g. <span><small><span bold>MORE</span>
    </small>: <a href="...">Title</a></span>) rather than plain body prose
    continuing the current item. A sweep that flattens this node's text
    instead of stopping here both strips the embedded link and later
    duplicates the item once that same link surfaces on its own.
    """
    if span_or_font.find("small") is None:
        return False
    a = span_or_font.find("a", href=True)
    if a is None:
        # The label's <small> may be wrapped together with its trailing
        # ": " in this span, with the actual link sitting OUTSIDE it as a
        # sibling instead of nested inside, e.g.
        # <span><small>X</small>: </span><a href="...">Title</a>.
        nxt = span_or_font.next_sibling
        for _ in range(3):
            if nxt is None:
                return False
            if isinstance(nxt, NavigableString):
                if str(nxt).strip():
                    return False
            elif getattr(nxt, "name", None) == "a":
                a = nxt
                break
            else:
                return False
            nxt = nxt.next_sibling
        if a is None:
            return False
    href = (a.get("href") or "").strip()
    return bool(href and not skip_url(href) and a.get_text(strip=True)
                and href != current_url)


def get_following_excerpts(link, _ladder_text="", _current_url="", _consumed=None):
    """
    Collect text between this link and the next <small> source label.
    Handles content at link-sibling level AND parent-span-sibling level.

    _consumed, if given a set, is populated with the href of every inline
    continuation anchor absorbed into an excerpt (e.g. a hyperlinked word
    near the end of a sentence) — the caller should treat those URLs as
    already handled so they aren't later reprocessed as a phantom separate
    item when the main link scan reaches them.
    """
    excerpts = []
    seen = set()
    # _br_run tracks consecutive <br> tags (>=2 means a real paragraph
    # break, matching the convention used elsewhere for cluster/paragraph
    # detection); _fresh_para forces the next add() to start a new entry
    # rather than merge into the previous one (used right after a paragraph
    # break, and after labels/subheadings).
    _br_run = [0]
    _fresh_para = [True]

    # Phrases that signal end of content — stop collecting if we see these
    STOP_PHRASES = (
        "Ladder of Divine Ascent",
        "Do not cease to picture",
        "Prayer request?",
        "Have ANY Catholic Question",
        "This month",
    )
    # _ladder_text comes from the parameter passed by get_news_items

    def _is_next_item_label(text_node):
        """
        True if this bare NavigableString is a source label heading the NEXT
        news item — e.g. "RELATED (X): " immediately before <a href="x.com...">.
        Pattern: short ALL-CAPS text (letters only considered), followed within
        a couple of siblings (skipping <br>/whitespace) by a valid news link.
        Without this check the walker absorbs the next item's entire body,
        which then gets emitted a second time when that link becomes (or is
        auto-repaired into) its own item — producing duplicated content.
        """
        t = " ".join(str(text_node).split()).strip(" :\xa0")
        if not t or len(t) > 40:
            return False
        letters = "".join(ch for ch in t if ch.isalpha())
        if not letters or letters != letters.upper():
            return False
        if '"' in t or '\u201c' in t:
            return False
        peek, steps = text_node.next_sibling, 0
        while peek is not None and steps < 3:
            if isinstance(peek, NavigableString):
                if str(peek).strip():
                    return False
            elif peek.name == "br":
                pass
            elif peek.name == "a" and peek.get("href"):
                ph = (peek.get("href") or "").strip()
                pt = peek.get_text(strip=True)
                return bool(ph and pt and len(pt) >= 5 and not skip_url(ph)
                            and not ph.startswith("mailto:"))
            else:
                return False
            steps += 1
            peek = peek.next_sibling
        return False

    def add(t):
        t = " ".join(t.split()).strip()
        if not t:
            return
        # HTML label strings (subheadings) are positional — allow duplicates, no length filter
        is_label = t.startswith("<strong")
        _punct_only = bool(t) and all(ch in ".,:;!?\"'’”)»" for ch in t)
        if not is_label and len(t) <= 8:
            # Short trailing punctuation (e.g. a closing "." after a
            # citation link split across tags) still belongs to the
            # sentence in progress — let it merge rather than vanish.
            if not (_punct_only and excerpts and not _fresh_para[0]):
                return
        if not is_label and t in seen:
            return
        if not is_label and any(phrase in t for phrase in STOP_PHRASES):
            return
        # Stop if this text IS the ladder excerpt (only for plain text)
        if (not is_label and _ladder_text and len(_ladder_text) > 10
                and _ladder_text[:30] in t):
            return
        if not is_label:
            seen.add(t)
        if is_label or _fresh_para[0] or not excerpts or excerpts[-1].startswith("<strong"):
            excerpts.append(t)
        else:
            # Continuation of the same source paragraph (no paragraph break
            # since the previous fragment) — merge instead of splitting into
            # a separate <p>. Handles inline-styled spans/anchors embedded
            # mid-sentence (e.g. italic emphasis, or a hyperlinked word near
            # the end of a sentence) that would otherwise fragment one
            # source sentence into several disconnected excerpt entries.
            _sep = "" if _punct_only else " "
            excerpts[-1] = (excerpts[-1].rstrip() + _sep + t).strip()
        _fresh_para[0] = is_label

    def walk_siblings(start_node):
        """Returns True if we stopped because we hit a source label."""
        nxt = start_node
        for _ in range(80):
            if nxt is None:
                return False
            if isinstance(nxt, NavigableString):
                t = str(nxt).strip(" :\n\xa0")
                if t:
                    _br_run[0] = 0
                    if _is_next_item_label(nxt):
                        return True  # next item's bare-text label — stop
                    add(t)
            elif hasattr(nxt, "name"):
                name = nxt.name
                if name != "br":
                    _br_run[0] = 0
                if name == "br":
                    _br_run[0] += 1
                    if _br_run[0] >= 2:
                        _fresh_para[0] = True
                elif name == "small":
                    # A <small> is a source label (stop) if:
                    # (a) it contains a meaningful <a> link itself, OR
                    # (b) a meaningful link follows within 3 siblings
                    has_link_ahead = False
                    # Check (a): does the <small> contain a link?
                    inner_link = nxt.find("a", href=True)
                    if inner_link:
                        lt = inner_link.get_text(strip=True)
                        lh = inner_link.get("href", "")
                        if lt and lh and not lh.startswith("mailto:"):
                            has_link_ahead = True
                    # Check (b): look at next siblings for a link
                    if not has_link_ahead:
                        peek = nxt.next_sibling
                        checked = 0
                        while peek is not None and checked < 3:
                            if isinstance(peek, NavigableString):
                                if str(peek).strip(" :\n\xa0"):
                                    checked += 1  # real text counts as a step
                                peek = peek.next_sibling
                                continue
                            if peek.name == "a":
                                link_text = peek.get_text(strip=True)
                                link_href = peek.get("href", "")
                                if (link_text and link_href and
                                        not link_href.startswith("mailto:")):
                                    has_link_ahead = True
                                break
                            if peek.name == "small":
                                break
                            if peek.name in ("ul", "ol"):
                                # This <small> labels a following bullet/feature
                                # list (e.g. "RELATED NEWS REPORTS"), not a plain
                                # prose subheading — leave both the label and the
                                # list entirely to get_following_features so it
                                # isn't absorbed here as flattened, link-stripped
                                # text and then rendered a second time.
                                has_link_ahead = True
                                break
                            # A container (e.g. <span>) that itself WRAPS the
                            # next item's label+link still counts as a link
                            # ahead — see the matching comment in the Level-2
                            # walker's identical check below.
                            _peek_a = peek.find("a", href=True) if hasattr(peek, "find") else None
                            if _peek_a:
                                _peek_t = _peek_a.get_text(strip=True)
                                _peek_h = _peek_a.get("href", "")
                                if _peek_t and _peek_h and not _peek_h.startswith("mailto:"):
                                    has_link_ahead = True
                                break
                            checked += 1
                            peek = getattr(peek, "next_sibling", None)
                    if has_link_ahead:
                        return True  # source label for next item — stop
                    # Section subheading — only add if short and contains no quotes
                    subheading_text = nxt.get_text(" ", strip=True)
                    if (subheading_text and len(subheading_text) <= 80
                            and '"' not in subheading_text
                            and '“' not in subheading_text):
                        add(f'<strong style="font-family:Verdana,Arial,sans-serif;' +
                            f'font-size:10px;letter-spacing:2px;text-transform:uppercase;' +
                            f'color:#7a1c1c;">{subheading_text}</strong>')
                    pass  # skip lists (handled by get_following_features)
                elif name == "a":
                    # An <a> that wraps a bold/small source label is the header
                    # of the NEXT item (inverted shape, e.g.
                    # <a href="x.com"><small><b>X</b></small></a>: body...).
                    # Stop here so that item's body isn't absorbed into this one.
                    a_href = nxt.get("href", "")
                    if (a_href and not a_href.startswith("mailto:")
                            and (nxt.find("small") is not None
                                 or nxt.find("span",
                                        style=lambda s: s and "font-weight" in (s or "")) is not None)):
                        return True
                    if (a_href and not a_href.startswith("mailto:")
                            and not skip_url(a_href) and a_href != _current_url
                            and nxt.get_text(strip=True)):
                        if _looks_like_new_item_anchor(nxt, _current_url):
                            return True
                        # Inline continuation link (e.g. a hyperlinked word
                        # near the end of a sentence, such as the "found
                        # here in English and here in Spanish" citation) —
                        # absorb its text and keep walking instead of
                        # dropping it or letting it surface later as a
                        # phantom separate item.
                        _txt = nxt.get_text(strip=False)
                        add(f'<a href="{a_href}" target="_blank" '
                            f'style="color:{C["link"]};font-weight:bold;">{_txt}</a>')
                        if _consumed is not None:
                            _consumed.add(a_href)
                    # Otherwise: inline body link — leave to existing handling.
                elif name == "big":
                    add(nxt.get_text(" ", strip=True))
                elif name == "p":
                    # Stop if the <p> contains a news link (it's a news item like UNIVERSALIS)
                    inner_a = nxt.find("a", href=True)
                    if inner_a:
                        ia_href = inner_a.get("href", "")
                        if ia_href and not skip_url(ia_href) and inner_a.get_text(strip=True):
                            return True  # next news item — stop
                    # Split on internal <br><br> so a bold-italic subheading
                    # or an indented block-quote embedded mid-paragraph keeps
                    # its own styling instead of being flattened by get_text().
                    for _frag in _p_subheading_fragments(nxt):
                        _fresh_para[0] = True  # each fragment is its own paragraph
                        add(_frag)  # add() filters stop phrases
                elif name in ("ul", "ol"):
                    # A bullet/feature list is owned and rendered entirely by
                    # get_following_features. Previously this case fell
                    # through unhandled and the walk silently continued past
                    # the list, which could absorb whatever text follows it
                    # as if it were this item's own excerpt (duplicating or
                    # misattributing content that belongs after the list).
                    # Stop here instead — matches the Level-2 walker below.
                    return False
                elif name in ("span", "font", "b", "i", "em"):
                    # A <span>/<font> that itself wraps a source label and a
                    # real link (e.g. the next item's own "<small><span
                    # bold>MORE</span></small>: <a href=...>Title</a>"
                    # header) is the start of a NEW item, not body prose —
                    # stop instead of flattening it into this item's excerpt
                    # (which would strip its link and duplicate it once that
                    # link surfaces as its own item).
                    if _span_precedes_new_item(nxt, _current_url):
                        return True
                    style = nxt.get("style", "") if hasattr(nxt, "get") else ""
                    t = nxt.get_text(" ", strip=True)
                    # Short bold non-italic text = source label — stop
                    # Normalize style: handle both "font-weight:bold" and "font-weight: bold"
                    style_norm = style.replace(" ", "")
                    if "font-weight:bold" in style_norm and len(t) < 80 and "font-style:italic" not in style_norm:
                        return True
                    # Short ALL-CAPS text (even without bold style) = likely source label.
                    # Allow dots/apostrophes/hyphens for common Catholic titles
                    # (FR., ST., ABP., MSGR., O'HARA, ST-JEROME).
                    t_norm = " ".join(t.split())  # normalize whitespace incl. newlines
                    if (t_norm and len(t_norm) < 60 and t_norm == t_norm.upper()
                            and all(c.isalpha() or c in " .'-" for c in t_norm)):
                        return True
                    # Preserve meaningful inline emphasis (italic/underline)
                    # instead of flattening it to plain prose — it merges
                    # into the surrounding running paragraph via add()'s
                    # continuation logic, so the emphasis survives without
                    # splitting the sentence into its own excerpt entry.
                    _emph = [s for s in ("font-style:italic", "text-decoration:underline")
                             if s in style_norm]
                    if t and _emph:
                        add(f'<span style="{";".join(_emph)};">{t}</span>')
                    else:
                        add(t)
            nxt = getattr(nxt, "next_sibling", None)
        return False

    # Level 1: walk siblings of the link itself
    hit = walk_siblings(link.next_sibling)

    # Level 1.5: if the link lives INSIDE its <small> source label
    # (e.g. <small>EXCERPT <a ...>title</a></small>: text..., or the link
    # nested one level deeper still inside a bold <span> within the
    # <small>, e.g. <small><span bold>VIA <a>GROK</a></span></small>: text),
    # the excerpt text starts right after the </small> — walk from there,
    # then climb. find_parent (not a direct-parent check) is needed so the
    # span-wrapped case is caught too; otherwise the trailing text of that
    # item is never reached by any walk and silently vanishes.
    parent = link.parent
    _small_anc = link.find_parent("small")
    if not hit and _small_anc is not None:
        # Level 1.4: if the link is nested inside a wrapper (e.g. a bold
        # <span>) that itself has further siblings BEFORE the <small>
        # closes -- i.e. the raw HTML never actually closed the <small>
        # after just the label, so the quote's own body text continues
        # inside it (e.g. "<small><span>EXCERPT<a>Title</a></span><span>
        # body text...</span>more body</small>") -- walk those first, or
        # that body text is never reached by any walker and silently
        # dropped.
        _link_container = link
        _p = link.parent
        while _p is not None and _p is not _small_anc:
            _link_container = _p
            _p = _p.parent
        if _link_container is not link:
            hit = walk_siblings(_link_container.next_sibling)
        if not hit:
            hit = walk_siblings(_small_anc.next_sibling)
        parent = _small_anc.parent

    # Level 2: walk siblings of parent span — only collect text between
    # this link's parent span and the next <ul> (which marks the AI REPORT boundary).
    # This captures the "ALARMING..." paragraphs for NCR but stops before "Overall".
    if not hit:
        if parent and parent.name in ("span", "p", "big"):
            nxt_sib = parent.next_sibling
            # Skip empty text nodes
            while nxt_sib and isinstance(nxt_sib, NavigableString) and not str(nxt_sib).strip():
                nxt_sib = getattr(nxt_sib, "next_sibling", None)
            # Only walk if next sibling is NOT a <ul> (which belongs to AI REPORT)
            # and NOT a <small> source label for the next item
            if nxt_sib and hasattr(nxt_sib, "name"):
                if nxt_sib.name not in ("ul", "ol"):
                    # Walk but stop at <ul> boundary
                    def walk_until_list(start):
                        n = start
                        for _ in range(80):
                            if n is None: break
                            if isinstance(n, NavigableString):
                                t = str(n).strip(" :\n\xa0")
                                if t:
                                    _br_run[0] = 0
                                    if _is_next_item_label(n):
                                        break  # next item's bare-text label — stop
                                    add(t)
                            elif hasattr(n, "name"):
                                if n.name in ("ul", "ol"):
                                    # Bullet/feature lists are handled by
                                    # get_following_features, which preserves
                                    # each <li>'s <a href> as a real link.
                                    # Absorbing them here via get_text() would
                                    # both strip those links and duplicate the
                                    # list (get_following_features renders it
                                    # too) — stop instead of collecting.
                                    break
                                if n.name != "br":
                                    _br_run[0] = 0
                                if n.name == "br":
                                    _br_run[0] += 1
                                    if _br_run[0] >= 2:
                                        _fresh_para[0] = True
                                elif n.name == "big":
                                    # For video items whose link is NOT the last link
                                    # in its parent <big>, stop at the next <big>
                                    # (it belongs to the next video, not this one).
                                    # But if the link IS the last in its parent, allow
                                    # collecting the next <big> as its summary.
                                    if _current_url and ("youtube.com" in _current_url or "youtu.be" in _current_url):
                                        # Find the original link by URL to check its position
                                        _n_links = n.parent.find_all("a", href=True) if n.parent else []
                                        _last_href = _n_links[-1].get("href","") if _n_links else ""
                                        if _last_href != _current_url:
                                            break  # not the last video in parent — stop
                                    # Collect text BEFORE any news link inside <big>
                                    # (the <big> may contain summary text + next video link)
                                    big_parts = []
                                    for _bc in n.children:
                                        if hasattr(_bc, 'name') and _bc.name == 'a':
                                            _href = _bc.get("href","")
                                            if not skip_url(_href) and _bc.get_text(strip=True):
                                                break  # hit next video link — stop
                                        elif isinstance(_bc, NavigableString):
                                            _bt = str(_bc).strip()
                                            if _bt: big_parts.append(_bt)
                                        elif hasattr(_bc, 'get_text'):
                                            _bt = _bc.get_text(" ", strip=True).strip()
                                            if _bt: big_parts.append(_bt)
                                    t = " ".join(big_parts).strip()
                                    if t and len(t) > 20:
                                        add(t)
                                elif n.name == "a":
                                    # Stop if this is a news link (start of next item)
                                    a_href = n.get("href", "")
                                    a_text = n.get_text(strip=True)
                                    if (a_href and not skip_url(a_href)
                                            and a_text and a_href != _current_url):
                                        if _looks_like_new_item_anchor(n, _current_url):
                                            break  # next news item — stop
                                        # Inline continuation link (e.g. a
                                        # hyperlinked word near the end of a
                                        # sentence, such as the "found here
                                        # in English and here in Spanish"
                                        # citation) — absorb it and keep
                                        # walking instead of dropping it or
                                        # letting it surface later as a
                                        # phantom separate item.
                                        _txt = n.get_text(strip=False)
                                        add(f'<a href="{a_href}" target="_blank" '
                                            f'style="color:{C["link"]};font-weight:bold;">{_txt}</a>')
                                        if _consumed is not None:
                                            _consumed.add(a_href)
                                elif n.name == "small":
                                    # Check if source label (has link after it)
                                    pk = n.next_sibling
                                    has_lnk = False
                                    _ck = 0
                                    while pk is not None and _ck < 3:
                                        if isinstance(pk, NavigableString):
                                            if str(pk).strip(" :\n\xa0"):
                                                _ck += 1
                                            pk = pk.next_sibling
                                            continue
                                        if pk.name == "a":
                                            has_lnk = True; break
                                        if pk.name == "small": break
                                        if pk.name in ("ul", "ol"):
                                            # Labels a following bullet/feature
                                            # list — leave it (and the list) to
                                            # get_following_features rather than
                                            # absorbing it as a prose subheading.
                                            has_lnk = True; break
                                        # A container (e.g. <span>) that itself
                                        # WRAPS the next item's label+link (as
                                        # with "VIA <a>Frank Rega</a>" sitting
                                        # inside an outer <span>) still counts
                                        # as a link ahead -- otherwise a bare
                                        # heading like "FROM THE MAILBAG" gets
                                        # absorbed as this item's own trailing
                                        # subheading instead of stopping before
                                        # the next item.
                                        _pk_a = pk.find("a", href=True) if hasattr(pk, "find") else None
                                        if _pk_a:
                                            _pk_t = _pk_a.get_text(strip=True)
                                            _pk_h = _pk_a.get("href", "")
                                            if _pk_t and _pk_h and not _pk_h.startswith("mailto:"):
                                                has_lnk = True
                                            break
                                        _ck += 1
                                        pk = getattr(pk, "next_sibling", None)
                                    if has_lnk: break
                                    # Section subheading — add as label
                                    lbl = n.get_text(" ", strip=True)
                                    if lbl: add(f'<strong>{lbl}</strong>')
                                elif n.name == "span":
                                    # Stop if this span contains a news link (next item)
                                    # but NOT if it's a same-URL continuation of the current item
                                    inner_a = n.find("a", href=True)
                                    if inner_a:
                                        ia_href = inner_a.get("href","")
                                        is_same_url = (_current_url and ia_href == _current_url)
                                        if (ia_href and not skip_url(ia_href)
                                                and inner_a.get_text(strip=True)
                                                and not is_same_url):
                                            break  # next news item starts here
                                    # Stop at bold source-label span (no link inside, but IS a label).
                                    # Allow dots/apostrophes/hyphens for common Catholic
                                    # titles (FR., ST., ABP., MSGR., O'HARA, ST-JEROME).
                                    style_norm = n.get("style","").replace(" ","")
                                    if "font-weight:bold" in style_norm:
                                        t_span = n.get_text(" ", strip=True).strip(" :")
                                        t_norm = " ".join(t_span.split())
                                        if (t_norm and len(t_norm) <= 60
                                                and t_norm == t_norm.upper()
                                                and all(c.isalpha() or c in " .'-" for c in t_norm)):
                                            break  # source label — stop
                                    # Recurse INTO span to collect its content
                                    # (SeaMonkey often wraps paragraphs in spans)
                                    for child in n.children:
                                        if isinstance(child, NavigableString):
                                            t = str(child).strip(" :\n\xa0")
                                            if t: add(t)
                                        elif hasattr(child, 'name') and child.name == 'p':
                                            # <p> inside span — process same as top-level <p>
                                            pt = " ".join(child.get_text(" ", strip=True).split())
                                            WALK_STOP_P = ("Ladder of Divine Ascent", "Prayer request",
                                                           "This month", "Have ANY Catholic")
                                            if not any(s in pt for s in WALK_STOP_P) and pt:
                                                strong = child.find("strong")
                                                sm = child.find("small")
                                                if strong and sm and len(pt) <= 80 and '"' not in pt:
                                                    add(f'<strong style="font-family:Verdana,Arial,sans-serif;'
                                                        f'font-size:10px;letter-spacing:2px;text-transform:uppercase;'
                                                        f'color:#7a1c1c;">{pt}</strong>')
                                                else:
                                                    add(pt)
                                        elif hasattr(child, "name"):
                                            if child.name == "small":
                                                pk2 = child.next_sibling
                                                has_lnk2 = False
                                                for _ in range(3):
                                                    if pk2 is None: break
                                                    if hasattr(pk2,"name") and pk2.name=="a":
                                                        has_lnk2=True; break
                                                    pk2=getattr(pk2,"next_sibling",None)
                                                if not has_lnk2:
                                                    # The label's <small> ran out of
                                                    # siblings inside the wrapping span —
                                                    # the link may sit just OUTSIDE it
                                                    # instead, e.g. <span><small>X</small>:
                                                    # </span><a href="...">Title</a>.
                                                    pk3 = n.next_sibling
                                                    for _ in range(3):
                                                        if pk3 is None: break
                                                        if isinstance(pk3, NavigableString):
                                                            if str(pk3).strip(" :\n\xa0"):
                                                                break
                                                        elif hasattr(pk3, "name"):
                                                            if (pk3.name == "a" and pk3.get("href")
                                                                    and pk3.get_text(strip=True)):
                                                                has_lnk2 = True
                                                            break
                                                        pk3 = getattr(pk3, "next_sibling", None)
                                                if not has_lnk2:
                                                    lbl2 = child.get_text(" ", strip=True)
                                                    if lbl2: add(f'<strong>{lbl2}</strong>')
                                            elif child.name == "br": pass
                                            else:
                                                t = child.get_text(" ", strip=True)
                                                if t and len(t) > 5: add(t)
                                elif n.name in ("font", "b"):
                                    t = " ".join(n.get_text(" ", strip=True).split())
                                    WALK_STOP = ("Ladder of Divine Ascent", "Prayer request",
                                                 "This month", "Have ANY Catholic")
                                    # Also stop if this IS the ladder excerpt text
                                    is_ladder = (_ladder_text and len(_ladder_text) > 10
                                                 and t.startswith(_ladder_text[:25]))
                                    if not any(s in t for s in WALK_STOP) and not is_ladder:
                                        add(t)
                                    if is_ladder:
                                        break
                                elif n.name == "p":
                                    # A sibling <p> carrying its own link is a
                                    # distinct item's paragraph in this
                                    # document's convention (every real item
                                    # heads its own <p> with at least a
                                    # headline <a>) — mirrors the same guard
                                    # already present in the Level-1 walker's
                                    # own <p> handling above. Without it, this
                                    # fallback walked straight through every
                                    # subsequent news item's paragraph up to
                                    # the next <ul>, duplicating each one's
                                    # full text into every preceding item.
                                    _inner_a = n.find("a", href=True)
                                    if _inner_a:
                                        _ia_href = _inner_a.get("href", "")
                                        if (_ia_href and not skip_url(_ia_href)
                                                and _inner_a.get_text(strip=True)):
                                            break  # next news item — stop
                                    # A <p> that introduces a following bullet
                                    # list (e.g. "...projected timelines:")
                                    # is that list's heading label, which
                                    # get_following_features already detects
                                    # and renders on its own — stop instead
                                    # of also absorbing it here as a plain
                                    # trailing paragraph (duplicate text).
                                    _peek, _steps2 = n.next_sibling, 0
                                    _precedes_list = False
                                    while _peek is not None and _steps2 < 5:
                                        if isinstance(_peek, NavigableString):
                                            if str(_peek).strip():
                                                break
                                        elif getattr(_peek, "name", None) in ("ul", "ol"):
                                            _precedes_list = True
                                            break
                                        elif getattr(_peek, "name", None) != "br":
                                            break
                                        _steps2 += 1
                                        _peek = _peek.next_sibling
                                    if _precedes_list:
                                        break
                                    t = " ".join(n.get_text(" ", strip=True).split())
                                    WALK_STOP = ("Ladder of Divine Ascent", "Prayer request",
                                                 "This month", "Have ANY Catholic")
                                    is_ladder = (_ladder_text and len(_ladder_text) > 10
                                                 and t.startswith(_ladder_text[:25]))
                                    if "Ladder of Divine Ascent" in t or is_ladder:
                                        break  # stop walking at Ladder paragraph
                                    if not any(s in t for s in WALK_STOP) and not is_ladder:
                                        # Split on internal <br><br> so a bold-italic
                                        # subheading or an indented block-quote embedded
                                        # mid-paragraph keeps its own styling instead of
                                        # being flattened by the get_text() above.
                                        for _frag in _p_subheading_fragments(n):
                                            _fresh_para[0] = True  # each fragment is its own paragraph
                                            add(_frag)
                            n = getattr(n, "next_sibling", None)
                    walk_until_list(parent.next_sibling)


    # Special case: YouTube link that is last <a> in a <big> parent
    # Its summary is in the NEXT <big> sibling — collect it directly
    _link_parent = link.parent
    if (not excerpts and _link_parent and _link_parent.name == "big"
            and ("youtube.com" in _current_url or "youtu.be" in _current_url)):
        all_a_in_big = _link_parent.find_all("a", href=True)
        if all_a_in_big and all_a_in_big[-1] is link:
            _nxt = _link_parent.next_sibling
            for _ in range(6):
                if _nxt is None: break
                if hasattr(_nxt, "name") and _nxt.name == "big":
                    _parts = []
                    for _bc in _nxt.children:
                        if hasattr(_bc, "name") and _bc.name == "a":
                            if not skip_url(_bc.get("href","")) and _bc.get_text(strip=True):
                                break
                        elif isinstance(_bc, NavigableString):
                            _bt = str(_bc).strip()
                            if _bt: _parts.append(_bt)
                        elif hasattr(_bc, "get_text"):
                            _bt = _bc.get_text(" ", strip=True).strip()
                            if _bt: _parts.append(_bt)
                    _t = " ".join(_parts).strip()
                    if _t and len(_t) > 20:
                        excerpts.append(_t)
                    break
                _nxt = _nxt.next_sibling

    return excerpts


def _capture_leading_turns(link):
    """Capture dialogue/prose that precedes `link` within its own
    enclosing <p>, for the shape where several speaker turns share ONE
    paragraph and only the LAST turn happens to carry a link — e.g. a
    multi-question interview:

        <p><small>WWNN</small>: Question one...<br><br>
           <small>Rev. Larrey</small>: Answer one...<br><br>
           <small>WWNN</small>: Question two...<br><br>
           <small>Rev. Larrey</small>: ...one excellent use is
           "<a href="...">Magisterium AI,</a>" founded by...</p>

    Every walker in this file only looks FORWARD from a link, so text
    sitting entirely BEFORE the one link in a paragraph like this has no
    path that ever collects it — it silently vanishes. This returns
    (leading_fragments, lead_in):
      leading_fragments -- excerpt-style fragments (bold <strong> label +
        text) for each EARLIER turn, in order, to prepend ahead of the
        item's own excerpts.
      lead_in -- plain text from the SAME turn as the link, before the
        link itself (no label -- the item's own source label already
        covers this turn), to be woven into a leading paragraph so the
        link renders inline within its sentence instead of disappearing.
    Returns ([], "") in the common case (a link that already heads its
    own paragraph, i.e. there's nothing of substance before it).
    """
    p = link.find_parent("p")
    if p is None:
        return [], ""
    turns = []          # completed (label, text) turns, in order
    cur_label = None
    cur_parts = []
    br_run = 0

    def flush():
        nonlocal cur_label, cur_parts
        text = " ".join(" ".join(cur_parts).split()).strip(" :")
        if text or cur_label:
            turns.append((cur_label, text))
        cur_label, cur_parts = None, []

    reached = False
    for node in p.children:
        if node is link:
            reached = True
            break
        if getattr(node, "name", None) == "br":
            br_run += 1
            if br_run >= 2:
                flush()
            continue
        br_run = 0
        if getattr(node, "name", None) == "small":
            lbl = node.get_text(" ", strip=True).strip(" :")
            if lbl:
                flush()
                cur_label = lbl
            continue
        if isinstance(node, NavigableString):
            t = str(node).strip(" :\n\xa0")
            if t:
                cur_parts.append(t)
        elif hasattr(node, "get_text"):
            t = node.get_text(" ", strip=True)
            if t:
                cur_parts.append(t)
    if not reached:
        return [], ""  # link isn't a direct child of this <p> — not our shape
    flush()
    if not turns:
        return [], ""
    *earlier, last = turns
    lead_in = last[1] if last else ""
    fragments = []
    for lbl, txt in earlier:
        if lbl:
            fragments.append(
                f'<strong style="font-family:Verdana,Arial,sans-serif;'
                f'font-size:10px;letter-spacing:2px;text-transform:uppercase;'
                f'color:#7a1c1c;">{lbl}</strong>')
        if txt:
            fragments.append(txt)
    return fragments, lead_in


def get_news_items(block):
    """
    Extract all news items from a raw entry block.

    For each meaningful news link, captures:
      source        — source label (PAULINE.ORG, NOTRE DAME NEWS, etc.)
      url           — href
      link_text     — visible title
      excerpts      — following text paragraphs / <big> text
      feature_items — ✦ bullet list items from a following <ul>
    """
    soup  = BeautifulSoup(block, "html.parser")
    _block_ladder = get_ladder(block)  # used to filter ladder text from excerpts
    # Built once per block; get_following_features uses it for list ownership.
    _doc_order = {id(el): i for i, el in enumerate(soup.descendants)}
    items = []
    seen  = set()

    # Pre-pass: SECTION HEADINGS over bare links (e.g. RELATED HEADLINES).
    # A <small> whose label span is BOLD+ITALIC and which is followed by 2+
    # plain <a> links (only <br>/whitespace between) is a heading for a
    # compact group of headlines — render once, not as per-item labels.
    headline_first  = {}   # first url -> group dict
    headline_member = set()
    for _sm in soup.find_all("small"):
        if _sm.find("a", href=True):
            continue  # label smalls with their own link are normal items
        _sp = _sm.find("span", style=True)
        if not _sp:
            continue
        _st = (_sp.get("style") or "").replace(" ", "")
        # A section heading is BOLD. Italic is an optional, stronger signal:
        #   bold + italic -> section even with a single link
        #   bold only     -> needs 2+ links (so a normal one-link item isn't
        #                    mistaken for a section heading)
        if "font-weight:bold" not in _st:
            continue
        _is_italic = "font-style:italic" in _st
        _heading = _sm.get_text(" ", strip=True).strip(" :")
        if not _heading or len(_heading) > 60:
            continue
        _links, _n, _steps = [], _sm.next_sibling, 0
        while _n is not None and _steps < 40:
            _steps += 1
            if isinstance(_n, NavigableString):
                if str(_n).strip():
                    break
            elif _n.name == "br":
                pass
            elif _n.name == "a" and _n.get("href"):
                _href = _n.get("href", "").strip()
                _txt  = clean(_n)
                if _href and _txt and not skip_url(_href):
                    _links.append((_href, _txt))
                else:
                    break
            else:
                break
            _n = _n.next_sibling
        _min = 1 if _is_italic else 2
        if len(_links) >= _min:
            headline_first[_links[0][0]] = {"heading": _heading, "links": _links}
            for _u, _t in _links:
                headline_member.add(_u)

    # Pre-scan: identify INLINE CONTINUATION links (see helper for details).
    # These are inline references within a previous item's content — not
    # separate news items. Without this filter, each inline <a> becomes its
    # own phantom card with quote-fragment text mistaken for a source label.
    _inline_a_ids, _cluster_of = _detect_inline_and_clusters(soup)
    # A "cluster primary" is an <a> that has at least one inline continuation
    # anchor mapped to it. Its rendering will be prose-only (label + flowing
    # body with inline anchors) rather than the standard blue-link title +
    # excerpt layout, to preserve quotes like the Augustine excerpt as one
    # continuous paragraph with clickable inline references.
    _cluster_primary_ids = {id(pa) for pa in _cluster_of.values()}

    for link in soup.find_all("a", href=True):
        url = link.get("href", "").strip()
        if not url or skip_url(url):
            continue
        # Skip embedded image / media links (e.g. an fbcdn photo linked inside a
        # post body). These are never news headlines; they belong to the body of
        # whatever item contains them (handled there).
        _upath = url.split("?", 1)[0].lower()
        if _upath.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")):
            continue

        # Inline continuation link (identified above) — belongs to the
        # preceding item's content, not its own news item.
        if id(link) in _inline_a_ids:
            continue

        link_text = clean(link)
        if not link_text:
            continue
        if len(link_text) < 5:
            # A short anchor text (e.g. "GROK" in "VIA <a>GROK</a>") isn't
            # junk when it's embedded in a larger <small> label that gives
            # it real context — only skip when there's nothing more to it
            # (a bare stray "»"-style anchor with no surrounding label).
            _sm_anc = link.find_parent("small")
            # NOTE: must use a space separator here -- without it adjacent
            # text/tag fragments collapse together (e.g. "VIA " + "X" ->
            # "VIAX", 4 chars) and a legitimately-labeled short anchor like
            # "VIA <a>X</a>" gets miscounted as bare junk and dropped.
            _sm_text_len = len(_sm_anc.get_text(" ", strip=True)) if _sm_anc else 0
            if _sm_text_len < 5:
                continue
        # Headline-group member: emit the whole group at its first link
        if url in headline_member:
            if url in headline_first and url not in seen:
                _g = headline_first[url]
                for _u, _t in _g["links"]:
                    seen.add(_u)
                items.append({
                    "source":         _g["heading"],
                    "url":            "",
                    "link_text":      "",
                    "excerpts":       [],
                    "feature_items":  [],
                    "headline_links": _g["links"],
                })
            continue
        # If the link is immediately followed by a colon sibling, include it
        # e.g. <a>POPE LEO XIV</a>: "Through..." → link_text = "POPE LEO XIV:"
        _nxt = link.next_sibling
        if (_nxt and isinstance(_nxt, NavigableString)
                and str(_nxt).strip().startswith(":")):
            link_text = link_text.rstrip(":") + ":"

        # Skip links that are papal/saint quote blocks (handled by get_collect)
        # Detect: link is in <small><span bold>, link text is POPE/SAINT name,
        # and the sibling text after the colon is quoted content (starts with ")
        _lt_upper = link_text.upper().rstrip(":")
        _is_quote_block = _is_quote_label(_lt_upper)
        if _is_quote_block:
            # Check the text immediately following — if it's quoted content, skip
            _after = link.next_sibling
            if _after and isinstance(_after, NavigableString):
                _after_t = str(_after).strip()
                # Only treat as a quote block if quoted content actually
                # follows — mirrors get_collect's own guard. A plain
                # "BISHOP X: headline" (no quote marks) stays a news item;
                # previously it was skipped here AND rejected by
                # get_collect, surviving only via the auto-repair net.
                _has_quote = ('"' in _after_t or '\u201c' in _after_t)
                if (_after_t.startswith('\u201c') or '"' in _after_t[:5]
                        or (_after_t.startswith(':') and _has_quote)):
                    continue  # this is a collect/quote block, not a news item
            elif _after is None:
                # The label <a> may be the last child of its own wrapping
                # bold <span>, with the quote body starting in a *sibling*
                # span instead of continuing inline (e.g. <small><span>
                # EXCERPT<a>...</a></span><span>(2005): "..."</span></small>).
                # Mirrors get_collect's own sibling-span fallback.
                _span_anc = link.find_parent("span", style=lambda s: s and "font-weight" in (s or ""))
                _sib = _span_anc.next_sibling if _span_anc is not None else None
                if _sib is not None:
                    _sib_t = (_sib.get_text(" ", strip=True) if hasattr(_sib, "get_text")
                              else str(_sib).strip())
                    if '"' in _sib_t or '\u201c' in _sib_t:
                        continue  # quote body lives in a sibling span \u2014 handled by get_collect
        # Merge consecutive same-URL <a> tags into one link_text.
        # SeaMonkey splits italic titles across multiple <a> tags with identical href.
        # These may appear as direct siblings OR as parent-level siblings.
        def _collect_same_url(start_node, target_url, max_steps=6):
            """Walk siblings; collect text from <a> tags matching target_url."""
            extra_parts = []
            nxt = start_node
            for _ in range(max_steps):
                if nxt is None:
                    break
                if hasattr(nxt, 'name') and nxt.name == 'a':
                    if nxt.get('href', '') == target_url:
                        t = clean(nxt)
                        if t:
                            extra_parts.append(t)
                    else:
                        break  # different link — stop
                elif hasattr(nxt, 'name') and nxt.name == 'span':
                    # Check if span starts with a same-URL link
                    first_a = nxt.find('a', href=True)
                    if first_a and first_a.get('href', '') == target_url:
                        t = clean(first_a)
                        if t:
                            extra_parts.append(t)
                    else:
                        break
                elif isinstance(nxt, NavigableString):
                    pass  # skip whitespace
                else:
                    break
                nxt = nxt.next_sibling
            return extra_parts
        # Check direct siblings first, then parent-level siblings
        for _start in [link.next_sibling, link.parent.next_sibling if link.parent else None]:
            if _start is None:
                continue
            _extras = _collect_same_url(_start, url)
            if _extras:
                link_text = (link_text.rstrip() + ' ' + ' '.join(_extras)).strip()
                break
        if url in seen:
            continue
        if is_domain_only(link_text):
            continue  # skip "MAGISTERIUM.COM" standalone
        if link_text.strip() in (":", "", ".", ","):
            continue
        # Links inside <li> tags: extract as items if they have a source label
        # (e.g. NEWS REPORTS section where each <li> is a separate news item)
        # But skip bare links inside <li> (no source label = pure bullet content)
        def _child_precedes_link(child):
            """True if `link` is this child itself OR nested somewhere
            inside it — needed because the label-carrying <small> and the
            link don't always sit at the same nesting depth (e.g. the link
            can be nested small>span>a rather than a direct <small>
            sibling), in which case a plain `child is link` identity check
            never fires and the scan below would run past the link
            entirely, misreading later content as part of the label."""
            if child is link:
                return True
            return hasattr(child, "descendants") and any(d is link for d in child.descendants)

        in_li = link.find_parent("li")
        if in_li:
            # Check if this <li> has a source label (<small> before the link)
            li_source = ""
            for child in in_li.children:
                if hasattr(child, 'name') and child.name == 'small':
                    if child.find("a", href=True) is not None:
                        # The <small> wraps the link itself (not just a label
                        # ahead of it) -- its raw get_text() would swallow any
                        # trailing excerpt prose nested in the same <small> as
                        # the link. Isolate just the label instead.
                        li_source = get_source_for_link(link)
                    else:
                        li_source = child.get_text(" ", strip=True)
                if _child_precedes_link(child):
                    break
                if hasattr(child, 'name') and child.name == 'a' and child is not link:
                    break  # another link before ours — stop
            if not li_source:
                continue  # no source label → skip (pure bullet)
            # Has a source label → extract as news item (source overridden below)

        # Links inside <p> tags: extract as items if preceded by <small> source label
        in_p = (not in_li) and link.find_parent("p")
        if in_p:
            p_source = ""
            for child in in_p.children:
                if hasattr(child, 'name') and child.name == 'small':
                    if child.find("a", href=True) is not None:
                        # Same "small wraps the link itself" case as in_li
                        # above -- isolate the label rather than swallowing
                        # trailing body prose nested in the same <small>.
                        p_source = get_source_for_link(link)
                    else:
                        p_source = child.get_text(" ", strip=True)
                if _child_precedes_link(child):
                    break
            if not p_source:
                continue  # no source in <p> → skip

        seen.add(url)

        # For links inside <li>, use the label found in that <li>
        if in_li:
            source = li_source
        # For links inside <p>, use the label found in that <p>
        elif in_p:
            source = p_source
        else:
            source = get_source_for_link(link)
        # YouTube/video links: find the "RELATED VIDEOS" section label if present
        if "youtube.com" in url or "youtu.be" in url:
            # Only override the already-detected label if an explicit
            # "RELATED VIDEOS" section heading is found nearby; otherwise keep
            # the source label we already found (e.g. a normal "YOUTUBE:" bookend).
            _rv = ""
            _p = link.parent
            for _ in range(10):
                if _p is None: break
                _prev = getattr(_p, "previous_sibling", None)
                while _prev:
                    if hasattr(_prev, "name"):
                        _t = _prev.get_text(" ", strip=True).upper()
                        if "RELATED VIDEO" in _t and len(_t) < 80:
                            _rv = _prev.get_text(" ", strip=True).strip(" :")
                            break
                    _prev = getattr(_prev, "previous_sibling", None)
                if _rv:
                    break
                _p = getattr(_p, "parent", None)
            if _rv:
                source = _rv
        # The "link immediately followed by a colon" heuristic above only
        # means to mark a *self-labeling* anchor (no separate source small
        # precedes it, e.g. "<a>POPE LEO XIV</a>: ..."). When a distinct
        # source label WAS found (e.g. "VIA" before "<a>Frank Rega</a>:
        # Venerable Pius XII..."), that trailing colon was just body
        # punctuation introducing the excerpt, not part of the title --
        # strip it back off so it doesn't render as "Frank Rega:".
        if source and link_text.endswith(":"):
            link_text = link_text[:-1]
        excerpts      = get_following_excerpts(link, _ladder_text=_block_ladder,
                                                  _current_url=url, _consumed=seen)
        feature_items = get_following_features(link, soup, doc_order=_doc_order,
                                                inline_ids=_inline_a_ids)

        # Remove excerpts that are continuation fragments already in link_text
        # Check if the excerpt text (stripped of punctuation) overlaps with link_text
        lt_lower = link_text.lower()
        def _is_continuation(e, lt):
            if e.startswith("<strong"):
                return False  # labels always kept
            el = e.lower().strip(" ,.:;")
            if not el or len(el) < 10:
                return False
            # Check if most of this excerpt is already in link_text
            return el in lt or lt.endswith(el[:40]) or el[:40] in lt
        excerpts = [e for e in excerpts if not _is_continuation(e, lt_lower)]
        # Self-labeling source link: the bold link text IS an ALL-CAPS source
        # label (e.g. "X NEWS REPORT") with the article body following as plain
        # text in the same <small><span bold>, and there is NO preceding label.
        body_bold = False
        if not source and excerpts:
            _lt_clean = link_text.rstrip(":").strip()
            _bold_container = (link.find_parent(
                            "span", style=lambda s: s and "font-weight" in (s or ""))
                        or link.find_parent("b"))
            _in_bold = _bold_container is not None
            # A leading "LABEL:" segment counts as self-labeling even if a
            # mixed-case title follows in the same link (e.g. "CHURCH
            # FATHERS: The Didache") -- only the label itself need be
            # all-caps, not the whole anchor text.
            _label_part = _lt_clean.split(':', 1)[0].strip() if ':' in _lt_clean else _lt_clean
            if (_lt_clean and len(_lt_clean) <= 40
                    and _label_part and _label_part.upper() == _label_part
                    and '"' not in _lt_clean and '\u201c' not in _lt_clean
                    and _in_bold):
                # X/Twitter self-labeling report blocks (e.g. "X NEWS REPORT:")
                # are rendered as a set-apart small-bold quote box by
                # get_social_report() — skip here to avoid double-rendering.
                if "x.com/" in url or "twitter.com/" in url:
                    continue
                # Other self-labeling links become a normal crimson-labelled
                # news card (h_news renders the label as the link).
                source    = _lt_clean
                link_text = ""
                # If the excerpt body itself sits inside the same bold
                # container as the label (e.g. an unquoted Cardinal/Bishop
                # citation rendered as one bold small block in the source,
                # rather than a quoted papal/saint pull-quote handled by
                # get_collect), preserve that bold styling instead of
                # flattening it to a normal-weight paragraph.
                _container_text = " ".join(_bold_container.get_text(" ", strip=True).split())
                body_bold = all(
                    " ".join(re.sub(r'<[^>]+>', '', e).split()).strip() in _container_text
                    for e in excerpts
                )
        # X/Twitter links become news items only when explicitly labeled
        # (e.g. "VIDEO CATHOLIC VOTE:"); bare/embedded social links are skipped.
        if ("x.com/" in url or "twitter.com/" in url) and not source:
            continue

        # Cluster primary: this link has one or more inline continuation
        # anchors after it (multi-link quote or parenthetical citation).
        # Capture the full flowing content — primary link + interstitial
        # text + inline anchors — and render as a prose-only card (label
        # followed directly by the paragraph, no separate blue title).
        if id(link) in _cluster_primary_ids:
            _cluster_fragments = _capture_cluster_excerpt(
                link, _inline_a_ids, C["link"])
            if _cluster_fragments:
                # If normal backward-walker missed the source label — as it
                # does when the label sits in a <small><span> block that's
                # a sibling of the link's container rather than a direct
                # predecessor — hunt one out. Look for the nearest earlier
                # <small> whose stripped text is a short ALL-CAPS label
                # (colon-terminated), scanning previous elements in doc
                # order across container boundaries.
                if not source:
                    _prev = link.previous_element
                    _hops = 0
                    while _prev is not None and _hops < 400:
                        if hasattr(_prev, "name") and _prev.name == "small":
                            _st = _prev.get_text(" ", strip=True).strip(" :")
                            _st_norm = " ".join(_st.split())
                            if (_st_norm and len(_st_norm) <= 60
                                    and _st_norm == _st_norm.upper()
                                    and all(c.isalpha() or c in " .'-"
                                            for c in _st_norm)):
                                source = _st_norm
                                break
                        _prev = _prev.previous_element
                        _hops += 1
                items.append({
                    "source":        source,
                    "url":           "",
                    "link_text":     "",
                    "excerpts":      _cluster_fragments,
                    # Use the feature list already computed for this link
                    # above (not discarded) — a cluster primary can still
                    # legitimately own a following bulleted list (e.g. a
                    # citation cluster like "(Decrypt; Business Insider)"
                    # that precedes a bullet list of related claims).
                    "feature_items": feature_items,
                })
                continue

        # Same-paragraph content that sits BEFORE this link (see
        # _capture_leading_turns) — every other walker in this file only
        # looks forward from a link, so a multi-turn paragraph where the
        # link only appears in the final turn would otherwise lose every
        # earlier turn, and even the lead-in clause of its own turn.
        _leading_fragments, _lead_in = _capture_leading_turns(link)
        if _leading_fragments or _lead_in:
            if _lead_in:
                _anchor_html = link.get_text(strip=False)
                _lead_para = (f'{_lead_in} <a href="{url}" target="_blank" '
                              f'style="color:{C["link"]};font-weight:bold;">{_anchor_html}</a>')
                excerpts = _leading_fragments + [_lead_para] + excerpts
                # The link now flows inline inside that leading paragraph
                # rather than heading its own headline/excerpt block.
                link_text = ""
                url = ""
            else:
                excerpts = _leading_fragments + excerpts

        items.append({
            "source":        source,
            "url":           url,
            "link_text":     link_text,
            "excerpts":      excerpts,
            "feature_items": feature_items,
            "body_bold":     body_bold,
        })

    # A bare "DONATE" item is never independent content — it's always a
    # continuation of whatever organization/appeal the immediately
    # preceding item just described (e.g. "AID TO THE CHURCH IN NEED"
    # followed by its own "DONATE: <link>"). Fold it into that item as a
    # sub-label + link, matching how a trailing subheading is already
    # rendered elsewhere in this file, instead of surfacing it as its own
    # disconnected card with no context for what the link is for.
    merged_items = []
    for it in items:
        if merged_items and (it.get("source") or "").strip().upper() == "DONATE":
            prev = merged_items[-1]
            donate_frag = [f'<strong>{it["source"].strip()}</strong>']
            if it.get("url"):
                link_text = it.get("link_text") or it["url"]
                donate_frag.append(
                    f'<a href="{it["url"]}" target="_blank" '
                    f'style="color:{C["link"]};font-weight:bold;">{link_text}</a>')
            donate_frag.extend(it.get("excerpts") or [])
            prev["excerpts"] = list(prev.get("excerpts") or []) + donate_frag
            continue
        merged_items.append(it)

    return merged_items



# ══════════════════════════════════════════════════════════════════════════
# HTML BUILDERS  (all inline styles — email safe)
# ══════════════════════════════════════════════════════════════════════════

def h_label(text):
    """Source label div in crimson uppercase."""
    if not text:
        return ""
    return (
        f'<div style="font-family:Verdana,Arial,sans-serif;font-size:10px;font-weight:bold;'
        f'letter-spacing:2px;text-transform:uppercase;color:{C["crimson"]};'
        f'margin-bottom:4px;">{text}</div>'
    )


def h_news(source, url, link_text, excerpts=None, feature_items=None, body_bold=False):
    """Build one news item: source label + linked title + excerpts + ✦ feature table.
    When feature_items exist and there are multiple excerpts, the last excerpt is
    treated as a concluding paragraph and rendered AFTER the bullet list.

    body_bold preserves source formatting for items whose whole quote (label
    + body) was one bold small block in the raw HTML (e.g. an unquoted
    Cardinal/Bishop citation) rather than a normal-weight news excerpt.
    """
    _weight = "font-weight:bold;" if body_bold else ""
    all_excerpts = [p for p in (excerpts or []) if p.strip(": \u00a0")]

    _last_is_label = bool(all_excerpts) and (
        all_excerpts[-1].startswith("<strong") and all_excerpts[-1].endswith("</strong>"))
    if feature_items and len(all_excerpts) > 1 and len(all_excerpts) <= 6 and not _last_is_label:
        # Short item with a feature list: excerpts before list, last as concluding para.
        # A trailing subheading label is never eligible for this move — it belongs
        # right where it appeared in the source flow, not after an unrelated bullet list.
        pre_excerpts  = all_excerpts[:-1]
        post_excerpts = all_excerpts[-1:]
    else:
        # Long-form summary (>6 excerpts) or no feature list: excerpts flow as
        # paragraphs; any feature list still renders as its own bullet table
        # (below), after them, in source order — never flattened into prose.
        pre_excerpts  = all_excerpts[:40]
        post_excerpts = []

    ex_html = ""
    for para in pre_excerpts:
        if para.startswith("<strong") and para.endswith("</strong>"):
            # Section subheading label — render as crimson uppercase div
            ex_html += (
                f'<div style="font-family:Verdana,Arial,sans-serif;font-size:10px;'
                f'font-weight:bold;letter-spacing:1px;text-transform:uppercase;'
                f'color:{C["crimson"]};margin:10px 0 4px 0;">{para}</div>'
            )
        else:
            ex_html += (
                f'<p style="font-family:Verdana,Arial,sans-serif;font-size:15px;'
                f'{_weight}color:{C["ink_mid"]};line-height:1.7;margin:6px 0 0 0;">{para}</p>'
            )

    concluding_html = ""
    for para in post_excerpts:
        if para.startswith("<strong") and para.endswith("</strong>"):
            concluding_html += (
                f'<div style="font-family:Verdana,Arial,sans-serif;font-size:10px;'
                f'font-weight:bold;letter-spacing:1px;text-transform:uppercase;'
                f'color:{C["crimson"]};margin:10px 0 4px 0;">{para}</div>'
            )
        else:
            concluding_html += (
                f'<p style="font-family:Verdana,Arial,sans-serif;font-size:15px;'
                f'{_weight}color:{C["ink_mid"]};line-height:1.7;margin:6px 0 0 0;">{para}</p>'
            )

    feat_html = ""
    post_list_html = ""
    if feature_items:
        # Separate regular bullets from post-list concluding text
        post_items = [f[len("__POST_LIST__"):] for f in feature_items if f.startswith("__POST_LIST__")]
        # Build feature table — __LABEL__ items become section headers, rest are bullets
        rows = ""
        in_table = False
        for i, item in enumerate(feature_items):
            if item.startswith("__POST_LIST__"):
                continue
            if item.startswith("__LABEL__"):
                # Close any open table, add subheading, start new table
                if in_table:
                    rows += f'</tbody></table>\n'
                    in_table = False
                label_text = item[len("__LABEL__"):]
                rows += (
                    f'<div style="font-family:Verdana,Arial,sans-serif;font-size:10px;'
                    f'font-weight:bold;letter-spacing:1px;text-transform:uppercase;'
                    f'color:{C["crimson"]};margin:10px 0 4px 0;">{label_text}</div>'
                )
            else:
                if not in_table:
                    rows += f'<table width="100%" cellspacing="0" cellpadding="4" border="0"><tbody>\n'
                    in_table = True
                # Check if next non-label, non-post item exists for border
                remaining = [f for f in feature_items[feature_items.index(item)+1:]
                             if not f.startswith("__POST_LIST__") and not f.startswith("__LABEL__")]
                border = f"border-bottom:1px dotted {C['rule']};" if remaining else ""
                rows += (
                    f'<tr><td style="padding:5px 0;{border}font-family:Verdana,Arial,sans-serif;'
                    f'font-size:14px;color:{C["ink_mid"]};line-height:1.5;">'
                    f'&#10022;&nbsp;{item}</td></tr>\n'
                )
        if in_table:
            rows += f'</tbody></table>\n'
        if rows:
            feat_html = rows
        for p in post_items:
            if p.startswith("__LABEL__"):
                # Bold-italic subheading swept in from the article's
                # continuing prose (e.g. "Overall Framing") — same styling
                # as the section-header divs above, not a plain paragraph.
                p_label = p[len("__LABEL__"):]
                post_list_html += (
                    f'<div style="font-family:Verdana,Arial,sans-serif;font-size:10px;'
                    f'font-weight:bold;letter-spacing:1px;text-transform:uppercase;'
                    f'color:{C["crimson"]};margin:10px 0 4px 0;">{p_label}</div>'
                )
            else:
                post_list_html += (
                    f'<p style="font-family:Verdana,Arial,sans-serif;font-size:15px;'
                    f'color:{C["ink_mid"]};line-height:1.7;margin:6px 0 0 0;">{p}</p>'
                )

    # When the source label IS the link (self-labeling item, e.g. an X news
    # post "X NEWS REPORT: ...") there is no separate headline. Render the
    # crimson source label itself as the clickable link and omit the empty
    # bold-blue headline line.
    if source and not (link_text or "").strip() and url:
        label_html = (
            f'<div style="font-family:Verdana,Arial,sans-serif;font-size:10px;'
            f'font-weight:bold;letter-spacing:2px;text-transform:uppercase;'
            f'color:{C["crimson"]};margin-bottom:4px;">'
            f'<a href="{url}" target="_blank" style="color:{C["crimson"]};'
            f'text-decoration:none;">{source}</a></div>'
        )
        head_html = ""
    elif source and not (link_text or "").strip() and not url:
        # Prose-only card: source label followed directly by body content.
        # Used for cluster primaries (e.g. St. Augustine multi-link quote,
        # Archbishop Sheen with parenthetical citation) where the body is
        # one flowing paragraph with inline anchor references, not a
        # separate blue-link title above a text block.
        label_html = h_label(source)
        head_html = ""
    else:
        label_html = h_label(source)
        head_html = (
            f'<div style="font-family:Verdana,Arial,sans-serif;font-size:15px;'
            f'font-weight:bold;line-height:1.4;">'
            f'<a href="{url}" target="_blank" style="color:{C["link"]};'
            f'text-decoration:none;">{link_text}</a></div>'
        )

    return (
        f'<table border="0" cellpadding="0" cellspacing="0" width="100%"'
        f' style="margin-bottom:18px;padding-bottom:18px;'
        f'border-bottom:1px dashed {C["rule"]};">'
        f'<tr><td>{label_html}{head_html}'
        f'{ex_html}{feat_html}{post_list_html}{concluding_html}</td></tr></table>\n'
    )

def h_scripture(ref, text):
    """Gold left-border scripture blockquote."""
    label = f"({ref})&nbsp; " if ref else ""
    return (
        f'<blockquote style="margin:0 0 22px 0;padding:8px 0 8px 14px;'
        f'border-left:3px solid {C["gold"]};font-style:italic;color:{C["ink_mid"]};'
        f'font-family:Verdana,Arial,sans-serif;font-size:15px;line-height:1.65;">'
        f'{label}{text}</blockquote>\n'
    )


def h_pull_quote(text, attr=""):
    """Parchment-background pull quote with optional attribution."""
    attr_html = f' &mdash;<strong>{attr}</strong>' if attr else ""
    return (
        f'<blockquote style="margin:0 0 16px 0;padding:10px 14px;'
        f'background-color:#f0ecd8;border-left:3px solid {C["gold"]};'
        f'font-family:Verdana,Arial,sans-serif;font-size:15px;color:{C["ink_mid"]};'
        f'line-height:1.65;">{text}{attr_html}</blockquote>\n'
    )


def h_ladder(text, step_num=None, step_title=None):
    """Ladder of Divine Ascent excerpt box. Step number and title are
    read from the source each week (previously hardcoded)."""
    if not text:
        return ""
    if step_num and step_title:
        step_label = f' &mdash; Step {step_num}: &ldquo;{step_title}&rdquo;'
    else:
        step_label = ''
    return (
        f'<div style="background-color:{C["ladder_bg"]};border:1px solid {C["ladder_bdr"]};'
        f'padding:12px 16px;margin-bottom:22px;">'
        f'<div style="font-family:Verdana,Arial,sans-serif;font-size:10px;font-weight:bold;'
        f'letter-spacing:1px;text-transform:uppercase;color:{C["crimson"]};'
        f'margin-bottom:6px;">'
        f'<a href="{LADDER_URL}" style="color:{C["crimson"]};text-decoration:none;">'
        f'Ladder of Divine Ascent</a>'
        f'{step_label}</div>'
        f'<p style="font-family:Verdana,Arial,sans-serif;font-size:15px;font-style:italic;'
        f'color:{C["ink_mid"]};margin:0;line-height:1.65;">{text}</p></div>\n'
    )


def h_list(tag, items):
    """Standard ul/ol list (used in archive entries with related-news lists)."""
    li_html = "".join(f'<li style="margin-bottom:4px;">{it}</li>' for it in items)
    return (
        f'<{tag} style="font-family:Verdana,Arial,sans-serif;font-size:15px;color:{C["ink_mid"]};'
        f'line-height:1.8;margin:0 0 16px 0;padding-left:22px;">'
        f'{li_html}</{tag}>\n'
    )


def h_divider():
    return (
        f'<img src="{LINE_GIF}" alt="" width="100%" height="2" '
        f'style="display:block;margin:0 0 22px 0;border:0;">\n'
    )


def h_feast_inline(feast):
    """Inline feast-day invocation for the date line, e.g.
    OUR LADY OF MOUNT CARMEL, PRAY FOR US! (feast name linked)."""
    if not feast:
        return ""
    if feast["url"]:
        name = (f'<a href="{feast["url"]}" target="_blank" '
                f'style="color:{C["link"]};text-decoration:underline;">'
                f'{feast["link_text"]}</a>')
    else:
        name = feast["link_text"]
    tail = feast["tail"]
    sep  = "" if tail[:1] in ",.;:!?" else (" " if tail else "")
    return (f'&nbsp;&nbsp;<span style="font-style:italic;font-weight:bold;'
            f'color:{C["ink_mid"]};letter-spacing:0;">{name}{sep}{tail}</span>')


def h_entry_header(date, subtitle="", feast=None):
    """Date heading with optional subtitle (e.g. DIVINE MERCY SUNDAY) and
    optional feast-day invocation (e.g. OUR LADY OF MOUNT CARMEL, PRAY FOR US!)."""
    sub = (
        f'&nbsp;&mdash;&nbsp;<span style="text-decoration:underline;">{subtitle}</span>'
        if subtitle else ""
    )
    return (
        f'<div style="font-family:Verdana,Arial,sans-serif;font-size:13px;'
        f'font-weight:bold;color:{C["crimson"]};letter-spacing:1px;'
        f'margin-bottom:4px;"><span style="text-decoration:underline;">'
        f'{date}</span>{sub}{h_feast_inline(feast)}</div><br>\n'
    )


# ══════════════════════════════════════════════════════════════════════════
# ENTRY ASSEMBLER
# ══════════════════════════════════════════════════════════════════════════

def h_headlines(heading, links):
    """Compact section: one crimson heading + a list of headline links."""
    rows = ""
    for i, (u, t) in enumerate(links):
        border = (f"border-bottom:1px dotted {C['rule']};"
                  if i < len(links) - 1 else "")
        rows += (
            f'<div style="font-family:Verdana,Arial,sans-serif;font-size:14px;'
            f'font-weight:bold;line-height:1.5;padding:5px 0;{border}">'
            f'<a href="{u}" target="_blank" style="color:{C["link"]};'
            f'text-decoration:none;">{t}</a></div>'
        )
    return (
        f'<table border="0" cellpadding="0" cellspacing="0" width="100%"'
        f' style="margin-bottom:18px;padding-bottom:18px;'
        f'border-bottom:1px dashed {C["rule"]};">'
        f'<tr><td>{h_label(heading)}{rows}</td></tr></table>\n'
    )


# AUTO-REPAIR: if the heuristics drop an item or label, rebuild it from the
# source and splice it back in. Runs inside build_entry_html so news4 AND the
# archive are both repaired. Advisory log shown after the run.
REPAIR_LOG  = []
REPAIR_SEEN = set()
_FID_BOILER = (
    "subscribe","ladder.html","news2.html","news.html","news4.html","bibleinayear",
    "mailto:","groups.google.com","catholicprophecy.info/links",
    "catholicprophecy.info/index","catholicprophecy.info/Catholic",
    "magisterium.com/widgets","docsbot.ai",
)


def _detect_inline_continuation_ids(soup):
    """Return a set of id(<a>) for anchors that are INLINE CONTINUATIONS
    of a preceding <a> in the same block (fewer than 2 <br> tags between
    them in document order). Shared between get_news_items and
    _entry_content_map so the auto-repair pass doesn't undo the skip.

    Catches two structural patterns that shouldn't produce separate
    news cards:
      1. Multi-link quotations (e.g. St. Augustine quote with individual
         words hyperlinked to Catholic Encyclopedia articles)
      2. Parenthetical source citations after a headline link (e.g.
         "On Good and Evil (From Your Life is Worth Living)")
    """
    inline_ids, _ = _detect_inline_and_clusters(soup)
    return inline_ids


def _detect_inline_and_clusters(soup):
    """Like _detect_inline_continuation_ids, but also returns a dict
    mapping each inline anchor's id to its cluster's PRIMARY anchor.
    The primary anchor is the first <a> in the run; every subsequent
    <a> without a <br><br> break belongs to the same cluster."""
    inline_ids = set()
    cluster_of = {}  # id(inline_a) -> primary_a (the object itself)
    prev_a = None
    prev_block = None
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or skip_url(href):
            continue
        upath = href.split("?", 1)[0].lower()
        if upath.endswith((".jpg", ".jpeg", ".png", ".gif",
                           ".webp", ".bmp", ".svg")):
            continue
        # Skip empty-text anchors (KompoZer artifacts like <a href="..."><br></a>).
        # Those aren't visible content — treating them as cluster members
        # would falsely promote the previous link to a cluster primary.
        if not a.get_text(strip=True):
            continue
        # The nearest enclosing <p>/<li> is this document's actual paragraph
        # unit. Two anchors in DIFFERENT such containers are never the same
        # cluster, no matter how few (or zero) <br> tags separate them —
        # e.g. adjacent "</p><p>" items with no <br> at all between them,
        # which the old <br>-count-only heuristic wrongly fused into one
        # cluster (swallowing an entire following news item's content).
        cur_block = a.find_parent(["p", "li"])
        if prev_a is not None:
            if cur_block is not None or prev_block is not None:
                boundary_crossed = cur_block is not prev_block
            else:
                # Neither anchor sits in a <p>/<li> — fall back to the
                # original <br>-count heuristic for older markup shapes
                # that don't use paragraph tags at all.
                boundary_crossed = False
            if not boundary_crossed:
                br = 0
                cur = prev_a.next_element
                while cur is not None and cur is not a:
                    if hasattr(cur, "name") and cur.name == "br":
                        br += 1
                        if br >= 2:
                            break
                    cur = cur.next_element
                if br < 2:
                    inline_ids.add(id(a))
                    cluster_of[id(a)] = prev_a
                    continue  # cluster anchor stays fixed on first link
        prev_a = a
        prev_block = cur_block
    return inline_ids, cluster_of


# Fixed end-of-entry markers (Ladder of Divine Ascent heading, prayer-request
# footer, archive footer) — never part of article prose. Shared with the
# STOP_PHRASES check in get_following_excerpts.
CLUSTER_STOP_PHRASES = (
    "Ladder of Divine Ascent",
    "Prayer request",
    "Have ANY Catholic Question",
    "This month",
)


def _flatten_for_cluster(node, inline_ids, link_color):
    """Recursively serialize a node to prose HTML, preserving inline
    anchors as clickable blue-styled links and dropping any styling
    (bold spans etc.) so the flowing quote reads naturally."""
    if isinstance(node, NavigableString):
        return str(node)
    if not hasattr(node, "name"):
        return ""
    if node.name == "br":
        return " "
    if node.name == "a":
        if id(node) in inline_ids:
            href = (node.get("href") or "").strip()
            text = node.get_text(strip=False)
            if href and text:
                return (f'<a href="{href}" target="_blank" '
                        f'style="color:{link_color};font-weight:bold;">'
                        f'{text}</a>')
            return text
        return ""  # non-inline anchors were meant to stop us — skip if reached
    return "".join(_flatten_for_cluster(c, inline_ids, link_color)
                    for c in node.children)


def _capture_cluster_excerpt(primary_a, inline_ids, link_color):
    """Capture cluster content from primary_a's next sibling onward,
    climbing to parent-sibling scopes as needed, stopping at <br><br>
    or a non-inline anchor. Returns a LIST of paragraph-level HTML
    fragments (primary link + interstitial text + inline anchor
    references) — one entry per source <p> boundary (plus one for any
    inline lead-in before the first <p>) — suitable for passing straight
    through as an item's "excerpts" list, so h_news wraps each fragment
    in its own <p> exactly like every other multi-paragraph item on the
    page, instead of flattening the whole article into a single <p>.
    """
    # Start with the primary anchor rendered as a blue-styled inline link
    _pref = ""
    _pheref = (primary_a.get("href") or "").strip()
    _ptext = primary_a.get_text(strip=False)
    if _pheref and _ptext:
        _pref = (f'<a href="{_pheref}" target="_blank" '
                 f'style="color:{link_color};font-weight:bold;">{_ptext}</a>')

    fragments = []
    current = [_pref] if _pref else []
    state = {"br_run": 0, "stopped": False}

    def _flush():
        nonlocal current
        text = "".join(current).strip()
        if text:
            fragments.append(text)
        current = []

    def _walk_siblings_forward(start):
        nonlocal current
        node = start
        while node is not None and not state["stopped"]:
            if hasattr(node, "name"):
                if node.name == "br":
                    state["br_run"] += 1
                    if state["br_run"] >= 2:
                        state["stopped"] = True
                        return
                    node = node.next_sibling
                    continue
                # Structural section breaks (<hr>) and injected page scripts
                # never belong to article prose — stop before absorbing them.
                if node.name in ("hr", "script", "style"):
                    state["stopped"] = True
                    return
                state["br_run"] = 0
                # A container whose text contains one of the fixed end-of-entry
                # markers (Ladder of Divine Ascent heading, prayer-request
                # footer, archive footer) is never article content — even when
                # its own link (e.g. ladder.html, mailto:) is itself skip_url'd
                # and so wouldn't otherwise trip the "non-inline anchor" check
                # below. Stop here so that footer/boilerplate text can't leak
                # into a cluster excerpt as duplicated prose.
                if hasattr(node, "get_text"):
                    _boundary_t = " ".join(node.get_text(" ", strip=True).split())
                    if any(p in _boundary_t for p in CLUSTER_STOP_PHRASES):
                        state["stopped"] = True
                        return
                if node.name == "a":
                    if id(node) in inline_ids:
                        href = (node.get("href") or "").strip()
                        text = node.get_text(strip=False)
                        if href and text:
                            current.append(
                                f'<a href="{href}" target="_blank" '
                                f'style="color:{link_color};font-weight:bold;">'
                                f'{text}</a>')
                        node = node.next_sibling
                        continue
                    # Non-cluster anchor → new item → stop
                    state["stopped"] = True
                    return
                # Container tag: check for non-inline anchor descendants
                if hasattr(node, "find_all"):
                    for a in node.find_all("a", href=True):
                        if id(a) not in inline_ids:
                            _h = (a.get("href") or "").strip()
                            if _h and not skip_url(_h):
                                state["stopped"] = True
                                return
                # Also stop if this container is a next-item boundary — a
                # bold span whose text is an ALL-CAPS source label
                # (e.g. "FR. ALTIER YOUTUBE:"), or one whose first children
                # are <br><br> starting a new visual block.
                if hasattr(node, "get_text"):
                    _ct = node.get_text(" ", strip=True).strip(" :")
                    _ct_norm = " ".join(_ct.split())
                    if (_ct_norm and 3 <= len(_ct_norm) <= 60
                            and _ct_norm == _ct_norm.upper()
                            and all(c.isalpha() or c in " .'-"
                                    for c in _ct_norm)):
                        state["stopped"] = True
                        return
                if hasattr(node, "children"):
                    _br_lead = 0
                    for _c in node.children:
                        if hasattr(_c, "name") and _c.name == "br":
                            _br_lead += 1
                            if _br_lead >= 2:
                                state["stopped"] = True
                                return
                        elif isinstance(_c, NavigableString) and not str(_c).strip():
                            continue
                        else:
                            break
                if node.name == "p":
                    # A <p> is a distinct source paragraph boundary. Flush
                    # whatever text preceded it (e.g. the primary link's own
                    # lead-in) as its own fragment, then render this <p> as
                    # its own fragment too — preserving the paragraph break
                    # that a flat concatenation would otherwise lose.
                    _flush()
                    _style = node.get("style") or ""
                    _style_norm = _style.replace(" ", "")
                    _flat = _flatten_for_cluster(node, inline_ids, link_color)
                    if _flat.strip():
                        if ("font-weight:bold" in _style_norm
                                and "font-style:italic" in _style_norm):
                            # Mid-article bold-italic subheading (e.g. a
                            # recap of the article title) — preserve the
                            # emphasis instead of flattening to plain prose.
                            fragments.append(
                                f'<span style="font-weight:bold;'
                                f'font-style:italic;">{_flat}</span>')
                        else:
                            _ml = re.search(r'margin-left:\s*(\d+)px', _style)
                            if _ml:
                                # Indented block-quote in the source — keep
                                # the indent as an inline-block so wrapped
                                # lines stay aligned under it.
                                fragments.append(
                                    f'<span style="display:inline-block;'
                                    f'margin-left:{_ml.group(1)}px;">'
                                    f'{_flat}</span>')
                            else:
                                fragments.append(_flat)
                    node = node.next_sibling
                    continue
                current.append(_flatten_for_cluster(node, inline_ids, link_color))
                node = node.next_sibling
            elif isinstance(node, NavigableString):
                current.append(str(node))
                state["br_run"] = 0
                node = node.next_sibling
            else:
                node = node.next_sibling

    # Level 1: walk siblings of primary_a
    _walk_siblings_forward(primary_a.next_sibling)
    # Level 2: climb to each parent's next-siblings until stopped
    _parent = primary_a.parent
    while _parent is not None and not state["stopped"]:
        _walk_siblings_forward(_parent.next_sibling)
        _parent = _parent.parent

    _flush()
    return fragments


def _entry_content_map(entry):
    soup = BeautifulSoup(entry["block"], "html.parser")
    inline_ids = _detect_inline_continuation_ids(soup)
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        # Same filter as get_news_items: inline continuation links are
        # not standalone items, so the repair pass must not treat their
        # absence as a defect to be fixed.
        if id(a) in inline_ids:
            continue
        href = (a.get("href") or "").replace("&amp;", "&").strip()
        text = " ".join(a.get_text(" ", strip=True).split())
        if not href or not text or len(text) < 5 or any(b in href for b in _FID_BOILER):
            continue
        if (href, text) in seen:
            continue
        seen.add((href, text)); links.append((href, text, a))
    labels, seen_l = [], set()
    for sm in soup.find_all("small"):
        t = " ".join(sm.get_text(" ", strip=True).split()).strip(" :")
        a_in = sm.find("a", href=True)
        if a_in is not None:
            at = " ".join(a_in.get_text(" ", strip=True).split())
            t = t.replace(at, "").strip(" :")
            lhref = (a_in.get("href") or "").replace("&amp;", "&").strip()
        else:
            nxt = sm.find_next("a", href=True)
            lhref = (nxt.get("href") or "").replace("&amp;", "&").strip() if nxt else ""
        if not t or len(t) < 3 or len(t) > 160 or t.upper() != t or t in seen_l:
            continue
        seen_l.add(t); labels.append((t, lhref))
    return links, labels


def repair_entry(entry, out):
    ITEM_OPEN = (f'<table border="0" cellpadding="0" cellspacing="0" width="100%"'
                 f' style="margin-bottom:18px;padding-bottom:18px;'
                 f'border-bottom:1px dashed {C["rule"]};">')
    HEAD_DIV  = ('<div style="font-family:Verdana,Arial,sans-serif;font-size:15px;'
                 'font-weight:bold;line-height:1.4;"><a href="')
    links, labels = _entry_content_map(entry)
    repaired = []
    def _norm(s): return " ".join(s.replace("&amp;", "&").split())
    on = _norm(out)
    for i, (href, text, a) in enumerate(links):
        if text in on or len(text) > 200:
            continue
        try:    src_label = get_source_for_link(a) or ""
        except Exception: src_label = ""
        try:    exc = get_following_excerpts(a, get_ladder(entry["block"]), href)
        except Exception: exc = []
        new_item = h_news(src_label, href, text, exc, [])
        ins = -1
        for j in range(i + 1, len(links)):
            p = out.find(f'href="{links[j][0]}"')
            if p == -1:
                p = out.find(f'href="{links[j][0].replace("&", "&amp;")}"')
            if p != -1:
                q = out.rfind(ITEM_OPEN, 0, p)
                if q != -1: ins = q
                break
        if ins == -1:
            lp = out.find('Ladder of Divine Ascent')
            q = out.rfind('<div style="background-color:#f0e8e8;border:1px solid', 0, lp) if lp != -1 else -1
            ins = q if q != -1 else len(out)
        out = out[:ins] + new_item + out[ins:]
        repaired.append(f"restored item: {text[:55]}")
        on = _norm(out)
    for label, lhref in labels:
        if label in on or not lhref:
            continue
        p = out.find(HEAD_DIV + lhref)
        if p == -1:
            p = out.find(HEAD_DIV + lhref.replace("&", "&amp;"))
        if p == -1:
            continue
        if 'letter-spacing:2px;text-transform:uppercase' in out[max(0, p-260):p]:
            continue
        out = out[:p] + h_label(label) + out[p:]
        repaired.append(f"restored label: {label[:55]}")
        on = _norm(out)
    for r in repaired:
        key = (entry["date"], r)
        if key not in REPAIR_SEEN:
            REPAIR_SEEN.add(key); REPAIR_LOG.append(f"{entry['date']} -- {r}")
    return out


def build_entry_html(entry, include_header=True):
    """
    Convert one raw entry dict into modernized HTML.

    include_header=False  for news4 (the page template supplies the date heading)
    include_header=True   for archive prepends (each entry needs its own heading)
    """
    block    = entry["block"]
    date     = entry["date"]
    subtitle = entry["subtitle"]

    out = h_entry_header(date, subtitle, entry.get("feast")) if include_header else ""

    # Scripture verse
    ref, scripture = get_scripture(block)
    if scripture:
        out += h_scripture(ref, scripture)

    # Pope/Saint pull-quote (parchment background blockquote)
    pq_text, pq_attr = get_pull_quote(block)
    if pq_text:
        out += h_pull_quote(pq_text, pq_attr)

    # Collect / prayer block (e.g. feast day collect linked from x.com/twitter.com,
    # or a Church Fathers/papal/saint quote elsewhere in the entry). Built here,
    # then inserted at its source-order position within the news stream below
    # (mirrors the social-post placement logic) rather than always being forced
    # to the top of the entry — a collect quote that appears near the end of the
    # raw bulletin (e.g. after several unrelated news items) should still render
    # near the end, not ahead of items that actually precede it in the source.
    collect_label, collect_url, collect_text = get_collect(block)
    collect_html = ""
    if collect_text:
        collect_html = f"""<div style="background-color:#f0e8e8;border-left:3px solid {C['crimson']};
padding:12px 16px;margin-bottom:22px;">
<div style="font-family:Verdana,Arial,sans-serif;font-size:10px;font-weight:bold;
letter-spacing:2px;text-transform:uppercase;color:{C['crimson']};margin-bottom:6px;">
<a href="{collect_url}" target="_blank" style="color:{C['crimson']};text-decoration:none;">{collect_label}</a>
</div>
<p style="font-family:Verdana,Arial,sans-serif;font-size:13px;font-weight:bold;
color:{C['ink_mid']};margin:0;line-height:1.6;">{collect_text}</p>
</div>"""

    # Social post (X/Twitter self-labeling). Rendering mirrors the source:
    #   body_bold=True  -> small-bold set-apart box (body was inside the bold span)
    #   body_bold=False -> ordinary news card: crimson linked label + normal body
    # Built here, then inserted at its source-order position within the news
    # stream below (the post may sit first, last, or between news items).
    sr_label, sr_url, sr_text, sr_bold = get_social_report(block)
    sr_html = ""
    if sr_text and sr_bold:
        sr_html = f"""<div style="background-color:{C['ladder_bg']};border-left:3px solid {C['crimson']};
padding:12px 16px;margin-bottom:22px;">
<div style="font-family:Verdana,Arial,sans-serif;font-size:10px;font-weight:bold;
letter-spacing:2px;text-transform:uppercase;color:{C['crimson']};margin-bottom:6px;">
<a href="{sr_url}" target="_blank" style="color:{C['crimson']};text-decoration:none;">{sr_label}</a>
</div>
<p style="font-family:Verdana,Arial,sans-serif;font-size:13px;font-weight:bold;
color:{C['ink_mid']};margin:0;line-height:1.6;">{sr_text}</p>
</div>"""
    elif sr_text:
        # Plain-body X post: render like an ordinary news item (crimson source
        # label linked to the tweet + a normal-weight body paragraph).
        sr_html = (
            f'<table border="0" cellpadding="0" cellspacing="0" width="100%"'
            f' style="margin-bottom:18px;padding-bottom:18px;'
            f'border-bottom:1px dashed {C["rule"]};"><tr><td>'
            f'<div style="font-family:Verdana,Arial,sans-serif;font-size:10px;'
            f'font-weight:bold;letter-spacing:2px;text-transform:uppercase;'
            f'color:{C["crimson"]};margin-bottom:4px;">'
            f'<a href="{sr_url}" target="_blank" style="color:{C["crimson"]};'
            f'text-decoration:none;">{sr_label}</a></div>'
            f'<p style="font-family:Verdana,Arial,sans-serif;font-size:15px;'
            f'color:{C["ink_mid"]};line-height:1.7;margin:6px 0 0 0;">{sr_text}</p>'
            f'</td></tr></table>\n'
        )

    # Document-order position of the collect quote / social post, so each
    # lands in the right place relative to the news items around it.
    def _src_pos(u):
        if not u:
            return 10 ** 9
        p = block.find(u)
        if p == -1:
            p = block.find(u.replace("&", "&amp;"))
        return p if p != -1 else 10 ** 9

    _pending = []
    if collect_text:
        _pending.append((_src_pos(collect_url), collect_html))
    if sr_text:
        _pending.append((_src_pos(sr_url), sr_html))
    _pending.sort(key=lambda p: p[0])
    _pending_idx = 0

    # News items
    for item in get_news_items(block):
        # Insert any collect/social block(s) before the first news item that
        # follows them in the source, in their own relative source order.
        _ipos = _src_pos(item.get("url", ""))
        while _pending_idx < len(_pending) and _pending[_pending_idx][0] < _ipos:
            out += _pending[_pending_idx][1]
            _pending_idx += 1
        if item.get("headline_links"):
            out += h_headlines(item["source"], item["headline_links"])
            continue
        out += h_news(
            item["source"],
            item["url"],
            item["link_text"],
            item["excerpts"],
            item["feature_items"],
            item.get("body_bold", False),
        )
    # Anything still pending came after every news item (or there were none).
    while _pending_idx < len(_pending):
        out += _pending[_pending_idx][1]
        _pending_idx += 1

    # Ladder excerpt
    _step_num, _step_title = get_ladder_step(block)
    out += h_ladder(get_ladder(block), _step_num, _step_title)

    # Safety net: restore anything the heuristics dropped
    return repair_entry(entry, out)


# ══════════════════════════════════════════════════════════════════════════
# PAGE TEMPLATE
# ══════════════════════════════════════════════════════════════════════════

STYLE_BLOCK = f"""
    body{{margin:0;padding:0;background-color:{C['bg_dark']};
         background-image:url('vatican.jpg');background-size:cover;
         background-position:center top;}}
    a{{color:{C['link']};}} a:hover{{color:{C['gold']};}}
    @media only screen and (max-width:620px){{
      .two-col-table{{width:100%!important;}}
      .main-col{{width:100%!important;display:block!important;}}
      .sidebar-col{{display:none!important;}}
      .page-wrap{{width:100%!important;padding:0 8px 32px!important;}}
      .content-card{{padding:16px 12px!important;}}
      .masthead-logo{{width:80px!important;height:auto!important;}}
      .masthead-title{{font-size:22px!important;}}
    }}
    @media only screen and (min-width:621px){{
      .sidebar-col{{display:table-cell!important;}}
    }}"""

def masthead():
    return f"""
<table border="0" cellpadding="0" cellspacing="0" width="100%"
       style="padding-top:20px;">
  <tr>
    <td width="120" valign="middle" style="padding-right:16px;">
      <img src="{LOGO_SRC}" class="masthead-logo" alt="Catholic Prophecy"
           width="110" style="display:block;border:0;">
    </td>
    <td valign="middle" style="border-left:3px solid {C['gold']};padding-left:16px;">
      <div style="font-family:Verdana,Arial,sans-serif;font-size:11px;font-weight:bold;
                  letter-spacing:3px;text-transform:uppercase;color:{C['gold_light']};
                  margin-bottom:4px;">Eyedoctor's Site</div>
      <div class="masthead-title"
           style="font-family:Verdana,Arial,sans-serif;font-size:28px;
                  font-weight:bold;color:#f5f0e8;line-height:1.15;
                  text-shadow:0 1px 4px #000;">Tribulation Times</div>
      <div style="font-style:italic;font-weight:bold;color:{C['gold_light']};
                  font-family:Verdana,Arial,sans-serif;font-size:15px;margin-top:2px;">
        Keep your eyes open!&hellip;</div>
    </td>
  </tr>
</table>
<hr style="border:none;border-top:1px solid {C['rule']};margin:14px 0;opacity:0.6;">"""


def nav_bar(third_label, third_url):
    return f"""
<table border="0" cellpadding="0" cellspacing="0" width="100%"
       style="border-bottom:1px solid {C['rule']};padding-bottom:12px;margin-bottom:16px;">
  <tr>
    <td style="font-family:Verdana,Arial,sans-serif;font-size:11px;
               letter-spacing:1px;text-transform:uppercase;">
      <a href="{SUBSCRIBE_URL}"
         style="color:{C['crimson']};text-decoration:none;margin-right:20px;">Subscribe</a>
      <a href="{SUBSCRIBE_URL}"
         style="color:{C['crimson']};text-decoration:none;margin-right:20px;">Unsubscribe</a>
      <a href="{third_url}"
         style="color:{C['crimson']};text-decoration:none;">{third_label}</a>
    </td>
  </tr>
</table>"""


def bible_link():
    # BIBLE_YEAR_URL is stored with a decoded "&" (see main()); re-escape it
    # for the href attribute so the generated markup stays valid HTML.
    _href = BIBLE_YEAR_URL.replace("&", "&amp;")
    return f"""
<p style="margin:0 0 18px 0;font-family:Verdana,Arial,sans-serif;font-size:14px;color:{C['ink_mid']};">
  <strong style="font-family:Verdana,Arial,sans-serif;font-size:11px;
                 text-transform:uppercase;letter-spacing:1px;">
    Read the Bible in One Year</strong>&nbsp;&nbsp;
  <a href="{_href}" target="_blank"
     style="background-color:{C['crimson']};color:#f5f0e8;text-decoration:none;
            padding:4px 12px;font-family:Verdana,Arial,sans-serif;font-size:11px;
            letter-spacing:1px;">{BIBLE_YEAR_LABEL} &rarr;</a>
</p>"""


def footer():
    return f"""
<div style="border-top:1px solid {C['rule']};padding-top:14px;font-family:Verdana,Arial,sans-serif;
            font-size:13px;color:{C['ink_mid']};line-height:1.8;">
  <p style="margin:0 0 6px 0;"><em>Prayer request?</em>&nbsp; Send an email to:
    <a href="mailto:PrayerRequest3@aol.com"
       style="color:{C['link']};">PrayerRequest3@aol.com</a></p>
  <p style="margin:0 0 6px 0;"><em>Have ANY Catholic Question? Just ask Ron Smith at:</em>
    <a href="mailto:hfministry@roadrunner.com"
       style="color:{C['link']};">hfministry@roadrunner.com</a></p>
  <p style="margin:0;">This month&rsquo;s archive:
    <a href="{ARCHIVES_URL}" style="color:{C['link']};">{ARCHIVES_URL}</a></p>
</div>"""


def sidebar():
    return f"""
        <td class="sidebar-col" valign="top" style="display:none;width:240px;padding-left:4px;">
          <div id="vatican-widget-box" style="border:1px solid {C['rule']};overflow:hidden;
                      background-image:url('vatican.jpg');background-size:cover;
                      background-position:center;background-color:{C['bg_dark']};
                      height:320px;">
            <vaticannews-widget fontsize="11" lang="en" background="transparent">
            </vaticannews-widget>
          </div>
        </td>"""


def build_news4(entries):
    """Build the complete news4.html page."""
    first_date  = entries[0]["date"].upper() if entries else "TODAY"
    first_feast = h_feast_inline(entries[0].get("feast")) if entries else ""

    blocks = []
    for i, entry in enumerate(entries):
        # include_header=False: page template already shows the date heading
        blocks.append(build_entry_html(entry, include_header=False))
        if i < len(entries) - 1:
            blocks.append(h_divider())

    main_html = "\n".join(blocks)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="600; URL={ARCHIVES_URL}">
  <meta name="MSSmartTagsPreventParsing" content="TRUE">
  <meta name="description" content="This daily updated web page examines current events
    in light of Biblical and Catholic revelation. Included are a review of Catholic
    prophecy, Warning resources, and links to other prophecy sites.">
  <meta name="keywords" content="catholic prophecy,prophecy,catholic,bible,tribtimes,
    tribulation,end times,eschatology,antichrist,rapture,watch,Jesus,revelation,Pope,
    Mary,Christian,signs in the heavens,the warning,seals,Jubilee 2000,visionary,Medugorje">
  <title>Eyedoctor's Site: The Tribulation Times</title>
  <!-- Vatican News widget must load before body -->
  <script src="https://www.vaticannews.va/widget.js"></script>
  <!-- Google Analytics 4 -->
  <script async src="https://www.googletagmanager.com/gtag/js?id={GA_ACCOUNT}"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', '{GA_ACCOUNT}');
  </script>
  <!--
    STYLE NOTES:
    - No CSS custom properties (unsupported in Outlook/Gmail)
    - No Google Fonts (blocked by email clients)
    - No CSS Grid or Flexbox for layout (use tables instead)
    - All layout-critical styles are ALSO inlined on elements
    - This <style> block improves browser/mobile rendering
    - Email clients that strip <style> fall back to inline styles
  -->
  <style>{STYLE_BLOCK}
  </style>
</head>
<body style="margin:0;padding:0;background-color:{C['bg_dark']};
             background-image:url('vatican.jpg');background-size:cover;
             background-position:center top;
             font-family:Verdana,Arial,sans-serif;">

<div class="page-wrap" style="max-width:860px;margin:0 auto;padding:0 16px 48px;">

  {masthead()}

  <!-- ── CONTENT CARD ── -->
  <div class="content-card"
       style="background-color:{C['parchment']};border:1px solid {C['rule']};
              padding:24px 28px;">

    <!-- Nav bar -->
    {nav_bar("View Archives", ARCHIVES_URL)}

    <!-- Bible in a Year -->
    {bible_link()}

    <!-- Date heading -->
    <div style="font-family:Verdana,Arial,sans-serif;font-size:13px;font-weight:bold;
                color:{C['crimson']};letter-spacing:1px;border-bottom:1px solid {C['rule']};
                padding-bottom:6px;margin-bottom:16px;text-transform:uppercase;">
      {first_date}{first_feast}
    </div>

    <!-- TWO-COLUMN LAYOUT (table for email compatibility) -->
    <table class="two-col-table" border="0" cellpadding="0" cellspacing="0" width="100%">
      <tr>
        <!-- MAIN CONTENT COLUMN -->
        <td class="main-col" valign="top" style="width:580px;padding-right:24px;">
          {main_html}
          {footer()}
        </td>
        <!-- /main-col -->
        <!-- SIDEBAR COLUMN (Vatican News widget) - hidden in email, shown on desktop via CSS -->
        {sidebar()}
      </tr>
    </table>
    <!-- /two-col -->

  </div><!-- /content-card -->

</div><!-- /page-wrap -->
<script>
  /* On phones the sidebar is hidden, so move the single Vatican News
     widget to the bottom of the page (the old site's behavior). */
  if (window.innerWidth <= 620) {{
    var box = document.getElementById('vatican-widget-box');
    if (box) {{
      box.style.height = '260px';
      box.style.width = '92%';
      box.style.maxWidth = '480px';
      box.style.margin = '20px auto 28px';
      document.body.appendChild(box);
    }}
  }}
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════
# ARCHIVE APPEND
# ══════════════════════════════════════════════════════════════════════════

def find_inject_point(archive_html):
    """
    Find the character position where new entries should be inserted.
    Priority:
      1. Explicit INJECT_MARKER comment
      2. Just after the banner image (pict10.jpg) closing tag
      3. Just before the first existing date heading in the content area
    """
    idx = archive_html.find(INJECT_MARKER)
    if idx != -1:
        return idx + len(INJECT_MARKER)

    m = re.search(
        r'(<img[^>]*pict10\.jpg[^>]*>)\s*</div>',
        archive_html, re.IGNORECASE
    )
    if m:
        return m.end()

    m2 = re.search(
        r'<div[^>]*text-decoration:underline[^>]*>'
        r'(?:January|February|March|April|May|June|July|August|'
        r'September|October|November|December)\s+\d{1,2},\s+\d{4}',
        archive_html, re.IGNORECASE
    )
    if m2:
        return m2.start()

    # Fallback 3b: the script's OWN heading format puts the underline on an
    # inner <span>, not the <div> — the pattern above never matches it. Find
    # the span, then back up to its enclosing <div> so the injection lands
    # before the whole heading rather than inside it.
    m3 = re.search(
        r'<span[^>]*text-decoration:\s*underline[^>]*>\s*'
        r'(?:January|February|March|April|May|June|July|August|'
        r'September|October|November|December)\s+\d{1,2},\s+\d{4}',
        archive_html, re.IGNORECASE
    )
    if m3:
        d = archive_html.rfind('<div', 0, m3.start())
        return d if d != -1 else m3.start()

    return -1


def normalize_head_meta(html):
    """Strip invalid/duplicate <meta> tags from the <head> that the W3C
    validator flags:
      - <meta http-equiv="Expires" ...>  (not a valid http-equiv value)
      - <meta http-equiv="Pragma" ...>   (not a valid http-equiv value)
      - <meta http-equiv="content-type" ...> WHEN a <meta charset> is also
        present (a document must not declare both)
    Returns (possibly modified html, True/False whether anything changed).
    """
    original = html

    # Drop invalid http-equiv values entirely (whole tag, whitespace-tolerant).
    for bad_value in ("Expires", "Pragma"):
        html = re.sub(
            r'[ \t]*<meta\s+http-equiv=["\']' + bad_value +
            r'["\'][^>]*>\s*\n?',
            '', html, flags=re.IGNORECASE)

    # If both a charset meta and an http-equiv="content-type" meta exist,
    # drop the content-type one (charset is the modern, sufficient form).
    if re.search(r'<meta\s+charset=', html, flags=re.IGNORECASE):
        html = re.sub(
            r'[ \t]*<meta\s+http-equiv=["\']content-type["\'][^>]*>\s*\n?',
            '', html, flags=re.IGNORECASE)

    return html, (html != original)


def ensure_responsive_images(html):
    """Make sure the archive's <style> block scales images to the viewport.
    The legacy KompoZer template hard-codes banner/divider widths (e.g.
    pict10.jpg at 776px, line.gif at 750px), which overflow a ~380px phone
    screen and crop the banner. A global `img { max-width:100%; height:auto }`
    rule fixes this. Injected once, idempotent on re-runs.
    Returns (possibly modified html, True/False whether anything changed).
    """
    if re.search(r'img\s*\{[^}]*max-width\s*:\s*100%', html):
        return html, False
    m = re.search(r'</style>', html, flags=re.IGNORECASE)
    if not m:
        return html, False
    rule = ("\n/* Responsive images: keep wide banners/dividers within the "
            "phone viewport */\nimg {\n    max-width: 100%;\n    height: auto;\n}\n")
    html = html[:m.start()] + rule + html[m.start():]
    return html, True


def prepend_to_archive(archive_path, entries):
    """Prepend new entries to the modern news2.html archive."""
    archive_path = Path(archive_path)
    if not archive_path.exists():
        print(f"  '{archive_path}' not found — skipping archive update.")
        return False

    html = archive_path.read_text(encoding="utf-8", errors="replace")

    # HEAD CLEANUP: strip any invalid/duplicate meta tags left over from
    # older versions of this file or manual edits, so the archive stays
    # W3C-valid even if it wasn't when we opened it.
    html, head_fixed = normalize_head_meta(html)
    if head_fixed:
        print("  Cleaned up invalid/duplicate <meta> tags in archive head.")

    html, css_fixed = ensure_responsive_images(html)
    if css_fixed:
        print("  Added responsive-image CSS to archive (mobile banner fix).")

    # RE-RUN PROTECTION: skip any entry whose dated heading is already in
    # the archive, so running the script twice cannot duplicate a day, and
    # a multi-day news.html only injects the days not yet archived.
    def _already_archived(date_str):
        return bool(re.search(
            r'text-decoration:\s*underline[^>]*>\s*' + re.escape(date_str),
            html))
    fresh = [e for e in entries if not _already_archived(e["date"])]
    skipped = len(entries) - len(fresh)
    if skipped:
        print(f"  {skipped} entr{'y' if skipped == 1 else 'ies'} already in "
              f"archive — skipped (re-run protection).")
    if not fresh:
        print("  Nothing new to add — archive left untouched.")
        return True

    if BACKUP_ARCHIVE:
        stamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = archive_path.with_name(f"news2_backup_{stamp}.html")
        shutil.copy2(archive_path, backup)
        print(f"  Backup saved: {backup.name}")
        # BACKUP ROTATION: keep only the 10 newest backups.
        old_backups = sorted(archive_path.parent.glob("news2_backup_*.html"))[:-10]
        for b in old_backups:
            try:
                b.unlink()
            except OSError:
                pass

    # Build what to inject (with headers, since archive needs date headings)
    parts = []
    for entry in fresh:
        parts.append(build_entry_html(entry, include_header=True))
    parts.append(h_divider())
    new_block = "\n" + "\n".join(parts) + "\n"

    idx = find_inject_point(html)
    if idx == -1:
        print("  WARNING: Could not find injection point in archive.")
        print(f"  Open {archive_path.name} and add this line where new entries go:\n")
        print(f"    {INJECT_MARKER}\n")
        print("  Then run the script again.")
        return False

    if INJECT_MARKER in html:
        updated = html[:idx] + new_block + html[idx:]
    else:
        updated = html[:idx] + INJECT_MARKER + "\n" + new_block + html[idx:]

    # ATOMIC WRITE: write to a temp file first, then replace. A crash or
    # power loss mid-write can no longer leave a truncated news2.html.
    tmp = archive_path.with_name(archive_path.name + ".tmp")
    tmp.write_text(updated, encoding="utf-8")
    tmp.replace(archive_path)
    return True


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def fidelity_check(entry, out_html):
    """Compare the newest source entry against the generated page; warn about any
    link, headline, or source label that did not survive. Advisory only."""
    out_norm = " ".join(out_html.replace("&amp;", "&").split())
    soup = BeautifulSoup(entry["block"], "html.parser")
    # Inline continuation links are not standalone items (see
    # _detect_inline_continuation_ids). Don't flag them as missing —
    # they were intentionally not rendered as separate cards.
    _inline_ids = _detect_inline_continuation_ids(soup)
    missing_links, total, seen = [], 0, set()
    for a in soup.find_all("a", href=True):
        if id(a) in _inline_ids:
            continue
        href = (a.get("href") or "").replace("&amp;", "&").strip()
        text = " ".join(a.get_text(" ", strip=True).split())
        if not href or not text or len(text) < 5 or any(b in href for b in _FID_BOILER):
            continue
        if (href, text) in seen:
            continue
        seen.add((href, text)); total += 1
        if href not in out_norm or text not in out_norm:
            missing_links.append((text[:60], href))
    missing_labels, lbl_total, seen_l = [], 0, set()
    for sm in soup.find_all("small"):
        t = " ".join(sm.get_text(" ", strip=True).split()).strip(" :")
        a_in = sm.find("a")
        if a_in is not None:
            at = " ".join(a_in.get_text(" ", strip=True).split())
            t = t.replace(at, "").strip(" :")
        if not t or len(t) < 3 or len(t) > 160 or t.upper() != t or t in seen_l:
            continue
        seen_l.add(t); lbl_total += 1
        if t not in out_norm:
            missing_labels.append(t[:70])
    print(f"\nFidelity check ({entry['date']}):")
    print(f"  Links:  {total - len(missing_links)}/{total} carried over")
    print(f"  Labels: {lbl_total - len(missing_labels)}/{lbl_total} carried over")
    if not missing_links and not missing_labels:
        print("  All content accounted for \u2713")
        return True
    for txt, href in missing_links:
        print(f"  \u26a0 MISSING ITEM : {txt}\n                   {href}")
    for t in missing_labels:
        print(f"  \u26a0 MISSING LABEL: {t}")
    print("  \u26a0 Review the page before uploading.")
    return False


def main():
    input_path = Path(INPUT_FILE)
    if not input_path.exists():
        print(f"\nERROR: '{INPUT_FILE}' not found.")
        print("Place this script in the same folder as your news.html.\n")
        sys.exit(1)

    print(f"\nReading {INPUT_FILE} ...")
    # Strict UTF-8 first; if the file is legacy Windows-1252 / ISO-8859-1
    # (the old news.html encoding bug), fall back explicitly instead of
    # silently mangling characters into U+FFFD replacement marks.
    _data = input_path.read_bytes()
    try:
        raw = _data.decode("utf-8")
    except UnicodeDecodeError:
        raw = _data.decode("cp1252", errors="replace")
        print("  Note: news.html is not valid UTF-8 — decoded as Windows-1252.")

    # Faithful Bible-in-a-Year button: read the visible link from the source
    # instead of relying on the hardcoded month constants above.
    global BIBLE_YEAR_URL, BIBLE_YEAR_LABEL
    _bm = re.search(
        r'<a[^>]+href="(https?://bibleinayearonline\.com/([a-z]+)-oyb[^"]*)"[^>]*>'
        r'\s*https?://bibleinayearonline', raw)
    if _bm:
        BIBLE_YEAR_URL   = _bm.group(1).replace("&amp;", "&")
        BIBLE_YEAR_LABEL = _bm.group(2).capitalize() + " Readings"
        print(f"  Bible-in-a-Year button: {BIBLE_YEAR_LABEL}")

    print("Extracting entries ...")
    entries = extract_entries(raw)
    if not entries:
        print("ERROR: No dated entries found.")
        print("The file should contain dates like 'May 1, 2026'.")
        sys.exit(1)

    print(f"Found {len(entries)} entr{'y' if len(entries)==1 else 'ies'}: "
          f"{', '.join(e['date'] for e in entries)}")

    # Build news4.html
    print(f"\nBuilding {OUTPUT_FILE} ...")
    page_html = build_news4(entries)
    _out = Path(OUTPUT_FILE)
    _tmp = _out.with_name(_out.name + ".tmp")
    _tmp.write_text(page_html, encoding="utf-8")
    _tmp.replace(_out)
    print(f"  Written: {OUTPUT_FILE}")

    fidelity_check(entries[0], page_html)
    if REPAIR_LOG:
        print("  Auto-repairs applied (give these a quick look in the preview):")
        for r in REPAIR_LOG:
            print(f"    \u2022 {r}")
    try:
        from datetime import date as _d
        _t = _d.today(); _exp = f"{_t.strftime('%B')} {_t.day}, {_t.year}"
        if entries[0]["date"] != _exp:
            print(f"  Note: newest entry is dated {entries[0]['date']} (today is {_exp}).")
    except Exception:
        pass

    # Update archive
    archive_result = "skipped (AUTO_APPEND_TO_ARCHIVE = False)"
    if AUTO_APPEND_TO_ARCHIVE:
        print(f"\nUpdating {ARCHIVE_FILE} ...")
        ok = prepend_to_archive(ARCHIVE_FILE, entries)
        archive_result = "updated \u2713" if ok else "skipped (see warning above)"

    print(f"""
+{'='*54}+
|  Conversion complete                                   |
+{'='*54}+
|  {OUTPUT_FILE:<52}|
|    Modern daily page -- preview, then upload           |
|                                                        |
|  {ARCHIVE_FILE} -- {archive_result:<35}|
+{'='*54}+
|  Steps:                                                |
|  1. Preview {OUTPUT_FILE} in your browser             |
|  2. Preview {ARCHIVE_FILE} to confirm placement       |
|  3. Upload both files to your server                   |
+{'='*54}+
""")


if __name__ == "__main__":
    main()
