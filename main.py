
import os
import json
import time
import threading
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# BITGET PRE-PUMP + DEMAND RADAR V10
# USDT FUTURES | 15M + 1H + 4H + 1D + 1W
# Telegram alarmi | Otomatik emir acmaz
# ============================================================

BASE = "https://api.bitget.com"
PRODUCT = "USDT-FUTURES"

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()

MAX_WORKERS = 4
MAX_CANDIDATES = 40
MAX_ALERTS = 10
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

SL_ATR = 1.5
DAILY_NEAR_PERCENT = 3.0
WEEKLY_NEAR_PERCENT = 6.0

STATE_FILE = "bitget_radar_state.json"
TIMEOUT = 15

EXCLUDED = {
    "AAPL", "TSLA", "NVDA", "AMZN", "META", "MSFT",
    "GOOGL", "GOOG", "NFLX", "COIN", "MSTR", "AMD",
    "INTC", "SPY", "QQQ", "PLTR", "HOOD", "ORCL"
}

http = requests.Session()
http.headers.update({"User-Agent": "BitgetDemandRadar/10.0"})
lock = threading.Lock()


# ============================================================
# YARDIMCILAR
# ============================================================

def log(message):
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"{message}",
        flush=True
    )


def num(value, default=0.0):
    try:
        value = float(value)
        if value == value and abs(value) != float("inf"):
            return value
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
            log(f"API hatasi {path}: {result.get('msg', result)}")
            return None

        return result.get("data")

    except Exception as exc:
        log(f"API baglanti hatasi {path}: {exc}")
        return None


# ============================================================
# DURUM / COOLDOWN / OI GECMISI
# ============================================================

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
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
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
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
        item = state["oi"].get(symbol, {})
    if isinstance(item, dict):
        return num(item.get("value"))
    return num(item)


def update_oi(values):
    with lock:
        for symbol, value in values.items():
            if value > 0:
                state["oi"][symbol] = {
                    "value": value,
                    "time": time.time()
                }
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

        log(f"Telegram hatasi: {result}")
        return False

    except Exception as exc:
        log(f"Telegram gonderim hatasi: {exc}")
        return False


# ============================================================
# BITGET KONTRATLARI / FIYATLAR
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

    # Son mum acik olabilir. Analizde kullanma.
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

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    gain = avg(gains)
    loss = avg(losses)

    if loss == 0:
        return 100.0 if gain > 0 else 50.0

    rs = gain / loss
    return 100.0 - 100.0 / (1.0 + rs)


def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0

    ranges = []

    for i in range(1, len(candles)):
        c = candles[i]
        previous = candles[i - 1]["close"]

        ranges.append(max(
            c["high"] - c["low"],
            abs(c["high"] - previous),
            abs(c["low"] - previous)
        ))

    return avg(ranges[-period:])


def volume_ratio(candles, period=20):
    if len(candles) < period + 2:
        return 1.0

    baseline = avg([
        c["volume"] for c in candles[-period-1:-1]
    ])

    return (
        candles[-1]["volume"] / baseline
        if baseline > 0 else 1.0
    )


def get_trend(candles):
    if len(candles) < 30:
        return "NEUTRAL"

    closes = [c["close"] for c in candles]
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
# DEMAND / SUPPLY BOLGESI
# ============================================================

def find_zones(candles):
    """
    Basit baz + impuls yaklasimi.
    Demand: baz mumunun dusuk fiyati ile govde ustu.
    Supply: baz govdesi alti ile yuksek fiyat.
    """
    if len(candles) < 30:
        return None, None

    demand = None
    supply = None
    recent = candles[-60:]

    for i in range(2, len(recent) - 3):
        base = recent[i]
        future = recent[i + 1:i + 4]

        if not future:
            continue

        base_range = base["high"] - base["low"]
        if base_range <= 0:
            continue

        body_ratio = (
            abs(base["close"] - base["open"]) / base_range
        )

        is_base = (
            base["close"] <= base["open"]
            or body_ratio <= 0.45
        )

        if not is_base:
            continue

        move = pct(base["close"], future[-1]["close"])

        # Yukari displacement: demand adayi
        if move >= 2.0 and future[-1]["close"] > base["high"]:
            demand = (
                base["low"],
                max(base["open"], base["close"])
            )

        # Asagi displacement: supply adayi
        elif move <= -2.0 and future[-1]["close"] < base["low"]:
            supply = (
                min(base["open"], base["close"]),
                base["high"]
            )

    return demand, supply


def zone_status(price, zone, near_percent):
    if not zone:
        return None

    low, high = zone

    if low <= price <= high:
        return {
            "status": "BOLGE ICINDE",
            "low": low,
            "high": high,
            "distance": 0.0
        }

    if price > high:
        distance = (price - high) / high * 100

        if distance <= near_percent:
            return {
                "status": "YAKLASIYOR",
                "low": low,
                "high": high,
                "distance": distance
            }

    # Bolgenin altina inen fiyat LONG demand adayi sayilmaz.
    return None


def near_zone(price, zone, tolerance=0.015):
    if not zone:
        return False

    low, high = zone
    return low * (1 - tolerance) <= price <= high * (1 + tolerance)


def fmt_price(value):
    if not value:
        return "N/A"
    return f"{value:.10g}"


# ============================================================
# PARA AKISI
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

        value = price * size

        if side == "buy":
            buy_notional += value
        elif side == "sell":
            sell_notional += value

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

        c15 = get_candles(symbol, "15m", 100)
        c1 = get_candles(symbol, "1H", 100)
        c4 = get_candles(symbol, "4H", 100)
        c1d = get_candles(symbol, "1D", 100)
        c1w = get_candles(symbol, "1W", 100)

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

        demand4, supply4 = find_zones(c4)
        demand1d, supply1d = find_zones(c1d)
        demand1w, supply1w = find_zones(c1w)

        daily_demand = zone_status(
            price, demand1d, DAILY_NEAR_PERCENT
        )
        weekly_demand = zone_status(
            price, demand1w, WEEKLY_NEAR_PERCENT
        )

        flow = get_trade_flow(symbol)
        oi = get_open_interest(symbol)
        old_oi = get_previous_oi(symbol)

        oi_change = (
            pct(old_oi, oi)
            if old_oi > 0 and oi > 0 else 0.0
        )

        atr = calculate_atr(c15)

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
            long_score += 6
            short_score += 6

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
            long_score += 8
            long_reasons.append(f"RSI 1H {rsi1:.1f}")
        elif rsi1 < 50:
            short_score += 8
            short_reasons.append(f"RSI 1H {rsi1:.1f}")

        # Trend
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

        # Fiyat yapisi
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

        # Demand / supply
        if near_zone(price, demand4):
            long_score += 8
            long_reasons.append("4H demand icinde/yakin")

        if near_zone(price, supply4):
            short_score += 8
            short_reasons.append("4H supply icinde/yakin")

        # Gunluk ve haftalik demand
        if daily_demand:
            long_score += 10
            long_reasons.append(
                f"Gunluk demand {daily_demand['status']}"
            )

        if weekly_demand:
            long_score += 15
            long_reasons.append(
                f"Haftalik demand {weekly_demand['status']}"
            )

        # Ayni anda gunluk + haftalik demand onceligi
        if daily_demand and weekly_demand:
            long_score += 8
            long_reasons.append("Gunluk + haftalik demand uyumu")

        # Para akisi: API verisi yoksa puan verme.
        if flow["total"] >= MIN_FLOW_NOTIONAL:
            if flow["ratio"] >= MIN_FLOW_RATIO:
                long_score += 12
                long_reasons.append(
                    f"Alim akisi x{flow['ratio']:.2f}"
                )
            elif flow["ratio"] <= 1 / MIN_FLOW_RATIO:
                short_score += 12
                short_reasons.append(
                    f"Satim akisi x{flow['ratio']:.2f}"
                )

        # OI: ilk taramada onceki veri olmayabilir.
        if old_oi > 0 and oi > 0 and oi_change >= MIN_OI_CHANGE:
            if trend1 == "LONG":
                long_score += 8
                long_reasons.append(f"OI artisi %{oi_change:.2f}")
            elif trend1 == "SHORT":
                short_score += 8
                short_reasons.append(f"OI artisi %{oi_change:.2f}")

        # BTC filtresi
        if btc == "LONG":
            long_score += 5
            short_score -= 10
            long_reasons.append("BTC 1H+4H pozitif")
        elif btc == "SHORT":
            short_score += 5
            long_score -= 10
            short_reasons.append("BTC 1H+4H negatif")

        # Asiri hizli hareket eden coinleri kovalamama
        if abs(move15) > MAX_15M_MOVE or abs(move1) > MAX_1H_MOVE:
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

        # BTC ters yon filtresi
        if btc != "NEUTRAL" and direction != btc:
            return None

        if direction == "LONG" and rsi15 > MAX_RSI:
            return None

        if direction == "SHORT" and rsi15 < 100 - MAX_RSI:
            return None

        # Demand odakli radar: demand bolgesinde LONG tercih et.
        if direction == "LONG" and not (
            daily_demand or weekly_demand or near_zone(price, demand4)
        ):
            return None

        if is_cooling(symbol, direction):
            return None

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
            "flow_ratio": flow["ratio"],
            "flow_total": flow["total"],
            "oi": oi,
            "oi_change": oi_change,
            "btc": btc,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "daily": daily_demand,
            "weekly": weekly_demand,
            "reasons": reasons
        }

    except Exception as exc:
        log(f"{symbol} analiz hatasi: {exc}")
        return None


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def format_zone(label, zone):
    if not zone:
        return f"{label}: uygun demand bulunamadi"

    return (
        f"{label}: {zone['status']}\n"
        f"Alt: {fmt_price(zone['low'])}\n"
        f"Ust: {fmt_price(zone['high'])}\n"
        f"Uzaklik: %{zone['distance']:.2f}"
    )


def format_signal(r):
    arrow = "🟢" if r["direction"] == "LONG" else "🔴"

    reasons = "\n".join(
        f"• {reason}" for reason in r["reasons"][:8]
    )

    return (
        f"{arrow} BITGET DEMAND RADAR V10\n\n"
        f"Coin: {r['symbol']}\n"
        f"Yon: {r['direction']}\n"
        f"Puan: {r['score']}\n"
        f"Fiyat: {fmt_price(r['price'])}\n"
        f"24S hacim: {r['volume24']:.0f} USDT\n"
        f"24S degisim: %{r['change24']:.2f}\n"
        f"RSI 15M: {r['rsi15']:.1f}\n"
        f"RSI 1H: {r['rsi1']:.1f}\n"
        f"15M hacim orani: x{r['vr15']:.2f}\n"
        f"Para akisi orani: x{r['flow_ratio']:.2f}\n"
        f"OI degisimi: %{r['oi_change']:.2f}\n"
        f"BTC yonu: {r['btc']}\n\n"
        f"{format_zone('GUNLUK DEMAND', r['daily'])}\n\n"
        f"{format_zone('HAFTALIK DEMAND', r['weekly'])}\n\n"
        f"Stop referansi: {fmt_price(r['stop'])}\n"
        f"TP1 referansi: {fmt_price(r['tp1'])}\n"
        f"TP2 referansi: {fmt_price(r['tp2'])}\n\n"
        f"Nedenler:\n{reasons}\n\n"
        "Uyari: Teknik tahmin; otomatik emir acmaz. "
        "Demand bolgeleri gecmis mumlardan hesaplanir."
    )


# ============================================================
# ANA TARAMA - GITHUB ACTIONS ICIN TEK TUR
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

        volume = ticker_volume(ticker)
        price = ticker_price(ticker)

        if price > 0 and volume >= MIN_24H_VOLUME:
            candidates.append((symbol, ticker, volume))

    candidates.sort(key=lambda item: item[2], reverse=True)
    candidates = candidates[:MAX_CANDIDATES]

    log(f"Analiz edilecek aday: {len(candidates)}")

    btc = get_btc_direction()
    log(f"BTC yonu: {btc}")

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

    update_oi(oi_updates)

    results.sort(key=lambda item: item["score"], reverse=True)
    results = results[:MAX_ALERTS]

    if not results:
        log("Filtreleri gecen sinyal yok.")
        return

    sent_count = 0

    for result in results:
        if send_telegram(format_signal(result)):
            mark_sent(result["symbol"], result["direction"])
            sent_count += 1
            log(
                f"Gonderildi: {result['symbol']} "
                f"{result['direction']} puan={result['score']}"
            )
        time.sleep(1)

    log(f"Tarama bitti. Telegram'a gonderilen: {sent_count}")


def main():
    log("BITGET DEMAND RADAR V10 baslatildi.")

    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("BOT_TOKEN veya CHAT_ID GitHub Secrets'ta eksik.")

    run_scan()
    log("Tarama tamamlandi.")


if __name__ == "__main__":
    main()
