import time
from collections import defaultdict, deque

from fastapi import APIRouter, Response, HTTPException, Depends, Request
from pydantic import BaseModel
from .. import db, auth as authmod

router = APIRouter(prefix="/api/auth", tags=["auth"])

_LOGIN_WINDOW_SEC = 10 * 60
_LOGIN_MAX_FAILURES = 8
_LOGIN_FAILURES: dict[str, deque[float]] = defaultdict(deque)


class LoginIn(BaseModel):
    username: str
    password: str


def _login_key(request: Request, username: str) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = (forwarded.split(",", 1)[0] or (request.client.host if request.client else "")).strip()
    return f"{ip}:{username.lower()}"


def _check_login_limit(key: str) -> None:
    now = time.monotonic()
    failures = _LOGIN_FAILURES[key]
    while failures and now - failures[0] > _LOGIN_WINDOW_SEC:
        failures.popleft()
    if len(failures) >= _LOGIN_MAX_FAILURES:
        raise HTTPException(429, "登录失败次数过多,请稍后再试")


def _record_login_failure(key: str) -> None:
    _LOGIN_FAILURES[key].append(time.monotonic())


@router.post("/login")
def login(body: LoginIn, response: Response, request: Request):
    key = _login_key(request, body.username)
    _check_login_limit(key)
    u = db.fetchone(
        "SELECT id, username, password_hash, display_name, role, active FROM users WHERE username=%s",
        (body.username,),
    )
    if not u or not u["active"] or not authmod.verify_password(body.password, u["password_hash"]):
        _record_login_failure(key)
        raise HTTPException(401, "用户名或密码错误")
    _LOGIN_FAILURES.pop(key, None)
    token = authmod.make_token(u["id"], u["username"], u["role"])
    response.set_cookie(
        key=authmod.JWT_COOKIE,
        value=token,
        max_age=authmod.JWT_TTL,
        httponly=True,
        samesite="lax",
        secure=authmod.cookie_secure_for_request(request),
        path="/",
    )
    db.execute("UPDATE users SET last_login_at = now() WHERE id=%s", (u["id"],))
    db.execute(
        "INSERT INTO events (user_id, action) VALUES (%s, %s)",
        (u["id"], "login"),
    )
    return {"id": u["id"], "username": u["username"], "display_name": u["display_name"], "role": u["role"]}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(authmod.JWT_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(authmod.get_current_user)):
    return user
