"""Download each image listed in song.json and shrink it to 1000 px.

A source is a direct URL, or "commons:<file name>" for Wikimedia Commons.
Usage: python3 scripts/fetch_images.py [--force]
"""

import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIRECTORY = ROOT / "assets" / "img"
MAX_SIDE_PIXELS = 1000


def source_url(source: str) -> str:
    if source.startswith("commons:"):
        name = urllib.parse.quote(source.removeprefix("commons:"))
        return f"https://commons.wikimedia.org/wiki/Special:FilePath/{name}?width={MAX_SIDE_PIXELS}"
    return source


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "curl/8.7.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main() -> None:
    force = "--force" in sys.argv
    song = json.loads((ROOT / "song.json").read_text())
    IMAGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for name, image in song["images"].items():
        target = IMAGE_DIRECTORY / name
        if target.exists() and not force:
            print(f"keep  {target.name}")
            continue
        target.write_bytes(download(source_url(image["source"])))
        subprocess.run(
            ["sips", "-Z", str(MAX_SIDE_PIXELS), "-s", "formatOptions", "80", str(target)],
            check=True,
            capture_output=True,
        )
        print(f"fetch {target.name} ({target.stat().st_size // 1024} kB)")
        time.sleep(1)


if __name__ == "__main__":
    main()
