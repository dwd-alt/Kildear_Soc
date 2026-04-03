import tkinter as tk
from tkinter import messagebox
import threading
import time
from PIL import Image, ImageTk
import webview  # pywebview - легкая альтернатива


# Установка: pip install pywebview pillow

class SplashWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)  # Убираем рамку

        # Размеры окна
        width, height = 400, 300
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.root.geometry(f'{width}x{height}+{x}+{y}')

        # Создаем canvas для градиента
        self.canvas = tk.Canvas(self.root, width=width, height=height, highlightthickness=0)
        self.canvas.pack()

        # Рисуем фиолетово-розовый градиент
        for i in range(height):
            # Вычисляем цвет для каждой строки
            ratio = i / height
            r = int(138 + (255 - 138) * ratio)  # от фиолетового к розовому
            g = int(43 + (105 - 43) * ratio)
            b = int(226 + (180 - 226) * ratio)
            color = f'#{r:02x}{g:02x}{b:02x}'
            self.canvas.create_line(0, i, width, i, fill=color)

        # Загружаем иконку
        try:
            img = Image.open("ico.png")
            img = img.resize((100, 100), Image.Resampling.LANCZOS)
            self.icon = ImageTk.PhotoImage(img)
            self.canvas.create_image(width // 2, height // 2, image=self.icon)
        except Exception as e:
            print(f"Иконка не загружена: {e}")
            # Если иконки нет, показываем текст
            self.canvas.create_text(width // 2, height // 2, text="🚀", font=("Arial", 50), fill="white")

        # Запускаем таймер на 3 секунды
        self.root.after(3000, self.open_main_window)
        self.root.mainloop()

    def open_main_window(self):
        self.root.destroy()
        # Открываем сайт в отдельном окне через webview
        webview.create_window("Мое приложение", "https://web.telegram.org", width=1200, height=800)
        webview.start()


if __name__ == "__main__":
    splash = SplashWindow()