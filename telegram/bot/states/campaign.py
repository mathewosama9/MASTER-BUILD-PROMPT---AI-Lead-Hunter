from aiogram.fsm.state import State, StatesGroup


class NewCampaign(StatesGroup):
    mode = State()
    free_text = State()
    country = State()
    custom_country = State()
    city = State()
    custom_city = State()
    industry = State()
    custom_industry = State()
    count = State()
    custom_count = State()
    summary = State()


class NoteInput(StatesGroup):
    body = State()


class TopUp(StatesGroup):
    method = State()
    reference = State()
    receipt = State()
