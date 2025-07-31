import os
import re
import uuid

from flask import render_template, redirect, url_for, flash, request, Blueprint, Response, send_from_directory, session
from app import app, db
from app.models import User, Flashcard, Activity
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


def log_activity(message):
    if current_user.is_authenticated:
        activity = Activity(user_id=current_user.id, message=message, timestamp=datetime.utcnow())
        db.session.add(activity)
        db.session.commit()





@app.route('/flashcards', methods=['GET', 'POST'])
@login_required
def flashcards():
    now = datetime.now(timezone.utc)

    # card due now
    flashcard = Flashcard.query.filter(
        Flashcard.user_id == current_user.id,
        Flashcard.due_date <= now
    ).order_by(Flashcard.due_date).first()

    # if none due
    if not flashcard:
        soon = now + timedelta(minutes=1)
        flashcard = Flashcard.query.filter(
            Flashcard.user_id == current_user.id,
            Flashcard.due_date <= soon
        ).order_by(Flashcard.due_date).first()

    # count due cards
    total_due = Flashcard.query.filter(
        Flashcard.user_id == current_user.id,
        Flashcard.due_date <= now
    ).count()

    # log only once per day
    if not flashcard:


        last_completion = db.session.query(sa.func.max(Activity.timestamp)).filter(
            Activity.user_id == current_user.id,
            Activity.message.like("Completed all due flashcards%")
        ).scalar()

        if not last_completion or last_completion.date() < now.date():
            # xp calculation logic
            cards_reviewed = session.pop('cards_reviewed', 0)
            session.pop('xp_earned', None)
            xp_earned = cards_reviewed * 10
            current_user.xp += xp_earned

            msg = f"Completed all due flashcards and earned {xp_earned} XP ✨" if xp_earned > 0 else "Completed all due flashcards"
            db.session.add(Activity(
                user_id=current_user.id,
                message=msg,
                timestamp=now
            ))

            # streak
            recent_days = db.session.query(Activity.timestamp).filter(
                Activity.user_id == current_user.id,
                Activity.message.like("Completed all due flashcards%")
            ).order_by(Activity.timestamp.desc()).limit(5).all()

            streak_days = sorted({ts.date() for (ts,) in recent_days}, reverse=True)
            today = now.date()

            if (
                today in streak_days and
                (today - timedelta(days=1)) in streak_days and
                (today - timedelta(days=2)) in streak_days
            ):
                db.session.add(Activity(
                    user_id=current_user.id,
                    message="Hit a 3-day flashcard streak! 🔥",
                    timestamp=now
                ))

            db.session.commit()

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

        # track xp
        cards_reviewed = session.get('cards_reviewed', 0)
        cards_reviewed += 1
        session['cards_reviewed'] = cards_reviewed

        # fsrs update
        fsrs_card = Card()
        updated_card, review_log = scheduler.review_card(fsrs_card, rating)
        flashcard.due_date = updated_card.due
        flashcard.last_review = now

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

        # log
        db.session.add(Activity(
            user_id=current_user.id,
            message="Added a new flashcard ✅",
            timestamp=datetime.utcnow()
        ))
        db.session.commit()

        flash("Flashcard added successfully.", "success")
        return redirect(url_for('add_flashcard'))

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
    if not file or file.filename == '':
        flash('No file selected.', 'danger')
        return redirect(url_for('dashboard'))

    if not file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
        flash('Invalid file type. Only images are allowed.', 'danger')
        return redirect(url_for('dashboard'))

    # gen unique filename
    filename = f"{uuid.uuid4().hex}_{file.filename}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    # delete old
    if current_user.profile_picture:
        old_path = os.path.join(app.config['UPLOAD_FOLDER'], current_user.profile_picture)
        if os.path.exists(old_path):
            os.remove(old_path)

    # update database
    current_user.profile_picture = filename
    db.session.commit()

    # log activity to feed
    activity = Activity(
        user_id=current_user.id,
        message="Uploaded new profile picture 🖼️"
    )
    db.session.add(activity)
    db.session.commit()

    flash('Profile picture updated!', 'success')
    return redirect(url_for('dashboard'))



# route 4 uploaded profile pictures
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(os.path.join(app.root_path, 'data', 'uploads'), filename)



#grammar page (started 25th jul)
@app.route('/grammar')
@login_required
def grammar():
    return render_template('grammar.html')


#in development - adding card from grammar explanation
@app.route('/add_grammar_card', methods=['POST'])
@login_required
def add_grammar_card():
    front = request.form.get('front', '').strip()
    reading = request.form.get('reading', '').strip()
    meaning = request.form.get('meaning', '').strip()
    raw_sentence = request.form.get('sentence', '')

    # extract clean sentence
    split_sentence = re.split(r'[。！？]', raw_sentence)
    base_sentence = split_sentence[0] + "。" if split_sentence else ""
    sentence_cleaned = re.sub(r'(?!<mark>|</mark>)(<[^>]*>)', '', base_sentence)
    sentence = sentence_cleaned.strip()

    back = request.form.get('back', '').strip()

    new_card = Flashcard(
        user_id=current_user.id,
        front=front,
        back=back,
        reading=reading,
        meaning=meaning,
        sentence=sentence,
        is_grammar=True
    )

    db.session.add(new_card)
    db.session.commit()

    # log
    db.session.add(Activity(
        user_id=current_user.id,
        message="Added a grammar flashcard 📚",
        timestamp=datetime.utcnow()
    ))
    db.session.commit()

    flash('Grammar flashcard added!', 'success')
    return redirect(url_for('grammar'))




#####editing and deleting cards on the browse cards page############
# edit a flashcard
@app.route("/edit/<int:card_id>", methods=["GET", "POST"])
@login_required
def edit_flashcard(card_id):
    card = Flashcard.query.get_or_404(card_id)
    if card.user_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("browse_flashcards"))

    form = FlashcardForm(obj=card)
    if form.validate_on_submit():
        card.front = form.front.data
        card.reading = form.reading.data
        card.meaning = form.meaning.data
        card.sentence = form.sentence.data
        db.session.commit()
        flash("Card updated!", "success")
        return redirect(url_for("browse_flashcards"))

    return render_template("edit_flashcard.html", form=form, card=card)


# delete card
@app.route("/delete/<int:card_id>", methods=["POST"])
@login_required
def delete_flashcard(card_id):
    card = Flashcard.query.get_or_404(card_id)
    if card.user_id != current_user.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("browse_flashcards"))

    db.session.delete(card)
    db.session.commit()
    flash("Card deleted.", "success")
    return redirect(url_for("browse_flashcards"))













#leaderboard page
@app.route('/leaderboard')
@login_required
def leaderboard():
    # get users and flashcard count
    results = db.session.query(
        User,
        sa.func.count(Flashcard.id).label('card_count')
    ).outerjoin(Flashcard).group_by(User.id).order_by(sa.desc('card_count')).all()

    # list w rank info (check over)
    leaderboard_data = [(user, count, idx + 1) for idx, (user, count) in enumerate(results)]

    return render_template('leaderboard.html', leaderboard=leaderboard_data)








@app.route("/")
def home():
    return render_template('home.html', title="Home")



# dashboard route
@app.route('/dashboard')
@login_required
def dashboard():
    from app.models import Flashcard, Activity

    user_id = current_user.id
    flashcard_count = Flashcard.query.filter_by(user_id=user_id).count()

    # days active
    first_activity = db.session.query(sa.func.min(Flashcard.last_review)).filter_by(user_id=user_id).scalar()
    days_active = (datetime.utcnow().date() - first_activity.date()).days + 1 if first_activity else 0

    # get last 10 activities
    recent_activities = Activity.query.filter_by(user_id=user_id).order_by(Activity.timestamp.desc()).limit(10).all()

    # calculate XP and level
    xp = sum(10 for a in recent_activities if "earned 10 XP" in a.message)
    level = xp // 100
    xp_to_next = 100 - (xp % 100)

    return render_template(
        'dashboard.html',
        user=current_user,
        flashcard_count=flashcard_count,
        days_active=days_active,
        recent_activities=recent_activities,
        xp=xp,
        level=level,
        xp_to_next=xp_to_next,
        badges=[]  # we'll fill this in later
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

        #added default profile picture
        new_user = User(
            username=form.username.data,
            email=form.email.data,
            profile_picture="default_avatar.png"
        )

        new_user.set_password(form.password.data)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('home'))
    return render_template('generic_form.html', title='Register', form=form)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))

