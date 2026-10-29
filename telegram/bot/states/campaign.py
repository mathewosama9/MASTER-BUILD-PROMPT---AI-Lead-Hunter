from aiogram.fsm.state import State, StatesGroup


class NewCampaign(StatesGroup):
    country = State()
    custom_country = State()
    city = State()
    industry = State()
    custom_industry = State()
    sources = State()
    count = State()
    custom_count = State()
    ai = State()
    confirm = State()
