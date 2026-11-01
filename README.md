# abshelver

**abshelver** is a companion web app to [Audiobookshelf](https://www.audiobookshelf.org/) to help with importing and organizing your audiobook library:

- **Import** audiobooks from an import directory to your library, naming the destination directory and file(s) according to audiobook title, narrator(s), author(s), series and sequence, with values pre-filled from audiofile metadata tags. You can edit these values and preview the import before any action is taken. Besides importing the audiobook file(s), an ABS-compatible `metadata.json` is written to the destination directory.
- **Organize** your library by scanning for ABS `metadata.json` files and then renaming audiobook directories and files to match, optionally removing stray files and empty directories. All actions to be taken are previewed first. Select only those actions you want to be taken.

(See [this repo's wiki](https://github.com/jaysoffian/abshelver/wiki) for examples of the web UI.)

## Library Layout

This program uses a single hard-coded library layout as follows:

```
/audiobooks/
  {Authors}/                                       # comma-separated author names
    {Title} {Narrators}/                           # standalone book
      {Title} {Narrators} - {Authors}.m4b
      {Title} {Narrators} - {Authors}.epub         # optional
    {Title} {Narrators}/                           # multi-file book
      {Title} {TT} {Narrators} - {Authors}.mp3     # TT is 01, 02, ... or 001, 002, ...
    {Series}/
      {N}. {Title} {Narrators}/                    # book in a series
        {Series} {N} - {Title} {Narrators} - {Authors}.m4b
```

Multi-file books get ` {TT} ` (two-digit or three-digit track number) after the title:
`{Title} {TT} {Narrators} - {Authors}.mp3`.

Authors and narrators are whatever Audiobookshelf says they are in `metadata.json` with more than one author or narrator joined by `, `.

For many authors, consider listing just a few and "et al" as the final author.

For many narrators such as a full cast performance, consider "Full Cast" as the narrator.

`/`, `\` and `:` in names become ` - `.

(See [this repo's wiki](https://github.com/jaysoffian/abshelver/wiki) for how this looks with a real-world library.)

## Configuration

| Variable | Required | Meaning |
|---|---|---|
| `ABSHELVER_IMPORT_DIR` | yes | directory scanned for import candidates |
| `ABSHELVER_LIBRARY_DIR` | yes | the Audiobookshelf library root |
| `AUDIOBOOKSHELF_URL` | no | base URL of the Audiobookshelf web UI, for the *Audiobookshelf ↗* link |

The `Dockerfile` defaults the first two to `/downloads` and `/audiobooks`. Startup
fails if either directory does not exist.

## Docker Compose

```yaml
services:
  abshelver:
    image: ghcr.io/jaysoffian/abshelver:latest
    user: "568:568"      # same uid/gid as the Audiobookshelf container
    ports: ["8556:8556"]
    environment:
      AUDIOBOOKSHELF_URL: https://audiobooks.example.org
    volumes:
      - /mnt/pool/media/Downloads:/downloads
      - /mnt/pool/media/AudioBooks:/audiobooks
    restart: unless-stopped
```

Mount the library at the same path Audiobookshelf uses. If the import directory and the
library are on the same filesystem, imports are instant renames; otherwise files are copied,
size-checked, then deleted.

## CLI

```
abshelver organize            scan the library, print every issue and the ordered
                              ops that would fix it; exit 1 if there are any
abshelver organize --doit     the same, then apply all of them
```

e.g.

```
ABSHELVER_LIBRARY_DIR="/Volumes/Media/AudioBooks" \
ABSHELVER_IMPORT_DIR="/Volumes/Media/Downloads" \
uv run abshelver organize
```

## License

[MIT](LICENSE.md).
