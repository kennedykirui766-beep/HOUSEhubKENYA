from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from flask_socketio import emit
from extensions import db, socketio
from models.models import User, ChatMessage
from datetime import datetime
import os
from werkzeug.utils import secure_filename
import base64

support_bp = Blueprint('support', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}
UPLOAD_FOLDER = 'static/uploads/chat'  # Ensure this directory exists


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@support_bp.route('/chat')
@login_required
def chat():
    messages = ChatMessage.query.filter(
        (ChatMessage.user_id == current_user.id) | (ChatMessage.support_agent_id == current_user.id)
    ).order_by(ChatMessage.timestamp.asc()).all()
    return render_template('support/chat.html', messages=messages, user=current_user)


@support_bp.route('/api/messages', methods=['GET'])
@login_required
def get_messages():
    messages = ChatMessage.query.filter(
        (ChatMessage.user_id == current_user.id) | (ChatMessage.support_agent_id == current_user.id)
    ).order_by(ChatMessage.timestamp.asc()).all()

    return jsonify([{
        'id': msg.id,
        'message': msg.message,
        'name': User.query.get(msg.user_id).name if msg.user_id else 'System',
        'timestamp': msg.timestamp.isoformat(),
        'is_sent': msg.user_id == current_user.id
    } for msg in messages])


@support_bp.route('/api/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, f"{current_user.id}_{filename}")
        file.save(filepath)

        file_url = url_for('static', filename=f'uploads/chat/{current_user.id}_{filename}')
        return jsonify({'url': file_url})

    return jsonify({'error': 'Invalid file type'}), 400


# Socket.IO events
@socketio.on('connect')
def handle_connect():
    print('Client connected')


@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')


@socketio.on('message')
def handle_message(data):
    last_msg = ChatMessage.query.filter_by(user_id=data['user_id']).order_by(ChatMessage.timestamp.desc()).first()
    if last_msg and (datetime.utcnow() - last_msg.timestamp).total_seconds() < 5:
        emit('rate_limit')
        return

    message = data['message'].strip()[:500]

    chat_msg = ChatMessage(
        user_id=data['user_id'],
        support_agent_id=data.get('agent_id'),
        message=message,
        timestamp=datetime.utcnow()
    )
    db.session.add(chat_msg)
    db.session.commit()

    emit('message', {
        'name': data['name'],
        'message': message,
        'timestamp': chat_msg.timestamp.isoformat(),
        'role': data.get('role', 'user')
    }, room=f"chat_{data['user_id']}")


@socketio.on('file_upload')
def handle_file_upload(data):
    file_data = base64.b64decode(data['fileData'])
    filename = secure_filename(data['fileName'])
    filepath = os.path.join(UPLOAD_FOLDER, f"{data['user_id']}_{filename}")

    with open(filepath, 'wb') as f:
        f.write(file_data)

    file_url = url_for('static', filename=f"uploads/chat/{data['user_id']}_{filename}")

    chat_msg = ChatMessage(
        user_id=data['user_id'],
        message=f"File uploaded: {data['fileName']} ({file_url})",
        timestamp=datetime.utcnow()
    )
    db.session.add(chat_msg)
    db.session.commit()

    emit('message', {
        'name': data['name'],
        'message': chat_msg.message,
        'timestamp': chat_msg.timestamp.isoformat()
    }, room=f"chat_{data['user_id']}")


@socketio.on('load_history')
def load_history(data):
    messages = ChatMessage.query.filter_by(user_id=data['user_id']).order_by(ChatMessage.timestamp.asc()).all()
    emit('chat_history', [{
        'name': User.query.get(msg.user_id).name if msg.user_id else 'System',
        'message': msg.message,
        'timestamp': msg.timestamp.isoformat(),
        'is_sent': msg.user_id == data['user_id']
    } for msg in messages])


@socketio.on('agent_status')
def agent_status(data):
    emit('agent_status', {'online': data['online']}, broadcast=True)


@support_bp.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role.lower() != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('main.index'))

    open_chats = ChatMessage.query.filter_by(is_read=False).all()
    return render_template('support/admin.html', chats=open_chats)
