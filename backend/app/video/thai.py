"""Thai line-breaking, done once so every renderer agrees.

Thai is written without spaces between words, so anything that lays out text
has to know where words end. Two of our renderers could not:

  * Chromium (tips cards) segments correctly on a dev macOS build but NOT in
    the render image, which broke `กลุ่มคำ` as `ก` + `ลุ่มคำ` in production
    while the identical card rendered correctly locally. We cannot depend on
    which ICU data a given Chromium build happens to ship.
  * libass (burned subtitles) has no Thai segmentation at all, and the
    character-count wrapper that stood in for it broke mid-word.

So we segment in Python and hand each renderer explicit break opportunities:
zero-width spaces for HTML, hard line breaks for SRT. Same input, same
breaks, every environment.
"""

from functools import lru_cache

# Characters that must never START a line: they attach to the word before
# them. pythainlp tokenizes `ขั้นๆ` as `ขั้น` + `ๆ`, so wrapping purely on
# token boundaries would strand the repetition mark alone on its own line --
# exactly the defect seen in a production demo subtitle.
_NO_BREAK_BEFORE = frozenset(
    "ๆ"   # MAIYAMOK, repetition mark
    "ฯ"   # PAIYANNOI, abbreviation mark
    "”’)]}"
    ".,!?;:"
)

ZWSP = "​"

# Zero-advance Thai combining vowel/tone marks (category Mn). They render on
# top of the preceding base character, so they must never be counted toward a
# line's width budget nor separated from their base.
_COMBINING = frozenset(
    "ัิีึืฺุู"
    "็่้๊๋์ํ๎"
)


@lru_cache(maxsize=1)
def _tokenizer():
    """Import pythainlp lazily and once.

    Kept out of module import so that importing this module (and anything
    that transitively imports it) never pays the dictionary load, and so a
    missing/broken pythainlp degrades at the call site rather than breaking
    collection of the whole app.
    """
    from pythainlp.tokenize import word_tokenize

    return word_tokenize


def words(text: str) -> list[str]:
    """Segment `text` into chunks that may be separated by a line break.

    Tokens that must not start a line are merged into the preceding chunk, so
    every boundary this returns is a legal place to break.
    """
    if not text:
        return []
    try:
        tokens = _tokenizer()(text, engine="newmm")
    except Exception:
        # Never fail a render over line-breaking. Falling back to one chunk
        # reproduces the pre-segmentation behaviour (the caller's width
        # budget still applies) rather than dropping the text.
        return [text]

    chunks: list[str] = []
    for token in tokens:
        if chunks and token and token[0] in _NO_BREAK_BEFORE:
            chunks[-1] += token
        else:
            chunks.append(token)
    return chunks


def clusters(text: str) -> list[str]:
    """Split into user-visible clusters: a base character plus any trailing
    zero-width combining marks. Used to measure width, since combining marks
    take no horizontal space.
    """
    out: list[str] = []
    for ch in text:
        if out and ch in _COMBINING:
            out[-1] += ch
        else:
            out.append(ch)
    return out


def width(text: str) -> int:
    """Advance-bearing cluster count -- what a line's width budget spends."""
    return len(clusters(text))


def _wrap_words(phrase: str, max_width: int) -> list[str]:
    """Word-wrap a single space-free phrase. Breaks only where `words()`
    allows. A chunk wider than the whole budget gets its own line rather than
    being split: an overhanging line beats a word broken in half.
    """
    lines: list[str] = []
    current = ""
    for chunk in words(phrase):
        if not current:
            current = chunk
        elif width(current) + width(chunk) <= max_width:
            current += chunk
        else:
            lines.append(current)
            current = chunk
    if current:
        lines.append(current)
    return lines or [phrase]


def wrap(text: str, max_width: int) -> list[str]:
    """Wrap `text` into lines of at most `max_width` clusters.

    Spaces outrank word boundaries. Thai runs words together but still uses
    spaces to separate phrases, so a space is the most natural place to break
    a subtitle -- breaking mid-phrase when a phrase boundary was available
    reads worse even though both are legal. So this fills by phrase first and
    only segments into words when a single phrase cannot fit on a line.
    """
    if not text.strip():
        return []

    lines: list[str] = []
    current = ""
    for phrase in (p for p in text.split(" ") if p.strip()):
        candidate = phrase if not current else f"{current} {phrase}"
        if width(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if width(phrase) <= max_width:
            current = phrase
        else:
            wrapped = _wrap_words(phrase, max_width)
            lines.extend(wrapped[:-1])
            current = wrapped[-1]
    if current:
        lines.append(current)
    return lines


def with_break_hints(text: str) -> str:
    """Insert zero-width spaces at legal break points, for HTML renderers.

    A browser will only break at these, so layout no longer depends on
    whether its ICU build carries Thai dictionary data. ZWSP is invisible and
    zero-width, so it changes nothing when the text fits on one line.
    """
    chunks = words(text)
    return ZWSP.join(chunks) if len(chunks) > 1 else text
