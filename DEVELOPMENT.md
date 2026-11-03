# Development notes

Only what the code and commit messages can't tell you.

## Tooling

```
uv sync                 # venv with dev tools (pytest, ruff, ty)
make serve              # http://127.0.0.1:8556 with reload; needs the env vars
make test               # prek hooks (ruff, ty, pyright, hadolint) + pytest
make build              # podman image for linux/amd64
```

`ffprobe` (ffmpeg) must be on the PATH. Put the env vars in `mise.local.toml`
(gitignored), pointing at the SMB/NFS mounts, so `make serve` and the CLI dry
run work against the real library. `prek install` adds the git hook.

## How Audiobookshelf behaves (verified against v2.37.2)

- The library's metadata precedence is folder structure, then audio tags,
  then ... then the item's `metadata.json`, later sources winning. After the
  first scan Audiobookshelf rewrites `metadata.json` in full and owns it.
- `"narrators": []` in `metadata.json` means "clear", not "unset".
- The folder watcher batches events and scans about 10 s after the last one.
  It ignores dot-files and `.tmp`/`.part` names, but not `.json`.
- Items are tracked by inode, so same-filesystem renames keep listening
  progress.
- A file like `Foo.tmp.aac` still shows up as a library file.
