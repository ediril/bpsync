# Content format

Date: 2026-10-25

## Decision

Each post is one Markdown file with YAML frontmatter under `posts/`. The
frontmatter holds the platform post ID once the file is linked to a post, plus
title, slug, date, status, categories, and tags. Categories and tags are names;
the WordPress adapter resolves them to term IDs.

### Markdown dialect

The body is CommonMark with three extensions:

- Pipe tables.
- Pandoc-style attributes: `[text]{style="color: red"}` for a styled span,
  `{target=_blank}` after a link or image, and `{.class}` on its own line before
  a paragraph or heading.
- Pandoc-style fenced divs, `::: {.class}` ... `:::`, for groups of blocks such
  as columns. An enclosing div uses a longer fence than the divs inside it.

Attributes appear only where an element carries styling that plain Markdown
cannot express. Attribute values are the platform's own (WordPress class names
and inline styles). Inline HTML remains valid Markdown and is the last resort.

### Push

Push renders the Markdown to plain HTML and sends it as classic (non-block) post
content. WPSync does not generate Gutenberg block markup. The rendered HTML
places line breaks only inside `<pre>`, so WordPress's `wpautop` display filter
cannot add paragraphs or breaks.

Images that point to local files are uploaded to the media library before the
post is saved. An image from the media library is rendered as WordPress's image
markup (`<figure class="wp-block-image size-large">` with `wp-image-ID`), using
the media ID and size recorded in the media table; an image title becomes its
caption. The local Markdown keeps the local path. Images with remote URLs are
sent as plain `<img>` elements. An embeddable URL alone in a paragraph is sent
as that bare URL, so WordPress's oEmbed support renders the player; WPSync does
not generate iframes for embeds.

### Pull

Pull reads the stored content (`context=edit`, `content.raw`). Block content
has the comments of static blocks removed; a dynamic block, or any block outside
the known static set, stays as its block markup so WordPress keeps rendering it.
Classic content, which WordPress stores without paragraph tags, is first
expanded the way WordPress's `wpautop` display filter expands it, so the
converted Markdown means what WordPress displays. WPSync implements that
behavior independently, because WordPress's code is GPL and cannot be
incorporated under WPSync's license, and checks it against WordPress's own
output (`tests/fixtures/wpautop.json`).

A WPSync converter written as the inverse of the push renderer turns the HTML
into Markdown. Each top-level element is then rendered back with the push
renderer and compared with the original. The comparison is display identity:
the same elements, attributes, and text, ignoring whitespace outside `<pre>`,
attribute order, character-reference spelling, and a fixed list of bookkeeping
classes the block editor adds to unstyled elements (such as `wp-block-heading`
and `wp-block-list`). An element that does not compare equal stays in the
Markdown as its original HTML, so pull never silently drops content. Pull
reports which posts kept HTML.

Embed blocks become their bare URL. Images from the site's media library are
downloaded into `images/` and the Markdown references the local file.

### Block-format posts

A post whose stored content contains block markup (`<!-- wp:`) is recorded as
block-format. Pushing it asks for confirmation, because the push replaces block
content with plain HTML. The recorded format comes from the content WordPress
last returned, so a successful push records plain HTML and later pushes do not
ask again. `diff` shows the format change before it happens.

## Rationale

Plain HTML is what WordPress has always accepted through the API, and it has no
validity requirement. Gutenberg markup must match each block's own save output
exactly, or the editor reports the block as invalid. That output changes between
WordPress releases, so generating it would tie WPSync to editor internals for
little gain. The cost is that posts WPSync writes open in the block editor as a
single Classic block. Only posts the user edits locally are pushed, so untouched
block posts keep their format.

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
- Preventing WordPress from wrapping inline elements that sit directly in a
  container, such as a quote's `<cite>`, in a paragraph when a block post is
  pushed as plain HTML. This is part of the accepted block-to-HTML change.
- WordPress pages; the MVP synchronizes posts only.
