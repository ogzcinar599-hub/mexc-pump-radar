import os
import json
import math
import time
import threading
import requests


# ============================================================
# 🚨 MEXC SUPPLY / DEMAND RADAR V18.0
#
# SADECE:
# ✅ MEXC USDT CRYPTO FUTURES
# ✅ 4H SUPPLY
# ✅ 4H DEMAND
# ✅ SWING LENGTH = 10
# ✅ HISTORY TO KEEP = 20
# ✅ ATR LENGTH = 14
# ✅ BOX WIDTH = 2.5
# ✅ FİYAT BÖLGEYE GELİNCE ALARM
#
# ❌ RSI YOK
# ❌ PARA AKIŞI YOK
# ❌ PRE-PUMP SKORU YOK
# ❌ TP YOK
# ❌ STOP YOK
# ❌ OTOMATİK İŞLEM YOK
#
# AMAÇ:
# TradingView'deki Supply / Demand bölgelerine
# mümkün olduğunca yakın alarm üretmek.
# ============================================================


# ============================================================
# MEXC
# ============================================================

BASE = "https://api.mexc.com"


# ============================================================
# TELEGRAM
# ============================================================

TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


# ============================================================
# TRADINGVIEW AYARLARINA GÖRE
# ============================================================

SWING_LENGTH = 10

HISTORY_TO_KEEP = 20

ATR_LENGTH = 14

BOX_WIDTH = 2.5


# ============================================================
# TARAMA
# ============================================================

MAX_SYMBOLS = 300

KLINE_COUNT = 180


# ============================================================
# FİYAT BÖLGEYE NE KADAR YAKLAŞIRSA ALARM?
#
# 0.00 = sadece zone içine girerse
#
# 0.003 = %0.30 yakınına kadar
#
# TradingView benzeri daha temiz alarm için
# küçük tutuldu.
# ============================================================

ZONE_ENTRY_TOLERANCE = 0.003


# ============================================================
# ZONE GEÇERLİLİK
# ============================================================

# Aynı zone tekrar tekrar alarm vermesin.

STATE_FILE = "sd_state_v180.json"

STATE_TTL = 21600


# ============================================================
# RATE LIMIT
# ============================================================

REQUEST_INTERVAL = 0.13

MAX_RETRY = 4

BACKOFF_BASE = 1.0

rate_lock = threading.Lock()

last_request_time = 0.0


# ============================================================
# NON CRYPTO
# ============================================================

NON_CRYPTO = {

    "TSLA",
    "TESLA",

    "AAPL",
    "APPLE",

    "NVDA",
    "NVIDIA",

    "MSFT",
    "MICROSOFT",

    "AMZN",
    "AMAZON",

    "GOOGL",
    "GOOG",
    "GOOGLE",

    "META",

    "MSTR",
    "MICROSTRATEGY",

    "COIN",
    "COINBASE",

    "AMD",
    "INTC",
    "NFLX",
    "PLTR",
    "BABA",
    "JPM",
    "BAC",
    "WMT",
    "DIS",
    "NKE",
    "PFE",
    "XOM",
    "CVX",
    "BA",
    "ORCL",
    "CRM",
    "AVGO",
    "QCOM",
    "UBER",
    "PYPL",
    "SHOP",
    "T",
    "V",
    "MA",

    "SPX",
    "SPX500",
    "US500",

    "NAS100",
    "NASDAQ",
    "NDX",

    "US30",
    "DJI",
    "DOW",

    "DAX",
    "GER40",

    "UK100",
    "FTSE",

    "JPN225",
    "JP225",

    "XAU",
    "XAG",
    "XPT",
    "XPD",

    "GOLD",
    "SILVER",
    "PLATINUM",

    "COPPER",

    "WTI",
    "USOIL",
    "OIL",

    "BRENT",
    "UKOIL",

    "NGAS",
    "NATGAS",

    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "USDCAD",
    "NZDUSD",

    "EURGBP",
    "EURJPY",
    "GBPJPY"
}


# ============================================================
# KEYWORDS
# ============================================================

NON_CRYPTO_KEYWORDS = {

    "STOCK",
    "SHARE",
    "INDEX",
    "NASDAQ",
    "NYSE",
    "FOREX",
    "GOLD",
    "SILVER",
    "OIL",
    "CRUDE",
    "COPPER",
    "TESLA",
    "APPLE",
    "NVIDIA",
    "MICROSOFT",
    "AMAZON",
    "META",
    "GOOGLE"
}


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({

    "User-Agent":
        "Mozilla/5.0 MEXC-SUPPLY-DEMAND-RADAR/18.0",

    "Accept":
        "application/json"

})


# ============================================================
# STATS
# ============================================================

stats = {

    "contracts": 0,

    "crypto": 0,

    "non_crypto": 0,

    "tickers": 0,

    "klines": 0,

    "supply_zones": 0,

    "demand_zones": 0,

    "price_in_zone": 0,

    "alerts": 0,

    "errors": 0,

    "rate_510": 0

}


# ============================================================
# NUMBER
# ============================================================

def fnum(
    value,
    default=0.0
):

    try:

        return float(value)

    except Exception:

        return default


# ============================================================
# CLAMP
# ============================================================

def clamp(
    value,
    low,
    high
):

    return max(

        low,

        min(
            high,
            value
        )

    )


# ============================================================
# PRICE
# ============================================================

def price(
    value
):

    value = fnum(value)

    if value >= 1000:

        return f"{value:,.2f}"

    if value >= 1:

        return f"{value:.4f}"

    if value >= 0.01:

        return f"{value:.6f}"

    if value >= 0.0001:

        return f"{value:.8f}"

    if value >= 0.00001:

        return f"{value:.9f}"

    return f"{value:.12f}"


# ============================================================
# RATE LIMIT
# ============================================================

def rate_wait():

    global last_request_time

    with rate_lock:

        now = time.time()

        elapsed = (
            now
            -
            last_request_time
        )

        if elapsed < REQUEST_INTERVAL:

            time.sleep(
                REQUEST_INTERVAL
                -
                elapsed
            )

        last_request_time = time.time()


# ============================================================
# API GET
# ============================================================

def api_get(
    url,
    params=None
):

    for attempt in range(
        MAX_RETRY + 1
    ):

        rate_wait()

        try:

            response = session.get(

                url,

                params=params,

                timeout=15

            )

            # ==================================================
            # RATE LIMIT
            # ==================================================

            if response.status_code == 510:

                stats[
                    "rate_510"
                ] += 1

                wait_time = (

                    BACKOFF_BASE
                    *
                    (
                        2 ** attempt
                    )

                )

                print(

                    f"⚠️ 510 | "
                    f"{wait_time:.1f}s"

                )

                time.sleep(
                    wait_time
                )

                continue

            # ==================================================
            # HTTP ERROR
            # ==================================================

            if not response.ok:

                stats[
                    "errors"
                ] += 1

                return None

            # ==================================================
            # JSON
            # ==================================================

            try:

                data = response.json()

            except Exception:

                stats[
                    "errors"
                ] += 1

                return None

            # ==================================================
            # BODY 510
            # ==================================================

            if isinstance(
                data,
                dict
            ):

                if str(

                    data.get(
                        "code",
                        ""
                    )

                ) == "510":

                    stats[
                        "rate_510"
                    ] += 1

                    wait_time = (

                        BACKOFF_BASE
                        *
                        (
                            2 ** attempt
                        )

                    )

                    time.sleep(
                        wait_time
                    )

                    continue

            return data

        except Exception as e:

            stats[
                "errors"
            ] += 1

            print(
                "API:",
                e
            )

            time.sleep(
                0.5
            )

    return None


# ============================================================
# KRİPTO KONTROL
# ============================================================

def is_crypto_contract(
    item
):

    symbol = str(

        item.get(
            "symbol",
            ""
        )

    ).upper()

    base_coin = str(

        item.get(
            "baseCoin",
            ""
        )

    ).upper()

    quote_coin = str(

        item.get(
            "quoteCoin",
            ""
        )

    ).upper()

    settle_coin = str(

        item.get(
            "settleCoin",
            ""
        )

    ).upper()

    text = (

        symbol
        +
        " "
        +
        base_coin

    ).upper()

    # ========================================================
    # SADECE USDT
    # ========================================================

    if settle_coin:

        if settle_coin != "USDT":

            return False

    if quote_coin:

        if quote_coin != "USDT":

            return False

    # ========================================================
    # BİLİNEN NON CRYPTO
    # ========================================================

    if base_coin in NON_CRYPTO:

        return False

    clean_symbol = symbol.replace(
        "_USDT",
        ""
    )

    if clean_symbol in NON_CRYPTO:

        return False

    # ========================================================
    # KEYWORD
    # ========================================================

    for keyword in NON_CRYPTO_KEYWORDS:

        if keyword in text:

            return False

    return True


# ============================================================
# CONTRACTS
# ============================================================

def get_contracts():

    data = api_get(

        f"{BASE}/api/v1/contract/detail"

    )

    if not isinstance(
        data,
        dict
    ):

        return {}

    rows = data.get(
        "data",
        []
    )

    if not isinstance(
        rows,
        list
    ):

        return {}

    contracts = {}

    for item in rows:

        symbol = str(

            item.get(
                "symbol",
                ""
            )

        ).upper()

        if not symbol.endswith(
            "_USDT"
        ):

            continue

        if not is_crypto_contract(
            item
        ):

            stats[
                "non_crypto"
            ] += 1

            continue

        contracts[
            symbol
        ] = {

            "base_coin":
                str(
                    item.get(
                        "baseCoin",
                        ""
                    )
                ).upper(),

            "contract_size":
                fnum(
                    item.get(
                        "contractSize",
                        1
                    ),
                    1
                )

        }

    stats[
        "contracts"
    ] = len(contracts)

    stats[
        "crypto"
    ] = len(contracts)

    return contracts


# ============================================================
# TICKERS
# ============================================================

def get_tickers():

    data = api_get(

        f"{BASE}/api/v1/contract/ticker"

    )

    if not isinstance(
        data,
        dict
    ):

        return {}

    rows = data.get(
        "data",
        []
    )

    if not isinstance(
        rows,
        list
    ):

        return {}

    result = {}

    for item in rows:

        symbol = str(

            item.get(
                "symbol",
                ""
            )

        ).upper()

        if not symbol:

            continue

        result[
            symbol
        ] = item

    stats[
        "tickers"
    ] = len(result)

    return result


# ============================================================
# 4H KLINE
# ============================================================

def get_4h_kline(
    symbol
):

    now = int(
        time.time()
    )

    candle_seconds = (
        4 * 60 * 60
    )

    start = (

        now
        -
        (
            KLINE_COUNT
            *
            candle_seconds
        )

    )

    data = api_get(

        f"{BASE}/api/v1/contract/kline/{symbol}",

        {

            "interval":
                "Hour4",

            "start":
                start,

            "end":
                now

        }

    )

    if not isinstance(
        data,
        dict
    ):

        return []

    raw = data.get(
        "data"
    )

    if not isinstance(
        raw,
        dict
    ):

        return []

    required = [

        "open",
        "close",
        "high",
        "low",
        "vol"

    ]

    for key in required:

        if key not in raw:

            return []

    try:

        count = min(

            len(
                raw[key]
            )

            for key in required

        )

    except Exception:

        return []

    if count < 60:

        return []

    candles = []

    for i in range(
        count
    ):

        o = fnum(
            raw["open"][i]
        )

        c = fnum(
            raw["close"][i]
        )

        h = fnum(
            raw["high"][i]
        )

        l = fnum(
            raw["low"][i]
        )

        v = fnum(
            raw["vol"][i]
        )

        if (

            o <= 0
            or
            c <= 0
            or
            h <= 0
            or
            l <= 0

        ):

            continue

        candles.append({

            "open":
                o,

            "close":
                c,

            "high":
                h,

            "low":
                l,

            "vol":
                v

        })

    if len(candles) >= 60:

        stats[
            "klines"
        ] += 1

    return candles


# ============================================================
# TRUE RANGE
# ============================================================

def true_ranges(
    candles
):

    if len(candles) < 2:

        return []

    result = []

    for i in range(
        1,
        len(candles)
    ):

        current = candles[i]

        previous = candles[
            i - 1
        ]

        tr = max(

            current["high"]
            -
            current["low"],

            abs(

                current["high"]
                -
                previous["close"]

            ),

            abs(

                current["low"]
                -
                previous["close"]

            )

        )

        result.append(
            tr
        )

    return result


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    candles,
    period=14
):

    if len(candles) < period + 2:

        return 0.0

    trs = true_ranges(
        candles
    )

    if len(trs) < period:

        return 0.0

    # Wilder benzeri ATR

    atr = (

        sum(
            trs[:period]
        )
        /
        period

    )

    for tr in trs[period:]:

        atr = (

            (
                atr
                *
                (period - 1)
            )
            +
            tr

        ) / period

    return atr


# ============================================================
# PIVOT HIGH
# ============================================================

def is_pivot_high(
    candles,
    index,
    length
):

    if index < length:

        return False

    if (

        index + length
        >=
        len(candles)

    ):

        return False

    current_high = candles[
        index
    ]["high"]

    for i in range(

        index - length,

        index + length + 1

    ):

        if i == index:

            continue

        if candles[i]["high"] > current_high:

            return False

    return True


# ============================================================
# PIVOT LOW
# ============================================================

def is_pivot_low(
    candles,
    index,
    length
):

    if index < length:

        return False

    if (

        index + length
        >=
        len(candles)

    ):

        return False

    current_low = candles[
        index
    ]["low"]

    for i in range(

        index - length,

        index + length + 1

    ):

        if i == index:

            continue

        if candles[i]["low"] < current_low:

            return False

    return True


# ============================================================
# ZONE WIDTH
#
# TradingView Box Width = 2.5 değerini doğrudan yüzde olarak
# kullanmıyoruz.
#
# ATR tabanlı bir zone oluşturuyoruz.
#
# 2.5 → zone genişliğinin ATR'nin kontrollü bir bölümü.
# ============================================================

def zone_width(
    atr
):

    if atr <= 0:

        return 0.0

    width = (

        atr
        *
        (
            BOX_WIDTH
            /
            10.0
        )

    )

    return width


# ============================================================
# DEMAND ZONE
# ============================================================

def build_demand_zone(
    candles,
    pivot_index,
    atr
):

    pivot = candles[
        pivot_index
    ]

    width = zone_width(
        atr
    )

    if width <= 0:

        return None

    # ========================================================
    # Demand zone:
    #
    # pivot low merkez alınır.
    #
    # Mumun gerçek gövdesi ile wick dikkate alınır.
    # ========================================================

    candle_low = pivot[
        "low"
    ]

    body_low = min(

        pivot["open"],

        pivot["close"]

    )

    body_high = max(

        pivot["open"],

        pivot["close"]

    )

    # Ana bölge pivot low çevresinde

    zone_low = candle_low

    zone_high = min(

        body_high,

        candle_low + width

    )

    # Çok dar ise ATR genişliği

    if zone_high <= zone_low:

        zone_high = (

            zone_low
            +
            width

        )

    return {

        "type":
            "DEMAND",

        "low":
            zone_low,

        "high":
            zone_high,

        "pivot_index":
            pivot_index,

        "pivot_price":
            candle_low,

        "atr":
            atr

    }


# ============================================================
# SUPPLY ZONE
# ============================================================

def build_supply_zone(
    candles,
    pivot_index,
    atr
):

    pivot = candles[
        pivot_index
    ]

    width = zone_width(
        atr
    )

    if width <= 0:

        return None

    candle_high = pivot[
        "high"
    ]

    body_high = max(

        pivot["open"],

        pivot["close"]

    )

    body_low = min(

        pivot["open"],

        pivot["close"]

    )

    zone_high = candle_high

    zone_low = max(

        body_low,

        candle_high - width

    )

    if zone_high <= zone_low:

        zone_low = (

            zone_high
            -
            width

        )

    return {

        "type":
            "SUPPLY",

        "low":
            zone_low,

        "high":
            zone_high,

        "pivot_index":
            pivot_index,

        "pivot_price":
            candle_high,

        "atr":
            atr

    }


# ============================================================
# ZONE DOĞRULAMA
#
# Pivotun gerçekten güçlü bir dönüş bölgesi olup olmadığını
# kontrol ediyoruz.
# ============================================================

def validate_demand(
    candles,
    zone
):

    idx = zone[
        "pivot_index"
    ]

    # Pivot sonrası minimum 3 mum gerekli

    if idx + 3 >= len(candles):

        return False

    pivot_low = zone[
        "pivot_price"
    ]

    future = candles[
        idx + 1:
        min(
            idx + 9,
            len(candles)
        )
    ]

    if not future:

        return False

    highest_after = max(

        x["high"]
        for x in future

    )

    # Demand'dan anlamlı uzaklaşma

    move = (

        (
            highest_after
            /
            pivot_low
        )
        -
        1

    )

    # En az yaklaşık %0.8 hareket

    if move < 0.008:

        return False

    return True


# ============================================================
# SUPPLY DOĞRULAMA
# ============================================================

def validate_supply(
    candles,
    zone
):

    idx = zone[
        "pivot_index"
    ]

    if idx + 3 >= len(candles):

        return False

    pivot_high = zone[
        "pivot_price"
    ]

    future = candles[
        idx + 1:
        min(
            idx + 9,
            len(candles)
        )
    ]

    if not future:

        return False

    lowest_after = min(

        x["low"]
        for x in future

    )

    move = (

        1
        -
        (
            lowest_after
            /
            pivot_high
        )

    )

    if move < 0.008:

        return False

    return True


# ============================================================
# ZONE ID
# ============================================================

def zone_id(
    symbol,
    zone
):

    return (

        f"{symbol}_"
        f"{zone['type']}_"
        f"{zone['pivot_index']}_"
        f"{round(zone['low'], 12)}_"
        f"{round(zone['high'], 12)}"

    )


# ============================================================
# ZONE'LARI BUL
#
# History To Keep = 20
# Son 20 geçerli pivot içerisinden
# Supply / Demand bölgelerini bulur.
# ============================================================

def find_zones(
    symbol,
    candles
):

    if len(candles) < 80:

        return []

    atr = calculate_atr(

        candles,

        ATR_LENGTH

    )

    if atr <= 0:

        return []

    zones = []

    # Son tamamlanmış bölgelere bak.
    #
    # En son 10 mum pivot doğrulaması için kullanılamayacağı
    # için sondan 11 mum önceye kadar tarıyoruz.

    last_confirmed_index = (

        len(candles)
        -
        SWING_LENGTH
        -
        1

    )

    first_index = max(

        SWING_LENGTH,

        last_confirmed_index
        -
        HISTORY_TO_KEEP
        -
        1

    )

    for index in range(

        first_index,

        last_confirmed_index + 1

    ):

        # ====================================================
        # PIVOT HIGH
        # ====================================================

        if is_pivot_high(

            candles,

            index,

            SWING_LENGTH

        ):

            zone = build_supply_zone(

                candles,

                index,

                atr

            )

            if zone and validate_supply(

                candles,

                zone

            ):

                zones.append(
                    zone
                )

                stats[
                    "supply_zones"
                ] += 1

        # ====================================================
        # PIVOT LOW
        # ====================================================

        if is_pivot_low(

            candles,

            index,

            SWING_LENGTH

        ):

            zone = build_demand_zone(

                candles,

                index,

                atr

            )

            if zone and validate_demand(

                candles,

                zone

            ):

                zones.append(
                    zone
                )

                stats[
                    "demand_zones"
                ] += 1

    # ========================================================
    # EN YENİLER
    # ========================================================

    zones.sort(

        key=lambda x:
            x["pivot_index"],

        reverse=True

    )

    return zones


# ============================================================
# FİYAT ZONE İÇİNDE Mİ?
# ============================================================

def price_in_zone(
    current_price,
    zone
):

    low = zone[
        "low"
    ]

    high = zone[
        "high"
    ]

    tolerance = (

        current_price
        *
        ZONE_ENTRY_TOLERANCE

    )

    # ========================================================
    # DOĞRUDAN İÇİNDE
    # ========================================================

    if (

        low
        <=
        current_price
        <=
        high

    ):

        return True, 0.0

    # ========================================================
    # DEMAND
    #
    # Fiyat zone'un biraz üstündeyse de yaklaşmış kabul et.
    # ========================================================

    if zone[
        "type"
    ] == "DEMAND":

        if (

            current_price
            >
            high

            and

            current_price
            -
            high
            <=
            tolerance

        ):

            distance = (

                (
                    current_price
                    -
                    high
                )
                /
                current_price

            ) * 100

            return True, distance

    # ========================================================
    # SUPPLY
    # ========================================================

    if zone[
        "type"
    ] == "SUPPLY":

        if (

            current_price
            <
            low

            and

            low
            -
            current_price
            <=
            tolerance

        ):

            distance = (

                (
                    low
                    -
                    current_price
                )
                /
                current_price

            ) * 100

            return True, distance

    return False, 0.0


# ============================================================
# ZONE ÇAKIŞMA KONTROLÜ
# ============================================================

def zone_is_valid(
    zone,
    current_price
):

    low = zone[
        "low"
    ]

    high = zone[
        "high"
    ]

    # ========================================================
    # Fiyat zone'u tamamen geçmişse artık alarm verme.
    # ========================================================

    if zone[
        "type"
    ] == "DEMAND":

        if current_price < low:

            return False

    if zone[
        "type"
    ] == "SUPPLY":

        if current_price > high:

            return False

    return True


# ============================================================
# EN YAKIN ZONE
# ============================================================

def get_active_zone(
    zones,
    current_price
):

    candidates = []

    for zone in zones:

        if not zone_is_valid(

            zone,

            current_price

        ):

            continue

        inside, distance = price_in_zone(

            current_price,

            zone

        )

        if not inside:

            continue

        candidates.append({

            "zone":
                zone,

            "distance":
                distance

        })

    if not candidates:

        return None

    # En yakın bölge

    candidates.sort(

        key=lambda x:
            x["distance"]

    )

    return candidates[0]


# ============================================================
# STATE
# ============================================================

def load_state():

    try:

        with open(

            STATE_FILE,

            "r",

            encoding="utf-8"

        ) as f:

            data = json.load(f)

        if isinstance(
            data,
            dict
        ):

            return data

    except Exception:

        pass

    return {}


# ============================================================
# STATE SAVE
# ============================================================

def save_state(
    state
):

    try:

        with open(

            STATE_FILE,

            "w",

            encoding="utf-8"

        ) as f:

            json.dump(

                state,

                f,

                ensure_ascii=False,

                indent=2

            )

    except Exception as e:

        print(
            "STATE:",
            e
        )


# ============================================================
# ALERT CONTROL
# ============================================================

def should_alert(
    symbol,
    zone,
    state
):

    zid = zone_id(

        symbol,

        zone

    )

    now = int(
        time.time()
    )

    old = state.get(
        zid
    )

    # ========================================================
    # İLK ALARM
    # ========================================================

    if not old:

        state[
            zid
        ] = {

            "time":
                now,

            "symbol":
                symbol,

            "type":
                zone["type"]

        }

        return True

    old_time = int(

        old.get(
            "time",
            0
        )

    )

    # ========================================================
    # 6 SAAT SONRA AYNI ZONE TEKRAR ALARM VEREBİLİR
    # ========================================================

    if (

        now
        -
        old_time
        >=
        STATE_TTL

    ):

        state[
            zid
        ] = {

            "time":
                now,

            "symbol":
                symbol,

            "type":
                zone["type"]

        }

        return True

    return False


# ============================================================
# TELEGRAM
# ============================================================

def telegram(
    text
):

    if not TOKEN or not CHAT_ID:

        print(
            "⚠️ Telegram TOKEN / CHAT_ID eksik."
        )

        return False

    try:

        response = session.post(

            f"https://api.telegram.org/"
            f"bot{TOKEN}/sendMessage",

            json={

                "chat_id":
                    CHAT_ID,

                "text":
                    text,

                "disable_web_page_preview":
                    True

            },

            timeout=15

        )

        if response.ok:

            return True

        print(

            "Telegram HTTP:",
            response.status_code

        )

        return False

    except Exception as e:

        print(
            "Telegram:",
            e
        )

        return False


# ============================================================
# ALARM METNİ
# ============================================================

def alert_text(
    symbol,
    zone,
    current_price,
    distance
):

    zone_type = zone[
        "type"
    ]

    if zone_type == "DEMAND":

        title = "🟦 DEMAND ALARMI"

        status = "DEMAND BÖLGESİ"

    else:

        title = "🟥 SUPPLY ALARMI"

        status = "SUPPLY BÖLGESİ"

    return (

        f"{title}\n\n"

        f"🪙 {symbol}\n\n"

        f"📌 4H {zone_type}\n"

        f"📍 Bölge: "
        f"{price(zone['low'])}"
        f" - "
        f"{price(zone['high'])}\n\n"

        f"💰 Fiyat: "
        f"{price(current_price)}\n"

        f"📏 Bölge uzaklığı: "
        f"{distance:.2f}%\n\n"

        f"🏗 Yapı: ✅\n"

        f"⏱ ZAMAN: 4H\n"

        f"📌 Durum: "
        f"{status}\n\n"

        "⚠️ Sadece Supply/Demand "
        "bölge alarmıdır.\n"

        "Otomatik işlem açmaz."

    )


# ============================================================
# SYMBOL ANALİZ
# ============================================================

def analyze_symbol(
    symbol,
    ticker
):

    current_price = fnum(

        ticker.get(
            "lastPrice"
        )

    )

    if current_price <= 0:

        return None

    candles = get_4h_kline(
        symbol
    )

    if not candles:

        return None

    zones = find_zones(

        symbol,

        candles

    )

    if not zones:

        return None

    active = get_active_zone(

        zones,

        current_price

    )

    if not active:

        return None

    return {

        "symbol":
            symbol,

        "price":
            current_price,

        "zone":
            active["zone"],

        "distance":
            active["distance"]

    }


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    print()

    print(
        "=" * 65
    )

    print(
        "🚨 MEXC SUPPLY / DEMAND RADAR V18.0"
    )

    print(
        "🪙 SADECE KRİPTO FUTURES"
    )

    print(
        "⏱ 4H"
    )

    print(
        "📐 SWING 10 | HISTORY 20 | ATR 14 | WIDTH 2.5"
    )

    print(
        "🎯 SADECE FİYAT ZONE'A GELİNCE ALARM"
    )

    print(
        "=" * 65
    )

    # ========================================================
    # CONTRACTS
    # ========================================================

    contracts = get_contracts()

    if not contracts:

        print(
            "❌ Futures alınamadı."
        )

        return

    # ========================================================
    # TICKERS
    # ========================================================

    tickers = get_tickers()

    if not tickers:

        print(
            "❌ Ticker alınamadı."
        )

        return

    # ========================================================
    # LİKİDİTE SIRALAMA
    #
    # Çok küçük / ölü coinleri ilk aşamada azaltıyoruz.
    # Ancak Supply/Demand sisteminin mantığını bozacak
    # teknik filtre kullanmıyoruz.
    # ========================================================

    symbols = []

    for symbol, info in contracts.items():

        ticker = tickers.get(
            symbol
        )

        if not ticker:

            continue

        amount24 = fnum(

            ticker.get(
                "amount24"
            )

        )

        last = fnum(

            ticker.get(
                "lastPrice"
            )

        )

        if last <= 0:

            continue

        # Likidite çok düşük coinleri ele

        if amount24 < 50_000:

            continue

        symbols.append({

            "symbol":
                symbol,

            "ticker":
                ticker,

            "amount24":
                amount24

        })

    # ========================================================
    # HACME GÖRE SIRALA
    # ========================================================

    symbols.sort(

        key=lambda x:
            x["amount24"],

        reverse=True

    )

    symbols = symbols[
        :MAX_SYMBOLS
    ]

    print()

    print(
        f"📊 Futures: "
        f"{len(contracts)}"
    )

    print(
        f"🪙 Kripto Futures: "
        f"{stats['crypto']}"
    )

    print(
        f"🔎 4H taranacak: "
        f"{len(symbols)}"
    )

    # ========================================================
    # STATE
    # ========================================================

    state = load_state()

    alerts = []

    # ========================================================
    # TARAMA
    # ========================================================

    for i, item in enumerate(

        symbols,

        1

    ):

        symbol = item[
            "symbol"
        ]

        ticker = item[
            "ticker"
        ]

        try:

            result = analyze_symbol(

                symbol,

                ticker

            )

        except Exception as e:

            print(

                f"❌ {symbol}:",
                e

            )

            continue

        if not result:

            continue

        zone = result[
            "zone"
        ]

        # ====================================================
        # ALARM
        # ====================================================

        if should_alert(

            symbol,

            zone,

            state

        ):

            alerts.append(
                result
            )

            print()

            print(
                "🚨 ALARM:"
            )

            print(
                symbol,
                zone["type"],
                price(
                    zone["low"]
                ),
                "-",
                price(
                    zone["high"]
                )
            )

            text = alert_text(

                symbol,

                zone,

                result["price"],

                result["distance"]

            )

            if telegram(
                text
            ):

                stats[
                    "alerts"
                ] += 1

        # ====================================================
        # İLERLEME
        # ====================================================

        if (

            i % 25
            ==
            0

        ):

            print(

                f"🔎 {i}/"
                f"{len(symbols)}"

            )

    # ========================================================
    # STATE
    # ========================================================

    save_state(
        state
    )

    # ========================================================
    # SONUÇ
    # ========================================================

    duration = (

        time.time()
        -
        started

    )

    print()

    print(
        "=" * 65
    )

    print(
        "✅ TARAMA TAMAMLANDI"
    )

    print(
        f"⏱ Süre: "
        f"{duration:.1f} sn"
    )

    print(
        f"🪙 Kripto: "
        f"{stats['crypto']}"
    )

    print(
        f"📦 Supply zone: "
        f"{stats['supply_zones']}"
    )

    print(
        f"📦 Demand zone: "
        f"{stats['demand_zones']}"
    )

    print(
        f"🚨 Yeni alarm: "
        f"{stats['alerts']}"
    )

    print(
        f"⚠️ 510: "
        f"{stats['rate_510']}"
    )

    print(
        f"❌ API hata: "
        f"{stats['errors']}"
    )

    print(
        "=" * 65
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
