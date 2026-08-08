#!/usr/bin/env python3
"""
BTC Strategy Arena - live paper-trading engine.
5 original long-only strategies, BTCUSDT 5m candles, $100,000 each.
TP +0.8% / SL -0.5%, 0.1% taker fee per side.
Run every 5 minutes (GitHub Actions cron). State persists in docs/data/.
"""
import json, math, os, time, urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "docs", "data")
STATE_F = os.path.join(DATA_DIR, "state.json")
TRADES_F = os.path.join(DATA_DIR, "trades.json")
EQUITY_F = os.path.join(DATA_DIR, "equity.json")

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
START_CAPITAL = 100_000.0
TP_PCT = 0.008          # +0.8%
SL_PCT = 0.005          # -0.5%
FEE = 0.001             # 0.1% per side
LOOKBACK = 60           # candles of history each strategy may inspect
MAX_EQUITY_POINTS = 8000

STRATEGIES = ["TAKER_TIDE", "CROWD_SURGE", "WICK_ABSORB", "ENTROPY_DRIFT", "RANGE_COIL"]

# ---------------------------------------------------------------- data fetch
def fetch_klines(limit=200):
    url = (f"https://data-api.binance.vision/api/v3/klines?symbol={SYMBOL}""
           f"&interval={INTERVAL}&limit={limit}")
    with urllib.request.urlopen(url, timeout=20) as r:
        raw = json.loads(r.read().decode())
    now_ms = int(time.time() * 1000)
    candles = []
    for k in raw:
        if int(k[6]) > now_ms:      # candle still open -> skip
            continue
        candles.append({
            "t": int(k[0]),                 # open time ms
            "o": float(k[1]), "h": float(k[2]),
            "l": float(k[3]), "c": float(k[4]),
            "v": float(k[5]),               # base volume
            "n": int(k[8]),                 # number of trades
            "tb": float(k[9]),              # taker buy base volume
        })
    return candles

# ---------------------------------------------------------------- helpers
def sma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n

def median(vals):
    s = sorted(vals)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2

# ---------------------------------------------------------------- strategies
# Each returns ("BUY"|"SELL"|None, meta_dict). `hist` = closed candles up to
# and including the candle being evaluated (last element). `pos` = open
# position dict or None.

def taker_tide(hist, pos):
    if len(hist) < 8:
        return None, {}
    ratios = [c["tb"] / c["v"] if c["v"] > 0 else 0.5 for c in hist[-6:]]
    avg6 = sum(ratios) / 6
    if pos:
        return ("SELL", {"reason": "tide flipped"}) if avg6 < 0.47 else (None, {})
    if avg6 > 0.56 and hist[-1]["c"] > hist[-7]["c"]:
        return "BUY", {"note": f"taker-buy {avg6:.1%}"}
    return None, {}

def crowd_surge(hist, pos):
    if len(hist) < 50:
        return None, {}
    closes = [c["c"] for c in hist]
    s20 = sma(closes, 20)
    if pos:
        return ("SELL", {"reason": "lost 20-MA"}) if hist[-1]["c"] < s20 else (None, {})
    counts = [c["n"] for c in hist[-49:-1]]
    mu = sum(counts) / len(counts)
    var = sum((x - mu) ** 2 for x in counts) / len(counts)
    sd = math.sqrt(var) or 1.0
    z = (hist[-1]["n"] - mu) / sd
    cur = hist[-1]
    if z > 2.0 and cur["c"] > cur["o"] and cur["c"] > s20:
        return "BUY", {"note": f"crowd z={z:.1f}"}
    return None, {}

def wick_absorb(hist, pos):
    if len(hist) < 13:
        return None, {}
    window = hist[-12:]
    lw = sum(min(c["o"], c["c"]) - c["l"] for c in window)
    uw = sum(c["h"] - max(c["o"], c["c"]) for c in window)
    ratio = lw / (uw + 1e-9)
    closes = [c["c"] for c in hist]
    if pos:
        return ("SELL", {"reason": "upper wicks dominate"}) if ratio < 0.8 else (None, {})
    if ratio > 1.5 and hist[-1]["c"] > sma(closes, 12):
        return "BUY", {"note": f"absorb {ratio:.2f}x"}
    return None, {}

def entropy_drift(hist, pos):
    if len(hist) < 26:
        return None, {}
    rets = [hist[i]["c"] - hist[i - 1]["c"] for i in range(len(hist) - 24, len(hist))]
    ups = sum(1 for r in rets if r > 0)
    p = ups / 24
    if p in (0.0, 1.0):
        h = 0.0
    else:
        h = -p * math.log2(p) - (1 - p) * math.log2(1 - p)
    if pos:
        return ("SELL", {"reason": "entropy rose"}) if h > 0.97 else (None, {})
    if h < 0.90 and sum(rets) > 0 and hist[-1]["c"] > hist[-25]["c"]:
        return "BUY", {"note": f"H={h:.2f} bits"}
    return None, {}

def range_coil(hist, pos):
    if len(hist) < 14:
        return None, {}
    if pos:
        stop = pos.get("meta", {}).get("coil_low")
        if stop and hist[-1]["c"] < stop:
            return "SELL", {"reason": "below coil low"}
        return None, {}
    prev = hist[-2]
    ranges = [c["h"] - c["l"] for c in hist[-13:-1]]
    if (prev["h"] - prev["l"]) > min(ranges) + 1e-9:
        return None, {}
    vols = [c["v"] for c in hist[-13:-1]]
    cur = hist[-1]
    if cur["c"] > prev["h"] and cur["v"] > median(vols):
        return "BUY", {"note": "coil break", "coil_low": prev["l"]}
    return None, {}

LOGIC = {
    "TAKER_TIDE": taker_tide,
    "CROWD_SURGE": crowd_surge,
    "WICK_ABSORB": wick_absorb,
    "ENTROPY_DRIFT": entropy_drift,
    "RANGE_COIL": range_coil,
}

# ---------------------------------------------------------------- state
def load(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default

def fresh_state():
    return {
        "meta": {"symbol": SYMBOL, "interval": INTERVAL,
                 "start_capital": START_CAPITAL, "tp_pct": TP_PCT,
                 "sl_pct": SL_PCT, "fee": FEE,
                 "started": datetime.now(timezone.utc).isoformat(),
                 "last_run": None, "last_candle": 0, "last_price": None},
        "strategies": {s: {"cash": START_CAPITAL, "position": None,
                           "equity": START_CAPITAL, "trades": 0, "wins": 0}
                       for s in STRATEGIES},
    }

# ---------------------------------------------------------------- trade ops
def open_pos(st, name, candle, meta, trades):
    price = candle["c"]
    cash = st["cash"]
    fee_paid = cash * FEE
    qty = (cash - fee_paid) / price
    st["cash"] = 0.0
    st["position"] = {"qty": qty, "entry": price, "entry_t": candle["t"],
                      "fee_in": fee_paid, "meta": meta}
    trades.append({"strategy": name, "side": "BUY", "price": price,
                   "qty": round(qty, 6), "time": candle["t"],
                   "note": meta.get("note", "")})

def close_pos(st, name, price, t, reason, trades):
    pos = st["position"]
    gross = pos["qty"] * price
    fee_paid = gross * FEE
    proceeds = gross - fee_paid
    cost = pos["qty"] * pos["entry"] + pos["fee_in"]
    pnl = proceeds - cost
    st["cash"] = proceeds
    st["position"] = None
    st["trades"] += 1
    if pnl > 0:
        st["wins"] += 1
    trades.append({"strategy": name, "side": "SELL", "price": price,
                   "qty": round(pos["qty"], 6), "time": t, "pnl": round(pnl, 2),
                   "note": reason})

def mark_equity(st, price):
    if st["position"]:
        st["equity"] = round(st["cash"] + st["position"]["qty"] * price, 2)
    else:
        st["equity"] = round(st["cash"], 2)

# ---------------------------------------------------------------- main loop
def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    state = load(STATE_F, fresh_state())
    trades = load(TRADES_F, [])
    equity = load(EQUITY_F, [])

    candles = fetch_klines()
    if not candles:
        return
    last_seen = state["meta"].get("last_candle", 0)
    new = [c for c in candles if c["t"] > last_seen]

    for i, candle in enumerate(new):
        # history = all candles up to and including this one
        idx = candles.index(candle)
        hist = candles[max(0, idx - LOOKBACK + 1): idx + 1]
        for name in STRATEGIES:
            st = state["strategies"][name]
            pos = st["position"]
            if pos:
                sl_price = pos["entry"] * (1 - SL_PCT)
                tp_price = pos["entry"] * (1 + TP_PCT)
                if candle["l"] <= sl_price:          # SL first: conservative
                    close_pos(st, name, sl_price, candle["t"], "stop-loss -0.5%", trades)
                elif candle["h"] >= tp_price:
                    close_pos(st, name, tp_price, candle["t"], "take-profit +0.8%", trades)
                else:
                    sig, meta = LOGIC[name](hist, pos)
                    if sig == "SELL":
                        close_pos(st, name, candle["c"], candle["t"],
                                  meta.get("reason", "signal exit"), trades)
            else:
                sig, meta = LOGIC[name](hist, None)
                if sig == "BUY":
                    open_pos(st, name, candle, meta, trades)
        state["meta"]["last_candle"] = candle["t"]

    price = candles[-1]["c"]
    for name in STRATEGIES:
        mark_equity(state["strategies"][name], price)

    state["meta"]["last_run"] = datetime.now(timezone.utc).isoformat()
    state["meta"]["last_price"] = price
    equity.append({"t": candles[-1]["t"],
                   **{s: state["strategies"][s]["equity"] for s in STRATEGIES},
                   "btc": price})
    equity = equity[-MAX_EQUITY_POINTS:]

    with open(STATE_F, "w") as f:
        json.dump(state, f, indent=1)
    with open(TRADES_F, "w") as f:
        json.dump(trades[-2000:], f, indent=1)
    with open(EQUITY_F, "w") as f:
        json.dump(equity, f)
    print(f"OK {datetime.now(timezone.utc).isoformat()} price={price} "
          f"new_candles={len(new)} trades_total={len(trades)}")

if __name__ == "__main__":
    main()
