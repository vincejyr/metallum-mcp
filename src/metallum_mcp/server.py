"""MCP server exposing Encyclopaedia Metallum (metal-archives.com) via pymetal."""
from __future__ import annotations

import functools
import itertools
from typing import Any, Callable, Literal, Optional

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from typing_extensions import Annotated

from pymetal import MetalArchives

from . import extras
from .client import PoliteClient

client = PoliteClient()
ma = MetalArchives(client=client)

server = MCPServer(
    name="metallum",
    version="1.0.0",
    instructions=(
        "Look up bands, releases, artists, labels, lyrics and reviews on Encyclopaedia Metallum "
        "(metal-archives.com). Every result carries numeric ids; search first, then pass ids to "
        "the get_* tools. Requests are rate-limited to one every 3 seconds to respect the site's "
        "crawl delay, so prefer one targeted call over many speculative ones."
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

ReleaseTypeName = Literal[
    "Full-length", "EP", "Demo", "Single", "Split", "Live album", "Compilation",
    "Video", "Boxed set", "Split video", "Collaboration",
]
GenreSlug = Literal[
    "avant-garde", "black", "death", "deathcore", "doom", "electronic", "experimental", "folk",
    "gothic", "grindcore", "groove", "heavy", "industrial", "metalcore", "pagan", "power",
    "progressive", "sludge", "speed", "stoner", "symphonic", "thrash", "viking",
]
Limit = Annotated[int, Field(ge=1, le=200, description="Max results to return")]
BandId = Annotated[int, Field(gt=0, description="Metal Archives band id (from search_bands)")]
ReleaseId = Annotated[int, Field(gt=0, description="Metal Archives release id (from search_albums or get_discography)")]
ArtistId = Annotated[int, Field(gt=0, description="Metal Archives artist id (from a lineup)")]


def dump(obj: Any) -> Any:
    """Pydantic models -> plain JSON-able dicts, minus None fields and edit-audit noise."""
    if isinstance(obj, BaseModel):
        data = obj.model_dump(mode="json", exclude_none=True)
        data.pop("audit", None)
        return data
    if isinstance(obj, (list, tuple)):
        return [dump(o) for o in obj]
    return obj


def take(iterator, limit: int) -> list:
    return dump(list(itertools.islice(iterator, limit)))


def tool(title: str):
    """Register a sync function as an async, read-only tool run in a worker thread.

    pymetal is blocking (and the polite client sleeps between requests), so
    running it off the event loop keeps the stdio session responsive.
    """
    def wrap(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def runner(*args, **kwargs):
            try:
                return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))
            except (ValueError, LookupError, RuntimeError) as exc:
                # Expected failures (bad input, not found, rate limited): show the model why.
                raise ToolError(str(exc)) from exc

        return server.tool(title=title, annotations=READ_ONLY)(runner)

    return wrap


# ---------------------------------------------------------------- search


@tool("Search bands")
def search_bands(
    name: str = "",
    genre: str = "",
    country: Annotated[str, Field(description="ISO country code, e.g. 'SE', 'NO', 'US' (see list_countries)")] = "",
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    themes: Annotated[str, Field(description="Lyrical themes, e.g. 'occultism'")] = "",
    location: Annotated[str, Field(description="City/region text, e.g. 'Gothenburg'")] = "",
    label: str = "",
    limit: Limit = 25,
) -> dict:
    """Search bands by name and/or advanced filters (genre text, country, formation year range,
    lyrical themes, location, label). At least one filter is required."""
    if not any([name, genre, country, year_from, year_to, themes, location, label]):
        raise ValueError("Give at least one of: name, genre, country, year range, themes, location, label.")
    hits = take(
        ma.search_bands(
            band_name=name, genre=genre, country=country, year_from=year_from, year_to=year_to,
            themes=themes, location=location, label=label, page_size=min(limit, 200),
        ),
        limit,
    )
    if country:
        # With a country filter MA returns the band's location in that column instead.
        for h in hits:
            if "country" in h:
                h["location"] = h.pop("country").strip()
            h["country"] = country.upper()
    return {"results": hits}


@tool("Search releases")
def search_albums(
    title: str = "",
    band: str = "",
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    release_types: Optional[list[ReleaseTypeName]] = None,
    genre: str = "",
    label: str = "",
    country: Annotated[str, Field(description="ISO country code of the band")] = "",
    limit: Limit = 25,
) -> dict:
    """Search releases by title, band name, release year range, type, genre, label or country."""
    if not any([title, band, year_from, year_to, release_types, genre, label, country]):
        raise ValueError("Give at least one search criterion.")
    return {
        "results": take(
            ma.search_albums(
                release_title=title, band_name=band, year_from=year_from, year_to=year_to,
                release_type=release_types, genre=genre, label=label, country=country,
                page_size=min(limit, 200),
            ),
            limit,
        )
    }


@tool("Search songs")
def search_songs(
    title: str = "",
    band: str = "",
    lyrics: Annotated[str, Field(description="Words that appear in the lyrics")] = "",
    release_title: str = "",
    limit: Limit = 25,
) -> dict:
    """Search songs by title, band, release or lyrics text. Hits include lyrics_id for get_lyrics."""
    if not any([title, band, lyrics, release_title]):
        raise ValueError("Give at least one of: title, band, lyrics, release_title.")
    return {
        "results": take(
            ma.search_songs(
                song_title=title, band_name=band, lyrics=lyrics, release_title=release_title,
                page_size=min(limit, 200),
            ),
            limit,
        )
    }


# ---------------------------------------------------------------- bands


@tool("Get band")
def get_band(band_id: BandId) -> dict:
    """Band profile (country, location, status, formation year, genres, lyrical themes, label)
    plus lineup grouped by status (current, past, live, last_known, guest_session), with
    each member's roles and years. Use get_band_bio for the biography."""
    band = dump(ma.get_band(band_id))
    band.pop("comment", None)  # pymetal can't parse it; get_band_bio has the full text
    lineup: dict[str, list] = {}
    for m in dump(ma.get_lineup(band_id)):
        status = m.pop("status")
        m.pop("band_id", None)
        lineup.setdefault(status, []).append(m)
    band["lineup"] = lineup
    return band


@tool("Get band biography")
def get_band_bio(band_id: BandId) -> dict:
    """Full band biography / history text."""
    return {"band_id": band_id, "bio": extras.band_bio(client, band_id)}


@tool("Get discography")
def get_discography(
    band_id: BandId,
    release_types: Optional[list[ReleaseTypeName]] = None,
) -> dict:
    """A band's releases with id, type, release year and review stats. Optionally filter by type."""
    releases = dump(ma.get_discography(band_id))
    if release_types:
        releases = [r for r in releases if r.get("type") in release_types]
    for r in releases:
        if not r.get("band_ids"):
            r.pop("band_ids", None)
    return {"band_id": band_id, "releases": releases}


@tool("Get similar bands")
def get_similar_bands(band_id: BandId, limit: Limit = 15) -> dict:
    """User-voted similar artists, ordered by match score (number of votes)."""
    return {"band_id": band_id, "similar": dump(ma.get_band_recommendations(band_id)[:limit])}


@tool("Get band links")
def get_band_links(band_id: BandId) -> dict:
    """External links for a band (official site, Bandcamp, Spotify, socials, merch), by section."""
    return {"band_id": band_id, "links": dump(ma.get_links(band_id))}


@tool("Get band reviews")
def get_band_reviews(band_id: BandId, limit: Limit = 25) -> dict:
    """Review list for a band's releases: release, score %, reviewer, date and review_url.
    Metadata only — pass review_url to get_review for the full text."""
    reviews = take(ma.get_band_reviews(band_id, paginate=False, page_size=min(limit, 200)), limit)
    for r in reviews:
        if not r.get("band_name"):
            r.pop("band_name", None)
    return {"band_id": band_id, "reviews": reviews}


@tool("Get random band")
def random_band(genre: Optional[GenreSlug] = None) -> dict:
    """A random band from the archive, optionally from a coarse genre bucket. Genre-filtered
    picks re-roll until they match, so they can take up to ~30 seconds."""
    return dump(ma.random_band(genre=genre, max_attempts=5 if genre else 2, sleep_between=0))


# ---------------------------------------------------------------- releases


@tool("Get release")
def get_album(album_id: ReleaseId) -> dict:
    """Release details (type, date, label, catalog no., format, review stats, notes), the
    tracklist (with per-track lyrics_id), and the lineup split into band / guest / staff."""
    release, songs, appearances = ma.get_release(album_id)
    out = dump(release)
    if not out.get("band_ids"):
        out.pop("band_ids", None)
    by_song = {s.ma_id: s for s in songs}
    tracks = []
    for a in sorted(appearances, key=lambda a: (a.disc_no, a.track_no)):
        s = by_song.get(a.song_id)
        t = {
            "disc": a.disc_no,
            "track": a.track_no,
            "title": a.title_override or (s.title if s else None),
            "length": a.length,
            "song_id": a.song_id,
            "lyrics_id": s.lyrics_id if s else None,
            "bonus": a.is_bonus or None,
            "instrumental": a.is_instrumental or None,
            "band_id": a.band_id or None,  # set on splits only
        }
        tracks.append({k: v for k, v in t.items() if v is not None})
    out["tracks"] = tracks
    lineup: dict[str, list] = {}
    for m in dump(ma.get_release_lineup(album_id)):
        section = m.pop("section", "band")
        m.pop("release_id", None)
        lineup.setdefault(section, []).append(m)
    out["lineup"] = lineup
    return out


@tool("Get other versions")
def get_other_versions(album_id: ReleaseId) -> dict:
    """Other versions of a release: reissues, remasters, regional and format editions."""
    return {"album_id": album_id, "versions": dump(ma.get_other_versions(album_id))}


@tool("Get lyrics")
def get_lyrics(lyrics_id: Annotated[str, Field(description="lyrics_id from get_album tracks or search_songs")]) -> dict:
    """Lyrics for a song."""
    text = ma.get_lyrics_by_song_id(lyrics_id)
    if text:
        text = text.replace("\r\n", "\n").strip()
    return {"lyrics_id": lyrics_id, "lyrics": text or None}


@tool("Get review")
def get_review(review_url: Annotated[str, Field(description="review_url from get_band_reviews or browse_reviews")]) -> dict:
    """Full text of a single review: title (with score), author, date and body."""
    if "metal-archives.com/reviews/" not in review_url:
        raise ValueError("review_url must be a metal-archives.com/reviews/... URL")
    return extras.review(client, review_url)


# ---------------------------------------------------------------- artists & labels


@tool("Get artist")
def get_artist(artist_id: ArtistId, include_bio: bool = True) -> dict:
    """Artist profile (real name, born/died, cause of death, origin) plus, by default, the full
    biography and trivia (two extra requests)."""
    out = dump(ma.get_artist(artist_id))
    out.pop("biography", None)  # pymetal can't parse it; fetched below
    if include_bio:
        out["biography"] = extras.artist_bio(client, artist_id)
        out["trivia"] = extras.artist_trivia(client, artist_id)
    return out


@tool("Get label")
def get_label(label_id: Annotated[int, Field(gt=0, description="Label id (from a band or release)")]) -> dict:
    """Record label profile: country, status, address, styles, founding date, sub-labels, parent."""
    return dump(ma.get_label(label_id))


# ---------------------------------------------------------------- browse & discovery


@tool("Browse bands")
def browse_bands(
    by: Literal["country", "genre", "letter"],
    value: Annotated[str, Field(description="Country code ('NO'), genre slug ('black'), or letter ('A', 'NBR' for numbers, '~' for other)")],
    limit: Limit = 50,
) -> dict:
    """List bands from the catalog by country, coarse genre, or first letter (first `limit` rows)."""
    fn = {
        "country": ma.browse_bands_by_country,
        "genre": ma.browse_bands_by_genre,
        "letter": ma.browse_bands_by_letter,
    }[by]
    return {"by": by, "value": value, "results": take(fn(value, paginate=False, page_size=limit), limit)}


@tool("Browse reviews")
def browse_reviews(
    year: Optional[int] = None,
    month: Annotated[Optional[int], Field(ge=1, le=12)] = None,
    limit: Limit = 50,
) -> dict:
    """Reviews posted in a given month (defaults to the current month). Metadata only;
    use get_review for the text."""
    return {"results": take(ma.browse_reviews(year=year, month=month, paginate=False, page_size=limit), limit)}


@tool("Get upcoming releases")
def get_upcoming_releases(limit: Limit = 50) -> dict:
    """Upcoming releases, soonest first."""
    return {"results": take(ma.get_upcoming_releases(paginate=False, page_size=limit), limit)}


@tool("Get deceased artists")
def get_rip_artists(limit: Limit = 50) -> dict:
    """Metal Archives' R.I.P. list: deceased artists with band, date and cause of death."""
    return {"results": take(ma.get_rip_artists(paginate=False, page_size=limit), limit)}


@tool("List countries")
def list_countries() -> dict:
    """Country codes Metal Archives uses (for country filters and browse_bands)."""
    return {"countries": ma.list_countries()}


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
