# BPSync

BPSync (Blog Post Sync, `bpsync`) is a command-line tool for managing blog
posts as local Markdown files: map a folder to a blog, pull its posts, edit
them in any editor, preview the differences, and push the changes back.
WordPress is the first supported platform.

BPSync is pre-alpha software. Profiles and the connection check work today;
pull, diff, and push are in progress (see `TODO.md`).

## Installation

BPSync requires Python 3.11 or newer. Install it from a checkout with uv:

```console
uv tool install --editable /path/to/bpsync/app
```

## Credentials

BPSync signs in with a WordPress Application Password, which you create in the
WordPress dashboard under **Users > Profile > Application Passwords**.
Application Passwords require the site to use HTTPS.

BPSync reads the password from an environment variable and never stores it. The
variable name comes from the profile name: profile `myblog` reads
`MYBLOG_WP_PASSWORD`. Choose a different variable with `--password-env` when
creating the profile.

## Profiles

A profile maps one local folder to one blog. Profiles are stored in
`~/.bpsync/config.json`. Folders may not overlap between profiles.

From the folder you want to use for the blog:

```console
export MYBLOG_WP_PASSWORD='abcd efgh ijkl mnop qrst uvwx'
bpsync create myblog --site https://example.com --username emrah
```

`create` offers the current directory as the profile's folder; press Enter to
accept it, or decline to name another. Use `--local-root PATH` to name it
directly, and omit `--username` to be prompted. Before saving the profile,
`create` finds the blog's REST API, signs in, and lists the blog's posts. If
the password variable is missing or sign-in fails, nothing is saved.

Commands run inside a profile's folder, or any folder below it, use that
profile automatically. Elsewhere, put the profile name before the command:

```console
bpsync connect           # sign in and list the blog's posts
bpsync myblog connect    # the same, from any directory
bpsync profiles          # list profiles; * marks the current one
bpsync profile --details # show the current profile's settings
bpsync root myblog       # print the profile's folder
bpsync map --local-root /new/folder   # move the profile to another folder
bpsync remove myblog     # remove the profile only
```

`map` asks for confirmation and only changes the local folder. A different
blog needs its own profile, because synchronization state belongs to one blog.
`remove` deletes only the profile; local files and the blog stay unchanged.

Commands may be shortened to any unique prefix, such as `bpsync conn`.

## Post files

Each post is a Markdown file under the profile folder's `posts/` directory, in
any subfolder. The file starts with a YAML header:

```markdown
---
id: 123
title: Hello world
slug: hello-world
date: 2026-10-01T09:30:00+02:00
status: published
categories:
- News
tags:
- python
---

The post body in Markdown.
```

- `id` links the file to a WordPress post. Leave it out for a new post.
- `title`, `slug`, and `date` are optional. A `date` needs a time zone offset
  or `Z`.
- `status` is one of `draft`, `published`, `scheduled`, `pending`, or
  `private`, and defaults to `draft`.
- `categories` and `tags` are lists of names.

The body is Markdown. Styling that plain Markdown cannot express uses
Pandoc-style attributes, and only where a post has such styling:

```markdown
Some [red text]{style="color: #c00"} and [a link](https://example.com/){target=_blank}.

{.has-text-align-right}
A right-aligned paragraph.

![Sunset](images/sunset.jpg "Caption"){.aligncenter}

:::: {.wp-block-columns}
::: {.wp-block-column}
Left column.
:::
::::
```

A video or other embeddable URL alone in a paragraph is embedded by WordPress.
Content with no Markdown form, such as galleries, stays in the file as HTML;
BPSync never drops it.

Other header entries, such as `layout:` from another tool, stay in the file
exactly as written and are never sent to WordPress. When BPSync rewrites a file,
it writes its own fields in the order above, sorts category and tag names, and
leaves other entries and their comments unchanged. Two files with the same `id`
are an error.

## Seeing what changed

Local files are the source of truth. `ls` lists the posts in the profile folder
with their IDs and slugs, without contacting the blog:

```console
bpsync ls
```

`diff` shows what a push would change and anything that would stop it:

```console
bpsync diff          # every post
bpsync diff 123      # one post, by ID
bpsync diff hello    # one post, by slug
bpsync diff posts/new-idea.md   # one post, by file
bpsync diff -a       # also list unchanged posts
bpsync --legend      # explain the status symbols
```

```text
~ l  123  posts/hello-world.md  content; block post becomes plain HTML on push
~ l  145  posts/release-notes.md  details
?    150  posts/about.md  content; also changed on WordPress since the last sync
- l  160  posts/old.md  deleted locally; WordPress keeps the post
+ l    -  posts/new-idea.md  new post
Not shown: 12 unchanged (-a to show)
```

`content` means the body changed and `details` means a header field changed.
`diff` never changes anything. It contacts the blog only for posts that changed
locally, to check whether they also changed on WordPress since the last sync,
and for new files, to match them against existing posts by title and slug.
With no local changes it works offline. Posts created or edited on WordPress
appear only through `pull`.

## License

BPSync is source-available under the [PolyForm Strict License 1.0.0](LICENSE).
Use is free of charge for the purposes permitted by that license, including:

- Any noncommercial purpose.
- The personal uses listed in the license, such as personal study and hobby
  projects, without any anticipated commercial application.
- Use by charitable organizations, educational institutions, public research
  organizations, public safety or health organizations, environmental protection
  organizations, and government institutions, regardless of funding source or
  obligations resulting from funding.

This license grants no rights to modify or redistribute BPSync or create works
based on it. The full license governs; this summary does not grant additional
permissions.

Commercial use outside those permissions requires a separate paid license.
Contact [Emrah Diril](mailto:emrah@diril.org) for pricing and a commercial
agreement before beginning such use.

BPSync is source-available, not open source.

## Development

```console
uv sync
uv run pytest
uv run ruff check src tests
```

### Versions

Versions use `<major>.<work-day>.<increment>` without leading zeroes and
advance from Git history, not from the build date:

- [`version.json`](version.json) gives the starting version of the history's
  first commit.
- Each later date with commits advances the work-day number by one, regardless
  of how many idle days pass.
- The increment counts the commits on the latest commit date, continuing from
  the starting increment on the first day.

Versions follow first-parent history, so commit dates must not go backwards.
Wheels and source archives keep the computed version; installed commands do
not use Git. Reinstall an editable checkout after committing to refresh its
version. `bpsync --version` prints the installed version.

### Releasing to PyPI

Use a PyPI account with two-factor authentication and an API token. Twine reads
credentials from `~/.pypirc` or `TWINE_USERNAME`/`TWINE_PASSWORD` and prompts
if needed. Do not store the token in the repository.

1. Commit everything to release. Preparation refuses a working tree with
   uncommitted changes, because the version describes the last commit.
2. With development dependencies installed (`uv sync`), run:

   ```console
   ./scripts/publish.sh
   ```

   The script uses the repository's `.venv/bin/python` when available,
   otherwise `python3`; set `PYTHON` to select another interpreter. Through the
   helpers in `scripts/helpers/`, it checks the release identity, runs lint and
   tests, builds the wheel and source archive with `uv build`, checks their
   metadata with Twine, installs the wheel into a clean environment to confirm
   `bpsync --version`, and uploads both artifacts. Prepared artifacts are kept
   in `dist/bpsync/<version>/` and reused if the script runs again for the same
   version.

   To prepare and validate artifacts without publishing, run
   `./scripts/publish.sh --prepare`.

3. Tag the release commit as `v<version>`, push the tag, and create a matching
   GitHub Release. PyPI does not require a tag, but it records which source was
   published.
4. Install the published version in a clean environment and run
   `bpsync --version` before announcing it.

PyPI never lets a published version be replaced. If publication fails after
PyPI accepted either artifact, make another commit (an empty commit is enough)
and publish the new version.
