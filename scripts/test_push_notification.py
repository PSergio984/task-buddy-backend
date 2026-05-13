import asyncio
import os
import sys

# Add the current directory to sys.path so we can import app
sys.path.append(os.getcwd())

from app.config import config
from app.tasks import _send_push_notification_async


async def test_push(user_id: int):
    print("--- Push Notification Delivery Test ---")
    print(f"Target User ID: {user_id}")
    print(f"VAPID Public Key:  {config.VAPID_PUBLIC_KEY[:15]}..." if config.VAPID_PUBLIC_KEY else "None")
    print(f"VAPID Private Key: {'Set (Hidden)' if config.VAPID_PRIVATE_KEY else 'None'}")

    title = "🔔 Test Notification"
    message = "If you're seeing this, push notifications are working correctly!"
    action_url = "/"

    try:
        print(f"Sending push notification to all subscriptions for user {user_id}...")
        await _send_push_notification_async(user_id, title, message, action_url)
        print("[DONE] Check your browser/device for the notification.")
    except Exception as e:
        print(f"[ERROR] Failed to send push notification: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_push_notification.py <user_id>")
        sys.exit(1)

    try:
        target_user_id = int(sys.argv[1])
    except ValueError:
        print("Error: User ID must be an integer.")
        sys.exit(1)

    asyncio.run(test_push(target_user_id))
