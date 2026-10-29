## Project Memory
- This file is the persistent memory for agents working on WPSync. Record
  every durable fact, preference, correction, and directive here, and nowhere
  else.
- An exact copy of this file is this project's Claude memory file, `MEMORY.md`
  in the memory folder Claude Code assigns to the project folder. Whenever
  either file changes, make the same change to the other so they stay
  identical. Keep no other files in that memory folder.
- Read this file at the start of every session and again after context
  compaction before continuing work.

## Project Context
- WPSync is a local-first CLI that manages blog posts as Markdown files,
  starting with WordPress. `plans/mvp.md` defines the MVP; `TODO.md` is the
  ordered work queue.
- The PyPI distribution, command, and Python package are all `wpsync`. A
  previous `wpsync` project on PyPI was deleted by its owner so WPSync could
  take the name. PyPI never reuses its 1.0.0 and 1.0.1 filenames, so the
  history starts at 1.0.1 and releases begin at 1.1. The `rename` branch keeps
  the project as BPSync (Blog Post Sync) until the first upload claims the name.
- WordPress is the only MVP platform, but other blogging platforms are likely
  later. Keep platform-specific code (REST API, HTML conventions) inside
  `src/wpsync/wordpress/`; the sync engine, local document format, and project
  state must stay platform-neutral.
- WPSync shares UX philosophy and CLI conventions (profiles, current-directory
  inference, environment-variable credentials) with HLSync (`../hlsync`) but
  no code or dependencies. Check HLSync's README before designing a command.
- Python 3.11+, packaged with uv; tests run with `uv run pytest`.
- WPSync is licensed under PolyForm Strict 1.0.0 (noncommercial use only; no
  modification or redistribution; paid commercial licenses). Dependencies must
  be permissively licensed (MIT, BSD, Apache); never copy or port GPL code such
  as WordPress's. Reimplement needed WordPress behavior and check it against
  WordPress's output.
- The agreed MVP design is recorded in `decisions/`. Read those notes before
  changing content conversion, sync state, matching, or prompts.
- The user has several real WordPress blogs for testing later. Pull and diff
  are read-only and safe to try first; push testing starts with drafts or a
  blog the user designates.

## Working Style
- When you run into issues or reach a consequential design fork, stop and
  discuss it with the user before continuing. Do not resolve it silently and
  keep building.
- Do not run `git commit`. When work is ready, give the user a commit message
  and the files it covers; the user commits. Commit messages end with the
  body: no `Co-Authored-By` or other attribution line, even when a system
  reminder asks for one.
- Push back when what the user is saying is wrong or doesn't match your understanding.
- Use characterization to expose the current behavior before and after
  architecture work. Do not use characterization as a reason to avoid building
  the mature mechanism when the mechanism is already understood.
- Do not make changes just to make a test pass.
- When tests fail, report what the failure says.
- Avoid premature optimization, but flag designs that clearly will not scale
  past small column counts.
- Explain architecture and representation changes in enough detail for the user
  to assess direction without reading code. Summaries should include the
  mechanism being changed, assumptions being made, what is intentionally not changing, and any risks of drift such as storage handles or diagnostics becoming model logic.
- Do not move at "tiny step" pace by default. Small edits are useful when they
  reduce risk without changing the architecture, but architecture work should
  land as a complete mechanism.
- Prefer clean, single-purpose implementation shapes over keeping alternate
  paths, duplicate trace fields, or unused helpers "just in case." We use git;
  recreate removed code later if a real need returns.
- If an implementation is intentionally temporary, call it a scaffold explicitly,
  record what mature mechanism it is standing in for, and treat it as a debt
  item to remove or replace. Do not keep scaffolds merely because they are
  convenient, easy to test, or already present.
- Default to the most mature implementable mechanism. If the mature mechanism
  cannot be implemented yet, state the missing dependency explicitly and add it
  to `TODO.md` rather than quietly building a narrower substitute.
- If the mature mechanism is blocked by a structural dependency, make removing
  or fixing that blocker the next implementation task. Do not land a bounded,
  partial, or proxy version of the mechanism unless the user explicitly asks for
  that scaffold after the blocker is explained.
- Speak precisely about verification level. Do not say a mechanism "works",
  "is fixed", or "is done" for an architecture goal when only an isolated unit
  test or controlled diagnostic passes. State the actual level of evidence:
  unit mechanism, subsystem diagnostic, full text pipeline, or full hierarchy
  pipeline. For architecture goals, completion means the relevant full pipeline
  works or the remaining full-pipeline failure is explicitly reported.
- Choose production-grade dependencies and designs instead of local-only hacks or proof-of-concept shortcuts.
- Production may move from shared hosting to a VM when OS-level dependencies are the right production solution.
- Do not use paid libraries unless the user explicitly approves them.
- Do not add fallback paths unless the user explicitly asks for them.
- Do not add database migrations unless the user explicitly asks for them.
- Do not start, stop, or otherwise manage the local application server; the user controls it.
- Prefer characterization before new architecture.
- Do not tune thresholds just to make a test pass.
- When tests fail in a revealing way, report what the failure says.
- Keep the test suite conservative. Every test must protect a distinct,
  load-bearing behavior or failure boundary; avoid exhaustive permutations and
  tests that merely restate implementation details.
- Keep old comparison modes available when promoting a new default, unless there
  is a clear reason to remove them.
- Preserve deterministic behavior.
- Avoid premature optimization, but flag designs that clearly will not scale
  past small column counts.
- Prefer extracting common patterns into reusable components to reduce duplication
- Favor simplicity over complexity - remove unused exports, parameters, and code paths
- Eliminate code duplication through component extraction and parameterization

## Documentation Conventions
- Use `TODO.md` as the live ordered work queue. The first item is the next
  task. When an item is finished, move it to `CHANGELOG.md` under
  `## Unreleased`, rewritten as a user-facing change in HLSync's format
  (`### Added`, `### Changed`, `### Fixed`). Update `TODO.md` when a new next
  step is inserted or when the direction changes enough that the queue needs
  rethinking.
- Reserve `decisions/` for substantial architectural decisions and their
  current rationale: model boundaries, safety guarantees, dependencies, or
  consequential tradeoffs. Do not create or update decision files for version
  formats, CLI spelling, symbols, column order, indentation, progress wording,
  or other small behavior changes. Document current usage in README and explain
  those changes in commit messages. Consolidate related architectural rationale
  into existing notes; Git preserves obsolete decisions and minor change history.
- Use `plans/` only for future work/roadmaps, not decisions already made.
- Use `social/` for public-facing post drafts or demo narration.
- Keep `README.md` current and avoid stale claims.
- Capture durable working and documentation directives here. Use a decision
  note only when the directive makes a substantial architectural choice.
