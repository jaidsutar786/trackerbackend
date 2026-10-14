#!/usr/bin/env python
"""
WebSocket Notification System - Verification Script
Ye script tumhare complete notification system ko test karega
"""

import os
import django
import sys

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth import get_user_model
from projects.models import Project, Issue
from notifications.models import Notification

User = get_user_model()

def print_header(text):
    print("\n" + "="*60)
    print(f"  {text}")
    print("="*60)

def print_success(text):
    print(f"✅ {text}")

def print_error(text):
    print(f"❌ {text}")

def print_info(text):
    print(f"ℹ️  {text}")

def check_configuration():
    """Check Django configuration"""
    print_header("1. Configuration Check")
    
    from django.conf import settings
    
    # Check INSTALLED_APPS
    required_apps = ['daphne', 'channels', 'notifications']
    for app in required_apps:
        if app in settings.INSTALLED_APPS:
            print_success(f"{app} installed")
        else:
            print_error(f"{app} NOT installed")
    
    # Check ASGI_APPLICATION
    if hasattr(settings, 'ASGI_APPLICATION'):
        print_success(f"ASGI_APPLICATION: {settings.ASGI_APPLICATION}")
    else:
        print_error("ASGI_APPLICATION not configured")
    
    # Check CHANNEL_LAYERS
    if hasattr(settings, 'CHANNEL_LAYERS'):
        backend = settings.CHANNEL_LAYERS['default']['BACKEND']
        print_success(f"Channel Layer: {backend}")
    else:
        print_error("CHANNEL_LAYERS not configured")

def check_models():
    """Check database models"""
    print_header("2. Database Models Check")
    
    # Check User model
    user_count = User.objects.count()
    print_info(f"Total Users: {user_count}")
    
    # Check roles
    for role in ['admin', 'manager', 'client']:
        count = User.objects.filter(role=role).count()
        print_info(f"  - {role.capitalize()}: {count}")
    
    # Check Projects
    project_count = Project.objects.count()
    print_info(f"Total Projects: {project_count}")
    
    # Check Issues
    issue_count = Issue.objects.count()
    print_info(f"Total Issues: {issue_count}")
    
    # Check Notifications
    notif_count = Notification.objects.count()
    print_info(f"Total Notifications: {notif_count}")
    
    if notif_count > 0:
        unread = Notification.objects.filter(read=False).count()
        print_info(f"  - Unread: {unread}")
        print_info(f"  - Read: {notif_count - unread}")

def check_signals():
    """Check if signals are registered"""
    print_header("3. Signal Registration Check")
    
    from django.db.models.signals import post_save, pre_save
    
    # Check Issue signals
    issue_receivers = post_save._live_receivers(Issue)
    if issue_receivers:
        print_success(f"Issue post_save signal: {len(issue_receivers)} receiver(s)")
    else:
        print_error("Issue post_save signal: No receivers")
    
    pre_save_receivers = pre_save._live_receivers(Issue)
    if pre_save_receivers:
        print_success(f"Issue pre_save signal: {len(pre_save_receivers)} receiver(s)")
    else:
        print_error("Issue pre_save signal: No receivers")

def check_websocket_routing():
    """Check WebSocket routing"""
    print_header("4. WebSocket Routing Check")
    
    try:
        from notifications.routing import websocket_urlpatterns
        print_success(f"WebSocket routes: {len(websocket_urlpatterns)} pattern(s)")
        for pattern in websocket_urlpatterns:
            print_info(f"  - {pattern.pattern}")
    except Exception as e:
        print_error(f"Routing error: {e}")

def check_consumer():
    """Check WebSocket consumer"""
    print_header("5. WebSocket Consumer Check")
    
    try:
        from notifications.consumers import NotificationConsumer
        print_success("NotificationConsumer imported successfully")
        
        # Check methods
        methods = ['connect', 'disconnect', 'receive', 'notification_message']
        for method in methods:
            if hasattr(NotificationConsumer, method):
                print_success(f"  - {method}() method exists")
            else:
                print_error(f"  - {method}() method missing")
    except Exception as e:
        print_error(f"Consumer error: {e}")

def test_notification_creation():
    """Test notification creation"""
    print_header("6. Notification Creation Test")
    
    try:
        # Get a test user
        user = User.objects.filter(role='admin').first()
        if not user:
            user = User.objects.first()
        
        if not user:
            print_error("No users found in database")
            return
        
        print_info(f"Test user: {user.username} ({user.role})")
        
        # Create test notification
        notif = Notification.objects.create(
            recipient=user,
            notification_type='test',
            title='Test Notification',
            message='This is a test notification',
            icon='🧪'
        )
        
        print_success(f"Created notification ID: {notif.id}")
        
        # Delete test notification
        notif.delete()
        print_success("Test notification cleaned up")
        
    except Exception as e:
        print_error(f"Notification creation failed: {e}")

def show_sample_users():
    """Show sample users for testing"""
    print_header("7. Sample Users for Testing")
    
    users = User.objects.all()[:5]
    if users:
        print_info("Use these credentials to test:")
        for user in users:
            print(f"  📧 {user.email} | Role: {user.role}")
    else:
        print_error("No users found")

def show_instructions():
    """Show testing instructions"""
    print_header("8. Testing Instructions")
    
    print("""
🚀 How to Test Your WebSocket Notification System:

STEP 1: Start Daphne Server
  cd backend
  source venv/bin/activate
  daphne -b 0.0.0.0 -p 8000 core.asgi_routing:application

STEP 2: Start React Frontend
  npm run dev

STEP 3: Test WebSocket Connection
  - Login to your app
  - Open browser console (F12)
  - Look for: "✅ WebSocket Connected"

STEP 4: Test Notifications
  A. Create New Issue (as Client)
     → Admin, Managers, Team Members should get notification
  
  B. Assign Issue (as Admin/Manager)
     → Assigned employee should get notification
  
  C. Change Status (as Admin/Manager/Employee)
     → Admin, Managers, Client, Assignee should get notification
  
  D. Add Comment (as anyone)
     → Issue reporter should get notification

STEP 5: Check Browser Console
  - Look for "📨 WebSocket Message:" logs
  - Verify notification appears in UI
  - Check browser notification (if permission granted)

STEP 6: Check Database
  python manage.py shell
  >>> from notifications.models import Notification
  >>> Notification.objects.all()
    """)

def main():
    print("\n" + "🔍 WebSocket Notification System - Verification Report".center(60))
    
    try:
        check_configuration()
        check_models()
        check_signals()
        check_websocket_routing()
        check_consumer()
        test_notification_creation()
        show_sample_users()
        show_instructions()
        
        print_header("✅ Verification Complete!")
        print("\nYour WebSocket notification system is ready to test! 🎉\n")
        
    except Exception as e:
        print_error(f"Verification failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
