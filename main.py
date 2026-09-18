import os
import json
import time
import threading
import requests


# ============================================================
# 🚀 MEXC SUPPLY / DEMAND RADAR V17.0
#
# SADECE:
# ✅ MEXC USDT CRYPTO FUTURES
# ✅ 4H SUPPLY / DEMAND
# ✅ SWING LENGTH = 7
# ✅ ATR LENGTH = 14
# ✅ HISTORY = 30
# ✅ PRICE ZONE ENTRY ALARM
#
# TELEGRAM:
# 🟦 DEMAND ALARMI
# 🟥 SUPPLY ALARMI
#
# YOK:
# ❌ PRE-PUMP SCORE
# ❌ PARA AKIŞI
# ❌ RSI
# ❌ TP / SL
# ❌ MOMENTUM
# ❌ OTOMATİK İŞLEM
# ============================================================


# ============================================================
# MEXC FUTURES API
# ============================================================

BASE = "https://contract.mexc.com"


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
# SUPPLY / DEMAND AYARLARI
# ============================================================

SWING_LENGTH = 7

ATR_LENGTH = 14

HISTORY_TO_KEEP = 30

BOX_WIDTH = 2.0


# ============================================================
# TARAMA
# ============================================================

MAX_SYMBOLS = 120

KLINE_COUNT = 120

MIN_24H_AMOUNT = 100_000


# ============================================================
# ALARM
# ============================================================

STATE_FILE = "supply_demand_state_v170.json"

STATE_TTL = 12 * 60 * 60


# ============================================================
# RATE LIMIT
# ============================================================

REQUEST_INTERVAL = 0.15

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
        "Mozilla/5.0 MEXC-SUPPLY-DEMAND-RADAR/17.0",

    "Accept":
        "application/json"

})


# ============================================================
# STATS
# ============================================================

stats = {

    "futures": 0,

    "crypto": 0,

    "non_crypto": 0,

    "kline_ok": 0,

    "zones_found": 0,

    "demand_zones": 0,

    "supply_zones": 0,

    "demand_alerts": 0,

    "supply_alerts": 0,

    "rate_510": 0,

    "api_error": 0

}


# ============================================================
# SAYI
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
# FİYAT
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

    return f"{value:.10f}"


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

                    f"⚠️ 510 RATE LIMIT | "
                    f"{wait_time:.1f}s"

                )

                time.sleep(
                    wait_time
                )

                continue

            if not response.ok:

                stats[
                    "api_error"
                ] += 1

                print(

                    "API HTTP:",
                    response.status_code

                )

                return None

            try:

                data = response.json()

            except Exception:

                stats[
                    "api_error"
                ] += 1

                return None

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
                "api_error"
            ] += 1

            print(
                "API HATASI:",
                e
            )

            time.sleep(
                0.5
            )

    return None


# ============================================================
# CRYPTO KONTROL
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

    # --------------------------------------------------------
    # USDT
    # --------------------------------------------------------

    if settle_coin:

        if settle_coin != "USDT":

            return False

    if quote_coin:

        if quote_coin != "USDT":

            return False

    # --------------------------------------------------------
    # NON CRYPTO
    # --------------------------------------------------------

    if base_coin in NON_CRYPTO:

        return False

    clean_symbol = symbol.replace(
        "_USDT",
        ""
    )

    if clean_symbol in NON_CRYPTO:

        return False

    # --------------------------------------------------------
    # KEYWORD
    # --------------------------------------------------------

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
        ] = item

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

        return []

    rows = data.get(
        "data",
        []
    )

    if not isinstance(
        rows,
        list
    ):

        return []

    return rows


# ============================================================
# 4H KLINE
# ============================================================

def get_kline(
    symbol
):

    interval = "Hour4"

    candle_seconds = 4 * 60 * 60

    now = int(
        time.time()
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
                interval,

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

    if any(

        key not in raw

        for key in required

    ):

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

            c <= 0
            or
            h <= 0
            or
            l <= 0

        ):

            continue

        candles.append({

            "open": o,

            "close": c,

            "high": h,

            "low": l,

            "vol": v

        })

    return candles


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    candles,
    period=14
):

    if len(candles) < period + 1:

        return 0.0

    trs = []

    for i in range(
        1,
        len(candles)
    ):

        current = candles[i]

        previous = candles[i - 1]

        high = current[
            "high"
        ]

        low = current[
            "low"
        ]

        previous_close = previous[
            "close"
        ]

        tr = max(

            high - low,

            abs(
                high
                -
                previous_close
            ),

            abs(
                low
                -
                previous_close
            )

        )

        trs.append(
            tr
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
                (
                    period - 1
                )
            )
            +
            tr

        ) / period

    return atr


# ============================================================
# SWING HIGH
# ============================================================

def is_swing_high(
    candles,
    index,
    length
):

    if (

        index - length < 0

        or

        index + length >= len(candles)

    ):

        return False

    value = candles[index][
        "high"
    ]

    for i in range(

        index - length,

        index + length + 1

    ):

        if i == index:

            continue

        if candles[i][
            "high"
        ] >= value:

            return False

    return True


# ============================================================
# SWING LOW
# ============================================================

def is_swing_low(
    candles,
    index,
    length
):

    if (

        index - length < 0

        or

        index + length >= len(candles)

    ):

        return False

    value = candles[index][
        "low"
    ]

    for i in range(

        index - length,

        index + length + 1

    ):

        if i == index:

            continue

        if candles[i][
            "low"
        ] <= value:

            return False

    return True


# ============================================================
# SUPPLY / DEMAND OLUŞTUR
#
# TradingView mantığına yaklaşmak için:
#
# SWING HIGH → SUPPLY
# SWING LOW  → DEMAND
#
# Bölge genişliği ATR ile hesaplanır.
# ============================================================

def build_zones(
    candles
):

    if len(candles) < 50:

        return [], []

    atr = calculate_atr(

        candles,

        ATR_LENGTH

    )

    if atr <= 0:

        return [], []

    supplies = []

    demands = []

    # Son mumlar kullanılabilir hale gelsin diye
    # son SWING_LENGTH mumunu atlıyoruz.

    last_index = (

        len(candles)
        -
        SWING_LENGTH
        -
        1

    )

    first_index = SWING_LENGTH

    for i in range(

        first_index,

        last_index + 1

    ):

        candle = candles[i]

        # ====================================================
        # SWING HIGH → SUPPLY
        # ====================================================

        if is_swing_high(

            candles,

            i,

            SWING_LENGTH

        ):

            high = candle[
                "high"
            ]

            open_price = candle[
                "open"
            ]

            close = candle[
                "close"
            ]

            body_high = max(

                open_price,

                close

            )

            body_low = min(

                open_price,

                close

            )

            # Bölgenin alt sınırı.
            # ATR genişliği + mum gövdesi dikkate alınır.

            zone_height = (

                atr
                *
                BOX_WIDTH

            )

            top = high

            bottom = max(

                body_low,

                top - zone_height

            )

            if bottom >= top:

                bottom = (

                    top
                    -
                    atr
                    *
                    0.5

                )

            supplies.append({

                "type":
                    "SUPPLY",

                "top":
                    top,

                "bottom":
                    bottom,

                "index":
                    i,

                "time":
                    i

            })

        # ====================================================
        # SWING LOW → DEMAND
        # ====================================================

        if is_swing_low(

            candles,

            i,

            SWING_LENGTH

        ):

            low = candle[
                "low"
            ]

            open_price = candle[
                "open"
            ]

            close = candle[
                "close"
            ]

            body_high = max(

                open_price,

                close

            )

            body_low = min(

                open_price,

                close

            )

            zone_height = (

                atr
                *
                BOX_WIDTH

            )

            bottom = low

            top = min(

                body_high,

                bottom + zone_height

            )

            if top <= bottom:

                top = (

                    bottom
                    +
                    atr
                    *
                    0.5

                )

            demands.append({

                "type":
                    "DEMAND",

                "top":
                    top,

                "bottom":
                    bottom,

                "index":
                    i,

                "time":
                    i

            })

    # ========================================================
    # EN YENİ BÖLGELER
    # ========================================================

    supplies.sort(

        key=lambda x:
            x["index"],

        reverse=True

    )

    demands.sort(

        key=lambda x:
            x["index"],

        reverse=True

    )

    supplies = supplies[
        :HISTORY_TO_KEEP
    ]

    demands = demands[
        :HISTORY_TO_KEEP
    ]

    stats[
        "supply_zones"
    ] += len(supplies)

    stats[
        "demand_zones"
    ] += len(demands)

    stats[
        "zones_found"
    ] += (

        len(supplies)
        +
        len(demands)

    )

    return supplies, demands


# ============================================================
# FİYAT BÖLGEDE Mİ?
# ============================================================

def price_in_zone(
    current_price,
    zone
):

    return (

        zone["bottom"]
        <=
        current_price
        <=
        zone["top"]

    )


# ============================================================
# BÖLGEYE YAKINLIK
#
# Fiyat henüz bölgeye girmediyse de çok yaklaştığında
# alarm verebilmesi için kullanıyoruz.
# ============================================================

def distance_to_zone(
    current_price,
    zone
):

    if price_in_zone(
        current_price,
        zone
    ):

        return 0.0

    if current_price > zone["top"]:

        return (

            (
                current_price
                -
                zone["top"]
            )
            /
            current_price

        ) * 100

    return (

        (
            zone["bottom"]
            -
            current_price
        )
        /
        current_price

    ) * 100


# ============================================================
# AKTİF ZONE BUL
#
# Fiyata en yakın geçerli bölge.
# ============================================================

def find_active_zones(
    current_price,
    supplies,
    demands
):

    active_supply = None

    active_demand = None

    # ========================================================
    # SUPPLY
    # ========================================================

    for zone in supplies:

        if price_in_zone(

            current_price,

            zone

        ):

            active_supply = zone

            break

    # ========================================================
    # DEMAND
    # ========================================================

    for zone in demands:

        if price_in_zone(

            current_price,

            zone

        ):

            active_demand = zone

            break

    return (

        active_supply,

        active_demand

    )


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

            "STATE HATASI:",

            e

        )


# ============================================================
# ZONE KEY
# ============================================================

def zone_key(
    symbol,
    zone
):

    return (

        f"{symbol}|"
        f"{zone['type']}|"
        f"{zone['index']}|"
        f"{zone['bottom']:.12f}|"
        f"{zone['top']:.12f}"

    )


# ============================================================
# ALARM KONTROL
#
# Aynı zone için tekrar tekrar mesaj göndermez.
# ============================================================

def should_alert_zone(
    symbol,
    zone,
    state
):

    key = zone_key(
        symbol,
        zone
    )

    now = int(
        time.time()
    )

    old = state.get(
        key
    )

    if old:

        old_time = int(

            old.get(
                "time",
                0
            )

        )

        # ====================================================
        # 12 SAAT İÇİNDE TEKRAR YOK
        # ====================================================

        if (

            now
            -
            old_time
            <
            STATE_TTL

        ):

            return False

    state[
        key
    ] = {

        "time":
            now,

        "type":
            zone["type"],

        "symbol":
            symbol

    }

    return True


# ============================================================
# TELEGRAM
# ============================================================

def telegram(
    text
):

    if not TOKEN or not CHAT_ID:

        print()

        print(
            "⚠️ Telegram TOKEN / CHAT_ID eksik."
        )

        print()

        print(
            text
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

        if not response.ok:

            print(

                "Telegram HTTP:",
                response.status_code

            )

            return False

        return True

    except Exception as e:

        print(

            "TELEGRAM HATASI:",
            e

        )

        return False


# ============================================================
# DEMAND MESAJI
# ============================================================

def demand_text(
    symbol,
    current_price,
    zone
):

    distance = distance_to_zone(

        current_price,

        zone

    )

    return (

        "🟦 DEMAND ALARMI\n"
        "\n"

        f"🪙 {symbol}\n"
        "\n"

        "📍 4H DEMAND\n"

        f"{price(zone['bottom'])}"
        " - "
        f"{price(zone['top'])}\n"
        "\n"

        f"💰 Fiyat: "
        f"{price(current_price)}\n"

        f"📏 Bölge uzaklığı: "
        f"{distance:.2f}%\n"
        "\n"

        "⏱ ZAMAN: 4H\n"

        "📌 Durum: "
        "DEMAND BÖLGESİ\n"
        "\n"

        "⚠️ Bu yalnızca Supply/Demand "
        "bölge alarmıdır.\n"
        "Otomatik işlem açmaz."

    )


# ============================================================
# SUPPLY MESAJI
# ============================================================

def supply_text(
    symbol,
    current_price,
    zone
):

    distance = distance_to_zone(

        current_price,

        zone

    )

    return (

        "🟥 SUPPLY ALARMI\n"
        "\n"

        f"🪙 {symbol}\n"
        "\n"

        "📍 4H SUPPLY\n"

        f"{price(zone['bottom'])}"
        " - "
        f"{price(zone['top'])}\n"
        "\n"

        f"💰 Fiyat: "
        f"{price(current_price)}\n"

        f"📏 Bölge uzaklığı: "
        f"{distance:.2f}%\n"
        "\n"

        "⏱ ZAMAN: 4H\n"

        "📌 Durum: "
        "SUPPLY BÖLGESİ\n"
        "\n"

        "⚠️ Bu yalnızca Supply/Demand "
        "bölge alarmıdır.\n"
        "Otomatik işlem açmaz."

    )


# ============================================================
# COIN TARAMA
# ============================================================

def scan_symbol(
    item
):

    symbol = item[
        "symbol"
    ]

    ticker = item[
        "ticker"
    ]

    current_price = fnum(

        ticker.get(
            "lastPrice"
        )

    )

    if current_price <= 0:

        return []

    candles = get_kline(
        symbol
    )

    if not candles:

        return []

    stats[
        "kline_ok"
    ] += 1

    supplies, demands = build_zones(
        candles
    )

    alerts = []

    active_supply, active_demand = find_active_zones(

        current_price,

        supplies,

        demands

    )

    # ========================================================
    # DEMAND
    # ========================================================

    if active_demand:

        alerts.append({

            "symbol":
                symbol,

            "price":
                current_price,

            "zone":
                active_demand

        })

    # ========================================================
    # SUPPLY
    # ========================================================

    if active_supply:

        alerts.append({

            "symbol":
                symbol,

            "price":
                current_price,

            "zone":
                active_supply

        })

    return alerts


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
        "🚀 MEXC SUPPLY / DEMAND RADAR V17.0"
    )

    print(
        "🪙 SADECE KRİPTO FUTURES"
    )

    print(
        "📊 TIMEFRAME: 4H"
    )

    print(
        f"📐 SWING LENGTH: {SWING_LENGTH}"
    )

    print(
        f"📏 ATR LENGTH: {ATR_LENGTH}"
    )

    print(
        f"📦 HISTORY: {HISTORY_TO_KEEP}"
    )

    print(
        "=" * 65
    )

    # ========================================================
    # CONTRACTS
    # ========================================================

    contracts = get_contracts()

    if not contracts:

        raise RuntimeError(
            "MEXC Futures alınamadı."
        )

    stats[
        "futures"
    ] = len(contracts)

    # ========================================================
    # TICKERS
    # ========================================================

    tickers = get_tickers()

    ticker_map = {

        str(

            x.get(
                "symbol",
                ""
            )

        ).upper():

        x

        for x in tickers

        if x.get(
            "symbol"
        )

    }

    # ========================================================
    # LIKIDITEYE GÖRE İLK 120
    #
    # Supply/Demand için çok düşük likiditeli coinleri
    # tamamen taramak yerine likit coinlerden başlıyoruz.
    # ========================================================

    candidates = []

    for symbol, info in contracts.items():

        ticker = ticker_map.get(
            symbol
        )

        if not ticker:

            continue

        amount24 = fnum(

            ticker.get(
                "amount24"
            )

        )

        last_price = fnum(

            ticker.get(
                "lastPrice"
            )

        )

        if (

            amount24
            <
            MIN_24H_AMOUNT

            or

            last_price
            <=
            0

        ):

            continue

        candidates.append({

            "symbol":
                symbol,

            "ticker":
                ticker,

            "amount24":
                amount24

        })

    candidates.sort(

        key=lambda x:
            x["amount24"],

        reverse=True

    )

    candidates = candidates[
        :MAX_SYMBOLS
    ]

    print()

    print(

        f"📊 Futures: "
        f"{len(contracts)}"

    )

    print(

        f"🪙 Kripto: "
        f"{stats['crypto']}"

    )

    print(

        f"🔎 Taranacak: "
        f"{len(candidates)}"

    )

    # ========================================================
    # STATE
    # ========================================================

    state = load_state()

    all_alerts = []

    # ========================================================
    # TARAMA
    # ========================================================

    for index, item in enumerate(

        candidates,

        1

    ):

        try:

            symbol = item[
                "symbol"
            ]

            print(

                f"[{index}/{len(candidates)}] "
                f"{symbol}",

                end="\r"

            )

            alerts = scan_symbol(
                item
            )

            for alert in alerts:

                zone = alert[
                    "zone"
                ]

                if should_alert_zone(

                    symbol,

                    zone,

                    state

                ):

                    all_alerts.append(
                        alert
                    )

        except Exception as e:

            print()

            print(

                f"❌ {item.get('symbol')} "
                f"HATA: {e}"

            )

    # ========================================================
    # STATE
    # ========================================================

    save_state(
        state
    )

    # ========================================================
    # TELEGRAM
    # ========================================================

    print()

    print(
        "========== ALARMLAR =========="
    )

    if not all_alerts:

        print(
            "ℹ️ Yeni Demand/Supply alarmı yok."
        )

    else:

        for alert in all_alerts:

            symbol = alert[
                "symbol"
            ]

            current_price = alert[
                "price"
            ]

            zone = alert[
                "zone"
            ]

            if zone["type"] == "DEMAND":

                message = demand_text(

                    symbol,

                    current_price,

                    zone

                )

                stats[
                    "demand_alerts"
                ] += 1

            else:

                message = supply_text(

                    symbol,

                    current_price,

                    zone

                )

                stats[
                    "supply_alerts"
                ] += 1

            print()

            print(
                message
            )

            telegram(
                message
            )

            time.sleep(
                0.3
            )

    # ========================================================
    # SUMMARY
    # ========================================================

    duration = (

        time.time()
        -
        started

    )

    summary = (

        "🛰 SUPPLY / DEMAND RADAR V17.0\n"
        "\n"

        f"🪙 Kripto Futures: "
        f"{stats['crypto']}\n"

        f"🔎 Taranan: "
        f"{len(candidates)}\n"
        "\n"

        f"📦 Demand bölgeleri: "
        f"{stats['demand_zones']}\n"

        f"📦 Supply bölgeleri: "
        f"{stats['supply_zones']}\n"
        "\n"

        f"🟦 Yeni Demand alarmı: "
        f"{stats['demand_alerts']}\n"

        f"🟥 Yeni Supply alarmı: "
        f"{stats['supply_alerts']}\n"
        "\n"

        f"⚠️ 510: "
        f"{stats['rate_510']}\n"

        f"❌ API hata: "
        f"{stats['api_error']}\n"
        "\n"

        f"⏱ Süre: "
        f"{duration:.1f} sn"

    )

    print()

    print(
        summary
    )

    telegram(
        summary
    )

    print()

    print(
        "✅ SUPPLY / DEMAND RADAR "
        "V17.0 TAMAMLANDI"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
