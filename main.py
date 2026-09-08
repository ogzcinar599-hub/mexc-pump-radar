import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC PUMP RADAR 7.0
#
# AMAÇ:
# SADECE GERÇEKTEN GÜÇLENEN VE DİRENÇ KIRILIMINA YAKLAŞAN
# / KIRILIMI YAPAN COINLERİ BULMAK
#
# SADECE MEXC USDT-M FUTURES
#
# ÖNEMLİ:
# Telegram başlangıç mesajı YOK
# İzleme adayı YOK
# Zayıf sinyal YOK
# ============================================================


BASE = "https://api.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================
# AYARLAR
# ============================================================

MIN_24H_VOLUME = 150000

MIN_24H_CHANGE = -5
MAX_24H_CHANGE = 18

# Daha seçici
MIN_SCORE = 82

# Aynı coin tekrar gönderilmesin
DUPLICATE_HOURS = 8

# Bir taramada maksimum sinyal
MAX_SIGNALS_PER_SCAN = 3

# Paralel
MAX_WORKERS = 12


# ============================================================
# MOMENTUM FİLTRELERİ
# ============================================================

# Son 15M hareket
MIN_15M_MOVE = 0.10
MAX_15M_MOVE = 2.50

# Son 1 saat hareket
MIN_1H_MOVE = 0.30
MAX_1H_MOVE = 6.00

# Hacim
MIN_VOLUME_RATIO = 1.30

# RSI
MIN_RSI_15 = 50
MAX_RSI_15 = 68

MIN_RSI_1H = 48
MAX_RSI_1H = 68


# ============================================================
# TP / STOP
# ============================================================

TP1_PCT = 2.0
TP2_PCT = 4.0
TP3_PCT = 6.5

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
    "User-Agent": "Mozilla/5.0 MEXC-Pump-Radar-7.0"
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

            print("Telegram gönderildi")

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
# TICKER
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

        tr = max(
            tr1,
            tr2,
            tr3
        )

        trs.append(tr)

    if len(trs) < period:

        return None

    return (
        sum(trs[-period:])
        / period
    )


# ============================================================
# YÜKSELEN DİP
# ============================================================

def higher_low(candles):

    if len(candles) < 8:

        return False

    recent = candles[-8:-1]

    lows = [
        x["low"]
        for x in recent
    ]

    # Son dip bölgesi
    first_low = min(
        lows[:4]
    )

    second_low = min(
        lows[4:]
    )

    return second_low > first_low


# ============================================================
# SON MUM ALICI KONTROLÜ
# ============================================================

def bullish_candle(candle):

    if candle["close"] <= candle["open"]:

        return False

    body = abs(
        candle["close"]
        - candle["open"]
    )

    full_range = (
        candle["high"]
        - candle["low"]
    )

    if full_range <= 0:

        return False

    body_ratio = (
        body
        / full_range
    )

    return body_ratio >= 0.45


# ============================================================
# DİRENÇ
# ============================================================

def resistance_level(candles):

    if len(candles) < 30:

        return None

    # Son 20 KAPANMIŞ mumun yüksekliği
    window = candles[-21:-1]

    if not window:

        return None

    return max(
        x["high"]
        for x in window
    )


# ============================================================
# ANA ANALİZ
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
    # SADECE KAPANMIŞ MUM
    # ========================================================

    last15 = c15[-2]
    prev15 = c15[-3]
    prev15_2 = c15[-4]

    last1 = c1[-2]
    prev1 = c1[-3]

    last4 = c4[-2]


    # ========================================================
    # FİYATLAR
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

    ema20_15_prev = ema(
        close15[:-1],
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


    if not all([
        ema9_15,
        ema20_15,
        ema20_15_prev,
        ema20_1,
        ema50_1,
        ema20_4
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

    if ticker["change"] < MIN_24H_CHANGE:

        return None

    if ticker["change"] > MAX_24H_CHANGE:

        return None


    # ========================================================
    # 15M MOMENTUM
    # ========================================================

    move15 = (
        (
            last15["close"]
            - prev15["close"]
        )
        / prev15["close"]
    ) * 100


    # ÇOK ÖNEMLİ:
    # Son 15M NEGATİF ise AL YOK

    if move15 < MIN_15M_MOVE:

        return None

    if move15 > MAX_15M_MOVE:

        return None


    # ========================================================
    # 1H MOMENTUM
    # ========================================================

    old1h = c15[-6]["close"]

    move1h = (
        (
            last15["close"]
            - old1h
        )
        / old1h
    ) * 100


    # Son 1 saat negatif ise AL YOK

    if move1h < MIN_1H_MOVE:

        return None

    if move1h > MAX_1H_MOVE:

        return None


    # ========================================================
    # SON MUM
    # ========================================================

    if not bullish_candle(last15):

        return None


    # ========================================================
    # ÖNCEKİ MUM DA ÇOK ZAYIF OLMASIN
    # ========================================================

    if prev15["close"] < prev15["open"]:

        # Önceki mum kırmızı olabilir ama çok büyük
        # satış mumu olmamalı.

        prev_move = (
            (
                prev15["close"]
                - prev15["open"]
            )
            / prev15["open"]
        ) * 100

        if prev_move < -1.2:

            return None


    # ========================================================
    # EMA 15M
    # ========================================================

    if ema9_15 <= ema20_15:

        return None


    # EMA20 yukarı eğimli olsun

    if ema20_15 <= ema20_15_prev:

        return None


    # ========================================================
    # 1H TREND
    # ========================================================

    if last1["close"] <= ema20_1:

        return None

    if ema20_1 <= ema50_1:

        return None


    # 1H son mum kırmızı ve güçlü satış ise alma

    if last1["close"] < last1["open"]:

        red_move = (
            (
                last1["close"]
                - last1["open"]
            )
            / last1["open"]
        ) * 100

        if red_move < -0.8:

            return None


    # ========================================================
    # 4H TREND
    # ========================================================

    if last4["close"] < ema20_4 * 0.985:

        return None


    # ========================================================
    # RSI
    # ========================================================

    if rsi15 < MIN_RSI_15:

        return None

    if rsi15 > MAX_RSI_15:

        return None

    if rsi1 < MIN_RSI_1H:

        return None

    if rsi1 > MAX_RSI_1H:

        return None


    # ========================================================
    # RSI YÖNÜ
    # ========================================================

    rsi15_prev = rsi(
        close15[:-1]
    )

    if rsi15_prev:

        if rsi15 <= rsi15_prev:

            return None


    # ========================================================
    # HACİM
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

    if avg_volume <= 0:

        return None

    volume_ratio = (
        last15["volume"]
        / avg_volume
    )


    if volume_ratio < MIN_VOLUME_RATIO:

        return None


    # ========================================================
    # SON 3 MUM ALICI BASKISI
    # ========================================================

    bullish_count = 0

    for candle in c15[-4:-1]:

        if candle["close"] > candle["open"]:

            bullish_count += 1


    if bullish_count < 2:

        return None


    # ========================================================
    # HIGHER LOW
    # ========================================================

    hl15 = higher_low(
        c15
    )

    hl1h = higher_low(
        c1
    )

    if not hl15:

        return None

    if not hl1h:

        return None


    # ========================================================
    # DİRENÇ
    # ========================================================

    resistance = resistance_level(
        c15
    )

    if not resistance:

        return None


    current_price = ticker["price"]


    # ========================================================
    # DİRENÇ MESAFESİ
    # ========================================================

    resistance_distance = (
        (
            resistance
            - current_price
        )
        / current_price
    ) * 100


    # Fiyat dirençten çok uzaktaysa AL YOK

    if resistance_distance > 1.5:

        return None


    # ========================================================
    # KIRILIM
    # ========================================================

    breakout = (
        last15["close"]
        > resistance
    )


    # Kırılım değilse fiyat en azından dirence çok yakın
    # olmalı

    if not breakout:

        if resistance_distance > 0.7:

            return None


    # ========================================================
    # KIRILIM MUMU
    # ========================================================

    breakout_strength = 0

    if breakout:

        breakout_strength = (
            (
                last15["close"]
                - resistance
            )
            / resistance
        ) * 100

        # Çok küçük sahte kırılımları engelle

        if breakout_strength < 0.05:

            return None

        # Aşırı kaçmış kırılımı alma

        if breakout_strength > 2.0:

            return None


    # ========================================================
    # ATR
    # ========================================================

    atr15 = atr(
        c15,
        14
    )

    if not atr15:

        return None


    # ========================================================
    # SCORE
    # ========================================================

    score = 0


    # EMA 15M
    score += 15


    # EMA 1H
    score += 15


    # 4H
    if last4["close"] >= ema20_4:

        score += 5


    # Hacim
    if volume_ratio >= 2.0:

        score += 20

    elif volume_ratio >= 1.6:

        score += 17

    elif volume_ratio >= 1.3:

        score += 13


    # Momentum
    if 0.5 <= move15 <= 1.8:

        score += 10

    else:

        score += 6


    if 0.8 <= move1h <= 4:

        score += 10

    else:

        score += 6


    # RSI
    if 55 <= rsi15 <= 64:

        score += 8

    else:

        score += 5


    # Higher Low
    if hl15:

        score += 5

    if hl1h:

        score += 5


    # Kırılım
    if breakout:

        score += 15


    # Son 3 mum
    if bullish_count == 3:

        score += 5


    # ========================================================
    # CEZA
    # ========================================================

    # 24H fazla yükselmiş
    if ticker["change"] > 12:

        score -= 8


    # 15M fazla hızlı
    if move15 > 2:

        score -= 8


    # 1H fazla hızlı
    if move1h > 5:

        score -= 8


    # ========================================================
    # SON SKOR
    # ========================================================

    if score < MIN_SCORE:

        return None


    # ========================================================
    # GİRİŞ
    # ========================================================

    entry = current_price


    # Fiyat son kapanıştan çok uzaksa
    # sinyal kaçmış olabilir

    candle_close_distance = (
        (
            current_price
            - last15["close"]
        )
        / last15["close"]
    ) * 100


    if candle_close_distance > 1.0:

        return None


    # ========================================================
    # STOP
    # ========================================================

    structure_stop = resistance - (
        atr15 * 0.8
    )

    percent_stop = entry * (
        1 - STOP_PCT / 100
    )

    stop = max(
        structure_stop,
        percent_stop
    )


    # Stop girişin üstünde olamaz

    if stop >= entry:

        stop = percent_stop


    # Stop çok yakınsa
    # minimum mesafe

    min_stop = entry * 0.985

    if stop > min_stop:

        stop = min_stop


    # ========================================================
    # TP
    # ========================================================

    tp1 = entry * (
        1 + TP1_PCT / 100
    )

    tp2 = entry * (
        1 + TP2_PCT / 100
    )

    tp3 = entry * (
        1 + TP3_PCT / 100
    )


    # ========================================================
    # RETURN
    # ========================================================

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

        "move1h": move1h,

        "move15m": move15,

        "volume_ratio": volume_ratio,

        "rsi15": rsi15,

        "rsi1": rsi1,

        "rsi4": rsi4,

        "resistance": resistance,

        "breakout": breakout,

        "higher_low": hl15

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
# TELEGRAM
# ============================================================

def format_signal(x):

    if x["breakout"]:

        setup = "🔥 DİRENÇ KIRILIMI"

    else:

        setup = "⚡ KIRILIM ÖNCESİ GÜÇLENME"


    return (

        "🚀 <b>PUMP RADAR AL</b>\n\n"

        f"💎 <b>{x['symbol']}</b>\n"

        f"⭐ Skor: <b>{x['score']}/100</b>\n"

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
        f"{'✅' if x['higher_low'] else '❌'}\n"

        f"🔥 Hacim teyidi: "
        f"{'✅' if x['volume_ratio'] >= 1.30 else '❌'}\n\n"

        "📡 <b>MEXC USDT FUTURES</b>\n\n"

        "⚠️ <i>Teknik filtrelerden geçen güçlü "
        "momentum sinyalidir. Garanti değildir.</i>"
    )


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print("")
    print("=" * 65)
    print("🚀 MEXC PUMP RADAR 7.0")
    print("🎯 KIRILIM + MOMENTUM + HACİM")
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
            "Futures kontrat alınamadı"
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
            "Ticker alınamadı"
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
    # HACİM SIRASI
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
            "Ön filtreden coin geçmedi"
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
                "Tekrar:",
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
                "GÖNDERİLDİ:",
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

    print("=" * 65)


# ============================================================
# PROGRAM
# ============================================================

if __name__ == "__main__":

    print("")
    print(
        "🚀 PUMP RADAR 7.0 BAŞLIYOR"
    )

    # ========================================================
    # ÖNEMLİ:
    # BURADA TELEGRAM TEST MESAJI YOK.
    # ========================================================

    if not BOT_TOKEN or not CHAT_ID:

        print(
            "Telegram secret eksik"
        )

    try:

        scan()

    except Exception as e:

        print(
            "ANA HATA:",
            e
        )

    print("")
    print(
        "Tarama tamamlandı."
    )
