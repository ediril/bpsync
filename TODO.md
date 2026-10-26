# Work Queue

- [ ] `push`: create and update posts with changed fields only, title and slug
  matching, conflict and format-change prompts, missing-term prompts, local
  image upload, and `--yes`. Add `diff -p POST` to show the text difference
  push would make, comparing the file with the current post converted to
  Markdown.
- [ ] Remote deletion command that moves a post to the WordPress trash.
- [ ] Characterize against the user's real blogs: `create` and `connect`
  sign-in, read-only pull and diff first, then push to drafts. Confirm `wpautop` handling, oEmbed URLs, and the
  HTML filter for users without `unfiltered_html`.
- [ ] README: installation, profiles, the sync workflow, prompts, and known
  limitations, kept current as each command lands.

## Backlog

- [ ] Markdown forms for content still kept as HTML: galleries, images wrapped
  in links, embeds with captions, preformatted text that is not code, tables
  without a header row, and classic-editor tables (push wraps tables in
  WordPress's `wp-block-table` figure, so an unwrapped table does not compare
  equal).

- [ ] Platform-neutral attribute aliases, such as `{align=right}` for
  WordPress's `has-text-align-right`, mapped per platform. Needed once a second
  blogging platform represents the same styling differently.
