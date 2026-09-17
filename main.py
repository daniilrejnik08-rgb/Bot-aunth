import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import asyncio
from datetime import datetime, timezone
from collections import defaultdict

from config import (
    TOKEN, VERIFY_TIMEOUT,
    SPAM_MESSAGES, SPAM_SECONDS, SPAM_MUTE_MINUTES,
    MAX_MENTIONS, MAX_EVERYONE, BAD_WORDS_ACTION,
    COLOR_SUCCESS, COLOR_ERROR, COLOR_INFO, COLOR_WARNING,
    COLOR_WELCOME, COLOR_MUTE
)
from database import (
    init_db, get_guild_settings, set_guild_settings,
    add_pending, remove_pending, get_pending,
    add_channel_mute, remove_channel_mute,
    add_bad_word, remove_bad_word, get_bad_words,
    add_report
)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Антиспам: {guild_id: {user_id: [timestamps]}}
spam_tracker = defaultdict(lambda: defaultdict(list))


# ==================== HELPERS ====================

async def send_mod_log(guild: discord.Guild, embed: discord.Embed):
    settings = await get_guild_settings(guild.id)
    if not settings:
        return
    channel_id = settings.get("mod_log_channel_id") or settings.get("log_channel_id")
    if channel_id:
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception:
                pass


async def apply_muted_role(member: discord.Member, reason: str = "Мут"):
    settings = await get_guild_settings(member.guild.id)
    if not settings or not settings.get("muted_role_id"):
        return False
    role = member.guild.get_role(settings["muted_role_id"])
    if not role:
        return False
    try:
        await member.add_roles(role, reason=reason)
        return True
    except discord.Forbidden:
        return False


async def remove_muted_role(member: discord.Member, reason: str = "Размут"):
    settings = await get_guild_settings(member.guild.id)
    if not settings or not settings.get("muted_role_id"):
        return False
    role = member.guild.get_role(settings["muted_role_id"])
    if not role:
        return False
    try:
        await member.remove_roles(role, reason=reason)
        return True
    except discord.Forbidden:
        return False


# ==================== VIEWS ====================

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Пройти верификацию",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="verify_button"
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user
        settings = await get_guild_settings(guild.id)

        if not settings or not settings["verified_role_id"]:
            embed = discord.Embed(title="Ошибка", description="Верификация ещё не настроена.", color=COLOR_ERROR)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        verified_role = guild.get_role(settings["verified_role_id"])
        unverified_role = guild.get_role(settings["unverified_role_id"]) if settings["unverified_role_id"] else None

        if verified_role in member.roles:
            embed = discord.Embed(title="Уже верифицирован", description="Ты уже прошёл верификацию!", color=COLOR_SUCCESS)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        try:
            await member.add_roles(verified_role, reason="Верификация")
            if unverified_role and unverified_role in member.roles:
                await member.remove_roles(unverified_role, reason="Верификация")
        except discord.Forbidden:
            embed = discord.Embed(title="Ошибка прав", description="У бота нет прав выдавать роли.", color=COLOR_ERROR)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await remove_pending(member.id, guild.id)

        welcome_channel = guild.get_channel(settings["welcome_channel_id"]) if settings["welcome_channel_id"] else None
        if welcome_channel:
            embed = discord.Embed(
                title="Добро пожаловать!",
                description=f"Привет, {member.mention}!\n\nРады видеть тебя на **{guild.name}**.",
                color=COLOR_WELCOME,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            if guild.icon:
                embed.set_author(name=guild.name, icon_url=guild.icon.url)
            embed.set_footer(text=f"Участник #{guild.member_count}")
            await welcome_channel.send(embed=embed)

        try:
            dm_embed = discord.Embed(
                title=f"Добро пожаловать на {guild.name}!",
                description=f"Привет, **{member.display_name}**!\n\nТы успешно прошёл верификацию.",
                color=COLOR_WELCOME
            )
            if guild.icon:
                dm_embed.set_thumbnail(url=guild.icon.url)
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        log_channel = guild.get_channel(settings["log_channel_id"]) if settings["log_channel_id"] else None
        if log_channel:
            embed = discord.Embed(title="Верификация пройдена", color=COLOR_SUCCESS, timestamp=datetime.now(timezone.utc))
            embed.add_field(name="Пользователь", value=f"{member.mention}\n`{member}`", inline=True)
            embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
            embed.set_thumbnail(url=member.display_avatar.url)
            await log_channel.send(embed=embed)

        success_embed = discord.Embed(
            title="Верификация пройдена!",
            description=f"Добро пожаловать, {member.mention}!",
            color=COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)


class ReportModal(discord.ui.Modal, title="Жалоба на участника"):
    reason = discord.ui.TextInput(
        label="Причина жалобы",
        style=discord.TextStyle.paragraph,
        placeholder="Опиши, что произошло...",
        required=True,
        max_length=1000
    )

    def __init__(self, reported: discord.Member):
        super().__init__()
        self.reported = reported

    async def on_submit(self, interaction: discord.Interaction):
        await add_report(
            interaction.guild.id,
            interaction.user.id,
            self.reported.id,
            self.reason.value,
            time.time()
        )

        embed = discord.Embed(
            title="Новая жалоба",
            color=COLOR_WARNING,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Кто пожаловался", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=False)
        embed.add_field(name="На кого", value=f"{self.reported.mention} (`{self.reported}`)", inline=False)
        embed.add_field(name="Причина", value=self.reason.value, inline=False)
        embed.set_thumbnail(url=self.reported.display_avatar.url)

        await send_mod_log(interaction.guild, embed)

        confirm = discord.Embed(
            title="Жалоба отправлена",
            description="Модераторы получили твою жалобу. Спасибо!",
            color=COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=confirm, ephemeral=True)


# ==================== EVENTS ====================

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(VerifyView())
    print(f"✅ Бот запущен как {bot.user}")
    print(f"📊 Серверов: {len(bot.guilds)}")
    check_timeouts.start()
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Команд синхронизировано: {len(synced)}")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")


@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return

    settings = await get_guild_settings(member.guild.id)
    if not settings:
        return

    if settings.get("unverified_role_id"):
        role = member.guild.get_role(settings["unverified_role_id"])
        if role:
            try:
                await member.add_roles(role, reason="Новый участник")
            except discord.Forbidden:
                pass

    await add_pending(member.id, member.guild.id, time.time())

    verify_channel = member.guild.get_channel(settings["verify_channel_id"]) if settings.get("verify_channel_id") else None
    if verify_channel:
        embed = discord.Embed(
            title="Требуется верификация",
            description=(
                f"Привет, {member.mention}!\n\n"
                f"Чтобы получить доступ к серверу, нажми кнопку ниже.\n\n"
                f"⏱ У тебя есть **{settings['verify_timeout']} минут**."
            ),
            color=COLOR_INFO
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        if member.guild.icon:
            embed.set_author(name=member.guild.name, icon_url=member.guild.icon.url)
        await verify_channel.send(content=member.mention, embed=embed, view=VerifyView())


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    # ----- Антиспам -----
    now = time.time()
    user_times = spam_tracker[message.guild.id][message.author.id]
    user_times.append(now)
    user_times[:] = [t for t in user_times if now - t < SPAM_SECONDS]

    if len(user_times) >= SPAM_MESSAGES:
        spam_tracker[message.guild.id][message.author.id].clear()
        try:
            await message.delete()
        except Exception:
            pass

        await apply_muted_role(message.author, reason=f"Антиспам ({SPAM_MESSAGES} сообщ. / {SPAM_SECONDS} сек)")
        embed = discord.Embed(
            title="Антиспам",
            description=f"{message.author.mention} получил мут за спам.",
            color=COLOR_MUTE,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Причина", value=f"{SPAM_MESSAGES} сообщений за {SPAM_SECONDS} сек.")
        await send_mod_log(message.guild, embed)

        try:
            await message.channel.send(
                f"{message.author.mention}, слишком быстро пишешь. Мут на {SPAM_MUTE_MINUTES} мин.",
                delete_after=10
            )
        except Exception:
            pass

        async def auto_unmute():
            await asyncio.sleep(SPAM_MUTE_MINUTES * 60)
            await remove_muted_role(message.author, reason="Авторазмут после спама")
        bot.loop.create_task(auto_unmute())
        return

    # ----- Антирассылка -----
    mention_count = len(message.mentions)
    has_everyone = message.mention_everyone

    if mention_count >= MAX_MENTIONS or has_everyone:
        try:
            await message.delete()
        except Exception:
            pass

        await apply_muted_role(message.author, reason="Антирассылка (массовые упоминания)")
        embed = discord.Embed(
            title="Антирассылка",
            description=f"{message.author.mention} попытался сделать массовое упоминание.",
            color=COLOR_ERROR,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Упоминаний", value=str(mention_count))
        embed.add_field(name="@everyone/@here", value="Да" if has_everyone else "Нет")
        await send_mod_log(message.guild, embed)

        try:
            await message.channel.send(
                f"{message.author.mention}, массовые упоминания запрещены.",
                delete_after=8
            )
        except Exception:
            pass
        return

    # ----- Автомод плохих слов -----
    bad_words = await get_bad_words(message.guild.id)
    if bad_words:
        content_lower = message.content.lower()
        found = [w for w in bad_words if w in content_lower]
        if found:
            try:
                await message.delete()
            except Exception:
                pass

            if BAD_WORDS_ACTION in ("mute", "both"):
                await apply_muted_role(message.author, reason=f"Плохие слова: {', '.join(found)}")

            embed = discord.Embed(
                title="Автомод: плохие слова",
                description=f"Сообщение от {message.author.mention} удалено.",
                color=COLOR_WARNING,
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Найденные слова", value=", ".join(f"`{w}`" for w in found))
            embed.add_field(name="Канал", value=message.channel.mention)
            await send_mod_log(message.guild, embed)

            try:
                await message.channel.send(
                    f"{message.author.mention}, такое писать нельзя.",
                    delete_after=6
                )
            except Exception:
                pass
            return

    await bot.process_commands(message)


# ==================== TASKS ====================

@tasks.loop(minutes=1)
async def check_timeouts():
    pending = await get_pending()
    now = time.time()

    for user_id, guild_id, joined_at in pending:
        settings = await get_guild_settings(guild_id)
        timeout = (settings["verify_timeout"] if settings else VERIFY_TIMEOUT) * 60

        if now - joined_at > timeout:
            guild = bot.get_guild(guild_id)
            if not guild:
                await remove_pending(user_id, guild_id)
                continue

            member = guild.get_member(user_id)
            if member:
                try:
                    await member.kick(reason="Не прошёл верификацию вовремя")
                    embed = discord.Embed(
                        title="Кик за отсутствие верификации",
                        description=f"{member} (`{member.id}`)",
                        color=COLOR_WARNING,
                        timestamp=datetime.now(timezone.utc)
                    )
                    await send_mod_log(guild, embed)
                except discord.Forbidden:
                    pass
            await remove_pending(user_id, guild_id)


# ==================== ВЕРИФИКАЦИЯ ====================

@bot.tree.command(name="setup", description="Настроить систему верификации и модерации")
@app_commands.describe(
    unverified_role="Роль неверифицированных",
    verified_role="Роль после верификации",
    muted_role="Роль мута (классический мут)",
    verify_channel="Канал верификации",
    welcome_channel="Канал приветствий",
    log_channel="Канал логов верификации",
    mod_log_channel="Канал логов модерации",
    timeout="Время на верификацию (минуты)"
)
@app_commands.checks.has_permissions(administrator=True)
async def setup(
    interaction: discord.Interaction,
    unverified_role: discord.Role = None,
    verified_role: discord.Role = None,
    muted_role: discord.Role = None,
    verify_channel: discord.TextChannel = None,
    welcome_channel: discord.TextChannel = None,
    log_channel: discord.TextChannel = None,
    mod_log_channel: discord.TextChannel = None,
    timeout: int = 15
):
    data = {}
    if unverified_role:
        data["unverified_role_id"] = unverified_role.id
    if verified_role:
        data["verified_role_id"] = verified_role.id
    if muted_role:
        data["muted_role_id"] = muted_role.id
    if verify_channel:
        data["verify_channel_id"] = verify_channel.id
    if welcome_channel:
        data["welcome_channel_id"] = welcome_channel.id
    if log_channel:
        data["log_channel_id"] = log_channel.id
    if mod_log_channel:
        data["mod_log_channel_id"] = mod_log_channel.id
    data["verify_timeout"] = timeout

    await set_guild_settings(interaction.guild.id, **data)

    embed = discord.Embed(title="Настройки сохранены", color=COLOR_SUCCESS, timestamp=datetime.now(timezone.utc))
    if unverified_role:
        embed.add_field(name="Неверифицирован", value=unverified_role.mention, inline=True)
    if verified_role:
        embed.add_field(name="Участник", value=verified_role.mention, inline=True)
    if muted_role:
        embed.add_field(name="Мут-роль", value=muted_role.mention, inline=True)
    if verify_channel:
        embed.add_field(name="Верификация", value=verify_channel.mention, inline=True)
    if welcome_channel:
        embed.add_field(name="Приветствия", value=welcome_channel.mention, inline=True)
    if log_channel:
        embed.add_field(name="Логи верификации", value=log_channel.mention, inline=True)
    if mod_log_channel:
        embed.add_field(name="Логи модерации", value=mod_log_channel.mention, inline=True)
    embed.add_field(name="Таймаут", value=f"{timeout} мин.", inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="send_verify", description="Отправить сообщение с кнопкой верификации")
@app_commands.checks.has_permissions(administrator=True)
async def send_verify(interaction: discord.Interaction):
    settings = await get_guild_settings(interaction.guild.id)
    if not settings or not settings.get("verified_role_id"):
        embed = discord.Embed(title="Сначала настрой бота", description="Используй `/setup`", color=COLOR_ERROR)
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    embed = discord.Embed(
        title="Верификация",
        description="Нажми кнопку ниже, чтобы получить доступ к серверу.",
        color=COLOR_INFO
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    await interaction.channel.send(embed=embed, view=VerifyView())
    await interaction.response.send_message(embed=discord.Embed(title="Готово", color=COLOR_SUCCESS), ephemeral=True)


# ==================== МОДЕРАЦИЯ: МУТ ====================

@bot.tree.command(name="mute", description="Замутить участника (роль или в одном канале)")
@app_commands.describe(
    member="Кого замутить",
    reason="Причина",
    channel="Если указать — мут только в этом канале"
)
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "Не указана",
    channel: discord.TextChannel = None
):
    if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
        embed = discord.Embed(title="Ошибка", description="Нельзя мутить этого участника.", color=COLOR_ERROR)
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    if channel:
        overwrite = channel.overwrites_for(member)
        overwrite.send_messages = False
        overwrite.add_reactions = False
        try:
            await channel.set_permissions(member, overwrite=overwrite, reason=reason)
            await add_channel_mute(member.id, interaction.guild.id, channel.id, reason, interaction.user.id, time.time())
        except discord.Forbidden:
            embed = discord.Embed(title="Ошибка", description="Нет прав менять права в канале.", color=COLOR_ERROR)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        embed = discord.Embed(
            title="Мут в канале",
            description=f"{member.mention} замучен в {channel.mention}",
            color=COLOR_MUTE,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Причина", value=reason)
        embed.add_field(name="Модератор", value=interaction.user.mention)
        await send_mod_log(interaction.guild, embed)
        await interaction.response.send_message(embed=embed)
    else:
        success = await apply_muted_role(member, reason=reason)
        if not success:
            embed = discord.Embed(
                title="Ошибка",
                description="Роль мута не настроена или нет прав. Используй `/setup` и укажи `muted_role`.",
                color=COLOR_ERROR
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        embed = discord.Embed(
            title="Участник замучен",
            description=f"{member.mention} получил мут.",
            color=COLOR_MUTE,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Причина", value=reason)
        embed.add_field(name="Модератор", value=interaction.user.mention)
        embed.set_thumbnail(url=member.display_avatar.url)
        await send_mod_log(interaction.guild, embed)
        await interaction.response.send_message(embed=embed)


@bot.tree.command(name="unmute", description="Размутить участника")
@app_commands.describe(
    member="Кого размутить",
    channel="Если указать — снять мут только с этого канала"
)
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute(
    interaction: discord.Interaction,
    member: discord.Member,
    channel: discord.TextChannel = None
):
    if channel:
        try:
            await channel.set_permissions(member, overwrite=None, reason="Размут")
            await remove_channel_mute(member.id, interaction.guild.id, channel.id)
        except discord.Forbidden:
            embed = discord.Embed(title="Ошибка", description="Нет прав.", color=COLOR_ERROR)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        embed = discord.Embed(
            title="Размут в канале",
            description=f"С {member.mention} снят мут в {channel.mention}",
            color=COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Модератор", value=interaction.user.mention)
        await send_mod_log(interaction.guild, embed)
        await interaction.response.send_message(embed=embed)
    else:
        success = await remove_muted_role(member, reason="Размут")
        if not success:
            embed = discord.Embed(title="Ошибка", description="Не удалось снять роль мута.", color=COLOR_ERROR)
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        embed = discord.Embed(
            title="Участник размучен",
            description=f"С {member.mention} снят мут.",
            color=COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Модератор", value=interaction.user.mention)
        embed.set_thumbnail(url=member.display_avatar.url)
        await send_mod_log(interaction.guild, embed)
        await interaction.response.send_message(embed=embed)


# ==================== ЖАЛОБЫ ====================

@bot.tree.command(name="report", description="Пожаловаться на участника")
@app_commands.describe(member="На кого жалоба")
async def report(interaction: discord.Interaction, member: discord.Member):
    if member.bot:
        embed = discord.Embed(title="Ошибка", description="Нельзя жаловаться на ботов.", color=COLOR_ERROR)
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    if member == interaction.user:
        embed = discord.Embed(title="Ошибка", description="Нельзя жаловаться на себя.", color=COLOR_ERROR)
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    modal = ReportModal(member)
    await interaction.response.send_modal(modal)


# ==================== АВТОМОД СЛОВ ====================

@bot.tree.command(name="addword", description="Добавить запрещённое слово")
@app_commands.describe(word="Слово (без пробелов)")
@app_commands.checks.has_permissions(manage_messages=True)
async def addword(interaction: discord.Interaction, word: str):
    word = word.lower().strip()
    if " " in word or len(word) < 2:
        embed = discord.Embed(title="Ошибка", description="Слово должно быть одним и минимум 2 символа.", color=COLOR_ERROR)
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    await add_bad_word(interaction.guild.id, word)
    embed = discord.Embed(title="Слово добавлено", description=f"`{word}` теперь в чёрном списке.", color=COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="removeword", description="Удалить запрещённое слово")
@app_commands.describe(word="Слово")
@app_commands.checks.has_permissions(manage_messages=True)
async def removeword(interaction: discord.Interaction, word: str):
    await remove_bad_word(interaction.guild.id, word.lower().strip())
    embed = discord.Embed(title="Слово удалено", description=f"`{word}` убрано из списка.", color=COLOR_SUCCESS)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="wordlist", description="Показать список запрещённых слов")
@app_commands.checks.has_permissions(manage_messages=True)
async def wordlist(interaction: discord.Interaction):
    words = await get_bad_words(interaction.guild.id)
    if not words:
        embed = discord.Embed(title="Чёрный список пуст", color=COLOR_INFO)
    else:
        embed = discord.Embed(
            title="Запрещённые слова",
            description=", ".join(f"`{w}`" for w in words),
            color=COLOR_INFO
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ==================== ПРОЧЕЕ ====================

@bot.tree.command(name="settings", description="Показать текущие настройки")
@app_commands.checks.has_permissions(administrator=True)
async def settings_cmd(interaction: discord.Interaction):
    settings = await get_guild_settings(interaction.guild.id)
    if not settings:
        embed = discord.Embed(title="Настройки не найдены", description="Используй `/setup`", color=COLOR_ERROR)
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    def r(rid):
        return f"<@&{rid}>" if rid else "`—`"
    def c(cid):
        return f"<#{cid}>" if cid else "`—`"

    embed = discord.Embed(title="Текущие настройки", color=COLOR_INFO, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Неверифицирован", value=r(settings.get("unverified_role_id")), inline=True)
    embed.add_field(name="Участник", value=r(settings.get("verified_role_id")), inline=True)
    embed.add_field(name="Мут-роль", value=r(settings.get("muted_role_id")), inline=True)
    embed.add_field(name="Верификация", value=c(settings.get("verify_channel_id")), inline=True)
    embed.add_field(name="Приветствия", value=c(settings.get("welcome_channel_id")), inline=True)
    embed.add_field(name="Логи верif.", value=c(settings.get("log_channel_id")), inline=True)
    embed.add_field(name="Логи модерации", value=c(settings.get("mod_log_channel_id")), inline=True)
    embed.add_field(name="Таймаут", value=f"{settings.get('verify_timeout', 15)} мин.", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ==================== ЗАПУСК ====================

async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
