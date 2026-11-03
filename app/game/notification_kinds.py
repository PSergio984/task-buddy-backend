"""Notification kind x channel matrix constants (issue #68).

Leaf module: schemas/game.py validates the prefs matrix against these —
importing the dispatch module for constants would drag the webpush/Brevo
stack (app.tasks -> AsyncSessionLocal, pywebpush) into every schema import
and risk an import cycle (game/service.py imports both). No behavior here.
"""

from app.models.notification import NotificationType

# The channels the matrix gates. quiet hours suppress push + email only;
# in_app is the feed row and is written whenever its channel is on.
CHANNELS = ("in_app", "push", "email")

# The kinds the prefs matrix covers; the task-reminder types predate it.
GAME_KINDS = (
    NotificationType.HABIT_REMINDER,
    NotificationType.DAILY_REMINDER,
    NotificationType.STREAK_RISK,
    NotificationType.LOW_HP,
    NotificationType.DAILY_MISSED,
    NotificationType.DEATH,
    NotificationType.PHASE_END,
    NotificationType.LEVEL_UP,
    NotificationType.ACHIEVEMENT,
    NotificationType.RECORD,
)

# Prefs keys are the lowercase enum values (matches the model docstring).
KIND_KEYS = frozenset(k.value.lower() for k in GAME_KINDS)
