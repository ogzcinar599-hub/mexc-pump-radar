import os
import json
import time
import math
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# MEXC PUMP RADAR
#
# 4H  = DIP + DÖNÜŞ ANA FİLTRESİ
# 1H  = TREND TEYİDİ
# 15M = MOMENTUM TEYİDİ
#
# Amaç:
# Zaten pump olmuş coinleri değil,
# 4H dipten yeni dönmeye başlayan güçlü adayları bulmak.
# ============================================================

BASE = "https://api.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============================================================
# AYARLAR
# ============================================================

MIN_SCORE = 88

MIN_24H_VOLUME = 500000

# 24H değişim:
# Çok düşmüş coin istemiyoruz,
# ama zaten aşırı pump yapmış coinleri de istemiyoruz.
MIN_24H_CHANGE = -12
MAX_24H_CHANGE = 15

MAX_SIGNALS_PER_SCAN = 3

SCAN_INTERVAL_MINUTES = 5

DUPLICATE_HOURS = 6

# TP / STOP
TP1_PCT = 1.8
TP2_PCT = 3.5
TP3_PCT = 5.5
STOP_PCT = 2.2

# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

# ============================================================
# DOSYA
# ============================================================

SENT_FILE = "sent_signals.json"


def load_sent():
    try:
        if os.path.exists(SENT_FILE):
            with open(SENT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass

    return {}


def save_sent(data):
    try:
        with open(SENT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):

    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secret eksik.")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        r = session.post(
            url,
            json=payload,
            timeout=20
        )

        print("Telegram:", r.status_code)

        if r.status_code == 200:
            return True

        print(r.text)

    except Exception as e:
        print("Telegram error:", e)

    return False


# ============================================================
# MEXC
# ============================================================

def get_json(url, params=None):

    try:
        r = session.get(
            url,
            params=params,
            timeout=15
        )

        if r.status_code != 200:
            return None

        return r.json()

    except Exception:
        return None


# ============================================================
# SYMBOLLER
# ============================================================

def get_usdt_symbols():

    data = get_json(
        f"{BASE}/api/v3/exchangeInfo"
    )

    if not data:
        return []

    symbols = []

    for s in data.get("symbols", []):

        symbol = s.get("symbol", "")
        status = s.get("status", "")

        if not symbol.endswith("USDT"):
            continue

        if status and status != "1" and status != "TRADING":
            continue

        # Stablecoin / gereksiz çiftler
        bad = [
            "USDCUSDT",
            "FDUSDUSDT",
            "TUSDUSDT",
            "DAIUSDT",
            "USDEUSDT"
        ]

        if symbol in bad:
            continue

        symbols.append(symbol)

    return symbols


# ============================================================
# KLINE
# ============================================================

def get_klines(symbol, interval, limit=100):

    data = get_json(
        f"{BASE}/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    if not data or not isinstance(data, list):
        return []

    candles = []

    for x in data:

        try:
            candles.append({
                "open": float(x[1]),
                "high": float(x[2]),
                "low": float(x[3]),
                "close": float(x[4]),
                "volume": float(x[5])
            })
        except Exception:
            continue

    return candles


# ============================================================
# 24H
# ============================================================

def get_24h():

    data = get_json(
        f"{BASE}/api/v3/ticker/24hr"
    )

    result = {}

    if not data:
        return result

    if isinstance(data, dict):
        data = [data]

    for x in data:

        try:
            symbol = x.get("symbol", "")

            if not symbol.endswith("USDT"):
                continue

            result[symbol] = {
                "price": float(x.get("lastPrice", 0)),
                "change": float(x.get("priceChangePercent", 0)),
                "volume": float(x.get("quoteVolume", 0))
            }

        except Exception:
            continue

    return result


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema_value = sum(values[:period]) / period

    for price in values[period:]:
        ema_value = (
            (price - ema_value) * multiplier
        ) + ema_value

    return ema_value


# ============================================================
# RSI
# ============================================================

def rsi(values, period=14):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):

        change = values[i] - values[i - 1]

        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1)) +
            gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) +
            losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ============================================================
# ATR
# ============================================================

def atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(1, len(candles)):

        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )

        trs.append(tr)

    if len(trs) < period:
        return None

    return sum(trs[-period:]) / period


# ============================================================
# 4H DIP ANALİZİ
# ============================================================

def analyze_4h(candles):

    if len(candles) < 60:
        return None

    closes = [x["close"] for x in candles]

    current = closes[-1]
    previous = closes[-2]

    ema20 = ema(closes, 20)
    ema20_prev = ema(closes[:-1], 20)

    ema50 = ema(closes, 50)

    rsi_now = rsi(closes, 14)

    if not all([
        ema20,
        ema20_prev,
        ema50,
        rsi_now
    ]):
        return None

    # --------------------------------------------------------
    # Son 12 adet 4H mum içindeki dip
    # --------------------------------------------------------

    recent = candles[-13:-1]

    swing_low = min(
        x["low"] for x in recent
    )

    if swing_low <= 0:
        return None

    recovery = (
        (current - swing_low)
        / swing_low
    ) * 100

    # Dipten dönüş çok küçükse henüz dönüş başlamamış olabilir
    if recovery < 1.0:
        return None

    # Çok fazla yükselmişse pump zaten başlamış olabilir
    if recovery > 12:
        return None

    # --------------------------------------------------------
    # Dipten dönüş kontrolü
    # --------------------------------------------------------

    last3 = candles[-3:]

    green_count = sum(
        1 for x in last3
        if x["close"] > x["open"]
    )

    if green_count < 2:
        return None

    # EMA20 yönü
    ema_rising = ema20 > ema20_prev

    if not ema_rising:
        return None

    # RSI aşırı yüksek olmayacak
    if rsi_now < 35 or rsi_now > 62:
        return None

    # Fiyat EMA20'ye yakın / üzerinde olmalı
    ema_distance = (
        (current - ema20)
        / ema20
    ) * 100

    if ema_distance < -3.0:
        return None

    if ema_distance > 8:
        return None

    # --------------------------------------------------------
    # 4H skor
    # --------------------------------------------------------

    score = 0

    # Dipten dönüş
    if 1 <= recovery <= 5:
        score += 20
    elif 5 < recovery <= 8:
        score += 15
    else:
        score += 8

    # EMA dönüşü
    if ema_rising:
        score += 15

    # EMA20'yi geri alma
    if current >= ema20:
        score += 15
    elif current >= ema20 * 0.995:
        score += 10

    # RSI
    if 40 <= rsi_now <= 55:
        score += 15
    elif 35 <= rsi_now < 40:
        score += 10
    elif 55 < rsi_now <= 62:
        score += 8

    # Son mum
    if current > previous:
        score += 10

    # Yeşil mum sayısı
    if green_count == 3:
        score += 10
    elif green_count == 2:
        score += 6

    return {
        "current": current,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi_now,
        "swing_low": swing_low,
        "recovery": recovery,
        "score": score
    }


# ============================================================
# 1H TEYİT
# ============================================================

def analyze_1h(candles):

    if len(candles) < 60:
        return None

    closes = [x["close"] for x in candles]

    current = closes[-1]
    previous = closes[-2]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    ema20_prev = ema(closes[:-1], 20)

    rsi_now = rsi(closes, 14)

    if not all([
        ema20,
        ema50,
        ema20_prev,
        rsi_now
    ]):
        return None

    score = 0

    # Fiyat EMA20 üzerinde
    if current >= ema20:
        score += 20
    elif current >= ema20 * 0.995:
        score += 12
    else:
        return None

    # EMA20 yönü
    if ema20 > ema20_prev:
        score += 15
    else:
        return None

    # EMA50 teyidi
    if current > ema50:
        score += 15

    # RSI
    if 48 <= rsi_now <= 68:
        score += 15
    elif 42 <= rsi_now < 48:
        score += 8
    else:
        return None

    # Son mum
    if current > previous:
        score += 10

    return {
        "score": score,
        "current": current,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi_now
    }


# ============================================================
# 15M MOMENTUM
# ============================================================

def analyze_15m(candles):

    if len(candles) < 50:
        return None

    closes = [x["close"] for x in candles]

    current = closes[-1]
    previous = closes[-2]

    ema20 = ema(closes, 20)

    rsi_now = rsi(closes, 14)

    if not ema20 or not rsi_now:
        return None

    score = 0

    # Fiyat EMA20 üstü
    if current > ema20:
        score += 15
    else:
        return None

    # RSI
    if 50 <= rsi_now <= 72:
        score += 15
    elif 45 <= rsi_now < 50:
        score += 8
    else:
        return None

    # Momentum
    if current > previous:
        score += 10

    # Hacim
    recent_volumes = [
        x["volume"]
        for x in candles[-21:-1]
    ]

    avg_volume = (
        sum(recent_volumes)
        / len(recent_volumes)
    )

    current_volume = candles[-1]["volume"]

    volume_ratio = (
        current_volume / avg_volume
        if avg_volume > 0
        else 0
    )

    if volume_ratio >= 2.0:
        score += 20
    elif volume_ratio >= 1.5:
        score += 15
    elif volume_ratio >= 1.25:
        score += 8

    return {
        "score": score,
        "current": current,
        "ema20": ema20,
        "rsi": rsi_now,
        "volume_ratio": volume_ratio
    }


# ============================================================
# COIN ANALİZİ
# ============================================================

def analyze_symbol(symbol, ticker):

    try:

        change = ticker.get("change", 0)
        volume = ticker.get("volume", 0)

        # ----------------------------------------------------
        # 24H filtre
        # ----------------------------------------------------

        if volume < MIN_24H_VOLUME:
            return None

        if change < MIN_24H_CHANGE:
            return None

        if change > MAX_24H_CHANGE:
            return None

        # ----------------------------------------------------
        # Veriler
        # ----------------------------------------------------

        candles_4h = get_klines(
            symbol,
            "4h",
            100
        )

        candles_1h = get_klines(
            symbol,
            "1h",
            100
        )

        candles_15m = get_klines(
            symbol,
            "15m",
            100
        )

        if not candles_4h or not candles_1h or not candles_15m:
            return None

        # ----------------------------------------------------
        # 4H ANA FİLTRE
        # ----------------------------------------------------

        four = analyze_4h(candles_4h)

        if not four:
            return None

        # ----------------------------------------------------
        # 1H TEYİT
        # ----------------------------------------------------

        one = analyze_1h(candles_1h)

        if not one:
            return None

        # ----------------------------------------------------
        # 15M TEYİT
        # ----------------------------------------------------

        fifteen = analyze_15m(candles_15m)

        if not fifteen:
            return None

        # ----------------------------------------------------
        # TOPLAM SKOR
        # ----------------------------------------------------

        score = (
            four["score"]
            + one["score"]
            + fifteen["score"]
        )

        # 4H ana filtre ağırlığı
        score += 10

        # ----------------------------------------------------
        # Risk
        # ----------------------------------------------------

        risk = STOP_PCT

        # ----------------------------------------------------
        # Minimum skor
        # ----------------------------------------------------

        if score < MIN_SCORE:
            return None

        entry = ticker["price"]

        if entry <= 0:
            return None

        tp1 = entry * (1 + TP1_PCT / 100)
        tp2 = entry * (1 + TP2_PCT / 100)
        tp3 = entry * (1 + TP3_PCT / 100)

        stop = entry * (1 - STOP_PCT / 100)

        return {
            "symbol": symbol,
            "score": score,
            "entry": entry,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "stop": stop,
            "change": change,
            "volume": volume,
            "recovery": four["recovery"],
            "rsi4h": four["rsi"],
            "rsi1h": one["rsi"],
            "rsi15m": fifteen["rsi"],
            "volume_ratio": fifteen["volume_ratio"]
        }

    except Exception as e:

        print(symbol, "error:", e)

        return None


# ============================================================
# MESAJ
# ============================================================

def format_signal(x):

    return (
        "🚨 <b>GÜÇLÜ PUMP ADAYI</b>\n\n"

        f"🪙 <b>{x['symbol']}</b>\n"
        f"⭐ <b>Skor: {x['score']}</b>\n\n"

        f"🟢 Giriş\n"
        f"<b>{x['entry']:.8f}</b>\n\n"

        f"🎯 TP1\n"
        f"<b>{x['tp1']:.8f}</b>\n\n"

        f"🎯 TP2\n"
        f"<b>{x['tp2']:.8f}</b>\n\n"

        f"🎯 TP3\n"
        f"<b>{x['tp3']:.8f}</b>\n\n"

        f"🛑 Stop\n"
        f"<b>{x['stop']:.8f}</b>\n\n"

        f"📊 24H: {x['change']:+.2f}%\n"
        f"📉 4H dipten dönüş: +{x['recovery']:.2f}%\n"
        f"⚡ 15M hacim: {x['volume_ratio']:.2f}x\n\n"

        f"🔎 4H RSI: {x['rsi4h']:.1f}\n"
        f"🔎 1H RSI: {x['rsi1h']:.1f}\n"
        f"🔎 15M RSI: {x['rsi15m']:.1f}\n\n"

        "📌 <b>4H DİP + DÖNÜŞ</b>\n"
        "📈 1H TREND TEYİDİ\n"
        "⚡ 15M MOMENTUM TEYİDİ\n\n"

        "⚠️ <i>Analiz sinyalidir, otomatik işlem açmaz.</i>"
    )


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print("=" * 60)
    print("MEXC PUMP RADAR BAŞLADI")
    print("=" * 60)

    symbols = get_usdt_symbols()

    if not symbols:
        print("Symbol alınamadı.")
        return

    print("USDT coin sayısı:", len(symbols))

    tickers = get_24h()

    if not tickers:
        print("Ticker alınamadı.")
        return

    candidates = []

    # --------------------------------------------------------
    # Paralel tarama
    # --------------------------------------------------------

    workers = 10

    with ThreadPoolExecutor(
        max_workers=workers
    ) as executor:

        futures = {}

        for symbol in symbols:

            ticker = tickers.get(symbol)

            if not ticker:
                continue

            futures[
                executor.submit(
                    analyze_symbol,
                    symbol,
                    ticker
                )
            ] = symbol

        for future in as_completed(futures):

            symbol = futures[future]

            try:
                result = future.result()

                if result:
                    candidates.append(result)

                    print(
                        "ADAY:",
                        symbol,
                        "SKOR:",
                        result["score"]
                    )

            except Exception as e:
                print(
                    "Future error:",
                    symbol,
                    e
                )

    # --------------------------------------------------------
    # Skora göre sırala
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print(
        "Güçlü aday:",
        len(candidates)
    )

    # --------------------------------------------------------
    # Duplicate kontrol
    # --------------------------------------------------------

    sent = load_sent()

    now = time.time()

    # Eski kayıtları temizle
    clean = {}

    for symbol, timestamp in sent.items():

        if now - timestamp < DUPLICATE_HOURS * 3600:
            clean[symbol] = timestamp

    sent = clean

    # --------------------------------------------------------
    # En güçlü adayları gönder
    # --------------------------------------------------------

    sent_count = 0

    for candidate in candidates:

        if sent_count >= MAX_SIGNALS_PER_SCAN:
            break

        symbol = candidate["symbol"]

        # 6 saat içinde gönderildiyse geç
        if symbol in sent:
            print(
                "DUPLICATE:",
                symbol
            )
            continue

        message = format_signal(candidate)

        success = send_telegram(message)

        if success:

            sent[symbol] = now

            save_sent(sent)

            sent_count += 1

            print(
                "GÖNDERİLDİ:",
                symbol
            )

    print(
        "Bu taramada gönderilen:",
        sent_count
    )


# ============================================================
# PROGRAM
# ============================================================

if __name__ == "__main__":

    print("Pump Radar çalışıyor...")

    while True:

        try:

            scan()

        except Exception as e:

            print(
                "ANA HATA:",
                e
            )

        print(
            f"{SCAN_INTERVAL_MINUTES} dakika bekleniyor..."
        )

        time.sleep(
            SCAN_INTERVAL_MINUTES * 60
        )
