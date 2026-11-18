# Own Your Future (OYF) Discord Bot

A Python Discord bot built with `discord.py`. It includes a ticket panel, ticket transcripts,
moderation tools, welcome messages, suggestions, giveaways, and SQLite storage.

## 1. Create the Discord application

1. Open https://discord.com/developers/applications
2. Select **New Application** and name it `Own Your Future`.
3. Open the **Bot** tab and create/reset the bot token.
4. Copy the token privately. Never post it in Discord or share it with anyone.
5. Under **Bot → Privileged Gateway Intents**, enable:
   - Server Members Intent
   - Message Content Intent
   - (Presence Intent is not needed)
6. Open **OAuth2 → URL Generator**:
   - Scopes: `bot` and `applications.commands`
   - Bot permissions: View Channels, Send Messages, Embed Links, Attach Files,
     Read Message History, Manage Channels, Manage Messages, Moderate Members,
     Kick Members, Ban Members, Add Reactions
7. Open the generated URL and invite the bot to your OYF server.
8. Put the bot's role above roles it needs to moderate, but do not give it Administrator
   unless you have a specific reason.

## 2. Install and run

Install Python 3.11 or newer.

### Windows
```bash
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

### macOS / Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and replace `PASTE_YOUR_BOT_TOKEN_HERE` with your bot token.
Then start the bot:

```bash
python main.py
```

Keep the terminal/process running. The bot must be online for commands and buttons to work.

## 3. Configure the OYF server

In your server, run these commands as an administrator:

1. `/setstaffrole` — choose your OYF staff role.
2. `/setlogs` — choose the channel for moderation logs and ticket transcripts.
3. `/setwelcome` — choose the welcome/goodbye channel.
4. `/setsuggestions` — choose the suggestions channel.
5. `/ticketpanel` — post the public ticket panel.
6. `/setup` — view the setup checklist again.

The bot creates its ticket category automatically the first time someone opens a ticket.

## 4. Commands

### Setup
- `/setup`
- `/setstaffrole role`
- `/setlogs channel`
- `/setwelcome channel`
- `/setsuggestions channel`
- `/ticketpanel`

### Tickets
- Ticket panel buttons: Support, Player Application, Staff Application, Partnership, Investor
- **Claim Ticket** button (staff only)
- **Close Ticket** button (ticket owner or staff)
- `/ticketdelete` (manage channels; closed tickets only)

Closed tickets are retained for staff review. A text transcript is sent to the configured log channel.
Set `/setlogs` before using tickets if you want transcripts stored in a log channel.

### Moderation
- `/warn member reason`
- `/warnings member`
- `/timeout member minutes reason`
- `/kick member reason`
- `/ban member reason`
- `/purge amount`

### Community
- `/suggest` — opens a suggestion form
- `/giveaway duration prize winners`
  - Duration examples: `30m`, `2h`, `1d`
  - Giveaways are entered with the 🎉 reaction (the Enter Giveaway button adds it).

## 5. Free hosting notes

The bot needs a continuously running Python process and a persistent disk for SQLite.
Many free hosting plans sleep, impose monthly limits, or remove local files on restart.
If the host sleeps, the bot goes offline until it wakes. If its filesystem is temporary,
the database may be lost. Check the host's current free-plan rules before deploying.

For a no-cost starting point, run it on a computer you control while it is on and connected
to the internet. A cloud free tier may work if it supports always-on background processes
and persistent storage, but availability and limits can change.

## 6. Important security and maintenance

- Never share your bot token. If it leaks, reset it immediately in the Developer Portal.
- Do not commit `.env` or the SQLite database to a public Git repository.
- Back up `oyf_bot.sqlite3`.
- Keep Python and dependencies updated.
- Give the bot only the permissions it needs.
- Giveaway entries are stored in SQLite when members click the Enter Giveaway button.

## Troubleshooting

**Slash commands do not appear:** Confirm the bot was invited with `applications.commands`.
Restart the bot. Set `GUILD_ID` in `.env` to your server ID for quicker guild command sync.

**Bot cannot create ticket channels:** Give it Manage Channels and View Channels permissions.
Make sure its role is not blocked by channel/category permission overwrites.

**Ticket transcripts do not appear:** Run `/setlogs` and make sure the bot can send messages
and attach files in that log channel.

**Welcome messages do not work:** Enable Server Members Intent in the Developer Portal and
run `/setwelcome`.

**Bot cannot timeout, kick, or ban:** Enable the corresponding bot permissions and move the
bot's role above the member's highest role.
