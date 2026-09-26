# VIBRANIUM CHESS

A modern Python + HTML chess experience powered by the original Vibranium engine.

## Modes
- **VS AI** — offline play against **JARVIS** with Easy / Medium / Hard difficulty.
- **LOCAL** — two players on one device and one screen. Enter Player 1 and Player 2 names; no room, link, or second browser is needed.
- **ONLINE** — create a room and share the HTTP invite link with another device/browser.

## Online behavior
- The active player sees **YOUR TURN**; the opponent sees **Player Name TURN**.
- The top status also shows whose turn it is.
- If a player leaves, the remaining player sees **PLAYER LEFT** and can start a **New Game**.
- Closing an online tab also sends a best-effort leave signal.

## Board
- Strict 8×8 square board.
- Black and white squares only.
- High-contrast black/white pieces.

## Run
```powershell
python app.py
```
Open `http://127.0.0.1:5000` on the PC.

For a phone on the same Wi-Fi, use the `PHONE / SAME WI-FI` address printed by the server.

No third-party Python packages are required.
