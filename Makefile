IMAGE := ghcr.io/jaysoffian/abshelver:latest

.PHONY: build
build:
	podman build --platform linux/amd64 \
		--build-arg GIT_COMMIT=$$(git rev-parse --short HEAD) \
		-t $(IMAGE) .

.PHONY: image
image: build
	podman save -o abshelver.tar $(IMAGE)

# Expects ABSHELVER_IMPORT_DIR and ABSHELVER_LIBRARY_DIR (and optionally
# AUDIOBOOKSHELF_URL) in the environment, e.g. from mise.local.toml.
.PHONY: serve
serve:
	mise x -- uv run uvicorn abshelver.app:app --host 127.0.0.1 --port 8556 --reload

.PHONY: test
test:
	mise x -- uv run prek -a
	mise x -- uv run pytest -v

.PHONY: update
update:
	mise x -- prek autoupdate
	mise x -- uv sync --upgrade
