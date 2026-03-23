import logging
import asyncio
import random
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

# Namaz kılmayanlar için sert uyarı ayetleri (30 dk öncesi)
AYET_UYARILARI = [
    '⚠️ *"Yazıklar olsun o namaz kılanlara ki, namazlarından gafildirler."*\n_(Maun 4-5)_\n\nHenüz işaretlemedin! Namazını kıldıysan işaretle 👇',
    '⚠️ *"Sizi şu yanık ateşe ne sürükledi? Derler ki: Biz namaz kılanlardan değildik."*\n_(Müddessir 42-43)_\n\nNamazını kılmadıysan hâlâ vakit var! 👇',
    '⚠️ *"Namazı terk etmek, küfür ile şirk arasındaki sınırdır."*\n_(Hadis-i Şerif)_\n\nBu namazı kaçırma! 👇',
    '⚠️ *"Kıyamet günü kulun ilk hesaba çekileceği ameli namazdır."*\n_(Hadis-i Şerif)_\n\nVakit geçmeden kıl veya işaretle! 👇',
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

def build_text(prayer_key, prayer_time_str, is_reminder, date, is_urgent=False):
    name = PRAYER_NAMES[prayer_key]

    if is_urgent:
        header = random.choice(AYET_UYARILARI)
        header = f"🔴 *{name} — 30 Dakika Kaldı!*\n\n" + header
    elif is_reminder:
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

def get_streak(user_id):
    history = db.get_user_daily_scores(user_id, days=60)
    streak  = 0
    today   = datetime.now(tz).date()
    for i in range(60):
        score = history.get((today - timedelta(days=i)).isoformat(), 0)
        if score == 5:
            streak += 1
        else:
            break
    return streak

def get_streak_by_name(first_name):
    uid = db.get_user_id_by_name(first_name)
    return get_streak(uid) if uid else 0

# ── Bildirimler ───────────────────────────────────────────────────────────────

async def send_prayer_notification(context: ContextTypes.DEFAULT_TYPE):
    pk   = context.job.data["prayer_key"]
    pts  = context.job.data["prayer_time_str"]
    date = datetime.now(tz).date().isoformat()

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
    """1 saat öncesi hatırlatma."""
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

async def send_urgent_reminder(context: ContextTypes.DEFAULT_TYPE):
    """30 dakika öncesi sert uyarı — sadece işaretlemeyenlere."""
    pk   = context.job.data["prayer_key"]
    pts  = context.job.data["prayer_time_str"]
    date = datetime.now(tz).date().isoformat()

    all_users  = db.get_all_known_users()
    detail     = db.get_prayer_detail_today(date, pk)
    marked_ids = {r["user_id"] for r in detail}

    # Sadece işaretlemeyenler varsa gönder
    unmarked = [u for u in all_users if u["user_id"] not in marked_ids]
    if not unmarked:
        return

    msg = await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=build_text(pk, pts, False, date, is_urgent=True),
        reply_markup=keyboard(pk), parse_mode="Markdown"
    )
    db.save_notification_message(pk, date, msg.message_id, pts, False)

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

    alerts = {
        "kildi":   "🤲 Allah kabul etsin! Namazınız hayırlı olsun.",
        "kilmadi": "❌ Kaydedildi. Bir sonrakinde hayırlı olsun inşallah.",
        "kaza":    "🔄 Kaza olarak işaretlendi. Unutma inşallah!"
    }
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
    date    = datetime.now(tz).date().isoformat()
    records = db.get_daily_summary(date)
    if not records:
        await context.bot.send_message(GROUP_CHAT_ID, "📊 Günlük Rapor\n\nBugün kayıt girilmedi.")
        return
    lines = [f"📊 *Günlük Namaz Raporu — {date}*\n"]
    for r in records:
        done       = r["kildi"] + r["kaza"]
        streak     = get_streak(r["user_id"])
        streak_txt = f"  🔥{streak}" if streak >= 2 else ""
        lines.append(f"👤 *{r['first_name']}*  {progress(done)}{streak_txt}\n"
                     f"   ✅{r['kildi']}  🔄{r['kaza']}  ❌{r['kilmadi']}  ({done}/5)")
    for r in records:
        if r["kildi"] + r["kaza"] < 5:
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
    best_perfect, champ_name = -1, ""
    for user_name, days in weekly.items():
        lines.append(f"👤 *{user_name}*")
        perfect = 0
        for date_str in dates:
            d      = datetime.fromisoformat(date_str)
            day_tr = DAY_TR.get(d.strftime("%A"), d.strftime("%A"))
            dd     = days.get(date_str, {"kildi": 0, "kaza": 0, "kilmadi": 0})
            done   = dd["kildi"] + dd["kaza"]
            total  = done + dd["kilmadi"]
            if total == 0:   icon, detail = "⬜", "kayıt yok"
            elif done == 5:  icon, detail, perfect = "🟢", "5/5 ✨", perfect + 1
            elif done >= 3:  icon, detail = "🟡", f"{done}/5"
            else:            icon, detail = "🔴", f"{done}/5"
            lines.append(f"   {icon} {day_tr}: {detail}")
        streak     = get_streak_by_name(user_name)
        streak_txt = f"  🔥 {streak} gün streak!" if streak >= 2 else ""
        lines.append(f"   ⭐ Tam gün: *{perfect}/7*{streak_txt}\n")
        if perfect > best_perfect:
            best_perfect, champ_name = perfect, user_name
    if champ_name and best_perfect > 0:
        lines.append(f"🏆 *Haftanın Şampiyonu: {champ_name}!* ({best_perfect} tam gün)")
    await context.bot.send_message(GROUP_CHAT_ID, "\n".join(lines), parse_mode="Markdown")

# ── Aylık rapor ───────────────────────────────────────────────────────────────

async def send_monthly_report(context: ContextTypes.DEFAULT_TYPE):
    today     = datetime.now(tz).date()
    first_day = today.replace(day=1)
    dates, d  = [], first_day
    while d <= today:
        dates.append(d.isoformat())
        d += timedelta(days=1)
    monthly = db.get_weekly_summary(dates)
    if not monthly:
        await context.bot.send_message(GROUP_CHAT_ID, "📆 Aylık Rapor\n\nBu ay kayıt yok.")
        return
    month_name = MONTH_TR.get(today.month, str(today.month))
    lines = [f"📆 *{today.year} {month_name} Aylık Rapor*\n"]
    for user_name, days in monthly.items():
        total_done, perfect_days = 0, 0
        for date_str in dates:
            dd   = days.get(date_str, {"kildi": 0, "kaza": 0, "kilmadi": 0})
            done = dd["kildi"] + dd["kaza"]
            total_done += done
            if done == 5:
                perfect_days += 1
        max_p = len(dates) * 5
        bar   = progress(int(total_done / max_p * 5))
        lines.append(f"👤 *{user_name}*  {bar}\n"
                     f"   🟢 Tam gün: {perfect_days}/{len(dates)}\n"
                     f"   🕌 Toplam: {total_done}/{max_p}")
    await context.bot.send_message(GROUP_CHAT_ID, "\n".join(lines), parse_mode="Markdown")

# ── Komutlar ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🕌 *Namaz Takip Botu Aktif!*\n\n"
        "📬 Her namaz vaktinde bildirim\n"
        "⏰ 1 saat önce hatırlatma\n"
        "🔴 30 dk önce sert uyarı\n"
        "👥 Herkesin durumu anlık görünür\n"
        "🔥 Streak takibi\n"
        "🏆 Haftalık şampiyon rozeti\n"
        "📊 Gece 00:00 günlük rapor\n"
        "📅 Pazar 23:59 haftalık rapor\n"
        "📆 Her ayın sonu aylık rapor\n\n"
        "/rapor — Bugünkü durum\n"
        "/bugun — Bugün ne kıldım?\n"
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

async def cmd_bugun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcının bugün hangi vakitleri kıldığını göster."""
    user  = update.effective_user
    date  = datetime.now(tz).date().isoformat()
    rows  = db.get_user_today_detail(user.id, date)
    status_map = {r["prayer_key"]: r["status"] for r in rows}

    lines = [f"🕌 *Bugünkü Namazların — {user.first_name}*\n"]
    for pk in PRAYER_ORDER:
        name   = PRAYER_NAMES[pk]
        status = status_map.get(pk)
        if status == "kildi":
            icon, txt = "✅", "Kıldım"
        elif status == "kaza":
            icon, txt = "🔄", "Kaza"
        elif status == "kilmadi":
            icon, txt = "❌", "Kılmadım"
        else:
            icon, txt = "⬜", "Henüz işaretlenmedi"
        lines.append(f"{icon} {name}: _{txt}_")

    done = sum(1 for s in status_map.values() if s in ("kildi", "kaza"))
    lines.append(f"\n{progress(done)} *{done}/5*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_haftalik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_weekly_report(context)

async def cmd_aylik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_monthly_report(context)

async def cmd_benim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user     = update.effective_user
    today    = datetime.now(tz).date()
    dates_30 = [(today - timedelta(days=i)).isoformat() for i in range(30)]
    monthly  = db.get_weekly_summary(dates_30)
    user_data = monthly.get(user.first_name, {})
    total_done, perfect_days = 0, 0
    for date_str in dates_30:
        dd   = user_data.get(date_str, {"kildi": 0, "kaza": 0, "kilmadi": 0})
        done = dd["kildi"] + dd["kaza"]
        total_done += done
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
        h, m        = map(int, ts.split(":"))
        prayer_dt   = tz.localize(datetime.combine(now.date(), time(h, m)))
        remind_dt   = prayer_dt - timedelta(hours=1)
        urgent_dt   = prayer_dt - timedelta(minutes=30)

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
        if urgent_dt > now:
            app.job_queue.run_once(
                send_urgent_reminder, when=urgent_dt,
                data={"prayer_key": pk, "prayer_time_str": ts}, name=f"urgent_{pk}"
            )
    logger.info("Günlük vakitler zamanlandı.")

async def reschedule_daily(context: ContextTypes.DEFAULT_TYPE):
    for job in context.application.job_queue.jobs():
        if job.name and any(job.name.startswith(p) for p in ("prayer_", "reminder_", "urgent_")):
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
    app.job_queue.run_daily(send_friday_reminder, time=time(9, 0, tzinfo=tz), days=(4,), name="friday_reminder")

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    db.init()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("rapor",    cmd_rapor))
    app.add_handler(CommandHandler("bugun",    cmd_bugun))
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
