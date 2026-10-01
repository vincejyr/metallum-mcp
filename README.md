# Metallum MCP

An MCP server that lets Claude (or any MCP client) look things up in [Encyclopaedia Metallum (metal-archives.com)](https://www.metal-archives.com): bands, lineups over time, discographies, releases, tracklists, lyrics, artists, labels, reviews, similar bands and catalog browsing.

It is built on [pymetal](https://github.com/LeMetadatarr/pymetal), wrapped with a rate-limited client and a few extra fetchers for things pymetal doesn't cover.

## Tools (22)

**Search**
| Tool | What it does |
|---|---|
| `search_bands` | By name and/or advanced filters: genre, country, formation year range, lyrical themes, location, label. Pages with `offset`; returns `total` and `next_offset` |
| `search_albums` | By title, band, year range, release type, genre, label, country. Pages like `search_bands` |
| `search_songs` | By title, band, release, or **words in the lyrics** |

**Bands**
| Tool | What it does |
|---|---|
| `get_band` | Profile plus lineup grouped by current / past / live / last-known / guest, with each member's roles and years |
| `get_band_bio` | Full biography (the band page only shows an excerpt) |
| `get_discography` | Releases with type, year and review stats, optionally filtered by type, year range, or reviewed releases only |
| `band_review_stats` | For up to 25 bands at once: release count, review count and review-weighted average score, sorted best first. Filters by type, year range and minimum reviews |
| `get_similar_bands` | User-voted similar artists, ranked by votes |
| `get_band_links` | Official site, Bandcamp, Spotify, socials, merch |
| `get_band_reviews` | Review list (score, reviewer, date, URL) |
| `random_band` | A random band, optionally from a genre bucket |

**Releases**
| Tool | What it does |
|---|---|
| `get_album` | Details, tracklist (per-disc, bonus/instrumental flags, `lyrics_id`), lineup split into band / guest / staff |
| `get_other_versions` | Reissues, remasters and regional editions |
| `get_lyrics` | Lyrics by `lyrics_id` |
| `get_review` | Full text of one review |

**People and labels**
| Tool | What it does |
|---|---|
| `get_artist` | Real name, born/died, cause of death, origin, plus full biography and trivia |
| `get_label` | Address, styles, founding date, sub-labels, parent label |

**Browse and discovery**
| Tool | What it does |
|---|---|
| `browse_bands` | By country code, genre bucket or first letter |
| `browse_reviews` | Reviews posted in a given month |
| `get_upcoming_releases` | Upcoming releases, soonest first |
| `get_rip_artists` | The R.I.P. list |
| `list_countries` | Country codes for filters |

Typical flow: `search_bands` → `get_band` / `get_discography` → `get_album` → `get_lyrics`.

For "which bands are rated highest" questions: page through `search_bands`, then pass batches of ids to `band_review_stats`. Averages come from Metal Archives' rounded per-release averages, so treat scores within about half a point as ties.

## Setup

Requires [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for the project; your system Python is not used.

```bash
git clone https://github.com/vincejyr/metallum-mcp.git
cd metallum-mcp
uv sync                        # create .venv and install pinned deps
uv run python test/smoke.py    # end-to-end test against the live site (~75s)
```

### Claude Code

```bash
claude mcp add --scope user metallum -- "$(pwd)/.venv/bin/metallum-mcp"
```

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS), using the absolute path to your clone:

```json
{
  "mcpServers": {
    "metallum": {
      "command": "/absolute/path/to/metallum-mcp/.venv/bin/metallum-mcp"
    }
  }
}
```

## How it uses pymetal

- **Pinned** to commit `ce5d75a` (v1.2.0a1, reviewed 2026-10-01). PyPI's `pymetal` is an older release published from a different repo, so install from git.
- **No anti-bot layer.** The `antibot` extra (`unblock_requests`: Cloudflare challenge solving, Wayback Machine fallback) is deliberately not installed. Plain requests work fine.
- **Polite client** (`src/metallum_mcp/client.py`) replaces pymetal's HTTP behaviour:
  - It doesn't impersonate Chrome's TLS fingerprint, and sends a fixed, honest User-Agent instead of a random one on every request.
  - It enforces the site's `Crawl-delay: 3` across all requests and threads.
  - It caches responses in memory for 30 minutes, and discography pages on disk for 7 days (SQLite at `~/.cache/metallum-mcp/`), so review-stat scans survive restarts and don't re-crawl.
- **Browse and review tools fetch one page only** (`paginate=False`). pymetal's default is to walk the entire catalogue.

### Gaps in pymetal that this server fills (`extras.py`)

| Gap | Fix |
|---|---|
| `Band.comment` is always `None` (wrong HTML selector) | `get_band_bio` reads the site's "read more" endpoint |
| `Artist.biography` is always `None` (bio is loaded separately) | `get_artist` fetches the bio and trivia from the "read more" endpoints |
| No way to get a review's text | `get_review` parses the review page |
| With a country filter, `search_bands` puts the band's location in `country` | `search_bands` moves it to `location` and fills `country` from the filter |

These are worth reporting upstream.


## Settings

| Variable | Default | Purpose |
|---|---|---|
| `MA_MIN_INTERVAL_MS` | `3000` | Minimum gap between requests |
| `MA_CACHE_TTL_MS` | `1800000` | In-memory cache lifetime |
| `MA_DISK_CACHE_TTL_DAYS` | `7` | Disk cache lifetime for discographies (`0` disables it) |
| `MA_CACHE_DIR` | `~/.cache/metallum-mcp` | Disk cache location |
| `MA_USER_AGENT` | `Mozilla/5.0 (compatible; metallum-mcp/1.0; personal use)` | User-Agent header |

## Notes

- Each uncached request takes about 3 seconds. `get_artist` with its bio makes 3 requests, and a genre-filtered `random_band` can take up to about 30 seconds. `band_review_stats` makes one request per uncached band, so a full batch of 25 takes about 75 seconds the first time.
- Meant for personal, interactive lookups, not bulk scraping.
- Parsing depends on the site's HTML. If a tool starts returning empty fields, run the smoke test to see which one broke.
- Uses MCP Python SDK 2.x (`MCPServer`, formerly `FastMCP`).

## Layout

```
src/metallum_mcp/server.py   MCP server and tool definitions
src/metallum_mcp/client.py   rate-limited, cached HTTP client for pymetal
src/metallum_mcp/extras.py   bios, trivia, review text
test/smoke.py                      end-to-end test through a real MCP client
```

## Credits and disclaimer

- Data comes from [Encyclopaedia Metallum](https://www.metal-archives.com), maintained by its volunteer community. This project is not affiliated with or endorsed by Metal Archives. Please respect the site and its rate limits.
- Built on [pymetal](https://github.com/LeMetadatarr/pymetal) (Apache-2.0).

## License

MIT. See [LICENSE](LICENSE).
