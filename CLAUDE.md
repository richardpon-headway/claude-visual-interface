# CVI — working notes for Claude

## Development workflow: always use a git worktree

Do all CVI code changes in a **separate git worktree**, never in the main checkout.
The user runs the app from the main checkout (`make run`: daemon on :47825, web on
:5175); editing those files directly can blank or crash the running app mid-edit.

- Create one per change: `git worktree add ../cvi-<slug> -b feat/<slug>`
- Do edits and run tests inside the worktree.
- Ship via PR → merge to `main`. The user then `git pull` + restarts `make run` to
  pick it up. Edits in the worktree are **not** live in the running app until merged,
  pulled, and restarted — that isolation is the point.
- To preview a change live in isolation, run a second `make run` from the worktree on
  alternate ports.

## Implementing a ticket: use the ticket's worktree

When implementing a feature for a ticket, work in **that ticket's worktree** if one
exists (match by the ticket id / branch name). Resolution order:

1. **Ticket worktree exists** → implement there.
2. **No worktree, but a matching branch exists** → check that branch out (in a
   worktree per above) and implement there.
3. **Neither — just a single checkout, no worktrees** → **stop and ask the user** how
   to proceed before editing. They may not use worktrees at all, and may or may not be
   OK with changes applied directly in the one shared checkout. Don't auto-edit a lone
   checkout without confirming.

## Run / test

- Run the app: `make run` (from the repo root).
- Daemon tests: `make test` (`uv run pytest tests/`). Lint: `uv run ruff check daemon/ tests/`.
- Web: `cd web && npx tsc -b --noEmit` (typecheck) · `npx vitest run` (tests) · `npm run build`.
