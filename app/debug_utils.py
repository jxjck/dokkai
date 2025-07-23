from datetime import datetime
from app import db
from app.models import User, Flashcard

def reset_db():
    print("resetting...:) ちょっと待ってね：）")

    db.drop_all()
    db.create_all()

    user1 = User(username="testuser", email="test@example.com")
    user1.set_password("testpass")

    user2 = User(username="user2", email="user2@user2.com", role="Admin")
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

    db.session.add_all(test_cards)
    db.session.commit()

    print("Database reset complete.")
    print(f"Added users: {user1.username}, {user2.username}")
    for card in test_cards:
        print(f"Added flashcard: {card.front} → {card.meaning}")
