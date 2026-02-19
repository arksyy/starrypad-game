#!/usr/bin/env python3
"""
StarryPad Simon Says - terminal-only memory game using all 16 pads.
Run: python game.py
Pad test (discover MIDI note numbers): python game.py --test
"""

import argparse
import random
import sys
import time

try:
    import mido
except ImportError:
    print("Missing dependency: run  pip install mido python-rtmidi")
    sys.exit(1)

# 16 pads: MIDI notes 31–46 (StarryPad)
NOTE_MIN, NOTE_MAX = 31, 46
PLAYABLE_NOTES = list(range(NOTE_MIN, NOTE_MAX + 1))


def note_to_pad_index(note: int) -> int | None:
    """Convert MIDI note to pad index 0–15, or None if out of range."""
    if NOTE_MIN <= note <= NOTE_MAX:
        return note - NOTE_MIN
    return None


def pad_index_to_note(index: int) -> int:
    """Convert pad index 0–15 to MIDI note."""
    return NOTE_MIN + index


def find_starrypad_ports(port_name_filter: str | None = None):
    """Return (input_name, output_name) for StarryPad, or (None, None)."""
    in_names = mido.get_input_names()
    out_names = mido.get_output_names()
    key = (port_name_filter or "starry").lower()
    in_name = next((n for n in in_names if key in n.lower()), None)
    out_name = next((n for n in out_names if key in n.lower()), None)
    return in_name, out_name


def light_pad(outport: mido.ports.BaseOutput | None, note: int, duration_s: float = 0.45):
    """Send note_on, wait, note_off. Also try note_on(velocity=0) for devices that use it as light off."""
    if outport:
        outport.send(mido.Message("note_on", note=note, velocity=127))
    time.sleep(duration_s)
    if outport:
        outport.send(mido.Message("note_off", note=note))
        outport.send(mido.Message("note_on", note=note, velocity=0))
    time.sleep(0.25)


def run_pad_test(inport: mido.ports.BaseInput):
    """Loop: print every pad press (note, velocity). Ctrl+C to exit."""
    print("Pad test mode. Press pads on the StarryPad (Ctrl+C to exit).")
    print("Note numbers for 16 pads are often 36–51.\n")
    try:
        for msg in inport:
            if msg.type == "note_on" and msg.velocity > 0:
                idx = note_to_pad_index(msg.note)
                extra = f" -> pad index {idx}" if idx is not None else ""
                print(f"  note={msg.note} velocity={msg.velocity}{extra}")
    except KeyboardInterrupt:
        print("\nDone.")


def play_sequence(
    outport: mido.ports.BaseOutput | None,
    sequence: list[int],
    *,
    on_step=None,
):
    """Play the sequence: light each pad in order; on_step(pad_1based, note) called per step."""
    for note in sequence:
        idx = note_to_pad_index(note)
        if on_step and idx is not None:
            on_step(idx + 1, note)
        light_pad(outport, note)
    if on_step:
        on_step(None, None)


def run_game(inport: mido.ports.BaseInput, outport: mido.ports.BaseOutput | None):
    """Main game loop: Simon Says with 16 pads, log-only terminal output."""
    sequence: list[int] = []
    level = 1
    phase = "idle"  # idle | playing | input | gameover
    expected_index = 0
    last_note: int | None = None
    last_note_time: float = 0.0
    DEBOUNCE_S = 0.35

    def start_round():
        nonlocal sequence, level, phase, expected_index
        sequence.append(random.choice(PLAYABLE_NOTES))
        level = len(sequence)
        phase = "playing"
        expected_index = 0
        print(f"\n--- Level {level} ---")
        print("Watch the sequence…")
        def on_step(pad_1based, note):
            if pad_1based is not None and note is not None:
                print(f"  Pad {pad_1based}")
        play_sequence(outport, sequence, on_step=on_step)
        phase = "input"
        expected_index = 0
        print("Your turn – repeat the sequence.")

    def game_over(received_note: int | None = None):
        nonlocal phase, sequence, level
        score = level - 1  # level at which they failed
        phase = "gameover"
        print("\nWrong! Game over.")
        if expected_index < len(sequence):
            print(f"Expected pad {expected_index + 1}.")
        print(f"Score: {score}")
        print("Press any pad to play again, or Ctrl+C to quit.")

    # Start first round
    start_round()

    try:
        while True:
            for msg in inport.iter_pending():
                if msg.type != "note_on" or msg.velocity == 0:
                    continue
                note = msg.note
                idx = note_to_pad_index(note)
                if idx is None:
                    continue

                if phase == "gameover":
                    # Restart
                    sequence = []
                    level = 1
                    start_round()
                    continue

                if phase != "input":
                    continue

                # Debounce: ignore duplicate note_on from same pad within DEBOUNCE_S
                now = time.time()
                if last_note == note and (now - last_note_time) < DEBOUNCE_S:
                    continue
                last_note = note
                last_note_time = now

                # User input during input phase
                if outport:
                    outport.send(mido.Message("note_on", note=note, velocity=127))
                time.sleep(0.15)
                if outport:
                    outport.send(mido.Message("note_off", note=note))
                    outport.send(mido.Message("note_on", note=note, velocity=0))

                if note != sequence[expected_index]:
                    game_over(received_note=note)
                    continue

                expected_index += 1
                print(f"  Pad {idx + 1}")
                if expected_index >= len(sequence):
                    print("\nCorrect! Next level.")
                    start_round()
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nBye.")


def main():
    parser = argparse.ArgumentParser(description="StarryPad Simon Says (16 pads, terminal)")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Pad test mode: print MIDI note for each pad press, then exit with Ctrl+C",
    )
    parser.add_argument(
        "--port",
        type=str,
        default=None,
        metavar="NAME",
        help="MIDI port name substring (default: look for 'starry')",
    )
    args = parser.parse_args()

    key = (args.port or "starry").lower()
    in_name, out_name = find_starrypad_ports(key)

    if not in_name:
        print("No StarryPad input found.")
        print("Available inputs:", mido.get_input_names())
        print("Connect the StarryPad and try again, or use --port NAME to match by name.")
        sys.exit(1)

    inport = mido.open_input(in_name)
    outport = mido.open_output(out_name) if out_name else None
    if not out_name:
        print("No StarryPad output found – terminal shows the sequence.")
        print("Available outputs:", mido.get_output_names())

    print("StarryPad Simon Says (16 pads)")
    print("Pads mapped to MIDI notes 31–46.")
    if args.test:
        run_pad_test(inport)
    else:
        run_game(inport, outport)

    inport.close()
    if outport:
        outport.close()


if __name__ == "__main__":
    main()
