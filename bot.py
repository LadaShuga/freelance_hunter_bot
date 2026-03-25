"""
bot.py - основной файл работы бота
"""

import asyncio
import os
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command

# Берем токен из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("Ошибка: BOT_TOKEN не найден!")
    exit(1)

# ========== НАСТРОЙКА ПУТЕЙ ==========
os.makedirs("data", exist_ok=True)

# ========== ИМПОРТ КОНФИГУРАЦИИ ==========
import config

# ========== ИНИЦИАЛИЗАЦИЯ БОТА ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЕЙ (упрощенный FSM) ==========
# Хранит, в каком режиме находится пользователь
user_states: Dict[int, Dict[str, Optional[str]]] = {}

# ========== ИМПОРТ СЕРВИСОВ ==========
# Импортируем после инициализации бота, чтобы избежать циклических импортов
from database import init_db, add_subscription, get_user_subscriptions, remove_subscription
from hh_parser import parse_hh_vacancies
from scheduler import start_scheduler


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def create_unsubscribe_keyboard(subscriptions: list) -> types.ReplyKeyboardMarkup:
    """Создает клавиатуру для отписки от подписок"""
    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    
    builder = ReplyKeyboardBuilder()
    
    for keyword in subscriptions:
        builder.add(types.KeyboardButton(text=f"❌ {keyword}"))
    
    builder.add(types.KeyboardButton(text="⬅️ Назад"))
    builder.adjust(2)
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def create_main_keyboard() -> types.ReplyKeyboardMarkup:
    """Создает основную клавиатуру бота"""
    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    
    builder = ReplyKeyboardBuilder()
    
    buttons = [
        types.KeyboardButton(text="🔍 Найти вакансии"),
        types.KeyboardButton(text="📋 Мои подписки"),
        types.KeyboardButton(text="✅ Подписаться"),
        types.KeyboardButton(text="❌ Отписаться"),
        types.KeyboardButton(text="ℹ️ Помощь")
    ]
    
    for button in buttons:
        builder.add(button)
    
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def create_cancel_keyboard() -> types.ReplyKeyboardMarkup:
    """Создает клавиатуру с кнопкой отмены"""
    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="❌ Отмена"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def create_subscription_keyboard() -> types.ReplyKeyboardMarkup:
    """Создает клавиатуру для подписки"""
    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    
    builder = ReplyKeyboardBuilder()
    
    # Популярные ключевые слова
    popular_keywords = ["Python", "JavaScript", "Java", "C++", "PHP", "Go", "SQL", "DevOps"]
    
    for keyword in popular_keywords:
        builder.add(types.KeyboardButton(text=f"➕ {keyword}"))
    
    builder.add(types.KeyboardButton(text="✏️ Ввести свое"))
    builder.add(types.KeyboardButton(text="⬅️ Назад"))
    builder.adjust(2, 2, 2, 2, 1)
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def create_subscription_choice_keyboard() -> types.ReplyKeyboardMarkup:
    """Клавиатура для выбора способа подписки"""
    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    
    builder = ReplyKeyboardBuilder()
    
    builder.add(types.KeyboardButton(text="➕ Выбрать из списка"))
    builder.add(types.KeyboardButton(text="✏️ Ввести свое"))
    builder.add(types.KeyboardButton(text="❌ Отмена"))
    builder.adjust(1)
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def format_salary(salary_data: Optional[dict]) -> str:
    """Форматирует зарплату для отображения"""
    if not salary_data:
        return "не указана"
    
    salary_from = salary_data.get('from')
    salary_to = salary_data.get('to')
    currency = salary_data.get('currency', 'руб.')
    
    if salary_from and salary_to:
        return f"{salary_from:,} - {salary_to:,} {currency}".replace(',', ' ')
    elif salary_from:
        return f"от {salary_from:,} {currency}".replace(',', ' ')
    elif salary_to:
        return f"до {salary_to:,} {currency}".replace(',', ' ')
    
    return "не указана"


def format_vacancy_for_message(vacancy: dict, index: int) -> str:
    """Форматирует одну вакансию для сообщения"""
    salary_text = format_salary(vacancy.get('salary'))
    company = vacancy.get('company', 'не указана')
    publish_date = vacancy.get('published_at_formatted', 'неизвестно')
    
    return (
        f"*{index}. {vacancy['name']}*\n"
        f"🏢 *Компания:* {company}\n"
        f"💰 *Зарплата:* {salary_text}\n"
        f"📅 *Опубликовано:* {publish_date}\n"
        f"🔗 [Ссылка на вакансию]({vacancy['alternate_url']})\n\n"
    )


# ========== ОБРАБОТЧИКИ КОМАНД ==========

@dp.message(Command("start"))
async def handle_start(message: types.Message):
    """Обработчик команды /start"""
    welcome_text = (
        "👋 Привет! Я *Freelance Hunter Bot* — твой помощник в поиске фриланс-заказов!\n\n"
        "🔍 *Что я умею:*\n"
        "• Искать свежие вакансии на HH.ru\n"
        "• Подписывать на уведомления по ключевым словам\n"
        "• Присылать ежедневную рассылку новых заказов\n\n"
        "📱 *Используй кнопки ниже или команды:*\n"
        "/parse - Найти вакансии\n"
        "/subscribe - Подписаться на рассылку\n"
        "/unsubscribe - Отписаться\n"
        "/help - Список команд\n\n"
        "🚀 *Давай начнем!*"
    )
    
    await message.answer(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=create_main_keyboard()
    )
    print(f"👤 Новый пользователь: {message.from_user.id}")


@dp.message(Command("help"))
async def handle_help(message: types.Message):
    """Обработчик команды /help"""
    help_text = (
        "📋 *Доступные команды:*\n\n"
        "🔸 *Основные команды:*\n"
        "/start - Начать работу с ботом\n"
        "/parse [ключевое слово] - Найти вакансии\n"
        "/subscribe - Подписаться на рассылку\n"
        "/unsubscribe - Отписаться от рассылки\n"
        "/mysubs - Мои подписки\n\n"
        
        "🔸 *Управление рассылкой:*\n"
        "Бот отправляет уведомления каждый день в 10:00 по МСК\n"
        "Вы можете подписаться на несколько ключевых слов\n\n"
        
        "🔸 *Примеры использования:*\n"
        "• `/parse Python` - найдет вакансии Python\n"
        "• `/subscribe` - откроет меню подписки"
    )
    
    await message.answer(
        help_text,
        parse_mode="Markdown",
        reply_markup=create_main_keyboard()
    )


@dp.message(Command("parse"))
async def handle_parse(message: types.Message):
    """Обработчик команды /parse"""
    parts = message.text.split()
    
    if len(parts) > 1:
        # Если ключевое слово указано сразу
        keyword = " ".join(parts[1:])
        await search_vacancies(message, keyword)
    else:
        # Просим ввести ключевое слово
        user_states[message.from_user.id] = {"mode": "search"}
        await message.answer(
            "🔍 *Введите ключевое слово для поиска:*\n\n"
            "Например: Python, JavaScript, дизайнер",
            parse_mode="Markdown",
            reply_markup=create_cancel_keyboard()
        )


@dp.message(Command("subscribe"))
async def handle_subscribe(message: types.Message):
    """Обработчик команды /subscribe"""
    user_id = message.from_user.id
    user_states[user_id] = {"mode": "subscribe", "step": "choose_option"}
    
    await message.answer(
        "📝 *Выберите способ подписки:*\n\n"
        "• 'Выбрать из списка' - готовые популярные профессии\n"
        "• 'Ввести свое' - любое ключевое слово",
        parse_mode="Markdown",
        reply_markup=create_subscription_choice_keyboard()
    )


@dp.message(Command("unsubscribe"))
async def handle_unsubscribe(message: types.Message):
    """Обработчик команды /unsubscribe"""
    user_id = message.from_user.id
    subscriptions = get_user_subscriptions(user_id)
    
    if not subscriptions:
        await message.answer(
            "ℹ️ У вас нет активных подписок.",
            reply_markup=create_main_keyboard()
        )
        return
    
    user_states[user_id] = {"mode": "unsubscribe"}
    
    await message.answer(
        "🗑️ *Выберите подписку для отмены:*",
        parse_mode="Markdown",
        reply_markup=create_unsubscribe_keyboard(subscriptions)
    )


@dp.message(Command("mysubs"))
async def handle_mysubs(message: types.Message):
    """Обработчик команды /mysubs"""
    user_id = message.from_user.id
    subscriptions = get_user_subscriptions(user_id)
    
    if subscriptions:
        subs_list = "\n".join([f"• *{sub}*" for sub in subscriptions])
        text = f"📋 *Ваши подписки:*\n\n{subs_list}\n\nВсего: {len(subscriptions)} подписок"
    else:
        text = (
            "📭 У вас пока нет подписок.\n\n"
            "Используйте команду /subscribe чтобы подписаться на уведомления!"
        )
    
    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=create_main_keyboard()
    )


# ========== ОБРАБОТЧИКИ КНОПОК ==========

@dp.message(F.text == "🔍 Найти вакансии")
async def handle_search_button(message: types.Message):
    """Обработчик кнопки 'Найти вакансии'"""
    user_states[message.from_user.id] = {"mode": "search"}
    await message.answer(
        "🔍 *Введите ключевое слово для поиска:*\n\n"
        "Например: Python, JavaScript, дизайнер",
        parse_mode="Markdown",
        reply_markup=create_cancel_keyboard()
    )


@dp.message(F.text == "✅ Подписаться")
async def handle_subscribe_button(message: types.Message):
    """Обработчик кнопки 'Подписаться'"""
    user_id = message.from_user.id
    user_states[user_id] = {"mode": "subscribe", "step": "choose_option"}
    
    await message.answer(
        "📝 *Выберите способ подписки:*\n\n"
        "• 'Выбрать из списка' - готовые популярные профессии\n"
        "• 'Ввести свое' - любое ключевое слово",
        parse_mode="Markdown",
        reply_markup=create_subscription_choice_keyboard()
    )


@dp.message(F.text == "❌ Отписаться")
async def handle_unsubscribe_button(message: types.Message):
    """Обработчик кнопки 'Отписаться'"""
    await handle_unsubscribe(message)


@dp.message(F.text == "📋 Мои подписки")
async def handle_mysubs_button(message: types.Message):
    """Обработчик кнопки 'Мои подписки'"""
    await handle_mysubs(message)


@dp.message(F.text == "ℹ️ Помощь")
async def handle_help_button(message: types.Message):
    """Обработчик кнопки 'Помощь'"""
    await handle_help(message)


@dp.message(F.text == "⬅️ Назад")
async def handle_back_button(message: types.Message):
    """Обработчик кнопки 'Назад'"""
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]
    
    await message.answer(
        "⬅️ Возвращаемся в главное меню",
        reply_markup=create_main_keyboard()
    )


@dp.message(F.text == "❌ Отмена")
async def handle_cancel_button(message: types.Message):
    """Обработчик кнопки 'Отмена'"""
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]
    
    await message.answer(
        "❌ Действие отменено",
        reply_markup=create_main_keyboard()
    )


# ========== ОБРАБОТЧИКИ КНОПОК ПОДПИСКИ ==========

@dp.message(F.text == "➕ Выбрать из списка")
async def handle_choose_from_list(message: types.Message):
    """Обработчик кнопки 'Выбрать из списка'"""
    await message.answer(
        "📝 *Выберите ключевое слово для подписки:*\n\n"
        "Можно выбрать из популярных или ввести свое.",
        parse_mode="Markdown",
        reply_markup=create_subscription_keyboard()
    )


@dp.message(F.text == "✏️ Ввести свое")
async def handle_custom_subscription_input(message: types.Message):
    """Обработчик кнопки 'Ввести свое' для подписки"""
    user_id = message.from_user.id
    user_states[user_id] = {"mode": "subscribe", "step": "custom_input"}
    
    await message.answer(
        "✏️ *Введите ключевое слово для подписки:*\n\n"
        "Например: Data Science, Product Manager, Backend разработчик\n\n"
        "Или нажмите '❌ Отмена' для отмены",
        parse_mode="Markdown",
        reply_markup=create_cancel_keyboard()
    )


# ========== ОБРАБОТЧИКИ СПЕЦИАЛЬНЫХ КНОПОК ==========

@dp.message(F.text.startswith("➕ "))
async def handle_add_subscription(message: types.Message):
    """Обработчик кнопок вида '+ Python'"""
    user_id = message.from_user.id
    
    # Проверяем, что пользователь в режиме подписки
    if user_id in user_states and user_states[user_id].get("mode") == "subscribe":
        keyword = message.text[2:].strip()
        
        if not keyword:
            await message.answer("Выберите ключевое слово из списка.")
            return
        
        if add_subscription(user_id, keyword):
            await message.answer(
                f"✅ Вы подписались на уведомления по запросу: *{keyword}*\n\n",
                parse_mode="Markdown",
                reply_markup=create_main_keyboard()
            )
            # Очищаем состояние
            if user_id in user_states:
                del user_states[user_id]
        else:
            await message.answer(
                f"ℹ️ Вы уже подписаны на *{keyword}*",
                parse_mode="Markdown",
                reply_markup=create_main_keyboard()
            )
            # Очищаем состояние
            if user_id in user_states:
                del user_states[user_id]
    else:
        # Если пользователь не в режиме подписки, просто ищем вакансии
        keyword = message.text[2:].strip()
        await search_vacancies(message, keyword)


@dp.message(F.text.startswith("❌ "))
async def handle_remove_subscription(message: types.Message):
    """Обработчик кнопок вида '❌ Python'"""
    user_id = message.from_user.id
    
    # Проверяем, что пользователь в режиме отписки
    if user_id in user_states and user_states[user_id].get("mode") == "unsubscribe":
        keyword = message.text[2:].strip()
        
        if not keyword:
            await message.answer("Выберите подписку для отмены.")
            return
        
        if remove_subscription(user_id, keyword):
            await message.answer(
                f"✅ Вы отписались от уведомлений по запросу: *{keyword}*",
                parse_mode="Markdown",
                reply_markup=create_main_keyboard()
            )
        else:
            await message.answer(
                f"ℹ️ У вас нет подписки на *{keyword}*",
                parse_mode="Markdown",
                reply_markup=create_main_keyboard()
            )
        
        # Очищаем состояние
        if user_id in user_states:
            del user_states[user_id]
    else:
        # Если не в режиме отписки, возможно это обычный текст
        await message.answer(
            "Используйте '❌ Отписаться' для управления подписками",
            reply_markup=create_main_keyboard()
        )


# ========== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ==========

@dp.message(F.text)
async def handle_text(message: types.Message):
    """Обработчик текстовых сообщений (поиск и другие команды)"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # 1. Сначала проверяем специальные кнопки (игнорируем их здесь)
    if text.startswith('/') or text in [
        "🔍 Найти вакансии", "📋 Мои подписки", "✅ Подписаться",
        "❌ Отписаться", "ℹ️ Помощь", "⬅️ Назад", "❌ Отмена",
        "✏️ Ввести свое", "➕ Выбрать из списка"
    ] or text.startswith("➕ ") or text.startswith("❌ "):
        return
    
    # 2. Проверяем состояние пользователя
    user_state = user_states.get(user_id, {})
    
    # 3. РЕЖИМ ПОИСКА
    if user_state.get("mode") == "search":
        # Режим поиска вакансий
        if user_id in user_states:
            del user_states[user_id]  # Сбрасываем состояние
        
        await search_vacancies(message, text)
    
    # 4. РЕЖИМ ПОДПИСКИ (ввод своего слова)
    elif user_state.get("mode") == "subscribe":
        # Пользователь ввел слово для подписки
        keyword = text.strip()
        
        # Проверяем длину
        if len(keyword) < 2:
            await message.answer("⚠️ Ключевое слово слишком короткое. Введите еще раз:")
            return
        
        # Проверяем, не число ли это
        if keyword.isdigit():
            await message.answer("⚠️ Ключевое слово не может состоять только из цифр. Введите текст:")
            return
        
        # Добавляем подписку
        if add_subscription(user_id, keyword):
            await message.answer(
                f"✅ Вы подписались на уведомления по запросу: *{keyword}*\n\n"
                f"Теперь вы будете получать свежие вакансии каждый день в 10:00 по МСК.",
                parse_mode="Markdown",
                reply_markup=create_main_keyboard()
            )
        else:
            await message.answer(
                f"ℹ️ Вы уже подписаны на *{keyword}*",
                parse_mode="Markdown",
                reply_markup=create_main_keyboard()
            )
        
        # Очищаем состояние
        if user_id in user_states:
            del user_states[user_id]
    
    # 5. РЕЖИМ ОТПИСКИ
    elif user_state.get("mode") == "unsubscribe":
        # Неожиданный текст в режиме отписки
        await message.answer(
            "Выберите подписку для отмены из списка выше или нажмите '⬅️ Назад'",
            reply_markup=create_main_keyboard()
        )
    
    # 6. ЕСЛИ СОСТОЯНИЯ НЕТ - это поиск по умолчанию
    else:
        # Проверяем, похоже ли на поисковый запрос
        if 2 <= len(text) <= 100:
            await search_vacancies(message, text)
        else:
            await message.answer(
                "🤔 Не понимаю ваш запрос. Используйте кнопки или команды:\n\n"
                "• Введите слово для поиска вакансий\n"
                "• Или нажмите '✅ Подписаться' для подписки на рассылку",
                reply_markup=create_main_keyboard()
            )


# ========== ОСНОВНАЯ ЛОГИКА ==========

async def search_vacancies(message: types.Message, keyword: str):
    """Основная функция поиска вакансий"""
    await message.answer(
        f"🔍 Ищу вакансии по запросу: *{keyword}*...", 
        parse_mode="Markdown"
    )
    
    try:
        vacancies = parse_hh_vacancies(keyword, per_page=5)
        
        if not vacancies:
            await no_vacancies_found(message, keyword)
            return
        
        response = create_vacancies_response(vacancies, keyword)
        
        await message.answer(
            response,
            parse_mode="Markdown",
            disable_web_page_preview=True,
            reply_markup=create_main_keyboard()
        )
        
    except Exception as e:
        await handle_search_error(message, e, keyword)


def create_vacancies_response(vacancies: list, keyword: str) -> str:
    """Создает ответ с найденными вакансиями"""
    response = f"📋 *Найдено {len(vacancies)} вакансий по запросу '{keyword}':*\n\n"
    
    for i, vacancy in enumerate(vacancies, 1):
        response += format_vacancy_for_message(vacancy, i)
    
    response += (
        f"💡 *Совет:* Подпишитесь на рассылку по запросу *{keyword}*, "
        f"чтобы получать новые вакансии автоматически!\n\n"
        f"Используйте команду /subscribe"
    )
    
    return response


async def no_vacancies_found(message: types.Message, keyword: str):
    """Обработка случая, когда вакансий не найдено"""
    await message.answer(
        f"😔 По запросу *{keyword}* не найдено вакансий.\n"
        f"Попробуйте другой запрос или проверьте соединение с интернетом.",
        parse_mode="Markdown",
        reply_markup=create_main_keyboard()
    )


async def handle_search_error(message: types.Message, error: Exception, keyword: str):
    """Обработка ошибок при поиске"""
    error_msg = str(error)
    
    if "per_page" in error_msg:
        await message.answer(
            f"⚠️ Техническая ошибка в парсере. Проверьте файл parser.py\n"
            f"Ошибка: {error_msg}",
            reply_markup=create_main_keyboard()
        )
    else:
        await message.answer(
            f"❌ Ошибка при поиске вакансий: {error_msg}\n"
            f"Попробуйте позже.",
            reply_markup=create_main_keyboard()
        )
    
    print(f"Ошибка парсинга: {error_msg}")


# ========== ЗАПУСК БОТА ==========

async def main():
    """Основная функция запуска бота"""
    # Инициализация БД
    init_db()
    print("✅ База данных инициализирована")
    
    # Запуск планировщика
    asyncio.create_task(start_scheduler())
    print("✅ Планировщик рассылки запущен")
    
    # Запуск бота
    await bot.delete_webhook(drop_pending_updates=True)
    
    print("🤖 Бот запущен и готов к работе!")
    print("Нажмите Ctrl+C для остановки")
    
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
