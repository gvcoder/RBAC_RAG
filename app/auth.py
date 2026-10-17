import bcrypt
from app.db import get_session, User

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

def authenticate_user(email: str, password: str, expected_role: str = None):
    session = get_session()
    try:
        user = session.query(User).filter(User.email == email.strip().lower()).first()
        if not user:
            return None
        if not verify_password(password, user.password_hash):
            return None
        if expected_role and user.role.lower() != expected_role.lower():
            return None
        return {
            "id": user.id,
            "email": user.email,
            "role": user.role
        }
    finally:
        session.close()

def seed_default_users():
    session = get_session()
    try:
        default_users = [
            ("admin@company.com", "Admin@123", "Admin"),
            ("hr@company.com", "HR@123", "HR"),
            ("employee@company.com", "Emp@123", "Employee"),
        ]
        for email, pwd, role in default_users:
            existing = session.query(User).filter(User.email == email).first()
            if not existing:
                u = User(
                    email=email,
                    password_hash=hash_password(pwd),
                    role=role
                )
                session.add(u)
        session.commit()
    finally:
        session.close()

def create_user(email: str, password: str, role: str):
    session = get_session()
    try:
        existing = session.query(User).filter(User.email == email.strip().lower()).first()
        if existing:
            return False, "User already exists with this email."
        user = User(
            email=email.strip().lower(),
            password_hash=hash_password(password),
            role=role
        )
        session.add(user)
        session.commit()
        return True, "User created successfully."
    except Exception as e:
        session.rollback()
        return False, str(e)
    finally:
        session.close()
