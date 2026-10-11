
import os
import json
import time
import threading
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# BITGET PRE-PUMP RADAR V9
# USDT FUTURES | 15M + 1H + 4H
# OI + PARA AKISI + RSI + HACIM + SUPPLY/DEMAND
# Telegram alarmi uretir; otomatik emir acmaz.
# ============================================================

BASE = "https://api.bitget.com"
PRODUCT = "USDT-FUTURES"

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()

MAX_WORKERS = 5
MAX_CANDIDATES = 30
MAX_ALERTS = 5
SCAN_INTERVAL = 180
COOLDOWN_HOURS = 4

MIN_SCORE = 65
MIN_24H_VOLUME = 100000
MIN_OI_CHANGE = 0.5
MIN_FLOW_NOTIONAL = 10000
MIN_FLOW_RATIO = 1.20
MIN_VOL_RATIO = 1.20

MAX_15M_MOVE = 8.0
MAX_1H_MOVE = 15.0
MIN_RSI = 45.0
MAX_RSI = 75.0

STATE_FILE = "bitget_radar_state.json"
TIMEOUT = 15

EXCLUDED = {
    "AAPL", "TSLA", "NVDA", "AMZN", "META", "MSFT",
    "GOOGL", "GOOG", "NFLX", "COIN", "MSTR", "AMD",
    "INTC", "SPY", "QQQ", "PLTR", "HOOD", "ORCL"
}

http = requests.Session()
http.headers.update({"User-Agent": "BitgetPrePumpRadar/9.0"})
lock = threading.Lock()


# ============================================================
# GENEL YARDIMCILAR
# ============================================================

def log(message):
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
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


def avg(values):
    return sum(values) / len(values) if values else 0.0


def pct(old, new):
    return (new - old) / old * 100.0 if old > 0 else 0.0


def api_get(path, params=None):
    try:
        response = http.get(
            BASE + path,
            params=params,
            timeout=TIMEOUT
        )
        response.raise_for_status()
        result = response.json()

        if result.get("code") != "00000":
            log(f"API hata {path}: {result.get('msg', result)}")
            return None

        return result.get("data")

    except Exception as exc:
        log(f"API baglanti hatasi {path}: {exc}")
        return None


# ============================================================
# KALICI DURUM / COOLDOWN
# ============================================================

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        data = {}

    if not isinstance(data, dict):
        data = {}

    data.setdefault("sent", {})
    data.setdefault("oi", {})
    return data


state = load_state()


def save_state():
    try:
        with lock:
            temp = STATE_FILE + ".tmp"
            with open(temp, "w", encoding="utf-8") as file:
                json.dump(state, file, ensure_ascii=False, indent=2)
            os.replace(temp, STATE_FILE)
    except OSError as exc:
        log(f"State kaydetme hatasi: {exc}")


def is_cooling(symbol, direction):
    key = f"{symbol}_{direction}"

    with lock:
        item = state["sent"].get(key, {})

    timestamp = num(
        item.get("time") if isinstance(item, dict) else item
    )

    return time.time() - timestamp < COOLDOWN_HOURS * 3600


def mark_sent(symbol, direction):
    with lock:
        state["sent"][f"{symbol}_{direction}"] = {
            "time": time.time()
        }

    save_state()


def get_previous_oi(symbol):
    with lock:
        return num(state["oi"].get(symbol))


def update_oi(values):
    with lock:
        for symbol, value in values.items():
            if value > 0:
                state["oi"][symbol] = value

    save_state()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        log("BOT_TOKEN veya CHAT_ID ayarlanmamis.")
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": message,
                "disable_web_page_preview": True
            },
            timeout=TIMEOUT
        )

        result = response.json()

        if response.ok and result.get("ok"):
            return True

        log(f"Telegram yaniti: {result}")
        return False

    except Exception as exc:
        log(f"Telegram hatasi: {exc}")
        return False


# ============================================================
# BITGET KONTRATLAR VE TICKER
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

    return symbols


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

    # Son mumun kapanmamış olma ihtimaline karşı çıkar.
    if len(candles) > 1:
        candles = candles[:-1]

    return candles[-limit:]


# ============================================================
# TEKNIK GOSTERGELER
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

    avg_gain = avg(gains)
    avg_loss = avg(losses)

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0

    ranges = []

    for i in range(1, len(candles)):
        candle = candles[i]
        previous_close = candles[i - 1]["close"]

        ranges.append(max(
            candle["high"] - candle["low"],
            abs(candle["high"] - previous_close),
            abs(candle["low"] - previous_close)
        ))

    return avg(ranges[-period:])


def volume_ratio(candles, period=20):
    if len(candles) < period + 2:
        return 1.0

    baseline = avg([
        candle["volume"]
        for candle in candles[-period - 1:-1]
    ])

    current = candles[-1]["volume"]

    return current / baseline if baseline > 0 else 1.0


def get_trend(candles):
    if len(candles) < 30:
        return "NEUTRAL"

    closes = [candle["close"] for candle in candles]

    fast = avg(closes[-9:])
    slow = avg(closes[-26:])

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
# YAKLASIK SUPPLY / DEMAND BOLGELERI
# ============================================================

def find_zones(candles):
    if len(candles) < 30:
        return None, None

    demand = None
    supply = None
    recent = candles[-60:]

    for i in range(2, len(recent) - 3):
        candle = recent[i]
        future = recent[i + 1:i + 4]

        move = pct(candle["close"], future[-1]["close"])

        if move >= 2.0:
            demand = (
                candle["low"],
                max(candle["open"], candle["close"])
            )

        elif move <= -2.0:
            supply = (
                min(candle["open"], candle["close"]),
                candle["high"]
            )

    return demand, supply


def near_zone(price, zone, tolerance=0.015):
    if not zone:
        return False

    low, high = zone

    return (
        low * (1 - tolerance)
        <= price
        <= high * (1 + tolerance)
    )


# ============================================================
# ALIM / SATIM AKISI
# ============================================================

def get_trade_flow(symbol):
    data = api_get(
        "/api/v2/mix/market/fills",
        {
            "symbol": symbol,
            "productType": PRODUCT,
            "limit": "100"
        }
    )

    buy_notional = 0.0
    sell_notional = 0.0

    if not isinstance(data, list):
        return {
            "buy": 0.0,
            "sell": 0.0,
            "total": 0.0,
            "ratio": 1.0
        }

    for trade in data:
        price = num(trade.get("price"))
        size = num(trade.get("size"))
        side = str(trade.get("side", "")).lower()

        if price <= 0 or size <= 0:
            continue

        notional = price * size

        if side == "buy":
            buy_notional += notional
        elif side == "sell":
            sell_notional += notional

    ratio = (
        buy_notional / sell_notional
        if sell_notional > 0
        else (99.0 if buy_notional > 0 else 1.0)
    )

    return {
        "buy": buy_notional,
        "sell": sell_notional,
        "total": buy_notional + sell_notional,
        "ratio": ratio
    }


# ============================================================
# OPEN INTEREST
# ============================================================

def get_open_interest(symbol):
    data = api_get(
        "/api/v2/mix/market/open-interest",
        {
            "symbol": symbol,
            "productType": PRODUCT
        }
    )

    if not isinstance(data, dict):
        return 0.0

    items = data.get("openInterestList", [])

    if not isinstance(items, list) or not items:
        return 0.0

    item = items[0]

    return num(item.get("size"), num(item.get("openInterest")))


# ============================================================
# BTC YON FILTRESI
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

def analyze_symbol(symbol, ticker, btc_direction):
    try:
        price = ticker_price(ticker)
        volume24 = ticker_volume(ticker)
        change24 = ticker_change(ticker)

        if price <= 0 or volume24 < MIN_24H_VOLUME:
            return None

        c15 = get_candles(symbol, "15m", 100)
        c1 = get_candles(symbol, "1H", 100)
        c4 = get_candles(symbol, "4H", 100)

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

        demand, supply = find_zones(c4)

        flow = get_trade_flow(symbol)
        oi = get_open_interest(symbol)
        old_oi = get_previous_oi(symbol)

        oi_change = (
            pct(old_oi, oi)
            if old_oi > 0 and oi > 0
            else 0.0
        )

        atr_value = calculate_atr(c15)

        long_score = 0
        short_score = 0
        long_reasons = []
        short_reasons = []

        # HACIM
        if vr15 >= MIN_VOL_RATIO:
            long_score += 10
            short_score += 10
            long_reasons.append(f"15M hacim x{vr15:.2f}")
            short_reasons.append(f"15M hacim x{vr15:.2f}")

        if vr1 >= 1.10:
            long_score += 6
            short_score += 6

        # RSI
        if MIN_RSI <= rsi15 <= MAX_RSI:
            long_score += 4
            short_score += 4

        if rsi15 > 50:
            long_score += 5
            long_reasons.append(f"RSI15 {rsi15:.1f}")
        elif rsi15 < 50:
            short_score += 5
            short_reasons.append(f"RSI15 {rsi15:.1f}")

        if rsi1 > 50:
            long_score += 8
            long_reasons.append(f"RSI1H {rsi1:.1f}")
        elif rsi1 < 50:
            short_score += 8
            short_reasons.append(f"RSI1H {rsi1:.1f}")

        # TREND
        if trend1 == "LONG":
            long_score += 10
            long_reasons.append("1H trend yukari")
        elif trend1 == "SHORT":
            short_score += 10
            short_reasons.append("1H trend asagi")

        if trend4 == "LONG":
            long_score += 12
            long_reasons.append("4H trend yukari")
        elif trend4 == "SHORT":
            short_score += 12
            short_reasons.append("4H trend asagi")

        # FIYAT YAPISI
        if structure1 == "LONG":
            long_score += 6
            long_reasons.append("1H yapi pozitif")
        elif structure1 == "SHORT":
            short_score += 6
            short_reasons.append("1H yapi negatif")

        if structure4 == "LONG":
            long_score += 8
            long_reasons.append("4H yapi pozitif")
        elif structure4 == "SHORT":
            short_score += 8
            short_reasons.append("4H yapi negatif")

        # PARA AKISI
        if flow["total"] >= MIN_FLOW_NOTIONAL:
            if flow["ratio"] >= MIN_FLOW_RATIO:
                long_score += 12
                long_reasons.append(
                    f"Alim akisi x{flow['ratio']:.2f}"
                )

            elif flow["ratio"] <= 1 / MIN_FLOW_RATIO:
                short_score += 12
                short_reasons.append(
                    f"Satim akisi x{1 / flow['ratio']:.2f}"
                )

        # OI ARTISI YON TEK BASINA BELIRLEMEZ.
        # Trendle ayni yone gittiginde ek puan verilir.
        if old_oi > 0 and oi > 0 and oi_change >= MIN_OI_CHANGE:
            if trend1 == "LONG":
                long_score += 8
                long_reasons.append(f"OI +%{oi_change:.2f}")
            elif trend1 == "SHORT":
                short_score += 8
                short_reasons.append(f"OI +%{oi_change:.2f}")

        # SUPPLY / DEMAND
        if near_zone(price, demand):
            long_score += 8
            long_reasons.append("Demand bolgesine yakin")

        if near_zone(price, supply):
            short_score += 8
            short_reasons.append("Supply bolgesine yakin")

        # BTC FILTRESI
        if btc_direction == "LONG":
            long_score += 5
            short_score -= 10
            long_reasons.append("BTC trend pozitif")

        elif btc_direction == "SHORT":
            short_score += 5
            long_score -= 10
            short_reasons.append("BTC trend negatif")

        # Asiri hizli hareket etmis coinleri kovalamama filtresi.
        if abs(move15) > MAX_MOVE15 or abs(move1) > MAX_MOVE1H:
            return None

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

        # BTC ters yon filtresi.
        if btc_direction != "NEUTRAL" and direction != btc_direction:
            return None

        # RSI asiri bolgelerdeyse sinyali ele.
        if direction == "LONG" and rsi15 > MAX_RSI:
            return None

        if direction == "SHORT" and rsi15 < 100 - MAX_RSI:
            return None

        if is_cooling(symbol, direction):
            return None

        # ATR tabanli tahmini seviyeler.
        if atr_value > 0:
            if direction == "LONG":
                stop = price - SL_ATR * atr_value
                tp1 = price + 2.0 * atr_value
                tp2 = price + 3.0 * atr_value
            else:
                stop = price + SL_ATR * atr_value
                tp1 = price - 2.0 * atr_value
                tp2 = price - 3.0 * atr_value
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
            "flow_ratio": flow["ratio"],
            "flow_total": flow["total"],
            "oi": oi,
            "oi_change": oi_change,
            "btc": btc_direction,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "reasons": reasons
        }

    except Exception as exc:
        log(f"{symbol} analiz hatasi: {exc}")
        return None


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def format_signal(result):
    arrow = "🟢" if result["direction"] == "LONG" else "🔴"

    reasons = "\n".join(
        f"• {reason}" for reason in result["reasons"][:6]
    )

    stop_text = f"{result['stop']:.8g}" if result["stop"] else "N/A"
    tp1_text = f"{result['tp1']:.8g}" if result["tp1"] else "N/A"
    tp2_text = f"{result['tp2']:.8g}" if result["tp2"] else "N/A"

    return (
        f"{arrow} BITGET PRE-PUMP RADAR\n\n"
        f"Coin: {result['symbol']}\n"
        f"Yon: {result['direction']}\n"
        f"Puan: {result['score']}\n"
        f"Fiyat: {result['price']:.8g}\n"
        f"24S degisim: %{result['change24']:.2f}\n"
        f"RSI 15M: {result['rsi15']:.1f}\n"
        f"RSI 1H: {result['rsi1']:.1f}\n"
        f"Hacim 15M: x{result['vr15']:.2f}\n"
        f"Para akisi: x{result['flow_ratio']:.2f}\n"
        f"OI degisimi: %{result['oi_change']:.2f}\n"
        f"BTC yonu: {result['btc']}\n\n"
        f"Stop referansi: {stop_text}\n"
        f"TP1 referansi: {tp1_text}\n"
        f"TP2 referansi: {tp2_text}\n\n"
        f"Nedenler:\n{reasons}\n\n"
        f"Not: Otomatik emir degildir. "
        f"Seviyeler ATR tabanli tahmindir."
    )


# ============================================================
# ANA TARAMA
# ============================================================

def run_scan():
    log("Bitget taramasi basladi.")

    all_tickers = get_tickers()
    if not all_tickers:
        log("Ticker verisi alinmadi.")
        return

    symbols = get_contracts()
    if not symbols:
        log("Kontrat listesi alinmadi.")
        return

    # En yuksek 24 saatlik hacimli adaylari sec.
    candidates = []

    for symbol in symbols:
        ticker = all_tickers.get(symbol)
        if not ticker:
            continue

        volume = ticker_volume(ticker)
        price = ticker_price(ticker)

        if price > 0 and volume >= MIN_24H_VOLUME:
            candidates.append((symbol, ticker, volume))

    candidates.sort(key=lambda x: x[2], reverse=True)
    candidates = candidates[:MAX_CANDIDATES]

    log(f"Aday sayisi: {len(candidates)}")

    btc = get_btc_direction()
    log(f"BTC yon filtresi: {btc}")

    results = []
    oi_updates = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(analyze_symbol, symbol, ticker, btc): symbol
            for symbol, ticker, _ in candidates
        }

        for future in as_completed(futures):
            symbol = futures[future]

            try:
                result = future.result()

                if result:
                    results.append(result)
                    if result["oi"] > 0:
                        oi_updates[symbol] = result["oi"]

            except Exception as exc:
                log(f"{symbol} sonuc hatasi: {exc}")

    # OI onceki degerlerini tarama sonunda guncelle.
    update_oi(oi_updates)

    results.sort(key=lambda x: x["score"], reverse=True)
    results = results[:MAX_ALERTS]

    if not results:
        log("Filtreleri gecen sinyal yok.")
        return

    for result in results:
        message = format_signal(result)

        # Sadece Telegram basarili olursa cooldown baslat.
        if send_telegram(message):
            mark_sent(result["symbol"], result["direction"])
            log(
                f"Telegram sinyali: {result['symbol']} "
                f"{result['direction']} puan={result['score']}"
            )
        else:
            log(f"Telegram gonderilemedi: {result['symbol']}")

    log(f"Tarama bitti. Sinyal sayisi: {len(results)}")


def main():
    log("BITGET PRE-PUMP RADAR V9 baslatildi.")

    if not BOT_TOKEN or not CHAT_ID:
        log("UYARI: BOT_TOKEN ve CHAT_ID ortam degiskenleri gerekli.")

    while True:
        started = time.time()

        try:
            run_scan()
        except KeyboardInterrupt:
            log("Radar durduruldu.")
            break
        except Exception as exc:
            log(f"Ana tarama hatasi: {exc}")

        elapsed = time.time() - started
        sleep_time = max(5, SCAN_INTERVAL - elapsed)

        log(f"Sonraki taramaya {int(sleep_time)} saniye.")
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
