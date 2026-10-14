from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from projects.models import Issue, IssueComment
from accounts.models import User
from .models import Notification
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


def send_notification_to_user(user_id, notification_data):
    """Send notification via WebSocket"""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f'notifications_{user_id}',
        {
            'type': 'notification_message',
            'notification': notification_data
        }
    )


@receiver(post_save, sender=Issue)
def create_issue_notifications(sender, instance, created, **kwargs):
    """Create notifications when issue is created or updated"""
    
    if created:
        # New issue - notify admin, managers, assigned employee, and all project team members
        admins = User.objects.filter(role='admin')
        managers = instance.project.team_members.filter(project_role='manager').select_related('user')
        
        recipients = list(admins)
        recipients.extend([m.user for m in managers])
        
        # Add all project team members (employees)
        all_team_members = instance.project.team_members.select_related('user')
        recipients.extend([tm.user for tm in all_team_members])
        
        # Add assigned employee if exists
        if instance.assignee:
            recipients.append(instance.assignee)
        
        # Remove duplicates
        recipients = list(set(recipients))
        
        for user in recipients:
            # Different message for assigned employee vs team members
            if user == instance.assignee:
                notif = Notification.objects.create(
                    recipient=user,
                    notification_type='issue_assigned',
                    title='New Issue Assigned to You',
                    message=f'You have been assigned: "{instance.title}"',
                    icon='✅',
                    issue_id=instance.id
                )
                # Send via WebSocket
                send_notification_to_user(user.id, {
                    'id': notif.id,
                    'title': notif.title,
                    'message': notif.message,
                    'icon': notif.icon,
                    'read': notif.read,
                    'created_at': notif.created_at.isoformat(),
                    'issue_id': notif.issue_id,
                })
            elif user.role in ['admin', 'manager']:
                notif = Notification.objects.create(
                    recipient=user,
                    notification_type='issue_created',
                    title='New Issue Reported',
                    message=f'{instance.reported_by.username} reported: "{instance.title}"',
                    icon='🐛',
                    issue_id=instance.id
                )
                # Send via WebSocket
                send_notification_to_user(user.id, {
                    'id': notif.id,
                    'title': notif.title,
                    'message': notif.message,
                    'icon': notif.icon,
                    'read': notif.read,
                    'created_at': notif.created_at.isoformat(),
                    'issue_id': notif.issue_id,
                })
            else:
                # Team members (employees) get notification about new issue in their project
                notif = Notification.objects.create(
                    recipient=user,
                    notification_type='issue_created',
                    title='New Issue in Your Project',
                    message=f'New issue in {instance.project.name}: "{instance.title}"',
                    icon='📝',
                    issue_id=instance.id
                )
                # Send via WebSocket
                send_notification_to_user(user.id, {
                    'id': notif.id,
                    'title': notif.title,
                    'message': notif.message,
                    'icon': notif.icon,
                    'read': notif.read,
                    'created_at': notif.created_at.isoformat(),
                    'issue_id': notif.issue_id,
                })
    else:
        # Issue updated - check what changed
        
        # Assignee changed - notify new assignee
        if hasattr(instance, '_assignee_changed') and instance.assignee:
            notif = Notification.objects.create(
                recipient=instance.assignee,
                notification_type='issue_assigned',
                title='Issue Assigned to You',
                message=f'You have been assigned: "{instance.title}"',
                icon='✅',
                issue_id=instance.id
            )
            # Send via WebSocket
            send_notification_to_user(instance.assignee.id, {
                'id': notif.id,
                'title': notif.title,
                'message': notif.message,
                'icon': notif.icon,
                'read': notif.read,
                'created_at': notif.created_at.isoformat(),
                'issue_id': notif.issue_id,
            })
        
        # Status changed - notify admin, managers, client, and assigned employee
        if hasattr(instance, '_status_changed'):
            admins = User.objects.filter(role='admin')
            managers = instance.project.team_members.filter(project_role='manager').select_related('user')
            
            recipients = list(admins)
            recipients.extend([m.user for m in managers])
            
            # Add client (issue reporter) to recipients
            if instance.reported_by and instance.reported_by.role == 'client':
                recipients.append(instance.reported_by)
            
            # Add assigned employee to recipients
            if instance.assignee:
                recipients.append(instance.assignee)
            
            # Remove duplicates
            recipients = list(set(recipients))
            
            for user in recipients:
                # Different message for client vs admin/manager/employee
                if user.role == 'client':
                    if instance.status == 'Done':
                        Notification.objects.create(
                            recipient=user,
                            notification_type='issue_status_changed',
                            title='Issue Resolved',
                            message=f'Your issue "{instance.title}" has been completed!',
                            icon='✅',
                            issue_id=instance.id
                        )
                    else:
                        Notification.objects.create(
                            recipient=user,
                            notification_type='issue_status_changed',
                            title='Issue Update',
                            message=f'Your issue "{instance.title}" is now {instance.status}',
                            icon='🔄',
                            issue_id=instance.id
                        )
                elif user == instance.assignee:
                    # Assigned employee gets specific message
                    Notification.objects.create(
                        recipient=user,
                        notification_type='issue_status_changed',
                        title='Your Task Updated',
                        message=f'Your task "{instance.title}" is now {instance.status}',
                        icon='🔄',
                        issue_id=instance.id
                    )
                else:
                    Notification.objects.create(
                        recipient=user,
                        notification_type='issue_status_changed',
                        title='Status Updated',
                        message=f'"{instance.title}" moved to {instance.status}',
                        icon='🔄',
                        issue_id=instance.id
                    )


@receiver(pre_save, sender=Issue)
def track_issue_changes(sender, instance, **kwargs):
    """Track if status or assignee is being changed"""
    if instance.pk:
        try:
            old_issue = Issue.objects.get(pk=instance.pk)
            if old_issue.status != instance.status:
                instance._status_changed = True
            if old_issue.assignee != instance.assignee:
                instance._assignee_changed = True
                instance._old_assignee = old_issue.assignee
        except Issue.DoesNotExist:
            pass


@receiver(post_save, sender=IssueComment)
def create_comment_notification(sender, instance, created, **kwargs):
    """Notify issue reporter when someone comments"""
    if created and instance.issue.reported_by:
        # Don't notify if commenter is the reporter
        if instance.author != instance.issue.reported_by:
            Notification.objects.create(
                recipient=instance.issue.reported_by,
                notification_type='issue_comment',
                title='New Comment',
                message=f'{instance.author.username} commented on "{instance.issue.title}"',
                icon='💬',
                issue_id=instance.issue.id
            )
