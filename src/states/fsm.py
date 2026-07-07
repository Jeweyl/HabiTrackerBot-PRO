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
