import os
import logging
import json
import random
import re
import datetime
from typing import Dict, List, Tuple
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получение токена
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# Состояния разговора
GOAL, CURRENT_LEVEL, TARGET_LEVEL, CONVERSATION_MODE, EXERCISE_MODE, WRITING_MODE = range(6)

# Глобальное хранилище данных
user_data = {}
vocabulary = {}
user_progress = {}
exercise_history = {}  # История выполненных упражнений

# Уровни английского
LEVELS = ["A1 (Начальный)", "A2 (Элементарный)", "B1 (Средний)", "B2 (Выше среднего)", "C1 (Продвинутый)", "C2 (Профессиональный)"]

# Расширенная база упражнений по темам и типам
EXERCISE_DATABASE = {
    "A1": {
        "grammar": [
            {
                "type": "verb_to_be",
                "question": "Выберите правильную форму: I ___ a student.",
                "answer": "am",
                "options": ["am", "is", "are"],
                "explanation": "С местоимением 'I' используется 'am'"
            },
            {
                "type": "articles", 
                "question": "Выберите правильный артикль: This is ___ apple.",
                "answer": "an",
                "options": ["a", "an", "the"],
                "explanation": "Перед словами, начинающимися с гласной, используется 'an'"
            },
            {
                "type": "pronouns",
                "question": "Выберите правильное местоимение: ___ is my friend.",
                "answer": "He",
                "options": ["He", "She", "It"],
                "explanation": "'He' используется для мужского рода"
            }
        ],
        "vocabulary": [
            {
                "type": "family",
                "question": "Переведите: мать",
                "answer": "mother",
                "options": ["father", "mother", "sister"],
                "explanation": "Mother - мать"
            },
            {
                "type": "colors",
                "question": "Какой цвет у травы?",
                "answer": "green",
                "options": ["red", "blue", "green"],
                "explanation": "Green - зеленый"
            }
        ],
        "sentence_building": [
            {
                "type": "word_order",
                "question": "Составьте предложение из слов: like / I / music",
                "answer": "I like music",
                "explanation": "Порядок слов: Подлежащее + сказуемое + дополнение"
            }
        ]
    },
    "A2": {
        "grammar": [
            {
                "type": "present_simple",
                "question": "Выберите правильную форму: She ___ to school every day.",
                "answer": "goes",
                "options": ["go", "goes", "going"],
                "explanation": "С he/she/it добавляется -s"
            },
            {
                "type": "past_simple",
                "question": "Выберите правильную форму: Yesterday I ___ to the park.",
                "answer": "went",
                "options": ["go", "went", "gone"],
                "explanation": "Went - прошедшая форма от go"
            },
            {
                "type": "prepositions",
                "question": "Выберите правильный предлог: I'm good ___ English.",
                "answer": "at",
                "options": ["in", "at", "on"],
                "explanation": "Good at - хорош в чем-то"
            }
        ],
        "vocabulary": [
            {
                "type": "weather",
                "question": "Как называется погода, когда светит солнце?",
                "answer": "sunny",
                "options": ["rainy", "sunny", "cloudy"],
                "explanation": "Sunny - солнечно"
            },
            {
                "type": "food",
                "question": "Что вы едите на завтрак? Выберите вариант:",
                "answer": "eggs",
                "options": ["pizza", "eggs", "soup"],
                "explanation": "Eggs - яйца, типичный завтрак"
            }
        ],
        "reading": [
            {
                "type": "comprehension",
                "question": "Прочитайте: 'Tom gets up at 7 am. He eats breakfast and goes to work.' Во сколько Том встает?",
                "answer": "7 am",
                "options": ["6 am", "7 am", "8 am"],
                "explanation": "В тексте сказано: gets up at 7 am"
            }
        ]
    },
    "B1": {
        "grammar": [
            {
                "type": "present_perfect",
                "question": "Выберите правильную форму: I ___ never been to London.",
                "answer": "have",
                "options": ["have", "has", "had"],
                "explanation": "I have never been - я никогда не был"
            },
            {
                "type": "conditionals",
                "question": "Выберите правильный вариант: If it rains, I ___ at home.",
                "answer": "will stay",
                "options": ["stay", "stayed", "will stay"],
                "explanation": "Первое условное: if + present, will + infinitive"
            },
            {
                "type": "passive",
                "question": "Выберите пассивную форму: The book ___ by millions.",
                "answer": "is read",
                "options": ["reads", "is read", "read"],
                "explanation": "Passive: be + past participle"
            }
        ],
        "vocabulary": [
            {
                "type": "work",
                "question": "Что означает 'deadline'?",
                "answer": "крайний срок",
                "options": ["отпуск", "крайний срок", "встреча"],
                "explanation": "Deadline - крайний срок выполнения работы"
            },
            {
                "type": "technology",
                "question": "Что вы используете для хранения файлов в интернете?",
                "answer": "cloud storage",
                "options": ["cloud storage", "hard disk", "USB"],
                "explanation": "Cloud storage - облачное хранилище"
            }
        ],
        "phrasal_verbs": [
            {
                "type": "common_phrasals",
                "question": "Что означает 'give up'?",
                "answer": "сдаваться",
                "options": ["продолжать", "сдаваться", "начинать"],
                "explanation": "Give up - сдаваться, прекращать попытки"
            }
        ]
    },
    "B2": {
        "grammar": [
            {
                "type": "reported_speech",
                "question": "Перефразируйте: 'I will come tomorrow.' He said that...",
                "answer": "he would come the next day",
                "options": ["he will come tomorrow", "he would come the next day", "he comes tomorrow"],
                "explanation": "Will становится would, tomorrow становится the next day"
            },
            {
                "type": "relative_clauses",
                "question": "Выберите правильный вариант: The person ___ called me is my boss.",
                "answer": "who",
                "options": ["who", "which", "where"],
                "explanation": "Who используется для людей"
            }
        ],
        "vocabulary": [
            {
                "type": "business",
                "question": "Что означает 'to negotiate'?",
                "answer": "вести переговоры",
                "options": ["подписывать", "вести переговоры", "отказывать"],
                "explanation": "Negotiate - вести переговоры"
            }
        ],
        "idioms": [
            {
                "type": "common_idioms",
                "question": "Что означает 'break the ice'?",
                "answer": "начать разговор",
                "options": ["уйти", "начать разговор", "рассердиться"],
                "explanation": "Break the ice - начать разговор в незнакомой компании"
            }
        ]
    }
}

# Тематические наборы упражнений
THEMATIC_EXERCISES = {
    "travel": [
        "Составьте диалог в аэропорту",
        "Переведите: 'Где находится ближайшая гостиница?'",
        "Что вы возьмете в путешествие? Напишите список",
        "Опишите ваше лучшее путешествие"
    ],
    "food": [
        "Опишите ваш любимый рецепт",
        "Составьте заказ в ресторане", 
        "Переведите названия 5 овощей",
        "Обсудите диетические предпочтения"
    ],
    "work": [
        "Составьте email коллеге",
        "Опишите вашу профессию",
        "Подготовьтесь к собеседованию",
        "Обсудите рабочий проект"
    ],
    "hobbies": [
        "Опишите ваше хобби",
        "Расскажите о любимом виде спорта", 
        "Обсудите последний прочитанный фильм",
        "Поделитесь музыкальными предпочтениями"
    ]
}

# Топики для разговорной практики  
CONVERSATION_TOPICS = {
    "A1": ["Семья", "Еда", "Дом", "Повседневные дела", "Хобби"],
    "A2": ["Путешествия", "Погода", "Покупки", "Работа", "Отдых"],
    "B1": ["Технологии", "Здоровье", "Образование", "Культура", "Социальные сети"],
    "B2": ["Экология", "Бизнес", "Наука", "Искусство", "Глобальные проблемы"]
}

def get_user_level(user_id: int) -> str:
    """Получить уровень пользователя"""
    return user_data.get(user_id, {}).get('current_level', 'A2 (Элементарный)')

def get_level_key(level: str) -> str:
    """Получить ключ уровня (A1, A2, etc)"""
    return level.split()[0]

def add_to_vocabulary(user_id: int, word: str):
    """Добавить слово в словарь пользователя"""
    if user_id not in vocabulary:
        vocabulary[user_id] = set()
    vocabulary[user_id].add(word.lower())

def update_progress(user_id: int, exercise_type: str, correct: bool = True):
    """Обновить прогресс пользователя"""
    if user_id not in user_progress:
        user_progress[user_id] = {
            'total_exercises': 0,
            'correct_answers': 0,
            'last_activity': datetime.datetime.now().isoformat(),
            'exercise_types': {},
            'themes': {},
            'accuracy_by_type': {}
        }
    
    user_progress[user_id]['total_exercises'] += 1
    user_progress[user_id]['last_activity'] = datetime.datetime.now().isoformat()
    
    if correct:
        user_progress[user_id]['correct_answers'] += 1
    
    # Обновляем статистику по типам упражнений
    if exercise_type not in user_progress[user_id]['exercise_types']:
        user_progress[user_id]['exercise_types'][exercise_type] = 0
    user_progress[user_id]['exercise_types'][exercise_type] += 1

def get_available_exercises(user_id: int) -> List[Dict]:
    """Получить доступные упражнения для пользователя, исключая недавно использованные"""
    level_key = get_level_key(get_user_level(user_id))
    if user_id not in exercise_history:
        exercise_history[user_id] = []
    
    # Получаем все упражнения для уровня
    all_exercises = []
    for category, exercises in EXERCISE_DATABASE.get(level_key, EXERCISE_DATABASE["A2"]).items():
        for exercise in exercises:
            exercise['category'] = category
            all_exercises.append(exercise)
    
    # Исключаем недавно использованные (последние 10)
    recent_ids = [ex.get('id', '') for ex in exercise_history[user_id][-10:]]
    available = [ex for ex in all_exercises if ex.get('type') not in recent_ids]
    
    # Если все упражнения использовались, сбрасываем историю
    if not available:
        exercise_history[user_id] = []
        available = all_exercises
    
    return available

def add_to_exercise_history(user_id: int, exercise: Dict):
    """Добавить упражнение в историю"""
    if user_id not in exercise_history:
        exercise_history[user_id] = []
    
    # Сохраняем только тип упражнения для простоты
    exercise_history[user_id].append({'type': exercise.get('type'), 'timestamp': datetime.datetime.now().isoformat()})
    
    # Ограничиваем историю 15 записями
    if len(exercise_history[user_id]) > 15:
        exercise_history[user_id] = exercise_history[user_id][-15:]

def generate_writing_task(level: str, theme: str = None) -> Dict:
    """Сгенерировать письменное задание"""
    themes = theme or random.choice(list(THEMATIC_EXERCISES.keys()))
    level_key = get_level_key(level)
    
    writing_tasks = {
        "A1": [
            f"Опишите ваш распорядок дня ({themes})",
            f"Напишите 5 предложений о вашей семье ({themes})",
            f"Опишите ваш любимый предмет в доме ({themes})"
        ],
        "A2": [
            f"Напишите email другу о ваших планах на выходные ({themes})",
            f"Опишите ваше последнее путешествие ({themes})", 
            f"Напишите отзыв о фильме или книге ({themes})"
        ],
        "B1": [
            f"Напишите эссе о преимуществах изучения английского ({themes})",
            f"Опишите профессиональные цели на ближайший год ({themes})",
            f"Напишите статью о проблемах окружающей среды ({themes})"
        ],
        "B2": [
            f"Напишите аналитический обзор текущих событий ({themes})",
            f"Создайте бизнес-предложение ({themes})",
            f"Напишите критический анализ произведения искусства ({themes})"
        ]
    }
    
    task = random.choice(writing_tasks.get(level_key, writing_tasks["A2"]))
    return {
        "type": "writing",
        "question": task,
        "min_words": 50 if level_key in ["A1", "A2"] else 100,
        "category": "writing",
        "theme": themes
    }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало работы с ботом"""
    welcome_text = """
👋 Добро пожаловать в English Tutor Bot!

Я помогу вам изучать английский язык через:
• 📚 Разнообразные упражнения (грамматика, словарный запас, чтение)
• 💬 Тематические диалоги  
• ✍️ Письменные задания
• 📊 Детальную статистику прогресса
• 🎯 Персональные рекомендации

Давайте начнем! Какова ваша цель изучения английского?
"""
    
    keyboard = [
        ["🗣️ Разговорная практика"],
        ["📖 Чтение и понимание"],
        ["✍️ Письмо и грамматика"],
        ["🎯 Общее улучшение"],
        ["💼 Бизнес английский"],
        ["✈️ Английский для путешествий"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    return GOAL

async def set_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка цели обучения"""
    user = update.message.from_user
    user_id = user.id
    
    if user_id not in user_data:
        user_data[user_id] = {}
    
    user_data[user_id]['goal'] = update.message.text
    user_data[user_id]['preferred_themes'] = []
    
    await update.message.reply_text(
        f"🎯 Отлично! Ваша цель: {update.message.text}\n\n"
        "Какой у вас текущий уровень английского?",
        reply_markup=ReplyKeyboardMarkup([
            LEVELS[:2],
            LEVELS[2:4], 
            LEVELS[4:]
        ], resize_keyboard=True)
    )
    return CURRENT_LEVEL

async def set_current_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка текущего уровня"""
    user = update.message.from_user
    user_id = user.id
    
    user_data[user_id]['current_level'] = update.message.text
    
    await update.message.reply_text(
        f"📚 Текущий уровень: {update.message.text}\n\n"
        "Какой уровень вы хотите достичь?",
        reply_markup=ReplyKeyboardMarkup([
            LEVELS[:2],
            LEVELS[2:4],
            LEVELS[4:]
        ], resize_keyboard=True)
    )
    return TARGET_LEVEL

async def set_target_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка целевого уровня и завершение настройки"""
    user = update.message.from_user
    user_id = user.id
    
    user_data[user_id]['target_level'] = update.message.text
    
    # Создаем персональный план
    plan = generate_study_plan(user_id)
    user_data[user_id]['plan'] = plan
    
    await update.message.reply_text(
        f"🎉 Настройка завершена!\n\n"
        f"📊 Ваш профиль:\n"
        f"• Цель: {user_data[user_id]['goal']}\n"
        f"• Текущий уровень: {user_data[user_id]['current_level']}\n"
        f"• Целевой уровень: {user_data[user_id]['target_level']}\n\n"
        f"📝 Рекомендации:\n{plan}",
        reply_markup=ReplyKeyboardMarkup([
            ["📚 Упражнения", "💬 Диалоги"],
            ["✍️ Письмо", "📊 Прогресс"],
            ["📖 Словарь", "🆘 Помощь"]
        ], resize_keyboard=True)
    )
    return ConversationHandler.END

def generate_study_plan(user_id: int) -> str:
    """Генерация персонального плана обучения"""
    data = user_data[user_id]
    current = get_level_key(data['current_level'])
    target = get_level_key(data['target_level'])
    goal = data['goal']
    
    plans = {
        "A1": "• Учите базовые фразы и слова (500+ слов)\n• Практикуйте Present Simple\n• Составляйте короткие предложения\n• Слушайте простые диалоги",
        "A2": "• Расширяйте словарный запас (1000+ слов)\n• Изучайте Past Simple и Future Simple\n• Тренируйтесь в диалогах на бытовые темы\n• Читайте адаптированные тексты", 
        "B1": "• Развивайте разговорные навыки\n• Изучайте Present Perfect и Conditionals\n• Практикуйте письмо (эссе, emails)\n• Смотрите фильмы с субтитрами",
        "B2": "• Совершенствуйте грамматику\n• Учите идиомы и фразовые глаголы\n• Готовьте презентации на английском\n• Читайте оригинальную литературу"
    }
    
    focus_areas = {
        "🗣️ Разговорная практика": "Уделите больше времени диалогам и произношению",
        "📖 Чтение и понимание": "Читайте разнообразные тексты каждый день", 
        "✍️ Письмо и грамматика": "Практикуйте письменные задания и грамматику",
        "💼 Бизнес английский": "Изучайте бизнес-лексику и деловую переписку",
        "✈️ Английский для путешествий": "Учите фразы для путешествий и диалоги"
    }
    
    base_plan = plans.get(current, "• Занимайтесь регулярно\n• Практикуйте все аспекты языка\n• Не бойтесь ошибок")
    focus = focus_areas.get(goal, "• Сбалансированно развивайте все навыки")
    
    return f"{base_plan}\n\n🎯 Особое внимание:\n{focus}"

async def start_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать упражнение"""
    user_id = update.message.from_user.id
    
    if user_id not in user_data:
        await update.message.reply_text("Пожалуйста, сначала завершите настройку с помощью /start")
        return
    
    # Выбираем случайное упражнение из доступных
    available_exercises = get_available_exercises(user_id)
    if not available_exercises:
        await update.message.reply_text("Поздравляем! Вы выполнили все доступные упражнения! 🎉")
        return
    
    exercise = random.choice(available_exercises)
    
    # Сохраняем текущее упражнение в контексте
    context.user_data['current_exercise'] = exercise
    context.user_data['exercise_start_time'] = datetime.datetime.now().isoformat()
    
    # Формируем сообщение с упражнением
    message = f"📚 **{exercise['category'].upper()} упражнение**\n\n{exercise['question']}"
    
    if 'options' in exercise:
        keyboard = [[opt] for opt in exercise['options']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=ReplyKeyboardRemove())
    
    # Добавляем в историю
    add_to_exercise_history(user_id, exercise)
    
    return EXERCISE_MODE

async def check_exercise_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить ответ на упражнение"""
    user_id = update.message.from_user.id
    user_answer = update.message.text.strip()
    
    if 'current_exercise' not in context.user_data:
        await update.message.reply_text("Пожалуйста, начните упражнение с помощью /exercise")
        return ConversationHandler.END
    
    exercise = context.user_data['current_exercise']
    is_correct = user_answer.lower() == exercise['answer'].lower()
    
    # Обновляем прогресс
    update_progress(user_id, exercise['type'], is_correct)
    
    # Формируем ответ с объяснением
    if is_correct:
        feedback = f"✅ **Правильно!**\n\n"
    else:
        feedback = f"❌ **Пока не совсем верно.**\n\n"
    
    if 'explanation' in exercise:
        feedback += f"💡 {exercise['explanation']}\n\n"
    
    feedback += f"Правильный ответ: **{exercise['answer']}**"
    
    await update.message.reply_text(
        feedback,
        reply_markup=ReplyKeyboardMarkup([
            ["📚 Следующее упражнение", "💬 Диалог"],
            ["✍️ Письменное задание", "📊 Прогресс"],
            ["🏠 Главное меню"]
        ], resize_keyboard=True)
    )
    
    # Очищаем текущее упражнение
    context.user_data.pop('current_exercise', None)
    
    return ConversationHandler.END

async def start_writing_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать письменное задание"""
    user_id = update.message.from_user.id
    
    if user_id not in user_data:
        await update.message.reply_text("Пожалуйста, сначала завершите настройку с помощью /start")
        return
    
    level = get_user_level(user_id)
    theme = random.choice(list(THEMATIC_EXERCISES.keys()))
    
    writing_task = generate_writing_task(level, theme)
    context.user_data['current_writing'] = writing_task
    
    await update.message.reply_text(
        f"✍️ **Письменное задание**\n\n"
        f"Тема: {writing_task['theme']}\n\n"
        f"{writing_task['question']}\n\n"
        f"💡 Минимум {writing_task['min_words']} слов\n"
        f"Напишите ваш текст:",
        reply_markup=ReplyKeyboardRemove()
    )
    
    return WRITING_MODE

async def check_writing_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить письменное задание"""
    user_id = update.message.from_user.id
    user_text = update.message.text
    
    if 'current_writing' not in context.user_data:
        await update.message.reply_text("Пожалуйста, начните письменное задание с помощью /writing")
        return ConversationHandler.END
    
    writing_task = context.user_data['current_writing']
    
    # Анализируем текст
    word_count = len(user_text.split())
    sentence_count = len(re.findall(r'[.!?]+', user_text))
    unique_words = len(set(re.findall(r'\b[a-zA-Z]+\b', user_text.lower())))
    
    # Добавляем слова в словарь
    words = re.findall(r'\b[a-zA-Z]+\b', user_text)
    for word in words:
        if len(word) > 3:
            add_to_vocabulary(user_id, word)
    
    # Формируем обратную связь
    feedback = f"✍️ **Анализ вашего текста:**\n\n"
    feedback += f"📊 Статистика:\n"
    feedback += f"• Слов: {word_count} (минимум {writing_task['min_words']})\n"
    feedback += f"• Предложений: {sentence_count}\n"
    feedback += f"• Уникальных слов: {unique_words}\n\n"
    
    if word_count < writing_task['min_words']:
        feedback += "❌ Текст слишком короткий. Попробуйте добавить больше деталей.\n\n"
    else:
        feedback += "✅ Отличная длина текста!\n\n"
    
    if sentence_count < 3:
        feedback += "💡 Совет: Используйте больше предложений для лучшей структуры.\n"
    else:
        feedback += "💡 Хорошая структура текста!\n"
    
    # Обновляем прогресс
    update_progress(user_id, "writing", word_count >= writing_task['min_words'])
    
    await update.message.reply_text(
        feedback,
        reply_markup=ReplyKeyboardMarkup([
            ["✍️ Новое письмо", "📚 Упражнения"],
            ["💬 Диалоги", "📊 Прогресс"],
            ["🏠 Главное меню"]
        ], resize_keyboard=True)
    )
    
    context.user_data.pop('current_writing', None)
    return ConversationHandler.END

async def start_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать разговорную практику"""
    user_id = update.message.from_user.id
    
    if user_id not in user_data:
        await update.message.reply_text("Пожалуйста, сначала завершите настройку с помощью /start")
        return
    
    level_key = get_level_key(get_user_level(user_id))
    topics = CONVERSATION_TOPICS.get(level_key, CONVERSATION_TOPICS["A2"])
    topic = random.choice(topics)
    
    # Генерируем стартовый вопрос в зависимости от уровня
    questions = {
        "A1": [
            f"What do you like about {topic.lower()}?",
            f"Do you have {topic.lower()} in your family?",
            f"What is your favorite {topic.lower()}?"
        ],
        "A2": [
            f"How often do you {topic.lower()}?",
            f"What did you do last time you {topic.lower()}ed?",
            f"Do you prefer {topic.lower()} alone or with friends?"
        ],
        "B1": [
            f"What are the advantages and disadvantages of {topic.lower()}?",
            f"How has {topic.lower()} changed in recent years?",
            f"What role does {topic.lower()} play in your life?"
        ],
        "B2": [
            f"How does {topic.lower()} impact society today?",
            f"What are the ethical considerations around {topic.lower()}?",
            f"How do you see the future of {topic.lower()}?"
        ]
    }
    
    question = random.choice(questions.get(level_key, questions["A2"]))
    
    context.user_data['conversation_topic'] = topic
    context.user_data['conversation_start'] = datetime.datetime.now().isoformat()
    context.user_data['conversation_messages'] = 0
    
    await update.message.reply_text(
        f"💬 **Разговорная практика**\n\n"
        f"Тема: {topic}\n\n"
        f"{question}\n\n"
        "Ответьте на вопрос на английском:",
        reply_markup=ReplyKeyboardMarkup([
            ["🔚 Завершить диалог", "🔄 Новая тема"],
            ["📚 Упражнения", "🏠 Главное меню"]
        ], resize_keyboard=True)
    )
    
    return CONVERSATION_MODE

async def handle_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка разговорной практики"""
    user_id = update.message.from_user.id
    user_message = update.message.text
    
    if user_message == "🔚 Завершить диалог":
        # Подводим итоги диалога
        start_time = context.user_data.get('conversation_start')
        messages = context.user_data.get('conversation_messages', 0)
        duration = "несколько минут"
        
        if start_time:
            start_dt = datetime.datetime.fromisoformat(start_time)
            duration_min = (datetime.datetime.now() - start_dt).seconds // 60
            duration = f"{duration_min} минут"
        
        await update.message.reply_text(
            f"🎉 Отличная разговорная практика!\n\n"
            f"💬 Вы практиковали: {duration}\n"
            f"📝 Сообщений: {messages}\n"
            f"📚 Новые слова добавлены в словарь\n"
            f"💪 Продолжайте в том же духе!",
            reply_markup=ReplyKeyboardMarkup([
                ["📚 Упражнения", "💬 Новая практика"],
                ["✍️ Письмо", "📊 Прогресс"],
                ["🏠 Главное меню"]
            ], resize_keyboard=True)
        )
        return ConversationHandler.END
        
    elif user_message == "🔄 Новая тема":
        return await start_conversation(update, context)
    
    elif user_message in ["📚 Упражнения", "🏠 Главное меню"]:
        return await handle_main_navigation(update, context)
    
    else:
        # Анализируем ответ пользователя
        context.user_data['conversation_messages'] = context.user_data.get('conversation_messages', 0) + 1
        
        words = re.findall(r'\b[a-zA-Z]+\b', user_message)
        for word in words:
            if len(word) > 3:
                add_to_vocabulary(user_id, word)
        
        # Простая обратная связь
        word_count = len(user_message.split())
        topic = context.user_data.get('conversation_topic', 'general')
        
        follow_up_questions = {
            "A1": ["Can you tell me more?", "Why do you like it?", "What else?"],
            "A2": ["Can you give an example?", "How did you feel?", "What happened next?"],
            "B1": ["What are your reasons for that?", "How does this compare to...?", "What are the implications?"],
            "B2": ["What evidence supports your view?", "How might others disagree?", "What are the long-term consequences?"]
        }
        
        level_key = get_level_key(get_user_level(user_id))
        next_question = random.choice(follow_up_questions.get(level_key, follow_up_questions["A2"]))
        
        feedback = "💬 "
        if word_count < 5:
            feedback += "Good start! "
        elif word_count < 10:
            feedback += "Nice answer! "
        else:
            feedback += "Excellent detailed response! "
        
        feedback += f"Let me ask you another question about {topic.lower()}:\n\n{next_question}"
        
        await update.message.reply_text(
            feedback,
            reply_markup=ReplyKeyboardMarkup([
                ["🔚 Завершить диалог", "🔄 Новая тема"],
                ["📚 Упражнения", "🏠 Главное меню"]
            ], resize_keyboard=True)
        )
        
        return CONVERSATION_MODE

async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать детальный прогресс пользователя"""
    user_id = update.message.from_user.id
    
    if user_id not in user_progress:
        await update.message.reply_text("📊 У вас пока нет данных о прогрессе. Начните выполнять упражнения!")
        return
    
    progress = user_progress[user_id]
    total = progress['total_exercises']
    correct = progress['correct_answers']
    accuracy = (correct / total * 100) if total > 0 else 0
    
    # Статистика по типам упражнений
    exercise_stats = ""
    for ex_type, count in progress.get('exercise_types', {}).items():
        exercise_stats += f"• {ex_type}: {count} раз\n"
    
    # Размер словаря
    vocab_size = len(vocabulary.get(user_id, set()))
    
    # Активность
    last_active = progress.get('last_activity')
    if last_active:
        last_dt = datetime.datetime.fromisoformat(last_active)
        days_ago = (datetime.datetime.now() - last_dt).days
        activity = f"{days_ago} дней назад" if days_ago > 0 else "сегодня"
    else:
        activity = "недавно"
    
    progress_text = f"""
📊 **Детальная статистика:**

🎯 Общий прогресс:
✅ Выполнено упражнений: {total}
🎯 Правильных ответов: {correct} ({accuracy:.1f}%)
📚 Размер словаря: {vocab_size} слов
📅 Последняя активность: {activity}

📈 По типам упражнений:
{exercise_stats if exercise_stats else "• Пока нет данных"}

💡 Рекомендации:
{get_recommendations(user_id)}
"""
    
    await update.message.reply_text(progress_text)

def get_recommendations(user_id: int) -> str:
    """Получить персонализированные рекомендации"""
    if user_id not in user_progress:
        return "Начните с базовых упражнений для вашего уровня."
    
    progress = user_progress[user_id]
    level = get_user_level(user_id)
    level_key = get_level_key(level)
    
    # Анализируем слабые места
    exercise_types = progress.get('exercise_types', {})
    
    if not exercise_types:
        return "Попробуйте разные типы упражнений для сбалансированного развития."
    
    # Находим наименее практикуемые типы
    if len(exercise_types) < 3:
        return "Попробуйте больше разнообразных упражнений!"
    
    least_practiced = min(exercise_types.items(), key=lambda x: x[1])
    
    recommendations = {
        "grammar": "Уделите больше внимания грамматическим упражнениям.",
        "vocabulary": "Пополняйте словарный запас с помощью новых слов.",
        "writing": "Практикуйте письменные задания для улучшения письма.",
        "reading": "Читайте больше текстов для улучшения понимания."
    }
    
    return recommendations.get(least_practiced[0], "Продолжайте практиковать все аспекты языка!")

async def show_vocabulary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать словарь пользователя с сортировкой"""
    user_id = update.message.from_user.id
    
    if user_id not in vocabulary or not vocabulary[user_id]:
        await update.message.reply_text("📖 Ваш словарь пуст. Начните общаться или выполнять упражнения, чтобы добавлять слова!")
        return
    
    words = sorted(list(vocabulary[user_id]))
    
    # Группируем слова по первой букве
    vocab_text = f"📖 **Ваш словарь ({len(words)} слов):**\n\n"
    
    current_letter = ""
    for word in words[:80]:  # Показываем максимум 80 слов
        first_letter = word[0].upper()
        if first_letter != current_letter:
            vocab_text += f"**{first_letter}**\n"
            current_letter = first_letter
        vocab_text += f"• {word}\n"
    
    if len(words) > 80:
        vocab_text += f"\n... и еще {len(words) - 80} слов!"
    
    vocab_text += f"\n💡 **Совет:** Используйте эти слова в следующих упражнениях!"
    
    await update.message.reply_text(vocab_text)

async def handle_main_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка основной навигации"""
    user_message = update.message.text
    
    if user_message in ["📚 Упражнения", "📚 Следующее упражнение"]:
        return await start_exercise(update, context)
    elif user_message in ["💬 Диалоги", "💬 Диалог", "💬 Новая практика"]:
        return await start_conversation(update, context)
    elif user_message in ["✍️ Письмо", "✍️ Письменное задание", "✍️ Новое письмо"]:
        return await start_writing_task(update, context)
    elif user_message == "📊 Прогресс":
        await show_progress(update, context)
        return ConversationHandler.END
    elif user_message == "📖 Словарь":
        await show_vocabulary(update, context)
        return ConversationHandler.END
    elif user_message == "🏠 Главное меню":
        await update.message.reply_text(
            "Возвращаю в главное меню!",
            reply_markup=ReplyKeyboardMarkup([
                ["📚 Упражнения", "💬 Диалоги"],
                ["✍️ Письмо", "📊 Прогресс"],
                ["📖 Словарь", "🆘 Помощь"]
            ], resize_keyboard=True)
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("Пожалуйста, используйте кнопки для навигации.")
        return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать расширенную справку"""
    help_text = """
📚 **Доступные команды:**

/start - Начать работу с ботом
/help - Показать эту справку  
/exercise - Начать упражнение
/conversation - Практика диалога
/writing - Письменное задание
/progress - Показать прогресс
/vocabulary - Показать словарь

🎯 **Типы упражнений:**
• Грамматика (времена, артикли, предлоги)
• Словарный запас (тематические слова)
• Чтение (понимание текстов)
• Фразовые глаголы и идиомы
• Письменные задания

💡 **Советы:**
• Занимайтесь регулярно
• Используйте разные типы упражнений
• Добавляйте новые слова в словарь
• Анализируйте свой прогресс

📞 **Поддержка:** Если возникли проблемы, используйте /help
"""
    await update.message.reply_text(help_text)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия"""
    await update.message.reply_text(
        "Текущее действие отменено. Возвращаю в главное меню!",
        reply_markup=ReplyKeyboardMarkup([
            ["📚 Упражнения", "💬 Диалоги"],
            ["✍️ Письмо", "📊 Прогресс"],
            ["📖 Словарь", "🆘 Помощь"]
        ], resize_keyboard=True)
    )
    return ConversationHandler.END

def main():
    """Запуск бота"""
    application = Application.builder().token(TOKEN).build()
    
    # Основной обработчик разговора (регистрация)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_goal)],
            CURRENT_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_current_level)],
            TARGET_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_target_level)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Обработчик упражнений
    exercise_handler = ConversationHandler(
        entry_points=[
            CommandHandler("exercise", start_exercise),
            MessageHandler(filters.Regex("^(📚 Упражнения|📚 Следующее упражнение)$"), start_exercise)
        ],
        states={
            EXERCISE_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_exercise_answer)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Обработчик письменных заданий
    writing_handler = ConversationHandler(
        entry_points=[
            CommandHandler("writing", start_writing_task),
            MessageHandler(filters.Regex("^(✍️ Письмо|✍️ Письменное задание|✍️ Новое письмо)$"), start_writing_task)
        ],
        states={
            WRITING_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_writing_task)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Обработчик разговорной практики
    conversation_handler = ConversationHandler(
        entry_points=[
            CommandHandler("conversation", start_conversation),
            MessageHandler(filters.Regex("^(💬 Диалоги|💬 Диалог|💬 Новая практика)$"), start_conversation)
        ],
        states={
            CONVERSATION_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_conversation)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Добавляем все обработчики
    application.add_handler(conv_handler)
    application.add_handler(exercise_handler)
    application.add_handler(writing_handler)
    application.add_handler(conversation_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("progress", show_progress))
    application.add_handler(CommandHandler("vocabulary", show_vocabulary))
    
    # Обработчик основной навигации
    application.add_handler(MessageHandler(
        filters.Regex("^(📊 Прогресс|📖 Словарь|🏠 Главное меню|🆘 Помощь)$"), 
        handle_main_navigation
    ))
    
    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()
