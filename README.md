# starrypad-game

Simon Says memory game using the **Donner StarryPad** (16 pads). The **web page** shows the sequence (lights up pads on screen); you **repeat the sequence on the physical StarryPad**. Python handles MIDI input from the pad and game logic.

## How it works

1. The screen shows a sequence by lighting up pads on the 4x4 grid
2. A text readout also shows the pad numbers (e.g. "3 → 7 → 12")
3. You repeat the sequence by pressing the matching pads on your StarryPad
4. Correct presses flash green; wrong presses flash red and end the game

## Run

1. Connect the StarryPad via USB.
2. Install dependencies: `pip install -r requirements.txt`
3. Start the server: `python server.py`
4. Open **http://localhost:8765** in a browser and click **Start**.

The Python script uses **mido** to read pad presses from the StarryPad (notes 31–46). The browser connects over WebSocket and displays the grid/sequence. No Web MIDI in the browser.

## Terminal-only (no browser)

To play with logs only (no web UI):

```bash
python main.py
```

## Pad test

To see which MIDI note each pad sends:

```bash
python main.py --test
```
