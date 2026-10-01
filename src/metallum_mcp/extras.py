"""Small fetchers for data pymetal doesn't cover (as of ce5d75a).

- Band and artist bios: the pages only embed a truncated excerpt and load the
  full text from a separate "read more" endpoint. pymetal's parsers miss both
  (Band.comment and Artist.biography come back None).
- Review text: pymetal returns review metadata only; there is no get_review.
"""
from __future__ import annotations

import re
from typing import Optional

from lxml import html as lxml_html

from pymetal.http import Client


def _text(fragment: str) -> Optional[str]:
    if not fragment.strip():
        return None
    root = lxml_html.fromstring(f"<div>{fragment}</div>")
    for br in root.iter("br"):
        br.tail = "\n" + (br.tail or "")
    text = root.text_content().replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or None


def band_bio(client: Client, band_id: int) -> Optional[str]:
    return _text(client.get(f"band/read-more/id/{band_id}").text)


def artist_bio(client: Client, artist_id: int) -> Optional[str]:
    return _text(client.get(f"artist/read-more/id/{artist_id}").text)


def artist_trivia(client: Client, artist_id: int) -> Optional[str]:
    return _text(client.get(f"artist/read-more/id/{artist_id}/field/trivia").text)


def review(client: Client, review_url: str) -> dict:
    page = client.get(review_url).text
    root = lxml_html.fromstring(page)
    box = root.xpath('//div[contains(@class,"reviewBox")]')
    if not box:
        raise LookupError(f"No review found at {review_url}")
    box = box[0]
    title = box.xpath('.//h3[contains(@class,"reviewTitle")]')
    content = box.xpath('.//div[contains(@class,"reviewContent")]')
    byline = box.xpath('.//a[contains(@class,"profileMenu")]')
    byline_text = byline[0].getparent().text_content() if byline else ""
    date = re.search(r",\s*([A-Z][a-z]+ \d{1,2}(?:st|nd|rd|th)?, \d{4})", byline_text)
    return {
        "review_url": review_url,
        "title": re.sub(r"\s+", " ", title[0].text_content()).strip() if title else None,
        "author": byline[0].text_content().strip() if byline else None,
        "posted_on": date.group(1) if date else None,
        "body": _text(lxml_html.tostring(content[0], encoding="unicode")) if content else None,
    }
