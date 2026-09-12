import os
import time
import requests


# ============================================================
# MEXC KLINE API TEST V4.1
# ============================================================

BASE = "https://api.mexc.com"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

session = requests.Session()

session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
})


# ============================================================
# FUTURES SYMBOL TEST
# ============================================================

def test_symbols():

    print()
    print("=" * 60)
    print("1️⃣ FUTURES SYMBOL TEST")
    print("=" * 60)

    url = BASE + "/api/v1/contract/detail"

    try:

        response = session.get(
            url,
            timeout=15
        )

        print("HTTP:", response.status_code)

        print(
            "Response:",
            response.text[:500]
        )

        if response.status_code != 200:

            print("❌ Futures API başarısız")
            return False

        data = response.json()

        rows = data.get("data", [])

        print(
            "✅ Futures sembol sayısı:",
            len(rows)
        )

        return len(rows) > 0

    except Exception as e:

        print("❌ HATA:", repr(e))

        return False


# ============================================================
# KLINE TEST
# ============================================================

def test_kline(symbol):

    print()
    print("=" * 60)
    print("2️⃣ KLINE TEST")
    print("=" * 60)

    print("Coin:", symbol)

    # --------------------------------------------------------
    # 15 DAKİKALIK MUM
    # --------------------------------------------------------

    end = int(time.time())

    start = end - (60 * 60 * 24)

    url = (
        BASE
        + "/api/v1/contract/kline/"
        + symbol
    )

    params = {
        "interval": "Min15",
        "start": start,
        "end": end
    }

    print()
    print("URL:")
    print(url)

    print()
    print("PARAMETRELER:")
    print(params)

    try:

        response = session.get(
            url,
            params=params,
            timeout=15
        )

        print()
        print("HTTP STATUS:")
        print(response.status_code)

        print()
        print("GERÇEK MEXC CEVABI:")
        print(response.text[:2000])

        print()

        if response.status_code != 200:

            print(
                "❌ HTTP HATASI:",
                response.status_code
            )

            return False

        try:

            data = response.json()

        except Exception as e:

            print(
                "❌ JSON okunamadı:",
                repr(e)
            )

            return False

        print()
        print("JSON ANAHTARLARI:")

        if isinstance(data, dict):

            print(
                list(data.keys())
            )

        print()

        raw = data.get("data")

        if not raw:

            print(
                "❌ data alanı boş."
            )

            return False

        print(
            "data tipi:",
            type(raw).__name__
        )

        if isinstance(raw, dict):

            print(
                "data anahtarları:",
                list(raw.keys())
            )

            times = raw.get("time", [])

            print()
            print(
                "MUM SAYISI:",
                len(times)
            )

            if len(times) > 0:

                print()
                print(
                    "✅ KLINE API ÇALIŞIYOR!"
                )

                print(
                    "İlk zaman:",
                    times[0]
                )

                print(
                    "Son zaman:",
                    times[-1]
                )

                return True

        print()
        print(
            "❌ Kline verisi beklenen formatta değil."
        )

        return False

    except Exception as e:

        print()
        print(
            "❌ REQUEST HATASI:"
        )

        print(
            repr(e)
        )

        return False


# ============================================================
# ANA
# ============================================================

def main():

    print()
    print("=" * 60)
    print("🚀 MEXC KLINE API DIAGNOSTIC V4.1")
    print("=" * 60)

    print()
    print(
        "BASE:",
        BASE
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    print()

    if TOKEN:
        print(
            "✅ TELEGRAM_BOT_TOKEN bulundu"
        )
    else:
        print(
            "⚠️ TELEGRAM_BOT_TOKEN yok"
        )

    if CHAT_ID:
        print(
            "✅ TELEGRAM_CHAT_ID bulundu"
        )
    else:
        print(
            "⚠️ TELEGRAM_CHAT_ID yok"
        )

    # --------------------------------------------------------
    # FUTURES
    # --------------------------------------------------------

    if not test_symbols():

        print()
        print(
            "❌ Futures API çalışmıyor."
        )

        return

    # --------------------------------------------------------
    # BTC KLINE
    # --------------------------------------------------------

    success = test_kline(
        "BTC_USDT"
    )

    print()
    print("=" * 60)

    if success:

        print(
            "🎉 KLINE API BAŞARILI"
        )

        print(
            "Artık gerçek radar koduna geçebiliriz."
        )

    else:

        print(
            "❌ KLINE API BAŞARISIZ"
        )

        print(
            "Yukarıdaki MEXC cevabı sorunun nedenini gösterecek."
        )

    print("=" * 60)


# ============================================================

if __name__ == "__main__":
    main()
