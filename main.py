
import os
import json
import time
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# BITGET DEMAND RADAR V11
# USDT FUTURES | 15M + 1H + 4H + 1D + 1W
# Demand, RSI, hacim, trend, BTC filtresi, Telegram
# Tek tarama: GitHub Actions ile uyumlu
# ============================================================

BASE = "https://api.bitget.com"
PRODUCT = "USDT-FUTURES"

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()

MAX_WORKERS = 4
MAX_CANDIDATES = 40
MAX_ALERTS = 10

MIN_24H_VOLUME = 100000
MIN_SCORE = 55

MIN_RSI = 45.0
MAX_RSI = 75.0
MIN_VOL_RATIO = 1.20

MAX_MOVE15 = 8.0
MAX_MOVE1H = 15.0

DAILY_NEAR_PERCENT = 3.0
WEEKLY_NEAR_PERCENT = 6.0

COOLDOWN_HOURS = 4
SL_ATR = 1.5
TIMEOUT = 15
STATE_FILE = "bitget_radar_state.json"

EXCLUDED = {
    "AAPL", "TSLA", "NVDA", "AMZN", "META", "MSFT",
    "GOOGL", "GOOG", "NFLX", "COIN", "MSTR", "AMD",
    "INTC", "SPY", "QQQ", "PLTR", "HOOD", "ORCL"
}

session = requests.Session()
session.headers.update({"User-Agent": "BitgetDemandRadar/11.0"})


# ============================================================
# YARDIMCILAR
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


def percent_change(old, new):
    return (new - old) / old * 100.0 if old > 0 else 0.0


def fmt_price(value):
    if value is None:
        return "N/A"
    return f"{value:.10g}"


def api_get(path, params=None):
    try:
        response = session.get(
            BASE + path,
            params=params,
            timeout=TIMEOUT
        )
        response.raise_for_status()
        result = response.json()

        if result.get("code") != "00000":
            log(f"API hatasi {path}: {result.get('msg', result)}")
            return None

        return result.get("data")

    except Exception as exc:
        log(f"API baglanti hatasi {path}: {exc}")
        return None


# ============================================================
# DURUM DOSYASI / COOLDOWN
# ============================================================

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass

    return {"sent": {}}


state = load_state()


def save_state():
    try:
        temp = STATE_FILE + ".tmp"
        with open(temp, "w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)
        os.replace(temp, STATE_FILE)
    except OSError as exc:
        log(f"Durum dosyasi kaydedilemedi: {exc}")


def is_cooling(symbol, direction):
    item = state.get("sent", {}).get(f"{symbol}_{direction}", {})
    timestamp = num(item.get("time")) if isinstance(item, dict) else 0.0

    return time.time() - timestamp < COOLDOWN_HOURS * 3600


def mark_sent(symbol, direction):
    state.setdefault("sent", {})
    state["sent"][f"{symbol}_{direction}"] = {"time": time.time()}
    save_state()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        log("BOT_TOKEN veya CHAT_ID eksik.")
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

        log(f"Telegram yaniti: {result}")
        return False

    except Exception as exc:
        log(f"Telegram gonderim hatasi: {exc}")
        return False


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

    candles.sort(key=lambda candle: candle["time"])

    # Son mum tamamlanmamış olabilir.
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

    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]

    avg_gain = average(gains)
    avg_loss = average(losses)

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0

    ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous_close = candles[i - 1]["close"]

        ranges.append(max(
            current["high"] - current["low"],
            abs(current["high"] - previous_close),
            abs(current["low"] - previous_close)
        ))

    return average(ranges[-period:])


def volume_ratio(candles, period=20):
    if len(candles) < period + 2:
        return 1.0

    baseline = average([
        candle["volume"]
        for candle in candles[-period-1:-1]
    ])

    current_volume = candles[-1]["volume"]

    return current_volume / baseline if baseline > 0 else 1.0


def get_trend(candles):
    if len(candles) < 30:
        return "NEUTRAL"

    closes = [candle["close"] for candle in candles]
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

    recent_high = max(c["high"] for c in recent)
    recent_low = min(c["low"] for c in recent)
    previous_high = max(c["high"] for c in previous)
    previous_low = min(c["low"] for c in previous)

    if recent_high > previous_high and recent_low > previous_low:
        return "LONG"

    if recent_high < previous_high and recent_low < previous_low:
        return "SHORT"

    return "NEUTRAL"


# ============================================================
# DEMAND / SUPPLY
# ============================================================

def find_zones(candles):
    """
    Basit baz + impuls kuraliyla yaklasik bolgeler belirler.
    Demand: impuls yukari gitmeden onceki baz.
    Supply: impuls asagi gitmeden onceki baz.
    """
    if len(candles) < 30:
        return None, None

    demand = None
    supply = None
    recent = candles[-60:]

    # En son olusan uygun bolgeyi bul.
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

        move = percent_change(base["close"], future[-1]["close"])

        if move >= 2.0 and future[-1]["close"] > base["high"]:
            demand = (
                base["low"],
                max(base["open"], base["close"])
            )
            break

        if move <= -2.0 and future[-1]["close"] < base["low"]:
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
        status = "BOLGE ICINDE"
        distance = 0.0

    elif price > high:
        distance = (price - high) / high * 100.0

        if distance > near_percent:
            return None

        status = "YAKLASIYOR"

    else:
        # Fiyat bolgenin altinda: kirilim riski.
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
# BTC FILTRESI
# ============================================================

def get_btc_direction():
    c1 = get_candles("BTCUSDT", "1H", 80)
    c4 = get_candles("BTCUSDT", "4H", 80)

    if len(c1) < 30 or len(c4) < 30:
        return "NEUTRAL"

    trend1 = get_trend(c1)
    trend4 = get_trend(c4)

    if trend1 == "LONG" and trend4 == "LONG":
        return "LONG"

    if trend1 == "SHORT" and trend4 == "SHORT":
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

        move15 = percent_change(closes15[-2], closes15[-1])
        move1 = percent_change(closes1[-2], closes1[-1])

        if abs(move15) > MAX_MOVE15 or abs(move1) > MAX_MOVE1H:
            return None

        demand4, supply4 = find_zones(c4)
        demand1d, _ = find_zones(c1d)
        demand1w, _ = find_zones(c1w)

        daily = assess_demand(price, demand1d, DAILY_NEAR_PERCENT)
        weekly = assess_demand(price, demand1w, WEEKLY_NEAR_PERCENT)

        long_score = 0
        short_score = 0
        long_reasons = []
        short_reasons = []

        # Hacim
        if vr15 >= MIN_VOL_RATIO:
            long_score += 10
            short_score += 10
            long_reasons.append(f"15M hacim x{vr15:.2f}")
            short_reasons.append(f"15M hacim x{vr15:.2f}")

        if vr1 >= 1.10:
            long_score += 5
            short_score += 5

        # RSI
        if MIN_RSI <= rsi15 <= MAX_RSI:
            long_score += 4
            short_score += 4

        if rsi15 > 50:
            long_score += 5
            long_reasons.append(f"RSI 15M {rsi15:.1f}")
        elif rsi15 < 50:
            short_score += 5
            short_reasons.append(f"RSI 15M {rsi15:.1f}")

        if rsi1 > 50:
            long_score += 7
            long_reasons.append(f"RSI 1H {rsi1:.1f}")
        elif rsi1 < 50:
            short_score += 7
            short_reasons.append(f"RSI 1H {rsi1:.1f}")

        # Trend
        if trend1 == "LONG":
            long_score += 10
            long_reasons.append("1H trend yukari")
        elif trend1 == "SHORT":
            short_score += 10
            short_reasons.append("1H trend asagi")

        if trend4 == "LONG":
            long_score += 10
            long_reasons.append("4H trend yukari")
        elif trend4 == "SHORT":
            short_score += 10
            short_reasons.append("4H trend asagi")

        # Fiyat yapisi
        if structure1 == "LONG":
            long_score += 5
            long_reasons.append("1H yukselen yapi")
        elif structure1 == "SHORT":
            short_score += 5
            short_reasons.append("1H dusen yapi")

        if structure4 == "LONG":
            long_score += 5
            long_reasons.append("4H yukselen yapi")
        elif structure4 == "SHORT":
            short_score += 5
            short_reasons.append("4H dusen yapi")

        # Demand
        if in_zone(price, demand4):
            long_score += 8
            long_reasons.append("4H demand icinde")

        if daily:
            long_score += 12
            long_reasons.append(f"Gunluk demand: {daily['status']}")

        if weekly:
            long_score += 15
            long_reasons.append(f"Haftalik demand: {weekly['status']}")

        if daily and weekly:
            long_score += 8
            long_reasons.append("Gunluk + haftalik demand uyumu")

        # BTC yonu
        if btc == "LONG":
            long_score += 5
            short_score -= 10
            long_reasons.append("BTC trend pozitif")
        elif btc == "SHORT":
            short_score += 5
            long_score -= 10
            short_reasons.append("BTC trend negatif")

        if long_score >= short_score:
            direction = "LONG"
            score = long_score
            reasons = long_reasons
        else:
            direction = "SHORT"
            score = short_score
            reasons = short_reasons

        if score < MIN_SCORE:
            return None

        if btc != "NEUTRAL" and direction != btc:
            return None

        if direction == "LONG":
            if rsi15 > MAX_RSI:
                return None

            # LONG adayinda en az bir demand bolgesi gerekli.
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
                tp1 = price + 2.0 * atr
                tp2 = price + 3.0 * atr
            else:
                stop = price + SL_ATR * atr
                tp1 = price - 2.0 * atr
                tp2 = price - 3.0 * atr
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
            "vr1": vr1,
            "btc": btc,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "daily": daily,
            "weekly": weekly,
            "reasons": reasons
        }

    except Exception as exc:
        log(f"{symbol} analiz hatasi: {exc}")
        return None


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def format_zone(title, zone):
    if not zone:
        return f"{title}: uygun bolge bulunamadi"

    return (
        f"{title}: {zone['status']}\n"
        f"Alt: {fmt_price(zone['low'])}\n"
        f"Ust: {fmt_price(zone['high'])}\n"
        f"Uzaklik: %{zone['distance']:.2f}"
    )


def format_signal(result):
    arrow = "🟢" if result["direction"] == "LONG" else "🔴"
    reasons = "\n".join(
        f"• {reason}" for reason in result["reasons"][:8]
    )

    return (
        f"{arrow} BITGET DEMAND RADAR V11\n\n"
        f"Coin: {result['symbol']}\n"
        f"Yon: {result['direction']}\n"
        f"Puan: {result['score']}\n"
        f"Fiyat: {fmt_price(result['price'])}\n"
        f"24S hacim: {result['volume24']:.0f} USDT\n"
        f"24S degisim: %{result['change24']:.2f}\n"
        f"RSI 15M: {result['rsi15']:.1f}\n"
        f"RSI 1H: {result['rsi1']:.1f}\n"
        f"15M hacim: x{result['vr15']:.2f}\n"
        f"BTC yonu: {result['btc']}\n\n"
        f"{format_zone('GUNLUK DEMAND', result['daily'])}\n\n"
        f"{format_zone('HAFTALIK DEMAND', result['weekly'])}\n\n"
        f"Stop referansi: {fmt_price(result['stop'])}\n"
        f"TP1 referansi: {fmt_price(result['tp1'])}\n"
        f"TP2 referansi: {fmt_price(result['tp2'])}\n\n"
        f"Nedenler:\n{reasons}\n\n"
        "Uyari: Bolgeler gecmis mumlardan hesaplanan teknik tahminlerdir. "
        "Otomatik emir acilmaz."
    )


# ============================================================
# TEK TARAMA
# ============================================================

def run_scan():
    log("Bitget demand taramasi basladi.")

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

    candidates.sort(key=lambda item: item[2], reverse=True)
    candidates = candidates[:MAX_CANDIDATES]

    log(f"Toplam kontrat: {len(symbols)}")
    log(f"Analiz adayi: {len(candidates)}")

    btc = get_btc_direction()
    log(f"BTC filtresi: {btc}")

    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(analyze_symbol, symbol, ticker, btc): symbol
            for symbol, ticker, _ in candidates
        }

        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception as exc:
                log(f"Analiz sonucu hatasi: {exc}")

    results.sort(key=lambda item: item["score"], reverse=True)

    if not results:
        log("Filtreleri gecen sinyal bulunamadi.")
        return

    results = results[:MAX_ALERTS]
    sent = 0

    for result in results:
        if send_telegram(format_signal(result)):
            mark_sent(result["symbol"], result["direction"])
            sent += 1
            log(
                f"Sinyal gonderildi: {result['symbol']} "
                f"{result['direction']} puan={result['score']}"
            )

        time.sleep(1)

    log(f"Tarama tamamlandi. Gonderilen sinyal: {sent}")


def main():
    log("BITGET DEMAND RADAR V11 basladi.")

    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "BOT_TOKEN veya CHAT_ID GitHub Secrets'ta eksik."
        )

    run_scan()
    log("Program normal sekilde sona erdi.")


if __name__ == "__main__":
    main()
