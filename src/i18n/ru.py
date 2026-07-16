"""Russian UI strings for HabiTracker."""

STRINGS: dict[str, str] = {
    # --- start / onboarding ---
    "start.title": "👋 <b>HabiTracker</b> — бот для привычек и расписания.",
    "start.body": (
        "Формируйте привычки, получайте задачи на день и отмечайте выполнение.\n"
        "AI-ассистент поможет превратить «хочу больше двигаться» "
        "в конкретную SMART-цель — без конфликтов времени в календаре."
    ),
    "start.how_to_title": "🚀 <b>Как начать</b>",
    "start.how_to_1": "1. Нажмите «➕ Создать привычку»",
    "start.how_to_2": "2. Выберите вручную или с помощью AI",
    "start.how_to_3": "3. Бот сам поставит задачи в расписание",
    "start.links_title": "🔗 <b>Ссылки</b>",
    "start.link_original": "• Оригинал: @{username}",
    "start.link_channel": "• Канал: {url}",
    "start.link_bot": "• Бот: {url}",
    "start.cta": "Выберите действие:",
    # --- main menu labels ---
    "main.menu": "🏠 Главное меню бота\nВыберите действие:",
    "main.open_dashboard": "🌐 Открыть приложение",
    "main.habits": "📋 Привычки",

    "main.new_habit": "➕ Создать привычку",
    "main.new_task": "➕ Добавить задачу",
    "main.today_tasks": "📅 Задачи на сегодня",
    "main.view_schedule": "📅 Расписание",
    "main.complete_tasks": "✅ Отметить выполненные",
    "main.statistics": "📊 Статистика",
    "main.settings": "⚙️ Настройки",
    "main.help": "❓ Помощь",
    "stats.open_dashboard": "📊 Открыть дашборд",
    "stats.back": "⬅️ Назад",
    "stats.btn_7d": "7д",
    "stats.btn_7d_active": "• 7д",
    "stats.btn_30d": "30д",
    "stats.btn_30d_active": "• 30д",
    "stats.btn_habits": "📋 Привычки",
    "stats.btn_daily": "📅 По дням",
    "stats.btn_overview": "📊 Сводка",
    "stats.refresh_link": "🔄 Ссылка на дашборд",
    "stats.title": "📊 <b>Ваша статистика за последние {days} дн.:</b>",
    "stats.title_empty": "📊 <b>Статистика</b>",
    "stats.empty_all": (
        "У вас пока нет задач и привычек.\n"
        "Создайте первую привычку или задачу, "
        "чтобы начать отслеживать прогресс! 🚀"
    ),
    "stats.empty_tasks": (
        "Задач за этот период нет. Добавьте задачи, "
        "чтобы увидеть прогресс!"
    ),
    "stats.completed_line": "✅ Выполнено: {completed} из {total} задач ({rate}%)",
    "stats.missed_line": "📅 Пропущено: {missed} задач",
    "stats.habits_line": "📋 Всего привычек: {count}",
    "stats.streak_line": "🔥 Текущая серия: {streak} дн. подряд",
    "stats.streak_zero": "🔥 Текущая серия: 0 дн.",
    "stats.keep_going": "Продолжайте в том же духе! 💪",
    "stats.dashboard_unavailable": (
        "\n\n⚠️ Веб-дашборд сейчас недоступен "
        "(не настроен URL или временная ошибка)."
    ),
    "stats.habits_title": "📋 <b>Привычки за {days} дн.</b>",
    "stats.habits_empty": "Привычек пока нет. Создайте первую в боте.",
    "stats.habit_line": "• <b>{title}</b> — {completed}/{total} ({rate}%)",
    "stats.daily_title": "📅 <b>По дням за {days} дн.</b>",
    "stats.daily_line": "{date}: ✅{completed} ❌{missed}",
    "stats.daily_empty_day": "{date}: —",
    "stats.link_issued": "✅ Ссылка на дашборд обновлена. Нажмите кнопку ниже.",
    "stats.link_failed": (
        "⚠️ Не удалось создать ссылку на дашборд. "
        "Проверьте, что DASHBOARD_PUBLIC_URL задан и Redis доступен."
    ),
    "main.under_development": "Функция '{label}' находится в разработке. Следите за обновлениями!",
    "main.new_habit_choice": "Выберите способ создания привычки:",
    # --- help ---
    "help.text": (
        "📖 <b>Как пользоваться ботом:</b>\n\n"
        "• <b>🌐 Открыть приложение</b> — веб-дашборд (привычки, задачи, статистика)\n"
        "• <b>➕ Создать привычку</b> — создайте новую привычку вручную "
        "или с помощью ИИ-ассистента\n"
        "• <b>📋 Привычки</b> — просмотр и управление вашими привычками\n"
        "• <b>📊 Статистика</b> — просмотр статистики выполнения привычек\n"
        "• <b>⚙️ Настройки</b> — настройка языка, часового пояса, напоминаний\n"
        "• <b>❓ Помощь</b> — вы здесь!\n\n"
        "По вопросам: @support"
    ),

    # --- common ---
    "common.back": "⬅️ Назад",
    "common.main_menu_btn": "🏠 В главное меню",
    "common.user_not_found": "⚠️ Пользователь не найден. Используйте /start для регистрации.",
    "common.cancel": "❌ Отмена",
    "common.cancelled": "❌ Действие отменено.",
    "common.error": "⚠️ Произошла ошибка. Попробуйте ещё раз.",
    "common.off": "выкл",
    "common.on": "вкл",
    "common.minutes": "{n} мин",
    # --- settings ---
    "settings.title": "⚙️ Настройки",
    "settings.choose": "Выберите параметр для изменения:",
    "settings.menu": (
        "⚙️ <b>Настройки</b>\n\n"
        "🌐 Язык: <b>{language}</b>\n"
        "🕐 Часовой пояс: <b>{timezone}</b>\n"
        "⏰ Уведомление: <b>{reminder}</b>\n"
        "⏱ Интервал проверки: <b>{interval}</b>\n"
        "🔕 Без спама check-in: <b>{no_spam}</b>\n"
        "📅 Спрашивать про перенос: <b>{ask_rollover}</b>\n\n"
        "Выберите параметр для изменения:"
    ),
    "settings.btn_language": "🌐 Язык",
    "settings.btn_timezone": "🕐 Часовой пояс",
    "settings.btn_reminder": "⏰ Время уведомления",
    "settings.btn_interval": "⏱ Интервал проверки",
    "settings.btn_no_spam": "🔕 Без спама check-in: {state}",
    "settings.btn_ask_rollover": "📅 Спрашивать про перенос: {state}",
    "settings.choose_language": "🌐 Выберите язык:",
    "settings.choose_timezone": "🕐 Выберите часовой пояс:",
    "settings.choose_reminder": "⏰ Выберите время ежедневного уведомления:",
    "settings.choose_interval": "⏱ Выберите интервал проверки выполнения:",
    "settings.lang_changed": "✅ Язык изменён на {code}.",
    "settings.tz_changed": "✅ Часовой пояс изменён на UTC{tz}.",
    "settings.reminder_set": "⏰ Время уведомления установлено на {time}.",
    "settings.reminder_off": "🔕 Уведомления отключены.",
    "settings.interval_set": "⏱ Интервал проверки установлен на {n} мин.",
    "settings.no_spam_on": "✅ Без спама check-in: включено.",
    "settings.no_spam_off": "✅ Без спама check-in: выключено.",
    "settings.ask_rollover_on": "✅ Спрашивать про перенос: включено.",
    "settings.ask_rollover_off": "✅ Спрашивать про перенос: выключено.",
    "settings.reminder_disable": "🔕 Отключить",
    "settings.interval_option": "{n} мин",
    # --- task extras ---
    "task.add_today": "➕ Добавить задачу",
    "task.no_time": "⏳ Без времени",
    "task.untimed": "без времени",
    "task.open_ended": "без окончания",
    "task.created_ok": "✅ Задача «{title}» успешно создана на {date}!",
    "task.ask_rollover": (
        "📅 Переносить задачу «{title}» на следующий день, "
        "если она не будет выполнена?"
    ),
    "task.rollover_yes": "✅ Да, переносить",
    "task.rollover_no": "❌ Нет",
    "task.rollover_enabled": "✅ Автоперенос включён для «{title}».",
    "task.rollover_disabled": "ℹ️ Автоперенос выключен для «{title}».",
    "task.btn_rollover_on": "📅 Автоперенос: вкл",
    "task.btn_rollover_off": "📅 Автоперенос: выкл",
    "task.rollover_toggled_on": "✅ Автоперенос включён.",
    "task.rollover_toggled_off": "ℹ️ Автоперенос выключен.",

    # --- reminder ---
    "reminder.text": (
        "⏰ Напоминание\n"
        "Пора отметить привычки и задачи на сегодня.\n"
        "Откройте бота и проверьте расписание."
    ),
    # --- check-in ---
    "checkin.prompt": "Выполнили «{title}»?",
    "checkin.yes_ack": "✅ «{title}» отмечено выполненным.",
    "checkin.no_ack": "❌ «{title}» — {status}. Напомним позже.",
    "checkin.mute_ack": "🔕 «{title}» — больше не напомним сегодня.",
    "checkin.snooze_ack": "⏰ «{title}» — напомним через {n} мин.",
    "checkin.moved_ack": "📅 «{title}» перенесено на {time}.",
    "checkin.choose_snooze": "Через сколько напомнить о «{title}»?",
    "checkin.choose_slot": "Выберите свободное время для «{title}»:",
    "checkin.no_free_slots": "Сегодня больше нет свободного времени для «{title}».",
    "checkin.status_done": "уже выполнено",
    "checkin.status_pending": "пока не выполнено",
    "checkin.invalid": "Некорректные данные.",
    "checkin.user_not_found": "Пользователь не найден.",
    "checkin.task_not_found": "⛔ Задача не найдена или недоступна.",
    "checkin.yes_toast": "✅ Отмечено выполненным",
    "checkin.no_toast": "Ок, напомним позже",
    "checkin.mute_toast": "Больше не напомним сегодня",
    "checkin.snooze_toast": "Напомним через {n} мин",
    "checkin.moved_toast": "Перенесено на {time}",
    "checkin.btn_yes": "✅ Да",
    "checkin.btn_mute": "❌ Нет, не напоминать",
    "checkin.btn_later": "⏰ Напомнить позже",
    "checkin.btn_reschedule": "📅 Перенести",
    "checkin.snooze_option": "{n} мин",
    "checkin.back": "⬅️ Назад",

    # --- task AI assistant (B4) ---
    "task_ai.choice_title": "Выберите способ добавления задачи:",
    "task_ai.btn_manual": "✍️ Добавить вручную",
    "task_ai.btn_ai": "🤖 Запросить помощь ассистента",
    "task_ai.btn_manual_create": "✍️ Создать вручную",
    "task_ai.prompt_title": (
        "Какую задачу добавить? Опишите её одной фразой "
        "(например, 'Созвон с командой на 30 минут')."
    ),
    "task_ai.prompt_title_dated": (
        "Задача на {date}. Опишите её одной фразой "
        "(например, 'Созвон с командой на 30 минут')."
    ),
    "task_ai.title_empty": "Пожалуйста, опишите задачу (минимум 1 символ).",
    "task_ai.title_too_long": (
        "Слишком длинное описание. Пожалуйста, уложитесь в 200 символов."
    ),
    "task_ai.waiting": "⏳ Подбираю время для задачи… Это может занять до 30 секунд.",
    "task_ai.unavailable": (
        "🤖 ИИ временно недоступен. "
        "Попробуйте позже или создайте задачу вручную."
    ),
    "task_ai.preview": (
        "🤖 <b>Предложенная задача (черновик):</b>\n\n"
        "<b>Задача:</b> {title}\n"
        "<b>Дата:</b> {date}\n"
        "<b>Время:</b> {time}\n"
        "<b>Длительность:</b> {duration}\n"
        "<b>Комментарий:</b> {comment}\n\n"
        "Создать эту задачу?"
    ),
    "task_ai.time_corrected_warning": (
        "⚠️ <b>Время скорректировано под сетку 15 мин:</b> {details}"
    ),

    "task_ai.created": (
        "✅ Задача успешно создана!\n\n"
        "<b>{title}</b>\n"
        "Дата: {date}\n"
        "Время: {time}"
    ),
    "task_ai.declined": "Хорошо, может быть, в другой раз!",
    "task_ai.invalid_plan": (
        "Некорректный план: не удалось определить время задачи. "
        "Попробуйте ещё раз или создайте вручную."
    ),
    "task_ai.save_failed": (
        "Не удалось сохранить задачу. Попробуйте позже или создайте вручную."
    ),
    "task_ai.conflict": (
        "⚠️ Задача «{title}» ({date}, {time}) конфликтует с существующими задачами.\n\n"
        "Выберите действие:"
    ),
    "task_ai.clarify_fallback": "Уточните, пожалуйста.",
    "task_ai.clarify_text_hint": "(напишите ответ или нажмите Пропустить)",
    "task_ai.clarify_time_hint": "(выберите время с шагом 15 минут)",
    "task_ai.skip": "⏭ Пропустить",
    "task_ai.yes": "✅ Да",
    "task_ai.no": "❌ Нет",
}


