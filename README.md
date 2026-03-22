# 🕌 Namaz Takip Telegram Botu

İstanbul namaz vakitlerinde Telegram grubuna bildirim gönderen,
kılındı/kılınmadı/kaza takibi yapan ve günlük rapor paylaşan bot.

---

## 📋 Özellikler

- ✅ Her namaz vaktinde otomatik bildirim
- ✅ Kıldım / Kılmadım / Kaza işaretleme (inline buton)
- ✅ Gece 00:00'da günlük rapor (kim kaç vakit kıldı)
- ✅ `/rapor` komutuyla anlık durum
- ✅ `/vakitler` komutuyla bugünkü vakitleri görme
- ✅ Diyanet metoduyla İstanbul vakitleri (Aladhan API)

---

## 🚀 Kurulum — Adım Adım

### 1. Bot Token Al

1. Telegram'da `@BotFather`'a yaz
2. `/newbot` → isim ver → kullanıcı adı ver (sonu `bot` ile bitmeli)
3. Sana verilen **token**'ı kopyala

### 2. Grup Chat ID'sini Bul

1. Botu gruba ekle
2. Botu **grup yöneticisi** yap (mesaj gönderebilmesi için)
3. Gruba herhangi bir mesaj yaz
4. Tarayıcıda şu URL'i aç:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
5. `"chat":{"id":` yazan yerdeki sayıyı kopyala (genellikle `-100` ile başlar)

### 3. Render.com'a Deploy Et (Ücretsiz)

1. [render.com](https://render.com) → GitHub ile kayıt ol
2. Bu klasörü GitHub'a push et
3. Render → **New → Blueprint** → repo'yu seç → `render.yaml` otomatik algılanır
4. Environment variables ekle:
   - `BOT_TOKEN` → BotFather'dan aldığın token
   - `GROUP_CHAT_ID` → Grubun ID'si (örn: `-1001234567890`)
5. **Deploy** 🎉

### 4. Alternatif: Railway.app

1. [railway.app](https://railway.app) → GitHub ile bağlan
2. Repo'yu seç → **Add Variables**:
   - `BOT_TOKEN`
   - `GROUP_CHAT_ID`
3. Deploy et (otomatik `Procfile`'ı bulur)

---

## 📁 Dosya Yapısı

```
namaz_bot/
├── bot.py            # Ana bot dosyası
├── prayer_times.py   # Namaz vakti API
├── database.py       # SQLite veritabanı
├── config.py         # Ayarlar
├── requirements.txt  # Python bağımlılıkları
├── render.yaml       # Render.com deploy config
├── Procfile          # Railway deploy config
└── README.md
```

---

## 💬 Bot Komutları

| Komut | Açıklama |
|-------|----------|
| `/start` | Botu başlat ve yardım göster |
| `/rapor` | Bugünkü namaz durumunu göster |
| `/vakitler` | Bugünkü İstanbul namaz vakitleri |

---

## ⚙️ Teknik Notlar

- **Namaz vakitleri**: Aladhan.com API, Diyanet metodu (13), her gün otomatik güncellenir
- **Veritabanı**: SQLite (Render disk üzerinde kalıcı)
- **Timezone**: Europe/Istanbul
- **Rapor saati**: Gece 00:00 (İstanbul saatiyle)
- Aynı namaz için tekrar tıklanırsa **güncellenir** (son tıklama geçerli)
