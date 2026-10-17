#!/usr/bin/env python3
"""Sample agent bot for Auction Acres.

Plays through the public HTTP/JSON API only - the same API any AI agent
uses. Usage:

    python bot.py --url http://localhost:8091 --code ABC123 [--name Rook]
    python bot.py --url http://localhost:8091 --create --seats 3 --name Rook
    (with --create, also spawns (seats-1) bot opponents via --spawn-opponents N)

Strategy: bid proportional to parcel value, boosted when racing for or
defending a terrain majority, with light randomization so it stays
unpredictable. Never bids more than it can afford.
"""
import argparse
import random
import sys
import time
import urllib.request
import urllib.error
import json


def req(method, url, data=None, timeout=10):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
        except Exception:
            err = {"error": f"http {e.code}"}
        print(f"API error {method} {url}: {err}", file=sys.stderr)
        sys.exit(1)


def decide_bid(tile, me, players, rounds_left):
    coins = me["coins"]
    if coins <= 0:
        return 0
    base = tile["value"] * 2.4
    mine = sum(1 for t in me["tiles"] if t["terrain"] == tile["terrain"])
    rival_best = max(
        (sum(1 for t in q["tiles"] if t["terrain"] == tile["terrain"])
         for q in players if q["id"] != me["id"]),
        default=0,
    )
    boost = 1.0
    if mine >= rival_best and rival_best > 0:
        boost = 1.6
    elif mine + 1 >= rival_best and tile["value"] >= 4:
        boost = 1.35
    if rounds_left <= 4 and tile["value"] >= 5:
        boost *= 1.3
    bid = int(round(base * boost * random.uniform(0.85, 1.15)))
    cap = coins if rounds_left <= 3 else max(1, int(coins * 0.45))
    return max(0, min(bid, cap, coins))


def main():
    ap = argparse.ArgumentParser(description="Auction Acres sample bot")
    ap.add_argument("--url", required=True, help="game base URL, e.g. http://localhost:8091")
    ap.add_argument("--name", default="Rook")
    ap.add_argument("--code", help="match code to join")
    ap.add_argument("--create", action="store_true", help="create a new match instead of joining")
    ap.add_argument("--seats", type=int, default=2)
    args = ap.parse_args()
    base = args.url.rstrip("/")

    if args.create:
        j = req("POST", base + "/api/matches",
                {"name": args.name, "seats": args.seats})
        print(f"Created match {j['code']}  (join link: {base}/?code={j['code']})", flush=True)
    else:
        if not args.code:
            ap.error("--code or --create is required")
        j = req("POST", base + f"/api/matches/{args.code}/join", {"name": args.name})
        print(f"Joined match {j['code']} as {args.name}", flush=True)

    mid, token, pid = j["match_id"], j["player_token"], j["player_id"]
    if args.create:
        req("POST", base + f"/api/matches/{mid}/start", {"player_token": token})
        print("Match started (empty seats filled by bots).", flush=True)

    last_round = 0
    while True:
        time.sleep(1.0)
        s = req("GET", base + f"/api/matches/{mid}/state?token={token}")["state"]
        if s["phase"] == "done":
            sc = s["scores"][pid]
            print(f"Match over. My score: {sc['total']} "
                  f"(parcels {sc['base']} + bonus {sc['bonus']} + coins {sc['coin_points']})", flush=True)
            return
        if s["phase"] != "bidding":
            continue
        if s["round"] == last_round:
            continue
        last_round = s["round"]
        me = next(p for p in s["players"] if p["id"] == pid)
        if me["bid_submitted"]:
            continue
        tile = s["current_tile"]
        bid = decide_bid(tile, me, s["players"], s["total_rounds"] - s["round"] + 1)
        req("POST", base + f"/api/matches/{mid}/bid",
            {"player_token": token, "amount": bid})
        print(f"Round {s['round']}: {tile['terrain']} {tile['value']} -> bid {bid} "
              f"(coins left {me['coins']})", flush=True)


if __name__ == "__main__":
    main()
