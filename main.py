import os
import json
import time
import math
import gzip
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import websocket


# ============================================================
# 🚀 MEXC PRE-PUMP RADAR V2
#
# SADECE:
# ✅ MEXC USDT FUTURES
# ✅ 15M + 1H + 4H
# ✅ RSI
# ✅ HACİM
# ✅ MOMENTUM
# ✅ OPEN FLOW
# ✅ BTC YÖNÜ
# ✅ DEMAND / SUPPLY
# ✅ TP / SL
# ✅ TELEGRAM
# ✅ DUPLICATE / COOLDOWN
#
# TEK TARAMA YAPAR VE ÇIKAR
# ============================================================


# ============================================================
# AYARLAR
# ============================================================

REST_URL = "https://api.mexc.com"
WS_URL = "wss://contract.mexc.com/edge"

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()

MAX_CANDIDATES = 50
MAX_WORKERS = 5

DEALS_LIMIT = 100

MIN_24H_VOLUME = 50000
MIN_VOLUME_RATIO = 1.15

MIN_OPEN_NOTIONAL = 15000
MIN_NET_RATIO = 5.0

MIN_SCORE = 70

COOLDOWN_HOURS = 4

STATE_FILE = "sent_signals.json"

WS_WAIT_SECONDS = 8

REQUEST_TIMEOUT = 15

# TP / SL
TP1_LONG = 1.03
TP2_LONG = 1.06
SL_LONG = 0.975

TP1_SHORT = 0.97
TP2_SHORT = 0.94
SL_SHORT = 1.025


# ============================================================
# HİSSE / TOKENIZED STOCK FİLTRESİ
# ============================================================

STOCK_FILTER = {
    "AAPL",
    "AMZN",
    "GOOGL",
    "GOOG",
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
    "QQQ",
    "SPY",
    "IWM",
}


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "MEXC-PrePump-Radar/2.0"
})


# ============================================================
# REQUEST RATE LIMIT
# ============================================================

REQUEST_LOCK = threading.Lock()
LAST_REQUEST = 0.0

REQUEST_INTERVAL = 0.12


def rate_limit():
    global LAST_REQUEST

    with REQUEST_LOCK:
        now = time.time()
        wait = REQUEST_INTERVAL - (now - LAST_REQUEST)

        if wait > 0:
            time.sleep(wait)

        LAST_REQUEST = time.time()


# ============================================================
# HTTP GET
# ============================================================

def http_get(path, params=None, retries=3):

    url = REST_URL + path

    for attempt in range(retries):

        try:

            rate_limit()

            response = SESSION.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 429:

                time.sleep(2 + attempt * 2)
                continue

            response.raise_for_status()

            data = response.json()

            return data

        except Exception as e:

            if attempt == retries - 1:
                return None

            time.sleep(1 + attempt)


    return None


# ============================================================
# CONTRACT DETAILS
# ============================================================

def get_contracts():

    data = http_get("/api/v1/contract/detail")

    if not data:
        return {}

    rows = data.get("data", [])

    result = {}

    for item in rows:

        try:

            symbol = item.get("symbol", "")

            if not symbol.endswith("_USDT"):
                continue

            if item.get("state") != 0:
                continue

            base = symbol.replace("_USDT", "").upper()

            if base in STOCK_FILTER:
                continue

            contract_size = float(
                item.get("contractSize", 0)
            )

            if contract_size <= 0:
                continue

            result[symbol] = {
                "contract_size": contract_size,
                "base": base
            }

        except Exception:
            continue

    return result


# ============================================================
# WEBSOCKET TÜM TICKERLAR
# ============================================================

def get_all_tickers_ws():

    tickers = {}

    ws = None

    try:

        ws = websocket.create_connection(
            WS_URL,
            timeout=5
        )

        subscribe = {
            "method": "sub.tickers",
            "param": {}
        }

        ws.send(json.dumps(subscribe))

        start = time.time()

        while time.time() - start < WS_WAIT_SECONDS:

            try:

                message = ws.recv()

                if not message:
                    continue

                if isinstance(message, bytes):

                    try:
                        message = gzip.decompress(
                            message
                        ).decode("utf-8")

                    except Exception:

                        message = message.decode(
                            "utf-8",
                            errors="ignore"
                        )

                data = json.loads(message)

                channel = data.get("channel", "")

                if channel != "push.tickers":
                    continue

                rows = data.get("data", [])

                if not isinstance(rows, list):
                    continue

                for row in rows:

                    symbol = row.get("symbol", "")

                    if not symbol.endswith("_USDT"):
                        continue

                    try:

                        price = float(
                            row.get("lastPrice", 0)
                        )

                        volume24 = float(
                            row.get("volume24", 0)
                        )

                        change = float(
                            row.get("riseFallRate", 0)
                        ) * 100

                        if price <= 0:
                            continue

                        tickers[symbol] = {
                            "price": price,
                            "volume24": volume24,
                            "change24": change
                        }

                    except Exception:
                        continue

            except Exception:
                continue

    except Exception as e:

        print("WS HATA:", e)

    finally:

        try:
            if ws:
                ws.close()
        except Exception:
            pass

    return tickers


# ============================================================
# KLINE
# ============================================================

def get_kline(symbol, interval, limit=50):

    data = http_get(
        f"/api/v1/contract/kline/{symbol}",
        params={
            "interval": interval
        }
    )

    if not data:
        return []

    raw = data.get("data")

    if not raw:
        return []

    try:

        times = raw.get("time", [])
        opens = raw.get("open", [])
        closes = raw.get("close", [])
        highs = raw.get("high", [])
        lows = raw.get("low", [])
        vols = raw.get("vol", [])

        rows = []

        length = min(
            len(times),
            len(opens),
            len(closes),
            len(highs),
            len(lows),
            len(vols)
        )

        for i in range(length):

            rows.append({
                "time": float(times[i]),
                "open": float(opens[i]),
                "close": float(closes[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "vol": float(vols[i])
            })

        if len(rows) > limit:
            rows = rows[-limit:]

        return rows

    except Exception:

        return []


# ============================================================
# RSI
# ============================================================

def calculate_rsi(closes, period=14):

    if len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):

        diff = closes[i] - closes[i - 1]

        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(
        gains[:period]
    ) / period

    avg_loss = sum(
        losses[:period]
    ) / period

    for i in range(period, len(gains)):

        avg_gain = (
            (avg_gain * (period - 1))
            + gains[i]
        ) / period

        avg_loss = (
            (avg_loss * (period - 1))
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(candles):

    if len(candles) < 25:
        return 0

    current = candles[-1]["vol"]

    previous = [
        x["vol"]
        for x in candles[-21:-1]
    ]

    avg = sum(previous) / len(previous)

    if avg <= 0:
        return 0

    return current / avg


# ============================================================
# MOMENTUM
# ============================================================

def momentum(candles, bars=4):

    if len(candles) <= bars:
        return 0

    old = candles[-bars - 1]["close"]
    new = candles[-1]["close"]

    if old == 0:
        return 0

    return ((new / old) - 1) * 100


# ============================================================
# DEMAND / SUPPLY
# ============================================================

def demand_supply(candles, price):

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

    demand_low = min(lows)
    supply_high = max(highs)

    demand_distance = (
        (price - demand_low)
        / price
    ) * 100

    supply_distance = (
        (supply_high - price)
        / price
    ) * 100

    demand = (
        0 <= demand_distance <= 2.0
    )

    supply = (
        0 <= supply_distance <= 2.0
    )

    return demand, supply


# ============================================================
# BTC YÖNÜ
# ============================================================

def get_btc_direction():

    results = []

    for interval in [
        "Min15",
        "Min60",
        "Hour4"
    ]:

        candles = get_kline(
            "BTC_USDT",
            interval,
            30
        )

        if len(candles) < 10:
            continue

        old = candles[-6]["close"]
        new = candles[-1]["close"]

        if old == 0:
            continue

        change = (
            (new / old) - 1
        ) * 100

        results.append(change)

    if len(results) < 2:
        return "NEUTRAL"

    positive = sum(
        1 for x in results
        if x > 0
    )

    negative = sum(
        1 for x in results
        if x < 0
    )

    if positive >= 2:
        return "BULLISH"

    if negative >= 2:
        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# OPEN FLOW
# ============================================================

def get_open_flow(symbol, contract_size):

    data = http_get(
        f"/api/v1/contract/deals/{symbol}",
        params={
            "limit": DEALS_LIMIT
        }
    )

    if not data:
        return None

    rows = data.get("data", [])

    if not rows:
        return None

    long_open = 0.0
    short_open = 0.0

    total_open = 0.0

    for trade in rows:

        try:

            price = float(
                trade.get("p", 0)
            )

            volume = float(
                trade.get("v", 0)
            )

            trade_type = int(
                trade.get("T", 0)
            )

            open_flag = int(
                trade.get("O", 0)
            )

            if price <= 0 or volume <= 0:
                continue

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
        long_open / total_open
    ) * 100

    short_ratio = (
        short_open / total_open
    ) * 100

    net = long_open - short_open

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
# COOLDOWN
# ============================================================

def load_state():

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return {}


def save_state(state):

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                state,
                f,
                indent=2
            )

    except Exception as e:

        print("STATE SAVE HATA:", e)


def is_on_cooldown(symbol, state):

    value = state.get(symbol)

    if not value:
        return False

    try:

        last_time = float(value)

        age = (
            time.time()
            - last_time
        )

        return age < (
            COOLDOWN_HOURS * 3600
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

    price = ticker["price"]

    contract_size = contract["contract_size"]

    volume24 = ticker["volume24"]

    change24 = ticker["change24"]

    if volume24 < MIN_24H_VOLUME:
        return None

    # --------------------------------------------------------
    # KLINE
    # --------------------------------------------------------

    c15 = get_kline(
        symbol,
        "Min15",
        50
    )

    c1h = get_kline(
        symbol,
        "Min60",
        50
    )

    c4h = get_kline(
        symbol,
        "Hour4",
        50
    )

    if (
        len(c15) < 25
        or len(c1h) < 25
        or len(c4h) < 25
    ):
        return None

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    rsi15 = calculate_rsi(
        [x["close"] for x in c15]
    )

    rsi1h = calculate_rsi(
        [x["close"] for x in c1h]
    )

    rsi4h = calculate_rsi(
        [x["close"] for x in c4h]
    )

    if (
        rsi15 is None
        or rsi1h is None
        or rsi4h is None
    ):
        return None

    # --------------------------------------------------------
    # HACİM
    # --------------------------------------------------------

    vol_ratio = volume_ratio(c15)

    if vol_ratio < MIN_VOLUME_RATIO:
        return None

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    mom15 = momentum(
        c15,
        4
    )

    mom1h = momentum(
        c1h,
        4
    )

    # --------------------------------------------------------
    # DEMAND / SUPPLY
    # --------------------------------------------------------

    demand, supply = demand_supply(
        c15,
        price
    )

    # --------------------------------------------------------
    # OPEN FLOW
    # --------------------------------------------------------

    flow = get_open_flow(
        symbol,
        contract_size
    )

    if not flow:
        return None

    if flow["total_open"] < MIN_OPEN_NOTIONAL:
        return None

    # --------------------------------------------------------
    # LONG / SHORT SCORE
    # --------------------------------------------------------

    long_score = 0
    short_score = 0

    # RSI 4H
    if 48 <= rsi4h <= 68:
        long_score += 15

    if 32 <= rsi4h <= 52:
        short_score += 15

    # RSI 1H
    if 50 <= rsi1h <= 68:
        long_score += 10

    if 32 <= rsi1h <= 50:
        short_score += 10

    # RSI 15M
    if 50 <= rsi15 <= 72:
        long_score += 8

    if 28 <= rsi15 <= 50:
        short_score += 8

    # Volume
    if vol_ratio >= 1.25:
        long_score += 10
        short_score += 10

    if vol_ratio >= 1.50:
        long_score += 5
        short_score += 5

    # Momentum
    if mom15 > 0.30:
        long_score += 8

    if mom15 < -0.30:
        short_score += 8

    if mom1h > 0.50:
        long_score += 7

    if mom1h < -0.50:
        short_score += 7

    # Demand / Supply
    if demand:
        long_score += 10

    if supply:
        short_score += 10

    # Open flow
    if flow["long_ratio"] >= 55:
        long_score += 15

    if flow["short_ratio"] >= 55:
        short_score += 15

    # Net flow
    if flow["net"] > 0:
        long_score += 5

    if flow["net"] < 0:
        short_score += 5

    # --------------------------------------------------------
    # BTC
    # --------------------------------------------------------

    btc = get_btc_direction()

    if btc == "BULLISH":
        long_score += 10
        short_score -= 8

    elif btc == "BEARISH":
        short_score += 10
        long_score -= 8

    long_score = max(
        0,
        min(100, long_score)
    )

    short_score = max(
        0,
        min(100, short_score)
    )

    # --------------------------------------------------------
    # YÖN
    # --------------------------------------------------------

    if long_score >= short_score:

        direction = "LONG"
        score = long_score

        if (
            flow["long_ratio"]
            < 53
        ):
            return None

        if (
            flow["net_ratio"]
            < MIN_NET_RATIO
        ):
            return None

        if mom15 < -1.5:
            return None

        if change24 > 15:
            return None

    else:

        direction = "SHORT"
        score = short_score

        if (
            flow["short_ratio"]
            < 53
        ):
            return None

        if (
            flow["net_ratio"]
            < MIN_NET_RATIO
        ):
            return None

        if mom15 > 1.5:
            return None

        if change24 < -15:
            return None

    if score < MIN_SCORE:
        return None

    # --------------------------------------------------------
    # TP / SL
    # --------------------------------------------------------

    if direction == "LONG":

        tp1 = price * TP1_LONG
        tp2 = price * TP2_LONG
        sl = price * SL_LONG

    else:

        tp1 = price * TP1_SHORT
        tp2 = price * TP2_SHORT
        sl = price * SL_SHORT

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


# ============================================================
# PARA FORMAT
# ============================================================

def money(value):

    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"

    if value >= 1_000:
        return f"{value / 1_000:.1f}K"

    return f"{value:.0f}"


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(signal):

    if not BOT_TOKEN or not CHAT_ID:

        print("⚠️ BOT_TOKEN / CHAT_ID eksik.")

        return False

    symbol = signal["symbol"]
    direction = signal["direction"]

    text = (
        f"🚨 <b>MEXC RADAR</b>\n\n"

        f"🪙 <b>{symbol}</b>\n"
        f"📈 Yön: <b>{direction}</b>\n"
        f"⭐ Skor: <b>{signal['score']:.0f}/100</b>\n\n"

        f"💰 Fiyat: "
        f"<code>{signal['price']:.8g}</code>\n"

        f"💵 Open Flow: "
        f"<b>{money(signal['total_open'])} USDT</b>\n"

        f"🟢 Long Open: "
        f"{signal['long_ratio']:.1f}%\n"

        f"🔴 Short Open: "
        f"{signal['short_ratio']:.1f}%\n"

        f"📊 Net Flow: "
        f"<b>{money(abs(signal['net']))} USDT</b>\n\n"

        f"📊 Volume: "
        f"<b>{signal['volume_ratio']:.2f}x</b>\n"

        f"RSI 15M: {signal['rsi15']:.1f}\n"
        f"RSI 1H: {signal['rsi1h']:.1f}\n"
        f"RSI 4H: {signal['rsi4h']:.1f}\n\n"

        f"📍 Demand: "
        f"{'✅' if signal['demand'] else '❌'}\n"

        f"📍 Supply: "
        f"{'✅' if signal['supply'] else '❌'}\n"

        f"₿ BTC: "
        f"<b>{signal['btc']}</b>\n\n"

        f"🎯 TP1: <code>{signal['tp1']:.8g}</code>\n"
        f"🎯 TP2: <code>{signal['tp2']:.8g}</code>\n"
        f"🛑 SL: <code>{signal['sl']:.8g}</code>\n\n"

        f"⚠️ Bu bir otomatik piyasa tarama sinyalidir; "
        f"işlem garantisi değildir."
    )

    url = (
        f"https://api.telegram.org/"
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

            return True

        print(
            "Telegram hata:",
            response.text[:500]
        )

        return False

    except Exception as e:

        print(
            "Telegram bağlantı hatası:",
            e
        )

        return False


# ============================================================
# ANA TARAMA
# ============================================================

def main():

    print()
    print("=" * 65)
    print("🚀 MEXC PRE-PUMP RADAR V2")
    print("=" * 65)

    print(
        "Zaman:",
        datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    if BOT_TOKEN and CHAT_ID:
        print("✅ Telegram yapılandırıldı")
    else:
        print(
            "⚠️ Telegram Secret eksik"
        )

    # --------------------------------------------------------
    # CONTRACTS
    # --------------------------------------------------------

    print()
    print("📡 Futures sözleşmeleri alınıyor...")

    contracts = get_contracts()

    if not contracts:

        print(
            "❌ Futures listesi alınamadı."
        )

        return

    print(
        f"✅ Aktif USDT Futures: "
        f"{len(contracts)}"
    )

    # --------------------------------------------------------
    # TICKERS
    # --------------------------------------------------------

    print()
    print(
        "📡 WebSocket ticker taraması..."
    )

    tickers = get_all_tickers_ws()

    if not tickers:

        print(
            "❌ Ticker verisi alınamadı."
        )

        return

    print(
        f"✅ Ticker alınan coin: "
        f"{len(tickers)}"
    )

    # --------------------------------------------------------
    # CONTRACT + TICKER KESİŞİMİ
    # --------------------------------------------------------

    candidates = []

    for symbol, ticker in tickers.items():

        if symbol not in contracts:
            continue

        if ticker["volume24"] <= 0:
            continue

        candidates.append(
            (
                symbol,
                ticker
            )
        )

    # En yüksek hacimli adaylar
    candidates.sort(
        key=lambda x: x[1]["volume24"],
        reverse=True
    )

    candidates = candidates[
        :MAX_CANDIDATES
    ]

    print(
        f"🔎 Detaylı taranacak: "
        f"{len(candidates)}"
    )

    if not candidates:

        print(
            "❌ Uygun aday bulunamadı."
        )

        return

    # --------------------------------------------------------
    # BTC
    # --------------------------------------------------------

    print()
    print("₿ BTC yönü hesaplanıyor...")

    btc_direction = get_btc_direction()

    print(
        f"₿ BTC YÖNÜ: "
        f"{btc_direction}"
    )

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    state = load_state()

    # --------------------------------------------------------
    # ANALİZ
    # --------------------------------------------------------

    results = []

    print()
    print("🔍 Teknik + Open Flow analizleri...")

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for symbol, ticker in candidates:

            if is_on_cooldown(
                symbol,
                state
            ):
                continue

            futures[
                executor.submit(
                    analyze_symbol,
                    symbol,
                    ticker,
                    contracts[symbol]
                )
            ] = symbol

        for future in as_completed(
            futures
        ):

            symbol = futures[future]

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception as e:

                print(
                    f"{symbol} hata: {e}"
                )

    # --------------------------------------------------------
    # SIRALA
    # --------------------------------------------------------

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    print()
    print(
        "=" * 65
    )

    print(
        f"🔥 GÜÇLÜ SONUÇ: "
        f"{len(results)}"
    )

    print(
        "=" * 65
    )

    # --------------------------------------------------------
    # SONUÇLAR
    # --------------------------------------------------------

    for r in results:

        print(
            f"{r['symbol']} | "
            f"{r['direction']} | "
            f"SCORE {r['score']:.0f} | "
            f"OPEN {money(r['total_open'])} | "
            f"LONG {r['long_ratio']:.1f}% | "
            f"SHORT {r['short_ratio']:.1f}% | "
            f"VOL {r['volume_ratio']:.2f}x | "
            f"RSI15 {r['rsi15']:.1f}"
        )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    sent = 0

    # Aynı taramada en fazla 5 alarm
    for signal in results[:5]:

        if send_telegram(signal):

            state[
                signal["symbol"]
            ] = time.time()

            sent += 1

    save_state(state)

    print()
    print(
        f"📨 Gönderilen alarm: {sent}"
    )

    print()
    print(
        "✅ Tarama tamamlandı."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\n⛔ Durduruldu."
        )

    except Exception as e:

        print(
            "\n❌ ANA HATA:",
            e
        )
