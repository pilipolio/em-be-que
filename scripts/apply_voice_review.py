"""Apply the corrections copied from imagier.html#review to anki/voices.json.

Usage: pbpaste | python3 scripts/apply_voice_review.py && python3 scripts/prepare_anki_media.py
The input maps a note id to {"use": take index, "takes": [{"start": s, "end": s}, ...]}.
"""

import json
import sys
from pathlib import Path

VOICES = Path(__file__).resolve().parent.parent / "anki" / "voices.json"


def main() -> None:
    edits = json.loads(sys.stdin.read())
    voices = json.loads(VOICES.read_text())
    changed = 0
    for recording in voices["recordings"]:
        for clip in recording["clips"]:
            edit = edits.get(str(clip["id"]))
            if not edit:
                continue
            clip["use"] = edit["use"]
            for take, times in zip(clip["takes"], edit["takes"]):
                take.update(start=float(times["start"]), end=float(times["end"]))
            changed += 1
            print(f"{clip['vi']}: take {edit['use'] + 1}, {clip['takes'][edit['use']]}")
    VOICES.write_text(json.dumps(voices, ensure_ascii=False, indent=1) + "\n")
    print(f"updated {changed} of {len(edits)} words in {VOICES}")


if __name__ == "__main__":
    main()
