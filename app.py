"""
Kildear Social Network — Полная версия с исправленным мессенджером
Добавлены: ответ на сообщение, редактирование, удаление, пересылка, эмодзи
"""

import os
import re
import time
import uuid
import base64
import logging
import platform
import json
import secrets
import string
import hashlib
import hmac
from io import BytesIO
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from functools import wraps
from urllib.parse import urlparse, urljoin
from typing import Optional, Dict, Any, List

import requests
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, abort, session, send_from_directory,
                   make_response, Response)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                         login_required, current_user)
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.datastructures import FileStorage
from sqlalchemy import or_, func, and_, text
from PIL import Image
import qrcode
from authlib.integrations.flask_client import OAuth
from markupsafe import escape

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
#  App Configuration
# ──────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)

# Определяем окружение
is_production = os.environ.get('RENDER') == 'true' or os.environ.get('FLASK_ENV') == 'production'
is_render = os.environ.get('RENDER') == 'true'
is_windows = platform.system() == 'Windows'

# Определяем базовую директорию
basedir = os.path.abspath(os.path.dirname(__file__))

# Настройка базы данных
if is_render:
    database_url = os.environ.get('DATABASE_URL', '')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    if '?' in database_url:
        SQLALCHEMY_DATABASE_URI = database_url + '&sslmode=require'
    else:
        SQLALCHEMY_DATABASE_URI = database_url + '?sslmode=require'
else:
    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'instance', 'kildear.db')

# Настройки для загрузки файлов
if is_render:
    UPLOAD_FOLDER = '/tmp/uploads'
else:
    UPLOAD_FOLDER = os.path.join('static', 'uploads')

UPLOAD_SUBFOLDERS = ['images', 'videos', 'chat_images', 'custom_avatars', 'custom_covers']

ALLOWED_IMAGE = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_VIDEO = {"mp4", "webm", "mov", "avi", "mkv"}
ALLOWED_AUDIO = {"mp3", "wav", "ogg", "m4a"}

# OAuth Configuration
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
YANDEX_CLIENT_ID = os.environ.get('YANDEX_CLIENT_ID', '')
YANDEX_CLIENT_SECRET = os.environ.get('YANDEX_CLIENT_SECRET', '')
VK_CLIENT_ID = os.environ.get('VK_CLIENT_ID', '54623675')
VK_CLIENT_SECRET = os.environ.get('VK_CLIENT_SECRET', '3410Kv2UzDqdtXZeZisJ')

# Base URL for OAuth redirects
BASE_URL = os.environ.get('BASE_URL', 'https://kildear.onrender.com' if is_render else 'http://localhost:5000')

# Preset avatars for users (1-10)
PRESET_AVATARS: Dict[int, str] = {
    1: '/static/avatars/preset/1av.png',
    2: '/static/avatars/preset/2av.png',
    3: '/static/avatars/preset/3av.png',
    4: '/static/avatars/preset/4av.png',
    5: '/static/avatars/preset/5av.png',
    6: '/static/avatars/preset/6av.png',
    7: '/static/avatars/preset/7av.png',
    8: '/static/avatars/preset/8av.png',
    9: '/static/avatars/preset/9av.png',
    10: '/static/avatars/preset/10av.png',
}

# Preset covers for users (1-5)
PRESET_COVERS: Dict[int, str] = {
    1: '/static/covers/preset/1cover.jpg',
    2: '/static/covers/preset/2cover.jpg',
    3: '/static/covers/preset/3cover.jpg',
    4: '/static/covers/preset/4cover.jpg',
    5: '/static/covers/preset/5cover.jpg',
}

# Preset avatars for groups
PRESET_GROUP_AVATARS: Dict[int, str] = {
    1: '/static/group_avatars/preset/1.png',
    2: '/static/group_avatars/preset/2.png',
    3: '/static/group_avatars/preset/3.png',
    4: '/static/group_avatars/preset/4.png',
    5: '/static/group_avatars/preset/5.png',
    6: '/static/group_avatars/preset/6.png',
    7: '/static/group_avatars/preset/7.png',
    8: '/static/group_avatars/preset/8.png',
}

# Preset avatars for channels
PRESET_CHANNEL_AVATARS: Dict[int, str] = {
    1: '/static/channel_avatars/preset/1.png',
    2: '/static/channel_avatars/preset/2.png',
    3: '/static/channel_avatars/preset/3.png',
    4: '/static/channel_avatars/preset/4.png',
    5: '/static/channel_avatars/preset/5.png',
    6: '/static/channel_avatars/preset/6.png',
}

app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", secrets.token_hex(32)),
    SQLALCHEMY_DATABASE_URI=SQLALCHEMY_DATABASE_URI,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={
        "pool_pre_ping": True,
        "pool_recycle": 300,
    } if is_render else {},
    MAX_CONTENT_LENGTH=int(os.environ.get("MAX_CONTENT_LENGTH", 100 * 1024 * 1024)),
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    WTF_CSRF_TIME_LIMIT=3600,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=is_production,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    REMEMBER_COOKIE_DURATION=timedelta(days=14),
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SECURE=is_production,
    SESSION_REFRESH_EACH_REQUEST=True,
)

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_mgr = LoginManager(app)
login_mgr.login_view = "login"
login_mgr.login_message = "Пожалуйста, войдите для доступа к этой странице."
login_mgr.login_message_category = "info"

# Rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per minute", "2000 per hour"],
    storage_uri="memory://" if is_render else "memory://",
)

# Socket.IO
if is_render:
    async_mode = 'eventlet'
elif is_windows:
    async_mode = 'threading'
else:
    async_mode = 'eventlet'

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode=async_mode,
    logger=True,
    engineio_logger=True,
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=10e6
)

# OAuth Setup
oauth = OAuth(app)

# Google OAuth
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    oauth.register(
        name='google',
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )

# Yandex OAuth
if YANDEX_CLIENT_ID and YANDEX_CLIENT_SECRET:
    oauth.register(
        name='yandex',
        client_id=YANDEX_CLIENT_ID,
        client_secret=YANDEX_CLIENT_SECRET,
        access_token_url='https://oauth.yandex.ru/token',
        authorize_url='https://oauth.yandex.ru/authorize',
        api_base_url='https://login.yandex.ru/',
        client_kwargs={
            'scope': 'login:email login:avatar login:info',
        }
    )


# ──────────────────────────────────────────────────────────────────────────────
#  БЕЗОПАСНЫЕ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ──────────────────────────────────────────────────────────────────────────────

def escape_html(text: Any) -> str:
    """Безопасное экранирование HTML"""
    if text is None:
        return ""
    return escape(str(text))


def safe_path_join(base_dir: str, *paths: str) -> str:
    """Безопасное объединение путей с защитой от path traversal"""
    cleaned_paths = []
    for path in paths:
        if not path:
            continue
        clean_path = os.path.basename(str(path))
        if clean_path in ('', '.', '..'):
            raise ValueError("Invalid path component")
        cleaned_paths.append(clean_path)

    full_path = os.path.join(base_dir, *cleaned_paths)
    real_base = os.path.realpath(base_dir)
    real_path = os.path.realpath(full_path)

    if not real_path.startswith(real_base):
        raise ValueError("Path traversal detected")

    return full_path


def safe_validate_email(email: str) -> bool:
    """Безопасная валидация email без ReDoS уязвимостей"""
    if not email or len(email) > 254:
        return False

    if '@' not in email:
        return False

    local, domain = email.rsplit('@', 1)

    if len(local) > 64 or len(domain) > 255:
        return False

    allowed = string.ascii_letters + string.digits + "._-"

    for char in local:
        if char not in allowed:
            return False

    for char in domain:
        if char not in allowed + '.':
            return False

    return '.' in domain and '..' not in domain


def safe_validate_username(username: str) -> bool:
    """Безопасная валидация username"""
    if not username or len(username) > 40 or len(username) < 3:
        return False

    allowed = string.ascii_letters + string.digits + "_"
    return all(c in allowed for c in username)


def safe_validate_password(password: str) -> bool:
    """Валидация пароля"""
    if not password or len(password) < 8:
        return False
    return True


def is_safe_url(target: str) -> bool:
    """Проверка, безопасен ли URL для перенаправления"""
    if not target:
        return False

    if target.startswith('/') and not target.startswith('//'):
        return True

    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))

    return test_url.scheme in ('http', 'https') and \
        ref_url.netloc == test_url.netloc


def mask_sensitive_data(data: Any, show_chars: int = 3) -> str:
    """Маскирование чувствительных данных для логов"""
    if not data:
        return "***"
    data_str = str(data)
    if len(data_str) <= show_chars * 2:
        return "*" * len(data_str)
    return data_str[:show_chars] + "****" + data_str[-show_chars:]


def sanitize_filename(filename: str) -> Optional[str]:
    """Очистка имени файла от опасных символов"""
    if not filename:
        return None
    name, ext = os.path.splitext(filename)
    safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '', name)
    safe_ext = re.sub(r'[^a-zA-Z0-9.]', '', ext)
    if not safe_name:
        safe_name = str(uuid.uuid4().hex)[:16]
    result = f"{safe_name}{safe_ext}"[:255]
    return result if result else None


def get_post_lifetime_hours(follower_count: int) -> Optional[int]:
    """Получение времени жизни поста в зависимости от количества подписчиков"""
    if follower_count >= 5000:
        return 24
    elif follower_count >= 3000:
        return 18
    elif follower_count >= 2000:
        return 12
    elif follower_count >= 1000:
        return 6
    elif follower_count >= 500:
        return 3
    else:
        return None


def schedule_post_expiration(post_id: int, post_type: str = 'post', follower_count: int = 0) -> Optional[datetime]:
    """Планирование автоматического удаления поста"""
    hours = get_post_lifetime_hours(follower_count)
    if hours is None:
        return None

    expires_at = datetime.utcnow() + timedelta(hours=hours)

    if post_type == 'post':
        expiration = PostExpiration(post_id=post_id, expires_at=expires_at)
    elif post_type == 'group_post':
        expiration = GroupPostExpiration(post_id=post_id, expires_at=expires_at)
    elif post_type == 'channel_post':
        expiration = ChannelPostExpiration(post_id=post_id, expires_at=expires_at)
    else:
        return None

    db.session.add(expiration)
    db.session.commit()
    return expires_at


def cleanup_expired_posts() -> None:
    """Очистка истекших постов"""
    now = datetime.utcnow()
    expired_posts = PostExpiration.query.filter(
        PostExpiration.expires_at <= now,
        PostExpiration.is_deleted == False
    ).all()
    for exp in expired_posts:
        if exp.post:
            db.session.delete(exp.post)
        exp.is_deleted = True
    db.session.commit()


def save_custom_file(file: FileStorage, subfolder: str) -> Optional[str]:
    """Безопасное сохранение кастомного файла (аватар/обложка)"""
    if not file or not file.filename:
        return None
    try:
        safe_filename = sanitize_filename(file.filename)
        if not safe_filename:
            return None
        ext = safe_filename.rsplit('.', 1)[1].lower() if '.' in safe_filename else ''
        if ext not in ALLOWED_IMAGE:
            return None
        img = Image.open(file)
        if subfolder == 'custom_avatars':
            img = img.resize((200, 200), Image.Resampling.LANCZOS)
        elif subfolder == 'custom_covers':
            img = img.resize((1200, 400), Image.Resampling.LANCZOS)
        new_filename = f"{uuid.uuid4().hex}.{ext}"
        try:
            upload_path = safe_path_join(app.config['UPLOAD_FOLDER'], subfolder)
        except ValueError:
            return None
        os.makedirs(upload_path, exist_ok=True)
        file_path = os.path.join(upload_path, new_filename)
        img.save(file_path, optimize=True, quality=85)
        if is_render:
            return f"/uploads/{subfolder}/{new_filename}"
        else:
            return f"/static/uploads/{subfolder}/{new_filename}"
    except Exception as e:
        logger.error(f"Error saving custom file: {e}")
        return None


def save_file(file: FileStorage, subfolder: str) -> Optional[str]:
    """Безопасное сохранение файла (медиа для постов)"""
    if not file or not file.filename:
        return None
    try:
        safe_filename = sanitize_filename(file.filename)
        if not safe_filename:
            return None
        ext = safe_filename.rsplit('.', 1)[1].lower() if '.' in safe_filename else ''
        if not ext or ext not in ALLOWED_VIDEO:
            return None
        new_filename = f"{uuid.uuid4().hex}.{ext}"
        try:
            upload_path = safe_path_join(app.config['UPLOAD_FOLDER'], subfolder)
        except ValueError:
            return None
        os.makedirs(upload_path, exist_ok=True)
        file_path = os.path.join(upload_path, new_filename)
        file.save(file_path)
        if is_render:
            return f"/uploads/{subfolder}/{new_filename}"
        else:
            return f"/static/uploads/{subfolder}/{new_filename}"
    except Exception as e:
        logger.error(f"Error saving file: {e}")
        return None


def ensure_upload_folders() -> None:
    """Создание всех необходимых папок для загрузок"""
    for folder in UPLOAD_SUBFOLDERS:
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], folder)
        try:
            os.makedirs(folder_path, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create folder {folder_path}: {e}")

    preset_folders = [
        ('static', 'avatars', 'preset'),
        ('static', 'covers', 'preset'),
        ('static', 'group_avatars', 'preset'),
        ('static', 'channel_avatars', 'preset'),
    ]
    for *parts, last in preset_folders:
        folder_path = os.path.join(*parts, last)
        try:
            os.makedirs(folder_path, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create preset folder {folder_path}: {e}")


def get_client_ip() -> str:
    """Получение IP адреса клиента"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or '0.0.0.0'


def track_failure(ip: str) -> None:
    """Отслеживание неудачных попыток для защиты от брутфорса"""
    now = time.time()
    fails = [t for t in _fail_log[ip] if now - t < 300]
    fails.append(now)
    _fail_log[ip] = fails
    if len(fails) >= 20:
        _blocked_ips.add(ip)


def notification_link(notif) -> str:
    """Генерация ссылки для уведомления"""
    if notif.type in ['like', 'comment', 'mention']:
        if notif.post_id:
            return url_for('view_post', post_id=notif.post_id)
    elif notif.type == 'follow':
        if notif.from_user:
            return url_for('profile', username=notif.from_user.username)
    elif notif.type in ['missed_call', 'incoming_call', 'voice_message']:
        if notif.from_user:
            return url_for('chat', username=notif.from_user.username)
    return '#'


def notification_icon(notif) -> str:
    """Иконка для уведомления"""
    icons = {
        'like': '❤️', 'comment': '💬', 'follow': '👤', 'mention': '@',
        'group_post': '👥', 'channel_post': '📢', 'missed_call': '📞',
        'incoming_call': '📞', 'voice_message': '🎤', 'message': '💬'
    }
    return icons.get(notif.type, '🔔')


def notification_text(notif) -> str:
    """Текст уведомления"""
    if notif.text:
        return notif.text
    if notif.type == 'like':
        return f"{notif.from_user.username} liked your post"
    elif notif.type == 'comment':
        return f"{notif.from_user.username} commented on your post"
    elif notif.type == 'follow':
        return f"{notif.from_user.username} started following you"
    elif notif.type == 'mention':
        return f"{notif.from_user.username} mentioned you in a post"
    elif notif.type == 'group_post':
        return f"New post in group"
    elif notif.type == 'channel_post':
        return f"New post in channel"
    elif notif.type == 'missed_call':
        return f"Missed call from {notif.from_user.username}"
    elif notif.type == 'voice_message':
        return f"Voice message from {notif.from_user.username}"
    elif notif.type == 'message':
        return f"New message from {notif.from_user.username}"
    return "New notification"


def create_user_from_oauth(email: str, username: str, display_name: str, avatar_url: str = None):
    """Create a new user from OAuth data"""
    base_username = re.sub(r'[^a-zA-Z0-9_]', '_', username.lower())[:30]
    final_username = base_username
    counter = 1
    while User.query.filter_by(username=final_username).first():
        final_username = f"{base_username[:25]}_{counter}"
        counter += 1
    if not email:
        email = f"{final_username}@oauth.user"
    else:
        existing = User.query.filter_by(email=email).first()
        if existing:
            email = f"{final_username}_{uuid.uuid4().hex[:8]}@oauth.user"
    new_user = User(
        username=final_username,
        email=email,
        display_name=display_name[:60] if display_name else final_username,
        bio="",
        preset_avatar=1,
        is_verified=False,
        is_banned=False
    )
    new_user.set_password(secrets.token_urlsafe(16))
    db.session.add(new_user)
    db.session.flush()
    if avatar_url:
        try:
            response = requests.get(avatar_url, timeout=10)
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content))
                img = img.resize((200, 200), Image.Resampling.LANCZOS)
                avatar_filename = f"oauth_{new_user.id}_{uuid.uuid4().hex}.png"
                avatar_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'custom_avatars')
                os.makedirs(avatar_dir, exist_ok=True)
                img.save(os.path.join(avatar_dir, avatar_filename), "PNG")
                new_user.can_upload_custom_avatar = True
                if is_render:
                    new_user.custom_avatar = f"/uploads/custom_avatars/{avatar_filename}"
                else:
                    new_user.custom_avatar = f"/static/uploads/custom_avatars/{avatar_filename}"
        except Exception as e:
            logger.error(f"Failed to download avatar from OAuth: {e}")
    db.session.commit()
    return new_user


def generate_pkce_pair() -> tuple:
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip('=')
    return code_verifier, code_challenge


# ──────────────────────────────────────────────────────────────────────────────
#  Database Models
# ──────────────────────────────────────────────────────────────────────────────

follows = db.Table(
    "follows",
    db.Column("follower_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("followed_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
)

post_likes = db.Table(
    "post_likes",
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("post_id", db.Integer, db.ForeignKey("post.id"), primary_key=True),
)

group_members = db.Table(
    "group_members",
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("group_id", db.Integer, db.ForeignKey("group.id"), primary_key=True),
)

channel_subs = db.Table(
    "channel_subs",
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("channel_id", db.Integer, db.ForeignKey("channel.id"), primary_key=True),
)

blocks = db.Table(
    "blocks",
    db.Column("blocker_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("blocked_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
)


class InfoBanner(db.Model):
    __tablename__ = 'info_banner'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    banner_type = db.Column(db.String(20), default='info')
    is_active = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    expires_at = db.Column(db.DateTime, nullable=True)
    creator = db.relationship("User", foreign_keys=[created_by])


class User(UserMixin, db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    display_name = db.Column(db.String(60), default="")
    bio = db.Column(db.String(500), default="")

    preset_avatar = db.Column(db.Integer, default=1)
    preset_cover = db.Column(db.Integer, nullable=True)

    can_upload_custom_avatar = db.Column(db.Boolean, default=False)
    can_upload_custom_cover = db.Column(db.Boolean, default=False)
    custom_avatar = db.Column(db.String(300), nullable=True)
    custom_cover = db.Column(db.String(300), nullable=True)

    website = db.Column(db.String(200), default="")
    location = db.Column(db.String(100), default="")
    accent_color = db.Column(db.String(7), default="#6c63ff")
    is_private = db.Column(db.Boolean, default=False)
    is_verified = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_moderator = db.Column(db.Boolean, default=False)
    is_online = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_secret = db.Column(db.String(32), nullable=True)

    # Relationships
    following = db.relationship(
        "User", secondary=follows,
        primaryjoin=follows.c.follower_id == id,
        secondaryjoin=follows.c.followed_id == id,
        backref=db.backref("followers", lazy="dynamic"),
        lazy="dynamic"
    )

    blocked_users = db.relationship(
        "User", secondary=blocks,
        primaryjoin=blocks.c.blocker_id == id,
        secondaryjoin=blocks.c.blocked_id == id,
        backref=db.backref("blocked_by", lazy="dynamic"),
        lazy="dynamic"
    )

    posts = db.relationship("Post", backref="author", lazy="dynamic", foreign_keys="Post.user_id")

    # Исправленные связи с Message
    sent_messages = db.relationship("Message", foreign_keys="Message.sender_id", back_populates="sender",
                                    lazy="dynamic")
    received_messages = db.relationship("Message", foreign_keys="Message.receiver_id", back_populates="receiver",
                                        lazy="dynamic")

    notifications = db.relationship("Notification", backref="recipient", lazy="dynamic",
                                    foreign_keys="Notification.user_id")
    comments = db.relationship("Comment", backref="author", lazy="dynamic")
    owned_groups = db.relationship("Group", backref="owner", lazy="dynamic")
    owned_channels = db.relationship("Channel", backref="owner", lazy="dynamic")
    login_history = db.relationship("LoginHistory", backref="user", lazy="dynamic")

    @property
    def follower_count(self) -> int:
        return self.followers.count()

    @property
    def avatar_url(self) -> str:
        if self.custom_avatar and self.can_upload_custom_avatar:
            return self.custom_avatar
        if self.preset_avatar and self.preset_avatar in PRESET_AVATARS:
            return PRESET_AVATARS[self.preset_avatar]
        return PRESET_AVATARS[1]

    @property
    def cover_url(self) -> Optional[str]:
        if self.custom_cover and self.can_upload_custom_cover:
            return self.custom_cover
        if self.preset_cover and self.preset_cover in PRESET_COVERS:
            return PRESET_COVERS[self.preset_cover]
        return None

    def set_preset_avatar(self, avatar_num: int) -> bool:
        if 1 <= avatar_num <= 10:
            self.preset_avatar = avatar_num
            return True
        return False

    def set_preset_cover(self, cover_num: Optional[int]) -> bool:
        if cover_num is None:
            self.preset_cover = None
            return True
        if 1 <= cover_num <= 5:
            self.preset_cover = cover_num
            return True
        return False

    def check_and_update_permissions(self) -> Dict[str, bool]:
        follower_count = self.follower_count
        if follower_count >= 1000 and not self.can_upload_custom_avatar:
            self.can_upload_custom_avatar = True
            db.session.commit()
            logger.info(f"User {mask_sensitive_data(self.username)} gained custom avatar permission")
        if follower_count >= 5000 and not self.can_upload_custom_cover:
            self.can_upload_custom_cover = True
            db.session.commit()
            logger.info(f"User {mask_sensitive_data(self.username)} gained custom cover permission")
        return {
            'can_upload_custom_avatar': self.can_upload_custom_avatar,
            'can_upload_custom_cover': self.can_upload_custom_cover
        }

    def get_post_lifetime_hours(self) -> Optional[int]:
        count = self.follower_count
        if count >= 5000:
            return 24
        elif count >= 3000:
            return 18
        elif count >= 2000:
            return 12
        elif count >= 1000:
            return 6
        elif count >= 500:
            return 3
        else:
            return None

    def set_password(self, pw: str) -> None:
        """Установка пароля с принудительным использованием pbkdf2:sha256"""
        if pw and safe_validate_password(pw):
            self.password_hash = generate_password_hash(pw, method='pbkdf2:sha256')

    def check_password(self, pw: str) -> bool:
        """Проверка пароля с автоматической конвертацией из scrypt"""
        if not self.password_hash:
            return False

        # Проверяем пароль
        if check_password_hash(self.password_hash, pw):
            # Если это старый scrypt хеш - конвертируем в pbkdf2
            if 'scrypt' in self.password_hash:
                self.set_password(pw)  # Пересохраняем новым методом
                db.session.commit()
            return True
        return False

    def is_following(self, user) -> bool:
        return self.following.filter(follows.c.followed_id == user.id).count() > 0

    def is_blocked(self, user) -> bool:
        return self.blocked_users.filter(blocks.c.blocked_id == user.id).count() > 0

    def block(self, user) -> bool:
        if not self.is_blocked(user):
            self.blocked_users.append(user)
            return True
        return False

    def unblock(self, user) -> bool:
        if self.is_blocked(user):
            self.blocked_users.remove(user)
            return True
        return False

    @property
    def following_count(self) -> int:
        return self.following.count()

    @property
    def post_count(self) -> int:
        return self.posts.count()

    def get_settings(self):
        if not hasattr(self, '_settings_cache'):
            settings = UserSettings.query.filter_by(user_id=self.id).first()
            if not settings:
                settings = UserSettings(user_id=self.id)
                db.session.add(settings)
                db.session.commit()
            self._settings_cache = settings
        return self._settings_cache


class UserGoogle(db.Model):
    __tablename__ = 'user_google'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    google_id = db.Column(db.String(100), nullable=False, unique=True)
    google_email = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref=db.backref("google_connection", uselist=False))


class UserYandex(db.Model):
    __tablename__ = 'user_yandex'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    yandex_id = db.Column(db.String(100), nullable=False, unique=True)
    yandex_email = db.Column(db.String(120), nullable=True)
    yandex_login = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref=db.backref("yandex_connection", uselist=False))


class UserVK(db.Model):
    __tablename__ = 'user_vk'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    vk_id = db.Column(db.String(50), nullable=False, unique=True)
    vk_access_token = db.Column(db.String(500), nullable=True)
    vk_email = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref=db.backref("vk_connection", uselist=False))


class VerificationRequest(db.Model):
    __tablename__ = 'verification_request'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), default='pending')
    admin_comment = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    user = db.relationship("User", foreign_keys=[user_id])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])


class AdminApplication(db.Model):
    __tablename__ = 'admin_application'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    position = db.Column(db.String(20), nullable=False)
    contacts = db.Column(db.String(200), nullable=False)
    about = db.Column(db.Text, nullable=False)
    experience = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending')
    admin_comment = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    user = db.relationship("User", foreign_keys=[user_id])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])


class PostExpiration(db.Model):
    __tablename__ = 'post_expiration'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False)
    post = db.relationship("Post")


class GroupPostExpiration(db.Model):
    __tablename__ = 'group_post_expiration'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("group_post.id"), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False)
    post = db.relationship("GroupPost")


class ChannelPostExpiration(db.Model):
    __tablename__ = 'channel_post_expiration'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("channel_post.id"), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False)
    post = db.relationship("ChannelPost")


class UserSettings(db.Model):
    __tablename__ = 'user_settings'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)
    notify_likes = db.Column(db.Boolean, default=True)
    notify_comments = db.Column(db.Boolean, default=True)
    notify_follows = db.Column(db.Boolean, default=True)
    notify_messages = db.Column(db.Boolean, default=True)
    notify_voice_messages = db.Column(db.Boolean, default=True)
    notify_calls = db.Column(db.Boolean, default=True)
    notify_group_posts = db.Column(db.Boolean, default=True)
    notify_channel_posts = db.Column(db.Boolean, default=True)
    sound_enabled = db.Column(db.Boolean, default=True)
    sound_volume = db.Column(db.Integer, default=70)
    call_sound_enabled = db.Column(db.Boolean, default=True)
    notification_sound = db.Column(db.String(50), default="default")
    show_last_seen = db.Column(db.Boolean, default=True)
    show_online_status = db.Column(db.Boolean, default=True)
    allow_messages_from = db.Column(db.String(20), default="everyone")
    allow_calls_from = db.Column(db.String(20), default="everyone")
    allow_voice_messages_from = db.Column(db.String(20), default="everyone")
    show_profile_photo = db.Column(db.Boolean, default=True)
    show_bio = db.Column(db.Boolean, default=True)
    chat_background = db.Column(db.String(200), default="")
    bubble_color_own = db.Column(db.String(7), default="#6c63ff")
    bubble_color_other = db.Column(db.String(7), default="#e4e6eb")
    enter_to_send = db.Column(db.Boolean, default=False)
    show_typing = db.Column(db.Boolean, default=True)
    show_read_receipts = db.Column(db.Boolean, default=True)
    theme = db.Column(db.String(20), default="dark")
    font_size = db.Column(db.String(10), default="medium")
    chat_font_size = db.Column(db.String(10), default="medium")
    default_scale = db.Column(db.Integer, default=100)
    animations_enabled = db.Column(db.Boolean, default=True)
    animation_speed = db.Column(db.String(10), default="normal")
    language = db.Column(db.String(10), default="ru")
    folders_data = db.Column(db.Text, default="[]")
    save_edited_messages = db.Column(db.Boolean, default=True)
    auto_delete_messages = db.Column(db.Integer, default=0)
    data_saver_mode = db.Column(db.Boolean, default=False)
    auto_play_videos = db.Column(db.Boolean, default=True)
    auto_play_gifs = db.Column(db.Boolean, default=True)
    camera_enabled = db.Column(db.Boolean, default=True)
    mic_enabled = db.Column(db.Boolean, default=True)
    battery_saver_mode = db.Column(db.Boolean, default=False)
    reduce_animations = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = db.relationship("User", backref=db.backref("settings", uselist=False))


class LoginHistory(db.Model):
    __tablename__ = 'login_history'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    ip_address = db.Column(db.String(45), nullable=False)
    user_agent = db.Column(db.String(200))
    location = db.Column(db.String(100))
    success = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class VoiceMessage(db.Model):
    __tablename__ = 'voice_message'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    audio_data = db.Column(db.Text, nullable=False)
    audio_mime = db.Column(db.String(50), default="audio/mpeg")
    audio_url = db.Column(db.String(300), default="")
    duration = db.Column(db.Integer, default=0)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def audio_url_data(self) -> str:
        if self.audio_data:
            return f"data:{self.audio_mime};base64,{self.audio_data}"
        return self.audio_url

    sender = db.relationship("User", foreign_keys=[sender_id], backref="sent_voice_msgs")
    receiver = db.relationship("User", foreign_keys=[receiver_id], backref="received_voice_msgs")


class Call(db.Model):
    __tablename__ = 'call'
    id = db.Column(db.Integer, primary_key=True)
    caller_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    callee_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    call_type = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(20), default='missed')
    duration = db.Column(db.Integer, default=0)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime, nullable=True)
    caller = db.relationship("User", foreign_keys=[caller_id])
    callee = db.relationship("User", foreign_keys=[callee_id])


class Report(db.Model):
    __tablename__ = 'report'
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reported_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey("comment.id"), nullable=True)
    reason = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    reporter = db.relationship("User", foreign_keys=[reporter_id])
    reported_user = db.relationship("User", foreign_keys=[reported_user_id])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])


class Post(db.Model):
    __tablename__ = 'post'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, default="")
    media_url = db.Column(db.String(300), default="")
    media_type = db.Column(db.String(20), default="text")
    thumbnail = db.Column(db.String(300), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    views = db.Column(db.Integer, default=0)
    liked_by = db.relationship("User", secondary=post_likes, backref="liked_posts", lazy="dynamic")
    comments = db.relationship("Comment", backref="post", lazy="dynamic", cascade="all,delete")
    expiration = db.relationship("PostExpiration", backref="post_rel", uselist=False, cascade="all,delete")

    @property
    def like_count(self) -> int:
        return self.liked_by.count()

    @property
    def comment_count(self) -> int:
        return self.comments.count()

    def is_liked_by(self, user) -> bool:
        return self.liked_by.filter(post_likes.c.user_id == user.id).count() > 0


class Comment(db.Model):
    __tablename__ = 'comment'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Message(db.Model):
    __tablename__ = 'message'

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, default="")
    media_url = db.Column(db.String(300), default="")
    is_read = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)
    is_edited = db.Column(db.Boolean, default=False)
    edit_count = db.Column(db.Integer, default=0)
    reply_to_id = db.Column(db.Integer, db.ForeignKey("message.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships - исправлено
    reply_to = db.relationship("Message", remote_side=[id], backref=db.backref("replies", lazy="dynamic"))

    sender = db.relationship("User", foreign_keys=[sender_id], back_populates="sent_messages")
    receiver = db.relationship("User", foreign_keys=[receiver_id], back_populates="received_messages")


class Group(db.Model):
    __tablename__ = 'group'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, default="")
    preset_avatar = db.Column(db.Integer, default=1)
    cover = db.Column(db.String(300), default="")
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    is_private = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    members = db.relationship("User", secondary=group_members, backref="groups", lazy="dynamic")
    posts = db.relationship("GroupPost", backref="group", lazy="dynamic", cascade="all,delete")

    @property
    def member_count(self) -> int:
        return self.members.count()

    @property
    def avatar_url(self) -> str:
        if self.preset_avatar and self.preset_avatar in PRESET_GROUP_AVATARS:
            return PRESET_GROUP_AVATARS[self.preset_avatar]
        return PRESET_GROUP_AVATARS[1]

    def set_preset_avatar(self, avatar_num: int) -> bool:
        if avatar_num in PRESET_GROUP_AVATARS:
            self.preset_avatar = avatar_num
            return True
        return False


class GroupPost(db.Model):
    __tablename__ = 'group_post'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, default="")
    media_url = db.Column(db.String(300), default="")
    media_type = db.Column(db.String(20), default="text")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    author = db.relationship("User")
    expiration = db.relationship("GroupPostExpiration", backref="post_rel", uselist=False, cascade="all,delete")


class Channel(db.Model):
    __tablename__ = 'channel'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, default="")
    preset_avatar = db.Column(db.Integer, default=1)
    cover = db.Column(db.String(300), default="")
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    is_nsfw = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subscribers = db.relationship("User", secondary=channel_subs, backref="subscribed_channels", lazy="dynamic")
    posts = db.relationship("ChannelPost", backref="channel", lazy="dynamic", cascade="all,delete")

    @property
    def sub_count(self) -> int:
        return self.subscribers.count()

    @property
    def avatar_url(self) -> str:
        if self.preset_avatar and self.preset_avatar in PRESET_CHANNEL_AVATARS:
            return PRESET_CHANNEL_AVATARS[self.preset_avatar]
        return PRESET_CHANNEL_AVATARS[1]

    def set_preset_avatar(self, avatar_num: int) -> bool:
        if avatar_num in PRESET_CHANNEL_AVATARS:
            self.preset_avatar = avatar_num
            return True
        return False


class ChannelPost(db.Model):
    __tablename__ = 'channel_post'
    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey("channel.id"), nullable=False)
    content = db.Column(db.Text, default="")
    media_url = db.Column(db.String(300), default="")
    media_type = db.Column(db.String(20), default="text")
    views = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expiration = db.relationship("ChannelPostExpiration", backref="post_rel", uselist=False, cascade="all,delete")


class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    type = db.Column(db.String(30), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=True)
    call_id = db.Column(db.Integer, db.ForeignKey("call.id"), nullable=True)
    text = db.Column(db.String(300), default="")
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    from_user = db.relationship("User", foreign_keys=[from_user_id])
    call = db.relationship("Call", foreign_keys=[call_id])


class UserAchievement(db.Model):
    __tablename__ = 'user_achievement'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    achievement_type = db.Column(db.String(50), nullable=False)
    achieved_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref="achievements")


# ──────────────────────────────────────────────────────────────────────────────
#  Template Filters
# ──────────────────────────────────────────────────────────────────────────────

@app.template_filter('timeago')
def timeago_filter(date):
    if not date:
        return 'recently'
    now = datetime.utcnow()
    diff = now - date
    if diff.days > 365:
        return f"{diff.days // 365}y ago"
    elif diff.days > 30:
        return f"{diff.days // 30}mo ago"
    elif diff.days > 0:
        return f"{diff.days}d ago"
    elif diff.seconds > 3600:
        return f"{diff.seconds // 3600}h ago"
    elif diff.seconds > 60:
        return f"{diff.seconds // 60}m ago"
    else:
        return "just now"


@app.template_filter('format_date')
def format_date_filter(date, format='%b %d, %Y'):
    return date.strftime(format) if date else ''


@app.template_filter('format_time')
def format_time_filter(date, format='%H:%M'):
    return date.strftime(format) if date else ''


@app.template_filter('escape_js')
def escape_js_filter(text):
    if not text:
        return ""
    return escape(str(text)).replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"')


# ──────────────────────────────────────────────────────────────────────────────
#  Auth loader
# ──────────────────────────────────────────────────────────────────────────────

@login_mgr.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ──────────────────────────────────────────────────────────────────────────────
#  Context Processors
# ──────────────────────────────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    unread = 0
    notif_count = 0
    stats = {}
    if current_user.is_authenticated:
        unread = Message.query.filter_by(
            receiver_id=current_user.id, is_read=False, is_deleted=False).count()
        notif_count = Notification.query.filter_by(
            user_id=current_user.id, is_read=False).count()
        if current_user.is_admin:
            stats['total_reports'] = Report.query.filter_by(status='pending').count()
            stats['pending_verification'] = VerificationRequest.query.filter_by(status='pending').count()
            stats['pending_admin_apps'] = AdminApplication.query.filter_by(status='pending').count()
            stats['banned_users'] = User.query.filter_by(is_banned=True).count()
            stats['active_banners'] = InfoBanner.query.filter_by(is_active=True).count()
    return dict(
        unread_messages=unread,
        notif_count=notif_count,
        stats=stats,
        csrf_token=generate_csrf,
        notification_link=notification_link,
        notification_icon=notification_icon,
        notification_text=notification_text,
        now=datetime.utcnow(),
        is_production=is_production,
        preset_avatars=PRESET_AVATARS,
        preset_covers=PRESET_COVERS,
        preset_group_avatars=PRESET_GROUP_AVATARS,
        preset_channel_avatars=PRESET_CHANNEL_AVATARS
    )


# ──────────────────────────────────────────────────────────────────────────────
#  DDoS Protection
# ──────────────────────────────────────────────────────────────────────────────

_req_log: Dict[str, List[float]] = defaultdict(list)
_blocked_ips: set = set()
_fail_log: Dict[str, List[float]] = defaultdict(list)


@app.before_request
def ddos_shield():
    ip = get_client_ip()
    if ip in _blocked_ips:
        abort(429)
    now = time.time()
    window = [t for t in _req_log[ip] if now - t < 10]
    window.append(now)
    _req_log[ip] = window
    if len(window) > 200:
        _blocked_ips.add(ip)
        app.logger.warning(f"[DDoS] Blocked IP: {mask_sensitive_data(ip)}")
        abort(429)
    if request.content_length and request.content_length > app.config["MAX_CONTENT_LENGTH"]:
        abort(413)


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    csp = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://cdn.socket.io https://cdnjs.cloudflare.com https://unpkg.com https://accounts.google.com https://oauth.vk.com https://login.yandex.ru",
        "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com",
        "font-src 'self' https://cdnjs.cloudflare.com",
        "img-src 'self' data: blob: https:",
        "media-src 'self' blob:",
        "connect-src 'self' wss: ws:",
        "frame-ancestors 'none'",
        "frame-src https://oauth.vk.com https://accounts.google.com https://login.yandex.ru"
    ]
    response.headers["Content-Security-Policy"] = '; '.join(csp)
    return response


# ──────────────────────────────────────────────────────────────────────────────
#  Декоратор для проверки прав администратора
# ──────────────────────────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)

    return decorated_function


# ──────────────────────────────────────────────────────────────────────────────
#  Google OAuth Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/login/google")
def login_google():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        flash("Google авторизация временно недоступна", "error")
        return redirect(url_for("login"))
    redirect_uri = url_for("google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/login/google/callback")
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
        user_info = oauth.google.parse_id_token(token)
        google_id = user_info.get('sub')
        email = user_info.get('email', '')
        name = user_info.get('name', '')
        avatar = user_info.get('picture', '')
        if not google_id:
            flash("Не удалось получить данные от Google", "error")
            return redirect(url_for("login"))
        existing_google = UserGoogle.query.filter_by(google_id=google_id).first()
        if existing_google:
            user = existing_google.user
            if user.is_banned:
                flash("Пользователь заблокирован", "error")
                return redirect(url_for("login"))
            login_user(user, remember=True)
            flash(f"Добро пожаловать, {escape_html(user.display_name or user.username)}!", "success")
            return redirect(url_for("index"))
        existing_user = None
        if email:
            existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            google_conn = UserGoogle(user_id=existing_user.id, google_id=google_id, google_email=email)
            db.session.add(google_conn)
            db.session.commit()
            login_user(existing_user, remember=True)
            flash(f"Аккаунт Google привязан к {escape_html(existing_user.username)}!", "success")
            return redirect(url_for("index"))
        username = re.sub(r'[^a-zA-Z0-9_]', '_', name.lower())[:30] if name else f"google_{google_id[:8]}"
        new_user = create_user_from_oauth(email, username, name, avatar)
        db.session.commit()
        google_conn = UserGoogle(user_id=new_user.id, google_id=google_id, google_email=email)
        db.session.add(google_conn)
        db.session.commit()
        login_user(new_user, remember=True)
        flash("Успешная регистрация через Google!", "success")
        return redirect(url_for("index"))
    except Exception as e:
        logger.error(f"Google OAuth error: {e}")
        flash("Ошибка при авторизации через Google", "error")
        return redirect(url_for("login"))


# ──────────────────────────────────────────────────────────────────────────────
#  Yandex OAuth Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/login/yandex")
def login_yandex():
    if not YANDEX_CLIENT_ID or not YANDEX_CLIENT_SECRET:
        flash("Яндекс авторизация временно недоступна", "error")
        return redirect(url_for("login"))
    redirect_uri = f"{BASE_URL}/login/yandex/callback"
    return oauth.yandex.authorize_redirect(redirect_uri)


@app.route("/login/yandex/callback")
def yandex_callback():
    try:
        token = oauth.yandex.authorize_access_token()
        resp = oauth.yandex.get('info')
        user_info = resp.json()
        yandex_id = str(user_info.get('id', ''))
        email = user_info.get('default_email', '')
        login = user_info.get('login', '')
        name = user_info.get('real_name', '') or user_info.get('display_name', '') or login
        avatar_url = user_info.get('avatar_url', '')
        if not yandex_id:
            flash("Не удалось получить данные от Яндекса", "error")
            return redirect(url_for("login"))
        existing_yandex = UserYandex.query.filter_by(yandex_id=yandex_id).first()
        if existing_yandex:
            user = existing_yandex.user
            if user.is_banned:
                flash("Пользователь заблокирован", "error")
                return redirect(url_for("login"))
            login_user(user, remember=True)
            flash(f"Добро пожаловать, {escape_html(user.display_name or user.username)}!", "success")
            return redirect(url_for("index"))
        existing_user = None
        if email:
            existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            yandex_conn = UserYandex(user_id=existing_user.id, yandex_id=yandex_id, yandex_email=email,
                                     yandex_login=login)
            db.session.add(yandex_conn)
            db.session.commit()
            login_user(existing_user, remember=True)
            flash(f"Аккаунт Яндекса привязан к {escape_html(existing_user.username)}!", "success")
            return redirect(url_for("index"))
        username = re.sub(r'[^a-zA-Z0-9_]', '_', login)[:30] if login else f"yandex_{yandex_id[:8]}"
        new_user = create_user_from_oauth(email, username, name, avatar_url)
        yandex_conn = UserYandex(user_id=new_user.id, yandex_id=yandex_id, yandex_email=email, yandex_login=login)
        db.session.add(yandex_conn)
        db.session.commit()
        login_user(new_user, remember=True)
        flash("Успешная регистрация через Яндекс!", "success")
        return redirect(url_for("index"))
    except Exception as e:
        logger.error(f"Yandex OAuth error: {e}")
        flash("Ошибка при авторизации через Яндекс", "error")
        return redirect(url_for("login"))


# ──────────────────────────────────────────────────────────────────────────────
#  VK OAuth Routes
# ──────────────────────────────────────────────────────────────────────────────

VK_REDIRECT_URI = f"{BASE_URL}/login/vk/callback"


@app.route("/login/vk")
def login_vk():
    from urllib.parse import quote
    code_verifier, code_challenge = generate_pkce_pair()
    session['vk_code_verifier'] = code_verifier
    session['vk_oauth_state'] = secrets.token_urlsafe(32)
    auth_url = (f"https://id.vk.ru/authorize?response_type=code&client_id={VK_CLIENT_ID}&"
                f"redirect_uri={quote(VK_REDIRECT_URI)}&scope=email&state={session['vk_oauth_state']}&"
                f"code_challenge={code_challenge}&code_challenge_method=S256&lang_id=0")
    return redirect(auth_url)


@app.route("/login/vk/callback")
def login_vk_callback():
    code = request.args.get("code")
    error = request.args.get("error")
    error_description = request.args.get("error_description")
    state = request.args.get("state")
    device_id = request.args.get("device_id")
    expected_state = session.pop('vk_oauth_state', None)
    code_verifier = session.pop('vk_code_verifier', None)
    if not expected_state or state != expected_state:
        flash("Ошибка безопасности при авторизации", "error")
        return redirect(url_for("login"))
    if error:
        flash(f"Ошибка авторизации ВК: {error_description or error}", "error")
        return redirect(url_for("login"))
    if not code:
        flash("Не получен код авторизации", "error")
        return redirect(url_for("login"))
    if not code_verifier:
        flash("Ошибка: отсутствует code_verifier", "error")
        return redirect(url_for("login"))
    try:
        token_url = "https://id.vk.ru/oauth2/auth"
        params = {"grant_type": "authorization_code", "client_id": VK_CLIENT_ID,
                  "client_secret": VK_CLIENT_SECRET, "code": code, "code_verifier": code_verifier,
                  "redirect_uri": VK_REDIRECT_URI}
        if device_id:
            params["device_id"] = device_id
        response = requests.post(token_url, data=params)
        token_data = response.json()
        if "error" in token_data:
            flash(f"Ошибка получения токена: {token_data.get('error_description', token_data.get('error'))}", "error")
            return redirect(url_for("login"))
        access_token = token_data.get("access_token")
        vk_user_id = str(token_data.get("user_id", ""))
        email = token_data.get("email", "")
        if not vk_user_id:
            flash("Не удалось получить ID пользователя VK", "error")
            return redirect(url_for("login"))
        user_info_url = "https://id.vk.ru/oauth2/user_info"
        user_info_params = {"access_token": access_token, "client_id": VK_CLIENT_ID}
        user_response = requests.get(user_info_url, params=user_info_params)
        user_data = user_response.json()
        first_name = ""
        last_name = ""
        vk_avatar = ""
        if "user" in user_data:
            vk_user = user_data["user"]
            first_name = vk_user.get("first_name", "")
            last_name = vk_user.get("last_name", "")
            vk_avatar = vk_user.get("avatar", "")
        display_name = f"{first_name} {last_name}".strip() or f"user_{vk_user_id}"
        existing_vk = UserVK.query.filter_by(vk_id=vk_user_id).first()
        if existing_vk:
            user = existing_vk.user
            if user.is_banned:
                flash("Пользователь заблокирован", "error")
                return redirect(url_for("login"))
            login_user(user, remember=True)
            flash(f"Добро пожаловать, {escape_html(user.display_name or user.username)}!", "success")
            return redirect(url_for("index"))
        existing_user = None
        if email:
            existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            vk_conn = UserVK(user_id=existing_user.id, vk_id=vk_user_id, vk_access_token=access_token, vk_email=email)
            db.session.add(vk_conn)
            db.session.commit()
            login_user(existing_user, remember=True)
            flash(f"Аккаунт ВКонтакте привязан к {escape_html(existing_user.username)}!", "success")
            return redirect(url_for("index"))
        username = re.sub(r'[^a-zA-Z0-9_]', '_', display_name.lower().replace(" ", "_"))[:30]
        new_user = create_user_from_oauth(email, username, display_name, vk_avatar)
        vk_conn = UserVK(user_id=new_user.id, vk_id=vk_user_id, vk_access_token=access_token, vk_email=email)
        db.session.add(vk_conn)
        db.session.commit()
        login_user(new_user, remember=True)
        flash("Успешная регистрация через ВКонтакте!", "success")
        return redirect(url_for("index"))
    except Exception as e:
        logger.error(f"VK callback error: {e}")
        db.session.rollback()
        flash("Произошла ошибка при авторизации", "error")
        return redirect(url_for("login"))


# ──────────────────────────────────────────────────────────────────────────────
#  OAuth Settings Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/settings/oauth")
@login_required
def settings_oauth():
    google_conn = UserGoogle.query.filter_by(user_id=current_user.id).first()
    yandex_conn = UserYandex.query.filter_by(user_id=current_user.id).first()
    vk_conn = UserVK.query.filter_by(user_id=current_user.id).first()
    return render_template("settings/oauth.html", google_conn=google_conn, yandex_conn=yandex_conn, vk_conn=vk_conn)


@app.route("/settings/google/disconnect", methods=["POST"])
@login_required
def disconnect_google():
    google_conn = UserGoogle.query.filter_by(user_id=current_user.id).first()
    if google_conn:
        db.session.delete(google_conn)
        db.session.commit()
        flash("Аккаунт Google отключен", "success")
    return redirect(url_for("settings_oauth"))


@app.route("/settings/yandex/disconnect", methods=["POST"])
@login_required
def disconnect_yandex():
    yandex_conn = UserYandex.query.filter_by(user_id=current_user.id).first()
    if yandex_conn:
        db.session.delete(yandex_conn)
        db.session.commit()
        flash("Аккаунт Яндекса отключен", "success")
    return redirect(url_for("settings_oauth"))


@app.route("/settings/vk/disconnect", methods=["POST"])
@login_required
def disconnect_vk():
    vk_conn = UserVK.query.filter_by(user_id=current_user.id).first()
    if vk_conn:
        db.session.delete(vk_conn)
        db.session.commit()
        flash("Аккаунт VK отключен", "success")
    return redirect(url_for("settings_oauth"))


# ──────────────────────────────────────────────────────────────────────────────
#  QR Code Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/qr/scan", methods=["GET"])
@login_required
def scan_qr_page():
    return render_template("scan_qr.html")


@app.route("/qr/search", methods=["POST"])
@login_required
def search_by_qr():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    qr_data = data.get("qr_data", "").strip()
    if len(qr_data) > 200:
        return jsonify({"error": "QR data too long"}), 400
    username = None
    if re.match(r'^[a-zA-Z0-9_]{3,40}$', qr_data):
        username = qr_data
    elif qr_data.startswith("kildear://user/"):
        username = qr_data.replace("kildear://user/", "")[:40]
    elif '/u/' in qr_data:
        parts = qr_data.split('/u/')
        if len(parts) > 1:
            username = parts[1].split('/')[0].split('?')[0][:40]
    elif '/profile/' in qr_data:
        parts = qr_data.split('/profile/')
        if len(parts) > 1:
            username = parts[1].split('/')[0].split('?')[0][:40]
    if not username or not safe_validate_username(username):
        return jsonify({"error": "Invalid QR code format"}), 400
    user = User.query.filter(func.lower(User.username) == username.lower()).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    if current_user.is_blocked(user):
        return jsonify({"error": "You have blocked this user"}), 403
    if user.is_banned:
        return jsonify({"error": "This user is banned"}), 403
    return jsonify({
        "success": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": escape_html(user.display_name or user.username),
            "avatar": user.avatar_url,
            "bio": escape_html(user.bio),
            "is_following": current_user.is_following(user),
            "follower_count": user.follower_count,
            "following_count": user.following_count,
            "post_count": user.post_count,
            "is_verified": user.is_verified
        }
    })


@app.route("/user/<int:user_id>/qrcode")
@login_required
def generate_user_qrcode(user_id):
    user = User.query.get_or_404(user_id)
    if current_user.is_blocked(user):
        return jsonify({"error": "Cannot view blocked user's QR code"}), 403
    if user.is_banned:
        return jsonify({"error": "User is banned"}), 403
    base_url = f"{request.scheme}://{request.host}"
    profile_url = f"{base_url}/u/{user.username}"
    qr_data = f"kildear://user/{user.username}\n{profile_url}"
    try:
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode()
        return jsonify({
            "success": True,
            "qr_code": f"data:image/png;base64,{img_base64}",
            "data": qr_data,
            "username": user.username,
            "display_name": escape_html(user.display_name or user.username),
            "profile_url": profile_url
        })
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        return jsonify({"success": False, "error": "Failed to generate QR code"}), 500


# ──────────────────────────────────────────────────────────────────────────────
#  Info Banner Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/admin/banners")
@login_required
@admin_required
def admin_banners():
    banners = InfoBanner.query.order_by(InfoBanner.order).all()
    return render_template("admin/banners.html", banners=banners)


@app.route("/admin/banners/create", methods=["POST"])
@login_required
@admin_required
def create_banner():
    try:
        title = escape_html(request.form.get("title", "").strip())
        content = escape_html(request.form.get("content", "").strip())
        banner_type = request.form.get("banner_type", "info")
        order = int(request.form.get("order", 0))
        expires_days = request.form.get("expires_days", type=int)
        if not title or not content:
            flash("Заполните заголовок и содержание", "error")
            return redirect(url_for("admin_banners"))
        expires_at = None
        if expires_days and expires_days > 0:
            expires_at = datetime.utcnow() + timedelta(days=expires_days)
        existing = InfoBanner.query.filter_by(order=order).first()
        if existing:
            banners_to_update = InfoBanner.query.filter(InfoBanner.order >= order).all()
            for banner in banners_to_update:
                banner.order += 1
            db.session.commit()
        banner = InfoBanner(title=title, content=content, banner_type=banner_type, is_active=True,
                            order=order, created_by=current_user.id, expires_at=expires_at)
        db.session.add(banner)
        db.session.commit()
        flash(f"Баннер '{title}' создан", "success")
    except Exception as e:
        logger.error(f"Error creating banner: {e}")
        flash("Ошибка при создании баннера", "error")
    return redirect(url_for("admin_banners"))


@app.route("/admin/banners/<int:banner_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_banner(banner_id):
    banner = InfoBanner.query.get_or_404(banner_id)
    banner.is_active = not banner.is_active
    db.session.commit()
    status = "активен" if banner.is_active else "неактивен"
    flash(f"Баннер '{banner.title}' теперь {status}", "success")
    return redirect(url_for("admin_banners"))


@app.route("/admin/banners/<int:banner_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_banner(banner_id):
    banner = InfoBanner.query.get_or_404(banner_id)
    title = banner.title
    db.session.delete(banner)
    db.session.commit()
    flash(f"Баннер '{title}' удален", "success")
    return redirect(url_for("admin_banners"))


@app.route("/admin/banners/<int:banner_id>/edit", methods=["POST"])
@login_required
@admin_required
def edit_banner(banner_id):
    banner = InfoBanner.query.get_or_404(banner_id)
    try:
        banner.title = escape_html(request.form.get("title", "").strip())
        banner.content = escape_html(request.form.get("content", "").strip())
        banner.banner_type = request.form.get("banner_type", "info")
        expires_days = request.form.get("expires_days", type=int)
        if expires_days and expires_days > 0:
            banner.expires_at = datetime.utcnow() + timedelta(days=expires_days)
        else:
            banner.expires_at = None
        db.session.commit()
        flash(f"Баннер '{banner.title}' обновлен", "success")
    except Exception as e:
        logger.error(f"Error editing banner: {e}")
        flash("Ошибка при обновлении баннера", "error")
    return redirect(url_for("admin_banners"))


@app.route("/admin/banners/<int:banner_id>/data")
@login_required
@admin_required
def get_banner_data(banner_id):
    banner = InfoBanner.query.get_or_404(banner_id)
    return jsonify({"title": banner.title, "content": banner.content, "banner_type": banner.banner_type})


@app.route("/api/banners/active")
def get_active_banners():
    now = datetime.utcnow()
    banners = InfoBanner.query.filter(
        InfoBanner.is_active == True,
        or_(InfoBanner.expires_at.is_(None), InfoBanner.expires_at > now)
    ).order_by(InfoBanner.order).all()
    return jsonify(
        [{"id": b.id, "title": b.title, "content": b.content, "banner_type": b.banner_type, "order": b.order} for b in
         banners])


# ──────────────────────────────────────────────────────────────────────────────
#  API Routes for Notifications
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/unread_counts")
@login_required
def unread_counts():
    notif_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    msg_count = Message.query.filter_by(receiver_id=current_user.id, is_read=False, is_deleted=False).count()
    voice_count = VoiceMessage.query.filter_by(receiver_id=current_user.id, is_read=False).count()
    return jsonify({"notifications": notif_count, "messages": msg_count, "voice_messages": voice_count})


@app.route("/api/mark_notification_read/<int:notif_id>", methods=["POST"])
@login_required
def mark_notification_read(notif_id):
    notif = Notification.query.filter_by(id=notif_id, user_id=current_user.id).first()
    if notif:
        notif.is_read = True
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"error": "Notification not found"}), 404


@app.route("/api/mark_all_notifications_read", methods=["POST"])
@login_required
def mark_all_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"success": True})


# ──────────────────────────────────────────────────────────────────────────────
#  Verification Request Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/verification/request", methods=["GET", "POST"])
@login_required
def request_verification():
    if current_user.is_verified:
        flash("Вы уже верифицированы!", "info")
        return redirect(url_for("profile", username=current_user.username))
    existing_request = VerificationRequest.query.filter_by(user_id=current_user.id, status='pending').first()
    if existing_request:
        flash("У вас уже есть активная заявка на верификацию", "warning")
        return redirect(url_for("profile", username=current_user.username))
    if request.method == "POST":
        reason = escape_html(request.form.get("reason", "").strip())
        if not reason or len(reason) < 10:
            flash("Пожалуйста, опишите причину получения верификации (минимум 10 символов)", "error")
            return render_template("verification_request.html")
        if len(reason) > 500:
            flash("Текст не должен превышать 500 символов", "error")
            return render_template("verification_request.html")
        verification_request = VerificationRequest(user_id=current_user.id, reason=reason)
        db.session.add(verification_request)
        db.session.commit()
        flash("Заявка на верификацию отправлена! Администраторы рассмотрят её в ближайшее время.", "success")
        return redirect(url_for("profile", username=current_user.username))
    return render_template("verification_request.html")


# ──────────────────────────────────────────────────────────────────────────────
#  Admin Application Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/apply", methods=["GET", "POST"])
@login_required
def apply_admin():
    if current_user.is_admin or current_user.is_moderator:
        flash("Вы уже являетесь администратором или модератором", "info")
        return redirect(url_for("index"))
    existing_application = AdminApplication.query.filter_by(user_id=current_user.id, status='pending').first()
    if existing_application:
        flash("У вас уже есть активная заявка", "warning")
        return redirect(url_for("index"))
    if request.method == "POST":
        position = request.form.get("position")
        contacts = escape_html(request.form.get("contacts", "").strip())
        about = escape_html(request.form.get("about", "").strip())
        experience = escape_html(request.form.get("experience", "").strip())
        if position not in ['admin', 'moderator']:
            flash("Выберите должность", "error")
            return render_template("apply_admin.html")
        if not contacts:
            flash("Укажите контакты для связи", "error")
            return render_template("apply_admin.html")
        if not about or len(about) < 50:
            flash("Опишите себя и причины (минимум 50 символов)", "error")
            return render_template("apply_admin.html")
        application = AdminApplication(user_id=current_user.id, position=position, contacts=contacts,
                                       about=about, experience=experience if experience else None)
        db.session.add(application)
        db.session.commit()
        flash("Заявка отправлена! Администраторы рассмотрят её и свяжутся с вами.", "success")
        return redirect(url_for("index"))
    return render_template("apply_admin.html")


# ──────────────────────────────────────────────────────────────────────────────
#  Custom Avatar/Cover Upload Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/profile/upload-avatar", methods=["POST"])
@login_required
def upload_custom_avatar():
    if not current_user.can_upload_custom_avatar:
        return jsonify(
            {"error": "У вас недостаточно подписчиков для загрузки своей аватарки. Нужно 1000 подписчиков."}), 403
    if 'avatar' not in request.files:
        return jsonify({"error": "Файл не выбран"}), 400
    file = request.files['avatar']
    if file.filename == '':
        return jsonify({"error": "Файл не выбран"}), 400
    avatar_url = save_custom_file(file, "custom_avatars")
    if not avatar_url:
        return jsonify({"error": "Неверный формат файла. Поддерживаются: PNG, JPG, JPEG, GIF, WEBP"}), 400
    if current_user.custom_avatar and current_user.custom_avatar.startswith('/static/uploads/custom_avatars/'):
        try:
            old_path = safe_path_join(app.config['UPLOAD_FOLDER'], 'custom_avatars',
                                      os.path.basename(current_user.custom_avatar.split('/')[-1]))
            if os.path.exists(old_path):
                os.remove(old_path)
        except:
            pass
    current_user.custom_avatar = avatar_url
    db.session.commit()
    flash("Аватарка успешно обновлена!", "success")
    return redirect(url_for("profile", username=current_user.username))


@app.route("/profile/upload-cover", methods=["POST"])
@login_required
def upload_custom_cover():
    if not current_user.can_upload_custom_cover:
        return jsonify(
            {"error": "У вас недостаточно подписчиков для загрузки своей обложки. Нужно 5000 подписчиков."}), 403
    if 'cover' not in request.files:
        return jsonify({"error": "Файл не выбран"}), 400
    file = request.files['cover']
    if file.filename == '':
        return jsonify({"error": "Файл не выбран"}), 400
    cover_url = save_custom_file(file, "custom_covers")
    if not cover_url:
        return jsonify({"error": "Неверный формат файла. Поддерживаются: PNG, JPG, JPEG, GIF, WEBP"}), 400
    if current_user.custom_cover and current_user.custom_cover.startswith('/static/uploads/custom_covers/'):
        try:
            old_path = safe_path_join(app.config['UPLOAD_FOLDER'], 'custom_covers',
                                      os.path.basename(current_user.custom_cover.split('/')[-1]))
            if os.path.exists(old_path):
                os.remove(old_path)
        except:
            pass
    current_user.custom_cover = cover_url
    db.session.commit()
    flash("Обложка успешно обновлена!", "success")
    return redirect(url_for("profile", username=current_user.username))


@app.route("/profile/remove-custom-avatar", methods=["POST"])
@login_required
def remove_custom_avatar():
    if current_user.custom_avatar:
        current_user.custom_avatar = None
        db.session.commit()
        flash("Кастомная аватарка удалена", "success")
    return redirect(url_for("profile", username=current_user.username))


@app.route("/profile/remove-custom-cover", methods=["POST"])
@login_required
def remove_custom_cover():
    if current_user.custom_cover:
        current_user.custom_cover = None
        db.session.commit()
        flash("Кастомная обложка удалена", "success")
    return redirect(url_for("profile", username=current_user.username))


# ──────────────────────────────────────────────────────────────────────────────
#  Admin Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/admin/restore-backup", methods=["POST"])
@login_required
@admin_required
def admin_restore_backup():
    try:
        if 'backup_file' not in request.files:
            flash("Файл не выбран", "error")
            return redirect(url_for("admin_database"))
        file = request.files['backup_file']
        if file.filename == '':
            flash("Файл не выбран", "error")
            return redirect(url_for("admin_database"))
        if not file.filename.endswith('.db'):
            flash("Поддерживаются только файлы .db", "error")
            return redirect(url_for("admin_database"))
        db_path = os.path.join(basedir, 'instance', 'kildear.db')
        if os.path.exists(db_path):
            import shutil
            backup_name = f"auto_backup_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            backup_path = os.path.join(basedir, 'instance', backup_name)
            shutil.copy2(db_path, backup_path)
            flash(f"Создана автоматическая резервная копия: {backup_name}", "info")
        file.save(db_path)
        flash("База данных восстановлена! Перезагрузите страницу.", "success")
    except Exception as e:
        logger.error(f"Restore error: {e}")
        flash("Ошибка при восстановлении", "error")
    return redirect(url_for("admin_database"))


@app.route("/admin/restore-backup/<filename>", methods=["POST"])
@login_required
@admin_required
def admin_restore_backup_file(filename):
    try:
        safe_filename = os.path.basename(filename)
        backup_path = os.path.join(basedir, 'instance', safe_filename)
        if not os.path.exists(backup_path):
            flash("Файл резервной копии не найден", "error")
            return redirect(url_for("admin_database"))
        db_path = os.path.join(basedir, 'instance', 'kildear.db')
        if os.path.exists(db_path):
            import shutil
            auto_backup = f"auto_backup_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            auto_backup_path = os.path.join(basedir, 'instance', auto_backup)
            shutil.copy2(db_path, auto_backup_path)
            flash(f"Создана автоматическая резервная копия: {auto_backup}", "info")
        import shutil
        shutil.copy2(backup_path, db_path)
        flash(f"База данных восстановлена из {safe_filename}!", "success")
    except Exception as e:
        logger.error(f"Restore from file error: {e}")
        flash("Ошибка при восстановлении", "error")
    return redirect(url_for("admin_database"))


@app.route("/admin/download-backup/<filename>")
@login_required
@admin_required
def admin_download_backup(filename):
    try:
        safe_filename = os.path.basename(filename)
        backup_path = os.path.join(basedir, 'instance', safe_filename)
        if not os.path.exists(backup_path):
            flash("Файл не найден", "error")
            return redirect(url_for("admin_database"))
        return send_file(backup_path, as_attachment=True, download_name=safe_filename)
    except Exception as e:
        logger.error(f"Download error: {e}")
        flash("Ошибка при скачивании", "error")
        return redirect(url_for("admin_database"))


@app.route("/admin/delete-backup/<filename>", methods=["POST"])
@login_required
@admin_required
def admin_delete_backup(filename):
    try:
        safe_filename = os.path.basename(filename)
        backup_path = os.path.join(basedir, 'instance', safe_filename)
        if os.path.exists(backup_path):
            os.remove(backup_path)
            flash(f"Файл {safe_filename} удален", "success")
        else:
            flash("Файл не найден", "error")
    except Exception as e:
        logger.error(f"Delete error: {e}")
        flash("Ошибка при удалении", "error")
    return redirect(url_for("admin_database"))


@app.route("/admin/export-json")
@login_required
@admin_required
def admin_export_json():
    try:
        users = []
        for user in User.query.all():
            users.append({
                "id": user.id, "username": user.username, "email": user.email,
                "display_name": user.display_name, "bio": user.bio,
                "created_at": user.created_at.isoformat(), "is_verified": user.is_verified,
                "follower_count": user.follower_count
            })
        posts = []
        for post in Post.query.all():
            posts.append({
                "id": post.id, "user_id": post.user_id, "content": post.content,
                "created_at": post.created_at.isoformat(), "likes": post.like_count, "comments": post.comment_count
            })
        data = {"exported_at": datetime.utcnow().isoformat(), "users": users, "posts": posts,
                "total_users": len(users), "total_posts": len(posts)}
        response = jsonify(data)
        response.headers[
            'Content-Disposition'] = f'attachment; filename=kildear_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        return response
    except Exception as e:
        logger.error(f"Export error: {e}")
        flash("Ошибка при экспорте", "error")
        return redirect(url_for("admin_database"))


@app.route("/admin/make-admin", methods=["POST"])
@login_required
@admin_required
def admin_make_admin():
    try:
        username = request.form.get("username", "").strip()
        role = request.form.get("role", "admin")
        user = User.query.filter(func.lower(User.username) == username.lower()).first()
        if not user:
            flash(f"Пользователь {username} не найден", "error")
            return redirect(url_for("admin_admins"))
        if user.id == current_user.id:
            flash("Нельзя изменить свои права", "error")
            return redirect(url_for("admin_admins"))
        if role == "admin":
            user.is_admin = True
            user.is_moderator = False
            flash(f"Пользователь {user.username} назначен администратором", "success")
        elif role == "moderator":
            user.is_moderator = True
            user.is_admin = False
            flash(f"Пользователь {user.username} назначен модератором", "success")
        db.session.commit()
    except Exception as e:
        logger.error(f"Error making admin: {e}")
        flash("Ошибка при назначении", "error")
    return redirect(url_for("admin_admins"))


@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    stats = {
        "total_users": User.query.count(),
        "total_posts": Post.query.count(),
        "total_comments": Comment.query.count(),
        "total_reports": Report.query.filter_by(status='pending').count(),
        "new_users_today": User.query.filter(User.created_at >= datetime.now(timezone.utc).date()).count(),
        "banned_users": User.query.filter_by(is_banned=True).count(),
        "pending_verification": VerificationRequest.query.filter_by(status='pending').count(),
        "pending_admin_apps": AdminApplication.query.filter_by(status='pending').count(),
        "active_banners": InfoBanner.query.filter_by(is_active=True).count(),
    }
    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
    pending_reports = Report.query.filter_by(status='pending').order_by(Report.created_at.desc()).limit(20).all()
    recent_logins = LoginHistory.query.order_by(LoginHistory.created_at.desc()).limit(20).all()
    recent_verifications = VerificationRequest.query.order_by(VerificationRequest.created_at.desc()).limit(10).all()
    recent_applications = AdminApplication.query.order_by(AdminApplication.created_at.desc()).limit(10).all()
    db_info = {'type': 'PostgreSQL' if is_render else 'SQLite', 'version': '15' if is_render else '3', 'size': None}
    return render_template("admin/dashboard.html", stats=stats, recent_users=recent_users,
                           pending_reports=pending_reports, recent_logins=recent_logins,
                           recent_verifications=recent_verifications, recent_applications=recent_applications,
                           db_info=db_info)


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "")
    query = User.query
    if search:
        search_safe = f"%{escape_html(search)}%"
        query = query.filter(
            or_(User.username.ilike(search_safe), User.email.ilike(search_safe), User.display_name.ilike(search_safe)))
    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template("admin/users.html", users=users, search=search)


@app.route("/admin/user/<int:user_id>/toggle-ban", methods=["POST"])
@login_required
@admin_required
def admin_toggle_ban(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Нельзя забанить самого себя", "error")
        return redirect(url_for("admin_users"))
    user.is_banned = not user.is_banned
    db.session.commit()
    status = "забанен" if user.is_banned else "разбанен"
    flash(f"Пользователь {user.username} {status}", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/user/<int:user_id>/toggle-admin", methods=["POST"])
@login_required
@admin_required
def admin_toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Нельзя изменить свои права администратора", "error")
        return redirect(url_for("admin_users"))
    user.is_admin = not user.is_admin
    db.session.commit()
    status = "назначен администратором" if user.is_admin else "лишен прав администратора"
    flash(f"Пользователь {user.username} {status}", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/user/<int:user_id>/toggle-moderator", methods=["POST"])
@login_required
@admin_required
def admin_toggle_moderator(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Нельзя изменить свои права", "error")
        return redirect(url_for("admin_users"))
    user.is_moderator = not user.is_moderator
    db.session.commit()
    status = "назначен модератором" if user.is_moderator else "лишен прав модератора"
    flash(f"Пользователь {user.username} {status}", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/user/<int:user_id>/toggle-verify", methods=["POST"])
@login_required
@admin_required
def admin_toggle_verify(user_id):
    user = User.query.get_or_404(user_id)
    user.is_verified = not user.is_verified
    db.session.commit()
    status = "верифицирован" if user.is_verified else "снята верификация"
    flash(f"Пользователь {user.username} {status}", "success")
    return redirect(request.referrer or url_for("admin_users"))


@app.route("/admin/user/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Нельзя удалить самого себя", "error")
        return redirect(url_for("admin_users"))
    username = user.username
    db.session.delete(user)
    db.session.commit()
    flash(f"Пользователь {username} полностью удален", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/verification-requests")
@login_required
@admin_required
def admin_verification_requests():
    status = request.args.get("status", "pending")
    query = VerificationRequest.query
    if status != "all":
        query = query.filter_by(status=status)
    requests = query.order_by(VerificationRequest.created_at.desc()).all()
    return render_template("admin/verification_requests.html", requests=requests, current_status=status)


@app.route("/admin/verification-request/<int:request_id>/review", methods=["POST"])
@login_required
@admin_required
def admin_review_verification(request_id):
    verification_request = VerificationRequest.query.get_or_404(request_id)
    action = request.form.get("action")
    comment = escape_html(request.form.get("comment", ""))
    if action == "approve":
        verification_request.status = "approved"
        user = verification_request.user
        user.is_verified = True
        flash(f"Пользователь {user.username} верифицирован", "success")
        notif = Notification(user_id=user.id, from_user_id=current_user.id, type="verification",
                             text=f"Ваша заявка на верификацию одобрена! Поздравляем!")
        db.session.add(notif)
    elif action == "reject":
        verification_request.status = "rejected"
        flash(f"Заявка отклонена", "warning")
        notif = Notification(user_id=verification_request.user.id, from_user_id=current_user.id, type="verification",
                             text=f"Ваша заявка на верификацию отклонена. Причина: {comment if comment else 'Не соответствует критериям'}")
        db.session.add(notif)
    verification_request.admin_comment = comment
    verification_request.reviewed_at = datetime.utcnow()
    verification_request.reviewed_by = current_user.id
    db.session.commit()
    return redirect(url_for("admin_verification_requests"))


@app.route("/admin/applications")
@login_required
@admin_required
def admin_applications():
    status = request.args.get("status", "pending")
    query = AdminApplication.query
    if status != "all":
        query = query.filter_by(status=status)
    applications = query.order_by(AdminApplication.created_at.desc()).all()
    return render_template("admin/applications.html", applications=applications, current_status=status)


@app.route("/admin/application/<int:app_id>/review", methods=["POST"])
@login_required
@admin_required
def admin_review_application(app_id):
    application = AdminApplication.query.get_or_404(app_id)
    action = request.form.get("action")
    comment = escape_html(request.form.get("comment", ""))
    if action == "approve":
        application.status = "approved"
        user = application.user
        if application.position == "admin":
            user.is_admin = True
        elif application.position == "moderator":
            user.is_moderator = True
        flash(f"Заявка одобрена. Пользователь {user.username} назначен {application.position}ом", "success")
        notif = Notification(user_id=user.id, from_user_id=current_user.id, type="admin_approved",
                             text=f"Ваша заявка на должность {application.position} одобрена! Поздравляем!")
        db.session.add(notif)
    elif action == "reject":
        application.status = "rejected"
        flash(f"Заявка отклонена", "warning")
        notif = Notification(user_id=application.user.id, from_user_id=current_user.id, type="admin_rejected",
                             text=f"Ваша заявка на должность {application.position} отклонена. Причина: {comment if comment else 'Не соответствует требованиям'}")
        db.session.add(notif)
    application.admin_comment = comment
    application.reviewed_at = datetime.utcnow()
    application.reviewed_by = current_user.id
    db.session.commit()
    return redirect(url_for("admin_applications"))


@app.route("/admin/reports")
@login_required
@admin_required
def admin_reports():
    status = request.args.get("status", "pending")
    query = Report.query
    if status != "all":
        query = query.filter_by(status=status)
    reports = query.order_by(Report.created_at.desc()).all()
    return render_template("admin/reports.html", reports=reports, current_status=status)


@app.route("/admin/report/<int:report_id>/review", methods=["POST"])
@login_required
@admin_required
def admin_review_report(report_id):
    report = Report.query.get_or_404(report_id)
    action = request.form.get("action")
    if action == "dismiss":
        report.status = "dismissed"
        flash("Жалоба отклонена", "success")
    elif action == "approve":
        report.status = "reviewed"
        if report.reported_user_id:
            user = User.query.get(report.reported_user_id)
            if user:
                user.is_banned = True
                flash(f"Пользователь {user.username} забанен", "success")
    report.reviewed_at = datetime.utcnow()
    report.reviewed_by = current_user.id
    db.session.commit()
    return redirect(url_for("admin_reports"))


@app.route("/admin/verification")
@login_required
@admin_required
def admin_verification():
    page = request.args.get("page", 1, type=int)
    users = User.query.filter_by(is_verified=False, is_banned=False).order_by(User.created_at.desc()).paginate(
        page=page, per_page=20)
    return render_template("admin/verification.html", users=users)


@app.route("/admin/banned")
@login_required
@ admin_required
def admin_banned():
    page = request.args.get("page", 1, type=int)
    users = User.query.filter_by(is_banned=True).order_by(User.last_seen.desc()).paginate(page=page, per_page=20)
    return render_template("admin/banned.html", users=users)


@app.route("/admin/admins")
@login_required
@admin_required
def admin_admins():
    admins = User.query.filter_by(is_admin=True).order_by(User.created_at).all()
    return render_template("admin/admins.html", admins=admins)


@app.route("/admin/logs")
@login_required
@admin_required
def admin_logs():
    page = request.args.get("page", 1, type=int)
    logs = LoginHistory.query.order_by(LoginHistory.created_at.desc()).paginate(page=page, per_page=50)
    return render_template("admin/logs.html", logs=logs)


@app.route("/admin/preset-avatars")
@login_required
@admin_required
def admin_preset_avatars():
    return render_template("admin/preset_avatars.html", group_avatars=PRESET_GROUP_AVATARS,
                           channel_avatars=PRESET_CHANNEL_AVATARS)


# ──────────────────────────────────────────────────────────────────────────────
#  Settings Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/settings")
@login_required
def settings_index():
    settings = current_user.get_settings()
    return render_template("settings/index.html", settings=settings)


@app.route("/settings/account", methods=["GET", "POST"])
@login_required
def settings_account():
    settings = current_user.get_settings()
    if request.method == "POST":
        try:
            data = request.get_json()
            if 'display_name' in data:
                current_user.display_name = escape_html(data['display_name'][:60])
            if 'bio' in data:
                current_user.bio = escape_html(data['bio'][:500])
            if 'location' in data:
                current_user.location = escape_html(data['location'][:100])
            if 'website' in data:
                current_user.website = escape_html(data['website'][:200])
            if 'email' in data and safe_validate_email(data['email']):
                current_user.email = data['email'].lower()
            if 'accent_color' in data and data['accent_color']:
                if re.match(r'^#[0-9a-fA-F]{6}$', data['accent_color']):
                    current_user.accent_color = data['accent_color'][:7]
            if 'is_private' in data:
                current_user.is_private = bool(data['is_private'])
            if 'preset_avatar' in data:
                avatar_num = int(data['preset_avatar'])
                if 1 <= avatar_num <= 10:
                    current_user.set_preset_avatar(avatar_num)
            if 'preset_cover' in data:
                cover_num = data['preset_cover']
                if cover_num and cover_num != '':
                    current_user.set_preset_cover(int(cover_num))
                else:
                    current_user.set_preset_cover(None)
            if 'theme' in data:
                settings.theme = data['theme']
            if 'current_password' in data and data['current_password']:
                if current_user.check_password(data['current_password']):
                    if 'new_password' in data and len(data['new_password']) >= 8:
                        if data['new_password'] == data.get('confirm_password'):
                            current_user.set_password(data['new_password'])
                        else:
                            return jsonify({"success": False, "error": "Passwords don't match"}), 400
                    else:
                        return jsonify({"success": False, "error": "Password must be at least 8 characters"}), 400
                else:
                    return jsonify({"success": False, "error": "Current password is incorrect"}), 400
            db.session.commit()
            return jsonify({"success": True, "message": "Account settings updated"})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating account settings: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    return render_template("settings/account.html", settings=settings)


@app.route("/settings/notifications", methods=["GET", "POST"])
@login_required
def settings_notifications():
    settings = current_user.get_settings()
    if request.method == "POST":
        try:
            data = request.get_json()
            for key in ['notify_likes', 'notify_comments', 'notify_follows', 'notify_messages',
                        'notify_voice_messages', 'notify_calls', 'notify_group_posts', 'notify_channel_posts',
                        'sound_enabled', 'call_sound_enabled']:
                if key in data:
                    setattr(settings, key, bool(data[key]))
            if 'notification_sound' in data:
                settings.notification_sound = data['notification_sound']
            if 'sound_volume' in data:
                settings.sound_volume = int(data['sound_volume'])
            db.session.commit()
            return jsonify({"success": True, "message": "Notification settings updated"})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating notification settings: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    return render_template("settings/notifications.html", settings=settings)


@app.route("/settings/privacy", methods=["GET", "POST"])
@login_required
def settings_privacy():
    settings = current_user.get_settings()
    if request.method == "POST":
        try:
            data = request.get_json()
            if 'show_last_seen' in data:
                settings.show_last_seen = bool(data['show_last_seen'])
            if 'show_online_status' in data:
                settings.show_online_status = bool(data['show_online_status'])
            if 'allow_messages_from' in data:
                settings.allow_messages_from = data['allow_messages_from']
            if 'allow_calls_from' in data:
                settings.allow_calls_from = data['allow_calls_from']
            if 'allow_voice_messages_from' in data:
                settings.allow_voice_messages_from = data['allow_voice_messages_from']
            if 'show_profile_photo' in data:
                settings.show_profile_photo = bool(data['show_profile_photo'])
            if 'show_bio' in data:
                settings.show_bio = bool(data['show_bio'])
            if 'data_saver_mode' in data:
                settings.data_saver_mode = bool(data['data_saver_mode'])
            db.session.commit()
            return jsonify({"success": True, "message": "Privacy settings updated"})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating privacy settings: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    return render_template("settings/privacy.html", settings=settings)


@app.route("/admin/backup-database", methods=["POST"])
@login_required
@admin_required
def admin_backup_database():
    try:
        if is_render:
            flash("Резервное копирование для PostgreSQL временно недоступно", "warning")
        else:
            import shutil
            db_path = os.path.join(basedir, 'instance', 'kildear.db')
            backup_path = os.path.join(basedir, 'instance', f'backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db')
            if os.path.exists(db_path):
                shutil.copy2(db_path, backup_path)
                flash(f"Резервная копия создана: {os.path.basename(backup_path)}", "success")
            else:
                flash("Файл базы данных не найден", "error")
    except Exception as e:
        logger.error(f"Backup error: {e}", exc_info=True)
        flash("Ошибка при создании резервной копии", "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/settings/chats", methods=["GET", "POST"])
@login_required
def settings_chats():
    settings = current_user.get_settings()
    if request.method == "POST":
        try:
            data = request.get_json()
            if 'enter_to_send' in data:
                settings.enter_to_send = bool(data['enter_to_send'])
            if 'show_typing' in data:
                settings.show_typing = bool(data['show_typing'])
            if 'show_read_receipts' in data:
                settings.show_read_receipts = bool(data['show_read_receipts'])
            if 'bubble_color_own' in data:
                settings.bubble_color_own = data['bubble_color_own'][:7]
            if 'bubble_color_other' in data:
                settings.bubble_color_other = data['bubble_color_other'][:7]
            if 'chat_background' in data:
                settings.chat_background = data['chat_background'][:200]
            db.session.commit()
            return jsonify({"success": True, "message": "Chat settings updated"})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating chat settings: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    return render_template("settings/chats.html", settings=settings)


@app.route("/settings/folders", methods=["GET", "POST"])
@login_required
def settings_folders():
    settings = current_user.get_settings()
    if request.method == "POST":
        try:
            data = request.get_json()
            if 'folders_data' in data:
                settings.folders_data = json.dumps(data['folders_data'])
            db.session.commit()
            return jsonify({"success": True, "message": "Folders updated"})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating folders: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    folders = json.loads(settings.folders_data) if settings.folders_data else []
    return render_template("settings/folders.html", settings=settings, folders=folders)


@app.route("/settings/advanced", methods=["GET", "POST"])
@login_required
def settings_advanced():
    settings = current_user.get_settings()
    if request.method == "POST":
        try:
            data = request.get_json()
            if 'save_edited_messages' in data:
                settings.save_edited_messages = bool(data['save_edited_messages'])
            if 'auto_delete_messages' in data:
                settings.auto_delete_messages = int(data['auto_delete_messages'])
            if 'data_saver_mode' in data:
                settings.data_saver_mode = bool(data['data_saver_mode'])
                session['data_saver_mode'] = settings.data_saver_mode
            if 'auto_play_videos' in data:
                settings.auto_play_videos = bool(data['auto_play_videos'])
            if 'auto_play_gifs' in data:
                settings.auto_play_gifs = bool(data['auto_play_gifs'])
            db.session.commit()
            return jsonify({"success": True, "message": "Advanced settings updated"})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating advanced settings: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    return render_template("settings/advanced.html", settings=settings)


@app.route("/settings/sound", methods=["GET", "POST"])
@login_required
def settings_sound():
    settings = current_user.get_settings()
    if request.method == "POST":
        try:
            data = request.get_json()
            if 'camera_enabled' in data:
                settings.camera_enabled = bool(data['camera_enabled'])
            if 'mic_enabled' in data:
                settings.mic_enabled = bool(data['mic_enabled'])
            db.session.commit()
            return jsonify({"success": True, "message": "Sound settings updated"})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating sound settings: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    return render_template("settings/sound.html", settings=settings)


@app.route("/settings/battery", methods=["GET", "POST"])
@login_required
def settings_battery():
    settings = current_user.get_settings()
    if request.method == "POST":
        try:
            data = request.get_json()
            if 'battery_saver_mode' in data:
                settings.battery_saver_mode = bool(data['battery_saver_mode'])
                session['battery_saver_mode'] = settings.battery_saver_mode
            if 'reduce_animations' in data:
                settings.reduce_animations = bool(data['reduce_animations'])
            if 'animations_enabled' in data:
                settings.animations_enabled = bool(data['animations_enabled'])
            if 'animation_speed' in data:
                settings.animation_speed = data['animation_speed']
            db.session.commit()
            return jsonify({"success": True, "message": "Battery settings updated"})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating battery settings: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    return render_template("settings/battery.html", settings=settings)


@app.route("/settings/language", methods=["GET", "POST"])
@login_required
def settings_language():
    settings = current_user.get_settings()
    if request.method == "POST":
        try:
            data = request.get_json()
            if 'language' in data:
                settings.language = data['language']
                session['language'] = settings.language
            if 'default_scale' in data:
                settings.default_scale = int(data['default_scale'])
                session['default_scale'] = settings.default_scale
            if 'font_size' in data:
                settings.font_size = data['font_size']
            if 'chat_font_size' in data:
                settings.chat_font_size = data['chat_font_size']
            db.session.commit()
            return jsonify({"success": True, "message": "Language settings updated"})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating language settings: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    return render_template("settings/language.html", settings=settings)


@app.route("/settings/update", methods=["POST"])
@login_required
def update_settings():
    try:
        data = request.get_json()
        settings = current_user.get_settings()
        for key, value in data.items():
            if hasattr(settings, key):
                if key in ['default_scale', 'sound_volume', 'auto_delete_messages']:
                    value = int(value) if value else 0
                elif key in ['notify_likes', 'notify_comments', 'notify_follows', 'notify_messages',
                             'notify_voice_messages', 'notify_calls', 'notify_group_posts', 'notify_channel_posts',
                             'sound_enabled', 'call_sound_enabled', 'show_last_seen', 'show_online_status',
                             'show_profile_photo', 'show_bio', 'enter_to_send', 'show_typing', 'show_read_receipts',
                             'animations_enabled', 'save_edited_messages', 'data_saver_mode', 'auto_play_videos',
                             'auto_play_gifs', 'camera_enabled', 'mic_enabled', 'battery_saver_mode',
                             'reduce_animations']:
                    value = bool(value)
                setattr(settings, key, value)
        settings.updated_at = datetime.utcnow()
        db.session.commit()
        if 'default_scale' in data:
            session['default_scale'] = data['default_scale']
        if 'language' in data:
            session['language'] = data['language']
        return jsonify({"success": True, "message": "Settings updated"})
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/settings/blocked")
@login_required
def settings_blocked():
    blocked_users = current_user.blocked_users.all()
    return render_template("settings/blocked.html", blocked_users=blocked_users)


@app.route("/settings/unblock/<int:user_id>", methods=["POST"])
@login_required
def settings_unblock(user_id):
    user = User.query.get_or_404(user_id)
    if current_user.unblock(user):
        db.session.commit()
        flash(f"Unblocked @{user.username}", "success")
    return redirect(url_for("settings_blocked"))


@app.route("/settings/export_data")
@login_required
def settings_export_data():
    try:
        user_data = {
            "user": {"username": current_user.username, "email": current_user.email,
                     "display_name": current_user.display_name, "bio": current_user.bio,
                     "location": current_user.location, "website": current_user.website,
                     "created_at": current_user.created_at.isoformat(), "is_verified": current_user.is_verified},
            "stats": {"followers": current_user.follower_count, "following": current_user.following_count,
                      "posts": current_user.post_count, "likes": sum(post.like_count for post in current_user.posts)},
            "posts": [{"content": post.content, "created_at": post.created_at.isoformat(),
                       "likes": post.like_count, "comments": post.comment_count}
                      for post in current_user.posts.limit(100).all()],
            "exported_at": datetime.utcnow().isoformat()
        }
        response = jsonify(user_data)
        response.headers['Content-Disposition'] = f'attachment; filename=kildear_data_{current_user.username}.json'
        return response
    except Exception as e:
        logger.error(f"Error exporting data: {e}")
        flash("Error exporting data", "error")
        return redirect(url_for("settings_advanced"))


# ──────────────────────────────────────────────────────────────────────────────
#  Voice Message Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/voice/send", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def send_voice_message():
    try:
        receiver_id = request.form.get("receiver_id", type=int)
        audio_file = request.files.get("audio")
        if not audio_file or not audio_file.filename:
            return jsonify({"error": "No audio file provided"}), 400
        receiver = User.query.get_or_404(receiver_id)
        if current_user.is_blocked(receiver):
            return jsonify({"error": "Cannot send message to blocked user"}), 403
        safe_filename = sanitize_filename(audio_file.filename)
        if not safe_filename:
            return jsonify({"error": "Invalid filename"}), 400
        ext = safe_filename.rsplit('.', 1)[1].lower() if '.' in safe_filename else ''
        if ext not in ALLOWED_AUDIO:
            return jsonify({"error": "Audio format not supported"}), 400
        audio_file.seek(0)
        audio_data = audio_file.read()
        if len(audio_data) > 10 * 1024 * 1024:
            return jsonify({"error": "Audio file too large"}), 400
        base64_data = base64.b64encode(audio_data).decode('utf-8')
        duration = request.form.get("duration", 0, type=int)
        voice_msg = VoiceMessage(sender_id=current_user.id, receiver_id=receiver.id,
                                 audio_data=base64_data, audio_mime=f"audio/{ext}", duration=duration)
        db.session.add(voice_msg)
        db.session.commit()
        notif = Notification(user_id=receiver.id, from_user_id=current_user.id,
                             type="voice_message", text=f"Voice message from {current_user.username}")
        db.session.add(notif)
        db.session.commit()
        room = "_".join(sorted([str(current_user.id), str(receiver.id)]))
        socketio.emit("new_voice_message", {
            "id": voice_msg.id, "sender_id": current_user.id, "sender_username": current_user.username,
            "sender_avatar": current_user.avatar_url, "audio_url": voice_msg.audio_url_data,
            "duration": voice_msg.duration, "created_at": voice_msg.created_at.strftime("%H:%M")
        }, room=room)
        send_notification(receiver.id, {
            "type": "voice_message", "from_user": {"id": current_user.id, "username": current_user.username,
                                                   "avatar": current_user.avatar_url},
            "text": f"Voice message from {current_user.username}"
        })
        return jsonify({"success": True, "id": voice_msg.id})
    except Exception as e:
        logger.error(f"Error sending voice message: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/voice/<int:message_id>")
@login_required
def get_voice_message(message_id):
    msg = VoiceMessage.query.get_or_404(message_id)
    if msg.sender_id != current_user.id and msg.receiver_id != current_user.id:
        abort(403)
    return jsonify({"id": msg.id, "sender_id": msg.sender_id, "audio_url": msg.audio_url_data,
                    "duration": msg.duration, "created_at": msg.created_at.isoformat(), "is_read": msg.is_read})


@app.route("/voice/mark-read/<int:message_id>", methods=["POST"])
@login_required
def mark_voice_read(message_id):
    msg = VoiceMessage.query.get_or_404(message_id)
    if msg.receiver_id == current_user.id:
        msg.is_read = True
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"error": "Not authorized"}), 403


@app.route("/voice/delete/<int:message_id>", methods=["POST"])
@login_required
def delete_voice_message(message_id):
    msg = VoiceMessage.query.get_or_404(message_id)
    if msg.sender_id != current_user.id:
        return jsonify({"error": "Not authorized"}), 403
    db.session.delete(msg)
    db.session.commit()
    return jsonify({"success": True})


# ──────────────────────────────────────────────────────────────────────────────
#  Call Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/call/start", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def start_call():
    try:
        data = request.get_json()
        callee_id = data.get('callee_id')
        call_type = data.get('type', 'audio')
        callee = User.query.get_or_404(callee_id)
        if current_user.is_blocked(callee):
            return jsonify({"error": "Cannot call blocked user"}), 403
        existing_call = Call.query.filter(
            and_(or_(and_(Call.caller_id == callee_id, Call.status == 'ongoing'),
                     and_(Call.callee_id == callee_id, Call.status == 'ongoing')))
        ).first()
        if existing_call:
            return jsonify({"error": "User is already in a call"}), 409
        call = Call(caller_id=current_user.id, callee_id=callee.id, call_type=call_type, status='ongoing')
        db.session.add(call)
        db.session.commit()
        webrtc_config = {'iceServers': [
            {'urls': 'stun:stun.l.google.com:19302'},
            {'urls': 'stun:stun1.l.google.com:19302'},
            {'urls': 'stun:stun2.l.google.com:19302'},
            {'urls': 'stun:stun3.l.google.com:19302'},
            {'urls': 'stun:stun4.l.google.com:19302'}
        ]}
        room = f"user_{callee.id}"
        socketio.emit("incoming_call", {
            "call_id": call.id, "caller_id": current_user.id, "caller_username": current_user.username,
            "caller_avatar": current_user.avatar_url, "type": call_type, "webrtc_config": webrtc_config
        }, room=room)
        return jsonify({"success": True, "call_id": call.id, "webrtc_config": webrtc_config})
    except Exception as e:
        logger.error(f"Error starting call: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/call/<int:call_id>/accept", methods=["POST"])
@login_required
def accept_call(call_id):
    call = Call.query.get_or_404(call_id)
    if call.callee_id != current_user.id:
        return jsonify({"error": "Not authorized"}), 403
    call.status = 'ongoing'
    call.started_at = datetime.utcnow()
    db.session.commit()
    room = f"user_{call.caller_id}"
    socketio.emit("call_accepted", {"call_id": call.id, "accepted_by": current_user.id}, room=room)
    return jsonify({"success": True})


@app.route("/call/<int:call_id>/reject", methods=["POST"])
@login_required
def reject_call(call_id):
    call = Call.query.get_or_404(call_id)
    if call.callee_id != current_user.id:
        return jsonify({"error": "Not authorized"}), 403
    call.status = 'rejected'
    call.ended_at = datetime.utcnow()
    db.session.commit()
    room = f"user_{call.caller_id}"
    socketio.emit("call_rejected", {"call_id": call.id, "rejected_by": current_user.id}, room=room)
    return jsonify({"success": True})


@app.route("/call/<int:call_id>/end", methods=["POST"])
@login_required
def end_call(call_id):
    call = Call.query.get_or_404(call_id)
    if call.caller_id != current_user.id and call.callee_id != current_user.id:
        return jsonify({"error": "Not authorized"}), 403
    call.status = 'completed'
    call.ended_at = datetime.utcnow()
    if call.started_at:
        duration = (call.ended_at - call.started_at).seconds
        call.duration = duration
    db.session.commit()
    other_id = call.caller_id if call.callee_id == current_user.id else call.callee_id
    room = f"user_{other_id}"
    socketio.emit("call_ended", {"call_id": call.id, "ended_by": current_user.id, "duration": call.duration}, room=room)
    return jsonify({"success": True})


@app.route("/call/history")
@login_required
def call_history():
    calls = Call.query.filter(or_(Call.caller_id == current_user.id, Call.callee_id == current_user.id)
                              ).order_by(Call.started_at.desc()).limit(50).all()
    call_list = []
    for call in calls:
        other = User.query.get(call.caller_id if call.callee_id == current_user.id else call.callee_id)
        call_list.append({
            "id": call.id, "other_user": {"id": other.id, "username": other.username,
                                          "display_name": other.display_name, "avatar": other.avatar_url},
            "type": call.call_type, "status": call.status, "duration": call.duration,
            "started_at": call.started_at.isoformat(), "is_outgoing": call.caller_id == current_user.id
        })
    return jsonify({"calls": call_list})


# ──────────────────────────────────────────────────────────────────────────────
#  CHAT API ROUTES (НОВЫЕ)
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/conversations")
@login_required
def api_get_conversations():
    sent_to = db.session.query(Message.receiver_id).filter_by(sender_id=current_user.id).distinct()
    recv_from = db.session.query(Message.sender_id).filter_by(receiver_id=current_user.id).distinct()
    uid_set = {r[0] for r in sent_to} | {r[0] for r in recv_from}
    blocked_ids = [b.id for b in current_user.blocked_users]
    uid_set = uid_set - set(blocked_ids)
    partners = User.query.filter(User.id.in_(uid_set)).all()
    conversations = []
    for p in partners:
        last = Message.query.filter(
            or_(and_(Message.sender_id == current_user.id, Message.receiver_id == p.id),
                and_(Message.sender_id == p.id, Message.receiver_id == current_user.id)),
            Message.is_deleted == False
        ).order_by(Message.created_at.desc()).first()
        unread = Message.query.filter_by(sender_id=p.id, receiver_id=current_user.id, is_read=False,
                                         is_deleted=False).count()
        conversations.append({
            "id": p.id, "username": p.username, "display_name": p.display_name or p.username,
            "avatar": p.avatar_url, "is_online": p.is_online, "is_verified": p.is_verified,
            "last_message": {
                "content": last.content[:50] if last and last.content else (
                    "📷 Photo" if last and last.media_url else None),
                "time": last.created_at.strftime("%H:%M") if last else None,
                "is_own": last.sender_id == current_user.id if last else None
            } if last else None,
            "unread_count": unread
        })
    conversations.sort(key=lambda x: x.get("last_message", {}).get("time", ""), reverse=True)
    return jsonify({"conversations": conversations})


@app.route("/api/messages/<username>")
@login_required
def api_get_messages(username):
    if not safe_validate_username(username):
        return jsonify({"error": "Invalid username"}), 400
    partner = User.query.filter(func.lower(User.username) == username.lower()).first_or_404()
    after_id = request.args.get('after_id', type=int, default=0)
    limit = request.args.get('limit', type=int, default=100)
    if current_user.is_blocked(partner):
        return jsonify({"error": "Blocked user"}), 403
    query = Message.query.filter(
        or_(and_(Message.sender_id == current_user.id, Message.receiver_id == partner.id),
            and_(Message.sender_id == partner.id, Message.receiver_id == current_user.id)),
        Message.is_deleted == False
    )
    if after_id > 0:
        query = query.filter(Message.id > after_id)
    messages = query.order_by(Message.created_at.asc()).limit(limit).all()
    return jsonify({
        "messages": [{
            "id": m.id, "sender_id": m.sender_id, "sender_username": m.sender.username,
            "sender_avatar": m.sender.avatar_url, "content": m.content, "media_url": m.media_url,
            "is_read": m.is_read, "is_edited": m.is_edited, "edit_count": m.edit_count,
            "reply_to_id": m.reply_to_id,
            "reply_to": {
                "id": m.reply_to.id, "content": m.reply_to.content[:100],
                "sender_username": m.reply_to.sender.username
            } if m.reply_to else None,
            "created_at": m.created_at.isoformat(), "time": m.created_at.strftime("%H:%M")
        } for m in messages]
    })


@app.route("/api/messages/<username>/send", methods=["POST"])
@login_required
@limiter.limit("120 per minute")
def api_send_message(username):
    if not safe_validate_username(username):
        return jsonify({"error": "Invalid username"}), 400
    partner = User.query.filter(func.lower(User.username) == username.lower()).first_or_404()
    if current_user.is_blocked(partner):
        return jsonify({"error": "Cannot send message to blocked user"}), 403
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    content = escape_html(data.get("content", "").strip())
    reply_to_id = data.get("reply_to_id", None)
    if not content:
        return jsonify({"error": "Message cannot be empty"}), 400
    msg = Message(sender_id=current_user.id, receiver_id=partner.id, content=content, reply_to_id=reply_to_id)
    db.session.add(msg)
    db.session.commit()
    notif = Notification(user_id=partner.id, from_user_id=current_user.id, type="message",
                         text=f"{current_user.username} sent you a message")
    db.session.add(notif)
    db.session.commit()
    room = "_".join(sorted([str(current_user.id), str(partner.id)]))
    socketio.emit("new_message", {
        "id": msg.id, "sender_id": current_user.id, "sender_username": current_user.username,
        "sender_avatar": current_user.avatar_url, "content": msg.content, "reply_to_id": msg.reply_to_id,
        "created_at": msg.created_at.isoformat(), "time": msg.created_at.strftime("%H:%M")
    }, room=room)
    return jsonify({
        "success": True,
        "message": {
            "id": msg.id, "sender_id": msg.sender_id, "sender_username": current_user.username,
            "sender_avatar": current_user.avatar_url, "content": msg.content,
            "created_at": msg.created_at.isoformat(), "time": msg.created_at.strftime("%H:%M"),
            "reply_to_id": msg.reply_to_id
        }
    })


@app.route("/api/messages/<int:message_id>/edit", methods=["POST"])
@login_required
def api_edit_message(message_id):
    msg = Message.query.get_or_404(message_id)
    if msg.sender_id != current_user.id:
        return jsonify({"error": "Cannot edit other's messages"}), 403
    data = request.get_json()
    new_content = escape_html(data.get("content", "").strip())
    if not new_content:
        return jsonify({"error": "Content cannot be empty"}), 400
    msg.content = new_content
    msg.is_edited = True
    msg.edit_count += 1
    msg.updated_at = datetime.utcnow()
    db.session.commit()
    room = "_".join(sorted([str(msg.sender_id), str(msg.receiver_id)]))
    socketio.emit("message_edited", {
        "message_id": msg.id, "new_content": msg.content, "edit_count": msg.edit_count
    }, room=room)
    return jsonify({"success": True, "content": msg.content, "edit_count": msg.edit_count})


@app.route("/api/messages/<int:message_id>/delete", methods=["POST"])
@login_required
def api_delete_message(message_id):
    msg = Message.query.get_or_404(message_id)
    if msg.sender_id != current_user.id:
        return jsonify({"error": "Cannot delete other's messages"}), 403
    msg.is_deleted = True
    db.session.commit()
    room = "_".join(sorted([str(msg.sender_id), str(msg.receiver_id)]))
    socketio.emit("message_deleted", {"message_id": msg.id}, room=room)
    return jsonify({"success": True})


@app.route("/api/messages/<int:message_id>/forward", methods=["POST"])
@login_required
def api_forward_message(message_id):
    original_msg = Message.query.get_or_404(message_id)
    if original_msg.is_deleted:
        return jsonify({"error": "Message not found"}), 404
    data = request.get_json()
    target_username = data.get("target_username")
    if not target_username:
        return jsonify({"error": "Target username required"}), 400
    target = User.query.filter(func.lower(User.username) == target_username.lower()).first()
    if not target:
        return jsonify({"error": "User not found"}), 404
    if current_user.is_blocked(target):
        return jsonify({"error": "Cannot forward to blocked user"}), 403
    forwarded_content = f"📨 Forwarded from @{original_msg.sender.username}: {original_msg.content}"
    new_msg = Message(sender_id=current_user.id, receiver_id=target.id, content=forwarded_content[:500])
    db.session.add(new_msg)
    db.session.commit()
    room = "_".join(sorted([str(current_user.id), str(target.id)]))
    socketio.emit("new_message", {
        "id": new_msg.id, "sender_id": current_user.id, "sender_username": current_user.username,
        "sender_avatar": current_user.avatar_url, "content": new_msg.content,
        "created_at": new_msg.created_at.isoformat(), "time": new_msg.created_at.strftime("%H:%M")
    }, room=room)
    return jsonify({"success": True, "message_id": new_msg.id})


@app.route("/api/messages/<username>/read", methods=["POST"])
@login_required
def api_mark_read(username):
    if not safe_validate_username(username):
        return jsonify({"error": "Invalid username"}), 400
    partner = User.query.filter(func.lower(User.username) == username.lower()).first_or_404()
    updated = Message.query.filter_by(sender_id=partner.id, receiver_id=current_user.id, is_read=False
                                      ).update({"is_read": True})
    db.session.commit()
    if updated > 0:
        room = "_".join(sorted([str(current_user.id), str(partner.id)]))
        socketio.emit("messages_read", {"reader_id": current_user.id}, room=room)
    return jsonify({"success": True})


@app.route("/api/typing/<username>", methods=["POST"])
@login_required
def api_typing_indicator(username):
    if not safe_validate_username(username):
        return jsonify({"error": "Invalid username"}), 400
    partner = User.query.filter(func.lower(User.username) == username.lower()).first_or_404()
    room = "_".join(sorted([str(current_user.id), str(partner.id)]))
    socketio.emit("typing", {"user_id": current_user.id, "username": current_user.username}, room=room)
    return jsonify({"success": True})


# ──────────────────────────────────────────────────────────────────────────────
#  Report Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/report/user/<int:user_id>", methods=["GET", "POST"])
@login_required
def report_user(user_id):
    reported_user = User.query.get_or_404(user_id)
    if reported_user.id == current_user.id:
        flash("Нельзя пожаловаться на самого себя", "error")
        return redirect(url_for("profile", username=reported_user.username))
    if request.method == "POST":
        reason = request.form.get("reason")
        description = escape_html(request.form.get("description", ""))
        if not reason:
            flash("Укажите причину жалобы", "error")
            return redirect(url_for("report_user", user_id=user_id))
        report = Report(reporter_id=current_user.id, reported_user_id=reported_user.id,
                        reason=reason, description=description, status='pending')
        db.session.add(report)
        db.session.commit()
        flash(f"Жалоба на пользователя {reported_user.username} отправлена", "success")
        return redirect(url_for("profile", username=reported_user.username))
    reasons = [("spam", "Спам"), ("harassment", "Домогательство"), ("hate_speech", "Разжигание ненависти"),
               ("violence", "Насилие"), ("scam", "Мошенничество"), ("fake_account", "Фейковый аккаунт"),
               ("other", "Другое")]
    return render_template("report_user.html", user=reported_user, reasons=reasons)


@app.route("/report/post/<int:post_id>", methods=["GET", "POST"])
@login_required
def report_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id == current_user.id:
        flash("Нельзя пожаловаться на свой пост", "error")
        return redirect(url_for("view_post", post_id=post_id))
    if request.method == "POST":
        reason = request.form.get("reason")
        description = escape_html(request.form.get("description", ""))
        if not reason:
            flash("Укажите причину жалобы", "error")
            return redirect(url_for("report_post", post_id=post_id))
        report = Report(reporter_id=current_user.id, reported_user_id=post.user_id,
                        post_id=post.id, reason=reason, description=description, status='pending')
        db.session.add(report)
        db.session.commit()
        flash(f"Жалоба на пост отправлена", "success")
        return redirect(url_for("view_post", post_id=post_id))
    reasons = [("spam", "Спам"), ("harassment", "Домогательство"), ("hate_speech", "Разжигание ненависти"),
               ("violence", "Насилие"), ("nsfw", "Неприемлемый контент"), ("copyright", "Нарушение авторских прав"),
               ("other", "Другое")]
    return render_template("report_post.html", post=post, reasons=reasons)


@app.route("/report/comment/<int:comment_id>", methods=["GET", "POST"])
@login_required
def report_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.user_id == current_user.id:
        flash("Нельзя пожаловаться на свой комментарий", "error")
        return redirect(url_for("view_post", post_id=comment.post_id))
    if request.method == "POST":
        reason = request.form.get("reason")
        description = escape_html(request.form.get("description", ""))
        if not reason:
            flash("Укажите причину жалобы", "error")
            return redirect(url_for("report_comment", comment_id=comment_id))
        report = Report(reporter_id=current_user.id, reported_user_id=comment.user_id,
                        comment_id=comment.id, reason=reason, description=description, status='pending')
        db.session.add(report)
        db.session.commit()
        flash(f"Жалоба на комментарий отправлена", "success")
        return redirect(url_for("view_post", post_id=comment.post_id))
    return render_template("report_comment.html", comment=comment)


# ──────────────────────────────────────────────────────────────────────────────
#  Auth Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        try:
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm", "")
            if not username or not email or not password:
                flash("Все поля обязательны для заполнения", "error")
                return render_template("register.html")
            if not safe_validate_username(username):
                flash("Имя пользователя должно быть 3-40 символов и содержать только буквы, цифры и подчеркивания",
                      "error")
                return render_template("register.html")
            if not safe_validate_email(email):
                flash("Неверный формат email", "error")
                return render_template("register.html")
            if not safe_validate_password(password):
                flash("Пароль должен быть не менее 8 символов", "error")
                return render_template("register.html")
            if password != confirm:
                flash("Пароли не совпадают", "error")
                return render_template("register.html")
            existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
            if existing_user:
                if existing_user.username == username:
                    flash("Пользователь с таким именем уже существует", "error")
                else:
                    flash("Пользователь с таким email уже существует", "error")
                return render_template("register.html")
            user = User(username=username, email=email, display_name=username, preset_avatar=1,
                        bio="", accent_color="#6c63ff", is_private=False, is_verified=False, is_banned=False)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user, remember=True)
            flash(f"Добро пожаловать в Kildear, {username}! 🎉", "success")
            return redirect(url_for("index"))
        except Exception as e:
            db.session.rollback()
            logger.error(f"Ошибка при регистрации: {str(e)}")
            flash("Произошла ошибка при регистрации. Пожалуйста, попробуйте позже.", "error")
            return render_template("register.html")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))
        ip = get_client_ip()
        user_agent = request.headers.get('User-Agent', '')
        user = User.query.filter(or_(func.lower(User.username) == identifier.lower(),
                                     func.lower(User.email) == identifier.lower())).first()
        login_success = False
        if user and user.check_password(password) and not user.is_banned:
            login_user(user, remember=remember)
            session.permanent = remember
            user.is_online = True
            user.last_seen = datetime.utcnow()
            user.check_and_update_permissions()
            login_success = True
            flash(f"С возвращением, {user.username}! 👋", "success")
        else:
            track_failure(ip)
            flash("Неверные учетные данные.", "error")
        try:
            login_history = LoginHistory(
                user_id=user.id if user else None,
                ip_address=mask_sensitive_data(ip, 2) if is_production else ip,
                user_agent=mask_sensitive_data(user_agent, 10)[:200],
                location=None, success=login_success
            )
            db.session.add(login_history)
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to save login history: {e}")
            db.session.rollback()
        if login_success:
            next_page = request.args.get("next")
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    current_user.is_online = False
    current_user.last_seen = datetime.utcnow()
    db.session.commit()
    logout_user()
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("login"))


# ──────────────────────────────────────────────────────────────────────────────
#  Feed / Home
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    followed_ids = [u.id for u in current_user.following.all()] + [current_user.id]
    blocked_ids = [b.id for b in current_user.blocked_users]
    posts = (Post.query.filter(Post.user_id.in_(followed_ids))
             .filter(Post.user_id.notin_(blocked_ids))
             .order_by(Post.created_at.desc())
             .paginate(page=page, per_page=15, error_out=False))
    suggestions = (User.query.filter(User.id.notin_(followed_ids + blocked_ids))
                   .filter(User.id != current_user.id)
                   .order_by(func.random()).limit(5).all())
    permissions = current_user.check_and_update_permissions()
    return render_template("index.html", posts=posts, suggestions=suggestions, permissions=permissions)


# ──────────────────────────────────────────────────────────────────────────────
#  Posts
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/post/create", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def create_post():
    content = escape_html(request.form.get("content", "").strip())
    media_file = request.files.get("media")
    media_url = ""
    media_type = "text"
    if media_file and media_file.filename:
        try:
            safe_filename = sanitize_filename(media_file.filename)
            if not safe_filename:
                flash("Недопустимое имя файла", "error")
                return redirect(url_for("index"))
            ext = safe_filename.rsplit(".", 1)[-1].lower() if '.' in safe_filename else ''
            if ext in ALLOWED_VIDEO:
                media_url = save_file(media_file, "videos") or ""
                media_type = "video"
            elif ext in ALLOWED_IMAGE:
                media_url = save_file(media_file, "images") or ""
                media_type = "image" if media_url else "text"
            else:
                flash(f"Неподдерживаемый тип файла", "error")
                return redirect(url_for("index"))
        except Exception as e:
            logger.error(f"Ошибка при сохранении файла: {e}")
            flash("Ошибка при загрузке файла", "error")
            return redirect(url_for("index"))
    if not content and not media_url:
        flash("Пост не может быть пустым.", "error")
        return redirect(url_for("index"))
    post = Post(user_id=current_user.id, content=content, media_url=media_url or "", media_type=media_type)
    db.session.add(post)
    db.session.commit()
    follower_count = current_user.follower_count
    hours = get_post_lifetime_hours(follower_count)
    if hours:
        schedule_post_expiration(post.id, 'post', follower_count)
        flash(f"Пост опубликован! Он будет автоматически удалён через {hours} часов.", "info")
    else:
        flash("Пост опубликован!", "success")
    return redirect(url_for("index"))


@app.route("/post/<int:post_id>")
@login_required
def view_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author.id in [b.id for b in current_user.blocked_users]:
        abort(403)
    post.views += 1
    db.session.commit()
    comments = post.comments.order_by(Comment.created_at.asc()).all()
    return render_template("post_detail.html", post=post, comments=comments)


@app.route("/post/<int:post_id>/like", methods=["POST"])
@login_required
def like_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author.id in [b.id for b in current_user.blocked_users]:
        return jsonify({"error": "Cannot interact with blocked user"}), 403
    if post.is_liked_by(current_user):
        post.liked_by.remove(current_user)
        liked = False
    else:
        post.liked_by.append(current_user)
        liked = True
        if post.user_id != current_user.id:
            n = Notification(user_id=post.user_id, from_user_id=current_user.id, type="like",
                             post_id=post.id, text=f"{current_user.username} liked your post.")
            db.session.add(n)
            send_notification(post.user_id, {
                "type": "like", "from_user": {"id": current_user.id, "username": current_user.username,
                                              "avatar": current_user.avatar_url},
                "post_id": post.id, "text": f"{current_user.username} liked your post"
            })
    db.session.commit()
    return jsonify({"liked": liked, "count": post.like_count})


@app.route("/post/<int:post_id>/comment", methods=["POST"])
@login_required
@limiter.limit("60 per hour")
def add_comment(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author.id in [b.id for b in current_user.blocked_users]:
        return jsonify({"error": "Cannot interact with blocked user"}), 403
    content = escape_html(request.form.get("content", "").strip())
    if not content:
        return jsonify({"error": "Comment cannot be empty."}), 400
    c = Comment(post_id=post.id, user_id=current_user.id, content=content)
    db.session.add(c)
    if post.user_id != current_user.id:
        n = Notification(user_id=post.user_id, from_user_id=current_user.id, type="comment",
                         post_id=post.id, text=f"{current_user.username} commented on your post.")
        db.session.add(n)
        send_notification(post.user_id, {
            "type": "comment", "from_user": {"id": current_user.id, "username": current_user.username,
                                             "avatar": current_user.avatar_url},
            "post_id": post.id, "comment": content[:50], "text": f"{current_user.username} commented on your post"
        })
    db.session.commit()
    return jsonify({"id": c.id, "username": current_user.username, "avatar": current_user.avatar_url,
                    "content": c.content, "created_at": c.created_at.strftime("%b %d, %Y")})


@app.route("/post/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        abort(403)
    db.session.delete(post)
    db.session.commit()
    flash("Post deleted.", "info")
    return redirect(url_for("index"))


# ──────────────────────────────────────────────────────────────────────────────
#  Profile
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/u/<username>")
@login_required
def profile(username):
    if not safe_validate_username(username):
        abort(404)
    user = User.query.filter(func.lower(User.username) == username.lower()).first_or_404()
    is_blocked = current_user.is_blocked(user) if user.id != current_user.id else False
    page = request.args.get("page", 1, type=int)
    tab = request.args.get("tab", "posts")
    if is_blocked:
        posts = []
        videos = []
    else:
        posts = user.posts.order_by(Post.created_at.desc()).paginate(page=page, per_page=12, error_out=False)
        videos = user.posts.filter_by(media_type="video").order_by(Post.created_at.desc()).limit(12).all()
    is_own = user.id == current_user.id
    is_following = current_user.is_following(user) if not is_own else False
    permissions = user.check_and_update_permissions() if is_own else None
    return render_template("profile.html", user=user, posts=posts, videos=videos,
                           is_own=is_own, is_following=is_following, is_blocked=is_blocked,
                           tab=tab, permissions=permissions)


@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        try:
            current_user.display_name = escape_html(request.form.get("display_name", "")[:60])
            current_user.bio = escape_html(request.form.get("bio", "")[:500])
            current_user.website = escape_html(request.form.get("website", "")[:200])
            current_user.location = escape_html(request.form.get("location", "")[:100])
            current_user.is_private = bool(request.form.get("is_private"))
            accent_color = request.form.get("accent_color")
            if not accent_color:
                accent_color = request.form.get("accent_color_custom", "#6c63ff")
            if re.match(r'^#[0-9a-fA-F]{6}$', accent_color):
                current_user.accent_color = accent_color[:7]
            preset_avatar = request.form.get("preset_avatar")
            if preset_avatar:
                try:
                    avatar_num = int(preset_avatar)
                    if 1 <= avatar_num <= 10:
                        current_user.set_preset_avatar(avatar_num)
                        flash(f"Avatar {avatar_num} selected!", "success")
                except (ValueError, TypeError):
                    pass
            preset_cover = request.form.get("preset_cover")
            if preset_cover:
                try:
                    cover_num = int(preset_cover)
                    if 1 <= cover_num <= 5:
                        current_user.set_preset_cover(cover_num)
                        flash(f"Cover {cover_num} selected!", "success")
                except (ValueError, TypeError):
                    pass
            elif request.form.get("remove_cover") == "1":
                current_user.set_preset_cover(None)
                flash("Cover removed", "info")
            current_password = request.form.get("current_password")
            new_password = request.form.get("new_password")
            if current_password and new_password:
                if current_user.check_password(current_password):
                    if safe_validate_password(new_password):
                        current_user.set_password(new_password)
                        flash("Password changed successfully!", "success")
                    else:
                        flash("New password must be at least 8 characters", "error")
                else:
                    flash("Current password is incorrect", "error")
            db.session.commit()
            flash("Profile updated successfully!", "success")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating profile: {e}")
            flash(f"Error updating profile", "error")
        return redirect(url_for("profile", username=current_user.username))
    permissions = current_user.check_and_update_permissions()
    return render_template("edit_profile.html", permissions=permissions)


@app.route("/follow/<username>", methods=["POST"])
@login_required
def follow(username):
    if not safe_validate_username(username):
        return jsonify({"error": "Invalid username"}), 400
    user = User.query.filter(func.lower(User.username) == username.lower()).first_or_404()
    if user.id == current_user.id:
        return jsonify({"error": "Cannot follow yourself."}), 400
    if current_user.is_blocked(user):
        return jsonify({"error": "Cannot follow blocked user"}), 400
    if current_user.is_following(user):
        current_user.following.remove(user)
        following = False
    else:
        current_user.following.append(user)
        following = True
        n = Notification(user_id=user.id, from_user_id=current_user.id, type="follow",
                         text=f"{current_user.username} started following you.")
        db.session.add(n)
        send_notification(user.id, {
            "type": "follow", "from_user": {"id": current_user.id, "username": current_user.username,
                                            "avatar": current_user.avatar_url},
            "text": f"{current_user.username} started following you"
        })
    db.session.commit()
    user.check_and_update_permissions()
    return jsonify({"following": following, "followers": user.follower_count})


# ──────────────────────────────────────────────────────────────────────────────
#  Block/Unblock Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/user/<int:user_id>/block", methods=["POST"])
@login_required
def block_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({"error": "Cannot block yourself"}), 400
    if current_user.block(user):
        if current_user.is_following(user):
            current_user.following.remove(user)
        if user.is_following(current_user):
            user.following.remove(current_user)
        db.session.commit()
        return jsonify({"success": True, "blocked": True})
    return jsonify({"error": "User already blocked"}), 400


@app.route("/user/<int:user_id>/unblock", methods=["POST"])
@login_required
def unblock_user(user_id):
    user = User.query.get_or_404(user_id)
    if current_user.unblock(user):
        db.session.commit()
        return jsonify({"success": True, "blocked": False})
    return jsonify({"error": "User not blocked"}), 400


# ──────────────────────────────────────────────────────────────────────────────
#  Video Feed
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/video")
@login_required
def video_feed():
    page = request.args.get("page", 1, type=int)
    blocked_ids = [b.id for b in current_user.blocked_users]
    videos = (Post.query.filter_by(media_type="video")
              .filter(Post.user_id.notin_(blocked_ids))
              .order_by(Post.created_at.desc())
              .paginate(page=page, per_page=10, error_out=False))
    return render_template("video.html", videos=videos)


# ──────────────────────────────────────────────────────────────────────────────
#  Search
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/search")
@login_required
@limiter.limit("60 per minute")
def search():
    q = request.args.get("q", "").strip()
    tab = request.args.get("tab", "people")
    if q.startswith('@'):
        q = q[1:]
    users = []
    posts = []
    groups = []
    channels = []
    blocked_ids = [b.id for b in current_user.blocked_users]
    if q and len(q) <= 100:
        pattern = f"%{escape_html(q)}%"
        users = User.query.filter(or_(User.username.ilike(pattern), User.display_name.ilike(pattern))
                                  ).filter(User.id != current_user.id).filter(User.id.notin_(blocked_ids)).limit(
            20).all()
        posts = Post.query.filter(Post.content.ilike(pattern)).filter(Post.user_id.notin_(blocked_ids)).limit(20).all()
        groups = Group.query.filter(or_(Group.name.ilike(pattern), Group.description.ilike(pattern))).limit(10).all()
        channels = Channel.query.filter(or_(Channel.name.ilike(pattern), Channel.description.ilike(pattern))).limit(
            10).all()
    if request.args.get("ajax") == "1" or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({"users": [{"id": u.id, "username": u.username, "display_name": u.display_name or u.username,
                                   "avatar": u.avatar_url, "is_online": u.is_online} for u in users]})
    return render_template("search.html", q=q, tab=tab, users=users, posts=posts, groups=groups, channels=channels)


# ──────────────────────────────────────────────────────────────────────────────
#  Chat Routes (основные)
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/chat")
@login_required
def chat_list():
    return render_template("chat_list.html")


@app.route("/chat/<username>")
@login_required
def chat(username):
    if not safe_validate_username(username):
        abort(404)
    partner = User.query.filter(func.lower(User.username) == username.lower()).first_or_404()
    is_blocked = current_user.is_blocked(partner)
    if not is_blocked:
        Message.query.filter_by(sender_id=partner.id, receiver_id=current_user.id, is_read=False
                                ).update({"is_read": True})
        db.session.commit()
    return render_template("chat.html", partner=partner, is_blocked=is_blocked)


# ──────────────────────────────────────────────────────────────────────────────
#  Groups
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/groups")
@login_required
def groups():
    my_groups = current_user.groups
    explore = Group.query.filter(~Group.members.any(User.id == current_user.id)).order_by(
        Group.created_at.desc()).limit(20).all()
    return render_template("groups.html", my_groups=my_groups, explore=explore)


@app.route("/groups/create", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per hour")
def create_group():
    if request.method == "POST":
        name = escape_html(request.form.get("name", "").strip()[:100])
        desc = escape_html(request.form.get("description", "").strip()[:500])
        priv = bool(request.form.get("is_private"))
        preset_avatar = int(request.form.get("preset_avatar", 1))
        if preset_avatar not in PRESET_GROUP_AVATARS:
            preset_avatar = 1
        base_slug = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-"))
        slug = base_slug[:50] + f"-{uuid.uuid4().hex[:6]}"
        g = Group(name=name, slug=slug, description=desc, owner_id=current_user.id,
                  is_private=priv, preset_avatar=preset_avatar)
        db.session.add(g)
        db.session.flush()
        g.members.append(current_user)
        db.session.commit()
        flash(f"Группа '{name}' создана!", "success")
        return redirect(url_for("group_detail", slug=g.slug))
    return render_template("create_group.html", preset_avatars=PRESET_GROUP_AVATARS)


@app.route("/groups/<slug>")
@login_required
def group_detail(slug):
    g = Group.query.filter_by(slug=slug).first_or_404()
    is_member = g.members.filter(User.id == current_user.id).count() > 0
    posts = g.posts.order_by(GroupPost.created_at.desc()).limit(30).all()
    is_owner = g.owner_id == current_user.id
    return render_template("group_detail.html", group=g, is_member=is_member, posts=posts, is_owner=is_owner,
                           preset_avatars=PRESET_GROUP_AVATARS)


@app.route("/groups/<slug>/edit", methods=["GET", "POST"])
@login_required
def edit_group(slug):
    g = Group.query.filter_by(slug=slug).first_or_404()
    if g.owner_id != current_user.id and not current_user.is_admin:
        abort(403)
    if request.method == "POST":
        try:
            g.name = escape_html(request.form.get("name", "").strip()[:100])
            g.description = escape_html(request.form.get("description", "").strip()[:500])
            g.is_private = bool(request.form.get("is_private"))
            preset_avatar = request.form.get("preset_avatar", type=int)
            if preset_avatar and preset_avatar in PRESET_GROUP_AVATARS:
                g.set_preset_avatar(preset_avatar)
            db.session.commit()
            flash("Группа обновлена", "success")
            return redirect(url_for("group_detail", slug=g.slug))
        except Exception as e:
            logger.error(f"Error editing group: {e}")
            flash("Ошибка при обновлении группы", "error")
    return render_template("edit_group.html", group=g, preset_avatars=PRESET_GROUP_AVATARS)


@app.route("/groups/<slug>/join", methods=["POST"])
@login_required
def join_group(slug):
    g = Group.query.filter_by(slug=slug).first_or_404()
    if not g.members.filter(User.id == current_user.id).count():
        g.members.append(current_user)
        db.session.commit()
        flash(f"Вы присоединились к группе '{g.name}'", "success")
    else:
        flash("Вы уже участник этой группы", "info")
    return redirect(url_for("group_detail", slug=slug))


@app.route("/groups/<slug>/leave", methods=["POST"])
@login_required
def leave_group(slug):
    g = Group.query.filter_by(slug=slug).first_or_404()
    if g.owner_id == current_user.id:
        flash("Владелец не может покинуть группу", "error")
    elif g.members.filter(User.id == current_user.id).count():
        g.members.remove(current_user)
        db.session.commit()
        flash(f"Вы покинули группу '{g.name}'", "info")
    return redirect(url_for("group_detail", slug=slug))


@app.route("/admin/database")
@login_required
@admin_required
def admin_database():
    inspector = db.inspect(db.engine)
    tables = inspector.get_table_names()
    db_size = None
    if is_render:
        try:
            result = db.session.execute(text("SELECT pg_database_size(current_database())"))
            db_size = result.scalar()
        except:
            pass
    return render_template("admin/database.html", tables=tables, db_size=db_size)


@app.route("/groups/<slug>/post", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def group_post(slug):
    g = Group.query.filter_by(slug=slug).first_or_404()
    if not g.members.filter(User.id == current_user.id).count():
        abort(403)
    content = escape_html(request.form.get("content", "").strip())
    media_file = request.files.get("media")
    media_url = ""
    media_type = "text"
    if media_file and media_file.filename:
        safe_filename = sanitize_filename(media_file.filename)
        if safe_filename:
            ext = safe_filename.rsplit(".", 1)[-1].lower()
            if ext in ALLOWED_VIDEO:
                media_url = save_file(media_file, "videos") or ""
                media_type = "video"
            elif ext in ALLOWED_IMAGE:
                media_url = save_file(media_file, "images") or ""
                media_type = "image" if media_url else "text"
    p = GroupPost(group_id=g.id, user_id=current_user.id, content=content, media_url=media_url or "",
                  media_type=media_type)
    db.session.add(p)
    db.session.commit()
    author_data = {"id": current_user.id, "username": current_user.username,
                   "display_name": current_user.display_name, "avatar": current_user.avatar_url}
    post_data = {"id": p.id, "content": p.content, "media_url": p.media_url,
                 "media_type": p.media_type, "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                 "author": author_data}
    group_room = f"group_{g.id}"
    socketio.emit("new_group_post", {"group_id": g.id, "group_slug": g.slug,
                                     "group_name": g.name, "post": post_data}, room=group_room)
    for member in g.members:
        if member.id != current_user.id:
            notif = Notification(user_id=member.id, from_user_id=current_user.id, type="group_post",
                                 text=f"New post in {g.name}")
            db.session.add(notif)
            send_notification(member.id, {"type": "group_post", "from_user": author_data,
                                          "group": {"id": g.id, "name": g.name, "slug": g.slug},
                                          "post": post_data, "text": f"New post in {g.name}"})
    db.session.commit()
    flash("Пост опубликован в группе!", "success")
    return redirect(url_for("group_detail", slug=slug))


# ──────────────────────────────────────────────────────────────────────────────
#  Channels
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/channels")
@login_required
def channels():
    my_channels = current_user.subscribed_channels
    explore = Channel.query.filter(~Channel.subscribers.any(User.id == current_user.id)).order_by(
        Channel.created_at.desc()).limit(20).all()
    return render_template("channels.html", my_channels=my_channels, explore=explore)


@app.route("/channels/create", methods=["GET", "POST"])
@login_required
@limiter.limit("5 per hour")
def create_channel():
    if request.method == "POST":
        name = escape_html(request.form.get("name", "").strip()[:100])
        desc = escape_html(request.form.get("description", "").strip()[:500])
        preset_avatar = int(request.form.get("preset_avatar", 1))
        if preset_avatar not in PRESET_CHANNEL_AVATARS:
            preset_avatar = 1
        base_slug = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-"))
        slug = base_slug[:50] + f"-{uuid.uuid4().hex[:6]}"
        c = Channel(name=name, slug=slug, description=desc, owner_id=current_user.id, preset_avatar=preset_avatar)
        db.session.add(c)
        db.session.flush()
        c.subscribers.append(current_user)
        db.session.commit()
        flash(f"Канал '{name}' создан!", "success")
        return redirect(url_for("channel_detail", slug=c.slug))
    return render_template("create_channel.html", preset_avatars=PRESET_CHANNEL_AVATARS)


@app.route("/channels/<slug>")
@login_required
def channel_detail(slug):
    c = Channel.query.filter_by(slug=slug).first_or_404()
    is_sub = c.subscribers.filter(User.id == current_user.id).count() > 0
    posts = c.posts.order_by(ChannelPost.created_at.desc()).limit(30).all()
    is_own = c.owner_id == current_user.id
    return render_template("channel_detail.html", channel=c, is_subscribed=is_sub, posts=posts, is_own=is_own,
                           preset_avatars=PRESET_CHANNEL_AVATARS)


@app.route("/channels/<slug>/edit", methods=["GET", "POST"])
@login_required
def edit_channel(slug):
    c = Channel.query.filter_by(slug=slug).first_or_404()
    if c.owner_id != current_user.id and not current_user.is_admin:
        abort(403)
    if request.method == "POST":
        try:
            c.name = escape_html(request.form.get("name", "").strip()[:100])
            c.description = escape_html(request.form.get("description", "").strip()[:500])
            c.is_nsfw = bool(request.form.get("is_nsfw"))
            preset_avatar = request.form.get("preset_avatar", type=int)
            if preset_avatar and preset_avatar in PRESET_CHANNEL_AVATARS:
                c.set_preset_avatar(preset_avatar)
            db.session.commit()
            flash("Канал обновлен", "success")
            return redirect(url_for("channel_detail", slug=c.slug))
        except Exception as e:
            logger.error(f"Error editing channel: {e}")
            flash("Ошибка при обновлении канала", "error")
    return render_template("edit_channel.html", channel=c, preset_avatars=PRESET_CHANNEL_AVATARS)


@app.route("/channels/<slug>/subscribe", methods=["POST"])
@login_required
def subscribe_channel(slug):
    c = Channel.query.filter_by(slug=slug).first_or_404()
    if c.subscribers.filter(User.id == current_user.id).count():
        c.subscribers.remove(current_user)
        subscribed = False
        flash(f"Вы отписались от канала '{c.name}'", "info")
    else:
        c.subscribers.append(current_user)
        subscribed = True
        flash(f"Вы подписались на канал '{c.name}'", "success")
    db.session.commit()
    return jsonify({"subscribed": subscribed, "count": c.sub_count})


@app.route("/channels/<slug>/publish", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def channel_publish(slug):
    c = Channel.query.filter_by(slug=slug).first_or_404()
    if c.owner_id != current_user.id:
        abort(403)
    content = escape_html(request.form.get("content", "").strip())
    media_file = request.files.get("media")
    media_url = ""
    media_type = "text"
    if media_file and media_file.filename:
        safe_filename = sanitize_filename(media_file.filename)
        if safe_filename:
            ext = safe_filename.rsplit(".", 1)[-1].lower()
            if ext in ALLOWED_VIDEO:
                media_url = save_file(media_file, "videos") or ""
                media_type = "video"
            elif ext in ALLOWED_IMAGE:
                media_url = save_file(media_file, "images") or ""
                media_type = "image" if media_url else "text"
    p = ChannelPost(channel_id=c.id, content=content, media_url=media_url or "", media_type=media_type)
    db.session.add(p)
    db.session.commit()
    post_data = {"id": p.id, "content": p.content, "media_url": p.media_url,
                 "media_type": p.media_type, "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S")}
    channel_room = f"channel_{c.id}"
    socketio.emit("new_channel_post", {"channel_id": c.id, "channel_slug": c.slug,
                                       "channel_name": c.name, "post": post_data}, room=channel_room)
    for subscriber in c.subscribers:
        if subscriber.id != current_user.id:
            notif = Notification(user_id=subscriber.id, from_user_id=current_user.id, type="channel_post",
                                 text=f"New post in {c.name}")
            db.session.add(notif)
            send_notification(subscriber.id, {"type": "channel_post",
                                              "from_user": {"id": current_user.id, "username": current_user.username},
                                              "channel": {"id": c.id, "name": c.name, "slug": c.slug},
                                              "post": post_data, "text": f"New post in {c.name}"})
    db.session.commit()
    flash("Пост опубликован в канале!", "success")
    return redirect(url_for("channel_detail", slug=slug))


# ──────────────────────────────────────────────────────────────────────────────
#  Notifications
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/notifications")
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(
        50).all()
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return render_template("notifications.html", notifs=notifs)


# ──────────────────────────────────────────────────────────────────────────────
#  Debug endpoint (only for admin)
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/debug/uploads")
@login_required
def debug_uploads():
    if not current_user.is_admin:
        abort(403)
    upload_folder = app.config['UPLOAD_FOLDER']
    result = {"upload_folder": upload_folder, "exists": os.path.exists(upload_folder), "is_render": is_render,
              "subfolders": {}}
    if os.path.exists(upload_folder):
        for subfolder in UPLOAD_SUBFOLDERS:
            path = os.path.join(upload_folder, subfolder)
            if os.path.exists(path):
                try:
                    files = os.listdir(path)[-20:]
                    result['subfolders'][subfolder] = {"path": path, "exists": True,
                                                       "writable": os.access(path, os.W_OK),
                                                       "file_count": len(os.listdir(path)), "recent_files": files}
                except Exception as e:
                    result['subfolders'][subfolder] = {"path": path, "exists": True, "error": str(e)}
            else:
                result['subfolders'][subfolder] = {"path": path, "exists": False}
    result['preset_stats'] = {
        'users_with_preset_avatar': User.query.filter(User.preset_avatar.isnot(None)).count(),
        'users_with_preset_cover': User.query.filter(User.preset_cover.isnot(None)).count(),
        'groups_with_preset_avatar': Group.query.filter(Group.preset_avatar.isnot(None)).count(),
        'channels_with_preset_avatar': Channel.query.filter(Channel.preset_avatar.isnot(None)).count()
    }
    return jsonify(result)


# ──────────────────────────────────────────────────────────────────────────────
#  Achievements Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/achievements")
@login_required
def achievements():
    all_achievements = [
        {"id": "first_post", "name": "First Post", "description": "Create your first post", "icon": "📝"},
        {"id": "popular_post", "name": "Popular Post", "description": "Get 100 likes on a single post", "icon": "❤️"},
        {"id": "100_followers", "name": "Growing Star", "description": "Reach 100 followers", "icon": "⭐"},
        {"id": "1000_followers", "name": "Influencer", "description": "Reach 1000 followers", "icon": "🏆"},
        {"id": "5000_followers", "name": "Superstar", "description": "Reach 5000 followers", "icon": "👑"},
        {"id": "group_member", "name": "Team Player", "description": "Join a group", "icon": "👥"},
        {"id": "channel_subscriber", "name": "Channel Surfer", "description": "Subscribe to a channel", "icon": "📢"},
        {"id": "message_sent", "name": "Social Butterfly", "description": "Send 50 messages", "icon": "💬"},
    ]
    user_achievements = {a.achievement_type for a in current_user.achievements}
    post_count = current_user.post_count
    follower_count = current_user.follower_count
    groups_count = current_user.groups.count()
    channels_count = current_user.subscribed_channels.count()
    messages_sent = Message.query.filter_by(sender_id=current_user.id).count()
    max_likes = db.session.query(func.max(Post.like_count)).filter_by(user_id=current_user.id).scalar() or 0
    new_achievements = []
    if post_count >= 1 and "first_post" not in user_achievements:
        new_achievements.append(UserAchievement(user_id=current_user.id, achievement_type="first_post"))
    if max_likes >= 100 and "popular_post" not in user_achievements:
        new_achievements.append(UserAchievement(user_id=current_user.id, achievement_type="popular_post"))
    if follower_count >= 100 and "100_followers" not in user_achievements:
        new_achievements.append(UserAchievement(user_id=current_user.id, achievement_type="100_followers"))
    if follower_count >= 1000 and "1000_followers" not in user_achievements:
        new_achievements.append(UserAchievement(user_id=current_user.id, achievement_type="1000_followers"))
    if follower_count >= 5000 and "5000_followers" not in user_achievements:
        new_achievements.append(UserAchievement(user_id=current_user.id, achievement_type="5000_followers"))
    if groups_count >= 1 and "group_member" not in user_achievements:
        new_achievements.append(UserAchievement(user_id=current_user.id, achievement_type="group_member"))
    if channels_count >= 1 and "channel_subscriber" not in user_achievements:
        new_achievements.append(UserAchievement(user_id=current_user.id, achievement_type="channel_subscriber"))
    if messages_sent >= 50 and "message_sent" not in user_achievements:
        new_achievements.append(UserAchievement(user_id=current_user.id, achievement_type="message_sent"))
    if new_achievements:
        for ach in new_achievements:
            db.session.add(ach)
        db.session.commit()
    earned_count = len(user_achievements) + len(new_achievements)
    total_count = len(all_achievements)
    return render_template("achievements.html", achievements=all_achievements, earned=earned_count, total=total_count)


# ──────────────────────────────────────────────────────────────────────────────
#  WebSocket Helper Functions
# ──────────────────────────────────────────────────────────────────────────────

def send_notification(user_id, notification_data):
    user_room = f"user_{user_id}"
    socketio.emit("new_notification", notification_data, room=user_room)


def send_group_update(group_id, update_data):
    group_room = f"group_{group_id}"
    socketio.emit("group_update", update_data, room=group_room)


def send_channel_update(channel_id, update_data):
    channel_room = f"channel_{channel_id}"
    socketio.emit("channel_update", update_data, room=channel_room)


# ──────────────────────────────────────────────────────────────────────────────
#  Socket.IO Events
# ──────────────────────────────────────────────────────────────────────────────

@socketio.on("connect")
def handle_connect():
    if current_user.is_authenticated:
        logger.info(f"User {mask_sensitive_data(str(current_user.id))} connected")
        user_room = f"user_{current_user.id}"
        join_room(user_room)


@socketio.on("disconnect")
def handle_disconnect():
    if current_user.is_authenticated:
        logger.info(f"User {mask_sensitive_data(str(current_user.id))} disconnected")
        current_user.is_online = False
        current_user.last_seen = datetime.utcnow()
        db.session.commit()


@socketio.on("join_chat")
def on_join(data):
    room = data.get("room")
    if room:
        join_room(room)
        emit("status", {"msg": "joined"}, room=room)


@socketio.on("leave_chat")
def on_leave(data):
    room = data.get("room")
    if room:
        leave_room(room)


@socketio.on("typing")
def on_typing(data):
    room = data.get("room")
    user = data.get("user")
    if room and user:
        emit("typing", {"user": user}, room=room, include_self=False)


@socketio.on("join_group_room")
def on_join_group(data):
    group_id = data.get("group_id")
    if group_id and current_user.is_authenticated:
        group = Group.query.get(group_id)
        if group and group.members.filter(User.id == current_user.id).count() > 0:
            room = f"group_{group_id}"
            join_room(room)


@socketio.on("leave_group_room")
def on_leave_group(data):
    group_id = data.get("group_id")
    if group_id:
        room = f"group_{group_id}"
        leave_room(room)


@socketio.on("join_channel_room")
def on_join_channel(data):
    channel_id = data.get("channel_id")
    if channel_id and current_user.is_authenticated:
        channel = Channel.query.get(channel_id)
        if channel and channel.subscribers.filter(User.id == current_user.id).count() > 0:
            room = f"channel_{channel_id}"
            join_room(room)


@socketio.on("leave_channel_room")
def on_leave_channel(data):
    channel_id = data.get("channel_id")
    if channel_id:
        room = f"channel_{channel_id}"
        leave_room(room)


@socketio.on("join_user_room")
def on_join_user():
    if current_user.is_authenticated:
        user_room = f"user_{current_user.id}"
        join_room(user_room)


# ──────────────────────────────────────────────────────────────────────────────
#  WebRTC Signaling
# ──────────────────────────────────────────────────────────────────────────────

@socketio.on("webrtc_offer")
def on_webrtc_offer(data):
    room = data.get("room")
    if room:
        emit("webrtc_offer", {"offer": data.get("offer"), "from": current_user.id}, room=room, include_self=False)


@socketio.on("webrtc_answer")
def on_webrtc_answer(data):
    room = data.get("room")
    if room:
        emit("webrtc_answer", {"answer": data.get("answer"), "from": current_user.id}, room=room, include_self=False)


@socketio.on("webrtc_ice_candidate")
def on_webrtc_ice_candidate(data):
    room = data.get("room")
    if room:
        emit("webrtc_ice_candidate", {"candidate": data.get("candidate"), "from": current_user.id}, room=room,
             include_self=False)


# ──────────────────────────────────────────────────────────────────────────────
#  Background Tasks
# ──────────────────────────────────────────────────────────────────────────────

def start_background_tasks():
    import threading
    def cleanup_task():
        while True:
            time.sleep(3600)
            with app.app_context():
                cleanup_expired_posts()

    thread = threading.Thread(target=cleanup_task, daemon=True)
    thread.start()
    logger.info("Background cleanup task started")


# ──────────────────────────────────────────────────────────────────────────────
#  Error Handlers
# ──────────────────────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, msg="Page not found."), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, msg="Access forbidden."), 403


@app.errorhandler(429)
def too_many(e):
    return render_template("error.html", code=429, msg="Too many requests. Please slow down."), 429


@app.errorhandler(413)
def too_large(e):
    return render_template("error.html", code=413, msg="File too large. Maximum upload size is 100 MB."), 413


@app.errorhandler(500)
def server_error(e):
    logger.error(f"Server error: {e}")
    return render_template("error.html", code=500, msg="Internal server error."), 500


# ──────────────────────────────────────────────────────────────────────────────
#  Static / Uploads
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/static/uploads/<path:filename>")
def uploaded_file(filename):
    safe_filename = os.path.basename(filename)
    return send_from_directory(app.config["UPLOAD_FOLDER"], safe_filename)


@app.route("/uploads/<path:subfolder>/<path:filename>")
def serve_upload(subfolder, filename):
    if subfolder not in UPLOAD_SUBFOLDERS:
        abort(404)
    safe_filename = os.path.basename(filename)
    safe_subfolder = os.path.basename(subfolder)
    if safe_subfolder not in UPLOAD_SUBFOLDERS:
        abort(404)
    try:
        file_path = safe_path_join(app.config['UPLOAD_FOLDER'], safe_subfolder, safe_filename)
    except ValueError:
        abort(404)
    if not os.path.exists(file_path):
        abort(404)
    return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], safe_subfolder), safe_filename)


# ──────────────────────────────────────────────────────────────────────────────
#  Create Admin User & Initialization
# ──────────────────────────────────────────────────────────────────────────────

def create_admin_user():
    try:
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin_password = os.environ.get('ADMIN_PASSWORD', secrets.token_urlsafe(12))
            admin = User(username='admin', email='admin@kildear.com', display_name='Administrator',
                         is_admin=True, is_verified=True, preset_avatar=1)
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            logger.info("✅ Администратор создан")
            logger.info(f"   👤 Username: admin")
            logger.info(f"   🔑 Password: {admin_password}")
            logger.info("   ⚠️  Смените пароль после первого входа!")
        else:
            logger.info("✅ Администратор уже существует")
    except Exception as e:
        logger.error(f"❌ Ошибка при создании администратора: {e}")


def run_migrations():
    try:
        inspector = db.inspect(db.engine)
        tables = inspector.get_table_names()
        if 'message' in tables:
            columns = [col['name'] for col in inspector.get_columns('message')]
            if 'is_edited' not in columns:
                if is_render:
                    db.session.execute(text('ALTER TABLE message ADD COLUMN is_edited BOOLEAN DEFAULT FALSE'))
                    db.session.execute(text('ALTER TABLE message ADD COLUMN edit_count INTEGER DEFAULT 0'))
                    db.session.execute(text('ALTER TABLE message ADD COLUMN updated_at TIMESTAMP'))
                else:
                    db.session.execute(text('ALTER TABLE message ADD COLUMN is_edited BOOLEAN DEFAULT 0'))
                    db.session.execute(text('ALTER TABLE message ADD COLUMN edit_count INTEGER DEFAULT 0'))
                    db.session.execute(text('ALTER TABLE message ADD COLUMN updated_at TIMESTAMP'))
                logger.info("➕ Добавлены колонки is_edited, edit_count, updated_at в message")
        db.session.commit()
        logger.info("🎉 Миграция базы данных завершена успешно!")
    except Exception as e:
        logger.error(f"❌ Ошибка при миграции: {e}")
        db.session.rollback()


def init_app():
    with app.app_context():
        try:
            db.create_all()
            logger.info("✅ Базовые таблицы созданы")
            run_migrations()
            ensure_upload_folders()
            test_file = os.path.join(app.config['UPLOAD_FOLDER'], 'test.txt')
            try:
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                logger.info("✅ Временная папка доступна для записи")
            except Exception as e:
                logger.warning(f"⚠️ Временная папка может быть недоступна: {e}")
            create_admin_user()
            start_background_tasks()
            logger.info("🎉 Инициализация приложения завершена!")
        except Exception as e:
            logger.error(f"❌ Ошибка при инициализации: {e}")


# ──────────────────────────────────────────────────────────────────────────────
#  Main Entry Point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_app()
    port = int(os.environ.get("PORT", 5000))
    print("\n" + "=" * 70)
    print("🚀 ЗАПУСК KILDEAR SOCIAL NETWORK (С ИСПРАВЛЕННЫМ МЕССЕНДЖЕРОМ)")
    print("=" * 70)
    print(f"🌐 Сервер запускается на порту: {port}")
    print(f"🎯 Режим: {'PRODUCTION' if is_production else 'DEVELOPMENT'}")
    print("=" * 70)
    print("📝 Функционал МЕССЕНДЖЕРА:")
    print("   ✅ Отправка текстовых сообщений")
    print("   ✅ Эмодзи (через picker)")
    print("   ✅ Ответ на сообщение (reply)")
    print("   ✅ Удаление сообщения")
    print("   ✅ Пересылка сообщения (forward)")
    print("   ✅ Редактирование сообщения (edit)")
    print("   ✅ Аудиозвонки (WebRTC)")
    print("   ✅ Индикатор набора текста")
    print("   ✅ Статус прочтения")
    print("=" * 70)
    print("📝 Для остановки нажмите Ctrl+C")
    print("=" * 70 + "\n")
    if is_production:
        socketio.run(app, host="0.0.0.0", port=port)
    else:
        socketio.run(app, debug=True, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)
