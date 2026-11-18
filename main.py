import os
import re
import io
import sqlite3
import random
import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
DB_PATH = os.getenv("DATABASE_PATH", "oyf_bot.sqlite3")
GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Add it to your .env file or hosting environment variables.")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.invites = True

bot = commands.Bot(command_prefix="!", intents=intents)
db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row


def init_db():
    with db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            guild_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (guild_id, key)
        );
        CREATE TABLE IF NOT EXISTS tickets (
            channel_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            claimed_by INTEGER,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS suggestions (
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            suggestion TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS giveaways (
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            prize TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            ended INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS giveaway_entries (
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (message_id, user_id)
        );
        """)


def setting(guild_id: int, key: str, default=None):
    row = db.execute("SELECT value FROM settings WHERE guild_id=? AND key=?", (guild_id, key)).fetchone()
    return row["value"] if row else default


def set_setting(guild_id: int, key: str, value):
    with db:
        db.execute(
            "INSERT INTO settings(guild_id,key,value) VALUES(?,?,?) "
            "ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",
            (guild_id, key, str(value))
        )


def is_staff(member: discord.Member) -> bool:
    role_id = int(setting(member.guild.id, "staff_role_id", "0") or 0)
    return member.guild_permissions.administrator or (role_id and any(r.id == role_id for r in member.roles))


async def send_log(guild: discord.Guild, embed: discord.Embed, file=None):
    channel_id = int(setting(guild.id, "log_channel_id", "0") or 0)
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel:
        try:
            await channel.send(embed=embed, file=file)
        except discord.HTTPException:
            pass


def brand_embed(title: str, description: str = ""):
    e = discord.Embed(title=title, description=description, color=discord.Color.from_rgb(105, 80, 220))
    e.set_footer(text="Own Your Future • OYF")
    return e


class TicketCreateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def create_ticket(self, interaction: discord.Interaction, category_name: str):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("This can only be used in a server.", ephemeral=True)

        existing = db.execute(
            "SELECT channel_id FROM tickets WHERE guild_id=? AND user_id=? AND status='open'",
            (guild.id, interaction.user.id)
        ).fetchone()
        if existing:
            ch = guild.get_channel(existing["channel_id"])
            if ch:
                return await interaction.response.send_message(f"You already have an open ticket: {ch.mention}", ephemeral=True)
            with db:
                db.execute("UPDATE tickets SET status='closed' WHERE channel_id=?", (existing["channel_id"],))

        category_id = int(setting(guild.id, "ticket_category_id", "0") or 0)
        category = guild.get_channel(category_id) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            category = await guild.create_category("OYF TICKETS")
            set_setting(guild.id, "ticket_category_id", category.id)

        staff_role_id = int(setting(guild.id, "staff_role_id", "0") or 0)
        staff_role = guild.get_role(staff_role_id) if staff_role_id else None
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True)
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True)

        safe_name = re.sub(r"[^a-z0-9-]", "", interaction.user.name.lower().replace(" ", "-"))[:18] or "member"
        channel = await guild.create_text_channel(
            name=f"{category_name.lower().replace(' ', '-')}-{safe_name}",
            category=category,
            overwrites=overwrites,
            topic=f"OYF {category_name} ticket • Opened by {interaction.user} ({interaction.user.id})"
        )
        with db:
            db.execute(
                "INSERT INTO tickets(channel_id,guild_id,user_id,category,created_at) VALUES(?,?,?,?,?)",
                (channel.id, guild.id, interaction.user.id, category_name, datetime.now(timezone.utc).isoformat())
            )
        embed = brand_embed(f"{category_name} Ticket", f"Welcome {interaction.user.mention}!\n\nPlease explain what you need help with. An OYF staff member will assist you.\n\n**Ticket owner:** {interaction.user.mention}")
        embed.add_field(name="Ticket controls", value="Staff can claim this ticket. Use **Close Ticket** when the issue is resolved.", inline=False)
        await channel.send(content=f"{interaction.user.mention}" + (f" {staff_role.mention}" if staff_role else ""), embed=embed, view=TicketControlsView())
        await interaction.response.send_message(f"Your ticket has been created: {channel.mention}", ephemeral=True)

    @discord.ui.button(label="Support", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="oyf_ticket_support")
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.create_ticket(interaction, "Support")

    @discord.ui.button(label="Player Application", emoji="🏆", style=discord.ButtonStyle.success, custom_id="oyf_ticket_player")
    async def player(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.create_ticket(interaction, "Player Application")

    @discord.ui.button(label="Staff Application", emoji="🛡️", style=discord.ButtonStyle.success, custom_id="oyf_ticket_staff")
    async def staff(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.create_ticket(interaction, "Staff Application")

    @discord.ui.button(label="Partnership", emoji="🤝", style=discord.ButtonStyle.secondary, custom_id="oyf_ticket_partner")
    async def partner(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.create_ticket(interaction, "Partnership")

    @discord.ui.button(label="Investor", emoji="💼", style=discord.ButtonStyle.secondary, custom_id="oyf_ticket_investor")
    async def investor(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.create_ticket(interaction, "Investor")


class TicketControlsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim Ticket", emoji="🙋", style=discord.ButtonStyle.primary, custom_id="oyf_ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            return await interaction.response.send_message("Only OYF staff can claim tickets.", ephemeral=True)
        row = db.execute("SELECT claimed_by FROM tickets WHERE channel_id=? AND status='open'", (interaction.channel_id,)).fetchone()
        if not row:
            return await interaction.response.send_message("This ticket is not registered as open.", ephemeral=True)
        if row["claimed_by"]:
            return await interaction.response.send_message("This ticket has already been claimed.", ephemeral=True)
        with db:
            db.execute("UPDATE tickets SET claimed_by=? WHERE channel_id=?", (interaction.user.id, interaction.channel_id))
        await interaction.response.send_message(f"Ticket claimed by {interaction.user.mention}.")
        await send_log(interaction.guild, brand_embed("Ticket Claimed", f"{interaction.channel.mention} was claimed by {interaction.user.mention}."))

    @discord.ui.button(label="Close Ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="oyf_ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = db.execute("SELECT user_id,status FROM tickets WHERE channel_id=?", (interaction.channel_id,)).fetchone()
        if not row or row["status"] != "open":
            return await interaction.response.send_message("This ticket is already closed or is not registered.", ephemeral=True)
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None or (member.id != row["user_id"] and not is_staff(member)):
            return await interaction.response.send_message("Only the ticket owner or OYF staff can close this ticket.", ephemeral=True)

        await interaction.response.defer()
        channel = interaction.channel
        lines = []
        async for msg in channel.history(limit=500, oldest_first=True):
            stamp = msg.created_at.strftime("%Y-%m-%d %H:%M UTC")
            content = msg.clean_content or ""
            if msg.attachments:
                content += " " + " ".join(a.url for a in msg.attachments)
            lines.append(f"[{stamp}] {msg.author} ({msg.author.id}): {content}")
        transcript = "\n".join(lines) or "No messages."
        file = discord.File(io.BytesIO(transcript.encode("utf-8")), filename=f"ticket-{channel.id}-transcript.txt")
        await send_log(interaction.guild, brand_embed("Ticket Transcript", f"Transcript for {channel.mention}"), file=file)
        with db:
            db.execute("UPDATE tickets SET status='closed' WHERE channel_id=?", (channel.id,))
        await channel.set_permissions(interaction.guild.get_member(row["user_id"]), view_channel=False)
        await channel.edit(name=f"closed-{channel.name}"[:90])
        await channel.send(embed=brand_embed("Ticket Closed", f"Closed by {interaction.user.mention}. A transcript was sent to the configured log channel. Staff can delete this channel when ready."))
        await interaction.followup.send("Ticket closed and transcript processed.", ephemeral=True)


class SuggestionModal(discord.ui.Modal, title="Submit an OYF Suggestion"):
    suggestion = discord.ui.TextInput(label="Your suggestion", style=discord.TextStyle.paragraph, max_length=1000, placeholder="Tell us what you would like to see improved...")

    async def on_submit(self, interaction: discord.Interaction):
        channel_id = int(setting(interaction.guild_id, "suggestion_channel_id", "0") or 0)
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if not channel:
            return await interaction.response.send_message("The suggestion channel has not been configured. Ask an administrator to run /setsuggestions.", ephemeral=True)
        embed = brand_embed("New OYF Suggestion", str(self.suggestion))
        embed.add_field(name="Submitted by", value=interaction.user.mention)
        msg = await channel.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        with db:
            db.execute("INSERT OR REPLACE INTO suggestions(message_id,guild_id,user_id,suggestion,created_at) VALUES(?,?,?,?,?)",
                       (msg.id, interaction.guild_id, interaction.user.id, str(self.suggestion), datetime.now(timezone.utc).isoformat()))
        await interaction.response.send_message("Your suggestion has been submitted. Thank you!", ephemeral=True)


class GiveawayJoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Enter Giveaway", emoji="🎉", style=discord.ButtonStyle.success, custom_id="oyf_giveaway_enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = db.execute(
            "SELECT ended FROM giveaways WHERE message_id=?",
            (interaction.message.id,)
        ).fetchone()
        if not giveaway or giveaway["ended"]:
            return await interaction.response.send_message("This giveaway is no longer accepting entries.", ephemeral=True)
        with db:
            db.execute(
                "INSERT OR IGNORE INTO giveaway_entries(message_id,user_id) VALUES(?,?)",
                (interaction.message.id, interaction.user.id)
            )
        await interaction.response.send_message("You're entered! Good luck.", ephemeral=True)


def parse_duration(value: str):
    match = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", value.lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    if seconds < 60 or seconds > 30 * 86400:
        return None
    return timedelta(seconds=seconds)


@bot.event
async def on_ready():
    init_db()
    bot.add_view(TicketCreateView())
    bot.add_view(TicketControlsView())
    bot.add_view(GiveawayJoinView())
    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild_obj)
            await bot.tree.sync(guild=guild_obj)
        else:
            await bot.tree.sync()
    except Exception as exc:
        print(f"Slash command sync error: {exc}")
    if not giveaway_watcher.is_running():
        giveaway_watcher.start()
    print(f"Logged in as {bot.user} (OYF bot is online)")


@bot.event
async def on_member_join(member: discord.Member):
    channel_id = int(setting(member.guild.id, "welcome_channel_id", "0") or 0)
    channel = member.guild.get_channel(channel_id) if channel_id else None
    if channel:
        embed = brand_embed("Welcome to Own Your Future!", f"Welcome {member.mention} to **OYF**!\n\nPlease read the rules and enjoy your stay.")
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)


@bot.event
async def on_member_remove(member: discord.Member):
    channel_id = int(setting(member.guild.id, "welcome_channel_id", "0") or 0)
    channel = member.guild.get_channel(channel_id) if channel_id else None
    if channel:
        await channel.send(embed=brand_embed("Member Left", f"**{member}** has left Own Your Future."))


@bot.tree.command(name="setup", description="Show the OYF bot setup checklist.")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    embed = brand_embed("OYF Bot Setup", "Use these commands to configure the bot:")
    embed.add_field(name="Staff role", value="`/setstaffrole role:@Staff`", inline=False)
    embed.add_field(name="Log channel", value="`/setlogs channel:#logs`", inline=False)
    embed.add_field(name="Welcome channel", value="`/setwelcome channel:#welcome`", inline=False)
    embed.add_field(name="Suggestions channel", value="`/setsuggestions channel:#suggestions`", inline=False)
    embed.add_field(name="Ticket panel", value="`/ticketpanel`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="setstaffrole", description="Set the OYF staff role.")
@app_commands.checks.has_permissions(administrator=True)
async def setstaffrole(interaction: discord.Interaction, role: discord.Role):
    set_setting(interaction.guild_id, "staff_role_id", role.id)
    await interaction.response.send_message(f"OYF staff role set to {role.mention}.", ephemeral=True)


@bot.tree.command(name="setlogs", description="Set the channel for moderation logs and ticket transcripts.")
@app_commands.checks.has_permissions(administrator=True)
async def setlogs(interaction: discord.Interaction, channel: discord.TextChannel):
    set_setting(interaction.guild_id, "log_channel_id", channel.id)
    await interaction.response.send_message(f"Logs will be sent to {channel.mention}.", ephemeral=True)


@bot.tree.command(name="setwelcome", description="Set the welcome and goodbye channel.")
@app_commands.checks.has_permissions(administrator=True)
async def setwelcome(interaction: discord.Interaction, channel: discord.TextChannel):
    set_setting(interaction.guild_id, "welcome_channel_id", channel.id)
    await interaction.response.send_message(f"Welcome and goodbye messages will use {channel.mention}.", ephemeral=True)


@bot.tree.command(name="setsuggestions", description="Set the channel where suggestions are posted.")
@app_commands.checks.has_permissions(administrator=True)
async def setsuggestions(interaction: discord.Interaction, channel: discord.TextChannel):
    set_setting(interaction.guild_id, "suggestion_channel_id", channel.id)
    await interaction.response.send_message(f"Suggestions will be posted in {channel.mention}.", ephemeral=True)


@bot.tree.command(name="ticketpanel", description="Post the OYF ticket panel.")
@app_commands.checks.has_permissions(administrator=True)
async def ticketpanel(interaction: discord.Interaction):
    embed = brand_embed("OYF Support Center", "Need assistance? Select the category that best matches your request.\n\n🎫 **Support** — General help\n🏆 **Player Application** — Join OYF as a competitive player\n🛡️ **Staff Application** — Apply for a staff position\n🤝 **Partnership** — Organization and creator partnerships\n💼 **Investor** — Business and investment inquiries")
    embed.add_field(name="Before opening a ticket", value="Please open only one ticket at a time and provide accurate information. Abusing the ticket system may result in restrictions.", inline=False)
    await interaction.channel.send(embed=embed, view=TicketCreateView())
    await interaction.response.send_message("OYF ticket panel posted.", ephemeral=True)


@bot.tree.command(name="suggest", description="Submit a suggestion to the OYF team.")
async def suggest(interaction: discord.Interaction):
    await interaction.response.send_modal(SuggestionModal())


@bot.tree.command(name="warn", description="Issue a warning to a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    with db:
        db.execute("INSERT INTO warnings(guild_id,user_id,moderator_id,reason,created_at) VALUES(?,?,?,?,?)",
                   (interaction.guild_id, member.id, interaction.user.id, reason, datetime.now(timezone.utc).isoformat()))
    await interaction.response.send_message(f"{member.mention} has been warned. Reason: {reason}")
    await send_log(interaction.guild, brand_embed("Member Warned", f"**Member:** {member.mention}\n**Moderator:** {interaction.user.mention}\n**Reason:** {reason}"))
    try:
        await member.send(embed=brand_embed("You received an OYF warning", f"Server: **{interaction.guild.name}**\nReason: {reason}"))
    except discord.HTTPException:
        pass


@bot.tree.command(name="warnings", description="View a member's warning history.")
@app_commands.checks.has_permissions(moderate_members=True)
async def warnings(interaction: discord.Interaction, member: discord.Member):
    rows = db.execute("SELECT reason,moderator_id,created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",
                      (interaction.guild_id, member.id)).fetchall()
    if not rows:
        return await interaction.response.send_message(f"{member.mention} has no recorded warnings.", ephemeral=True)
    lines = [f"• {r['reason']} — <@{r['moderator_id']}> ({r['created_at'][:10]})" for r in rows]
    await interaction.response.send_message(embed=brand_embed(f"Warnings for {member}", "\n".join(lines)), ephemeral=True)


@bot.tree.command(name="timeout", description="Timeout a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout_member(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason provided"):
    if member.top_role >= interaction.user.top_role and interaction.guild.owner_id != interaction.user.id:
        return await interaction.response.send_message("You cannot timeout a member with an equal or higher role.", ephemeral=True)
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await interaction.response.send_message(f"{member.mention} was timed out for {minutes} minutes. Reason: {reason}")
    await send_log(interaction.guild, brand_embed("Member Timed Out", f"**Member:** {member.mention}\n**Moderator:** {interaction.user.mention}\n**Duration:** {minutes} minutes\n**Reason:** {reason}"))


@bot.tree.command(name="kick", description="Kick a member.")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if member.top_role >= interaction.user.top_role and interaction.guild.owner_id != interaction.user.id:
        return await interaction.response.send_message("You cannot kick a member with an equal or higher role.", ephemeral=True)
    await member.kick(reason=reason)
    await interaction.response.send_message(f"Removed **{member}**. Reason: {reason}")
    await send_log(interaction.guild, brand_embed("Member Kicked", f"**Member:** {member} (`{member.id}`)\n**Moderator:** {interaction.user.mention}\n**Reason:** {reason}"))


@bot.tree.command(name="ban", description="Ban a member.")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if member.top_role >= interaction.user.top_role and interaction.guild.owner_id != interaction.user.id:
        return await interaction.response.send_message("You cannot ban a member with an equal or higher role.", ephemeral=True)
    await member.ban(reason=reason)
    await interaction.response.send_message(f"Banned **{member}**. Reason: {reason}")
    await send_log(interaction.guild, brand_embed("Member Banned", f"**Member:** {member} (`{member.id}`)\n**Moderator:** {interaction.user.mention}\n**Reason:** {reason}"))


@bot.tree.command(name="purge", description="Delete recent messages in this channel.")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"Deleted {len(deleted)} messages.", ephemeral=True)


@bot.tree.command(name="ticketdelete", description="Delete the current closed ticket channel.")
@app_commands.checks.has_permissions(manage_channels=True)
async def ticketdelete(interaction: discord.Interaction):
    row = db.execute("SELECT status FROM tickets WHERE channel_id=?", (interaction.channel_id,)).fetchone()
    if not row or row["status"] != "closed":
        return await interaction.response.send_message("Only a registered, closed ticket can be deleted.", ephemeral=True)
    await interaction.response.send_message("Deleting this ticket channel in 5 seconds.")
    await asyncio.sleep(5)
    await interaction.channel.delete(reason=f"Ticket deleted by {interaction.user}")


@bot.tree.command(name="giveaway", description="Start a giveaway. Duration examples: 30m, 2h, 1d.")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway(interaction: discord.Interaction, duration: str, prize: str, winners: app_commands.Range[int, 1, 10] = 1):
    delta = parse_duration(duration)
    if not delta:
        return await interaction.response.send_message("Invalid duration. Use 30m, 2h, or 1d (1 minute to 30 days).", ephemeral=True)
    end = datetime.now(timezone.utc) + delta
    embed = brand_embed("🎉 OYF GIVEAWAY", f"**Prize:** {prize}\n**Winners:** {winners}\n**Ends:** <t:{int(end.timestamp())}:R>\n\nClick **Enter Giveaway** to participate.")
    embed.add_field(name="Hosted by", value=interaction.user.mention)
    await interaction.response.defer()
    msg = await interaction.channel.send(embed=embed, view=GiveawayJoinView())
    with db:
        db.execute("INSERT INTO giveaways(message_id,guild_id,channel_id,prize,ends_at) VALUES(?,?,?,?,?)",
                   (msg.id, interaction.guild_id, interaction.channel_id, prize, end.isoformat()))
    await interaction.followup.send(f"Giveaway created: {msg.jump_url}", ephemeral=True)


@tasks.loop(seconds=30)
async def giveaway_watcher():
    now = datetime.now(timezone.utc)
    rows = db.execute("SELECT * FROM giveaways WHERE ended=0").fetchall()
    for row in rows:
        try:
            end = datetime.fromisoformat(row["ends_at"])
            if end > now:
                continue
            guild = bot.get_guild(row["guild_id"])
            channel = guild.get_channel(row["channel_id"]) if guild else None
            message = await channel.fetch_message(row["message_id"]) if channel else None
            if message:
                entry_rows = db.execute(
                    "SELECT user_id FROM giveaway_entries WHERE message_id=?",
                    (row["message_id"],)
                ).fetchall()
                entrants = []
                for entry in entry_rows:
                    user = guild.get_member(entry["user_id"]) if guild else None
                    if user and not user.bot:
                        entrants.append(user)
                # Use the configured winner count from the original embed if present; default to one.
                winner_count = 1
                if message.embeds and message.embeds[0].fields:
                    for field in message.embeds[0].fields:
                        if field.name == "Winners":
                            try: winner_count = int(field.value)
                            except ValueError: pass
                chosen = random.sample(entrants, min(winner_count, len(entrants))) if entrants else []
                if chosen:
                    await channel.send(f"🎉 Congratulations {', '.join(u.mention for u in chosen)}! You won **{row['prize']}**.")
                else:
                    await channel.send(f"The giveaway for **{row['prize']}** ended with no entrants.")
                ended_embed = brand_embed("Giveaway Ended", f"**Prize:** {row['prize']}\n**Winners:** {', '.join(u.mention for u in chosen) if chosen else 'No entrants'}")
                await message.edit(embed=ended_embed, view=None)
            with db:
                db.execute("UPDATE giveaways SET ended=1 WHERE message_id=?", (row["message_id"],))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError) as exc:
            print(f"Giveaway processing issue for {row['message_id']}: {exc}")
            with db:
                db.execute("UPDATE giveaways SET ended=1 WHERE message_id=?", (row["message_id"],))


@giveaway_watcher.before_loop
async def before_giveaway_watcher():
    await bot.wait_until_ready()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "You don't have permission to use that command."
    elif isinstance(error, app_commands.CommandOnCooldown):
        message = "Please wait before using that command again."
    else:
        message = "Something went wrong while running that command."
        print(f"Command error: {repr(error)}")
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


init_db()
bot.run(TOKEN)
