import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC CRYPTO FUTURES RADAR V6
#
# 🟢 GÜÇLÜ HAREKET ADAYI
# 🟡 ERKEN HAREKET ADAYI
# 🔻 PUMP SONRASI DÜŞÜŞ
#
# SADECE MEXC USDT CRYPTO FUTURES
# STOCK / ETF / INDEX YOK
# ============================================================


BASE = "https://contract.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================
# AYARLAR
# ============================================================

# 60 ALTINA MESAJ YOK
MIN_SCORE = 60

# Bir taramada maksimum 5 sinyal
MAX_SIGNALS_PER_SCAN = 5

# Aynı sinyalin tekrar gönderilme süresi
DUPLICATE_HOURS = 4

# Minimum 24H hacim
MIN_24H_VOLUME = 150000

# 24H değişim
MIN_24H_CHANGE = -30
MAX_24H_CHANGE = 100

# Paralel tarama
MAX_WORKERS = 20


# ============================================================
# TP / STOP
# ============================================================

TP1_PCT = 1.8
TP2_PCT = 3.5
TP3_PCT = 5.5

STOP_PCT = 2.2


# ============================================================
# DOSYA
# ============================================================

SENT_FILE = "sent_signals.json"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 MEXC-Pump-Radar-V6"
})


# ============================================================
# JSON
# ============================================================

def get_json(url, params=None):

    try:

        response = session.get(
            url,
            params=params,
            timeout=15
        )

        if response.status_code != 200:

            print(
                "HTTP:",
                response.status_code,
                url
            )

            return None

        data = response.json()

        if (
            isinstance(data, dict)
            and data.get("success") is False
        ):

            return None

        return data

    except Exception as e:

        print(
            "GET HATA:",
            e
        )

        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):

    if not BOT_TOKEN:

        print("TELEGRAM_BOT_TOKEN eksik")

        return False

    if not CHAT_ID:

        print("TELEGRAM_CHAT_ID eksik")

        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    payload = {

        "chat_id": CHAT_ID,

        "text": text,

        # Parse kullanmıyoruz.
        # Böylece entity hatası olmaz.
        "disable_web_page_preview": True
    }

    try:

        response = session.post(
            url,
            json=payload,
            timeout=15
        )

        if response.status_code == 200:

            print("Telegram gönderildi")

            return True

        print(
            "Telegram hata:",
            response.status_code,
            response.text
        )

    except Exception as e:

        print(
            "Telegram bağlantı hatası:",
            e
        )

    return False


# ============================================================
# TELEGRAM TEST
# ============================================================

def telegram_test():

    message = (
        "🟢 MEXC RADAR V6 AKTİF\n\n"
        "Telegram bağlantısı çalışıyor.\n"
        "GitHub Actions çalışıyor.\n\n"
        "Sadece MEXC Crypto Futures\n"
        "Stock / ETF / Index yok\n\n"
        "🟢 Erken hareket\n"
        "🔻 Pump sonrası düşüş\n\n"
        "Minimum skor: 60\n"
        "Maksimum sinyal: 5"
    )

    return send_telegram(message)


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

    except Exception as e:

        print(
            "Sent okuma hatası:",
            e
        )

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

        print(
            "Sent yazma hatası:",
            e
        )


# ============================================================
# FUTURES CONTRACTS
# ============================================================

def get_futures_contracts():

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

        try:

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
            ).upper()

            settle = str(
                x.get(
                    "settleCoin",
                    ""
                )
            ).upper()

            if not symbol.endswith("_USDT"):
                continue

            if quote != "USDT":
                continue

            if settle != "USDT":
                continue

            result.append(symbol)

        except Exception:

            continue

    return result


# ============================================================
# FUTURES TICKER
# ============================================================

def get_futures_tickers():

    data = get_json(
        f"{BASE}/api/v1/contract/ticker"
    )

    if not data:

        return {}

    rows = data.get(
        "data",
        []
    )

    if isinstance(
        rows,
        dict
    ):

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

            last_price = float(
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

            amount24 = float(
                x.get(
                    "amount24",
                    0
                ) or 0
            )

            volume24 = float(
                x.get(
                    "volume24",
                    0
                ) or 0
            )

            high24 = float(
                x.get(
                    "high24Price",
                    0
                ) or 0
            )

            low24 = float(
                x.get(
                    "lower24Price",
                    0
                ) or 0
            )

            result[symbol] = {

                "price":
                    last_price,

                "change":
                    change,

                "amount24":
                    amount24,

                "volume24":
                    volume24,

                "high24":
                    high24,

                "low24":
                    low24
            }

        except Exception:

            continue

    return result


# ============================================================
# KLINES
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=120
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

    if count <= 0:

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

            continue

    return candles


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:

        return None

    multiplier = (
        2 /
        (period + 1)
    )

    value = (
        sum(values[:period])
        / period
    )

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

        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

    return 100 - (
        100 /
        (1 + rs)
    )


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
# HACİM ORANI
# ============================================================

def get_volume_ratio(candles):

    if len(candles) < 22:

        return 0

    old = [
        x["volume"]
        for x in candles[-21:-1]
        if x["volume"] > 0
    ]

    if not old:

        return 0

    avg = (
        sum(old)
        / len(old)
    )

    if avg <= 0:

        return 0

    return (
        candles[-1]["volume"]
        / avg
    )


# ============================================================
# ERKEN HAREKET
# ============================================================

def analyze_early(
    symbol,
    ticker,
    c4,
    c1,
    c15
):

    if min(
        len(c4),
        len(c1),
        len(c15)
    ) < 60:

        return None

    price = ticker["price"]

    if price <= 0:

        return None

    close4 = [
        x["close"]
        for x in c4
    ]

    close1 = [
        x["close"]
        for x in c1
    ]

    close15 = [
        x["close"]
        for x in c15
    ]

    # ========================================================
    # EMA / RSI
    # ========================================================

    ema20_4 = ema(
        close4,
        20
    )

    ema20_4_prev = ema(
        close4[:-1],
        20
    )

    ema50_4 = ema(
        close4,
        50
    )

    rsi4 = rsi(
        close4
    )

    ema20_1 = ema(
        close1,
        20
    )

    ema50_1 = ema(
        close1,
        50
    )

    ema20_1_prev = ema(
        close1[:-1],
        20
    )

    rsi1 = rsi(
        close1
    )

    ema20_15 = ema(
        close15,
        20
    )

    rsi15 = rsi(
        close15
    )

    if not all([
        ema20_4,
        ema20_4_prev,
        ema50_4,
        rsi4,
        ema20_1,
        ema50_1,
        ema20_1_prev,
        rsi1,
        ema20_15,
        rsi15
    ]):

        return None

    # ========================================================
    # 4H DİP
    # ========================================================

    recent4 = c4[-13:-1]

    swing_low = min(
        x["low"]
        for x in recent4
    )

    if swing_low <= 0:

        return None

    recovery = (
        (
            price
            - swing_low
        )
        / swing_low
    ) * 100

    # Çok uzaklaşmış coin olmasın
    if recovery < 0.5:

        return None

    if recovery > 15:

        return None

    # ========================================================
    # 4H RSI
    # ========================================================

    if rsi4 < 32:

        return None

    if rsi4 > 68:

        return None

    # ========================================================
    # EMA DÖNÜŞ
    # ========================================================

    ema_rising = (
        ema20_4
        > ema20_4_prev
    )

    # Tam yükseliş şartı yerine
    # küçük tolerans bırakıyoruz.
    if not ema_rising:

        # Eğer fiyat EMA20'nin üstündeyse
        # yine aday olabilir.
        if price < ema20_4:

            return None

    # ========================================================
    # SON 3 MUM
    # ========================================================

    green4 = sum(
        1
        for x in c4[-3:]
        if x["close"] > x["open"]
    )

    if green4 < 1:

        return None

    # ========================================================
    # 1H
    # ========================================================

    if price < ema20_1 * 0.985:

        return None

    if rsi1 < 38:

        return None

    if rsi1 > 72:

        return None

    # ========================================================
    # 15M
    # ========================================================

    if price < ema20_15 * 0.985:

        return None

    if rsi15 < 40:

        return None

    if rsi15 > 75:

        return None

    # ========================================================
    # HACİM
    # ========================================================

    volume_ratio = get_volume_ratio(
        c15
    )

    # Hacim hiç yoksa direkt eleme.
    # Ama 2x şart koşmuyoruz.
    if volume_ratio < 0.65:

        return None

    # ========================================================
    # SKOR
    # ========================================================

    score = 0

    # Dipten dönüş
    if 0.5 <= recovery <= 4:

        score += 22

    elif recovery <= 7:

        score += 17

    elif recovery <= 10:

        score += 12

    else:

        score += 6

    # EMA dönüş
    if ema_rising:

        score += 15

    else:

        score += 5

    # 4H EMA20
    if price >= ema20_4:

        score += 15

    elif price >= ema20_4 * 0.995:

        score += 10

    else:

        score += 5

    # EMA50
    if price > ema50_4:

        score += 8

    # RSI
    if 40 <= rsi4 <= 58:

        score += 15

    elif 35 <= rsi4 < 40:

        score += 10

    elif 58 < rsi4 <= 68:

        score += 8

    # Mum
    if green4 == 3:

        score += 10

    elif green4 == 2:

        score += 8

    else:

        score += 4

    # 1H EMA
    if price >= ema20_1:

        score += 10

    else:

        score += 5

    # 15M
    if price >= ema20_15:

        score += 10

    else:

        score += 5

    # Hacim
    if volume_ratio >= 2:

        score += 10

    elif volume_ratio >= 1.3:

        score += 7

    elif volume_ratio >= 1:

        score += 4

    score = min(
        score,
        100
    )

    if score < MIN_SCORE:

        return None

    # ========================================================
    # SINIF
    # ========================================================

    if score >= 75:

        title = "🟢 GÜÇLÜ HAREKET ADAYI"

    else:

        title = "🟡 ERKEN HAREKET ADAYI"

    return {

        "type":
            "EARLY",

        "title":
            title,

        "symbol":
            symbol,

        "score":
            score,

        "entry":
            price,

        "change":
            ticker["change"],

        "recovery":
            recovery,

        "volume_ratio":
            volume_ratio,

        "rsi4h":
            rsi4,

        "rsi1h":
            rsi1,

        "rsi15m":
            rsi15
    }


# ============================================================
# PUMP SONRASI DÜŞÜŞ
# ============================================================

def analyze_drop(
    symbol,
    ticker,
    c4,
    c1,
    c15
):

    if min(
        len(c4),
        len(c1),
        len(c15)
    ) < 60:

        return None

    price = ticker["price"]

    if price <= 0:

        return None

    close4 = [
        x["close"]
        for x in c4
    ]

    close1 = [
        x["close"]
        for x in c1
    ]

    close15 = [
        x["close"]
        for x in c15
    ]

    ema20_4 = ema(
        close4,
        20
    )

    ema20_1 = ema(
        close1,
        20
    )

    ema20_15 = ema(
        close15,
        20
    )

    rsi4 = rsi(
        close4
    )

    rsi1 = rsi(
        close1
    )

    rsi15 = rsi(
        close15
    )

    if not all([
        ema20_4,
        ema20_1,
        ema20_15,
        rsi4,
        rsi1,
        rsi15
    ]):

        return None

    # ========================================================
    # PUMP ZİRVESİ
    # ========================================================

    peak4 = max(
        x["high"]
        for x in c4[-18:-1]
    )

    peak15 = max(
        x["high"]
        for x in c15[-25:-1]
    )

    peak = max(
        peak4,
        peak15
    )

    if peak <= 0:

        return None

    drop = (
        (
            peak
            - price
        )
        / peak
    ) * 100

    # Çok küçük düşüş değil
    if drop < 2:

        return None

    # Çok çökmüş coin değil
    if drop > 18:

        return None

    # 24H halen güçlü olmalı
    if ticker["change"] < 3:

        return None

    # ========================================================
    # RSI
    # ========================================================

    if rsi15 > 65:

        return None

    if rsi1 > 70:

        return None

    # ========================================================
    # EMA
    # ========================================================

    if price > ema20_15 * 1.015:

        return None

    # ========================================================
    # HACİM
    # ========================================================

    volume_ratio = get_volume_ratio(
        c15
    )

    # ========================================================
    # SKOR
    # ========================================================

    score = 0

    # Zirveden düşüş
    if 2 <= drop <= 5:

        score += 25

    elif drop <= 8:

        score += 22

    elif drop <= 12:

        score += 16

    else:

        score += 10

    # 24H pump gücü
    change = ticker["change"]

    if change >= 20:

        score += 25

    elif change >= 10:

        score += 20

    elif change >= 5:

        score += 15

    else:

        score += 8

    # 15M RSI
    if rsi15 <= 48:

        score += 15

    elif rsi15 <= 55:

        score += 10

    else:

        score += 5

    # EMA düşüş
    if price < ema20_15:

        score += 10

    if price < ema20_1:

        score += 10

    # Hacim
    if volume_ratio >= 1.5:

        score += 10

    elif volume_ratio >= 1.1:

        score += 6

    elif volume_ratio >= 0.8:

        score += 3

    score = min(
        score,
        100
    )

    if score < MIN_SCORE:

        return None

    return {

        "type":
            "DROP",

        "title":
            "🔻 PUMP SONRASI DÜŞÜŞ ADAYI",

        "symbol":
            symbol,

        "score":
            score,

        "entry":
            price,

        "change":
            change,

        "drop":
            drop,

        "volume_ratio":
            volume_ratio,

        "rsi4h":
            rsi4,

        "rsi1h":
            rsi1,

        "rsi15m":
            rsi15
    }


# ============================================================
# COIN ANALİZ
# ============================================================

def analyze_symbol(item):

    symbol, ticker = item

    try:

        c4 = get_klines(
            symbol,
            "Hour4",
            120
        )

        c1 = get_klines(
            symbol,
            "Min60",
            120
        )

        c15 = get_klines(
            symbol,
            "Min15",
            120
        )

        if not c4:

            return []

        if not c1:

            return []

        if not c15:

            return []

        results = []

        # ====================================================
        # EARLY
        # ====================================================

        early = analyze_early(
            symbol,
            ticker,
            c4,
            c1,
            c15
        )

        if early:

            results.append(
                early
            )

        # ====================================================
        # DROP
        # ====================================================

        drop = analyze_drop(
            symbol,
            ticker,
            c4,
            c1,
            c15
        )

        if drop:

            results.append(
                drop
            )

        return results

    except Exception as e:

        print(
            symbol,
            "ANALİZ HATASI:",
            e
        )

        return []


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def format_signal(x):

    entry = x["entry"]

    # ========================================================
    # EARLY = LONG
    # ========================================================

    if x["type"] == "EARLY":

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

        stop = (
            entry
            * (1 - STOP_PCT / 100)
        )

        extra = (
            f"📈 4H dipten dönüş: "
            f"+{x['recovery']:.2f}%"
        )

        direction = "🟢 YÖN: YUKARI"

    # ========================================================
    # DROP = SHORT
    # ========================================================

    else:

        # Düşüşte TP aşağıda
        tp1 = (
            entry
            * (1 - TP1_PCT / 100)
        )

        tp2 = (
            entry
            * (1 - TP2_PCT / 100)
        )

        tp3 = (
            entry
            * (1 - TP3_PCT / 100)
        )

        # Stop yukarıda
        stop = (
            entry
            * (1 + STOP_PCT / 100)
        )

        extra = (
            f"📉 Zirveden düşüş: "
            f"-{x['drop']:.2f}%"
        )

        direction = "🔻 YÖN: AŞAĞI"

    # ========================================================
    # MESAJ
    # ========================================================

    message = (

        f"{x['title']}\n\n"

        f"💎 {x['symbol']}\n"

        f"⭐ Skor: "
        f"{x['score']}/100\n\n"

        f"{direction}\n\n"

        f"🟢 Giriş: "
        f"{price_format(entry)}\n"

        f"🎯 TP1: "
        f"{price_format(tp1)}\n"

        f"🎯 TP2: "
        f"{price_format(tp2)}\n"

        f"🎯 TP3: "
        f"{price_format(tp3)}\n"

        f"🛑 Stop: "
        f"{price_format(stop)}\n\n"

        f"📊 24H: "
        f"{x['change']:+.2f}%\n"

        f"{extra}\n"

        f"⚡ 15M hacim: "
        f"{x['volume_ratio']:.2f}x\n\n"

        f"RSI 4H: "
        f"{x['rsi4h']:.1f}\n"

        f"RSI 1H: "
        f"{x['rsi1h']:.1f}\n"

        f"RSI 15M: "
        f"{x['rsi15m']:.1f}\n\n"

        f"📡 MEXC CRYPTO FUTURES\n"

        f"⚠️ Bu bir analiz sinyalidir."
    )

    return message


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print("")
    print("=" * 65)
    print("🚀 MEXC CRYPTO FUTURES RADAR V6")
    print("=" * 65)

    # ========================================================
    # CONTRACTS
    # ========================================================

    contracts = get_futures_contracts()

    if not contracts:

        print(
            "❌ Futures kontratları alınamadı."
        )

        send_telegram(
            "🔴 RADAR HATASI\n\n"
            "MEXC Futures kontratları alınamadı."
        )

        return

    # ========================================================
    # TICKERS
    # ========================================================

    tickers = get_futures_tickers()

    if not tickers:

        print(
            "❌ Futures ticker alınamadı."
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

        price = ticker.get(
            "price",
            0
        )

        change = ticker.get(
            "change",
            0
        )

        amount24 = ticker.get(
            "amount24",
            0
        )

        volume24 = ticker.get(
            "volume24",
            0
        )

        if price <= 0:

            continue

        # Hacim kontrolü
        #
        # amount24 veya volume24'ten
        # yeterli olanı kullanıyoruz.
        liquidity = max(
            amount24,
            volume24
        )

        if liquidity < MIN_24H_VOLUME:

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

    # Hacmi yüksek olanlar önce
    filtered.sort(
        key=lambda x: max(
            x[1].get("amount24", 0),
            x[1].get("volume24", 0)
        ),
        reverse=True
    )

    print(
        "Crypto Futures:",
        len(contracts)
    )

    print(
        "Ticker:",
        len(tickers)
    )

    print(
        "Ön filtre:",
        len(filtered)
    )

    # ========================================================
    # DETAYLI TARAMA
    # ========================================================

    if not filtered:

        print(
            "❌ Ön filtreden coin geçmedi."
        )

        return

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

                    candidates.extend(
                        result
                    )

            except Exception as e:

                print(
                    symbol,
                    "FUTURE HATA:",
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
    # AYNI COINDE SADECE EN GÜÇLÜ SİNYAL
    # ========================================================

    best = {}

    for candidate in candidates:

        symbol = candidate[
            "symbol"
        ]

        old = best.get(
            symbol
        )

        if old is None:

            best[symbol] = candidate

        elif (
            candidate["score"]
            > old["score"]
        ):

            best[symbol] = candidate

    candidates = list(
        best.values()
    )

    # ========================================================
    # SKORA GÖRE
    # ========================================================

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    print("")
    print(
        "🔥 60+ aday:",
        len(candidates)
    )

    for x in candidates[:10]:

        print(
            x["symbol"],
            x["type"],
            x["score"]
        )

    # ========================================================
    # DUPLICATE
    # ========================================================

    sent = load_sent()

    now = time.time()

    clean_sent = {}

    for key, timestamp in sent.items():

        try:

            if (
                now
                - float(timestamp)
                < DUPLICATE_HOURS * 3600
            ):

                clean_sent[key] = timestamp

        except Exception:

            pass

    sent = clean_sent

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

        signal_type = candidate[
            "type"
        ]

        duplicate_key = (
            f"{signal_type}:{symbol}"
        )

        if duplicate_key in sent:

            print(
                "⏭ DUPLICATE:",
                duplicate_key
            )

            continue

        message = format_signal(
            candidate
        )

        success = send_telegram(
            message
        )

        if success:

            sent[
                duplicate_key
            ] = now

            save_sent(
                sent
            )

            sent_count += 1

            print(
                "✅ GÖNDERİLDİ:",
                signal_type,
                symbol,
                candidate["score"]
            )

    # ========================================================
    # SONUÇ
    # ========================================================

    print("")
    print(
        "📨 Gönderilen:",
        sent_count
    )

    if not candidates:

        print(
            "Bu taramada 60+ aday bulunamadı."
        )

    print(
        "🏁 RADAR TAMAMLANDI"
    )


# ============================================================
# PROGRAM
# ============================================================

if __name__ == "__main__":

    print("")
    print("🚀 RADAR V6 BAŞLIYOR")
    print("")

    if not BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN YOK"
        )

    if not CHAT_ID:

        print(
            "❌ TELEGRAM_CHAT_ID YOK"
        )

    # Telegram test
    if BOT_TOKEN and CHAT_ID:

        telegram_test()

    try:

        scan()

    except Exception as e:

        print(
            "🔴 ANA HATA:",
            e
        )

        send_telegram(
            "🔴 PUMP RADAR ANA HATA\n\n"
            + str(e)[:500]
        )

    print("")
    print(
        "🏁 Program tamamlandı."
    )
