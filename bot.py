import discord
from discord.ext import commands
from dotenv import load_dotenv
from pymongo import MongoClient
import os

load_dotenv()

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
SCORES_CHANNEL_ID = 1398149394288873572   # channel where users post "+1"
SCOREBOARD_CHANNEL_ID = 1398149394288873572  # where the embed lives (can be same channel)
PAGE_SIZE = 10  # players per page

# Users who can use admin commands regardless of server permissions
ADMIN_IDS = {353320170196041749, 590038326631858196}
# ──────────────────────────────────────────────────────────────────────────────

# ── MongoDB setup ─────────────────────────────────────────────────────────────
mongo = MongoClient(MONGO_URI)
db = mongo["scoreboard"]
scores_col = db["scores"]

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ── Auth helper ───────────────────────────────────────────────────────────────

def is_admin(ctx: commands.Context) -> bool:
    return ctx.author.id in ADMIN_IDS or ctx.author.guild_permissions.administrator


# ── Database helpers ──────────────────────────────────────────────────────────

def get_scores() -> list:
    return list(scores_col.find({}, {"_id": 0}).sort("points", -1))


def add_point(user_id: str, display_name: str, amount: int = 1) -> None:
    scores_col.update_one(
        {"user_id": user_id},
        {"$inc": {"points": amount}, "$set": {"name": display_name}},
        upsert=True
    )


def remove_points(user_id: str, amount: int) -> bool:
    doc = scores_col.find_one({"user_id": user_id})
    if not doc or doc.get("points", 0) == 0:
        return False
    new_total = max(0, doc["points"] - amount)
    if new_total == 0:
        scores_col.delete_one({"user_id": user_id})
    else:
        scores_col.update_one({"user_id": user_id}, {"$set": {"points": new_total}})
    return True


def add_trophy(user_id: str, display_name: str, amount: int = 1) -> None:
    scores_col.update_one(
        {"user_id": user_id},
        {"$inc": {"trophies": amount}, "$set": {"name": display_name}},
        upsert=True
    )


def remove_trophy(user_id: str, amount: int = 1) -> bool:
    doc = scores_col.find_one({"user_id": user_id})
    if not doc or doc.get("trophies", 0) == 0:
        return False
    new_total = max(0, doc["trophies"] - amount)
    scores_col.update_one({"user_id": user_id}, {"$set": {"trophies": new_total}})
    return True


# ── Embed builder ─────────────────────────────────────────────────────────────

def get_medal(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"**{rank}.**")


def build_embed(page: int = 0) -> tuple[discord.Embed, int]:
    scores = get_scores()
    total_pages = max(1, -(-len(scores) // PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))

    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_scores = scores[start:end]

    if not scores:
        description = "No scores yet — post a +1 to get started!"
    else:
        lines = []
        for i, entry in enumerate(page_scores, start=start + 1):
            medal = get_medal(i)
            name = entry.get("name", "Unknown")
            pts = entry.get("points", 0)
            trophies = entry.get("trophies", 0)

            trophy_str = "  ".join(["🏆"] * trophies) if trophies > 0 else ""
            trophy_part = f"   |   {trophy_str}" if trophy_str else ""

            lines.append(f"{medal} **{name}** — {pts} pt{'s' if pts != 1 else ''}{trophy_part}")
        description = "\n".join(lines)

    embed = discord.Embed(
        title="🏆 Scoreboard",
        description=description,
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"Page {page + 1} of {total_pages} • Post +1 to add a point")
    embed.timestamp = discord.utils.utcnow()
    return embed, total_pages


# ── Pagination view ───────────────────────────────────────────────────────────

class ScoreboardView(discord.ui.View):
    def __init__(self, page: int = 0):
        super().__init__(timeout=180)
        self.page = page

    async def update(self, interaction: discord.Interaction):
        embed, total_pages = build_embed(self.page)
        self.first_button.disabled = self.page == 0
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page >= total_pages - 1
        self.last_button.disabled = self.page >= total_pages - 1
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def first_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = 0
        await self.update(interaction)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        await self.update(interaction)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await self.update(interaction)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def last_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        _, total_pages = build_embed(self.page)
        self.page = total_pages - 1
        await self.update(interaction)


# ── Core: post the scoreboard embed ──────────────────────────────────────────

async def update_scoreboard() -> None:
    channel = bot.get_channel(SCOREBOARD_CHANNEL_ID)
    if channel is None:
        channel = await bot.fetch_channel(SCOREBOARD_CHANNEL_ID)

    embed, total_pages = build_embed(0)
    view = ScoreboardView(page=0)

    view.first_button.disabled = True
    view.prev_button.disabled = True
    if total_pages <= 1:
        view.next_button.disabled = True
        view.last_button.disabled = True

    await channel.send(embed=embed, view=view)


# ── Events ────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.channel.id == SCORES_CHANNEL_ID and message.content.strip() == "+1":
        user_id = str(message.author.id)
        display_name = message.author.display_name
        add_point(user_id, display_name)
        await message.add_reaction("✅")

    await bot.process_commands(message)


# ── Member resolver (supports @mention or raw user ID) ────────────────────────

async def resolve_member(ctx: commands.Context, user: str) -> discord.Member | None:
    # Strip mention formatting if present
    user_id = user.strip("<@!>")
    try:
        member = await ctx.guild.fetch_member(int(user_id))
        return member
    except (ValueError, discord.NotFound, discord.HTTPException):
        await ctx.reply("❌ Couldn't find that member. Use @mention or their user ID.")
        return None


# ── Commands ──────────────────────────────────────────────────────────────────

@bot.command(name="scores")
async def scores_cmd(ctx: commands.Context):
    """Show the scoreboard."""
    await update_scoreboard()


@bot.command(name="addpoints")
async def addpoints_cmd(ctx: commands.Context, user: str, amount: int):
    """[Admin] Add points to a user. Usage: !addpoints @user 10 or !addpoints USERID 10"""
    if not is_admin(ctx):
        await ctx.reply("❌ You don't have permission to use that command.")
        return
    if amount <= 0:
        await ctx.reply("❌ Amount must be a positive number.")
        return
    member = await resolve_member(ctx, user)
    if not member:
        return
    add_point(str(member.id), member.display_name, amount)
    await ctx.message.add_reaction("✅")


@bot.command(name="removepoints")
async def removepoints_cmd(ctx: commands.Context, user: str, amount: int):
    """[Admin] Remove points from a user. Usage: !removepoints @user 5 or !removepoints USERID 5"""
    if not is_admin(ctx):
        await ctx.reply("❌ You don't have permission to use that command.")
        return
    if amount <= 0:
        await ctx.reply("❌ Amount must be a positive number.")
        return
    member = await resolve_member(ctx, user)
    if not member:
        return
    if remove_points(str(member.id), amount):
        await ctx.message.add_reaction("✅")
    else:
        await ctx.reply(f"**{member.display_name}** has no points to remove.")


@bot.command(name="addtrophy")
async def addtrophy_cmd(ctx: commands.Context, user: str, amount: int = 1):
    """[Admin] Add trophies to a user. Usage: !addtrophy @user 2 or !addtrophy USERID 2"""
    if not is_admin(ctx):
        await ctx.reply("❌ You don't have permission to use that command.")
        return
    if amount <= 0:
        await ctx.reply("❌ Amount must be a positive number.")
        return
    member = await resolve_member(ctx, user)
    if not member:
        return
    add_trophy(str(member.id), member.display_name, amount)
    await ctx.message.add_reaction("✅")


@bot.command(name="removetrophy")
async def removetrophy_cmd(ctx: commands.Context, user: str, amount: int = 1):
    """[Admin] Remove trophies from a user. Usage: !removetrophy @user 2 or !removetrophy USERID 2"""
    if not is_admin(ctx):
        await ctx.reply("❌ You don't have permission to use that command.")
        return
    if amount <= 0:
        await ctx.reply("❌ Amount must be a positive number.")
        return
    member = await resolve_member(ctx, user)
    if not member:
        return
    if remove_trophy(str(member.id), amount):
        await ctx.message.add_reaction("✅")
    else:
        await ctx.reply(f"**{member.display_name}** has no trophies to remove.")


# ── Error handler ─────────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply("❌ You don't have permission to use that command.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.reply("❌ Couldn't find that member. Make sure you @mention them.")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("❌ Invalid argument. Make sure you @mention a user and provide a valid number.")
    else:
        raise error


# ── Run ───────────────────────────────────────────────────────────────────────

bot.run(BOT_TOKEN)