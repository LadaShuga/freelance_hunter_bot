"""
scheduler.py - Планировщик ежедневной рассылки вакансий
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional 

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from shared import bot_instance
from hh_parser import parse_hh_vacancies
from database import (
    get_all_subscriptions,
    add_vacancy_for_cache,
    get_last_sent_time,
    update_last_sent_time,
    cleanup_old_vacancies
)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# КОНФИГУРАЦИЯ РАССЫЛКИ -
SEND_HOUR = 13    
SEND_MINUTE = 0
TIMEZONE = "Europe/Moscow"
VACANCIES_PER_USER = 3  
DELAY_BETWEEN_USERS = 0.5  


async def send_daily_notifications():
    """Основная функция ежедневной рассылки"""
    if bot_instance is None:
        logger.error("❌ Бот не инициализирован, пропускаем рассылку")
        return
    
    logger.info("📧 Запуск ежедневной рассылки...")
    
    # Получаем все подписки
    subscriptions = get_all_subscriptions()
    
    if not subscriptions:
        logger.info("📭 Нет активных подписок, пропускаем рассылку")
        return
    
    logger.info(f"👥 Найдено {len(subscriptions)} подписок")
    
    # Очищаем старые вакансии из кэша 
    cleanup_old_vacancies(30)
    
    # Отправляем уведомления каждому пользователю
    successful_sends = 0
    failed_sends = 0
    
    for user_id, keyword in subscriptions:
        try:
            success = await send_to_user(user_id, keyword)
            if success:
                successful_sends += 1
            else:
                failed_sends += 1
            
            # Пауза чтобы не спамить и не превысить лимиты Telegram
            await asyncio.sleep(DELAY_BETWEEN_USERS)
            
        except Exception as e:
            logger.error(f"❌ Критическая ошибка для пользователя {user_id}: {e}")
            failed_sends += 1
    
    logger.info(f"✅ Рассылка завершена. Успешно: {successful_sends}, Ошибок: {failed_sends}")


async def send_to_user(user_id: int, keyword: str) -> bool:
    """
    Отправляет уведомление конкретному пользователю
    
    Returns:
        True если отправка успешна, False если ошибка
    """
    try:
        # Получаем время последней рассылки
        last_sent = get_last_sent_time(user_id, keyword)
        
        # Ищем новые вакансии
        vacancies = await get_new_vacancies_for_user(keyword, last_sent)
        
        if not vacancies:
            await send_no_vacancies_message(user_id, keyword)
            update_last_sent_time(user_id, keyword)  # Обновляем время даже если вакансий нет
            return True
        
        # Отправляем вакансии
        await send_vacancies_message(user_id, keyword, vacancies)
        
        # Кэшируем вакансии для будущих рассылок
        cache_vacancies(vacancies)
        
        # Обновляем время последней рассылки
        update_last_sent_time(user_id, keyword)
        
        logger.info(f"📨 Отправлено {len(vacancies)} вакансий пользователю {user_id} по '{keyword}'")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки пользователю {user_id}: {e}")
        return False


async def get_new_vacancies_for_user(keyword: str, last_sent: datetime) -> list:
    """
    Получает новые вакансии для пользователя
    
    Если last_sent None (первая рассылка), берем вакансии за последние 2 дня
    """
    try:
        # Если это первая рассылка, берем вакансии за последние 2 дня
        if last_sent is None:
            cutoff_date = datetime.now() - timedelta(days=2)
        else:
            cutoff_date = last_sent
        
        # Ищем вакансии
        vacancies = parse_hh_vacancies(keyword, per_page=VACANCIES_PER_USER)
        
        # Фильтруем по дате (если API не поддерживает фильтрацию по дате)
        filtered_vacancies = []
        for vacancy in vacancies:
            pub_date = parse_vacancy_date(vacancy)
            if pub_date and pub_date > cutoff_date:
                filtered_vacancies.append(vacancy)
        
        return filtered_vacancies[:VACANCIES_PER_USER]  # Ограничиваем количество
        
    except Exception as e:
        logger.error(f"Ошибка получения вакансий по '{keyword}': {e}")
        return []


def parse_vacancy_date(vacancy: dict) -> Optional[datetime]:
    """Парсит дату публикации вакансии"""
    try:
        date_str = vacancy.get('published_at')
        if not date_str:
            return None
        
        if date_str.endswith('Z'):
            date_str = date_str[:-1] + '+00:00'
        
        return datetime.fromisoformat(date_str)
    except (ValueError, AttributeError):
        return None


def cache_vacancies(vacancies: list):
    """Сохраняет вакансии в кэш для будущих рассылок"""
    for vacancy in vacancies:
        try:
            add_vacancy_for_cache(vacancy)
        except Exception as e:
            logger.warning(f"Не удалось кэшировать вакансию: {e}")


async def send_no_vacancies_message(user_id: int, keyword: str):
    """Отправляет сообщение если вакансий не найдено"""
    try:
        message = (
            f"🔔 *Ежедневная рассылка по запросу '{keyword}'*\n\n"
            f"К сожалению, сегодня не найдено новых вакансий 😔\n\n"
            f"_Вы можете изменить ключевое слово командой /subscribe_"
        )
        
        await bot_instance.send_message(
            user_id,
            message,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки 'нет вакансий' пользователю {user_id}: {e}")


async def send_vacancies_message(user_id: int, keyword: str, vacancies: list):
    """Отправляет сообщение со списком вакансий"""
    try:
        # Формируем заголовок
        message = f"🔔 *Ежедневная рассылка по запросу '{keyword}'*\n\n"
        message += f"Найдено *{len(vacancies)}* новых вакансий:\n\n"
        
        # Добавляем каждую вакансию
        for i, vacancy in enumerate(vacancies, 1):
            message += format_vacancy_for_notification(vacancy, i)
        
        # Добавляем подпись
        message += "\n_Чтобы отписаться, используйте команду /unsubscribe_"
        
        # Отправляем сообщение
        await bot_instance.send_message(
            user_id,
            message,
            parse_mode="Markdown",
            disable_web_page_preview=True  # Чтобы ссылки не разворачивались
        )
        
    except Exception as e:
        logger.error(f"Ошибка отправки вакансий пользователю {user_id}: {e}")
        raise


def format_vacancy_for_notification(vacancy: dict, index: int) -> str:
    """Форматирует вакансию для уведомления"""
    # Название
    title = vacancy.get('name', 'Без названия')
    
    # Компания
    company = vacancy.get('company', 'Не указана')
    
    # Зарплата
    salary = vacancy.get('salary', {})
    salary_text = format_salary_for_notification(salary)
    
    # Дата
    date_str = vacancy.get('published_at_formatted', 'неизвестно')
    
    # Ссылка
    url = vacancy.get('alternate_url', '#')
    
    return (
        f"*{index}. {title}*\n"
        f"🏢 *Компания:* {company}\n"
        f"💰 *Зарплата:* {salary_text}\n"
        f"📅 *Опубликовано:* {date_str}\n"
        f"🔗 [Ссылка на вакансию]({url})\n\n"
    )


def format_salary_for_notification(salary_data: dict) -> str:
    """Форматирует зарплату для уведомления"""
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


# ========== УПРАВЛЕНИЕ ПЛАНИРОВЩИКОМ ==========

async def start_scheduler():
    """
    Запускает планировщик рассылки
    """
    scheduler = AsyncIOScheduler()
    
    # Основная ежедневная рассылка
    scheduler.add_job(
        send_daily_notifications,
        CronTrigger(
            hour=SEND_HOUR,
            minute=SEND_MINUTE,
            timezone=TIMEZONE
        ),
        id="daily_notifications",
        name="Ежедневная рассылка вакансий",
        replace_existing=True
    )
    
    
    
    scheduler.start()
    logger.info(f"✅ Планировщик запущен. Рассылка в {SEND_HOUR:02d}:{SEND_MINUTE:02d} по {TIMEZONE}")
    
    # Бесконечный цикл чтобы планировщик работал
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("🛑 Планировщик остановлен")


def run_scheduler():
    """
    Запускает планировщик в фоне
    Используется в bot.py
    """
    asyncio.create_task(start_scheduler())