"""Build dist/index.html from src/page.html, song.json and the assets.

The audio goes into the page as a data URI. The images stay as files in dist/img.
The Claude artifact host wraps the page in a document itself. Any other host needs --standalone.
Usage: python3 scripts/build.py [--standalone]
"""

import base64
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
STANDALONE_HEAD = (
    '<!doctype html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    "<style>body { margin: 0; } img { max-width: 100%; }</style>\n</head>\n<body>\n"
)


def main() -> None:
    song = json.loads((ROOT / "song.json").read_text())
    audio = base64.b64encode((ROOT / song["audio"]).read_bytes()).decode()
    credits = {
        name: {"credit": image["credit"], "licence_url": image.get("licence_url")}
        for name, image in song["images"].items()
    }
    page = (ROOT / "src" / "page.html").read_text()
    page = page.replace("__SENTENCES__", json.dumps(song["sentences"], ensure_ascii=False))
    page = page.replace("__CREDITS__", json.dumps(credits, ensure_ascii=False))
    page = page.replace("__AUDIO__", f"data:audio/mpeg;base64,{audio}")

    (DIST / "img").mkdir(parents=True, exist_ok=True)
    for name in credits:
        shutil.copy(ROOT / "assets" / "img" / name, DIST / "img" / name)
    if "--standalone" in sys.argv:
        page = STANDALONE_HEAD + page + "</body>\n</html>\n"
    (DIST / "index.html").write_text(page)
    print(f"wrote {DIST / 'index.html'} ({len(page) // 1024} kB)")


if __name__ == "__main__":
    main()
