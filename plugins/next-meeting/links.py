"""Join-link detection for calendar events. Standard library only, no bar needed.

A "Join" button only makes sense for a video-meeting provider, so the first URL
whose host belongs to one of them wins; any https URL in the LOCATION field is
the fallback for self-hosted or unknown tools.
"""

import html
import re
from collections.abc import Iterable
from urllib.parse import urlsplit

URL = re.compile(r"https?://[^\s<>\"'\\]+")
TRAILING = ".,;:!?)>]}"
# Host suffixes of the providers a Join button is offered for.
PROVIDERS = (
    "zoom.us",
    "zoom.com",
    "zoomgov.com",
    "meet.google.com",
    "teams.microsoft.com",
    "teams.live.com",
    "teams.cloud.microsoft",
    "webex.com",
    "meet.jit.si",
    "whereby.com",
    "goto.com",
    "gotomeeting.com",
    "gotomeet.me",
    "gotowebinar.com",
    "bluejeans.com",
)


def urls_in(text: str) -> list[str]:
    """Every http(s) URL in a text: HTML entities decoded, trailing punctuation dropped."""
    return [match.group(0).rstrip(TRAILING) for match in URL.finditer(html.unescape(text))]


def is_meeting_url(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return any(host == provider or host.endswith("." + provider) for provider in PROVIDERS)


def find_join_url(fields: Iterable[str], location: str = "") -> str:
    """The first provider URL across the fields, in order; else the first https URL in the location."""
    for text in fields:
        for url in urls_in(text):
            if is_meeting_url(url):
                return url
    return next((url for url in urls_in(location) if url.startswith("https://")), "")
