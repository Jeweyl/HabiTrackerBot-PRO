"""FSM state groups for the Telegram bot navigation."""

from aiogram.fsm.state import State, StatesGroup


class MainFSM(StatesGroup):
    """Main FSM group for top-level bot navigation.

    Attributes:
        main_menu: State representing the main menu screen.
    """

    main_menu = State()


class NewHabitFSM(StatesGroup):
    """FSM group for the "New Habit" creation wizard.

    Attributes:
        title: User enters the habit name/title.
        start_time: User selects the daily start time.
        end_time: User selects the daily end time.
        frequency: User selects the repeat frequency.
    """

    title = State()
    start_time = State()
    end_time = State()
    frequency = State()


class EditHabitFSM(StatesGroup):
    """FSM group for editing an existing habit.

    Attributes:
        choose_field: User selects which field to edit.
        title: User enters a new title.
        start_time: User selects a new start time.
        end_time: User selects a new end time.
        frequency: User selects a new frequency.
        confirm_delete: User confirms habit deletion.
    """

    choose_field = State()
    title = State()
    start_time = State()
    end_time = State()
    frequency = State()
    confirm_delete = State()


class NewTaskFSM(StatesGroup):
    """FSM group for the "New Task" creation wizard.

    Attributes:
        select_date: User selects a date via the calendar (entry point).
        title: User enters the task title.
        start_time: User selects the task start time.
        end_time: User selects the task end time (may be ``None``).
        confirm: User reviews and confirms the task before saving.
    """

    select_date = State()
    title = State()
    start_time = State()
    end_time = State()
    confirm = State()


class ConflictFSM(StatesGroup):
    """FSM group for resolving time conflicts when saving a task.

    Attributes:
        choose_action: User chooses how to handle the conflict
            (force add / edit schedule / edit task / cancel).
    """

    choose_action = State()


class EditTaskFSM(StatesGroup):
    """FSM group for the task management and editing flow.

    Attributes:
        choose_action: User chooses delete / edit / reset / back / main menu.
        edit_field: User selects which field to edit.
        edit_title: User enters a new title.
        edit_date: User selects a new date via the calendar.
        edit_start_time: User selects a new start time.
        edit_end_time: User selects a new end time.
        confirm_changes: User reviews and confirms the changes.
    """

    choose_action = State()
    edit_field = State()
    edit_title = State()
    edit_date = State()
    edit_start_time = State()
    edit_end_time = State()
    confirm_changes = State()


class AIAssistantFSM(StatesGroup):
    """FSM group for the AI-assisted SMART goal wizard.

    Guides the user through a conversational flow where the AI
    collects information, generates recommendations, and creates
    habits and tasks automatically.

    Attributes:
        start: Initial greeting and title input.
        ask_adaptive_q1: First adaptive question based on habit title keywords.
        ask_adaptive_q2: Second adaptive question based on habit title keywords.
        confirm_recommendations: Show AI recommendations and ask for confirmation.
    """

    start = State()
    ask_adaptive_q1 = State()
    ask_adaptive_q2 = State()
    confirm_recommendations = State()


class ConflictHabitFSM(StatesGroup):
    """FSM group for resolving habit time conflicts.

    Attributes:
        choose_action: User chooses how to handle the conflict
            (change time / frequency / force add / edit schedule / edit tasks / cancel).
    """

    choose_action = State()


class SettingsFSM(StatesGroup):
    """FSM for settings menu and configuration flows.

    States:
        menu: Main settings menu.
        language: Language selection.
        timezone: Timezone selection.
        reminder_time: Reminder time selection.
        check_interval: Check interval selection.
    """

    menu = State()
    language = State()
    timezone = State()
    reminder_time = State()
    check_interval = State()


class HabitFSM(StatesGroup):
    """FSM group for the two-level habit navigation menu.

    Attributes:
        view_list: View the habit text list with an «Интерактировать» button.
        interact_list: Sub-menu with each habit as an inline button.
        manage_single: Manage a single habit (edit / delete).
    """

    view_list = State()
    interact_list = State()
    manage_single = State()
