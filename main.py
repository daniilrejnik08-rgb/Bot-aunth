import discord
from discord.ext import commands, tasks
from discord import app_commands
import time, asyncio, random, re
from datetime import datetime, timezone
from collections import defaultdict

from config import *
from database import *

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
spam_tracker = defaultdict(lambda: defaultdict(list))


def fmt(sec: float) -> str:
    sec = int(max(0, sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    if h: return f"{h}ч {m}м"
    if m: return f"{m}м {s}с"
    return f"{s}с"


def is_valid_image_url(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    return any(url.lower().split("?")[0].endswith(ext) for ext in (
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".gifv"
    )) or "imgur" in url or "tenor" in url or "giphy" in url or "discord" in url or "media" in url


async def modlog(guild, embed):
    s = await get_guild_settings(guild.id)
    if not s: return
    cid = s.get("mod_log_channel_id") or s.get("log_channel_id")
    if cid:
        ch = guild.get_channel(cid)
        if ch:
            try: await ch.send(embed=embed)
            except: pass


async def mute_role(member, reason="Мут"):
    s = await get_guild_settings(member.guild.id)
    if not s or not s.get("muted_role_id"): return False
    role = member.guild.get_role(s["muted_role_id"])
    if not role: return False
    try:
        await member.add_roles(role, reason=reason)
        return True
    except: return False


async def unmute_role(member, reason="Размут"):
    s = await get_guild_settings(member.guild.id)
    if not s or not s.get("muted_role_id"): return False
    role = member.guild.get_role(s["muted_role_id"])
    if not role: return False
    try:
        await member.remove_roles(role, reason=reason)
        return True
    except: return False


async def build_profile_embed(member: discord.Member) -> discord.Embed:
    w, b = await get_balance(member.id, member.guild.id)
    prof = await get_profile(member.id, member.guild.id)
    color = prof["color"] or GOLD

    emb = discord.Embed(color=color, timestamp=datetime.now(timezone.utc))
    emb.set_author(name=member.display_name, icon_url=member.display_avatar.url)

    if prof["bio"]:
        emb.description = f"*{prof['bio']}*"

    emb.add_field(name="Кошелёк", value=f"```{w:,} {CURRENCY}```", inline=True)
    emb.add_field(name="Банк", value=f"```{b:,} {CURRENCY}```", inline=True)
    emb.add_field(name="Всего", value=f"```{w + b:,} {CURRENCY}```", inline=True)

    emb.set_thumbnail(url=member.display_avatar.url)

    if prof["banner"]:
        emb.set_image(url=prof["banner"])

    joined = discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "—"
    emb.set_footer(text=f"На сервере {joined}  •  ID: {member.id}")
    return emb


# ═══════════════════ PROFILE + ECO PANEL ═══════════════════

class ProfileView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=180)
        self.owner_id = owner_id

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.owner_id:
            await inter.response.send_message("Это чужой профиль.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Daily", emoji="🎁", style=discord.ButtonStyle.success, row=0)
    async def daily(self, inter: discord.Interaction, _):
        last = await get_cd(inter.user.id, inter.guild.id, "last_daily")
        left = DAILY_COOLDOWN - (time.time() - last)
        if left > 0:
            return await inter.response.send_message(f"⏳ Через **{fmt(left)}**", ephemeral=True)
        amount = random.randint(DAILY_MIN, DAILY_MAX)
        await add_money(inter.user.id, inter.guild.id, amount)
        await set_cd(inter.user.id, inter.guild.id, "last_daily", time.time())
        await inter.response.send_message(
            embed=discord.Embed(title="🎁 Daily", description=f"+**{amount:,}** {CURRENCY}", color=GREEN),
            ephemeral=True)
        await inter.message.edit(embed=await build_profile_embed(inter.user), view=self)

    @discord.ui.button(label="Work", emoji="💼", style=discord.ButtonStyle.primary, row=0)
    async def work(self, inter: discord.Interaction, _):
        last = await get_cd(inter.user.id, inter.guild.id, "last_work")
        left = WORK_COOLDOWN - (time.time() - last)
        if left > 0:
            return await inter.response.send_message(f"⏳ Через **{fmt(left)}**", ephemeral=True)
        jobs = ["программистом", "курьером", "стримером", "поваром", "дизайнером", "таксистом"]
        amount = random.randint(WORK_MIN, WORK_MAX)
        await add_money(inter.user.id, inter.guild.id, amount)
        await set_cd(inter.user.id, inter.guild.id, "last_work", time.time())
        await inter.response.send_message(
            embed=discord.Embed(title="💼 Work", description=f"Работал **{random.choice(jobs)}**\n+**{amount:,}** {CURRENCY}", color=BLURPLE),
            ephemeral=True)
        await inter.message.edit(embed=await build_profile_embed(inter.user), view=self)

    @discord.ui.button(label="Crime", emoji="🔫", style=discord.ButtonStyle.danger, row=0)
    async def crime(self, inter: discord.Interaction, _):
        last = await get_cd(inter.user.id, inter.guild.id, "last_crime")
        left = CRIME_COOLDOWN - (time.time() - last)
        if left > 0:
            return await inter.response.send_message(f"⏳ Через **{fmt(left)}**", ephemeral=True)
        await set_cd(inter.user.id, inter.guild.id, "last_crime", time.time())
        if random.randint(1, 100) <= CRIME_CHANCE:
            amount = random.randint(CRIME_MIN, CRIME_MAX)
            await add_money(inter.user.id, inter.guild.id, amount)
            emb = discord.Embed(title="🔫 Успех", description=f"+**{amount:,}** {CURRENCY}", color=GREEN)
        else:
            await add_money(inter.user.id, inter.guild.id, -CRIME_FAIL)
            emb = discord.Embed(title="🚔 Поймали", description=f"Штраф **{CRIME_FAIL}** {CURRENCY}", color=RED)
        await inter.response.send_message(embed=emb, ephemeral=True)
        await inter.message.edit(embed=await build_profile_embed(inter.user), view=self)

    @discord.ui.button(label="Банк", emoji="🏦", style=discord.ButtonStyle.secondary, row=1)
    async def bank(self, inter: discord.Interaction, _):
        await inter.response.send_modal(BankModal())

    @discord.ui.button(label="Магазин", emoji="🛒", style=discord.ButtonStyle.secondary, row=1)
    async def shop(self, inter: discord.Interaction, _):
        items = await get_shop(inter.guild.id)
        if not items:
            return await inter.response.send_message("Магазин пуст. Админ: `/additem`", ephemeral=True)
        options = [discord.SelectOption(
            label=f"{name} — {price} {CURRENCY}"[:100],
            value=str(iid),
            description=(desc or "")[:100]
        ) for iid, name, price, desc, _ in items[:25]]
        view = discord.ui.View(timeout=60)
        select = discord.ui.Select(placeholder="Выбери товар...", options=options)

        async def cb(i: discord.Interaction):
            item = await get_item(int(select.values[0]), i.guild.id)
            if not item:
                return await i.response.send_message("Не найден.", ephemeral=True)
            _, name, price, _, role_id = item
            w, _ = await get_balance(i.user.id, i.guild.id)
            if w < price:
                return await i.response.send_message(f"Нужно **{price}** {CURRENCY}", ephemeral=True)
            await add_money(i.user.id, i.guild.id, -price)
            if role_id:
                role = i.guild.get_role(role_id)
                if role:
                    try: await i.user.add_roles(role, reason=f"Покупка {name}")
                    except:
                        await add_money(i.user.id, i.guild.id, price)
                        return await i.response.send_message("Нет прав на роль.", ephemeral=True)
            else:
                await add_inv(i.user.id, i.guild.id, item[0])
            await i.response.send_message(
                embed=discord.Embed(title="🛒 Куплено", description=f"**{name}** за **{price}** {CURRENCY}", color=GREEN),
                ephemeral=True)

        select.callback = cb
        view.add_item(select)
        await inter.response.send_message(embed=discord.Embed(title="🛒 Магазин", color=PINK), view=view, ephemeral=True)

    @discord.ui.button(label="Настроить", emoji="🎨", style=discord.ButtonStyle.secondary, row=1)
    async def customize(self, inter: discord.Interaction, _):
        await inter.response.send_message(
            embed=discord.Embed(
                title="🎨 Кастомизация профиля",
                description=(
                    f"**Баннер (GIF/картинка)** — `{PRICE_BANNER}` {CURRENCY}\n`/setbanner <ссылка>`\n\n"
                    f"**Описание** — `{PRICE_BIO}` {CURRENCY}\n`/setbio <текст>`\n\n"
                    f"**Цвет полоски** — `{PRICE_COLOR}` {CURRENCY}\n`/setcolor #FFAA00`\n\n"
                    f"**Сбросить баннер** — бесплатно\n`/setbanner none`"
                ),
                color=BLURPLE
            ),
            ephemeral=True
        )


class BankModal(discord.ui.Modal, title="Банк"):
    amount = discord.ui.TextInput(label="Сумма (или all)", placeholder="100 / all", required=True)
    action = discord.ui.TextInput(label="Действие: deposit или withdraw", placeholder="deposit", required=True, max_length=10)

    async def on_submit(self, inter: discord.Interaction):
        w, b = await get_balance(inter.user.id, inter.guild.id)
        raw = self.amount.value.strip().lower()
        act = self.action.value.strip().lower()
        try:
            amt = w if (act.startswith("d") and raw == "all") else b if (act.startswith("w") and raw == "all") else int(raw)
        except:
            return await inter.response.send_message("Неверная сумма.", ephemeral=True)
        if amt <= 0:
            return await inter.response.send_message("Сумма > 0", ephemeral=True)

        if act.startswith("d"):
            if amt > w:
                return await inter.response.send_message("Мало в кошельке.", ephemeral=True)
            await add_money(inter.user.id, inter.guild.id, -amt)
            await add_bank(inter.user.id, inter.guild.id, amt)
            emb = discord.Embed(title="🏦 Депозит", description=f"**{amt:,}** {CURRENCY} → банк", color=GREEN)
        elif act.startswith("w"):
            if amt > b:
                return await inter.response.send_message("Мало в банке.", ephemeral=True)
            await add_bank(inter.user.id, inter.guild.id, -amt)
            await add_money(inter.user.id, inter.guild.id, amt)
            emb = discord.Embed(title="💸 Снятие", description=f"**{amt:,}** {CURRENCY} ← банк", color=GREEN)
        else:
            return await inter.response.send_message("Пиши `deposit` или `withdraw`", ephemeral=True)
        await inter.response.send_message(embed=emb, ephemeral=True)


# ═══════════════════ VERIFY ═══════════════════

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Пройти верификацию", style=discord.ButtonStyle.success, emoji="✅", custom_id="verify_btn")
    async def verify(self, inter: discord.Interaction, _):
        g, m = inter.guild, inter.user
        s = await get_guild_settings(g.id)
        if not s or not s["verified_role_id"]:
            return await inter.response.send_message("Не настроено.", ephemeral=True)
        vrole = g.get_role(s["verified_role_id"])
        urole = g.get_role(s["unverified_role_id"]) if s["unverified_role_id"] else None
        if vrole in m.roles:
            return await inter.response.send_message("Уже верифицирован!", ephemeral=True)
        try:
            await m.add_roles(vrole, reason="Верификация")
            if urole and urole in m.roles:
                await m.remove_roles(urole, reason="Верификация")
        except discord.Forbidden:
            return await inter.response.send_message(
                embed=discord.Embed(title="Нет прав", description="Подними роль бота **выше** выдаваемых ролей.", color=RED),
                ephemeral=True)

        await remove_pending(m.id, g.id)
        await ensure_user(m.id, g.id, START_BALANCE)

        wch = g.get_channel(s["welcome_channel_id"]) if s["welcome_channel_id"] else None
        if wch:
            emb = discord.Embed(title="✨ Добро пожаловать!", description=f"{m.mention}, рады тебя видеть!", color=PINK)
            emb.set_thumbnail(url=m.display_avatar.url)
            if g.icon: emb.set_author(name=g.name, icon_url=g.icon.url)
            emb.set_footer(text=f"#{g.member_count}  •  +{START_BALANCE} {CURRENCY}")
            await wch.send(embed=emb)

        try:
            await m.send(embed=discord.Embed(
                title=f"Добро пожаловать на {g.name}",
                description=f"Верификация пройдена.\nСтартовый баланс: **{START_BALANCE}** {CURRENCY}\n\nНастрой профиль: `/profile`",
                color=PINK))
        except: pass

        lch = g.get_channel(s["log_channel_id"]) if s["log_channel_id"] else None
        if lch:
            e = discord.Embed(title="✅ Верификация", color=GREEN, timestamp=datetime.now(timezone.utc))
            e.add_field(name="Участник", value=f"{m.mention}\n`{m.id}`")
            e.set_thumbnail(url=m.display_avatar.url)
            await lch.send(embed=e)

        await inter.response.send_message(embed=discord.Embed(title="Готово! 🎉", color=GREEN), ephemeral=True)


class ReportModal(discord.ui.Modal, title="Жалоба"):
    reason = discord.ui.TextInput(label="Что произошло?", style=discord.TextStyle.paragraph, max_length=1000)
    def __init__(self, target): super().__init__(); self.target = target
    async def on_submit(self, inter: discord.Interaction):
        await add_report(inter.guild.id, inter.user.id, self.target.id, self.reason.value, time.time())
        e = discord.Embed(title="🚨 Жалоба", color=GOLD, timestamp=datetime.now(timezone.utc))
        e.add_field(name="От", value=inter.user.mention, inline=True)
        e.add_field(name="На", value=self.target.mention, inline=True)
        e.add_field(name="Причина", value=self.reason.value, inline=False)
        e.set_thumbnail(url=self.target.display_avatar.url)
        await modlog(inter.guild, e)
        await inter.response.send_message(embed=discord.Embed(title="Отправлено", color=GREEN), ephemeral=True)


# ═══════════════════ EVENTS ═══════════════════

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(VerifyView())
    print(f"✅ {bot.user} | серверов: {len(bot.guilds)}")
    check_timeouts.start()
    try: print(f"🔄 {len(await bot.tree.sync())} команд")
    except Exception as e: print(e)


@bot.event
async def on_member_join(member: discord.Member):
    if member.bot: return
    s = await get_guild_settings(member.guild.id)
    if not s: return
    if s.get("unverified_role_id"):
        role = member.guild.get_role(s["unverified_role_id"])
        if role:
            try: await member.add_roles(role, reason="Новый")
            except: pass
    await add_pending(member.id, member.guild.id, time.time())
    ch = member.guild.get_channel(s["verify_channel_id"]) if s.get("verify_channel_id") else None
    if ch:
        emb = discord.Embed(title="🔐 Верификация", description=f"Привет, {member.mention}!\nНажми кнопку.\n⏱ **{s['verify_timeout']} мин.**", color=BLURPLE)
        emb.set_thumbnail(url=member.display_avatar.url)
        await ch.send(content=member.mention, embed=emb, view=VerifyView())


@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot or not msg.guild: return
    now = time.time()
    t = spam_tracker[msg.guild.id][msg.author.id]
    t.append(now)
    t[:] = [x for x in t if now - x < SPAM_SECONDS]
    if len(t) >= SPAM_MESSAGES:
        spam_tracker[msg.guild.id][msg.author.id].clear()
        try: await msg.delete()
        except: pass
        await mute_role(msg.author, "Антиспам")
        async def au():
            await asyncio.sleep(SPAM_MUTE_MINUTES * 60)
            await unmute_role(msg.author)
        bot.loop.create_task(au())
        return
    if len(msg.mentions) >= MAX_MENTIONS or msg.mention_everyone:
        try: await msg.delete()
        except: pass
        await mute_role(msg.author, "Антирассылка")
        return
    words = await get_bad_words(msg.guild.id)
    if words and any(w in msg.content.lower() for w in words):
        try: await msg.delete()
        except: pass
        if BAD_WORDS_ACTION in ("mute", "both"):
            await mute_role(msg.author, "Плохие слова")
        return
    await bot.process_commands(msg)


@tasks.loop(minutes=1)
async def check_timeouts():
    for uid, gid, joined in await get_pending():
        s = await get_guild_settings(gid)
        to = (s["verify_timeout"] if s else VERIFY_TIMEOUT) * 60
        if time.time() - joined > to:
            g = bot.get_guild(gid)
            if g and (m := g.get_member(uid)):
                try:
                    await m.kick(reason="Не прошёл верификацию")
                    await modlog(g, discord.Embed(title="Кик", description=str(m), color=GOLD))
                except: pass
            await remove_pending(uid, gid)


# ═══════════════════ COMMANDS ═══════════════════

@bot.tree.command(name="profile", description="💎 Красивый профиль")
@app_commands.describe(member="Чей профиль посмотреть")
async def profile(inter: discord.Interaction, member: discord.Member = None):
    member = member or inter.user
    emb = await build_profile_embed(member)
    view = ProfileView(member.id) if member.id == inter.user.id else None
    await inter.response.send_message(embed=emb, view=view)


@bot.tree.command(name="setbanner", description="🖼 Баннер профиля (GIF) — платно")
@app_commands.describe(url="Ссылка на GIF/картинку или none")
async def setbanner(inter: discord.Interaction, url: str):
    if url.lower() in ("none", "удалить", "remove", "clear"):
        await set_profile_banner(inter.user.id, inter.guild.id, None)
        return await inter.response.send_message(embed=discord.Embed(title="Баннер убран", color=GREEN), ephemeral=True)

    if not is_valid_image_url(url):
        return await inter.response.send_message(
            embed=discord.Embed(
                title="Неверная ссылка",
                description="Нужна прямая ссылка на `.png` `.jpg` `.gif` `.webp`\nИли Imgur / Tenor / Discord CDN",
                color=RED
            ),
            ephemeral=True
        )

    w, _ = await get_balance(inter.user.id, inter.guild.id)
    if w < PRICE_BANNER:
        return await inter.response.send_message(
            embed=discord.Embed(title="Недостаточно средств", description=f"Нужно **{PRICE_BANNER}** {CURRENCY}, у тебя **{w}**", color=RED),
            ephemeral=True
        )

    await add_money(inter.user.id, inter.guild.id, -PRICE_BANNER)
    await set_profile_banner(inter.user.id, inter.guild.id, url)
    emb = discord.Embed(title="🖼 Баннер установлен", description=f"Списано **{PRICE_BANNER}** {CURRENCY}", color=GREEN)
    emb.set_image(url=url)
    await inter.response.send_message(embed=emb, ephemeral=True)


@bot.tree.command(name="setbio", description="✏️ Описание профиля — платно")
@app_commands.describe(text="Текст (до 150 символов) или none")
async def setbio(inter: discord.Interaction, text: str):
    if text.lower() in ("none", "удалить", "remove", "clear"):
        await set_profile_bio(inter.user.id, inter.guild.id, None)
        return await inter.response.send_message("Описание убрано.", ephemeral=True)

    w, _ = await get_balance(inter.user.id, inter.guild.id)
    if w < PRICE_BIO:
        return await inter.response.send_message(
            embed=discord.Embed(title="Недостаточно средств", description=f"Нужно **{PRICE_BIO}** {CURRENCY}", color=RED),
            ephemeral=True
        )

    text = text[:150]
    await add_money(inter.user.id, inter.guild.id, -PRICE_BIO)
    await set_profile_bio(inter.user.id, inter.guild.id, text)
    await inter.response.send_message(
        embed=discord.Embed(title="✏️ Био обновлено", description=f"*{text}*\n\nСписано **{PRICE_BIO}** {CURRENCY}", color=GREEN),
        ephemeral=True
    )


@bot.tree.command(name="setcolor", description="🎨 Цвет профиля — платно")
@app_commands.describe(color="HEX, например #FF55AA")
async def setcolor(inter: discord.Interaction, color: str):
    color = color.strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", color):
        return await inter.response.send_message("Нужен HEX из 6 символов, например `FF55AA`", ephemeral=True)

    w, _ = await get_balance(inter.user.id, inter.guild.id)
    if w < PRICE_COLOR:
        return await inter.response.send_message(
            embed=discord.Embed(title="Недостаточно средств", description=f"Нужно **{PRICE_COLOR}** {CURRENCY}", color=RED),
            ephemeral=True
        )

    value = int(color, 16)
    await add_money(inter.user.id, inter.guild.id, -PRICE_COLOR)
    await set_profile_color(inter.user.id, inter.guild.id, value)
    emb = discord.Embed(title="🎨 Цвет установлен", description=f"`#{color.upper()}`\nСписано **{PRICE_COLOR}** {CURRENCY}", color=value)
    await inter.response.send_message(embed=emb, ephemeral=True)


@bot.tree.command(name="pay", description="Перевести деньги")
@app_commands.describe(member="Кому", amount="Сумма")
async def pay(inter: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0 or member.bot or member == inter.user:
        return await inter.response.send_message("Нельзя.", ephemeral=True)
    if not await transfer(inter.user.id, member.id, inter.guild.id, amount):
        return await inter.response.send_message("Недостаточно средств.", ephemeral=True)
    await inter.response.send_message(embed=discord.Embed(
        title="💸 Перевод", description=f"{inter.user.mention} → {member.mention}\n**{amount:,}** {CURRENCY}", color=GREEN))


@bot.tree.command(name="rob", description="Ограбить")
@app_commands.describe(member="Жертва")
async def rob(inter: discord.Interaction, member: discord.Member):
    if member.bot or member == inter.user:
        return await inter.response.send_message("Нельзя.", ephemeral=True)
    last = await get_cd(inter.user.id, inter.guild.id, "last_rob")
    left = ROB_COOLDOWN - (time.time() - last)
    if left > 0:
        return await inter.response.send_message(f"⏳ Через **{fmt(left)}**", ephemeral=True)
    tw, _ = await get_balance(member.id, inter.guild.id)
    if tw < ROB_MIN:
        return await inter.response.send_message("Мало денег у жертвы.", ephemeral=True)
    await set_cd(inter.user.id, inter.guild.id, "last_rob", time.time())
    if random.randint(1, 100) <= ROB_CHANCE:
        amt = random.randint(ROB_MIN, max(ROB_MIN, int(tw * 0.25)))
        await add_money(member.id, inter.guild.id, -amt)
        await add_money(inter.user.id, inter.guild.id, amt)
        emb = discord.Embed(title="🔫 Успех", description=f"**{amt:,}** {CURRENCY} у {member.mention}", color=GREEN)
    else:
        fine = random.randint(40, 120)
        await add_money(inter.user.id, inter.guild.id, -fine)
        emb = discord.Embed(title="🚔 Неудача", description=f"Штраф **{fine}** {CURRENCY}", color=RED)
    await inter.response.send_message(embed=emb)


@bot.tree.command(name="top", description="Топ богачей")
async def top(inter: discord.Interaction):
    rows = await get_top(inter.guild.id)
    if not rows:
        return await inter.response.send_message("Пусто.", ephemeral=True)
    lines = []
    for i, (uid, w, b) in enumerate(rows, 1):
        m = inter.guild.get_member(uid)
        name = m.display_name if m else f"ID {uid}"
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"`{i}.`")
        lines.append(f"{medal} **{name}** — {(w+b):,} {CURRENCY}")
    await inter.response.send_message(embed=discord.Embed(title="🏆 Топ", description="\n".join(lines), color=GOLD))


@bot.tree.command(name="gamble", description="Казино")
@app_commands.describe(game="Игра", amount="Ставка")
@app_commands.choices(game=[
    app_commands.Choice(name="Монетка x2", value="coin"),
    app_commands.Choice(name="Слоты x2–x5", value="slots")
])
async def gamble(inter: discord.Interaction, game: app_commands.Choice[str], amount: int):
    if amount <= 0:
        return await inter.response.send_message("Ставка > 0", ephemeral=True)
    w, _ = await get_balance(inter.user.id, inter.guild.id)
    if w < amount:
        return await inter.response.send_message("Недостаточно.", ephemeral=True)
    if game.value == "coin":
        if random.choice([True, False]):
            await add_money(inter.user.id, inter.guild.id, amount)
            emb = discord.Embed(title="🪙 Победа", description=f"+**{amount:,}** {CURRENCY}", color=GREEN)
        else:
            await add_money(inter.user.id, inter.guild.id, -amount)
            emb = discord.Embed(title="🪙 Проигрыш", description=f"-**{amount:,}** {CURRENCY}", color=RED)
    else:
        icons = ["🍒", "🍋", "🍇", "⭐", "💎"]
        roll = [random.choice(icons) for _ in range(3)]
        show = " │ ".join(roll)
        if len(set(roll)) == 1:
            win = amount * 5
            await add_money(inter.user.id, inter.guild.id, win)
            emb = discord.Embed(title="🎰 ДЖЕКПОТ", description=f"**{show}**\n+**{win:,}** {CURRENCY}", color=GREEN)
        elif roll[0] == roll[1] or roll[1] == roll[2]:
            win = amount * 2
            await add_money(inter.user.id, inter.guild.id, win)
            emb = discord.Embed(title="🎰 Победа", description=f"**{show}**\n+**{win:,}** {CURRENCY}", color=GREEN)
        else:
            await add_money(inter.user.id, inter.guild.id, -amount)
            emb = discord.Embed(title="🎰 Мимо", description=f"**{show}**\n-**{amount:,}** {CURRENCY}", color=RED)
    await inter.response.send_message(embed=emb)


@bot.tree.command(name="inventory", description="Инвентарь")
async def inventory(inter: discord.Interaction):
    items = await get_inv(inter.user.id, inter.guild.id)
    if not items:
        return await inter.response.send_message(embed=discord.Embed(title="Пусто", color=BLURPLE), ephemeral=True)
    text = "\n".join(f"**{n}** ×{q}" for _, n, q, _ in items)
    await inter.response.send_message(embed=discord.Embed(title=f"🎒 {inter.user.display_name}", description=text, color=PINK))


@bot.tree.command(name="mute", description="Мут")
@app_commands.describe(member="Кого", reason="Причина", channel="Канал")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute_cmd(inter: discord.Interaction, member: discord.Member, reason: str = "—", channel: discord.TextChannel = None):
    if member.top_role >= inter.user.top_role and inter.user != inter.guild.owner:
        return await inter.response.send_message("Нельзя.", ephemeral=True)
    if channel:
        ow = channel.overwrites_for(member)
        ow.send_messages = False
        try:
            await channel.set_permissions(member, overwrite=ow, reason=reason)
            await add_channel_mute(member.id, inter.guild.id, channel.id, reason, inter.user.id, time.time())
        except: return await inter.response.send_message("Нет прав.", ephemeral=True)
        emb = discord.Embed(title="🔇 Мут в канале", description=f"{member.mention} → {channel.mention}", color=GOLD)
    else:
        if not await mute_role(member, reason):
            return await inter.response.send_message("Роль мута не настроена.", ephemeral=True)
        emb = discord.Embed(title="🔇 Мут", description=member.mention, color=GOLD)
    emb.add_field(name="Причина", value=reason)
    await modlog(inter.guild, emb)
    await inter.response.send_message(embed=emb)


@bot.tree.command(name="unmute", description="Размут")
@app_commands.describe(member="Кого", channel="Канал")
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute_cmd(inter: discord.Interaction, member: discord.Member, channel: discord.TextChannel = None):
    if channel:
        try:
            await channel.set_permissions(member, overwrite=None)
            await remove_channel_mute(member.id, inter.guild.id, channel.id)
        except: return await inter.response.send_message("Нет прав.", ephemeral=True)
        emb = discord.Embed(title="🔊 Размут", description=f"{member.mention}", color=GREEN)
    else:
        if not await unmute_role(member):
            return await inter.response.send_message("Не удалось.", ephemeral=True)
        emb = discord.Embed(title="🔊 Размут", description=member.mention, color=GREEN)
    await modlog(inter.guild, emb)
    await inter.response.send_message(embed=emb)


@bot.tree.command(name="report", description="Жалоба")
async def report(inter: discord.Interaction, member: discord.Member):
    if member.bot or member == inter.user:
        return await inter.response.send_message("Нельзя.", ephemeral=True)
    await inter.response.send_modal(ReportModal(member))


@bot.tree.command(name="additem", description="Товар в магазин")
@app_commands.describe(name="Название", price="Цена", description="Описание", role="Роль")
@app_commands.checks.has_permissions(administrator=True)
async def additem(inter: discord.Interaction, name: str, price: int, description: str = "", role: discord.Role = None):
    await add_shop_item(inter.guild.id, name, price, description, role.id if role else None)
    emb = discord.Embed(title="🛒 Добавлено", description=f"**{name}** — {price} {CURRENCY}", color=GREEN)
    if role: emb.add_field(name="Роль", value=role.mention)
    await inter.response.send_message(embed=emb)


@bot.tree.command(name="setup", description="Настройка")
@app_commands.checks.has_permissions(administrator=True)
async def setup(inter: discord.Interaction,
                unverified_role: discord.Role = None, verified_role: discord.Role = None,
                muted_role: discord.Role = None, verify_channel: discord.TextChannel = None,
                welcome_channel: discord.TextChannel = None, log_channel: discord.TextChannel = None,
                mod_log_channel: discord.TextChannel = None, timeout: int = 15):
    data = {}
    if unverified_role: data["unverified_role_id"] = unverified_role.id
    if verified_role: data["verified_role_id"] = verified_role.id
    if muted_role: data["muted_role_id"] = muted_role.id
    if verify_channel: data["verify_channel_id"] = verify_channel.id
    if welcome_channel: data["welcome_channel_id"] = welcome_channel.id
    if log_channel: data["log_channel_id"] = log_channel.id
    if mod_log_channel: data["mod_log_channel_id"] = mod_log_channel.id
    data["verify_timeout"] = timeout
    await set_guild_settings(inter.guild.id, **data)
    await inter.response.send_message(embed=discord.Embed(title="✅ Сохранено", color=GREEN), ephemeral=True)


@bot.tree.command(name="send_verify", description="Кнопка верификации")
@app_commands.checks.has_permissions(administrator=True)
async def send_verify(inter: discord.Interaction):
    emb = discord.Embed(title="🔐 Верификация", description="Нажми кнопку, чтобы получить доступ.", color=BLURPLE)
    if inter.guild.icon: emb.set_thumbnail(url=inter.guild.icon.url)
    await inter.channel.send(embed=emb, view=VerifyView())
    await inter.response.send_message("Готово", ephemeral=True)


@bot.tree.command(name="addword", description="Запретить слово")
@app_commands.checks.has_permissions(manage_messages=True)
async def addword(inter: discord.Interaction, word: str):
    await add_bad_word(inter.guild.id, word.strip().lower())
    await inter.response.send_message(f"`{word}` добавлено.", ephemeral=True)


async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
