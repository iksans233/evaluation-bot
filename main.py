import logging
import os
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, CallbackQueryHandler, PicklePersistence, CallbackContext, TypeHandler, ApplicationHandlerStop
from telegram import Update, BotCommand
import config
import database
import handlers
import scheduler

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# New function for access control
telegram_app: Application = None

async def pre_update_callback(update: Update, context: CallbackContext) -> None: # type: ignore
    """
    Checks if the incoming update is from the authorized user.
    If not, it sends a message and stops the update from being processed further.
    """
    if update.effective_user:
        user_id = update.effective_user.id
        if user_id != config.ADMIN_CHAT_ID:
            logger.warning(f"Unauthorized access attempt from user ID: {user_id}")
            if update.message:
                await update.message.reply_text("Maaf, bot ini hanya dapat digunakan oleh pemiliknya.")
            elif update.callback_query:
                await update.callback_query.answer("Maaf, Anda tidak diizinkan menggunakan bot ini.", show_alert=True)
            raise ApplicationHandlerStop # Stop processing this update

async def post_init_telegram_app(application: Application) -> None:
    """Sets the bot's commands after initialization."""
    commands = [
        # Perintah bot Anda
        BotCommand("start", "Mulai bot dan lihat bantuan"),
        BotCommand("new_evaluation", "Buat catatan evaluasi baru"),
        BotCommand("list_evaluations", "Lihat semua catatan evaluasi"),
        BotCommand("cancel", "Batalkan operasi saat ini"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Custom bot commands have been set.")
    
    # Pindahkan pemanggilan scheduler.start_scheduler ke sini
    scheduler.start_scheduler(application.bot)

# A shared list of fallbacks for all conversations
# This ensures consistent behavior for cancellation and unknown commands.
shared_fallbacks = [
    CommandHandler("cancel", handlers.cancel_command),
    # This handler catches any command that is not explicitly handled in a state.
    # It reminds the user they are in a conversation.
    MessageHandler(filters.COMMAND, handlers.unknown_command_in_conv)
]

def setup_telegram_handlers(application: Application):
    """
    Sets up all Telegram bot handlers.
    This function is separated to be called during FastAPI startup.
    """
    # Add the pre_update callback for access control. Group -1 ensures it runs first.
    application.add_handler(TypeHandler(Update, pre_update_callback), group=-1) # type: ignore

    # Add handlers
    application.add_handler(CommandHandler("start", handlers.start_command))
    application.add_handler(CommandHandler("list_evaluations", handlers.list_evaluations_command))
    
    # Conversation handler for new evaluation
    new_evaluation_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("new_evaluation", handlers.new_evaluation_command)],
        states={
            handlers.TEXT_NOTE: [
                # Izinkan pengguna untuk memulai ulang percakapan kapan saja
                CommandHandler("new_evaluation", handlers.new_evaluation_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_text_note)
            ],
            handlers.IMAGE_NOTE: [
                # Izinkan pengguna untuk memulai ulang percakapan kapan saja
                CommandHandler("new_evaluation", handlers.new_evaluation_command),
                MessageHandler(filters.PHOTO, handlers.receive_image_note),
                CommandHandler("done", handlers.receive_image_note),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_image_note)
            ],
        },
        fallbacks=shared_fallbacks,
        persistent=True, # Tambahkan ini jika Anda ingin percakapan berlanjut setelah restart
        name="new_evaluation_conversation" # Beri nama untuk persistensi
    )
    application.add_handler(new_evaluation_conv_handler)
    
    # Callback query handler untuk tombol lain (disable, delete flow)
    other_buttons_pattern = r"^(enable_reminder|disable_reminder|delete_eval|confirm_delete|cancel_delete)_\d+$"
    application.add_handler(CallbackQueryHandler(handlers.button_callback_handler, pattern=other_buttons_pattern))
    logger.info("Telegram handlers set up.")

def main() -> None:
    """Start the bot."""
    global telegram_app
    logger.info("Starting bot in webhook mode...")

    # Initialize database
    database.init_db()

    # Buat objek persistensi untuk menyimpan status percakapan
    persistence = PicklePersistence(filepath="bot_persistence.pickle")

    # Create the Application and pass your bot's token.
    telegram_app = Application.builder().token(config.BOT_TOKEN).persistence(persistence).post_init(post_init_telegram_app).build()

    # Setup all Telegram handlers
    setup_telegram_handlers(telegram_app)
    
    # Jalankan bot dalam mode webhook
    logger.info(f"Listening on http://127.0.0.1:{config.PORT}")
    logger.info(f"Webhook will be set to {config.WEBHOOK_URL}/{config.WEBHOOK_PATH}")
    telegram_app.run_webhook(
        listen="127.0.0.1",  # Listen on localhost as requested
        port=config.PORT,
        url_path=config.WEBHOOK_PATH,
        webhook_url=f"{config.WEBHOOK_URL}/{config.WEBHOOK_PATH}"
    )

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        # Ensure scheduler is shut down on error
        scheduler.shutdown_scheduler()