# Content format

Date: 2026-10-25

## Decision

Each post is one Markdown file with YAML frontmatter under `posts/`. The
frontmatter holds the platform post ID once the file is linked to a post, plus
title, slug, date, status, categories, and tags. Categories and tags are names;
the WordPress adapter resolves them to term IDs.

### Markdown dialect

The body is CommonMark with four extensions:

- Pipe tables.
- Pandoc-style attributes: `[text]{style="color: red"}` for a styled span,
  `{target=_blank}` after a link or image, and `{.class}` on its own line before
  a paragraph or heading.
- Pandoc-style fenced divs, `::: {.class}` ... `:::`, for groups of blocks such
  as columns. An enclosing div uses a longer fence than the divs inside it.
- Pandoc raw HTML fences, ```` ```{=html} ```` ... ```` ``` ````, whose content
  is published exactly as written.

Attributes appear only where an element carries styling that plain Markdown
cannot express. Attribute values are the platform's own (WordPress class names
and inline styles). Inline HTML remains valid Markdown; content kept as HTML is
written as plain HTML when Markdown reads it back unchanged, and in a raw HTML
fence otherwise.

### Push

Push renders the Markdown to plain HTML and sends it as classic (non-block) post
content. BPSync does not generate Gutenberg block markup. Rendered blocks are
separated by blank lines and contain line breaks only inside `<pre>`, so
WordPress's `wpautop` display filter cannot add paragraphs or breaks. HTML kept
in the Markdown is sent exactly as written.

Images that point to local files are uploaded to the media library before the
post is saved. An image from the media library is rendered as WordPress's image
markup (`<figure class="wp-block-image size-large">` with `wp-image-ID`), using
the media ID and size recorded in the media table; an image title becomes its
caption. The local Markdown keeps the local path. Images with remote URLs are
sent as plain `<img>` elements. An embeddable URL alone in a paragraph is sent
as that bare URL, so WordPress's oEmbed support renders the player; BPSync does
not generate iframes for embeds.

### Pull

Pull reads the stored content (`context=edit`, `content.raw`) and checks every
conversion against a model of what WordPress displays:

- Content with block markup is displayed block by block. A static block shows
  its HTML without block comments; a dynamic block, or any block outside the
  known static set, is compared as its markup; a plain embed shows its URL.
- Content without block markup goes through `wpautop`. BPSync implements that
  filter's behavior independently, because WordPress's code is GPL and cannot be
  incorporated under BPSync's license, and checks it against WordPress's own
  output (`tests/fixtures/wpautop.json`).
- HTML is parsed with html5lib, which follows the HTML parsing rules browsers
  use, so misnested tags, duplicate attributes, and character references mean
  what they mean to a reader's browser.

The stored content is split into units: each top-level block and each run of
content between blocks, or, for classic content, the parts `wpautop` would
treat as separate paragraphs or blocks. A converter written as the inverse of
the push renderer turns each unit into Markdown. The unit is converted only if
the HTML push would send for it displays the same as the original. A unit that
does not convert stays in the Markdown as its exact original source. Finally,
the whole post is put through the model as push would send it and compared
with the stored post; conversions that change the whole post's display are
kept as source until it displays the same. Pull reports which parts it kept.

The comparison of displays ignores whitespace browsers do not show (around
block elements and at line edges), attribute order, character-reference
spelling, `<b>`/`<strong>` and `<i>`/`<em>`, attribute-less spans and empty
formatting elements, spaces at the edges of plain bold or italic text, one
trailing newline in `<pre>`, comments' whitespace, a paragraph holding only a
comment (WordPress wraps `<!--more-->` that way), and a fixed list of
bookkeeping classes the block editor adds to unstyled elements (such as
`wp-block-heading` and `wp-block-list`). Inline styles that set `white-space`
or `display` make whitespace significant.

Embed blocks without custom classes or alignment become their bare URL. Images
from the site's media library are downloaded into `images/` and the Markdown
references the local file; only images the final Markdown uses are downloaded.
A classic-editor image (`<p><img class="wp-image-N size-X">`) and a block-editor
image figure are read as the same image, with alignment allowed on either
element, so a classic post's images become Markdown images and are pushed back
in the block editor's image markup. Captions with their own attributes, and
figures with classes other than alignment and size, are kept as source.

### Block-format posts

A post whose stored content contains block markup (`<!-- wp:`) is recorded as
block-format. Pushing it asks for confirmation, because the push replaces block
content with plain HTML. Blocks kept as source stay blocks, and a post that
keeps any block markup is not put through `wpautop` by WordPress. The recorded format comes from the content WordPress
last returned, so a successful push records plain HTML and later pushes do not
ask again. `diff` shows the format change before it happens.

## Rationale

Plain HTML is what WordPress has always accepted through the API, and it has no
validity requirement. Gutenberg markup must match each block's own save output
exactly, or the editor reports the block as invalid. That output changes between
WordPress releases, so generating it would tie BPSync to editor internals for
little gain. The cost is that posts BPSync writes open in the block editor as a
single Classic block. Only posts the user edits locally are pushed, so untouched
block posts keep their format.

Comparing what WordPress displays, rather than the markup itself, lets ordinary
posts become clean Markdown while proving that nothing visible changes, and
lets the format change from block to plain HTML be checked like any other
difference. Keeping unconverted parts as their exact source makes the fallback
loss-free by construction. A multi-model review found that the first design,
which re-serialized kept parts from a parsed tree, compared parts in isolation,
and used Python's lenient HTML parser, could change displayed content; html5lib
(MIT) replaced that parser.

Existing HTML-to-Markdown libraries (`markdownify`, `html-to-markdown`) were
evaluated on Gutenberg fixtures and real posts. Both silently drop attributes
such as text alignment, link targets, and span styles, and `markdownify` drops
iframes. A round-trip check is required regardless of the converter, and it
limits conversion to what the push renderer can produce, so a converter that
mirrors the renderer converts everything that can pass the check without a
large dependency.

Attribute syntax keeps styled posts readable as Markdown instead of leaving
whole elements as HTML. Pandoc's syntax is an existing convention that Pandoc,
Quarto, and MyST render. Viewers without support show the braces as text.
Ignoring the editor's bookkeeping classes keeps ordinary block posts as plain
Markdown; a theme that styles those classes could render a pushed post slightly
differently.

## Intentionally excluded

- Generating Gutenberg block markup on push.
- Converting a block post to plain HTML without confirmation.
- Uploading remote images or rewriting their URLs.
- Platform-neutral aliases for attribute values; see `TODO.md`.
- Converting content whose plain-HTML display would differ from its block
  display, such as a quote with a `<cite>` that `wpautop` would wrap in a
  paragraph; such blocks are kept as source.
- WordPress pages; the MVP synchronizes posts only.
