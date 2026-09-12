import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V11
#
# AMAÇ:
# Pump başlamadan ÖNCE gerçek anlamlı yeni pozisyon akışı
# olan coinleri bulmak.
#
# PARA AKIŞI = ANA FİLTRE
#
# Küçük işlem:
# $727 +100%  -> RED
# $2K   +100%  -> RED
#
# Anlamlı işlem:
# $25K+        -> değerlendir
# $100K+       -> güçlü
# $250K+       -> çok güçlü
# $500K+       -> çok güçlü
#
# SKOR:
# PARA AKIŞI = 50
# TEKNİK     = 30
# HACİM      = 20
# ============================================================


# ============================================================
# AYARLAR
# ============================================================

BASE = "https://api.mexc.com"

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID"
)

MAX_WORKERS = 8

CANDLE_COUNT = 90

TECH_TOP = 120

MAX_ALERTS = 6

MIN_SCORE = 55

MIN_MONEY_SCORE = 18

REQUEST_INTERVAL = 0.10

DEALS_LIMIT = 100

# ------------------------------------------------------------
# GERÇEK PARA FİLTRESİ
# ------------------------------------------------------------

MIN_OPEN_NOTIONAL = 25000

# Açılış akışının 24H hacme minimum oranı
MIN_OPEN_24H_RATIO = 0.001

# Çok küçük 24H hacimli coinleri ele
MIN_24H_AMOUNT = 100000


session = requests.Session()

_last_request = 0.0

CONTRACT_INFO = {}


# ============================================================
# MEXC GET
# ============================================================

def mexc_get(
    path,
    params=None,
    timeout=15
):

    global _last_request

    wait = (
        REQUEST_INTERVAL
        -
        (
            time.time()
            -
            _last_request
        )
    )

    if wait > 0:
        time.sleep(wait)

    try:

        response = session.get(
            BASE + path,
            params=params or {},
            timeout=timeout
        )

        _last_request = time.time()

        if response.status_code != 200:
            return None

        data = response.json()

        if isinstance(data, dict):

            if data.get("success") is False:
                return None

        return data

    except Exception:

        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):

    if (
        not TELEGRAM_BOT_TOKEN
        or
        not TELEGRAM_CHAT_ID
    ):

        print(
            "⚠️ Telegram ENV bulunamadı."
        )

        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    try:

        response = session.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text
            },
            timeout=15
        )

        return (
            response.status_code == 200
        )

    except Exception:

        return False


# ============================================================
# FUTURES
# ============================================================

def get_contracts():

    global CONTRACT_INFO

    data = mexc_get(
        "/api/v1/contract/detail"
    )

    if not data:
        return []

    rows = data.get(
        "data",
        []
    )

    if not isinstance(rows, list):
        return []

    CONTRACT_INFO = {}

    symbols = []

    for item in rows:

        symbol = item.get(
            "symbol",
            ""
        )

        if not symbol.endswith(
            "_USDT"
        ):
            continue

        try:

            state = int(
                item.get(
                    "state",
                    0
                )
            )

        except Exception:

            state = 0

        if state != 0:
            continue

        try:

            contract_size = float(
                item.get(
                    "contractSize",
                    0
                )
            )

        except Exception:

            contract_size = 0.0

        if contract_size <= 0:
            continue

        CONTRACT_INFO[symbol] = {
            "contract_size": contract_size
        }

        symbols.append(symbol)

    return sorted(
        set(symbols)
    )


# ============================================================
# KLINE
# ============================================================

def get_klines(
    symbol,
    interval
):

    end = int(
        time.time()
    )

    start = (
        end
        -
        (
            CANDLE_COUNT
            *
            4
            *
            3600
        )
    )

    data = mexc_get(
        f"/api/v1/contract/kline/{symbol}",
        {
            "interval": interval,
            "start": start,
            "end": end
        }
    )

    if not data:
        return []

    d = data.get("data")

    if not isinstance(
        d,
        dict
    ):
        return []

    times = d.get(
        "time",
        []
    )

    opens = d.get(
        "open",
        []
    )

    closes = d.get(
        "close",
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

    vols = d.get(
        "vol",
        []
    )

    n = min(
        len(times),
        len(opens),
        len(closes),
        len(highs),
        len(lows),
        len(vols)
    )

    candles = []

    for i in range(n):

        try:

            candles.append({
                "time": float(times[i]),
                "open": float(opens[i]),
                "close": float(closes[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "vol": float(vols[i])
            })

        except Exception:

            pass

    return candles


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    values,
    period=14
):

    if len(values) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(
        1,
        len(values)
    ):

        diff = (
            values[i]
            -
            values[i - 1]
        )

        if diff > 0:

            gains.append(diff)
            losses.append(0.0)

        else:

            gains.append(0.0)
            losses.append(-diff)

    avg_gain = (
        sum(gains[-period:])
        /
        period
    )

    avg_loss = (
        sum(losses[-period:])
        /
        period
    )

    if avg_loss == 0:
        return 100.0

    rs = (
        avg_gain
        /
        avg_loss
    )

    return (
        100
        -
        (
            100
            /
            (1 + rs)
        )
    )


# ============================================================
# PERCENT
# ============================================================

def pct_change(
    current,
    previous
):

    if previous == 0:
        return 0.0

    return (
        (
            current
            -
            previous
        )
        /
        previous
        *
        100
    )


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(
    candles,
    recent=5,
    base=20
):

    if len(candles) < recent + base:
        return 1.0

    recent_avg = (
        sum(
            x["vol"]
            for x in candles[-recent:]
        )
        /
        recent
    )

    previous = candles[
        -(recent + base):-recent
    ]

    previous_avg = (
        sum(
            x["vol"]
            for x in previous
        )
        /
        len(previous)
    )

    if previous_avg <= 0:
        return 1.0

    return (
        recent_avg
        /
        previous_avg
    )


# ============================================================
# VOLUME ACCELERATION
# ============================================================

def volume_acceleration(
    candles
):

    if len(candles) < 15:
        return 1.0

    recent = (
        sum(
            x["vol"]
            for x in candles[-5:]
        )
        /
        5
    )

    previous = (
        sum(
            x["vol"]
            for x in candles[-10:-5]
        )
        /
        5
    )

    if previous <= 0:
        return 1.0

    return (
        recent
        /
        previous
    )


# ============================================================
# HIGHER LOW
# ============================================================

def higher_low(
    candles
):

    if len(candles) < 16:
        return False

    recent = min(
        x["low"]
        for x in candles[-8:]
    )

    previous = min(
        x["low"]
        for x in candles[-16:-8]
    )

    return (
        recent > previous
    )


# ============================================================
# COMPRESSION
# ============================================================

def compression(
    candles
):

    if len(candles) < 10:
        return False

    high = max(
        x["high"]
        for x in candles[-10:]
    )

    low = min(
        x["low"]
        for x in candles[-10:]
    )

    if low <= 0:
        return False

    rng = (
        (
            high - low
        )
        /
        low
        *
        100
    )

    return rng <= 18


# ============================================================
# TEKNİK ANALİZ
# ============================================================

def analyze_technical(
    symbol
):

    try:

        c4 = get_klines(
            symbol,
            "Hour4"
        )

        c1 = get_klines(
            symbol,
            "Min60"
        )

        c15 = get_klines(
            symbol,
            "Min15"
        )

        if (
            len(c4) < 50
            or
            len(c1) < 50
            or
            len(c15) < 50
        ):

            return None

        p4 = [
            x["close"]
            for x in c4
        ]

        p1 = [
            x["close"]
            for x in c1
        ]

        p15 = [
            x["close"]
            for x in c15
        ]

        current = p15[-1]

        if current <= 0:
            return None

        rsi4 = calculate_rsi(p4)

        rsi1 = calculate_rsi(p1)

        rsi15 = calculate_rsi(p15)

        v1 = volume_ratio(c1)

        v15 = volume_ratio(c15)

        acc1 = volume_acceleration(c1)

        acc15 = volume_acceleration(c15)

        mom1 = pct_change(
            p1[-1],
            p1[-5]
        )

        mom15 = pct_change(
            p15[-1],
            p15[-5]
        )

        move5 = pct_change(
            p15[-1],
            p15[-6]
        )

        move20 = pct_change(
            p15[-1],
            p15[-21]
        )

        resistance_price = max(
            x["high"]
            for x in c1[-25:]
        )

        resistance = (
            (
                resistance_price
                -
                current
            )
            /
            current
            *
            100
        )

        hl = higher_low(c1)

        comp = compression(c4)

        # ====================================================
        # AŞIRI ISINMA RED
        # ====================================================

        if rsi4 > 72:
            return None

        if rsi1 > 72:
            return None

        if rsi15 > 76:
            return None

        if v15 > 7:
            return None

        if move5 > 10:
            return None

        if move20 > 18:
            return None

        if resistance > 10:
            return None

        # ====================================================
        # TEKNİK PUAN
        # ====================================================

        score = 0

        if 45 <= rsi4 <= 65:
            score += 8

        elif 40 <= rsi4 <= 70:
            score += 5

        if 50 <= rsi1 <= 65:
            score += 8

        elif 45 <= rsi1 <= 70:
            score += 5

        if 50 <= rsi15 <= 68:
            score += 7

        elif 45 <= rsi15 <= 72:
            score += 4

        if 0.9 <= v1 <= 2.5:
            score += 7

        elif v1 >= 0.7:
            score += 4

        if 0.8 <= v15 <= 3:
            score += 7

        elif v15 >= 0.7:
            score += 4

        if 0 < mom1 <= 4:
            score += 5

        if 0 < mom15 <= 3:
            score += 5

        if hl:
            score += 6

        if comp:
            score += 5

        if 0.5 <= resistance <= 5:
            score += 7

        elif 0 <= resistance <= 8:
            score += 4

        return {

            "symbol": symbol,

            "technical_score": score,

            "rsi4": rsi4,

            "rsi1": rsi1,

            "rsi15": rsi15,

            "v1": v1,

            "v15": v15,

            "acc1": acc1,

            "acc15": acc15,

            "mom1": mom1,

            "mom15": mom15,

            "move5": move5,

            "move20": move20,

            "resistance": resistance,

            "higher_low": hl,

            "compression": comp
        }

    except Exception:

        return None


# ============================================================
# TICKER
# ============================================================

def get_ticker(
    symbol
):

    data = mexc_get(
        "/api/v1/contract/ticker",
        {
            "symbol": symbol
        }
    )

    if not data:
        return None

    return data.get("data")


# ============================================================
# DEAL FLOW
# ============================================================

def get_deal_flow(
    symbol
):

    data = mexc_get(
        f"/api/v1/contract/deals/{symbol}",
        {
            "limit": DEALS_LIMIT
        }
    )

    if not data:
        return None

    rows = data.get(
        "data",
        []
    )

    if not isinstance(rows, list):
        return None

    info = CONTRACT_INFO.get(
        symbol
    )

    if not info:
        return None

    contract_size = info[
        "contract_size"
    ]

    buy_open = 0.0

    sell_open = 0.0

    buy_all = 0.0

    sell_all = 0.0

    open_count = 0

    for row in rows:

        try:

            price = float(
                row.get("p", 0)
            )

            volume = float(
                row.get("v", 0)
            )

            T = int(
                row.get("T", 0)
            )

            O = int(
                row.get("O", 0)
            )

            if (
                price <= 0
                or
                volume <= 0
            ):
                continue

            notional = (
                price
                *
                volume
                *
                contract_size
            )

            if T == 1:
                buy_all += notional

            elif T == 2:
                sell_all += notional

            # O=1 = open
            if O == 1:

                open_count += 1

                if T == 1:
                    buy_open += notional

                elif T == 2:
                    sell_open += notional

        except Exception:

            continue

    open_total = (
        buy_open
        +
        sell_open
    )

    # ========================================================
    # TICKER
    # ========================================================

    ticker = get_ticker(
        symbol
    )

    amount24 = 0.0

    funding = 0.0

    if ticker:

        try:

            amount24 = float(
                ticker.get(
                    "amount24",
                    0
                )
            )

        except Exception:
            pass

        try:

            funding = float(
                ticker.get(
                    "fundingRate",
                    0
                )
            )

        except Exception:
            pass

    # ========================================================
    # OPEN FLOW OLMUYORSA RED
    # ========================================================

    if open_total <= 0:
        return None

    # ========================================================
    # 24H HACİM KONTROL
    # ========================================================

    if amount24 < MIN_24H_AMOUNT:
        return None

    # ========================================================
    # GERÇEK PARA KONTROLÜ
    #
    # $727 / $2K BURADA ELENİR
    # ========================================================

    if open_total < MIN_OPEN_NOTIONAL:
        return None

    # ========================================================
    # OPEN / 24H
    # ========================================================

    open_ratio = (
        open_total
        /
        amount24
    )

    if open_ratio < MIN_OPEN_24H_RATIO:
        return None

    # ========================================================
    # NET
    # ========================================================

    net = (
        buy_open
        -
        sell_open
    )

    net_pct = (
        net
        /
        open_total
        *
        100
    )

    buy_share = (
        buy_open
        /
        open_total
        *
        100
    )

    return {

        "buy_open": buy_open,

        "sell_open": sell_open,

        "open_total": open_total,

        "net": net,

        "net_pct": net_pct,

        "buy_share": buy_share,

        "open_count": open_count,

        "amount24": amount24,

        "open_ratio": open_ratio,

        "funding_rate": funding
    }


# ============================================================
# PARA SKORU
# ============================================================

def money_score(
    flow
):

    if not flow:
        return 0

    net = flow[
        "net_pct"
    ]

    buy = flow[
        "buy_share"
    ]

    open_total = flow[
        "open_total"
    ]

    open_ratio = flow[
        "open_ratio"
    ]

    score = 0

    # ========================================================
    # NET FLOW
    # ========================================================

    if net >= 40:
        score += 25

    elif net >= 30:
        score += 23

    elif net >= 20:
        score += 20

    elif net >= 15:
        score += 17

    elif net >= 10:
        score += 14

    elif net >= 7:
        score += 10

    elif net >= 4:
        score += 6

    elif net >= 0:
        score += 2

    else:
        return 0

    # ========================================================
    # BUY SHARE
    # ========================================================

    if buy >= 80:
        score += 12

    elif buy >= 72:
        score += 10

    elif buy >= 65:
        score += 8

    elif buy >= 60:
        score += 6

    elif buy >= 55:
        score += 3

    elif buy < 50:
        score -= 10

    # ========================================================
    # OPEN / 24H
    # ========================================================

    if open_ratio >= 0.01:
        score += 8

    elif open_ratio >= 0.005:
        score += 7

    elif open_ratio >= 0.0025:
        score += 6

    elif open_ratio >= 0.001:
        score += 4

    else:
        score += 1

    # ========================================================
    # MUTLAK PARA
    # ========================================================

    if open_total >= 1000000:
        score += 5

    elif open_total >= 500000:
        score += 5

    elif open_total >= 250000:
        score += 4

    elif open_total >= 100000:
        score += 3

    elif open_total >= 50000:
        score += 2

    else:
        score += 1

    # ========================================================
    # %100 BUY + düşük para
    # ========================================================

    if (
        buy >= 99
        and
        open_total < 100000
    ):

        score -= 8

    return max(
        0,
        min(
            score,
            50
        )
    )


# ============================================================
# HACİM SKORU
# ============================================================

def volume_score(
    tech
):

    score = 0

    v1 = tech["v1"]

    v15 = tech["v15"]

    a1 = tech["acc1"]

    a15 = tech["acc15"]

    if 1.3 <= v1 <= 2.5:
        score += 6

    elif 1 <= v1 < 1.3:
        score += 4

    elif v1 >= 2.5:
        score += 5

    elif v1 >= 0.8:
        score += 2

    if 1.3 <= v15 <= 2.8:
        score += 6

    elif 1 <= v15 < 1.3:
        score += 4

    elif v15 >= 2.8:
        score += 4

    elif v15 >= 0.8:
        score += 2

    if a1 >= 1.5:
        score += 4

    elif a1 >= 1.2:
        score += 2

    if a15 >= 1.5:
        score += 4

    elif a15 >= 1.2:
        score += 2

    return min(
        score,
        20
    )


# ============================================================
# FINAL
# ============================================================

def calculate_final(
    tech,
    flow
):

    money = money_score(
        flow
    )

    if money < MIN_MONEY_SCORE:
        return None

    technical = min(
        (
            tech[
                "technical_score"
            ]
            /
            65
            *
            30
        ),
        30
    )

    volume = volume_score(
        tech
    )

    total = (
        money
        +
        technical
        +
        volume
    )

    # ========================================================
    # ISINMA CEZALARI
    # ========================================================

    if tech["rsi15"] > 72:
        total -= 8

    if tech["rsi1"] > 68:
        total -= 5

    if tech["v15"] > 5:
        total -= 8

    if tech["mom1"] > 6:
        total -= 6

    if tech["move5"] > 7:
        total -= 8

    if tech["move20"] > 12:
        total -= 8

    # ========================================================
    # FUNDING
    # ========================================================

    funding = flow[
        "funding_rate"
    ]

    if funding > 0.0015:
        total -= 6

    elif funding > 0.001:
        total -= 3

    if flow["net_pct"] < 0:
        return None

    if total < MIN_SCORE:
        return None

    result = dict(
        tech
    )

    result[
        "money_score"
    ] = money

    result[
        "technical_part"
    ] = technical

    result[
        "volume_part"
    ] = volume

    result[
        "total_score"
    ] = round(
        total,
        1
    )

    result[
        "flow"
    ] = flow

    return result


# ============================================================
# FIRE
# ============================================================

def fire_level(
    money,
    net
):

    if (
        money >= 42
        and
        net >= 20
    ):
        return "🔥🔥🔥"

    if (
        money >= 34
        and
        net >= 12
    ):
        return "🔥🔥"

    if money >= 25:
        return "🔥"

    return "⚡"


# ============================================================
# PARA FORMAT
# ============================================================

def money_format(
    value
):

    if value >= 1000000:

        return (
            f"${value / 1000000:.2f}M"
        )

    if value >= 1000:

        return (
            f"${value / 1000:.0f}K"
        )

    return (
        f"${value:.0f}"
    )


# ============================================================
# TELEGRAM MESAJ
# ============================================================

def format_telegram(
    result
):

    flow = result[
        "flow"
    ]

    money = result[
        "money_score"
    ]

    net = flow[
        "net_pct"
    ]

    fire = fire_level(
        money,
        net
    )

    return (
        "🚨 PRE-PUMP\n\n"

        f"🪙 {result['symbol']}\n"

        f"⭐ "
        f"{result['total_score']:.0f}/100\n\n"

        f"💰 Para Girişi: "
        f"{fire} "
        f"{net:+.1f}%\n"

        f"💵 Açılış Akışı: "
        f"{money_format(flow['open_total'])}\n"

        f"🟢 Alış Baskısı: "
        f"{flow['buy_share']:.0f}%\n"

        f"📈 Hacim: "
        f"{result['v1']:.1f}x\n"

        f"🎯 Direnç: "
        f"%{result['resistance']:.1f}\n\n"

        "TP1 +3% | "
        "TP2 +6% | "
        "TP3 +10%"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    print("")
    print("=" * 65)
    print("🚀 MEXC PRE-PUMP RADAR V11")
    print("=" * 65)

    print(
        "💰 PARA AKIŞI = ANA FİLTRE"
    )

    print(
        f"💵 Minimum açılış akışı = "
        f"${MIN_OPEN_NOTIONAL:,}"
    )

    print(
        "📊 TEKNİK = 30"
    )

    print(
        "📈 HACİM = 20"
    )

    # ========================================================
    # FUTURES
    # ========================================================

    print("")
    print(
        "🔎 MEXC Futures coinleri alınıyor..."
    )

    symbols = get_contracts()

    print(
        f"✅ Futures: "
        f"{len(symbols)}"
    )

    if not symbols:
        print(
            "❌ Futures bulunamadı."
        )
        return

    # ========================================================
    # API TEST
    # ========================================================

    print("")
    print(
        "🧪 API TEST..."
    )

    kline = get_klines(
        "BTC_USDT",
        "Min15"
    )

    print(
        "✅ Kline OK"
        if kline
        else
        "❌ Kline HATA"
    )

    ticker = get_ticker(
        "BTC_USDT"
    )

    print(
        "✅ Ticker OK"
        if ticker
        else
        "❌ Ticker HATA"
    )

    flow_test = get_deal_flow(
        "BTC_USDT"
    )

    if flow_test:

        print(
            "✅ İşlem akışı OK | "
            f"Net: "
            f"{flow_test['net_pct']:+.2f}% | "
            f"Buy: "
            f"{flow_test['buy_share']:.1f}% | "
            f"Open: "
            f"${flow_test['open_total']:,.0f}"
        )

    else:

        print(
            "⚠️ BTC flow filtreye takıldı."
        )

    # ========================================================
    # TEKNİK
    # ========================================================

    print("")
    print(
        "🟣 TEKNİK ÖN FİLTRE..."
    )

    candidates = []

    completed = 0

    total = len(symbols)

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_technical,
                symbol
            ): symbol

            for symbol in symbols
        }

        for future in as_completed(
            futures
        ):

            completed += 1

            try:

                result = future.result()

            except Exception:

                result = None

            if result:
                candidates.append(
                    result
                )

            if (
                completed % 100 == 0
                or
                completed == total
            ):

                print(
                    f"İlerleme "
                    f"{completed}/{total} "
                    f"| Teknik aday "
                    f"{len(candidates)}"
                )

    candidates.sort(
        key=lambda x:
            x["technical_score"],
        reverse=True
    )

    candidates = candidates[
        :TECH_TOP
    ]

    print("")
    print(
        f"✅ Teknik aday: "
        f"{len(candidates)}"
    )

    # ========================================================
    # PARA AKIŞI
    # ========================================================

    print("")
    print(
        "💰 GERÇEK PARA AKIŞI TARAMASI..."
    )

    final = []

    checked = 0

    rejected_small = 0

    flow_found = 0

    strong = 0

    total_candidates = len(
        candidates
    )

    for tech in candidates:

        checked += 1

        symbol = tech[
            "symbol"
        ]

        flow = get_deal_flow(
            symbol
        )

        if flow is None:

            rejected_small += 1

        else:

            flow_found += 1

            ms = money_score(
                flow
            )

            if ms >= MIN_MONEY_SCORE:

                strong += 1

                result = calculate_final(
                    tech,
                    flow
                )

                if result:

                    final.append(
                        result
                    )

        if (
            checked % 20 == 0
            or
            checked == total_candidates
        ):

            print(
                f"Para akışı "
                f"{checked}/{total_candidates} "
                f"| Flow {flow_found} "
                f"| Küçük/uygunsuz {rejected_small} "
                f"| Güçlü {strong} "
                f"| Final {len(final)}"
            )

    # ========================================================
    # SIRALA
    # ========================================================

    final.sort(
        key=lambda x: (
            x["total_score"],
            x["money_score"],
            x["flow"]["open_total"],
            x["flow"]["net_pct"]
        ),
        reverse=True
    )

    # ========================================================
    # SONUÇ
    # ========================================================

    print("")
    print("=" * 65)
    print("🏆 EN GÜÇLÜ PRE-PUMP ADAYLARI")
    print("=" * 65)

    if final:

        for r in final[:15]:

            f = r[
                "flow"
            ]

            print(
                f"{r['symbol']:15} | "
                f"Skor {r['total_score']:5.1f} | "
                f"Para {r['money_score']:2d} | "
                f"Net {f['net_pct']:+6.1f}% | "
                f"Buy {f['buy_share']:5.1f}% | "
                f"Open ${f['open_total']:,.0f}"
            )

    else:

        print(
            "❌ Güçlü para akışı bulunamadı."
        )

    # ========================================================
    # TELEGRAM
    # ========================================================

    print("")
    print(
        "📨 TELEGRAM GÖNDERİMİ..."
    )

    sent = 0

    for result in final[
        :MAX_ALERTS
    ]:

        message = format_telegram(
            result
        )

        print("")
        print(
            message
        )

        if send_telegram(
            message
        ):

            sent += 1

    # ========================================================
    # BİTİŞ
    # ========================================================

    elapsed = (
        time.time()
        -
        started
    )

    print("")
    print("=" * 65)
    print("✅ V11 RADAR TAMAMLANDI")
    print("=" * 65)

    print(
        f"⏱ Süre: "
        f"{elapsed:.1f} sn"
    )

    print(
        f"🌐 Futures: "
        f"{len(symbols)}"
    )

    print(
        f"🔎 Teknik: "
        f"{len(candidates)}"
    )

    print(
        f"💰 Flow: "
        f"{flow_found}"
    )

    print(
        f"🗑 Küçük/Uygunsuz: "
        f"{rejected_small}"
    )

    print(
        f"🔥 Güçlü para: "
        f"{strong}"
    )

    print(
        f"🎯 Final: "
        f"{len(final)}"
    )

    print(
        f"📨 Telegram: "
        f"{sent}"
    )

    print("=" * 65)


# ============================================================
# BAŞLAT
# ============================================================

if __name__ == "__main__":

    print("")
    print("=" * 65)
    print("🚀 MEXC PRE-PUMP RADAR V11 BAŞLADI")
    print("=" * 65)

    main()
