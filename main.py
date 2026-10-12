
import os
import json
import time
import threading
import requests
from datetime import datetime, timezone

# ============================================================
# BITGET DEMAND RADAR V15
# LONG + SHORT | 25 COIN | FILTRE TANI
# ============================================================

BASE = "https://api.bitget.com"
PRODUCT = "USDT-FUTURES"

BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("BOT_TOKEN") or ""
).strip()

CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("CHAT_ID") or ""
).strip()

MAX_CANDIDATES = 25
MAX_ALERTS = 5

MIN_24H_VOLUME = 100000
MIN_SCORE = 50
MIN_RSI = 45
MAX_RSI = 75
MIN_VOL_RATIO = 1.10

MAX_MOVE15 = 8.0
MAX_MOVE1H = 15.0

DAILY_NEAR_PERCENT = 3.0
WEEKLY_NEAR_PERCENT = 6.0

COOLDOWN_HOURS = 4
SL_ATR = 1.5
TIMEOUT = 20
STATE_FILE = "bitget_radar_state.json"

REQUEST_DELAY = 0.40
MAX_RETRIES = 5

EXCLUDED = {
    "AAPL", "TSLA", "NVDA", "AMZN", "META", "MSFT",
    "GOOGL", "GOOG", "NFLX", "COIN", "MSTR", "AMD",
    "INTC", "SPY", "QQQ", "PLTR", "HOOD", "ORCL"
}

http = requests.Session()
http.headers.update({"User-Agent": "BitgetDemandRadar/15.0"})

api_lock = threading.Lock()
state_lock = threading.Lock()
last_api_request = 0.0
rejections = {}


# ============================================================
# YARDIMCILAR VE FILTRE RAPORU
# ============================================================

def log(message):
    print(
        f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC] "
        f"{message}",
        flush=True
    )


def reject(reason):
    rejections[reason] = rejections.get(reason, 0) + 1
    return None


def num(value, default=0.0):
    try:
        value = float(value)
        if value == value and abs(value) != float("inf"):
            return value
    except (TypeError, ValueError):
        pass
    return default


def average(values):
    return sum(values) / len(values) if values else 0.0


def pct(old, new):
    return (new - old) / old * 100 if old > 0 else 0.0


def fmt(value):
    return f"{value:.10g}" if value else "N/A"


# ============================================================
# BITGET API - HIZ SINIRI KORUMASI
# ============================================================

def api_get(path, params=None):
    global last_api_request

    for attempt in range(MAX_RETRIES):
        try:
            with api_lock:
                wait = REQUEST_DELAY - (
                    time.monotonic() - last_api_request
                )
                if wait > 0:
                    time.sleep(wait)

                response = http.get(
                    BASE + path,
                    params=params,
                    timeout=TIMEOUT
                )
                last_api_request = time.monotonic()

            if response.status_code == 429:
                delay = min(2 ** attempt, 30)
                log(f"429 hiz siniri: {path}; {delay} sn bekleniyor.")
                time.sleep(delay)
                continue

            if response.status_code in (500, 502, 503, 504):
                delay = min(2 ** attempt, 20)
                log(f"Sunucu hatasi {response.status_code}: {path}")
                time.sleep(delay)
                continue

            response.raise_for_status()
            result = response.json()

            if result.get("code") != "00000":
                log(
                    f"API hatasi {path}: "
                    f"{result.get('msg', result)}"
                )
                return None

            return result.get("data")

        except (requests.RequestException, ValueError) as exc:
            log(f"API denemesi {attempt + 1}/{MAX_RETRIES}: {exc}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(min(2 ** attempt, 20))

    return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        log("Telegram token/chat ID eksik.")
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "disable_web_page_preview": True
            },
            timeout=TIMEOUT
        )
        response.raise_for_status()
        result = response.json()

        if result.get("ok"):
            return True

        log(f"Telegram hatasi: {result}")
        return False

    except requests.RequestException as exc:
        log(f"Telegram gonderim hatasi: {exc}")
        return False


# ============================================================
# TEKRAR SINYAL ENGELI
# ============================================================

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("sent", {})
            return data
    except (OSError, ValueError):
        pass

    return {"sent": {}}


state = load_state()


def save_state():
    try:
        with state_lock:
            temp = STATE_FILE + ".tmp"
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(temp, STATE_FILE)
    except OSError as exc:
        log(f"Durum dosyasi kaydedilemedi: {exc}")


def is_cooling(symbol, direction):
    with state_lock:
        item = state.get("sent", {}).get(
            f"{symbol}_{direction}", {}
        )
        timestamp = num(item.get("time"))

    return time.time() - timestamp < COOLDOWN_HOURS * 3600


def mark_sent(symbol, direction):
    with state_lock:
        state.setdefault("sent", {})
        state["sent"][f"{symbol}_{direction}"] = {
            "time": time.time()
        }
    save_state()


# ============================================================
# KONTRATLAR VE TICKER
# ============================================================

def get_contracts():
    data = api_get(
        "/api/v2/mix/market/contracts",
        {"productType": PRODUCT}
    )

    if not isinstance(data, list):
        return []

    symbols = []

    for item in data:
        symbol = str(item.get("symbol", "")).upper()
        base_coin = str(item.get("baseCoin", "")).upper()

        if not symbol.endswith("USDT"):
            continue
        if base_coin in EXCLUDED:
            continue
        if item.get("symbolStatus") not in (None, "normal"):
            continue

        symbols.append(symbol)

    return sorted(set(symbols))


def get_tickers():
    data = api_get(
        "/api/v2/mix/market/tickers",
        {"productType": PRODUCT}
    )

    if not isinstance(data, list):
        return {}

    return {
        item["symbol"]: item
        for item in data
        if isinstance(item, dict) and item.get("symbol")
    }


def ticker_price(ticker):
    return num(ticker.get("lastPr"))


def ticker_volume(ticker):
    value = num(ticker.get("usdtVolume"))
    return value if value > 0 else num(ticker.get("quoteVolume"))


# ============================================================
# MUM VERILERI
# ============================================================

def get_candles(symbol, interval, limit=100):
    data = api_get(
        "/api/v2/mix/market/candles",
        {
            "symbol": symbol,
            "productType": PRODUCT,
            "granularity": interval,
            "limit": str(limit)
        }
    )

    if not isinstance(data, list):
        return []

    candles = []

    for row in data:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue

        candle = {
            "time": num(row[0]),
            "open": num(row[1]),
            "high": num(row[2]),
            "low": num(row[3]),
            "close": num(row[4]),
            "volume": num(row[5])
        }

        if candle["close"] > 0:
            candles.append(candle)

    candles.sort(key=lambda c: c["time"])

    # Son mum tamamlanmamis olabilir.
    if len(candles) > 1:
        candles = candles[:-1]

    return candles[-limit:]


# ============================================================
# RSI / ATR / HACIM / TREND
# ============================================================

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0

    changes = [
        closes[i] - closes[i - 1]
        for i in range(len(closes) - period, len(closes))
    ]

    gain = average([max(x, 0) for x in changes])
    loss = average([max(-x, 0) for x in changes])

    if loss == 0:
        return 100.0 if gain > 0 else 50.0

    rs = gain / loss
    return 100 - 100 / (1 + rs)


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0

    ranges = []

    for i in range(1, len(candles)):
        c = candles[i]
        prev = candles[i - 1]["close"]

        ranges.append(max(
            c["high"] - c["low"],
            abs(c["high"] - prev),
            abs(c["low"] - prev)
        ))

    return average(ranges[-period:])


def volume_ratio(candles, period=20):
    if len(candles) < period + 2:
        return 1.0

    baseline = average([
        c["volume"] for c in candles[-period-1:-1]
    ])

    return candles[-1]["volume"] / baseline if baseline > 0 else 1.0


def get_trend(candles):
    if len(candles) < 30:
        return "NEUTRAL"

    closes = [c["close"] for c in candles]
    fast = average(closes[-9:])
    slow = average(closes[-26:])

    if fast > slow and closes[-1] >= closes[-2]:
        return "LONG"
    if fast < slow and closes[-1] <= closes[-2]:
        return "SHORT"

    return "NEUTRAL"


def get_structure(candles):
    if len(candles) < 12:
        return "NEUTRAL"

    recent = candles[-6:]
    previous = candles[-12:-6]

    rh = max(c["high"] for c in recent)
    rl = min(c["low"] for c in recent)
    ph = max(c["high"] for c in previous)
    pl = min(c["low"] for c in previous)

    if rh > ph and rl > pl:
        return "LONG"
    if rh < ph and rl < pl:
        return "SHORT"

    return "NEUTRAL"


# ============================================================
# SUPPLY / DEMAND
# ============================================================

def find_zones(candles):
    if len(candles) < 30:
        return None, None

    demand = None
    supply = None
    recent = candles[-60:]

    for i in range(len(recent) - 4, 1, -1):
        base = recent[i]
        future = recent[i + 1:i + 4]

        candle_range = base["high"] - base["low"]
        if candle_range <= 0:
            continue

        body_ratio = (
            abs(base["close"] - base["open"]) / candle_range
        )

        if not (
            base["close"] <= base["open"]
            or body_ratio <= 0.45
        ):
            continue

        move = pct(base["close"], future[-1]["close"])

        if move >= 2 and future[-1]["close"] > base["high"]:
            if demand is None:
                demand = (
                    base["low"],
                    max(base["open"], base["close"])
                )

        if move <= -2 and future[-1]["close"] < base["low"]:
            if supply is None:
                supply = (
                    min(base["open"], base["close"]),
                    base["high"]
                )

        if demand and supply:
            break

    return demand, supply


def assess_zone(price, zone, near_percent, direction):
    if not zone:
        return None

    low, high = zone

    if low <= price <= high:
        return {
            "low": low, "high": high,
            "status": "ICINDE", "distance": 0.0
        }

    if direction == "LONG" and price > high:
        distance = (price - high) / high * 100
    elif direction == "SHORT" and price < low:
        distance = (low - price) / low * 100
    else:
        return None

    if distance > near_percent:
        return None

    return {
        "low": low, "high": high,
        "status": "YAKLASIYOR", "distance": distance
    }


def in_zone(price, zone):
    return bool(zone and zone[0] <= price <= zone[1])


# ============================================================
# BTC YONU
# ============================================================

def get_btc_direction():
    c1 = get_candles("BTCUSDT", "1H", 80)
    c4 = get_candles("BTCUSDT", "4H", 80)

    if len(c1) < 30 or len(c4) < 30:
        return "NEUTRAL"

    t1 = get_trend(c1)
    t4 = get_trend(c4)

    if t1 == "LONG" and t4 == "LONG":
        return "LONG"
    if t1 == "SHORT" and t4 == "SHORT":
        return "SHORT"

    return "NEUTRAL"


# ============================================================
# COIN ANALIZI
# ============================================================

def analyze_symbol(symbol, ticker, btc):
    price = ticker_price(ticker)
    volume24 = ticker_volume(ticker)

    if price <= 0 or volume24 < MIN_24H_VOLUME:
        return reject("Fiyat veya 24H hacim")

    c15 = get_candles(symbol, "15m")
    c1 = get_candles(symbol, "1H")
    c4 = get_candles(symbol, "4H")
    c1d = get_candles(symbol, "1D")
    c1w = get_candles(symbol, "1W")

    if min(len(c15), len(c1), len(c4)) < 30:
        return reject("Yetersiz mum verisi")

    closes15 = [c["close"] for c in c15]
    closes1 = [c["close"] for c in c1]

    rsi15 = calculate_rsi(closes15)
    rsi1 = calculate_rsi(closes1)
    vr15 = volume_ratio(c15)
    vr1 = volume_ratio(c1)

    trend1 = get_trend(c1)
    trend4 = get_trend(c4)
    structure1 = get_structure(c1)
    structure4 = get_structure(c4)

    move15 = pct(closes15[-2], closes15[-1])
    move1 = pct(closes1[-2], closes1[-1])

    if abs(move15) > MAX_MOVE15 or abs(move1) > MAX_MOVE1H:
        return reject("Ani fiyat hareketi")

    demand4, supply4 = find_zones(c4)
    demand1d, supply1d = find_zones(c1d)
    demand1w, supply1w = find_zones(c1w)

    dl = assess_zone(price, demand1d, DAILY_NEAR_PERCENT, "LONG")
    wl = assess_zone(price, demand1w, WEEKLY_NEAR_PERCENT, "LONG")
    ds = assess_zone(price, supply1d, DAILY_NEAR_PERCENT, "SHORT")
    ws = assess_zone(price, supply1w, WEEKLY_NEAR_PERCENT, "SHORT")

    long_score = 0
    short_score = 0

    if vr15 >= MIN_VOL_RATIO:
        long_score += 10
        short_score += 10

    if vr1 >= 1.10:
        long_score += 5
        short_score += 5

    if MIN_RSI <= rsi15 <= MAX_RSI:
        long_score += 4
        short_score += 4

    if rsi15 > 50:
        long_score += 5
    elif rsi15 < 50:
        short_score += 5

    if rsi1 > 50:
        long_score += 7
    elif rsi1 < 50:
        short_score += 7

    if trend1 == "LONG":
        long_score += 10
    elif trend1 == "SHORT":
        short_score += 10

    if trend4 == "LONG":
        long_score += 10
    elif trend4 == "SHORT":
        short_score += 10

    if structure1 == "LONG":
        long_score += 5
    elif structure1 == "SHORT":
        short_score += 5

    if structure4 == "LONG":
        long_score += 5
    elif structure4 == "SHORT":
        short_score += 5

    if in_zone(price, demand4):
        long_score += 8
    if in_zone(price, supply4):
        short_score += 8

    if dl:
        long_score += 12
    if wl:
        long_score += 15
    if dl and wl:
        long_score += 8

    if ds:
        short_score += 12
    if ws:
        short_score += 15
    if ds and ws:
        short_score += 8

    # BTC yonu puani etkiler; NEUTRAL iki yone de izin verir.
    if btc == "LONG":
        long_score += 5
        short_score -= 10
    elif btc == "SHORT":
        short_score += 5
        long_score -= 10

    if long_score >= short_score:
        direction, score = "LONG", long_score
    else:
        direction, score = "SHORT", short_score

    if score < MIN_SCORE:
        return reject("Puan esigi")

    if btc != "NEUTRAL" and direction != btc:
        return reject("BTC ters yon filtresi")

    if direction == "LONG":
        if rsi15 > MAX_RSI:
            return reject("LONG RSI yuksek")

        if not (dl or wl or in_zone(price, demand4)):
            return reject("LONG demand bolgesi yok")

    else:
        if rsi15 < 100 - MAX_RSI:
            return reject("SHORT RSI dusuk")

        if not (ds or ws or in_zone(price, supply4)):
            return reject("SHORT supply bolgesi yok")

    if is_cooling(symbol, direction):
        return reject("Cooldown")

    atr = calculate_atr(c15)
    if atr <= 0:
        return reject("ATR hesaplanamadi")

    if direction == "LONG":
        stop = price - SL_ATR * atr
        tp1 = price + 2 * atr
        tp2 = price + 3 * atr
        daily, weekly = dl, wl
    else:
        stop = price + SL_ATR * atr
        tp1 = price - 2 * atr
        tp2 = price - 3 * atr
        daily, weekly = ds, ws

    return {
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "price": price,
        "volume24": volume24,
        "rsi15": rsi15,
        "rsi1": rsi1,
        "vr15": vr15,
        "vr1": vr1,
        "btc": btc,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "daily": daily,
        "weekly": weekly
    }


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def format_signal(r):
    arrow = "🟢" if r["direction"] == "LONG" else "🔴"

    def zone_text(zone):
        if not zone:
            return "Bulunamadi\nYok"

        return (
            f"{zone['status']}\n"
            f"{zone['low']:.8g} - {zone['high']:.8g}"
            f" | %{zone['distance']:.2f}"
        )

    return (
        f"{arrow} BITGET DEMAND RADAR V15\n\n"
        f"{r['symbol']} | {r['direction']} | Puan {r['score']}\n"
        f"Fiyat: {fmt(r['price'])}\n\n"
        f"📍 Gunluk bolge:\n{zone_text(r['daily'])}\n\n"
        f"📍 Haftalik bolge:\n{zone_text(r['weekly'])}\n\n"
        f"🛑 Stop: {fmt(r['stop'])}\n"
        f"🎯 TP1: {fmt(r['tp1'])}\n"
        f"🎯 TP2: {fmt(r['tp2'])}\n\n"
        f"Hacim 15M x{r['vr15']:.2f} | 1H x{r['vr1']:.2f}\n"
        f"RSI 15M: {r['rsi15']:.0f} | 1H: {r['rsi1']:.0f}\n"
        f"BTC: {r['btc']}\n\n"
        "⚠️ Teknik sinyal; otomatik emir acmaz."
    )


# ============================================================
# TARAMA
# ============================================================

def run_scan():
    rejections.clear()
    log("BITGET DEMAND RADAR V15 taramasi basladi.")

    tickers = get_tickers()
    if not tickers:
        raise RuntimeError("Bitget ticker verisi alinamadi.")

    symbols = get_contracts()
    if not symbols:
        raise RuntimeError("Bitget kontrat listesi alinamadi.")

    candidates = []

    for symbol in symbols:
        ticker = tickers.get(symbol)
        if not ticker:
            continue

        price = ticker_price(ticker)
        volume = ticker_volume(ticker)

        if price > 0 and volume >= MIN_24H_VOLUME:
            candidates.append((symbol, ticker, volume))

    candidates.sort(key=lambda x: x[2], reverse=True)
    candidates = candidates[:MAX_CANDIDATES]

    log(f"Toplam kontrat: {len(symbols)}")
    log(f"Analiz adayi: {len(candidates)}")

    btc = get_btc_direction()
    log(f"BTC filtresi: {btc}")

    results = []

    # Sirali istek: API hiz siniri riskini azaltir.
    for symbol, ticker, _ in candidates:
        try:
            result = analyze_symbol(symbol, ticker, btc)
            if result:
                results.append(result)
        except Exception as exc:
            log(f"{symbol} analiz hatasi: {exc}")
            reject("Beklenmeyen analiz hatasi")

    results.sort(key=lambda x: x["score"], reverse=True)

    log(f"Gecerli sinyal adayi: {len(results)}")
    log("----- FILTRE RAPORU -----")

    if rejections:
        for reason, count in sorted(
            rejections.items(), key=lambda x: x[1], reverse=True
        ):
            log(f"{reason}: {count}")
    else:
        log("Filtre reddi yok.")

    log("-------------------------")

    if not results:
        log("Sinyal yok. Filtre raporunu kontrol et.")
        return

    sent_count = 0

    for result in results:
        if sent_count >= MAX_ALERTS:
            break

        if send_telegram(format_signal(result)):
            mark_sent(result["symbol"], result["direction"])
            sent_count += 1
            log(
                f"Gonderildi: {result['symbol']} "
                f"{result['direction']} puan={result['score']}"
            )

        time.sleep(1)

    log(f"Tarama tamamlandi. Gonderilen: {sent_count}")


def main():
    log("BITGET DEMAND RADAR V15 basladi.")

    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Telegram Secrets eksik: "
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID"
        )

    run_scan()
    log("Program tamamlandi.")


if __name__ == "__main__":
    main()
