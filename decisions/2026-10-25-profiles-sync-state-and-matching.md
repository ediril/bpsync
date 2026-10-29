# Profiles, sync state, and matching

Date: 2026-10-25

## Decision

### Profiles

A profile maps one local folder to one blog, following HLSync's profile model.
Profiles live in `~/.wpsync/config.json` and hold the site URL, the discovered
REST API root, the username, the password environment-variable name, and one
canonical local root. Local roots may not equal, contain, or be contained by
another profile's root. `wpsync create NAME --site URL` creates a profile and
proposes the current directory as its root. Commands run inside a mapped root
use that profile; elsewhere the profile is named before the command
(`wpsync myblog pull`). No profile selection persists between commands.

Credentials are WordPress Application Passwords read from an environment
variable. The variable name defaults to one derived from the profile name, such
as `MYBLOG_WP_PASSWORD`, and can be overridden when the profile is created.
Credential values are never stored.

`create` only checks that the site advertises a WordPress REST API and saves
the profile; it needs no credentials. `init` signs in, checks that the account
can edit posts, creates the folder's sync state, and runs the first pull of
every post and its images. `diff`, `pull`, and `push` refuse a folder without
sync state, so nothing is pushed to a blog that has not been pulled first. The
state is created only after sign-in succeeds, so a failed `init` can simply be
rerun; an interrupted first pull is finished by `pull`.

### Sync state

Local files are the source of truth; WordPress is where they are published.
WPSync assumes the blog is not normally edited independently and checks the
WordPress side only to avoid overwriting a change made there by accident.

Each local root holds `.wpsync/state.db`, a SQLite database that stores no
post content. A `site` row records which blog the folder belongs to, and WPSync
refuses to use the database with a different blog. For every linked post the
`posts` table stores the post ID, the local path, two checksums of the file as
of the last sync (one of the body, one of the synchronized header fields
together), a fingerprint of the WordPress post as of the last sync (its title,
content, slug, status, date, and category and tag IDs), and its content format
(block or plain HTML). The media table arrives with pull. One pull or push of a
post updates its rows in a single transaction.

A post changed locally when either checksum differs. Push sends the content
only when the body checksum differs, and the header fields only when the header
checksum differs, so editing only a post's header never replaces block content.

WPSync contacts WordPress only when a command needs it:

- `diff` and `push` fetch, by ID, the posts that changed locally, and warn when
  one also changed on WordPress since the last sync.
- `diff` and `push` fetch the lightweight post list only when a new local file
  needs matching.
- `pull` fetches every post with its content.

Posts created or changed on WordPress therefore appear only through `pull`.

`diff`, `pull`, and `push` act on every post or on one post, selected by post
ID, slug, or file path.

### Matching

A file without a post ID is matched against remote posts by title and slug at
push time:

- Title and slug identify the same post, or only one of them matches a post:
  ask whether to update that post, naming what matched.
- The title matches several posts, or title and slug identify different posts:
  list the candidates and stop.
- Nothing matches: create a new post.

A confirmed match writes the post ID into the file's frontmatter. A first pull
is not required before push; matching prevents duplicate posts.

### Prompts

WPSync asks before it updates a matched post, overwrites a conflict, creates
missing categories or tags, or converts a block-format post to plain HTML.
Every prompt defaults to No. `-y` / `--yes` answers yes to every prompt within
the selected files. When no terminal can answer, a prompt counts as No and the
message names `--yes`.

Remote deletion is a separate command that moves the post to the WordPress
trash. Pull never deletes local files.

## Rationale

The profile model matches HLSync so the two tools behave alike. Checksums and a
fingerprint recorded at each sync tell WPSync which side changed without
comparing clocks, which HLSync needs only because FTP cannot read remote
content cheaply. Storing checksums instead of copies keeps the database small;
a text diff of pending changes compares the file with the current WordPress
post, and Git covers history. Contacting WordPress only for locally changed
posts keeps everyday commands fast and offline-capable, at the cost of not
noticing WordPress-side edits to posts the user has not touched. SQLite gives
atomic multi-row updates for a post and its media without hand-written
journaling.

Titles repeat across posts, while WordPress keeps published slugs unique, so
matching requires agreement or a single candidate and never picks among several.
A single `--yes` flag covers every prompt because every case is a question WPSync
would otherwise ask.

## Risks

- The WordPress REST API has no conditional update. A remote edit made between
  WPSync's conflict check and its save is not detected.
- The media table exists only in the local root. If it is lost, WPSync cannot
  recognize uploaded images and the next push uploads duplicates.
- Git can store `state.db` as a backup but cannot diff or merge it.

## Intentionally excluded

- Storing credentials or using the OS keychain for the MVP.
- Contacting the blog with credentials during `create`.
- Detecting WordPress-side changes to posts that are unchanged locally,
  except through `pull`.
- Selecting several posts in one command; a command acts on one post or all.
- Matching on title or slug without confirmation.
- Permanent remote deletion.
