# Mjolnir (Phase 1 - MVP)
**The Ban Hammer with a Stopwatch** ⚡

Mjolnir is a Discord bot that tracks playtime for a target game (default: *League of Legends*) and enforces configurable limits with **automatic timeouts** instead of bans.

---

## ✨ Current Features (Phase 1)

- ✅ **Playtime Tracking** – Records how long opted-in members play the target game
- ✅ **Automatic Timeouts** – Users who exceed weekly limits get timed out (not banned!)
- ✅ **Consent-Based** – Users must `/opt-in` before tracking starts
- ✅ **Admin Controls** – `/hammer on|off|status` to enable/disable tracking globally
- ✅ **SQLite Persistence** – Stores sessions and settings locally
- ✅ **Configurable Thresholds** – Set weekly hour limits and timeout durations

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.10 or higher
- A Discord bot token ([Create one here](https://discord.com/developers/applications))
- **Important:** Enable these Privileged Gateway Intents in Discord Developer Portal:
  - ✅ Presence Intent
  - ✅ Server Members Intent

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/Josperdo/Mjolnir.git
cd Mjolnir

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .
```

### 3. Configuration

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env and add your bot token
# DISCORD_BOT_TOKEN=your_actual_bot_token_here
```

### 4. Run the Bot

```bash
# Start Mjolnir
python -m app.bot

# Or using the installed script
mjolnir
```

---

## 📋 Commands

### User Commands
- `/opt-in` - Start tracking your playtime
- `/opt-out` - Stop tracking your playtime

### Admin Commands (Requires Administrator permission)
- `/hammer on` - Enable playtime tracking globally
- `/hammer off` - Disable playtime tracking globally
- `/hammer status` - View current bot status and settings

---

## ⚙️ Default Settings

Settings are stored in the database and can be modified:

- **Target Game:** League of Legends
- **Weekly Threshold:** 20 hours
- **Timeout Duration:** 24 hours

These defaults can be changed in the database or through future admin commands (Phase 2).

---

## 🔨 How It Works

1. **Opt-in System:** Users run `/opt-in` to consent to tracking
2. **Presence Monitoring:** Bot watches for when opted-in users play the target game
3. **Session Tracking:** Records start/stop times automatically
4. **Weekly Limits:** Calculates total playtime over the last 7 days
5. **Automatic Timeouts:** When threshold is exceeded, user gets timed out
6. **Reversible:** Timeouts expire automatically - no bans, no reinvites needed!

---

## 🛠️ Upcoming Features (Phase 2 & 3)

**Phase 2 - Configuration & Flexibility:**
- Multiple configurable thresholds with graduated timeouts
- Daily/weekly/session time windows
- Admin commands to modify settings
- Manual pardon/override commands

**Phase 3 - Polish & QoL:**
- `/mystats` command to view your playtime
- DM warnings before timeouts
- Milestone announcements
- Leaderboards
- Historical tracking and graphs
- Data export functionality

---

## 🐛 Troubleshooting

**Bot doesn't track presence:**
- Ensure "Presence Intent" is enabled in Discord Developer Portal
- Verify "Server Members Intent" is also enabled
- Make sure users have run `/opt-in`

**"Missing Permissions" errors:**
- Bot needs "Timeout Members" permission
- Grant the bot role appropriate permissions in Server Settings

**Bot doesn't start:**
- Check your `.env` file has the correct `DISCORD_BOT_TOKEN`
- Verify Python 3.10+ is installed: `python --version`

---

## 📊 Database Schema

The bot uses SQLite with three main tables:
- `users` - Tracks user opt-in status
- `play_sessions` - Records individual play sessions
- `settings` - Global bot configuration

Database file: `mjolnir.db` (configurable via `DATABASE_PATH` in `.env`)

---

## 🤝 Contributing

This is a work in progress! Feel free to:
- Report bugs
- Suggest features
- Submit pull requests

---

## 📝 License

MIT License - See LICENSE file for details

---

## 🎯 Project Status

**Current Phase:** Phase 1 (MVP) - Complete ✅

**Next Steps:**
- Implement Phase 2 (Configuration & Multiple Thresholds)
- Add comprehensive testing
- Improve error handling
- Add logging system
