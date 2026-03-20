#!/usr/bin/env python3
"""
Скрипт для очистки app.py от кода миграции
Запуск: python3 clean_app.py
"""

import re

def clean_app_file():
    """Удаляет блок миграции из app.py"""
    
    try:
        # Читаем файл
        with open('app.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Проверяем, есть ли блок миграции в файле
        if 'response = input("\\nПродолжить? (y/n): ")' in content:
            print("🔍 Найден блок миграции в app.py")
            
            # Находим и удаляем блок с миграцией
            # Ищем от "🔄 МИГРАЦИЯ БАЗЫ ДАННЫХ" до конца миграции
            pattern = r'print\("\\n" \+ "="\*70\)\s*print\("🔄 МИГРАЦИЯ БАЗЫ ДАННЫХ KILDEAR SOCIAL NETWORK"\)\s*print\("="\*70\)\s*print\("Этот скрипт изменит типы полей на TEXT и добавит новые колонки"\)\s*print\("для хранения Base64 изображений\.?"\)\s*print\("="\*70\)\s*response = input\("\\nПродолжить\? \(y/n\): "\)\s*if response\.lower\(\) \!= \'y\':\s*print\("Миграция отменена\."\)\s*sys\.exit\(0\)\s*main\(\)\s*print\("="\*70\)'
            
            # Удаляем блок
            content = re.sub(pattern, '', content, flags=re.DOTALL)
            
            # Альтернативный вариант: удаляем конкретные строки
            lines = content.split('\n')
            new_lines = []
            skip = False
            skip_count = 0
            
            for line in lines:
                if 'response = input' in line and 'Продолжить?' in line:
                    skip = True
                    skip_count = 0
                    continue
                
                if skip:
                    skip_count += 1
                    if skip_count > 10:  # Пропускаем 10 строк после input
                        skip = False
                    continue
                
                new_lines.append(line)
            
            content = '\n'.join(new_lines)
            
            # Записываем очищенный файл
            with open('app_clean.py', 'w', encoding='utf-8') as f:
                f.write(content)
            
            print("✅ Создан файл app_clean.py без блока миграции")
            print("📝 Чтобы заменить исходный файл, выполните:")
            print("   mv app_clean.py app.py")
            
        else:
            print("✅ Блок миграции не найден в app.py")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    clean_app_file()
