from flask import render_template, redirect, url_for, flash, request, Blueprint
from app import app, db
from app.models import User, Flashcard
from app.forms import LoginForm, RegisterForm, FlashcardForm
from flask_login import current_user, login_user, logout_user, login_required
import sqlalchemy as sa
from datetime import datetime, timedelta, timezone

from fsrs import Scheduler, Card, Rating


flashcards_bp = Blueprint('flashcards', __name__)

##edit test
##edit test
##edit test
##edit test
##edit test

#push test 2


scheduler = Scheduler()

@app.route('/flashcards', methods=['GET', 'POST'])
@login_required
def flashcards():

    flashcard = Flashcard.query.filter(
        Flashcard.user_id == current_user.id,
        Flashcard.due_date <= datetime.now(timezone.utc)
    ).order_by(Flashcard.due_date).first()


    total_due = Flashcard.query.filter(
        Flashcard.user_id == current_user.id,
        Flashcard.due_date <= datetime.now(timezone.utc)
    ).count()

    if not flashcard:

        return render_template('flashcards.html', flashcard=None, total_due=0, show_answer=False)

    if request.method == 'POST':
        if request.form.get('action') == 'show':
            return render_template('flashcards.html', flashcard=flashcard, total_due=total_due, show_answer=True)

        rating_str = request.form.get('rating')
        rating_map = {
            'again': Rating.Again,
            'good': Rating.Good
        }
        rating = rating_map.get(rating_str)

        if rating is None:
            flash('Invalid rating.', 'danger')
            return redirect(url_for('flashcards'))

        #build fsrs card, check here
        fsrs_card = Card()

        updated_card, review_log = scheduler.review_card(fsrs_card, rating)
        flashcard.due_date = updated_card.due
        flashcard.last_review = datetime.now(timezone.utc)
        db.session.commit()

        flash(f"Card updated! Next due: {flashcard.due_date}", 'success')
        return redirect(url_for('flashcards'))


    return render_template('flashcards.html', flashcard=flashcard, total_due=total_due, show_answer=False)


@app.route('/add_flashcard', methods=['GET', 'POST'])
@login_required
def add_flashcard():
    form = FlashcardForm()
    if form.validate_on_submit():
        new_card = Flashcard(
            user_id=current_user.id,
            front=form.front.data,
            back=form.meaning.data,
            reading=form.reading.data,
            meaning=form.meaning.data,
            sentence=form.sentence.data,
            due_date=datetime.now(timezone.utc)
        )
        db.session.add(new_card)
        db.session.commit()
        flash('Flashcard added!', 'success')
        return redirect(url_for('flashcards'))
    return render_template('add_flashcard.html', form=form)

@app.route('/browse')
@login_required
def browse_flashcards():
    user_cards = Flashcard.query.filter_by(user_id=current_user.id).all()
    return render_template('browse_flashcards.html', flashcards=user_cards)


















@app.route("/")
def home():
    return render_template('home.html', title="Home")

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", title="Dashboard", user=current_user)






@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            sa.select(User).where(User.username == form.username.data))
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password', 'danger')
            return redirect(url_for('login'))
        user.last_login_at = datetime.utcnow()
        db.session.commit()
        login_user(user, remember=form.remember_me.data)
        return redirect(url_for('dashboard'))
    return render_template('generic_form.html', title='Sign In', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = RegisterForm()
    if form.validate_on_submit():
        new_user = User(username=form.username.data, email=form.email.data)
        new_user.set_password(form.password.data)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('home'))
    return render_template('generic_form.html', title='Register', form=form)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))

