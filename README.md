# Mjolnir
**The Ban Hammer with a Stopwatch**

Mjolnir is a Discord bot that tracks playtime across multiple games and enforces configurable limits with **automatic timeouts** instead of bans.

---

## Features

- **Multi-Game Tracking** – Track any number of games simultaneously; users opt individual games in or out
- **Game Groups** – Set combined playtime limits across a group of games (e.g. LoL + Valorant + CS2)
- **Graduated Timeouts** – Multiple escalating thresholds (warn, short timeout, long timeout)
- **Multiple Time Windows** – Rolling 7-day, daily, calendar week, and per-session limits
- **Game-Specific Rules** – Threshold rules can apply globally, to one game, or to a game group
- **Public Roast Messages** – Threshold notifications posted publicly with randomized roast messages
- **Custom Roast Messages** – Admins can replace the default roasts with their own
- **Playtime Visibility** – `/mystats` shows multi-window progress bars, per-game breakdown, daily stats, session info, and upcoming thresholds
- **Playtime History** – `/history` shows weekly/monthly trends, day-of-week patterns, and optional chart images
- **Leaderboard** – `/leaderboard` shows server-wide rankings (most hours, longest session, most sessions)
- **Consent-Based** – Users must `/opt-in` before tracking starts
- **Privacy Controls** – `/privacy` lets users control leaderboard visibility; `/delete-my-data` removes everything
- **Data Export** – `/export` downloads all stored data as JSON (GDPR-friendly)
- **Admin Controls** – Full suite of `/hammer` commands for configuration, overrides, and auditing
- **Weekly Recaps** – Scheduled DMs and shame leaderboard posts in the announcement channel
- **SQLite Persistence** – Stores sessions, rules, and settings locally
- **Dedup Tracking** – Threshold actions only fire once per window period
- **Structured Logging** – All bot activity logged via Python's logging module

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
git clone https://github.com/Josperdo/mjolnir.git
cd mjolnir

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
- `/opt-in` — Start tracking your playtime (shows current tracked games and threshold rules)
- `/opt-out` — Stop tracking your playtime
- `/mygames` — View all tracked games and toggle individual games on/off for yourself
- `/mystats` — View playtime across all windows, progress bars, per-game breakdown, daily stats, session stats, warning/timeout history, and active session
- `/leaderboard` — View server-wide playtime rankings for the last 7 days (opted-in users only)
- `/history [period] [graph]` — View weekly or monthly playtime history, trends, and day-of-week patterns; optional chart image (requires matplotlib)
- `/privacy` — Toggle your leaderboard visibility
- `/export` — Download all your data as a JSON file
- `/delete-my-data` — Permanently remove all your tracking data

### Admin Commands (Requires Administrator permission)
- `/hammer on` — Enable playtime tracking globally
- `/hammer off` — Disable playtime tracking globally
- `/hammer status` — View bot status, tracked games, threshold rules, and announcement channel config
- `/hammer setchannel <channel>` — Set the announcement channel for threshold alerts
- `/hammer setgame <game>` — Change the legacy target game and register it in the tracking registry
- `/hammer setschedule <day> <hour>` — Configure weekly recap schedule (DMs + shame board)
- `/hammer pardon <user>` — Remove a user's timeout early
- `/hammer exempt <user>` — Toggle a user's exemption from tracking (e.g. streamers)
- `/hammer resetplaytime <user>` — Reset a user's playtime history and threshold events
- `/hammer audit [count]` — View recent admin actions from the audit log

#### Rules
- `/hammer rules list` — View all threshold rules
- `/hammer rules add <hours> <action> <window> [duration] [game] [group_id]` — Add a threshold rule (global, per-game, or per-group)
- `/hammer rules remove <id>` — Remove a rule by ID

#### Roasts
- `/hammer roasts list` — View all custom roast messages
- `/hammer roasts add <action> <message>` — Add a custom roast for warn or timeout events
- `/hammer roasts remove <id>` — Remove a custom roast by ID

#### Games
- `/hammer games list` — List all tracked games with enabled/disabled status
- `/hammer games add <game>` — Add a game to the tracking registry
- `/hammer games remove <game>` — Remove a game from the tracking registry (history preserved)

#### Groups
- `/hammer groups list` — List all game groups and their members
- `/hammer groups create <name>` — Create a new game group
- `/hammer groups delete <group_id>` — Delete a game group
- `/hammer groups addgame <group_id> <game>` — Add a game to a group
- `/hammer groups removegame <group_id> <game>` — Remove a game from a group

---

## Default Threshold Rules

Rules are seeded on first startup and stored in the database. They can be fully managed via `/hammer rules` commands:

| Threshold | Window | Action | Duration |
|-----------|--------|--------|----------|
| 10 hours | Rolling 7-day | Warning | — |
| 15 hours | Rolling 7-day | Timeout | 1 hour |
| 20 hours | Rolling 7-day | Timeout | 6 hours |
| 30 hours | Rolling 7-day | Timeout | 24 hours |

Rules can be global (apply across all games), game-specific, or group-specific (combined playtime across multiple games).

### Announcement Channel

Set an announcement channel via `/hammer setchannel`. When configured, warnings and timeouts post publicly with `@mention` + a random roast message. Falls back to DM if not configured.

---

## How It Works

1. **Opt-in System:** Users run `/opt-in` to consent to tracking
2. **Presence Monitoring:** Bot watches for when opted-in users play any tracked game
3. **Per-Game Sessions:** Start/stop times recorded per game automatically
4. **Multi-Window Limits:** Calculates playtime across rolling 7-day, daily, calendar week, and session windows
5. **Graduated Enforcement:** When a threshold is crossed, the most severe new action is applied
6. **Dedup Protection:** Each rule only fires once per window period
7. **Public Shaming:** Posts roast messages in the announcement channel with @mention
8. **Reversible:** Timeouts expire automatically — no bans, no reinvites needed!

---

## Database Schema

The bot uses SQLite with the following tables:

| Table | Purpose |
|-------|---------|
| `users` | User opt-in status, exemption, and privacy settings |
| `play_sessions` | Individual play sessions (game, start time, end time, duration) |
| `settings` | Global bot configuration (tracking toggle, channels, schedule, etc.) |
| `threshold_rules` | Graduated threshold rules (hours, action, duration, window, game/group scope) |
| `threshold_events` | Dedup tracking for triggered thresholds |
| `tracked_games` | Registry of games the bot monitors |
| `game_groups` | Named groups of games for combined playtime limits |
| `game_group_members` | Membership mapping between groups and game names |
| `user_game_exclusions` | Per-user opt-outs for individual tracked games |
| `proactive_warnings` | Tracks sent proactive (pre-threshold) warnings |
| `audit_log` | Admin action history (pardon, exempt, reset, etc.) |
| `custom_roasts` | Admin-customizable roast messages for warn/timeout events |

Database file: `mjolnir.db` (configurable via `DATABASE_PATH` in `.env`)

---

## License

MIT License — See LICENSE file for details

---

## Design Decisions & Notes

### Why Timeouts Instead of Bans?
- **Reversible** — Timeouts expire automatically, no manual unbanning needed
- **No reinvites** — Users stay in the server, just can't participate temporarily
- **Less punitive** — Better for friendly enforcement in gaming communities
- **Native Discord feature** — Up to 28 days, built-in UI support

### Why Opt-In System?
- **Privacy** — Users consent to being tracked
- **Compliance** — GDPR-friendly approach
- **Trust** — Users know exactly what's being monitored

### Why SQLite?
- **Simple** — No external database server needed
- **Portable** — Single file, easy backups
- **Sufficient** — Handles small-medium Discord servers easily
- **Upgradeable** — Can migrate to PostgreSQL later for large servers

### Key Technical Choices
- **Slash commands** — Modern Discord standard, better UX
- **Presence monitoring** — Real-time tracking without polling
- **Multiple time windows** — Rolling 7-day, daily, calendar week, and session limits
- **Graduated thresholds** — Escalating consequences instead of a single hard cutoff
- **Game groups** — Combined limits across related games without separate rules per game
- **Public roasts** — Fun accountability via announcement channel
- **Structured logging** — Python `logging` module throughout; `"app"` root logger, discord.py internals suppressed to WARNING
- **Dataclasses** — Clean, type-safe models
