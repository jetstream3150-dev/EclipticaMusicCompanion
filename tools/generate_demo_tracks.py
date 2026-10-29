"""Create audio fixtures for browser and GUI tests; these are not packaged.

No third-party recordings are downloaded or included. The two synth voices,
drums and note patterns below are generated locally using the standard library.
"""
from array import array
from math import exp, pi, sin, tanh
from pathlib import Path
from random import Random
import sys
import wave


RATE = 22050
TAU = 2.0 * pi
CHORDS = ((45, 48, 52), (41, 45, 48), (48, 52, 55), (43, 47, 50))


def add_note(buf, start, duration, midi, level, voice):
    first = max(0, int(start * RATE))
    count = min(len(buf) - first, int(duration * RATE))
    if count <= 0:
        return
    frequency = 440.0 * 2.0 ** ((midi - 69) / 12.0)
    step = TAU * frequency / RATE
    attack = max(1, int(RATE * (.035 if voice == 'pad' else .006)))
    release = max(1, int(RATE * (.16 if voice == 'pad' else .06)))
    for i in range(count):
        envelope = min(1.0, i / attack, (count - i) / release)
        phase = step * i
        if voice == 'bass':
            sample = .8 * sin(phase) + .2 * sin(2 * phase)
        elif voice == 'pad':
            sample = .60 * sin(phase) + .24 * sin(phase * 1.002) + .16 * sin(2 * phase)
        else:
            sample = .64 * sin(phase) + .24 * sin(2 * phase) + .12 * sin(3 * phase)
        buf[first + i] += level * envelope * sample


def add_drum(buf, start, kind, level, rng):
    first = int(start * RATE)
    duration = {'kick': .23, 'snare': .17, 'hat': .055}[kind]
    count = min(int(duration * RATE), len(buf) - first)
    if count <= 0:
        return
    previous_noise = 0.0
    for i in range(count):
        t = i / RATE
        if kind == 'kick':
            # The phase integral gives the kick a downward frequency sweep.
            phase = TAU * (43 * t + 75 * .03 * (1 - exp(-t / .03)))
            sample = sin(phase) * exp(-t * 19)
        elif kind == 'snare':
            sample = (.72 * (rng.random() * 2 - 1) + .28 * sin(TAU * 180 * t)) * exp(-t * 23)
        else:
            noise = rng.random() * 2 - 1
            sample = (noise - previous_noise * .75) * exp(-t * 70)
            previous_noise = noise
        buf[first + i] += level * sample


def render(path, style):
    bpm = {'battle': 128, 'boss': 138, 'calm': 108}[style]
    beat = 60.0 / bpm
    bars = 8
    buf = array('f', [0.0]) * int(bars * 4 * beat * RATE)
    rng = Random({'battle': 1201, 'boss': 1202, 'calm': 1203}[style])
    for bar in range(bars):
        base = bar * 4 * beat
        chord = CHORDS[bar % len(CHORDS)]
        for note in chord:
            add_note(buf, base, 3.75 * beat, note + 12, .035 if style != 'boss' else .042, 'pad')
        for n in range(4):
            add_drum(buf, base + n * beat, 'kick', .20 if style == 'calm' else .30, rng)
            if n in (1, 3):
                add_drum(buf, base + n * beat, 'snare', .08 if style == 'calm' else .14, rng)
            add_note(buf, base + n * beat, .72 * beat, chord[0] - 12, .115, 'bass')
            for eighth in range(2):
                add_drum(buf, base + (n + eighth / 2) * beat, 'hat', .025 if style == 'calm' else .045, rng)
        pattern = (0, 1, 2, 1, 0, 2, 1, 2) if style == 'calm' else (0, 2, 1, 2, 0, 1, 2, 1)
        for eighth, chord_index in enumerate(pattern):
            shift = 24 if (style != 'calm' and (bar // 2) % 2) else 12
            if style == 'boss' and eighth in (3, 7):
                shift += 12
            add_note(buf, base + eighth * beat / 2, .34 * beat, chord[chord_index] + shift,
                     .055 if style == 'calm' else .078, 'lead')
    frames = array('h')
    for i, sample in enumerate(buf):
        edge = min(1.0, i / 220.0, (len(buf) - i - 1) / 220.0)
        frames.append(int(32767 * max(0.0, edge) * tanh(sample * 1.25)))
    if sys.byteorder != 'little':
        frames.byteswap()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes(frames.tobytes())
    print(f'Generated original {style} demo: {path.name}, {len(buf) / RATE:.1f} seconds')


def main():
    destination = Path(__file__).resolve().parent.parent / 'demo_audio'
    for style in ('battle', 'boss', 'calm'):
        render(destination / f'{style}.wav', style)


if __name__ == '__main__':
    main()
