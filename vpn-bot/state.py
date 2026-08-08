import json
import os
import secrets
import tempfile

import config


class State:
    def __init__(self, path):
        self.path = path
        self.offset = 0
        self.users = {}            # chat_id -> user dict, see _new_user()
        self.pending_payments = {}  # transaction_id -> {chat_id, plan_id, amount, kind: "sub"|"withdraw_topup"}
        self._load()

    def _new_user(self, referrer=None):
        return {
            "referrer": referrer,
            "xui_email": None,
            "xui_uuid": None,
            "expiry_ms": 0,
            "ref_balance": 0.0,   # legacy cash balance: no longer accrues, still withdrawable
            "ref_count": 0,
            "ref_days": 0,        # bonus days earned by inviting, cumulative
            "days_banked": 0,     # owed days for a referrer who has no client yet
            "ref_rewarded": False,  # this user's first payment has already paid out their inviter
            "trial_used": False,
            "sub_token": secrets.token_hex(16),
            "region": config.DEFAULT_REGION,
        }

    def ensure_user(self, chat_id, referrer=None):
        # Nobody invites themselves — enforced here so no caller can leak days through it.
        if referrer == chat_id:
            referrer = None
        if chat_id not in self.users:
            self.users[chat_id] = self._new_user(referrer)
        elif referrer is not None and self.users[chat_id]["referrer"] is None:
            self.users[chat_id]["referrer"] = referrer
        user = self.users[chat_id]
        if not user.get("sub_token"):
            user["sub_token"] = secrets.token_hex(16)
        if not user.get("region"):
            user["region"] = config.DEFAULT_REGION
        # Users saved before the day-based referral rework are missing these keys.
        for key, default in (("ref_days", 0), ("days_banked", 0), ("ref_rewarded", False)):
            user.setdefault(key, default)
        return user

    def find_by_sub_token(self, token):
        for chat_id, user in self.users.items():
            if user.get("sub_token") == token:
                return chat_id, user
        return None, None

    def _load(self):
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.offset = data.get("offset", 0)
        self.users = {int(k): v for k, v in data.get("users", {}).items()}
        self.pending_payments = data.get("pendingPayments", {})

    def save(self):
        data = {
            "offset": self.offset,
            "users": {str(k): v for k, v in self.users.items()},
            "pendingPayments": self.pending_payments,
        }
        d = os.path.dirname(self.path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=d, prefix=".state_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp_path, self.path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def is_admin(self, chat_id):
        return chat_id in config.ADMIN_CHAT_IDS

    def count_referral(self, referrer_id, days):
        """Records one paid referral. The days themselves are applied by subscriptions."""
        user = self.ensure_user(referrer_id)
        user["ref_count"] += 1
        user["ref_days"] += days


state = State(config.STATE_PATH)
