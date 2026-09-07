import os
import json
import time
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC CRYPTO FUTURES PUMP RADAR V5
#
# 🟡 ERKEN PUMP
# 🔥 GÜÇLÜ ERKEN PUMP
# 🔻 PUMP SONRASI DÜŞÜŞ
#
# SADECE MEXC USDT CRYPTO FUTURES
# STOCK / ETF / INDEX FİLTRELİ
# ============================================================


BASE = "https://contract.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================
# AYARLAR
# ============================================================

# 24H minimum hacim
MIN_24H_VOLUME = 250000

# Çok düşmüş coinleri alma
MIN_24H_CHANGE = -20

# Çoktan aşırı pump yapmış coinleri alma
MAX_24H_CHANGE = 60


# ============================================================
# SİNYAL PUANLARI
# ============================================================

# Erken pump
MIN_EARLY_SCORE = 65

# Güçlü erken pump
STRONG_EARLY_SCORE = 75

# Pump sonrası düşüş
MIN_DROP_SCORE = 68


# ============================================================
# MAKSİMUM SİNYAL
# ============================================================

MAX_SIGNALS_PER_SCAN = 4


# ============================================================
# AYNI COİN TEKRAR SÜRESİ
# ============================================================

DUPLICATE_HOURS = 4


# ============================================================
# PARALEL TARAMA
# ============================================================

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
    "User-Agent": "Mozilla/5.0 MEXC-Pump-Radar-V5"
})


# ============================================================
# STOCK / ETF / INDEX KORUMASI
# ============================================================

BLOCK_WORDS = [

    "STOCK",
    "ETF",
    "INDEX",
    "INDEXES",
    "SP500",
    "SPX",
    "NASDAQ",
    "DOW",
    "DJI",
    "NYSE",
    "TSLA",
    "AAPL",
    "AMZN",
    "GOOG",
    "GOOGL",
    "META",
    "MSFT",
    "NVDA",
    "NFLX",
    "COIN",
    "MSTR",
    "HOOD",
    "PLTR",
    "AMD",
    "INTC",
    "BA",
    "DIS",
    "NIO",
    "PFE",
    "QQQ",
    "SPY",
    "DXY",
    "GOLD",
    "SILVER",
    "OIL",
    "BRENT",
    "WTI"
]


def is_normal_crypto_contract(symbol, data=None):

    """
    Sadece normal crypto futures bırakmaya çalışır.

    Örnek:
    BTC_USDT      -> EVET
    ETH_USDT      -> EVET
    NEAR_USDT     -> EVET

    STOCK / ETF / INDEX benzeri:
    -> HAYIR
    """

    if not symbol:
        return False

    symbol_upper = symbol.upper()

    # USDT zorunlu
    if not symbol_upper.endswith("_USDT"):
        return False

    # Blok kelimeleri
    for word in BLOCK_WORDS:

        if word in symbol_upper:

            return False


    # API contract bilgisi varsa ayrıca kontrol
    if isinstance(data, dict):

        base_coin = str(
            data.get("baseCoin", "")
        ).upper()

        quote_coin = str(
            data.get("quoteCoin", "")
        ).upper()

        settle_coin = str(
            data.get("settleCoin", "")
        ).upper()


        if quote_coin and quote_coin != "USDT":
            return False

        if settle_coin and settle_coin != "USDT":
            return False


        combined = (
            symbol_upper
            + "_"
            + base_coin
        )


        for word in BLOCK_WORDS:

            if word in combined:

                return False


    return True


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
            "sent_signals okuma hatası:",
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
            "sent_signals yazma hatası:",
            e
        )


# ============================================================
# GENERIC GET
# ============================================================

def get_json(
    url,
    params=None
):

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
            "❌ Telegram hata:",
            e
        )


    return False


# ============================================================
# TELEGRAM TEST
# ============================================================

def telegram_test():

    message = (

        "🟢 <b>PUMP RADAR V5 AKTİF</b>\n\n"

        "✅ Telegram bağlantısı çalışıyor.\n"
        "✅ GitHub Actions çalışıyor.\n\n"

        "💎 Sadece MEXC Crypto Futures\n"
        "🚫 Stock / ETF / Index yok\n\n"

        "🔎 4H dip + dönüş\n"
        "📈 1H trend\n"
        "⚡ 15M momentum\n"
        "📊 Hacim artışı\n"
        "🔻 Pump sonrası düşüş\n\n"

        "🎯 Daha esnek puanlama sistemi aktif."
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


    if not isinstance(rows, list):

        return []


    result = []


    for x in rows:

        if not isinstance(x, dict):

            continue


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
        # USDT FUTURES
        # ----------------------------------------------------

        if not symbol.endswith("_USDT"):
            continue


        if quote and quote != "USDT":
            continue


        if settle and settle != "USDT":
            continue


        # ----------------------------------------------------
        # STOCK / ETF / INDEX ENGELİ
        # ----------------------------------------------------

        if not is_normal_crypto_contract(
            symbol,
            x
        ):

            continue


        result.append(
            symbol
        )


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

            symbol = str(
                x.get(
                    "symbol",
                    ""
                )
            ).upper()


            if not is_normal_crypto_contract(
                symbol
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

                "price": price,

                "change": change,

                "volume": volume,

                "volume_contract":
                    volume_contract,

                "high24": high24,

                "low24": low24
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

                "open": float(
                    opens[i]
                ),

                "high": float(
                    highs[i]
                ),

                "low": float(
                    lows[i]
                ),

                "close": float(
                    closes[i]
                ),

                "volume": float(
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
# VOLUME RATIO
# ============================================================

def get_volume_ratio(candles):

    if len(candles) < 22:

        return 0


    volumes = [

        x["volume"]

        for x in candles[-21:-1]

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
        candles[-1]["volume"]
        / avg_volume
    )


# ============================================================
# ERKEN PUMP V5
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


    # ========================================================
    # EMA
    # ========================================================

    ema20_4 = ema(
        close4,
        20
    )

    ema50_4 = ema(
        close4,
        50
    )

    ema20_4_prev = ema(
        close4[:-1],
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

    ema20_1_prev = ema(
        close1[:-1],
        20
    )


    ema20_15 = ema(
        close15,
        20
    )


    # ========================================================
    # RSI
    # ========================================================

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


    # ========================================================
    # 4H DİP
    # ========================================================

    recent4 = c4[-17:-1]


    if len(recent4) < 8:

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


    # Çok yukarı kaçmış coinleri alma
    if recovery > 12:

        return None


    # Aşırı zayıf coin
    if rsi4 < 30:

        return None


    # Aşırı pump bölgesi
    if rsi4 > 72:

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


    # --------------------------------------------------------
    # 4H DIP
    # --------------------------------------------------------

    if recovery <= 2:

        score += 20

    elif recovery <= 4:

        score += 18

    elif recovery <= 6:

        score += 15

    elif recovery <= 9:

        score += 10

    else:

        score += 5


    # --------------------------------------------------------
    # 4H RSI
    # --------------------------------------------------------

    if 40 <= rsi4 <= 55:

        score += 15

    elif 35 <= rsi4 < 40:

        score += 12

    elif 55 < rsi4 <= 62:

        score += 12

    elif 62 < rsi4 <= 70:

        score += 7


    # --------------------------------------------------------
    # 4H EMA DÖNÜŞ
    # --------------------------------------------------------

    if ema20_4 > ema20_4_prev:

        score += 15

    elif ema20_4 >= ema20_4_prev * 0.999:

        score += 8


    # --------------------------------------------------------
    # 4H EMA KONUM
    # --------------------------------------------------------

    if price >= ema20_4:

        score += 10

    elif price >= ema20_4 * 0.985:

        score += 7

    elif price >= ema50_4:

        score += 4


    # --------------------------------------------------------
    # 1H TREND
    # --------------------------------------------------------

    if ema20_1 > ema20_1_prev:

        score += 10


    if price >= ema20_1:

        score += 8

    elif price >= ema20_1 * 0.985:

        score += 4


    # --------------------------------------------------------
    # 1H RSI
    # --------------------------------------------------------

    if 42 <= rsi1 <= 60:

        score += 8

    elif 38 <= rsi1 < 42:

        score += 5

    elif 60 < rsi1 <= 68:

        score += 5


    # --------------------------------------------------------
    # 15M MOMENTUM
    # --------------------------------------------------------

    if price >= ema20_15:

        score += 8

    elif price >= ema20_15 * 0.985:

        score += 5


    # --------------------------------------------------------
    # 15M RSI
    # --------------------------------------------------------

    if 42 <= rsi15 <= 60:

        score += 7

    elif 38 <= rsi15 < 42:

        score += 5

    elif 60 < rsi15 <= 68:

        score += 4


    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    if volume_ratio >= 2.0:

        score += 12

    elif volume_ratio >= 1.5:

        score += 9

    elif volume_ratio >= 1.2:

        score += 6

    elif volume_ratio >= 0.8:

        score += 2


    # --------------------------------------------------------
    # 24H DEĞİŞİM
    # --------------------------------------------------------

    change = ticker["change"]


    # Erken pump için en güzel bölge
    if -2 <= change <= 8:

        score += 8

    elif 8 < change <= 15:

        score += 5

    elif -8 <= change < -2:

        score += 4


    score = min(
        score,
        100
    )


    # ========================================================
    # YAPISAL KONTROL
    # ========================================================

    # Çok aşırı düşen coinleri ele
    if rsi15 < 28:

        return None


    # 24H çoktan uçmuşsa erken pump değildir
    if change > 60:

        return None


    # ========================================================
    # SONUÇ
    # ========================================================

    if score < MIN_EARLY_SCORE:

        return None


    if score >= STRONG_EARLY_SCORE:

        title = "🔥 GÜÇLÜ ERKEN PUMP"

    else:

        title = "🟡 ERKEN PUMP ADAYI"


    return {

        "type": "EARLY",

        "title": title,

        "symbol": symbol,

        "score": score,

        "entry": price,

        "change": change,

        "recovery": recovery,

        "volume_ratio": volume_ratio,

        "rsi4h": rsi4,

        "rsi1h": rsi1,

        "rsi15m": rsi15
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


    # ========================================================
    # PUMP ZİRVESİ
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
        (peak - price)
        / peak
    ) * 100


    # Çok küçük düşüş
    if drop < 3:

        return None


    # Çok büyük çöküş
    if drop > 18:

        return None


    # 24H halen pozitif/kuvvetli olmalı
    if ticker["change"] < 3:

        return None


    # RSI
    if rsi15 > 62:

        return None


    if rsi1 > 68:

        return None


    volume_ratio = get_volume_ratio(
        c15
    )


    score = 0


    # ========================================================
    # DÜŞÜŞ MESAFESİ
    # ========================================================

    if 3 <= drop <= 6:

        score += 25

    elif drop <= 9:

        score += 20

    elif drop <= 12:

        score += 14

    else:

        score += 7


    # ========================================================
    # PUMP GÜCÜ
    # ========================================================

    change = ticker["change"]


    if change >= 20:

        score += 20

    elif change >= 12:

        score += 17

    elif change >= 7:

        score += 13

    else:

        score += 8


    # ========================================================
    # RSI
    # ========================================================

    if rsi15 <= 45:

        score += 15

    elif rsi15 <= 52:

        score += 10

    else:

        score += 5


    # ========================================================
    # EMA
    # ========================================================

    if price < ema20_15:

        score += 10


    if price < ema20_1:

        score += 10


    # ========================================================
    # HACİM
    # ========================================================

    if volume_ratio >= 1.5:

        score += 10

    elif volume_ratio >= 1.1:

        score += 6

    elif volume_ratio >= 0.8:

        score += 2


    score = min(
        score,
        100
    )


    if score < MIN_DROP_SCORE:

        return None


    return {

        "type": "DROP",

        "title":
            "🔻 PUMP SONRASI DÜŞÜŞ",

        "symbol": symbol,

        "score": score,

        "entry": price,

        "change": change,

        "drop": drop,

        "volume_ratio": volume_ratio,

        "rsi4h":
            rsi(
                close4
            ),

        "rsi1h": rsi1,

        "rsi15m": rsi15
    }


# ============================================================
# COIN ANALİZİ
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
        # ERKEN PUMP
        # ====================================================

        early = analyze_early(
            symbol,
            ticker,
            candles4,
            candles1,
            candles15
        )


        if early:

            results.append(
                early
            )


        # ====================================================
        # PUMP SONRASI
        # ====================================================

        drop = analyze_drop(
            symbol,
            ticker,
            candles4,
            candles1,
            candles15
        )


        if drop:

            results.append(
                drop
            )


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


    if x["type"] == "DROP":

        # Düşüş sonrası LONG için
        # normal TP / STOP
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


        extra = (
            f"📉 Zirveden düşüş: "
            f"-{x['drop']:.2f}%\n"
        )


    else:

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


        extra = (
            f"📈 4H dipten dönüş: "
            f"+{x['recovery']:.2f}%\n"
        )


    return (

        f"{x['title']}\n\n"

        f"💎 <b>{x['symbol']}</b>\n"

        f"🟢 <b>LONG</b>\n"

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
        f"{price_format(stop)}</b>\n\n"

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
    print("=" * 60)

    print(
        "🚀 MEXC CRYPTO FUTURES PUMP RADAR V5"
    )

    print("=" * 60)


    # ========================================================
    # CONTRACTS
    # ========================================================

    contracts = (
        get_futures_contracts()
    )


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

    tickers = (
        get_futures_tickers()
    )


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


        # Hacim
        if volume < MIN_24H_VOLUME:

            continue


        # Çok düşmüş
        if change < MIN_24H_CHANGE:

            continue


        # Çok pump olmuş
        if change > MAX_24H_CHANGE:

            continue


        # Tekrar güvenlik kontrolü
        if not is_normal_crypto_contract(
            symbol
        ):

            continue


        filtered.append(
            (
                symbol,
                ticker
            )
        )


    # ========================================================
    # HACMİ YÜKSEKLER ÖNCE
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
        "🔎 Detaylı tarama:",
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


    candidates = sorted(
        best.values(),
        key=lambda x: x["score"],
        reverse=True
    )


    # ========================================================
    # SAYIM
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
    # SENT DOSYASI
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
