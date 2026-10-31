# WPSync

WPSync (`wpsync`) is a command-line tool for managing blog posts as local
Markdown files: map a folder to a blog, pull its posts, edit them in any
editor, preview the differences, and push the changes back. WordPress is the
first supported platform.

WPSync is pre-alpha software. Profiles, pull, and diff work today; push is in
progress (see `TODO.md`).

## Installation

WPSync requires Python 3.11 or newer. Install it from a checkout with uv:

```console
uv tool install --editable /path/to/wpsync/app
```

## Credentials

WPSync signs in with a WordPress Application Password, which you create in the
WordPress dashboard under **Users > Profile > Application Passwords**.
Application Passwords require the site to use HTTPS.

WPSync reads the password from an environment variable and never stores it. The
variable name comes from the profile name: profile `myblog` reads
`MYBLOG_WP_PASSWORD`. Choose a different variable with `--password-env` when
creating the profile.

## Profiles

A profile maps one local folder to one blog. Profiles are stored in
`~/.wpsync/config.json`. Folders may not overlap between profiles.

From the folder you want to use for the blog:

```console
wpsync create myblog --site https://example.com --username emrah
export MYBLOG_WP_PASSWORD='abcd efgh ijkl mnop qrst uvwx'
wpsync pull
```

`create` checks that the address is a WordPress site and saves the profile
without signing in. It offers the current directory as the profile's folder;
press Enter to accept it, or decline to name another. Use `--local-root PATH`
to name it directly, and omit `-u`/`--username` to be prompted. The username is
your WordPress login name or email address. A blog installed in a subfolder,
such as `https://example.com/blog`, works like any other.

The first `pull` downloads every post and its images (see
[Pulling posts](#pulling-posts)). It also says which account signed in and
notes any limits: an account that can edit only its own posts, such as an
Author, does not see other authors' posts.

Commands run inside a profile's folder, or any folder below it, use that
profile automatically. Elsewhere, put the profile name before the command:

```console
wpsync pull              # bring changes from the blog
wpsync myblog pull       # the same, from any directory
wpsync profiles          # list profiles; * marks the current one
wpsync profile --details # show the current profile's settings
wpsync root myblog       # print the profile's folder
wpsync map --local-root /new/folder   # move the profile to another folder
wpsync remove myblog     # remove the profile only
```

`map` asks for confirmation and only changes the local folder. A different
blog needs its own profile, because synchronization state belongs to one blog.
`remove` deletes only the profile; local files and the blog stay unchanged.

Commands may be shortened to any unique prefix, such as `wpsync di`.

## Post files

Each post is a Markdown file under the profile folder's `posts/` directory, in
any subfolder. The file starts with a YAML header:

```markdown
---
id: 123
title: Hello world
slug: hello-world
date: 2026-10-01T09:30:00+02:00
status: public
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
- `status` is `public` or `private`, and defaults to `private`. Push publishes
  a public post; a public post with a future `date` is scheduled. Push never
  sends a private post, except to turn a published post that became private
  into a WordPress draft, which keeps its ID, comments, and address for when it
  is made public again. Pull writes published posts as `public` and drafts,
  scheduled, pending, and WordPress-private posts as `private`.
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
Content with no Markdown form, such as galleries, stays in the file as its
exact original HTML; WPSync never drops it. When plain HTML would not survive
Markdown unchanged, it is wrapped in a raw HTML fence, which is published
exactly as written:

````markdown
```{=html}
<!-- wp:gallery -->
<figure class="wp-block-gallery">…</figure>
<!-- /wp:gallery -->
```
````

Other header entries, such as `layout:` from another tool, stay in the file
exactly as written and are never sent to WordPress. When WPSync rewrites a file,
it writes its own fields in the order above, sorts category and tag names, and
leaves other entries and their comments unchanged. Two files with the same `id`
are an error.

## Pulling posts

`pull` brings the blog's posts into the profile folder: each post becomes
`posts/<slug>.md`, and images from the site's media library are downloaded into
`images/` and referenced from the Markdown. The copy of an image that the post
displays is downloaded, usually WordPress's resized `large` copy.

If an image's file is gone from the server, or the server answers with something
other than an image, pull lists it as `missing:` on the post's line and carries on. The
Markdown refers to `images/<name>` as usual, and later pulls add the file if the
server has it again. Any other download failure, such as a server error, stops
the pull; rerun it to continue.

Blank paragraphs and repeated line breaks, which only force vertical space in
WordPress, are left out of the Markdown. The post keeps that spacing on the blog
until you edit and push it.

```console
wpsync pull          # every post
wpsync pull 123      # one post, by ID
wpsync pull hello    # one post, by slug, including one not pulled yet
wpsync pull -y       # answer yes to every question
```

```text
+  123  posts/hello-world.md  2 images
~  145  posts/release-notes.md
?  150  posts/about.md  changed on both sides; your file is unchanged
+  160  posts/gallery-tour.md  kept as HTML: core/gallery
Pulled 3 posts (2 new, 1 updated), 2 images; 1 skipped. Rerun pull with --yes to accept the skipped changes.
```

Pull never loses local work:

- A file you edited is replaced only after you confirm, and only when the post
  also changed on WordPress. Without a terminal, or when you answer no, the
  file is skipped.
- A WordPress post with the same slug as a local file that has no `id` yet is
  linked to that file only after you confirm, so pull does not create a
  duplicate. A shared title alone does not link them, because titles need not
  be unique.
- A file you deleted is not restored, and a post deleted on WordPress keeps its
  local file.
- Header entries WPSync does not sync, such as `layout:`, are kept when a file
  is updated.

Dates are written in the blog's time zone. Images placed inside a line of text,
rather than on their own, keep their WordPress address and are not downloaded.

## Seeing what changed

Local files are the source of truth. `ls` lists the posts in the profile folder
without contacting the blog. On a terminal, it cuts lines to fit instead of
letting them wrap:

```console
$ wpsync ls
ID  Attr  Issues  Title (file)
67  p     2       Hurt (hurt.md)
 -  -     -       Idea (idea.md)
```

`wpsync ls -l` prints every column in full, adding each post's slug, file, and
address on the blog as of the last pull.

`Attr` shows `p` for a public post. `Issues` counts what is wrong with a post;
`show` says what, for one post chosen by ID, slug, file, or title:

```console
$ wpsync show hurt
ID:         67
Title:      Hurt
Slug:       hurt
Status:     public
Date:       2025-11-04T10:00:00-05:00
Categories: Notes
Tags:       -
File:       posts/hurt.md
URL:        https://blog.test/hurt/
Issues:     2
  missing file: https://blog.test/wp-content/uploads/2025/11/photo.png
  missing file: https://blog.test/wp-content/uploads/2025/11/discussion.html
```

An issue is an image or embedded page that a pull found missing from the server.
Pull tries missing files again each time. It checks the images it downloads and
iframes showing uploaded files, when it pulls a post. It does not check images
inside kept HTML, in a line of text, or on other sites, or uploads a post only
links to.

`diff` shows what a push would change and anything that would stop it:

```console
wpsync diff          # every post
wpsync diff 123      # one post, by ID
wpsync diff hello    # one post, by slug
wpsync diff "Hello World"   # one post, by title
wpsync diff posts/new-idea.md   # one post, by file
wpsync diff -a       # also list unchanged posts
wpsync --legend      # explain the diff and ls symbols
```

```text
~ l  123  posts/hello-world.md  content; block post becomes plain HTML on push
~ l  145  posts/release-notes.md  details
?    150  posts/about.md  content; also changed on WordPress since the last sync
- l  160  posts/old.md  deleted locally; WordPress keeps the post
+ l    -  posts/new-idea.md  new post
~ l  170  posts/old-news.md  unpublish; becomes a draft on WordPress
Not shown: 12 unchanged, 3 private (-a to show)
```

`content` means the body changed and `details` means a header field changed.
Private posts (`x l`) are listed with `-a`; their edits stay local.
`diff` never changes anything. It contacts the blog only for posts that changed
locally, to check whether they also changed on WordPress since the last sync,
and for new files, to check their slugs and titles against existing posts. A
taken slug is a conflict (`?`); a shared title is noted, since push asks before
creating a second post with the same title.
With no local changes it works offline. Posts created or edited on WordPress
appear only through `pull`.

## License

WPSync is source-available under the [PolyForm Strict License 1.0.0](LICENSE).
Use is free of charge for the purposes permitted by that license, including:

- Any noncommercial purpose.
- The personal uses listed in the license, such as personal study and hobby
  projects, without any anticipated commercial application.
- Use by charitable organizations, educational institutions, public research
  organizations, public safety or health organizations, environmental protection
  organizations, and government institutions, regardless of funding source or
  obligations resulting from funding.

This license grants no rights to modify or redistribute WPSync or create works
based on it. The full license governs; this summary does not grant additional
permissions.

Commercial use outside those permissions requires a separate paid license.
Contact [Emrah Diril](mailto:emrah@diril.org) for pricing and a commercial
agreement before beginning such use.

WPSync is source-available, not open source.

## Development

See [`TODO.md`](TODO.md) for the ordered work queue and
[`CHANGELOG.md`](CHANGELOG.md) for completed changes.

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
not use Git. `uv sync` rebuilds the development install when `version.json` or
the current commit changes; a copy installed with `uv tool install` keeps its
version until it is reinstalled. `wpsync --version` prints the installed version.

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
   `wpsync --version`, and uploads both artifacts. Prepared artifacts are kept
   in `dist/wpsync/<version>/` and reused if the script runs again for the same
   version.

   To prepare and validate artifacts without publishing, run
   `./scripts/publish.sh --prepare`.

3. Tag the release commit as `v<version>`, push the tag, and create a matching
   GitHub Release. PyPI does not require a tag, but it records which source was
   published.
4. Install the published version in a clean environment and run
   `wpsync --version` before announcing it.

PyPI never lets a published version be replaced. If publication fails after
PyPI accepted either artifact, make another commit (an empty commit is enough)
and publish the new version.
