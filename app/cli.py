from __future__ import annotations

import argparse

from sqlalchemy import select

from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.core.i18n import get_default_language
from app.models.enums import Role
from app.models.user import User
from app.services.users import create_user


def seed_super_admin(email: str, display_name: str) -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    session = get_session_factory()()
    try:
        existing = session.scalar(select(User).where(User.email == email.lower()))
        if existing is not None:
            existing.display_name = display_name
            existing.role = Role.SUPER_ADMIN
            existing.is_active = True
            session.commit()
            print(f"Updated existing user {email} as super_admin")
            return

        user = create_user(
            session,
            email=email.lower(),
            display_name=display_name,
            role=Role.SUPER_ADMIN,
            preferred_language=get_default_language(),
            is_active=True,
            actor_user_id=None,
        )
        print(f"Created super_admin user id={user.id} email={user.email}")
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Room Management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed-super-admin", help="Seed or update the initial super admin")
    seed.add_argument("--email", required=True)
    seed.add_argument("--display-name", required=True)

    args = parser.parse_args()
    if args.command == "seed-super-admin":
        seed_super_admin(args.email, args.display_name)


if __name__ == "__main__":
    main()
