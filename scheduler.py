import logging
from datetime import datetime, timedelta
import random, asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler # Ubah ke AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot

import database
import message_formatter # Import the new module

# Get a logger for this module
logger = logging.getLogger(__name__)

# Inisialisasi scheduler dengan zona waktu UTC
scheduler = AsyncIOScheduler(timezone='UTC') # Ubah ke AsyncIOScheduler

JOB_ID = 'daily_random_reminder'

async def check_and_send_daily_reminders(bot: Bot):
    """
    Runs every minute. It schedules a random time for today's reminder if not already set.
    If the current time matches the scheduled time, it sends the reminders.
    """
    now_utc = datetime.utcnow()
    job_state = database.get_or_create_job_state(JOB_ID)

    # Check if we need to schedule a new time for today
    if job_state.scheduled_time.date() < now_utc.date():
        # Generate a random time between 05:00 and 23:59 UTC
        random_hour = random.randint(5, 23)
        random_minute = random.randint(0, 59)
        new_scheduled_time = now_utc.replace(hour=random_hour, minute=random_minute, second=0, microsecond=0)
        
        logger.info(f"Scheduler: New random time for today is {new_scheduled_time.strftime('%H:%M')} UTC.")
        database.update_job_state(JOB_ID, new_scheduled_time)
        job_state.scheduled_time = new_scheduled_time

    # Check if it's time to run the job
    # We check a 1-minute window to ensure it runs even with minor delays.
    if job_state.scheduled_time <= now_utc < job_state.scheduled_time + timedelta(minutes=1):
        logger.info(f"Scheduler: It's time to send daily reminders at {now_utc.strftime('%H:%M')} UTC.")
        
        # Fetch all evaluations with reminders enabled
        all_active_evals = database.get_all_active_reminders()

        if not all_active_evals:
            logger.info("Scheduler: No active reminders to send.")
            return

        # --- LOGIKA BARU: Pilih 2 evaluasi secara acak ---
        REMINDER_LIMIT = 2
        num_to_sample = min(len(all_active_evals), REMINDER_LIMIT)
        selected_evaluations = random.sample(all_active_evals, num_to_sample)

        logger.info(f"Scheduler: Found {len(all_active_evals)} active reminders. Randomly selected {len(selected_evaluations)} to send.")

        # Send header message
        user_id = selected_evaluations[0].user_id # Assuming one user
        await bot.send_message(
            chat_id=user_id,
            text="🔔 Waktunya untuk evaluasi harian Anda! 🔔📝"
        )

        for eval_item in selected_evaluations:
            logger.info(f"Scheduler: Sending reminder for evaluation ID {eval_item.id} to user {eval_item.user_id}.")
            try:
                formatted_text, image_file_id = message_formatter.format_evaluation_message(eval_item, include_reminder_info=False)
                await bot.send_message(chat_id=eval_item.user_id, text=formatted_text, parse_mode='HTML')

                if image_file_id:
                    try:
                        await bot.send_photo(chat_id=eval_item.user_id, photo=image_file_id)
                    except Exception as e:
                        logger.error(f"Gagal mengirim foto untuk eval {eval_item.id} ke user {eval_item.user_id}: {e}")
                
                await bot.send_message(chat_id=eval_item.user_id, text="---")
                await asyncio.sleep(1) # Small delay to avoid rate limiting
            except Exception as e:
                logger.error(f"Gagal mengirim pengingat untuk eval {eval_item.id} ke user {eval_item.user_id}: {e}")


def start_scheduler(bot: Bot):
    """
    Menambahkan tugas ke penjadwal dan memulainya.
    Tugas akan berjalan setiap menit.
    """
    if not scheduler.running:
        # Jalankan tugas 'check_and_send_daily_reminders' setiap menit
        scheduler.add_job(check_and_send_daily_reminders, CronTrigger(minute='*'), args=[bot])
        scheduler.start()
        logger.info("Scheduler started. Reminder job will run every minute.")


def shutdown_scheduler():
    """Mematikan penjadwal dengan aman."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shut down.")