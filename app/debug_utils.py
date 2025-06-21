from app import db
from app.models import User

def reset_db():
    print("Resetting the database...")

    db.drop_all()
    db.create_all()

    user1 = User(username="testuser", email="test@example.com")
    user1.set_password("testpass")

    user2 = User(username="admin", email="admin@example.com", role="Admin")
    user2.set_password("adminpass")

    db.session.add_all([user1, user2])
    db.session.commit()

    print("Database reset complete.")
    print(f"Added users: {user1.username}, {user2.username}")
