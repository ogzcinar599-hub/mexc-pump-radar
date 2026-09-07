import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC PUMP ÖNCESİ RADAR
#
# AMAÇ:
# Pump olmuş coinleri yakalamak değil,
# pump başlamadan hemen önce hareketlenen coinleri bulmak.
#
# SADECE:
# MEXC USDT-M FUTURES
#
# SİNYAL:
# 🟢 PUMP ÖNCESİ
#
# İZLEME ADAYI YOK
# DÜŞÜŞ SİNYALİ YOK
# ============================================================


BASE = "https://api.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================
# AYARLAR
# ============================================================

# Daha fazla coin yakalamak için
MIN_24H_VOLUME = 100000

# 24H aşırı pump olmuş coinleri ele
MIN_24H_CHANGE = -8
MAX_24H_CHANGE = 25

# Ana sinyal skoru
MIN_SCORE = 65

# Aynı coin tekrar gelmesin
DUPLICATE_HOURS = 3

# Bir taramada maksimum
MAX_SIGNALS_PER_SCAN = 6

# Paralel
MAX_WORKERS = 12


# ============================================================
# TP / STOP
# ============================================================

TP1_PCT = 2.0
TP2_PCT = 4.0
TP3_PCT = 7.0

STOP_PCT = 2.5


# ============================================================
# DOSYA
# ============================================================

SENT_FILE = "sent_signals.json"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 MEXC-Pump-Radar/5.0"
})


# ============================================================
# JSON
# ============================================================

def get_json(url, params=None):

    try:

        r = session.get(
            url,
            params=params,
            timeout=15
        )

        if r.status_code != 200:

            print(
                "HTTP:",
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
# TELEGRAM
# ============================================================

def send_telegram(text):

    if not BOT_TOKEN or not CHAT_ID:

        print("Telegram secret eksik")

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

        r = session.post(
            url,
            json=payload,
            timeout=15
        )

        if r.status_code == 200:

            print("✅ Telegram gönderildi")

            return True

        print(
            "Telegram hata:",
            r.text
        )

    except Exception as e:

        print(
            "Telegram bağlantı:",
            e
        )

    return False


# ============================================================
# TELEGRAM TEST
# ============================================================

def telegram_test():

    msg = (

        "🟢 <b>PUMP RADAR 5.0</b>\n\n"

        "✅ Sistem aktif\n"
        "💎 MEXC USDT Futures\n\n"

        "🚀 Pump öncesi hareket aranıyor\n"
        "⚡ 15M momentum\n"
        "📈 1H trend\n"
        "💥 Hacim patlaması\n"
        "📊 Alıcı baskısı\n\n"

        "❌ İzleme adayı yok\n"
        "❌ Pump sonrası sinyal yok\n"
        "❌ Ters trend yok\n\n"

        "🎯 Sadece güçlü giriş sinyalleri"
    )

    return send_telegram(msg)


# ============================================================
# SENT
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

    except Exception:

        pass

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
                indent=2
            )

    except Exception as e:

        print(
            "Sent kayıt:",
            e
        )


# ============================================================
# FUTURES KONTRATLARI
# ============================================================

def get_contracts():

    data = get_json(
        f"{BASE}/api/v1/contract/detail"
    )

    if not data:

        return []

    rows = data.get(
        "data",
        []
    )

    result = []

    for x in rows:

        symbol = str(
            x.get(
                "symbol",
                ""
            )
        )

        quote = str(
            x.get(
                "quoteCoin",
                ""
            )
        )

        settle = str(
            x.get(
                "settleCoin",
                ""
            )
        )

        # SADECE USDT FUTURES
        if not symbol.endswith("_USDT"):
            continue

        if quote != "USDT":
            continue

        if settle != "USDT":
            continue

        result.append(symbol)

    return result


# ============================================================
# FUTURES TICKER
# ============================================================

def get_tickers():

    data = get_json(
        f"{BASE}/api/v1/contract/ticker"
    )

    if not data:

        return {}

    rows = data.get(
        "data",
        []
    )

    if isinstance(rows, dict):

        rows = [rows]

    result = {}

    for x in rows:

        try:

            symbol = x.get(
                "symbol",
                ""
            )

            if not symbol.endswith("_USDT"):
                continue

            price = float(
                x.get(
                    "lastPrice",
                    0
                ) or 0
            )

            change = float(
                x.get(
                    "riseFallRate",
                    0
                ) or 0
            ) * 100

            volume = float(
                x.get(
                    "amount24",
                    0
                ) or 0
            )

            if price <= 0:
                continue

            result[symbol] = {

                "price": price,

                "change": change,

                "volume": volume

            }

        except Exception:

            continue

    return result


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=100
):

    data = get_json(
        f"{BASE}/api/v1/contract/kline/{symbol}",
        {
            "interval": interval
        }
    )

    if not data:

        return []

    market = data.get(
        "data"
    )

    if not market:

        return []

    opens = market.get(
        "open",
        []
    )

    highs = market.get(
        "high",
        []
    )

    lows = market.get(
        "low",
        []
    )

    closes = market.get(
        "close",
        []
    )

    volumes = market.get(
        "vol",
        []
    )

    count = min(
        len(opens),
        len(highs),
        len(lows),
        len(closes),
        len(volumes)
    )

    if count < 30:

        return []

    start = max(
        0,
        count - limit
    )

    candles = []

    for i in range(
        start,
        count
    ):

        try:

            candles.append({

                "open":
                    float(opens[i]),

                "high":
                    float(highs[i]),

                "low":
                    float(lows[i]),

                "close":
                    float(closes[i]),

                "volume":
                    float(volumes[i])

            })

        except Exception:

            pass

    return candles


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:

        return None

    multiplier = 2 / (
        period + 1
    )

    value = sum(
        values[:period]
    ) / period

    for price in values[period:]:

        value = (
            (price - value)
            * multiplier
        ) + value

    return value


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

        diff = (
            values[i]
            - values[i - 1]
        )

        if diff > 0:

            gains.append(diff)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(diff)
            )

    avg_gain = (
        sum(
            gains[:period]
        ) / period
    )

    avg_loss = (
        sum(
            losses[:period]
        ) / period
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

    return (
        100
        - 100 / (1 + rs)
    )


# ============================================================
# ATR BENZERİ VOLATİLİTE
# ============================================================

def volatility(candles):

    if len(candles) < 15:

        return 0

    moves = []

    for x in candles[-15:]:

        if x["open"] <= 0:
            continue

        move = (
            (
                x["high"]
                - x["low"]
            )
            / x["open"]
        ) * 100

        moves.append(move)

    if not moves:

        return 0

    return sum(moves) / len(moves)


# ============================================================
# PUMP ÖNCESİ ANALİZ
# ============================================================

def analyze(
    symbol,
    ticker,
    c15,
    c1,
    c4
):

    if min(
        len(c15),
        len(c1),
        len(c4)
    ) < 50:

        return None

    price = ticker["price"]

    # ========================================================
    # SON KAPANMIŞ MUMU KULLAN
    # ========================================================

    # Son mum devam ediyor olabilir.
    # Bu nedenle -2 kullanıyoruz.
    last15 = c15[-2]
    prev15 = c15[-3]

    last1 = c1[-2]
    prev1 = c1[-3]

    last4 = c4[-2]

    close15 = [
        x["close"]
        for x in c15[:-1]
    ]

    close1 = [
        x["close"]
        for x in c1[:-1]
    ]

    close4 = [
        x["close"]
        for x in c4[:-1]
    ]

    # ========================================================
    # EMA
    # ========================================================

    ema9_15 = ema(
        close15,
        9
    )

    ema20_15 = ema(
        close15,
        20
    )

    ema20_1 = ema(
        close1,
        20
    )

    ema50_1 = ema(
        close1,
        50
    )

    ema20_4 = ema(
        close4,
        20
    )

    # ========================================================
    # RSI
    # ========================================================

    rsi15 = rsi(
        close15
    )

    rsi1 = rsi(
        close1
    )

    rsi4 = rsi(
        close4
    )

    if not all([
        ema9_15,
        ema20_15,
        ema20_1,
        ema50_1,
        ema20_4,
        rsi15,
        rsi1,
        rsi4
    ]):

        return None

    # ========================================================
    # 1 — AŞIRI PUMP YAPMIŞ MI?
    # ========================================================

    high24 = max(
        x["high"]
        for x in c15[-97:-1]
    )

    if high24 <= 0:

        return None

    distance_from_high = (
        (
            high24
            - price
        )
        / high24
    ) * 100

    # Zirveden çok uzaktaysa
    # pump öncesi değil.
    if distance_from_high > 18:

        return None

    # ========================================================
    # 2 — SON 1 SAAT HAREKETİ
    # ========================================================

    old_price = c15[-6]["close"]

    move_1h = (
        (
            last15["close"]
            - old_price
        )
        / old_price
    ) * 100

    # Hafif pozitif hareket lazım
    if move_1h < 0.3:

        return None

    # Çoktan uçmuşsa alma
    if move_1h > 10:

        return None

    # ========================================================
    # 3 — SON 15 DAKİKA MOMENTUM
    # ========================================================

    move_15m = (
        (
            last15["close"]
            - prev15["close"]
        )
        / prev15["close"]
    ) * 100

    # Son mum negatifse alma
    if move_15m < -0.3:

        return None

    # Tek mumda çok pump
    if move_15m > 5:

        return None

    # ========================================================
    # 4 — EMA 9 / 20 CROSS
    # ========================================================

    ema9_prev = ema(
        close15[:-1],
        9
    )

    ema20_prev = ema(
        close15[:-1],
        20
    )

    cross_up = (
        ema9_prev <= ema20_prev
        and
        ema9_15 > ema20_15
    )

    # Cross yoksa ama EMA yapısı pozitifse
    # yine puan vereceğiz.
    ema_bullish = (
        ema9_15 > ema20_15
    )

    # ========================================================
    # 5 — 1H TREND
    # ========================================================

    trend1h = (
        last1["close"]
        > ema20_1
    )

    strong_trend1h = (
        ema20_1
        > ema50_1
    )

    # Fiyat EMA20 altında ise alma
    if last1["close"] < ema20_1 * 0.995:

        return None

    # ========================================================
    # 6 — 4H ÇOK ZAYIF OLMASIN
    # ========================================================

    if last4["close"] < ema20_4 * 0.97:

        return None

    # ========================================================
    # 7 — RSI
    # ========================================================

    # Çok düşük = henüz hazır değil
    if rsi15 < 45:

        return None

    # Çok yüksek = pump başlamış olabilir
    if rsi15 > 72:

        return None

    if rsi1 < 45:

        return None

    if rsi1 > 70:

        return None

    # ========================================================
    # 8 — HACİM PATLAMASI
    # ========================================================

    volumes = [
        x["volume"]
        for x in c15[-21:-1]
        if x["volume"] > 0
    ]

    if len(volumes) < 10:

        return None

    avg_volume = (
        sum(volumes)
        / len(volumes)
    )

    volume_ratio = (
        last15["volume"]
        / avg_volume
    )

    # Hacim en önemli filtrelerden biri
    if volume_ratio < 1.05:

        return None

    # ========================================================
    # 9 — SON 3 MUMDA ALICI BASKISI
    # ========================================================

    bullish = 0

    for candle in c15[-4:-1]:

        if candle["close"] > candle["open"]:

            bullish += 1

    if bullish < 2:

        return None

    # ========================================================
    # 10 — HACİM + FİYAT BİRLİKTE
    # ========================================================

    price_volume_ok = (
        move_15m > 0
        and
        volume_ratio >= 1.15
    )

    # ========================================================
    # SCORE
    # ========================================================

    score = 0

    # 15M EMA
    if cross_up:

        score += 20

    elif ema_bullish:

        score += 12

    # 1H trend
    if strong_trend1h:

        score += 15

    elif trend1h:

        score += 10

    # Hacim
    if volume_ratio >= 2.0:

        score += 20

    elif volume_ratio >= 1.5:

        score += 16

    elif volume_ratio >= 1.25:

        score += 12

    else:

        score += 7

    # Son hareket
    if 0.3 <= move_1h <= 4:

        score += 15

    elif move_1h <= 7:

        score += 10

    else:

        score += 5

    # RSI
    if 52 <= rsi15 <= 65:

        score += 10

    elif 45 <= rsi15 < 52:

        score += 7

    else:

        score += 5

    # Yeşil mumlar
    if bullish == 3:

        score += 10

    else:

        score += 6

    # Fiyat hacim
    if price_volume_ok:

        score += 10

    # 4H
    if last4["close"] >= ema20_4:

        score += 5

    # ========================================================
    # PUMP ÖNCESİ ÖZEL FİLTRE
    # ========================================================

    # Son 1 saatte çok yükselmişse
    # artık pump öncesi değildir.
    if move_1h > 7:

        score -= 15

    # 24H zaten çok yükselmişse
    if ticker["change"] > 18:

        score -= 15

    # 15M tek mumda patlamışsa
    if move_15m > 3:

        score -= 10

    # ========================================================
    # SON KONTROL
    # ========================================================

    if score < MIN_SCORE:

        return None

    # ========================================================
    # TP / STOP
    # ========================================================

    entry = price

    tp1 = entry * (
        1 + TP1_PCT / 100
    )

    tp2 = entry * (
        1 + TP2_PCT / 100
    )

    tp3 = entry * (
        1 + TP3_PCT / 100
    )

    stop = entry * (
        1 - STOP_PCT / 100
    )

    return {

        "symbol": symbol,

        "score": min(
            int(score),
            100
        ),

        "entry": entry,

        "tp1": tp1,

        "tp2": tp2,

        "tp3": tp3,

        "stop": stop,

        "change": ticker["change"],

        "move1h": move_1h,

        "move15m": move_15m,

        "volume_ratio": volume_ratio,

        "rsi15": rsi15,

        "rsi1": rsi1,

        "rsi4": rsi4,

        "cross": cross_up

    }


# ============================================================
# COIN ANALİZİ
# ============================================================

def analyze_symbol(item):

    symbol, ticker = item

    try:

        c15 = get_klines(
            symbol,
            "Min15",
            100
        )

        c1 = get_klines(
            symbol,
            "Min60",
            100
        )

        c4 = get_klines(
            symbol,
            "Hour4",
            100
        )

        if not c15 or not c1 or not c4:

            return None

        return analyze(
            symbol,
            ticker,
            c15,
            c1,
            c4
        )

    except Exception as e:

        print(
            symbol,
            "hata:",
            e
        )

        return None


# ============================================================
# PRICE FORMAT
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
# TELEGRAM MESAJ
# ============================================================

def format_signal(x):

    return (

        "🚀 <b>PUMP ÖNCESİ SİNYAL</b>\n\n"

        f"💎 <b>{x['symbol']}</b>\n"

        f"⭐ Skor: "
        f"<b>{x['score']}/100</b>\n\n"

        f"🟢 Giriş: "
        f"<b>{price_format(x['entry'])}</b>\n"

        f"🎯 TP1: "
        f"{price_format(x['tp1'])}\n"

        f"🎯 TP2: "
        f"{price_format(x['tp2'])}\n"

        f"🎯 TP3: "
        f"{price_format(x['tp3'])}\n"

        f"🛑 Stop: "
        f"{price_format(x['stop'])}\n\n"

        f"📊 24H: "
        f"{x['change']:+.2f}%\n"

        f"⚡ 1H hareket: "
        f"+{x['move1h']:.2f}%\n"

        f"🔥 15M hareket: "
        f"{x['move15m']:+.2f}%\n"

        f"💥 Hacim: "
        f"{x['volume_ratio']:.2f}x\n\n"

        f"📈 15M RSI: "
        f"{x['rsi15']:.1f}\n"

        f"📈 1H RSI: "
        f"{x['rsi1']:.1f}\n"

        f"📊 4H RSI: "
        f"{x['rsi4']:.1f}\n\n"

        + (
            "🔥 EMA9/20 KESİŞİMİ\n"
            if x["cross"]
            else
            "📈 EMA TRENDİ POZİTİF\n"
        )

        + "\n"

        "📡 <b>MEXC USDT FUTURES</b>\n\n"

        "⚠️ <i>Erken hareket sinyalidir. "
        "Pump garantisi değildir.</i>"
    )


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print("")
    print("=" * 65)
    print("🚀 MEXC PUMP ÖNCESİ RADAR 5.0")
    print("=" * 65)

    # ========================================================
    # CONTRACT
    # ========================================================

    contracts = get_contracts()

    print(
        "Futures kontrat:",
        len(contracts)
    )

    if not contracts:

        print(
            "❌ Futures kontrat alınamadı"
        )

        send_telegram(
            "🔴 <b>RADAR HATASI</b>\n\n"
            "MEXC Futures kontratları alınamadı."
        )

        return

    # ========================================================
    # TICKER
    # ========================================================

    tickers = get_tickers()

    print(
        "Ticker:",
        len(tickers)
    )

    if not tickers:

        print(
            "❌ Ticker alınamadı"
        )

        return

    # ========================================================
    # ÖN FİLTRE
    # ========================================================

    filtered = []

    for symbol in contracts:

        ticker = tickers.get(
            symbol
        )

        if not ticker:

            continue

        volume = ticker["volume"]

        change = ticker["change"]

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

    # ========================================================
    # HACİME GÖRE
    # ========================================================

    filtered.sort(
        key=lambda x: x[1]["volume"],
        reverse=True
    )

    print(
        "24H ön filtre:",
        len(filtered)
    )

    if not filtered:

        print(
            "❌ Ön filtreden coin geçmedi"
        )

        return

    # ========================================================
    # DETAYLI TARAMA
    # ========================================================

    candidates = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for item in filtered:

            future = executor.submit(
                analyze_symbol,
                item
            )

            futures[future] = item[0]

        total = len(futures)

        for i, future in enumerate(
            as_completed(futures),
            1
        ):

            symbol = futures[
                future
            ]

            try:

                result = future.result()

                if result:

                    candidates.append(
                        result
                    )

                    print(
                        "🔥 ADAY:",
                        symbol,
                        result["score"]
                    )

            except Exception as e:

                print(
                    symbol,
                    e
                )

            if (
                i % 25 == 0
                or i == total
            ):

                print(
                    f"İlerleme: "
                    f"{i}/{total}"
                )

    # ========================================================
    # SKOR
    # ========================================================

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print("")
    print(
        "🚀 PUMP ÖNCESİ ADAY:",
        len(candidates)
    )

    # ========================================================
    # SENT
    # ========================================================

    sent = load_sent()

    now = time.time()

    clean = {}

    for symbol, timestamp in sent.items():

        try:

            if (
                now
                - float(timestamp)
                <
                DUPLICATE_HOURS * 3600
            ):

                clean[symbol] = timestamp

        except Exception:

            pass

    sent = clean

    # ========================================================
    # TELEGRAM
    # ========================================================

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
                "⏭ Tekrar:",
                symbol
            )

            continue

        message = format_signal(
            candidate
        )

        if send_telegram(
            message
        ):

            sent[symbol] = now

            save_sent(
                sent
            )

            sent_count += 1

            print(
                "✅ GÖNDERİLDİ:",
                symbol,
                candidate["score"]
            )

    print("")
    print(
        "📨 Telegram gönderilen:",
        sent_count
    )

    print("=" * 65)


# ============================================================
# PROGRAM
# ============================================================

if __name__ == "__main__":

    print("")
    print(
        "🚀 PUMP RADAR BAŞLIYOR"
    )

    if BOT_TOKEN and CHAT_ID:

        telegram_test()

    else:

        print(
            "❌ Telegram secret eksik"
        )

    try:

        scan()

    except Exception as e:

        print(
            "🔴 ANA HATA:",
            e
        )

        send_telegram(
            "🔴 <b>RADAR HATASI</b>\n\n"
            f"<code>{str(e)[:500]}</code>"
        )

    print("")
    print(
        "🏁 Tarama tamamlandı."
    )
