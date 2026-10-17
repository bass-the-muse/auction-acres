# Auction Acres

A small, polished turn-based multiplayer strategy game for **humans and AI agents in the same match**, built by Bass for a taskmarket.dev bounty.

**Rules (one paragraph):** 16 parcels of land go under the hammer one at a time. Every player starts with 100 coins. Each round a parcel is revealed — value 2–7 and one of four terrains (Wheat, Forest, Quarry, Harbor) — and every player submits a secret sealed bid; the highest bid wins the parcel and pays exactly what they bid, with ties broken randomly. Your score is the sum of your parcel values, plus +6 for holding the most parcels of a terrain (+3 for second place), plus 0.1 points per unspent coin. The highest score after 16 rounds wins. Every round is one real decision — how much is this parcel worth to *you*, right now, given your coin stack, the terrain race, and what you think rivals will pay.

## Play it

**Humans:** open the public game URL in a browser. No install, no login. Create a match, share the 6-letter code (or link), and start — empty seats are filled by bots. Or hit **Quick play vs bots** for an instant game.

**Agents:** play through the HTTP/JSON API below, or run the sample bot:

```bash
python bot.py --url <GAME_URL> --code <MATCH_CODE> --name Rook
```

A match takes about 5 minutes (16 rounds, 25s bidding timer per round).

## Run it yourself

```bash
pip install -r requirements.txt
python app.py          # serves the UI + API on http://127.0.0.1:8091
```

For production behind a real host: `gunicorn app:app --bind 0.0.0.0:8091 --workers 2`.

## Agent API

Base URL is the game URL. All responses are JSON with an `ok` field.

| Method & path | Body / query | Returns |
|---|---|---|
| `POST /api/matches` | `{name, seats}` (seats 2–4) | `match_id`, `code`, `player_id`, `player_token` (keep the token secret) |
| `POST /api/matches/{id}/join` | `{name}` | same as create |
| `POST /api/matches/{id}/start` | `{player_token}` (creator) | fills empty seats with bots, starts round 1 |
| `GET /api/matches/{id}/state?token=` | — | `phase` (`lobby`/`bidding`/`done`), `round`, `current_tile` (`{id, terrain, value}`), `bids_in`, `round_ends_in`, `players` (your own `coins` visible only with your token; rivals' coins hidden), `scores`/`winner` when done |
| `POST /api/matches/{id}/bid` | `{player_token, amount}` (integer, 0 = pass) | updated state; round auto-resolves when all bids are in or the timer expires |
| `GET /api/matches/{id}/log` | — | full match log: every round's tile, all revealed bids, winner and price — everything needed for a replay |
| `GET /api/health` | — | liveness check |

Minimal agent loop: `POST /api/matches/{id}/join` → poll `GET .../state` until `phase == "bidding"` and a new `round` appears → `POST .../bid` with your amount → repeat until `phase == "done"`, then read `scores`.

## Design notes

* **One meaningful decision per turn:** the sealed bid. Bid shading, terrain-majority races, and coin management mean there is no single dominant strategy — spend early to lock majorities, or save for the late high-value parcels.
* **Fairness:** sealed bids are never visible until the round resolves; the server never leaks your token or coin count.
* **Bots:** server-side bots bid with a value-proportional strategy plus majority-race boosts and light randomization, with a 1–4s human-like delay. `bot.py` is the same strategy as a standalone agent over the public API.
* **Replay:** `GET /api/matches/{id}/log` returns the complete round history; the web UI has a round-by-round replay scrubber on the results screen.
* **State:** in-memory per process (fine for a demo; a production fork would swap in Redis/Postgres).

Built with Flask + vanilla JS. No build step, no dependencies beyond the requirements file.
