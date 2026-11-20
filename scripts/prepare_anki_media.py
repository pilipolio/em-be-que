"""Copy the pictures and word sounds of one category from anki-deck/ to assets/anki/, and write anki/<category>.json.

The pictures become 640 px JPEG, with a 240 px thumbnail. The word sound is, in this order: the chosen take
of a family recording in anki/voices.json, the word sound of the deck, or the macOS Vietnamese voice "Linh".
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
PADDING = (0.1, 0.15)  # seconds kept before and after a take: the pauses cut soft starts and ends


def voice_clips() -> dict[int, dict]:
    path = ROOT / "anki" / "voices.json"
    if not path.exists():
        return {}
    recordings = json.loads(path.read_text())["recordings"]
    return {
        clip["id"]: {**clip, "recording": r["file"], "speaker": r["speaker"]} for r in recordings for clip in r["clips"]
    }


def cut(recording: Path, take: dict, target: Path) -> None:
    start = max(0.0, take["start"] - PADDING[0])
    fades = "afade=t=in:d=0.03,areverse,afade=t=in:d=0.05,areverse"
    command = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-to", f"{take['end'] + PADDING[1]:.2f}"]
    command += ["-i", str(recording), "-af", fades, "-ac", "1", "-c:a", "aac", "-b:a", "64k"]
    command += ["-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact", str(target)]
    subprocess.run(command, check=True)


def resize(source: Path, size: int, target: Path) -> None:
    command = ["sips", "-Z", str(size), "-s", "format", "jpeg", "-s", "formatOptions", "75"]
    subprocess.run([*command, str(source), "--out", str(target)], check=True, capture_output=True)


def main() -> None:
    category = sys.argv[1] if len(sys.argv) > 1 else "animal"
    notes = json.loads((ROOT / "anki" / "deck.json").read_text())["notes"]
    media = {name: number for number, name in json.loads((DECK_DIR / "media").read_text()).items()}
    (OUT / "img").mkdir(parents=True, exist_ok=True)
    (OUT / "thumb").mkdir(parents=True, exist_ok=True)
    (OUT / "audio").mkdir(parents=True, exist_ok=True)
    (OUT / "voice").mkdir(parents=True, exist_ok=True)
    voices = voice_clips()

    items = []
    for note in notes:
        if note["category"] != category or "excluded" in note or not note["pictures"]:
            continue
        image = f"img/{note['id']}.jpg"
        thumbnail = f"thumb/{note['id']}.jpg"
        picture = DECK_DIR / media[note["pictures"][0]]
        resize(picture, 640, OUT / image)
        resize(picture, 240, OUT / thumbnail)
        if note["word_sound"]:
            audio = f"audio/{note['id']}.mp3"
            shutil.copy(DECK_DIR / media[note["word_sound"]], OUT / audio)
            audio_source = "deck"
        else:
            audio = f"audio/{note['id']}.m4a"
            # Each run of say gives new bytes for the same speech: keep the file in git.
            if not (OUT / audio).exists():
                subprocess.run(
                    [
                        "say",
                        "-v",
                        "Linh",
                        "--file-format=m4af",
                        "--data-format=aac",
                        "-o",
                        str(OUT / audio),
                        note["word"],
                    ],
                    check=True,
                )
            audio_source = "macOS voice Linh"
        item = {
            "id": note["id"],
            "vi": note["word"],
            "fr": note["fr"],
            "image": image,
            "thumbnail": thumbnail,
            "audio": audio,
            "audio_source": audio_source,
        }
        if note["id"] in voices:
            clip = voices[note["id"]]
            item["audio"] = f"voice/{note['id']}.m4a"
            cut(ROOT / clip["recording"], clip["takes"][clip["use"]], OUT / item["audio"])
            # The label shows the word as the speaker says it, for example with "con" in front.
            item.update(vi=clip["vi"], audio_source=clip["speaker"])
            item["voice"] = {"recording": clip["recording"].removeprefix("assets/"), "use": clip["use"]}
            item["voice"]["takes"] = [{"start": t["start"], "end": t["end"]} for t in clip["takes"]]
        items.append(item)

    path = ROOT / "anki" / f"{category}.json"
    path.write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n")
    size = sum(file.stat().st_size for file in OUT.rglob("*") if file.is_file())
    print(f"wrote {path} ({len(items)} notes), assets/anki is {size // 1024} kB")


if __name__ == "__main__":
    main()
