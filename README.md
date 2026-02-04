# Mjolnir (Phase 1 - MVP)
**The Ban Hammer with a Stopwatch**

Mjolnir is a Discord bot that tracks playtime for a target game (default: *League of Legends*) and enforces configurable limits with **automatic timeouts** instead of bans.

---

## Current Features (Phase 1)

- **Playtime Tracking** – Records how long opted-in members play the target game
- **Automatic Timeouts** – Users who exceed weekly limits get timed out (not banned!)
- **Playtime Visibility** – `/mystats` shows users their weekly hours, progress bar, and remaining headroom
- **Consent-Based** – Users must `/opt-in` before tracking starts
- **Admin Controls** – `/hammer on|off|status` to enable/disable tracking globally
- **SQLite Persistence** – Stores sessions and settings locally
- **Configurable Thresholds** – Set weekly hour limits and timeout durations

---

## Quick Start

### 1. Prerequisites
- Python 3.10 or higher
- A Discord bot token ([Create one here](https://discord.com/developers/applications))
- **Important:** Enable these Privileged Gateway Intents in Discord Developer Portal:
  - Presence Intent
  - Server Members Intent

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

## Commands

### User Commands
- `/opt-in` - Start tracking your playtime
- `/opt-out` - Stop tracking your playtime
- `/mystats` - View your weekly playtime, progress toward the limit, and active session info

### Admin Commands (Requires Administrator permission)
- `/hammer on` - Enable playtime tracking globally
- `/hammer off` - Disable playtime tracking globally
- `/hammer status` - View current bot status and settings

---

## Default Settings

Settings are stored in the database and can be modified:

- **Target Game:** League of Legends
- **Weekly Threshold:** 20 hours
- **Timeout Duration:** 24 hours

These defaults can be changed in the database or through future admin commands (Phase 2).

---

## How It Works

1. **Opt-in System:** Users run `/opt-in` to consent to tracking
2. **Presence Monitoring:** Bot watches for when opted-in users play the target game
3. **Session Tracking:** Records start/stop times automatically
4. **Weekly Limits:** Calculates total playtime over the last 7 days
5. **Automatic Timeouts:** When threshold is exceeded, user gets timed out
6. **Reversible:** Timeouts expire automatically - no bans, no reinvites needed!

---

## Development Roadmap

### **Phase 1: Core Functionality** COMPLETE
**Goal:** Get basic tracking and timeouts working

**Implemented:**
- Bot connects to Discord with proper intents (Presence + Members)
- Tracks when opted-in users play target game via presence updates
- Records play sessions in SQLite database (start/stop times, duration)
- Applies timeout when user exceeds single threshold (20h/week default)
- Admin toggle tracking on/off globally (`/hammer on|off|status`)
- Users can opt-in/opt-out (`/opt-in`, `/opt-out`)
- Automatic timeout enforcement (not bans - easier to manage!)
- Basic DM notification on timeout
- User stats command (`/mystats`) with progress bar and live session tracking

**Tech Stack:**
- Discord.py 2.x with slash commands
- SQLite for persistence
- Environment-based configuration (.env)

---

### **Phase 2: Configuration & Multiple Thresholds** 🔄 NEXT
**Goal:** Make the bot flexible with graduated consequences

**Planned Features:**

**1. Graduated Timeout System**
- Multiple configurable thresholds instead of single 20h limit
- Example: 10h = warning, 15h = 1h timeout, 20h = 6h timeout, 30h = 24h timeout
- Store threshold rules in database
- Each threshold has: hours, action (warn/timeout), duration

**2. Multiple Time Windows**
- Daily limits: "No more than 4 hours/day"
- Weekly limits: "No more than 20 hours/week" (current)
- Session limits: "No single session longer than 3 hours"
- Rolling windows: Last 7 days vs calendar week

**3. Admin Configuration Commands**
- `/settings view` - See current thresholds and limits
- `/settings set-threshold <hours> <action> <duration>` - Add/modify threshold
- `/settings set-game <game_name>` - Change target game
- `/settings remove-threshold <hours>` - Remove a threshold
- Modify settings without touching database directly

**4. Manual Override Commands**
- `/pardon <user>` - Remove user's timeout early
- `/exempt <user>` - Whitelist user from tracking (e.g., streamers)
- `/reset-playtime <user>` - Reset user's weekly counter
- Admin audit log for all manual actions

**5. Grace Periods & Warnings**
- Warning messages before hitting next threshold
- "You've played 14h this week. At 15h, you'll get a 1h timeout."
- Cooldown system: Reset punishment tier after good behavior
- Configurable warning threshold (e.g., warn at 90% of limit)

**Implementation Notes:**
- Add `thresholds` table to database
- Add `exemptions` table for whitelisted users
- Create new admin cog file: `app/cogs/settings.py`
- Update watcher to check multiple thresholds
- Add warning tracking to prevent spam

---

### **Phase 3: Cosmetic Features & Polish** FUTURE
**Goal:** Improve user experience and add fun features

**Planned Features:**

**1. User Stats & Dashboard**
- `/mystats` - ✅ Basic version implemented in Phase 1 (weekly hours, progress bar, active session)
  - *Still planned:* daily breakdown, total session count, warning status display
- `/leaderboard` - Server-wide playtime rankings (opt-in only)
  - Most hours played
  - Longest single session
  - Most frequent player

**2. Enhanced Notifications**
- DM warnings before hitting thresholds
- Public milestone announcements (optional)
  - "User X has played 10 hours this week!"
  - Custom/randomized messages
  - Configurable announcement channel
- Weekly summary DMs
- Timeout expiration notifications

**3. Historical Tracking & Analytics**
- `/history` - View your playtime over time
- Graph generation (weekly/monthly trends)
- Compare current week to previous weeks
- Identify patterns (e.g., "You play most on weekends")

**4. Data Management**
- `/export` - Export your data as JSON (GDPR compliance)
- `/delete-my-data` - Remove all your tracking data
- Privacy controls per user

**5. Multi-Game Support**
- Track multiple games with separate limits
- Game groups: Limit "competitive games" combined (LoL + Valorant + CS2)
- Per-game opt-in: Choose which games to track
- Game-specific thresholds

**6. Advanced Features** (Nice-to-have)
- Integration with Riot Games API for match history
- Productivity rewards: Reduce timeout if user joins study channels
- Scheduled breaks: Auto-enable stricter limits during exam weeks
- Buddy system: Users set accountability partners who get notified

**7. Improved Logging & Error Handling**
- Comprehensive logging system (not just print statements)
- Error tracking and reporting
- Admin notification on critical errors
- Graceful degradation if Discord API is slow

**Implementation Notes:**
- Consider PostgreSQL for production (better concurrency)
- Add graphing library (matplotlib/plotly)
- Create visualization cog: `app/cogs/stats.py`
- Add scheduled tasks using `@tasks.loop()` for weekly resets
- Implement proper logging with Python's logging module

---

## Current Phase Status

** Phase 1 Complete** - Core tracking and timeout system working
** Phase 2 In Planning** - Graduated timeouts and configuration
** Phase 3 Planned** - Polish and cosmetic features

---

## Troubleshooting

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

## Database Schema

The bot uses SQLite with three main tables:
- `users` - Tracks user opt-in status
- `play_sessions` - Records individual play sessions
- `settings` - Global bot configuration

Database file: `mjolnir.db` (configurable via `DATABASE_PATH` in `.env`)

---

## Contributing

This is a work in progress! Feel free to:
- Report bugs
- Suggest features
- Submit pull requests

---

## License

MIT License - See LICENSE file for details

---

## Design Decisions & Notes

### Why Timeouts Instead of Bans?
- **Reversible** - Timeouts expire automatically, no manual unbanning needed
- **No reinvites** - Users stay in the server, just can't participate temporarily
- **Less punitive** - Better for friendly enforcement in gaming communities
- **Native Discord feature** - Up to 28 days, built-in UI support

### Why Opt-In System?
- **Privacy** - Users consent to being tracked
- **Compliance** - GDPR-friendly approach
- **Trust** - Users know exactly what's being monitored

### Why SQLite?
- **Simple** - No external database server needed
- **Portable** - Single file, easy backups
- **Sufficient** - Handles small-medium Discord servers easily
- **Upgradeable** - Can migrate to PostgreSQL later for large servers

### Key Technical Choices
- **Slash commands** - Modern Discord standard, better UX
- **Presence monitoring** - Real-time tracking without polling
- **Rolling 7-day window** - More fair than strict calendar weeks
- **Dataclasses** - Clean, type-safe models

---

## Quick Reference: What's Next?

1. **Current state:** Phase 1 complete - basic tracking works
2. **Test first:** Run the bot and verify core functionality
3. **Next implementation:** Phase 2 - Graduated timeouts
4. **Start with:** Add `thresholds` table and multi-threshold checking logic
5. **Then add:** Admin commands to configure thresholds
6. **Finally add:** Warning system and grace periods

**Phase 2 Priority Order:**
1. Graduated timeout system (most important)
2. Admin configuration commands (enables easy testing)
3. Manual override commands (pardon/exempt)
4. Grace periods & warnings (polish)
5. Multiple time windows (daily/session limits)
