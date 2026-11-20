# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-whisper==0.4.3"]
# ///
"""Find the animal words in a family voice note and record each take in anki/voices.json.

The speaker says the animals in deck order, from a given animal, one or more takes each, with a
pause between takes. Speech in another language (an introduction) is skipped.

1. Pauses (ffmpeg silencedetect) cut the recording into segments. A very short segment ("con"
   alone) joins the next one when the gap is short.
2. Whisper transcribes each segment. It only labels the segments: the pauses set the times.
3. Each segment goes to the current animal or to the next one, whichever name is closer.

Usage: uv run scripts/import_voice.py assets/voice/<file> --from "rùa biển" [--speaker "grand-père"]
Then check the table, listen in imagier.html#review, and run scripts/prepare_anki_media.py.
"""

import argparse
import json
import re
import subprocess
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import mlx_whisper
from mlx_whisper.audio import SAMPLE_RATE, load_audio

ROOT = Path(__file__).resolve().parent.parent
VOICES = ROOT / "anki" / "voices.json"
MODEL = "mlx-community/whisper-large-v3-turbo"
SILENCE = "silencedetect=noise=-35dB:d=0.4"
SHORT_SEGMENT = 0.9  # seconds: shorter segments are a part of a take
SHORT_GAP = 0.7  # seconds: a short segment joins the next one over a gap this short
MIN_SCORE = 0.45  # below this similarity, a segment is not an animal name


def plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z ]", " ", text)
    return re.sub(r"^(con )+", "", re.sub(r"\s+", " ", text).strip())


def score(heard: str, word: str) -> float:
    return SequenceMatcher(None, plain(heard).replace(" ", ""), plain(word).replace(" ", "")).ratio()


def segments(path: Path, duration: float) -> list[tuple[float, float]]:
    log = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", SILENCE, "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stderr
    times = [float(value) for value in re.findall(r"silence_(?:start|end): ([0-9.]+)", log)]
    if len(times) % 2:
        times.append(duration)
    found, previous = [], 0.0
    for start, end in zip(times[::2], times[1::2]):
        if start > previous:
            found.append((previous, start))
        previous = end
    if duration > previous:
        found.append((previous, duration))
    joined = []
    for start, end in found:
        if joined and joined[-1][1] - joined[-1][0] < SHORT_SEGMENT and start - joined[-1][1] < SHORT_GAP:
            start = joined.pop()[0]
        joined.append((start, end))
    return joined


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("recording", type=Path)
    parser.add_argument("--from", dest="first", required=True, help="Vietnamese word of the first animal")
    parser.add_argument("--speaker", default="grand-père")
    parser.add_argument("--category", default="animal")
    arguments = parser.parse_args()

    recording = arguments.recording.resolve()
    notes = json.loads((ROOT / "anki" / "deck.json").read_text())["notes"]
    animals = [note for note in notes if note["category"] == arguments.category and "excluded" not in note]
    index = next(i for i, note in enumerate(animals) if arguments.first in (note["word"], note["vi"]))

    audio = load_audio(str(recording))
    clips, current = [], None
    for start, end in segments(recording, len(audio) / SAMPLE_RATE):
        piece = audio[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)]
        heard = mlx_whisper.transcribe(piece, path_or_hf_repo=MODEL, language="vi")["text"].strip()
        stay = score(heard, animals[current]["word"]) if current is not None else 0.0
        move = score(heard, animals[index]["word"]) if index < len(animals) else 0.0
        if max(stay, move) < MIN_SCORE:
            print(f"{start:6.2f}-{end:6.2f}  skipped       {heard}")
            continue
        if move > stay:
            current, index = index, index + 1
            note = animals[current]
            word = note["word"] if note["word"].startswith("con ") else "con " + note["word"]
            clips.append({"id": note["id"], "vi": word, "fr": note["fr"], "use": 0, "takes": []})
        clips[-1]["takes"].append({"start": round(start, 2), "end": round(end, 2), "heard": heard})
        print(f"{start:6.2f}-{end:6.2f}  {clips[-1]['vi']:<14} {heard}")

    entry = {
        "file": str(recording.relative_to(ROOT)),
        "speaker": arguments.speaker,
        "clips": clips,
    }
    voices = json.loads(VOICES.read_text()) if VOICES.exists() else {"recordings": []}
    voices["recordings"] = [r for r in voices["recordings"] if r["file"] != entry["file"]] + [entry]
    VOICES.write_text(json.dumps(voices, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {VOICES}: {len(clips)} words, {sum(len(c['takes']) for c in clips)} takes")


if __name__ == "__main__":
    main()
