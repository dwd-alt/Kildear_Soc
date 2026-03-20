#!/usr/bin/env python3
"""
Скрипт миграции для исправления типов полей в PostgreSQL
Запуск: python migration_fix.py
"""

import os
import sys
import logging
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import ProgrammingError

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_database_url():
    """Получить URL базы данных из переменных окружения"""
    database_url = os.environ.get('DATABASE_URL', '')
    
    if not database_url:
        logger.error("❌ DATABASE_URL не установлен!")
        logger.info("Пожалуйста, установите переменную окружения DATABASE_URL")
        sys.exit(1)
    
    # Конвертируем postgres:// в postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    # Добавляем sslmode для Render
    if '?' in database_url:
        database_url = database_url + '&sslmode=require'
    else:
        database_url = database_url + '?sslmode=require'
    
    return database_url

def check_column_type(conn, table, column):
    """Проверить текущий тип колонки"""
    try:
        result = conn.execute(text(f"""
            SELECT data_type, character_maximum_length 
            FROM information_schema.columns 
            WHERE table_name = '{table}' 
            AND column_name = '{column}'
        """))
        row = result.fetchone()
        if row:
            return {'type': row[0], 'max_length': row[1]}
        return None
    except Exception as e:
        logger.error(f"Ошибка при проверке типа {table}.{column}: {e}")
        return None

def alter_column_to_text(conn, table, column):
    """Изменить тип колонки на TEXT"""
    try:
        # Проверяем текущий тип
        current_type = check_column_type(conn, table, column)
        if current_type:
            logger.info(f"📊 Текущий тип {table}.{column}: {current_type['type']} (max: {current_type['max_length']})")
            
            # Если уже TEXT, пропускаем
            if current_type['type'] == 'text':
                logger.info(f"✅ {table}.{column} уже имеет тип TEXT")
                return True
        
        # Изменяем тип
        logger.info(f"🔄 Изменение типа {table}.{column} на TEXT...")
        conn.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN {column} TYPE TEXT'))
        conn.commit()
        logger.info(f"✅ {table}.{column} успешно изменен на TEXT")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при изменении {table}.{column}: {e}")
        return False

def add_column_if_not_exists(conn, table, column, column_type, default=None):
    """Добавить колонку если она не существует"""
    try:
        # Проверяем существование колонки
        result = conn.execute(text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' 
            AND column_name = '{column}'
        """))
        
        if result.fetchone():
            logger.info(f"✅ Колонка {table}.{column} уже существует")
            return True
        
        # Добавляем колонку
        sql = f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS {column} {column_type}'
        if default:
            sql += f' DEFAULT {default}'
        
        logger.info(f"➕ Добавление колонки {table}.{column}...")
        conn.execute(text(sql))
        conn.commit()
        logger.info(f"✅ Колонка {table}.{column} добавлена")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при добавлении {table}.{column}: {e}")
        return False

def main():
    """Основная функция миграции"""
    database_url = get_database_url()
    logger.info(f"🔗 Подключение к базе данных...")
    
    try:
        engine = create_engine(database_url)
        
        with engine.connect() as conn:
            # Получаем список всех таблиц
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            logger.info(f"📊 Найдены таблицы: {', '.join(tables)}")
            
            print("\n" + "="*70)
            print("1. ИЗМЕНЕНИЕ ТИПОВ ПОЛЕЙ НА TEXT")
            print("="*70)
            
            # Определяем поля для изменения на TEXT
            text_fields = {
                'user': ['avatar', 'cover_photo'],
                'post': ['media_url', 'thumbnail'],
                'message': ['media_url'],
                'group': ['avatar', 'cover'],
                'channel': ['avatar', 'cover'],
                'voice_message': ['audio_url']
            }
            
            for table, columns in text_fields.items():
                if table in tables:
                    logger.info(f"\n📝 Обработка таблицы {table}...")
                    for column in columns:
                        alter_column_to_text(conn, table, column)
                else:
                    logger.warning(f"⚠️ Таблица {table} не найдена")
            
            print("\n" + "="*70)
            print("2. ДОБАВЛЕНИЕ НОВЫХ КОЛОНОК ДЛЯ BASE64")
            print("="*70)
            
            # Добавляем новые колонки для Base64 хранения
            new_columns = {
                'user': [
                    ('avatar_data', 'TEXT'),
                    ('avatar_mime', 'VARCHAR(50)', "'image/png'"),
                    ('cover_data', 'TEXT'),
                    ('cover_mime', 'VARCHAR(50)', "'image/jpeg'"),
                ],
                'post': [
                    ('media_data', 'TEXT'),
                    ('media_mime', 'VARCHAR(50)'),
                ],
                'message': [
                    ('media_data', 'TEXT'),
                    ('media_mime', 'VARCHAR(50)'),
                ],
                'group': [
                    ('avatar_data', 'TEXT'),
                    ('avatar_mime', 'VARCHAR(50)', "'image/png'"),
                    ('cover_data', 'TEXT'),
                    ('cover_mime', 'VARCHAR(50)', "'image/jpeg'"),
                ],
                'channel': [
                    ('avatar_data', 'TEXT'),
                    ('avatar_mime', 'VARCHAR(50)', "'image/png'"),
                    ('cover_data', 'TEXT'),
                    ('cover_mime', 'VARCHAR(50)', "'image/jpeg'"),
                ],
                'voice_message': [
                    ('audio_data', 'TEXT'),
                ]
            }
            
            for table, columns in new_columns.items():
                if table in tables:
                    logger.info(f"\n📝 Добавление колонок в таблицу {table}...")
                    for col_info in columns:
                        if len(col_info) == 2:
                            col_name, col_type = col_info
                            default = None
                        else:
                            col_name, col_type, default = col_info
                        add_column_if_not_exists(conn, table, col_name, col_type, default)
            
            print("\n" + "="*70)
            print("3. СОЗДАНИЕ НЕДОСТАЮЩИХ ТАБЛИЦ")
            print("="*70)
            
            # Создаем недостающие таблицы
            required_tables = ['login_history', 'voice_message', 'call', 'report']
            
            for table in required_tables:
                if table not in tables:
                    logger.info(f"📝 Создание таблицы {table}...")
                    
                    if table == 'login_history':
                        conn.execute(text("""
                            CREATE TABLE IF NOT EXISTS login_history (
                                id SERIAL PRIMARY KEY,
                                user_id INTEGER REFERENCES "user"(id),
                                ip_address VARCHAR(45) NOT NULL,
                                user_agent VARCHAR(500),
                                location VARCHAR(100),
                                success BOOLEAN DEFAULT TRUE,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                        """))
                    elif table == 'voice_message':
                        conn.execute(text("""
                            CREATE TABLE IF NOT EXISTS voice_message (
                                id SERIAL PRIMARY KEY,
                                sender_id INTEGER NOT NULL REFERENCES "user"(id),
                                receiver_id INTEGER NOT NULL REFERENCES "user"(id),
                                audio_data TEXT,
                                audio_mime VARCHAR(50) DEFAULT 'audio/mpeg',
                                audio_url TEXT DEFAULT '',
                                duration INTEGER DEFAULT 0,
                                is_read BOOLEAN DEFAULT FALSE,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                        """))
                    elif table == 'call':
                        conn.execute(text("""
                            CREATE TABLE IF NOT EXISTS call (
                                id SERIAL PRIMARY KEY,
                                caller_id INTEGER NOT NULL REFERENCES "user"(id),
                                callee_id INTEGER NOT NULL REFERENCES "user"(id),
                                call_type VARCHAR(10) NOT NULL,
                                status VARCHAR(20) DEFAULT 'missed',
                                duration INTEGER DEFAULT 0,
                                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                ended_at TIMESTAMP
                            )
                        """))
                    elif table == 'report':
                        conn.execute(text("""
                            CREATE TABLE IF NOT EXISTS report (
                                id SERIAL PRIMARY KEY,
                                reporter_id INTEGER NOT NULL REFERENCES "user"(id),
                                reported_user_id INTEGER REFERENCES "user"(id),
                                post_id INTEGER REFERENCES post(id),
                                comment_id INTEGER REFERENCES comment(id),
                                reason VARCHAR(200) NOT NULL,
                                description TEXT,
                                status VARCHAR(20) DEFAULT 'pending',
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                reviewed_at TIMESTAMP,
                                reviewed_by INTEGER REFERENCES "user"(id)
                            )
                        """))
                    
                    conn.commit()
                    logger.info(f"✅ Таблица {table} создана")
            
            print("\n" + "="*70)
            print("4. СОЗДАНИЕ ИНДЕКСОВ")
            print("="*70)
            
            # Создаем индексы для производительности
            indexes = [
                ('idx_user_username', 'user', 'username'),
                ('idx_user_email', 'user', 'email'),
                ('idx_user_is_admin', 'user', 'is_admin'),
                ('idx_post_user_id', 'post', 'user_id'),
                ('idx_post_created_at', 'post', 'created_at'),
                ('idx_message_sender', 'message', 'sender_id'),
                ('idx_message_receiver', 'message', 'receiver_id'),
                ('idx_notification_user', 'notification', 'user_id'),
                ('idx_voice_message_receiver', 'voice_message', 'receiver_id'),
                ('idx_voice_message_sender', 'voice_message', 'sender_id'),
                ('idx_call_caller', 'call', 'caller_id'),
                ('idx_call_callee', 'call', 'callee_id'),
            ]
            
            for idx_name, table_name, column in indexes:
                if table_name in tables or table_name == 'voice_message':
                    try:
                        logger.info(f"📝 Создание индекса {idx_name}...")
                        conn.execute(text(f'CREATE INDEX IF NOT EXISTS {idx_name} ON "{table_name}" ({column})'))
                        conn.commit()
                        logger.info(f"✅ Индекс {idx_name} создан")
                    except Exception as e:
                        logger.warning(f"⚠️ Не удалось создать индекс {idx_name}: {e}")
            
            print("\n" + "="*70)
            print("5. ОБНОВЛЕНИЕ ДАННЫХ")
            print("="*70)
            
            # Обновляем значения по умолчанию
            try:
                logger.info("📝 Установка значений по умолчанию...")
                conn.execute(text('UPDATE "user" SET is_admin = FALSE WHERE is_admin IS NULL'))
                conn.execute(text('UPDATE "user" SET is_online = FALSE WHERE is_online IS NULL'))
                conn.execute(text('UPDATE "user" SET two_factor_enabled = FALSE WHERE two_factor_enabled IS NULL'))
                conn.execute(text('UPDATE "user" SET avatar_mime = \'image/png\' WHERE avatar_mime IS NULL'))
                conn.execute(text('UPDATE "user" SET cover_mime = \'image/jpeg\' WHERE cover_mime IS NULL'))
                conn.execute(text('UPDATE voice_message SET is_read = FALSE WHERE is_read IS NULL'))
                conn.commit()
                logger.info("✅ Данные обновлены")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при обновлении данных: {e}")
            
            print("\n" + "="*70)
            print("6. ПРОВЕРКА РЕЗУЛЬТАТОВ")
            print("="*70)
            
            # Проверяем результаты
            logger.info("📊 Проверка типов полей:")
            
            for table, columns in text_fields.items():
                if table in tables:
                    for column in columns:
                        col_info = check_column_type(conn, table, column)
                        if col_info:
                            logger.info(f"  {table}.{column}: {col_info['type']} (max: {col_info['max_length']})")
            
            # Проверяем количество записей
            for table in tables:
                try:
                    result = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
                    count = result.scalar()
                    logger.info(f"📊 Таблица {table}: {count} записей")
                except:
                    pass
            
            logger.info("\n🎉 МИГРАЦИЯ УСПЕШНО ЗАВЕРШЕНА!")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при миграции: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🔄 МИГРАЦИЯ БАЗЫ ДАННЫХ KILDEAR SOCIAL NETWORK")
    print("="*70)
    print("Этот скрипт изменит типы полей на TEXT и добавит новые колонки")
    print("для хранения Base64 изображений.")
    print("="*70)
    
    response = input("\nПродолжить? (y/n): ")
    if response.lower() != 'y':
        print("Миграция отменена.")
        sys.exit(0)
    
    main()
    print("="*70)
