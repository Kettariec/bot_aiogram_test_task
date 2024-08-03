import asyncio
import logging
import os
import sqlite3
from io import BytesIO

import requests
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from aiogram.utils.exceptions import MessageNotModified
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from PIL import Image

logging.basicConfig(level=logging.INFO)

load_dotenv()
API_TOKEN = os.getenv('API_TOKEN')
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)


def create_db():
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                age INTEGER NOT NULL
            )
        ''')
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logging.error(f"Ошибка при создании базы данных: {e}")


def add_user(user_id: int, name: str, age: int):
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (id, name, age)
            VALUES (?, ?, ?)
        ''', (user_id, name, age))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logging.error(f"Ошибка при добавлении пользователя в базу данных: {e}")


def get_all_users():
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, age FROM users')
        users = cursor.fetchall()
        conn.close()
        return users
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении "
                      f"пользователей из базы данных: {e}")
        return []


create_db()


class Form(StatesGroup):
    name = State()
    age = State()


class WeatherForm(StatesGroup):
    city = State()


class TimeoutMiddleware:
    def __init__(self):
        self.pending_requests = {}

    def add_request(self, user_id: int, task: asyncio.Task):
        self.pending_requests[user_id] = task

    def remove_request(self, user_id: int):
        if user_id in self.pending_requests:
            task = self.pending_requests.pop(user_id)
            task.cancel()

    async def check_timeout(self, user_id: int):
        await asyncio.sleep(900)
        if user_id in self.pending_requests:
            try:
                await bot.send_message(user_id, "Вы забыли ответить")
            except Exception as e:
                logging.error(f"Ошибка при отправке напоминания: {e}")


timeout_middleware = TimeoutMiddleware()


@dp.message_handler(commands=['start'], state='*')
async def cmd_start(message: types.Message):
    await Form.name.set()
    timeout_middleware.remove_request(message.from_user.id)
    await message.reply("Привет! Как тебя зовут?")

    task = asyncio.create_task(timeout_middleware.check_timeout
                               (message.from_user.id))
    timeout_middleware.add_request(message.from_user.id, task)


@dp.message_handler(state=Form.name)
async def process_name(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['name'] = message.text
    await Form.next()
    await message.reply("Сколько тебе лет?")

    timeout_middleware.remove_request(message.from_user.id)

    task = asyncio.create_task(timeout_middleware.check_timeout
                               (message.from_user.id))
    timeout_middleware.add_request(message.from_user.id, task)


@dp.message_handler(state=Form.age)
async def process_age(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['age'] = message.text

        try:
            age = int(data['age'])
            name = data['name']
            user_id = message.from_user.id

            add_user(user_id, name, age)

            if 10 <= age % 100 <= 20:
                age_text = "лет"
            else:
                last_digit = age % 10
                if last_digit == 1:
                    age_text = "год"
                elif 2 <= last_digit <= 4:
                    age_text = "года"
                else:
                    age_text = "лет"

            await message.reply(f"Приятно познакомиться, {name}!\n"
                                f"Тебе {age} {age_text}.")
        except ValueError:
            await message.reply("Пожалуйста, введи числовое "
                                "значение для возраста.")

    timeout_middleware.remove_request(message.from_user.id)
    await state.finish()


@dp.message_handler(commands=['users'])
async def list_users(message: types.Message):
    try:
        users = get_all_users()
        if not users:
            await message.reply("Нет зарегистрированных пользователей.")
        else:
            response = "Зарегистрированные пользователи:\n\n"
            for user in users:
                user_id, name, age = user
                response += f"ID: {user_id}, Имя: {name}, Возраст: {age}\n"
            await message.reply(response)
    except Exception as e:
        logging.error(f"Ошибка при обработке команды /users: {e}")
        await message.reply("Произошла ошибка при "
                            "получении списка пользователей.")


@dp.message_handler(commands=['help'])
async def send_help(message: types.Message):
    try:
        await message.reply("Доступные команды: /start, /help, /echo, "
                            "/photo, /menu, /users, /weather")
    except Exception as e:
        logging.error(f"Ошибка при обработке команды /help: {e}")
        await message.reply("Произошла ошибка при выполнении команды /help.")


@dp.message_handler(commands=['echo'])
async def echo_message(message: types.Message):
    try:
        args = message.get_args()
        if not args:
            await message.reply("Вы не ввели сообщение для эхо.")
        else:
            await message.reply(args)
    except Exception as e:
        logging.error(f"Ошибка при обработке команды /echo: {e}")
        await message.reply("Произошла ошибка при выполнении команды /echo.")


@dp.message_handler(commands=['menu'])
async def show_menu(message: types.Message):
    try:
        keyboard = InlineKeyboardMarkup()
        buttons = [
            InlineKeyboardButton("Выбор 1", callback_data='choice_1'),
            InlineKeyboardButton("Выбор 2", callback_data='choice_2')
        ]
        keyboard.add(*buttons)
        await message.reply("Сделайте выбор:", reply_markup=keyboard)
    except Exception as e:
        logging.error(f"Ошибка при обработке команды /menu: {e}")
        await message.reply("Произошла ошибка при выполнении команды /menu.")


@dp.message_handler(content_types=types.ContentTypes.PHOTO)
async def handle_photo(message: types.Message):
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_path = file.file_path
        file_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{file_path}"

        async with await bot.get_session() as session:
            async with session.get(file_url) as response:
                response.raise_for_status()
                img_bytes = await response.read()

        with Image.open(BytesIO(img_bytes)) as img:
            width, height = img.size
            await message.reply(f"Размер изображения: "
                                f"{width}x{height} пикселей.")
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при запросе изображения: {e}")
        await message.reply("Произошла ошибка при получении "
                            "изображения. Попробуйте еще раз.")
    except Exception as e:
        logging.error(f"Ошибка при обработке изображения: {e}")
        await message.reply("Произошла ошибка при обработке "
                            "изображения. Попробуйте еще раз.")


@dp.message_handler(commands=['weather'], state='*')
async def cmd_weather(message: types.Message):
    await WeatherForm.city.set()
    await message.reply("Пожалуйста, введите название города:")


@dp.message_handler(state=WeatherForm.city)
async def process_city(message: types.Message, state: FSMContext):
    city_name = message.text
    await state.finish()

    geocode_url = f"https://nominatim.openstreetmap.org/search?format=json&q={city_name}"

    try:
        response = requests.get(geocode_url)
        response.raise_for_status()
        geocode_data = response.json()

        if not geocode_data:
            await message.reply("Не удалось найти город. Попробуйте еще раз.")
            return

        location = geocode_data[0]
        lat = location['lat']
        lon = location['lon']

        weather_url = (f"https://api.open-meteo.com/v1/forecast?latitude="
                       f"{lat}&longitude={lon}&current_weather=true&hourly=temperature_2m,"
                       "relative_humidity_2m,windspeed_10m,weathercode")
        weather_response = requests.get(weather_url)
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        current_weather = weather_data.get('current_weather')
        hourly_data = weather_data.get('hourly', {})

        if current_weather and hourly_data:
            temperature = current_weather.get('temperature')
            windspeed = current_weather.get('windspeed')
            weathercode = current_weather.get('weathercode')

            humidity_data = hourly_data.get('relative_humidity_2m', [])
            if humidity_data:
                humidity = humidity_data[0]
            else:
                humidity = "неизвестно"

            weather_descriptions = {
                0: "Ясно",
                1: "Маленькие облака",
                2: "Облачно",
                3: "Дождь",
                4: "Снег",
                5: "Гроза",
                6: "Туман",
                7: "Дождь со снегом",
                8: "Снег с дождем"
            }
            weather_description = weather_descriptions.get(weathercode, "Неизвестно")

            response_message = (
                f"Погода в городе {city_name}:\n"
                f"Температура: {temperature}°C\n"
                f"Скорость ветра: {windspeed} м/с\n"
                f"Влажность: {humidity}%\n"
                f"Состояние погоды: {weather_description}"
            )
            await message.reply(response_message)
        else:
            await message.reply("Не удалось получить данные о погоде. Попробуйте позже.")

    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при запросе: {e}")
        await message.reply("Произошла ошибка при получении данных. Попробуйте позже.")
    except ValueError:
        await message.reply("Не удалось обработать ответ сервера. Попробуйте еще раз.")


@dp.callback_query_handler(Text(startswith='choice_'))
async def process_callback(callback_query: types.CallbackQuery):
    try:
        choice = callback_query.data
        if choice == 'choice_1':
            await bot.answer_callback_query(callback_query.id,
                                            text="Вы выбрали Выбор 1")
            await bot.send_message(callback_query.from_user.id,
                                   "Вы выбрали Выбор 1")
        elif choice == 'choice_2':
            await bot.answer_callback_query(callback_query.id,
                                            text="Вы выбрали Выбор 2")
            await bot.send_message(callback_query.from_user.id,
                                   "Вы выбрали Выбор 2")
    except MessageNotModified:
        pass
    except Exception as e:
        logging.error(f"Ошибка при обработке callback: {e}")
        await bot.send_message(callback_query.from_user.id,
                               "Произошла ошибка, попробуйте позже.")


async def send_daily_notification():
    user_chat_ids = {user[0] for user in get_all_users()}
    for chat_id in user_chat_ids:
        try:
            await bot.send_message(chat_id,
                                   "Не забудьте проверить уведомления!")
        except Exception as e:
            logging.error(f"Ошибка при отправке "
                          f"сообщения пользователю {chat_id}: {e}")


scheduler = AsyncIOScheduler()
scheduler.add_job(send_daily_notification, CronTrigger(hour=9, minute=0))
scheduler.start()


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
