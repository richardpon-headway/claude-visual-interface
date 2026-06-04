.PHONY: install run test clean

PYTHON ?= 3.13

install:
	mise trust >/dev/null 2>&1 || true
	mise install
	uv sync --python $(PYTHON)
	@if [ -f web/package.json ]; then cd web && pnpm install; else echo "web/package.json not present yet — skipping pnpm install"; fi

run:
	@echo "starting daemon (:47825)"
	@(uv run python -m daemon.main 2>&1 | sed 's/^/[daemon] /') & \
	 (if [ -f web/package.json ]; then cd web && pnpm dev 2>&1 | sed 's/^/[web]    /'; fi) & \
	 wait

test:
	uv run pytest tests/ -v

clean:
	rm -rf .venv web/node_modules web/dist daemon/static
