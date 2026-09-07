import os
import json
import time
import requests

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# MEXC CRYPTO FUTURES PUMP RADAR
#
# SADECE FUTURES
#
# 4H  = DIP + DÖNÜŞ
# 1H  = TREND
# 15M = MOMENTUM + HACİM
#
# Stock / ETF / Index / Stablecoin filtreli
# ============================================================


# ============================================================
# MEXC FUTURES API
# ============================================================

BASE = "https://api.mexc.com"


# ============================================================
# TELEGRAM
# ============================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ============================================================
# AYARLAR
# ============================================================

# Güçlü aday için minimum skor
MIN_SCORE = 80

# 24H minimum USDT hacmi
MIN_24H_VOLUME = 300000

# 24H değişim
MIN_24H_CHANGE = -15
MAX_24H_CHANGE = 12

# Maksimum sinyal
MAX_SIGNALS_PER_SCAN = 3

# Aynı coin kaç saat tekrar gelmesin
DUPLICATE_HOURS = 6

# TP / STOP
TP1_PCT = 1.8
TP2_PCT = 3.5
TP3_PCT = 5.5
STOP_PCT = 2.2

# Paralel istek
MAX_WORKERS = 10


# ============================================================
# DOSYA
# ============================================================

SENT_FILE = "sent_signals.json"


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0 MEXC-Crypto-Futures-PumpRadar/2.0"
})


# ============================================================
# GENEL JSON
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
                "HTTP HATA:",
                response.status_code,
                url
            )

            return None

        data = response.json()

        return data

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

        print("❌ TELEGRAM_BOT_TOKEN eksik")

        return False

    if not CHAT_ID:

        print("❌ TELEGRAM_CHAT_ID eksik")

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

        if response.status_code == 200:

            print("✅ Telegram gönderildi")

            return True

        print(
            "❌ Telegram:",
            response.status_code,
            response.text[:300]
        )

    except Exception as e:

        print(
            "❌ Telegram bağlantı hatası:",
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
        "🚫 Stock / ETF / Index hariç\n"
        "💎 Sadece Crypto Futures\n\n"
        "🔎 4H dip + dönüş\n"
        "📈 1H trend\n"
        "⚡ 15M momentum + hacim\n\n"
        "🚀 Radar taramaya başladı."
    )

    return send_telegram(message)


# ============================================================
# SENT SIGNALS
# ============================================================

def load_sent():

    try:

        if not os.path.exists(SENT_FILE):

            return {}

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
# STABLECOIN / STOCK FİLTRESİ
# ============================================================

BAD_BASES = {

    "USDT",
    "USDC",
    "USD1",
    "FDUSD",
    "TUSD",
    "USDE",
    "DAI",
    "USDD",
    "PYUSD",
    "USDP",
    "BUSD",

}


BAD_WORDS = {

    "STOCK",
    "STOCKS",
    "ETF",
    "INDEX",
    "INDEXES",
    "INDEXED",
    "FUND",
    "SHARE",
    "SHARES",
    "EQUITY",
    "EQUITIES",
    "NASDAQ",
    "SP500",
    "SPX",
    "DOW",
    "TESLA",
    "APPLE",
    "AMAZON",
    "META",
    "NVIDIA",
    "MICROSOFT",
    "GOOGLE",
    "COINBASE",
    "MSTR"

}


def is_crypto_futures(symbol, contract=None):

    if not symbol:

        return False

    symbol = symbol.upper()

    # --------------------------------------------------------
    # Futures sembolü olmalı
    # Örnek:
    # BTC_USDT
    # ETH_USDT
    # IMX_USDT
    # --------------------------------------------------------

    if not symbol.endswith("_USDT"):

        return False

    # --------------------------------------------------------
    # Stock / ETF / Index
    # --------------------------------------------------------

    for bad in BAD_WORDS:

        if bad in symbol:

            return False

    # --------------------------------------------------------
    # Base coin
    # --------------------------------------------------------

    base = symbol.replace("_USDT", "")

    if base in BAD_BASES:

        return False

    # --------------------------------------------------------
    # Contract bilgisi varsa kontrol
    # --------------------------------------------------------

    if contract:

        quote_coin = str(
            contract.get(
                "quoteCoin",
                "USDT"
            )
        ).upper()

        settle_coin = str(
            contract.get(
                "settleCoin",
                "USDT"
            )
        ).upper()

        if quote_coin != "USDT":

            return False

        if settle_coin != "USDT":

            return False

        state = contract.get(
            "state"
        )

        if state is not None:

            try:

                if int(state) != 0:

                    return False

            except Exception:

                pass

    return True


# ============================================================
# FUTURES CONTRACTS
# ============================================================

def get_futures_contracts():

    url = (
        f"{BASE}/api/v1/contract/detail"
    )

    data = get_json(url)

    if not data:

        return {}

    contracts = data.get(
        "data",
        []
    )

    if not isinstance(
        contracts,
        list
    ):

        return {}

    result = {}

    for contract in contracts:

        try:

            symbol = str(
                contract.get(
                    "symbol",
                    ""
                )
            ).upper()

            if not is_crypto_futures(
                symbol,
                contract
            ):

                continue

            result[symbol] = contract

        except Exception:

            continue

    print(
        "Crypto Futures:",
        len(result)
    )

    return result


# ============================================================
# FUTURES TICKER
# ============================================================

def get_futures_tickers():

    url = (
        f"{BASE}/api/v1/contract/ticker"
    )

    data = get_json(url)

    if not data:

        return {}

    ticker_data = data.get(
        "data",
        []
    )

    # Bazen tek obje gelebilir
    if isinstance(
        ticker_data,
        dict
    ):

        ticker_data = [
            ticker_data
        ]

    if not isinstance(
        ticker_data,
        list
    ):

        return {}

    result = {}

    for x in ticker_data:

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

            last_price = float(
                x.get(
                    "lastPrice",
                    0
                )
            )

            rise_fall = float(
                x.get(
                    "riseFallRate",
                    0
                )
            )

            volume24 = float(
                x.get(
                    "volume24",
                    0
                )
            )

            # riseFallRate bazı API
            # cevaplarında decimal olabilir.
            # Örn 0.025 = %2.5

            change = rise_fall * 100

            result[symbol] = {

                "price": last_price,

                "change": change,

                "volume": volume24

            }

        except Exception:

            continue

    print(
        "Ticker alınan Futures:",
        len(result)
    )

    return result


# ============================================================
# FUTURES KLINE
# ============================================================

def get_klines(
    symbol,
    interval,
    limit=100
):

    url = (
        f"{BASE}/api/v1/contract/kline/"
        f"{symbol}"
    )

    data = get_json(
        url,
        {
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

    candles = []

    # --------------------------------------------------------
    # MEXC Futures formatı:
    #
    # data:
    # {
    #   time: [],
    #   open: [],
    #   close: [],
    #   high: [],
    #   low: [],
    #   vol: []
    # }
    # --------------------------------------------------------

    if isinstance(
        raw,
        dict
    ):

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

        length = min(
            len(times),
            len(opens),
            len(closes),
            len(highs),
            len(lows),
            len(volumes)
        )

        start = max(
            0,
            length - limit
        )

        for i in range(
            start,
            length
        ):

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

    # --------------------------------------------------------
    # Alternatif liste formatı
    # --------------------------------------------------------

    elif isinstance(
        raw,
        list
    ):

        for x in raw[-limit:]:

            try:

                if isinstance(
                    x,
                    list
                ) and len(x) >= 6:

                    candles.append({

                        "time": int(
                            x[0]
                        ),

                        "open": float(
                            x[1]
                        ),

                        "close": float(
                            x[2]
                        ),

                        "high": float(
                            x[3]
                        ),

                        "low": float(
                            x[4]
                        ),

                        "volume": float(
                            x[5]
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
# ATR
# ============================================================

def atr(
    candles,
    period=14
):

    if len(candles) < (
        period + 1
    ):

        return None

    trs = []

    for i in range(
        1,
        len(candles)
    ):

        high = candles[i]["high"]
        low = candles[i]["low"]

        previous_close = (
            candles[i - 1]["close"]
        )

        tr = max(
            high - low,
            abs(
                high
                - previous_close
            ),
            abs(
                low
                - previous_close
            )
        )

        trs.append(tr)

    if len(trs) < period:

        return None

    return (
        sum(
            trs[-period:]
        )
        / period
    )


# ============================================================
# 4H DIP + DÖNÜŞ
# ============================================================

def analyze_4h(candles):

    if len(candles) < 70:

        return None

    # Son mum devam eden mum olabilir.
    # Onu analizden çıkarıyoruz.

    closed = candles[:-1]

    if len(closed) < 65:

        return None

    closes = [
        x["close"]
        for x in closed
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

    # --------------------------------------------------------
    # 12 TAMAMLANMIŞ MUMUN DİBİ
    # --------------------------------------------------------

    recent = closed[-13:-1]

    if len(recent) < 10:

        return None

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

    # Çok dipteyse henüz dönüş başlamamış
    if recovery < 1.0:

        return None

    # Fazla yükseldiyse erken pump değil
    if recovery > 11:

        return None

    # --------------------------------------------------------
    # SON 3 MUM
    # --------------------------------------------------------

    last3 = closed[-3:]

    green_count = sum(
        1
        for x in last3
        if x["close"] > x["open"]
    )

    if green_count < 2:

        return None

    # --------------------------------------------------------
    # EMA20 DÖNÜŞ
    # --------------------------------------------------------

    if ema20 <= ema20_prev:

        return None

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if rsi_now < 38:

        return None

    if rsi_now > 65:

        return None

    # --------------------------------------------------------
    # EMA MESAFE
    # --------------------------------------------------------

    ema_distance = (
        (
            current
            - ema20
        )
        / ema20
    ) * 100

    if ema_distance < -2.5:

        return None

    if ema_distance > 7:

        return None

    # --------------------------------------------------------
    # SCORE
    # Maksimum yaklaşık 45
    # --------------------------------------------------------

    score = 0

    # Dip dönüşü
    if 1 <= recovery <= 4:

        score += 18

    elif 4 < recovery <= 7:

        score += 14

    else:

        score += 8

    # EMA dönüş
    score += 10

    # EMA20 geri alma
    if current >= ema20:

        score += 8

    elif current >= ema20 * 0.997:

        score += 5

    # RSI
    if 42 <= rsi_now <= 58:

        score += 7

    elif 38 <= rsi_now < 42:

        score += 4

    elif 58 < rsi_now <= 65:

        score += 4

    # Yeşil mum
    if green_count == 3:

        score += 5

    elif green_count == 2:

        score += 3

    # Son mum pozitif
    if current > previous:

        score += 4

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
# 1H TREND
# ============================================================

def analyze_1h(candles):

    if len(candles) < 65:

        return None

    closed = candles[:-1]

    closes = [
        x["close"]
        for x in closed
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

    # EMA20
    if current >= ema20:

        score += 12

    elif current >= ema20 * 0.997:

        score += 8

    else:

        return None

    # EMA20 yukarı
    if ema20 > ema20_prev:

        score += 10

    else:

        return None

    # EMA50
    if current > ema50:

        score += 8

    # RSI
    if 48 <= rsi_now <= 65:

        score += 7

    elif 43 <= rsi_now < 48:

        score += 4

    else:

        return None

    # Son mum
    if current > previous:

        score += 5

    return {

        "score": score,

        "current": current,

        "ema20": ema20,

        "ema50": ema50,

        "rsi": rsi_now

    }


# ============================================================
# 15M MOMENTUM
# ============================================================

def analyze_15m(candles):

    if len(candles) < 50:

        return None

    closed = candles[:-1]

    closes = [
        x["close"]
        for x in closed
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

    # --------------------------------------------------------
    # EMA20
    # --------------------------------------------------------

    if current > ema20:

        score += 8

    elif current >= ema20 * 0.997:

        score += 4

    else:

        return None

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 50 <= rsi_now <= 68:

        score += 8

    elif 46 <= rsi_now < 50:

        score += 4

    else:

        return None

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if current > previous:

        score += 5

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    recent_volumes = [
        x["volume"]
        for x in closed[-21:-1]
    ]

    if len(recent_volumes) < 10:

        return None

    avg_volume = (
        sum(recent_volumes)
        / len(recent_volumes)
    )

    current_volume = (
        closed[-1]["volume"]
    )

    if avg_volume <= 0:

        return None

    volume_ratio = (
        current_volume
        / avg_volume
    )

    # --------------------------------------------------------
    # HACİM PUANI
    # --------------------------------------------------------

    if volume_ratio >= 3.0:

        score += 14

    elif volume_ratio >= 2.0:

        score += 11

    elif volume_ratio >= 1.5:

        score += 8

    elif volume_ratio >= 1.25:

        score += 4

    # --------------------------------------------------------
    # HACİM ÇOK DÜŞÜKSE
    # --------------------------------------------------------

    if volume_ratio < 0.85:

        return None

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
    symbol,
    ticker
):

    try:

        change = ticker.get(
            "change",
            0
        )

        volume = ticker.get(
            "volume",
            0
        )

        price = ticker.get(
            "price",
            0
        )

        # ----------------------------------------------------
        # 24H FİLTRE
        # ----------------------------------------------------

        if volume < MIN_24H_VOLUME:

            return None

        if change < MIN_24H_CHANGE:

            return None

        if change > MAX_24H_CHANGE:

            return None

        if price <= 0:

            return None

        # ----------------------------------------------------
        # 4H
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 1H
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 15M
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # TOPLAM SKOR
        # ----------------------------------------------------

        score = (
            four["score"]
            + one["score"]
            + fifteen["score"]
            + 10
        )

        # ----------------------------------------------------
        # MINIMUM
        # ----------------------------------------------------

        if score < MIN_SCORE:

            return None

        # ----------------------------------------------------
        # GİRİŞ
        # ----------------------------------------------------

        entry = price

        # ----------------------------------------------------
        # TP
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # STOP
        # ----------------------------------------------------

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

            "entry": entry,

            "tp1": tp1,

            "tp2": tp2,

            "tp3": tp3,

            "stop": stop,

            "change": change,

            "volume": volume,

            "recovery": four["recovery"],

            "rsi4h": four["rsi"],

            "rsi1h": one["rsi"],

            "rsi15m": fifteen["rsi"],

            "volume_ratio": fifteen["volume_ratio"]

        }

    except Exception as e:

        print(
            symbol,
            "analiz hatası:",
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
# TELEGRAM SIGNAL
# ============================================================

def format_signal(x):

    if x["score"] >= 90:

        title = "🔥 ÇOK GÜÇLÜ PUMP ADAYI"

    elif x["score"] >= 85:

        title = "🟢 GÜÇLÜ PUMP ADAYI"

    else:

        title = "🟡 ERKEN PUMP ADAYI"

    return (

        f"{title}\n\n"

        f"💎 <b>{x['symbol']}</b>\n"
        f"⭐ <b>Skor: {x['score']}/100</b>\n\n"

        f"🟢 Giriş: "
        f"<b>{price_format(x['entry'])}</b>\n"

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

        "📌 4H DİP + DÖNÜŞ\n"
        "📈 1H TREND TEYİDİ\n"
        "⚡ 15M MOMENTUM + HACİM\n\n"

        "💎 <b>MEXC CRYPTO FUTURES</b>\n"
        "⚠️ <i>Analiz sinyalidir, otomatik işlem açmaz.</i>"

    )


# ============================================================
# ANA TARAMA
# ============================================================

def scan():

    print("")
    print("=" * 65)
    print("🚀 MEXC CRYPTO FUTURES PUMP RADAR")
    print("=" * 65)

    # --------------------------------------------------------
    # CONTRACTS
    # --------------------------------------------------------

    contracts = (
        get_futures_contracts()
    )

    if not contracts:

        print(
            "❌ Futures contract alınamadı."
        )

        send_telegram(
            "🔴 <b>PUMP RADAR HATASI</b>\n\n"
            "MEXC Futures contract listesi alınamadı."
        )

        return

    # --------------------------------------------------------
    # TICKERS
    # --------------------------------------------------------

    tickers = (
        get_futures_tickers()
    )

    if not tickers:

        print(
            "❌ Futures ticker alınamadı."
        )

        send_telegram(
            "🔴 <b>PUMP RADAR HATASI</b>\n\n"
            "MEXC Futures ticker verisi alınamadı."
        )

        return

    # --------------------------------------------------------
    # ÖN FİLTRE
    # --------------------------------------------------------

    filtered = []

    for symbol, contract in contracts.items():

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

        price = ticker.get(
            "price",
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

    print(
        "24H filtre sonrası:",
        len(filtered)
    )

    if not filtered:

        print(
            "❌ Ön filtreden coin geçmedi."
        )

        return

    # --------------------------------------------------------
    # PARALEL TARAMA
    # --------------------------------------------------------

    candidates = []

    total = len(filtered)

    completed = 0

    print(
        "🔎 Detaylı tarama:",
        total,
        "coin"
    )

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

            futures[future] = symbol

        for future in as_completed(
            futures
        ):

            symbol = futures[
                future
            ]

            completed += 1

            try:

                result = (
                    future.result()
                )

                if result:

                    candidates.append(
                        result
                    )

                    print(
                        "🔥 ADAY:",
                        symbol,
                        "|",
                        result["score"],
                        "/100",
                        "| 15M:",
                        f"{result['volume_ratio']:.2f}x"
                    )

            except Exception as e:

                print(
                    "Future hata:",
                    symbol,
                    e
                )

            if completed % 25 == 0:

                print(
                    "İlerleme:",
                    completed,
                    "/",
                    total
                )

    # --------------------------------------------------------
    # SKOR SIRALAMA
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    print("")
    print(
        "🔥 Güçlü aday:",
        len(candidates)
    )

    # --------------------------------------------------------
    # ADAY YOK
    # --------------------------------------------------------

    if not candidates:

        print(
            "Bu taramada güçlü sinyal yok."
        )

        return

    # --------------------------------------------------------
    # SENT
    # --------------------------------------------------------

    sent = load_sent()

    now = time.time()

    clean = {}

    for symbol, timestamp in sent.items():

        try:

            if (
                now
                - float(timestamp)
                < DUPLICATE_HOURS * 3600
            ):

                clean[
                    symbol
                ] = timestamp

        except Exception:

            continue

    sent = clean

    # --------------------------------------------------------
    # GÖNDER
    # --------------------------------------------------------

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
                "⏭ DUPLICATE:",
                symbol
            )

            continue

        message = format_signal(
            candidate
        )

        success = (
            send_telegram(
                message
            )
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
                symbol
            )

    print("")
    print(
        "📨 Gönderilen:",
        sent_count
    )

    print("=" * 65)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print("")
    print(
        "🚀 MEXC CRYPTO FUTURES RADAR"
    )
    print("")

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

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

    else:

        print(
            "❌ Telegram secretları eksik."
        )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    try:

        scan()

    except Exception as e:

        print(
            "🔴 ANA HATA:",
            repr(e)
        )

        if BOT_TOKEN and CHAT_ID:

            send_telegram(
                "🔴 <b>PUMP RADAR ANA HATA</b>\n\n"
                f"<code>{str(e)[:500]}</code>"
            )

    print("")
    print(
        "🏁 Radar tamamlandı."
    )
