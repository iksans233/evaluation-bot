import logging
import os
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, CallbackQueryHandler, PicklePersistence, CallbackContext, TypeHandler, ApplicationHandlerStop
from telegram import Update, BotCommand, error
import config
import database
import handlers
import scheduler
from fastapi import FastAPI, Request, Response, status
import uvicorn

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# New function for access control
# Global Telegram Application instance
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
    
    # Run the catch-up job for missed reminders once at startup
    await scheduler.send_missed_reminders(application.bot) # type: ignore

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

    # Get the bot instance to pass to the scheduler
    # bot_instance = application.bot # No longer needed as application.bot is directly accessible

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
            handlers.REMINDER_TIME: [
                CommandHandler("skip", handlers.skip_reminder),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_reminder_time)
            ],
        },
        fallbacks=shared_fallbacks,
        persistent=True, # Tambahkan ini jika Anda ingin percakapan berlanjut setelah restart
        name="new_evaluation_conversation" # Beri nama untuk persistensi
    )
    application.add_handler(new_evaluation_conv_handler)

    # NEW: Conversation handler for setting/changing reminders from /list_evaluations
    set_reminder_conv_handler = ConversationHandler(
        entry_points=[
            # Ini adalah entry point dari tombol "Atur/Ubah Pengingat" di list_evaluations
            CallbackQueryHandler(handlers.set_reminder_entry_point, pattern=r"^set_reminder_\d+$")
        ],
        states={
            handlers.REMINDER_TIME: [ # Re-use the REMINDER_TIME state and receive_reminder_time handler
                MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.receive_reminder_time)
            ],
        },
        fallbacks=shared_fallbacks,
        persistent=True,
        name="set_reminder_conversation" # Beri nama unik
    )
    application.add_handler(set_reminder_conv_handler)

    # Callback query handler untuk tombol lain (disable, delete flow)
    # Dibuat lebih spesifik agar tidak menangkap 'set_reminder_'
    other_buttons_pattern = r"^(disable_reminder|delete_eval|confirm_delete|cancel_delete)_\d+$"
    application.add_handler(CallbackQueryHandler(handlers.button_callback_handler, pattern=other_buttons_pattern))
    logger.info("Telegram handlers set up.")


# Create the FastAPI app instance
app = FastAPI()

@app.on_event("startup")
async def startup_event():
    """
    Initializes the Telegram bot application and sets up the webhook.
    This runs when the FastAPI application starts.
    """
    global telegram_app
    logger.info("FastAPI startup event triggered.")

    # Initialize database
    database.init_db()

    # Buat objek persistensi untuk menyimpan status percakapan
    # Catatan: PicklePersistence mungkin tidak ideal untuk sistem file ephemeral di PaaS
    # karena data akan hilang saat container restart. Pertimbangkan database untuk persistensi yang lebih baik.
    persistence = PicklePersistence(filepath="bot_persistence.pickle")

    # Create the Application and pass your bot's token.
    telegram_app = Application.builder().token(config.BOT_TOKEN).persistence(persistence).post_init(post_init_telegram_app).build()

    # Setup all Telegram handlers
    setup_telegram_handlers(telegram_app)

    # Set the webhook
    if config.WEBHOOK_URL and config.WEBHOOK_PATH:
        full_webhook_url = f"{config.WEBHOOK_URL}{config.WEBHOOK_PATH}"
        logger.info(f"Setting webhook to: {full_webhook_url}")
        try:
            await telegram_app.bot.set_webhook(url=full_webhook_url)
            # Start the application in webhook mode (this starts the internal update processing)
            await telegram_app.start()
            logger.info("Telegram Application started in webhook mode.")
        except error.TelegramError as e:
            logger.error(f"Failed to set webhook or start Telegram Application: {e}")
            # Depending on the error, you might want to exit or log more severely
    else:
        logger.error("WEBHOOK_URL or WEBHOOK_PATH not set. Bot will not receive updates via webhook.")

@app.on_event("shutdown")
async def shutdown_event():
    """
    Shuts down the Telegram bot application and scheduler.
    This runs when the FastAPI application shuts down.
    """
    logger.info("FastAPI shutdown event triggered.")
    if telegram_app:
        await telegram_app.stop()
        await telegram_app.shutdown()
        logger.info("Telegram Application shut down.")
    scheduler.shutdown_scheduler()
    logger.info("Scheduler shut down.")

@app.post(config.WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """Endpoint for Telegram to send updates."""
    if not telegram_app:
        logger.error("Telegram Application not initialized.")
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    try:
        request_body = await request.json()
        update = Update.de_json(request_body, telegram_app.bot)
        await telegram_app.update_queue.put(update)
        return Response(status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error processing webhook update: {e}")
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"message": "Telegram Bot is running!"}

if __name__ == "__main__":
    try:
        # This block is for local development if you want to run FastAPI directly.
        # For Render, you will use the 'uvicorn main:app --host 0.0.0.0 --port $PORT' command.
        uvicorn.run(app, host="0.0.0.0", port=config.PORT)
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        # Ensure scheduler is shut down on error
        scheduler.shutdown_scheduler()