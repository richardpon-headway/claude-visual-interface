.PHONY: install run test clean backfill-sidecars

PYTHON ?= 3.13

# Resolve pnpm through mise rather than PATH: ~/.local/bin holds Headway's Chainguard
# pnpm launcher, which login PATH puts ahead of mise's pnpm and which fails in a repo
# with no `packageManager` field (like this one). Asking mise directly sidesteps that.
PNPM ?= $(shell mise which pnpm 2>/dev/null || command -v pnpm 2>/dev/null || echo pnpm)

install:
	mise trust >/dev/null 2>&1 || true
	mise install
	uv sync --python $(PYTHON)
	@if [ -f web/package.json ]; then cd web && $(PNPM) install; else echo "web/package.json not present yet — skipping pnpm install"; fi

run:
	@echo "starting daemon (:47825)"
	@(uv run python -m daemon.main 2>&1 | sed 's/^/[daemon] /') & \
	 (if [ -f web/package.json ]; then cd web && $(PNPM) dev 2>&1 | sed 's/^/[web]    /'; fi) & \
	 wait

test:
	uv run pytest tests/ -v

clean:
	rm -rf .venv web/node_modules web/dist daemon/static

backfill-sidecars:
	uv run python -m daemon.backfill_sidecars
