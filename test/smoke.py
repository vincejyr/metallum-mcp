"""End-to-end smoke test: launches the server over stdio and calls every tool
against the live site. Requests are rate-limited (3s each), so this takes a
couple of minutes. Run with: uv run python test/smoke.py  (VERBOSE=1 for output)
"""
import json
import os
import sys

import anyio
from mcp.client.client import Client, StdioServerParameters

failed = 0


async def main() -> None:
    global failed
    params = StdioServerParameters(command=sys.executable, args=["-m", "metallum_mcp.server"])
    async with Client(params, read_timeout_seconds=120) as c:
        tools = (await c.list_tools()).tools
        print("tools:", len(tools), ", ".join(t.name for t in tools))

        async def call(name, args, check):
            global failed
            res = await c.call_tool(name, args)
            text = res.content[0].text if res.content else ""
            data = res.structured_content
            if data is None:
                try:
                    data = json.loads(text)
                except Exception:
                    data = None
            try:
                passed = not res.is_error and data is not None and check(data)
            except Exception:
                passed = False
            failed += not passed
            print(f"{'PASS' if passed else 'FAIL'} {name} {json.dumps(args, ensure_ascii=False)}")
            if not passed or os.environ.get("VERBOSE"):
                print("   ", text[:1200])
            return data

        await call("search_bands", {"name": "Opeth", "limit": 3}, lambda d: d["results"][0]["ma_id"] == 38)
        await call("search_bands", {"country": "PT", "genre": "Heavy", "year_from": 1980, "year_to": 1985, "limit": 3},
                   lambda d: d["results"] and d["results"][0]["country"] == "PT" and "location" in d["results"][0])
        band = await call("get_band", {"band_id": 38},
                          lambda d: d["name"] == "Opeth" and len(d["lineup"]["current"]) >= 4 and "past" in d["lineup"])
        await call("get_band_bio", {"band_id": 38}, lambda d: len(d["bio"]) > 5000)
        await call("get_discography", {"band_id": 38, "release_types": ["Full-length"]},
                   lambda d: any(r["ma_id"] == 130 for r in d["releases"]) and all(r["type"] == "Full-length" for r in d["releases"]))
        album = await call("get_album", {"album_id": 130},
                           lambda d: d["title"] == "Blackwater Park" and len(d["tracks"]) == 8
                           and d["tracks"][0]["title"] == "The Leper Affinity" and d["lineup"]["band"])
        await call("get_lyrics", {"lyrics_id": album["tracks"][0]["lyrics_id"]},
                   lambda d: d["lyrics"].startswith("We entered winter"))
        await call("get_other_versions", {"album_id": 130}, lambda d: len(d["versions"]) > 3)
        await call("search_albums", {"title": "Blackwater Park", "band": "Opeth"},
                   lambda d: any(r["ma_id"] == 130 for r in d["results"]))
        await call("search_songs", {"title": "The Drapery Falls", "band": "Opeth", "limit": 3},
                   lambda d: d["results"][0]["lyrics_id"])
        await call("get_similar_bands", {"band_id": 38, "limit": 5}, lambda d: len(d["similar"]) == 5)
        await call("get_band_links", {"band_id": 38}, lambda d: any(l["section"] == "Official" for l in d["links"]))
        reviews = await call("get_band_reviews", {"band_id": 38, "limit": 3}, lambda d: len(d["reviews"]) == 3)
        await call("get_review", {"review_url": reviews["reviews"][0]["review_url"]}, lambda d: len(d["body"]) > 500)
        await call("get_artist", {"artist_id": 144},
                   lambda d: d["real_name"] == "Lars Mikael Åkerfeldt" and len(d["biography"]) > 500)
        await call("get_label", {"label_id": 46}, lambda d: d["name"] == "Music for Nations")
        await call("browse_bands", {"by": "genre", "value": "doom", "limit": 5}, lambda d: len(d["results"]) == 5)
        await call("browse_reviews", {"limit": 5}, lambda d: len(d["results"]) > 0)
        await call("get_upcoming_releases", {"limit": 5}, lambda d: len(d["results"]) == 5)
        await call("get_rip_artists", {"limit": 5}, lambda d: len(d["results"]) == 5)
        await call("list_countries", {}, lambda d: d["countries"].get("SE") == "Sweden")
        await call("random_band", {}, lambda d: d.get("name"))

        # Validation errors should reach the model with their message, not a generic crash.
        res = await c.call_tool("search_bands", {})
        msg = res.content[0].text if res.content else ""
        ok = res.is_error and "at least one" in msg
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'} search_bands {{}} -> error message surfaced: {msg!r}")

    print(f"\n{failed} FAILED" if failed else "\nALL PASSED")
    sys.exit(1 if failed else 0)


anyio.run(main)
