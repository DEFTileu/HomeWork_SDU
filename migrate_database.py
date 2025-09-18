"""
Утилита для применения SQL миграций к базе данных MySQL
"""
import asyncio
import aiomysql
from bot.config import settings
import re

async def apply_migration():
    """Добавляет столбец section_code в таблицу schedule_lessons"""

    # Парсим MySQL DATABASE_URL
    # Пример: mysql+asyncmy://user:password@localhost:3306/dbname
    db_url = settings.DATABASE_URL

    # Извлекаем параметры подключения
    pattern = r'mysql\+asyncmy://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
    match = re.match(pattern, db_url)

    if not match:
        print(f"❌ Не удалось разобрать DATABASE_URL: {db_url}")
        return

    user, password, host, port, database = match.groups()

    try:
        conn = await aiomysql.connect(
            host=host,
            port=int(port),
            user=user,
            password=password,
            db=database
        )

        cursor = await conn.cursor()

        # Проверяем, существует ли уже столбец section_code
        check_query = """
        SELECT COLUMN_NAME 
        FROM INFORMATION_SCHEMA.COLUMNS 
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'schedule_lessons' AND COLUMN_NAME = 'section_code'
        """

        await cursor.execute(check_query, (database,))
        result = await cursor.fetchone()

        if not result:
            print("Добавляю столбец section_code...")
            await cursor.execute("ALTER TABLE schedule_lessons ADD COLUMN section_code VARCHAR(16) NULL")
            await conn.commit()
            print("✅ Столбец section_code успешно добавлен!")
        else:
            print("✅ Столбец section_code уже существует!")

        await cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Ошибка при применении миграции: {e}")

if __name__ == "__main__":
    asyncio.run(apply_migration())
