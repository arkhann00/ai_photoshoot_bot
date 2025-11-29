# Используем официальный образ Python 3.13
FROM python:3.13-slim

# Не буферизуем вывод, чтобы логи сразу шли в docker logs
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Рабочая директория внутри контейнера
WORKDIR /app

# Устанавливаем системные зависимости (если понадобятся шрифты/ssl и т.п.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Копируем зависимости
COPY requirements.txt /app/requirements.txt

# Устанавливаем Python-зависимости
RUN pip install --no-cache-dir -r /app/requirements.txt

# Копируем исходники бота
COPY . /app

# По умолчанию БД (sqlite) будет лежать в /app/bot.db
# DATABASE_URL в .env должен выглядеть, например:
# DATABASE_URL=sqlite+aiosqlite:///./bot.db

# Стартуем бота
CMD ["python", "-m", "src.main"]
