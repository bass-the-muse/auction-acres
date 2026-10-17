"""Auction Acres - sealed-bid territory auction game for humans and AI agents.

One Flask app serves:
  - the human web UI at /
  - the agent HTTP/JSON API under /api/

Game: 16 parcels auctioned one at a time, 2-4 players, everyone starts
with 100 coins. Each round a parcel (value 1-6, one of four terrains) is
revealed and every player submits a sealed bid. Highest bid wins the
parcel and pays the bid. Score = parcel values + terrain majority
bonuses (most of a terrain: +6, second: +3) + leftover coins x 0.1.
Highest score wins.
"""
import json
import random
import threading
import time
import uuid

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="")

TERRAINS = ["Wheat", "Forest", "Quarry", "Harbor"]
ROUNDS = 16
START_COINS = 100
BID_TIMEOUT = 25  # seconds per round before auto-resolve
FIRST_BONUS = 6
SECOND_BONUS = 3
COIN_VALUE = 0.1

matches = {}
lock = threading.Lock()


def new_token():
    return uuid.uuid4().hex[:16]


def make_deck(seed=None):
    rng = random.Random(seed)
    values = [2, 3, 4, 5, 6, 7]
    deck = []
    tid = 0
    for terrain in TERRAINS:
        vals = values[:]
        rng.shuffle(vals)
        for v in vals[:4]:
            tid += 1
            deck.append({"id": tid, "terrain": terrain, "value": v})
    rng.shuffle(deck)
    return deck[:ROUNDS]


def public_player(p, me_id=None):
    out = {
        "id": p["id"],
        "name": p["name"],
        "is_bot": p["is_bot"],
        "tiles": p["tiles"],
        "tile_count": len(p["tiles"]),
        "bid_submitted": p["bid"] is not None,
        "is_me": p["id"] == me_id,
    }
    if p["id"] == me_id:
        out["coins"] = p["coins"]
    return out


def scores(players):
    """Return {player_id: score_breakdown}."""
    result = {}
    for p in players:
        base = sum(t["value"] for t in p["tiles"])
        bonus = 0
        detail = []
        for terrain in TERRAINS:
            counts = sorted(
                ((len([t for t in q["tiles"] if t["terrain"] == terrain]), q["id"]) for q in players),
                reverse=True,
            )
            top = counts[0][0]
            if top == 0:
                continue
            leaders = [pid for c, pid in counts if c == top]
            if p["id"] in leaders:
                b = FIRST_BONUS // len(leaders) if len(leaders) > 1 else FIRST_BONUS
                # keep it simple: tied leaders split? no - each gets full, doc'd
                b = FIRST_BONUS
                bonus += b
                detail.append(f"{terrain} majority +{b}")
            elif counts[1][0] > 0 and p["id"] == counts[1][1]:
                bonus += SECOND_BONUS
                detail.append(f"{terrain} runner-up +{SECOND_BONUS}")
        coin_pts = round(p["coins"] * COIN_VALUE, 1)
        result[p["id"]] = {
            "base": base,
            "bonus": bonus,
            "bonus_detail": detail,
            "coin_points": coin_pts,
            "total": round(base + bonus + coin_pts, 1),
        }
    return result


def current_tile(m):
    if m["phase"] != "bidding" or m["round"] >= ROUNDS:
        return None
    return m["deck"][m["round"]]


def state_view(m, me_id=None):
    sc = scores(m["players"]) if m["phase"] == "done" else None
    return {
        "match_id": m["id"],
        "code": m["code"],
        "phase": m["phase"],
        "seats": m["seats"],
        "round": m["round"] + 1 if m["phase"] == "bidding" else m["round"],
        "total_rounds": ROUNDS,
        "current_tile": current_tile(m),
        "bids_in": sum(1 for p in m["players"] if p["bid"] is not None),
        "round_ends_in": max(0, int(m["round_deadline"] - time.time())) if m["phase"] == "bidding" else None,
        "players": [public_player(p, me_id) for p in m["players"]],
        "scores": sc,
        "winner": m.get("winner"),
    }


def bot_bid_amount(bot, tile, m):
    """Sample strategy: value-proportional with majority-race boost and noise."""
    coins = bot["coins"]
    if coins <= 0:
        return 0
    base = tile["value"] * 2.4
    # boost if close to a terrain majority
    mine = len([t for t in bot["tiles"] if t["terrain"] == tile["terrain"]])
    rival_best = max(
        (len([t for t in q["tiles"] if t["terrain"] == tile["terrain"]]) for q in m["players"] if q["id"] != bot["id"]),
        default=0,
    )
    boost = 1.0
    if mine >= rival_best and rival_best > 0:
        boost = 1.6  # defending a lead
    elif mine + 1 >= rival_best and tile["value"] >= 4:
        boost = 1.35  # racing for a majority
    # late-game urgency: spend down on high-value tiles
    rounds_left = ROUNDS - m["round"]
    if rounds_left <= 4 and tile["value"] >= 5:
        boost *= 1.3
    bid = base * boost * random.uniform(0.85, 1.15)
    bid = int(round(bid))
    # don't blow the whole stack early
    cap = coins if rounds_left <= 3 else max(1, int(coins * 0.45))
    return max(0, min(bid, cap, coins))


def resolve_round(m):
    tile = m["deck"][m["round"]]
    bids = {p["id"]: (p["bid"] or 0) for p in m["players"]}
    top = max(bids.values())
    contenders = [pid for pid, b in bids.items() if b == top]
    winner_id = random.choice(contenders)
    tie = len(contenders) > 1
    for p in m["players"]:
        if p["id"] == winner_id:
            p["coins"] -= bids[winner_id]
            p["tiles"].append(tile)
        p["bid"] = None
    entry = {
        "round": m["round"] + 1,
        "tile": tile,
        "bids": [{"player_id": pid, "name": name_of(m, pid), "amount": amt} for pid, amt in bids.items()],
        "winner_id": winner_id,
        "winner_name": name_of(m, winner_id),
        "price": bids[winner_id],
        "tie": tie,
    }
    m["log"].append(entry)
    m["round"] += 1
    if m["round"] >= ROUNDS:
        m["phase"] = "done"
        sc = scores(m["players"])
        m["winner"] = max(sc.items(), key=lambda kv: kv[1]["total"])[0]
        m["final_scores"] = sc
    else:
        m["round_deadline"] = time.time() + BID_TIMEOUT
        # schedule bot bids with a small human-like delay
        for p in m["players"]:
            if p["is_bot"]:
                p["bot_due"] = time.time() + random.uniform(1.0, 4.0)


def name_of(m, pid):
    for p in m["players"]:
        if p["id"] == pid:
            return p["name"]
    return "?"


def sweeper():
    while True:
        time.sleep(1.0)
        now = time.time()
        with lock:
            for m in list(matches.values()):
                if m["phase"] != "bidding":
                    continue
                # bot bids due
                for p in m["players"]:
                    if p["is_bot"] and p["bid"] is None and now >= p.get("bot_due", 0):
                        tile = m["deck"][m["round"]]
                        p["bid"] = bot_bid_amount(p, tile, m)
                # resolve when everyone bid or timeout
                if all(p["bid"] is not None for p in m["players"]) or now >= m["round_deadline"]:
                    resolve_round(m)


threading.Thread(target=sweeper, daemon=True).start()


def get_match_or_404(mid):
    m = matches.get(mid)
    if not m:
        return None, (jsonify({"ok": False, "error": "match not found"}), 404)
    return m, None


def player_from_token(m, token):
    if not token:
        return None
    for p in m["players"]:
        if p["token"] == token:
            return p
    return None


# ---------- API ----------

@app.route("/api/matches", methods=["POST"])
def api_create():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "Player").strip()[:24] or "Player"
    try:
        seats = int(data.get("seats", 4))
    except (TypeError, ValueError):
        seats = 4
    seats = max(2, min(4, seats))
    mid = uuid.uuid4().hex[:8]
    code = mid[:6].upper()
    pid = uuid.uuid4().hex[:8]
    token = new_token()
    m = {
        "id": mid,
        "code": code,
        "seats": seats,
        "players": [{
            "id": pid, "name": name, "token": token,
            "coins": START_COINS, "tiles": [], "is_bot": False,
            "bid": None, "bot_due": 0,
        }],
        "creator": pid,
        "round": 0,
        "deck": make_deck(),
        "phase": "lobby",
        "round_deadline": 0,
        "log": [],
        "created": time.time(),
    }
    with lock:
        matches[mid] = m
    return jsonify({"ok": True, "match_id": mid, "code": code,
                    "player_id": pid, "player_token": token})


@app.route("/api/matches/<mid>/join", methods=["POST"])
def api_join(mid):
    m, err = get_match_or_404(mid)
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "Player").strip()[:24] or "Player"
    with lock:
        if m["phase"] != "lobby":
            return jsonify({"ok": False, "error": "match already started"}), 400
        if len(m["players"]) >= m["seats"]:
            return jsonify({"ok": False, "error": "match is full"}), 400
        pid = uuid.uuid4().hex[:8]
        token = new_token()
        m["players"].append({
            "id": pid, "name": name, "token": token,
            "coins": START_COINS, "tiles": [], "is_bot": False,
            "bid": None, "bot_due": 0,
        })
    return jsonify({"ok": True, "match_id": mid, "code": m["code"],
                    "player_id": pid, "player_token": token})


@app.route("/api/matches/<mid>/start", methods=["POST"])
def api_start(mid):
    m, err = get_match_or_404(mid)
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    with lock:
        me = player_from_token(m, data.get("player_token"))
        if not me:
            return jsonify({"ok": False, "error": "bad token"}), 401
        if m["phase"] != "lobby":
            return jsonify({"ok": False, "error": "already started"}), 400
        # fill empty seats with bots
        n = 0
        while len(m["players"]) < m["seats"]:
            n += 1
            m["players"].append({
                "id": uuid.uuid4().hex[:8], "name": f"Bot-{n}",
                "token": new_token(), "coins": START_COINS, "tiles": [],
                "is_bot": True, "bid": None, "bot_due": time.time() + random.uniform(1.0, 3.0),
            })
        m["phase"] = "bidding"
        m["round_deadline"] = time.time() + BID_TIMEOUT
    return jsonify({"ok": True, "state": state_view(m, me["id"])})


@app.route("/api/matches/<mid>/state", methods=["GET"])
def api_state(mid):
    m, err = get_match_or_404(mid)
    if err:
        return err
    token = request.args.get("token", "")
    with lock:
        me = player_from_token(m, token)
        me_id = me["id"] if me else None
        return jsonify({"ok": True, "state": state_view(m, me_id)})


@app.route("/api/matches/<mid>/bid", methods=["POST"])
def api_bid(mid):
    m, err = get_match_or_404(mid)
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    with lock:
        me = player_from_token(m, data.get("player_token") or data.get("token"))
        if not me:
            return jsonify({"ok": False, "error": "bad token"}), 401
        if me["is_bot"]:
            return jsonify({"ok": False, "error": "bots bid automatically"}), 400
        if m["phase"] != "bidding":
            return jsonify({"ok": False, "error": "not in bidding phase"}), 400
        if me["bid"] is not None:
            return jsonify({"ok": False, "error": "already bid this round"}), 400
        try:
            amount = int(data.get("amount", 0))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "amount must be an integer"}), 400
        if amount < 0 or amount > me["coins"]:
            return jsonify({"ok": False, "error": f"amount must be 0..{me['coins']}"}), 400
        me["bid"] = amount
        if all(p["bid"] is not None for p in m["players"]):
            resolve_round(m)
        return jsonify({"ok": True, "state": state_view(m, me["id"])})


@app.route("/api/matches/<mid>/log", methods=["GET"])
def api_log(mid):
    m, err = get_match_or_404(mid)
    if err:
        return err
    with lock:
        return jsonify({"ok": True, "match_id": mid, "code": m["code"],
                        "phase": m["phase"], "rounds": m["log"],
                        "final_scores": m.get("final_scores"),
                        "winner": m.get("winner")})


@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"ok": True, "game": "auction-acres", "matches": len(matches)})


# ---------- frontend ----------

@app.route("/", methods=["GET"])
def index():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8091)
