import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import asyncio
from datetime import datetime, timezone

from config import TOKEN, VERIFY_TIMEOUT, COLOR_SUCCESS, COLOR_ERROR, COLOR_INFO, COLOR_WARNING, COLOR_WELCOME
from database import (
    init_db, get_guild_settings, set_guild_settings,
    add_pending, remove_pending, get_pending
)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


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
            embed = discord.Embed(
                title="Ошибка",
                description="Верификация ещё не настроена администратором.",
                color=COLOR_ERROR
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        verified_role = guild.get_role(settings["verified_role_id"])
        unverified_role = guild.get_role(settings["unverified_role_id"]) if settings["unverified_role_id"] else None

        if verified_role in member.roles:
            embed = discord.Embed(
                title="Уже верифицирован",
                description="Ты уже прошёл верификацию!",
                color=COLOR_SUCCESS
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        try:
            await member.add_roles(verified_role, reason="Верификация")
            if unverified_role and unverified_role in member.roles:
                await member.remove_roles(unverified_role, reason="Верификация")
        except discord.Forbidden:
            embed = discord.Embed(
                title="Ошибка прав",
                description="У бота нет прав выдавать роли. Проверь иерархию ролей.",
                color=COLOR_ERROR
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await remove_pending(member.id, guild.id)

        # Красивое приветствие в канал
        welcome_channel = guild.get_channel(settings["welcome_channel_id"]) if settings["welcome_channel_id"] else None
        if welcome_channel:
            embed = discord.Embed(
                title="Добро пожаловать!",
                description=(
                    f"Привет, {member.mention}!\n\n"
                    f"Рады видеть тебя на **{guild.name}**.\n"
                    f"Теперь тебе открыт полный доступ к серверу."
                ),
                color=COLOR_WELCOME,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            if guild.icon:
                embed.set_author(name=guild.name, icon_url=guild.icon.url)
            embed.set_footer(text=f"Участник #{guild.member_count}")
            await welcome_channel.send(embed=embed)

        # Приветствие в ЛС
        try:
            dm_embed = discord.Embed(
                title=f"Добро пожаловать на {guild.name}!",
                description=(
                    f"Привет, **{member.display_name}**!\n\n"
                    f"Ты успешно прошёл верификацию.\n"
                    f"Приятного общения на сервере!"
                ),
                color=COLOR_WELCOME
            )
            if guild.icon:
                dm_embed.set_thumbnail(url=guild.icon.url)
            dm_embed.set_footer(text="Это автоматическое сообщение")
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass  # ЛС закрыты

        # Красивый лог
        log_channel = guild.get_channel(settings["log_channel_id"]) if settings["log_channel_id"] else None
        if log_channel:
            embed = discord.Embed(
                title="Верификация пройдена",
                color=COLOR_SUCCESS,
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Пользователь", value=f"{member.mention}\n`{member}`", inline=True)
            embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
            embed.add_field(name="Аккаунт создан", value=discord.utils.format_dt(member.created_at, "R"), inline=False)
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"Сервер: {guild.name}")
            await log_channel.send(embed=embed)

        # Ответ пользователю
        success_embed = discord.Embed(
            title="Верификация пройдена!",
            description=f"Добро пожаловать, {member.mention}!\nТеперь тебе доступны все каналы.",
            color=COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)


# ==================== EVENTS ====================

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(VerifyView())
    print(f"✅ Бот запущен как {bot.user}")
    print(f"📊 Серверов: {len(bot.guilds)}")
    check_timeouts.start()

    # Синхронизация slash-команд
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Синхронизировано команд: {len(synced)}")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")


@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return

    settings = await get_guild_settings(member.guild.id)
    if not settings:
        return

    # Выдаём роль "Неверифицирован"
    if settings["unverified_role_id"]:
        role = member.guild.get_role(settings["unverified_role_id"])
        if role:
            try:
                await member.add_roles(role, reason="Новый участник")
            except discord.Forbidden:
                pass

    await add_pending(member.id, member.guild.id, time.time())

    # Сообщение в канал верификации
    verify_channel = member.guild.get_channel(settings["verify_channel_id"]) if settings["verify_channel_id"] else None
    if verify_channel:
        embed = discord.Embed(
            title="Требуется верификация",
            description=(
                f"Привет, {member.mention}!\n\n"
                f"Чтобы получить доступ к серверу, нажми кнопку ниже.\n\n"
                f"⏱ У тебя есть **{settings['verify_timeout']} минут**.\n"
                f"После этого ты будешь автоматически исключён."
            ),
            color=COLOR_INFO
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        if member.guild.icon:
            embed.set_author(name=member.guild.name, icon_url=member.guild.icon.url)
        embed.set_footer(text="Нажми на кнопку, чтобы продолжить")
        await verify_channel.send(content=member.mention, embed=embed, view=VerifyView())


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
                    log_channel = guild.get_channel(settings["log_channel_id"]) if settings and settings["log_channel_id"] else None
                    if log_channel:
                        embed = discord.Embed(
                            title="Исключён за отсутствие верификации",
                            description=f"{member.mention} (`{member}`)\nне прошёл верификацию за отведённое время.",
                            color=COLOR_WARNING,
                            timestamp=datetime.now(timezone.utc)
                        )
                        embed.set_thumbnail(url=member.display_avatar.url)
                        await log_channel.send(embed=embed)
                except discord.Forbidden:
                    pass
            await remove_pending(user_id, guild_id)


# ==================== КОМАНДЫ ====================

@bot.tree.command(name="setup", description="Настроить систему верификации")
@app_commands.describe(
    unverified_role="Роль для неверифицированных",
    verified_role="Роль после верификации",
    verify_channel="Канал с кнопкой верификации",
    welcome_channel="Канал приветствий",
    log_channel="Канал логов",
    timeout="Время на верификацию в минутах"
)
@app_commands.checks.has_permissions(administrator=True)
async def setup(
    interaction: discord.Interaction,
    unverified_role: discord.Role = None,
    verified_role: discord.Role = None,
    verify_channel: discord.TextChannel = None,
    welcome_channel: discord.TextChannel = None,
    log_channel: discord.TextChannel = None,
    timeout: int = 15
):
    data = {}
    if unverified_role:
        data["unverified_role_id"] = unverified_role.id
    if verified_role:
        data["verified_role_id"] = verified_role.id
    if verify_channel:
        data["verify_channel_id"] = verify_channel.id
    if welcome_channel:
        data["welcome_channel_id"] = welcome_channel.id
    if log_channel:
        data["log_channel_id"] = log_channel.id
    data["verify_timeout"] = timeout

    await set_guild_settings(interaction.guild.id, **data)

    embed = discord.Embed(
        title="Настройки сохранены",
        description="Система верификации успешно настроена!",
        color=COLOR_SUCCESS,
        timestamp=datetime.now(timezone.utc)
    )
    if unverified_role:
        embed.add_field(name="Роль неверифицированных", value=unverified_role.mention, inline=True)
    if verified_role:
        embed.add_field(name="Роль верифицированных", value=verified_role.mention, inline=True)
    if verify_channel:
        embed.add_field(name="Канал верификации", value=verify_channel.mention, inline=True)
    if welcome_channel:
        embed.add_field(name="Канал приветствий", value=welcome_channel.mention, inline=True)
    if log_channel:
        embed.add_field(name="Канал логов", value=log_channel.mention, inline=True)
    embed.add_field(name="Таймаут", value=f"`{timeout} мин.`", inline=True)
    embed.set_footer(text="Используй /send_verify чтобы отправить кнопку")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="send_verify", description="Отправить сообщение с кнопкой верификации")
@app_commands.checks.has_permissions(administrator=True)
async def send_verify(interaction: discord.Interaction):
    settings = await get_guild_settings(interaction.guild.id)
    if not settings or not settings["verified_role_id"]:
        embed = discord.Embed(
            title="Сначала настрой бота",
            description="Используй команду `/setup` перед отправкой кнопки.",
            color=COLOR_ERROR
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    embed = discord.Embed(
        title="Верификация",
        description=(
            "Добро пожаловать на сервер!\n\n"
            "Чтобы получить доступ ко всем каналам, нажми кнопку ниже.\n\n"
            "После нажатия тебе будет выдана роль участника."
        ),
        color=COLOR_INFO
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    embed.set_footer(text="Нажми на кнопку, чтобы продолжить")

    await interaction.channel.send(embed=embed, view=VerifyView())

    success = discord.Embed(
        title="Готово",
        description="Сообщение с кнопкой верификации отправлено!",
        color=COLOR_SUCCESS
    )
    await interaction.response.send_message(embed=success, ephemeral=True)


@bot.tree.command(name="settings", description="Показать текущие настройки верификации")
@app_commands.checks.has_permissions(administrator=True)
async def settings_cmd(interaction: discord.Interaction):
    settings = await get_guild_settings(interaction.guild.id)
    if not settings:
        embed = discord.Embed(
            title="Настройки не найдены",
            description="Сначала используй `/setup`",
            color=COLOR_ERROR
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    def role_mention(rid):
        return f"<@&{rid}>" if rid else "`Не задано`"

    def channel_mention(cid):
        return f"<#{cid}>" if cid else "`Не задано`"

    embed = discord.Embed(
        title="Текущие настройки",
        color=COLOR_INFO,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Роль неверифицированных", value=role_mention(settings["unverified_role_id"]), inline=True)
    embed.add_field(name="Роль верифицированных", value=role_mention(settings["verified_role_id"]), inline=True)
    embed.add_field(name="Канал верификации", value=channel_mention(settings["verify_channel_id"]), inline=True)
    embed.add_field(name="Канал приветствий", value=channel_mention(settings["welcome_channel_id"]), inline=True)
    embed.add_field(name="Канал логов", value=channel_mention(settings["log_channel_id"]), inline=True)
    embed.add_field(name="Таймаут", value=f"`{settings['verify_timeout']} мин.`", inline=True)
    embed.set_footer(text=f"Сервер ID: {interaction.guild.id}")

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ==================== ЗАПУСК ====================

async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
