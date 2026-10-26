# Changelog

## Unreleased

### Added

- Profiles map one local folder to one blog, following HLSync: `create`,
  `connect`, `map`, `remove`, `root`, `profile`, and `profiles`, stored in
  `~/.wpsync/config.json`, with current-directory inference, a profile-prefix
  override, and an Application Password read from an environment variable.
  `create` and `connect` sign in and list the blog's posts.
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
- `diff [POST]` shows local changes in HLSync's notation, with the second
  column marking the side that changed. It contacts the blog only for changed
  or new posts and matches new files to existing posts by title and slug.
  `ls` lists local posts by ID, slug, and title.
- `pull [POST]` brings posts into `posts/<slug>.md` and downloads the images
  they display into `images/`. Edited files are replaced, and unlinked files
  are linked, only after confirmation or `--yes`; pull never restores or
  deletes local files.
- `scripts/publish.sh [--prepare]` builds, checks, and publishes releases to
  PyPI.

### Changed

- License WPSync under PolyForm Strict 1.0.0.
- Derive versions from Git history like HLSync: `<major>.<work-day>.<increment>`
  starting from `version.json`. Versions start at 2.0.1, after the 1.0.x
  releases already published under the `wpsync` name on PyPI.
