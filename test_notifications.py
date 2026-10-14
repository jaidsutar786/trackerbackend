"""
Test Notification System

Run: python3 test_notifications.py

This will show:
1. If signals are working
2. If notifications are being created
3. Who is getting notifications
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from notifications.models import Notification
from projects.models import Issue
from accounts.models import User

print("=" * 60)
print("NOTIFICATION SYSTEM TEST")
print("=" * 60)

# Check total notifications
total = Notification.objects.count()
print(f"\n✓ Total Notifications in DB: {total}")

if total > 0:
    print("\n📋 Recent Notifications:")
    print("-" * 60)
    for notif in Notification.objects.all()[:10]:
        status = "✓ Read" if notif.read else "● Unread"
        print(f"{status} | {notif.recipient.username} ({notif.recipient.role})")
        print(f"   {notif.icon} {notif.title}")
        print(f"   {notif.message}")
        print(f"   Created: {notif.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print("-" * 60)
else:
    print("\n⚠ No notifications found!")
    print("\nPossible reasons:")
    print("1. Signals not registered (check notifications/apps.py)")
    print("2. No issues created/updated yet")
    print("3. Migration not run")

# Check recent issues
print("\n📝 Recent Issues:")
print("-" * 60)
for issue in Issue.objects.all()[:5]:
    assignee_name = issue.assignee.username if issue.assignee else "Unassigned"
    print(f"Issue: {issue.title}")
    print(f"  Status: {issue.status}")
    print(f"  Assignee: {assignee_name}")
    print(f"  Reporter: {issue.reported_by.username}")
    print("-" * 60)

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)
