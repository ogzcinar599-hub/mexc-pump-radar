import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC PUMP RADAR 6.0
#
# SADECE:
# MEXC USDT-M FUTURES
#
# AMAÇ:
# Pump olmuş coinleri kovalamak yerine,
# güçlü yükseliş başlamadan önce oluşan yapıyı bulmak.
#
# 4H  = ANA TREND
# 1H  = TREND + HIGHER LOW
# 15M = DİRENÇ + KIRILIM + RETEST + HACİM
#
# TELEGRAM:
# SADECE GERÇEK SİNYAL
#
# ❌ TEST MESAJI YOK
# ❌ SİSTEM AKTİF MESAJI YOK
# ❌ İZLEME ADAYI YOK
# ❌ SELL YOK
# ============================================================


# ============================================================
# API
# ============================================================

BASE = "https://contract.mexc.com"


BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


# ============================================================
# GENEL AYARLAR
# ============================================================

MIN_24H_VOLUME = 100000

MIN_24H_CHANGE = -5.0
MAX_24H_CHANGE = 15.0

MIN_SCORE = 78

DUPLICATE_HOURS = 6

MAX_SIGNALS_PER_SCAN = 4

MAX_WORKERS = 12


# ============================================================
# MOMENTUM FİLTRELERİ
# ============================================================

MIN_VOLUME_RATIO = 1.50

MAX_1H_MOVE = 5.0

MAX_15M_MOVE = 2.5

MAX_BREAKOUT_DISTANCE = 1.5

RETEST_TOLERANCE = 0.008


# ============================================================
# RSI
# ============================================================

RSI_MIN_15M = 50
RSI_MAX_15M = 68

RSI_MIN_1H = 50
RSI_MAX_1H = 68

RSI_MIN_4H = 42
RSI_MAX_4H = 70


# ============================================================
# STOP / TP
# ============================================================

MIN_STOP_PCT = 0.8

MAX_STOP_PCT = 3.0

TP1_R = 1.5

TP2_R = 2.5

TP3_R = 4.0


# ============================================================
# DOSYA
# ============================================================

SENT_FILE = "sent_signals.json"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent":
        "Mozilla/5.0 MEXC-Pump-Radar/6.0"
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

            print(
                "HTTP HATA:",
                response.status_code,
                url
            )

            return None

        return response.json()

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

    if not BOT_TOKEN or not CHAT_ID:

        print(
            "❌ Telegram secret eksik"
        )

        return False

    url = (
        "https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    payload = {

        "chat_id":
            CHAT_ID,

        "text":
            text,

        "parse_mode":
            "HTML",

        "disable_web_page_preview":
            True

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
            "❌ Telegram hata:",
            response.text
        )

    except Exception as e:

        print(
            "❌ Telegram bağlantı:",
            e
        )

    return False


# ============================================================
# SENT SIGNALS
# ============================================================

def load_sent():

    try:

        if os.path.exists(
            SENT_FILE
        ):

            with open(
                SENT_FILE,
                "r",
                encoding="utf-8"
            ) as file:

                data = json.load(file)

                if isinstance(
                    data,
                    dict
                ):

                    return data

    except Exception as e:

        print(
            "Sent okuma hata:",
            e
        )

    return {}


def save_sent(data):

    try:

        with open(
            SENT_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                indent=2
            )

    except Exception as e:

        print(
            "Sent kayıt hata:",
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

    for row in rows:

        try:

            symbol = str(
                row.get(
                    "symbol",
                    ""
                )
            )

            quote = str(
                row.get(
                    "quoteCoin",
                    ""
                )
            )

            settle = str(
                row.get(
                    "settleCoin",
                    ""
                )
            )

            # ------------------------------------------------
            # SADECE USDT FUTURES
            # ------------------------------------------------

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

    return result


# ============================================================
# TICKERS
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

    if isinstance(
        rows,
        dict
    ):

        rows = [rows]

    result = {}

    for row in rows:

        try:

            symbol = row.get(
                "symbol",
                ""
            )

            if not symbol.endswith(
                "_USDT"
            ):

                continue

            price = float(
                row.get(
                    "lastPrice",
                    0
                ) or 0
            )

            change = float(
                row.get(
                    "riseFallRate",
                    0
                ) or 0
            ) * 100

            volume = float(
                row.get(
                    "amount24",
                    0
                ) or 0
            )

            if price <= 0:

                continue

            result[symbol] = {

                "price":
                    price,

                "change":
                    change,

                "volume":
                    volume

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
            "interval":
                interval
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

    multiplier = 2 / (
        period + 1
    )

    value = sum(
        values[:period]
    ) / period

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

    if len(values) < (
        period + 1
    ):

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

            gains.append(
                diff
            )

            losses.append(
                0
            )

        else:

            gains.append(
                0
            )

            losses.append(
                abs(diff)
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

        return 100

    rs_value = (
        avg_gain
        / avg_loss
    )

    return (
        100
        - (
            100
            / (
                1
                + rs_value
            )
        )
    )


# ============================================================
# ATR
# ============================================================

def atr(
    candles,
    period=14
):

    if len(candles) < (
        period + 1
    ):

        return None

    trs = []

    for i in range(
        1,
        len(candles)
    ):

        current = candles[i]

        previous = candles[i - 1]

        tr1 = (
            current["high"]
            - current["low"]
        )

        tr2 = abs(
            current["high"]
            - previous["close"]
        )

        tr3 = abs(
            current["low"]
            - previous["close"]
        )

        trs.append(
            max(
                tr1,
                tr2,
                tr3
            )
        )

    if len(trs) < period:

        return None

    return (
        sum(
            trs[-period:]
        )
        / period
    )


# ============================================================
# CANDLE BODY %
# ============================================================

def candle_body_percent(
    candle
):

    if candle["open"] <= 0:

        return 0

    return (
        abs(
            candle["close"]
            - candle["open"]
        )
        / candle["open"]
    ) * 100


# ============================================================
# ANALİZ
# ============================================================

def analyze(
    symbol,
    ticker,
    c15,
    c1,
    c4
):

    # --------------------------------------------------------
    # YETERLİ VERİ
    # --------------------------------------------------------

    if min(
        len(c15),
        len(c1),
        len(c4)
    ) < 60:

        return None


    # --------------------------------------------------------
    # SADECE KAPANMIŞ MUM
    # --------------------------------------------------------

    last15 = c15[-2]

    prev15 = c15[-3]

    prev2_15 = c15[-4]

    last1 = c1[-2]

    prev1 = c1[-3]

    last4 = c4[-2]

    price = ticker["price"]


    # --------------------------------------------------------
    # CLOSE
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # EMA
    # --------------------------------------------------------

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

    ema50_4 = ema(
        close4,
        50
    )


    if not all([
        ema9_15,
        ema20_15,
        ema20_1,
        ema50_1,
        ema20_4,
        ema50_4
    ]):

        return None


    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

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
        rsi15,
        rsi1,
        rsi4
    ]):

        return None


    # ========================================================
    # 1 — 24H FİLTRE
    # ========================================================

    if ticker["change"] < MIN_24H_CHANGE:

        return None

    if ticker["change"] > MAX_24H_CHANGE:

        return None


    # ========================================================
    # 2 — 4H ANA TREND
    # ========================================================

    # Fiyat EMA20 altında olmayacak
    if last4["close"] < ema20_4:

        return None

    # EMA20 > EMA50
    if ema20_4 <= ema50_4:

        return None

    # RSI
    if rsi4 < RSI_MIN_4H:

        return None

    if rsi4 > RSI_MAX_4H:

        return None


    # ========================================================
    # 3 — 1H TREND
    # ========================================================

    if last1["close"] < ema20_1:

        return None

    if ema20_1 <= ema50_1:

        return None

    if rsi1 < RSI_MIN_1H:

        return None

    if rsi1 > RSI_MAX_1H:

        return None


    # ========================================================
    # 4 — 1H MOMENTUM
    # ========================================================

    old1h = c1[-7]["close"]

    if old1h <= 0:

        return None

    move1h = (
        (
            last1["close"]
            - old1h
        )
        / old1h
    ) * 100


    # Negatif 1H hareket yok
    if move1h < 0:

        return None


    # Çoktan uçmuş coin yok
    if move1h > MAX_1H_MOVE:

        return None


    # ========================================================
    # 5 — 15M MOMENTUM
    # ========================================================

    if prev15["close"] <= 0:

        return None

    move15m = (
        (
            last15["close"]
            - prev15["close"]
        )
        / prev15["close"]
    ) * 100


    # Son mum çok sert yükselmişse
    # giriş geç kalmış olabilir.
    if move15m > MAX_15M_MOVE:

        return None


    # Sert kırmızı mum
    if move15m < -0.30:

        return None


    # ========================================================
    # 6 — 15M RSI
    # ========================================================

    if rsi15 < RSI_MIN_15M:

        return None

    if rsi15 > RSI_MAX_15M:

        return None


    # ========================================================
    # 7 — 15M EMA TRENDİ
    # ========================================================

    if ema9_15 <= ema20_15:

        return None


    # ========================================================
    # 8 — LOKAL DİRENÇ
    #
    # Son kapalı mumdan önceki
    # 20 mumun en yüksek noktası.
    # ========================================================

    resistance_candles = c15[-22:-2]

    if len(
        resistance_candles
    ) < 15:

        return None

    resistance = max(
        x["high"]
        for x in resistance_candles
    )

    if resistance <= 0:

        return None


    # ========================================================
    # 9 — DİRENÇ KIRILIMI
    # ========================================================

    breakout = (
        last15["close"]
        > resistance
    )

    if not breakout:

        return None


    # ========================================================
    # 10 — KIRILIM MUMU BOYUTU
    # ========================================================

    body15 = candle_body_percent(
        last15
    )

    # Çok büyük mumdan giriş yapma
    if body15 > 2.5:

        return None


    # ========================================================
    # 11 — KIRILIMDAN SONRA FİYAT ÇOK UZAK MI?
    # ========================================================

    breakout_distance = (
        (
            price
            - resistance
        )
        / resistance
    ) * 100


    if breakout_distance < 0:

        return None


    if breakout_distance > MAX_BREAKOUT_DISTANCE:

        return None


    # ========================================================
    # 12 — RETEST
    # ========================================================

    retest = (
        last15["low"]
        <=
        resistance
        * (
            1
            + RETEST_TOLERANCE
        )
    )


    previous_structure_ok = (
        prev15["close"]
        >=
        resistance
        * 0.985
    )


    # Kırılım sonrası yapı
    # direnç bölgesine temas etmeli.
    if (
        not retest
        and
        not previous_structure_ok
    ):

        return None


    # ========================================================
    # 13 — HACİM
    # ========================================================

    volumes = [
        x["volume"]
        for x in c15[-22:-2]
        if x["volume"] > 0
    ]


    if len(volumes) < 15:

        return None


    avg_volume = (
        sum(volumes)
        / len(volumes)
    )


    if avg_volume <= 0:

        return None


    volume_ratio = (
        last15["volume"]
        / avg_volume
    )


    # Minimum hacim
    if volume_ratio < MIN_VOLUME_RATIO:

        return None


    # Daha güçlü teyit
    if volume_ratio < 1.50:

        return None


    strong_volume = (
        volume_ratio >= 2.0
    )


    # ========================================================
    # 14 — SON MUM ALICI
    # ========================================================

    if last15["close"] <= last15["open"]:

        return None


    # ========================================================
    # 15 — SON 3 MUM ALICI BASKISI
    # ========================================================

    bullish_count = 0

    for candle in c15[-5:-2]:

        if candle["close"] > candle["open"]:

            bullish_count += 1


    if bullish_count < 2:

        return None


    # ========================================================
    # 16 — 15M HIGHER LOW
    # ========================================================

    recent_low = min(
        x["low"]
        for x in c15[-8:-2]
    )

    older_low = min(
        x["low"]
        for x in c15[-16:-8]
    )


    higher_low = (
        recent_low
        >=
        older_low
        * 0.995
    )


    if not higher_low:

        return None


    # ========================================================
    # 17 — 1H HIGHER LOW
    # ========================================================

    recent_1h_low = min(
        x["low"]
        for x in c1[-5:-2]
    )

    older_1h_low = min(
        x["low"]
        for x in c1[-10:-5]
    )


    higher_low_1h = (
        recent_1h_low
        >=
        older_1h_low
        * 0.99
    )


    if not higher_low_1h:

        return None


    # ========================================================
    # 18 — ATR
    # ========================================================

    atr15 = atr(
        c15[:-1],
        14
    )


    if not atr15:

        return None


    if atr15 <= 0:

        return None


    # ========================================================
    # SCORE
    # ========================================================

    score = 0


    # --------------------------------------------------------
    # 4H
    # --------------------------------------------------------

    score += 12


    if last4["close"] > ema20_4:

        score += 6


    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    score += 12


    if last1["close"] > ema20_1:

        score += 6


    # --------------------------------------------------------
    # 1H HIGHER LOW
    # --------------------------------------------------------

    if higher_low_1h:

        score += 8


    # --------------------------------------------------------
    # 15M EMA
    # --------------------------------------------------------

    score += 8


    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    score += 12


    # --------------------------------------------------------
    # RETEST
    # --------------------------------------------------------

    if retest:

        score += 10

    else:

        score += 5


    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    if volume_ratio >= 2.5:

        score += 12

    elif volume_ratio >= 2.0:

        score += 10

    elif volume_ratio >= 1.7:

        score += 8

    else:

        score += 6


    # --------------------------------------------------------
    # HIGHER LOW
    # --------------------------------------------------------

    if higher_low:

        score += 8


    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 53 <= rsi15 <= 63:

        score += 8

    elif 50 <= rsi15 < 53:

        score += 5

    else:

        score += 4


    # --------------------------------------------------------
    # 1H MOMENTUM
    # --------------------------------------------------------

    if 0.3 <= move1h <= 3:

        score += 6

    elif move1h <= 5:

        score += 3


    # --------------------------------------------------------
    # GÜÇLÜ HACİM
    # --------------------------------------------------------

    if strong_volume:

        score += 5


    # ========================================================
    # NEGATİF PUAN
    # ========================================================

    if ticker["change"] > 12:

        score -= 8


    if move1h > 4:

        score -= 8


    if move15m > 2:

        score -= 6


    if body15 > 2:

        score -= 5


    if rsi15 > 65:

        score -= 5


    # ========================================================
    # MINIMUM SCORE
    # ========================================================

    if score < MIN_SCORE:

        return None


    # ========================================================
    # ENTRY
    # ========================================================

    entry = price


    if entry < resistance:

        return None


    # ========================================================
    # STOP
    # ========================================================

    technical_stop = min(
        last15["low"],
        resistance * 0.992
    )


    atr_stop = (
        entry
        - (
            atr15
            * 1.2
        )
    )


    stop = min(
        technical_stop,
        atr_stop
    )


    if stop <= 0:

        return None


    # ========================================================
    # STOP %
    # ========================================================

    stop_pct = (
        (
            entry
            - stop
        )
        / entry
    ) * 100


    # Çok yakın stop
    if stop_pct < MIN_STOP_PCT:

        stop = (
            entry
            * (
                1
                - MIN_STOP_PCT / 100
            )
        )

        stop_pct = MIN_STOP_PCT


    # Çok uzak stop
    if stop_pct > MAX_STOP_PCT:

        return None


    # ========================================================
    # RISK
    # ========================================================

    risk = (
        entry
        - stop
    )


    if risk <= 0:

        return None


    # ========================================================
    # TP
    # ========================================================

    tp1 = (
        entry
        + (
            risk
            * TP1_R
        )
    )

    tp2 = (
        entry
        + (
            risk
            * TP2_R
        )
    )

    tp3 = (
        entry
        + (
            risk
            * TP3_R
        )
    )


    # ========================================================
    # SON GÜVENLİK
    # ========================================================

    distance = (
        (
            entry
            - resistance
        )
        / resistance
    ) * 100


    if distance > MAX_BREAKOUT_DISTANCE:

        return None


    return {

        "symbol":
            symbol,

        "score":
            min(
                int(score),
                100
            ),

        "entry":
            entry,

        "tp1":
            tp1,

        "tp2":
            tp2,

        "tp3":
            tp3,

        "stop":
            stop,

        "stop_pct":
            stop_pct,

        "change":
            ticker["change"],

        "move1h":
            move1h,

        "move15m":
            move15m,

        "volume_ratio":
            volume_ratio,

        "rsi15":
            rsi15,

        "rsi1":
            rsi1,

        "rsi4":
            rsi4,

        "resistance":
            resistance,

        "retest":
            retest,

        "higher_low":
            higher_low,

        "higher_low_1h":
            higher_low_1h

    }


# ============================================================
# COIN ANALİZ
# ============================================================

def analyze_symbol(item):

    symbol, ticker = item

    try:

        c15 = get_klines(
            symbol,
            "Min15",
            120
        )

        c1 = get_klines(
            symbol,
            "Min60",
            120
        )

        c4 = get_klines(
            symbol,
            "Hour4",
            120
        )


        if not c15:

            return None

        if not c1:

            return None

        if not c4:

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
            "ANALİZ HATASI:",
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
# TELEGRAM SIGNAL
# ============================================================

def format_signal(x):

    retest_text = (
        "✅ RETEST"
        if x["retest"]
        else
        "⚡ KIRILIM YAPISI"
    )


    return (

        "🚀 <b>PUMP ÖNCESİ AL</b>\n\n"

        f"💎 <b>{x['symbol']}</b>\n"

        f"⭐ Skor: "
        f"<b>{x['score']}/100</b>\n\n"

        f"🟢 Giriş: "
        f"<b>{price_format(x['entry'])}</b>\n"

        f"🎯 TP1: "
        f"<b>{price_format(x['tp1'])}</b>\n"

        f"🎯 TP2: "
        f"<b>{price_format(x['tp2'])}</b>\n"

        f"🎯 TP3: "
        f"<b>{price_format(x['tp3'])}</b>\n"

        f"🛑 Stop: "
        f"<b>{price_format(x['stop'])}</b>\n\n"

        f"📊 24H: "
        f"{x['change']:+.2f}%\n"

        f"⚡ 1H: "
        f"{x['move1h']:+.2f}%\n"

        f"🔥 15M: "
        f"{x['move15m']:+.2f}%\n"

        f"💥 Hacim: "
        f"{x['volume_ratio']:.2f}x\n\n"

        f"📈 RSI 15M: "
        f"{x['rsi15']:.1f}\n"

        f"📈 RSI 1H: "
        f"{x['rsi1']:.1f}\n"

        f"📊 RSI 4H: "
        f"{x['rsi4']:.1f}\n\n"

        f"🔑 Direnç: "
        f"{price_format(x['resistance'])}\n"

        f"{retest_text}\n"

        "📈 Higher Low: ✅\n"

        "📈 1H Trend: ✅\n"

        "🔥 Hacim Teyidi: ✅\n\n"

        "📡 <b>MEXC USDT FUTURES</b>\n\n"

        "⚠️ <i>Teknik filtrelerden geçen "
        "erken giriş sinyalidir.</i>"
    )


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print("")
    print("=" * 70)

    print(
        "🚀 MEXC PUMP RADAR 6.0"
    )

    print(
        "🎯 KIRILIM + RETEST + HACİM"
    )

    print("=" * 70)


    # ========================================================
    # CONTRACTS
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

        return


    # ========================================================
    # TICKERS
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
        key=lambda x:
            x[1]["volume"],
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
                        "🔥 GÜÇLÜ:",
                        symbol,
                        result["score"]
                    )


            except Exception as e:

                print(
                    symbol,
                    "HATA:",
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
    # SKOR SIRALAMA
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
        "🎯 Güçlü aday:",
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
                DUPLICATE_HOURS
                * 3600
            ):

                clean[
                    symbol
                ] = timestamp

        except Exception:

            continue


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


        # Aynı coin
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

            sent[
                symbol
            ] = now


            save_sent(
                sent
            )


            sent_count += 1


            print(
                "✅ GÖNDERİLDİ:",
                symbol,
                candidate["score"]
            )


    # ========================================================
    # SONUÇ
    # ========================================================

    print("")

    print(
        "📨 Telegram gönderilen:",
        sent_count
    )

    print("=" * 70)


# ============================================================
# PROGRAM
# ============================================================

if __name__ == "__main__":

    print("")
    print(
        "🚀 PUMP RADAR 6.0 BAŞLIYOR"
    )

    # ========================================================
    # TELEGRAM TESTİ YOK
    #
    # Burada özellikle send_telegram() çağırmıyoruz.
    # Böylece Telegram'a "Sistem aktif" mesajı gitmez.
    # ========================================================

    if BOT_TOKEN and CHAT_ID:

        print(
            "✅ Telegram bağlantı bilgileri hazır"
        )

    else:

        print(
            "❌ Telegram secret eksik"
        )


    # ========================================================
    # SCAN
    # ========================================================

    try:

        scan()


    except Exception as e:

        print(
            "🔴 ANA HATA:",
            e
        )

        # Hata mesajını da Telegram'a
        # göndermiyoruz.
        #
        # Böylece Telegram kanalında
        # sadece gerçek sinyaller görünür.


    print("")

    print(
        "🏁 Tarama tamamlandı."
    )
