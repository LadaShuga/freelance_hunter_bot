"""
hh_parser.py 
"""

import requests
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Vacancy:
    """Минимальный класс для представления вакансии"""
    title: str
    url: str
    company: str
    salary: Optional[Dict]
    published_at: str
    formatted_date: str = ""
    
    @classmethod
    def from_hh_data(cls, data: Dict[str, Any]) -> 'Vacancy':
        """Создает Vacancy из данных HH API"""
        # Обработка компании
        employer = data.get('employer', {})
        company = employer.get('name', 'Не указана')
        
        # Обработка даты
        published_at = data.get('published_at', '')
        formatted_date = cls._format_date(published_at)
        
        return cls(
            title=data.get('name', 'Без названия'),
            url=data.get('alternate_url', '#'),
            company=company,
            salary=data.get('salary'),
            published_at=published_at,
            formatted_date=formatted_date
        )
    
    @staticmethod
    def _format_date(date_str: str) -> str:
        """Форматирует дату из ISO в читаемый вид"""
        if not date_str:
            return "неизвестно"
        
        try:
            # Убираем Z в конце строки, если есть
            if date_str.endswith('Z'):
                date_str = date_str[:-1] + '+00:00'
            
            dt = datetime.fromisoformat(date_str)
            return dt.strftime("%d.%m.%Y %H:%M")
        except (ValueError, AttributeError):
            return "неизвестно"
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразует в словарь для совместимости"""
        return {
            'name': self.title,
            'alternate_url': self.url,
            'company': self.company,
            'salary': self.salary,
            'published_at': self.published_at,
            'published_at_formatted': self.formatted_date,
            'employer': {'name': self.company}
        }


class HHParser:
    """Основной класс для работы с API HH.ru"""
    
    BASE_URL = "https://api.hh.ru/vacancies"
    
    def __init__(self, timeout: int = 10, max_retries: int = 2):
        """Инициализация парсера """
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        
        # Настройка заголовков для имитации браузера
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 FreelanceHunterBot/1.0',
            'Accept': 'application/json',
            'Accept-Language': 'ru-RU,ru;q=0.9'
        })
    
    def search_vacancies(
        self, 
        keyword: str, 
        per_page: int = 5,
        area: int = 1,
        retry_count: int = 0
    ) -> List[Vacancy]:
        """
        Поиск вакансий по ключевому слову с повторными попытками
        
        Args:
            keyword: Ключевое слово для поиска
            per_page: Количество вакансий (1-100)
            area: ID региона (1 - Москва)
            retry_count: Текущая попытка (для рекурсии)
            
        Returns:
            Список объектов Vacancy
        """
        params = {
            'text': keyword,
            'area': area,
            'per_page': min(max(per_page, 1), 100),  # Ограничение 1-100
            'page': 0,
            'order_by': 'publication_time',
            'search_field': 'name'
        }
        
        try:
            response = self.session.get(
                self.BASE_URL, 
                params=params, 
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            vacancies_data = data.get('items', [])
            
            # Преобразуем данные в объекты Vacancy
            vacancies = []
            for item in vacancies_data:
                try:
                    vacancy = Vacancy.from_hh_data(item)
                    vacancies.append(vacancy)
                except Exception as e:
                    logger.warning(f"Ошибка обработки вакансии: {e}")
                    continue
            
            logger.info(f"Найдено {len(vacancies)} вакансий по запросу '{keyword}'")
            return vacancies
            
        except requests.exceptions.Timeout:
            logger.warning(f"Таймаут при поиске '{keyword}'")
            if retry_count < self.max_retries:
                logger.info(f"Повторная попытка {retry_count + 1}/{self.max_retries}")
                time.sleep(1)  # Пауза перед повторной попыткой
                return self.search_vacancies(keyword, per_page, area, retry_count + 1)
            return []
            
        except requests.exceptions.ConnectionError:
            logger.error(f"Ошибка соединения при поиске '{keyword}'")
            return []
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP ошибка {e.response.status_code}: {e}")
            return []
            
        except Exception as e:
            logger.error(f"Неожиданная ошибка при поиске '{keyword}': {e}")
            return []
    
    def get_vacancy_details(self, vacancy_id: str) -> Optional[Dict]:
        """
        Получает детали вакансии по ID
        
        Args:
            vacancy_id: ID вакансии на HH.ru
            
        Returns:
            Словарь с деталями или None
        """
        url = f"{self.BASE_URL}/{vacancy_id}"
        
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Ошибка получения деталей вакансии {vacancy_id}: {e}")
            return None
    
    def close(self):
        """Закрывает сессию"""
        self.session.close()


# ========== СОВМЕСТИМЫЕ ФУНКЦИИ ==========

_parser_instance = None

def get_parser() -> HHParser:
    """Возвращает экземпляр парсера (синглтон)"""
    global _parser_instance
    if _parser_instance is None:
        _parser_instance = HHParser()
    return _parser_instance


def parse_hh_vacancies(
    keyword: str = "Python", 
    area: int = 1, 
    per_page: int = 10
) -> List[Dict[str, Any]]:
    """
    Основная функция для использования в боте
    Совместима с существующим кодом
    
    Args:
        keyword: Ключевое слово для поиска
        area: ID региона
        per_page: Количество вакансий
        
    Returns:
        Список словарей с вакансиями
    """
    parser = get_parser()
    vacancies = parser.search_vacancies(keyword, per_page, area)
    
    # Преобразуем в список словарей для совместимости
    return [vacancy.to_dict() for vacancy in vacancies]


def search_vacancies(keyword: str, per_page: int = 5) -> List[Dict[str, Any]]:
    """
    Упрощенная функция для поиска вакансий
    Используется в bot.py
    
    Args:
        keyword: Ключевое слово
        per_page: Количество вакансий
        
    Returns:
        Список словарей с вакансиями
    """
    return parse_hh_vacancies(keyword, per_page=per_page)


def format_salary_for_display(salary_data: Optional[Dict]) -> str:
    """
    Форматирует зарплату для отображения
    Может использоваться в других модулях
    
    Args:
        salary_data: Данные о зарплате из API
        
    Returns:
        Отформатированная строка
    """
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


