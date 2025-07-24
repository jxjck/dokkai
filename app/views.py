import os

from flask import render_template, redirect, url_for, flash, request, Blueprint, Response, send_from_directory
from app import app, db
from app.models import User, Flashcard
from app.forms import LoginForm, RegisterForm, FlashcardForm
from flask_login import current_user, login_user, logout_user, login_required
import sqlalchemy as sa
from datetime import datetime, timedelta, timezone
import csv
from io import StringIO

from fsrs import Scheduler, Card, Rating

from werkzeug.utils import secure_filename


flashcards_bp = Blueprint('flashcards', __name__)


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

# maybe change this later, not sure how to handle
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/upload_profile_image', methods=['POST'])
@login_required
def upload_profile_image():
    file = request.files.get('profile_image')
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        upload_path = os.path.join(app.root_path, 'data', 'uploads', filename)
        os.makedirs(os.path.dirname(upload_path), exist_ok=True)  # make sure the dir exists
        file.save(upload_path)

        current_user.profile_picture = filename
        db.session.commit()

    return redirect(url_for('dashboard'))


# route 4 uploaded profile pictures
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(os.path.join(app.root_path, 'data', 'uploads'), filename)













@app.route("/")
def home():
    return render_template('home.html', title="Home")



# dashboard route
@app.route('/dashboard')
@login_required
def dashboard():
    # get full user object from database to avoid LocalProxy issues
    user = User.query.get(current_user.id)

    # calculate stats
    flashcard_count = Flashcard.query.filter_by(user_id=user.id).count()
    if user.last_login_at:
        days_active = (datetime.utcnow().date() - user.last_login_at.date()).days + 1
    else:
        days_active = 1

    return render_template(
        'dashboard.html',
        user=user,
        flashcard_count=flashcard_count,
        days_active=days_active
    )





# exporting flashcards (currently as csv, look at .apkg (anki) and maybe .txt too)
@app.route("/export_flashcards")
@login_required
def export_flashcards():
    # get cards for current user
    flashcards = Flashcard.query.filter_by(user_id=current_user.id).all()

    # create in-memory csv
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["Front", "Back", "Reading", "Meaning", "Sentence", "Due Date"])

    # write each flashcard row to the csv
    for card in flashcards:
        writer.writerow([
            card.front,
            card.back,
            card.reading,
            card.meaning,
            card.sentence,
            card.due_date.strftime("%Y-%m-%d %H:%M")
        ])

    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=dokkai_flashcards.csv"}
    )







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

