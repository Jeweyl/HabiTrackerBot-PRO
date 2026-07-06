"""FSM state groups for the Telegram bot navigation."""

from aiogram.fsm.state import State, StatesGroup


class MainFSM(StatesGroup):
    """Main FSM group for top-level bot navigation.

    Attributes:
        main_menu: State representing the main menu screen.
    """

    main_menu = State()
