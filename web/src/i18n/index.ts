/** Lightweight EN/RU i18n for the Vue dashboard. */

export type Lang = "en" | "ru"

type Dict = Record<string, string>

const en: Dict = {
  "login.title": "Signing in…",
  "login.body": "Exchanging your one-time link for a secure session.",
  "error.hint": "Open the bot → Statistics → «Open dashboard» for a new link.",
  "error.missing_token.title": "Link incomplete",
  "error.missing_token.body":
    "This page needs a one-time token from the Telegram bot.",
  "error.invalid_token.title": "Link invalid or expired",
  "error.invalid_token.body":
    "The one-time link was already used, expired, or is invalid.",
  "error.not_authenticated.title": "Session required",
  "error.not_authenticated.body":
    "Open a fresh dashboard link from the bot to continue.",
  "error.exchange_failed.title": "Could not sign in",
  "error.exchange_failed.body":
    "The server could not exchange your token. Try again later.",
  "error.unknown.title": "Something went wrong",
  "error.unknown.body": "Please request a new dashboard link from the bot.",
  "dash.title": "HabiTracker Dashboard",
  "dash.subtitle": "Read-only stats · last {days} days",
  "dash.logout": "Log out",
  "dash.loading": "Loading stats…",
  "dash.load_error": "Failed to load dashboard data",
  "dash.partial": "Partial data may still be shown below.",
  "dash.refresh": "Refresh",
  "dash.completion": "Completion",
  "dash.streak": "Streak",
  "dash.habits": "Habits",
  "dash.missed": "Missed",
  "dash.tasks_ratio": "{completed}/{total} tasks",
  "dash.no_data": "No data",
  "dash.days_in_row": "days in a row",
  "dash.templates": "templates",
  "dash.incomplete": "incomplete",
  "dash.chart_title": "Completion chart",
  "dash.habits_title": "Habit breakdown",
  "dash.schedule_title": "Schedule",
  "chart.empty": "No completion data for this period yet.",
  "chart.completed": "Completed",
  "chart.missed": "Missed",
  "habits.empty": "No habits yet. Create one in the bot.",
  "schedule.empty": "No tasks in this range. Your schedule will show up here.",
  "schedule.done": "done",
  "schedule.open": "open",
  "schedule.untitled": "Untitled",
}

const ru: Dict = {
  "login.title": "Вход…",
  "login.body": "Обмениваем одноразовую ссылку на безопасную сессию.",
  "error.hint":
    "Откройте бота → Статистика → «Открыть дашборд» для новой ссылки.",
  "error.missing_token.title": "Ссылка неполная",
  "error.missing_token.body":
    "Этой странице нужен одноразовый токен из Telegram-бота.",
  "error.invalid_token.title": "Ссылка недействительна или устарела",
  "error.invalid_token.body":
    "Одноразовая ссылка уже использована, истекла или неверна.",
  "error.not_authenticated.title": "Нужна сессия",
  "error.not_authenticated.body":
    "Откройте свежую ссылку на дашборд из бота, чтобы продолжить.",
  "error.exchange_failed.title": "Не удалось войти",
  "error.exchange_failed.body":
    "Сервер не смог обменять токен. Попробуйте позже.",
  "error.unknown.title": "Что-то пошло не так",
  "error.unknown.body": "Запросите новую ссылку на дашборд в боте.",
  "dash.title": "HabiTracker — дашборд",
  "dash.subtitle": "Статистика только для чтения · последние {days} дн.",
  "dash.logout": "Выйти",
  "dash.loading": "Загрузка статистики…",
  "dash.load_error": "Не удалось загрузить данные дашборда",
  "dash.partial": "Ниже могут отображаться частичные данные.",
  "dash.refresh": "Обновить",
  "dash.completion": "Выполнение",
  "dash.streak": "Серия",
  "dash.habits": "Привычки",
  "dash.missed": "Пропущено",
  "dash.tasks_ratio": "{completed}/{total} задач",
  "dash.no_data": "Нет данных",
  "dash.days_in_row": "дней подряд",
  "dash.templates": "шаблонов",
  "dash.incomplete": "не выполнено",
  "dash.chart_title": "График выполнения",
  "dash.habits_title": "По привычкам",
  "dash.schedule_title": "Расписание",
  "chart.empty": "Пока нет данных о выполнении за этот период.",
  "chart.completed": "Выполнено",
  "chart.missed": "Пропущено",
  "habits.empty": "Привычек пока нет. Создайте первую в боте.",
  "schedule.empty":
    "В этом диапазоне нет задач. Расписание появится здесь.",
  "schedule.done": "готово",
  "schedule.open": "открыто",
  "schedule.untitled": "Без названия",
}

const catalogs: Record<Lang, Dict> = { en, ru }

const LANG_KEY = "habitracker_lang"

export function normalizeLang(raw: string | null | undefined): Lang {
  if (!raw) {
    return detectBrowserLang()
  }
  const code = String(raw).trim().toLowerCase()
  if (code.startsWith("en")) {
    return "en"
  }
  if (code.startsWith("ru")) {
    return "ru"
  }
  return detectBrowserLang()
}

export function detectBrowserLang(): Lang {
  try {
    const nav = typeof navigator !== "undefined" ? navigator.language : ""
    if (nav && nav.toLowerCase().startsWith("en")) {
      return "en"
    }
  } catch {
    // ignore
  }
  return "ru"
}

export function getStoredLang(): Lang | null {
  try {
    const raw = sessionStorage.getItem(LANG_KEY)
    if (raw === "en" || raw === "ru") {
      return raw
    }
  } catch {
    // ignore
  }
  return null
}

export function setStoredLang(lang: Lang): void {
  try {
    sessionStorage.setItem(LANG_KEY, lang)
  } catch {
    // ignore
  }
}

export function resolveLang(preferred?: string | null): Lang {
  if (preferred) {
    return normalizeLang(preferred)
  }
  return getStoredLang() ?? detectBrowserLang()
}

export function t(
  key: string,
  lang: Lang,
  params?: Record<string, string | number>,
): string {
  const catalog = catalogs[lang] ?? catalogs.ru
  let text = catalog[key] ?? catalogs.en[key] ?? key
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      text = text.replaceAll(`{${k}}`, String(v))
    }
  }
  return text
}
