"""
database.py - Простая и надежная работа с SQLite базой данных
Управление подписками и кэшированием вакансий
"""

import sqlite3
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Путь к базе данных
DB_PATH = "data/bot_database.db"


# ========== УТИЛИТЫ ДЛЯ РАБОТЫ С БД ==========

@contextmanager
def get_connection():
    """Контекстный менеджер для работы с БД (автоматическое закрытие)"""
    # Создаем папку если ее нет
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Для доступа к полям по имени
    try:
        yield conn
    finally:
        conn.close()


def execute_query(query: str, params: tuple = (), fetch_one: bool = False):
    """
    Универсальная функция для выполнения запросов
    
    Args:
        query: SQL запрос
        params: Параметры для запроса
        fetch_one: Вернуть одну строку или все
        
    Returns:
        Результат запроса
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        
        if query.strip().upper().startswith("SELECT"):
            if fetch_one:
                result = cur.fetchone()
                return dict(result) if result else None
            else:
                return [dict(row) for row in cur.fetchall()]
        else:
            conn.commit()
            return cur.rowcount


# ========== ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ==========

def init_db():
    """Создает таблицы если их нет"""
    create_tables = """
    -- Таблица подписок
    CREATE TABLE IF NOT EXISTS subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        keyword TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, keyword)
    );
    
    -- Таблица вакансий (кеш)
    CREATE TABLE IF NOT EXISTS vacancies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        link TEXT UNIQUE NOT NULL,
        company TEXT,
        salary TEXT,
        published_at TIMESTAMP,
        source TEXT DEFAULT 'hh.ru',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- Время последней рассылки для пользователя и ключевого слова
    CREATE TABLE IF NOT EXISTS last_sent (
        user_id INTEGER,
        keyword TEXT,
        last_sent TIMESTAMP,
        PRIMARY KEY (user_id, keyword)
    );
    """
    
    try:
        # Выполняем все CREATE TABLE запросы
        for statement in create_tables.split(';'):
            if statement.strip():
                execute_query(statement.strip())
        
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")


# ========== РАБОТА С ПОДПИСКАМИ ==========

def add_subscription(user_id: int, keyword: str) -> bool:
    """
    Добавляет подписку пользователя
    
    Returns:
        True - если подписка добавлена
        False - если подписка уже существует или ошибка
    """
    try:
        query = "INSERT OR IGNORE INTO subscriptions (user_id, keyword) VALUES (?, ?)"
        affected = execute_query(query, (user_id, keyword))
        return affected > 0
    except Exception as e:
        logger.error(f"Ошибка добавления подписки: {e}")
        return False


def remove_subscription(user_id: int, keyword: str) -> bool:
    """
    Удаляет подписку пользователя
    
    Returns:
        True - если подписка удалена
        False - если подписки не было или ошибка
    """
    try:
        query = "DELETE FROM subscriptions WHERE user_id = ? AND keyword = ?"
        affected = execute_query(query, (user_id, keyword))
        return affected > 0
    except Exception as e:
        logger.error(f"Ошибка удаления подписки: {e}")
        return False


def get_user_subscriptions(user_id: int) -> List[str]:
    """Возвращает список подписок пользователя"""
    try:
        query = "SELECT keyword FROM subscriptions WHERE user_id = ? ORDER BY created_at"
        results = execute_query(query, (user_id,))
        return [row['keyword'] for row in results]
    except Exception as e:
        logger.error(f"Ошибка получения подписок: {e}")
        return []


def get_all_subscriptions() -> List[Tuple[int, str]]:
    """Возвращает все подписки для рассылки"""
    try:
        query = "SELECT user_id, keyword FROM subscriptions"
        results = execute_query(query)
        return [(row['user_id'], row['keyword']) for row in results]
    except Exception as e:
        logger.error(f"Ошибка получения всех подписок: {e}")
        return []


# ========== РАБОТА С ВАКАНСИЯМИ (для рассылки) ==========

def add_vacancy_for_cache(vacancy_data: Dict[str, Any]) -> bool:
    """
    Добавляет вакансию в кэш для рассылки
    
    Args:
        vacancy_data: Данные вакансии из парсера
    """
    try:
        # Подготовка данных
        title = vacancy_data.get('name', '')[:200]  # Ограничиваем длину
        link = vacancy_data.get('alternate_url', '')
        company = vacancy_data.get('company', '')[:100]
        
        # Форматируем зарплату
        salary_info = vacancy_data.get('salary', {})
        salary_text = _format_salary_for_db(salary_info)
        
        # Парсим дату
        published_at = _parse_date(vacancy_data.get('published_at'))
        
        # Вставляем в БД (игнорируем если уже есть по уникальной ссылке)
        query = """
        INSERT OR IGNORE INTO vacancies 
        (title, link, company, salary, published_at, source) 
        VALUES (?, ?, ?, ?, ?, 'hh.ru')
        """
        
        affected = execute_query(query, (
            title, link, company, salary_text, 
            published_at.isoformat() if published_at else None
        ))
        
        return affected > 0
        
    except Exception as e:
        logger.error(f"Ошибка добавления вакансии в кэш: {e}")
        return False


def get_new_vacancies_for_keyword(keyword: str, last_sent: Optional[datetime]) -> List[Dict[str, Any]]:
    """
    Возвращает новые вакансии для ключевого слова после указанной даты
    
    Args:
        keyword: Ключевое слово для поиска
        last_sent: Дата последней рассылки (или None если никогда не было)
    
    Returns:
        Список вакансий
    """
    try:
        # Если never sent, берем вакансии за последние 7 дней
        if last_sent is None:
            last_sent = datetime.now() - timedelta(days=7)
        
        query = """
        SELECT * FROM vacancies 
        WHERE (title LIKE ? OR company LIKE ?) 
        AND published_at > ?
        ORDER BY published_at DESC
        LIMIT 10
        """
        
        search_pattern = f"%{keyword}%"
        params = (search_pattern, search_pattern, last_sent.isoformat())
        
        vacancies = execute_query(query, params)
        
        # Конвертируем даты обратно в datetime
        for vac in vacancies:
            if vac.get('published_at'):
                try:
                    vac['published_at'] = datetime.fromisoformat(vac['published_at'])
                except:
                    vac['published_at'] = None
        
        return vacancies
        
    except Exception as e:
        logger.error(f"Ошибка получения новых вакансий: {e}")
        return []


def update_last_sent_time(user_id: int, keyword: str) -> bool:
    """Обновляет время последней рассылки"""
    try:
        query = """
        INSERT OR REPLACE INTO last_sent (user_id, keyword, last_sent) 
        VALUES (?, ?, ?)
        """
        execute_query(query, (user_id, keyword, datetime.now().isoformat()))
        return True
    except Exception as e:
        logger.error(f"Ошибка обновления времени рассылки: {e}")
        return False


def get_last_sent_time(user_id: int, keyword: str) -> Optional[datetime]:
    """Возвращает время последней рассылки"""
    try:
        query = "SELECT last_sent FROM last_sent WHERE user_id = ? AND keyword = ?"
        result = execute_query(query, (user_id, keyword), fetch_one=True)
        
        if result and result.get('last_sent'):
            return datetime.fromisoformat(result['last_sent'])
        return None
        
    except Exception as e:
        logger.error(f"Ошибка получения времени рассылки: {e}")
        return None


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def _format_salary_for_db(salary_data: Dict) -> Optional[str]:
    """Форматирует зарплату для сохранения в БД"""
    if not salary_data:
        return None
    
    salary_from = salary_data.get('from')
    salary_to = salary_data.get('to')
    currency = salary_data.get('currency', 'руб.')
    
    if salary_from and salary_to:
        return f"{salary_from} - {salary_to} {currency}"
    elif salary_from:
        return f"от {salary_from} {currency}"
    elif salary_to:
        return f"до {salary_to} {currency}"
    
    return None


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Парсит дату из строки"""
    if not date_str:
        return datetime.now()
    
    try:
        # Убираем Z в конце если есть
        if date_str.endswith('Z'):
            date_str = date_str[:-1] + '+00:00'
        
        return datetime.fromisoformat(date_str)
    except (ValueError, AttributeError):
        return datetime.now()


def cleanup_old_vacancies(days_to_keep: int = 30) -> int:
    """Удаляет старые вакансии из кэша"""
    try:
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        query = "DELETE FROM vacancies WHERE published_at < ?"
        affected = execute_query(query, (cutoff_date.isoformat(),))
        
        logger.info(f"🗑️ Удалено {affected} старых вакансий (старше {days_to_keep} дней)")
        return affected
        
    except Exception as e:
        logger.error(f"Ошибка очистки старых вакансий: {e}")
        return 0


def get_stats() -> Dict[str, Any]:
    """Возвращает статистику базы данных"""
    try:
        stats = {}
        
        # Количество подписок
        result = execute_query("SELECT COUNT(*) as count FROM subscriptions", fetch_one=True)
        stats['subscriptions'] = result['count'] if result else 0
        
        # Количество вакансий в кэше
        result = execute_query("SELECT COUNT(*) as count FROM vacancies", fetch_one=True)
        stats['vacancies'] = result['count'] if result else 0
        
        # Количество уникальных пользователей
        result = execute_query("SELECT COUNT(DISTINCT user_id) as count FROM subscriptions", fetch_one=True)
        stats['users'] = result['count'] if result else 0
        
        # Популярные ключевые слова
        results = execute_query("""
            SELECT keyword, COUNT(*) as count 
            FROM subscriptions 
            GROUP BY keyword 
            ORDER BY count DESC 
            LIMIT 5
        """)
        stats['top_keywords'] = [(r['keyword'], r['count']) for r in results]
        
        return stats
        
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        return {}

