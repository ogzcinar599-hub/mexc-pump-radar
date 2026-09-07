import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC CRYPTO FUTURES PUMP RADAR V3
#
# 🟡 ERKEN PUMP
# 🚀 PUMP BAŞLANGICI
# 🔻 PUMP SONRASI DÜŞÜŞ
#
# SADECE MEXC CRYPTO FUTURES
# STOCK / ETF / INDEX YOK
# ============================================================


BASE = "https://contract.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================
# AYARLAR
# ============================================================

# Daha fazla normal coin taramak için düşürüldü
MIN_24H_VOLUME = 100000

# Çok çökmüş coinleri alma
MIN_24H_CHANGE = -20

# Çoktan aşırı pump yapmış coinleri erken sinyale alma
MAX_24H_CHANGE = 60


# Sinyal eşikleri
MIN_EARLY_SCORE = 58
MIN_START_SCORE = 62
MIN_DROP_SCORE = 62


# Tek taramada maksimum Telegram sinyali
MAX_SIGNALS_PER_SCAN = 5


# Aynı sinyalin tekrar gönderilme süresi
DUPLICATE_HOURS = 4


# Paralel tarama
MAX_WORKERS = 25


# ============================================================
# LONG TP / STOP
# ============================================================

LONG_TP1 = 1.8
LONG_TP2 = 3.5
LONG_TP3 = 5.5
LONG_STOP = 2.2


# ============================================================
# SHORT TP / STOP
# Pump sonrası düşüş için
# ============================================================

SHORT_TP1 = 2.0
SHORT_TP2 = 4.0
SHORT_TP3 = 6.0
SHORT_STOP = 2.5


# ============================================================
# DOSYA
# ============================================================

SENT_FILE = "sent_signals.json"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 MEXC-Pump-Radar/3.0"
})


# ============================================================
# JSON GET
# ============================================================

def get_json(url, params=None):

    try:

        response = session.get(
            url,
            params=params,
            timeout=12
        )

        if response.status_code != 200:
            return None

        data = response.json()

        if (
            isinstance(data, dict)
            and data.get("success") is False
        ):
            return None

        return data

    except Exception:

        return None


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

        print("sent okuma hatası:", e)

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

        print("sent yazma hatası:", e)


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

        if response.status_code == 200:

            print("✅ Telegram gönderildi")
            return True

        print(
            "❌ Telegram:",
            response.text[:500]
        )

    except Exception as e:

        print("❌ Telegram hata:", e)

    return False


# ============================================================
# TELEGRAM TEST
# ============================================================

def telegram_test():

    message = (

        "🟢 <b>PUMP RADAR AKTİF</b>\n\n"

        "✅ Telegram bağlantısı çalışıyor.\n"
        "✅ GitHub Actions çalışıyor.\n\n"

        "🚫 Stock / ETF / Index yok\n"
        "💎 Sadece MEXC Crypto Futures\n\n"

        "🟡 Erken pump\n"
        "🚀 Pump başlangıcı\n"
        "🔻 Pump sonrası düşüş\n\n"

        "🔎 4H dip + dönüş\n"
        "📈 1H trend\n"
        "⚡ 15M momentum + hacim"
    )

    return send_telegram(message)


# ============================================================
# STOCK / ETF / INDEX FİLTRESİ
# ============================================================

def is_crypto_contract(x):

    symbol = str(
        x.get("symbol", "")
    ).upper()

    base_coin = str(
        x.get("baseCoin", "")
    ).upper()

    quote = str(
        x.get("quoteCoin", "")
    ).upper()

    settle = str(
        x.get("settleCoin", "")
    ).upper()

    combined = (
        symbol
        + " "
        + base_coin
    )

    # --------------------------------------------------------
    # SADECE USDT
    # --------------------------------------------------------

    if not symbol.endswith("_USDT"):
        return False

    if quote != "USDT":
        return False

    if settle != "USDT":
        return False

    # --------------------------------------------------------
    # STOCK / ETF / INDEX İSİMLERİ
    # --------------------------------------------------------

    blocked = [

        "ETF",
        "STOCK",
        "INDEX",
        "INDEXED",
        "SP500",
        "SPX",
        "NASDAQ",
        "DOW",
        "NYSE",
        "GOLD",
        "SILVER",
        "OIL",
        "WTI",
        "BRENT",
        "USDJPY",
        "EURUSD",
        "GBPUSD",
        "XAU",
        "XAG"
    ]

    for word in blocked:

        if word in combined:

            return False

    return True


# ============================================================
# FUTURES CONTRACT
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

            if not is_crypto_contract(x):
                continue

            symbol = x.get(
                "symbol",
                ""
            )

            if symbol:
                result.append(symbol)

        except Exception:

            continue

    return list(
        dict.fromkeys(result)
    )


# ============================================================
# TICKER
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

    if isinstance(rows, dict):
        rows = [rows]

    result = {}

    for x in rows:

        try:

            symbol = str(
                x.get("symbol", "")
            ).upper()

            if not symbol.endswith("_USDT"):
                continue

            result[symbol] = {

                "price": float(
                    x.get(
                        "lastPrice",
                        0
                    ) or 0
                ),

                "change": float(
                    x.get(
                        "riseFallRate",
                        0
                    ) or 0
                ) * 100,

                "volume": float(
                    x.get(
                        "amount24",
                        0
                    ) or 0
                ),

                "volume_contract": float(
                    x.get(
                        "volume24",
                        0
                    ) or 0
                ),

                "high24": float(
                    x.get(
                        "high24Price",
                        0
                    ) or 0
                ),

                "low24": float(
                    x.get(
                        "lower24Price",
                        0
                    ) or 0
                )
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

    if count < 60:
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

                "open": float(opens[i]),

                "high": float(highs[i]),

                "low": float(lows[i]),

                "close": float(closes[i]),

                "volume": float(volumes[i])
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

    multiplier = 2 / (
        period + 1
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

def rsi(values, period=14):

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
            losses.append(abs(change))

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
        100 / (1 + rs)
    )


# ============================================================
# HACİM ORANI
# ============================================================

def volume_ratio(candles):

    if len(candles) < 25:
        return 0

    old = [
        x["volume"]
        for x in candles[-21:-1]
        if x["volume"] > 0
    ]

    if not old:
        return 0

    avg = sum(old) / len(old)

    if avg <= 0:
        return 0

    return (
        candles[-1]["volume"]
        / avg
    )


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
# 🟡 ERKEN PUMP
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

    # --------------------------------------------------------
    # İNDİKATÖRLER
    # --------------------------------------------------------

    ema20_4 = ema(close4, 20)
    ema50_4 = ema(close4, 50)

    ema20_4_prev = ema(
        close4[:-2],
        20
    )

    ema20_1 = ema(close1, 20)
    ema50_1 = ema(close1, 50)

    ema20_1_prev = ema(
        close1[:-2],
        20
    )

    ema20_15 = ema(close15, 20)

    rsi4 = rsi(close4)
    rsi1 = rsi(close1)
    rsi15 = rsi(close15)

    if not all([
        ema20_4,
        ema50_4,
        ema20_4_prev,
        ema20_1,
        ema50_1,
        ema20_1_prev,
        ema20_15,
        rsi4,
        rsi1,
        rsi15
    ]):

        return None

    # --------------------------------------------------------
    # 4H DİP
    # --------------------------------------------------------

    recent4 = c4[-18:-1]

    swing_low = min(
        x["low"]
        for x in recent4
    )

    if swing_low <= 0:
        return None

    recovery = (
        (price - swing_low)
        / swing_low
    ) * 100

    # Çok uzaklaşmış coinleri alma
    if recovery < 0.3:
        return None

    if recovery > 15:
        return None

    # --------------------------------------------------------
    # 4H SON MUM YAPISI
    # --------------------------------------------------------

    green4 = sum(
        1
        for x in c4[-4:]
        if x["close"] > x["open"]
    )

    # En azından son 4 mumdan biri güçlü olmalı
    if green4 < 1:
        return None

    # --------------------------------------------------------
    # 15M MOMENTUM
    # --------------------------------------------------------

    momentum15 = (
        (
            close15[-1]
            / close15[-5]
        ) - 1
    ) * 100

    # Son 1 saat çok kötü ise alma
    if momentum15 < -2.5:
        return None

    # Çoktan uçmuşsa erken pump değildir
    if momentum15 > 10:
        return None

    # --------------------------------------------------------
    # 1H MOMENTUM
    # --------------------------------------------------------

    momentum1 = (
        (
            close1[-1]
            / close1[-4]
        ) - 1
    ) * 100

    if momentum1 < -5:
        return None

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    vr = volume_ratio(c15)

    # --------------------------------------------------------
    # SKOR
    # --------------------------------------------------------

    score = 0

    # 4H dip
    if 0.3 <= recovery <= 4:
        score += 20

    elif recovery <= 7:
        score += 16

    elif recovery <= 11:
        score += 10

    else:
        score += 5

    # 4H EMA dönüş
    if ema20_4 > ema20_4_prev:
        score += 15

    # Fiyat 4H EMA20'ye yakın
    if price >= ema20_4:
        score += 12

    elif price >= ema20_4 * 0.985:
        score += 8

    # EMA50 üzerinde / yakın
    if price >= ema50_4:
        score += 8

    elif price >= ema50_4 * 0.97:
        score += 5

    # 4H RSI
    if 40 <= rsi4 <= 58:
        score += 12

    elif 35 <= rsi4 <= 63:
        score += 7

    # 1H EMA dönüş
    if ema20_1 > ema20_1_prev:
        score += 10

    # 1H fiyat
    if price >= ema20_1:
        score += 8

    # 15M momentum
    if 0.2 <= momentum15 <= 3:
        score += 10

    elif momentum15 <= 5:
        score += 6

    # 15M RSI
    if 45 <= rsi15 <= 65:
        score += 7

    # Hacim
    if vr >= 2:
        score += 12

    elif vr >= 1.5:
        score += 9

    elif vr >= 1.15:
        score += 5

    # 24H çok şişmemişse bonus
    change = ticker["change"]

    if 0 <= change <= 12:
        score += 8

    elif -5 <= change < 0:
        score += 5

    elif 12 < change <= 25:
        score += 3

    if score < MIN_EARLY_SCORE:
        return None

    return {

        "type": "EARLY",

        "title":
            "🟡 ERKEN PUMP ADAYI",

        "symbol":
            symbol,

        "score":
            min(score, 100),

        "entry":
            price,

        "change":
            change,

        "recovery":
            recovery,

        "momentum15":
            momentum15,

        "volume_ratio":
            vr,

        "rsi4h":
            rsi4,

        "rsi1h":
            rsi1,

        "rsi15m":
            rsi15
    }


# ============================================================
# 🚀 PUMP BAŞLANGICI
# ============================================================

def analyze_start(
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

    close1 = [
        x["close"]
        for x in c1
    ]

    close15 = [
        x["close"]
        for x in c15
    ]

    ema20_1 = ema(
        close1,
        20
    )

    ema20_15 = ema(
        close15,
        20
    )

    rsi1 = rsi(
        close1
    )

    rsi15 = rsi(
        close15
    )

    if not all([
        ema20_1,
        ema20_15,
        rsi1,
        rsi15
    ]):

        return None

    # Son 3 mum momentum
    momentum3 = (
        (
            close15[-1]
            / close15[-4]
        ) - 1
    ) * 100

    # Son 8 mum
    momentum8 = (
        (
            close15[-1]
            / close15[-9]
        ) - 1
    ) * 100

    # Çok büyük hareket artık başlangıç değil
    if momentum3 < 0.8:
        return None

    if momentum3 > 12:
        return None

    if momentum8 < 0.5:
        return None

    # 15M son direnç
    previous = c15[-13:-1]

    resistance = max(
        x["high"]
        for x in previous
    )

    breakout_distance = (
        (
            price
            - resistance
        )
        / resistance
    ) * 100

    vr = volume_ratio(c15)

    # Hacim şartı
    if vr < 1.15:
        return None

    score = 0

    # Momentum
    if 1 <= momentum3 <= 4:
        score += 25

    elif momentum3 <= 7:
        score += 18

    else:
        score += 10

    # 15M EMA
    if price > ema20_15:
        score += 15

    # 1H EMA
    if price > ema20_1:
        score += 15

    # 15M RSI
    if 50 <= rsi15 <= 68:
        score += 15

    elif rsi15 < 72:
        score += 8

    # 1H RSI
    if 45 <= rsi1 <= 65:
        score += 10

    # Hacim
    if vr >= 2.5:
        score += 15

    elif vr >= 1.7:
        score += 11

    elif vr >= 1.15:
        score += 6

    # Dirence yakınlık
    if -1 <= breakout_distance <= 2:
        score += 12

    elif breakout_distance < 4:
        score += 7

    # 24H
    if 0 <= ticker["change"] <= 25:
        score += 8

    elif ticker["change"] <= 40:
        score += 4

    if score < MIN_START_SCORE:
        return None

    return {

        "type": "START",

        "title":
            "🚀 PUMP BAŞLANGICI",

        "symbol":
            symbol,

        "score":
            min(score, 100),

        "entry":
            price,

        "change":
            ticker["change"],

        "momentum15":
            momentum3,

        "volume_ratio":
            vr,

        "rsi4h":
            rsi(
                [
                    x["close"]
                    for x in c4
                ]
            ),

        "rsi1h":
            rsi1,

        "rsi15m":
            rsi15
    }


# ============================================================
# 🔻 PUMP SONRASI DÜŞÜŞ
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

    close1 = [
        x["close"]
        for x in c1
    ]

    close15 = [
        x["close"]
        for x in c15
    ]

    ema20_1 = ema(
        close1,
        20
    )

    ema20_15 = ema(
        close15,
        20
    )

    rsi1 = rsi(
        close1
    )

    rsi15 = rsi(
        close15
    )

    if not all([
        ema20_1,
        ema20_15,
        rsi1,
        rsi15
    ]):

        return None

    # --------------------------------------------------------
    # PUMP ZİRVESİ
    # --------------------------------------------------------

    peak15 = max(
        x["high"]
        for x in c15[-25:-1]
    )

    peak1 = max(
        x["high"]
        for x in c1[-8:-1]
    )

    peak = max(
        peak15,
        peak1
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
    if drop < 3:
        return None

    # Çok çökmüşse artık geç
    if drop > 18:
        return None

    # Pump gerçekten güçlü olmalı
    if ticker["change"] < 5:
        return None

    # 15M aşağı momentum
    momentum15 = (
        (
            close15[-1]
            / close15[-5]
        ) - 1
    ) * 100

    if momentum15 > 1:
        return None

    vr = volume_ratio(c15)

    score = 0

    # Zirveden düşüş
    if 3 <= drop <= 6:
        score += 25

    elif drop <= 9:
        score += 20

    elif drop <= 13:
        score += 15

    else:
        score += 8

    # Pump büyüklüğü
    change = ticker["change"]

    if change >= 25:
        score += 25

    elif change >= 15:
        score += 20

    elif change >= 8:
        score += 15

    else:
        score += 8

    # 15M EMA kırılması
    if price < ema20_15:
        score += 15

    # 1H EMA
    if price < ema20_1:
        score += 10

    # RSI
    if rsi15 <= 50:
        score += 12

    elif rsi15 <= 58:
        score += 7

    # Hacim
    if vr >= 2:
        score += 13

    elif vr >= 1.3:
        score += 9

    elif vr >= 1.05:
        score += 5

    if score < MIN_DROP_SCORE:
        return None

    return {

        "type": "DROP",

        "title":
            "🔻 PUMP SONRASI DÜŞÜŞ",

        "symbol":
            symbol,

        "score":
            min(score, 100),

        "entry":
            price,

        "change":
            change,

        "drop":
            drop,

        "momentum15":
            momentum15,

        "volume_ratio":
            vr,

        "rsi4h":
            rsi(
                [
                    x["close"]
                    for x in c4
                ]
            ),

        "rsi1h":
            rsi1,

        "rsi15m":
            rsi15
    }


# ============================================================
# COIN ANALİZİ
# ============================================================

def analyze_symbol(item):

    symbol, ticker = item

    try:

        c4 = get_klines(
            symbol,
            "Hour4",
            100
        )

        c1 = get_klines(
            symbol,
            "Min60",
            100
        )

        c15 = get_klines(
            symbol,
            "Min15",
            100
        )

        if not c4 or not c1 or not c15:
            return []

        results = []

        # ----------------------------------------------------
        # ERKEN
        # ----------------------------------------------------

        early = analyze_early(
            symbol,
            ticker,
            c4,
            c1,
            c15
        )

        if early:
            results.append(early)

        # ----------------------------------------------------
        # PUMP BAŞLANGICI
        # ----------------------------------------------------

        start = analyze_start(
            symbol,
            ticker,
            c4,
            c1,
            c15
        )

        if start:
            results.append(start)

        # ----------------------------------------------------
        # PUMP SONRASI DÜŞÜŞ
        # ----------------------------------------------------

        drop = analyze_drop(
            symbol,
            ticker,
            c4,
            c1,
            c15
        )

        if drop:
            results.append(drop)

        return results

    except Exception as e:

        print(
            symbol,
            "analiz hatası:",
            e
        )

        return []


# ============================================================
# TELEGRAM SİNYAL
# ============================================================

def format_signal(x):

    entry = x["entry"]

    # --------------------------------------------------------
    # LONG
    # --------------------------------------------------------

    if x["type"] in [
        "EARLY",
        "START"
    ]:

        tp1 = entry * (
            1 + LONG_TP1 / 100
        )

        tp2 = entry * (
            1 + LONG_TP2 / 100
        )

        tp3 = entry * (
            1 + LONG_TP3 / 100
        )

        stop = entry * (
            1 - LONG_STOP / 100
        )

        direction = "🟢 LONG"

        trade = (
            f"🟢 Giriş: "
            f"<b>{price_format(entry)}</b>\n"
            f"🎯 TP1: "
            f"{price_format(tp1)}\n"
            f"🎯 TP2: "
            f"{price_format(tp2)}\n"
            f"🎯 TP3: "
            f"{price_format(tp3)}\n"
            f"🛑 Stop: "
            f"{price_format(stop)}\n"
        )

    # --------------------------------------------------------
    # SHORT
    # --------------------------------------------------------

    else:

        tp1 = entry * (
            1 - SHORT_TP1 / 100
        )

        tp2 = entry * (
            1 - SHORT_TP2 / 100
        )

        tp3 = entry * (
            1 - SHORT_TP3 / 100
        )

        stop = entry * (
            1 + SHORT_STOP / 100
        )

        direction = "🔴 SHORT"

        trade = (
            f"🔴 Giriş: "
            f"<b>{price_format(entry)}</b>\n"
            f"🎯 TP1: "
            f"{price_format(tp1)}\n"
            f"🎯 TP2: "
            f"{price_format(tp2)}\n"
            f"🎯 TP3: "
            f"{price_format(tp3)}\n"
            f"🛑 Stop: "
            f"{price_format(stop)}\n"
        )

    # --------------------------------------------------------
    # EXTRA
    # --------------------------------------------------------

    if x["type"] == "DROP":

        extra = (
            f"📉 Zirveden: "
            f"-{x['drop']:.2f}%\n"
        )

    else:

        extra = (
            f"⚡ 15M momentum: "
            f"{x['momentum15']:+.2f}%\n"
        )

    return (

        f"{x['title']}\n\n"

        f"💎 <b>{x['symbol']}</b>\n"

        f"{direction}\n"

        f"⭐ <b>Skor: "
        f"{x['score']}/100</b>\n\n"

        f"{trade}\n"

        f"📊 24H: "
        f"{x['change']:+.2f}%\n"

        f"{extra}"

        f"⚡ 15M hacim: "
        f"{x['volume_ratio']:.2f}x\n\n"

        f"🔎 4H RSI: "
        f"{x['rsi4h']:.1f}\n"

        f"🔎 1H RSI: "
        f"{x['rsi1h']:.1f}\n"

        f"🔎 15M RSI: "
        f"{x['rsi15m']:.1f}\n\n"

        "📡 <b>MEXC CRYPTO FUTURES</b>\n"

        "⚠️ <i>Analiz sinyalidir, "
        "otomatik işlem açmaz.</i>"
    )


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print("")
    print("=" * 65)
    print("🚀 MEXC CRYPTO FUTURES PUMP RADAR V3")
    print("=" * 65)


    # ========================================================
    # CONTRACT
    # ========================================================

    contracts = get_futures_contracts()

    if not contracts:

        print(
            "❌ Futures kontratları alınamadı."
        )

        send_telegram(
            "🔴 <b>RADAR HATASI</b>\n\n"
            "MEXC Futures kontratları alınamadı."
        )

        return


    # ========================================================
    # TICKER
    # ========================================================

    tickers = get_futures_tickers()

    if not tickers:

        print(
            "❌ Futures ticker alınamadı."
        )

        send_telegram(
            "🔴 <b>RADAR HATASI</b>\n\n"
            "MEXC Futures ticker alınamadı."
        )

        return


    # ========================================================
    # ÖN FİLTRE
    # ========================================================

    filtered = []

    for symbol in contracts:

        ticker = tickers.get(symbol)

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


    # Hacme göre
    filtered.sort(
        key=lambda x: x[1]["volume"],
        reverse=True
    )


    print("")
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


    if not filtered:

        print(
            "❌ Ön filtreden coin geçmedi."
        )

        return


    # ========================================================
    # DETAYLI TARAMA
    # ========================================================

    candidates = []

    print(
        "🔍 Detaylı tarama:",
        len(filtered),
        "coin"
    )


    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {}

        for item in filtered:

            future = executor.submit(
                analyze_symbol,
                item
            )

            future_map[
                future
            ] = item[0]

        total = len(
            future_map
        )

        for i, future in enumerate(
            as_completed(future_map),
            1
        ):

            symbol = future_map[
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
                    "future hata:",
                    e
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
    # AYNI COİNDE EN İYİ SİNYAL
    # ========================================================

    best = {}

    for candidate in candidates:

        key = (
            candidate["symbol"],
            candidate["type"]
        )

        old = best.get(key)

        if old is None:

            best[key] = candidate

        elif (
            candidate["score"]
            > old["score"]
        ):

            best[key] = candidate


    candidates = list(
        best.values()
    )


    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )


    print("")
    print(
        "🔥 Toplam güçlü sinyal:",
        len(candidates)
    )


    # ========================================================
    # SİNYAL TİPLERİ
    # ========================================================

    early_count = sum(
        1
        for x in candidates
        if x["type"] == "EARLY"
    )

    start_count = sum(
        1
        for x in candidates
        if x["type"] == "START"
    )

    drop_count = sum(
        1
        for x in candidates
        if x["type"] == "DROP"
    )


    print(
        "🟡 Erken:",
        early_count
    )

    print(
        "🚀 Başlangıç:",
        start_count
    )

    print(
        "🔻 Düşüş:",
        drop_count
    )


    # ========================================================
    # SENT DOSYASI
    # ========================================================

    sent = load_sent()

    now = time.time()

    clean_sent = {}

    for key, timestamp in sent.items():

        try:

            if (
                now - float(timestamp)
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
    # SONUÇ
    # ========================================================

    if not candidates:

        print("")
        print(
            "⚠️ Bu taramada güçlü sinyal yok."
        )

        # Telegram'a her taramada boş mesaj atma
        # İstersen burayı aktif edebiliriz.

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
    print("🚀 RADAR BAŞLIYOR")
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

            "🔴 <b>PUMP RADAR ANA HATA</b>\n\n"

            f"<code>"
            f"{str(e)[:500]}"
            f"</code>"
        )


    print("")
    print(
        "🏁 Radar taraması tamamlandı."
    )
