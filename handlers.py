from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler
import database
import logging
from datetime import datetime
import message_formatter # Import the new module

# Get a logger for this module
logger = logging.getLogger(__name__)

# States for conversation handler
TEXT_NOTE, IMAGE_NOTE = range(2)

def _create_evaluation_keyboard(eval_item: database.EvaluationDTO) -> InlineKeyboardMarkup:
    """Helper function to create the dynamic inline keyboard for an evaluation."""
    keyboard = []
    first_row = []
    
    if eval_item.reminder_enabled:
        first_row.append(InlineKeyboardButton("🚫 Nonaktifkan Pengingat", callback_data=f"disable_reminder_{eval_item.id}"))
    else:
        first_row.append(InlineKeyboardButton("🔔 Aktifkan Pengingat", callback_data=f"enable_reminder_{eval_item.id}"))
        
    keyboard.append(first_row)
    # The delete button is always present on its own row for safety and clarity
    keyboard.append([InlineKeyboardButton("🗑️ Hapus", callback_data=f"delete_eval_{eval_item.id}")])
    
    return InlineKeyboardMarkup(keyboard)


async def start_command(update: Update, context: CallbackContext) -> None:
    """Sends a welcome message and explains bot usage."""
    await update.message.reply_html( # Gunakan HTML untuk formatting
        "👋 Halo! Saya adalah <b>Bot Evaluasi Trading</b> Anda. "
        "Saya bisa membantu Anda menyimpan catatan pembelajaran reaksi pasar atau ide, "
        "termasuk gambar, dan mengingatkan Anda setiap hari. 📈\n\n"
        "Gunakan /new_evaluation untuk menambahkan catatan baru.\n"
        "Gunakan /list_evaluations untuk melihat catatan Anda."
    )

async def new_evaluation_command(update: Update, context: CallbackContext) -> int:
    """Starts the conversation to add a new evaluation."""
    logger.info("new_evaluation_command called. User: %s. Setting state to TEXT_NOTE.", update.effective_user.id)
    await update.message.reply_html( # Gunakan HTML untuk formatting
        "📝 Silakan kirim <b>catatan teks</b> Anda untuk evaluasi ini. "
        "Anda juga bisa mengirim gambar setelahnya."
    )
    return TEXT_NOTE

async def receive_text_note(update: Update, context: CallbackContext) -> int:
    """Receives the text note for the evaluation."""
    logger.info("receive_text_note called. User: %s.", update.effective_user.id)
    user_id = update.effective_user.id
    text_note = update.message.text
    logger.info(f"Received text note from user {user_id}: '{text_note[:50]}...'")
    
    # Store the text temporarily in user_data
    context.user_data['current_evaluation_text'] = text_note
    context.user_data['current_evaluation_image_file_id'] = None # Reset image_file_id

    await update.message.reply_html( # Gunakan HTML untuk formatting
        "✅ Catatan teks diterima! Sekarang, jika Anda ingin menambahkan gambar, "
        "silakan kirim gambarnya. Jika tidak, ketik /done untuk menyimpan."
    )
    logger.info("Replied to user and transitioned to IMAGE_NOTE state.")
    return IMAGE_NOTE

async def receive_image_note(update: Update, context: CallbackContext) -> int:
    """Receives the image note for the evaluation."""
    user_id = update.effective_user.id
    
    if update.message.photo:
        # Get the file_id of the largest photo
        file_id = update.message.photo[-1].file_id
        context.user_data['current_evaluation_image_file_id'] = file_id
        await update.message.reply_html( # Gunakan HTML untuk formatting
            "📸 Gambar diterima! Ketik /done untuk menyimpan evaluasi ini."
        )
        return IMAGE_NOTE # Stay in IMAGE_NOTE state to allow more images (though we only store one file_id)
    elif update.message.text and update.message.text.lower() == '/done':
        # User finished adding notes/images
        text_note = context.user_data.get('current_evaluation_text')
        image_file_id = context.user_data.get('current_evaluation_image_file_id')

        if not text_note and not image_file_id:
            await update.message.reply_text("Tidak ada catatan atau gambar yang diberikan. Evaluasi dibatalkan.")
            return ConversationHandler.END

        evaluation = database.save_evaluation(user_id, text_note, image_file_id)        
        if evaluation:
            await update.message.reply_html(
                f"✅ Evaluasi Anda telah disimpan! <b>ID: {evaluation.id}</b>\n\n"
                "Anda dapat mengaktifkan pengingat harian acak dari /list_evaluations."
            )
        else:
            await update.message.reply_html( # Gunakan HTML untuk formatting
                "❌ Maaf, terjadi kesalahan saat menyimpan evaluasi Anda. Silakan coba lagi."
            )
        # Clear all temporary data to ensure a clean state, consistent with cancel/skip
        context.user_data.clear()
        return ConversationHandler.END
    else:
        await update.message.reply_html( # Gunakan HTML untuk formatting
            "⚠️ Mohon maaf, saya hanya bisa menerima gambar atau perintah /done. "
            "Silakan kirim gambar atau ketik /done."
        )
        return IMAGE_NOTE

async def cancel_command(update: Update, context: CallbackContext) -> int:
    """Cancels the current conversation and clears all temporary user data."""
    logger.info("cancel_command called. User: %s.", update.effective_user.id)
    await update.message.reply_html("❌ Operasi telah dibatalkan.")
    # Clear all temporary data to prevent state leakage between different conversations
    context.user_data.clear()
    return ConversationHandler.END

async def unknown_command_in_conv(update: Update, context: CallbackContext) -> None:
    """Handles any unknown command sent during a conversation."""
    await update.message.reply_html(
        "⚠️ Saya sedang menunggu masukan untuk operasi sebelumnya. "
        "Silakan selesaikan operasi tersebut, atau ketik /cancel untuk membatalkan."
    )
    # We return None, so the conversation state does not change.

async def list_evaluations_command(update: Update, context: CallbackContext) -> None:
    """Lists all evaluations for the user."""
    logger.info("list_evaluations_command called. User: %s.", update.effective_user.id)
    user_id = update.effective_user.id
    evaluations = database.get_all_evaluations(user_id)

    if not evaluations:
        await update.message.reply_html("Anda belum memiliki catatan evaluasi. Gunakan /new_evaluation untuk membuat yang pertama! ✨")
        return

    for eval_item in evaluations:
        # Use the new message formatter
        formatted_text, _ = message_formatter.format_evaluation_message(eval_item)
        reply_markup = _create_evaluation_keyboard(eval_item)
        await update.message.reply_html(formatted_text, reply_markup=reply_markup)

async def button_callback_handler(update: Update, context: CallbackContext) -> None:
    """Handles inline keyboard button presses."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    data = query.data
    logger.info(f"button_callback_handler received callback_data: {data}") # Tambahkan baris ini
    user_id = query.from_user.id # For security checks (tetap diperlukan untuk logika hapus)

    if data.startswith("enable_reminder_") or data.startswith("disable_reminder_"):
        is_enabling = data.startswith("enable_reminder_")
        evaluation_id = int(data.split("_")[2])
        success = database.update_evaluation_reminder(evaluation_id, is_enabling)
        
        if success:
            # Refetch the updated evaluation to rebuild the message and keyboard
            eval_item: database.EvaluationDTO = database.get_evaluation_by_id(evaluation_id, user_id)
            if eval_item:
                # Regenerate message and keyboard
                formatted_text, _ = message_formatter.format_evaluation_message(eval_item)
                reply_markup = _create_evaluation_keyboard(eval_item)
                await query.edit_message_text(text=formatted_text, reply_markup=reply_markup, parse_mode='HTML')
                feedback_text = "Pengingat diaktifkan!" if is_enabling else "Pengingat dinonaktifkan!"
                await query.answer(feedback_text) # Give feedback via toast
            else:
                # Fallback if refetch fails
                await query.edit_message_text(f"Status pengingat untuk Evaluasi ID <b>{evaluation_id}</b> telah diperbarui.", parse_mode='HTML')
        else:
            await query.answer("Gagal memperbarui status pengingat.", show_alert=True)

    # --- Deletion Logic ---
    elif data.startswith("delete_eval_"):
        evaluation_id = int(data.split("_")[2])
        keyboard = [
            [
                InlineKeyboardButton("✅ Ya, Hapus", callback_data=f"confirm_delete_{evaluation_id}"),
                InlineKeyboardButton("❌ Batal", callback_data=f"cancel_delete_{evaluation_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text( # Gunakan HTML untuk formatting
            text=f"🗑️ Apakah Anda yakin ingin menghapus Evaluasi ID: <b>{evaluation_id}</b> secara permanen?",
            reply_markup=reply_markup
        )
    elif data.startswith("confirm_delete_"):
        evaluation_id = int(data.split("_")[2])
        # Pass user_id to the delete function for security
        deleted = database.delete_evaluation(evaluation_id=evaluation_id, user_id=user_id)
        if deleted:
            await query.edit_message_text(f"✅ Evaluasi ID: <b>{evaluation_id}</b> telah berhasil dihapus.", parse_mode='HTML')
        else:
            await query.edit_message_text("❌ Gagal menghapus evaluasi. Mungkin evaluasi tersebut sudah tidak ada atau bukan milik Anda.")
    elif data.startswith("cancel_delete_"):
        # The user cancelled the deletion. Restore the original message.
        evaluation_id: int = int(data.split("_")[2])
        eval_item: database.EvaluationDTO = database.get_evaluation_by_id(evaluation_id, user_id)
        if eval_item:
            # Restore the original message and keyboard
            formatted_text, _ = message_formatter.format_evaluation_message(eval_item)
            reply_markup = _create_evaluation_keyboard(eval_item)
            await query.edit_message_text(text=formatted_text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            # Fallback if the item was deleted in the meantime or not found
            await query.edit_message_text("👍 Penghapusan dibatalkan.")