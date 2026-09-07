import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC CRYPTO FUTURES PUMP RADAR V6
#
# SADECE:
# ✅ MEXC USDT CRYPTO FUTURES
#
# ARAMA:
# 🟡 ERKEN PUMP
# 🔻 PUMP SONRASI DÜŞÜŞ
#
# ZAMAN DİLİMLERİ:
# 4H = ANA YAPI
# 1H = TREND
# 15M = MOMENTUM
# ============================================================


BASE = "https://contract.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================
# AYARLAR
# ============================================================

# 24H minimum hacim
MIN_24H_VOLUME = 200000

# 24H değişim
MIN_24H_CHANGE = -30
MAX_24H_CHANGE = 100


# ============================================================
# SKOR
# ============================================================

# Normal güçlü sinyal
STRONG_SCORE = 65

# Eğer hiç güçlü sinyal yoksa kullanılacak
FALLBACK_SCORE = 58


# Bir taramada maksimum sinyal
MAX_SIGNALS_PER_SCAN = 4


# Aynı sinyalin tekrar gönderilme süresi
DUPLICATE_HOURS = 4


# Paralel analiz
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
    "User-Agent": "Mozilla/5.0 MEXC-Pump-Radar/6.0"
})


# ============================================================
# JSON GET
# ============================================================

def get_json(url, params=None):

    try:

        response = session.get(
            url,
            params=params,
            timeout=15
        )

        if response.status_code != 200:
            return None

        data = response.json()

        if isinstance(data, dict):

            if data.get("success") is False:
                return None

        return data

    except Exception as e:

        print(
            "GET hata:",
            str(e)[:150]
        )

        return None


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

                data = json.load(f)

                if isinstance(data, dict):
                    return data

    except Exception as e:

        print(
            "sent okuma hatası:",
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
            "sent yazma hatası:",
            e
        )


# ============================================================
# TELEGRAM
#
# HTML KULLANMIYORUZ.
# Böylece:
# "can't parse entities"
# hatası oluşmaz.
# ============================================================

def send_telegram(text):

    if not BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN eksik"
        )

        return False

    if not CHAT_ID:

        print(
            "❌ TELEGRAM_CHAT_ID eksik"
        )

        return False


    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )


    payload = {

        "chat_id": CHAT_ID,

        "text": text,

        "disable_web_page_preview": True
    }


    try:

        response = session.post(
            url,
            json=payload,
            timeout=15
        )


        if response.status_code == 200:

            print(
                "✅ Telegram gönderildi"
            )

            return True


        print(
            "❌ Telegram:",
            response.text[:500]
        )


    except Exception as e:

        print(
            "❌ Telegram hata:",
            e
        )


    return False


# ============================================================
# TELEGRAM TEST
# ============================================================

def telegram_test():

    message = (

        "🟢 PUMP RADAR AKTİF\n\n"

        "✅ Telegram bağlantısı çalışıyor.\n"
        "✅ GitHub Actions çalışıyor.\n\n"

        "🚫 Stock / ETF / Index yok\n"
        "💎 Sadece MEXC Crypto Futures\n\n"

        "🔎 4H dip + dönüş\n"
        "📈 1H trend\n"
        "⚡ 15M momentum + hacim\n"
        "🔻 Pump sonrası düşüş"
    )

    return send_telegram(
        message
    )


# ============================================================
# FUTURES CONTRACTLARI
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
            ).upper()


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


            # =================================================
            # SADECE USDT FUTURES
            # =================================================

            if not symbol.endswith(
                "_USDT"
            ):
                continue


            if quote != "USDT":
                continue


            if settle != "USDT":
                continue


            result.append(
                symbol
            )


        except Exception:

            continue


    return list(
        dict.fromkeys(result)
    )


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

            symbol = str(
                x.get(
                    "symbol",
                    ""
                )
            ).upper()


            if not symbol.endswith(
                "_USDT"
            ):

                continue


            price = float(
                x.get(
                    "lastPrice",
                    0
                )
                or 0
            )


            change = float(
                x.get(
                    "riseFallRate",
                    0
                )
                or 0
            ) * 100


            volume = float(
                x.get(
                    "amount24",
                    0
                )
                or 0
            )


            volume_contract = float(
                x.get(
                    "volume24",
                    0
                )
                or 0
            )


            high24 = float(
                x.get(
                    "high24Price",
                    0
                )
                or 0
            )


            low24 = float(
                x.get(
                    "lower24Price",
                    0
                )
                or 0
            )


            if price <= 0:
                continue


            result[symbol] = {

                "price":
                    price,

                "change":
                    change,

                "volume":
                    volume,

                "volume_contract":
                    volume_contract,

                "high24":
                    high24,

                "low24":
                    low24
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


    if not isinstance(
        market,
        dict
    ):

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


    if count < 10:
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

def ema(
    values,
    period
):

    if len(values) < period:
        return None


    multiplier = (
        2 /
        (period + 1)
    )


    value = (
        sum(
            values[:period]
        )
        / period
    )


    for price in values[period:]:

        value = (
            (
                price - value
            )
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

            gains.append(
                change
            )

            losses.append(0)

        else:

            gains.append(0)

            losses.append(
                abs(change)
            )


    avg_gain = (
        sum(
            gains[:period]
        )
        / period
    )


    avg_loss = (
        sum(
            losses[:period]
        )
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
# 15M HACİM ORANI
# ============================================================

def volume_ratio_15m(c15):

    if len(c15) < 22:
        return 0


    volumes = [

        x["volume"]

        for x in c15[-21:-1]

        if x["volume"] > 0
    ]


    if not volumes:
        return 0


    avg_volume = (
        sum(volumes)
        / len(volumes)
    )


    if avg_volume <= 0:
        return 0


    return (
        c15[-1]["volume"]
        / avg_volume
    )


# ============================================================
# ERKEN PUMP
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


    price = ticker["price"]


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
    # 4H DİP / DÖNÜŞ
    # ========================================================

    recent4 = c4[-13:-1]


    if not recent4:
        return None


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


    # Çok dipte veya çok yükselmiş coinleri alma
    if recovery < 0.5:
        return None


    if recovery > 13:
        return None


    # ========================================================
    # RSI
    # ========================================================

    if rsi4 < 32:
        return None


    if rsi4 > 68:
        return None


    # ========================================================
    # EMA DÖNÜŞ
    # ========================================================

    ema_turn = (
        ema20_4
        > ema20_4_prev
    )


    # ========================================================
    # SON 3 MUM
    # ========================================================

    green4 = sum(

        1

        for x in c4[-3:]

        if x["close"]
        > x["open"]
    )


    # En az 1 yeşil mum
    if green4 < 1:
        return None


    # ========================================================
    # 1H
    # ========================================================

    if price < ema20_1 * 0.99:
        return None


    ema1_turn = (
        ema20_1
        > ema20_1_prev
    )


    if rsi1 < 38:
        return None


    if rsi1 > 72:
        return None


    # ========================================================
    # 15M
    # ========================================================

    if price < ema20_15 * 0.985:
        return None


    if rsi15 < 38:
        return None


    if rsi15 > 75:
        return None


    # ========================================================
    # HACİM
    # ========================================================

    volume_ratio = (
        volume_ratio_15m(c15)
    )


    # ========================================================
    # SKOR
    # ========================================================

    score = 0


    # --------------------------------------------------------
    # DİPTEN DÖNÜŞ
    # --------------------------------------------------------

    if 0.5 <= recovery <= 4:

        score += 20

    elif recovery <= 7:

        score += 16

    elif recovery <= 10:

        score += 10

    else:

        score += 5


    # --------------------------------------------------------
    # EMA DÖNÜŞ
    # --------------------------------------------------------

    if ema_turn:
        score += 15


    # --------------------------------------------------------
    # 4H EMA
    # --------------------------------------------------------

    if price >= ema20_4:

        score += 12

    elif price >= ema20_4 * 0.995:

        score += 8


    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 40 <= rsi4 <= 58:

        score += 14

    elif 35 <= rsi4 <= 63:

        score += 10


    # --------------------------------------------------------
    # YEŞİL MUM
    # --------------------------------------------------------

    if green4 == 3:

        score += 10

    elif green4 == 2:

        score += 8

    elif green4 == 1:

        score += 4


    # --------------------------------------------------------
    # 1H TREND
    # --------------------------------------------------------

    if price >= ema20_1:

        score += 8


    if ema1_turn:

        score += 5


    # --------------------------------------------------------
    # 15M MOMENTUM
    # --------------------------------------------------------

    if price >= ema20_15:

        score += 6


    if 42 <= rsi15 <= 65:

        score += 5


    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    if volume_ratio >= 2:

        score += 10

    elif volume_ratio >= 1.5:

        score += 7

    elif volume_ratio >= 1.1:

        score += 4


    score = min(
        score,
        100
    )


    return {

        "type":
            "EARLY",

        "title":
            "🟡 ERKEN PUMP ADAYI",

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

    rsi4 = rsi(
        close4
    )

    ema20_1 = ema(
        close1,
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
        rsi4,
        ema20_1,
        rsi1,
        ema20_15,
        rsi15
    ]):

        return None


    # ========================================================
    # SON PUMP ZİRVESİ
    # ========================================================

    peak4 = max(
        x["high"]
        for x in c4[-18:-1]
    )


    peak15 = max(
        x["high"]
        for x in c15[-17:-1]
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


    # Yeni başlayan düşüş
    if drop < 2.5:
        return None


    if drop > 16:
        return None


    # Pump gerçekten güçlü olmalı
    if ticker["change"] < 3:
        return None


    # ========================================================
    # RSI
    # ========================================================

    if rsi15 > 62:
        return None


    if rsi1 > 65:
        return None


    # ========================================================
    # EMA
    # ========================================================

    if price > ema20_15 * 1.015:
        return None


    # ========================================================
    # HACİM
    # ========================================================

    volume_ratio = (
        volume_ratio_15m(c15)
    )


    # ========================================================
    # SKOR
    # ========================================================

    score = 0


    # Zirveden düşüş
    if 2.5 <= drop <= 6:

        score += 25

    elif drop <= 9:

        score += 20

    elif drop <= 12:

        score += 13

    else:

        score += 7


    # Pump gücü
    if ticker["change"] >= 15:

        score += 25

    elif ticker["change"] >= 10:

        score += 20

    elif ticker["change"] >= 5:

        score += 15

    else:

        score += 10


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

        score += 5


    score = min(
        score,
        100
    )


    return {

        "type":
            "DROP",

        "title":
            "🔻 PUMP SONRASI DÜŞÜŞ",

        "symbol":
            symbol,

        "score":
            score,

        "entry":
            price,

        "change":
            ticker["change"],

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

        candles4 = get_klines(
            symbol,
            "Hour4",
            100
        )


        candles1 = get_klines(
            symbol,
            "Min60",
            100
        )


        candles15 = get_klines(
            symbol,
            "Min15",
            100
        )


        if not candles4:
            return []


        if not candles1:
            return []


        if not candles15:
            return []


        results = []


        # ====================================================
        # EARLY
        # ====================================================

        early = analyze_early(
            symbol,
            ticker,
            candles4,
            candles1,
            candles15
        )


        if early:

            # Normalde 58 üzeri adayları saklıyoruz
            if early["score"] >= FALLBACK_SCORE:

                results.append(
                    early
                )


        # ====================================================
        # DROP
        # ====================================================

        drop = analyze_drop(
            symbol,
            ticker,
            candles4,
            candles1,
            candles15
        )


        if drop:

            if drop["score"] >= FALLBACK_SCORE:

                results.append(
                    drop
                )


        return results


    except Exception as e:

        print(
            symbol,
            "analiz hatası:",
            str(e)[:150]
        )

        return []


# ============================================================
# TELEGRAM SİNYAL
# ============================================================

def format_signal(x):

    entry = x["entry"]


    tp1 = (
        entry
        * (
            1
            + TP1_PCT / 100
        )
    )


    tp2 = (
        entry
        * (
            1
            + TP2_PCT / 100
        )
    )


    tp3 = (
        entry
        * (
            1
            + TP3_PCT / 100
        )
    )


    stop = (
        entry
        * (
            1
            - STOP_PCT / 100
        )
    )


    if x["type"] == "DROP":

        extra = (
            f"📉 Zirveden düşüş: "
            f"-{x['drop']:.2f}%"
        )

    else:

        extra = (
            f"📈 4H dipten dönüş: "
            f"+{x['recovery']:.2f}%"
        )


    # ========================================================
    # HTML YOK
    # Telegram parser problemi olmaz.
    # ========================================================

    return (

        f"{x['title']}\n\n"

        f"💎 {x['symbol']}\n"

        f"🟢 LONG\n"

        f"⭐ Skor: {x['score']}/100\n\n"

        f"🟢 Giriş: {price_format(entry)}\n"

        f"🎯 TP1: {price_format(tp1)}\n"

        f"🎯 TP2: {price_format(tp2)}\n"

        f"🎯 TP3: {price_format(tp3)}\n"

        f"🛑 Stop: {price_format(stop)}\n\n"

        f"📊 24H: {x['change']:+.2f}%\n"

        f"{extra}\n"

        f"⚡ 15M hacim: "
        f"{x['volume_ratio']:.2f}x\n\n"

        f"🔎 4H RSI: "
        f"{x['rsi4h']:.1f}\n"

        f"🔎 1H RSI: "
        f"{x['rsi1h']:.1f}\n"

        f"🔎 15M RSI: "
        f"{x['rsi15m']:.1f}\n\n"

        f"📡 MEXC CRYPTO FUTURES\n\n"

        f"⚠️ Analiz sinyalidir, "
        f"otomatik işlem açmaz."
    )


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print("")
    print("=" * 60)

    print(
        "🚀 MEXC CRYPTO FUTURES PUMP RADAR V6"
    )

    print("=" * 60)


    # ========================================================
    # CONTRACT
    # ========================================================

    contracts = (
        get_futures_contracts()
    )


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
    # TICKER
    # ========================================================

    tickers = (
        get_futures_tickers()
    )


    if not tickers:

        print(
            "❌ Futures ticker alınamadı."
        )

        send_telegram(
            "🔴 RADAR HATASI\n\n"
            "MEXC Futures ticker alınamadı."
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


    # ========================================================
    # HACİM SIRASI
    # ========================================================

    filtered.sort(
        key=lambda x: x[1]["volume"],
        reverse=True
    )


    print(
        "💎 Crypto Futures:",
        len(contracts)
    )


    print(
        "📊 Ticker:",
        len(tickers)
    )


    print(
        "🔎 Ön filtre:",
        len(filtered)
    )


    print(
        "🔍 Detaylı tarama:",
        len(filtered),
        "coin"
    )


    if not filtered:

        print(
            "❌ Ön filtreden coin geçmedi."
        )

        return


    # ========================================================
    # DETAYLI ANALİZ
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


            futures[
                future
            ] = item[0]


        total = len(
            futures
        )


        for i, future in enumerate(
            as_completed(futures),
            1
        ):

            symbol = futures[
                future
            ]


            try:

                results = (
                    future.result()
                )


                if results:

                    candidates.extend(
                        results
                    )


            except Exception as e:

                print(
                    symbol,
                    "future hata:",
                    str(e)[:150]
                )


            if (
                i % 25 == 0
                or i == total
            ):

                print(
                    f"İlerleme: "
                    f"{i} / {total}"
                )


    # ========================================================
    # AYNI COIN TEK SİNYAL
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

            best[
                symbol
            ] = candidate


        elif (
            candidate["score"]
            > old["score"]
        ):

            best[
                symbol
            ] = candidate


    candidates = list(
        best.values()
    )


    # ========================================================
    # SKOR SIRASI
    # ========================================================

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )


    # ========================================================
    # STRONG + FALLBACK
    # ========================================================

    strong = [

        x

        for x in candidates

        if x["score"]
        >= STRONG_SCORE
    ]


    fallback = [

        x

        for x in candidates

        if FALLBACK_SCORE
        <= x["score"]
        < STRONG_SCORE
    ]


    # Önce güçlüleri kullan
    selected = strong[:MAX_SIGNALS_PER_SCAN]


    # Güçlü sinyal azsa tamamla
    if len(selected) < MAX_SIGNALS_PER_SCAN:

        remaining = (
            MAX_SIGNALS_PER_SCAN
            - len(selected)
        )


        selected.extend(
            fallback[:remaining]
        )


    # ========================================================
    # SONUÇ
    # ========================================================

    print("")
    print(
        "🔥 Toplam aday:",
        len(candidates)
    )


    print(
        "⭐ Güçlü:",
        len(strong)
    )


    print(
        "🟡 Erken:",
        sum(
            1
            for x in selected
            if x["type"] == "EARLY"
        )
    )


    print(
        "🔻 Düşüş:",
        sum(
            1
            for x in selected
            if x["type"] == "DROP"
        )
    )


    # ========================================================
    # SENT
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

                clean_sent[
                    key
                ] = timestamp


        except Exception:

            continue


    sent = clean_sent


    # ========================================================
    # TELEGRAM
    # ========================================================

    sent_count = 0


    for candidate in selected:

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
            f"{signal_type}:"
            f"{symbol}"
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
    # HİÇ GÖNDERİLMEDİYSE
    # ========================================================

    if sent_count == 0:

        print(
            "📭 Yeni Telegram sinyali gönderilmedi."
        )


    # ========================================================
    # SONUÇ
    # ========================================================

    print("")
    print(
        "📨 Gönderilen:",
        sent_count
    )


    print(
        "🏁 Radar tamamlandı."
    )


# ============================================================
# PROGRAM
# ============================================================

if __name__ == "__main__":

    print("")
    print(
        "🚀 RADAR BAŞLIYOR"
    )
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
            str(e)
        )


        send_telegram(

            "🔴 PUMP RADAR ANA HATA\n\n"

            f"{str(e)[:500]}"
        )


    print("")
    print(
        "🏁 Radar taraması tamamlandı."
    )
