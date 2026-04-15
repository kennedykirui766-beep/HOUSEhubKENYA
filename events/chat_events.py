from datetime import datetime
from app import socketio, db
from models.models import Message

@socketio.on("message_received")
def handle_received(data):
    msg = Message.query.get(data["message_id"])

    if msg:
        msg.delivered_at = datetime.utcnow()
        db.session.commit()