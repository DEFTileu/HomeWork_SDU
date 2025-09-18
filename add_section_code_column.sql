-- Добавление столбца section_code в таблицу schedule_lessons
ALTER TABLE schedule_lessons ADD COLUMN section_code VARCHAR(16) NULL;

-- Обновление существующих записей (если нужно)
-- UPDATE schedule_lessons SET section_code = NULL WHERE section_code IS NULL;
