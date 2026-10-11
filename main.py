
import os
import json
import time
import threading
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# BITGET DEMAND RADAR V13
# USDT FUTURES | 15M / 1H / 4H / 1D / 1W
# Kisa Telegram mesaji + API 429 korumasi
# ============================================================

BASE = "https://api.bitget.com"
PRODUCT = "USDT-FUTURES"

BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("BOT_TOKEN")
    or ""
).strip()

CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("CHAT_ID")
    or ""
).strip()

# API yukunu azalt
MAX_WORKERS = 1
MAX_CANDIDATES = 25
MAX_ALERTS = 5

MIN_24H_VOLUME = 100000
MIN_SCORE = 55
MIN_RSI = 45
MAX_RSI = 75
MIN_VOL_RATIO = 1.20

MAX_MOVE15 = 8.0
MAX_MOVE1H = 15.0

DAILY_NEAR_PERCENT = 3.0
WEEKLY_NEAR_PERCENT = 6.0

COOLDOWN_HOURS = 4
SL_ATR = 1.5
TIMEOUT = 20
STATE_FILE = "bitget_radar_state.json"

# API istekleri arasinda bekleme
REQUEST_DELAY = 0.40
MAX_RETRIES = 5

EXCLUDED = {
    "AAPL", "TSLA", "NVDA", "AMZN", "META", "MSFT",
    "GOOGL", "GOOG", "NFLX", "COIN", "MSTR", "AMD",
    "INTC", "SPY", "QQQ", "PLTR", "HOOD", "ORCL"
}

http = requests.Session()
http.headers.update({"User-Agent": "BitgetDemandRadar/13.0"})

# Tum API isteklerini siraya koy
api_lock = threading.Lock()
last_api_request = 0.0


# ============================================================
# GENEL YARDIMCILAR
# ============================================================

def log(message):
    print(
        f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC] "
        f"{message}",
        flush=True
    )


def num(value, default=0.0):
    try:
        result = float(value)
        if result == result and abs(result) != float("inf"):
            return result
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
# BITGET API - 429 / BAGLANTI HATASI KORUMASI
# ============================================================

def api_get(path, params=None):
    global last_api_request

    for attempt in range(MAX_RETRIES):
        try:
            with api_lock:
                wait = REQUEST_DELAY - (time.monotonic() - last_api_request)
                if wait > 0:
                    time.sleep(wait)

                response = http.get(
                    BASE + path,
                    params=params,
                    timeout=TIMEOUT
                )
                last_api_request = time.monotonic()

            if response.status_code == 429:
                wait_seconds = min(2 ** attempt, 30)
                log(
                    f"Bitget 429 hiz siniri: {path}. "
                    f"{wait_seconds} sn beklenecek."
                )
                time.sleep(wait_seconds)
                continue

            if response.status_code in (500, 502, 503, 504):
                wait_seconds = min(2 ** attempt, 20)
                log(
                    f"Bitget sunucu hatasi {response.status_code}. "
                    f"{wait_seconds} sn sonra tekrar denenecek."
                )
                time.sleep(wait_seconds)
                continue

            response.raise_for_status()
            result = response.json()

            if result.get("code") != "00000":
                log(
                    f"Bitget API hatasi {path}: "
                    f"{result.get('msg', result)}"
                )
                return None

            return result.get("data")

        except (requests.RequestException, ValueError) as exc:
            wait_seconds = min(2 ** attempt, 20)
            log(
                f"API istegi basarisiz "
                f"({attempt + 1}/{MAX_RETRIES}) {path}: {exc}"
            )

            if attempt < MAX_RETRIES - 1:
                time.sleep(wait_seconds)

    log(f"API istegi tum denemelerde basarisiz: {path}")
    return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        log("Telegram token veya chat ID eksik.")
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

        log(f"Telegram API hatasi: {result}")
        return False

    except requests.RequestException as exc:
        log(f"Telegram gonderim hatasi: {exc}")
        return False


# ============================================================
# COOLDOWN DURUMU
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
        temp = STATE_FILE + ".tmp"

        with open(temp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        os.replace(temp, STATE_FILE)

    except OSError as exc:
        log(f"Durum dosyasi kaydedilemedi: {exc}")


def is_cooling(symbol, direction):
    item = state.get("sent", {}).get(f"{symbol}_{direction}", {})
    timestamp = num(item.get("time")) if isinstance(item, dict) else 0

    return time.time() - timestamp < COOLDOWN_HOURS * 3600


def mark_sent(symbol, direction):
    state.setdefault("sent", {})
    state["sent"][f"{symbol}_{direction}"] = {"time": time.time()}
    save_state()


# ============================================================
# KONTRATLAR VE FIYATLAR
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
    return num(
        ticker.get("usdtVolume"),
        num(ticker.get("quoteVolume"))
    )


def ticker_change(ticker):
    value = num(ticker.get("change24h"))
    return value * 100 if abs(value) <= 1 else value


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
# RSI, ATR, HACIM VE TREND
# ============================================================

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0

    changes = [
        closes[i] - closes[i - 1]
        for i in range(len(closes) - period, len(closes))
    ]

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    gain = average(gains)
    loss = average(losses)

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
# DEMAND / SUPPLY BOLGELERI
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

        is_base = (
            base["close"] <= base["open"]
            or body_ratio <= 0.45
        )

        if not is_base:
            continue

        move = pct(base["close"], future[-1]["close"])

        if move >= 2 and future[-1]["close"] > base["high"]:
            demand = (
                base["low"],
                max(base["open"], base["close"])
            )
            break

        if move <= -2 and future[-1]["close"] < base["low"]:
            supply = (
                min(base["open"], base["close"]),
                base["high"]
            )
            break

    return demand, supply


def assess_demand(price, zone, near_percent):
    if not zone:
        return None

    low, high = zone

    if low <= price <= high:
        status = "ICINDE"
        distance = 0.0

    elif price > high:
        distance = (price - high) / high * 100

        if distance > near_percent:
            return None

        status = "YAKLASIYOR"

    else:
        return None

    return {
        "low": low,
        "high": high,
        "status": status,
        "distance": distance
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
    try:
        price = ticker_price(ticker)
        volume24 = ticker_volume(ticker)
        change24 = ticker_change(ticker)

        if price <= 0 or volume24 < MIN_24H_VOLUME:
            return None

        c15 = get_candles(symbol, "15m")
        c1 = get_candles(symbol, "1H")
        c4 = get_candles(symbol, "4H")
        c1d = get_candles(symbol, "1D")
        c1w = get_candles(symbol, "1W")

        if min(len(c15), len(c1), len(c4)) < 30:
            return None

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
            return None

        demand4, _ = find_zones(c4)
        demand1d, _ = find_zones(c1d)
        demand1w, _ = find_zones(c1w)

        daily = assess_demand(price, demand1d, DAILY_NEAR_PERCENT)
        weekly = assess_demand(price, demand1w, WEEKLY_NEAR_PERCENT)

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

        if daily:
            long_score += 12

        if weekly:
            long_score += 15

        if daily and weekly:
            long_score += 8

        if btc == "LONG":
            long_score += 5
            short_score -= 10
        elif btc == "SHORT":
            short_score += 5
            long_score -= 10

        if long_score >= short_score:
            direction = "LONG"
            score = long_score
        else:
            direction = "SHORT"
            score = short_score

        if score < MIN_SCORE:
            return None

        if btc != "NEUTRAL" and direction != btc:
            return None

        if direction == "LONG":
            if rsi15 > MAX_RSI:
                return None

            if not (daily or weekly or in_zone(price, demand4)):
                return None

        if direction == "SHORT" and rsi15 < 100 - MAX_RSI:
            return None

        if is_cooling(symbol, direction):
            return None

        atr = calculate_atr(c15)

        if atr > 0:
            if direction == "LONG":
                stop = price - SL_ATR * atr
                tp1 = price + 2 * atr
                tp2 = price + 3 * atr
            else:
                stop = price + SL_ATR * atr
                tp1 = price - 2 * atr
                tp2 = price - 3 * atr
        else:
            stop = tp1 = tp2 = 0.0

        return {
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "price": price,
            "volume24": volume24,
            "change24": change24,
            "rsi15": rsi15,
            "rsi1": rsi1,
            "vr15": vr15,
            "btc": btc,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "daily": daily,
            "weekly": weekly
        }

    except Exception as exc:
        log(f"{symbol} analiz hatasi: {exc}")
        return None


# ============================================================
# KISA TELEGRAM MESAJI
# ============================================================

def format_signal(r):
    arrow = "🟢" if r["direction"] == "LONG" else "🔴"

    daily = r.get("daily")
    weekly = r.get("weekly")

    if daily:
        daily_text = (
            f"{daily['low']:.8g} - {daily['high']:.8g}"
            f" | %{daily['distance']:.2f}"
        )
        daily_status = daily["status"]
    else:
        daily_text = "Yok"
        daily_status = "Bulunamadi"

    if weekly:
        weekly_text = (
            f"{weekly['low']:.8g} - {weekly['high']:.8g}"
            f" | %{weekly['distance']:.2f}"
        )
        weekly_status = weekly["status"]
    else:
        weekly_text = "Yok"
        weekly_status = "Bulunamadi"

    return (
        f"{arrow} BITGET DEMAND RADAR\n\n"
        f"{r['symbol']} | {r['direction']} | Puan {r['score']}\n"
        f"Fiyat: {fmt(r['price'])}\n\n"
        f"📍 Gunluk demand: {daily_status}\n"
        f"{daily_text}\n\n"
        f"📍 Haftalik demand: {weekly_status}\n"
        f"{weekly_text}\n\n"
        f"🛑 Stop: {fmt(r['stop'])}\n"
        f"🎯 TP1: {fmt(r['tp1'])}\n"
        f"🎯 TP2: {fmt(r['tp2'])}\n\n"
        f"Hacim x{r['vr15']:.2f} | RSI {r['rsi15']:.0f}\n"
        f"BTC: {r['btc']}\n\n"
        "⚠️ Teknik sinyal; otomatik emir acmaz."
    )


# ============================================================
# TARAMA
# ============================================================

def run_scan():
    log("Bitget taramasi basladi.")

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

    log(f"Kontrat sayisi: {len(symbols)}")
    log(f"Analiz adayi: {len(candidates)}")

    btc = get_btc_direction()
    log(f"BTC filtresi: {btc}")

    results = []

    # Tek worker: ayni anda cok sayida API istegi gonderme.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(analyze_symbol, symbol, ticker, btc): symbol
            for symbol, ticker, _ in candidates
        }

        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception as exc:
                log(f"Analiz sonucu hatasi: {exc}")

    results.sort(key=lambda r: r["score"], reverse=True)

    if not results:
        log("Filtreleri gecen sinyal bulunamadi.")
        return

    sent_count = 0

    for result in results:
        if sent_count >= MAX_ALERTS:
            break

        if send_telegram(format_signal(result)):
            mark_sent(result["symbol"], result["direction"])
            sent_count += 1

            log(
                f"Sinyal gonderildi: {result['symbol']} "
                f"{result['direction']} puan={result['score']}"
            )

        time.sleep(1)

    log(f"Tarama tamamlandi. Gonderilen sinyal: {sent_count}")


def main():
    log("BITGET DEMAND RADAR V13 basladi.")

    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Telegram Secret eksik. "
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID kontrol et."
        )

    run_scan()
    log("Program tamamlandi.")


if __name__ == "__main__":
    main()
