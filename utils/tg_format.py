"""
utils/tg_format.py — normalize LLM output into safe Telegram HTML.

LLMs (gpt-oss especially) ignore "use Telegram HTML, not Markdown" instructions
and emit a MIX of HTML tags and Markdown (**bold**, `* bullets`, `# headers`),
plus bare "<"/">" from math ("a < b"). Markdown does not render in Telegram HTML,
a bare "<" gets misparsed as a tag, and the mix can make Telegram reject the whole
message (which surfaced as literal <b>/&lt;b&gt; via a broken escape-fallback).
These helpers make output robust regardless of what the model emits:

  * markdown_to_telegram_html — convert the Markdown the model emits into HTML/text.
  * render_for_telegram — full pipeline: markdown->HTML, keep only supported tags,
    escape stray <>& so bare "<" is not treated as a tag, balance tags.
  * strip_to_plain — last-resort fallback: strip real tags + leftover markdown to
    clean plain text, so a parse failure never shows literal <b> or &lt;b&gt;.
"""

import html
import re

# Tags Telegram accepts in HTML parse mode (plus a few we normalise into / wrap with).
_ALLOWED = ("b", "i", "u", "s", "strong", "em", "code", "pre", "a", "tg-spoiler", "blockquote")
_ALLOWED_SET = set(_ALLOWED)

# A well-formed supported tag (opening/closing, optional attributes).
_ALLOWED_TAG_RE = re.compile(r"</?(?:" + "|".join(_ALLOWED) + r")(?:\s[^<>]*)?>", re.IGNORECASE)
# Any well-formed HTML-ish tag (used to drop unsupported tags / strip to plain).
_ANY_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9-]*(?:\s[^<>]*)?/?>")
# An existing character entity, so we do not double-escape "&".
_ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")


def markdown_to_telegram_html(text: str) -> str:
    """Convert the Markdown LLMs emit despite HTML-only instructions."""
    if not text:
        return text
    # Code spans first, so their contents are not touched by the other rules.
    text = re.sub(r"`([^`\n]+)`", lambda m: f"<code>{m.group(1)}</code>", text)
    # Bold: **text** and __text__
    text = re.sub(r"\*\*([^\n*]+?)\*\*", lambda m: f"<b>{m.group(1)}</b>", text)
    text = re.sub(r"__([^\n_]+?)__", lambda m: f"<b>{m.group(1)}</b>", text)
    # Headers: leading #..###### on their own line -> bold
    text = re.sub(
        r"(?m)^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$",
        lambda m: f"<b>{m.group(1)}</b>",
        text,
    )
    # Bullets: line-leading * / - / + followed by whitespace -> bullet dot
    text = re.sub(r"(?m)^([ \t]*)[*\-+][ \t]+", lambda m: f"{m.group(1)}\u2022 ", text)
    return text


def _convert_sup_sub(text: str) -> str:
    text = re.sub(r"<sup>(.*?)</sup>", lambda m: f"^{m.group(1)}", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<sub>(.*?)</sub>", lambda m: f"_{m.group(1)}", text, flags=re.IGNORECASE | re.DOTALL)
    return text


def _escape_and_filter_tags(text: str) -> str:
    """Keep supported tags verbatim, drop unsupported tags (keep their inner text),
    and escape stray '<' '>' '&' so a bare '<' in "a < b" is not parsed as a tag."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "<":
            m = _ALLOWED_TAG_RE.match(text, i)
            if m:
                out.append(m.group(0))   # keep a supported tag verbatim
                i = m.end()
                continue
            m2 = _ANY_TAG_RE.match(text, i)
            if m2:
                i = m2.end()             # drop an unsupported tag, keep surrounding text
                continue
            out.append("&lt;")           # stray '<'
            i += 1
        elif c == ">":
            out.append("&gt;")           # stray '>' (real tags were consumed above)
            i += 1
        elif c == "&":
            if _ENTITY_RE.match(text, i):
                out.append("&")          # keep an existing entity's '&'
            else:
                out.append("&amp;")
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def balance_html_tags(text: str) -> str:
    """Balance supported tags: ignore a mismatched closing tag, auto-close the rest.
    Used per-chunk when a long message is split (a split may leave a tag open)."""
    out: list[str] = []
    stack: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "<":
            end = text.find(">", i + 1)
            if end == -1:
                out.append(text[i:])
                break
            inner = text[i + 1:end].strip()
            is_closing = inner.startswith("/")
            parts = (inner[1:] if is_closing else inner).split()
            tag_name = parts[0].lower() if parts else ""
            if tag_name in _ALLOWED_SET:
                if is_closing:
                    if stack and stack[-1] == tag_name:
                        stack.pop()
                        out.append(text[i:end + 1])
                    # else ignore mismatched close
                else:
                    stack.append(tag_name)
                    out.append(text[i:end + 1])
            i = end + 1
        else:
            out.append(text[i])
            i += 1
    while stack:
        out.append(f"</{stack.pop()}>")
    return "".join(out)


def render_for_telegram(text: str) -> str:
    """Full pipeline: Markdown -> Telegram HTML, keep supported tags, escape stray
    <>&, balance tags. The result is safe to send with parse_mode=HTML."""
    text = markdown_to_telegram_html(text or "")
    text = _convert_sup_sub(text)
    text = _escape_and_filter_tags(text)
    return balance_html_tags(text)


def strip_to_plain(text: str) -> str:
    """Last-resort fallback: strip real tags + leftover markdown to clean plain text,
    so a parse failure degrades to readable text (never literal <b> or &lt;b&gt;).
    A bare '<' in "a < b" is preserved (the tag regex requires a letter after '<')."""
    if not text:
        return text
    t = _ANY_TAG_RE.sub("", text)                              # remove real tags only
    t = html.unescape(t)                                        # &lt; -> <  (no visible entities)
    t = re.sub(r"\*\*|__", "", t)                               # leftover bold markers
    t = re.sub(r"(?m)^([ \t]*)[*\-+][ \t]+", "\\1\u2022 ", t)   # bullets -> dot
    return t.strip()
