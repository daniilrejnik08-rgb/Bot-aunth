import aiosqlite
from pathlib import Path
from typing import List

DB_PATH = Path("bot.db")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guilds (
                guild_id INTEGER PRIMARY KEY,
                unverified_role_id INTEGER,
                verified_role_id INTEGER,
                muted_role_id INTEGER,
                verify_channel_id INTEGER,
                welcome_channel_id INTEGER,
                log_channel_id INTEGER,
                mod_log_channel_id INTEGER,
                verify_timeout INTEGER DEFAULT 15
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pending_verifications (
                user_id INTEGER,
                guild_id INTEGER,
                joined_at REAL,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channel_mutes (
                user_id INTEGER,
                guild_id INTEGER,
                channel_id INTEGER,
                reason TEXT,
                muted_by INTEGER,
                muted_at REAL,
                PRIMARY KEY (user_id, guild_id, channel_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bad_words (
                guild_id INTEGER,
                word TEXT,
                PRIMARY KEY (guild_id, word)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                reporter_id INTEGER,
                reported_id INTEGER,
                reason TEXT,
                created_at REAL
            )
        """)
        await db.commit()


async def get_guild_settings(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM guilds WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "unverified_role_id": row[1],
                    "verified_role_id": row[2],
                    "muted_role_id": row[3],
                    "verify_channel_id": row[4],
                    "welcome_channel_id": row[5],
                    "log_channel_id": row[6],
                    "mod_log_channel_id": row[7],
                    "verify_timeout": row[8] or 15
                }
            return None

async def set_guild_settings(guild_id: int, **kwargs):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM guilds WHERE guild_id = ?", (guild_id,)) as c:
            exists = await c.fetchone()

        if exists:
            sets = ", ".join(f"{k} = ?" for k in kwargs.keys())
            values = list(kwargs.values()) + [guild_id]
            await db.execute(f"UPDATE guilds SET {sets} WHERE guild_id = ?", values)
        else:
            columns = ["guild_id"] + list(kwargs.keys())
            placeholders = ", ".join("?" for _ in columns)
            values = [guild_id] + list(kwargs.values())
            await db.execute(
                f"INSERT INTO guilds ({', '.join(columns)}) VALUES ({placeholders})",
                values
            )
        await db.commit()


async def add_pending(user_id: int, guild_id: int, joined_at: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO pending_verifications (user_id, guild_id, joined_at) VALUES (?, ?, ?)",
            (user_id, guild_id, joined_at)
        )
        await db.commit()

async def remove_pending(user_id: int, guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM pending_verifications WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        await db.commit()

async def get_pending(guild_id: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        if guild_id:
            async with db.execute(
                "SELECT user_id, guild_id, joined_at FROM pending_verifications WHERE guild_id = ?",
                (guild_id,)
            ) as cursor:
                return await cursor.fetchall()
        else:
            async with db.execute(
                "SELECT user_id, guild_id, joined_at FROM pending_verifications"
            ) as cursor:
                return await cursor.fetchall()


async def add_channel_mute(user_id: int, guild_id: int, channel_id: int, reason: str, muted_by: int, muted_at: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO channel_mutes (user_id, guild_id, channel_id, reason, muted_by, muted_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, guild_id, channel_id, reason, muted_by, muted_at)
        )
        await db.commit()

async def remove_channel_mute(user_id: int, guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM channel_mutes WHERE user_id = ? AND guild_id = ? AND channel_id = ?",
            (user_id, guild_id, channel_id)
        )
        await db.commit()


async def add_bad_word(guild_id: int, word: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO bad_words (guild_id, word) VALUES (?, ?)",
            (guild_id, word.lower())
        )
        await db.commit()

async def remove_bad_word(guild_id: int, word: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM bad_words WHERE guild_id = ? AND word = ?",
            (guild_id, word.lower())
        )
        await db.commit()

async def get_bad_words(guild_id: int) -> List[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT word FROM bad_words WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]


async def add_report(guild_id: int, reporter_id: int, reported_id: int, reason: str, created_at: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reports (guild_id, reporter_id, reported_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, reporter_id, reported_id, reason, created_at)
        )
        await db.commit()
