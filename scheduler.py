import logging
from datetime import datetime
import random

from apscheduler.schedulers.asyncio import AsyncIOScheduler # Ubah ke AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot

import database
import message_formatter # Import the new module

# Get a logger for this module
logger = logging.getLogger(__name__)

# Inisialisasi scheduler dengan zona waktu UTC
scheduler = AsyncIOScheduler(timezone='UTC') # Ubah ke AsyncIOScheduler


async def send_missed_reminders(bot: Bot):
    """
    Runs once at startup to send any reminders that were missed while the bot was offline.
    """
    logger.info("Catch-up Job: Checking for missed reminders...")
    now_utc = datetime.utcnow()

    # Use the new, more efficient database query to get only the reminders that were actually missed.
    evaluations_to_check = database.get_missed_reminders(now_utc)

    if not evaluations_to_check:
        logger.info("Catch-up Job: No missed reminders to check.")
        return

    for eval_item in evaluations_to_check:
        # The database query has already filtered everything, so we can just send.
        try:
            logger.info(f"Catch-up Job: Found missed reminder for eval {eval_item.id}. Sending now.")
            
            # Send a slightly different message for missed reminders
            await bot.send_message(
                chat_id=eval_item.user_id,
                text=f"🔔 Ini pengingat yang terlewat untuk hari ini (Evaluasi ID: {eval_item.id})! 🔔⏰"
            )

            # Use the new message formatter
            formatted_text, image_file_id = message_formatter.format_evaluation_message(eval_item, include_reminder_info=False)
            await bot.send_message(chat_id=eval_item.user_id, text=formatted_text, parse_mode='HTML')

            if image_file_id:
                try:
                    await bot.send_photo(chat_id=eval_item.user_id, photo=image_file_id)
                except Exception as e:
                    logger.error(f"Catch-up Job: Failed to send photo for eval {eval_item.id}: {e}")

            # IMPORTANT: Update the database to mark it as sent (penting untuk mencegah pengiriman berulang)
            database.update_last_reminder_sent(eval_item.id)

        except Exception as e:
            logger.error(f"Catch-up Job: Error processing missed reminder for eval {eval_item.id}: {e}")

    logger.info("Catch-up Job: Finished checking for missed reminders.")


async def send_reminders(bot: Bot):
    """
    Berjalan setiap menit untuk memeriksa dan mengirim pengingat yang jatuh tempo.
    """
    now_utc = datetime.utcnow()
    current_time_str = now_utc.strftime('%H:%M')  # Format HH:MM untuk perbandingan
    logger.info(f"Scheduler: Checking for reminders at {current_time_str} UTC.")

    # Ambil evaluasi yang jatuh tempo, diurutkan berdasarkan yang paling lama tidak diingatkan
    evaluations_to_send = database.get_due_reminders(current_time_str)

    if not evaluations_to_send:
        logger.info(f"Scheduler: No due reminders at {current_time_str} UTC.")
        return  # Tidak ada yang perlu diperiksa, keluar lebih awal

    # --- LOGIKA BARU: Pilih 2 evaluasi secara acak ---
    REMINDER_LIMIT = 2
    num_to_sample = min(len(evaluations_to_send), REMINDER_LIMIT)

    # Pilih secara acak dari daftar yang sudah diurutkan (memberi prioritas pada yang lama)
    selected_evaluations = random.sample(evaluations_to_send, num_to_sample)

    logger.info(f"Scheduler: Found {len(evaluations_to_send)} due reminders. Randomly selected {len(selected_evaluations)} to send.")

    # Untuk melacak pengguna yang sudah dikirimi pesan header dalam siklus ini
    reminded_users = set()

    for eval_item in selected_evaluations:
        logger.info(f"Scheduler: Sending reminder for evaluation ID {eval_item.id} to user {eval_item.user_id}.")
        try:
                # Kirim pesan header sekali per pengguna per siklus
                if eval_item.user_id not in reminded_users:
                    await bot.send_message(
                        chat_id=eval_item.user_id,
                        text="🔔 Waktunya untuk evaluasi harian Anda! 🔔📝"
                    )
                    reminded_users.add(eval_item.user_id)

                # Kirim pesan teks terlebih dahulu
                formatted_text, image_file_id = message_formatter.format_evaluation_message(eval_item, include_reminder_info=False)
                await bot.send_message(
                    chat_id=eval_item.user_id,
                    text=formatted_text,
                    parse_mode='HTML'
                )

                # Jika ada gambar, kirim secara terpisah
                if image_file_id:
                    try:
                        await bot.send_photo(chat_id=eval_item.user_id, photo=image_file_id)
                    except Exception as e:
                        logger.error(f"Gagal mengirim foto untuk eval {eval_item.id} ke user {eval_item.user_id}: {e}")
                        await bot.send_message(chat_id=eval_item.user_id, text="<i>(Gagal mengirim gambar terkait.)</i>", parse_mode='HTML')
                # Kirim pemisah untuk kejelasan
                # Kirim pemisah untuk kejelasan
                await bot.send_message(chat_id=eval_item.user_id, text="---")

                # IMPORTANT: Update the database to mark it as sent
                database.update_last_reminder_sent(eval_item.id)
        except Exception as e:
            logger.error(f"Gagal mengirim pengingat untuk eval {eval_item.id} ke user {eval_item.user_id}: {e}")


def start_scheduler(bot: Bot):
    """
    Menambahkan tugas ke penjadwal dan memulainya.
    Tugas akan berjalan setiap menit.
    """
    if not scheduler.running:
        # Jalankan tugas 'send_reminders' setiap menit
        scheduler.add_job(send_reminders, CronTrigger(minute='*'), args=[bot])
        scheduler.start()
        logger.info("Scheduler started. Reminder job will run every minute.")


def shutdown_scheduler():
    """Mematikan penjadwal dengan aman."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shut down.")