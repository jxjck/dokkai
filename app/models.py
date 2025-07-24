from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so
from flask_login import UserMixin
from sqlalchemy import ForeignKey
from sqlalchemy.orm import mapped_column, relationship
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login
from dataclasses import dataclass
from datetime import datetime
import os



@login.user_loader
def load_user(id):
    return db.session.get(User, int(id))

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True)
    email = db.Column(db.String(120), index=True, unique=True)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(10), default="Normal")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, default=None)

    flashcards = db.relationship('Flashcard', backref='user', lazy='dynamic')


    # wk4 store filename for user's profile picture
    profile_picture = db.Column(db.String(255), nullable=True)




    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Flashcard(db.Model):
    __tablename__ = 'flashcards'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    front = db.Column(db.String(255), nullable=False)
    back = db.Column(db.String(255), nullable=False)
    reading = db.Column(db.String(255))
    meaning = db.Column(db.String(255))
    sentence = db.Column(db.String(500))

    repetition = db.Column(db.Integer, default=0)
    interval = db.Column(db.Integer, default=1)
    ease_factor = db.Column(db.Float, default=2.5)
    stability = db.Column(db.Float, default=4.0)
    difficulty = db.Column(db.Float, default=3.0)
    lapses = db.Column(db.Integer, default=0)
    due_date = db.Column(db.DateTime, default=datetime.utcnow)
    last_review = db.Column(db.DateTime, default=None)

    def __repr__(self):
        return f"<Flashcard {self.front} - {self.back} (due {self.due_date})>"
