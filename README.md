# abshelver

**abshelver** is a companion web app to [Audiobookshelf](https://www.audiobookshelf.org/) to help with importing and organizing your audiobook library:

- **Import** audiobooks from an import directory to your library, naming the destination directory and file(s) according to audiobook title, narrator(s), author(s), series and sequence, with values pre-filled from audiofile metadata tags. You can edit these values and preview the import before any action is taken. Besides importing the audiobook file(s), an ABS-compatible `metadata.json` is written to the destination directory.
- **Organize** your library by scanning for ABS `metadata.json` files and then renaming audiobook directories and files to match, optionally removing stray files and empty directories. All actions to be taken are previewed first. Select only those actions you want to be taken.
- **Library** shows a `tree`-style listing of your library. Author, series and book names link to their Audiobookshelf pages when an API key is configured, and audiobooks and ebooks can be downloaded directly.

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

Configuration is via the following environment variables:

- `ABSHELVER_IMPORT_DIR`: Directory scanned for audiobooks to import to your library. Required. `Dockerfile` default is `/downloads`.

- `ABSHELVER_LIBRARY_DIR`: Audiobookshelf library root directory. Required. `Dockerfile` default is `/audiobooks`.

- `AUDIOBOOKSHELF_URL`: Audiobookshelf base URL. e.g. `https://audiobookshelf.example.org`. No default. Configure to add a button that links to your Audiobookshelf installation.

- `AUDIOBOOKSHELF_API_KEY`: [Audiobookshelf API key](https://audiobookshelf.org/docs/documentation/server-management/api-keys). No default. Configure to allow Library page items to link to their corresponding author, series, and audiobook pages in your Audiobookshelf installation. `AUDIOBOOKSHELF_URL` must also be configured. This key should be associated with a read-only guest user. e.g. create a guest user named `abshelver` with a random password and grant the user only the three "access" permissions. Then create an API key named `abshelver` associated to the `abshelver` guest user.

## Docker Compose

```yaml
services:
  abshelver:
    image: ghcr.io/jaysoffian/abshelver:latest
    user: "568:568"      # same uid/gid as the Audiobookshelf container
    ports: ["8556:8556"]
    environment:
      ABSHELVER_IMPORT_DIR: /media/downloads
      ABSHELVER_LIBRARY_DIR: /media/audiobooks
      AUDIOBOOKSHELF_URL: https://audiobooks.example.org
      AUDIOBOOKSHELF_API_KEY: ${ABS_API_KEY}
    volumes:
      - /path/to/media:/media  # See note 1.
    restart: unless-stopped
```

<sup>1: Files are moved from the import directory to the library directory if both are under the same mount point; otherwise they are copied and then deleted.</sup>

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

[MIT](LICENSE.md)
