import requests
from datetime import datetime
import pytz
import logging

logger = logging.getLogger(__name__)

TIMEZONE = "Europe/Istanbul"
tz = pytz.timezone(TIMEZONE)

# Diyanet method = 13
ALADHAN_URL = "https://api.aladhan.com/v1/timingsByCity"

def get_prayer_times_today() -> dict:
    """
    Aladhan API'den İstanbul için bugünkü namaz vakitlerini çeker.
    Dönen dict: {"Fajr": "05:43", "Dhuhr": "13:12", ...}
    """
    now = datetime.now(tz)
    params = {
        "city": "Istanbul",
        "country": "Turkey",
        "method": 13,  # Diyanet İşleri Başkanlığı
        "date": now.strftime("%d-%m-%Y")
    }

    try:
        response = requests.get(ALADHAN_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        timings = data["data"]["timings"]

        result = {
            "Fajr":    timings["Fajr"][:5],
            "Dhuhr":   timings["Dhuhr"][:5],
            "Asr":     timings["Asr"][:5],
            "Maghrib": timings["Maghrib"][:5],
            "Isha":    timings["Isha"][:5],
        }
        logger.info(f"Namaz vakitleri alındı: {result}")
        return result

    except Exception as e:
        logger.error(f"Namaz vakitleri alınamadı: {e}")
        # Fallback: sabit vakitler (sadece hata durumunda)
        return {
            "Fajr":    "05:30",
            "Dhuhr":   "13:00",
            "Asr":     "16:00",
            "Maghrib": "19:00",
            "Isha":    "20:30",
        }
