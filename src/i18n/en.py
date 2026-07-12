"""English UI strings for HabiTracker."""

STRINGS: dict[str, str] = {
    # --- start / onboarding ---
    "start.title": "👋 <b>HabiTracker</b> — a bot for habits and schedules.",
    "start.body": (
        "Build habits, get daily tasks, and track completion.\n"
        "The AI assistant turns «I want to move more» into a concrete "
        "SMART goal — without calendar time conflicts."
    ),
    "start.how_to_title": "🚀 <b>How to start</b>",
    "start.how_to_1": "1. Tap «➕ Create habit»",
    "start.how_to_2": "2. Choose manual or AI-assisted",
    "start.how_to_3": "3. The bot schedules tasks for you",
    "start.links_title": "🔗 <b>Links</b>",
    "start.link_original": "• Original: @{username}",
    "start.link_channel": "• Channel: {url}",
    "start.link_bot": "• Bot: {url}",
    "start.cta": "Choose an action:",
    # --- main menu labels ---
    "main.menu": "🏠 Main menu\nChoose an action:",
    "main.habits": "📋 Habits",
    "main.new_habit": "➕ Create habit",
    "main.new_task": "➕ Add task",
    "main.today_tasks": "📅 Today's tasks",
    "main.view_schedule": "📅 Schedule",
    "main.complete_tasks": "✅ Mark completed",
    "main.statistics": "📊 Statistics",
    "main.settings": "⚙️ Settings",
    "main.help": "❓ Help",
    "main.under_development": "Feature '{label}' is under development. Stay tuned!",
    "main.new_habit_choice": "Choose how to create a habit:",
    # --- help ---
    "help.text": (
        "📖 <b>How to use the bot:</b>\n\n"
        "• <b>➕ Create habit</b> — create a new habit manually "
        "or with the AI assistant\n"
        "• <b>📋 Habits</b> — view and manage your habits\n"
        "• <b>📊 Statistics</b> — view habit completion stats\n"
        "• <b>⚙️ Settings</b> — language, timezone, reminders\n"
        "• <b>❓ Help</b> — you are here!\n\n"
        "Support: @support"
    ),
    # --- common ---
    "common.back": "⬅️ Back",
    "common.main_menu_btn": "🏠 Main menu",
    "common.user_not_found": "⚠️ User not found. Use /start to register.",
    "common.cancel": "❌ Cancel",
    "common.cancelled": "❌ Action cancelled.",
    "common.error": "⚠️ Something went wrong. Please try again.",
    "common.off": "off",
    "common.minutes": "{n} min",
    # --- settings ---
    "settings.title": "⚙️ Settings",
    "settings.choose": "Choose a setting to change:",
    "settings.menu": (
        "⚙️ <b>Settings</b>\n\n"
        "🌐 Language: <b>{language}</b>\n"
        "🕐 Timezone: <b>{timezone}</b>\n"
        "⏰ Reminder: <b>{reminder}</b>\n"
        "⏱ Check interval: <b>{interval}</b>\n\n"
        "Choose a setting to change:"
    ),
    "settings.btn_language": "🌐 Language",
    "settings.btn_timezone": "🕐 Timezone",
    "settings.btn_reminder": "⏰ Reminder time",
    "settings.btn_interval": "⏱ Check interval",
    "settings.choose_language": "🌐 Choose language:",
    "settings.choose_timezone": "🕐 Choose timezone:",
    "settings.choose_reminder": "⏰ Choose daily reminder time:",
    "settings.choose_interval": "⏱ Choose check-in interval:",
    "settings.lang_changed": "✅ Language changed to {code}.",
    "settings.tz_changed": "✅ Timezone changed to UTC{tz}.",
    "settings.reminder_set": "⏰ Reminder time set to {time}.",
    "settings.reminder_off": "🔕 Reminders disabled.",
    "settings.interval_set": "⏱ Check interval set to {n} min.",
    "settings.reminder_disable": "🔕 Disable",
    "settings.interval_option": "{n} min",
    # --- reminder ---
    "reminder.text": (
        "⏰ Reminder\n"
        "Time to mark today's habits and tasks.\n"
        "Open the bot and check your schedule."
    ),
    # --- check-in ---
    "checkin.prompt": "Did you complete «{title}»?",
    "checkin.yes_ack": "✅ «{title}» marked as completed.",
    "checkin.no_ack": "❌ «{title}» — {status}. We'll remind you later.",
    "checkin.status_done": "already completed",
    "checkin.status_pending": "not completed yet",
    "checkin.invalid": "Invalid data.",
    "checkin.user_not_found": "User not found.",
    "checkin.task_not_found": "⛔ Task not found or unavailable.",
    "checkin.yes_toast": "✅ Marked as completed",
    "checkin.no_toast": "OK, we'll remind you later",
}
