# full_migration.py
import os
import sys
import logging
from sqlalchemy import create_engine, text, inspect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_database_url():
    """Получить URL базы данных"""
    database_url = os.environ.get('DATABASE_URL', '')
    if not database_url:
        logger.error("❌ DATABASE_URL не установлен!")
        sys.exit(1)
    
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    if '?' in database_url:
        database_url = database_url + '&sslmode=require'
    else:
        database_url = database_url + '?sslmode=require'
    
    return database_url

def add_column(conn, table, column, column_type, default=None):
    """Добавить колонку если она не существует"""
    try:
        # Проверяем существование колонки
        inspector = inspect(conn)
        columns = [col['name'] for col in inspector.get_columns(table)]
        
        if column in columns:
            logger.info(f"✅ Колонка {table}.{column} уже существует")
            return True
        
        # Добавляем колонку
        sql = f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS {column} {column_type}'
        if default:
            sql += f' DEFAULT {default}'
        
        conn.execute(text(sql))
        conn.commit()
        logger.info(f"➕ Добавлена колонка {table}.{column}")
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
            # Проверяем существующие таблицы
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            logger.info(f"📊 Существующие таблицы: {tables}")
            
            # 1. Добавляем колонки в таблицу user
            if 'user' in tables:
                logger.info("\n📝 Обновление таблицы user...")
                add_column(conn, 'user', 'avatar_data', 'TEXT')
                add_column(conn, 'user', 'avatar_mime', 'VARCHAR(50)', "'image/png'")
                add_column(conn, 'user', 'cover_data', 'TEXT')
                add_column(conn, 'user', 'cover_mime', 'VARCHAR(50)', "'image/jpeg'")
                add_column(conn, 'user', 'two_factor_enabled', 'BOOLEAN', 'FALSE')
                add_column(conn, 'user', 'two_factor_secret', 'VARCHAR(32)')
                add_column(conn, 'user', 'is_online', 'BOOLEAN', 'FALSE')
                add_column(conn, 'user', 'is_admin', 'BOOLEAN', 'FALSE')
            else:
                logger.warning("⚠️ Таблица user не найдена!")
            
            # 2. Добавляем колонки в таблицу voice_message
            if 'voice_message' in tables:
                logger.info("\n📝 Обновление таблицы voice_message...")
                add_column(conn, 'voice_message', 'audio_data', 'TEXT')
                add_column(conn, 'voice_message', 'audio_mime', 'VARCHAR(50)', "'audio/mpeg'")
                add_column(conn, 'voice_message', 'audio_url', 'VARCHAR(300)', "''")
                add_column(conn, 'voice_message', 'duration', 'INTEGER', '0')
                add_column(conn, 'voice_message', 'is_read', 'BOOLEAN', 'FALSE')
            else:
                logger.info("📝 Создание таблицы voice_message...")
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS voice_message (
                        id SERIAL PRIMARY KEY,
                        sender_id INTEGER REFERENCES "user"(id),
                        receiver_id INTEGER REFERENCES "user"(id),
                        audio_data TEXT,
                        audio_mime VARCHAR(50) DEFAULT 'audio/mpeg',
                        audio_url VARCHAR(300) DEFAULT '',
                        duration INTEGER DEFAULT 0,
                        is_read BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.commit()
                logger.info("✅ Таблица voice_message создана")
            
            # 3. Добавляем колонки в таблицу post
            if 'post' in tables:
                logger.info("\n📝 Обновление таблицы post...")
                add_column(conn, 'post', 'media_data', 'TEXT')
                add_column(conn, 'post', 'media_mime', 'VARCHAR(50)')
            else:
                logger.warning("⚠️ Таблица post не найдена!")
            
            # 4. Добавляем колонки в таблицу message
            if 'message' in tables:
                logger.info("\n📝 Обновление таблицы message...")
                add_column(conn, 'message', 'media_data', 'TEXT')
                add_column(conn, 'message', 'media_mime', 'VARCHAR(50)')
            else:
                logger.warning("⚠️ Таблица message не найдена!")
            
            # 5. Добавляем колонки в таблицу group
            if 'group' in tables:
                logger.info("\n📝 Обновление таблицы group...")
                add_column(conn, 'group', 'avatar_data', 'TEXT')
                add_column(conn, 'group', 'avatar_mime', 'VARCHAR(50)', "'image/png'")
                add_column(conn, 'group', 'cover_data', 'TEXT')
                add_column(conn, 'group', 'cover_mime', 'VARCHAR(50)', "'image/jpeg'")
            else:
                logger.warning("⚠️ Таблица group не найдена!")
            
            # 6. Добавляем колонки в таблицу channel
            if 'channel' in tables:
                logger.info("\n📝 Обновление таблицы channel...")
                add_column(conn, 'channel', 'avatar_data', 'TEXT')
                add_column(conn, 'channel', 'avatar_mime', 'VARCHAR(50)', "'image/png'")
                add_column(conn, 'channel', 'cover_data', 'TEXT')
                add_column(conn, 'channel', 'cover_mime', 'VARCHAR(50)', "'image/jpeg'")
            else:
                logger.warning("⚠️ Таблица channel не найдена!")
            
            # 7. Создаем таблицу login_history если её нет
            if 'login_history' not in tables:
                logger.info("\n📝 Создание таблицы login_history...")
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
                conn.commit()
                logger.info("✅ Таблица login_history создана")
            
            # 8. Создаем таблицу call если её нет
            if 'call' not in tables:
                logger.info("\n📝 Создание таблицы call...")
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS call (
                        id SERIAL PRIMARY KEY,
                        caller_id INTEGER REFERENCES "user"(id),
                        callee_id INTEGER REFERENCES "user"(id),
                        call_type VARCHAR(10) NOT NULL,
                        status VARCHAR(20) DEFAULT 'missed',
                        duration INTEGER DEFAULT 0,
                        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        ended_at TIMESTAMP
                    )
                """))
                conn.commit()
                logger.info("✅ Таблица call создана")
            
            # 9. Создаем таблицу report если её нет
            if 'report' not in tables:
                logger.info("\n📝 Создание таблицы report...")
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS report (
                        id SERIAL PRIMARY KEY,
                        reporter_id INTEGER REFERENCES "user"(id),
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
                logger.info("✅ Таблица report создана")
            
            # 10. Создаем индексы для производительности
            logger.info("\n📝 Создание индексов...")
            indexes = [
                ('idx_voice_message_receiver', 'voice_message', 'receiver_id'),
                ('idx_voice_message_sender', 'voice_message', 'sender_id'),
                ('idx_login_history_user', 'login_history', 'user_id'),
                ('idx_login_history_created', 'login_history', 'created_at'),
                ('idx_call_caller', 'call', 'caller_id'),
                ('idx_call_callee', 'call', 'callee_id'),
            ]
            
            for idx_name, table_name, column in indexes:
                if table_name in tables or table_name == 'voice_message':
                    try:
                        conn.execute(text(f'CREATE INDEX IF NOT EXISTS {idx_name} ON "{table_name}" ({column})'))
                        conn.commit()
                        logger.info(f"✅ Индекс {idx_name} создан")
                    except Exception as e:
                        logger.warning(f"⚠️ Не удалось создать индекс {idx_name}: {e}")
            
            # 11. Обновляем существующие записи
            logger.info("\n📝 Обновление данных...")
            try:
                conn.execute(text('UPDATE "user" SET is_admin = FALSE WHERE is_admin IS NULL'))
                conn.execute(text('UPDATE "user" SET is_online = FALSE WHERE is_online IS NULL'))
                conn.execute(text('UPDATE "user" SET two_factor_enabled = FALSE WHERE two_factor_enabled IS NULL'))
                conn.execute(text('UPDATE voice_message SET is_read = FALSE WHERE is_read IS NULL'))
                conn.commit()
                logger.info("✅ Данные обновлены")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при обновлении данных: {e}")
            
            logger.info("\n🎉 Миграция успешно завершена!")
            
    except Exception as e:
        logger.error(f"❌ Ошибка миграции: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("🔄 ПОЛНАЯ МИГРАЦИЯ БАЗЫ ДАННЫХ KILDEAR")
    print("=" * 70)
    main()
    print("=" * 70)
