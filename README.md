# Mjolnir - Work in Progress
**The Ban Hammer with a Stopwatch**

Mjolnir is a Discord bot that tracks playtime for a target game (default: *League of Legends*) and enforces configurable limits with **automatic timeouts** instead of bans.

---

## Current Features

- **Playtime Tracking** – Records how long opted-in members play the target game
- **Graduated Timeouts** – Multiple escalating thresholds (warn, short timeout, long timeout)
- **Multiple Time Windows** – Rolling 7-day, daily, calendar week, and per-session limits
- **Public Roast Messages** – Threshold notifications posted publicly with randomized roast messages
- **Playtime Visibility** – `/mystats` shows multi-window progress bars, upcoming thresholds, and active session info
- **Consent-Based** – Users must `/opt-in` before tracking starts
- **Admin Controls** – `/hammer on|off|status` to enable/disable tracking globally
- **SQLite Persistence** – Stores sessions, rules, and settings locally
- **Dedup Tracking** – Threshold actions only fire once per window period

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

### 5. Run Tests

Dev dependencies (pytest) are included in the install step above. To run the test suite:

```bash
pytest tests/ -v
```

> **Note:** If you're on Python 3.9 or skipped the editable install, prefix with `PYTHONPATH=.` so the `app` package resolves: `PYTHONPATH=. pytest tests/ -v`

---

## Commands

### User Commands
- `/opt-in` - Start tracking your playtime (shows threshold rules summary)
- `/opt-out` - Stop tracking your playtime
- `/mystats` - View playtime across all windows, progress bars, upcoming thresholds, and active session

### Admin Commands (Requires Administrator permission)
- `/hammer on` - Enable playtime tracking globally
- `/hammer off` - Disable playtime tracking globally
- `/hammer status` - View bot status, threshold rules, and announcement channel config

---

## Default Threshold Rules

Rules are seeded on first startup and stored in the database:

| Threshold | Window | Action | Duration |
|-----------|--------|--------|----------|
| 10 hours | Rolling 7-day | Warning | — |
| 15 hours | Rolling 7-day | Timeout | 1 hour |
| 20 hours | Rolling 7-day | Timeout | 6 hours |
| 30 hours | Rolling 7-day | Timeout | 24 hours |

Rules can be customized via direct database edits. Admin commands for rule CRUD are planned.

### Announcement Channel

Set `announcement_channel_id` in the settings table to a Discord channel ID. When configured, warnings and timeouts post publicly with `@mention` + a random roast message. Falls back to DM if not configured.

---

## How It Works

1. **Opt-in System:** Users run `/opt-in` to consent to tracking
2. **Presence Monitoring:** Bot watches for when opted-in users play the target game
3. **Session Tracking:** Records start/stop times automatically
4. **Multi-Window Limits:** Calculates playtime across rolling 7-day, daily, calendar week, and session windows
5. **Graduated Enforcement:** When a threshold is crossed, the most severe new action is applied
6. **Dedup Protection:** Each rule only fires once per window period (except session rules)
7. **Public Shaming:** Posts roast messages in the announcement channel with @mention
8. **Reversible:** Timeouts expire automatically - no bans, no reinvites needed!

---

## Development Roadmap

### Phase 1: Core Functionality — COMPLETE
**Goal:** Get basic tracking and timeouts working

- [x] Bot connects to Discord with proper intents (Presence + Members)
- [x] Tracks when opted-in users play target game via presence updates
- [x] Records play sessions in SQLite database (start/stop times, duration)
- [x] Applies timeout when user exceeds threshold
- [x] Admin toggle tracking on/off globally (`/hammer on|off|status`)
- [x] Users can opt-in/opt-out (`/opt-in`, `/opt-out`)
- [x] Automatic timeout enforcement (not bans - easier to manage!)
- [x] Basic DM notification on timeout
- [x] User stats command (`/mystats`) with progress bar and live session tracking

---

### Phase 2: Configuration & Multiple Thresholds — IN PROGRESS
**Goal:** Make the bot flexible with graduated consequences

**Graduated Timeout System**
- [x] Multiple configurable thresholds instead of single 20h limit
- [x] Default rules: 10h = warning, 15h = 1h timeout, 20h = 6h timeout, 30h = 24h timeout
- [x] Store threshold rules in database (`threshold_rules` table)
- [x] Each threshold has: hours, action (warn/timeout), duration, window type
- [x] Dedup tracking via `threshold_events` table
- [x] Public roast messages posted to announcement channel with @mention
- [x] Fallback to DM when no announcement channel configured

**Multiple Time Windows**
- [x] Rolling 7-day window (existing behavior, now explicit)
- [x] Daily limits (rolling 24h)
- [x] Calendar week limits (Monday-Sunday)
- [x] Session limits (per-session duration)
- [x] `/mystats` shows progress across all active windows

**Admin Configuration Commands**
- [ ] `/hammer rules list` - View all threshold rules
- [ ] `/hammer rules add <hours> <action> <duration> <window>` - Add a rule
- [ ] `/hammer rules remove <id>` - Remove a rule
- [ ] `/hammer setchannel` - Set announcement channel from Discord
- [ ] `/settings set-game <game_name>` - Change target game

**Manual Override Commands**
- [ ] `/pardon <user>` - Remove user's timeout early
- [ ] `/exempt <user>` - Whitelist user from tracking (e.g., streamers)
- [ ] `/reset-playtime <user>` - Reset user's weekly counter
- [ ] Admin audit log for manual actions

**Grace Periods & Warnings**
- [ ] Proactive warning messages before hitting next threshold
- [ ] "You've played 14h this week. At 15h, you'll get a 1h timeout."
- [ ] Cooldown system: Reset punishment tier after good behavior
- [ ] Configurable warning threshold (e.g., warn at 90% of limit)

---

### Phase 3: Cosmetic Features & Polish — PLANNED
**Goal:** Improve user experience and add fun features

**User Stats & Dashboard**
- [ ] `/mystats` enhancements: daily breakdown, total session count, warning status
- [ ] `/leaderboard` - Server-wide playtime rankings (opt-in only)
  - [ ] Most hours played
  - [ ] Longest single session
  - [ ] Most frequent player

**Enhanced Notifications**
- [ ] Admin-customizable roast messages (move from hardcoded to DB table)
- [ ] Weekly summary DMs
- [ ] Timeout expiration notifications
- [ ] Shame leaderboard / weekly recap posts in announcement channel

**Historical Tracking & Analytics**
- [ ] `/history` - View your playtime over time
- [ ] Graph generation (weekly/monthly trends)
- [ ] Compare current week to previous weeks
- [ ] Identify patterns (e.g., "You play most on weekends")

**Data Management**
- [ ] `/export` - Export your data as JSON (GDPR compliance)
- [ ] `/delete-my-data` - Remove all your tracking data
- [ ] Privacy controls per user

**Multi-Game Support**
- [ ] Track multiple games with separate limits
- [ ] Game groups: Limit "competitive games" combined (LoL + Valorant + CS2)
- [ ] Per-game opt-in: Choose which games to track
- [ ] Game-specific thresholds

**Advanced Features** (Nice-to-have)
- [ ] Integration with Riot Games API for match history
- [ ] Productivity rewards: Reduce timeout if user joins study channels
- [ ] Scheduled breaks: Auto-enable stricter limits during exam weeks
- [ ] Buddy system: Users set accountability partners who get notified

**Infrastructure & Code Quality**
- [ ] Comprehensive logging system (replace print statements with Python logging)
- [ ] Error tracking and reporting
- [ ] Admin notification on critical errors
- [ ] Graceful degradation if Discord API is slow
- [ ] Consider PostgreSQL for production (better concurrency)

---

## Current Status

- **Phase 1** — Complete
- **Phase 2** — In progress (graduated timeouts + multi-window done, admin commands next)
- **Phase 3** — Planned

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

The bot uses SQLite with these tables:
- `users` - Tracks user opt-in status
- `play_sessions` - Records individual play sessions
- `settings` - Global bot configuration (includes `announcement_channel_id`)
- `threshold_rules` - Graduated threshold rules (hours, action, duration, window type)
- `threshold_events` - Dedup tracking for triggered thresholds

Database file: `mjolnir.db` (configurable via `DATABASE_PATH` in `.env`)

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
- **Multiple time windows** - Rolling 7-day, daily, calendar week, and session limits
- **Graduated thresholds** - Escalating consequences instead of a single hard cutoff
- **Public roasts** - Fun accountability via announcement channel
- **Dataclasses** - Clean, type-safe models
