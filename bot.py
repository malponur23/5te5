import logging
import asyncio
from datetime import datetime, time, timedelta
import pytz

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest

from prayer_times import get_prayer_times_today
from database import Database
from config import BOT_TOKEN, GROUP_CHAT_ID, TIMEZONE

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

db = Database()
tz = pytz.timezone(TIMEZONE)

PRAYER_NAMES = {
    "Fajr":    "🌅 Sabah",
    "Dhuhr":   "☀️ Öğle",
    "Asr":     "🌤 İkindi",
    "Maghrib": "🌇 Akşam",
    "Isha":    "🌙 Yatsı",
}
PRAYER_ORDER = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
DAY_TR = {
    "Monday":"Pazartesi","Tuesday":"Salı","Wednesday":"Çarşamba",
    "Thursday":"Perşembe","Friday":"Cuma","Saturday":"Cumartesi","Sunday":"Pazar"
}

MONTH_TR = {
    1:"Ocak",2:"Şubat",3:"Mart",4:"Nisan",5:"Mayıs",6:"Haziran",
    7:"Temmuz",8:"Ağustos",9:"Eylül",10:"Ekim",11:"Kasım",12:"Aralık"
}

TESELLI = [
    "Üzülme, yarın telafi edersin inşallah! 💪",
    "Önemli olan devam etmek, vazgeçmemek! 🌟",
    "Her gün yeni bir fırsat, yarın daha iyi olacak! 🤲",
    "Allah affedicidir, bir sonrakinde daha dikkatli ol! 🌙",
]

# ── Yardımcılar ──────────────────────────────────────────────────────────────

def keyboard(prayer_key):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Kıldım",   callback_data=f"pray|kildi|{prayer_key}"),
         InlineKeyboardButton("❌ Kılmadım", callback_data=f"pray|kilmadi|{prayer_key}")],
        [InlineKeyboardButton("🔄 Kaza Olarak İşaretle", callback_data=f"pray|kaza|{prayer_key}")]
    ])

def progress(done, total=5):
    return "█" * min(done, total) + "░" * (total - min(done, total))

def build_text(prayer_key, prayer_time_str, is_reminder, date):
    name = PRAYER_NAMES[prayer_key]
    if is_reminder:
        header = f"⏰ *{name} Hatırlatması*\nVakit: `{prayer_time_str}` yaklaşıyor!\n\nKıldın mı? İşaretlemedin 👇"
    else:
        header = f"{name} *Namazı Vakti Girdi!* 🕌\nSaat: `{prayer_time_str}`\n\nNamazınızı kıldınız mı? 👇"

    all_users   = db.get_all_known_users()
    detail      = db.get_prayer_detail_today(date, prayer_key)
    user_status = {r["user_id"]: r["status"] for r in detail}

    if not all_users:
        return header

    lines = ["\n📋 *Bu Namazın Durumu:*"]
    for u in all_users:
        s    = user_status.get(u["user_id"])
        icon = {"kildi": "✅", "kaza": "🔄", "kilmadi": "❌"}.get(s, "⬜")
        lines.append(f"  {icon} {u['first_name']}")
    return header + "\n".join(lines)

# ── Streak hesapla ────────────────────────────────────────────────────────────

def get_streak(user_id):
    """Kaç gün üst üste 5/5 yapıldığını hesapla."""
    history = db.get_user_daily_scores(user_id, days=60)
    streak = 0
    today = datetime.now(tz).date()
    for i in range(len(history)):
        day_date = today - timedelta(days=i)
        score = history.get(day_date.isoformat(), 0)
        if score == 5:
            streak += 1
        else:
            break
    return streak

# ── Bildirimler ───────────────────────────────────────────────────────────────

async def send_prayer_notification(context: ContextTypes.DEFAULT_TYPE):
    pk   = context.job.data["prayer_key"]
    pts  = context.job.data["prayer_time_str"]
    date = datetime.now(tz).date().isoformat()

    # Cuma özel mesajı
    extra = ""
    if datetime.now(tz).strftime("%A") == "Friday" and pk == "Dhuhr":
        extra = "\n\n🌟 *Cuma Mübarek Olsun!* Cuma namazını kaçırmayın! 🕌"

    text = build_text(pk, pts, False, date) + extra
    msg  = await context.bot.send_message(
        chat_id=GROUP_CHAT_ID, text=text,
        reply_markup=keyboard(pk), parse_mode="Markdown"
    )
    db.save_notification_message(pk, date, msg.message_id, pts, False)

async def send_prayer_reminder(context: ContextTypes.DEFAULT_TYPE):
    pk   = context.job.data["prayer_key"]
    pts  = context.job.data["prayer_time_str"]
    date = datetime.now(tz).date().isoformat()

    all_users  = db.get_all_known_users()
    detail     = db.get_prayer_detail_today(date, pk)
    marked_ids = {r["user_id"] for r in detail}
    if all_users and all(u["user_id"] in marked_ids for u in all_users):
        return

    msg = await context.bot.send_message(
        chat_id=GROUP_CHAT_ID, text=build_text(pk, pts, True, date),
        reply_markup=keyboard(pk), parse_mode="Markdown"
    )
    db.save_notification_message(pk, date, msg.message_id, pts, True)

# ── Cuma özel bildirimi ───────────────────────────────────────────────────────

async def send_friday_reminder(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text="🌟 *Cuma Mübarek Olsun!*\n\nBugün Cuma — en hayırlı gün! 🤲\nCuma namazını kaçırmayın.",
        parse_mode="Markdown"
    )

# ── Buton ─────────────────────────────────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    if parts[0] != "pray":
        return

    _, status, prayer_key = parts
    user  = query.from_user
    date  = datetime.now(tz).date().isoformat()

    db.record_prayer(user.id, user.username or user.first_name,
                     user.first_name, prayer_key, status, date)

    alerts = {"kildi":   "✅ Namazınız hayırlı olsun!",
              "kilmadi": "❌ Bir sonrakinde hayırlı olsun.",
              "kaza":    "🔄 Kaza olarak işaretlendi."}
    await query.answer(alerts.get(status, "Kaydedildi."), show_alert=True)

    for notif in db.get_notification_messages(prayer_key, date):
        try:
            await context.bot.edit_message_text(
                chat_id=GROUP_CHAT_ID, message_id=notif["message_id"],
                text=build_text(prayer_key, notif["prayer_time_str"],
                                notif["is_reminder"] == 1, date),
                reply_markup=keyboard(prayer_key), parse_mode="Markdown"
            )
        except BadRequest:
            pass

# ── Günlük rapor ──────────────────────────────────────────────────────────────

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    today   = datetime.now(tz).date()
    date    = today.isoformat()
    records = db.get_daily_summary(date)

    if not records:
        await context.bot.send_message(GROUP_CHAT_ID, "📊 Günlük Rapor\n\nBugün kayıt girilmedi.")
        return

    lines = [f"📊 *Günlük Namaz Raporu — {date}*\n"]
    best_done  = -1
    best_names = []

    for r in records:
        done   = r["kildi"] + r["kaza"]
        streak = get_streak(r["user_id"]) if "user_id" in r else 0
        streak_txt = f"  🔥{streak}" if streak >= 2 else ""
        lines.append(f"👤 *{r['first_name']}*  {progress(done)}{streak_txt}\n"
                     f"   ✅{r['kildi']}  🔄{r['kaza']}  ❌{r['kilmadi']}  ({done}/5)")
        if done > best_done:
            best_done  = done
            best_names = [r["first_name"]]
        elif done == best_done:
            best_names.append(r["first_name"])

    # Eksik olanlar için teselli
    import random
    for r in records:
        done = r["kildi"] + r["kaza"]
        if done < 5:
            lines.append(f"\n_{random.choice(TESELLI)}_")
            break

    await context.bot.send_message(GROUP_CHAT_ID, "\n".join(lines), parse_mode="Markdown")

# ── Haftalık rapor ────────────────────────────────────────────────────────────

async def send_weekly_report(context: ContextTypes.DEFAULT_TYPE):
    today      = datetime.now(tz).date()
    week_start = today - timedelta(days=6)
    dates      = [(week_start + timedelta(days=i)).isoformat() for i in range(7)]
    weekly     = db.get_weekly_summary(dates)

    if not weekly:
        await context.bot.send_message(GROUP_CHAT_ID, "📅 Haftalık Rapor\n\nBu hafta kayıt yok.")
        return

    lines = ["📅 *Haftalık Namaz Raporu*",
             f"🗓 _{week_start.isoformat()} → {today.isoformat()}_\n"]

    best_perfect = -1
    champ_name   = ""

    for user_name, days in weekly.items():
        lines.append(f"👤 *{user_name}*")
        perfect = 0
        for date_str in dates:
            d      = datetime.fromisoformat(date_str)
            day_tr = DAY_TR.get(d.strftime("%A"), d.strftime("%A"))
            dd     = days.get(date_str, {"kildi": 0, "kaza": 0, "kilmadi": 0})
            done   = dd["kildi"] + dd["kaza"]
            total  = done + dd["kilmadi"]

            if total == 0:       icon, detail = "⬜", "kayıt yok"
            elif done == 5:      icon, detail, perfect = "🟢", "5/5 ✨", perfect + 1
            elif done >= 3:      icon, detail = "🟡", f"{done}/5"
            else:                icon, detail = "🔴", f"{done}/5"

            lines.append(f"   {icon} {day_tr}: {detail}")

        streak = get_streak_by_name(user_name)
        streak_txt = f"  🔥 {streak} gün streak!" if streak >= 2 else ""
        lines.append(f"   ⭐ Tam gün: *{perfect}/7*{streak_txt}\n")

        if perfect > best_perfect:
            best_perfect = perfect
            champ_name   = user_name

    # Haftalık şampiyon rozeti
    if champ_name and best_perfect > 0:
        lines.append(f"🏆 *Haftanın Şampiyonu: {champ_name}!* ({best_perfect} tam gün)")

    await context.bot.send_message(GROUP_CHAT_ID, "\n".join(lines), parse_mode="Markdown")

def get_streak_by_name(first_name):
    user_id = db.get_user_id_by_name(first_name)
    if not user_id:
        return 0
    return get_streak(user_id)

# ── Aylık rapor ───────────────────────────────────────────────────────────────

async def send_monthly_report(context: ContextTypes.DEFAULT_TYPE):
    today      = datetime.now(tz).date()
    # Ayın ilk günü hesapla
    first_day  = today.replace(day=1)
    dates      = []
    d = first_day
    while d <= today:
        dates.append(d.isoformat())
        d += timedelta(days=1)

    monthly = db.get_weekly_summary(dates)  # aynı fonksiyon çalışır

    if not monthly:
        await context.bot.send_message(GROUP_CHAT_ID, "📆 Aylık Rapor\n\nBu ay kayıt yok.")
        return

    month_name = MONTH_TR.get(today.month, str(today.month))
    lines = [f"📆 *{today.year} {month_name} Aylık Rapor*\n"]

    for user_name, days in monthly.items():
        total_done    = 0
        perfect_days  = 0
        for date_str in dates:
            dd   = days.get(date_str, {"kildi": 0, "kaza": 0, "kilmadi": 0})
            done = dd["kildi"] + dd["kaza"]
            total_done   += done
            if done == 5:
                perfect_days += 1

        max_possible = len(dates) * 5
        bar = progress(int(total_done / max_possible * 5))
        lines.append(
            f"👤 *{user_name}*  {bar}\n"
            f"   🟢 Tam gün: {perfect_days}/{len(dates)}\n"
            f"   🕌 Toplam: {total_done}/{max_possible}"
        )

    await context.bot.send_message(GROUP_CHAT_ID, "\n".join(lines), parse_mode="Markdown")

# ── Komutlar ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🕌 *Namaz Takip Botu Aktif!*\n\n"
        "📬 Her namaz vaktinde bildirim\n"
        "⏰ Vakitten 1 saat önce hatırlatma\n"
        "👥 Herkesin durumu anlık görünür\n"
        "🔥 Streak takibi\n"
        "🏆 Haftalık şampiyon rozeti\n"
        "📊 Gece 00:00 günlük rapor\n"
        "📅 Pazar 23:59 haftalık rapor\n"
        "📆 Her ayın sonu aylık rapor\n\n"
        "/rapor — Bugünkü durum\n"
        "/haftalik — Bu haftanın raporu\n"
        "/aylik — Bu ayın raporu\n"
        "/benim — Kendi istatistiklerim\n"
        "/vakitler — Bugünkü vakitler",
        parse_mode="Markdown"
    )

async def cmd_rapor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date    = datetime.now(tz).date().isoformat()
    records = db.get_daily_summary(date)
    if not records:
        await update.message.reply_text("Bugün henüz kayıt yok.")
        return
    lines = [f"📊 *Bugünkü Durum — {date}*\n"]
    for r in records:
        done = r["kildi"] + r["kaza"]
        lines.append(f"👤 *{r['first_name']}*  {progress(done)}\n"
                     f"   ✅{r['kildi']}  🔄{r['kaza']}  ❌{r['kilmadi']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_haftalik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_weekly_report(context)

async def cmd_aylik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_monthly_report(context)

async def cmd_benim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    today   = datetime.now(tz).date()
    dates_30 = [(today - timedelta(days=i)).isoformat() for i in range(30)]

    monthly = db.get_weekly_summary(dates_30)
    user_data = monthly.get(user.first_name, {})

    total_done   = 0
    perfect_days = 0
    for date_str in dates_30:
        dd   = user_data.get(date_str, {"kildi": 0, "kaza": 0, "kilmadi": 0})
        done = dd["kildi"] + dd["kaza"]
        total_done   += done
        if done == 5:
            perfect_days += 1

    streak     = get_streak(user.id)
    max_streak = db.get_max_streak(user.id)

    lines = [
        f"📊 *{user.first_name} — Son 30 Gün*\n",
        f"🕌 Toplam namaz: *{total_done}/150*",
        f"🟢 Tam gün (5/5): *{perfect_days}/30*",
        f"🔥 Mevcut streak: *{streak} gün*",
        f"⭐ En uzun streak: *{max_streak} gün*",
        f"\n{progress(int(total_done/150*5))} %{int(total_done/150*100)}"
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_vakitler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    times = get_prayer_times_today()
    lines = ["🕌 *Bugünkü İstanbul Namaz Vakitleri*\n"]
    for k, v in PRAYER_NAMES.items():
        lines.append(f"{v}: `{times.get(k, '?')}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ── Scheduler ─────────────────────────────────────────────────────────────────

def _schedule_day(app):
    times = get_prayer_times_today()
    now   = datetime.now(tz)
    for pk in PRAYER_ORDER:
        ts = times.get(pk)
        if not ts:
            continue
        h, m      = map(int, ts.split(":"))
        prayer_dt = tz.localize(datetime.combine(now.date(), time(h, m)))
        remind_dt = prayer_dt - timedelta(hours=1)

        if prayer_dt > now:
            app.job_queue.run_once(
                send_prayer_notification, when=prayer_dt,
                data={"prayer_key": pk, "prayer_time_str": ts}, name=f"prayer_{pk}"
            )
        if remind_dt > now:
            app.job_queue.run_once(
                send_prayer_reminder, when=remind_dt,
                data={"prayer_key": pk, "prayer_time_str": ts}, name=f"reminder_{pk}"
            )
    logger.info("Günlük vakitler zamanlandı.")

async def reschedule_daily(context: ContextTypes.DEFAULT_TYPE):
    for job in context.application.job_queue.jobs():
        if job.name and (job.name.startswith("prayer_") or job.name.startswith("reminder_")):
            job.schedule_removal()
    _schedule_day(context.application)

def schedule_prayers(app):
    _schedule_day(app)
    now           = datetime.now(tz)
    next_midnight = tz.localize(datetime.combine(now.date(), time(0, 0))) + timedelta(days=1)

    app.job_queue.run_once(send_daily_report, when=next_midnight, name="daily_report_once")
    app.job_queue.run_daily(reschedule_daily,    time=time(0, 1,  tzinfo=tz), name="reschedule")
    app.job_queue.run_daily(send_daily_report,   time=time(0, 0,  tzinfo=tz), name="daily_report")
    app.job_queue.run_daily(send_weekly_report,  time=time(23, 59, tzinfo=tz), days=(6,), name="weekly_report")
    app.job_queue.run_daily(send_monthly_report, time=time(23, 58, tzinfo=tz), days=(6,), name="monthly_check")
    # Cuma sabahı özel bildirim
    app.job_queue.run_daily(send_friday_reminder, time=time(9, 0, tzinfo=tz), days=(4,), name="friday_reminder")

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    db.init()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("rapor",    cmd_rapor))
    app.add_handler(CommandHandler("haftalik", cmd_haftalik))
    app.add_handler(CommandHandler("aylik",    cmd_aylik))
    app.add_handler(CommandHandler("benim",    cmd_benim))
    app.add_handler(CommandHandler("vakitler", cmd_vakitler))
    app.add_handler(CallbackQueryHandler(button_callback))
    schedule_prayers(app)
    logger.info("Bot başlatıldı 🕌")
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
