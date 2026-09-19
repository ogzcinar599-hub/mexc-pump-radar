import os
import json
import time
import threading
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC MONEY FLOW RADAR V4.1
#
# FUTURES
# PARA GİRİŞİ
# HACİM
# RSI
# DEMAND
# BTC YÖNÜ
# TELEGRAM
#
# ÖNEMLİ:
# MEXC ticker endpoint'i sembol verilmeden güvenilir şekilde
# tüm coinleri döndürmediği için coin ticker'ları kontrollü
# şekilde tek tek çekiyoruz.
#
# Ticker CACHE sayesinde her taramada 998 istek yapılmaz.
# ============================================================


# ============================================================
# MEXC
# ============================================================

BASE_URL = "https://api.mexc.com"


# ============================================================
# TELEGRAM
# ============================================================

BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "BURAYA_BOT_TOKEN"
)

CHAT_ID = os.getenv(
    "CHAT_ID",
    "BURAYA_CHAT_ID"
)


# ============================================================
# GENEL AYARLAR
# ============================================================

SCAN_INTERVAL = 180

MAX_ALERTS = 8

COOLDOWN_HOURS = 4

MAX_WORKERS = 5


# ============================================================
# TICKER AYARLARI
# ============================================================

# İlk aşamada tüm futures ticker'larını alıyoruz.
# Sonrasında sadece en yüksek hacimli coinleri analiz ediyoruz.

TICKER_CACHE_FILE = "ticker_cache.json"

TICKER_CACHE_TTL = 300


# ============================================================
# DETAYLI ANALİZ
# ============================================================

TOP_CANDIDATES = 80

DEALS_LIMIT = 100


# ============================================================
# FİLTRELER
# ============================================================

# 24H USDT hacmi
MIN_24H_VOLUME = 100000


# 15M hacim
# Önceki 1.20 yerine biraz gevşettik.
MIN_VOLUME_RATIO = 1.05


# Long para oranı
MIN_LONG_RATIO = 52.0


# Net para farkı
MIN_NET_RATIO = 3.0


# Minimum açık işlem notional
MIN_OPEN_NOTIONAL = 20000


# RSI
MIN_RSI_15 = 42
MAX_RSI_15 = 75

MIN_RSI_1H = 42
MAX_RSI_1H = 72

MIN_RSI_4H = 40
MAX_RSI_4H = 70


# Aşırı pump olmuş coinleri alma
MAX_15M_PUMP = 8.0
MAX_1H_PUMP = 15.0


# Minimum toplam skor
MIN_SCORE = 35


# ============================================================
# RATE LIMIT
# ============================================================

REQUEST_INTERVAL = 0.12

request_lock = threading.Lock()

last_request_time = 0.0


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({

    "User-Agent":
        "Mozilla/5.0",

    "Accept":
        "application/json"

})


# ============================================================
# STATE
# ============================================================

STATE_FILE = "money_flow_state.json"


def load_state():

    try:

        if not os.path.exists(
            STATE_FILE
        ):

            return {}

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return {}


def save_state():

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                STATE,
                f,
                indent=2
            )

    except Exception:

        pass


STATE = load_state()


# ============================================================
# REQUEST
# ============================================================

def api_get(
    path,
    params=None,
    timeout=12
):

    global last_request_time

    with request_lock:

        now = time.monotonic()

        wait = (

            REQUEST_INTERVAL
            -
            (
                now -
                last_request_time
            )

        )

        if wait > 0:

            time.sleep(
                wait
            )

        last_request_time = (
            time.monotonic()
        )

    url = (
        BASE_URL +
        path
    )

    try:

        response = session.get(

            url,

            params=params,

            timeout=timeout

        )

        if response.status_code == 429:

            print(
                "⚠️ RATE LIMIT - bekleniyor..."
            )

            time.sleep(2)

            return None

        if response.status_code != 200:

            return None

        return response.json()

    except Exception:

        return None


# ============================================================
# STOCK / FIYAT ENDEKSİ / TOKENIZED STOCK FILTRESI
# ============================================================

STOCK_WORDS = [

    "STOCK",

    "AAPL",
    "TSLA",
    "NVDA",
    "MSFT",
    "AMZN",
    "META",
    "GOOG",
    "GOOGL",
    "NFLX",
    "COIN",
    "MSTR",
    "AMD",
    "INTC",
    "BA",
    "DIS",
    "NIO",
    "BABA",
    "PDD",
    "PLTR",

    "SPY",
    "QQQ",
    "IWM",
    "DIA",

    "GOLD",
    "SILVER",

    "OIL",

    "XAUT"

]


def is_stock_like(
    symbol
):

    s = symbol.upper()

    for word in STOCK_WORDS:

        if word in s:

            return True

    return False


# ============================================================
# CONTRACT CACHE
# ============================================================

CONTRACT_CACHE = {}

CONTRACT_CACHE_TIME = 0

CONTRACT_CACHE_TTL = 3600


# ============================================================
# FUTURES LISTESI
# ============================================================

def get_contracts():

    global CONTRACT_CACHE
    global CONTRACT_CACHE_TIME

    now = time.time()

    if (

        CONTRACT_CACHE
        and

        (
            now -
            CONTRACT_CACHE_TIME
        )
        <
        CONTRACT_CACHE_TTL

    ):

        return CONTRACT_CACHE

    print(
        "📡 Futures listesi alınıyor..."
    )

    data = api_get(

        "/api/v1/contract/detail"

    )

    if not data:

        if CONTRACT_CACHE:

            print(
                "⚠️ Cache kullanılıyor."
            )

            return CONTRACT_CACHE

        return {}

    rows = data.get(
        "data",
        []
    )

    result = {}

    for item in rows:

        try:

            symbol = item.get(
                "symbol",
                ""
            )

            quote_coin = item.get(
                "quoteCoin",
                ""
            )

            state = int(
                item.get(
                    "state",
                    0
                )
            )

            contract_size = float(
                item.get(
                    "contractSize",
                    0
                )
            )

            api_allowed = item.get(
                "apiAllowed",
                True
            )

            if not symbol:

                continue

            if quote_coin != "USDT":

                continue

            if state != 0:

                continue

            if not api_allowed:

                continue

            if contract_size <= 0:

                continue

            if is_stock_like(
                symbol
            ):

                continue

            result[symbol] = {

                "contract_size":
                    contract_size,

                "base_coin":
                    item.get(
                        "baseCoin",
                        ""
                    )

            }

        except Exception:

            continue

    if result:

        CONTRACT_CACHE = result

        CONTRACT_CACHE_TIME = now

    return result


# ============================================================
# TICKER CACHE
# ============================================================

TICKER_CACHE = {}

TICKER_CACHE_TIME = 0


def load_ticker_cache():

    global TICKER_CACHE
    global TICKER_CACHE_TIME

    try:

        if not os.path.exists(
            TICKER_CACHE_FILE
        ):

            return

        with open(
            TICKER_CACHE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            obj = json.load(f)

        TICKER_CACHE = obj.get(
            "tickers",
            {}
        )

        TICKER_CACHE_TIME = float(
            obj.get(
                "time",
                0
            )
        )

    except Exception:

        TICKER_CACHE = {}


def save_ticker_cache():

    try:

        with open(
            TICKER_CACHE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump({

                "time":
                    TICKER_CACHE_TIME,

                "tickers":
                    TICKER_CACHE

            }, f)

    except Exception:

        pass


load_ticker_cache()


# ============================================================
# TEK TICKER
# ============================================================

def get_ticker(
    symbol
):

    data = api_get(

        "/api/v1/contract/ticker",

        {
            "symbol":
                symbol
        }

    )

    if not data:

        return None

    item = data.get(
        "data"
    )

    if not item:

        return None

    if isinstance(
        item,
        list
    ):

        if not item:

            return None

        item = item[0]

    if not isinstance(
        item,
        dict
    ):

        return None

    return item


# ============================================================
# TÜM TICKERLARI CACHELE
# ============================================================

def refresh_tickers(
    contracts
):

    global TICKER_CACHE
    global TICKER_CACHE_TIME

    now = time.time()

    # Cache hala geçerliyse
    if (

        TICKER_CACHE
        and

        (
            now -
            TICKER_CACHE_TIME
        )
        <
        TICKER_CACHE_TTL

    ):

        print(
            "📦 Ticker cache kullanılıyor:",
            len(TICKER_CACHE)
        )

        return TICKER_CACHE


    print()
    print(
        "📊 Futures ticker'ları güncelleniyor..."
    )

    symbols = list(
        contracts.keys()
    )

    total = len(
        symbols
    )

    new_cache = {}

    completed = 0

    # Kontrollü worker
    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {

            executor.submit(
                get_ticker,
                symbol
            ):
                symbol

            for symbol in symbols

        }

        for future in as_completed(
            future_map
        ):

            symbol = future_map[
                future
            ]

            try:

                ticker = future.result()

                if ticker:

                    new_cache[
                        symbol
                    ] = ticker

            except Exception:

                pass

            completed += 1

            if completed % 100 == 0:

                print(

                    f"   Ticker: "
                    f"{completed}/{total}"

                )


    if new_cache:

        TICKER_CACHE = new_cache

        TICKER_CACHE_TIME = time.time()

        save_ticker_cache()

    print(
        "✅ Ticker alınan:",
        len(TICKER_CACHE)
    )

    return TICKER_CACHE


# ============================================================
# TOP COINLER
# ============================================================

def get_top_candidates(
    contracts
):

    tickers = refresh_tickers(
        contracts
    )

    if not tickers:

        return []

    candidates = []

    for symbol, info in (
        contracts.items()
    ):

        ticker = tickers.get(
            symbol
        )

        if not ticker:

            continue

        try:

            amount24 = float(
                ticker.get(
                    "amount24",
                    0
                )
            )

            if amount24 < MIN_24H_VOLUME:

                continue

            price = float(
                ticker.get(
                    "lastPrice",
                    0
                )
            )

            change24 = float(
                ticker.get(
                    "riseFallRate",
                    0
                )
            ) * 100

            candidates.append({

                "symbol":
                    symbol,

                "amount24":
                    amount24,

                "price":
                    price,

                "change24":
                    change24,

                "ticker":
                    ticker

            })

        except Exception:

            continue

    # 24H hacme göre sırala

    candidates.sort(

        key=lambda x:
            x["amount24"],

        reverse=True

    )

    return candidates[
        :TOP_CANDIDATES
    ]


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=80
):

    data = api_get(

        f"/api/v1/contract/kline/{symbol}",

        {
            "interval":
                interval,

            "limit":
                limit

        }

    )

    if not data:

        return []

    d = data.get(
        "data"
    )

    if not d:

        return []

    try:

        times = d.get(
            "time",
            []
        )

        opens = d.get(
            "open",
            []
        )

        highs = d.get(
            "high",
            []
        )

        lows = d.get(
            "low",
            []
        )

        closes = d.get(
            "close",
            []
        )

        volumes = d.get(
            "vol",
            []
        )

        length = min(

            len(times),
            len(opens),
            len(highs),
            len(lows),
            len(closes),
            len(volumes)

        )

        result = []

        for i in range(
            length
        ):

            result.append({

                "time":
                    float(
                        times[i]
                    ),

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

        return result

    except Exception:

        return []


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    closes,
    period=14
):

    if len(closes) <= period:

        return None

    gains = []

    losses = []

    for i in range(
        1,
        len(closes)
    ):

        diff = (

            closes[i] -
            closes[i - 1]

        )

        if diff >= 0:

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
        /
        period
    )

    avg_loss = (
        sum(
            losses[:period]
        )
        /
        period
    )

    for i in range(
        period,
        len(gains)
    ):

        avg_gain = (

            (
                avg_gain *
                (period - 1)
            )
            +
            gains[i]

        ) / period

        avg_loss = (

            (
                avg_loss *
                (period - 1)
            )
            +
            losses[i]

        ) / period

    if avg_loss == 0:

        return 100

    rs = (
        avg_gain /
        avg_loss
    )

    return (

        100 -
        (
            100 /
            (1 + rs)
        )

    )


# ============================================================
# HACİM ORANI
# ============================================================

def get_volume_ratio(
    klines
):

    if len(klines) < 25:

        return 0

    # Son kapanmış mum
    current = klines[-2]

    previous = [

        x["volume"]

        for x in
        klines[
            -22:-2
        ]

    ]

    if not previous:

        return 0

    average = (
        sum(previous)
        /
        len(previous)
    )

    if average <= 0:

        return 0

    return (

        current["volume"]
        /
        average

    )


# ============================================================
# FİYAT DEĞİŞİMİ
# ============================================================

def get_change(
    klines,
    candles
):

    if len(klines) < (
        candles + 3
    ):

        return 0

    current = klines[-2][
        "close"
    ]

    old = klines[
        -2 - candles
    ][
        "close"
    ]

    if old <= 0:

        return 0

    return (

        (
            current -
            old
        )
        /
        old

    ) * 100


# ============================================================
# BTC YÖNÜ
# ============================================================

def get_btc_direction():

    k15 = get_klines(
        "BTC_USDT",
        "Min15",
        60
    )

    k1h = get_klines(
        "BTC_USDT",
        "Min60",
        60
    )

    k4h = get_klines(
        "BTC_USDT",
        "Hour4",
        60
    )

    if (

        len(k15) < 30
        or
        len(k1h) < 30
        or
        len(k4h) < 30

    ):

        return "NEUTRAL"


    r15 = calculate_rsi([

        x["close"]
        for x in k15[:-1]

    ])

    r1h = calculate_rsi([

        x["close"]
        for x in k1h[:-1]

    ])

    r4h = calculate_rsi([

        x["close"]
        for x in k4h[:-1]

    ])


    if None in (
        r15,
        r1h,
        r4h
    ):

        return "NEUTRAL"


    score = 0

    if r15 >= 51:

        score += 1

    elif r15 <= 47:

        score -= 1


    if r1h >= 51:

        score += 1

    elif r1h <= 47:

        score -= 1


    if r4h >= 51:

        score += 1

    elif r4h <= 47:

        score -= 1


    if score >= 2:

        return "BULLISH"

    if score <= -2:

        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# PARA GİRİŞİ
# ============================================================

def get_money_flow(
    symbol,
    contract_size
):

    data = api_get(

        f"/api/v1/contract/deals/{symbol}",

        {
            "limit":
                DEALS_LIMIT
        }

    )

    if not data:

        return None

    deals = data.get(
        "data"
    )

    if not deals:

        return None

    long_open = 0.0

    short_open = 0.0

    long_count = 0

    short_count = 0


    for deal in deals:

        try:

            price = float(
                deal.get(
                    "p",
                    0
                )
            )

            volume = float(
                deal.get(
                    "v",
                    0
                )
            )

            trade_type = int(
                deal.get(
                    "T",
                    0
                )
            )

            operation = int(
                deal.get(
                    "O",
                    0
                )
            )

            # Sadece OPEN
            if operation != 1:

                continue

            if price <= 0:

                continue

            if volume <= 0:

                continue

            notional = (

                price
                *
                volume
                *
                contract_size

            )

            if trade_type == 1:

                long_open += notional

                long_count += 1

            elif trade_type == 2:

                short_open += notional

                short_count += 1

        except Exception:

            continue


    total_open = (

        long_open +
        short_open

    )

    if total_open <= 0:

        return None


    long_ratio = (

        long_open /
        total_open

    ) * 100


    short_ratio = (

        short_open /
        total_open

    ) * 100


    net_open = (

        long_open -
        short_open

    )


    net_ratio = (

        net_open /
        total_open

    ) * 100


    # ========================================================
    # MONEY SCORE
    # ========================================================

    score = 0


    if long_ratio >= 52:

        score += 10

    if long_ratio >= 55:

        score += 10

    if long_ratio >= 60:

        score += 10

    if long_ratio >= 65:

        score += 10

    if long_ratio >= 70:

        score += 10


    if net_ratio >= 3:

        score += 5

    if net_ratio >= 7:

        score += 5

    if net_ratio >= 12:

        score += 5


    return {

        "long_open":
            long_open,

        "short_open":
            short_open,

        "total_open":
            total_open,

        "long_ratio":
            long_ratio,

        "short_ratio":
            short_ratio,

        "net_open":
            net_open,

        "net_ratio":
            net_ratio,

        "long_count":
            long_count,

        "short_count":
            short_count,

        "money_score":
            score

    }


# ============================================================
# DEMAND
# ============================================================

def detect_demand(
    klines
):

    if len(klines) < 25:

        return False

    candles = klines[
        -22:-2
    ]

    lowest = min(
        x["low"]
        for x in candles
    )

    highest = max(
        x["high"]
        for x in candles
    )

    current = klines[-2][
        "close"
    ]

    price_range = (
        highest -
        lowest
    )

    if price_range <= 0:

        return False

    position = (

        current -
        lowest

    ) / price_range


    # Alt %30 bölgesi
    if position > 0.30:

        return False


    # Son mum pozitif olsun
    last = klines[-2]

    if last["close"] < last["open"]:

        return False


    return True


# ============================================================
# SKOR
# ============================================================

def calculate_score(
    flow,
    volume_ratio,
    rsi15,
    rsi1h,
    rsi4h,
    demand,
    btc
):

    score = 0


    # ========================================================
    # PARA
    # ========================================================

    score += flow[
        "money_score"
    ]


    # ========================================================
    # HACİM
    # ========================================================

    if volume_ratio >= 1.05:

        score += 5

    if volume_ratio >= 1.30:

        score += 5

    if volume_ratio >= 1.70:

        score += 5

    if volume_ratio >= 2.50:

        score += 5


    # ========================================================
    # RSI
    # ========================================================

    if 48 <= rsi15 <= 65:

        score += 5

    if 48 <= rsi1h <= 65:

        score += 5

    if 45 <= rsi4h <= 65:

        score += 5


    # ========================================================
    # DEMAND
    # ========================================================

    if demand:

        score += 10


    # ========================================================
    # BTC
    # ========================================================

    if btc == "BULLISH":

        score += 5

    elif btc == "BEARISH":

        score -= 5


    return score


# ============================================================
# COIN ANALİZ
# ============================================================

def analyze_coin(
    candidate,
    contract,
    btc
):

    symbol = candidate[
        "symbol"
    ]

    try:

        contract_size = float(
            contract[
                "contract_size"
            ]
        )


        # ====================================================
        # PARA
        # ====================================================

        flow = get_money_flow(

            symbol,
            contract_size

        )

        if not flow:

            return None


        # ====================================================
        # MIN OPEN
        # ====================================================

        if flow[
            "total_open"
        ] < MIN_OPEN_NOTIONAL:

            return None


        # ====================================================
        # LONG
        # ====================================================

        if flow[
            "long_ratio"
        ] < MIN_LONG_RATIO:

            return None


        # ====================================================
        # NET
        # ====================================================

        if flow[
            "net_ratio"
        ] < MIN_NET_RATIO:

            return None


        # ====================================================
        # 15M
        # ====================================================

        k15 = get_klines(

            symbol,
            "Min15",
            80

        )

        if len(k15) < 30:

            return None


        volume = get_volume_ratio(
            k15
        )


        if volume < MIN_VOLUME_RATIO:

            return None


        change15 = get_change(
            k15,
            1
        )

        change1h = get_change(
            k15,
            4
        )


        if change15 > MAX_15M_PUMP:

            return None


        if change1h > MAX_1H_PUMP:

            return None


        # ====================================================
        # 1H
        # ====================================================

        k1h = get_klines(

            symbol,
            "Min60",
            80

        )

        if len(k1h) < 30:

            return None


        # ====================================================
        # 4H
        # ====================================================

        k4h = get_klines(

            symbol,
            "Hour4",
            80

        )

        if len(k4h) < 30:

            return None


        # ====================================================
        # RSI
        # ====================================================

        rsi15 = calculate_rsi([

            x["close"]
            for x in k15[:-1]

        ])

        rsi1h = calculate_rsi([

            x["close"]
            for x in k1h[:-1]

        ])

        rsi4h = calculate_rsi([

            x["close"]
            for x in k4h[:-1]

        ])


        if None in (
            rsi15,
            rsi1h,
            rsi4h
        ):

            return None


        # ====================================================
        # RSI FILTER
        # ====================================================

        if not (

            MIN_RSI_15
            <=
            rsi15
            <=
            MAX_RSI_15

        ):

            return None


        if not (

            MIN_RSI_1H
            <=
            rsi1h
            <=
            MAX_RSI_1H

        ):

            return None


        if not (

            MIN_RSI_4H
            <=
            rsi4h
            <=
            MAX_RSI_4H

        ):

            return None


        # ====================================================
        # DEMAND
        # ====================================================

        demand = detect_demand(
            k4h
        )


        # ====================================================
        # SCORE
        # ====================================================

        score = calculate_score(

            flow,

            volume,

            rsi15,

            rsi1h,

            rsi4h,

            demand,

            btc

        )


        if score < MIN_SCORE:

            return None


        return {

            "symbol":
                symbol,

            "score":
                score,

            "money_score":
                flow[
                    "money_score"
                ],

            "long_open":
                flow[
                    "long_open"
                ],

            "short_open":
                flow[
                    "short_open"
                ],

            "total_open":
                flow[
                    "total_open"
                ],

            "long_ratio":
                flow[
                    "long_ratio"
                ],

            "short_ratio":
                flow[
                    "short_ratio"
                ],

            "net_open":
                flow[
                    "net_open"
                ],

            "net_ratio":
                flow[
                    "net_ratio"
                ],

            "volume_ratio":
                volume,

            "rsi15":
                rsi15,

            "rsi1h":
                rsi1h,

            "rsi4h":
                rsi4h,

            "change15":
                change15,

            "change1h":
                change1h,

            "demand":
                demand,

            "btc":
                btc,

            "amount24":
                candidate[
                    "amount24"
                ]

        }

    except Exception:

        return None


# ============================================================
# PARA FORMAT
# ============================================================

def money_format(
    value
):

    if value >= 1_000_000:

        return (
            f"{value / 1_000_000:.2f}M"
        )

    if value >= 1_000:

        return (
            f"{value / 1_000:.1f}K"
        )

    return (
        f"{value:.0f}"
    )


# ============================================================
# TELEGRAM GÖNDER
# ============================================================

def send_telegram(
    message
):

    if (

        not BOT_TOKEN
        or
        BOT_TOKEN ==
        "BURAYA_BOT_TOKEN"

    ):

        print(
            "⚠️ BOT_TOKEN ayarlanmamış."
        )

        return False


    if (

        not CHAT_ID
        or
        CHAT_ID ==
        "BURAYA_CHAT_ID"

    ):

        print(
            "⚠️ CHAT_ID ayarlanmamış."
        )

        return False


    url = (

        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"

    )


    try:

        response = session.post(

            url,

            data={

                "chat_id":
                    CHAT_ID,

                "text":
                    message,

                "parse_mode":
                    "HTML",

                "disable_web_page_preview":
                    True

            },

            timeout=15

        )


        if response.status_code == 200:

            print(
                "📨 Telegram gönderildi."
            )

            return True


        print(
            "❌ Telegram hata:",
            response.text[:300]
        )

        return False


    except Exception as e:

        print(
            "❌ Telegram bağlantı hatası:",
            e
        )

        return False


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def build_message(
    x
):

    if x["demand"]:

        zone = "🟢 DEMAND"

    else:

        zone = "⚪ DEMAND YOK"


    if x["btc"] == "BULLISH":

        btc = "🟢 BTC BULLISH"

    elif x["btc"] == "BEARISH":

        btc = "🔴 BTC BEARISH"

    else:

        btc = "⚪ BTC NEUTRAL"


    return f"""
🚨 <b>MONEY FLOW RADAR</b>

🟢 <b>{x["symbol"]}</b>

🔥 Skor:
<b>{x["score"]}</b>

💰 Para Girişi:
<b>{money_format(x["net_open"])} USDT</b>

🟢 Long:
<b>{money_format(x["long_open"])} USDT</b>

🔴 Short:
<b>{money_format(x["short_open"])} USDT</b>

📊 Long Oranı:
<b>%{x["long_ratio"]:.1f}</b>

📈 Hacim:
<b>{x["volume_ratio"]:.2f}x</b>

RSI 15M:
<b>{x["rsi15"]:.1f}</b>

RSI 1H:
<b>{x["rsi1h"]:.1f}</b>

RSI 4H:
<b>{x["rsi4h"]:.1f}</b>

🎯 {zone}

{btc}
""".strip()


# ============================================================
# COOLDOWN
# ============================================================

def can_send(
    symbol
):

    last = STATE.get(
        symbol,
        0
    )

    return (

        time.time() -
        last

    ) >= (

        COOLDOWN_HOURS *
        3600

    )


# ============================================================
# SCAN
# ============================================================

def scan():

    print()
    print(
        "=" * 60
    )

    print(
        "🚀 MEXC MONEY FLOW RADAR V4.1"
    )

    print(
        "=" * 60
    )


    # ========================================================
    # BTC
    # ========================================================

    btc = get_btc_direction()

    print(
        "BTC YÖNÜ:",
        btc
    )


    # ========================================================
    # CONTRACTS
    # ========================================================

    contracts = get_contracts()

    if not contracts:

        print(
            "❌ Futures listesi alınamadı."
        )

        return


    print(
        "Toplam Futures:",
        len(contracts)
    )


    # ========================================================
    # CANDIDATES
    # ========================================================

    candidates = get_top_candidates(
        contracts
    )


    print(
        "Detaylı taranacak:",
        len(candidates)
    )


    if not candidates:

        print(
            "❌ Aday bulunamadı."
        )

        return


    print(
        "İlk 10 aday:"
    )


    for c in candidates[:10]:

        print(

            " ",
            c["symbol"],
            "| 24H:",
            money_format(
                c["amount24"]
            )

        )


    # ========================================================
    # ANALİZ
    # ========================================================

    results = []


    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {}


        for candidate in candidates:

            symbol = candidate[
                "symbol"
            ]

            future = executor.submit(

                analyze_coin,

                candidate,

                contracts[symbol],

                btc

            )

            future_map[
                future
            ] = symbol


        for future in as_completed(
            future_map
        ):

            try:

                result = future.result()

                if result:

                    results.append(
                        result
                    )

            except Exception:

                pass


    # ========================================================
    # SIRALA
    # ========================================================

    results.sort(

        key=lambda x: (

            x["score"],

            x["net_open"],

            x["volume_ratio"]

        ),

        reverse=True

    )


    print()
    print(
        "🔥 GÜÇLÜ SONUÇ:",
        len(results)
    )


    # ========================================================
    # SONUÇLAR
    # ========================================================

    for x in results:

        print(

            f"{x['symbol']} "
            f"| SCORE: {x['score']} "
            f"| MONEY: {x['money_score']} "
            f"| LONG: {x['long_ratio']:.1f}% "
            f"| NET: {money_format(x['net_open'])} "
            f"| VOL: {x['volume_ratio']:.2f}x "
            f"| RSI15: {x['rsi15']:.1f} "
            f"| DEMAND: {x['demand']}"

        )


    # ========================================================
    # TELEGRAM
    # ========================================================

    sent = 0


    for x in results:

        symbol = x[
            "symbol"
        ]


        if not can_send(
            symbol
        ):

            continue


        message = build_message(
            x
        )


        if send_telegram(
            message
        ):

            STATE[
                symbol
            ] = time.time()

            save_state()

            sent += 1


        if sent >= MAX_ALERTS:

            break


    print()
    print(
        "📨 Gönderilen alarm:",
        sent
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print(
        "🚀 MEXC MONEY FLOW RADAR V4.1 BAŞLADI"
    )

    print()
    print(
        "Toplam Futures → Ticker → "
        "TOP coinler → Para → Hacim → RSI"
    )

    print()


    while True:

        try:

            scan()

        except KeyboardInterrupt:

            print(
                "Program kapatıldı."
            )

            break

        except Exception as e:

            print(
                "❌ ANA HATA:",
                e
            )


        print()
        print(
            f"⏳ {SCAN_INTERVAL} saniye bekleniyor..."
        )

        time.sleep(
            SCAN_INTERVAL
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
