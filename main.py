import os
import json
import time
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC CRYPTO FUTURES PUMP RADAR V3
#
# 🟡 ERKEN PUMP
# 🔥 PUMP BAŞLADI
# 🔻 PUMP SONRASI DÜŞÜŞ
#
# SADECE CRYPTO FUTURES
#
# ❌ STOCK
# ❌ ETF
# ❌ INDEX
# ❌ GOLD
# ❌ SILVER
# ❌ OIL
# ❌ EARN
#
# 4H = DIP / DÖNÜŞ
# 1H = TREND
# 15M = MOMENTUM + HACİM
# ============================================================


# ============================================================
# MEXC
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
    "")


# ============================================================
# AYARLAR
# ============================================================

# Daha fazla normal altcoin taransın
MIN_24H_VOLUME = 100000

# Çok sert düşenleri ilk aşamada ele
MIN_24H_CHANGE = -20

# Aşırı pump olmuşları erken pump kısmından çıkar
MAX_24H_CHANGE = 70


# ============================================================
# SKORLAR
# ============================================================

# Daha önce 72 idi
MIN_EARLY_SCORE = 65

# Daha önce 70 idi
MIN_DROP_SCORE = 65

# Pump başladı kategorisi
MIN_PUMP_SCORE = 70


# ============================================================
# MAKSİMUM TELEGRAM SİNYALİ
# ============================================================

MAX_SIGNALS_PER_SCAN = 6


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
    "User-Agent": "Mozilla/5.0 MEXC-Pump-Radar/3.0"
})


# ============================================================
# SADECE CRYPTO FİLTRESİ
# ============================================================

BLOCKED_KEYWORDS = [

    # Stock
    "STOCK",

    # ETF
    "ETF",

    # Index
    "INDEX",

    # EARN ürünleri
    "EARN",

    # Precious metals
    "SILVER",
    "GOLD",

    # Commodities
    "OIL",
    "BRENT",
    "WTI",

    # FX / traditional markets
    "FOREX",
    "EUR",
    "GBP",
    "JPY",
    "AUD",
    "CAD",
    "CHF",

    # Traditional market identifiers
    "SPX",
    "SP500",
    "NDX",
    "NASDAQ",
    "DOW",
    "DJI",

    # Common stock names
    "AAPL",
    "TSLA",
    "NVDA",
    "AMZN",
    "META",
    "MSFT",
    "GOOG",
    "GOOGL",
    "NFLX",
    "AMD",
    "COIN",
    "MSTR",
    "PLTR",

    # Metals symbols
    "XAU",
    "XAG",

]


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
            ) as f:

                data = json.load(f)

                if isinstance(
                    data,
                    dict
                ):

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

            print(
                "HTTP hata:",
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
            "GET hata:",
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

        "🟢 <b>PUMP RADAR AKTİF</b>\n\n"

        "✅ Telegram bağlantısı çalışıyor.\n"
        "✅ GitHub Actions çalışıyor.\n\n"

        "🚫 Stock / ETF / Index yok\n"
        "🚫 Gold / Silver / Oil yok\n"
        "🚫 EARN ürünleri yok\n"
        "💎 Sadece Crypto Futures\n\n"

        "🟡 Erken pump\n"
        "🔥 Pump başlayanlar\n"
        "🔻 Pump sonrası düşüş\n\n"

        "🔎 4H dip + dönüş\n"
        "📈 1H trend\n"
        "⚡ 15M momentum + hacim"

    )

    return send_telegram(
        message
    )


# ============================================================
# SYMBOL CRYPTO MU?
# ============================================================

def is_crypto_symbol(
    symbol,
    contract=None
):

    if not symbol:

        return False


    symbol_upper = symbol.upper()


    # --------------------------------------------------------
    # USDT şartı
    # --------------------------------------------------------

    if not symbol_upper.endswith(
        "_USDT"
    ):

        return False


    # --------------------------------------------------------
    # Kelime filtresi
    # --------------------------------------------------------

    for word in BLOCKED_KEYWORDS:

        if word in symbol_upper:

            return False


    # --------------------------------------------------------
    # Contract bilgisi
    # --------------------------------------------------------

    if contract:

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

        base_coin = str(
            contract.get(
                "baseCoin",
                ""
            )
        ).upper()


        if quote != "USDT":

            return False


        if settle != "USDT":

            return False


        if not base_coin:

            return False


        # Base coin de geleneksel ürün ise çıkar
        for word in BLOCKED_KEYWORDS:

            if word in base_coin:

                return False


    return True


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

        symbol = x.get(
            "symbol",
            ""
        )


        # Sadece aktif kontratlar
        state = x.get(
            "state",
            0
        )


        try:

            state = int(state)

        except Exception:

            state = 0


        # 0 = enabled
        if state != 0:

            continue


        if not is_crypto_symbol(
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

            symbol = x.get(
                "symbol",
                ""
            )


            if not is_crypto_symbol(
                symbol
            ):

                continue


            result[symbol] = {

                "price":
                    float(
                        x.get(
                            "lastPrice",
                            0
                        )
                        or 0
                    ),

                "change":
                    float(
                        x.get(
                            "riseFallRate",
                            0
                        )
                        or 0
                    ) * 100,

                "volume":
                    float(
                        x.get(
                            "amount24",
                            0
                        )
                        or 0
                    ),

                "volume_contract":
                    float(
                        x.get(
                            "volume24",
                            0
                        )
                        or 0
                    ),

                "high24":
                    float(
                        x.get(
                            "high24Price",
                            0
                        )
                        or 0
                    ),

                "low24":
                    float(
                        x.get(
                            "lower24Price",
                            0
                        )
                        or 0
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
                price
                - value
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
# HACİM ORANI
# ============================================================

def volume_ratio(
    candles,
    lookback=20
):

    if len(candles) < (
        lookback + 2
    ):

        return 0


    previous = [

        x["volume"]

        for x in candles[
            -(lookback + 1):-1
        ]

        if x["volume"] > 0

    ]


    if not previous:

        return 0


    avg = (
        sum(previous)
        / len(previous)
    )


    if avg <= 0:

        return 0


    return (
        candles[-1]["volume"]
        / avg
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
    # 4H DİP / TOPARLANMA
    # ========================================================

    recent4 = c4[-25:-1]


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


    # Çok uzaklaşmış coin erken pump değildir
    if recovery < 0.5:

        return None


    if recovery > 15:

        return None


    # ========================================================
    # 4H PUAN
    # ========================================================

    score = 0


    # Dipten dönüş
    if 1 <= recovery <= 6:

        score += 20

    elif recovery <= 10:

        score += 15

    else:

        score += 8


    # EMA yönü
    if ema20_4 > ema20_4_prev:

        score += 15


    # Fiyat EMA20 üstü
    if price >= ema20_4:

        score += 10

    elif price >= ema20_4 * 0.99:

        score += 6


    # EMA20 / EMA50
    if ema20_4 >= ema50_4:

        score += 8


    # RSI
    if 42 <= rsi4 <= 58:

        score += 12

    elif 38 <= rsi4 <= 63:

        score += 8


    # Son 3 mum
    green4 = sum(

        1

        for x in c4[-3:]

        if x["close"] > x["open"]

    )


    if green4 == 3:

        score += 8

    elif green4 >= 2:

        score += 5


    # ========================================================
    # 1H
    # ========================================================

    if ema20_1 > ema20_1_prev:

        score += 10


    if price >= ema20_1:

        score += 8


    if ema20_1 >= ema50_1:

        score += 5


    if 48 <= rsi1 <= 68:

        score += 8

    elif 42 <= rsi1 <= 72:

        score += 4


    # ========================================================
    # 15M
    # ========================================================

    if price >= ema20_15:

        score += 6


    if 48 <= rsi15 <= 68:

        score += 6

    elif 43 <= rsi15 <= 72:

        score += 3


    # ========================================================
    # HACİM
    # ========================================================

    vr = volume_ratio(
        c15
    )


    if vr >= 2.5:

        score += 10

    elif vr >= 1.5:

        score += 7

    elif vr >= 1.15:

        score += 4


    score = min(
        score,
        100
    )


    # ========================================================
    # MINIMUM ŞART
    # ========================================================

    if score < MIN_EARLY_SCORE:

        return None


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
            vr,

        "rsi4h":
            rsi4,

        "rsi1h":
            rsi1,

        "rsi15m":
            rsi15

    }


# ============================================================
# 🔥 PUMP BAŞLADI
# ============================================================

def analyze_pump(
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


    # Son 24 saat güçlü hareket
    change = ticker[
        "change"
    ]


    if change < 8:

        return None


    if change > 60:

        return None


    # Son 4H dip
    recent4 = c4[-25:-1]


    low4 = min(
        x["low"]
        for x in recent4
    )


    if low4 <= 0:

        return None


    move = (
        (
            price
            - low4
        )
        / low4
    ) * 100


    # Pump hareketi en az %6
    if move < 6:

        return None


    if move > 35:

        return None


    vr = volume_ratio(
        c15
    )


    score = 0


    # 24H
    if change >= 20:

        score += 20

    elif change >= 12:

        score += 15

    else:

        score += 10


    # 4H hareket
    if move >= 15:

        score += 20

    elif move >= 10:

        score += 15

    else:

        score += 10


    # 1H
    if price >= ema20_1:

        score += 15


    if 50 <= rsi1 <= 72:

        score += 10


    # 15M
    if price >= ema20_15:

        score += 10


    if 55 <= rsi15 <= 75:

        score += 10


    # Hacim
    if vr >= 3:

        score += 15

    elif vr >= 2:

        score += 10

    elif vr >= 1.4:

        score += 6


    score = min(
        score,
        100
    )


    if score < MIN_PUMP_SCORE:

        return None


    return {

        "type":
            "PUMP",

        "title":
            "🔥 PUMP BAŞLADI",

        "symbol":
            symbol,

        "score":
            score,

        "entry":
            price,

        "change":
            change,

        "recovery":
            move,

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


    price = ticker[
        "price"
    ]


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

        ema20_1,
        ema20_15,

        rsi4,
        rsi1,
        rsi15

    ]):

        return None


    # ========================================================
    # ZİRVE
    # ========================================================

    peak4 = max(
        x["high"]
        for x in c4[-20:-1]
    )


    peak15 = max(
        x["high"]
        for x in c15[-20:-1]
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
    if drop < 3:

        return None


    # Çok fazla düşmüşse artık
    # "pump sonrası erken düşüş" değil
    if drop > 18:

        return None


    # Pump yapmış olması gerekiyor
    if ticker["change"] < 5:

        return None


    score = 0


    # ========================================================
    # Pump büyüklüğü
    # ========================================================

    change = ticker[
        "change"
    ]


    if change >= 25:

        score += 20

    elif change >= 15:

        score += 15

    else:

        score += 10


    # ========================================================
    # Tepeden düşüş
    # ========================================================

    if 3 <= drop <= 6:

        score += 25

    elif drop <= 9:

        score += 20

    elif drop <= 13:

        score += 12

    else:

        score += 7


    # ========================================================
    # 15M RSI
    # ========================================================

    if rsi15 <= 48:

        score += 15

    elif rsi15 <= 55:

        score += 10

    elif rsi15 <= 60:

        score += 5


    # ========================================================
    # EMA
    # ========================================================

    if price < ema20_15:

        score += 12


    if price < ema20_1:

        score += 10


    # ========================================================
    # HACİM
    # ========================================================

    vr = volume_ratio(
        c15
    )


    if vr >= 2:

        score += 12

    elif vr >= 1.3:

        score += 8

    elif vr >= 1.05:

        score += 4


    score = min(
        score,
        100
    )


    if score < MIN_DROP_SCORE:

        return None


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
            vr,

        "rsi4h":
            rsi4,

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


        # ----------------------------------------------------
        # ERKEN PUMP
        # ----------------------------------------------------

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


        # ----------------------------------------------------
        # PUMP BAŞLADI
        # ----------------------------------------------------

        pump = analyze_pump(
            symbol,
            ticker,
            candles4,
            candles1,
            candles15
        )


        if pump:

            results.append(
                pump
            )


        # ----------------------------------------------------
        # PUMP SONRASI DÜŞÜŞ
        # ----------------------------------------------------

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

    entry = x[
        "entry"
    ]


    # --------------------------------------------------------
    # EARLY / PUMP
    # --------------------------------------------------------

    if x["type"] in [
        "EARLY",
        "PUMP"
    ]:

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


        if x["type"] == "PUMP":

            extra = (

                f"🔥 4H hareket: "
                f"+{x['recovery']:.2f}%\n"

            )

        else:

            extra = (

                f"📉 4H dipten dönüş: "
                f"+{x['recovery']:.2f}%\n"

            )


        return (

            f"{x['title']}\n\n"

            f"💎 <b>{x['symbol']}</b>\n"

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


    # --------------------------------------------------------
    # DROP
    # --------------------------------------------------------

    return (

        f"{x['title']}\n\n"

        f"💎 <b>{x['symbol']}</b>\n"

        f"⭐ <b>Skor: "
        f"{x['score']}/100</b>\n\n"

        f"📈 24H: "
        f"{x['change']:+.2f}%\n"

        f"📉 Tepeden düşüş: "
        f"-{x['drop']:.2f}%\n"

        f"⚡ 15M hacim: "
        f"{x['volume_ratio']:.2f}x\n\n"

        f"🔎 4H RSI: "
        f"{x['rsi4h']:.1f}\n"

        f"🔎 1H RSI: "
        f"{x['rsi1h']:.1f}\n"

        f"🔎 15M RSI: "
        f"{x['rsi15m']:.1f}\n\n"

        "⚠️ <b>Pump sonrası satış baskısı "
        "başlamış olabilir.</b>\n\n"

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
        "🚀 MEXC CRYPTO FUTURES PUMP RADAR V3"
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
            "❌ Crypto Futures alınamadı."
        )

        send_telegram(

            "🔴 <b>RADAR HATASI</b>\n\n"

            "MEXC Crypto Futures alınamadı."

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


        if volume < MIN_24H_VOLUME:

            continue


        if change < MIN_24H_CHANGE:

            continue


        # Aşırı pump olmuşları
        # erken pump kısmına sokmuyoruz
        if change > MAX_24H_CHANGE:

            continue


        filtered.append(

            (
                symbol,
                ticker
            )

        )


    # Hacmi yüksekler önce
    filtered.sort(

        key=lambda x:
        x[1]["volume"],

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
        "🔎 24H filtre:",
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

        send_telegram(

            "🟡 <b>RADAR</b>\n\n"

            "Ön filtreden coin geçmedi."

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


        total = len(
            futures
        )


        for i, future in enumerate(

            as_completed(
                futures
            ),

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

                    f"🔎 İlerleme: "
                    f"{i} / {total}"

                )


    # ========================================================
    # COIN + SİNYAL TİPİ TEKLE
    # ========================================================

    best = {}


    for candidate in candidates:

        key = (

            candidate["type"]
            + ":"
            + candidate["symbol"]

        )


        old = best.get(
            key
        )


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

        key=lambda x:
        x["score"],

        reverse=True

    )


    print("")
    print(
        "🔥 Bulunan güçlü aday:",
        len(candidates)
    )


    # ========================================================
    # TİP İSTATİSTİĞİ
    # ========================================================

    early_count = sum(

        1

        for x in candidates

        if x["type"] == "EARLY"

    )


    pump_count = sum(

        1

        for x in candidates

        if x["type"] == "PUMP"

    )


    drop_count = sum(

        1

        for x in candidates

        if x["type"] == "DROP"

    )


    print(
        "🟡 Early:",
        early_count
    )

    print(
        "🔥 Pump:",
        pump_count
    )

    print(
        "🔻 Drop:",
        drop_count
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

                clean_sent[
                    key
                ] = timestamp


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
            "🟡 Bu taramada güçlü aday yok."
        )

        print(
            "Filtreler çalışıyor ancak "
            "şartları sağlayan coin bulunamadı."
        )


    print("")
    print(
        "📨 Telegram gönderilen:",
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
