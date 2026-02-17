"""
Admin cog for Mjolnir.
Provides commands for users to opt-in/out and admins to control the bot.
"""
import io
import json
import discord
from datetime import datetime, timedelta, timezone
from typing import Optional

from discord import app_commands
from discord.ext import commands


# Display labels for window types
WINDOW_LABELS = {
    "rolling_7d": "Rolling 7-Day",
    "daily": "Daily (24h)",
    "weekly": "Calendar Week",
    "session": "Per Session",
}


def _build_privacy_embed(user) -> discord.Embed:
    """Build the privacy settings embed for a user."""
    embed = discord.Embed(title="Privacy Settings", color=discord.Color.blurple())
    lb_status = "Visible" if user.leaderboard_visible else "Hidden"
    embed.add_field(
        name="Leaderboard Visibility",
        value=(
            f"**{lb_status}**\n"
            "Controls whether you appear on `/leaderboard`."
        ),
        inline=False,
    )
    embed.set_footer(text="Changes take effect immediately.")
    return embed


class DeleteDataView(discord.ui.View):
    """Confirmation view for /delete-my-data."""

    def __init__(self, db, user_id: int):
        super().__init__(timeout=60)
        self.db = db
        self.user_id = user_id

    @discord.ui.button(label="Yes, delete everything", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        result = self.db.delete_all_user_data(self.user_id)
        self.stop()
        await interaction.response.edit_message(
            content=(
                "Your data has been permanently deleted.\n"
                f"Removed **{result['sessions_deleted']}** sessions, "
                f"**{result['events_deleted']}** threshold events, "
                f"and **{result['warnings_deleted']}** warnings."
            ),
            view=None,
        )
        print(f"User {self.user_id} permanently deleted their data")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content="Cancelled. Your data is safe.",
            view=None,
        )


class PrivacyView(discord.ui.View):
    """Interactive view for /privacy settings."""

    def __init__(self, db, user_id: int, leaderboard_visible: bool):
        super().__init__(timeout=60)
        self.db = db
        self.user_id = user_id
        self._sync_button(leaderboard_visible)

    def _sync_button(self, leaderboard_visible: bool):
        if leaderboard_visible:
            self.toggle_leaderboard.label = "Hide from leaderboard"
            self.toggle_leaderboard.style = discord.ButtonStyle.secondary
        else:
            self.toggle_leaderboard.label = "Show on leaderboard"
            self.toggle_leaderboard.style = discord.ButtonStyle.success

    @discord.ui.button(label="placeholder", style=discord.ButtonStyle.secondary)
    async def toggle_leaderboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = self.db.get_user(self.user_id)
        new_visible = not user.leaderboard_visible
        self.db.set_leaderboard_visible(self.user_id, new_visible)
        updated_user = self.db.get_user(self.user_id)
        self._sync_button(new_visible)
        embed = _build_privacy_embed(updated_user)
        await interaction.response.edit_message(embed=embed, view=self)


class Admin(commands.Cog):
    """Admin and user management commands."""

    def __init__(self, bot):
        """Initialize the admin cog."""
        self.bot = bot
        self.db = bot.db

    # ===== User Commands =====

    @app_commands.command(name="opt-in", description="Opt in to playtime tracking")
    async def opt_in(self, interaction: discord.Interaction):
        """Allow user to opt in to tracking."""
        # Set user as opted in
        self.db.set_user_opt_in(interaction.user.id, True)

        settings = self.db.get_settings()
        rules = self.db.get_threshold_rules()

        # Build rules summary grouped by window type
        rules_by_window: dict[str, list] = {}
        for rule in rules:
            rules_by_window.setdefault(rule.window_type, []).append(rule)

        rules_lines = []
        for window_type, window_rules in rules_by_window.items():
            label = WINDOW_LABELS.get(window_type, window_type)
            entries = []
            for r in window_rules:
                if r.action == "timeout":
                    entries.append(f"{r.hours}h = {r.duration_hours}h timeout")
                else:
                    entries.append(f"{r.hours}h = warning")
            rules_lines.append(f"**{label}:** {', '.join(entries)}")

        rules_text = "\n".join(rules_lines) if rules_lines else "No rules configured."

        await interaction.response.send_message(
            f"You've opted in to playtime tracking!\n\n"
            f"**Target game:** {settings.target_game}\n\n"
            f"**Thresholds:**\n{rules_text}\n\n"
            f"If you exceed a threshold, you may be warned or timed out.\n"
            f"Use `/opt-out` to stop tracking at any time.",
            ephemeral=True
        )

        print(f"{interaction.user.name} opted in to tracking")

    @app_commands.command(name="opt-out", description="Opt out of playtime tracking")
    async def opt_out(self, interaction: discord.Interaction):
        """Allow user to opt out of tracking."""
        # Set user as opted out
        self.db.set_user_opt_in(interaction.user.id, False)

        await interaction.response.send_message(
            "You've opted out of playtime tracking.\n\n"
            "Your previous play sessions are still saved, but we won't track new sessions.\n"
            "Use `/opt-in` if you change your mind!",
            ephemeral=True
        )

        print(f"{interaction.user.name} opted out of tracking")

    @app_commands.command(name="export", description="Export your data as JSON (GDPR compliance)")
    async def export(self, interaction: discord.Interaction):
        """Send the invoking user all their stored data as a JSON file."""
        user = self.db.get_user(interaction.user.id)
        if user is None:
            await interaction.response.send_message(
                "You have no data stored in this system.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        data = self.db.get_user_export_data(interaction.user.id)
        json_bytes = json.dumps(data, indent=2).encode("utf-8")
        buf = io.BytesIO(json_bytes)
        buf.seek(0)

        filename = f"mjolnir_export_{interaction.user.id}.json"
        file = discord.File(buf, filename=filename)

        await interaction.followup.send(
            "Here's all the data Mjolnir has stored about you.\n"
            "This includes your play sessions, threshold events, and account settings.",
            file=file,
            ephemeral=True,
        )
        print(f"{interaction.user.name} exported their data")

    @app_commands.command(name="delete-my-data", description="Permanently remove all your tracking data")
    async def delete_my_data(self, interaction: discord.Interaction):
        """Let the invoking user permanently delete all their data."""
        user = self.db.get_user(interaction.user.id)
        if user is None:
            await interaction.response.send_message(
                "You have no data stored in this system.",
                ephemeral=True,
            )
            return

        view = DeleteDataView(self.db, interaction.user.id)
        await interaction.response.send_message(
            "**Are you sure you want to delete all your data?**\n\n"
            "This will permanently remove:\n"
            "- All your play sessions\n"
            "- All threshold events and warnings\n"
            "- Your account record\n\n"
            "This action **cannot be undone**.",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="privacy", description="Manage your privacy settings")
    async def privacy(self, interaction: discord.Interaction):
        """View and toggle privacy controls for the invoking user."""
        user = self.db.get_user(interaction.user.id)
        if user is None:
            await interaction.response.send_message(
                "You have no data stored in this system. Use `/opt-in` first.",
                ephemeral=True,
            )
            return

        embed = _build_privacy_embed(user)
        view = PrivacyView(self.db, interaction.user.id, user.leaderboard_visible)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="mystats", description="View your weekly playtime stats")
    async def mystats(self, interaction: discord.Interaction):
        """Show the invoking user their current playtime across all tracked windows."""
        user = self.db.get_user(interaction.user.id)
        if user is None or not user.opted_in:
            await interaction.response.send_message(
                "You're not currently opted in to playtime tracking.\n"
                "Use `/opt-in` to start!",
                ephemeral=True
            )
            return

        settings = self.db.get_settings()
        rules = self.db.get_threshold_rules()

        # Group rules by window type
        rules_by_window: dict[str, list] = {}
        for rule in rules:
            rules_by_window.setdefault(rule.window_type, []).append(rule)

        # If no rules exist, fall back to legacy single-threshold display
        if not rules:
            rules_by_window = {"rolling_7d": []}

        # Compute playtime for each window and find the closest threshold
        # Track the highest fill percentage for embed color
        max_fill_pct = 0.0

        embed = discord.Embed(title="Your Playtime Stats", color=discord.Color.green())

        # Get active session for live time calculation
        active_session = self.db.get_active_session(interaction.user.id, settings.target_game)
        active_elapsed = 0.0
        if active_session:
            active_elapsed = (
                datetime.now(timezone.utc) - active_session.start_time
            ).total_seconds() / 3600

        for window_type in ["rolling_7d", "daily", "weekly", "session"]:
            window_rules = rules_by_window.get(window_type)
            if not window_rules:
                continue

            label = WINDOW_LABELS.get(window_type, window_type)

            # Get base playtime (completed sessions)
            playtime = self.db.get_playtime_for_window(
                interaction.user.id, window_type
            )

            # Add active session elapsed time for non-session windows
            if window_type != "session" and active_elapsed > 0:
                playtime += active_elapsed

            # Find the next threshold the user hasn't exceeded yet
            next_threshold = None
            for r in window_rules:
                if playtime < r.hours:
                    next_threshold = r
                    break

            # Use highest rule as the bar cap if all exceeded
            bar_cap = next_threshold.hours if next_threshold else window_rules[-1].hours
            fill_pct = min(playtime / bar_cap, 1.0) if bar_cap > 0 else 0.0
            if fill_pct > max_fill_pct:
                max_fill_pct = fill_pct

            # Progress bar
            bar_length = 20
            filled = min(int(fill_pct * bar_length), bar_length)
            bar = "\u2588" * filled + "\u2591" * (bar_length - filled)

            # Next action text
            if next_threshold:
                remaining = max(next_threshold.hours - playtime, 0.0)
                next_text = f"{remaining:.1f}h until {next_threshold.action}"
            else:
                next_text = "All thresholds exceeded"

            embed.add_field(
                name=label,
                value=f"{bar}\n**{playtime:.1f}** / **{bar_cap}** hours\n{next_text}",
                inline=False,
            )

        # Active session field
        if active_session and active_elapsed > 0:
            embed.add_field(
                name="Active Session",
                value=f"**{active_elapsed:.1f} hrs** this session",
                inline=True,
            )

        # Daily breakdown (last 7 days)
        daily_breakdown = self.db.get_daily_breakdown(interaction.user.id)
        day_labels = []
        for date_str, hours in daily_breakdown:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            day_labels.append(f"{dt.strftime('%a')}: {hours:.1f}h")
        embed.add_field(
            name="Daily Breakdown (Last 7 Days)",
            value=" | ".join(day_labels),
            inline=False,
        )

        # Session stats
        session_stats = self.db.get_session_stats(interaction.user.id)
        embed.add_field(
            name="Session Stats",
            value=(
                f"Total sessions: {session_stats['session_count']}\n"
                f"Longest: {session_stats['longest_session_hours']:.1f}h\n"
                f"Average: {session_stats['avg_session_hours']:.1f}h"
            ),
            inline=True,
        )

        # Warning & timeout counts
        wt_counts = self.db.get_warning_timeout_counts(interaction.user.id)
        embed.add_field(
            name="Warnings & Timeouts",
            value=(
                f"Warnings: {wt_counts['warn']}\n"
                f"Timeouts: {wt_counts['timeout']}"
            ),
            inline=True,
        )

        # Upcoming thresholds summary
        upcoming_lines = []
        for window_type, window_rules in rules_by_window.items():
            label = WINDOW_LABELS.get(window_type, window_type)
            playtime = self.db.get_playtime_for_window(
                interaction.user.id, window_type
            )
            if window_type != "session" and active_elapsed > 0:
                playtime += active_elapsed

            pending = [r for r in window_rules if playtime < r.hours]
            if pending:
                entries = []
                for r in pending:
                    if r.action == "timeout":
                        entries.append(f"{r.hours}h (timeout {r.duration_hours}h)")
                    else:
                        entries.append(f"{r.hours}h (warn)")
                upcoming_lines.append(f"**{label}:** {', '.join(entries)}")

        if upcoming_lines:
            embed.add_field(
                name="Upcoming Thresholds",
                value="\n".join(upcoming_lines),
                inline=False,
            )

        # Set embed color based on closest threshold proximity
        if max_fill_pct >= 1.0:
            embed.color = discord.Color.red()
        elif max_fill_pct >= 0.75:
            embed.color = discord.Color.orange()
        elif max_fill_pct >= 0.5:
            embed.color = discord.Color.gold()
        else:
            embed.color = discord.Color.green()

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="View server-wide playtime rankings (opted-in users only)")
    async def leaderboard(self, interaction: discord.Interaction):
        """Show server-wide playtime leaderboard for the last 7 days."""
        most_hours = self.db.get_leaderboard_most_hours()
        longest_session = self.db.get_leaderboard_longest_session()
        most_sessions = self.db.get_leaderboard_most_sessions()

        if not most_hours and not longest_session and not most_sessions:
            await interaction.response.send_message(
                "No playtime data available for the last 7 days.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Playtime Leaderboard (Last 7 Days)",
            color=discord.Color.gold()
        )

        if most_hours:
            lines = [
                f"{i+1}. <@{uid}> — {hours:.1f}h"
                for i, (uid, hours) in enumerate(most_hours)
            ]
            embed.add_field(name="Most Hours Played", value="\n".join(lines), inline=False)

        if longest_session:
            lines = [
                f"{i+1}. <@{uid}> — {hours:.1f}h"
                for i, (uid, hours) in enumerate(longest_session)
            ]
            embed.add_field(name="Longest Single Session", value="\n".join(lines), inline=False)

        if most_sessions:
            lines = [
                f"{i+1}. <@{uid}> — {count} sessions"
                for i, (uid, count) in enumerate(most_sessions)
            ]
            embed.add_field(name="Most Frequent Player", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="history", description="View your playtime history and trends")
    @app_commands.describe(
        period="Time period to analyze (default: weekly)",
        graph="Generate a visual chart image (requires matplotlib)",
    )
    @app_commands.choices(
        period=[
            app_commands.Choice(name="Weekly (last 8 weeks)", value="weekly"),
            app_commands.Choice(name="Monthly (last 6 months)", value="monthly"),
        ],
    )
    async def history(
        self,
        interaction: discord.Interaction,
        period: str = "weekly",
        graph: bool = False,
    ):
        """Show playtime history, trends, and day-of-week patterns."""
        user = self.db.get_user(interaction.user.id)
        if user is None or not user.opted_in:
            await interaction.response.send_message(
                "You're not opted in to playtime tracking.\nUse `/opt-in` to start!",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        if period == "weekly":
            history_data = self.db.get_weekly_history(interaction.user.id, weeks=8)
            chart_title = "Weekly Playtime (Last 8 Weeks)"
            period_label = "Week"
        else:
            history_data = self.db.get_monthly_history(interaction.user.id, months=6)
            chart_title = "Monthly Playtime (Last 6 Months)"
            period_label = "Month"

        dow_data = self.db.get_dow_pattern(interaction.user.id, days=30)

        embed = discord.Embed(title="Playtime History", color=discord.Color.blue())

        # Text bar chart
        max_h = max((h for _, h in history_data), default=0.0) or 1.0
        bar_len = 15
        chart_lines = []
        for label, hours in history_data:
            filled = min(int((hours / max_h) * bar_len), bar_len)
            bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
            chart_lines.append(f"`{label}` {bar} **{hours:.1f}h**")
        embed.add_field(
            name=chart_title,
            value="\n".join(chart_lines) if chart_lines else "No data yet.",
            inline=False,
        )

        # Current vs previous period comparison
        if len(history_data) >= 2:
            current_h = history_data[-1][1]
            prev_h = history_data[-2][1]
            diff = current_h - prev_h
            if diff > 0:
                arrow, change_str = "▲", f"+{diff:.1f}h"
            elif diff < 0:
                arrow, change_str = "▼", f"-{abs(diff):.1f}h"
            else:
                arrow, change_str = "→", "no change"
            embed.add_field(
                name=f"This {period_label} vs Last {period_label}",
                value=(
                    f"Current: **{current_h:.1f}h**\n"
                    f"Previous: **{prev_h:.1f}h**\n"
                    f"Change: {arrow} **{change_str}**"
                ),
                inline=True,
            )

        # Day-of-week pattern
        if any(v > 0 for v in dow_data.values()):
            max_dow_h = max(dow_data.values()) or 1.0
            dow_lines = []
            for i, name in enumerate(DOW_NAMES):
                hours = dow_data.get(i, 0.0)
                filled = min(int((hours / max_dow_h) * 10), 10)
                bar = "\u2588" * filled + "\u2591" * (10 - filled)
                dow_lines.append(f"`{name}` {bar} {hours:.1f}h")
            embed.add_field(
                name="Day-of-Week Pattern (Last 30 Days)",
                value="\n".join(dow_lines),
                inline=False,
            )
            busiest = max(dow_data, key=dow_data.get)
            embed.add_field(
                name="Pattern Insight",
                value=f"You play most on **{DOW_NAMES[busiest]}s**.",
                inline=True,
            )

        if not graph:
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Generate chart image
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.patches as mpatches

            labels = [lbl for lbl, _ in history_data]
            hours_vals = [h for _, h in history_data]
            dow_hours = [dow_data.get(i, 0.0) for i in range(7)]

            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
            fig.set_facecolor("#2C2F33")

            # History bar chart
            ax1.bar(labels, hours_vals, color="#5865F2", width=0.6, edgecolor="#FFFFFF22")
            ax1.set_title(chart_title, color="white", fontsize=10, pad=8)
            ax1.set_ylabel("Hours", color="#B9BBBE")
            ax1.tick_params(colors="#B9BBBE")
            ax1.set_facecolor("#36393F")
            for spine in ax1.spines.values():
                spine.set_edgecolor("#4F545C")
            ax1.yaxis.grid(True, color="#4F545C", linestyle="--", alpha=0.5)
            ax1.set_axisbelow(True)
            plt.setp(ax1.get_xticklabels(), rotation=30, ha="right", fontsize=8, color="#B9BBBE")

            # Day-of-week chart
            weekend_colors = ["#FEE75C" if i >= 5 else "#5865F2" for i in range(7)]
            ax2.bar(DOW_NAMES, dow_hours, color=weekend_colors, width=0.6, edgecolor="#FFFFFF22")
            ax2.set_title("Day-of-Week Pattern (30 Days)", color="white", fontsize=10, pad=8)
            ax2.set_ylabel("Hours", color="#B9BBBE")
            ax2.tick_params(colors="#B9BBBE")
            ax2.set_facecolor("#36393F")
            for spine in ax2.spines.values():
                spine.set_edgecolor("#4F545C")
            ax2.yaxis.grid(True, color="#4F545C", linestyle="--", alpha=0.5)
            ax2.set_axisbelow(True)
            plt.setp(ax2.get_xticklabels(), color="#B9BBBE")
            weekday_patch = mpatches.Patch(color="#5865F2", label="Weekday")
            weekend_patch = mpatches.Patch(color="#FEE75C", label="Weekend")
            ax2.legend(
                handles=[weekday_patch, weekend_patch],
                facecolor="#2C2F33", labelcolor="white", framealpha=0.8,
            )

            plt.tight_layout(pad=2.0)
            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=120, facecolor="#2C2F33")
            buf.seek(0)
            plt.close(fig)

            file = discord.File(buf, filename="history.png")
            embed.set_image(url="attachment://history.png")
            await interaction.followup.send(embed=embed, file=file, ephemeral=True)

        except ImportError:
            embed.set_footer(text="Install matplotlib to enable graph generation: pip install matplotlib")
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ===== Admin Commands =====

    hammer = app_commands.Group(
        name="hammer",
        description="Control Mjolnir's tracking system",
        default_permissions=discord.Permissions(administrator=True),
    )

    rules = app_commands.Group(
        name="rules",
        description="Manage threshold rules",
        parent=hammer,
    )

    roasts = app_commands.Group(
        name="roasts",
        description="Manage custom roast messages",
        parent=hammer,
    )

    @hammer.command(name="on", description="Enable playtime tracking")
    async def hammer_on(self, interaction: discord.Interaction):
        """Enable playtime tracking."""
        settings = self.db.get_settings()

        if settings.tracking_enabled:
            await interaction.response.send_message(
                "Tracking is already enabled.",
                ephemeral=True
            )
        else:
            self.db.update_settings(tracking_enabled=True)
            await interaction.response.send_message(
                "**Mjolnir activated!**\n\n"
                "Playtime tracking is now **enabled**.\n"
                f"Monitoring: **{settings.target_game}**",
                ephemeral=False
            )
            print("Tracking enabled by admin")

    @hammer.command(name="off", description="Disable playtime tracking")
    async def hammer_off(self, interaction: discord.Interaction):
        """Disable playtime tracking."""
        settings = self.db.get_settings()

        if not settings.tracking_enabled:
            await interaction.response.send_message(
                "Tracking is already disabled.",
                ephemeral=True
            )
        else:
            self.db.update_settings(tracking_enabled=False)
            await interaction.response.send_message(
                "**Mjolnir deactivated.**\n\n"
                "Playtime tracking is now **disabled**.\n"
                "Active sessions will not be tracked.",
                ephemeral=False
            )
            print("Tracking disabled by admin")

    @hammer.command(name="status", description="View Mjolnir's current status and configuration")
    async def hammer_status(self, interaction: discord.Interaction):
        """Show bot status, settings, and rule summary."""
        settings = self.db.get_settings()
        status_text = "ENABLED" if settings.tracking_enabled else "DISABLED"
        opted_in_count = len(self.db.get_opted_in_users())
        rules = self.db.get_threshold_rules()

        embed = discord.Embed(
            title="Mjolnir Status",
            color=discord.Color.blue() if settings.tracking_enabled else discord.Color.red()
        )

        embed.add_field(
            name="Tracking Status",
            value=f"**{status_text}**",
            inline=True
        )

        embed.add_field(
            name="Opted-In Users",
            value=f"**{opted_in_count}** users",
            inline=True
        )

        embed.add_field(
            name="Target Game",
            value=f"**{settings.target_game}**",
            inline=False
        )

        channel_text = "Not configured"
        if settings.announcement_channel_id:
            channel = self.bot.get_channel(settings.announcement_channel_id)
            channel_text = channel.mention if channel else f"ID: {settings.announcement_channel_id}"
        embed.add_field(
            name="Announcement Channel",
            value=channel_text,
            inline=True,
        )

        if rules:
            rules_by_window: dict[str, list] = {}
            for rule in rules:
                rules_by_window.setdefault(rule.window_type, []).append(rule)

            rules_lines = []
            for window_type, window_rules in rules_by_window.items():
                label = WINDOW_LABELS.get(window_type, window_type)
                entries = []
                for r in window_rules:
                    if r.action == "timeout":
                        entries.append(f"{r.hours}h = {r.duration_hours}h timeout")
                    else:
                        entries.append(f"{r.hours}h = warning")
                rules_lines.append(f"**{label}:** {', '.join(entries)}")

            embed.add_field(
                name="Threshold Rules",
                value="\n".join(rules_lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="Threshold Rules",
                value="No rules configured.",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ----- /hammer setchannel -----

    @hammer.command(
        name="setchannel",
        description="Set the announcement channel for threshold alerts"
    )
    @app_commands.describe(channel="The text channel to send announcements to")
    async def hammer_setchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        """Set the announcement channel."""
        self.db.update_settings(announcement_channel_id=channel.id)
        await interaction.response.send_message(
            f"Announcement channel set to {channel.mention}.",
            ephemeral=True
        )
        print(f"Announcement channel set to #{channel.name} by admin")

    # ----- /hammer setgame -----

    @hammer.command(name="setgame", description="Change the target game to monitor")
    @app_commands.describe(game="The game name to track (case-insensitive matching)")
    async def hammer_setgame(self, interaction: discord.Interaction, game: str):
        """Change the target game being tracked."""
        game = game.strip()
        if not game:
            await interaction.response.send_message(
                "Game name cannot be empty.", ephemeral=True
            )
            return

        self.db.update_settings(target_game=game)
        await interaction.response.send_message(
            f"Target game updated to **{game}**.",
            ephemeral=True
        )
        print(f"Target game changed to '{game}' by admin")

    # ----- /hammer rules list -----

    @rules.command(name="list", description="View all threshold rules")
    async def rules_list(self, interaction: discord.Interaction):
        """Display every threshold rule grouped by window type."""
        all_rules = self.db.get_threshold_rules()

        if not all_rules:
            await interaction.response.send_message(
                "No threshold rules configured.\n"
                "Use `/hammer rules add` to create one.",
                ephemeral=True
            )
            return

        rules_by_window: dict[str, list] = {}
        for rule in all_rules:
            rules_by_window.setdefault(rule.window_type, []).append(rule)

        embed = discord.Embed(title="Threshold Rules", color=discord.Color.blue())

        for window_type in ["rolling_7d", "daily", "weekly", "session"]:
            window_rules = rules_by_window.get(window_type)
            if not window_rules:
                continue

            label = WINDOW_LABELS.get(window_type, window_type)
            lines = []
            for r in window_rules:
                if r.action == "timeout":
                    lines.append(
                        f"`#{r.id}` — **{r.hours}h** = "
                        f"**{r.duration_hours}h** timeout"
                    )
                else:
                    lines.append(f"`#{r.id}` — **{r.hours}h** = warning")
            embed.add_field(name=label, value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ----- /hammer rules add -----

    @rules.command(name="add", description="Add a new threshold rule")
    @app_commands.describe(
        hours="Playtime threshold in hours",
        action="Action to take when threshold is reached",
        duration="Timeout duration in hours (required for timeout action)",
        window="Time window for this rule",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="warn", value="warn"),
            app_commands.Choice(name="timeout", value="timeout"),
        ],
        window=[
            app_commands.Choice(name="Rolling 7-Day", value="rolling_7d"),
            app_commands.Choice(name="Daily (24h)", value="daily"),
            app_commands.Choice(name="Calendar Week", value="weekly"),
            app_commands.Choice(name="Per Session", value="session"),
        ],
    )
    async def rules_add(
        self,
        interaction: discord.Interaction,
        hours: float,
        action: str,
        window: str,
        duration: Optional[int] = None,
    ):
        """Add a threshold rule after validating inputs."""
        if hours <= 0:
            await interaction.response.send_message(
                "Hours must be greater than 0.", ephemeral=True
            )
            return

        if action == "timeout" and (duration is None or duration <= 0):
            await interaction.response.send_message(
                "A timeout rule requires a positive duration (hours).",
                ephemeral=True
            )
            return

        if action == "warn":
            duration = None

        rule = self.db.add_threshold_rule(
            hours=hours,
            action=action,
            duration_hours=duration,
            window_type=window,
        )

        label = WINDOW_LABELS.get(window, window)
        if action == "timeout":
            desc = f"**{hours}h** = **{duration}h** timeout"
        else:
            desc = f"**{hours}h** = warning"

        await interaction.response.send_message(
            f"Rule `#{rule.id}` added to **{label}**:\n{desc}",
            ephemeral=True
        )
        print(f"Threshold rule #{rule.id} added by admin")

    # ----- /hammer rules remove -----

    @rules.command(name="remove", description="Remove a threshold rule by ID")
    @app_commands.describe(rule_id="The rule ID to remove (shown in rules list)")
    async def rules_remove(self, interaction: discord.Interaction, rule_id: int):
        """Delete a threshold rule."""
        deleted = self.db.delete_threshold_rule(rule_id)

        if deleted:
            await interaction.response.send_message(
                f"Rule `#{rule_id}` has been removed.",
                ephemeral=True
            )
            print(f"Threshold rule #{rule_id} removed by admin")
        else:
            await interaction.response.send_message(
                f"No rule found with ID `#{rule_id}`.",
                ephemeral=True
            )


    # ----- /hammer roasts list -----

    @roasts.command(name="list", description="View all custom roast messages")
    async def roasts_list(self, interaction: discord.Interaction):
        """Display custom roast messages or indicate defaults are in use."""
        all_roasts = self.db.get_custom_roasts()

        if not all_roasts:
            await interaction.response.send_message(
                "No custom roasts configured — using default roast messages.\n"
                "Use `/hammer roasts add` to add your own!",
                ephemeral=True
            )
            return

        embed = discord.Embed(title="Custom Roast Messages", color=discord.Color.orange())

        warn_roasts = [r for r in all_roasts if r.action == "warn"]
        timeout_roasts = [r for r in all_roasts if r.action == "timeout"]

        if warn_roasts:
            lines = [f"`#{r.id}` — {r.message}" for r in warn_roasts]
            embed.add_field(name="Warning Roasts", value="\n".join(lines), inline=False)

        if timeout_roasts:
            lines = [f"`#{r.id}` — {r.message}" for r in timeout_roasts]
            embed.add_field(name="Timeout Roasts", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ----- /hammer roasts add -----

    @roasts.command(name="add", description="Add a custom roast message")
    @app_commands.describe(
        action="When to use this roast (warn or timeout)",
        message="The roast message text",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="warn", value="warn"),
            app_commands.Choice(name="timeout", value="timeout"),
        ],
    )
    async def roasts_add(
        self, interaction: discord.Interaction, action: str, message: str
    ):
        """Add a custom roast message."""
        message = message.strip()
        if not message:
            await interaction.response.send_message(
                "Roast message cannot be empty.", ephemeral=True
            )
            return

        roast = self.db.add_custom_roast(action=action, message=message)
        await interaction.response.send_message(
            f"Roast `#{roast.id}` added for **{action}**:\n{message}",
            ephemeral=True
        )
        print(f"Custom roast #{roast.id} added by admin")

    # ----- /hammer roasts remove -----

    @roasts.command(name="remove", description="Remove a custom roast by ID")
    @app_commands.describe(roast_id="The roast ID to remove (shown in roasts list)")
    async def roasts_remove(self, interaction: discord.Interaction, roast_id: int):
        """Delete a custom roast message."""
        deleted = self.db.delete_custom_roast(roast_id)

        if deleted:
            await interaction.response.send_message(
                f"Roast `#{roast_id}` has been removed.",
                ephemeral=True
            )
            print(f"Custom roast #{roast_id} removed by admin")
        else:
            await interaction.response.send_message(
                f"No roast found with ID `#{roast_id}`.",
                ephemeral=True
            )

    # ----- /hammer setschedule -----

    DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    @hammer.command(
        name="setschedule",
        description="Set the day and hour for weekly recap posts"
    )
    @app_commands.describe(
        day="Day of the week for weekly recap",
        hour="Hour in UTC (0-23) for weekly recap",
    )
    @app_commands.choices(
        day=[
            app_commands.Choice(name="Monday", value=0),
            app_commands.Choice(name="Tuesday", value=1),
            app_commands.Choice(name="Wednesday", value=2),
            app_commands.Choice(name="Thursday", value=3),
            app_commands.Choice(name="Friday", value=4),
            app_commands.Choice(name="Saturday", value=5),
            app_commands.Choice(name="Sunday", value=6),
        ],
    )
    async def hammer_setschedule(
        self, interaction: discord.Interaction, day: int, hour: int
    ):
        """Set the weekly recap schedule."""
        if hour < 0 or hour > 23:
            await interaction.response.send_message(
                "Hour must be between 0 and 23.", ephemeral=True
            )
            return

        self.db.update_settings(weekly_recap_day=day, weekly_recap_hour=hour)
        day_name = self.DAY_NAMES[day]
        await interaction.response.send_message(
            f"Weekly recap set to **{day_name}** at **{hour:02d}:00 UTC**.",
            ephemeral=True
        )
        print(f"Weekly recap schedule set to {day_name} {hour:02d}:00 UTC by admin")

    # ===== Manual Override Commands =====

    # ----- /hammer pardon -----

    @hammer.command(name="pardon", description="Remove a user's timeout early")
    @app_commands.describe(user="The user to pardon")
    async def hammer_pardon(
        self, interaction: discord.Interaction, user: discord.Member
    ):
        """Remove a user's active timeout."""
        try:
            await user.timeout(None, reason=f"Pardoned by {interaction.user.name}")
        except discord.Forbidden:
            await interaction.response.send_message(
                f"Cannot pardon {user.mention} — missing permissions.",
                ephemeral=True
            )
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"Failed to pardon {user.mention}: {e}",
                ephemeral=True
            )
            return

        self.db.add_audit_log(
            admin_id=interaction.user.id,
            action_type="pardon",
            target_user_id=user.id,
            details=f"Timeout removed by {interaction.user.name}",
        )

        await interaction.response.send_message(
            f"{user.mention} has been pardoned. Their timeout has been removed.",
            ephemeral=True
        )
        print(f"{user.name} pardoned by {interaction.user.name}")

    # ----- /hammer exempt -----

    @hammer.command(
        name="exempt",
        description="Toggle a user's exemption from tracking"
    )
    @app_commands.describe(user="The user to exempt or un-exempt")
    async def hammer_exempt(
        self, interaction: discord.Interaction, user: discord.Member
    ):
        """Toggle exemption status for a user."""
        db_user = self.db.get_user(user.id)
        currently_exempt = db_user.exempt if db_user else False
        new_status = not currently_exempt

        self.db.set_user_exempt(user.id, new_status)

        action = "exempt" if new_status else "unexempt"
        self.db.add_audit_log(
            admin_id=interaction.user.id,
            action_type=action,
            target_user_id=user.id,
        )

        if new_status:
            await interaction.response.send_message(
                f"{user.mention} is now **exempt** from tracking.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{user.mention} is no longer exempt from tracking.",
                ephemeral=True
            )
        print(f"{user.name} {action}ed by {interaction.user.name}")

    # ----- /hammer resetplaytime -----

    @hammer.command(
        name="resetplaytime",
        description="Reset a user's playtime history and threshold events"
    )
    @app_commands.describe(user="The user whose playtime to reset")
    async def hammer_resetplaytime(
        self, interaction: discord.Interaction, user: discord.Member
    ):
        """Reset all play sessions and threshold events for a user."""
        sessions_deleted = self.db.delete_user_sessions(user.id)
        events_cleared = self.db.clear_threshold_events(user.id)

        self.db.add_audit_log(
            admin_id=interaction.user.id,
            action_type="reset_playtime",
            target_user_id=user.id,
            details=f"Deleted {sessions_deleted} sessions, {events_cleared} events",
        )

        await interaction.response.send_message(
            f"Reset playtime for {user.mention}.\n"
            f"Removed **{sessions_deleted}** sessions and "
            f"**{events_cleared}** threshold events.",
            ephemeral=True
        )
        print(f"Playtime reset for {user.name} by {interaction.user.name}")

    # ----- /hammer audit -----

    @hammer.command(name="audit", description="View recent admin actions")
    @app_commands.describe(count="Number of entries to show (default 10)")
    async def hammer_audit(
        self, interaction: discord.Interaction, count: Optional[int] = 10
    ):
        """Display recent audit log entries."""
        entries = self.db.get_audit_log(limit=min(count or 10, 25))

        if not entries:
            await interaction.response.send_message(
                "No audit log entries yet.", ephemeral=True
            )
            return

        embed = discord.Embed(title="Admin Audit Log", color=discord.Color.dark_grey())

        for entry in entries:
            timestamp = entry.created_at.strftime("%Y-%m-%d %H:%M UTC")
            value = (
                f"Admin: <@{entry.admin_id}>\n"
                f"Target: <@{entry.target_user_id}>\n"
                f"Time: {timestamp}"
            )
            if entry.details:
                value += f"\n{entry.details}"
            embed.add_field(
                name=entry.action_type.replace("_", " ").title(),
                value=value,
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    """Load the Admin cog."""
    await bot.add_cog(Admin(bot))
