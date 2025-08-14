import os
import re
import uuid

from flask import render_template, redirect, url_for, flash, request, Blueprint, Response, send_from_directory, session, jsonify
from sqlalchemy import func


from app import app, db
from app.models import User, Flashcard, Activity, Deck
from app.forms import LoginForm, RegisterForm, FlashcardForm
from flask_login import current_user, login_user, logout_user, login_required
import sqlalchemy as sa
from datetime import datetime, timedelta, timezone, date
import csv
from io import StringIO

from fsrs import Scheduler, Card, Rating

from werkzeug.utils import secure_filename

from app.premade_decks import days_of_week_deck

from app.premade_decks import premade_decks

import random

from .kana_dict import kana_data


#note to self- remove redundant imports @ some point

#ai assisstant thing
import os
from dotenv import load_dotenv
import openai

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")



flashcards_bp = Blueprint('flashcards', __name__)


scheduler = Scheduler()


def log_activity(message):
    if current_user.is_authenticated:
        activity = Activity(user_id=current_user.id, message=message, timestamp=datetime.utcnow())
        db.session.add(activity)
        db.session.commit()



###aug9
@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/how-to-use')
def how_to_use():
    return render_template('how_to_use.html')





@app.route('/kana', methods=['GET', 'POST'])
@login_required
def kana_guesser():
    result = None
    kana_char = ''
    correct_romaji = ''
    kana_pool = []

    selected_groups = request.form.getlist("selected_groups")
    #default select
    if request.method == 'GET':
        if 'kana_correct_count' not in session:
            session['kana_correct_count'] = 0
        if not selected_groups:
            selected_groups = ["h_a"]
    #toggle
    toggled_group = request.form.get("group")
    if toggled_group:
        if toggled_group in selected_groups:
            selected_groups.remove(toggled_group)
        else:
            selected_groups.append(toggled_group)
    #building kana groups fix
    for group in selected_groups:
        if group == "hiragana_combo":
            kana_pool += kana_data["hiragana_combinations"]
        elif group == "katakana_combo":
            kana_pool += kana_data["katakana_combinations"]
        elif group.startswith("h_"):
            kana_pool += kana_data["hiragana"].get(group[2:], [])
        elif group.startswith("k_"):
            kana_pool += kana_data["katakana"].get(group[2:], [])

    if not kana_pool:
        kana_pool = kana_data["hiragana"].get("a", [])

    #answer submission
    if request.method == "POST" and "user_input" in request.form:
        user_input = request.form.get("user_input", "").strip().lower()
        prev_kana = request.form.get("prev_kana")
        prev_romaji = request.form.get("prev_romaji")
        if user_input == prev_romaji:
            result = "Correct!"
            session["kana_correct_count"] = session.get("kana_correct_count", 0) + 1

            #updating the streak
            if session["kana_correct_count"] > current_user.kana_streak:
                current_user.kana_streak = session["kana_correct_count"]
                db.session.commit()
        else:
            result = f"Incorrect. The answer was '{prev_romaji}'."
            session["kana_correct_count"] = 0  # Reset on wrong answer

    #choose next かna :-)
    kana = random.choice(kana_pool)
    kana_char = kana["kana"]
    correct_romaji = kana["romaji"]

    def build_group_list(kana_dict, prefix):
        groups = []
        for key, kana_list in kana_dict.items():
            label = "".join(k["kana"] for k in kana_list)
            romaji = ", ".join(k["romaji"] for k in kana_list)
            groups.append({"label": label, "romaji": romaji, "value": f"{prefix}_{key}"})
        return groups

    hiragana_groups = build_group_list(kana_data["hiragana"], "h")
    katakana_groups = build_group_list(kana_data["katakana"], "k")

    return render_template(
        "kana_guesser.html",
        kana=kana_char,
        result=result,
        correct_romaji=correct_romaji,
        selected_groups=selected_groups,
        hiragana_groups=hiragana_groups,
        katakana_groups=katakana_groups
    )






@app.route('/flashcards', methods=['GET', 'POST'])
@login_required
def flashcards():
    now = datetime.now(timezone.utc)

    # --- daily new-card quota state ---
    new_limit = current_user.new_cards_per_day or 10
    reviewed_new_ids = session.get('reviewed_new_card_ids', [])
    today_key = now.date().isoformat()
    if session.get('new_quota_date') != today_key:
        session['new_quota_date'] = today_key
        reviewed_new_ids = []
        session['reviewed_new_card_ids'] = reviewed_new_ids

    # --- counts for UI ---
    new_available = Flashcard.query.filter(
        Flashcard.user_id == current_user.id,
        Flashcard.repetition == 0
    ).count()

    review_due = Flashcard.query.filter(
        Flashcard.user_id == current_user.id,
        Flashcard.repetition > 1,
        Flashcard.due_date <= now
    ).count()

    # learning = any card still in learning/relearn steps (stable green number)
    learning_total = Flashcard.query.filter(
        Flashcard.user_id == current_user.id,
        Flashcard.learning_step_index.isnot(None)
    ).count()

    combined_due = review_due + learning_total

    # new due today (respect quota)
    new_due_all = Flashcard.query.filter(
        Flashcard.user_id == current_user.id,
        Flashcard.repetition == 0,
        ~Flashcard.id.in_(reviewed_new_ids)
    ).count()
    new_quota_left = max(0, new_limit - len(reviewed_new_ids))
    new_due_today = min(new_due_all, new_quota_left)

    total_due = review_due + new_due_today

    # ---------- POST FIRST: lock to submitted card_id ----------
    if request.method == 'POST':
        card_id = request.form.get('card_id', type=int)
        action = request.form.get('action')
        rating_str = request.form.get('rating')

        if not card_id:
            return redirect(url_for('flashcards'))

        flashcard = Flashcard.query.filter(
            Flashcard.id == card_id,
            Flashcard.user_id == current_user.id
        ).first()
        if not flashcard:
            return redirect(url_for('flashcards'))

        # 1) Just flip and show the back of THIS card
        if action == 'show':
            return render_template(
                'flashcards.html',
                flashcard=flashcard,
                total_due=total_due,
                new_due=new_due_today,
                review_due=review_due,
                learning_due=learning_total,
                combined_due=combined_due,
                new_available=new_available,
                show_answer=True
            )

        # 2) Rating on THIS card
        if rating_str:
            rating_map = {'again': Rating.Again, 'good': Rating.Good}
            rating = rating_map.get(rating_str)
            if rating is None:
                flash('Invalid rating.', 'danger')
                return redirect(url_for('flashcards'))

            session['cards_reviewed'] = session.get('cards_reviewed', 0) + 1

            # FSRS baseline (we still override due for learning/relearn steps below)
            fsrs_card = Card()
            updated_card, _ = scheduler.review_card(fsrs_card, rating)
            flashcard.last_review = now
            flashcard.due_date = updated_card.due

            # Step plans (Anki-like)
            NEW_STEPS = [1, 5, 30]   # minutes
            RELEARN_STEPS = [2, 5]
            def due_in_minutes(m): return now + timedelta(minutes=m)

            step = flashcard.learning_step_index

            if flashcard.repetition == 0:
                # first-time seen -> enter learning step 0
                if flashcard.id not in reviewed_new_ids:
                    reviewed_new_ids.append(flashcard.id)
                    session['reviewed_new_card_ids'] = reviewed_new_ids
                flashcard.repetition = 1
                flashcard.learning_step_index = 0
                flashcard.due_date = due_in_minutes(NEW_STEPS[0])

            elif flashcard.repetition == 1:
                is_relearn = flashcard.is_lapsed_learning
                if is_relearn:
                    idx = step or 0
                    if rating == Rating.Good:
                        if idx < len(RELEARN_STEPS) - 1:
                            idx += 1
                            flashcard.learning_step_index = idx
                            flashcard.due_date = due_in_minutes(RELEARN_STEPS[idx])
                        else:
                            # graduate from relearn
                            flashcard.repetition = 2
                            flashcard.learning_step_index = None
                            flashcard.is_lapsed_learning = False
                    else:
                        # again -> restart relearn
                        flashcard.learning_step_index = 0
                        flashcard.due_date = due_in_minutes(RELEARN_STEPS[0])
                else:
                    idx = step or 0
                    if rating == Rating.Good:
                        if idx < len(NEW_STEPS) - 1:
                            idx += 1
                            flashcard.learning_step_index = idx
                            flashcard.due_date = due_in_minutes(NEW_STEPS[idx])
                        else:
                            # graduate new -> enter review
                            flashcard.repetition = 2
                            flashcard.learning_step_index = None
                    else:
                        # again -> back to step 0
                        flashcard.learning_step_index = 0
                        flashcard.due_date = due_in_minutes(NEW_STEPS[0])

            else:
                # review card
                if rating == Rating.Again:
                    flashcard.lapses = (flashcard.lapses or 0) + 1
                    flashcard.repetition = 1
                    flashcard.is_lapsed_learning = True
                    flashcard.learning_step_index = 0
                    flashcard.due_date = due_in_minutes(RELEARN_STEPS[0])
                else:
                    flashcard.learning_step_index = None  # stays in review

            db.session.commit()
            flash(f"Card updated! Next due: {flashcard.due_date}", 'success')
            return redirect(url_for('flashcards'))

        # Unknown POST
        return redirect(url_for('flashcards'))

    # ---------- GET: choose next card ----------
    last_card_id = session.get('last_card_id')

    def pick_first_other(q, order_clause):
        if last_card_id:
            alt = q.filter(Flashcard.id != last_card_id).order_by(order_clause).first()
            if alt:
                return alt
        return q.order_by(order_clause).first()

    # 1) review due now
    review_q = Flashcard.query.filter(
        Flashcard.user_id == current_user.id,
        Flashcard.repetition > 1,
        Flashcard.due_date <= now
    )
    review_card = pick_first_other(review_q, Flashcard.due_date)

    # 2) learning due now
    learning_due_q = Flashcard.query.filter(
        Flashcard.user_id == current_user.id,
        Flashcard.repetition == 1,
        Flashcard.due_date <= now
    )
    learning_due_card = pick_first_other(learning_due_q, Flashcard.due_date)

    # 3) new (quota)
    new_card = None
    if new_quota_left > 0:
        new_q = Flashcard.query.filter(
            Flashcard.user_id == current_user.id,
            Flashcard.repetition == 0,
            ~Flashcard.id.in_(reviewed_new_ids)
        )
        new_card = pick_first_other(new_q, Flashcard.id)

    flashcard = review_card or learning_due_card or new_card

    # 4) nothing due? show soonest learning even if not due (ignore mini timers)
    if not flashcard and review_due == 0 and new_due_today == 0:
        learning_any_q = Flashcard.query.filter(
            Flashcard.user_id == current_user.id,
            Flashcard.repetition == 1
        )
        flashcard = pick_first_other(learning_any_q, Flashcard.due_date)

    # 5) still nothing? peek ahead 1 minute
    if not flashcard:
        soon = now + timedelta(minutes=1)
        peek_q = Flashcard.query.filter(
            Flashcard.user_id == current_user.id,
            Flashcard.due_date <= soon
        )
        flashcard = pick_first_other(peek_q, Flashcard.due_date)

    if not flashcard:
        # completion logging (once per day)
        last_completion = db.session.query(sa.func.max(Activity.timestamp)).filter(
            Activity.user_id == current_user.id,
            Activity.message.like("Completed all due flashcards%")
        ).scalar()
        if not last_completion or last_completion.date() < now.date():
            cards_reviewed = session.pop('cards_reviewed', 0)
            session.pop('xp_earned', None)
            xp_earned = cards_reviewed * 10
            current_user.xp += xp_earned
            msg = (f"Completed all due flashcards and earned {xp_earned} XP ✨"
                   if xp_earned > 0 else "Completed all due flashcards")
            db.session.add(Activity(user_id=current_user.id, message=msg, timestamp=now))
            recent_days = db.session.query(Activity.timestamp).filter(
                Activity.user_id == current_user.id,
                Activity.message.like("Completed all due flashcards%")
            ).order_by(Activity.timestamp.desc()).limit(5).all()
            streak_days = sorted({ts.date() for (ts,) in recent_days}, reverse=True)
            today = now.date()
            if (today in streak_days and
                (today - timedelta(days=1)) in streak_days and
                (today - timedelta(days=2)) in streak_days):
                db.session.add(Activity(
                    user_id=current_user.id,
                    message="Hit a 3-day flashcard streak! 🔥",
                    timestamp=now
                ))
            db.session.commit()

        session['last_card_id'] = None
        return render_template(
            'flashcards.html',
            flashcard=None,
            total_due=0,
            new_due=new_due_today,
            review_due=review_due,
            learning_due=learning_total,
            combined_due=combined_due,
            new_available=new_available,
            show_answer=False
        )

    # remember which we chose (for anti-repeat)
    session['last_card_id'] = flashcard.id

    return render_template(
        'flashcards.html',
        flashcard=flashcard,
        total_due=total_due,
        new_due=new_due_today,
        review_due=review_due,
        learning_due=learning_total,
        combined_due=combined_due,
        new_available=new_available,
        show_answer=False
    )






#for new cards per day
@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    new_limit = request.form.get('new_cards_per_day', type=int)
    if new_limit is not None and new_limit >= 0:
        current_user.new_cards_per_day = new_limit
        db.session.commit()
        flash('New card limit updated.', 'success')
    else:
        flash('Invalid input.', 'danger')
    return redirect(url_for('flashcards'))





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
            message="Added a new flashcard!",
            timestamp=datetime.utcnow()
        ))
        db.session.commit()

        flash("Flashcard added successfully.", "success")
        return redirect(url_for('add_flashcard'))

    return render_template('add_flashcard.html', form=form)





#move up later##


@app.route('/grammar_assistant', methods=['POST'])
@login_required
def grammar_assistant():
    ##move up later after tests##
    import os, re, json
    from flask import jsonify, request

    data = request.get_json(silent=True) or {}
    user_msg = (data.get('message') or '').strip()
    lesson_title = (data.get('lesson_title') or '').strip()
    lesson_context = (data.get('lesson_context') or '').strip()

    if not user_msg:
        return jsonify({"error": "Ask me for an example (e.g., 'て-form please')."}), 400

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return jsonify({"error": "Server is missing OPENAI_API_KEY."}), 500

    system = (
        "You are a Japanese grammar assistant inside a flashcard app. "
        "Given a CURRENT LESSON title + short lesson text + a user request, "
        "return ONE concise example in STRICT JSON (no prose) with schema:\n"
        "{"
        '  \"focus_token\": \"string (e.g., だ, です, へ, に, ます, でした)\",'
        '  \"jp_sentence\": \"string (one natural sentence, end with 。 or ！)\",'
        '  \"en_sentence\": \"string (short one-line gloss, end with .)\",'
        '  \"meaning_label\": \"string (e.g., Copula (polite) / Particle (direction) / Verb (irregular polite))\",'
        '  \"short_explanation\": \"string (1 short line explaining the grammar use)\"'
        "}\n"
        "Rules: Use vocabulary/grammar consistent with the lesson. Keep it N5/N4 and short. "
        "Prefer forms highlighted in the lesson (e.g., でした for polite past)."
    )
    user = {
        "lesson_title": lesson_title,
        "lesson_context": lesson_context[:1800],
        "request": user_msg
    }

    try:
        import openai
        openai.api_key = api_key

        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            temperature=0.6,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)}
            ],
            max_tokens=500
        )
        raw = (resp.choices[0].message["content"] or "").strip()
    except Exception as e:
        return jsonify({"error": f"AI error: {e}"}), 500

    try:
        j = json.loads(raw)
        focus = (j.get("focus_token") or "").strip()
        jp = (j.get("jp_sentence") or "").strip()
        en = (j.get("en_sentence") or "").strip()
        meaning_label = (j.get("meaning_label") or "").strip()
        short_expl = (j.get("short_explanation") or "").strip()
    except Exception:
        return jsonify({"error": "Malformed AI reply. Please try again."}), 502

    if not jp or not en:
        return jsonify({"error": "Couldn’t craft an example. Try rephrasing."}), 422

    if not re.search(r"[。！？]$", jp):
        jp += "。"
    if not re.search(r"[.!?]$", en):
        en += "."

    focus_display = focus if focus else (lesson_title.split(":")[-1].strip() or "文法")
    front = f"{focus_display}<br>{jp}"

    jp_marked = jp.replace(focus, f"<mark>{focus}</mark>", 1) if focus else jp
    sentence_for_db = f"{jp_marked} {en}"

    back = short_expl or f"Example using {focus_display}."
    reading = ""
    meaning = meaning_label or "Grammar"

    card = {
        "front": front,
        "back": back,
        "reading": reading,
        "meaning": meaning,
        "sentence": sentence_for_db,
        "jp": jp,
        "en": en,
        "focus": focus_display
    }

    reply = f"{jp}\n{en}\n\n{short_expl}" if short_expl else f"{jp}\n{en}"
    return jsonify({"reply": reply, "card": card})














@app.route("/browse_decks")
@login_required
def browse_decks():
    return render_template("browse_decks.html", decks=premade_decks.values())

@app.route("/preview_premade_deck/<deck_name>")
@login_required
def preview_premade_deck(deck_name):
    deck = premade_decks.get(deck_name)
    if not deck:
        flash("Deck not found.", "danger")
        return redirect(url_for("browse_decks"))
    return render_template("preview_deck.html", deck=deck)


@app.route("/import_premade_deck", methods=["POST"])
@login_required
def import_premade_deck():
    deck_name = request.form.get("deck_name")
    deck = premade_decks.get(deck_name)
    if not deck:
        flash("Deck not found.", "danger")
        return redirect(url_for("browse_decks"))

    for card in deck["cards"]:
        flashcard = Flashcard(
            user_id=current_user.id,
            front=card["front"],
            back=card["back"],
            reading=card.get("reading", ""),
            meaning=card.get("meaning", ""),
            sentence=card.get("sentence", ""),
        )
        db.session.add(flashcard)

    db.session.commit()
    flash(f"{deck_name} deck imported!", "success")
    return redirect(url_for("browse_flashcards"))




@app.route('/import_deck/<int:deck_id>', methods=['POST'])
@login_required
def import_deck(deck_id):
    original = Deck.query.get_or_404(deck_id)
    if original.user_id is not None:
        flash("You can only import pre-made decks.", "warning")
        return redirect(url_for('browse_decks'))

    #create new deck for user
    user_deck = Deck(name=original.name, description=original.description, user_id=current_user.id)
    db.session.add(user_deck)
    db.session.commit()

    #copy cards
    for card in original.flashcards:
        copy = Flashcard(
            user_id=current_user.id,
            front=card.front,
            back=card.back,
            reading=card.reading,
            meaning=card.meaning,
            sentence=card.sentence,
            due_date=datetime.utcnow(),
            deck_id=user_deck.id
        )
        db.session.add(copy)

    db.session.commit()
    flash(f"Imported deck: {original.name}", "success")
    return redirect(url_for('flashcards'))














@app.route('/browse')
@login_required
def browse_flashcards():
    user_cards = Flashcard.query.filter_by(user_id=current_user.id).all()
    return render_template('browse_flashcards.html', flashcards=user_cards)

#note to self### ~ maybe change this later, not sure how to handle with proper practices
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

    #gen unique filenme
    filename = f"{uuid.uuid4().hex}_{file.filename}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    #del old
    if current_user.profile_picture:
        old_path = os.path.join(app.config['UPLOAD_FOLDER'], current_user.profile_picture)
        if os.path.exists(old_path):
            os.remove(old_path)
    #update db
    current_user.profile_picture = filename
    db.session.commit()
    #log
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


#adding card from grammar explanation
@app.route('/add_grammar_card', methods=['POST'])
@login_required
def add_grammar_card():
    front = request.form.get('front', '').strip()
    reading = request.form.get('reading', '').strip()
    meaning = request.form.get('meaning', '').strip()
    raw_sentence = request.form.get('sentence', '')

    #extract clean sentence
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

    #log logic
    db.session.add(Activity(
        user_id=current_user.id,
        message="Added a grammar flashcard 📚",
        timestamp=datetime.utcnow()
    ))
    db.session.commit()

    flash('Grammar flashcard added!', 'success')
    return redirect(url_for('grammar'))




#####editing and deleting cards on the browse cards page############
#edit cardz
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


#delete  a card from db
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
    card_count = sa.func.count(Flashcard.id).label('card_count')

    #get user and card count
    results = db.session.query(
        User,
        card_count
    ).outerjoin(Flashcard).group_by(User.id).all()

    #sort users in Python by level and then flashcard count
    sorted_results = sorted(results, key=lambda item: (item[0].level, item[1]), reverse=True)

    #rank thing
    leaderboard_data = [
        (user, count, idx + 1, user.level)
        for idx, (user, count) in enumerate(sorted_results)
    ]

    return render_template('leaderboard.html', leaderboard=leaderboard_data)



#public profile thing on leaderboard
@app.route('/user/<username>')
def public_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    flashcard_count = Flashcard.query.filter_by(user_id=user.id).count()

    activities = []
    if user.show_activity_public:
        activities = Activity.query.filter_by(user_id=user.id).order_by(Activity.timestamp.desc()).limit(10).all()

    return render_template('public_profile.html',
                           user=user,
                           flashcard_count=flashcard_count,
                           activities=activities)



@app.route('/toggle_public_activity', methods=['POST'])
@login_required
def toggle_public_activity():
    show = request.form.get('show_activity_public') == 'on'
    current_user.show_activity_public = show
    db.session.commit()
    flash("Public profile setting updated.", "success")
    return redirect(url_for('dashboard'))





@app.route("/")
def home():
    if current_user.is_authenticated:
        today = date.today()
        last_week = today - timedelta(days=6)

        reviewed_counts = db.session.query(
            func.date(Flashcard.last_review),
            func.count()
        ).filter(
            Flashcard.user_id == current_user.id,
            Flashcard.last_review != None,
            Flashcard.last_review >= last_week
        ).group_by(func.date(Flashcard.last_review)).all()

        date_labels = [(today - timedelta(days=i)).isoformat() for i in reversed(range(7))]
        data_dict = {d: 0 for d in date_labels}
        for d, count in reviewed_counts:
            data_dict[d] = count

        #count duecards
        now = datetime.utcnow()
        due_count = Flashcard.query.filter(
            Flashcard.user_id == current_user.id,
            Flashcard.due_date <= now
        ).count()

        return render_template("home.html", title="Home", card_data=data_dict, due_count=due_count)

    return render_template("home.html", title="Home")





#dashboard route
@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user

    flashcard_count = Flashcard.query.filter_by(user_id=user.id).count()

    #track unique days user has completed all flashcards
    unique_days = db.session.query(func.date(Activity.timestamp)).filter(
        Activity.user_id == user.id,
        Activity.message.like("Completed all due flashcards%")
    ).distinct().count()

    #recent activity
    recent_activities = Activity.query.filter_by(user_id=user.id).order_by(
        Activity.timestamp.desc()).limit(5).all()

    #xp and level
    xp = user.xp
    level = int((xp / 100) ** 0.5)
    xp_for_next = ((level + 1) ** 2) * 100
    xp_to_next = xp_for_next - xp

    # todays cards
    today = date.today()
    reviewed_today = Flashcard.query.filter(
        Flashcard.user_id == user.id,
        Flashcard.last_review != None,
        func.date(Flashcard.last_review) == today
    ).count()

    # recs
    reading_minutes = reviewed_today * 2
    listening_minutes = int(reviewed_today * 1.5)

    return render_template('dashboard.html',
                           user=user,
                           flashcard_count=flashcard_count,
                           days_active=unique_days,
                           recent_activities=recent_activities,
                           level=level,
                           xp_to_next=xp_to_next,
                           reading_minutes=reading_minutes,
                           listening_minutes=listening_minutes)










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

@app.route("/kana")
def kana():
    return render_template("kana.html", title="Kana")






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
            profile_picture="img/default_avatar.png"
        )

        new_user.set_password(form.password.data)
        db.session.add(new_user)
        db.session.commit()

        flash('Account created :) You can now log in at the top right.', 'success')
        return redirect(url_for('home'))
    return render_template('generic_form.html', title='Register', form=form)



@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))

