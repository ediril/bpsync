"""Expand classic-editor content the way WordPress displays it.

The classic editor stores paragraphs as blank-line-separated text and line
breaks as single newlines; WordPress's `wpautop` display filter adds the `<p>`
and `<br />` tags. This is an independent implementation of that behavior,
checked against WordPress's own output in characterization runs.
"""

from __future__ import annotations

import re

BLOCKS = (
    "table|thead|tfoot|caption|col|colgroup|tbody|tr|td|th|div|dl|dd|dt|ul|ol|li|"
    "pre|form|map|area|blockquote|address|math|style|p|h[1-6]|hr|fieldset|legend|"
    "section|article|aside|hgroup|header|footer|nav|figure|figcaption|details|menu|"
    "summary"
)
BLOCK_TAG = rf"</?(?:{BLOCKS})[^>]*>"
PRE_CONTENT = re.compile(r"(<pre\b[^>]*>)(.*?)(</pre>)", re.S | re.I)
KEPT_NEWLINES = re.compile(r"<(script|style|svg|math)\b.*?</\1>", re.S | re.I)
MARKUP = re.compile(r"<!--.*?-->|<[^>]*>", re.S)
PRE_PLACEHOLDER = "\x00pre{}\x00"
NEWLINE_PLACEHOLDER = "\x01"


def _sub(pattern: str, replacement: str, text: str) -> str:
    return re.sub(pattern, replacement, text, flags=re.I)


def autop(text: str) -> str:
    if not text.strip():
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    preformatted: list[str] = []

    def hide_pre(match: re.Match[str]) -> str:
        preformatted.append(match.group(2))
        return (
            match.group(1)
            + PRE_PLACEHOLDER.format(len(preformatted) - 1)
            + match.group(3)
        )

    def keep_newlines(match: re.Match[str]) -> str:
        return match.group(0).replace("\n", NEWLINE_PLACEHOLDER)

    text = PRE_CONTENT.sub(hide_pre, text)
    # Newlines inside a tag or comment belong to that markup, not to the text.
    text = MARKUP.sub(keep_newlines, text)
    text = _sub(r"<br\s*/?>\s*<br\s*/?>", "\n\n", text)
    text = _sub(rf"(<(?:{BLOCKS})[\s/>])", r"\n\n\1", text)
    text = _sub(rf"(</(?:{BLOCKS})>)", r"\1\n\n", text)
    text = _sub(r"(<hr\s*/?>)", r"\1\n\n", text)
    chunks = (chunk.strip() for chunk in re.split(r"\n\s*\n", text))
    text = "".join(f"<p>{chunk}</p>\n" for chunk in chunks if chunk)

    text = _sub(r"<p>\s*</p>", "", text)
    text = _sub(r"<p>([^<]+)</(div|address|form)>", r"<p>\1</p></\2>", text)
    text = _sub(rf"<p>\s*({BLOCK_TAG})\s*</p>", r"\1", text)
    text = _sub(r"<p>(<li.+?)</p>", r"\1", text)
    text = _sub(r"<p><blockquote([^>]*)>", r"<blockquote\1><p>", text)
    text = text.replace("</blockquote></p>", "</p></blockquote>")
    text = _sub(rf"<p>\s*({BLOCK_TAG})", r"\1", text)
    text = _sub(rf"({BLOCK_TAG})\s*</p>", r"\1", text)

    text = KEPT_NEWLINES.sub(keep_newlines, text)
    text = _sub(r"<br\s*/?>", "<br />", text)
    text = re.sub(r"(?<!<br />)\s*\n", "<br />\n", text)
    text = _sub(rf"({BLOCK_TAG})\s*<br />", r"\1", text)
    text = _sub(
        r"<br />(\s*</?(?:p|li|div|dl|dd|dt|th|pre|td|ul|ol)[^>]*>)", r"\1", text
    )
    text = re.sub(r"\n</p>$", "</p>", text)

    text = text.replace(NEWLINE_PLACEHOLDER, "\n")
    for index, content in enumerate(preformatted):
        text = text.replace(PRE_PLACEHOLDER.format(index), content)
    return text
