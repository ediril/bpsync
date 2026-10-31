# Work Queue

- [ ] `push`: create and update posts with changed fields only, slug and
  title checks before creating a post (see the matching decision), writing the
  slug WordPress assigns back into the file, conflict and format-change
  prompts, missing-term prompts, local image upload (a media row with no local
  file is a missing image: send its library markup, upload nothing), and
  `--yes`. Publish public posts, skip private ones, and turn a published post
  that became private into a draft. Add `diff -p POST` to show the text difference push
  would make, comparing the file with the current post converted to Markdown.
- [ ] Remote deletion command that moves a post to the WordPress trash.
- [ ] Characterize against the user's real blogs: `init` and first-pull
  sign-in, read-only pull and diff first, then push to a blog the user
  designates. Confirm `wpautop` handling, oEmbed URLs, and the
  HTML filter for users without `unfiltered_html`.
- [ ] README: installation, profiles, the sync workflow, prompts, and known
  limitations, kept current as each command lands.
- [ ] `tag` command: list tags with post counts, show or change one post's tags
  (`+tag`, `-tag`), and filter `ls` by tag. Edits local files only; push sends
  the changes. Decide whether it also handles categories. This lets a command
  select several posts, which the profiles decision currently excludes.
- [ ] `import apple-notes [-f FOLDER]...`: read Apple Notes' database (macOS,
  Full Disk Access) and write each note to `posts/apple-notes/<slug>.md` as a
  private post with an `apple-notes-id` header key, so importing again updates
  the same file without touching wpsync's fields. A Python port of notemodo's
  `noteslib` (gzip plus a small protobuf decoder for the note schema from the
  MIT-licensed apple_cloud_notes_parser), kept in its own module that the sync
  code never imports, and checked against real notes. Copies attachments into
  `images/`.

## Backlog

- [ ] Markdown forms for content still kept as HTML: galleries, images wrapped
  in links, embeds with captions, preformatted text that is not code, tables
  without a header row, and classic-editor tables (push wraps tables in
  WordPress's `wp-block-table` figure, so an unwrapped table does not compare
  equal).

- [ ] Platform-neutral attribute aliases, such as `{align=right}` for
  WordPress's `has-text-align-right`, mapped per platform. Needed once a second
  blogging platform represents the same styling differently.
