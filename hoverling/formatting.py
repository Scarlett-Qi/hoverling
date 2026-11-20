"""Render common AI Markdown into escaped GTK/Pango markup.

No HTML is evaluated and links remain ordinary text. The separate plain-text
representation is used for copying, so presentation markers do not leak into
the clipboard. Selection previews never pass through this renderer.
"""
from dataclasses import dataclass
from html import escape
import re


@dataclass(frozen=True)
class FormattedText:
    text: str
    markup: str


def _inline(text: str, depth: int = 0) -> FormattedText:
    if depth >= 8:
        return FormattedText(text, escape(text))
    plain, markup = [], []
    pos = 0
    while pos < len(text):
        char = text[pos]
        if char == "\\" and pos + 1 < len(text) and text[pos + 1] in r"\`*_{}[]()#+-.!>~":
            literal = text[pos + 1]
            plain.append(literal)
            markup.append(escape(literal))
            pos += 2
            continue
        if char == "`":
            end_run = pos
            while end_run < len(text) and text[end_run] == "`":
                end_run += 1
            marker = text[pos:end_run]
            end = text.find(marker, end_run)
            if end >= 0:
                literal = text[end_run:end]
                plain.append(literal)
                markup.append("<tt>" + escape(literal) + "</tt>")
                pos = end + len(marker)
                continue
        if char == "[":
            link = re.match(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", text[pos:])
            if link:
                title = _inline(link.group(1), depth + 1)
                url = link.group(2)
                plain.append(title.text + " (" + url + ")")
                markup.append(title.markup + " (" + escape(url) + ")")
                pos += link.end()
                continue
        matched = False
        for marker, tag in (("**", "b"), ("__", "b"), ("~~", "s"), ("*", "i"), ("_", "i")):
            if not text.startswith(marker, pos):
                continue
            if len(marker) == 1 and pos and text[pos - 1].isalnum():
                continue
            end = text.find(marker, pos + len(marker))
            if end < 0:
                continue
            inner = text[pos + len(marker):end]
            # Model output often has '**译文： **', with a space before the
            # closing marker. Accept that common variant deliberately.
            if not inner.strip():
                continue
            if len(marker) == 1 and (inner[0].isspace() or inner[-1].isspace()):
                continue
            if marker == "_" and end + 1 < len(text) and text[end + 1].isalnum():
                continue
            formatted = _inline(inner.strip() if len(marker) == 2 else inner, depth + 1)
            plain.append(formatted.text)
            markup.append("<" + tag + ">" + formatted.markup + "</" + tag + ">")
            pos = end + len(marker)
            matched = True
            break
        if matched:
            continue
        plain.append(char)
        markup.append(escape(char))
        pos += 1
    return FormattedText("".join(plain), "".join(markup))


def render_markdown(text: str) -> FormattedText:
    """Support headings, emphasis, lists, code, quotes and readable links.

    This is a small display subset, not a web browser or a full CommonMark
    implementation. Malformed or unsupported syntax remains readable text.
    """
    if len(text) > 50000:
        return FormattedText(text, escape(text))
    plain, markup = [], []
    fence = None
    for line in text.split("\n"):
        fenced = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if fence is not None:
            if fenced and fenced.group(1)[0] == fence[0] and len(fenced.group(1)) >= len(fence) and not fenced.group(2).strip():
                fence = None
                continue
            plain.append(line)
            markup.append("<tt>" + escape(line) + "</tt>")
            continue
        if fenced:
            fence = fenced.group(1)
            continue
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)(?:\s+#+)?\s*$", line)
        bullet = re.match(r"^(\s*)[-+*]\s+(.+)$", line)
        quote = re.match(r"^\s*>\s?(.*)$", line)
        if heading:
            formatted = _inline(heading.group(1))
            plain.append(formatted.text)
            markup.append("<b>" + formatted.markup + "</b>")
        elif re.fullmatch(r"\s*(?:-{3,}|\*{3,}|_{3,})\s*", line):
            plain.append("────────")
            markup.append("────────")
        elif bullet:
            formatted = _inline(bullet.group(2))
            prefix = bullet.group(1) + "• "
            plain.append(prefix + formatted.text)
            markup.append(escape(prefix) + formatted.markup)
        elif quote:
            formatted = _inline(quote.group(1))
            plain.append("│ " + formatted.text)
            markup.append("│ <i>" + formatted.markup + "</i>")
        else:
            formatted = _inline(line)
            plain.append(formatted.text)
            markup.append(formatted.markup)
    return FormattedText("\n".join(plain), "\n".join(markup))
