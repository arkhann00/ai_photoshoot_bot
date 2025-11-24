from aiogram.fsm.state import State, StatesGroup

class MainStates(StatesGroup):
    start = State()
    support = State()
    balance = State()
    making_photoshoot = State()
    making_photoshoot_process = State()
    making_photoshoot_failed = State()
    making_photoshoot_success = State()

class AdminStates(StatesGroup):
    admin_menu = State()
    search_user = State()