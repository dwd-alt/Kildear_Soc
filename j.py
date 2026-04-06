"""
Kildear Social Network — Complete Version
Full-featured backend with admin panel, voice messages, calls, stickers, locations, and reactions
"""

import os
import re
import time
import uuid
import base64
import logging
import platform
import json
import hashlib
import secrets
from io import BytesIO
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps
from urllib.parse import urlparse

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, abort, session, send_from_directory,
                   make_response)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                         login_required, current_user)
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import or_, func, and_, text, desc
from PIL import Image
import qrcode
from itsdangerous import URLSafeTimedSerializer

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
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB
else:
    UPLOAD_FOLDER = os.path.join('static', 'uploads')
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024

UPLOAD_SUBFOLDERS = ['images', 'videos', 'chat_images', 'stickers', 'voice_messages', 'avatars', 'covers']

ALLOWED_IMAGE = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
ALLOWED_VIDEO = {"mp4", "webm", "mov", "avi", "mkv", "flv"}
ALLOWED_AUDIO = {"mp3", "wav", "ogg", "m4a", "webm", "aac"}

# Preset avatars (1-10)
PRESET_AVATARS = {
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

# Preset covers (1-5)
PRESET_COVERS = {
    1: '/static/covers/preset/1cover.jpg',
    2: '/static/covers/preset/2cover.jpg',
    3: '/static/covers/preset/3cover.jpg',
    4: '/static/covers/preset/4cover.jpg',
    5: '/static/covers/preset/5cover.jpg',
}

app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", secrets.token_hex(32)),
    SQLALCHEMY_DATABASE_URI=SQLALCHEMY_DATABASE_URI,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 10,
        "max_overflow": 20
    } if is_render else {},
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    WTF_CSRF_TIME_LIMIT=3600,
    WTF_CSRF_SECRET_KEY=os.environ.get("WTF_CSRF_SECRET_KEY", secrets.token_hex(32)),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=is_production,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    REMEMBER_COOKIE_DURATION=timedelta(days=14),
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SECURE=is_production,
    SESSION_REFRESH_EACH_REQUEST=True,
    PREFERRED_URL_SCHEME='https' if is_production else 'http'
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
    default_limits=["200 per minute", "2000 per hour", "5000 per day"],
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
    max_http_buffer_size=10e6,
    manage_session=False
)

# Serializer for email tokens
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])


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


@app.template_filter('truncate')
def truncate_filter(s, length=100):
    if not s:
        return ''
    return s[:length] + '...' if len(s) > length else s


@app.template_filter('nl2br')
def nl2br_filter(s):
    if not s:
        return ''
    return s.replace('\n', '<br>')


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


def moderator_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or (
                not current_user.is_admin and not getattr(current_user, 'is_moderator', False)):
            abort(403)
        return f(*args, **kwargs)

    return decorated_function


# ──────────────────────────────────────────────────────────────────────────────
#  Database Models
# ──────────────────────────────────────────────────────────────────────────────

follows = db.Table(
    "follows",
    db.Column("follower_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("followed_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("created_at", db.DateTime, default=datetime.utcnow)
)

post_likes = db.Table(
    "post_likes",
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("post_id", db.Integer, db.ForeignKey("post.id"), primary_key=True),
    db.Column("created_at", db.DateTime, default=datetime.utcnow)
)

post_saves = db.Table(
    "post_saves",
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("post_id", db.Integer, db.ForeignKey("post.id"), primary_key=True),
    db.Column("created_at", db.DateTime, default=datetime.utcnow)
)

group_members = db.Table(
    "group_members",
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("group_id", db.Integer, db.ForeignKey("group.id"), primary_key=True),
    db.Column("joined_at", db.DateTime, default=datetime.utcnow),
    db.Column("role", db.String(20), default="member")
)

channel_subs = db.Table(
    "channel_subs",
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("channel_id", db.Integer, db.ForeignKey("channel.id"), primary_key=True),
    db.Column("subscribed_at", db.DateTime, default=datetime.utcnow)
)

blocks = db.Table(
    "blocks",
    db.Column("blocker_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("blocked_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("created_at", db.DateTime, default=datetime.utcnow)
)

mutes = db.Table(
    "mutes",
    db.Column("muter_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("muted_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("created_at", db.DateTime, default=datetime.utcnow)
)


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(60), default="")
    bio = db.Column(db.String(500), default="")

    preset_avatar = db.Column(db.Integer, default=1)
    preset_cover = db.Column(db.Integer, nullable=True)
    custom_avatar = db.Column(db.String(300), default="")
    custom_cover = db.Column(db.String(300), default="")

    website = db.Column(db.String(200), default="")
    location = db.Column(db.String(100), default="")
    birthday = db.Column(db.Date, nullable=True)
    accent_color = db.Column(db.String(7), default="#6c63ff")

    is_private = db.Column(db.Boolean, default=False)
    is_verified = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_moderator = db.Column(db.Boolean, default=False)
    is_online = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 2FA
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_secret = db.Column(db.String(32), nullable=True)

    # Email verification
    email_verified = db.Column(db.Boolean, default=False)
    email_verify_token = db.Column(db.String(100), nullable=True)

    # Password reset
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)

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

    muted_users = db.relationship(
        "User", secondary=mutes,
        primaryjoin=mutes.c.muter_id == id,
        secondaryjoin=mutes.c.muted_id == id,
        backref=db.backref("muted_by", lazy="dynamic"),
        lazy="dynamic"
    )

    posts = db.relationship("Post", backref="author", lazy="dynamic", foreign_keys="Post.user_id")
    sent_msgs = db.relationship("Message", backref="sender", lazy="dynamic", foreign_keys="Message.sender_id")
    recv_msgs = db.relationship("Message", backref="receiver", lazy="dynamic", foreign_keys="Message.receiver_id")
    notifications = db.relationship("Notification", backref="recipient", lazy="dynamic",
                                    foreign_keys="Notification.user_id")
    comments = db.relationship("Comment", backref="author", lazy="dynamic")
    owned_groups = db.relationship("Group", backref="owner", lazy="dynamic")
    owned_channels = db.relationship("Channel", backref="owner", lazy="dynamic")
    login_history = db.relationship("LoginHistory", backref="user", lazy="dynamic")
    message_reactions = db.relationship("MessageReaction", backref="user", lazy="dynamic")

    @property
    def avatar_url(self):
        if self.custom_avatar and os.path.exists(
                os.path.join(app.config['UPLOAD_FOLDER'], 'avatars', self.custom_avatar)):
            return f"/static/uploads/avatars/{self.custom_avatar}"
        if self.preset_avatar and self.preset_avatar in PRESET_AVATARS:
            return PRESET_AVATARS[self.preset_avatar]
        return PRESET_AVATARS[1]

    @property
    def cover_url(self):
        if self.custom_cover and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], 'covers', self.custom_cover)):
            return f"/static/uploads/covers/{self.custom_cover}"
        if self.preset_cover and self.preset_cover in PRESET_COVERS:
            return PRESET_COVERS[self.preset_cover]
        return None

    def set_preset_avatar(self, avatar_num):
        if 1 <= avatar_num <= 10:
            self.preset_avatar = avatar_num
            self.custom_avatar = ""
            return True
        return False

    def set_custom_avatar(self, filename):
        self.custom_avatar = filename
        self.preset_avatar = None

    def set_preset_cover(self, cover_num):
        if cover_num is None:
            self.preset_cover = None
            return True
        if 1 <= cover_num <= 5:
            self.preset_cover = cover_num
            self.custom_cover = ""
            return True
        return False

    def set_custom_cover(self, filename):
        self.custom_cover = filename
        self.preset_cover = None

    def set_password(self, pw: str):
        self.password_hash = generate_password_hash(pw, method='scrypt')

    def check_password(self, pw: str) -> bool:
        return check_password_hash(self.password_hash, pw)

    def is_following(self, user):
        return self.following.filter(follows.c.followed_id == user.id).count() > 0

    def is_blocked(self, user):
        return self.blocked_users.filter(blocks.c.blocked_id == user.id).count() > 0

    def is_muted(self, user):
        return self.muted_users.filter(mutes.c.muted_id == user.id).count() > 0

    def block(self, user):
        if not self.is_blocked(user):
            self.blocked_users.append(user)
            return True
        return False

    def unblock(self, user):
        if self.is_blocked(user):
            self.blocked_users.remove(user)
            return True
        return False

    def mute(self, user):
        if not self.is_muted(user):
            self.muted_users.append(user)
            return True
        return False

    def unmute(self, user):
        if self.is_muted(user):
            self.muted_users.remove(user)
            return True
        return False

    @property
    def follower_count(self):
        return self.followers.count()

    @property
    def following_count(self):
        return self.following.count()

    @property
    def post_count(self):
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

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name or self.username,
            "avatar": self.avatar_url,
            "is_online": self.is_online,
            "is_verified": self.is_verified,
            "accent_color": self.accent_color
        }


class UserSettings(db.Model):
    __tablename__ = "user_settings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)

    # Notification settings
    notify_likes = db.Column(db.Boolean, default=True)
    notify_comments = db.Column(db.Boolean, default=True)
    notify_follows = db.Column(db.Boolean, default=True)
    notify_messages = db.Column(db.Boolean, default=True)
    notify_voice_messages = db.Column(db.Boolean, default=True)
    notify_calls = db.Column(db.Boolean, default=True)
    notify_group_posts = db.Column(db.Boolean, default=True)
    notify_channel_posts = db.Column(db.Boolean, default=True)
    notify_mentions = db.Column(db.Boolean, default=True)

    # Sound settings
    sound_enabled = db.Column(db.Boolean, default=True)
    sound_volume = db.Column(db.Integer, default=70)
    call_sound_enabled = db.Column(db.Boolean, default=True)
    notification_sound = db.Column(db.String(50), default="default")
    message_sound = db.Column(db.String(50), default="default")

    # Privacy settings
    show_last_seen = db.Column(db.Boolean, default=True)
    show_online_status = db.Column(db.Boolean, default=True)
    show_followers = db.Column(db.Boolean, default=True)
    show_following = db.Column(db.Boolean, default=True)
    allow_messages_from = db.Column(db.String(20), default="everyone")
    allow_calls_from = db.Column(db.String(20), default="everyone")
    allow_voice_messages_from = db.Column(db.String(20), default="everyone")
    show_profile_photo = db.Column(db.Boolean, default=True)
    show_bio = db.Column(db.Boolean, default=True)
    show_email = db.Column(db.Boolean, default=False)

    # Chat settings
    chat_background = db.Column(db.String(200), default="")
    bubble_color_own = db.Column(db.String(7), default="#6c63ff")
    bubble_color_other = db.Column(db.String(7), default="#e4e6eb")
    enter_to_send = db.Column(db.Boolean, default=False)
    show_typing = db.Column(db.Boolean, default=True)
    show_read_receipts = db.Column(db.Boolean, default=True)
    show_delivery_receipts = db.Column(db.Boolean, default=True)

    # Appearance
    theme = db.Column(db.String(20), default="dark")
    font_size = db.Column(db.String(10), default="medium")
    chat_font_size = db.Column(db.String(10), default="medium")
    default_scale = db.Column(db.Integer, default=100)

    # Animation
    animations_enabled = db.Column(db.Boolean, default=True)
    animation_speed = db.Column(db.String(10), default="normal")
    reduce_motion = db.Column(db.Boolean, default=False)

    # Language
    language = db.Column(db.String(10), default="ru")

    # Folders
    folders_data = db.Column(db.Text, default="[]")

    # Advanced
    save_edited_messages = db.Column(db.Boolean, default=True)
    auto_delete_messages = db.Column(db.Integer, default=0)
    data_saver_mode = db.Column(db.Boolean, default=False)
    auto_play_videos = db.Column(db.Boolean, default=True)
    auto_play_gifs = db.Column(db.Boolean, default=True)
    preload_images = db.Column(db.Boolean, default=True)

    # Camera & Mic
    camera_enabled = db.Column(db.Boolean, default=True)
    mic_enabled = db.Column(db.Boolean, default=True)

    # Battery
    battery_saver_mode = db.Column(db.Boolean, default=False)
    reduce_animations = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("settings", uselist=False))


class LoginHistory(db.Model):
    __tablename__ = "login_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    ip_address = db.Column(db.String(45), nullable=False)
    user_agent = db.Column(db.String(500))
    location = db.Column(db.String(100))
    device_type = db.Column(db.String(50))
    success = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="login_history")


class VoiceMessage(db.Model):
    __tablename__ = "voice_message"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    audio_data = db.Column(db.Text, nullable=False)
    audio_mime = db.Column(db.String(50), default="audio/webm")
    audio_url = db.Column(db.String(300), default="")
    duration = db.Column(db.Integer, default=0)
    is_read = db.Column(db.Boolean, default=False)
    is_listened = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def audio_url_data(self):
        if self.audio_data:
            return f"data:{self.audio_mime};base64,{self.audio_data}"
        return self.audio_url

    sender = db.relationship("User", foreign_keys=[sender_id], backref="sent_voice_msgs")
    receiver = db.relationship("User", foreign_keys=[receiver_id], backref="received_voice_msgs")


class Call(db.Model):
    __tablename__ = "call"

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
    __tablename__ = "report"

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reported_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey("comment.id"), nullable=True)
    message_id = db.Column(db.Integer, db.ForeignKey("message.id"), nullable=True)
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
    __tablename__ = "post"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    content = db.Column(db.Text, default="")
    media_url = db.Column(db.String(300), default="")
    media_type = db.Column(db.String(20), default="text")
    thumbnail = db.Column(db.String(300), default="")
    aspect_ratio = db.Column(db.Float, default=1.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    views = db.Column(db.Integer, default=0)
    is_pinned = db.Column(db.Boolean, default=False)
    is_edited = db.Column(db.Boolean, default=False)

    liked_by = db.relationship("User", secondary=post_likes, backref="liked_posts", lazy="dynamic")
    saved_by = db.relationship("User", secondary=post_saves, backref="saved_posts", lazy="dynamic")
    comments = db.relationship("Comment", backref="post", lazy="dynamic", cascade="all,delete-orphan")

    @property
    def like_count(self):
        return self.liked_by.count()

    @property
    def comment_count(self):
        return self.comments.count()

    @property
    def save_count(self):
        return self.saved_by.count()

    def is_liked_by(self, user) -> bool:
        return self.liked_by.filter(post_likes.c.user_id == user.id).count() > 0

    def is_saved_by(self, user) -> bool:
        return self.saved_by.filter(post_saves.c.user_id == user.id).count() > 0


class Comment(db.Model):
    __tablename__ = "comment"

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("comment.id"), nullable=True)
    content = db.Column(db.Text, nullable=False)
    likes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_edited = db.Column(db.Boolean, default=False)

    replies = db.relationship("Comment", backref=db.backref("parent", remote_side=[id]), lazy="dynamic")

    @property
    def reply_count(self):
        return self.replies.count()


class Message(db.Model):
    __tablename__ = "message"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    content = db.Column(db.Text, default="")
    media_url = db.Column(db.String(300), default="")
    media_type = db.Column(db.String(20), default="text")
    is_read = db.Column(db.Boolean, default=False)
    is_delivered = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)
    is_deleted_for_sender = db.Column(db.Boolean, default=False)
    is_deleted_for_receiver = db.Column(db.Boolean, default=False)
    reply_to_id = db.Column(db.Integer, db.ForeignKey("message.id"), nullable=True)
    forwarded_from_id = db.Column(db.Integer, db.ForeignKey("message.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    edited_at = db.Column(db.DateTime, nullable=True)

    replies = db.relationship("Message", backref=db.backref("reply_to", remote_side=[id]))
    reactions = db.relationship("MessageReaction", backref="message", lazy="dynamic", cascade="all,delete-orphan")
    location = db.relationship("SharedLocation", backref="message", uselist=False, cascade="all,delete-orphan")


class MessageReaction(db.Model):
    __tablename__ = "message_reaction"

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("message.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reaction = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('message_id', 'user_id', name='unique_user_message_reaction'),)


class SharedLocation(db.Model):
    __tablename__ = "shared_location"

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("message.id"), nullable=False, unique=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    address = db.Column(db.String(500))
    place_name = db.Column(db.String(200))
    zoom = db.Column(db.Integer, default=15)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class StickerPack(db.Model):
    __tablename__ = "sticker_pack"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    icon = db.Column(db.String(300), default="/static/stickers/default_pack.png")
    cover = db.Column(db.String(300), default="")
    description = db.Column(db.String(500), default="")
    author = db.Column(db.String(100), default="Kildear")
    is_premium = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    price = db.Column(db.Integer, default=0)
    order = db.Column(db.Integer, default=0)
    sticker_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    stickers = db.relationship("Sticker", backref="pack", lazy="dynamic", cascade="all,delete-orphan")


class Sticker(db.Model):
    __tablename__ = "sticker"

    id = db.Column(db.Integer, primary_key=True)
    pack_id = db.Column(db.Integer, db.ForeignKey("sticker_pack.id"), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)
    image_url = db.Column(db.String(300), nullable=False)
    image_webp = db.Column(db.String(300))
    width = db.Column(db.Integer, default=512)
    height = db.Column(db.Integer, default=512)
    order = db.Column(db.Integer, default=0)
    is_animated = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class UserSticker(db.Model):
    __tablename__ = "user_sticker"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    sticker_id = db.Column(db.Integer, db.ForeignKey("sticker.id"), nullable=False)
    purchased_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")
    sticker = db.relationship("Sticker")


class Group(db.Model):
    __tablename__ = "group"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, default="")
    avatar = db.Column(db.String(300), default="/static/default_group.png")
    cover = db.Column(db.String(300), default="")
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    is_private = db.Column(db.Boolean, default=False)
    member_count = db.Column(db.Integer, default=0)
    post_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    members = db.relationship("User", secondary=group_members, backref="groups", lazy="dynamic")
    posts = db.relationship("GroupPost", backref="group", lazy="dynamic", cascade="all,delete")

    def update_counts(self):
        self.member_count = self.members.count()
        self.post_count = self.posts.count()
        db.session.commit()


class GroupPost(db.Model):
    __tablename__ = "group_post"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    content = db.Column(db.Text, default="")
    media_url = db.Column(db.String(300), default="")
    media_type = db.Column(db.String(20), default="text")
    likes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = db.relationship("User")


class Channel(db.Model):
    __tablename__ = "channel"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, default="")
    avatar = db.Column(db.String(300), default="/static/default_channel.png")
    cover = db.Column(db.String(300), default="")
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    is_nsfw = db.Column(db.Boolean, default=False)
    sub_count = db.Column(db.Integer, default=0)
    post_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subscribers = db.relationship("User", secondary=channel_subs, backref="subscribed_channels", lazy="dynamic")
    posts = db.relationship("ChannelPost", backref="channel", lazy="dynamic", cascade="all,delete")

    def update_counts(self):
        self.sub_count = self.subscribers.count()
        self.post_count = self.posts.count()
        db.session.commit()


class ChannelPost(db.Model):
    __tablename__ = "channel_post"

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey("channel.id"), nullable=False)
    content = db.Column(db.Text, default="")
    media_url = db.Column(db.String(300), default="")
    media_type = db.Column(db.String(20), default="text")
    views = db.Column(db.Integer, default=0)
    likes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = "notification"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    from_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    type = db.Column(db.String(30), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey("post.id"), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey("comment.id"), nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=True)
    channel_id = db.Column(db.Integer, db.ForeignKey("channel.id"), nullable=True)
    call_id = db.Column(db.Integer, db.ForeignKey("call.id"), nullable=True)
    message_id = db.Column(db.Integer, db.ForeignKey("message.id"), nullable=True)
    text = db.Column(db.String(300), default="")
    image = db.Column(db.String(300), default="")
    is_read = db.Column(db.Boolean, default=False)
    is_seen = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    from_user = db.relationship("User", foreign_keys=[from_user_id])
    post = db.relationship("Post", foreign_keys=[post_id])
    comment = db.relationship("Comment", foreign_keys=[comment_id])
    group = db.relationship("Group", foreign_keys=[group_id])
    channel = db.relationship("Channel", foreign_keys=[channel_id])
    call = db.relationship("Call", foreign_keys=[call_id])
    message = db.relationship("Message", foreign_keys=[message_id])


class Hashtag(db.Model):
    __tablename__ = "hashtag"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    post_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


post_hashtags = db.Table(
    "post_hashtags",
    db.Column("post_id", db.Integer, db.ForeignKey("post.id"), primary_key=True),
    db.Column("hashtag_id", db.Integer, db.ForeignKey("hashtag.id"), primary_key=True)
)


class Story(db.Model):
    __tablename__ = "story"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    media_url = db.Column(db.String(300), nullable=False)
    media_type = db.Column(db.String(20), default="image")
    text = db.Column(db.String(200), default="")
    background_color = db.Column(db.String(7), default="#6c63ff")
    views = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(hours=24))

    user = db.relationship("User", backref="stories")

    @property
    def is_expired(self):
        return datetime.utcnow() > self.expires_at


story_views = db.Table(
    "story_views",
    db.Column("story_id", db.Integer, db.ForeignKey("story.id"), primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("viewed_at", db.DateTime, default=datetime.utcnow)
)


# ──────────────────────────────────────────────────────────────────────────────
#  Helper Functions
# ──────────────────────────────────────────────────────────────────────────────

def notification_link(notif):
    if notif.type in ['like', 'comment', 'mention']:
        if notif.post_id:
            return url_for('view_post', post_id=notif.post_id)
    elif notif.type == 'follow':
        if notif.from_user:
            return url_for('profile', username=notif.from_user.username)
    elif notif.type in ['missed_call', 'incoming_call', 'voice_message', 'message']:
        if notif.from_user:
            return url_for('chat', username=notif.from_user.username)
    elif notif.type in ['group_post', 'group_mention']:
        if notif.group_id:
            return url_for('group_detail', slug=notif.group.slug)
    elif notif.type == 'channel_post':
        if notif.channel_id:
            return url_for('channel_detail', slug=notif.channel.slug)
    return '#'


def notification_icon(notif):
    icons = {
        'like': '❤️',
        'comment': '💬',
        'follow': '👤',
        'mention': '@',
        'group_post': '👥',
        'group_mention': '@',
        'channel_post': '📢',
        'missed_call': '📞',
        'incoming_call': '📞',
        'voice_message': '🎤',
        'message': '💬',
        'story_reply': '📸',
        'story_mention': '@'
    }
    return icons.get(notif.type, '🔔')


def notification_text(notif):
    if notif.text:
        return notif.text
    texts = {
        'like': f"{notif.from_user.username} liked your post",
        'comment': f"{notif.from_user.username} commented on your post",
        'follow': f"{notif.from_user.username} started following you",
        'mention': f"{notif.from_user.username} mentioned you in a post",
        'group_post': f"New post in {notif.group.name}",
        'channel_post': f"New post in {notif.channel.name}",
        'message': f"New message from {notif.from_user.username}",
        'voice_message': f"Voice message from {notif.from_user.username}",
        'missed_call': f"Missed call from {notif.from_user.username}"
    }
    return texts.get(notif.type, "New notification")


def ensure_upload_folders():
    """Create all necessary upload directories"""
    for folder in UPLOAD_SUBFOLDERS:
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], folder)
        try:
            os.makedirs(folder_path, exist_ok=True)
            logger.info(f"✅ Folder ready: {folder_path}")
        except Exception as e:
            logger.error(f"Failed to create folder {folder_path}: {e}")

    # Preset folders
    preset_avatar_folder = os.path.join('static', 'avatars', 'preset')
    preset_cover_folder = os.path.join('static', 'covers', 'preset')
    sticker_folder = os.path.join('static', 'stickers')

    for folder in [preset_avatar_folder, preset_cover_folder, sticker_folder]:
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create {folder}: {e}")

    logger.info("✅ All upload folders ready")


def save_file(file, subfolder: str, resize=None):
    """Save uploaded file with optional image resizing"""
    if not file or not file.filename:
        return None

    try:
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        filename = f"{uuid.uuid4().hex}.{ext}"
        upload_path = os.path.join(app.config['UPLOAD_FOLDER'], subfolder)
        os.makedirs(upload_path, exist_ok=True)
        file_path = os.path.join(upload_path, filename)

        # Save file
        file.save(file_path)

        # Resize image if requested
        if resize and ext in ALLOWED_IMAGE:
            try:
                img = Image.open(file_path)
                if resize == 'thumbnail':
                    img.thumbnail((300, 300))
                elif isinstance(resize, tuple):
                    img.thumbnail(resize)
                img.save(file_path, optimize=True, quality=85)
            except Exception as e:
                logger.warning(f"Could not resize image: {e}")

        if is_render:
            return f"/uploads/{subfolder}/{filename}"
        else:
            return f"/static/uploads/{subfolder}/{filename}"
    except Exception as e:
        logger.error(f"Error saving file: {e}")
        return None


def save_base64_image(base64_data, subfolder: str):
    """Save base64 encoded image"""
    try:
        if ',' in base64_data:
            base64_data = base64_data.split(',')[1]

        image_data = base64.b64decode(base64_data)
        filename = f"{uuid.uuid4().hex}.png"
        upload_path = os.path.join(app.config['UPLOAD_FOLDER'], subfolder)
        os.makedirs(upload_path, exist_ok=True)
        file_path = os.path.join(upload_path, filename)

        with open(file_path, 'wb') as f:
            f.write(image_data)

        if is_render:
            return f"/uploads/{subfolder}/{filename}"
        else:
            return f"/static/uploads/{subfolder}/{filename}"
    except Exception as e:
        logger.error(f"Error saving base64 image: {e}")
        return None


def extract_hashtags(content):
    """Extract hashtags from post content"""
    if not content:
        return []
    hashtags = re.findall(r'#(\w+)', content)
    return [h.lower() for h in hashtags]


def update_hashtags(post_id, hashtags):
    """Update hashtags for a post"""
    for tag_name in set(hashtags):
        hashtag = Hashtag.query.filter_by(name=tag_name).first()
        if not hashtag:
            hashtag = Hashtag(name=tag_name)
            db.session.add(hashtag)
        hashtag.post_count += 1
        db.session.execute(post_hashtags.insert().values(post_id=post_id, hashtag_id=hashtag.id))
    db.session.commit()


@app.route('/uploads/<path:subfolder>/<path:filename>')
def serve_upload(subfolder, filename):
    if subfolder not in UPLOAD_SUBFOLDERS:
        abort(404)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], subfolder, filename)
    if not os.path.exists(file_path):
        abort(404)
    return send_from_directory(
        os.path.join(app.config['UPLOAD_FOLDER'], subfolder),
        filename
    )


# ──────────────────────────────────────────────────────────────────────────────
#  DDoS Protection
# ──────────────────────────────────────────────────────────────────────────────
_req_log: dict = defaultdict(list)
_blocked_ips: set = set()
_fail_log: dict = defaultdict(list)


def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    return request.remote_addr or '0.0.0.0'


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
        app.logger.warning(f"[DDoS] Blocked IP: {ip}")
        abort(429)

    if request.content_length and request.content_length > app.config["MAX_CONTENT_LENGTH"]:
        abort(413)


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"

    csp = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.socket.io https://cdnjs.cloudflare.com https://unpkg.com https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://unpkg.com",
        "font-src 'self' https://cdnjs.cloudflare.com data:",
        "img-src 'self' data: blob: https://*.openstreetmap.org",
        "media-src 'self' blob: data:",
        "connect-src 'self' wss: ws: https://nominatim.openstreetmap.org",
        "frame-src 'self' https://www.openstreetmap.org",
        "frame-ancestors 'none'"
    ]
    response.headers["Content-Security-Policy"] = '; '.join(csp)
    return response


def track_failure(ip: str):
    now = time.time()
    fails = [t for t in _fail_log[ip] if now - t < 300]
    fails.append(now)
    _fail_log[ip] = fails
    if len(fails) >= 20:
        _blocked_ips.add(ip)


# ──────────────────────────────────────────────────────────────────────────────
#  Auth loader
# ──────────────────────────────────────────────────────────────────────────────
@login_mgr.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@login_mgr.unauthorized_handler
def unauthorized():
    flash("Please log in to access this page.", "warning")
    return redirect(url_for('login', next=request.url))


# ──────────────────────────────────────────────────────────────────────────────
#  Context Processors
# ──────────────────────────────────────────────────────────────────────────────
@app.context_processor
def inject_globals():
    unread = 0
    notif_count = 0
    unread_voice = 0
    stats = {}

    if current_user.is_authenticated:
        unread = Message.query.filter(
            Message.receiver_id == current_user.id,
            Message.is_read == False,
            Message.is_deleted == False,
            Message.is_deleted_for_receiver == False
        ).count()

        notif_count = Notification.query.filter_by(
            user_id=current_user.id, is_read=False
        ).count()

        unread_voice = VoiceMessage.query.filter_by(
            receiver_id=current_user.id, is_read=False
        ).count()

        if current_user.is_admin:
            stats['total_reports'] = Report.query.filter_by(status='pending').count()
            stats['pending_verification'] = User.query.filter_by(is_verified=False, is_banned=False).count()
            stats['banned_users'] = User.query.filter_by(is_banned=True).count()
            stats['total_users'] = User.query.count()
            stats['total_posts'] = Post.query.count()

    return dict(
        unread_messages=unread,
        notif_count=notif_count,
        unread_voice=unread_voice,
        stats=stats,
        csrf_token=generate_csrf,
        notification_link=notification_link,
        notification_icon=notification_icon,
        notification_text=notification_text,
        now=datetime.utcnow(),
        is_production=is_production,
        preset_avatars=PRESET_AVATARS,
        preset_covers=PRESET_COVERS
    )


# ──────────────────────────────────────────────────────────────────────────────
#  API Routes for Notifications
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/api/unread_counts")
@login_required
def unread_counts():
    notif_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    msg_count = Message.query.filter(
        Message.receiver_id == current_user.id,
        Message.is_read == False,
        Message.is_deleted == False,
        Message.is_deleted_for_receiver == False
    ).count()
    voice_count = VoiceMessage.query.filter_by(receiver_id=current_user.id, is_read=False).count()
    return jsonify({
        "notifications": notif_count,
        "messages": msg_count,
        "voice_messages": voice_count
    })


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


@app.route("/api/mark_all_messages_read/<int:user_id>", methods=["POST"])
@login_required
def mark_all_messages_read(user_id):
    Message.query.filter_by(
        sender_id=user_id,
        receiver_id=current_user.id,
        is_read=False
    ).update({"is_read": True})
    VoiceMessage.query.filter_by(
        sender_id=user_id,
        receiver_id=current_user.id,
        is_read=False
    ).update({"is_read": True})
    db.session.commit()
    return jsonify({"success": True})


# ──────────────────────────────────────────────────────────────────────────────
#  Admin Routes
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    stats = {
        "total_users": User.query.count(),
        "total_posts": Post.query.count(),
        "total_comments": Comment.query.count(),
        "total_reports": Report.query.filter_by(status='pending').count(),
        "total_groups": Group.query.count(),
        "total_channels": Channel.query.count(),
        "new_users_today": User.query.filter(
            User.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)).count(),
        "new_posts_today": Post.query.filter(
            Post.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)).count(),
        "banned_users": User.query.filter_by(is_banned=True).count(),
        "verified_users": User.query.filter_by(is_verified=True).count(),
        "online_users": User.query.filter_by(is_online=True).count(),
    }

    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
    recent_posts = Post.query.order_by(Post.created_at.desc()).limit(10).all()
    pending_reports = Report.query.filter_by(status='pending').order_by(Report.created_at.desc()).limit(20).all()
    recent_logins = LoginHistory.query.order_by(LoginHistory.created_at.desc()).limit(20).all()

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        recent_users=recent_users,
        recent_posts=recent_posts,
        pending_reports=pending_reports,
        recent_logins=recent_logins
    )


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "")
    filter_by = request.args.get("filter", "all")

    query = User.query
    if search:
        query = query.filter(
            or_(
                User.username.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                User.display_name.ilike(f"%{search}%")
            )
        )

    if filter_by == "banned":
        query = query.filter_by(is_banned=True)
    elif filter_by == "verified":
        query = query.filter_by(is_verified=True)
    elif filter_by == "admin":
        query = query.filter_by(is_admin=True)
    elif filter_by == "unverified":
        query = query.filter_by(is_verified=False, is_banned=False)

    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template("admin/users.html", users=users, search=search, filter_by=filter_by)


@app.route("/admin/user/<int:user_id>")
@login_required
@admin_required
def admin_user_detail(user_id):
    user = User.query.get_or_404(user_id)
    posts = user.posts.order_by(Post.created_at.desc()).limit(20).all()
    login_history = user.login_history.order_by(LoginHistory.created_at.desc()).limit(20).all()
    reports_against = Report.query.filter_by(reported_user_id=user_id).order_by(Report.created_at.desc()).all()
    reports_by = Report.query.filter_by(reporter_id=user_id).order_by(Report.created_at.desc()).all()

    return render_template(
        "admin/user_detail.html",
        user=user,
        posts=posts,
        login_history=login_history,
        reports_against=reports_against,
        reports_by=reports_by
    )


@app.route("/admin/user/<int:user_id>/toggle-ban", methods=["POST"])
@login_required
@admin_required
def admin_toggle_ban(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Cannot ban yourself", "error")
        return redirect(url_for("admin_users"))

    user.is_banned = not user.is_banned
    if user.is_banned:
        user.is_online = False
        # Send notification
        room = f"user_{user.id}"
        socketio.emit("account_banned", {"message": "Your account has been banned"}, room=room)

    db.session.commit()
    status = "banned" if user.is_banned else "unbanned"
    flash(f"User {user.username} {status}", "success")
    return redirect(request.referrer or url_for("admin_users"))


@app.route("/admin/user/<int:user_id>/toggle-admin", methods=["POST"])
@login_required
@admin_required
def admin_toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Cannot change your own admin status", "error")
        return redirect(url_for("admin_users"))

    user.is_admin = not user.is_admin
    db.session.commit()
    status = "granted admin rights" if user.is_admin else "removed admin rights"
    flash(f"User {user.username} {status}", "success")
    return redirect(request.referrer or url_for("admin_users"))


@app.route("/admin/user/<int:user_id>/toggle-verify", methods=["POST"])
@login_required
@admin_required
def admin_toggle_verify(user_id):
    user = User.query.get_or_404(user_id)
    user.is_verified = not user.is_verified
    db.session.commit()
    status = "verified" if user.is_verified else "unverified"
    flash(f"User {user.username} {status}", "success")
    return redirect(request.referrer or url_for("admin_users"))


@app.route("/admin/user/<int:user_id>/toggle-moderator", methods=["POST"])
@login_required
@admin_required
def admin_toggle_moderator(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Cannot change your own moderator status", "error")
        return redirect(url_for("admin_users"))

    user.is_moderator = not user.is_moderator
    db.session.commit()
    status = "granted moderator rights" if user.is_moderator else "removed moderator rights"
    flash(f"User {user.username} {status}", "success")
    return redirect(request.referrer or url_for("admin_users"))


@app.route("/admin/user/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Cannot delete yourself", "error")
        return redirect(url_for("admin_users"))

    username = user.username
    db.session.delete(user)
    db.session.commit()
    flash(f"User {username} has been permanently deleted", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/posts")
@login_required
@admin_required
def admin_posts():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "")

    query = Post.query
    if search:
        query = query.filter(Post.content.ilike(f"%{search}%"))

    posts = query.order_by(Post.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template("admin/posts.html", posts=posts, search=search)


@app.route("/admin/post/<int:post_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash("Post deleted", "success")
    return redirect(request.referrer or url_for("admin_posts"))


@app.route("/admin/reports")
@login_required
@admin_required
def admin_reports():
    status = request.args.get("status", "pending")
    type_filter = request.args.get("type", "all")

    query = Report.query
    if status != "all":
        query = query.filter_by(status=status)
    if type_filter == "user":
        query = query.filter(Report.reported_user_id.isnot(None))
    elif type_filter == "post":
        query = query.filter(Report.post_id.isnot(None))
    elif type_filter == "comment":
        query = query.filter(Report.comment_id.isnot(None))

    reports = query.order_by(Report.created_at.desc()).all()
    return render_template("admin/reports.html", reports=reports, current_status=status, current_type=type_filter)


@app.route("/admin/report/<int:report_id>/review", methods=["POST"])
@login_required
@admin_required
def admin_review_report(report_id):
    report = Report.query.get_or_404(report_id)
    action = request.form.get("action")
    note = request.form.get("note", "")

    if action == "dismiss":
        report.status = "dismissed"
        flash("Report dismissed", "success")
    elif action == "approve":
        report.status = "reviewed"
        if report.reported_user_id:
            user = User.query.get(report.reported_user_id)
            if user:
                user.is_banned = True
                flash(f"User {user.username} has been banned", "success")
        if report.post_id:
            post = Post.query.get(report.post_id)
            if post:
                db.session.delete(post)
                flash("Post deleted", "success")
        if report.comment_id:
            comment = Comment.query.get(report.comment_id)
            if comment:
                db.session.delete(comment)
                flash("Comment deleted", "success")
    elif action == "warn":
        report.status = "warned"
        flash("Warning issued", "success")

    report.reviewed_at = datetime.utcnow()
    report.reviewed_by = current_user.id

    db.session.commit()
    return redirect(url_for("admin_reports"))


@app.route("/admin/groups")
@login_required
@admin_required
def admin_groups():
    groups = Group.query.order_by(Group.created_at.desc()).all()
    return render_template("admin/groups.html", groups=groups)


@app.route("/admin/group/<int:group_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_group(group_id):
    group = Group.query.get_or_404(group_id)
    db.session.delete(group)
    db.session.commit()
    flash(f"Group '{group.name}' deleted", "success")
    return redirect(url_for("admin_groups"))


@app.route("/admin/channels")
@login_required
@admin_required
def admin_channels():
    channels = Channel.query.order_by(Channel.created_at.desc()).all()
    return render_template("admin/channels.html", channels=channels)


@app.route("/admin/logs")
@login_required
@admin_required
def admin_logs():
    page = request.args.get("page", 1, type=int)
    logs = LoginHistory.query.order_by(LoginHistory.created_at.desc()).paginate(page=page, per_page=50)
    return render_template("admin/logs.html", logs=logs)


@app.route("/admin/statistics")
@login_required
@admin_required
def admin_statistics():
    # Get statistics for charts
    last_7_days = []
    for i in range(6, -1, -1):
        date = datetime.utcnow().date() - timedelta(days=i)
        date_start = datetime.combine(date, datetime.min.time())
        date_end = datetime.combine(date, datetime.max.time())

        new_users = User.query.filter(User.created_at.between(date_start, date_end)).count()
        new_posts = Post.query.filter(Post.created_at.between(date_start, date_end)).count()

        last_7_days.append({
            "date": date.strftime("%Y-%m-%d"),
            "users": new_users,
            "posts": new_posts
        })

    # Top users by posts
    top_users = db.session.query(
        User.id, User.username, User.display_name, User.avatar_url,
        func.count(Post.id).label('post_count')
    ).outerjoin(Post).group_by(User.id).order_by(func.count(Post.id).desc()).limit(10).all()

    # Top hashtags
    top_hashtags = Hashtag.query.order_by(Hashtag.post_count.desc()).limit(10).all()

    return render_template(
        "admin/statistics.html",
        stats=last_7_days,
        top_users=top_users,
        top_hashtags=top_hashtags
    )


# ──────────────────────────────────────────────────────────────────────────────
#  Settings Routes (FULL VERSION)
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
                current_user.display_name = data['display_name'][:60]
            if 'bio' in data:
                current_user.bio = data['bio'][:500]
            if 'location' in data:
                current_user.location = data['location'][:100]
            if 'website' in data:
                current_user.website = data['website'][:200]
            if 'email' in data:
                if re.match(r"^[^@]+@[^@]+\.[^@]+$", data['email']):
                    if data['email'] != current_user.email:
                        current_user.email = data['email'].lower()
                        current_user.email_verified = False
            if 'accent_color' in data and data['accent_color']:
                current_user.accent_color = data['accent_color'][:7]
            if 'is_private' in data:
                current_user.is_private = bool(data['is_private'])

            # Avatar
            if 'preset_avatar' in data:
                avatar_num = int(data['preset_avatar'])
                if 1 <= avatar_num <= 10:
                    current_user.set_preset_avatar(avatar_num)

            # Cover
            if 'preset_cover' in data:
                cover_num = data['preset_cover']
                if cover_num and cover_num != '':
                    current_user.set_preset_cover(int(cover_num))
                else:
                    current_user.set_preset_cover(None)

            # Theme
            if 'theme' in data:
                settings.theme = data['theme']

            # Language
            if 'language' in data:
                settings.language = data['language']
                session['language'] = settings.language

            # Change password
            if 'current_password' in data and data['current_password']:
                if current_user.check_password(data['current_password']):
                    if 'new_password' in data and len(data['new_password']) >= 8:
                        if data['new_password'] == data.get('confirm_password'):
                            current_user.set_password(data['new_password'])
                            flash("Password changed successfully!", "success")
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


@app.route("/settings/avatar", methods=["POST"])
@login_required
def settings_avatar():
    try:
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[1].lower()
                if ext in ALLOWED_IMAGE:
                    filename = save_file(file, "avatars", resize=(200, 200))
                    if filename:
                        current_user.set_custom_avatar(os.path.basename(filename))
                        db.session.commit()
                        flash("Avatar updated!", "success")
                else:
                    flash("Invalid image format", "error")
        return redirect(url_for("settings_account"))
    except Exception as e:
        flash(f"Error: {e}", "error")
        return redirect(url_for("settings_account"))


@app.route("/settings/cover", methods=["POST"])
@login_required
def settings_cover():
    try:
        if 'cover' in request.files:
            file = request.files['cover']
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[1].lower()
                if ext in ALLOWED_IMAGE:
                    filename = save_file(file, "covers", resize=(1200, 400))
                    if filename:
                        current_user.set_custom_cover(os.path.basename(filename))
                        db.session.commit()
                        flash("Cover updated!", "success")
                else:
                    flash("Invalid image format", "error")
        return redirect(url_for("settings_account"))
    except Exception as e:
        flash(f"Error: {e}", "error")
        return redirect(url_for("settings_account"))


@app.route("/settings/notifications", methods=["GET", "POST"])
@login_required
def settings_notifications():
    settings = current_user.get_settings()

    if request.method == "POST":
        try:
            data = request.get_json()

            for key in ['notify_likes', 'notify_comments', 'notify_follows',
                        'notify_messages', 'notify_voice_messages', 'notify_calls',
                        'notify_group_posts', 'notify_channel_posts', 'notify_mentions',
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
            return jsonify({"success": False, "error": str(e)}), 500

    return render_template("settings/privacy.html", settings=settings)


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
            return jsonify({"success": False, "error": str(e)}), 500

    return render_template("settings/chats.html", settings=settings)


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
            return jsonify({"success": False, "error": str(e)}), 500

    return render_template("settings/advanced.html", settings=settings)


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


@app.route("/settings/muted")
@login_required
def settings_muted():
    muted_users = current_user.muted_users.all()
    return render_template("settings/muted.html", muted_users=muted_users)


@app.route("/settings/unmute/<int:user_id>", methods=["POST"])
@login_required
def settings_unmute(user_id):
    user = User.query.get_or_404(user_id)
    if current_user.unmute(user):
        db.session.commit()
        flash(f"Unmuted @{user.username}", "success")
    return redirect(url_for("settings_muted"))


@app.route("/settings/sessions")
@login_required
def settings_sessions():
    sessions = LoginHistory.query.filter_by(user_id=current_user.id).order_by(LoginHistory.created_at.desc()).limit(
        20).all()
    return render_template("settings/sessions.html", sessions=sessions)


@app.route("/settings/delete_account", methods=["POST"])
@login_required
def settings_delete_account():
    password = request.form.get("password")
    if not current_user.check_password(password):
        flash("Incorrect password", "error")
        return redirect(url_for("settings_advanced"))

    user_id = current_user.id
    logout_user()

    user = User.query.get(user_id)
    db.session.delete(user)
    db.session.commit()

    flash("Your account has been permanently deleted", "info")
    return redirect(url_for("register"))


@app.route("/settings/export_data")
@login_required
def settings_export_data():
    try:
        user_data = {
            "user": {
                "username": current_user.username,
                "email": current_user.email,
                "display_name": current_user.display_name,
                "bio": current_user.bio,
                "location": current_user.location,
                "website": current_user.website,
                "created_at": current_user.created_at.isoformat(),
                "is_verified": current_user.is_verified
            },
            "stats": {
                "followers": current_user.follower_count,
                "following": current_user.following_count,
                "posts": current_user.post_count
            },
            "posts": [
                {
                    "content": post.content,
                    "created_at": post.created_at.isoformat(),
                    "likes": post.like_count,
                    "comments": post.comment_count
                }
                for post in current_user.posts.limit(100).all()
            ],
            "exported_at": datetime.utcnow().isoformat()
        }

        response = make_response(json.dumps(user_data, indent=2))
        response.headers['Content-Type'] = 'application/json'
        response.headers['Content-Disposition'] = f'attachment; filename=kildear_data_{current_user.username}.json'
        return response

    except Exception as e:
        flash(f"Error exporting data: {e}", "error")
        return redirect(url_for("settings_advanced"))


# ──────────────────────────────────────────────────────────────────────────────
#  Sticker Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/stickers")
@login_required
def get_stickers():
    packs = StickerPack.query.filter_by(is_active=True).order_by(StickerPack.order).all()
    result = []
    for pack in packs:
        stickers = pack.stickers.order_by(Sticker.order).all()
        result.append({
            "id": pack.id,
            "name": pack.name,
            "slug": pack.slug,
            "icon": pack.icon,
            "is_premium": pack.is_premium,
            "price": pack.price,
            "stickers": [{
                "id": s.id,
                "emoji": s.emoji,
                "image_url": s.image_url,
                "width": s.width,
                "height": s.height,
                "is_animated": s.is_animated
            } for s in stickers]
        })
    return jsonify({"packs": result})


@app.route("/sticker/send", methods=["POST"])
@login_required
@limiter.limit("120 per minute")
def send_sticker():
    try:
        data = request.get_json()
        receiver_id = data.get("receiver_id")
        sticker_id = data.get("sticker_id")

        receiver = User.query.get_or_404(receiver_id)
        sticker = Sticker.query.get_or_404(sticker_id)

        if current_user.is_blocked(receiver):
            return jsonify({"error": "Cannot send to blocked user"}), 403

        msg = Message(
            sender_id=current_user.id,
            receiver_id=receiver.id,
            content=f"[Sticker: {sticker.emoji}]",
            media_url=sticker.image_url,
            media_type="sticker"
        )
        db.session.add(msg)
        db.session.commit()

        message_data = {
            "id": msg.id,
            "sender_id": current_user.id,
            "sender_username": current_user.username,
            "sender_avatar": current_user.avatar_url,
            "content": msg.content,
            "media_url": msg.media_url,
            "media_type": "sticker",
            "sticker": {
                "id": sticker.id,
                "emoji": sticker.emoji,
                "image_url": sticker.image_url
            },
            "created_at": msg.created_at.strftime("%H:%M")
        }

        room = "_".join(sorted([str(current_user.id), str(receiver.id)]))
        socketio.emit("new_message", message_data, room=room)

        # Send notification
        if receiver.id != current_user.id:
            notif = Notification(
                user_id=receiver.id,
                from_user_id=current_user.id,
                type="message",
                message_id=msg.id,
                text=f"{current_user.username} sent you a sticker"
            )
            db.session.add(notif)
            db.session.commit()
            send_notification(receiver.id, {
                "type": "message",
                "from_user": {"id": current_user.id, "username": current_user.username,
                              "avatar": current_user.avatar_url},
                "text": f"Sent you a sticker"
            })

        return jsonify({"success": True, "id": msg.id})

    except Exception as e:
        logger.error(f"Error sending sticker: {e}")
        return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────────────────────────────────────────
#  Location Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/location/send", methods=["POST"])
@login_required
@limiter.limit("60 per hour")
def send_location():
    try:
        data = request.get_json()
        receiver_id = data.get("receiver_id")
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        address = data.get("address", "")
        place_name = data.get("place_name", "")

        receiver = User.query.get_or_404(receiver_id)

        if current_user.is_blocked(receiver):
            return jsonify({"error": "Cannot send to blocked user"}), 403

        msg = Message(
            sender_id=current_user.id,
            receiver_id=receiver.id,
            content=f"📍 {place_name or 'Location'}",
            media_type="location"
        )
        db.session.add(msg)
        db.session.flush()

        location = SharedLocation(
            message_id=msg.id,
            latitude=latitude,
            longitude=longitude,
            address=address,
            place_name=place_name
        )
        db.session.add(location)
        db.session.commit()

        message_data = {
            "id": msg.id,
            "sender_id": current_user.id,
            "sender_username": current_user.username,
            "sender_avatar": current_user.avatar_url,
            "content": msg.content,
            "media_type": "location",
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "address": address,
                "place_name": place_name
            },
            "created_at": msg.created_at.strftime("%H:%M")
        }

        room = "_".join(sorted([str(current_user.id), str(receiver.id)]))
        socketio.emit("new_message", message_data, room=room)

        return jsonify({"success": True, "id": msg.id})

    except Exception as e:
        logger.error(f"Error sending location: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/location/reverse", methods=["POST"])
@login_required
def reverse_geocode():
    """Reverse geocode coordinates to address"""
    try:
        data = request.get_json()
        lat = data.get("lat")
        lng = data.get("lng")

        # Use OpenStreetMap Nominatim (free, no API key needed)
        import requests
        response = requests.get(
            f"https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lng, "format": "json", "addressdetails": 1},
            headers={"User-Agent": "Kildear Social Network"}
        )

        if response.status_code == 200:
            data = response.json()
            address = data.get("display_name", "")
            place_name = data.get("name", "") or data.get("address", {}).get("city", "") or data.get("address", {}).get(
                "town", "") or "Location"
            return jsonify({"success": True, "address": address, "place_name": place_name})

        return jsonify({"success": False, "error": "Geocoding failed"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ──────────────────────────────────────────────────────────────────────────────
#  Reaction Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/message/<int:message_id>/react", methods=["POST"])
@login_required
def add_reaction(message_id):
    try:
        data = request.get_json()
        reaction = data.get("reaction")

        msg = Message.query.get_or_404(message_id)

        # Check if user can react to this message
        if msg.sender_id != current_user.id and msg.receiver_id != current_user.id:
            return jsonify({"error": "Cannot react to this message"}), 403

        # Check if reaction already exists
        existing = MessageReaction.query.filter_by(
            message_id=message_id,
            user_id=current_user.id
        ).first()

        if existing:
            if existing.reaction == reaction:
                # Remove reaction if same
                db.session.delete(existing)
                added = False
            else:
                # Update reaction
                existing.reaction = reaction
                added = True
        else:
            # Add new reaction
            new_reaction = MessageReaction(
                message_id=message_id,
                user_id=current_user.id,
                reaction=reaction
            )
            db.session.add(new_reaction)
            added = True

        db.session.commit()

        # Get all reactions for this message
        reactions = {}
        all_reactions = MessageReaction.query.filter_by(message_id=message_id).all()
        for r in all_reactions:
            if r.reaction not in reactions:
                reactions[r.reaction] = []
            user = User.query.get(r.user_id)
            reactions[r.reaction].append({
                "user_id": r.user_id,
                "username": user.username,
                "avatar": user.avatar_url
            })

        # Notify via socket
        room = "_".join(sorted([str(msg.sender_id), str(msg.receiver_id)]))
        socketio.emit("message_reaction", {
            "message_id": message_id,
            "reactions": reactions,
            "user_reaction": reaction if added else None,
            "user_id": current_user.id
        }, room=room)

        return jsonify({
            "success": True,
            "added": added,
            "reaction": reaction,
            "reactions": reactions
        })

    except Exception as e:
        logger.error(f"Error adding reaction: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/message/<int:message_id>/reactions")
@login_required
def get_reactions(message_id):
    """Get all reactions for a message"""
    msg = Message.query.get_or_404(message_id)

    if msg.sender_id != current_user.id and msg.receiver_id != current_user.id:
        abort(403)

    reactions = {}
    all_reactions = MessageReaction.query.filter_by(message_id=message_id).all()

    for r in all_reactions:
        if r.reaction not in reactions:
            reactions[r.reaction] = []
        user = User.query.get(r.user_id)
        reactions[r.reaction].append({
            "user_id": r.user_id,
            "username": user.username,
            "avatar": user.avatar_url
        })

    return jsonify({"reactions": reactions})


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

        ext = audio_file.filename.rsplit('.', 1)[1].lower()
        if ext not in ALLOWED_AUDIO:
            return jsonify({"error": "Audio format not supported"}), 400

        audio_file.seek(0)
        audio_data = audio_file.read()
        base64_data = base64.b64encode(audio_data).decode('utf-8')

        duration = request.form.get("duration", 0, type=int)

        voice_msg = VoiceMessage(
            sender_id=current_user.id,
            receiver_id=receiver.id,
            audio_data=base64_data,
            audio_mime=f"audio/{ext}",
            duration=duration
        )
        db.session.add(voice_msg)
        db.session.commit()

        # Send notification
        notif = Notification(
            user_id=receiver.id,
            from_user_id=current_user.id,
            type="voice_message",
            text=f"Voice message from {current_user.username}"
        )
        db.session.add(notif)
        db.session.commit()
        send_notification(receiver.id, {
            "type": "voice_message",
            "from_user": {"id": current_user.id, "username": current_user.username, "avatar": current_user.avatar_url},
            "text": f"Voice message from {current_user.username}"
        })

        room = "_".join(sorted([str(current_user.id), str(receiver.id)]))
        socketio.emit("new_voice_message", {
            "id": voice_msg.id,
            "sender_id": current_user.id,
            "sender_username": current_user.username,
            "sender_avatar": current_user.avatar_url,
            "audio_url": voice_msg.audio_url_data,
            "duration": voice_msg.duration,
            "created_at": voice_msg.created_at.strftime("%H:%M")
        }, room=room)

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

    # Mark as listened if receiver
    if msg.receiver_id == current_user.id and not msg.is_listened:
        msg.is_listened = True
        db.session.commit()

    return jsonify({
        "id": msg.id,
        "sender_id": msg.sender_id,
        "audio_url": msg.audio_url_data,
        "duration": msg.duration,
        "created_at": msg.created_at.isoformat(),
        "is_read": msg.is_read,
        "is_listened": msg.is_listened
    })


@app.route("/voice/mark-read/<int:message_id>", methods=["POST"])
@login_required
def mark_voice_read(message_id):
    msg = VoiceMessage.query.get_or_404(message_id)
    if msg.receiver_id == current_user.id:
        msg.is_read = True
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"error": "Not authorized"}), 403


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

        # Check if user is already in a call
        existing_call = Call.query.filter(
            and_(
                or_(
                    Call.caller_id == callee.id,
                    Call.callee_id == callee.id
                ),
                Call.status == 'ongoing'
            )
        ).first()

        if existing_call:
            return jsonify({"error": "User is already in a call"}), 409

        call = Call(
            caller_id=current_user.id,
            callee_id=callee.id,
            call_type=call_type,
            status='ringing'
        )
        db.session.add(call)
        db.session.commit()

        webrtc_config = {
            'iceServers': [
                {'urls': 'stun:stun.l.google.com:19302'},
                {'urls': 'stun:stun1.l.google.com:19302'},
                {'urls': 'stun:stun2.l.google.com:19302'},
                {'urls': 'stun:stun3.l.google.com:19302'},
                {'urls': 'stun:stun4.l.google.com:19302'}
            ]
        }

        room = f"user_{callee.id}"
        socketio.emit("incoming_call", {
            "call_id": call.id,
            "caller_id": current_user.id,
            "caller_username": current_user.username,
            "caller_avatar": current_user.avatar_url,
            "type": call_type,
            "webrtc_config": webrtc_config
        }, room=room)

        return jsonify({
            "success": True,
            "call_id": call.id,
            "webrtc_config": webrtc_config
        })

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

    # Send notification to caller
    notif = Notification(
        user_id=call.caller_id,
        from_user_id=current_user.id,
        type="incoming_call",
        call_id=call.id,
        text=f"{current_user.username} accepted your call"
    )
    db.session.add(notif)
    db.session.commit()

    room = f"user_{call.caller_id}"
    socketio.emit("call_accepted", {
        "call_id": call.id,
        "accepted_by": current_user.id
    }, room=room)

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

    # Send notification
    notif = Notification(
        user_id=call.caller_id,
        from_user_id=current_user.id,
        type="missed_call",
        call_id=call.id,
        text=f"{current_user.username} rejected your call"
    )
    db.session.add(notif)
    db.session.commit()
    send_notification(call.caller_id, {
        "type": "missed_call",
        "from_user": {"id": current_user.id, "username": current_user.username, "avatar": current_user.avatar_url},
        "text": f"Rejected your call"
    })

    room = f"user_{call.caller_id}"
    socketio.emit("call_rejected", {
        "call_id": call.id,
        "rejected_by": current_user.id
    }, room=room)

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
    socketio.emit("call_ended", {
        "call_id": call.id,
        "ended_by": current_user.id,
        "duration": call.duration
    }, room=room)

    return jsonify({"success": True})


@app.route("/call/history")
@login_required
def call_history():
    calls = Call.query.filter(
        or_(
            Call.caller_id == current_user.id,
            Call.callee_id == current_user.id
        )
    ).order_by(Call.started_at.desc()).limit(50).all()

    call_list = []
    for call in calls:
        other = User.query.get(call.caller_id if call.callee_id == current_user.id else call.callee_id)
        call_list.append({
            "id": call.id,
            "other_user": {
                "id": other.id,
                "username": other.username,
                "display_name": other.display_name,
                "avatar": other.avatar_url
            },
            "type": call.call_type,
            "status": call.status,
            "duration": call.duration,
            "started_at": call.started_at.isoformat(),
            "is_outgoing": call.caller_id == current_user.id
        })

    return jsonify({"calls": call_list})


# ──────────────────────────────────────────────────────────────────────────────
#  Report Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/report/user/<int:user_id>", methods=["GET", "POST"])
@login_required
def report_user(user_id):
    reported_user = User.query.get_or_404(user_id)

    if reported_user.id == current_user.id:
        flash("Cannot report yourself", "error")
        return redirect(url_for("profile", username=reported_user.username))

    if request.method == "POST":
        reason = request.form.get("reason")
        description = request.form.get("description", "")

        if not reason:
            flash("Please select a reason", "error")
            return redirect(url_for("report_user", user_id=user_id))

        report = Report(
            reporter_id=current_user.id,
            reported_user_id=reported_user.id,
            reason=reason,
            description=description,
            status='pending'
        )
        db.session.add(report)
        db.session.commit()

        flash(f"Report against {reported_user.username} submitted", "success")
        return redirect(url_for("profile", username=reported_user.username))

    reasons = [
        ("spam", "Spam"),
        ("harassment", "Harassment"),
        ("hate_speech", "Hate speech"),
        ("violence", "Violence"),
        ("scam", "Scam"),
        ("fake_account", "Fake account"),
        ("underage", "Underage user"),
        ("other", "Other")
    ]

    return render_template("report_user.html", user=reported_user, reasons=reasons)


@app.route("/report/post/<int:post_id>", methods=["GET", "POST"])
@login_required
def report_post(post_id):
    post = Post.query.get_or_404(post_id)

    if post.user_id == current_user.id:
        flash("Cannot report your own post", "error")
        return redirect(url_for("view_post", post_id=post_id))

    if request.method == "POST":
        reason = request.form.get("reason")
        description = request.form.get("description", "")

        if not reason:
            flash("Please select a reason", "error")
            return redirect(url_for("report_post", post_id=post_id))

        report = Report(
            reporter_id=current_user.id,
            reported_user_id=post.user_id,
            post_id=post.id,
            reason=reason,
            description=description,
            status='pending'
        )
        db.session.add(report)
        db.session.commit()

        flash("Report submitted", "success")
        return redirect(url_for("view_post", post_id=post_id))

    reasons = [
        ("spam", "Spam"),
        ("harassment", "Harassment"),
        ("hate_speech", "Hate speech"),
        ("violence", "Violence"),
        ("nsfw", "NSFW content"),
        ("copyright", "Copyright violation"),
        ("other", "Other")
    ]

    return render_template("report_post.html", post=post, reasons=reasons)


@app.route("/report/comment/<int:comment_id>", methods=["GET", "POST"])
@login_required
def report_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)

    if comment.user_id == current_user.id:
        flash("Cannot report your own comment", "error")
        return redirect(url_for("view_post", post_id=comment.post_id))

    if request.method == "POST":
        reason = request.form.get("reason")
        description = request.form.get("description", "")

        if not reason:
            flash("Please select a reason", "error")
            return redirect(url_for("report_comment", comment_id=comment_id))

        report = Report(
            reporter_id=current_user.id,
            reported_user_id=comment.user_id,
            comment_id=comment.id,
            reason=reason,
            description=description,
            status='pending'
        )
        db.session.add(report)
        db.session.commit()

        flash("Report submitted", "success")
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
                flash("All fields are required", "error")
                return render_template("register.html")

            if not re.match(r"^[a-zA-Z0-9_]{3,40}$", username):
                flash("Username must be 3-40 characters and contain only letters, numbers, and underscores", "error")
                return render_template("register.html")

            if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
                flash("Invalid email format", "error")
                return render_template("register.html")

            if len(password) < 8:
                flash("Password must be at least 8 characters", "error")
                return render_template("register.html")

            if password != confirm:
                flash("Passwords do not match", "error")
                return render_template("register.html")

            existing_user = User.query.filter(
                (User.username == username) | (User.email == email)
            ).first()

            if existing_user:
                if existing_user.username == username:
                    flash("Username already taken", "error")
                else:
                    flash("Email already registered", "error")
                return render_template("register.html")

            user = User(
                username=username,
                email=email,
                display_name=username,
                preset_avatar=1,
                bio="",
                accent_color="#6c63ff",
                is_private=False,
                is_verified=False,
                is_banned=False
            )
            user.set_password(password)

            db.session.add(user)
            db.session.commit()

            # Create user settings
            settings = UserSettings(user_id=user.id)
            db.session.add(settings)
            db.session.commit()

            login_user(user, remember=True)

            flash(f"Welcome to Kildear, {username}! 🎉", "success")
            return redirect(url_for("index"))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Registration error: {str(e)}")
            flash("An error occurred during registration. Please try again.", "error")
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

        user = User.query.filter(
            or_(
                func.lower(User.username) == identifier.lower(),
                func.lower(User.email) == identifier.lower()
            )
        ).first()

        login_success = False

        if user and user.check_password(password) and not user.is_banned:
            login_user(user, remember=remember)
            session.permanent = remember

            user.is_online = True
            user.last_seen = datetime.utcnow()

            login_success = True
            flash(f"Welcome back, {user.username}! 👋", "success")
        else:
            track_failure(ip)
            flash("Invalid credentials.", "error")

        # Log login attempt
        try:
            login_history = LoginHistory(
                user_id=user.id if user else None,
                ip_address=ip,
                user_agent=user_agent[:500],
                location=None,
                success=login_success
            )
            db.session.add(login_history)
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to save login history: {e}")
            db.session.rollback()

        if login_success:
            next_page = request.args.get("next")
            return redirect(next_page or url_for("index"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    current_user.is_online = False
    current_user.last_seen = datetime.utcnow()
    db.session.commit()

    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per hour")
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()

        if user:
            # Generate reset token
            token = serializer.dumps(email, salt='password-reset')
            user.reset_token = token
            user.reset_token_expires = datetime.utcnow() + timedelta(hours=24)
            db.session.commit()

            # In a real app, send email here
            flash(f"Password reset link has been sent to {email}", "info")
        else:
            flash("No account found with that email", "error")

        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        email = serializer.loads(token, salt='password-reset', max_age=86400)
    except:
        flash("Invalid or expired reset link", "error")
        return redirect(url_for("login"))

    user = User.query.filter_by(email=email).first()

    if not user or user.reset_token != token or user.reset_token_expires < datetime.utcnow():
        flash("Invalid or expired reset link", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if len(password) < 8:
            flash("Password must be at least 8 characters", "error")
        elif password != confirm:
            flash("Passwords do not match", "error")
        else:
            user.set_password(password)
            user.reset_token = None
            user.reset_token_expires = None
            db.session.commit()

            flash("Password has been reset. You can now log in.", "success")
            return redirect(url_for("login"))

    return render_template("reset_password.html", token=token)


# ──────────────────────────────────────────────────────────────────────────────
#  Feed / Home
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    followed_ids = [u.id for u in current_user.following.all()] + [current_user.id]
    blocked_ids = [b.id for b in current_user.blocked_users]

    posts = Post.query.filter(
        Post.user_id.in_(followed_ids),
        Post.user_id.notin_(blocked_ids)
    ).order_by(Post.created_at.desc()).paginate(page=page, per_page=15, error_out=False)

    # Get story suggestions
    story_users = User.query.filter(
        User.id != current_user.id,
        User.id.notin_(blocked_ids),
        User.stories.any(Story.expires_at > datetime.utcnow())
    ).limit(10).all()

    suggestions = User.query.filter(
        User.id.notin_(followed_ids + blocked_ids),
        User.id != current_user.id
    ).order_by(func.random()).limit(5).all()

    return render_template("index.html", posts=posts, suggestions=suggestions, story_users=story_users)


# ──────────────────────────────────────────────────────────────────────────────
#  Posts
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/post/create", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def create_post():
    content = request.form.get("content", "").strip()
    media_file = request.files.get("media")
    media_url = ""
    media_type = "text"

    if media_file and media_file.filename:
        try:
            ext = media_file.filename.rsplit(".", 1)[-1].lower() if '.' in media_file.filename else ''

            if ext in ALLOWED_VIDEO:
                media_url = save_file(media_file, "videos") or ""
                media_type = "video"
            elif ext in ALLOWED_IMAGE:
                media_url = save_file(media_file, "images", resize=(1200, 1200)) or ""
                media_type = "image"
            else:
                flash(f"Unsupported file type", "error")
                return redirect(url_for("index"))
        except Exception as e:
            logger.error(f"Error saving file: {e}")
            flash("Error uploading file", "error")
            return redirect(url_for("index"))

    if not content and not media_url:
        flash("Post cannot be empty.", "error")
        return redirect(url_for("index"))

    post = Post(
        user_id=current_user.id,
        content=content,
        media_url=media_url or "",
        media_type=media_type
    )

    db.session.add(post)
    db.session.commit()

    # Extract and add hashtags
    hashtags = extract_hashtags(content)
    if hashtags:
        update_hashtags(post.id, hashtags)

    flash("Post published!", "success")
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
            notif = Notification(
                user_id=post.user_id,
                from_user_id=current_user.id,
                type="like",
                post_id=post.id,
                text=f"{current_user.username} liked your post"
            )
            db.session.add(notif)
            db.session.commit()
            send_notification(post.user_id, {
                "type": "like",
                "from_user": {"id": current_user.id, "username": current_user.username,
                              "avatar": current_user.avatar_url},
                "post_id": post.id,
                "text": f"Liked your post"
            })

    db.session.commit()
    return jsonify({"liked": liked, "count": post.like_count})


@app.route("/post/<int:post_id>/save", methods=["POST"])
@login_required
def save_post(post_id):
    post = Post.query.get_or_404(post_id)

    if post.is_saved_by(current_user):
        post.saved_by.remove(current_user)
        saved = False
    else:
        post.saved_by.append(current_user)
        saved = True

    db.session.commit()
    return jsonify({"saved": saved, "count": post.save_count})


@app.route("/post/<int:post_id>/comment", methods=["POST"])
@login_required
@limiter.limit("60 per hour")
def add_comment(post_id):
    post = Post.query.get_or_404(post_id)

    if post.author.id in [b.id for b in current_user.blocked_users]:
        return jsonify({"error": "Cannot interact with blocked user"}), 403

    content = request.form.get("content", "").strip()
    parent_id = request.form.get("parent_id", type=int)

    if not content:
        return jsonify({"error": "Comment cannot be empty."}), 400

    comment = Comment(
        post_id=post.id,
        user_id=current_user.id,
        content=content,
        parent_id=parent_id
    )
    db.session.add(comment)

    if post.user_id != current_user.id:
        notif = Notification(
            user_id=post.user_id,
            from_user_id=current_user.id,
            type="comment",
            post_id=post.id,
            comment_id=comment.id,
            text=f"{current_user.username} commented on your post"
        )
        db.session.add(notif)
        send_notification(post.user_id, {
            "type": "comment",
            "from_user": {"id": current_user.id, "username": current_user.username, "avatar": current_user.avatar_url},
            "post_id": post.id,
            "comment": content[:50],
            "text": f"Commented on your post"
        })

    db.session.commit()

    return jsonify({
        "id": comment.id,
        "username": current_user.username,
        "display_name": current_user.display_name,
        "avatar": current_user.avatar_url,
        "content": comment.content,
        "created_at": comment.created_at.strftime("%b %d, %Y"),
        "reply_count": 0
    })


@app.route("/post/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(post)
    db.session.commit()
    flash("Post deleted.", "info")
    return redirect(url_for("index"))


@app.route("/post/<int:post_id>/edit", methods=["POST"])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id != current_user.id:
        abort(403)

    content = request.form.get("content", "").strip()
    if not content:
        flash("Post cannot be empty", "error")
        return redirect(url_for("view_post", post_id=post_id))

    post.content = content
    post.is_edited = True
    post.updated_at = datetime.utcnow()
    db.session.commit()

    flash("Post updated", "success")
    return redirect(url_for("view_post", post_id=post_id))


# ──────────────────────────────────────────────────────────────────────────────
#  Profile
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/u/<username>")
@login_required
def profile(username):
    user = User.query.filter(func.lower(User.username) == username.lower()).first_or_404()

    is_blocked = current_user.is_blocked(user) if user.id != current_user.id else False
    is_muted = current_user.is_muted(user) if user.id != current_user.id else False

    page = request.args.get("page", 1, type=int)
    tab = request.args.get("tab", "posts")

    if is_blocked:
        posts = []
        posts_pagination = None
        saved_posts = []
    else:
        if tab == "posts":
            posts_pagination = user.posts.order_by(Post.created_at.desc()).paginate(page=page, per_page=12,
                                                                                    error_out=False)
            posts = posts_pagination.items
        elif tab == "saved" and user.id == current_user.id:
            saved_posts = current_user.saved_posts.order_by(post_saves.c.created_at.desc()).paginate(page=page,
                                                                                                     per_page=12,
                                                                                                     error_out=False)
            posts = saved_posts.items
        else:
            posts_pagination = user.posts.order_by(Post.created_at.desc()).paginate(page=page, per_page=12,
                                                                                    error_out=False)
            posts = posts_pagination.items

    is_own = user.id == current_user.id
    is_following = current_user.is_following(user) if not is_own else False

    # Get mutual followers count
    mutual_followers = 0
    if not is_own and not is_blocked:
        mutual_followers = user.followers.filter(User.id.in_([f.id for f in current_user.following])).count()

    return render_template(
        "profile.html",
        user=user,
        posts=posts,
        posts_pagination=posts_pagination if tab == "posts" else None,
        saved_posts=saved_posts if tab == "saved" else None,
        is_own=is_own,
        is_following=is_following,
        is_blocked=is_blocked,
        is_muted=is_muted,
        tab=tab,
        mutual_followers=mutual_followers
    )


@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        try:
            current_user.display_name = request.form.get("display_name", "")[:60]
            current_user.bio = request.form.get("bio", "")[:500]
            current_user.website = request.form.get("website", "")[:200]
            current_user.location = request.form.get("location", "")[:100]
            current_user.is_private = bool(request.form.get("is_private"))

            birthday = request.form.get("birthday")
            if birthday:
                try:
                    current_user.birthday = datetime.strptime(birthday, "%Y-%m-%d").date()
                except:
                    pass

            accent_color = request.form.get("accent_color")
            if not accent_color:
                accent_color = request.form.get("accent_color_custom", "#6c63ff")
            current_user.accent_color = accent_color[:7]

            preset_avatar = request.form.get("preset_avatar")
            if preset_avatar:
                try:
                    avatar_num = int(preset_avatar)
                    if 1 <= avatar_num <= 10:
                        current_user.set_preset_avatar(avatar_num)
                except (ValueError, TypeError):
                    pass

            preset_cover = request.form.get("preset_cover")
            if preset_cover:
                try:
                    cover_num = int(preset_cover)
                    if 1 <= cover_num <= 5:
                        current_user.set_preset_cover(cover_num)
                except (ValueError, TypeError):
                    pass
            elif request.form.get("remove_cover") == "1":
                current_user.set_preset_cover(None)

            # Avatar upload
            if 'avatar_file' in request.files:
                file = request.files['avatar_file']
                if file and file.filename:
                    ext = file.filename.rsplit('.', 1)[1].lower()
                    if ext in ALLOWED_IMAGE:
                        filename = save_file(file, "avatars", resize=(200, 200))
                        if filename:
                            current_user.set_custom_avatar(os.path.basename(filename))

            # Cover upload
            if 'cover_file' in request.files:
                file = request.files['cover_file']
                if file and file.filename:
                    ext = file.filename.rsplit('.', 1)[1].lower()
                    if ext in ALLOWED_IMAGE:
                        filename = save_file(file, "covers", resize=(1200, 400))
                        if filename:
                            current_user.set_custom_cover(os.path.basename(filename))

            # Change password
            current_password = request.form.get("current_password")
            new_password = request.form.get("new_password")
            if current_password and new_password:
                if current_user.check_password(current_password):
                    if len(new_password) >= 8:
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
            flash(f"Error updating profile: {str(e)}", "error")

        return redirect(url_for("profile", username=current_user.username))

    return render_template("edit_profile.html")


@app.route("/follow/<username>", methods=["POST"])
@login_required
def follow(username):
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
        notif = Notification(
            user_id=user.id,
            from_user_id=current_user.id,
            type="follow",
            text=f"{current_user.username} started following you"
        )
        db.session.add(notif)
        db.session.commit()
        send_notification(user.id, {
            "type": "follow",
            "from_user": {"id": current_user.id, "username": current_user.username, "avatar": current_user.avatar_url},
            "text": f"Started following you"
        })

    db.session.commit()
    return jsonify({"following": following, "followers": user.follower_count})


# ──────────────────────────────────────────────────────────────────────────────
#  Block/Mute Routes
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


@app.route("/user/<int:user_id>/mute", methods=["POST"])
@login_required
def mute_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({"error": "Cannot mute yourself"}), 400

    if current_user.mute(user):
        db.session.commit()
        return jsonify({"success": True, "muted": True})
    return jsonify({"error": "User already muted"}), 400


@app.route("/user/<int:user_id>/unmute", methods=["POST"])
@login_required
def unmute_user(user_id):
    user = User.query.get_or_404(user_id)
    if current_user.unmute(user):
        db.session.commit()
        return jsonify({"success": True, "muted": False})
    return jsonify({"error": "User not muted"}), 400


# ──────────────────────────────────────────────────────────────────────────────
#  Explore / Search
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/explore")
@login_required
def explore():
    page = request.args.get("page", 1, type=int)
    blocked_ids = [b.id for b in current_user.blocked_users]

    # Trending posts
    trending = Post.query.filter(
        Post.user_id.notin_(blocked_ids),
        Post.created_at >= datetime.utcnow() - timedelta(days=7)
    ).order_by(Post.views.desc(), Post.like_count.desc()).limit(20).all()

    # Recommended users
    following_ids = [f.id for f in current_user.following.all()] + [current_user.id]
    recommended = User.query.filter(
        User.id.notin_(following_ids + blocked_ids),
        User.is_banned == False
    ).order_by(func.random()).limit(10).all()

    # Popular hashtags
    popular_hashtags = Hashtag.query.order_by(Hashtag.post_count.desc()).limit(10).all()

    return render_template("explore.html", trending=trending, recommended=recommended,
                           popular_hashtags=popular_hashtags)


@app.route("/search")
@login_required
@limiter.limit("60 per minute")
def search():
    q = request.args.get("q", "").strip()
    tab = request.args.get("tab", "people")

    if q.startswith('#'):
        q = q[1:]
        tab = "hashtags"

    users = []
    posts = []
    hashtags = []

    blocked_ids = [b.id for b in current_user.blocked_users]

    if q:
        pattern = f"%{q}%"

        if tab == "people" or tab == "all":
            users = User.query.filter(
                or_(
                    User.username.ilike(pattern),
                    User.display_name.ilike(pattern)
                ),
                User.id != current_user.id,
                User.id.notin_(blocked_ids),
                User.is_banned == False
            ).limit(20).all()

        if tab == "posts" or tab == "all":
            posts = Post.query.filter(
                Post.content.ilike(pattern),
                Post.user_id.notin_(blocked_ids)
            ).order_by(Post.created_at.desc()).limit(20).all()

        if tab == "hashtags" or tab == "all":
            hashtags = Hashtag.query.filter(
                Hashtag.name.ilike(pattern)
            ).order_by(Hashtag.post_count.desc()).limit(10).all()

    if request.args.get("ajax") == "1":
        return jsonify({
            "users": [{
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name or u.username,
                "avatar": u.avatar_url,
                "is_online": u.is_online
            } for u in users]
        })

    return render_template("search.html", q=q, tab=tab, users=users, posts=posts, hashtags=hashtags)


@app.route("/hashtag/<tag>")
@login_required
def hashtag(tag):
    hashtag = Hashtag.query.filter_by(name=tag.lower()).first_or_404()
    page = request.args.get("page", 1, type=int)
    blocked_ids = [b.id for b in current_user.blocked_users]

    posts = Post.query.join(post_hashtags).filter(
        post_hashtags.c.hashtag_id == hashtag.id,
        Post.user_id.notin_(blocked_ids)
    ).order_by(Post.created_at.desc()).paginate(page=page, per_page=15, error_out=False)

    return render_template("hashtag.html", hashtag=hashtag, posts=posts)


# ──────────────────────────────────────────────────────────────────────────────
#  Chat
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/chat")
@login_required
def chat_list():
    try:
        # Get unique conversation partners
        sent_to = db.session.query(Message.receiver_id).filter_by(sender_id=current_user.id,
                                                                  is_deleted_for_sender=False).distinct()
        recv_from = db.session.query(Message.sender_id).filter_by(receiver_id=current_user.id,
                                                                  is_deleted_for_receiver=False).distinct()
        uid_set = {r[0] for r in sent_to} | {r[0] for r in recv_from}

        blocked_ids = [b.id for b in current_user.blocked_users]
        uid_set = uid_set - set(blocked_ids)

        partners = User.query.filter(User.id.in_(uid_set)).all()

        conversations = []
        for p in partners:
            # Get last message
            last = Message.query.filter(
                or_(
                    and_(Message.sender_id == current_user.id, Message.receiver_id == p.id,
                         Message.is_deleted_for_sender == False),
                    and_(Message.sender_id == p.id, Message.receiver_id == current_user.id,
                         Message.is_deleted_for_receiver == False)
                ),
                Message.is_deleted == False
            ).order_by(Message.created_at.desc()).first()

            # Count unread
            unread = Message.query.filter_by(
                sender_id=p.id,
                receiver_id=current_user.id,
                is_read=False,
                is_deleted=False,
                is_deleted_for_receiver=False
            ).count()

            voice_unread = VoiceMessage.query.filter_by(
                sender_id=p.id,
                receiver_id=current_user.id,
                is_read=False
            ).count()

            conversations.append({
                "user": p,
                "last": last,
                "unread": unread,
                "voice_unread": voice_unread
            })

        conversations.sort(key=lambda x: x["last"].created_at if x["last"] else datetime.min, reverse=True)
        return render_template("chat_list.html", conversations=conversations)

    except Exception as e:
        logger.error(f"Error in chat_list: {e}")
        flash("Error loading chats", "error")
        return redirect(url_for("index"))


@app.route("/chat/<username>")
@login_required
def chat(username):
    try:
        partner = User.query.filter(func.lower(User.username) == username.lower()).first_or_404()

        is_blocked = current_user.is_blocked(partner)
        is_muted = current_user.is_muted(partner)

        if not is_blocked:
            # Mark messages as read
            Message.query.filter_by(
                sender_id=partner.id,
                receiver_id=current_user.id,
                is_read=False
            ).update({"is_read": True})

            VoiceMessage.query.filter_by(
                sender_id=partner.id,
                receiver_id=current_user.id,
                is_read=False
            ).update({"is_read": True})

            db.session.commit()

        if is_blocked:
            messages = []
        else:
            messages = Message.query.filter(
                or_(
                    and_(Message.sender_id == current_user.id, Message.receiver_id == partner.id,
                         Message.is_deleted_for_sender == False),
                    and_(Message.sender_id == partner.id, Message.receiver_id == current_user.id,
                         Message.is_deleted_for_receiver == False)
                ),
                Message.is_deleted == False
            ).order_by(Message.created_at.asc()).limit(100).all()

            # Load locations and reactions for messages
            for msg in messages:
                if msg.media_type == 'location':
                    msg.location = SharedLocation.query.filter_by(message_id=msg.id).first()
                msg.reaction_list = MessageReaction.query.filter_by(message_id=msg.id).all()

        return render_template(
            "chat.html",
            partner=partner,
            messages=messages,
            is_blocked=is_blocked,
            is_muted=is_muted
        )

    except Exception as e:
        logger.error(f"Error in chat: {e}")
        flash("Error loading chat", "error")
        return redirect(url_for("chat_list"))


@app.route("/chat/<username>/send", methods=["POST"])
@login_required
@limiter.limit("120 per minute")
def send_message(username):
    try:
        partner = User.query.filter(func.lower(User.username) == username.lower()).first_or_404()

        if current_user.is_blocked(partner):
            return jsonify({"error": "Cannot send message to blocked user"}), 403

        if current_user.is_muted(partner):
            return jsonify({"error": "Cannot send message to muted user"}), 403

        content = request.form.get("content", "").strip()
        media_file = request.files.get("media")
        media_url = ""
        media_type = "text"
        reply_to_id = request.form.get("reply_to", type=int)

        if media_file and media_file.filename:
            ext = media_file.filename.rsplit('.', 1)[1].lower() if '.' in media_file.filename else ''

            if ext in ALLOWED_IMAGE:
                media_url = save_file(media_file, "chat_images", resize=(1000, 1000)) or ""
                media_type = "image"
            elif ext in ALLOWED_VIDEO:
                media_url = save_file(media_file, "videos") or ""
                media_type = "video"

        if not content and not media_url:
            return jsonify({"error": "Message cannot be empty."}), 400

        msg = Message(
            sender_id=current_user.id,
            receiver_id=partner.id,
            content=content,
            media_url=media_url,
            media_type=media_type,
            reply_to_id=reply_to_id,
            is_delivered=True
        )
        db.session.add(msg)
        db.session.commit()

        # Send notification if user has notifications enabled
        if partner.id != current_user.id:
            settings = partner.get_settings()
            if settings.notify_messages:
                notif = Notification(
                    user_id=partner.id,
                    from_user_id=current_user.id,
                    type="message",
                    message_id=msg.id,
                    text=f"New message from {current_user.username}"
                )
                db.session.add(notif)
                db.session.commit()
                send_notification(partner.id, {
                    "type": "message",
                    "from_user": {"id": current_user.id, "username": current_user.username,
                                  "avatar": current_user.avatar_url},
                    "message": content[:50],
                    "text": f"New message from {current_user.username}"
                })

        message_data = {
            "id": msg.id,
            "sender_id": current_user.id,
            "sender_username": current_user.username,
            "sender_avatar": current_user.avatar_url,
            "content": msg.content,
            "media_url": msg.media_url,
            "media_type": msg.media_type,
            "reply_to_id": msg.reply_to_id,
            "created_at": msg.created_at.strftime("%H:%M")
        }

        room = "_".join(sorted([str(current_user.id), str(partner.id)]))
        socketio.emit("new_message", message_data, room=room)

        return jsonify({"ok": True, "id": msg.id})

    except Exception as e:
        logger.error(f"Error in send_message: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/chat/message/<int:message_id>/delete", methods=["POST"])
@login_required
def delete_message(message_id):
    try:
        msg = Message.query.get_or_404(message_id)

        if msg.sender_id == current_user.id:
            msg.is_deleted_for_sender = True
        elif msg.receiver_id == current_user.id:
            msg.is_deleted_for_receiver = True
        else:
            return jsonify({"error": "Cannot delete this message"}), 403

        # If both deleted, mark as fully deleted
        if msg.is_deleted_for_sender and msg.is_deleted_for_receiver:
            msg.is_deleted = True

        db.session.commit()

        # Notify other user
        room = "_".join(sorted([str(msg.sender_id), str(msg.receiver_id)]))
        socketio.emit("message_deleted", {"message_id": message_id}, room=room)

        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"Error deleting message: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/chat/message/<int:message_id>/edit", methods=["POST"])
@login_required
def edit_message(message_id):
    try:
        msg = Message.query.get_or_404(message_id)

        if msg.sender_id != current_user.id:
            return jsonify({"error": "Cannot edit other's messages"}), 403

        content = request.form.get("content", "").strip()
        if not content:
            return jsonify({"error": "Message cannot be empty"}), 400

        msg.content = content
        msg.edited_at = datetime.utcnow()
        db.session.commit()

        room = "_".join(sorted([str(msg.sender_id), str(msg.receiver_id)]))
        socketio.emit("message_edited", {
            "message_id": message_id,
            "content": content,
            "edited_at": msg.edited_at.isoformat()
        }, room=room)

        return jsonify({"success": True})

    except Exception as e:
        logger.error(f"Error editing message: {e}")
        return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────────────────────────────────────────
#  Groups
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/groups")
@login_required
def groups():
    my_groups = current_user.groups
    explore = Group.query.filter(
        ~Group.members.any(User.id == current_user.id),
        Group.is_private == False
    ).order_by(Group.member_count.desc()).limit(20).all()
    return render_template("groups.html", my_groups=my_groups, explore=explore)


@app.route("/groups/create", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per hour")
def create_group():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        desc = request.form.get("description", "").strip()[:500]
        priv = bool(request.form.get("is_private"))

        base_slug = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-"))
        slug = base_slug[:50] + f"-{uuid.uuid4().hex[:6]}"

        g = Group(
            name=name,
            slug=slug,
            description=desc,
            owner_id=current_user.id,
            is_private=priv
        )

        db.session.add(g)
        db.session.flush()
        g.members.append(current_user)
        db.session.commit()
        g.update_counts()

        flash(f"Group '{name}' created!", "success")
        return redirect(url_for("group_detail", slug=g.slug))

    return render_template("create_group.html")


@app.route("/groups/<slug>")
@login_required
def group_detail(slug):
    g = Group.query.filter_by(slug=slug).first_or_404()
    is_member = g.members.filter(User.id == current_user.id).count() > 0
    is_owner = g.owner_id == current_user.id
    posts = g.posts.order_by(GroupPost.created_at.desc()).limit(30).all()

    return render_template(
        "group_detail.html",
        group=g,
        is_member=is_member,
        is_owner=is_owner,
        posts=posts
    )


@app.route("/groups/<slug>/join", methods=["POST"])
@login_required
def join_group(slug):
    g = Group.query.filter_by(slug=slug).first_or_404()

    if not g.members.filter(User.id == current_user.id).count():
        g.members.append(current_user)
        db.session.commit()
        g.update_counts()
        flash(f"You joined '{g.name}'", "success")
        send_group_update(g.id, {"type": "member_joined", "user_id": current_user.id, "username": current_user.username,
                                 "member_count": g.member_count})
    else:
        flash("You are already a member", "info")

    return redirect(url_for("group_detail", slug=slug))


@app.route("/groups/<slug>/leave", methods=["POST"])
@login_required
def leave_group(slug):
    g = Group.query.filter_by(slug=slug).first_or_404()

    if g.owner_id == current_user.id:
        flash("Owner cannot leave the group. Transfer ownership first or delete the group.", "error")
    elif g.members.filter(User.id == current_user.id).count():
        g.members.remove(current_user)
        db.session.commit()
        g.update_counts()
        flash(f"You left '{g.name}'", "info")
        send_group_update(g.id, {"type": "member_left", "user_id": current_user.id, "username": current_user.username,
                                 "member_count": g.member_count})

    return redirect(url_for("group_detail", slug=slug))


@app.route("/groups/<slug>/post", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def group_post(slug):
    g = Group.query.filter_by(slug=slug).first_or_404()

    if not g.members.filter(User.id == current_user.id).count():
        abort(403)

    content = request.form.get("content", "").strip()
    media_file = request.files.get("media")
    media_url = ""
    media_type = "text"

    if media_file and media_file.filename:
        ext = media_file.filename.rsplit(".", 1)[-1].lower()
        if ext in ALLOWED_VIDEO:
            media_url = save_file(media_file, "videos") or ""
            media_type = "video"
        elif ext in ALLOWED_IMAGE:
            media_url = save_file(media_file, "images") or ""
            media_type = "image"

    p = GroupPost(
        group_id=g.id,
        user_id=current_user.id,
        content=content,
        media_url=media_url or "",
        media_type=media_type
    )

    db.session.add(p)
    db.session.commit()
    g.update_counts()

    flash("Post published in group!", "success")
    return redirect(url_for("group_detail", slug=slug))


@app.route("/groups/<slug>/delete", methods=["POST"])
@login_required
def delete_group(slug):
    g = Group.query.filter_by(slug=slug).first_or_404()

    if g.owner_id != current_user.id and not current_user.is_admin:
        abort(403)

    name = g.name
    db.session.delete(g)
    db.session.commit()

    flash(f"Group '{name}' has been deleted", "success")
    return redirect(url_for("groups"))


# ──────────────────────────────────────────────────────────────────────────────
#  Channels
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/channels")
@login_required
def channels():
    my_channels = current_user.subscribed_channels
    explore = Channel.query.filter(
        ~Channel.subscribers.any(User.id == current_user.id),
        Channel.is_nsfw == False
    ).order_by(Channel.sub_count.desc()).limit(20).all()
    return render_template("channels.html", my_channels=my_channels, explore=explore)


@app.route("/channels/create", methods=["GET", "POST"])
@login_required
@limiter.limit("5 per hour")
def create_channel():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:100]
        desc = request.form.get("description", "").strip()[:500]
        is_nsfw = bool(request.form.get("is_nsfw"))

        base_slug = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-"))
        slug = base_slug[:50] + f"-{uuid.uuid4().hex[:6]}"

        c = Channel(
            name=name,
            slug=slug,
            description=desc,
            owner_id=current_user.id,
            is_nsfw=is_nsfw
        )

        db.session.add(c)
        db.session.flush()
        c.subscribers.append(current_user)
        db.session.commit()
        c.update_counts()

        flash(f"Channel '{name}' created!", "success")
        return redirect(url_for("channel_detail", slug=c.slug))

    return render_template("create_channel.html")


@app.route("/channels/<slug>")
@login_required
def channel_detail(slug):
    c = Channel.query.filter_by(slug=slug).first_or_404()
    is_sub = c.subscribers.filter(User.id == current_user.id).count() > 0
    is_own = c.owner_id == current_user.id
    posts = c.posts.order_by(ChannelPost.created_at.desc()).limit(30).all()

    return render_template(
        "channel_detail.html",
        channel=c,
        is_subscribed=is_sub,
        is_own=is_own,
        posts=posts
    )


@app.route("/channels/<slug>/subscribe", methods=["POST"])
@login_required
def subscribe_channel(slug):
    c = Channel.query.filter_by(slug=slug).first_or_404()

    if c.subscribers.filter(User.id == current_user.id).count():
        c.subscribers.remove(current_user)
        subscribed = False
        flash(f"You unsubscribed from '{c.name}'", "info")
    else:
        c.subscribers.append(current_user)
        subscribed = True
        flash(f"You subscribed to '{c.name}'", "success")

    db.session.commit()
    c.update_counts()

    send_channel_update(c.id, {
        "type": "subscriber_changed",
        "user_id": current_user.id,
        "username": current_user.username,
        "subscriber_count": c.sub_count
    })

    return jsonify({"subscribed": subscribed, "count": c.sub_count})


@app.route("/channels/<slug>/publish", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def channel_publish(slug):
    c = Channel.query.filter_by(slug=slug).first_or_404()

    if c.owner_id != current_user.id:
        abort(403)

    content = request.form.get("content", "").strip()
    media_file = request.files.get("media")
    media_url = ""
    media_type = "text"

    if media_file and media_file.filename:
        ext = media_file.filename.rsplit(".", 1)[-1].lower()
        if ext in ALLOWED_VIDEO:
            media_url = save_file(media_file, "videos") or ""
            media_type = "video"
        elif ext in ALLOWED_IMAGE:
            media_url = save_file(media_file, "images") or ""
            media_type = "image"

    p = ChannelPost(
        channel_id=c.id,
        content=content,
        media_url=media_url or "",
        media_type=media_type
    )

    db.session.add(p)
    db.session.commit()
    c.update_counts()

    # Notify subscribers
    post_data = {
        "id": p.id,
        "content": p.content,
        "media_url": p.media_url,
        "media_type": p.media_type,
        "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S")
    }

    for subscriber in c.subscribers:
        if subscriber.id != current_user.id:
            notif = Notification(
                user_id=subscriber.id,
                from_user_id=current_user.id,
                type="channel_post",
                channel_id=c.id,
                text=f"New post in {c.name}"
            )
            db.session.add(notif)
            send_notification(subscriber.id, {
                "type": "channel_post",
                "from_user": {"id": current_user.id, "username": current_user.username},
                "channel": {"id": c.id, "name": c.name, "slug": c.slug},
                "post": post_data,
                "text": f"New post in {c.name}"
            })

    db.session.commit()

    flash("Post published in channel!", "success")
    return redirect(url_for("channel_detail", slug=slug))


@app.route("/channels/<slug>/delete", methods=["POST"])
@login_required
def delete_channel(slug):
    c = Channel.query.filter_by(slug=slug).first_or_404()

    if c.owner_id != current_user.id and not current_user.is_admin:
        abort(403)

    name = c.name
    db.session.delete(c)
    db.session.commit()

    flash(f"Channel '{name}' has been deleted", "success")
    return redirect(url_for("channels"))


# ──────────────────────────────────────────────────────────────────────────────
#  Stories
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/story/create", methods=["POST"])
@login_required
@limiter.limit("20 per day")
def create_story():
    try:
        media_file = request.files.get("media")
        text = request.form.get("text", "").strip()[:200]
        background_color = request.form.get("background_color", "#6c63ff")

        if not media_file and not text:
            return jsonify({"error": "Story cannot be empty"}), 400

        media_url = ""
        media_type = "text"

        if media_file and media_file.filename:
            ext = media_file.filename.rsplit('.', 1)[1].lower()
            if ext in ALLOWED_IMAGE:
                media_url = save_file(media_file, "images", resize=(1080, 1920)) or ""
                media_type = "image"
            elif ext in ALLOWED_VIDEO:
                media_url = save_file(media_file, "videos") or ""
                media_type = "video"

        story = Story(
            user_id=current_user.id,
            media_url=media_url,
            media_type=media_type,
            text=text,
            background_color=background_color
        )
        db.session.add(story)
        db.session.commit()

        return jsonify({"success": True, "story_id": story.id})

    except Exception as e:
        logger.error(f"Error creating story: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/stories")
@login_required
def get_stories():
    blocked_ids = [b.id for b in current_user.blocked_users]

    stories_data = []
    users_with_stories = User.query.filter(
        User.id != current_user.id,
        User.id.notin_(blocked_ids),
        User.stories.any(Story.expires_at > datetime.utcnow())
    ).limit(20).all()

    for user in users_with_stories:
        stories = Story.query.filter(
            Story.user_id == user.id,
            Story.expires_at > datetime.utcnow()
        ).order_by(Story.created_at).all()

        # Check if user has viewed stories
        viewed = False
        for story in stories:
            if db.session.query(story_views).filter_by(story_id=story.id, user_id=current_user.id).first():
                viewed = True
                break

        stories_data.append({
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "avatar": user.avatar_url,
                "accent_color": user.accent_color
            },
            "stories": [{
                "id": s.id,
                "media_url": s.media_url,
                "media_type": s.media_type,
                "text": s.text,
                "background_color": s.background_color,
                "created_at": s.created_at.isoformat()
            } for s in stories],
            "viewed": viewed
        })

    return jsonify({"stories": stories_data})


@app.route("/story/<int:story_id>/view", methods=["POST"])
@login_required
def view_story(story_id):
    story = Story.query.get_or_404(story_id)

    # Record view if not already viewed
    existing = db.session.query(story_views).filter_by(story_id=story_id, user_id=current_user.id).first()
    if not existing:
        db.session.execute(
            story_views.insert().values(story_id=story_id, user_id=current_user.id, viewed_at=datetime.utcnow()))
        story.views += 1
        db.session.commit()

    return jsonify({"success": True})


# ──────────────────────────────────────────────────────────────────────────────
#  Notifications
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/notifications")
@login_required
def notifications():
    page = request.args.get("page", 1, type=int)
    type_filter = request.args.get("type", "all")

    query = Notification.query.filter_by(user_id=current_user.id)

    if type_filter != "all":
        query = query.filter_by(type=type_filter)

    notifs = query.order_by(Notification.created_at.desc()).paginate(page=page, per_page=30, error_out=False)

    # Mark as read
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()

    return render_template("notifications.html", notifs=notifs, type_filter=type_filter)


@app.route("/notifications/clear", methods=["POST"])
@login_required
def clear_notifications():
    Notification.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"success": True})


# ──────────────────────────────────────────────────────────────────────────────
#  QR Code Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/user/<int:user_id>/qrcode")
@login_required
def generate_user_qrcode(user_id):
    user = User.query.get_or_404(user_id)

    if current_user.is_blocked(user):
        return jsonify({"error": "Cannot view blocked user's QR code"}), 403

    if user.is_banned:
        return jsonify({"error": "User is banned"}), 403

    qr_data = f"kildear://user/{user.username}"

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
        "display_name": user.display_name or user.username
    })


@app.route("/qr/generate", methods=["POST"])
@login_required
def generate_qr():
    qr_data = f"kildear://user/{current_user.username}"

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
        "username": current_user.username
    })


@app.route("/qr/scan")
@login_required
def scan_qr_page():
    return render_template("scan_qr.html")


@app.route("/qr/search", methods=["POST"])
@login_required
def search_by_qr():
    data = request.get_json()
    qr_data = data.get("qr_data", "").strip()

    if not qr_data:
        return jsonify({"error": "No QR data provided"}), 400

    if qr_data.startswith("kildear://user/"):
        username = qr_data.replace("kildear://user/", "")
        user = User.query.filter(func.lower(User.username) == username.lower()).first()

        if user:
            if current_user.is_blocked(user):
                return jsonify({"success": False, "error": "You have blocked this user"}), 403

            if user.is_banned:
                return jsonify({"success": False, "error": "This user is banned"}), 403

            return jsonify({
                "success": True,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name or user.username,
                    "avatar": user.avatar_url,
                    "bio": user.bio,
                    "is_following": current_user.is_following(user),
                    "follower_count": user.follower_count,
                    "following_count": user.following_count,
                    "post_count": user.post_count,
                    "is_verified": user.is_verified
                }
            })
        else:
            return jsonify({"success": False, "error": "User not found"}), 404

    return jsonify({"success": False, "error": "Invalid QR code format"}), 400


# ──────────────────────────────────────────────────────────────────────────────
#  WebSocket Helper Functions
# ──────────────────────────────────────────────────────────────────────────────

def send_notification(user_id, notification_data):
    room = f"user_{user_id}"
    socketio.emit("new_notification", notification_data, room=room)


def send_group_update(group_id, update_data):
    room = f"group_{group_id}"
    socketio.emit("group_update", update_data, room=room)


def send_channel_update(channel_id, update_data):
    room = f"channel_{channel_id}"
    socketio.emit("channel_update", update_data, room=room)


# ──────────────────────────────────────────────────────────────────────────────
#  Socket.IO Events
# ──────────────────────────────────────────────────────────────────────────────

@socketio.on("connect")
def handle_connect():
    if current_user.is_authenticated:
        logger.info(f"User {current_user.id} connected")
        user_room = f"user_{current_user.id}"
        join_room(user_room)


@socketio.on("disconnect")
def handle_disconnect():
    if current_user.is_authenticated:
        logger.info(f"User {current_user.id} disconnected")
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


@socketio.on("stop_typing")
def on_stop_typing(data):
    room = data.get("room")
    if room:
        emit("stop_typing", {}, room=room, include_self=False)


@socketio.on("mark_read")
def on_mark_read(data):
    message_id = data.get("message_id")
    if message_id:
        msg = Message.query.get(message_id)
        if msg and msg.receiver_id == current_user.id:
            msg.is_read = True
            db.session.commit()
            room = "_".join(sorted([str(msg.sender_id), str(msg.receiver_id)]))
            emit("read_receipt", {"message_id": message_id, "user_id": current_user.id}, room=room)


@socketio.on("join_group_room")
def on_join_group(data):
    group_id = data.get("group_id")
    if group_id and current_user.is_authenticated:
        group = Group.query.get(group_id)
        if group and group.members.filter(User.id == current_user.id).count() > 0:
            room = f"group_{group_id}"
            join_room(room)


@socketio.on("join_channel_room")
def on_join_channel(data):
    channel_id = data.get("channel_id")
    if channel_id and current_user.is_authenticated:
        channel = Channel.query.get(channel_id)
        if channel and channel.subscribers.filter(User.id == current_user.id).count() > 0:
            room = f"channel_{channel_id}"
            join_room(room)


# WebRTC Signaling
@socketio.on("webrtc_offer")
def on_webrtc_offer(data):
    room = data.get("room")
    if room:
        emit("webrtc_offer", {"offer": data.get("offer"), "from": current_user.id, "call_id": data.get("call_id")},
             room=room, include_self=False)


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
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# ──────────────────────────────────────────────────────────────────────────────
#  Initialize Database and Stickers
# ──────────────────────────────────────────────────────────────────────────────

def init_sticker_packs():
    """Create default sticker packs"""
    try:
        if StickerPack.query.first():
            logger.info("Sticker packs already exist")
            return

        # Default pack
        default_pack = StickerPack(
            name="Kildear Default",
            slug="kildear-default",
            icon="/static/stickers/default_pack.png",
            description="Default sticker pack",
            is_premium=False,
            order=0
        )
        db.session.add(default_pack)
        db.session.flush()

        default_stickers = [
            {"emoji": "😀", "url": "/static/stickers/smile.png"},
            {"emoji": "😂", "url": "/static/stickers/laugh.png"},
            {"emoji": "🥰", "url": "/static/stickers/love.png"},
            {"emoji": "😮", "url": "/static/stickers/shock.png"},
            {"emoji": "😢", "url": "/static/stickers/cry.png"},
            {"emoji": "😡", "url": "/static/stickers/angry.png"},
            {"emoji": "🎉", "url": "/static/stickers/party.png"},
            {"emoji": "🔥", "url": "/static/stickers/fire.png"},
            {"emoji": "👍", "url": "/static/stickers/thumb.png"},
            {"emoji": "👎", "url": "/static/stickers/thumb_down.png"},
        ]

        for i, sticker_data in enumerate(default_stickers):
            sticker = Sticker(
                pack_id=default_pack.id,
                emoji=sticker_data["emoji"],
                image_url=sticker_data["url"],
                order=i
            )
            db.session.add(sticker)

        # Premium pack
        premium_pack = StickerPack(
            name="Kildear Premium",
            slug="kildear-premium",
            icon="/static/stickers/premium_pack.png",
            description="Premium sticker pack",
            is_premium=True,
            price=99,
            order=1
        )
        db.session.add(premium_pack)
        db.session.flush()

        premium_stickers = [
            {"emoji": "✨", "url": "/static/stickers/premium/star.png"},
            {"emoji": "⭐", "url": "/static/stickers/premium/gold.png"},
            {"emoji": "💎", "url": "/static/stickers/premium/diamond.png"},
            {"emoji": "👑", "url": "/static/stickers/premium/crown.png"},
            {"emoji": "🎈", "url": "/static/stickers/premium/balloon.png"},
            {"emoji": "🎁", "url": "/static/stickers/premium/gift.png"},
        ]

        for i, sticker_data in enumerate(premium_stickers):
            sticker = Sticker(
                pack_id=premium_pack.id,
                emoji=sticker_data["emoji"],
                image_url=sticker_data["url"],
                order=i
            )
            db.session.add(sticker)

        db.session.commit()
        logger.info("✅ Default sticker packs created")

    except Exception as e:
        logger.error(f"Error creating sticker packs: {e}")


def create_admin_user():
    """Create first admin user if none exists"""
    try:
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin_password = os.environ.get('ADMIN_PASSWORD', 'Admin123!')
            admin = User(
                username='admin',
                email='admin@kildear.com',
                display_name='Administrator',
                is_admin=True,
                is_verified=True,
                preset_avatar=1
            )
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            logger.info("✅ Admin user created")
            logger.info(f"   Username: admin")
            logger.info(f"   Password: {admin_password}")
        else:
            logger.info("✅ Admin user already exists")
    except Exception as e:
        logger.error(f"Error creating admin: {e}")


def run_migrations():
    """Run database migrations"""
    try:
        inspector = db.inspect(db.engine)
        tables = inspector.get_table_names()

        # Check for missing tables
        required_tables = ['user_settings', 'login_history', 'voice_message', 'call', 'report',
                           'message_reaction', 'shared_location', 'sticker_pack', 'sticker',
                           'story', 'hashtag']

        for table in required_tables:
            if table not in tables:
                logger.info(f"Creating table {table}...")
                db.create_all()
                break

        # Check for missing columns
        if 'user' in tables:
            columns = [col['name'] for col in inspector.get_columns('user')]

            if 'is_moderator' not in columns:
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN is_moderator BOOLEAN DEFAULT FALSE'))
                logger.info("Added is_moderator column")

            if 'birthday' not in columns:
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN birthday DATE'))
                logger.info("Added birthday column")

            if 'custom_avatar' not in columns:
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN custom_avatar VARCHAR(300) DEFAULT ""'))
                logger.info("Added custom_avatar column")

            if 'custom_cover' not in columns:
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN custom_cover VARCHAR(300) DEFAULT ""'))
                logger.info("Added custom_cover column")

        db.session.commit()
        logger.info("✅ Database migrations completed")

    except Exception as e:
        logger.error(f"Error in migrations: {e}")
        db.session.rollback()


def init_app():
    """Initialize application"""
    with app.app_context():
        try:
            db.create_all()
            logger.info("✅ Base tables created")

            run_migrations()
            ensure_upload_folders()
            create_admin_user()
            init_sticker_packs()

            logger.info("🎉 App initialization completed!")

        except Exception as e:
            logger.error(f"❌ Init error: {e}")


# ──────────────────────────────────────────────────────────────────────────────
#  Run App
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_app()

    port = int(os.environ.get("PORT", 5000))

    print("\n" + "=" * 70)
    print("🚀 KILDEAR SOCIAL NETWORK STARTING")
    print("=" * 70)
    print(f"🌐 Port: {port}")
    print(f"📁 Upload folder: {app.config['UPLOAD_FOLDER']}")
    print(f"🎨 Preset avatars: 10")
    print(f"🖼️ Preset covers: 5")
    print(f"🐍 Python: {platform.python_version()}")
    print(f"🖥️ Platform: {platform.system()}")
    print(f"🎯 Mode: {'PRODUCTION' if is_production else 'DEVELOPMENT'}")
    print("=" * 70)
    print("📝 Press Ctrl+C to stop")
    print("=" * 70 + "\n")

    if is_production:
        socketio.run(app, host="0.0.0.0", port=port)
    else:
        socketio.run(app, debug=True, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)