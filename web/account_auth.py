"""Email and password accounts beside Google SSO.

Follows the FastSME shared local-account pattern used by the sister products
(FastHRM ``web/account_auth.py``: scrypt hashes, SHA-256 hashed single-use
tokens, fixed-window throttles, Postmark mail via ``POSTMARK_API_TOKEN`` and
``FROM_EMAIL``) and hardens it for FastAccounts:

* accounts live in the main database (migration 0009), so PostgreSQL in
  production, instead of a side SQLite file;
* every response is identical whether or not an address exists;
* registration requires confirming the email *and* re-entering the chosen
  password, so a stranger cannot pre-register someone else's address;
* sign-in rotates the session and a password reset invalidates every other
  session through ``session_version``;
* without mail configuration nothing fails: requests log a warning and the
  generic message is shown.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from core_utils import new_id, utc_now
from database import get_database
from web import i18n
from web.google_auth import access_allowed

log = logging.getLogger("fastaccounts.auth")

PASSWORD_MIN = 10
PASSWORD_MAX = 1024
RESET_TTL = 60 * 60
VERIFY_TTL = 24 * 60 * 60

# action: (attempts, window seconds)
LIMITS: dict[str, tuple[int, int]] = {
    "login": (10, 15 * 60),        # failed sign-ins per email (lockout)
    "login_ip": (50, 15 * 60),     # failed sign-ins per client address
    "register": (5, 60 * 60),
    "register_ip": (20, 60 * 60),
    "forgot": (5, 60 * 60),
    "forgot_ip": (20, 60 * 60),
    "token_ip": (20, 15 * 60),     # verify/reset form submissions per client
}

# OWASP-equivalent scrypt cost (N=2^14, r=8, p=5) with a modest 16 MiB footprint.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 5
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                            dklen=32, maxmem=_SCRYPT_MAXMEM)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str | None) -> bool:
    """Verify current hashes and the sister products' ``scrypt$N$salt$hash`` form."""
    try:
        parts = (encoded or "").split("$")
        if len(parts) == 6 and parts[0] == "scrypt":
            n, r, p, salt, expected = int(parts[1]), int(parts[2]), int(parts[3]), parts[4], parts[5]
        elif len(parts) == 4 and parts[0] == "scrypt":
            n, r, p, salt, expected = int(parts[1]), 8, 1, parts[2], parts[3]
        else:
            return False
        expected_bytes = base64.urlsafe_b64decode(expected)
        actual = hashlib.scrypt(password.encode(), salt=base64.urlsafe_b64decode(salt), n=n, r=r, p=p,
                                dklen=len(expected_bytes), maxmem=_SCRYPT_MAXMEM)
        return hmac.compare_digest(actual, expected_bytes)
    except (ValueError, TypeError):
        return False


def needs_rehash(encoded: str | None) -> bool:
    return not (encoded or "").startswith(f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$")


_DUMMY_HASH: str | None = None


def _burn_password_check(password: str) -> None:
    """Spend the same work as a real check so timing does not reveal accounts."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
    verify_password(password or "", _DUMMY_HASH)


def normalize_email(value) -> str:
    value = str(value or "").strip().lower()
    return value if len(value) <= 254 and _EMAIL.fullmatch(value) else ""


def valid_password(value) -> bool:
    return isinstance(value, str) and PASSWORD_MIN <= len(value) <= PASSWORD_MAX


def token_digest(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def client_address(request) -> str:
    """Client address behind one trusted proxy: the right-most forwarded hop."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        hop = forwarded.split(",")[-1].strip()
        if hop:
            return hop
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------- mail
def mail_configured() -> bool:
    return bool(os.getenv("POSTMARK_API_TOKEN", "").strip() and os.getenv("FROM_EMAIL", "").strip())


def public_base_url() -> str:
    """Links in mail use configuration only, never the request Host header."""
    for key in ("FASTACCOUNTS_PUBLIC_URL", "FASTSME_PUBLIC_URL"):
        value = os.getenv(key, "").strip().rstrip("/")
        if value.startswith(("https://", "http://")):
            return value
    return ""


def send_email(to: str, subject: str, html_body: str, text_body: str) -> bool:
    """Postmark transactional send (same env names as the sister products)."""
    token = os.getenv("POSTMARK_API_TOKEN", "").strip()
    sender = os.getenv("FROM_EMAIL", "").strip()
    if not token or not sender:
        log.warning("Account email not sent: POSTMARK_API_TOKEN and FROM_EMAIL are not configured")
        return False
    payload = json.dumps({
        "From": sender, "To": to, "Subject": subject, "HtmlBody": html_body,
        "TextBody": text_body, "MessageStream": "outbound", "Tag": "account",
    }).encode()
    request = UrlRequest(
        "https://api.postmarkapp.com/email", data=payload, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "X-Postmark-Server-Token": token},
    )
    try:
        with urlopen(request, timeout=15) as response:
            ok = response.status == 200
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        log.warning("Account email delivery failed: %s", type(error).__name__)
        return False
    if not ok:
        log.warning("Account email delivery was not accepted by Postmark")
    return ok


def _send_link(email: str, name: str, purpose: str, token: str, lang: str) -> bool:
    base = public_base_url()
    if not base:
        log.warning("Account email not sent: FASTACCOUNTS_PUBLIC_URL is not configured")
        return False
    T = lambda key: i18n.t(f"auth.{key}", lang)
    link = f"{base}/auth/local/{purpose}/{token}"
    if (os.getenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "").lower() == "true"
            and not mail_configured()):
        label = "sign-up verification" if purpose == "verify" else "password reset"
        log.warning("Local dev link (%s): %s", label, link)
    subject = T(f"mail_{purpose}_subject")
    lines = [T("mail_greeting").format(name=name or email), T(f"mail_{purpose}_body"),
             T(f"mail_{purpose}_expiry"), T("mail_ignore")]
    text = "\n\n".join([lines[0], lines[1], link, *lines[2:]])
    body = (f"<p>{html.escape(lines[0])}</p><p>{html.escape(lines[1])}</p>"
            f"<p><a href=\"{html.escape(link, quote=True)}\">{html.escape(subject)}</a></p>"
            + "".join(f"<p>{html.escape(line)}</p>" for line in lines[2:]))
    return send_email(email, subject, body, text)


# ---------------------------------------------------------------- store
class AccountStore:
    def __init__(self, db=None):
        self._db = db

    @property
    def db(self):
        return self._db or get_database()

    # throttles ---------------------------------------------------------
    @staticmethod
    def _subject(subject: str) -> str:
        return hashlib.sha256((subject or "").encode()).hexdigest()

    def limited(self, subject: str, action: str) -> bool:
        limit, window = LIMITS[action]
        row = self.db.one("SELECT window_start,attempts FROM auth_rate_limits WHERE subject_hash=? AND action=?",
                          (self._subject(subject), action))
        return bool(row and int(row["window_start"]) > int(time.time()) - window and int(row["attempts"]) >= limit)

    def hit(self, subject: str, action: str) -> None:
        _, window = LIMITS[action]
        now, key = int(time.time()), self._subject(subject)
        with self.db.transaction() as tx:
            row = tx.one("SELECT window_start FROM auth_rate_limits WHERE subject_hash=? AND action=?", (key, action))
            if not row or int(row["window_start"]) <= now - window:
                tx.execute("INSERT INTO auth_rate_limits(subject_hash,action,window_start,attempts) VALUES (?,?,?,1) "
                           "ON CONFLICT(subject_hash,action) DO UPDATE SET window_start=excluded.window_start,attempts=1",
                           (key, action, now))
            else:
                tx.execute("UPDATE auth_rate_limits SET attempts=attempts+1 WHERE subject_hash=? AND action=?", (key, action))

    def consume(self, subject: str, action: str) -> bool:
        """Count an attempt; False once the window's allowance is spent."""
        if self.limited(subject, action):
            return False
        self.hit(subject, action)
        return True

    def clear(self, subject: str, action: str) -> None:
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM auth_rate_limits WHERE subject_hash=? AND action=?", (self._subject(subject), action))

    # accounts ----------------------------------------------------------
    def get(self, email: str) -> dict | None:
        email = normalize_email(email)
        return self.db.one("SELECT * FROM user_accounts WHERE email=?", (email,)) if email else None

    def _issue(self, tx, account_id: str, purpose: str, ttl: int) -> str:
        now = int(time.time())
        tx.execute("DELETE FROM auth_tokens WHERE expires_at<?", (now - 86400,))
        tx.execute("DELETE FROM auth_tokens WHERE account_id=? AND purpose=? AND used_at IS NULL", (account_id, purpose))
        token = secrets.token_urlsafe(32)
        tx.execute("INSERT INTO auth_tokens(id,account_id,purpose,token_hash,expires_at,created_at) VALUES (?,?,?,?,?,?)",
                   (new_id(), account_id, purpose, token_digest(token), now + ttl, utc_now()))
        return token

    def _valid_token(self, tx, token: str, purpose: str) -> dict | None:
        if not token or len(token) > 200:
            return None
        return tx.one("SELECT t.id AS token_id,a.* FROM auth_tokens t JOIN user_accounts a ON a.id=t.account_id "
                      "WHERE t.token_hash=? AND t.purpose=? AND t.used_at IS NULL AND t.expires_at>?",
                      (token_digest(token), purpose, int(time.time())))

    def register(self, email: str, password: str, name: str, lang: str = "en") -> None:
        """Always ends with the same public outcome; mail only when appropriate."""
        email, name = normalize_email(email), (name or "").strip()[:120]
        if not email or not valid_password(password):
            raise ValueError("invalid")
        existing = self.get(email)
        if existing and existing["email_verified"]:
            _burn_password_check(password)
            log.info("Registration ignored for an existing verified account")
            return
        if not access_allowed(email):
            _burn_password_check(password)
            log.info("Registration ignored for an address without workspace access")
            return
        now, password_hash = utc_now(), hash_password(password)
        with self.db.transaction() as tx:
            if existing:
                account_id = existing["id"]
                tx.execute("UPDATE user_accounts SET name=?,password_hash=?,updated_at=? WHERE id=?",
                           (name, password_hash, now, account_id))
            else:
                account_id = new_id()
                tx.execute("INSERT INTO user_accounts(id,email,name,password_hash,email_verified,created_at,updated_at) "
                           "VALUES (?,?,?,?,0,?,?)", (account_id, email, name, password_hash, now, now))
            token = self._issue(tx, account_id, "verify", VERIFY_TTL)
        _send_link(email, name, "verify", token, lang)

    def confirm_email(self, token: str, password: str) -> dict | None:
        """Verify an address only for the person who chose the pending password."""
        with self.db.transaction() as tx:
            account = self._valid_token(tx, token, "verify")
            if not account:
                _burn_password_check(password)
                return None
            if not verify_password(password or "", account["password_hash"]):
                return None
            tx.execute("UPDATE auth_tokens SET used_at=? WHERE id=?", (int(time.time()), account["token_id"]))
            tx.execute("UPDATE user_accounts SET email_verified=1,updated_at=? WHERE id=?", (utc_now(), account["id"]))
            return tx.one("SELECT * FROM user_accounts WHERE id=?", (account["id"],))

    def authenticate(self, email: str, password: str) -> dict | None:
        account = self.get(email)
        if not account or not account["password_hash"]:
            _burn_password_check(password)
            return None
        if not verify_password(password or "", account["password_hash"]):
            return None
        if not account["email_verified"] or not access_allowed(account["email"]):
            return None
        if needs_rehash(account["password_hash"]):
            with self.db.transaction() as tx:
                tx.execute("UPDATE user_accounts SET password_hash=?,updated_at=? WHERE id=?",
                           (hash_password(password), utc_now(), account["id"]))
        return account

    def request_reset(self, email: str, lang: str = "en") -> None:
        """Send a one-hour reset link; Google-only members may set a password this way."""
        email = normalize_email(email)
        if not email:
            return
        account = self.get(email)
        if not account:
            if not access_allowed(email):
                return
            now = utc_now()
            with self.db.transaction() as tx:
                tx.execute("INSERT INTO user_accounts(id,email,name,email_verified,created_at,updated_at) "
                           "VALUES (?,?,'',0,?,?) ON CONFLICT(email) DO NOTHING", (new_id(), email, now, now))
            account = self.get(email)
        with self.db.transaction() as tx:
            token = self._issue(tx, account["id"], "reset", RESET_TTL)
        _send_link(email, account["name"], "reset", token, lang)

    def reset_password(self, token: str, password: str) -> dict | None:
        if not valid_password(password):
            return None
        with self.db.transaction() as tx:
            account = self._valid_token(tx, token, "reset")
            if not account:
                return None
            now = utc_now()
            tx.execute("UPDATE auth_tokens SET used_at=? WHERE id=?", (int(time.time()), account["token_id"]))
            tx.execute("DELETE FROM auth_tokens WHERE account_id=? AND used_at IS NULL", (account["id"],))
            tx.execute("UPDATE user_accounts SET password_hash=?,email_verified=1,session_version=session_version+1,"
                       "password_changed_at=?,updated_at=? WHERE id=?",
                       (hash_password(password), now, now, account["id"]))
            return tx.one("SELECT * FROM user_accounts WHERE id=?", (account["id"],))

    def link_google(self, email: str, name: str = "") -> dict | None:
        """Map a verified Google login to the same account as the email address."""
        email, name, now = normalize_email(email), (name or "").strip()[:120], utc_now()
        if not email:
            return None
        with self.db.transaction() as tx:
            row = tx.one("SELECT * FROM user_accounts WHERE email=?", (email,))
            if row:
                # An unverified password was never proven by the mailbox owner; drop it.
                tx.execute("UPDATE user_accounts SET google_linked=1,email_verified=1,"
                           "password_hash=CASE WHEN email_verified=1 THEN password_hash ELSE NULL END,"
                           "name=CASE WHEN name='' THEN ? ELSE name END,updated_at=? WHERE id=?",
                           (name, now, row["id"]))
                if not row["email_verified"]:
                    tx.execute("DELETE FROM auth_tokens WHERE account_id=? AND purpose='verify'", (row["id"],))
            else:
                tx.execute("INSERT INTO user_accounts(id,email,name,email_verified,google_linked,created_at,updated_at) "
                           "VALUES (?,?,?,1,1,?,?)", (new_id(), email, name, now, now))
            return tx.one("SELECT * FROM user_accounts WHERE email=?", (email,))


accounts = AccountStore()


# ---------------------------------------------------------------- sessions
def establish_session(session, account: dict, method: str) -> None:
    """Rotate the whole signed session on every sign-in (fixation defence)."""
    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    session["user"] = {"email": account["email"], "name": account.get("name") or account["email"],
                       "auth": method, "sv": int(account.get("session_version") or 1)}
    session["csrf_token"] = secrets.token_urlsafe(32)


def session_user_valid(user: dict | None) -> bool:
    """False once a password reset has bumped the account's session version."""
    if not user or not user.get("email"):
        return False
    try:
        row = get_database().one("SELECT session_version FROM user_accounts WHERE email=?",
                                 (str(user["email"]).strip().lower(),))
    except Exception:
        log.exception("Session check failed")
        return False
    if not row:
        return True
    try:
        version = int(user.get("sv") or 1)
    except (TypeError, ValueError):
        return False
    return version == int(row["session_version"])


def form_csrf(session) -> str:
    token = session.get("csrf_token")
    if not token:
        token = session["csrf_token"] = secrets.token_urlsafe(32)
    return token


def csrf_ok(session, submitted) -> bool:
    expected = session.get("csrf_token") or ""
    return bool(expected and submitted and hmac.compare_digest(str(expected), str(submitted)))
