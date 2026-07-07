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
