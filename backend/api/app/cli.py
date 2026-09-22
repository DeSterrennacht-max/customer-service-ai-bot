"""Operator-only recovery: python -m backend.api.app.cli reset-superadmin --username NAME."""
import argparse
from getpass import getpass

from sqlalchemy import select

from backend.api.app.core.security import get_password_hash, validate_new_password
from backend.api.app.db.models.entities import User, UserRole
from backend.api.app.db.session import SessionLocal
from backend.api.app.services.auth_session_service import revoke_all_sessions


def main() -> None:
    parser = argparse.ArgumentParser(description="Recover an existing super administrator; requires database operator access")
    parser.add_argument("command", choices=["reset-superadmin"])
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    password = getpass("新密码（至少 12 个字符，包含字母和数字）: ")
    validate_new_password(password)
    if password != getpass("再次输入新密码: "):
        raise SystemExit("两次密码不一致，未修改账号")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login_username == args.username, User.role == UserRole.SUPER_ADMIN).with_for_update())
        if not user or not user.is_active:
            raise SystemExit("找不到启用的超级管理员账号，未作修改")
        user.password_hash = get_password_hash(password)
        revoke_all_sessions(db, user)
        db.commit()
    print("密码已重置，旧登录会话已失效。")


if __name__ == "__main__":
    main()
