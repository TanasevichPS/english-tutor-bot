import os
import logging
import json
import random
import re
import sqlite3
import datetime
from typing import Dict, List
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
GOAL, CURRENT_LEVEL, TARGET_LEVEL, CONVERSATION_MODE, EXERCISE_MODE = range(5)

# Глобальное хранилище данных (в памяти)
user_data = {}
vocabulary = {}
user_progress = {}

# Уровни английского
LEVELS = ["A1 (Начальный)", "A2 (Элементарный)", "B1 (Средний)", "B2 (Выше среднего)", "C1 (Продвинутый)", "C2 (Профессиональный)"]

# База упражнений
EXERCISES = {
    "A1": [
        {
            "type": "translation",
            "question": "Переведите: 'Я люблю изучать английский'",
            "answer": "I love learning English",
            "hint": "Вспомните: love + ing форма глагола"
        },
        {
            "type": "gap_filling", 
            "question": "Заполните пропуск: I ___ breakfast at 8 am.",
            "answer": "have",
            "options": ["have", "has", "am"]
        },
        {
            "type": "sentence_building",
            "question": "Составьте предложение из слов: like / I / music / listening / to",
            "answer": "I like listening to music",
            "hint": "Порядок: Подлежащее + сказуемое + дополнение"
        }
    ],
    "A2": [
        {
            "type": "conversation",
            "question": "Ответьте на вопрос: What did you do yesterday?",
            "answer_patterns": ["yesterday", "went", "did", "was"],
            "hint": "Используйте Past Simple"
        },
        {
            "type": "grammar",
            "question": "Выберите правильный вариант: She ___ to school every day.",
            "answer": "goes",
            "options": ["go", "goes", "is going"]
        }
    ],
    "B1": [
        {
            "type": "writing",
            "question": "Напишите 3-4 предложения о вашем хобби",
            "min_words": 20,
            "hint": "Используйте Present Simple и слова: enjoy, usually, often"
        },
        {
            "type": "grammar",
            "question": "Выберите правильное время: If I ___ time, I will call you.",
            "answer": "have",
            "options": ["have", "had", "will have"]
        }
    ]
}

# Темы для разговорной практики
CONVERSATION_TOPICS = {
    "A1": ["Food", "Family", "Daily routine", "Hobbies"],
    "A2": ["Travel", "Weather", "Shopping", "Weekend plans"],
    "B1": ["Work", "Technology", "Health", "Culture"],
    "B2": ["Education", "Environment", "Social media", "Future plans"]
}

def get_user_level(user_id: int) -> str:
    """Получить уровень пользователя"""
    return user_data.get(user_id, {}).get('current_level', 'A2 (Элементарный)')

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
            'exercise_types': {}
        }
    
    user_progress[user_id]['total_exercises'] += 1
    user_progress[user_id]['last_activity'] = datetime.datetime.now().isoformat()
    
    if correct:
        user_progress[user_id]['correct_answers'] += 1
    
    if exercise_type not in user_progress[user_id]['exercise_types']:
        user_progress[user_id]['exercise_types'][exercise_type] = 0
    user_progress[user_id]['exercise_types'][exercise_type] += 1

def get_level_key(level: str) -> str:
    """Получить ключ уровня (A1, A2, etc)"""
    return level.split()[0]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало работы с ботом"""
    welcome_text = """
👋 Добро пожаловать в English Tutor Bot!

Я помогу вам изучать английский язык через:
• 📚 Интерактивные упражнения
• 💬 Практику диалогов  
• 📊 Отслеживание прогресса
• 📝 Персональную программу

Давайте начнем! Какова ваша цель изучения английского?
"""
    
    keyboard = [
        ["🗣️ Разговорная практика"],
        ["📖 Чтение и понимание"],
        ["✍️ Письмо и грамматика"],
        ["🎯 Общее улучшение"]
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
            ["📚 Начать урок", "💬 Практика диалога"],
            ["📊 Мой прогресс", "📖 Мой словарь"],
            ["🆘 Помощь", "⚙️ Настройки"]
        ], resize_keyboard=True)
    )
    return ConversationHandler.END

def generate_study_plan(user_id: int) -> str:
    """Генерация персонального плана обучения"""
    data = user_data[user_id]
    current = get_level_key(data['current_level'])
    target = get_level_key(data['target_level'])
    
    plans = {
        "A1": "• Учите базовые фразы и слова\n• Практикуйте простое настоящее время\n• Составляйте короткие предложения",
        "A2": "• Расширяйте словарный запас\n• Изучайте прошедшее время\n• Тренируйтесь в диалогах", 
        "B1": "• Развивайте разговорные навыки\n• Изучайте сложные времена\n• Читайте адаптированные тексты",
        "B2": "• Смотрите фильмы на английском\n• Практикуйте письмо\n• Говорите на разные темы"
    }
    
    return plans.get(current, "• Занимайтесь регулярно\n• Практикуйте все аспекты языка\n• Не бойтесь ошибок")

async def start_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать урок с упражнениями"""
    user_id = update.message.from_user.id
    
    if user_id not in user_data:
        await update.message.reply_text("Пожалуйста, сначала завершите настройку с помощью /start")
        return
    
    level = get_level_key(get_user_level(user_id))
    exercises = EXERCISES.get(level, EXERCISES["A2"])
    exercise = random.choice(exercises)
    
    # Сохраняем текущее упражнение в контексте
    context.user_data['current_exercise'] = exercise
    context.user_data['exercise_start_time'] = datetime.datetime.now().isoformat()
    
    message = f"📚 **Упражнение**\n\n{exercise['question']}"
    if 'hint' in exercise:
        message += f"\n\n💡 Подсказка: {exercise['hint']}"
    
    if exercise['type'] == 'gap_filling' and 'options' in exercise:
        keyboard = [[opt] for opt in exercise['options']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=ReplyKeyboardRemove())
    
    return EXERCISE_MODE

async def check_exercise_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить ответ на упражнение"""
    user_id = update.message.from_user.id
    user_answer = update.message.text.strip()
    
    if 'current_exercise' not in context.user_data:
        await update.message.reply_text("Пожалуйста, начните упражнение с помощью /lesson")
        return ConversationHandler.END
    
    exercise = context.user_data['current_exercise']
    is_correct = False
    feedback = ""
    
    # Проверка в зависимости от типа упражнения
    if exercise['type'] == 'translation':
        # Простая проверка перевода - ищем ключевые слова
        expected_words = exercise['answer'].lower().split()
        user_words = user_answer.lower().split()
        matches = sum(1 for word in expected_words if word in user_words)
        is_correct = matches >= len(expected_words) * 0.6  # 60% совпадений
        
    elif exercise['type'] == 'gap_filling':
        is_correct = user_answer.lower() == exercise['answer'].lower()
        
    elif exercise['type'] == 'sentence_building':
        # Проверяем наличие ключевых слов в правильном порядке
        expected_words = exercise['answer'].lower().split()
        user_words = user_answer.lower().split()
        is_correct = all(word in user_words for word in expected_words)
        
    elif exercise['type'] == 'conversation':
        # Для разговорных упражнений проверяем наличие ключевых слов
        expected_patterns = exercise['answer_patterns']
        user_lower = user_answer.lower()
        matches = sum(1 for pattern in expected_patterns if pattern in user_lower)
        is_correct = matches >= len(expected_patterns) * 0.5
        
    elif exercise['type'] == 'grammar':
        is_correct = user_answer.lower() == exercise['answer'].lower()
        
    elif exercise['type'] == 'writing':
        # Для письменных заданий проверяем длину
        word_count = len(user_answer.split())
        is_correct = word_count >= exercise.get('min_words', 15)
        feedback = f"✅ Отлично! Вы написали {word_count} слов."
        
    # Обновляем прогресс
    update_progress(user_id, exercise['type'], is_correct)
    
    # Добавляем слова в словарь
    words = re.findall(r'\b[a-zA-Z]+\b', user_answer)
    for word in words:
        if len(word) > 3:  # Добавляем только слова длиннее 3 букв
            add_to_vocabulary(user_id, word)
    
    # Формируем ответ
    if is_correct:
        if not feedback:
            feedback = "✅ Правильно! Отличная работа!"
        if exercise['type'] in ['translation', 'sentence_building']:
            feedback += f"\n\nПример правильного ответа: '{exercise['answer']}'"
    else:
        feedback = f"❌ Пока не совсем верно. Попробуйте еще раз!\n\nПравильный ответ: '{exercise.get('answer', 'Посмотрите в подсказке')}'"
    
    await update.message.reply_text(
        feedback,
        reply_markup=ReplyKeyboardMarkup([
            ["📚 Следующее упражнение", "💬 Практика диалога"],
            ["📊 Мой прогресс", "🏠 Главное меню"]
        ], resize_keyboard=True)
    )
    
    # Очищаем текущее упражнение
    context.user_data.pop('current_exercise', None)
    
    return ConversationHandler.END

async def start_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать разговорную практику"""
    user_id = update.message.from_user.id
    
    if user_id not in user_data:
        await update.message.reply_text("Пожалуйста, сначала завершите настройку с помощью /start")
        return
    
    level = get_level_key(get_user_level(user_id))
    topics = CONVERSATION_TOPICS.get(level, CONVERSATION_TOPICS["A2"])
    topic = random.choice(topics)
    
    # Генерируем стартовый вопрос
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
        ]
    }
    
    question = random.choice(questions.get(level, questions["A2"]))
    
    # Сохраняем тему для продолжения диалога
    context.user_data['conversation_topic'] = topic
    context.user_data['conversation_start'] = datetime.datetime.now().isoformat()
    
    await update.message.reply_text(
        f"💬 **Разговорная практика**\n\n"
        f"Тема: {topic}\n\n"
        f"{question}\n\n"
        "Ответьте на вопрос на английском:",
        reply_markup=ReplyKeyboardMarkup([
            ["🔚 Завершить диалог", "🔄 Новая тема"],
            ["📚 К упражнениям", "🏠 Главное меню"]
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
        duration = "несколько минут"
        if start_time:
            start_dt = datetime.datetime.fromisoformat(start_time)
            duration_min = (datetime.datetime.now() - start_dt).seconds // 60
            duration = f"{duration_min} минут"
        
        await update.message.reply_text(
            f"🎉 Отличная разговорная практика!\n\n"
            f"💬 Вы практиковали английский {duration}\n"
            f"📚 Новые слова добавлены в ваш словарь\n"
            f"💪 Продолжайте в том же духе!",
            reply_markup=ReplyKeyboardMarkup([
                ["📚 Начать урок", "💬 Новая практика"],
                ["📊 Мой прогресс", "🏠 Главное меню"]
            ], resize_keyboard=True)
        )
        return ConversationHandler.END
        
    elif user_message == "🔄 Новая тема":
        return await start_conversation(update, context)
    
    elif user_message in ["📚 К упражнениям", "🏠 Главное меню"]:
        return await handle_main_navigation(update, context)
    
    else:
        # Анализируем ответ пользователя и даем обратную связь
        words = re.findall(r'\b[a-zA-Z]+\b', user_message)
        for word in words:
            if len(word) > 3:
                add_to_vocabulary(user_id, word)
        
        # Простая обратная связь
        feedback = "💬 Спасибо за ответ! "
        
        # Проверяем длину ответа
        word_count = len(user_message.split())
        if word_count < 5:
            feedback += "Попробуйте дать более развернутый ответ."
        elif word_count < 10:
            feedback += "Хороший ответ! Можете добавить больше деталей."
        else:
            feedback += "Отличный развернутый ответ!"
        
        # Следующий вопрос по теме
        topic = context.user_data.get('conversation_topic', 'general')
        follow_up_questions = [
            "Can you tell me more about that?",
            "Why do you think that?",
            "What happened next?",
            "How did you feel about it?"
        ]
        
        next_question = random.choice(follow_up_questions)
        
        await update.message.reply_text(
            f"{feedback}\n\n{next_question}",
            reply_markup=ReplyKeyboardMarkup([
                ["🔚 Завершить диалог", "🔄 Новая тема"],
                ["📚 К упражнениям", "🏠 Главное меню"]
            ], resize_keyboard=True)
        )
        
        return CONVERSATION_MODE

async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать прогресс пользователя"""
    user_id = update.message.from_user.id
    
    if user_id not in user_progress:
        await update.message.reply_text("📊 У вас пока нет данных о прогрессе. Начните выполнять упражнения!")
        return
    
    progress = user_progress[user_id]
    total = progress['total_exercises']
    correct = progress['correct_answers']
    accuracy = (correct / total * 100) if total > 0 else 0
    
    # Самые частые типы упражнений
    exercise_types = progress.get('exercise_types', {})
    popular_type = max(exercise_types.items(), key=lambda x: x[1]) if exercise_types else ("нет данных", 0)
    
    # Размер словаря
    vocab_size = len(vocabulary.get(user_id, set()))
    
    progress_text = f"""
📊 **Ваш прогресс:**

✅ Выполнено упражнений: {total}
🎯 Правильных ответов: {correct} ({accuracy:.1f}%)
📚 Размер словаря: {vocab_size} слов
⭐ Любимый тип упражнений: {popular_type[0]} ({popular_type[1]} раз)

💡 Совет: Практикуйтесь регулярно для лучших результатов!
"""
    
    await update.message.reply_text(progress_text)

async def show_vocabulary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать словарь пользователя"""
    user_id = update.message.from_user.id
    
    if user_id not in vocabulary or not vocabulary[user_id]:
        await update.message.reply_text("📖 Ваш словарь пуст. Начните общаться или выполнять упражнения, чтобы добавлять слова!")
        return
    
    words = sorted(list(vocabulary[user_id]))
    
    # Показываем слова группами по 20
    vocab_text = f"📖 **Ваш словарь ({len(words)} слов):**\n\n"
    
    for i in range(0, min(len(words), 60), 20):  # Показываем максимум 60 слов
        group = words[i:i+20]
        vocab_text += f"**{i+1}-{i+len(group)}:** {', '.join(group)}\n\n"
    
    if len(words) > 60:
        vocab_text += f"... и еще {len(words) - 60} слов!"
    
    await update.message.reply_text(vocab_text)

async def handle_main_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка основной навигации"""
    user_message = update.message.text
    
    if user_message == "📚 Начать урок" or user_message == "📚 Следующее упражнение":
        return await start_lesson(update, context)
    elif user_message == "💬 Практика диалога" or user_message == "💬 Новая практика":
        return await start_conversation(update, context)
    elif user_message == "📊 Мой прогресс":
        await show_progress(update, context)
        return ConversationHandler.END
    elif user_message == "📖 Мой словарь":
        await show_vocabulary(update, context)
        return ConversationHandler.END
    elif user_message == "🏠 Главное меню":
        await update.message.reply_text(
            "Возвращаю в главное меню!",
            reply_markup=ReplyKeyboardMarkup([
                ["📚 Начать урок", "💬 Практика диалога"],
                ["📊 Мой прогресс", "📖 Мой словарь"],
                ["🆘 Помощь", "⚙️ Настройки"]
            ], resize_keyboard=True)
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("Пожалуйста, используйте кнопки для навигации.")
        return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать справку"""
    help_text = """
📚 **Доступные команды:**

/start - Начать работу с ботом
/help - Показать эту справку  
/lesson - Начать урок
/conversation - Практика диалога
/progress - Показать прогресс
/vocabulary - Показать словарь

🎯 **Функции:**
• Интерактивные упражнения
• Разговорная практика с обратной связью
• Отслеживание прогресса
• Персональный словарь
• Рекомендации по обучению

💡 **Совет:** Занимайтесь регулярно для лучших результатов!
"""
    await update.message.reply_text(help_text)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия"""
    await update.message.reply_text(
        "Текущее действие отменено. Возвращаю в главное меню!",
        reply_markup=ReplyKeyboardMarkup([
            ["📚 Начать урок", "💬 Практика диалога"],
            ["📊 Мой прогресс", "📖 Мой словарь"],
            ["🆘 Помощь"]
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
            CommandHandler("lesson", start_lesson),
            MessageHandler(filters.Regex("^(📚 Начать урок|📚 Следующее упражнение)$"), start_lesson)
        ],
        states={
            EXERCISE_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_exercise_answer)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Обработчик разговорной практики
    conversation_handler = ConversationHandler(
        entry_points=[
            CommandHandler("conversation", start_conversation),
            MessageHandler(filters.Regex("^(💬 Практика диалога|💬 Новая практика)$"), start_conversation)
        ],
        states={
            CONVERSATION_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_conversation)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Добавляем все обработчики
    application.add_handler(conv_handler)
    application.add_handler(exercise_handler)
    application.add_handler(conversation_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("progress", show_progress))
    application.add_handler(CommandHandler("vocabulary", show_vocabulary))
    
    # Обработчик основной навигации
    application.add_handler(MessageHandler(
        filters.Regex("^(📊 Мой прогресс|📖 Мой словарь|🏠 Главное меню|🆘 Помощь)$"), 
        handle_main_navigation
    ))
    
    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()
