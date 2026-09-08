import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC PUMP RADAR 7.0
#
# AMAÇ:
# Pump olmuş coinleri kovalamak yerine,
# pump öncesi güçlenmeye başlayan coinleri bulmak.
#
# 4H  -> ANA YAPI
# 1H  -> TREND
# 15M -> MOMENTUM / HACİM / DİRENÇ
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
# MEXC
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
# ANA AYARLAR
# ============================================================

MIN_24H_VOLUME = 100000

# Çok düşmüş coinleri alma
MIN_24H_CHANGE = -10.0

# Zaten çok pump yapmış coinleri alma
MAX_24H_CHANGE = 18.0

# Gerçek sinyal için minimum skor
MIN_SCORE = 70

# Aynı coin tekrar gönderilmesin
DUPLICATE_HOURS = 6

# Bir taramada maksimum sinyal
MAX_SIGNALS_PER_SCAN = 6

# Paralel tarama
MAX_WORKERS = 12


# ============================================================
# PUMP FİLTRELERİ
# ============================================================

# 15M hacim / ortalama hacim
MIN_VOLUME_RATIO = 1.20

# Son 15M mumda aşırı kaçış olmasın
MAX_15M_MOVE = 4.0

# Son 1 saatte aşırı kaçış olmasın
MAX_1H_MOVE = 7.0


# ============================================================
# RSI
# ============================================================

RSI15_MIN = 45
RSI15_MAX = 70

RSI1_MIN = 45
RSI1_MAX = 72


# ============================================================
# TP / STOP
# ============================================================

TP1_R = 1.2
TP2_R = 2.0
TP3_R = 3.0

MIN_STOP_PCT = 0.8
MAX_STOP_PCT = 3.5


# ============================================================
# DOSYA
# ============================================================

SENT_FILE = "sent_signals.json"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 MEXC-Pump-Radar/7.0"
})


# ============================================================
# GET JSON
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

        print(
            "❌ Telegram secret eksik"
        )

        return False

    url = (
        "https://api.telegram.org/"
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

            print(
                "✅ Telegram gönderildi"
            )

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

                data = json.load(f)

                if isinstance(data, dict):

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
        ) as f:

            json.dump(
                data,
                f,
                indent=2
            )

    except Exception as e:

        print(
            "Sent kayıt hata:",
            e
        )


# ============================================================
# CONTRACTS
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

def rsi(values, period=14):

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
            losses.append(abs(diff))

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

    rs_value = (
        avg_gain
        / avg_loss
    )

    return (
        100
        - (
            100
            / (
                1 + rs_value
            )
        )
    )


# ============================================================
# ATR
# ============================================================

def atr(candles, period=14):

    if len(candles) < period + 1:

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
# CANDLE BODY
# ============================================================

def body_percent(candle):

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
# ANALYZE
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
    ) < 60:

        return None


    # ========================================================
    # KAPANMIŞ MUM
    # ========================================================

    last15 = c15[-2]
    prev15 = c15[-3]
    prev2_15 = c15[-4]

    last1 = c1[-2]
    prev1 = c1[-3]

    last4 = c4[-2]


    price = ticker["price"]


    # ========================================================
    # CLOSE
    # ========================================================

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

    ema50_15 = ema(
        close15,
        50
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
        ema50_15,
        ema20_1,
        ema50_1,
        ema20_4,
        ema50_4
    ]):

        return None


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
        rsi15,
        rsi1,
        rsi4
    ]):

        return None


    # ========================================================
    # 24H
    # ========================================================

    change24 = ticker["change"]


    if change24 < MIN_24H_CHANGE:

        return None


    if change24 > MAX_24H_CHANGE:

        return None


    # ========================================================
    # 1H HAREKET
    # ========================================================

    old1h = c15[-6]["close"]

    if old1h <= 0:

        return None


    move1h = (
        (
            last15["close"]
            - old1h
        )
        / old1h
    ) * 100


    # Çok hızlı kaçmışsa alma
    if move1h > MAX_1H_MOVE:

        return None


    # Çok sert düşüşteyse alma
    if move1h < -3:

        return None


    # ========================================================
    # 15M HAREKET
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


    # Tek mumda pump kovalamıyoruz
    if move15m > MAX_15M_MOVE:

        return None


    # Çok sert kırmızı mum
    if move15m < -1.0:

        return None


    # ========================================================
    # 4H TREND
    # ========================================================

    trend4h = (
        last4["close"]
        > ema20_4
    )

    strong4h = (
        ema20_4
        > ema50_4
    )


    # Tam ters trendi ele
    if (
        last4["close"]
        < ema50_4 * 0.98
    ):

        return None


    # ========================================================
    # 1H TREND
    # ========================================================

    trend1h = (
        last1["close"]
        > ema20_1
    )

    strong1h = (
        ema20_1
        > ema50_1
    )


    # 1H tamamen aşağı trend ise alma
    if (
        last1["close"]
        < ema50_1 * 0.98
    ):

        return None


    # ========================================================
    # 15M TREND
    # ========================================================

    ema_bullish = (
        ema9_15
        > ema20_15
    )


    ema_cross = (
        ema9_15 > ema20_15
        and
        ema(
            close15[:-1],
            9
        )
        <=
        ema(
            close15[:-1],
            20
        )
    )


    # ========================================================
    # RSI
    # ========================================================

    if rsi15 < RSI15_MIN:

        return None


    if rsi15 > RSI15_MAX:

        return None


    if rsi1 < RSI1_MIN:

        return None


    if rsi1 > RSI1_MAX:

        return None


    # ========================================================
    # DİRENÇ
    #
    # Son 16 kapanmış mumun en yüksek noktası
    # ========================================================

    resistance_zone = c15[-18:-2]


    if len(
        resistance_zone
    ) < 10:

        return None


    resistance = max(
        x["high"]
        for x in resistance_zone
    )


    if resistance <= 0:

        return None


    # Fiyatın dirence uzaklığı
    resistance_distance = (
        (
            resistance
            - price
        )
        / price
    ) * 100


    # Dirençten çok uzaktaysa pump hazırlığı değil
    if resistance_distance > 4.0:

        return None


    # ========================================================
    # DİRENÇ YAKINLIĞI
    # ========================================================

    near_resistance = (
        price >= resistance * 0.985
    )


    testing_resistance = (
        last15["high"]
        >= resistance * 0.995
    )


    breakout = (
        last15["close"]
        > resistance
    )


    # ========================================================
    # HACİM
    # ========================================================

    volume_history = [
        x["volume"]
        for x in c15[-22:-2]
        if x["volume"] > 0
    ]


    if len(
        volume_history
    ) < 12:

        return None


    avg_volume = (
        sum(volume_history)
        / len(volume_history)
    )


    if avg_volume <= 0:

        return None


    volume_ratio = (
        last15["volume"]
        / avg_volume
    )


    # Hacim tamamen ölü ise alma
    if volume_ratio < MIN_VOLUME_RATIO:

        return None


    # ========================================================
    # SON 3 MUM ALICI BASKISI
    # ========================================================

    bullish_count = 0


    for candle in c15[-5:-2]:

        if (
            candle["close"]
            >
            candle["open"]
        ):

            bullish_count += 1


    # ========================================================
    # HIGHER LOW
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
        older_low * 0.995
    )


    # ========================================================
    # 1H HIGHER LOW
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
        older_1h_low * 0.99
    )


    # ========================================================
    # FİYAT SIKIŞMASI
    #
    # Pump öncesi genelde fiyat sıkışır.
    # Son 8 mum ile önceki 8 mumun aralığını karşılaştır.
    # ========================================================

    recent_range_high = max(
        x["high"]
        for x in c15[-10:-2]
    )

    recent_range_low = min(
        x["low"]
        for x in c15[-10:-2]
    )


    older_range_high = max(
        x["high"]
        for x in c15[-18:-10]
    )

    older_range_low = min(
        x["low"]
        for x in c15[-18:-10]
    )


    recent_range = (
        (
            recent_range_high
            - recent_range_low
        )
        / recent_range_low
    ) * 100


    older_range = (
        (
            older_range_high
            - older_range_low
        )
        / older_range_low
    ) * 100


    compression = (
        recent_range
        <=
        older_range * 0.90
    )


    # ========================================================
    # SON MUM BODY
    # ========================================================

    body15 = body_percent(
        last15
    )


    # Tek mumda dev pump
    if body15 > 4:

        return None


    # ========================================================
    # SCORE
    # ========================================================

    score = 0


    # --------------------------------------------------------
    # 4H
    # --------------------------------------------------------

    if trend4h:

        score += 10


    if strong4h:

        score += 8


    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    if trend1h:

        score += 10


    if strong1h:

        score += 8


    # --------------------------------------------------------
    # 1H HIGHER LOW
    # --------------------------------------------------------

    if higher_low_1h:

        score += 8


    # --------------------------------------------------------
    # 15M EMA
    # --------------------------------------------------------

    if ema_bullish:

        score += 8


    if ema_cross:

        score += 6


    # --------------------------------------------------------
    # DİRENÇ
    # --------------------------------------------------------

    if near_resistance:

        score += 8


    if testing_resistance:

        score += 6


    if breakout:

        score += 8


    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    if volume_ratio >= 2.5:

        score += 14

    elif volume_ratio >= 2.0:

        score += 12

    elif volume_ratio >= 1.7:

        score += 10

    elif volume_ratio >= 1.5:

        score += 8

    else:

        score += 5


    # --------------------------------------------------------
    # ALICI BASKISI
    # --------------------------------------------------------

    if bullish_count == 3:

        score += 9

    elif bullish_count == 2:

        score += 6

    elif bullish_count == 1:

        score += 2


    # --------------------------------------------------------
    # HIGHER LOW
    # --------------------------------------------------------

    if higher_low:

        score += 8


    # --------------------------------------------------------
    # COMPRESSION
    # --------------------------------------------------------

    if compression:

        score += 7


    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 52 <= rsi15 <= 63:

        score += 7

    elif 48 <= rsi15 < 52:

        score += 4

    elif 63 < rsi15 <= 67:

        score += 4


    # --------------------------------------------------------
    # 1H MOMENTUM
    # --------------------------------------------------------

    if 0.3 <= move1h <= 3.5:

        score += 6

    elif 0 <= move1h < 0.3:

        score += 3


    # ========================================================
    # NEGATİF PUANLAR
    # ========================================================

    # 24H fazla yükseldiyse
    if change24 > 12:

        score -= 7


    # Son 1 saat fazla yükseldiyse
    if move1h > 5:

        score -= 8


    # Son 15M fazla yükseldiyse
    if move15m > 2.5:

        score -= 5


    # RSI çok ısındıysa
    if rsi15 > 65:

        score -= 4


    # ========================================================
    # PUAN FİLTRESİ
    # ========================================================

    if score < MIN_SCORE:

        return None


    # ========================================================
    # ENTRY
    # ========================================================

    entry = price


    # ========================================================
    # ATR
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
    # STOP
    # ========================================================

    structure_low = min(
        last15["low"],
        prev15["low"],
        prev2_15["low"]
    )


    atr_stop = (
        entry
        - (
            atr15
            * 1.25
        )
    )


    # Yapısal stop
    stop = min(
        structure_low,
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


    # Çok uzak stop
    if stop_pct > MAX_STOP_PCT:

        return None


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

    if tp1 <= entry:

        return None


    if tp2 <= tp1:

        return None


    if tp3 <= tp2:

        return None


    # ========================================================
    # RETURN
    # ========================================================

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
            change24,

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

        "near_resistance":
            near_resistance,

        "testing_resistance":
            testing_resistance,

        "breakout":
            breakout,

        "higher_low":
            higher_low,

        "higher_low_1h":
            higher_low_1h,

        "compression":
            compression,

        "ema_cross":
            ema_cross

    }


# ============================================================
# SYMBOL ANALİZ
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
# TELEGRAM SIGNAL
# ============================================================

def format_signal(x):

    if x["breakout"]:

        setup = "🔥 DİRENÇ KIRILIMI"

    elif x["testing_resistance"]:

        setup = "⚡ DİRENÇ TESTİ"

    else:

        setup = "🚀 PUMP ÖNCESİ GÜÇLENME"


    return (

        "🚀 <b>PUMP RADAR AL</b>\n\n"

        f"💎 <b>{x['symbol']}</b>\n"

        f"⭐ Skor: "
        f"<b>{x['score']}/100</b>\n"

        f"📌 {setup}\n\n"

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
        f"<b>{x['volume_ratio']:.2f}x</b>\n\n"

        f"📈 RSI 15M: "
        f"{x['rsi15']:.1f}\n"

        f"📈 RSI 1H: "
        f"{x['rsi1']:.1f}\n"

        f"📊 RSI 4H: "
        f"{x['rsi4']:.1f}\n\n"

        f"🔑 Direnç: "
        f"{price_format(x['resistance'])}\n"

        f"📈 Higher Low: "
        f"{'✅' if x['higher_low'] else '—'}\n"

        f"📈 1H Higher Low: "
        f"{'✅' if x['higher_low_1h'] else '—'}\n"

        f"🔥 Hacim teyidi: ✅\n"

        f"📊 Sıkışma: "
        f"{'✅' if x['compression'] else '—'}\n\n"

        "📡 <b>MEXC USDT FUTURES</b>\n\n"

        "⚠️ <i>Teknik filtrelerden geçen "
        "erken hareket sinyalidir. "
        "Pump garantisi değildir.</i>"
    )


# ============================================================
# MAIN SCAN
# ============================================================

def scan():

    print("")
    print("=" * 70)

    print(
        "🚀 MEXC PUMP RADAR 7.0"
    )

    print(
        "🎯 PUMP ÖNCESİ GÜÇLENME"
    )

    print(
        "🔥 HACİM + TREND + DİRENÇ + MOMENTUM"
    )

    print("=" * 70)


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
    # HACME GÖRE SIRALA
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

            futures[
                future
            ] = item[0]


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
    # SCORE
    # ========================================================

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["volume_ratio"],
            x["move1h"]
        ),
        reverse=True
    )


    print("")

    print(
        "🎯 GÜÇLÜ ADAY:",
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
        "🚀 PUMP RADAR 7.0 BAŞLIYOR"
    )


    # ========================================================
    # TELEGRAM TESTİ YOK
    # ========================================================
    #
    # ÖNEMLİ:
    # Burada telegram_test() YOK.
    #
    # Telegram'a:
    # ❌ Sistem aktif
    # ❌ Pump radar 7.0
    # ❌ Test
    # mesajı gitmez.
    #
    # SADECE GERÇEK SİNYAL GİDER.
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

        # Hata mesajını Telegram'a
        # göndermiyoruz.


    print("")

    print(
        "🏁 Tarama tamamlandı."
    )
