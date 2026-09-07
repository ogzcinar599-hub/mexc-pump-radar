import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC CRYPTO FUTURES PUMP RADAR
#
# SADECE KRİPTO FUTURES
#
# 4H  = DIP + DÖNÜŞ
# 1H  = TREND
# 15M = MOMENTUM + HACİM
#
# STOCK / ETF / HİSSE FUTURES HARİÇ
# ============================================================


BASE = "https://api.mexc.com"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================
# AYARLAR
# ============================================================

MIN_SCORE = 72

STRONG_SCORE = 82

MIN_24H_VOLUME = 300000

MIN_24H_CHANGE = -15
MAX_24H_CHANGE = 12

MAX_SIGNALS_PER_SCAN = 3

DUPLICATE_HOURS = 6

TP1_PCT = 1.8
TP2_PCT = 3.5
TP3_PCT = 5.5
STOP_PCT = 2.2

MAX_WORKERS = 8

MAX_SYMBOLS_TO_SCAN = 180

# Güçlü alarm için minimum 15M hacim
STRONG_VOLUME_RATIO = 1.25


# ============================================================
# DOSYA
# ============================================================

SENT_FILE = "sent_signals.json"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 PumpRadar-CryptoFutures/3.0"
})


# ============================================================
# STOCK / HİSSE FUTURES
# ============================================================

# MEXC stock futures tarafında kullanılan bilinen semboller.
# Liste zamanla genişleyebileceği için ayrıca isim kontrolleri
# de yapıyoruz.

STOCK_BASES = {

    # Teknoloji
    "AAPL",
    "AMD",
    "NVDA",
    "INTC",
    "AVGO",
    "QCOM",
    "MU",
    "MSFT",
    "GOOGL",
    "GOOG",
    "AMZN",
    "META",
    "TSLA",

    # Finans
    "COIN",
    "HOOD",
    "JPM",
    "BAC",
    "C",
    "GS",
    "MS",

    # Tüketici
    "MCD",
    "NKE",
    "SBUX",
    "WMT",
    "COST",

    # Diğer büyük hisseler
    "NFLX",
    "DIS",
    "ORCL",
    "CRM",
    "UBER",
    "ABNB",
    "SHOP",
    "PLTR",
    "SNOW",
    "ROKU",

    # Yeni/çeşitli stock futures
    "AA",
    "APH",
    "STM",
    "ON",
    "ENTG",
    "JBL",
    "KKR",
    "VLO",
    "MPC",
    "DVN",
    "BKR",
    "TSEM",
    "ROK",
    "MSTU",
    "MUSTOCK",

    # Örnek diğer hisse ürünleri
    "CHYM",
    "MS"
}


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

    base = str(
        contract.get(
            "baseCoin",
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

    combined = (
        symbol
        + " "
        + base
        + " "
        + display
        + " "
        + display2
    )

    # --------------------------------------------------------
    # Direkt bilinen stock base
    # --------------------------------------------------------

    if base in STOCK_BASES:

        return True

    # --------------------------------------------------------
    # Stock kelimeleri
    # --------------------------------------------------------

    stock_words = [

        "STOCK",
        "EQUITY",
        "SHARE",
        "US STOCK"
    ]

    for word in stock_words:

        if word in combined:

            return True

    # --------------------------------------------------------
    # Bilinen hisse sembolü + USDT
    # --------------------------------------------------------

    clean_symbol = (
        symbol
        .replace(
            "_USDT",
            ""
        )
        .replace(
            "USDT",
            ""
        )
    )

    if clean_symbol in STOCK_BASES:

        return True

    return False


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
            "sent okuma hatası:",
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
            "sent yazma hatası:",
            e
        )


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
            "Telegram HTTP:",
            response.status_code
        )

        if response.status_code == 200:

            print(
                "✅ Telegram mesajı gönderildi"
            )

            return True

        print(
            "❌ Telegram:",
            response.text[:500]
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
        "✅ GitHub Actions çalışıyor.\n"
        "✅ MEXC Futures bağlantısı çalışıyor.\n\n"

        "🚫 Stock Futures hariç\n"
        "🔎 4H dip + dönüş\n"
        "📈 1H trend\n"
        "⚡ 15M momentum + hacim\n\n"

        "🎯 Crypto Futures taraması başladı."
    )

    return send_telegram(
        message
    )


# ============================================================
# JSON
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
                response.status_code
            )

            return None

        return response.json()

    except Exception as e:

        print(
            "GET hata:",
            e
        )

        return None


# ============================================================
# FUTURES SYMBOLS
# ============================================================

def get_futures_symbols():

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

    symbols = []

    stock_count = 0

    for contract in contracts:

        try:

            symbol = str(
                contract.get(
                    "symbol",
                    ""
                )
            ).upper()

            base = str(
                contract.get(
                    "baseCoin",
                    ""
                )
            ).upper()

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

            state = contract.get(
                "state",
                99
            )

            hidden = contract.get(
                "isHidden",
                False
            )

            # ------------------------------------------------
            # SADECE USDT-M
            # ------------------------------------------------

            if quote != "USDT":
                continue

            if settle != "USDT":
                continue

            if not symbol.endswith(
                "_USDT"
            ):
                continue

            # ------------------------------------------------
            # SADECE AKTİF
            # ------------------------------------------------

            if state != 0:
                continue

            if hidden:
                continue

            # ------------------------------------------------
            # STOCK KONTROL
            # ------------------------------------------------

            if is_stock_contract(
                contract
            ):

                stock_count += 1

                print(
                    "🚫 STOCK ATILDI:",
                    symbol,
                    base
                )

                continue

            symbols.append(
                symbol
            )

        except Exception:

            continue

    print("")
    print(
        "🪙 Crypto Futures:",
        len(symbols)
    )

    print(
        "🚫 Stock Futures elenen:",
        stock_count
    )

    return symbols


# ============================================================
# FUTURES TICKERS
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

    if isinstance(
        raw,
        dict
    ):

        raw = [raw]

    result = {}

    for x in raw:

        try:

            symbol = str(
                x.get(
                    "symbol",
                    ""
                )
            ).upper()

            if not symbol.endswith(
                "_USDT"
            ):

                continue

            price = float(
                x.get(
                    "lastPrice",
                    0
                )
            )

            volume24 = float(
                x.get(
                    "volume24",
                    0
                )
            )

            amount24 = float(
                x.get(
                    "amount24",
                    0
                )
            )

            rate = float(
                x.get(
                    "riseFallRate",
                    0
                )
            )

            change = (
                rate * 100
            )

            result[symbol] = {

                "price": price,

                "volume": volume24,

                "amount": amount24,

                "change": change,

                "funding": float(
                    x.get(
                        "fundingRate",
                        0
                    )
                )
            }

        except Exception:

            continue

    print(
        "Futures ticker:",
        len(result)
    )

    return result


# ============================================================
# KLINES
# ============================================================

def get_klines(
    symbol,
    interval
):

    try:

        url = (
            f"{BASE}/api/v1/contract/"
            f"kline/{symbol}"
        )

        response = session.get(
            url,
            params={
                "interval": interval
            },
            timeout=15
        )

        if response.status_code != 200:

            return []

        result = response.json()

        data = result.get(
            "data"
        )

        if not data:

            return []

        times = data.get(
            "time",
            []
        )

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

        n = min(
            len(times),
            len(opens),
            len(closes),
            len(highs),
            len(lows),
            len(volumes)
        )

        candles = []

        for i in range(n):

            try:

                candles.append({

                    "time": int(
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

                    "volume": float(
                        volumes[i]
                    )
                })

            except Exception:

                continue

        # Açık son mum kullanılmaz
        if len(candles) > 2:

            candles = candles[:-1]

        return candles

    except Exception as e:

        print(
            "Kline hata:",
            symbol,
            interval,
            e
        )

        return []


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
        2 / (period + 1)
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

            gains.append(change)
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
# 4H
# ============================================================

def analyze_4h(candles):

    if len(candles) < 60:

        return None

    closes = [
        x["close"]
        for x in candles
    ]

    current = closes[-1]

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

    # Son 20 kapalı mum
    recent = candles[-21:]

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

    # Çoktan pump olmuş coin
    if recovery > 12:

        return None

    score = 0

    # --------------------------------------------------------
    # DIP
    # --------------------------------------------------------

    if 1 <= recovery <= 4:

        score += 25

    elif 4 < recovery <= 7:

        score += 20

    elif 7 < recovery <= 10:

        score += 12

    elif recovery <= 12:

        score += 6

    # --------------------------------------------------------
    # EMA DÖNÜŞ
    # --------------------------------------------------------

    if ema20 > ema20_prev:

        score += 20

    # --------------------------------------------------------
    # EMA UZAKLIĞI
    # --------------------------------------------------------

    ema_distance = (
        (
            current
            - ema20
        )
        / ema20
    ) * 100

    if -1.5 <= ema_distance <= 3:

        score += 15

    elif -3 <= ema_distance < -1.5:

        score += 10

    elif 3 < ema_distance <= 6:

        score += 8

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 38 <= rsi_now <= 52:

        score += 20

    elif 52 < rsi_now <= 58:

        score += 15

    elif 34 <= rsi_now < 38:

        score += 10

    elif 58 < rsi_now <= 62:

        score += 8

    # --------------------------------------------------------
    # SON MUM
    # --------------------------------------------------------

    last = candles[-1]

    if last["close"] > last["open"]:

        score += 10

    candle_range = (
        last["high"]
        - last["low"]
    )

    body = abs(
        last["close"]
        - last["open"]
    )

    if candle_range > 0:

        body_ratio = (
            body
            / candle_range
        )

    else:

        body_ratio = 0

    if body_ratio >= 0.60:

        score += 10

    elif body_ratio >= 0.35:

        score += 5

    # EMA50 bonus
    if current > ema50:

        score += 5

    return {

        "score": min(
            score,
            100
        ),

        "current": current,

        "rsi": rsi_now,

        "recovery": recovery,

        "ema20": ema20,

        "ema50": ema50,

        "ema_distance": ema_distance
    }


# ============================================================
# 1H
# ============================================================

def analyze_1h(candles):

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

    if current >= ema20:

        score += 30

    elif current >= ema20 * 0.997:

        score += 20

    elif current >= ema20 * 0.99:

        score += 10

    if ema20 > ema20_prev:

        score += 25

    elif ema20 >= ema20_prev * 0.999:

        score += 10

    if current > ema50:

        score += 20

    elif current >= ema50 * 0.995:

        score += 10

    if 48 <= rsi_now <= 65:

        score += 20

    elif 42 <= rsi_now < 48:

        score += 12

    elif 65 < rsi_now <= 70:

        score += 10

    if current > previous:

        score += 5

    return {

        "score": min(
            score,
            100
        ),

        "rsi": rsi_now,

        "ema20": ema20,

        "ema50": ema50
    }


# ============================================================
# 15M
# ============================================================

def analyze_15m(candles):

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

    rsi_now = rsi(
        closes,
        14
    )

    if not ema20 or not rsi_now:

        return None

    score = 0

    # EMA
    if current > ema20:

        score += 25

    elif current >= ema20 * 0.997:

        score += 15

    # RSI
    if 50 <= rsi_now <= 68:

        score += 25

    elif 45 <= rsi_now < 50:

        score += 15

    elif 68 < rsi_now <= 72:

        score += 10

    # Son mum
    if current > previous:

        score += 15

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    recent_volumes = [
        x["volume"]
        for x in candles[-21:-1]
    ]

    if recent_volumes:

        avg_volume = (
            sum(
                recent_volumes
            )
            / len(
                recent_volumes
            )
        )

        current_volume = (
            candles[-1]["volume"]
        )

        if avg_volume > 0:

            volume_ratio = (
                current_volume
                / avg_volume
            )

        else:

            volume_ratio = 0

    else:

        volume_ratio = 0

    # --------------------------------------------------------
    # HACİM PUANI
    # --------------------------------------------------------

    if volume_ratio >= 2.0:

        score += 35

    elif volume_ratio >= 1.5:

        score += 28

    elif volume_ratio >= 1.25:

        score += 20

    elif volume_ratio >= 1.10:

        score += 10

    return {

        "score": min(
            score,
            100
        ),

        "rsi": rsi_now,

        "ema20": ema20,

        "volume_ratio": volume_ratio
    }


# ============================================================
# COIN ANALİZİ
# ============================================================

def analyze_symbol(
    symbol,
    ticker
):

    try:

        price = ticker.get(
            "price",
            0
        )

        change = ticker.get(
            "change",
            0
        )

        volume = ticker.get(
            "amount",
            0
        )

        if price <= 0:

            return None

        if volume < MIN_24H_VOLUME:

            return None

        if change < MIN_24H_CHANGE:

            return None

        if change > MAX_24H_CHANGE:

            return None

        # ----------------------------------------------------
        # 4H
        # ----------------------------------------------------

        candles4 = get_klines(
            symbol,
            "Hour4"
        )

        if not candles4:

            return None

        four = analyze_4h(
            candles4
        )

        if not four:

            return None

        # ----------------------------------------------------
        # 1H
        # ----------------------------------------------------

        candles1 = get_klines(
            symbol,
            "Min60"
        )

        if not candles1:

            return None

        one = analyze_1h(
            candles1
        )

        if not one:

            return None

        # ----------------------------------------------------
        # 15M
        # ----------------------------------------------------

        candles15 = get_klines(
            symbol,
            "Min15"
        )

        if not candles15:

            return None

        fifteen = analyze_15m(
            candles15
        )

        if not fifteen:

            return None

        # ----------------------------------------------------
        # AĞIRLIK
        #
        # 4H 50%
        # 1H 30%
        # 15M 20%
        # ----------------------------------------------------

        score = (

            four["score"] * 0.50

            +

            one["score"] * 0.30

            +

            fifteen["score"] * 0.20
        )

        score = round(
            score
        )

        # ----------------------------------------------------
        # ÇOK ÖNEMLİ:
        # 15M HACİM ÇOK ZAYIFSA
        # GÜÇLÜ ALARM DEĞİL
        # ----------------------------------------------------

        volume_ratio = (
            fifteen[
                "volume_ratio"
            ]
        )

        # ----------------------------------------------------
        # 72 altı = alma
        # ----------------------------------------------------

        if score < MIN_SCORE:

            return None

        # ----------------------------------------------------
        # GÜÇLÜ SINIF
        # ----------------------------------------------------

        if (
            score >= STRONG_SCORE
            and
            volume_ratio >=
            STRONG_VOLUME_RATIO
        ):

            signal_type = (
                "🔥 GÜÇLÜ"
            )

        else:

            signal_type = (
                "🟡 ERKEN"
            )

        # ----------------------------------------------------
        # Giriş
        # ----------------------------------------------------

        entry = price

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

        return {

            "symbol": symbol,

            "score": score,

            "signal_type": signal_type,

            "entry": entry,

            "tp1": tp1,

            "tp2": tp2,

            "tp3": tp3,

            "stop": stop,

            "change": change,

            "recovery": four[
                "recovery"
            ],

            "rsi4h": four[
                "rsi"
            ],

            "rsi1h": one[
                "rsi"
            ],

            "rsi15m": fifteen[
                "rsi"
            ],

            "score4h": four[
                "score"
            ],

            "score1h": one[
                "score"
            ],

            "score15m": fifteen[
                "score"
            ],

            "volume_ratio":
                volume_ratio,

            "funding":
                ticker.get(
                    "funding",
                    0
                )
        }

    except Exception as e:

        print(
            symbol,
            "analiz hata:",
            e
        )

        return None


# ============================================================
# FİYAT
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
# SIGNAL MESAJ
# ============================================================

def format_signal(x):

    if (
        x["signal_type"]
        == "🔥 GÜÇLÜ"
    ):

        title = (
            "🔥 <b>GÜÇLÜ PUMP ADAYI</b>"
        )

    else:

        title = (
            "🟡 <b>ERKEN PUMP ADAYI</b>"
        )

    return (

        f"{title}\n\n"

        f"🪙 <b>{x['symbol']}</b>\n"

        f"⭐ <b>Skor: "
        f"{x['score']}/100</b>\n\n"

        f"🟢 <b>Giriş:</b> "
        f"{price_format(x['entry'])}\n"

        f"🎯 <b>TP1:</b> "
        f"{price_format(x['tp1'])}\n"

        f"🎯 <b>TP2:</b> "
        f"{price_format(x['tp2'])}\n"

        f"🎯 <b>TP3:</b> "
        f"{price_format(x['tp3'])}\n"

        f"🛑 <b>Stop:</b> "
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

        f"📌 4H: "
        f"{x['score4h']}/100\n"

        f"📈 1H: "
        f"{x['score1h']}/100\n"

        f"⚡ 15M: "
        f"{x['score15m']}/100\n\n"

        "📡 <b>MEXC CRYPTO FUTURES</b>\n"

        "⚠️ <i>Analiz sinyalidir, "
        "otomatik işlem açmaz.</i>"
    )


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print("")
    print("=" * 70)
    print(
        "🚀 MEXC CRYPTO FUTURES "
        "PUMP RADAR"
    )
    print("=" * 70)

    # --------------------------------------------------------
    # FUTURES
    # --------------------------------------------------------

    symbols = get_futures_symbols()

    if not symbols:

        send_telegram(
            "🔴 <b>RADAR HATASI</b>\n\n"
            "Crypto Futures listesi alınamadı."
        )

        return

    # --------------------------------------------------------
    # TICKER
    # --------------------------------------------------------

    tickers = get_futures_tickers()

    if not tickers:

        send_telegram(
            "🔴 <b>RADAR HATASI</b>\n\n"
            "Futures ticker alınamadı."
        )

        return

    # --------------------------------------------------------
    # ÖN FİLTRE
    # --------------------------------------------------------

    filtered = []

    for symbol in symbols:

        ticker = tickers.get(
            symbol
        )

        if not ticker:

            continue

        price = ticker.get(
            "price",
            0
        )

        change = ticker.get(
            "change",
            0
        )

        volume = ticker.get(
            "amount",
            0
        )

        if price <= 0:

            continue

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

    # Hacme göre sırala
    filtered.sort(
        key=lambda x:
        x[1].get(
            "amount",
            0
        ),
        reverse=True
    )

    filtered = filtered[
        :MAX_SYMBOLS_TO_SCAN
    ]

    print("")
    print(
        "24H filtre sonrası:",
        len(filtered)
    )

    print(
        "Taranacak coin:",
        len(filtered)
    )

    if not filtered:

        print(
            "❌ Uygun coin yok."
        )

        return

    # --------------------------------------------------------
    # PARALEL
    # --------------------------------------------------------

    candidates = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for symbol, ticker in filtered:

            future = executor.submit(
                analyze_symbol,
                symbol,
                ticker
            )

            futures[
                future
            ] = symbol

        completed = 0

        total = len(
            futures
        )

        for future in as_completed(
            futures
        ):

            symbol = futures[
                future
            ]

            completed += 1

            try:

                result = future.result()

                if result:

                    candidates.append(
                        result
                    )

                    print(
                        "🔥 ADAY:",
                        symbol,
                        "|",
                        result["score"],
                        "| 4H",
                        result["score4h"],
                        "| 1H",
                        result["score1h"],
                        "| 15M",
                        result["score15m"],
                        "| VOL",
                        f"{result['volume_ratio']:.2f}x"
                    )

            except Exception as e:

                print(
                    "Future hata:",
                    symbol,
                    e
                )

            if (
                completed % 25
                == 0
            ):

                print(
                    "İlerleme:",
                    completed,
                    "/",
                    total
                )

    # --------------------------------------------------------
    # SIRALA
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x:
        (
            x["signal_type"]
            == "🔥 GÜÇLÜ",
            x["score"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    print("")
    print(
        "🎯 ADAY SAYISI:",
        len(candidates)
    )

    # --------------------------------------------------------
    # EN İYİLER
    # --------------------------------------------------------

    for x in candidates[:10]:

        print(
            x["symbol"],
            "|",
            x["signal_type"],
            "|",
            x["score"],
            "| 15M",
            f"{x['volume_ratio']:.2f}x"
        )

    if not candidates:

        print(
            "Bu taramada sinyal yok."
        )

        return

    # --------------------------------------------------------
    # DUPLICATE
    # --------------------------------------------------------

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

            pass

    sent = clean

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    sent_count = 0

    # Önce güçlüler
    strong = [

        x for x in candidates

        if (
            x["signal_type"]
            == "🔥 GÜÇLÜ"
        )
    ]

    early = [

        x for x in candidates

        if (
            x["signal_type"]
            != "🔥 GÜÇLÜ"
        )
    ]

    ordered = (
        strong
        + early
    )

    for candidate in ordered:

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
                "⏭ DUPLICATE:",
                symbol
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

    print("")
    print(
        "📨 Gönderilen:",
        sent_count
    )

    print("=" * 70)


# ============================================================
# PROGRAM
# ============================================================

if __name__ == "__main__":

    print("")
    print(
        "🚀 CRYPTO FUTURES "
        "PUMP RADAR BAŞLIYOR"
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

    if (
        BOT_TOKEN
        and CHAT_ID
    ):

        telegram_test()

    else:

        print(
            "❌ Telegram secretları eksik."
        )

    try:

        scan()

    except Exception as e:

        print(
            "🔴 ANA HATA:",
            e
        )

        send_telegram(
            "🔴 <b>RADAR ANA HATA</b>\n\n"
            f"<code>{str(e)[:500]}</code>"
        )

    print("")
    print(
        "🏁 Radar tamamlandı."
    )
