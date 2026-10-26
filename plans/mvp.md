# WPSync — MVP

## Purpose

WPSync is a local-first CLI tool for managing WordPress blog posts as Markdown files, without using the WordPress editor.

It follows the same UX philosophy as HLSync: simple commands, predictable synchronization, and explicit control over changes.

## Core workflow

```bash
wpsync init    # Connect a local directory to a WordPress blog
wpsync pull    # Import or update local posts from WordPress
wpsync diff    # Preview differences between local and remote
wpsync push    # Publish local changes to WordPress
```

- **Local-first:** Users write and edit Markdown files in any editor.
- **Bidirectional:** Existing WordPress posts can be pulled locally; local changes can be pushed back.
- **Incremental:** Only changed content is synchronized.
- **Safe:** Never silently overwrite conflicting changes or delete content.
- **Predictable:** No automatic synchronization or publishing.

## Content

Each post is represented by a Markdown file with YAML frontmatter.

Supported content includes:

- Title, slug, date, status (draft/published), categories, and tags.
- Markdown text, links, and images.
- Local images that are uploaded to and retrieved from WordPress.
- Existing WordPress posts, preserving their identity and permalinks.

WordPress remains responsible for presentation, themes, and public URLs.

## Synchronization behavior

**Pull**
- Initial pull imports existing WordPress posts as local Markdown files.
- Subsequent pulls retrieve remote changes.
- Existing local edits are protected.
- HTML/Gutenberg conversion limitations are reported; unsupported content must not be silently lost.

**Diff**
- Shows new, modified, deleted, and conflicting posts.
- Clearly indicates which side has changed.
- Does not modify anything.

**Push**
- Creates new posts and updates existing ones.
- Preserves WordPress post identities.
- Uploads referenced images as needed.
- Refuses conflicting changes unless explicitly resolved.
- Remote deletion is a separate, explicitly requested operation.

## User experience

- Minimal CLI with clear, readable output.
- Project configuration stored locally.
- Authentication configured during initialization; credentials stored securely.
- Remember synchronization state between runs.
- Useful errors and actionable conflict messages.
- Safe defaults; no surprises.

## Out of scope for MVP

- GUI or web editor.
- Background synchronization or file watching.
- Multiple blogging platforms.
- Multi-site synchronization from a single project.
- Full Gutenberg round-trip fidelity for arbitrary blocks.
- WordPress theme, plugin, or site administration.
- Sharing code or dependencies with HLSync.

## Success criteria

A user can connect an existing WordPress blog, pull its posts into a local directory, edit them in Markdown, preview changes, and push updates back without losing content or unintentionally modifying other posts.

**The guiding principle: Local files are the working environment; WordPress is the publishing platform.**