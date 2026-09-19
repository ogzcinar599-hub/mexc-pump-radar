import os
import json
import time
import threading
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V3
#
# MEXC USDT FUTURES
#
# 15M + 1H + 4H
# RSI
# HACİM
# MOMENTUM
# OPEN FLOW
# BTC YÖNÜ
# DEMAND / SUPPLY
# TP / SL
# TELEGRAM
# COOLDOWN
#
# TEK TARAMA YAPAR VE ÇIKAR
# ============================================================


# ============================================================
# AYARLAR
# ============================================================

BASE_URL = "https://api.mexc.com"

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()

MAX_CANDIDATES = 35
MAX_WORKERS = 4

DEALS_LIMIT = 100

MIN_24H_VOLUME = 100000

MIN_VOLUME_RATIO = 1.10

MIN_OPEN_NOTIONAL = 15000

MIN_NET_RATIO = 4.0

MIN_LONG_RATIO = 53.0
MIN_SHORT_RATIO = 53.0

MIN_SCORE = 65

COOLDOWN_HOURS = 4

STATE_FILE = "sent_signals.json"

REQUEST_TIMEOUT = 15

REQUEST_INTERVAL = 0.12


# ============================================================
# PUMP FİLTRELERİ
# ============================================================

MAX_15M_PUMP = 8.0
MAX_1H_PUMP = 15.0


# ============================================================
# TP / SL
# ============================================================

LONG_TP1 = 1.03
LONG_TP2 = 1.06
LONG_SL = 0.975

SHORT_TP1 = 0.97
SHORT_TP2 = 0.94
SHORT_SL = 1.025


# ============================================================
# TOKENIZED STOCK / STOCK FİLTRESİ
# ============================================================

STOCK_FILTER = {
    "AAPL",
    "AMZN",
    "GOOG",
    "GOOGL",
    "META",
    "MSFT",
    "NVDA",
    "TSLA",
    "NFLX",
    "AMD",
    "INTC",
    "COIN",
    "MSTR",
    "PLTR",
    "HOOD",
    "ARM",
    "ORCL",
    "CRM",
    "BA",
    "DIS",
    "NKE",
    "JPM",
    "V",
    "MA",
    "WMT",
    "PFE",
    "BAC",
    "COST",
    "XOM",
    "CVX",
    "SPY",
    "QQQ",
    "IWM",
}


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "MEXC-PRE-PUMP-RADAR/3.0"
})


# ============================================================
# RATE LIMIT
# ============================================================

REQUEST_LOCK = threading.Lock()

LAST_REQUEST = 0.0


def rate_limit():

    global LAST_REQUEST

    with REQUEST_LOCK:

        now = time.time()

        wait = REQUEST_INTERVAL - (
            now - LAST_REQUEST
        )

        if wait > 0:
            time.sleep(wait)

        LAST_REQUEST = time.time()


# ============================================================
# HTTP
# ============================================================

def api_get(
    path,
    params=None,
    retries=3
):

    url = BASE_URL + path

    for attempt in range(retries):

        try:

            rate_limit()

            response = SESSION.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 429:

                wait = 2 + (
                    attempt * 2
                )

                print(
                    f"⚠️ Rate limit. "
                    f"{wait}s bekleniyor..."
                )

                time.sleep(wait)

                continue

            response.raise_for_status()

            return response.json()

        except Exception as e:

            if attempt == retries - 1:

                return None

            time.sleep(
                1 + attempt
            )

    return None


# ============================================================
# CONTRACT LİSTESİ
# ============================================================

def get_contracts():

    print(
        "📡 Futures sözleşmeleri alınıyor..."
    )

    data = api_get(
        "/api/v1/contract/detail"
    )

    if not data:
        return {}

    rows = data.get(
        "data",
        []
    )

    contracts = {}

    for item in rows:

        try:

            symbol = str(
                item.get(
                    "symbol",
                    ""
                )
            )

            if not symbol.endswith(
                "_USDT"
            ):
                continue

            state = item.get(
                "state"
            )

            if state is not None:

                try:

                    if int(state) != 0:
                        continue

                except Exception:
                    pass

            base = symbol.replace(
                "_USDT",
                ""
            ).upper()

            if base in STOCK_FILTER:
                continue

            contract_size = float(
                item.get(
                    "contractSize",
                    0
                )
            )

            if contract_size <= 0:
                continue

            contracts[symbol] = {
                "contract_size": contract_size
            }

        except Exception:
            continue

    return contracts


# ============================================================
# TICKER
# ============================================================

def get_tickers():

    data = api_get(
        "/api/v1/contract/ticker"
    )

    if not data:
        return {}

    raw = data.get(
        "data"
    )

    if not raw:
        return {}

    tickers = {}

    # --------------------------------------------------------
    # Liste gelirse
    # --------------------------------------------------------

    if isinstance(raw, list):

        rows = raw

    # --------------------------------------------------------
    # Dict gelirse
    # --------------------------------------------------------

    elif isinstance(raw, dict):

        # Bazı cevaplarda tek ticker
        if "symbol" in raw:

            rows = [raw]

        else:

            rows = []

            for value in raw.values():

                if isinstance(
                    value,
                    list
                ):
                    rows.extend(value)

                elif isinstance(
                    value,
                    dict
                ):
                    rows.append(value)

    else:

        return {}

    for row in rows:

        try:

            symbol = str(
                row.get(
                    "symbol",
                    ""
                )
            )

            if not symbol.endswith(
                "_USDT"
            ):
                continue

            price = float(
                row.get(
                    "lastPrice",
                    0
                )
            )

            volume = float(
                row.get(
                    "volume24",
                    0
                )
            )

            change = float(
                row.get(
                    "riseFallRate",
                    0
                )
            )

            # MEXC bazı cevaplarda 0.05
            # şeklinde oran verebilir.
            if abs(change) <= 1:

                change *= 100

            if price <= 0:
                continue

            tickers[symbol] = {
                "price": price,
                "volume24": volume,
                "change24": change
            }

        except Exception:
            continue

    return tickers


# ============================================================
# KLINE
# ============================================================

def get_kline(
    symbol,
    interval
):

    data = api_get(
        f"/api/v1/contract/kline/{symbol}",
        params={
            "interval": interval
        }
    )

    if not data:
        return []

    raw = data.get(
        "data"
    )

    if not raw:
        return []

    try:

        times = raw.get(
            "time",
            []
        )

        opens = raw.get(
            "open",
            []
        )

        closes = raw.get(
            "close",
            []
        )

        highs = raw.get(
            "high",
            []
        )

        lows = raw.get(
            "low",
            []
        )

        volumes = raw.get(
            "vol",
            []
        )

        count = min(
            len(times),
            len(opens),
            len(closes),
            len(highs),
            len(lows),
            len(volumes)
        )

        candles = []

        for i in range(count):

            candles.append({
                "time": float(
                    times[i]
                ),
                "open": float(
                    opens[i]
                ),
                "close": float(
                    closes[i]
                ),
                "high": float(
                    highs[i]
                ),
                "low": float(
                    lows[i]
                ),
                "vol": float(
                    volumes[i]
                )
            })

        return candles[-60:]

    except Exception:

        return []


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    closes,
    period=14
):

    if len(closes) < (
        period + 1
    ):
        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(closes)
    ):

        change = (
            closes[i]
            - closes[i - 1]
        )

        if change >= 0:

            gains.append(change)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(
                abs(change)
            )

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

        return 100.0

    rs = avg_gain / avg_loss

    return (
        100
        - (
            100
            / (1 + rs)
        )
    )


# ============================================================
# HACİM RATIO
# ============================================================

def get_volume_ratio(
    candles
):

    if len(candles) < 25:
        return 0

    current = candles[-1]["vol"]

    previous = [
        x["vol"]
        for x in candles[-21:-1]
    ]

    if not previous:
        return 0

    average = (
        sum(previous)
        / len(previous)
    )

    if average <= 0:
        return 0

    return current / average


# ============================================================
# MOMENTUM
# ============================================================

def get_momentum(
    candles,
    bars
):

    if len(candles) <= bars:
        return 0

    old_price = candles[
        -bars - 1
    ]["close"]

    new_price = candles[
        -1
    ]["close"]

    if old_price <= 0:
        return 0

    return (
        (
            new_price
            / old_price
        ) - 1
    ) * 100


# ============================================================
# DEMAND / SUPPLY
# ============================================================

def get_demand_supply(
    candles,
    price
):

    if len(candles) < 25:

        return False, False

    recent = candles[-30:]

    lows = [
        x["low"]
        for x in recent
    ]

    highs = [
        x["high"]
        for x in recent
    ]

    demand_level = min(lows)

    supply_level = max(highs)

    demand_distance = (
        (
            price
            - demand_level
        )
        / price
    ) * 100

    supply_distance = (
        (
            supply_level
            - price
        )
        / price
    ) * 100

    demand = (
        0
        <= demand_distance
        <= 2.0
    )

    supply = (
        0
        <= supply_distance
        <= 2.0
    )

    return demand, supply


# ============================================================
# BTC YÖNÜ
# ============================================================

def get_btc_direction():

    directions = []

    for interval in (
        "Min15",
        "Min60",
        "Hour4"
    ):

        candles = get_kline(
            "BTC_USDT",
            interval
        )

        if len(candles) < 10:
            continue

        old = candles[
            -6
        ]["close"]

        new = candles[
            -1
        ]["close"]

        if old <= 0:
            continue

        change = (
            (
                new / old
            ) - 1
        ) * 100

        directions.append(
            change
        )

    if len(directions) < 2:

        return "NEUTRAL"

    bullish = sum(
        x > 0
        for x in directions
    )

    bearish = sum(
        x < 0
        for x in directions
    )

    if bullish >= 2:
        return "BULLISH"

    if bearish >= 2:
        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# OPEN FLOW
# ============================================================

def get_open_flow(
    symbol,
    contract_size
):

    data = api_get(
        f"/api/v1/contract/deals/{symbol}",
        params={
            "limit": DEALS_LIMIT
        }
    )

    if not data:
        return None

    rows = data.get(
        "data",
        []
    )

    if not rows:
        return None

    long_open = 0.0
    short_open = 0.0

    total_open = 0.0

    for trade in rows:

        try:

            price = float(
                trade.get(
                    "p",
                    0
                )
            )

            volume = float(
                trade.get(
                    "v",
                    0
                )
            )

            trade_type = int(
                trade.get(
                    "T",
                    0
                )
            )

            open_flag = int(
                trade.get(
                    "O",
                    0
                )
            )

            if (
                price <= 0
                or volume <= 0
            ):
                continue

            # Sadece yeni pozisyon açılışları
            if open_flag != 1:
                continue

            notional = (
                price
                * volume
                * contract_size
            )

            if notional <= 0:
                continue

            total_open += notional

            if trade_type == 1:

                long_open += notional

            elif trade_type == 2:

                short_open += notional

        except Exception:
            continue

    if total_open <= 0:

        return None

    long_ratio = (
        long_open
        / total_open
    ) * 100

    short_ratio = (
        short_open
        / total_open
    ) * 100

    net = (
        long_open
        - short_open
    )

    net_ratio = (
        abs(net)
        / total_open
    ) * 100

    return {
        "long_open": long_open,
        "short_open": short_open,
        "total_open": total_open,
        "long_ratio": long_ratio,
        "short_ratio": short_ratio,
        "net": net,
        "net_ratio": net_ratio
    }


# ============================================================
# STATE
# ============================================================

def load_state():

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

            if isinstance(
                data,
                dict
            ):
                return data

    except Exception:
        pass

    return {}


def save_state(
    state
):

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                state,
                file,
                indent=2
            )

    except Exception as e:

        print(
            "State kayıt hatası:",
            e
        )


def cooldown_active(
    symbol,
    state
):

    value = state.get(
        symbol
    )

    if value is None:
        return False

    try:

        age = (
            time.time()
            - float(value)
        )

        return age < (
            COOLDOWN_HOURS
            * 3600
        )

    except Exception:

        return False


# ============================================================
# ANALİZ
# ============================================================

def analyze_symbol(
    symbol,
    ticker,
    contract
):

    try:

        price = ticker[
            "price"
        ]

        volume24 = ticker[
            "volume24"
        ]

        change24 = ticker[
            "change24"
        ]

        contract_size = contract[
            "contract_size"
        ]

        if volume24 < MIN_24H_VOLUME:

            return None

        # ----------------------------------------------------
        # 15M
        # ----------------------------------------------------

        c15 = get_kline(
            symbol,
            "Min15"
        )

        # ----------------------------------------------------
        # 1H
        # ----------------------------------------------------

        c1h = get_kline(
            symbol,
            "Min60"
        )

        # ----------------------------------------------------
        # 4H
        # ----------------------------------------------------

        c4h = get_kline(
            symbol,
            "Hour4"
        )

        if (
            len(c15) < 25
            or len(c1h) < 25
            or len(c4h) < 25
        ):

            return None

        # ----------------------------------------------------
        # RSI
        # ----------------------------------------------------

        rsi15 = calculate_rsi([
            x["close"]
            for x in c15
        ])

        rsi1h = calculate_rsi([
            x["close"]
            for x in c1h
        ])

        rsi4h = calculate_rsi([
            x["close"]
            for x in c4h
        ])

        if (
            rsi15 is None
            or rsi1h is None
            or rsi4h is None
        ):

            return None

        # ----------------------------------------------------
        # HACİM
        # ----------------------------------------------------

        vol_ratio = get_volume_ratio(
            c15
        )

        if (
            vol_ratio
            < MIN_VOLUME_RATIO
        ):

            return None

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        mom15 = get_momentum(
            c15,
            4
        )

        mom1h = get_momentum(
            c1h,
            4
        )

        # ----------------------------------------------------
        # DEMAND / SUPPLY
        # ----------------------------------------------------

        demand, supply = (
            get_demand_supply(
                c15,
                price
            )
        )

        # ----------------------------------------------------
        # OPEN FLOW
        # ----------------------------------------------------

        flow = get_open_flow(
            symbol,
            contract_size
        )

        if not flow:
            return None

        if (
            flow["total_open"]
            < MIN_OPEN_NOTIONAL
        ):

            return None

        # ----------------------------------------------------
        # SKORLAR
        # ----------------------------------------------------

        long_score = 0
        short_score = 0

        # 4H RSI
        if 45 <= rsi4h <= 68:
            long_score += 15

        if 32 <= rsi4h <= 52:
            short_score += 15

        # 1H RSI
        if 48 <= rsi1h <= 68:
            long_score += 10

        if 32 <= rsi1h <= 52:
            short_score += 10

        # 15M RSI
        if 48 <= rsi15 <= 72:
            long_score += 8

        if 28 <= rsi15 <= 52:
            short_score += 8

        # Volume
        if vol_ratio >= 1.20:

            long_score += 8
            short_score += 8

        if vol_ratio >= 1.50:

            long_score += 5
            short_score += 5

        # Momentum
        if mom15 > 0.25:
            long_score += 8

        if mom15 < -0.25:
            short_score += 8

        if mom1h > 0.40:
            long_score += 7

        if mom1h < -0.40:
            short_score += 7

        # Demand / Supply
        if demand:
            long_score += 10

        if supply:
            short_score += 10

        # Open Flow
        if (
            flow["long_ratio"]
            >= MIN_LONG_RATIO
        ):

            long_score += 15

        if (
            flow["short_ratio"]
            >= MIN_SHORT_RATIO
        ):

            short_score += 15

        # Net flow
        if flow["net"] > 0:

            long_score += 5

        elif flow["net"] < 0:

            short_score += 5

        # ----------------------------------------------------
        # BTC
        # ----------------------------------------------------

        btc = get_btc_direction()

        if btc == "BULLISH":

            long_score += 10
            short_score -= 5

        elif btc == "BEARISH":

            short_score += 10
            long_score -= 5

        long_score = max(
            0,
            min(
                100,
                long_score
            )
        )

        short_score = max(
            0,
            min(
                100,
                short_score
            )
        )

        # ----------------------------------------------------
        # YÖN
        # ----------------------------------------------------

        if long_score >= short_score:

            direction = "LONG"
            score = long_score

            if (
                flow["long_ratio"]
                < MIN_LONG_RATIO
            ):

                return None

            if (
                flow["net_ratio"]
                < MIN_NET_RATIO
            ):

                return None

            if (
                mom15
                < -1.5
            ):

                return None

            if change24 > 15:

                return None

        else:

            direction = "SHORT"
            score = short_score

            if (
                flow["short_ratio"]
                < MIN_SHORT_RATIO
            ):

                return None

            if (
                flow["net_ratio"]
                < MIN_NET_RATIO
            ):

                return None

            if (
                mom15
                > 1.5
            ):

                return None

            if change24 < -15:

                return None

        # ----------------------------------------------------
        # SKOR FİLTRESİ
        # ----------------------------------------------------

        if score < MIN_SCORE:

            return None

        # ----------------------------------------------------
        # TP / SL
        # ----------------------------------------------------

        if direction == "LONG":

            tp1 = price * LONG_TP1
            tp2 = price * LONG_TP2
            sl = price * LONG_SL

        else:

            tp1 = price * SHORT_TP1
            tp2 = price * SHORT_TP2
            sl = price * SHORT_SL

        return {
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "price": price,
            "rsi15": rsi15,
            "rsi1h": rsi1h,
            "rsi4h": rsi4h,
            "volume_ratio": vol_ratio,
            "momentum15": mom15,
            "momentum1h": mom1h,
            "long_open": flow["long_open"],
            "short_open": flow["short_open"],
            "total_open": flow["total_open"],
            "long_ratio": flow["long_ratio"],
            "short_ratio": flow["short_ratio"],
            "net": flow["net"],
            "net_ratio": flow["net_ratio"],
            "demand": demand,
            "supply": supply,
            "btc": btc,
            "change24": change24,
            "tp1": tp1,
            "tp2": tp2,
            "sl": sl
        }

    except Exception as e:

        print(
            f"{symbol} analiz hatası: {e}"
        )

        return None


# ============================================================
# PARA FORMAT
# ============================================================

def money(
    value
):

    value = abs(
        float(value)
    )

    if value >= 1_000_000:

        return (
            f"{value / 1_000_000:.2f}M"
        )

    if value >= 1_000:

        return (
            f"{value / 1_000:.1f}K"
        )

    return f"{value:.0f}"


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(
    signal
):

    if (
        not BOT_TOKEN
        or not CHAT_ID
    ):

        print(
            "⚠️ BOT_TOKEN veya CHAT_ID eksik."
        )

        return False

    direction = signal[
        "direction"
    ]

    emoji = (
        "🟢"
        if direction == "LONG"
        else "🔴"
    )

    text = (
        f"🚨 <b>MEXC RADAR</b>\n\n"

        f"🪙 <b>{signal['symbol']}</b>\n"

        f"{emoji} Yön: "
        f"<b>{direction}</b>\n"

        f"⭐ Skor: "
        f"<b>{signal['score']:.0f}/100</b>\n\n"

        f"💰 Fiyat: "
        f"<code>{signal['price']:.8g}</code>\n"

        f"💵 Open Flow: "
        f"<b>{money(signal['total_open'])} USDT</b>\n"

        f"🟢 Long Open: "
        f"{signal['long_ratio']:.1f}%\n"

        f"🔴 Short Open: "
        f"{signal['short_ratio']:.1f}%\n"

        f"📊 Net Flow: "
        f"<b>{money(signal['net'])} USDT</b>\n\n"

        f"📈 Volume: "
        f"<b>{signal['volume_ratio']:.2f}x</b>\n"

        f"RSI 15M: "
        f"{signal['rsi15']:.1f}\n"

        f"RSI 1H: "
        f"{signal['rsi1h']:.1f}\n"

        f"RSI 4H: "
        f"{signal['rsi4h']:.1f}\n\n"

        f"📍 Demand: "
        f"{'✅' if signal['demand'] else '❌'}\n"

        f"📍 Supply: "
        f"{'✅' if signal['supply'] else '❌'}\n"

        f"₿ BTC: "
        f"<b>{signal['btc']}</b>\n\n"

        f"🎯 TP1: "
        f"<code>{signal['tp1']:.8g}</code>\n"

        f"🎯 TP2: "
        f"<code>{signal['tp2']:.8g}</code>\n"

        f"🛑 SL: "
        f"<code>{signal['sl']:.8g}</code>\n\n"

        f"⚠️ Otomatik tarama sinyalidir."
    )

    url = (
        "https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    try:

        response = SESSION.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML"
            },
            timeout=15
        )

        if response.ok:

            print(
                f"✅ Telegram gönderildi: "
                f"{signal['symbol']}"
            )

            return True

        print(
            "❌ Telegram hata:",
            response.text[:500]
        )

        return False

    except Exception as e:

        print(
            "❌ Telegram bağlantı hatası:",
            e
        )

        return False


# ============================================================
# ANA
# ============================================================

def main():

    print()
    print("=" * 70)
    print("🚀 MEXC PRE-PUMP RADAR V3")
    print("=" * 70)

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    if (
        BOT_TOKEN
        and CHAT_ID
    ):

        print(
            "✅ Telegram hazır"
        )

    else:

        print(
            "⚠️ Telegram Secret eksik"
        )

    # --------------------------------------------------------
    # CONTRACTS
    # --------------------------------------------------------

    contracts = get_contracts()

    print(
        f"✅ USDT Futures: "
        f"{len(contracts)}"
    )

    if not contracts:

        print(
            "❌ Futures alınamadı."
        )

        return

    # --------------------------------------------------------
    # TICKERS
    # --------------------------------------------------------

    print(
        "📡 Ticker verileri alınıyor..."
    )

    tickers = get_tickers()

    print(
        f"✅ Ticker: "
        f"{len(tickers)}"
    )

    if not tickers:

        print(
            "❌ Ticker alınamadı."
        )

        return

    # --------------------------------------------------------
    # ADAYLAR
    # --------------------------------------------------------

    candidates = []

    for symbol, ticker in tickers.items():

        if symbol not in contracts:
            continue

        if (
            ticker["volume24"]
            < MIN_24H_VOLUME
        ):
            continue

        candidates.append(
            (
                symbol,
                ticker
            )
        )

    candidates.sort(
        key=lambda item:
            item[1]["volume24"],
        reverse=True
    )

    candidates = candidates[
        :MAX_CANDIDATES
    ]

    print(
        f"🔎 Detaylı tarama: "
        f"{len(candidates)}"
    )

    # --------------------------------------------------------
    # BTC
    # --------------------------------------------------------

    print(
        "₿ BTC yönü hesaplanıyor..."
    )

    btc = get_btc_direction()

    print(
        f"₿ BTC: {btc}"
    )

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    state = load_state()

    # --------------------------------------------------------
    # ANALİZ
    # --------------------------------------------------------

    results = []

    print(
        "🔍 Coinler analiz ediliyor..."
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for symbol, ticker in candidates:

            if cooldown_active(
                symbol,
                state
            ):
                continue

            future = executor.submit(
                analyze_symbol,
                symbol,
                ticker,
                contracts[symbol]
            )

            futures[
                future
            ] = symbol

        for future in as_completed(
            futures
        ):

            symbol = futures[
                future
            ]

            try:

                result = future.result()

                if result:

                    results.append(
                        result
                    )

            except Exception as e:

                print(
                    f"{symbol} hata: {e}"
                )

    # --------------------------------------------------------
    # SIRALAMA
    # --------------------------------------------------------

    results.sort(
        key=lambda x:
            x["score"],
        reverse=True
    )

    print()
    print("=" * 70)
    print(
        f"🔥 GÜÇLÜ SONUÇ: "
        f"{len(results)}"
    )
    print("=" * 70)

    # --------------------------------------------------------
    # SONUÇLAR
    # --------------------------------------------------------

    for result in results:

        print(
            f"{result['symbol']} | "
            f"{result['direction']} | "
            f"SCORE: "
            f"{result['score']:.0f} | "
            f"OPEN: "
            f"{money(result['total_open'])} | "
            f"LONG: "
            f"{result['long_ratio']:.1f}% | "
            f"SHORT: "
            f"{result['short_ratio']:.1f}% | "
            f"VOL: "
            f"{result['volume_ratio']:.2f}x | "
            f"RSI15: "
            f"{result['rsi15']:.1f}"
        )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    sent = 0

    # Aynı taramada maksimum 5 alarm
    for signal in results[:5]:

        if send_telegram(
            signal
        ):

            state[
                signal["symbol"]
            ] = time.time()

            sent += 1

    save_state(
        state
    )

    print()
    print(
        f"📨 Gönderilen alarm: "
        f"{sent}"
    )

    print(
        "✅ TARAMA TAMAMLANDI"
    )

    print("=" * 70)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "⛔ Durduruldu."
        )

    except Exception as e:

        print(
            "❌ ANA HATA:",
            e
        )
