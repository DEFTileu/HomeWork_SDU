from __future__ import annotations

from typing import Tuple, Optional

from bs4 import BeautifulSoup as BS, BeautifulSoup
import logging
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from fake_useragent import UserAgent

from bot.database.models import ScheduleLesson
from bot.config import settings
from bot.services.auth import login_user
import aiohttp
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import re


# Константы для парсинга расписания
MAIN_URL = "https://my.sdu.edu.kz/index.php"
schedule_data_template = {
    "mod": "schedule",
    "ajx": "1",
    "action": "showSchedule",
    "year": "2025",
    "term": "1",
    "type": "I",
    "details": "0",
}

DAY_INDEX = {"Mo": 1, "Tu": 2, "We": 3, "Th": 4, "Fr": 5, "Sa": 6}


def get_day_of_week(j: int) -> int:
    """Возвращает день недели по индексу столбца"""
    day_mapping = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}  # Mo-Sa = 1-6
    return day_mapping.get(j, 1)


def _extract_time(td) -> tuple:
    """Extracts start and end time from the 'td' element."""
    time_text = td.get_text(strip=True)
    match = re.match(r"(\d{2}:\d{2})-(\d{2}:\d{2})", time_text)
    if match:
        start_time, end_time = match.groups()
        return start_time, end_time
    raise ValueError("Invalid time format")


async def import_schedule_html(db: AsyncSession, user_id: int, html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "clTbl"})
    if not table:
        logging.debug("Schedule parse: table .clTbl not found, imported=0")
        logging.debug(f"HTML sample: {html[:500]}")
        return 0

    # Clear previous schedule entries
    await db.execute(delete(ScheduleLesson).where(ScheduleLesson.user_id == user_id))

    trs = table.find_all("tr")
    logging.debug(f"Found {len(trs)} table rows")

    inserted = 0
    lessons_to_insert = []

    for i in range(1, max(1, len(trs) - 4)):  # skip header row and footer
        tr = trs[i]
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        # Time extraction (try-catch if it's not in the expected format)
        try:
            start_time, end_time = _extract_time(tds[0])
            logging.debug(f"Row {i}: time {start_time}-{end_time}")
        except Exception as e:
            logging.debug(f"Row {i}: failed to extract time from {tds[0]} - {str(e)}")
            continue

        # Day cells (Mo..Sa)
        for j, td in enumerate(tds[1:], start=1):
            if not td or not td.find('a'):  # skip empty cells
                continue
            lessons = td.find_all('a')
            locations = td.find_all('span', title=True)
            logging.debug(f"Day {j}: found {len(lessons)} lessons, {len(locations)} locations")

            for z in range(len(lessons)):
                a = lessons[z]
                code = (a.text or '').strip()
                title = a.get('title')
                # Handle room extraction (pair with locations)
                room = None
                idx = z * 2 + 1
                if idx < len(locations):
                    room = (locations[idx].text or '').strip()
                logging.debug(f"Lesson: {code} | {title} | {room}")

                lessons_to_insert.append(
                    {
                        "user_id": user_id,
                        "day_of_week": j,
                        "start_time": start_time,
                        "end_time": end_time,
                        "course_code": code,
                        "title": title,
                        "lesson_type": None,
                        "teacher": None,
                        "room": room,
                    }
                )
                inserted += 1

    # Bulk insert into the database
    if lessons_to_insert:
        for lesson_data in lessons_to_insert:
            lesson = ScheduleLesson(**lesson_data)
            db.add(lesson)
        await db.commit()
        logging.debug(f"Schedule parse: imported={inserted}")
    else:
        logging.debug("No lessons to import.")

    return inserted


async def fetch_and_import_schedule(
    db: AsyncSession,
    user_id: int,
    session_payload: Optional[dict] = None,
    year: Optional[int] = None,
    term: Optional[int] = None,
    type_code: str = "I",
    details: int = 0,
) -> int:
    if year is None or term is None:
        year_calc, term_calc = get_current_year_and_term()
        year = year or year_calc
        term = term or term_calc
    cookies = None
    if session_payload:
        cookies = session_payload.get("cookies")
    # Build headers similar to curl; keep it minimal but valid
    headers = {
        "Accept": "*/*",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://my.sdu.edu.kz",
        "Pragma": "no-cache",
        "Referer": "https://my.sdu.edu.kz/index.php?mod=schedule",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    data = {
        "mod": "schedule",
        "ajx": "1",
        "action": "showSchedule",
        "year": str(year),
        "term": str(term),
        "type": type_code,
        "details": str(details),
        str(int(time.time() * 1000)): "",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://my.sdu.edu.kz/index.php",
            headers=headers,
            data=data,
            cookies=cookies,
            allow_redirects=False,
        ) as resp:
            text = await resp.text()
            print(text)
            logging.debug(f"Schedule fetch: status={resp.status} len={len(text)}")
            if settings.DEBUG:
                logging.debug(f"Response sample: {text[:1000]}")
            return await import_schedule_html(db, user_id, text)


async def parse_schedule(username: str, password: str) -> list:
    """Парсинг расписания с сайта SDU"""
    arr = []
    schedule_datas = schedule_data_template.copy()

    # Устанавливаем текущий год и семестр
    year, term = get_current_year_and_term()
    schedule_datas["year"] = str(year)
    schedule_datas["term"] = str(term)
    # schedule_datas[str(int(time.time() * 1000))] = ""

    HEADERS = {'User-Agent': UserAgent().random}
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        # Логинимся с использованием существующей функции
        login_success = await login_user(username=username, password=password, session=session)
        if not login_success:
            logging.error("Failed to login during schedule parsing")
            return arr

        async with session.post(MAIN_URL, data=schedule_datas, ssl=False) as response:
            schedule = await response.text()
            soup = BS(schedule, 'lxml')

            table = soup.find('table', attrs={'class': 'clTbl'})
            if not table:
                logging.debug("Schedule table not found")
                return arr

            trs = table.find_all('tr')
            for i in range(1, len(trs) - 4):
                tr = trs[i]
                tds = tr.find_all('td')
                if len(tds) < 2:
                    continue

                # Извлекаем время
                time_span = tds[0].find('span')
                if not time_span:
                    continue
                time = time_span.text

                for j in range(1, len(tds)):
                    td = tds[j]
                    if len(td) == 1:
                        continue

                    # Ищем все ячейки с занятиями
                    lesson_cells = td.find_all('a')

                    for lesson_index, lesson_link in enumerate(lesson_cells):
                        # Извлекаем код предмета
                        course_code = lesson_link.text.strip()

                        # Извлекаем полное название из атрибута title
                        full_title = lesson_link.get('title', '')

                        # Ищем информацию о типе урока в span после ссылки
                        lesson_type = ""
                        section_code = ""
                        # Ищем span с квадратными скобками типа [14-P], [03-N] и т.д.
                        next_element = lesson_link.next_sibling
                        while next_element:
                            if hasattr(next_element, 'name') and next_element.name == 'span':
                                span_text = next_element.get_text(strip=True)
                                # Проверяем, содержит ли span текст в квадратных скобках
                                if span_text.startswith('[') and span_text.endswith(']'):
                                    section_code = span_text
                                    # Определяем тип занятия по последней букве
                                    if span_text.endswith('-P]'):
                                        lesson_type = "Практика"
                                    elif span_text.endswith('-N]'):
                                        lesson_type = "Лекция"
                                    elif span_text.endswith('-L]'):
                                        lesson_type = "Лабораторная"
                                    break
                            next_element = next_element.next_sibling

                        # Ищем имя преподавателя в span с name="details"
                        teacher_name = ""
                        details_spans = td.find_all('span', {'name': 'details'})
                        for details_span in details_spans:
                            details_text = details_span.get_text(strip=True)
                            # Преподавате��ь ��обычно указан после <br> в details
                            if details_text and len(details_text.split('\n')) > 1:
                                teacher_name = details_text.split('\n')[-1].strip()
                                break

                        # Ищем аудиторию - извлекаем текст из последнего span после img house.gif
                        location = ""
                        # Ищем img с src="images/house.gif" - это указатель на кабинет
                        house_img = td.find('img', src="images/house.gif")
                        if house_img:
                            # Кабинет указан в последнем span после этой картинки
                            # Ищем все span элементы после house.gif
                            next_element = house_img.next_sibling
                            while next_element:
                                if hasattr(next_element, 'name') and next_element.name == 'span':
                                    # Проверяем, что в span есть номер кабинета (не details)
                                    span_text = next_element.get_text(strip=True)
                                    if span_text and not next_element.get('name') == 'details':
                                        # Извлекаем только номер кабинета (например E117, I101)
                                        if re.match(r'^[A-Z]+\d+', span_text):
                                            location = span_text.replace(" ", "")
                                            break
                                next_element = next_element.next_sibling

                        # Если не нашли через house.gif, используем оригинальную логику с индексом
                        if not location:
                            locations = td.find_all('span', title=True)
                            location_index = lesson_index * 2 + 1
                            if location_index < len(locations):
                                location_text = locations[location_index].get_text(strip=True)
                                location = location_text.replace(" ", "")

                        # Добавляем расширенную информацию в массив
                        arr.append([
                            time,
                            get_day_of_week(j),
                            course_code,
                            location,
                            full_title,
                            lesson_type,
                            section_code,
                            teacher_name
                        ])

    return arr


async def fetch_and_import_schedule_new(
    db: AsyncSession,
    user_id: int,
    username: str,
    password: str,
) -> int:
    """Обновленная функция для получения и импорта расписания с использованием новой логики парсинга"""
    try:
        # Используем новую функцию парсинга
        schedule_data = await parse_schedule(username, password)

        if not schedule_data:
            logging.debug("No schedule data received")
            return 0

        # Очищаем предыдущие записи расписания
        await db.execute(delete(ScheduleLesson).where(ScheduleLesson.user_id == user_id))

        inserted = 0
        for item in schedule_data:
            # Теперь item содержит 8 элементов: [time, day_of_week, course_code, location, full_title, lesson_type, section_code, teacher_name]
            if len(item) >= 4:
                time_str = item[0]
                day_of_week = item[1]
                course_code = item[2]
                location = item[3]
                full_title = item[4] if len(item) > 4 else ""
                lesson_type = item[5] if len(item) > 5 else ""
                section_code = item[6] if len(item) > 6 else ""
                teacher_name = item[7] if len(item) > 7 else ""

                # Парсим время
                try:
                    start_time, end_time = parse_time_string(time_str)
                except ValueError:
                    logging.warning(f"Could not parse time: {time_str}")
                    continue

                # Создаем объект занятия с полной информацией
                lesson = ScheduleLesson(
                    user_id=user_id,
                    day_of_week=day_of_week,
                    start_time=start_time,
                    end_time=end_time,
                    course_code=course_code,
                    title=full_title,
                    lesson_type=lesson_type,
                    section_code=section_code,
                    teacher=teacher_name,
                    room=location,
                )
                db.add(lesson)
                inserted += 1

        await db.commit()
        logging.debug(f"Schedule parse: imported={inserted} lessons with extended info")
        return inserted

    except Exception as e:
        logging.exception(f"Error in fetch_and_import_schedule_new: {e}")
        return 0

def parse_time_string(time_str: str) -> Tuple[str, str]:
    """Парсит строку времени в формате '09:00-10:30' или просто '09:00'"""
    time_str = time_str.strip()

    # Проверяем формат с диапазоном времени
    if '-' in time_str:
        parts = time_str.split('-')
        if len(parts) == 2:
            start_time = parts[0].strip()
            end_time = parts[1].strip()
            return start_time, end_time

    # Если нет диапазона, предполагаем 50 минута занятие
    match = re.match(r'(\d{1,2}):(\d{2})', time_str)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))

        # Добавляем 0 час 30 минут
        end_minute = minute + 50
        end_hour = hour + 0
        if end_minute >= 60:
            end_minute -= 60
            end_hour += 1

        start_time = f"{hour:02d}:{minute:02d}"
        end_time = f"{end_hour:02d}:{end_minute:02d}"
        return start_time, end_time

    raise ValueError(f"Could not parse time string: {time_str}")

def get_current_year_and_term() -> Tuple[int, int]:
    tz = ZoneInfo(settings.TIMEZONE)
    now = datetime.now(tz)
    month = now.month
    # Academic year starts in September
    if month >= 9:
        academic_year_start = now.year
        term = 1
    elif 1 <= month <= 6:
        academic_year_start = now.year - 1
        term = 2
    else:
        # July-August – assume still previous academic year, optional summer term 3
        academic_year_start = now.year - 1
        term = 3
    # API expects the starting year, e.g. 2025 for 2025-2026 term 1/2
    return academic_year_start, term
