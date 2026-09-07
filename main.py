import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC CRYPTO FUTURES PUMP RADAR V4
#
# 🟡 EARLY  = Pump başlamadan hemen önce / başlangıç
# 🔻 DROP   = Pump yapmış, tepe oluşturmuş ve düşüş başlamış
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

# 24H minimum işlem hacmi
MIN_24H_VOLUME = 300000

# Erken pump için çok yüksek 24H değişim istemiyoruz.
# Çünkü amacımız zaten pump başlamadan yakalamak.
EARLY_MIN_CHANGE = -5
EARLY_MAX_CHANGE = 18

# Pump sonrası düşüş için
DROP_MIN_CHANGE = 8
DROP_MAX_CHANGE = 80


# ============================================================
# SKOR
# ============================================================

MIN_EARLY_SCORE = 75
MIN_DROP_SCORE = 75


# Bir taramada maksimum sinyal
MAX_SIGNALS_PER_SCAN = 4


# Aynı sinyali tekrar gönderme
DUPLICATE_HOURS = 4


# Paralel tarama
MAX_WORKERS = 20


# ============================================================
# TP / STOP
# ============================================================

# LONG
LONG_TP1 = 1.8
LONG_TP2 = 3.5
LONG_TP3 = 5.5
LONG_STOP = 2.2


# SHORT
SHORT_TP1 = 1.8
SHORT_TP2 = 3.5
SHORT_TP3 = 5.5
SHORT_STOP = 2.2


# ============================================================
# DOSYA
# ============================================================

SENT_FILE = "sent_signals.json"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 MEXC-Pump-Radar/4.0"
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
# GET JSON
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

        if (
            isinstance(data, dict)
            and data.get("success") is False
        ):

            return None

        return data

    except Exception:

        return None


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
            response.text
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

        "🟢 <b>PUMP RADAR AKTİF V4</b>\n\n"

        "✅ Telegram bağlantısı çalışıyor.\n"
        "✅ GitHub Actions çalışıyor.\n\n"

        "🚫 Stock / ETF / Index yok\n"
        "💎 Sadece MEXC Crypto Futures\n\n"

        "🟡 Erken pump başlangıcı\n"
        "🔻 Pump sonrası düşüş\n\n"

        "📉 4H yapı\n"
        "📈 1H trend\n"
        "⚡ 15M momentum\n"
        "📊 15M hacim teyidi\n\n"

        "🎯 Güçlü sinyal filtresi aktif."
    )

    return send_telegram(message)


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

        # ----------------------------------------------------
        # SADECE USDT FUTURES
        # ----------------------------------------------------

        if not symbol.endswith("_USDT"):
            continue

        if quote != "USDT":
            continue

        if settle != "USDT":
            continue

        # ----------------------------------------------------
        # Bazı isimlerde olabilecek istenmeyen ürünler
        # ----------------------------------------------------

        bad_words = [
            "ETF",
            "INDEX",
            "STOCK",
            "UP_",
            "DOWN_",
            "3L_",
            "3S_",
            "5L_",
            "5S_"
        ]

        if any(
            word in symbol
            for word in bad_words
        ):

            continue

        result.append(symbol)

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

    if isinstance(rows, dict):

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

    market = data.get("data")

    if not market:

        return []

    opens = market.get("open", [])
    highs = market.get("high", [])
    lows = market.get("low", [])
    closes = market.get("close", [])
    volumes = market.get("vol", [])

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

    multiplier = 2 / (period + 1)

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
# MOMENTUM
# ============================================================

def momentum_percent(candles, bars=1):

    if len(candles) <= bars:

        return 0

    old = candles[-1 - bars]["close"]
    new = candles[-1]["close"]

    if old <= 0:

        return 0

    return (
        (new - old)
        / old
    ) * 100


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(candles, lookback=20):

    if len(candles) < lookback + 1:

        return 0

    volumes = [
        x["volume"]
        for x in candles[-lookback-1:-1]
        if x["volume"] > 0
    ]

    if not volumes:

        return 0

    avg = (
        sum(volumes)
        / len(volumes)
    )

    if avg <= 0:

        return 0

    return (
        candles[-1]["volume"]
        / avg
    )


# ============================================================
# 🟡 ERKEN PUMP ANALİZİ
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
    # EMA
    # --------------------------------------------------------

    ema20_4 = ema(close4, 20)
    ema50_4 = ema(close4, 50)

    ema20_1 = ema(close1, 20)
    ema50_1 = ema(close1, 50)

    ema20_15 = ema(close15, 20)

    ema20_4_prev = ema(
        close4[:-1],
        20
    )

    ema20_1_prev = ema(
        close1[:-1],
        20
    )

    ema20_15_prev = ema(
        close15[:-1],
        20
    )

    rsi4 = rsi(close4)
    rsi1 = rsi(close1)
    rsi15 = rsi(close15)

    if not all([
        ema20_4,
        ema50_4,
        ema20_1,
        ema50_1,
        ema20_15,
        ema20_4_prev,
        ema20_1_prev,
        ema20_15_prev,
        rsi4,
        rsi1,
        rsi15
    ]):

        return None

    # --------------------------------------------------------
    # 4H SWING LOW
    # --------------------------------------------------------

    recent4 = c4[-18:-1]

    if len(recent4) < 10:

        return None

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

    # Çok uzamış coin istemiyoruz
    if recovery < 1:

        return None

    if recovery > 12:

        return None

    # --------------------------------------------------------
    # 4H YAPI
    # --------------------------------------------------------

    if ema20_4 <= ema20_4_prev:

        return None

    if price < ema20_4 * 0.992:

        return None

    # EMA50'nin çok altında olmasın
    if price < ema50_4 * 0.96:

        return None

    # --------------------------------------------------------
    # 4H RSI
    # --------------------------------------------------------

    if rsi4 < 40:

        return None

    if rsi4 > 67:

        return None

    # --------------------------------------------------------
    # 1H TREND
    # --------------------------------------------------------

    if price < ema20_1:

        return None

    if ema20_1 <= ema20_1_prev:

        return None

    if ema20_1 < ema50_1 * 0.985:

        return None

    if rsi1 < 45:

        return None

    if rsi1 > 68:

        return None

    # --------------------------------------------------------
    # 15M MOMENTUM
    # --------------------------------------------------------

    mom15_1 = momentum_percent(
        c15,
        1
    )

    mom15_4 = momentum_percent(
        c15,
        4
    )

    mom15_8 = momentum_percent(
        c15,
        8
    )

    # EN ÖNEMLİ FİLTRE
    # Normal duran coin buradan elenir.

    if mom15_1 < 0.20:

        return None

    if mom15_4 < 0.30:

        return None

    if mom15_8 < 0.40:

        return None

    if price < ema20_15:

        return None

    if ema20_15 <= ema20_15_prev:

        return None

    # RSI
    if rsi15 < 48:

        return None

    if rsi15 > 72:

        return None

    # --------------------------------------------------------
    # SON 15M MUM
    # --------------------------------------------------------

    last15 = c15[-1]

    body = abs(
        last15["close"]
        - last15["open"]
    )

    candle_range = (
        last15["high"]
        - last15["low"]
    )

    if candle_range <= 0:

        return None

    body_ratio = (
        body
        / candle_range
    )

    # Çok zayıf mum istemiyoruz
    if body_ratio < 0.35:

        return None

    # Son mum kırmızı ve zayıfsa erken pump değil
    if last15["close"] <= last15["open"]:

        return None

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    vr = volume_ratio(
        c15,
        20
    )

    # Normal hacimli coin istemiyoruz
    if vr < 1.20:

        return None

    # --------------------------------------------------------
    # 24H
    # --------------------------------------------------------

    change = ticker["change"]

    if change < EARLY_MIN_CHANGE:

        return None

    if change > EARLY_MAX_CHANGE:

        return None

    # --------------------------------------------------------
    # SKOR
    # --------------------------------------------------------

    score = 0

    # Dip dönüş
    if 1 <= recovery <= 5:
        score += 15
    elif recovery <= 8:
        score += 10
    else:
        score += 5

    # 4H EMA dönüş
    score += 10

    # 4H fiyat
    if price >= ema20_4:
        score += 10

    # 1H trend
    if price > ema20_1:
        score += 10

    if ema20_1 > ema50_1:
        score += 5

    # 15M momentum
    if mom15_1 >= 0.50:
        score += 10
    elif mom15_1 >= 0.30:
        score += 7
    else:
        score += 4

    if mom15_4 >= 1.00:
        score += 10
    elif mom15_4 >= 0.60:
        score += 7
    else:
        score += 4

    # Hacim
    if vr >= 2.0:
        score += 15
    elif vr >= 1.5:
        score += 12
    elif vr >= 1.2:
        score += 8

    # Son mum
    if body_ratio >= 0.65:
        score += 10
    elif body_ratio >= 0.50:
        score += 7
    else:
        score += 4

    # RSI
    if 50 <= rsi15 <= 65:
        score += 5

    return {

        "type": "EARLY",

        "title": "🟡 ERKEN PUMP ADAYI",

        "symbol": symbol,

        "score": min(score, 100),

        "entry": price,

        "change": change,

        "recovery": recovery,

        "momentum1": mom15_1,

        "momentum4": mom15_4,

        "momentum8": mom15_8,

        "volume_ratio": vr,

        "rsi4h": rsi4,

        "rsi1h": rsi1,

        "rsi15m": rsi15
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

    ema20_4 = ema(close4, 20)
    ema20_1 = ema(close1, 20)
    ema20_15 = ema(close15, 20)

    ema20_15_prev = ema(
        close15[:-1],
        20
    )

    rsi4 = rsi(close4)
    rsi1 = rsi(close1)
    rsi15 = rsi(close15)

    if not all([
        ema20_4,
        ema20_1,
        ema20_15,
        ema20_15_prev,
        rsi4,
        rsi1,
        rsi15
    ]):

        return None

    # --------------------------------------------------------
    # PUMP ZİRVESİ
    # --------------------------------------------------------

    peak4 = max(
        x["high"]
        for x in c4[-24:-1]
    )

    peak1 = max(
        x["high"]
        for x in c1[-30:-1]
    )

    peak15 = max(
        x["high"]
        for x in c15[-32:-1]
    )

    peak = max(
        peak4,
        peak1,
        peak15
    )

    if peak <= 0:

        return None

    drop = (
        (peak - price)
        / peak
    ) * 100

    # Yeni başlamış düşüş
    if drop < 3:

        return None

    # Çok düşmüş coin artık geç
    if drop > 15:

        return None

    # --------------------------------------------------------
    # 24H PUMP GÜCÜ
    # --------------------------------------------------------

    change = ticker["change"]

    if change < DROP_MIN_CHANGE:

        return None

    if change > DROP_MAX_CHANGE:

        return None

    # --------------------------------------------------------
    # 15M DÜŞÜŞ MOMENTUMU
    # --------------------------------------------------------

    mom15_1 = momentum_percent(
        c15,
        1
    )

    mom15_4 = momentum_percent(
        c15,
        4
    )

    # Düşüş gerçekten başlamış olmalı
    if mom15_1 > -0.15:

        return None

    if mom15_4 > -0.30:

        return None

    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

    if price > ema20_15 * 1.005:

        return None

    if ema20_15 >= ema20_15_prev:

        return None

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if rsi15 > 60:

        return None

    if rsi1 > 65:

        return None

    # Çok aşırı düşmüş coin istemiyoruz
    if rsi15 < 25:

        return None

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    vr = volume_ratio(
        c15,
        20
    )

    if vr < 1.10:

        return None

    # --------------------------------------------------------
    # SON MUM
    # --------------------------------------------------------

    last15 = c15[-1]

    if last15["close"] >= last15["open"]:

        return None

    body = abs(
        last15["close"]
        - last15["open"]
    )

    candle_range = (
        last15["high"]
        - last15["low"]
    )

    if candle_range <= 0:

        return None

    body_ratio = (
        body
        / candle_range
    )

    if body_ratio < 0.30:

        return None

    # --------------------------------------------------------
    # SKOR
    # --------------------------------------------------------

    score = 0

    # Zirveden düşüş
    if 3 <= drop <= 6:
        score += 20
    elif drop <= 9:
        score += 15
    elif drop <= 12:
        score += 10
    else:
        score += 5

    # Pump gücü
    if change >= 20:
        score += 20
    elif change >= 15:
        score += 17
    elif change >= 10:
        score += 13
    else:
        score += 8

    # 15M momentum
    if mom15_1 <= -0.70:
        score += 15
    elif mom15_1 <= -0.35:
        score += 10
    else:
        score += 5

    if mom15_4 <= -1.50:
        score += 15
    elif mom15_4 <= -0.80:
        score += 10
    else:
        score += 5

    # EMA
    if price < ema20_15:
        score += 10

    if price < ema20_1:
        score += 10

    # Hacim
    if vr >= 2.0:
        score += 10
    elif vr >= 1.5:
        score += 7
    elif vr >= 1.1:
        score += 4

    # Son kırmızı mum
    if body_ratio >= 0.60:
        score += 10
    elif body_ratio >= 0.45:
        score += 7
    else:
        score += 4

    return {

        "type": "DROP",

        "title": "🔻 PUMP SONRASI DÜŞÜŞ",

        "symbol": symbol,

        "score": min(score, 100),

        "entry": price,

        "change": change,

        "drop": drop,

        "momentum1": mom15_1,

        "momentum4": mom15_4,

        "volume_ratio": vr,

        "rsi4h": rsi4,

        "rsi1h": rsi1,

        "rsi15m": rsi15
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

        # ----------------------------------------------------
        # EARLY
        # ----------------------------------------------------

        early = analyze_early(
            symbol,
            ticker,
            c4,
            c1,
            c15
        )

        if early:

            if (
                early["score"]
                >= MIN_EARLY_SCORE
            ):

                results.append(early)

        # ----------------------------------------------------
        # DROP
        # ----------------------------------------------------

        drop = analyze_drop(
            symbol,
            ticker,
            c4,
            c1,
            c15
        )

        if drop:

            if (
                drop["score"]
                >= MIN_DROP_SCORE
            ):

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

    # ========================================================
    # LONG
    # ========================================================

    if x["type"] == "EARLY":

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

        extra = (
            f"📈 15M momentum: "
            f"+{x['momentum1']:.2f}%\n"

            f"📈 Son 1H momentum: "
            f"+{x['momentum4']:.2f}%\n"

            f"📉 4H dip dönüşü: "
            f"+{x['recovery']:.2f}%\n"
        )

    # ========================================================
    # SHORT
    # ========================================================

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

        extra = (
            f"📉 Zirveden düşüş: "
            f"-{x['drop']:.2f}%\n"

            f"📉 15M momentum: "
            f"{x['momentum1']:.2f}%\n"

            f"📉 Son 1H momentum: "
            f"{x['momentum4']:.2f}%\n"
        )

    # ========================================================
    # MESAJ
    # ========================================================

    return (

        f"{x['title']}\n\n"

        f"💎 <b>{x['symbol']}</b>\n"

        f"{direction}\n"

        f"⭐ <b>Skor: "
        f"{x['score']}/100</b>\n\n"

        f"🟢 Giriş: "
        f"<b>{price_format(entry)}</b>\n"

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
    print("🚀 MEXC CRYPTO FUTURES PUMP RADAR V4")
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

        # Çok aşırı dump/pump coinleri
        if change < -25:

            continue

        if change > 80:

            continue

        filtered.append(
            (
                symbol,
                ticker
            )
        )

    # Hacmi yüksekler önce
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

            symbol = futures[future]

            try:

                results = future.result()

                if results:

                    candidates.extend(
                        results
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
    # AYNI COİNİ TEKLE
    # ========================================================

    best = {}

    for candidate in candidates:

        symbol = candidate["symbol"]

        old = best.get(symbol)

        if old is None:

            best[symbol] = candidate

        elif candidate["score"] > old["score"]:

            best[symbol] = candidate

    candidates = sorted(
        best.values(),
        key=lambda x: x["score"],
        reverse=True
    )

    # ========================================================
    # TİP SAYILARI
    # ========================================================

    early_count = sum(
        1
        for x in candidates
        if x["type"] == "EARLY"
    )

    drop_count = sum(
        1
        for x in candidates
        if x["type"] == "DROP"
    )

    print("")
    print(
        "🔥 TOPLAM GÜÇLÜ SİNYAL:",
        len(candidates)
    )

    print(
        "🟡 ERKEN:",
        early_count
    )

    print(
        "🔻 DÜŞÜŞ:",
        drop_count
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

        symbol = candidate["symbol"]

        signal_type = candidate["type"]

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

            sent[duplicate_key] = now

            save_sent(sent)

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

        print(
            "⚪ Bu taramada güçlü sinyal yok."
        )

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
