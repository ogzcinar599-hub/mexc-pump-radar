import os
import json
import time
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC CRYPTO FUTURES PUMP RADAR
# ============================================================
#
# SADECE:
# ✅ MEXC USDT-M CRYPTO FUTURES
# ❌ SPOT YOK
# ❌ STOCK FUTURES YOK
#
# STRATEJİ:
#
# 4H  = DIP + YENİ DÖNÜŞ
# 1H  = TREND TEYİDİ
# 15M = MOMENTUM + HACİM PATLAMASI
#
# AMAÇ:
# Pump olmuş coinleri değil,
# pump başlamadan hemen önce güçlenen coinleri bulmak.
#
# ============================================================


# ============================================================
# MEXC FUTURES API
# ============================================================

BASE = "https://api.mexc.com"


# ============================================================
# TELEGRAM
# ============================================================

BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


# ============================================================
# AYARLAR
# ============================================================

# Güçlü sinyal için minimum skor
MIN_SCORE = 82

# 24H minimum USDT hacmi
MIN_24H_VOLUME = 500000

# 24H değişim
#
# Çok düşmüş coinleri alma
# Çok pump yapmış coinleri de alma
#
MIN_24H_CHANGE = -15
MAX_24H_CHANGE = 12


# Bir taramada maksimum Telegram sinyali
MAX_SIGNALS_PER_SCAN = 3


# Aynı coin kaç saat tekrar gönderilmesin
DUPLICATE_HOURS = 6


# ============================================================
# TP / STOP
# ============================================================

TP1_PCT = 1.8
TP2_PCT = 3.5
TP3_PCT = 5.5

STOP_PCT = 2.2


# ============================================================
# THREAD
# ============================================================

MAX_WORKERS = 12


# ============================================================
# SENT FILE
# ============================================================

SENT_FILE = "sent_signals.json"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 MEXC-Crypto-Pump-Radar/2.0"
})


# ============================================================
# STOCK FUTURES
# ============================================================
#
# MEXC'de stock futures ayrıca bulunuyor.
# Bu radar sadece CRYPTO arıyor.
#
# Listeye bilinen stock sembollerini ekliyoruz.
# Ayrıca API'den gelen isimlerde stock/equity
# kelimelerini de kontrol ediyoruz.
#
# ============================================================

STOCK_SYMBOLS = {

    # Eski / yaygın
    "COIN_USDT",
    "HOOD_USDT",
    "NVDA_USDT",
    "AAPL_USDT",
    "AMZN_USDT",
    "GOOGL_USDT",
    "META_USDT",
    "TSLA_USDT",
    "MCD_USDT",

    # 2026 eklenenler
    "VST_USDT",
    "UPST_USDT",
    "FCX_USDT",
    "BLK_USDT",
    "AXP_USDT",

    "ALAB_USDT",
    "TER_USDT",

    "BSP_USDT",
    "FLEX_USDT",
    "TTWO_USDT",
    "KSTR_USDT",
    "STRC_USDT",

    "ANET_USDT",
    "ETN_USDT",
    "AVAV_USDT",
    "APD_USDT",

    "RTX_USDT",
    "NIO_USDT",
    "SMR_USDT",
    "AEHR_USDT",

    "MSTU_USDT",
    "TSEM_USDT",
    "ABNB_USDT",
    "ROK_USDT",

    "OUST_USDT",
    "AMC_USDT",
    "PL_USDT",

    "NEM_USDT",
    "SLB_USDT",
    "PYPL_USDT",
    "TEM_USDT",

    "KO_USDT",

    "TSLL_USDT",
    "NVDL_USDT",
    "RAM_USDT",

    # MUON / MUSTOCK konusu
    #
    # Kullanıcı isteği gereği özellikle dışarıda bırakıyoruz.
    #
    "MUSTOCK_USDT",
    "MU_USDT",
    "MUUSDT"
}


# ============================================================
# GENERIC GET
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

        response = session.post(
            url,
            json=payload,
            timeout=15
        )

        print(
            "Telegram:",
            response.status_code
        )

        if response.status_code == 200:

            print(
                "✅ Telegram gönderildi"
            )

            return True

        print(
            "❌ Telegram:",
            response.text
        )

    except Exception as e:

        print(
            "Telegram hata:",
            e
        )

    return False


# ============================================================
# TELEGRAM TEST
# ============================================================

def telegram_test():

    message = (

        "🟢 <b>PUMP RADAR AKTİF</b>\n\n"

        "✅ Telegram bağlantısı çalışıyor.\n"
        "✅ GitHub Actions çalışıyor.\n\n"

        "🚫 Stock Futures hariç\n"
        "🪙 Sadece Crypto Futures\n\n"

        "🔎 4H dip + dönüş\n"
        "📈 1H trend teyidi\n"
        "⚡ 15M momentum + hacim\n\n"

        "🎯 Pump öncesi radar taraması başladı."
    )

    return send_telegram(
        message
    )


# ============================================================
# SENT
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
            ) as f:

                return json.load(f)

    except Exception as e:

        print(
            "sent okuma:",
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
                indent=2,
                ensure_ascii=False
            )

    except Exception as e:

        print(
            "sent yazma:",
            e
        )


# ============================================================
# STOCK KONTROL
# ============================================================

def is_stock_contract(contract):

    symbol = str(
        contract.get(
            "symbol",
            ""
        )
    ).upper()

    display = str(
        contract.get(
            "displayNameEn",
            ""
        )
    ).upper()

    display2 = str(
        contract.get(
            "displayName",
            ""
        )
    ).upper()

    base_coin = str(
        contract.get(
            "baseCoin",
            ""
        )
    ).upper()

    # --------------------------------------------------------
    # Açık blacklist
    # --------------------------------------------------------

    if symbol in STOCK_SYMBOLS:

        return True


    # --------------------------------------------------------
    # API isimlerinde stock/equity geçiyorsa
    # --------------------------------------------------------

    combined = (
        symbol
        + " "
        + display
        + " "
        + display2
        + " "
        + base_coin
    )

    stock_words = [
        "STOCK",
        "EQUITY",
        "SHARE",
        "SHARES"
    ]

    for word in stock_words:

        if word in combined:

            return True


    return False


# ============================================================
# FUTURES CONTRACTLAR
# ============================================================

def get_futures_contracts():

    data = get_json(
        f"{BASE}/api/v1/contract/detail"
    )

    if not data:

        return []

    contracts = data.get(
        "data",
        []
    )

    if not isinstance(
        contracts,
        list
    ):

        return []


    result = []


    for contract in contracts:

        try:

            symbol = str(
                contract.get(
                    "symbol",
                    ""
                )
            ).upper()

            if not symbol:

                continue


            # ------------------------------------------------
            # SADECE USDT SETTLEMENT
            # ------------------------------------------------

            quote = str(
                contract.get(
                    "quoteCoin",
                    ""
                )
            ).upper()

            settle = str(
                contract.get(
                    "settleCoin",
                    ""
                )
            ).upper()

            if quote != "USDT":

                continue

            if settle != "USDT":

                continue


            # ------------------------------------------------
            # AKTİF
            # ------------------------------------------------

            state = contract.get(
                "state",
                0
            )

            try:

                state = int(state)

            except Exception:

                state = 0

            if state != 0:

                continue


            # ------------------------------------------------
            # STOCK FİLTRESİ
            # ------------------------------------------------

            if is_stock_contract(
                contract
            ):

                print(
                    "🚫 STOCK:",
                    symbol
                )

                continue


            result.append(
                contract
            )

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


    raw = data.get(
        "data",
        []
    )


    # Bazı cevaplarda tek dict gelebilir
    if isinstance(
        raw,
        dict
    ):

        if "resultList" in raw:

            raw = raw[
                "resultList"
            ]

        else:

            raw = [raw]


    if not isinstance(
        raw,
        list
    ):

        return {}


    result = {}


    for x in raw:

        try:

            symbol = str(
                x.get(
                    "symbol",
                    ""
                )
            ).upper()

            if not symbol:

                continue


            price = float(
                x.get(
                    "lastPrice",
                    0
                )
            )

            volume = float(
                x.get(
                    "amount24",
                    0
                )
            )

            if volume <= 0:

                volume = float(
                    x.get(
                        "volume24",
                        0
                    )
                )


            change = (
                float(
                    x.get(
                        "riseFallRate",
                        0
                    )
                )
                * 100
            )


            result[symbol] = {

                "price": price,

                "volume": volume,

                "change": change
            }

        except Exception:

            continue


    return result


# ============================================================
# FUTURES KLINE
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


    data = data.get(
        "data",
        {}
    )

    if not isinstance(
        data,
        dict
    ):

        return []


    opens = data.get(
        "open",
        []
    )

    closes = data.get(
        "close",
        []
    )

    highs = data.get(
        "high",
        []
    )

    lows = data.get(
        "low",
        []
    )

    volumes = data.get(
        "vol",
        []
    )

    times = data.get(
        "time",
        []
    )


    if not closes:

        return []


    candles = []


    count = min(
        len(opens),
        len(closes),
        len(highs),
        len(lows),
        len(volumes)
    )


    # Son limit mum
    start = max(
        0,
        count - limit
    )


    for i in range(
        start,
        count
    ):

        try:

            candles.append({

                "time":
                    int(
                        times[i]
                    )
                    if i < len(times)
                    else 0,

                "open":
                    float(
                        opens[i]
                    ),

                "high":
                    float(
                        highs[i]
                    ),

                "low":
                    float(
                        lows[i]
                    ),

                "close":
                    float(
                        closes[i]
                    ),

                "volume":
                    float(
                        volumes[i]
                    )
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

        change = (
            values[i]
            - values[i - 1]
        )


        if change >= 0:

            gains.append(
                change
            )

            losses.append(
                0
            )

        else:

            gains.append(
                0
            )

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

        return 100


    rs = (
        avg_gain
        / avg_loss
    )


    return (
        100
        - (
            100
            / (1 + rs)
        )
    )


# ============================================================
# 4H ANALİZ
# ============================================================

def analyze_4h(
    candles
):

    if len(candles) < 60:

        return None


    # Son mumun tamamlanmış olup olmadığını
    # API bazında kesinleştirmeden kullanıyoruz.
    # Fakat dip hesabında son 12 tamamlanmış mum:
    recent = candles[-13:-1]


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


    # ========================================================
    # DİP
    # ========================================================

    swing_low = min(
        x["low"]
        for x in recent
    )


    if swing_low <= 0:

        return None


    recovery = (
        (
            current
            - swing_low
        )
        / swing_low
    ) * 100


    # Çok dipte ve henüz dönüş başlamamış
    if recovery < 1.2:

        return None


    # Çok yükselmiş = pump zaten başlamış olabilir
    if recovery > 9.0:

        return None


    # ========================================================
    # SON 3 MUM
    # ========================================================

    last3 = candles[-3:]


    green_count = sum(
        1
        for x in last3
        if x["close"] > x["open"]
    )


    if green_count < 2:

        return None


    # ========================================================
    # EMA DÖNÜŞÜ
    # ========================================================

    ema_rising = (
        ema20
        > ema20_prev
    )


    if not ema_rising:

        return None


    # ========================================================
    # RSI
    # ========================================================

    if rsi_now < 38:

        return None


    if rsi_now > 63:

        return None


    # ========================================================
    # EMA MESAFE
    # ========================================================

    ema_distance = (
        (
            current
            - ema20
        )
        / ema20
    ) * 100


    if ema_distance < -2.5:

        return None


    if ema_distance > 6:

        return None


    # ========================================================
    # SCORE
    # ========================================================

    score = 0


    # Dip bölgesi
    if 1.2 <= recovery <= 4:

        score += 25

    elif 4 < recovery <= 6:

        score += 18

    elif 6 < recovery <= 9:

        score += 10


    # EMA yukarı
    score += 15


    # EMA20 üstü
    if current >= ema20:

        score += 15

    elif current >= (
        ema20 * 0.997
    ):

        score += 8


    # RSI
    if 42 <= rsi_now <= 55:

        score += 15

    elif 38 <= rsi_now < 42:

        score += 10

    elif 55 < rsi_now <= 63:

        score += 7


    # Son mum
    if current > previous:

        score += 10


    # Yeşil mum
    if green_count == 3:

        score += 10

    elif green_count == 2:

        score += 6


    return {

        "score": score,

        "current": current,

        "ema20": ema20,

        "ema50": ema50,

        "rsi": rsi_now,

        "swing_low": swing_low,

        "recovery": recovery
    }


# ============================================================
# 1H ANALİZ
# ============================================================

def analyze_1h(
    candles
):

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


    # ========================================================
    # EMA20
    # ========================================================

    if current >= ema20:

        score += 20

    elif current >= (
        ema20 * 0.997
    ):

        score += 12

    else:

        return None


    # ========================================================
    # EMA20 YUKARI
    # ========================================================

    if ema20 > ema20_prev:

        score += 20

    else:

        return None


    # ========================================================
    # EMA50
    # ========================================================

    if current > ema50:

        score += 15


    # ========================================================
    # RSI
    # ========================================================

    if 48 <= rsi_now <= 65:

        score += 15

    elif 43 <= rsi_now < 48:

        score += 8

    else:

        return None


    # ========================================================
    # SON MUM
    # ========================================================

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
# 15M ANALİZ
# ============================================================

def analyze_15m(
    candles
):

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
        ema20_prev,
        rsi_now
    ]):

        return None


    # ========================================================
    # EMA
    # ========================================================

    if current <= ema20:

        return None


    # ========================================================
    # EMA YUKARI
    # ========================================================

    if ema20 <= ema20_prev:

        return None


    # ========================================================
    # RSI
    # ========================================================

    if rsi_now < 48:

        return None


    if rsi_now > 70:

        return None


    # ========================================================
    # HACİM
    # ========================================================

    previous_volumes = [
        x["volume"]
        for x in candles[-21:-1]
    ]


    if not previous_volumes:

        return None


    avg_volume = (
        sum(
            previous_volumes
        )
        /
        len(
            previous_volumes
        )
    )


    current_volume = (
        candles[-1]["volume"]
    )


    if avg_volume <= 0:

        return None


    volume_ratio = (
        current_volume
        /
        avg_volume
    )


    # ========================================================
    # EN ÖNEMLİ YENİ FİLTRE
    #
    # 1.00x bile olmayan hacmi artık kabul etmiyoruz.
    #
    # Pump öncesi için en az 1.20x.
    # Güçlü sinyal için 1.50x+.
    # ========================================================

    if volume_ratio < 1.20:

        return None


    score = 0


    # EMA
    score += 15


    # EMA yukarı
    score += 10


    # RSI
    if 50 <= rsi_now <= 62:

        score += 15

    elif 48 <= rsi_now < 50:

        score += 8

    elif 62 < rsi_now <= 70:

        score += 8


    # Son mum
    if current > previous:

        score += 10


    # Hacim
    if volume_ratio >= 2.5:

        score += 30

    elif volume_ratio >= 2.0:

        score += 25

    elif volume_ratio >= 1.5:

        score += 20

    elif volume_ratio >= 1.2:

        score += 10


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
    contract,
    ticker
):

    symbol = contract.get(
        "symbol",
        ""
    )


    try:

        # ====================================================
        # TICKER
        # ====================================================

        change = float(
            ticker.get(
                "change",
                0
            )
        )


        volume = float(
            ticker.get(
                "volume",
                0
            )
        )


        price = float(
            ticker.get(
                "price",
                0
            )
        )


        if price <= 0:

            return None


        # ====================================================
        # 24H
        # ====================================================

        if volume < MIN_24H_VOLUME:

            return None


        if change < MIN_24H_CHANGE:

            return None


        if change > MAX_24H_CHANGE:

            return None


        # ====================================================
        # 4H
        # ====================================================

        candles_4h = get_klines(
            symbol,
            "Hour4",
            100
        )


        if not candles_4h:

            return None


        four = analyze_4h(
            candles_4h
        )


        if not four:

            return None


        # ====================================================
        # 1H
        # ====================================================

        candles_1h = get_klines(
            symbol,
            "Min60",
            100
        )


        if not candles_1h:

            return None


        one = analyze_1h(
            candles_1h
        )


        if not one:

            return None


        # ====================================================
        # 15M
        # ====================================================

        candles_15m = get_klines(
            symbol,
            "Min15",
            100
        )


        if not candles_15m:

            return None


        fifteen = analyze_15m(
            candles_15m
        )


        if not fifteen:

            return None


        # ====================================================
        # TOPLAM SKOR
        # ====================================================

        score = (
            four["score"]
            + one["score"]
            + fifteen["score"]
        )


        # Ek güçlü teyit
        if (
            four["recovery"] <= 6
            and
            fifteen["volume_ratio"] >= 1.5
        ):

            score += 5


        # ====================================================
        # MIN SCORE
        # ====================================================

        if score < MIN_SCORE:

            return None


        # ====================================================
        # ENTRY
        # ====================================================

        entry = price


        # ====================================================
        # TP
        # ====================================================

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


        # ====================================================
        # STOP
        # ====================================================

        stop = (
            entry
            * (
                1
                - STOP_PCT / 100
            )
        )


        return {

            "symbol":
                symbol,

            "score":
                score,

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

            "change":
                change,

            "volume":
                volume,

            "recovery":
                four["recovery"],

            "rsi4h":
                four["rsi"],

            "rsi1h":
                one["rsi"],

            "rsi15m":
                fifteen["rsi"],

            "volume_ratio":
                fifteen["volume_ratio"]
        }


    except Exception as e:

        print(
            symbol,
            "analiz:",
            e
        )

        return None


# ============================================================
# PRICE FORMAT
# ============================================================

def price_format(
    price
):

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
# SIGNAL MESSAGE
# ============================================================

def format_signal(
    x
):

    return (

        "🟢 <b>ERKEN PUMP ADAYI</b>\n\n"

        f"🪙 <b>{x['symbol']}</b>\n"

        f"⭐ <b>Skor: "
        f"{x['score']}/100</b>\n\n"

        f"🟢 <b>Giriş:</b> "
        f"{price_format(x['entry'])}\n"

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

        f"📉 4H dönüş: "
        f"+{x['recovery']:.2f}%\n"

        f"⚡ 15M hacim: "
        f"{x['volume_ratio']:.2f}x\n\n"

        f"🔎 4H RSI: "
        f"{x['rsi4h']:.1f}\n"

        f"🔎 1H RSI: "
        f"{x['rsi1h']:.1f}\n"

        f"🔎 15M RSI: "
        f"{x['rsi15m']:.1f}\n\n"

        "📌 <b>4H DİP + DÖNÜŞ</b>\n"
        "📈 <b>1H TREND TEYİDİ</b>\n"
        "⚡ <b>15M MOMENTUM + HACİM</b>\n\n"

        "⚠️ <i>Analiz sinyalidir, "
        "otomatik işlem açmaz.</i>"
    )


# ============================================================
# ANA SCAN
# ============================================================

def scan():

    print("")
    print("=" * 70)
    print("🚀 MEXC CRYPTO FUTURES PUMP RADAR")
    print("=" * 70)


    # ========================================================
    # CONTRACTS
    # ========================================================

    contracts = (
        get_futures_contracts()
    )


    if not contracts:

       
