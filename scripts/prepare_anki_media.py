"""Copy the pictures and word sounds of one category from anki-deck/ to assets/anki/, and write anki/<category>.json.

The pictures become 640 px JPEG. A note without a word sound in the deck gets one from the macOS
Vietnamese voice "Linh".
Usage: python3 scripts/prepare_anki_media.py [category]   (default: animal)
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECK_DIR = ROOT / "anki-deck"
OUT = ROOT / "assets" / "anki"


def main() -> None:
    category = sys.argv[1] if len(sys.argv) > 1 else "animal"
    notes = json.loads((ROOT / "anki" / "deck.json").read_text())["notes"]
    media = {name: number for number, name in json.loads((DECK_DIR / "media").read_text()).items()}
    (OUT / "img").mkdir(parents=True, exist_ok=True)
    (OUT / "audio").mkdir(parents=True, exist_ok=True)

    items = []
    for note in notes:
        if note["category"] != category or "excluded" in note or not note["pictures"]:
            continue
        image = f"img/{note['id']}.jpg"
        subprocess.run(
            [
                "sips",
                "-Z",
                "640",
                "-s",
                "format",
                "jpeg",
                "-s",
                "formatOptions",
                "75",
                str(DECK_DIR / media[note["pictures"][0]]),
                "--out",
                str(OUT / image),
            ],
            check=True,
            capture_output=True,
        )
        if note["word_sound"]:
            audio = f"audio/{note['id']}.mp3"
            shutil.copy(DECK_DIR / media[note["word_sound"]], OUT / audio)
            audio_source = "deck"
        else:
            audio = f"audio/{note['id']}.m4a"
            subprocess.run(
                ["say", "-v", "Linh", "--file-format=m4af", "--data-format=aac", "-o", str(OUT / audio), note["word"]],
                check=True,
            )
            audio_source = "macOS voice Linh"
        items.append(
            {
                "id": note["id"],
                "vi": note["word"],
                "fr": note["fr"],
                "image": image,
                "audio": audio,
                "audio_source": audio_source,
            }
        )

    path = ROOT / "anki" / f"{category}.json"
    path.write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n")
    size = sum(file.stat().st_size for file in OUT.rglob("*") if file.is_file())
    print(f"wrote {path} ({len(items)} notes), assets/anki is {size // 1024} kB")


if __name__ == "__main__":
    main()
