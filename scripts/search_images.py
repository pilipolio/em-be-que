"""Search Openverse for freely licensed photos and build a contact sheet to choose from.

Each argument is "<key>=<query>". Output goes to candidates/:
  <key>-<n>.jpg     thumbnails, n = 1..4
  results.json      url, creator and licence of each candidate
  sheet.png         one row per key, in argument order
Usage: python3 scripts/search_images.py "trau=water buffalo" "lua=rice plant"
"""

import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = ROOT / "candidates"
PER_QUERY = 4
HEADERS = {"User-Agent": "curl/8.7.1"}


def get(url: str) -> bytes:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
                return r.read()
        except Exception as error:  # noqa: BLE001
            print(f"  retry {attempt + 1}: {error}")
            time.sleep(5)
    return b""


def main() -> None:
    CANDIDATES.mkdir(exist_ok=True)
    results_path = CANDIDATES / "results.json"
    results = json.loads(results_path.read_text()) if results_path.exists() else {}
    tiles: list[str] = []
    for argument in sys.argv[1:]:
        key, query = argument.split("=", 1)
        parameters = urllib.parse.urlencode(
            {"q": query, "page_size": PER_QUERY, "license": "cc0,pdm,by,by-sa", "mature": "false"}
        )
        body = get(f"https://api.openverse.org/v1/images/?{parameters}")
        found = json.loads(body).get("results", []) if body else []
        print(f"{key}: {len(found)} results for '{query}'")
        results[key] = []
        for number in range(1, PER_QUERY + 1):
            tile = CANDIDATES / f"{key}-{number}.jpg"
            tile.unlink(missing_ok=True)
            if number <= len(found):
                item = found[number - 1]
                data = get(item["thumbnail"])
                if data:
                    tile.write_bytes(data)
                results[key].append(
                    {
                        "url": item["url"],
                        "creator": item.get("creator"),
                        "license": f"{item['license']} {item.get('license_version') or ''}".strip(),
                        "title": item.get("title"),
                        "page": item.get("foreign_landing_url"),
                    }
                )
            normalised = CANDIDATES / f".tile-{len(tiles):03d}.png"
            source = ["-i", str(tile)] if tile.exists() else ["-f", "lavfi", "-i", "color=gray:s=320x240"]
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", *source, "-frames:v", "1", "-vf",
                 "scale=320:240:force_original_aspect_ratio=decrease,pad=320:240:(ow-iw)/2:(oh-ih)/2:white",
                 str(normalised)],
                check=False,
            )
            tiles.append(str(normalised))
        time.sleep(2)
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    rows = len(tiles) // PER_QUERY
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(CANDIDATES / ".tile-%03d.png"),
         "-vf", f"tile={PER_QUERY}x{rows}", "-frames:v", "1", str(CANDIDATES / "sheet.png")],
        check=True,
    )
    for tile in tiles:
        Path(tile).unlink(missing_ok=True)
    print(f"wrote {CANDIDATES / 'sheet.png'}")


if __name__ == "__main__":
    main()
