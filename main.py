# BY LOUD
import logging
import asyncio
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from config import BOT_TOKEN, ADMIN_ID, REVIEWS_CHANNEL_ID, POST_CHANNEL_ID, SITE_URL, API_URL
import requests
import json
import os

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def is_admin(user_id):
    return str(user_id) == str(ADMIN_ID)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет доступа к этому боту.")
        return
    
    await update.message.reply_text(
        "Админ-панель\n\n"
        "Команды:\n"
        "/send_post - отправить пост с фото и кнопкой\n"
        "/update_reviews - принудительно проверить и обновить отзывы\n"
        "/help - справка"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    await update.message.reply_text(
        "Админ-панель\n\n"
        "/send_post - создать пост с фотографией и кнопкой 'Посмотреть био'\n"
        "/update_reviews - принудительно проверить канал отзывов и отправить данные на сайт\n"
        "/help - показать эту справку\n\n"
        "Примечание: /update_reviews проверяет только существующие сообщения в канале"
    )

async def send_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    await update.message.reply_text(
        "Отправь фотографию с подписью для поста.\n"
        "Подпись будет использована как текст поста."
    )
    context.user_data['waiting_for_photo'] = True

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    if not context.user_data.get('waiting_for_photo'):
        return
    
    photo = update.message.photo[-1]
    caption = update.message.caption or "Посмотри мое био!"
    
    keyboard = [
        [InlineKeyboardButton("Посмотреть био", url=SITE_URL)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        if POST_CHANNEL_ID:
            await context.bot.send_photo(
                chat_id=POST_CHANNEL_ID,
                photo=photo.file_id,
                caption=caption,
                reply_markup=reply_markup
            )
            await update.message.reply_text("Пост отправлен в канал!")
        else:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo.file_id,
                caption=caption,
                reply_markup=reply_markup
            )
            await update.message.reply_text("Пост отправлен!")
        context.user_data['waiting_for_photo'] = False
    except Exception as e:
        logger.error(f"Ошибка при отправке поста: {e}")
        await update.message.reply_text(f"Ошибка: {e}")

async def update_reviews_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    status_msg = await update.message.reply_text("⏳ Начинаю проверку отзывов...")
    
    try:
        await status_msg.edit_text("📊 Подсчитываю сообщения в канале...\n⏳ Это может занять время...")
        count = await count_channel_messages(context.bot, REVIEWS_CHANNEL_ID)
        
        await status_msg.edit_text(f"✅ Найдено сообщений: {count}\n📤 Отправляю данные на сайт...")
        
        try:
            response = requests.post(API_URL, json={'count': count}, timeout=30, headers={'Content-Type': 'application/json'})
            
            if response.status_code == 200:
                result = response.json()
                await status_msg.edit_text(
                    f"✅ Готово!\n\n"
                    f"📊 Количество отзывов: {count}+\n"
                    f"🌐 Данные успешно отправлены на сайт"
                )
            else:
                await status_msg.edit_text(
                    f"⚠️ Ошибка при отправке на сайт\n\n"
                    f"📊 Найдено сообщений: {count}\n"
                    f"❌ Код ответа: {response.status_code}\n"
                    f"Попробуй еще раз или проверь настройки API"
                )
        except requests.exceptions.RequestException as e:
            await status_msg.edit_text(
                f"❌ Ошибка подключения к API\n\n"
                f"📊 Найдено сообщений: {count}\n"
                f"🔗 URL: {API_URL}\n"
                f"Ошибка: {str(e)}"
            )
            logger.error(f"Ошибка подключения к API: {e}")
            
    except Exception as e:
        logger.error(f"Ошибка при обновлении отзывов: {e}")
        await status_msg.edit_text(f"❌ Критическая ошибка: {str(e)}")

async def count_channel_messages(bot, channel_id):
    try:
        count = 0
        
        try:
            chat = await bot.get_chat(chat_id=channel_id)
            logger.info(f"Информация о канале: {chat.title}, тип: {chat.type}, ID: {chat.id}")
        except Exception as e:
            logger.error(f"Не удалось получить информацию о канале: {e}")
            return 0
        
        logger.info("Использую упрощенный метод подсчета...")
        return await count_via_simple_method(bot, channel_id)
            
    except Exception as e:
        logger.error(f"Критическая ошибка при подсчете: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 0

async def count_via_simple_method(bot, channel_id):
    try:
        logger.info("Метод подсчета через пересылку сообщений...")
        
        chat = await bot.get_chat(chat_id=channel_id)
        logger.info(f"Канал: {chat.title}, ID: {chat.id}")
        
        from config import BOT_TOKEN
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
        
        count = 0
        message_id = 1
        not_found_streak = 0
        max_streak = 50
        max_check = 10000
        
        logger.info("Проверяю сообщения через пересылку...")
        
        async with aiohttp.ClientSession() as session:
            while message_id < max_check and not_found_streak < max_streak:
                try:
                    url = f"{api_url}/forwardMessage"
                    payload = {
                        'chat_id': str(ADMIN_ID),
                        'from_chat_id': str(channel_id),
                        'message_id': message_id
                    }
                    
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            if result.get('ok'):
                                count += 1
                                not_found_streak = 0
                                if count <= 5 or count % 10 == 0:
                                    logger.info(f"Найдено: {count}, проверяю ID: {message_id}")
                            else:
                                not_found_streak += 1
                        else:
                            not_found_streak += 1
                    
                    message_id += 1
                    
                    if not_found_streak >= max_streak:
                        logger.info(f"Конец канала. Найдено: {count}, последний ID: {message_id - max_streak}")
                        break
                        
                except Exception as e:
                    logger.debug(f"Ошибка для {message_id}: {e}")
                    message_id += 1
                    not_found_streak += 1
                    continue
        
        logger.info(f"Итого: {count} сообщений")
        return count
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 0

async def auto_update_reviews(context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("Автоматическое обновление отзывов...")
        count = await count_channel_messages(context.bot, REVIEWS_CHANNEL_ID)
        if count > 0:
            try:
                response = requests.post(API_URL, json={'count': count}, timeout=30, headers={'Content-Type': 'application/json'})
                if response.status_code == 200:
                    logger.info(f"Автообновление отзывов: {count}+")
                else:
                    logger.warning(f"Автообновление: ошибка отправки на сайт (код {response.status_code})")
            except Exception as e:
                logger.error(f"Автообновление: ошибка подключения к API: {e}")
        else:
            logger.warning("Автообновление: не найдено сообщений")
    except Exception as e:
        logger.error(f"Ошибка автообновления: {e}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("send_post", send_post_command))
    application.add_handler(CommandHandler("update_reviews", update_reviews_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    try:
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_repeating(
                lambda context: asyncio.create_task(auto_update_reviews(context)),
                interval=1800,
                first=10
            )
            logger.info("Автообновление отзывов настроено: каждые 30 минут")
        else:
            logger.warning("JobQueue недоступен. Автообновление отключено.")
    except Exception as e:
        logger.warning(f"Не удалось настроить автообновление: {e}")
    
    webhook_url = os.environ.get('RENDER_EXTERNAL_URL')
    port = int(os.environ.get('PORT', 8080))
    
    if webhook_url:
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="webhook",
            webhook_url=f"{webhook_url.rstrip('/')}/webhook"
        )
    else:
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
