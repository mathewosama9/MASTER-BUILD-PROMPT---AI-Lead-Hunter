"""Every notification kind, its defaults, and how the admin's policy and the user's choices combine.

Channels for one user and one kind = the admin policy's channels (Admin → Notifications), narrowed by the user's
own choices (Settings → Notifications) where the policy lets the user turn the kind off. Mandatory kinds (security)
ignore the user's choices; admin kinds go to platform admins only.
"""

from dataclasses import dataclass

from app.models.enums import NotifyChannel

CHANNELS = (NotifyChannel.IN_APP, NotifyChannel.EMAIL, NotifyChannel.TELEGRAM)


@dataclass(frozen=True)
class Kind:
    key: str
    category: str  # campaigns | billing | account | news | admin
    channels: tuple[str, ...]  # on by default
    mandatory: bool = False  # the user cannot turn it off
    admin: bool = False  # sent to platform admins only

    @property
    def marketing(self) -> bool:
        """Emails of these kinds carry an unsubscribe link."""
        return self.category == "news"


_ALL = (NotifyChannel.IN_APP, NotifyChannel.EMAIL, NotifyChannel.TELEGRAM)
_APP_TG = (NotifyChannel.IN_APP, NotifyChannel.TELEGRAM)

KINDS: dict[str, Kind] = {
    k.key: k
    for k in (
        Kind("campaign_completed", "campaigns", _ALL),
        Kind("campaign_failed", "campaigns", _ALL),
        Kind("credits_low", "billing", _ALL),
        Kind("credits_exhausted", "billing", _ALL),
        Kind("credits_added", "billing", _ALL),
        Kind("payment_succeeded", "billing", _ALL),
        Kind("payment_failed", "billing", _ALL),
        Kind("topup_approved", "billing", _ALL),
        Kind("topup_rejected", "billing", _ALL),
        Kind("trial_ending", "billing", _ALL),
        Kind("trial_ended", "billing", _ALL),
        Kind("account_suspended", "account", _ALL, mandatory=True),
        Kind("password_changed", "account", _ALL, mandatory=True),
        # Mandatory: the user is waiting for it, and it may be the only way an unconfirmed inbox learns to confirm.
        Kind("account_approved", "account", _ALL, mandatory=True),
        Kind("account_rejected", "account", (NotifyChannel.EMAIL,), mandatory=True),
        Kind("telegram_linked", "account", _ALL),
        Kind("announcement", "news", _ALL),
        Kind("marketing", "news", (NotifyChannel.IN_APP, NotifyChannel.EMAIL)),
        Kind("admin_new_user", "admin", _APP_TG, admin=True),
        Kind("admin_signup_review", "admin", _APP_TG, admin=True),
        Kind("admin_signup_suspicious", "admin", _APP_TG, admin=True),
        Kind("admin_new_payment", "admin", _APP_TG, admin=True),
        Kind("admin_topup_request", "admin", _APP_TG, admin=True),
        Kind("admin_contact", "admin", _APP_TG, admin=True),
        Kind("admin_review", "admin", _APP_TG, admin=True),
        Kind("admin_campaign_failed", "admin", _APP_TG, admin=True),
        Kind("admin_daily_digest", "admin", (NotifyChannel.EMAIL, NotifyChannel.TELEGRAM), admin=True),
    )
}


def default_policy(kind: Kind) -> dict:
    return {
        "enabled": True,
        "channels": {c.value: c in kind.channels for c in CHANNELS},
        "user_can_disable": not kind.mandatory,
    }


def policy_for(stored: dict | None, kind: Kind) -> dict:
    """The admin's saved policy for `kind`, filled in from the defaults."""
    base = default_policy(kind)
    saved = (stored or {}).get(kind.key) or {}
    if isinstance(saved.get("enabled"), bool):
        base["enabled"] = saved["enabled"]
    for c, on in (saved.get("channels") or {}).items():
        if c in base["channels"] and isinstance(on, bool):
            base["channels"][c] = on
    if isinstance(saved.get("user_can_disable"), bool) and not kind.mandatory:
        base["user_can_disable"] = saved["user_can_disable"]
    return base


def full_policy(stored: dict | None) -> dict[str, dict]:
    return {key: policy_for(stored, kind) for key, kind in KINDS.items()}


def clean_policy(raw: dict) -> dict:
    """What the admin may save: known kinds and channels only, booleans only."""
    out: dict[str, dict] = {}
    for key, value in (raw or {}).items():
        kind = KINDS.get(key)
        if kind is None or not isinstance(value, dict):
            continue
        out[key] = policy_for({key: value}, kind)
    return out


def user_choice(prefs: dict | None, kind: Kind, channel: str) -> bool:
    saved = ((prefs or {}).get(kind.key) or {}).get(channel)
    return saved if isinstance(saved, bool) else True


def channels_for(stored_policy: dict | None, prefs: dict | None, kind: Kind) -> set[str]:
    """Channels to use for one user, before checking the user can actually be reached on them."""
    policy = policy_for(stored_policy, kind)
    if not policy["enabled"]:
        return set()
    allowed = {c for c, on in policy["channels"].items() if on}
    if kind.mandatory or not policy["user_can_disable"]:
        return allowed
    return {c for c in allowed if user_choice(prefs, kind, c)}


def clean_prefs(raw: dict, *, admin: bool = False) -> dict:
    """What a user may save: known kinds (admin kinds for platform admins only) and channels, booleans only."""
    out: dict[str, dict] = {}
    for key, value in (raw or {}).items():
        kind = KINDS.get(key)
        if kind is None or (kind.admin and not admin) or kind.mandatory or not isinstance(value, dict):
            continue
        choices = {c.value: value[c.value] for c in CHANNELS if isinstance(value.get(c.value), bool)}
        if choices:
            out[key] = choices
    return out
