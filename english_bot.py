import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получение токена
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# Состояния разговора
GOAL, CURRENT_LEVEL = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало работы с ботом"""
    welcome_text = """
👋 Добро пожаловать в English Tutor Bot!

Я помогу вам изучать английский язык.

Давайте начнем! Какова ваша цель изучения английского?
"""
    
    keyboard = [
        ["🗣️ Разговорная практика"],
        ["📖 Чтение и понимание"],
        ["✍️ Письмо"],
        ["🎯 Общее улучшение"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    return GOAL

async def set_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка цели обучения"""
    user = update.message.from_user
    context.user_data['goal'] = update.message.text
    
    await update.message.reply_text(
        f"Отлично! Ваша цель: {update.message.text}\n\n"
        "Какой у вас текущий уровень английского?",
        reply_markup=ReplyKeyboardMarkup([
            ["A1 (Начальный)", "A2 (Элементарный)"],
            ["B1 (Средний)", "B2 (Выше среднего)"],
            ["C1 (Продвинутый)", "C2 (Профессиональный)"]
        ], resize_keyboard=True)
    )
    return CURRENT_LEVEL

async def set_current_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Установка текущего уровня"""
    user = update.message.from_user
    context.user_data['current_level'] = update.message.text
    
    await update.message.reply_text(
        f"🎉 Отлично! Настройка завершена!\n\n"
        f"Ваша цель: {context.user_data['goal']}\n"
        f"Текущий уровень: {context.user_data['current_level']}\n\n"
        "Теперь вы можете начать обучение!",
        reply_markup=ReplyKeyboardMarkup([
            ["📚 Урок", "💬 Практика диалога"],
            ["📊 Прогресс", "🆘 Помощь"]
        ], resize_keyboard=True)
    )
    return ConversationHandler.END

async def start_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начать урок"""
    exercises = [
        "📝 **Упражнение 1:** Напишите 3 предложения о вашем дне",
        "🎯 **Упражнение 2:** Переведите: 'Я люблю изучать английский'",
        "💬 **Упражнение 3:** Ответьте на вопрос: What's your favorite hobby?",
    ]
    
    exercise = exercises[0]  # Простое упражнение
    
    await update.message.reply_text(
        f"📚 **Начнем урок!**\n\n{exercise}\n\n"
        "Напишите ваш ответ:"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка обычных сообщений"""
    user_message = update.message.text
    
    if user_message == "📚 Урок":
        await start_lesson(update, context)
    elif user_message == "💬 Практика диалога":
        await update.message.reply_text(
            "💬 **Режим диалога**\n\n"
            "Let's practice English! What did you do yesterday?"
        )
    elif user_message == "📊 Прогресс":
        await update.message.reply_text(
            "📊 **Ваш прогресс**\n\n"
            "✅ Завершено уроков: 0\n"
            "🎯 Активность: Новичок\n"
            "💪 Продолжайте в том же духе!"
        )
    elif user_message == "🆘 Помощь":
        await help_command(update, context)
    else:
        # Простой ответ на любое сообщение
        await update.message.reply_text(
            f"Спасибо за ваше сообщение!\n\n"
            f"Вы написали: '{user_message}'\n\n"
            "Продолжайте практиковать английский! 🚀"
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать справку"""
    help_text = """
📚 **Доступные команды:**

/start - Начать работу с ботом
/help - Показать эту справку
/lesson - Начать урок

🎯 **Функции:**
• Простые упражнения
• Практика диалогов
• Отслеживание прогресса

💡 **Совет:** Регулярно занимайтесь для лучших результатов!
"""
    await update.message.reply_text(help_text)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена разговора"""
    await update.message.reply_text(
        "До свидания! Возвращайтесь для продолжения обучения.",
        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
    )
    return ConversationHandler.END

def main() -> None:
    """Запуск бота"""
    application = Application.builder().token(TOKEN).build()
    
    # Обработчик разговора
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_goal)],
            CURRENT_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_current_level)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("lesson", start_lesson))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()
