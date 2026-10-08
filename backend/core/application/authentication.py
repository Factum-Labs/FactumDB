"""Shared local-account policy; persistence and device verification are ports."""

import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Mapping
from typing import Protocol, TypedDict


class User(TypedDict):
    username: str


class Account(User):
    user_id: int
    salt: bytes
    password_hash: bytes
    device_identity: str


class AuthStatus(TypedDict):
    user: User | None


class AuthenticationRequiredError(PermissionError):
    pass


class AuthenticationError(PermissionError):
    pass


class DeviceSecurity(Protocol):
    def identity(self) -> str: ...
    def verify(self) -> str: ...


class AccountStore(Protocol):
    def find(self, key: str) -> Account | None: ...
    def create(
        self, username: str, key: str, salt: bytes, digest: bytes, identity: str
    ) -> None: ...
    def throttle(self) -> tuple[int, float]: ...
    def set_throttle(self, failures: int, until: float) -> None: ...


class AuthenticationService:
    def __init__(self, accounts: AccountStore, device: DeviceSecurity) -> None:
        self.accounts, self.device = accounts, device
        self.user: User | None = None

    @staticmethod
    def credentials(payload: Mapping[str, object], confirmation: bool = False) -> tuple[str, str]:
        fields = {"username", "password"} | ({"password_confirmation"} if confirmation else set())
        if set(payload) != fields:
            raise ValueError("Unsupported account fields")
        username, password = payload.get("username"), payload.get("password")
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username):
            raise ValueError("Username must be 3-64 letters, numbers, dots, underscores or hyphens")
        minimum = 12 if confirmation else 1
        if not isinstance(password, str) or not minimum <= len(password) <= 1024:
            raise ValueError(f"Password must contain {minimum}-1024 characters")
        if confirmation and password != payload["password_confirmation"]:
            raise ValueError("Passwords do not match")
        return username, password

    @staticmethod
    def digest(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=32768,
            r=8,
            p=3,
            maxmem=64 * 1024 * 1024,
            dklen=32,
        )

    def signup(self, payload: Mapping[str, object]) -> AuthStatus:
        if self.user is not None:
            raise AuthenticationError("Sign out before creating another account")
        username, password = self.credentials(payload, confirmation=True)
        if self.accounts.find(username.lower()):
            raise ValueError("Username is already registered")
        # Verification happens inside the backend, never via a renderer boolean.
        identity = self.device.verify()
        if identity != self.device.identity():
            raise AuthenticationError("Verify the currently signed-in device account")
        salt = secrets.token_bytes(16)
        self.accounts.create(
            username, username.lower(), salt, self.digest(password, salt), identity
        )
        self.user = {"username": username}
        return self.status({})

    def login(self, payload: Mapping[str, object]) -> AuthStatus:
        if self.user is not None:
            raise AuthenticationError("Sign out before signing in to another account")
        username, password = self.credentials(payload)
        failures, until = self.accounts.throttle()
        now = time.time()
        if until > now:
            raise AuthenticationError("Too many attempts. Try again in 30 seconds")
        account = self.accounts.find(username.lower())
        # Unknown usernames incur the same password derivation work.
        digest = self.digest(password, account["salt"] if account else bytes(16))
        valid = hmac.compare_digest(digest, account["password_hash"] if account else bytes(32))
        if not valid or account is None or account["device_identity"] != self.device.identity():
            failures = (0 if until else failures) + 1
            self.accounts.set_throttle(failures, now + 30 if failures >= 5 else 0)
            raise AuthenticationError("Incorrect username or password for this device account")
        self.accounts.set_throttle(0, 0)
        self.user = {"username": account["username"]}
        return self.status({})

    def require_user(self) -> User:
        if self.user is None:
            raise AuthenticationRequiredError("Sign in before using FactumDB")
        return self.user

    def require_actor(self) -> dict[str, str]:
        user = self.require_user()
        account = self.accounts.find(user["username"].lower())
        if account is None:
            raise AuthenticationRequiredError("Sign in before using FactumDB")
        return {"actor_id": str(account["user_id"]), "actor_username": account["username"]}

    def status(self, payload: Mapping[str, object]) -> AuthStatus:
        if payload:
            raise ValueError("No fields expected")
        return {"user": self.user}

    def logout(self, payload: Mapping[str, object]) -> AuthStatus:
        if payload:
            raise ValueError("No fields expected")
        self.user = None
        return self.status({})
