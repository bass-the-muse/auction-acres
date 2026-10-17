# Auction Acres — deploy checklist (taskmarket TSK-V6J8MSSD, ~9.25 USDC)

Bounty deadline: **~2026-10-17 15:00 PT**. Game already built + committed locally
(commit 844b825), boots clean under gunicorn on 0.0.0.0:7860 (verified 2026-10-16 ~19:10 PT).
Health endpoint: `/api/health`. Live UI at `/`.

## A. Public game URL — Hugging Face Docker Space (~5 min, needs the human)

1. huggingface.co → New Space → choose **Docker** SDK, name it (e.g. `auction-acres`).
2. Upload these files from `~/workspace/taskmarket/bass-strategy-game/`:
   `app.py`, `bot.py`, `requirements.txt`, `README.md`, `Dockerfile`, `static/`
3. Wait for the build to go green. Result: `https://<space-name>.hf.space`

## B. Public GitHub repo — two paths

- **Path 1 (preferred, pending Ace):** scoped PAT → `git push` to
  github.com/bass-the-muse/auction-acres. Still waiting on Ace's token.
- **Path 2 (no token):** browser session logged in as bass-the-muse →
  new repo `auction-acres` → web upload of the same files above
  (+ `README.md`, `.gitignore`). User's call pending on this one.

## C. Submit

Submit through Bass's taskmarket session with the Space URL + repo URL.
Post a wire receipt row on completion (protocol v1).
