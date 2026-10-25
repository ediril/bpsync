# Work Queue

- [ ] Profiles: `create`, `profiles`, `profile`, `map`, `remove`, `root`, and
  `connect`, stored in `~/.wpsync/config.json` with HLSync's root rules,
  current-directory inference, profile-prefix override, and environment-variable
  credentials. Includes the WordPress client foundation: REST API discovery,
  Application Password authentication, paginated requests, error reporting, and
  the lightweight post listing that `create` and `connect` show.
- [x] Local post documents: frontmatter parsing, validation, and serialization;
  scanning `posts/`; duplicate post-ID detection.
- [x] Content conversion: Markdown (CommonMark, pipe tables, Pandoc attributes
  and fenced divs) to `wpautop`-safe plain HTML for push; stored WordPress HTML
  to Markdown for pull through a converter that mirrors the renderer, a
  `wpautop` port for classic content, and a per-element display-identity check
  that keeps unconvertible elements as HTML and reports them.
- [x] Sync state, `diff`, and `ls`: `.wpsync/state.db` with per-file body and
  header checksums, WordPress fingerprints, and the blog identity; `diff [POST]`
  in HLSync notation, fetching only locally changed posts and matching new
  files by title and slug; `ls` listing local posts by ID, slug, and title.
- [ ] `pull`: create and update local files, record content format, protect
  local edits, prompt on conflicts, and download media into `images/` with the
  media table. Map classic-editor images (`<p><img class="wp-image-N
  size-X">`) to Markdown images through the media table; they are kept as HTML
  until then.
- [ ] `push`: create and update posts with changed fields only, title and slug
  matching, conflict and format-change prompts, missing-term prompts, local
  image upload, and `--yes`. Add `diff -p POST` to show the text difference
  push would make, comparing the file with the current post converted to
  Markdown.
- [ ] Remote deletion command that moves a post to the WordPress trash.
- [ ] Characterize against the user's real blogs: read-only pull and diff
  first, then push to drafts. Confirm `wpautop` handling, oEmbed URLs, and the
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
