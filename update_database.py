"""
Скрипт для добавления новых полей в таблицу homeworks
"""
import asyncio
import asyncpg
from bot.config import settings


async def update_database():
    """Добавляем новые поля в таблицу homeworks"""

    # Парсим DATABASE_URL для получения параметров подключения
    db_url = settings.DATABASE_URL
    if db_url.startswith('mysql+asyncmy://'):
        print("Обнаружена MySQL база данных")
        import aiomysql

        # Парсим URL
        # mysql+asyncmy://user:password@host:port/database
        parts = db_url.replace('mysql+asyncmy://', '').split('/')
        db_name = parts[-1]
        auth_host = parts[0].split('@')
        host_port = auth_host[-1].split(':')
        host = host_port[0]
        port = int(host_port[1]) if len(host_port) > 1 else 3306
        user_pass = auth_host[0].split(':')
        user = user_pass[0]
        password = user_pass[1] if len(user_pass) > 1 else ''

        conn = await aiomysql.connect(
            host=host, port=port, user=user, password=password, db=db_name
        )

        try:
            cursor = await conn.cursor()

            # Проверяем, существуют ли уже колонки
            await cursor.execute("SHOW COLUMNS FROM homeworks LIKE 'lesson_id'")
            lesson_id_exists = await cursor.fetchone()

            await cursor.execute("SHOW COLUMNS FROM homeworks LIKE 'is_archived'")
            is_archived_exists = await cursor.fetchone()

            # Добавляем колонки, если их нет
            if not lesson_id_exists:
                print("Добавляем колонку lesson_id...")
                await cursor.execute("""
                    ALTER TABLE homeworks 
                    ADD COLUMN lesson_id INT NULL,
                    ADD INDEX ix_homeworks_lesson_id (lesson_id),
                    ADD FOREIGN KEY fk_homework_lesson (lesson_id) 
                    REFERENCES schedule_lessons(id) ON DELETE SET NULL
                """)

            if not is_archived_exists:
                print("Добавляем колонки архивирования...")
                await cursor.execute("""
                    ALTER TABLE homeworks 
                    ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT FALSE,
                    ADD COLUMN archived_at DATETIME NULL,
                    ADD INDEX ix_homeworks_is_archived (is_archived)
                """)

            await conn.commit()
            print("✅ База данных успешно обновлена!")

        finally:
            conn.close()

    else:
        print(f"Неподдерживаемый тип базы данных: {db_url}")


if __name__ == "__main__":
    asyncio.run(update_database())
