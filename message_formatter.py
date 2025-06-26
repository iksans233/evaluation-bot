from datetime import datetime
from typing import Tuple, Optional
from database import EvaluationDTO # Import the DTO

def format_evaluation_message(eval_item: EvaluationDTO, include_image_info: bool = True, include_reminder_info: bool = True) -> Tuple[str, Optional[str]]:
    """
    Formats an evaluation item into a human-readable message.
    Returns a tuple: (formatted_text_message, image_file_id_if_any)
    """
    message_parts = []
    message_parts.append(f"🆔 <b>ID:</b> {eval_item.id}")
    message_parts.append(f"⏰ <b>Waktu:</b> {eval_item.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")

    if eval_item.text_note:
        message_parts.append(f"📝 <b>Catatan:</b>")
        message_parts.append(f"<b>{eval_item.text_note}</b>")
    else:
        message_parts.append(f"📝 <b>Catatan:</b> Tidak ada catatan teks.")

    if include_image_info:
        if eval_item.image_file_id:
            message_parts.append(f"📸 <b>Gambar:</b> Ada")
        else:
            message_parts.append(f"📸 <b>Gambar:</b> Tidak ada")

    if include_reminder_info:
        reminder_status = "Aktif" if eval_item.reminder_enabled else "Tidak Aktif"
        reminder_time_str = f" pada {eval_item.reminder_time} UTC" if eval_item.reminder_time else ""
        message_parts.append(f"🔔 <b>Pengingat:</b> {reminder_status}{reminder_time_str}")

    return "\n".join(message_parts), eval_item.image_file_id