# Changelog

## Unreleased

### Added

- Profiles map one local folder to one blog, following HLSync: `create`,
  `map`, `remove`, `root`, `profile`, and `profiles`, stored in
  `~/.wpsync/config.json`, with current-directory inference, a profile-prefix
  override, and an Application Password read from an environment variable.
  `create` checks that the address is a WordPress site without signing in.
- Read and write post files: Markdown under `posts/` with a YAML header.
  WPSync rewrites its own fields canonically, keeps other header entries and
  their comments byte for byte, and reports every invalid file and every post
  ID shared by two files at once.
- Convert post content between WordPress and Markdown. Push renders plain HTML
  that WordPress displays as written. Pull reads stored block and classic
  content, uses Pandoc-style attributes and fenced divs only where a post has
  styling plain Markdown cannot express, and checks every conversion against a
  model of what WordPress displays. Anything that would display differently is
  kept as its exact original source, as plain HTML or in a ```` ```{=html} ````
  fence.
- Post `status` is `public` or `private`, and new files are private. Push
  will publish public posts and never send private ones, except to turn a
  published post that became private into a draft. Pull writes published posts
  as public and drafts, scheduled, pending, and WordPress-private posts as
  private.
- `diff [POST]` shows local changes in HLSync's notation, with the second
  column marking the side that changed. It contacts the blog only for changed
  or new posts. A new file whose slug belongs to a post is a conflict, and a
  shared title is noted. Private posts are listed with `-a`, and a published
  post made private shows as `unpublish`. `ls` lists local posts by ID, slug,
  and title.
- `pull [POST]` brings posts into `posts/<slug>.md` and downloads the images
  they display into `images/`. Edited files are replaced, and unlinked files
  are linked, only after confirmation or `--yes`; pull never restores or
  deletes local files.
  An image whose file is gone from the server, or that comes back as something
  other than an image, is reported, and the post is still pulled with that
  image kept as its original HTML.
- `scripts/publish.sh [--prepare]` builds, checks, and publishes releases to
  PyPI.

### Changed

- License WPSync under PolyForm Strict 1.0.0.
- Derive versions from Git history like HLSync: `<major>.<work-day>.<increment>`
  starting from `version.json`. The history starts at 1.0.1, so
  releases begin at 1.1 and follow the 1.0.x releases a previous `wpsync`
  project published on PyPI.
