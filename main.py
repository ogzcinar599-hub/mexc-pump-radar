import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC PUMP RADAR
#
# 4H  = DIP + DÖNÜŞ ANA FİLTRESİ
# 1H  = TREND TEYİDİ
# 15M = MOMENTUM TEYİDİ
#
# AMAÇ:
# Zaten pump olmuş coinleri değil,
# 4H dipten yeni dönmeye başlayan coinleri bulmak.
# ============================================================


BASE = "https://api.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================
# AYARLAR
# ============================================================

MIN_SCORE = 88

MIN_24H_VOLUME = 500000

# 24 saatlik değişim
MIN_24H_CHANGE = -12
MAX_24H_CHANGE = 15

# Bir taramada maksimum sinyal
MAX_SIGNALS_PER_SCAN = 3

# Duplicate süresi
DUPLICATE_HOURS = 6

# TP / STOP
TP1_PCT = 1.8
TP2_PCT = 3.5
TP3_PCT = 5.5
STOP_PCT = 2.2

# Paralel işlem
MAX_WORKERS = 20

# ============================================================
# DOSYA
# ============================================================

SENT_FILE = "sent_signals.json"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 PumpRadar/1.0"
})


# ============================================================
# SENT SIGNALS
# ============================================================

def load_sent():

    try:

        if os.path.exists(SENT_FILE):

            with open(
                SENT_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                return json.load(f)

    except Exception as e:

        print("sent_signals okuma hatası:", e)

    return {}


def save_sent(data):

    try:

        with open(
            SENT_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print("sent_signals yazma hatası:", e)


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):

    if not BOT_TOKEN:

        print("❌ TELEGRAM_BOT_TOKEN eksik")

        return False

    if not CHAT_ID:

        print("❌ TELEGRAM_CHAT_ID eksik")

        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    payload = {

        "chat_id": CHAT_ID,

        "text": text,

        "parse_mode": "HTML",

        "disable_web_page_preview": True
    }

    try:

        response = session.post(
            url,
            json=payload,
            timeout=15
        )

        print(
            "Telegram HTTP:",
            response.status_code
        )

        if response.status_code == 200:

            print("✅ Telegram mesajı gönderildi")

            return True

        print(
            "❌ Telegram cevap:",
            response.text
        )

    except Exception as e:

        print(
            "❌ Telegram bağlantı hatası:",
            e
        )

    return False


# ============================================================
# TELEGRAM TEST
# ============================================================

def telegram_test():

    print("")
    print("=" * 60)
    print("TELEGRAM TEST")
    print("=" * 60)

    message = (
        "🟢 <b>PUMP RADAR AKTİF</b>\n\n"
        "✅ Telegram bağlantısı çalışıyor.\n"
        "✅ GitHub Actions çalışıyor.\n\n"
        "🔎 4H dip + dönüş\n"
        "📈 1H trend teyidi\n"
        "⚡ 15M momentum teyidi\n\n"
        "Radar taramaya başladı."
    )

    return send_telegram(message)


# ============================================================
# GENERIC JSON
# ============================================================

def get_json(url, params=None):

    try:

        r = session.get(
            url,
            params=params,
            timeout=12
        )

        if r.status_code != 200:

            print(
                "HTTP hata:",
                r.status_code,
                url
            )

            return None

        return r.json()

    except Exception as e:

        print(
            "GET hata:",
            e
        )

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

    bad_symbols = {
        "USDCUSDT",
        "FDUSDUSDT",
        "TUSDUSDT",
        "DAIUSDT",
        "USDEUSDT",
        "USD1USDT"
    }

    for s in data.get("symbols", []):

        symbol = s.get(
            "symbol",
            ""
        )

        status = s.get(
            "status",
            ""
        )

        if not symbol.endswith("USDT"):
            continue

        if symbol in bad_symbols:
            continue

        # MEXC farklı API sürümlerinde
        # farklı status döndürebiliyor.
        if status:
            if str(status) not in (
                "1",
                "TRADING"
            ):
                continue

        symbols.append(symbol)

    return symbols


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=100
):

    data = get_json(
        f"{BASE}/api/v3/klines",
        {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )

    if not data:
        return []

    if not isinstance(data, list):
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
# 24H TICKER
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

            symbol = x.get(
                "symbol",
                ""
            )

            if not symbol.endswith("USDT"):
                continue

            result[symbol] = {

                "price": float(
                    x.get(
                        "lastPrice",
                        0
                    )
                ),

                "change": float(
                    x.get(
                        "priceChangePercent",
                        0
                    )
                ),

                "volume": float(
                    x.get(
                        "quoteVolume",
                        0
                    )
                )
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

    multiplier = 2 / (
        period + 1
    )

    ema_value = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        ema_value = (
            (price - ema_value)
            * multiplier
        ) + ema_value

    return ema_value


# ============================================================
# RSI
# ============================================================

def rsi(
    values,
    period=14
):

    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        change = (
            values[i]
            - values[i - 1]
        )

        if change >= 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
            )

    avg_gain = (
        sum(gains[:period])
        / period
    )

    avg_loss = (
        sum(losses[:period])
        / period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (
            (
                avg_gain
                * (period - 1)
            )
            + gains[i]
        ) / period

        avg_loss = (
            (
                avg_loss
                * (period - 1)
            )
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100

    rs = (
        avg_gain
        / avg_loss
    )

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# 4H DIP + DÖNÜŞ
# ============================================================

def analyze_4h(candles):

    if len(candles) < 60:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]
    previous = closes[-2]

    ema20 = ema(
        closes,
        20
    )

    ema20_prev = ema(
        closes[:-1],
        20
    )

    ema50 = ema(
        closes,
        50
    )

    rsi_now = rsi(
        closes,
        14
    )

    if not all([
        ema20,
        ema20_prev,
        ema50,
        rsi_now
    ]):
        return None

    # --------------------------------------------------------
    # SON 12 TAMAMLANMIŞ 4H MUMUNUN DİBİ
    # --------------------------------------------------------

    recent = candles[-13:-1]

    swing_low = min(
        x["low"]
        for x in recent
    )

    if swing_low <= 0:
        return None

    recovery = (
        (current - swing_low)
        / swing_low
    ) * 100

    # Dipten yeni dönüş
    if recovery < 1.0:
        return None

    # Çok yükselmiş coin = pump başlamış olabilir
    if recovery > 12:
        return None

    # --------------------------------------------------------
    # SON 3 MUM
    # --------------------------------------------------------

    last3 = candles[-3:]

    green_count = sum(
        1
        for x in last3
        if x["close"] > x["open"]
    )

    # En az 2 yeşil
    if green_count < 2:
        return None

    # --------------------------------------------------------
    # EMA20 YUKARI DÖNÜYOR MU?
    # --------------------------------------------------------

    ema_rising = (
        ema20 > ema20_prev
    )

    if not ema_rising:
        return None

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if rsi_now < 35:
        return None

    if rsi_now > 62:
        return None

    # --------------------------------------------------------
    # FİYAT - EMA20
    # --------------------------------------------------------

    ema_distance = (
        (current - ema20)
        / ema20
    ) * 100

    if ema_distance < -3:
        return None

    if ema_distance > 8:
        return None

    # --------------------------------------------------------
    # 4H SCORE
    # --------------------------------------------------------

    score = 0

    # Dipten dönüş
    if 1 <= recovery <= 5:
        score += 20

    elif 5 < recovery <= 8:
        score += 15

    else:
        score += 8

    # EMA dönüş
    score += 15

    # EMA20 geri alınmış
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

    # Son mum pozitif
    if current > previous:

        score += 10

    # Yeşil mumlar
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
# 1H TREND
# ============================================================

def analyze_1h(candles):

    if len(candles) < 60:
        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]
    previous = closes[-2]

    ema20 = ema(
        closes,
        20
    )

    ema50 = ema(
        closes,
        50
    )

    ema20_prev = ema(
        closes[:-1],
        20
    )

    rsi_now = rsi(
        closes,
        14
    )

    if not all([
        ema20,
        ema50,
        ema20_prev,
        rsi_now
    ]):
        return None

    score = 0

    # EMA20 üstü
    if current >= ema20:

        score += 20

    elif current >= ema20 * 0.995:

        score += 12

    else:

        return None

    # EMA20 yukarı
    if ema20 > ema20_prev:

        score += 15

    else:

        return None

    # EMA50 üstü
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

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]
    previous = closes[-2]

    ema20 = ema(
        closes,
        20
    )

    rsi_now = rsi(
        closes,
        14
    )

    if not ema20 or not rsi_now:
        return None

    score = 0

    # EMA20 üstü
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

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    recent_volumes = [
        x["volume"]
        for x in candles[-21:-1]
    ]

    if not recent_volumes:
        return None

    avg_volume = (
        sum(recent_volumes)
        / len(recent_volumes)
    )

    current_volume = candles[-1]["volume"]

    if avg_volume <= 0:

        volume_ratio = 0

    else:

        volume_ratio = (
            current_volume
            / avg_volume
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

def analyze_symbol(
    symbol,
    ticker
):

    try:

        change = ticker.get(
            "change",
            0
        )

        volume = ticker.get(
            "volume",
            0
        )

        # ----------------------------------------------------
        # 24H FILTRE
        # ----------------------------------------------------

        if volume < MIN_24H_VOLUME:

            return None

        if change < MIN_24H_CHANGE:

            return None

        if change > MAX_24H_CHANGE:

            return None

        # ----------------------------------------------------
        # 4H
        # ----------------------------------------------------

        candles_4h = get_klines(
            symbol,
            "4h",
            100
        )

        if not candles_4h:

            return None

        four = analyze_4h(
            candles_4h
        )

        if not four:

            return None

        # ----------------------------------------------------
        # 1H
        # ----------------------------------------------------

        candles_1h = get_klines(
            symbol,
            "1h",
            100
        )

        if not candles_1h:

            return None

        one = analyze_1h(
            candles_1h
        )

        if not one:

            return None

        # ----------------------------------------------------
        # 15M
        # ----------------------------------------------------

        candles_15m = get_klines(
            symbol,
            "15m",
            100
        )

        if not candles_15m:

            return None

        fifteen = analyze_15m(
            candles_15m
        )

        if not fifteen:

            return None

        # ----------------------------------------------------
        # TOPLAM SKOR
        # ----------------------------------------------------

        score = (
            four["score"]
            + one["score"]
            + fifteen["score"]
            + 10
        )

        if score < MIN_SCORE:

            return None

        # ----------------------------------------------------
        # GİRİŞ
        # ----------------------------------------------------

        entry = ticker["price"]

        if entry <= 0:

            return None

        # ----------------------------------------------------
        # TP
        # ----------------------------------------------------

        tp1 = (
            entry
            * (1 + TP1_PCT / 100)
        )

        tp2 = (
            entry
            * (1 + TP2_PCT / 100)
        )

        tp3 = (
            entry
            * (1 + TP3_PCT / 100)
        )

        # ----------------------------------------------------
        # STOP
        # ----------------------------------------------------

        stop = (
            entry
            * (1 - STOP_PCT / 100)
        )

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

        print(
            symbol,
            "analiz hatası:",
            e
        )

        return None


# ============================================================
# FİYAT FORMAT
# ============================================================

def price_format(price):

    if price >= 100:

        return f"{price:.2f}"

    if price >= 1:

        return f"{price:.4f}"

    if price >= 0.01:

        return f"{price:.6f}"

    if price >= 0.0001:

        return f"{price:.8f}"

    return f"{price:.10f}"


# ============================================================
# MESAJ
# ============================================================

def format_signal(x):

    return (

        "🚨 <b>GÜÇLÜ PUMP ADAYI</b>\n\n"

        f"🪙 <b>{x['symbol']}</b>\n"
        f"⭐ <b>Skor: {x['score']}</b>\n\n"

        "🟢 <b>Giriş</b>\n"
        f"{price_format(x['entry'])}\n\n"

        "🎯 <b>TP1</b>\n"
        f"{price_format(x['tp1'])}\n\n"

        "🎯 <b>TP2</b>\n"
        f"{price_format(x['tp2'])}\n\n"

        "🎯 <b>TP3</b>\n"
        f"{price_format(x['tp3'])}\n\n"

        "🛑 <b>Stop</b>\n"
        f"{price_format(x['stop'])}\n\n"

        f"📊 24H: {x['change']:+.2f}%\n"
        f"📉 4H dipten dönüş: +{x['recovery']:.2f}%\n"
        f"⚡ 15M hacim: {x['volume_ratio']:.2f}x\n\n"

        f"🔎 4H RSI: {x['rsi4h']:.1f}\n"
        f"🔎 1H RSI: {x['rsi1h']:.1f}\n"
        f"🔎 15M RSI: {x['rsi15m']:.1f}\n\n"

        "📌 <b>4H DİP + DÖNÜŞ</b>\n"
        "📈 <b>1H TREND TEYİDİ</b>\n"
        "⚡ <b>15M MOMENTUM TEYİDİ</b>\n\n"

        "⚠️ <i>Analiz sinyalidir, otomatik işlem açmaz.</i>"
    )


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print("")
    print("=" * 60)
    print("🚀 MEXC PUMP RADAR BAŞLADI")
    print("=" * 60)

    # --------------------------------------------------------
    # SYMBOLLER
    # --------------------------------------------------------

    symbols = get_usdt_symbols()

    if not symbols:

        print("❌ Symbol alınamadı.")

        send_telegram(
            "🔴 <b>PUMP RADAR HATASI</b>\n\n"
            "MEXC coin listesi alınamadı."
        )

        return

    print(
        "USDT coin sayısı:",
        len(symbols)
    )

    # --------------------------------------------------------
    # 24H
    # --------------------------------------------------------

    tickers = get_24h()

    if not tickers:

        print("❌ Ticker alınamadı.")

        send_telegram(
            "🔴 <b>PUMP RADAR HATASI</b>\n\n"
            "MEXC 24H verileri alınamadı."
        )

        return

    # --------------------------------------------------------
    # ÖN FİLTRE
    #
    # Kline isteğini gereksiz coinlere yapmıyoruz.
    # Bu taramayı ciddi şekilde hızlandırır.
    # --------------------------------------------------------

    filtered = []

    for symbol in symbols:

        ticker = tickers.get(
            symbol
        )

        if not ticker:
            continue

        volume = ticker.get(
            "volume",
            0
        )

        change = ticker.get(
            "change",
            0
        )

        if volume < MIN_24H_VOLUME:
            continue

        if change < MIN_24H_CHANGE:
            continue

        if change > MAX_24H_CHANGE:
            continue

        filtered.append(
            (
                symbol,
                ticker
            )
        )

    print(
        "24H filtre sonrası:",
        len(filtered)
    )

    if not filtered:

        send_telegram(
            "🔎 <b>PUMP RADAR</b>\n\n"
            "Bu taramada 24H filtresini geçen "
            "coin bulunamadı."
        )

        return

    # --------------------------------------------------------
    # PARALEL TARAMA
    # --------------------------------------------------------

    candidates = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for symbol, ticker in filtered:

            future = executor.submit(
                analyze_symbol,
                symbol,
                ticker
            )

            futures[future] = symbol

        completed = 0
        total = len(futures)

        for future in as_completed(
            futures
        ):

            symbol = futures[future]

            completed += 1

            try:

                result = future.result()

                if result:

                    candidates.append(
                        result
                    )

                    print(
                        "🔥 ADAY:",
                        symbol,
                        "SKOR:",
                        result["score"],
                        "4H dönüş:",
                        f"{result['recovery']:.2f}%"
                    )

            except Exception as e:

                print(
                    "Future hata:",
                    symbol,
                    e
                )

            if completed % 50 == 0:

                print(
                    "İlerleme:",
                    completed,
                    "/",
                    total
                )

    # --------------------------------------------------------
    # SKORA GÖRE SIRALA
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print("")
    print(
        "4H + 1H + 15M güçlü aday:",
        len(candidates)
    )

    # --------------------------------------------------------
    # ADAY YOK
    # --------------------------------------------------------

    if not candidates:

        print(
            "Bu taramada sinyal yok."
        )

        # Telegram'a her 5 dakikada
        # gereksiz mesaj yağdırmamak için
        # aday yok mesajı göndermiyoruz.

        return

    # --------------------------------------------------------
    # DUPLICATE
    # --------------------------------------------------------

    sent = load_sent()

    now = time.time()

    clean = {}

    for symbol, timestamp in sent.items():

        try:

            if (
                now - float(timestamp)
                < DUPLICATE_HOURS * 3600
            ):

                clean[symbol] = timestamp

        except Exception:

            pass

    sent = clean

    # --------------------------------------------------------
    # GÖNDER
    # --------------------------------------------------------

    sent_count = 0

    for candidate in candidates:

        if (
            sent_count
            >= MAX_SIGNALS_PER_SCAN
        ):

            break

        symbol = candidate[
            "symbol"
        ]

        if symbol in sent:

            print(
                "⏭ DUPLICATE:",
                symbol
            )

            continue

        message = format_signal(
            candidate
        )

        success = send_telegram(
            message
        )

        if success:

            sent[symbol] = now

            save_sent(
                sent
            )

            sent_count += 1

            print(
                "✅ GÖNDERİLDİ:",
                symbol
            )

    print("")
    print(
        "📨 Bu taramada gönderilen:",
        sent_count
    )

    print("=" * 60)


# ============================================================
# PROGRAM
# ============================================================

if __name__ == "__main__":

    print("")
    print("🚀 PUMP RADAR BAŞLIYOR")
    print("")

    # --------------------------------------------------------
    # TELEGRAM TEST
    # --------------------------------------------------------

    if not BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN YOK"
        )

    if not CHAT_ID:

        print(
            "❌ TELEGRAM_CHAT_ID YOK"
        )

    if BOT_TOKEN and CHAT_ID:

        telegram_test()

    else:

        print(
            "❌ Telegram secretları eksik."
        )

    # --------------------------------------------------------
    # TEK TARAMA
    #
    # GitHub Actions için sonsuz while kullanmıyoruz.
    # --------------------------------------------------------

    try:

        scan()

    except Exception as e:

        print(
            "🔴 ANA HATA:",
            e
        )

        send_telegram(
            "🔴 <b>PUMP RADAR ANA HATA</b>\n\n"
            f"<code>{str(e)[:500]}</code>"
        )

    print("")
    print("🏁 Radar taraması tamamlandı.")
