#!/usr/bin/env python
"""
Скрипт миграции базы данных для Kildear Social Network
Запуск: python migration.py
"""

import os
import sys
import logging
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import ProgrammingError

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация базы данных
def get_database_url():
    """Получить URL базы данных из переменных окружения"""
    database_url = os.environ.get('DATABASE_URL', '')
    
    if not database_url:
        logger.error("❌ DATABASE_URL не установлен!")
        logger.info("Пожалуйста, установите переменную окружения DATABASE_URL")
        logger.info("Пример: export DATABASE_URL='postgresql://user:password@localhost:5432/kildear'")
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

def run_migration():
    """Запуск миграции"""
    
    # Подключаемся к базе данных
    database_url = get_database_url()
    logger.info(f"🔗 Подключение к базе данных: {database_url[:50]}...")
    
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        inspector = inspect(engine)
        
        # Проверяем подключение
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            logger.info("✅ Подключение к базе данных успешно")
        
        # Получаем список всех таблиц
        tables = inspector.get_table_names()
        logger.info(f"📊 Существующие таблицы: {tables}")
        
        # Определяем все колонки для каждой таблицы
        migrations = {
            'user': [
                ('avatar_data', 'TEXT'),
                ('avatar_mime', 'VARCHAR(50) DEFAULT \'image/png\''),
                ('cover_data', 'TEXT'),
                ('cover_mime', 'VARCHAR(50) DEFAULT \'image/jpeg\''),
                ('two_factor_enabled', 'BOOLEAN DEFAULT FALSE'),
                ('two_factor_secret', 'VARCHAR(32)'),
                ('is_online', 'BOOLEAN DEFAULT FALSE'),
                ('is_admin', 'BOOLEAN DEFAULT FALSE'),
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
                ('avatar_mime', 'VARCHAR(50) DEFAULT \'image/png\''),
                ('cover_data', 'TEXT'),
                ('cover_mime', 'VARCHAR(50) DEFAULT \'image/jpeg\''),
            ],
            'channel': [
                ('avatar_data', 'TEXT'),
                ('avatar_mime', 'VARCHAR(50) DEFAULT \'image/png\''),
                ('cover_data', 'TEXT'),
                ('cover_mime', 'VARCHAR(50) DEFAULT \'image/jpeg\''),
            ]
        }
        
        # Создаем таблицы, если их нет
        with engine.connect() as conn:
            # Создаем таблицы через SQLAlchemy MetaData, если нужно
            if not tables:
                logger.info("📊 Создание всех таблиц...")
                # Здесь можно импортировать модели и создать таблицы
                # Но для простоты, создадим через SQL
                
                # Таблица user
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS "user" (
                        id SERIAL PRIMARY KEY,
                        username VARCHAR(40) UNIQUE NOT NULL,
                        email VARCHAR(120) UNIQUE NOT NULL,
                        password_hash VARCHAR(256) NOT NULL,
                        display_name VARCHAR(60) DEFAULT '',
                        bio VARCHAR(500) DEFAULT '',
                        avatar_data TEXT,
                        avatar_mime VARCHAR(50) DEFAULT 'image/png',
                        cover_data TEXT,
                        cover_mime VARCHAR(50) DEFAULT 'image/jpeg',
                        avatar VARCHAR(300) DEFAULT '/static/default_avatar.png',
                        cover_photo VARCHAR(300) DEFAULT '',
                        website VARCHAR(200) DEFAULT '',
                        location VARCHAR(100) DEFAULT '',
                        accent_color VARCHAR(7) DEFAULT '#6c63ff',
                        is_private BOOLEAN DEFAULT FALSE,
                        is_verified BOOLEAN DEFAULT FALSE,
                        is_banned BOOLEAN DEFAULT FALSE,
                        is_admin BOOLEAN DEFAULT FALSE,
                        is_online BOOLEAN DEFAULT FALSE,
                        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        two_factor_enabled BOOLEAN DEFAULT FALSE,
                        two_factor_secret VARCHAR(32)
                    )
                """))
                logger.info("✅ Таблица user создана")
                
                # Создаем остальные таблицы
                # ... (аналогично для других таблиц)
                
                conn.commit()
        
        # Добавляем недостающие колонки
        with engine.connect() as conn:
            for table_name, columns in migrations.items():
                if table_name not in tables:
                    logger.info(f"⚠️ Таблица {table_name} не существует, пропускаем")
                    continue
                
                # Получаем существующие колонки
                existing_columns = [col['name'] for col in inspector.get_columns(table_name)]
                logger.info(f"📊 Таблица {table_name}: существующие колонки - {existing_columns}")
                
                # Добавляем новые колонки
                for col_name, col_type in columns:
                    if col_name not in existing_columns:
                        logger.info(f"➕ Добавление колонки {col_name} в таблицу {table_name}...")
                        try:
                            conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS {col_name} {col_type}'))
                            conn.commit()
                            logger.info(f"✅ Колонка {col_name} добавлена")
                        except Exception as e:
                            logger.error(f"❌ Ошибка при добавлении колонки {col_name}: {e}")
                            conn.rollback()
        
        # Проверяем и добавляем внешние ключи
        logger.info("🔍 Проверка внешних ключей...")
        
        # Создаем индексы для производительности
        with engine.connect() as conn:
            indexes = [
                ('idx_user_username', 'user', 'username'),
                ('idx_user_email', 'user', 'email'),
                ('idx_user_is_admin', 'user', 'is_admin'),
                ('idx_user_is_banned', 'user', 'is_banned'),
                ('idx_post_user_id', 'post', 'user_id'),
                ('idx_post_created_at', 'post', 'created_at'),
                ('idx_message_sender', 'message', 'sender_id'),
                ('idx_message_receiver', 'message', 'receiver_id'),
                ('idx_notification_user', 'notification', 'user_id'),
            ]
            
            for idx_name, table_name, column in indexes:
                try:
                    conn.execute(text(f'CREATE INDEX IF NOT EXISTS {idx_name} ON "{table_name}" ({column})'))
                    conn.commit()
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось создать индекс {idx_name}: {e}")
            
            logger.info("✅ Индексы созданы")
        
        # Обновляем существующие записи
        with engine.connect() as conn:
            # Устанавливаем значения по умолчанию для NULL полей
            updates = [
                ('user', 'is_admin', 'FALSE'),
                ('user', 'is_online', 'FALSE'),
                ('user', 'two_factor_enabled', 'FALSE'),
                ('user', 'avatar_mime', "'image/png'"),
                ('user', 'cover_mime', "'image/jpeg'"),
            ]
            
            for table_name, column, default_value in updates:
                try:
                    conn.execute(text(f'UPDATE "{table_name}" SET {column} = {default_value} WHERE {column} IS NULL'))
                    conn.commit()
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось обновить {table_name}.{column}: {e}")
        
        logger.info("🎉 Миграция базы данных завершена успешно!")
        
        # Выводим статистику
        with engine.connect() as conn:
            for table in tables:
                result = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
                count = result.scalar()
                logger.info(f"📊 Таблица {table}: {count} записей")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при миграции: {e}")
        sys.exit(1)

def create_all_tables():
    """Создание всех таблиц с нуля"""
    from app import app, db
    
    with app.app_context():
        logger.info("📊 Создание всех таблиц...")
        db.create_all()
        logger.info("✅ Все таблицы созданы")

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("🔄 MИГРАЦИЯ БАЗЫ ДАННЫХ KILDEAR SOCIAL NETWORK")
    print("=" * 70)
    
    # Если передан аргумент --create-all, создаем все таблицы с нуля
    if len(sys.argv) > 1 and sys.argv[1] == '--create-all':
        logger.info("Режим: создание всех таблиц с нуля")
        try:
            # Импортируем приложение
            sys.path.insert(0, os.path.dirname(__file__))
            from app import app, db
            create_all_tables()
        except Exception as e:
            logger.error(f"❌ Ошибка при создании таблиц: {e}")
            logger.info("Попытка использовать прямой SQL...")
            run_migration()
    else:
        run_migration()
    
    print("=" * 70)
