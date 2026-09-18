import aiosqlite
from pathlib import Path
from typing import List, Tuple, Optional

DB_PATH = Path("bot.db")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS guilds (
            guild_id INTEGER PRIMARY KEY,
            unverified_role_id INTEGER, verified_role_id INTEGER, muted_role_id INTEGER,
            verify_channel_id INTEGER, welcome_channel_id INTEGER,
            log_channel_id INTEGER, mod_log_channel_id INTEGER,
            verify_timeout INTEGER DEFAULT 15)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS pending_verifications (
            user_id INTEGER, guild_id INTEGER, joined_at REAL,
            PRIMARY KEY (user_id, guild_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS channel_mutes (
            user_id INTEGER, guild_id INTEGER, channel_id INTEGER,
            reason TEXT, muted_by INTEGER, muted_at REAL,
            PRIMARY KEY (user_id, guild_id, channel_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS bad_words (
            guild_id INTEGER, word TEXT, PRIMARY KEY (guild_id, word))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER, reporter_id INTEGER, reported_id INTEGER,
            reason TEXT, created_at REAL)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS economy (
            user_id INTEGER, guild_id INTEGER,
            wallet INTEGER DEFAULT 150, bank INTEGER DEFAULT 0,
            last_daily REAL DEFAULT 0, last_work REAL DEFAULT 0,
            last_crime REAL DEFAULT 0, last_rob REAL DEFAULT 0,
            PRIMARY KEY (user_id, guild_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER, guild_id INTEGER,
            banner TEXT, bio TEXT, color INTEGER DEFAULT 16766720,
            PRIMARY KEY (user_id, guild_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER,
            name TEXT, price INTEGER, description TEXT, role_id INTEGER)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER, guild_id INTEGER, item_id INTEGER, quantity INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, guild_id, item_id))""")
        await db.commit()

# ——— Guild ———
async def get_guild_settings(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM guilds WHERE guild_id=?", (guild_id,)) as c:
            r = await c.fetchone()
            if not r: return None
            return {"unverified_role_id": r[1], "verified_role_id": r[2], "muted_role_id": r[3],
                    "verify_channel_id": r[4], "welcome_channel_id": r[5], "log_channel_id": r[6],
                    "mod_log_channel_id": r[7], "verify_timeout": r[8] or 15}

async def set_guild_settings(guild_id: int, **kwargs):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM guilds WHERE guild_id=?", (guild_id,)) as c:
            exists = await c.fetchone()
        if exists:
            sets = ", ".join(f"{k}=?" for k in kwargs)
            await db.execute(f"UPDATE guilds SET {sets} WHERE guild_id=?", list(kwargs.values()) + [guild_id])
        else:
            cols = ["guild_id"] + list(kwargs)
            await db.execute(f"INSERT INTO guilds ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
                             [guild_id] + list(kwargs.values()))
        await db.commit()

async def add_pending(uid, gid, t):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO pending_verifications VALUES (?,?,?)", (uid, gid, t))
        await db.commit()

async def remove_pending(uid, gid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM pending_verifications WHERE user_id=? AND guild_id=?", (uid, gid))
        await db.commit()

async def get_pending(gid=None):
    async with aiosqlite.connect(DB_PATH) as db:
        q = "SELECT user_id,guild_id,joined_at FROM pending_verifications"
        if gid:
            async with db.execute(q + " WHERE guild_id=?", (gid,)) as c: return await c.fetchall()
        async with db.execute(q) as c: return await c.fetchall()

async def add_channel_mute(uid, gid, cid, reason, by, t):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO channel_mutes VALUES (?,?,?,?,?,?)", (uid, gid, cid, reason, by, t))
        await db.commit()

async def remove_channel_mute(uid, gid, cid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM channel_mutes WHERE user_id=? AND guild_id=? AND channel_id=?", (uid, gid, cid))
        await db.commit()

async def add_bad_word(gid, word):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO bad_words VALUES (?,?)", (gid, word.lower()))
        await db.commit()

async def remove_bad_word(gid, word):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bad_words WHERE guild_id=? AND word=?", (gid, word.lower()))
        await db.commit()

async def get_bad_words(gid) -> List[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT word FROM bad_words WHERE guild_id=?", (gid,)) as c:
            return [r[0] for r in await c.fetchall()]

async def add_report(gid, reporter, reported, reason, t):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO reports (guild_id,reporter_id,reported_id,reason,created_at) VALUES (?,?,?,?,?)",
                         (gid, reporter, reported, reason, t))
        await db.commit()

# ——— Economy ———
async def ensure_user(uid, gid, start=150):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM economy WHERE user_id=? AND guild_id=?", (uid, gid)) as c:
            if not await c.fetchone():
                await db.execute("INSERT INTO economy (user_id,guild_id,wallet) VALUES (?,?,?)", (uid, gid, start))
                await db.commit()

async def get_balance(uid, gid) -> Tuple[int, int]:
    await ensure_user(uid, gid)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT wallet,bank FROM economy WHERE user_id=? AND guild_id=?", (uid, gid)) as c:
            r = await c.fetchone()
            return (r[0], r[1]) if r else (0, 0)

async def add_money(uid, gid, amount):
    await ensure_user(uid, gid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE economy SET wallet=wallet+? WHERE user_id=? AND guild_id=?", (amount, uid, gid))
        await db.commit()

async def add_bank(uid, gid, amount):
    await ensure_user(uid, gid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE economy SET bank=bank+? WHERE user_id=? AND guild_id=?", (amount, uid, gid))
        await db.commit()

async def transfer(fid, tid, gid, amount) -> bool:
    w, _ = await get_balance(fid, gid)
    if w < amount: return False
    await add_money(fid, gid, -amount)
    await add_money(tid, gid, amount)
    return True

async def get_cd(uid, gid, field) -> float:
    await ensure_user(uid, gid)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT {field} FROM economy WHERE user_id=? AND guild_id=?", (uid, gid)) as c:
            r = await c.fetchone()
            return r[0] if r else 0.0

async def set_cd(uid, gid, field, val):
    await ensure_user(uid, gid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE economy SET {field}=? WHERE user_id=? AND guild_id=?", (val, uid, gid))
        await db.commit()

async def get_top(gid, limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id,wallet,bank FROM economy WHERE guild_id=? ORDER BY (wallet+bank) DESC LIMIT ?",
            (gid, limit)) as c:
            return await c.fetchall()

# ——— Profiles ———
async def ensure_profile(uid, gid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM profiles WHERE user_id=? AND guild_id=?", (uid, gid)) as c:
            if not await c.fetchone():
                await db.execute("INSERT INTO profiles (user_id,guild_id) VALUES (?,?)", (uid, gid))
                await db.commit()

async def get_profile(uid, gid) -> dict:
    await ensure_profile(uid, gid)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT banner,bio,color FROM profiles WHERE user_id=? AND guild_id=?", (uid, gid)) as c:
            r = await c.fetchone()
            return {"banner": r[0], "bio": r[1], "color": r[2] or 0xFEE75C} if r else {"banner": None, "bio": None, "color": 0xFEE75C}

async def set_profile_banner(uid, gid, url: Optional[str]):
    await ensure_profile(uid, gid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE profiles SET banner=? WHERE user_id=? AND guild_id=?", (url, uid, gid))
        await db.commit()

async def set_profile_bio(uid, gid, bio: Optional[str]):
    await ensure_profile(uid, gid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE profiles SET bio=? WHERE user_id=? AND guild_id=?", (bio, uid, gid))
        await db.commit()

async def set_profile_color(uid, gid, color: int):
    await ensure_profile(uid, gid)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE profiles SET color=? WHERE user_id=? AND guild_id=?", (color, uid, gid))
        await db.commit()

# ——— Shop ———
async def add_shop_item(gid, name, price, desc="", role_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO shop_items (guild_id,name,price,description,role_id) VALUES (?,?,?,?,?)",
                         (gid, name, price, desc, role_id))
        await db.commit()

async def remove_shop_item(iid, gid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM shop_items WHERE id=? AND guild_id=?", (iid, gid))
        await db.commit()

async def get_shop(gid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id,name,price,description,role_id FROM shop_items WHERE guild_id=? ORDER BY price", (gid,)) as c:
            return await c.fetchall()

async def get_item(iid, gid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id,name,price,description,role_id FROM shop_items WHERE id=? AND guild_id=?", (iid, gid)) as c:
            return await c.fetchone()

async def add_inv(uid, gid, iid, qty=1):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT quantity FROM inventory WHERE user_id=? AND guild_id=? AND item_id=?", (uid, gid, iid)) as c:
            r = await c.fetchone()
        if r:
            await db.execute("UPDATE inventory SET quantity=quantity+? WHERE user_id=? AND guild_id=? AND item_id=?", (qty, uid, gid, iid))
        else:
            await db.execute("INSERT INTO inventory VALUES (?,?,?,?)", (uid, gid, iid, qty))
        await db.commit()

async def get_inv(uid, gid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""SELECT i.item_id,s.name,i.quantity,s.description FROM inventory i
            JOIN shop_items s ON i.item_id=s.id WHERE i.user_id=? AND i.guild_id=?""", (uid, gid)) as c:
            return await c.fetchall()
