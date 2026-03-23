import sqlite3
import os
import logging
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)
DB_PATH = os.environ.get("DB_PATH", "namaz_bot.db")
TIMEZONE = "Europe/Istanbul"


class Database:

    def init(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prayers (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    username    TEXT,
                    first_name  TEXT,
                    prayer_key  TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, prayer_key, date)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    prayer_key      TEXT NOT NULL,
                    date            TEXT NOT NULL,
                    message_id      INTEGER NOT NULL,
                    prayer_time_str TEXT NOT NULL,
                    is_reminder     INTEGER NOT NULL DEFAULT 0,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        logger.info("Veritabanı hazır.")

    def _conn(self):
        return sqlite3.connect(DB_PATH)

    def record_prayer(self, user_id, username, first_name, prayer_key, status, date):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO prayers (user_id, username, first_name, prayer_key, status, date)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, prayer_key, date)
                DO UPDATE SET status=excluded.status,
                              username=excluded.username,
                              first_name=excluded.first_name
            """, (user_id, username, first_name, prayer_key, status, date))
            conn.commit()

    def get_daily_summary(self, date):
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT user_id, first_name,
                    SUM(CASE WHEN status='kildi'   THEN 1 ELSE 0 END) AS kildi,
                    SUM(CASE WHEN status='kaza'    THEN 1 ELSE 0 END) AS kaza,
                    SUM(CASE WHEN status='kilmadi' THEN 1 ELSE 0 END) AS kilmadi
                FROM prayers WHERE date=? GROUP BY user_id ORDER BY (kildi+kaza) DESC
            """, (date,)).fetchall()
        return [dict(r) for r in rows]

    def get_prayer_detail_today(self, date, prayer_key):
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT user_id, first_name, status FROM prayers
                WHERE date=? AND prayer_key=?
            """, (date, prayer_key)).fetchall()
        return [dict(r) for r in rows]

    def get_all_known_users(self):
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT DISTINCT user_id, first_name FROM prayers ORDER BY first_name
            """).fetchall()
        return [dict(r) for r in rows]

    def get_user_id_by_name(self, first_name):
        with self._conn() as conn:
            row = conn.execute("""
                SELECT user_id FROM prayers WHERE first_name=? LIMIT 1
            """, (first_name,)).fetchone()
        return row[0] if row else None

    def get_weekly_summary(self, dates):
        placeholders = ",".join("?" * len(dates))
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f"""
                SELECT user_id, first_name, date,
                    SUM(CASE WHEN status='kildi'   THEN 1 ELSE 0 END) AS kildi,
                    SUM(CASE WHEN status='kaza'    THEN 1 ELSE 0 END) AS kaza,
                    SUM(CASE WHEN status='kilmadi' THEN 1 ELSE 0 END) AS kilmadi
                FROM prayers WHERE date IN ({placeholders})
                GROUP BY user_id, date ORDER BY first_name, date
            """, dates).fetchall()
        result = {}
        for r in rows:
            name = r["first_name"]
            if name not in result:
                result[name] = {}
            result[name][r["date"]] = {
                "kildi": r["kildi"], "kaza": r["kaza"], "kilmadi": r["kilmadi"]
            }
        return result

    def get_user_daily_scores(self, user_id, days=60):
        """Kullanıcının son N gündeki günlük namaz sayısını döner {date: score}"""
        tz   = pytz.timezone(TIMEZONE)
        today = datetime.now(tz).date()
        dates = [(today - timedelta(days=i)).isoformat() for i in range(days)]
        placeholders = ",".join("?" * len(dates))
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f"""
                SELECT date,
                    SUM(CASE WHEN status IN ('kildi','kaza') THEN 1 ELSE 0 END) AS done
                FROM prayers
                WHERE user_id=? AND date IN ({placeholders})
                GROUP BY date
            """, [user_id] + dates).fetchall()
        return {r["date"]: r["done"] for r in rows}

    def get_max_streak(self, user_id):
        """Kullanıcının tüm zamanların en uzun streakini hesapla."""
        scores = self.get_user_daily_scores(user_id, days=365)
        tz     = pytz.timezone(TIMEZONE)
        today  = datetime.now(tz).date()
        max_s  = cur = 0
        for i in range(365):
            d = (today - timedelta(days=i)).isoformat()
            if scores.get(d, 0) == 5:
                cur += 1
                max_s = max(max_s, cur)
            else:
                cur = 0
        return max_s

    def save_notification_message(self, prayer_key, date, message_id, prayer_time_str, is_reminder):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO notifications (prayer_key, date, message_id, prayer_time_str, is_reminder)
                VALUES (?, ?, ?, ?, ?)
            """, (prayer_key, date, message_id, prayer_time_str, int(is_reminder)))
            conn.commit()

    def get_user_prayer_status(self, user_id, prayer_key, date):
        """Kullanıcının belirli bir namazın mevcut statüsünü döner."""
        with self._conn() as conn:
            row = conn.execute("""
                SELECT status FROM prayers
                WHERE user_id=? AND prayer_key=? AND date=?
            """, (user_id, prayer_key, date)).fetchone()
        return row[0] if row else None

    def get_user_today_detail(self, user_id, date):
        """Kullanıcının bugün hangi vakitleri kıldığını döner."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT prayer_key, status FROM prayers
                WHERE user_id=? AND date=?
            """, (user_id, date)).fetchall()
        return [dict(r) for r in rows]

    def get_notification_messages(self, prayer_key, date):
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT message_id, prayer_time_str, is_reminder FROM notifications
                WHERE prayer_key=? AND date=? ORDER BY id
            """, (prayer_key, date)).fetchall()
        return [dict(r) for r in rows]
