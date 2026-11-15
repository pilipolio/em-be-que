# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = ["torch==2.5.1", "torchaudio==2.5.1", "numpy<2.3"]
# ///
"""Force-align the known lyrics to the recording and write word times into song.json.

For each sentence, the script cuts the clip [start - 0.3 s, end + 0.3 s] and aligns the
sentence's syllables with the MMS forced-alignment model (torchaudio.pipelines.MMS_FA, a CTC
model). It writes `start` and `end` (absolute seconds, 2 decimals) on each entry of `words`.
A word with two syllables spans from its first syllable start to its last syllable end.

MMS_FA knows only lower-case Latin letters, so each syllable is aligned in a form without
diacritics ("đ" becomes "d"). The Vietnamese text in song.json does not change.

A CTC model marks only the first frames of a held sung vowel, so the aligned end is too early.
The script therefore extends each word end up to the next word start (the sentence end for the
last word), less any trailing silence. The table shows the raw CTC end too.

Checks: times are monotonic, each word sits inside its sentence span, no word is shorter than
0.1 s. The table also gives the nearest energy onset for each word start, and lists energy
onsets that no word start explains. A voiced consonant (l, n, m, đ) gives no clear energy
onset, so "far from onset" is a hint to listen, not a proof of error.

Usage (from the project folder; the first run downloads torch and the 1.2 GB model):
    uv run scripts/align_words.py            # align, print the tables, write song.json
    uv run scripts/align_words.py --dry-run  # align and print, do not write
    uv run scripts/align_words.py --check    # only check the times already in song.json
"""

import argparse
import json
import subprocess
import tempfile
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict

import numpy
import torch
import torchaudio

ROOT = Path(__file__).resolve().parent.parent
SONG_PATH = ROOT / "song.json"
SAMPLE_RATE = 16_000
PADDING_SECONDS = 0.3
MINIMUM_WORD_SECONDS = 0.1
ENERGY_FRAME_SECONDS = 0.01
ONSET_TOLERANCE_SECONDS = 0.15
SILENCE_DECIBELS = -45.0


class Word(TypedDict):
    vi: str
    fr: str
    image: NotRequired[str]
    start: NotRequired[float]
    end: NotRequired[float]


class Sentence(TypedDict):
    start: float
    end: float
    vi: str
    fr: str
    image: str
    words: list[Word]


@dataclass
class SyllableSpan:
    text: str
    start: float
    end: float
    score: float


@dataclass
class WordReport:
    """Alignment details that the table shows but song.json does not keep."""

    connectionist_end: float
    score: float
    syllable_starts: list[float]


def romanise(syllable: str) -> str:
    """Return the syllable in lower case, without diacritics, with letters a-z only."""
    text = syllable.lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    return "".join(character for character in text if "a" <= character <= "z")


def decode_audio(audio_path: Path, start: float, end: float) -> numpy.ndarray:
    """Decode [start, end] of the file to 16 kHz mono floats with ffmpeg and the wave module."""
    with tempfile.TemporaryDirectory() as directory:
        wave_path = Path(directory) / "clip.wav"
        command = [
            "ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-i", str(audio_path), "-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16",
            str(wave_path),
        ]
        subprocess.run(command, check=True)
        with wave.open(str(wave_path), "rb") as reader:
            frames = reader.readframes(reader.getnframes())
    return numpy.frombuffer(frames, dtype=numpy.int16).astype(numpy.float32) / 32768.0


def energy_decibels(samples: numpy.ndarray) -> numpy.ndarray:
    """Return the RMS level in dB for each 10 ms frame, smoothed over 30 ms."""
    frame = int(ENERGY_FRAME_SECONDS * SAMPLE_RATE)
    count = len(samples) // frame
    energy = numpy.sqrt(numpy.mean(samples[: count * frame].reshape(count, frame) ** 2, axis=1))
    return numpy.convolve(20 * numpy.log10(energy + 1e-5), numpy.ones(3) / 3, mode="same")


def energy_onsets(decibels: numpy.ndarray, offset: float) -> list[float]:
    """Return absolute times where the level rises fast (a syllable attack)."""
    # Rise over 50 ms: a consonant-to-vowel attack or a start after a breath.
    rise = numpy.zeros_like(decibels)
    rise[5:] = decibels[5:] - decibels[:-5]
    floor = numpy.percentile(decibels, 20)
    onsets: list[float] = []
    for index in range(1, len(rise) - 1):
        is_peak = rise[index] >= rise[index - 1] and rise[index] > rise[index + 1]
        if is_peak and rise[index] > 6.0 and decibels[index] > floor + 6.0:
            time = offset + (index - 2) * ENERGY_FRAME_SECONDS
            if not onsets or time - onsets[-1] > 0.08:
                onsets.append(time)
    return onsets


def sound_end(decibels: numpy.ndarray, offset: float, earliest: float, latest: float) -> float:
    """Return the end of the last sound in [earliest, latest], never before earliest."""
    first = max(0, int((earliest - offset) / ENERGY_FRAME_SECONDS))
    last = min(len(decibels), int((latest - offset) / ENERGY_FRAME_SECONDS))
    loud = numpy.nonzero(decibels[first:last] > SILENCE_DECIBELS)[0]
    if len(loud) == 0:
        return earliest
    return min(latest, max(earliest, offset + (first + loud[-1] + 1) * ENERGY_FRAME_SECONDS))


class Aligner:
    def __init__(self) -> None:
        bundle = torchaudio.pipelines.MMS_FA
        self.model = bundle.get_model(with_star=False)
        self.model.eval()
        self.tokenizer = bundle.get_tokenizer()
        self.aligner = bundle.get_aligner()

    def align(self, samples: numpy.ndarray, syllables: list[str]) -> list[SyllableSpan]:
        """Align the romanised syllables to the clip. Times are relative to the clip start."""
        waveform = torch.from_numpy(samples.copy()).unsqueeze(0)
        with torch.inference_mode():
            emission, _ = self.model(waveform)
        romanised = [romanise(syllable) for syllable in syllables]
        token_spans = self.aligner(emission[0], self.tokenizer(romanised))
        seconds_per_frame = waveform.size(1) / emission.size(1) / SAMPLE_RATE
        spans = []
        for syllable, character_spans in zip(syllables, token_spans):
            length = sum(span.end - span.start for span in character_spans)
            score = sum(span.score * (span.end - span.start) for span in character_spans) / length
            spans.append(
                SyllableSpan(
                    text=syllable,
                    start=character_spans[0].start * seconds_per_frame,
                    end=character_spans[-1].end * seconds_per_frame,
                    score=score,
                )
            )
        return spans


def align_sentence(sentence: Sentence, audio_path: Path, aligner: Aligner) -> list[WordReport]:
    clip_start = max(0.0, sentence["start"] - PADDING_SECONDS)
    samples = decode_audio(audio_path, clip_start, sentence["end"] + PADDING_SECONDS)
    decibels = energy_decibels(samples)
    syllables = [syllable for word in sentence["words"] for syllable in word["vi"].split()]
    spans = aligner.align(samples, syllables)

    reports = []
    position = 0
    for word in sentence["words"]:
        count = len(word["vi"].split())
        word_spans = spans[position : position + count]
        position += count
        word["start"] = round(max(sentence["start"], clip_start + word_spans[0].start), 2)
        reports.append(
            WordReport(
                connectionist_end=clip_start + word_spans[-1].end,
                score=min(span.score for span in word_spans),
                syllable_starts=[clip_start + span.start for span in word_spans],
            )
        )

    words = sentence["words"]
    for index, (word, report) in enumerate(zip(words, reports)):
        latest = words[index + 1]["start"] if index + 1 < len(words) else sentence["end"]
        earliest = min(latest, max(report.connectionist_end, word["start"] + MINIMUM_WORD_SECONDS))
        word["end"] = round(sound_end(decibels, clip_start, earliest, latest), 2)
    return reports


def check_sentence(
    number: int, sentence: Sentence, audio_path: Path, previous_end: float,
    reports: list[WordReport] | None,
) -> int:
    """Print the table for one sentence and return the number of hard problems."""
    clip_start = sentence["start"] - 0.5
    decibels = energy_decibels(decode_audio(audio_path, clip_start, sentence["end"] + 0.2))
    onsets = [
        onset for onset in energy_onsets(decibels, clip_start)
        if sentence["start"] - 0.1 <= onset <= sentence["end"]
    ]
    print(f"\n{number}. {sentence['vi']}  [{sentence['start']:.2f} - {sentence['end']:.2f}]")
    print(f"   {'word':<12} {'start':>6} {'end':>6} {'length':>6} {'ctc end':>7} {'score':>5} "
          f"{'onset':>6} {'delta':>6}  notes")
    problems = 0
    for index, word in enumerate(sentence["words"]):
        start, end = word["start"], word["end"]
        notes = []
        if start < previous_end - 1e-6 or end < start:
            notes.append("NOT MONOTONIC")
        if start < sentence["start"] - 1e-6 or end > sentence["end"] + 1e-6:
            notes.append("OUTSIDE SENTENCE")
        if end - start < MINIMUM_WORD_SECONDS - 1e-6:
            notes.append("SHORT")
        problems += len(notes)
        nearest = min(onsets, key=lambda onset: abs(onset - start), default=None)
        delta = start - nearest if nearest is not None else float("nan")
        if nearest is None or abs(delta) > ONSET_TOLERANCE_SECONDS:
            notes.append("far from onset")
        report = reports[index] if reports else None
        if report and report.score < 0.3:
            notes.append("low score")
        ctc_end = f"{report.connectionist_end:7.2f}" if report else "      -"
        score = f"{report.score:5.2f}" if report else "    -"
        onset = f"{nearest:6.2f}" if nearest is not None else "     -"
        print(f"   {word['vi']:<12} {start:6.2f} {end:6.2f} {end - start:6.2f} {ctc_end} {score} "
              f"{onset} {delta:+6.2f}  {', '.join(notes)}")
        previous_end = end
    starts = [word["start"] for word in sentence["words"]]
    starts += [start for report in reports or [] for start in report.syllable_starts]
    unexplained = [
        onset for onset in onsets
        if min(abs(onset - start) for start in starts) > ONSET_TOLERANCE_SECONDS
    ]
    print(f"   energy onsets no syllable start explains: "
          f"{' '.join(f'{onset:.2f}' for onset in unexplained) or '-'}")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="do not write song.json")
    parser.add_argument("--check", action="store_true", help="only check the times in song.json")
    arguments = parser.parse_args()

    song = json.loads(SONG_PATH.read_text())
    audio_path = ROOT / song["audio"]
    sentences: list[Sentence] = song["sentences"]
    aligner = None if arguments.check else Aligner()
    problems = 0
    previous_end = 0.0
    for number, sentence in enumerate(sentences, start=1):
        reports = align_sentence(sentence, audio_path, aligner) if aligner else None
        problems += check_sentence(number, sentence, audio_path, previous_end, reports)
        previous_end = sentence["words"][-1]["end"]
    print(f"\n{problems} hard problem(s)")
    if aligner and not arguments.dry_run:
        SONG_PATH.write_text(json.dumps(song, ensure_ascii=False, indent=2))
        print(f"wrote {SONG_PATH}")


if __name__ == "__main__":
    main()
