import aiosqlite
from pathlib import Path

DB_PATH = Path("bot.db")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guilds (
                guild_id INTEGER PRIMARY KEY,
                unverified_role_id INTEGER,
                verified_role_id INTEGER,
                verify_channel_id INTEGER,
                welcome_channel_id INTEGER,
                log_channel_id INTEGER,
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
        await db.commit()

async def get_guild_settings(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM guilds WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "unverified_role_id": row[1],
                    "verified_role_id": row[2],
                    "verify_channel_id": row[3],
                    "welcome_channel_id": row[4],
                    "log_channel_id": row[5],
                    "verify_timeout": row[6] or 15
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
