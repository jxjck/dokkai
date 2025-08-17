from datetime import datetime
from app import db
from app.models import User, Flashcard
def reset_db():
    print("resetting...ちょっと待ってね:)")

    db.drop_all()
    db.create_all()

    user1 = User(
        username="testuser",
        email="test@example.com",

        profile_picture="img/default_avatar.png"
  #dummy avatar check filepath
    )
    user1.set_password("testpass")

    user2 = User(
        username="user2",
        email="user2@user2.com",
        role="Admin",

        profile_picture="img/default_avatar.png"
 #dummy avatar
    )
    user2.set_password("User2@user2.com")

    db.session.add_all([user1, user2])
    db.session.commit()

    test_cards = [
        Flashcard(
            user_id=user2.id,
            front="ありがとう",
            back="Thank you",
            reading="ありがとう",
            meaning="Thank you",
            sentence="手伝ってくれてありがとう。",
            due_date=datetime.utcnow()
        ),
        Flashcard(
            user_id=user2.id,
            front="猫",
            back="Cat",
            reading="ねこ",
            meaning="Cat",
            sentence="猫が大好きです。",
            due_date=datetime.utcnow()
        ),
        Flashcard(
            user_id=user2.id,
            front="水",
            back="Water",
            reading="みず",
            meaning="Water",
            sentence="水を一杯ください。",
            due_date=datetime.utcnow()
        )
    ]


    days_of_week_deck = [
        Flashcard(
            user_id=user2.id,
            front="月曜日",
            back="Monday",
            reading="げつようび",
            meaning="Monday",
            sentence="月曜日は新しい週の始まりです。",
            due_date=datetime.utcnow()
        ),
        Flashcard(
            user_id=user2.id,
            front="火曜日",
            back="Tuesday",
            reading="かようび",
            meaning="Tuesday",
            sentence="火曜日にはミーティングがあります。",
            due_date=datetime.utcnow()
        ),
        Flashcard(
            user_id=user2.id,
            front="水曜日",
            back="Wednesday",
            reading="すいようび",
            meaning="Wednesday",
            sentence="水曜日はジムに行きます。",
            due_date=datetime.utcnow()
        ),
        Flashcard(
            user_id=user2.id,
            front="木曜日",
            back="Thursday",
            reading="もくようび",
            meaning="Thursday",
            sentence="木曜日は仕事が忙しいです。",
            due_date=datetime.utcnow()
        ),
        Flashcard(
            user_id=user2.id,
            front="金曜日",
            back="Friday",
            reading="きんようび",
            meaning="Friday",
            sentence="金曜日は友達と会います。",
            due_date=datetime.utcnow()
        ),
        Flashcard(
            user_id=user2.id,
            front="土曜日",
            back="Saturday",
            reading="どようび",
            meaning="Saturday",
            sentence="土曜日はゆっくり休みます。",
            due_date=datetime.utcnow()
        ),
        Flashcard(
            user_id=user2.id,
            front="日曜日",
            back="Sunday",
            reading="にちようび",
            meaning="Sunday",
            sentence="日曜日には公園に行きます。",
            due_date=datetime.utcnow()
        ),
    ]

    db.session.add_all(test_cards)
    db.session.add_all(days_of_week_deck)
    db.session.commit()

    print("Database reset complete.")
    print(f"Added users: {user1.username}, {user2.username}")
    for card in test_cards:
        print(f"Added flashcard: {card.front} → {card.meaning}")

    for card in days_of_week_deck:
        print(f"Added flashcard: {card.front} → {card.meaning}")

