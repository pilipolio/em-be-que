"""Write the notes of the Anki deck "Bé Học Tiếng Anh" to anki/deck.json, with one category per note.

Source: https://ankiweb.net/shared/info/1119829676, unzipped into anki-deck/ (not in git).
The deck has no tags. Claude Haiku (through the `claude` CLI) gives each note a category from its
Vietnamese, French and English words. Categories already in anki/deck.json are kept, so only new
notes go to Haiku.
Usage: ANKI_DB=anki-deck/collection.anki21 uv run --with anki-reader python scripts/extract_anki.py
"""

import html
import json
import re
import subprocess
from pathlib import Path

from anki_reader import AnkiDB

ROOT = Path(__file__).resolve().parent.parent
DECK = ROOT / "anki" / "deck.json"
FIELDS = ["vi", "en", "sentence_vi", "fr", "audio", "picture"]
SOURCE = "https://ankiweb.net/shared/info/1119829676"
CATEGORIES = [
    "animal",
    "fruit",
    "légume",
    "fleur",
    "plante",
    "véhicule",
    "nourriture",
    "boisson",
    "corps",
    "vêtement",
    "maison",
    "objet",
    "couleur",
    "forme",
    "métier",
    "sport",
    "action",
    "émotion",
    "nature",
    "lieu",
    "autre",
]
PROMPT = (
    "Each input line is: note id, Vietnamese word, French translation, English translation, "
    "separated by tabs. Give each note exactly one category in French, from this list: "
    + ", ".join(CATEGORIES)
    + ". 'animal' means any living animal (mammal, bird, fish, insect, sea animal), not food made "
    "from it. Reply with JSON only, no code fence: an object that maps each note id (as a string) "
    "to its category. Include all ids."
)
# Deck errors found by hand: the note is kept in deck.json but not used by the pages.
EXCLUDED = {1739961581886: "the picture is the rooster of gà trống, not a chick"}


def text(field: str) -> str:
    field = re.sub(r"<br\s*/?>|</div>", " ", field)
    field = html.unescape(re.sub(r"<[^>]+>", "", field))
    return re.sub(r"\s+", " ", field).strip()


def terms(vi: str) -> list[str]:
    return [term.strip() for term in re.split(r"[,;≠]", vi) if term.strip()]


def word_sound(vi: str, sounds: list[str]) -> str | None:
    """The deck names a word clip after the word, and a sentence clip after the sentence."""
    for sound in sounds:
        if sound.removesuffix(".mp3").split(",")[0].strip() in terms(vi):
            return sound
    return None


def classify(notes: list[dict]) -> dict[str, str]:
    lines = "\n".join(f"{note['id']}\t{note['vi']}\t{note['fr']}\t{note['en']}" for note in notes)
    reply = subprocess.run(
        ["claude", "-p", "--model", "haiku", "--output-format", "text", PROMPT],
        input=lines,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    categories = json.loads(reply[reply.index("{") : reply.rindex("}") + 1])
    return {key: value if value in CATEGORIES else "autre" for key, value in categories.items()}


def main() -> None:
    known = {}
    if DECK.exists():
        known = {note["id"]: note for note in json.loads(DECK.read_text())["notes"]}
    notes = []
    for note_id, fields in AnkiDB().query_db("select id, flds from notes order by id"):
        values = dict(zip(FIELDS, fields.split("\x1f")))
        sounds = re.findall(r"\[sound:([^\]]+)\]", values["audio"])
        pictures = re.findall(r'<img[^>]+src="([^"]+)"', values["picture"])
        vi = text(values["vi"])
        note = {
            "id": note_id,
            "vi": vi,
            "word": terms(vi)[0],
            "en": text(values["en"]),
            "fr": text(values["fr"]),
            "sentence_vi": text(values["sentence_vi"]),
            "sounds": sounds,
            "word_sound": word_sound(vi, sounds),
            "pictures": [html.unescape(picture) for picture in pictures],
        }
        if "category" in known.get(note_id, {}):
            note["category"] = known[note_id]["category"]
        if note_id in EXCLUDED:
            note["excluded"] = EXCLUDED[note_id]
        notes.append(note)

    new = [note for note in notes if "category" not in note]
    if new:
        categories = classify(new)
        for note in new:
            note["category"] = categories.get(str(note["id"]), "autre")
        print(f"classified {len(new)} notes with Claude Haiku")

    DECK.parent.mkdir(exist_ok=True)
    deck = {"source": SOURCE, "category_source": "claude haiku, see scripts/extract_anki.py", "notes": notes}
    DECK.write_text(json.dumps(deck, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {DECK} ({len(notes)} notes)")


if __name__ == "__main__":
    main()
