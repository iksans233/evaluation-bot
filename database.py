from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, func
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, date
from dataclasses import dataclass
from contextlib import contextmanager
import logging
import config

Base = declarative_base()

# Get a logger for this module
logger = logging.getLogger(__name__)

# Data Transfer Object (DTO) for Evaluation
# This is used to pass data outside of SQLAlchemy sessions
from typing import Optional

@dataclass
class EvaluationDTO:
    id: int
    user_id: int
    text_note: Optional[str]
    image_file_id: Optional[str]
    timestamp: datetime
    reminder_enabled: bool
    reminder_time: Optional[str]
    last_reminder_sent: Optional[datetime]

class Evaluation(Base):
    __tablename__ = 'evaluations'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    text_note = Column(Text, nullable=True)
    image_file_id = Column(String, nullable=True) # Telegram file_id
    timestamp = Column(DateTime, default=datetime.utcnow)
    reminder_enabled = Column(Boolean, default=False)
    reminder_time = Column(String, nullable=True) # e.g., "05:00"
    last_reminder_sent = Column(DateTime, nullable=True) # Tracks the last time a reminder was sent

    def __repr__(self):
        return f"<Evaluation(id={self.id}, user_id={self.user_id}, text='{self.text_note[:20]}...')>"

# For SQLite, we need to allow access from multiple threads (main bot thread and scheduler thread)
connect_args = {}
if 'sqlite' in config.DATABASE_URL:
    connect_args = {"check_same_thread": False}

engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
Session = sessionmaker(bind=engine)

@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    session = Session()
    try:
        yield session
        session.commit()
    except Exception as e:
        logger.error(f"Database transaction failed: {e}")
        session.rollback()
        raise
    finally:
        session.close()

def init_db():
    Base.metadata.create_all(engine)

def save_evaluation(user_id, text_note=None, image_file_id=None) -> Optional[EvaluationDTO]:
    """Saves a new evaluation to the database and returns a DTO, or None on failure."""
    evaluation = Evaluation(
        user_id=user_id,
        text_note=text_note,
        image_file_id=image_file_id
    )
    try:
        with session_scope() as session:
            session.add(evaluation)
            session.flush() # Use flush to get the ID before the transaction is committed

            # Create DTO before session closes to avoid session-related issues
            evaluation_dto = EvaluationDTO(
                id=evaluation.id,
                user_id=evaluation.user_id,
                text_note=evaluation.text_note,
                image_file_id=evaluation.image_file_id,
                timestamp=evaluation.timestamp,
                reminder_enabled=evaluation.reminder_enabled,
                reminder_time=evaluation.reminder_time,
                last_reminder_sent=evaluation.last_reminder_sent
            )
            logger.info(f"Successfully saved evaluation with ID {evaluation.id} for user {user_id}.")
            return evaluation_dto
    except Exception:
        # The session_scope already logged the specific error
        logger.error(f"Could not save evaluation for user {user_id}.")
        return None

def get_all_evaluations(user_id) -> list[EvaluationDTO]:
    """Fetches all evaluations for a specific user."""
    try:
        with session_scope() as session:
            evaluations = session.query(Evaluation).filter_by(user_id=user_id).order_by(Evaluation.timestamp.desc()).all()
            return [
                EvaluationDTO(
                    id=eval.id,
                    user_id=eval.user_id,
                    text_note=eval.text_note,
                    image_file_id=eval.image_file_id,
                    timestamp=eval.timestamp,
                    reminder_enabled=eval.reminder_enabled,
                    reminder_time=eval.reminder_time,
                    last_reminder_sent=eval.last_reminder_sent
                ) for eval in evaluations
            ]
    except Exception:
        # The session_scope already logged the specific error
        logger.error(f"Could not fetch evaluations for user {user_id}.")
        return []

def get_evaluation_by_id(evaluation_id: int, user_id: int) -> Optional[EvaluationDTO]:
    """Fetches a single evaluation by its ID, ensuring it belongs to the user."""
    try:
        with session_scope() as session:
            eval_item = session.query(Evaluation).filter_by(id=evaluation_id, user_id=user_id).first()
            if eval_item:
                return EvaluationDTO(
                    id=eval_item.id,
                    user_id=eval_item.user_id,
                    text_note=eval_item.text_note,
                    image_file_id=eval_item.image_file_id,
                    timestamp=eval_item.timestamp,
                    reminder_enabled=eval_item.reminder_enabled,
                    reminder_time=eval_item.reminder_time,
                    last_reminder_sent=eval_item.last_reminder_sent
                )
            return None
    except Exception:
        # The session_scope already logged the specific error
        logger.error(f"Could not fetch evaluation {evaluation_id} for user {user_id}.")
        return None

def get_missed_reminders(now: datetime) -> list[EvaluationDTO]:
    """
    Fetches evaluations that have a reminder time that has passed today
    and for which a reminder has not yet been sent today.
    """
    today_utc_date = now.date()
    # The time is stored as 'HH:MM' string, so we compare it as a string.
    current_time_str = now.strftime('%H:%M')

    try:
        with session_scope() as session:
            evaluations = session.query(Evaluation).filter(
                Evaluation.reminder_enabled == True,
                Evaluation.reminder_time != None,
                Evaluation.reminder_time < current_time_str,
                (Evaluation.last_reminder_sent == None) | (func.date(Evaluation.last_reminder_sent) < today_utc_date)
            ).all()
            
            return [
                EvaluationDTO(
                    id=eval.id, user_id=eval.user_id, text_note=eval.text_note,
                    image_file_id=eval.image_file_id, timestamp=eval.timestamp,
                    reminder_enabled=eval.reminder_enabled, reminder_time=eval.reminder_time,
                    last_reminder_sent=eval.last_reminder_sent
                ) for eval in evaluations
            ]
    except Exception:
        logger.error(f"Failed to fetch missed reminders due to a database error.")
        return []

def get_due_reminders(time_str: str) -> list[EvaluationDTO]:
    """Fetches all enabled reminders scheduled for a specific time."""
    try:
        with session_scope() as session:
            today_utc = datetime.utcnow().date()
            # Ambil evaluasi yang waktunya cocok, belum dikirimi pengingat hari ini,
            # dan urutkan berdasarkan yang paling lama tidak dikirimi pengingat.
            evaluations = session.query(Evaluation).filter(
                Evaluation.reminder_enabled == True,
                Evaluation.reminder_time == time_str,
                (Evaluation.last_reminder_sent == None) | (func.date(Evaluation.last_reminder_sent) < today_utc)
            ).order_by(Evaluation.last_reminder_sent.asc().nullsfirst()).all()
            
            return [
                EvaluationDTO(
                    id=eval.id, user_id=eval.user_id, text_note=eval.text_note,
                    image_file_id=eval.image_file_id, timestamp=eval.timestamp,
                    reminder_enabled=eval.reminder_enabled, reminder_time=eval.reminder_time,
                    last_reminder_sent=eval.last_reminder_sent
                ) for eval in evaluations
            ]
    except Exception:
        logger.error(f"Failed to fetch due reminders for time {time_str} due to a database error.")
        return []

def delete_evaluation(evaluation_id, user_id):
    """Deletes an evaluation from the database if it belongs to the user."""
    try:
        with session_scope() as session:
            # Find the evaluation and ensure it belongs to the correct user
            evaluation = session.query(Evaluation).filter_by(id=evaluation_id, user_id=user_id).first()
            if evaluation:
                session.delete(evaluation)
                logger.info(f"Successfully deleted evaluation with ID {evaluation_id} for user {user_id}.")
                return True
            else:
                # Evaluation not found or doesn't belong to the user
                logger.warning(f"Attempt to delete non-existent or unauthorized evaluation ID {evaluation_id} by user {user_id}.")
                return False
    except Exception:
        logger.error(f"Failed to delete evaluation ID {evaluation_id} for user {user_id} due to a database error.")
        return False

def update_evaluation_reminder(evaluation_id, enabled, time=None):
    """Updates the reminder status for a given evaluation and returns True on success."""
    try:
        with session_scope() as session:
            evaluation = session.query(Evaluation).filter_by(id=evaluation_id).first()
            if not evaluation:
                logger.warning(f"Attempted to update non-existent evaluation ID {evaluation_id}.")
                return False # Not found
            
            evaluation.reminder_enabled = enabled
            evaluation.reminder_time = time if enabled else None
            if not enabled:
                evaluation.last_reminder_sent = None
            
            return True
    except Exception:
        logger.error(f"Failed to update reminder for evaluation ID {evaluation_id} due to a database error.")
        return False

def update_last_reminder_sent(evaluation_id):
    """Updates the last_reminder_sent timestamp for a given evaluation."""
    try:
        with session_scope() as session:
            evaluation = session.query(Evaluation).filter_by(id=evaluation_id).first()
            if evaluation:
                evaluation.last_reminder_sent = datetime.utcnow()
    except Exception:
        logger.error(f"Failed to update last_reminder_sent for evaluation ID {evaluation_id} due to a database error.")