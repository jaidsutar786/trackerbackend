from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from projects.models import Issue, IssueComment, Project, ProjectMember, Feature, Task, SubTask
from accounts.models import User
from .models import Notification, NotificationPreference
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


def send_ws(user_id, data):
    try:
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(
            f'notifications_{user_id}',
            {'type': 'notification_message', 'notification': data}
        )
    except Exception as e:
        print(f"WS error: {e}")


def send_data_update(user_id, entity, action, data=None):
    try:
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(
            f'notifications_{user_id}',
            {'type': 'data_update', 'entity': entity, 'action': action, 'data': data or {}}
        )
    except Exception as e:
        print(f"WS data_update error: {e}")


def build_notification_links(issue=None, project=None, feature=None, task=None, subtask=None):
    return {
        'issue': {
            'id': issue.id,
            'title': issue.title,
            'status': issue.status,
            'priority': issue.priority,
            'project_id': issue.project_id,
        } if issue else None,
        'project': {
            'id': project.id,
            'name': project.name,
            'slug': project.slug,
            'project_key': project.project_key,
        } if project else None,
        'feature': {
            'id': feature.id,
            'feature_id': feature.feature_id,
            'title': feature.title,
            'status': feature.status,
            'project_id': feature.project_id,
            'module_id': feature.module_id,
        } if feature else None,
        'task': {
            'id': task.id,
            'task_id': task.task_id,
            'title': task.title,
            'status': task.status,
            'priority': task.priority,
            'project_id': task.project_id,
            'feature_id': task.feature_id,
            'module_id': task.module_id,
        } if task else None,
        'subtask': {
            'id': subtask.id,
            'title': subtask.title,
            'status': subtask.status,
            'priority': subtask.priority,
            'task_id': subtask.task_id,
            'task_title': subtask.task.title,
            'project_id': subtask.task.project_id,
        } if subtask else None,
    }


def notify(recipient, ntype, title, message, icon='',
           issue_id=None, project_id=None, feature_id=None, task_id=None, subtask_id=None,
           actor=None):
    preference, _ = NotificationPreference.objects.get_or_create(user=recipient)
    if not preference.allows(ntype):
        return None

    issue = Issue.objects.filter(pk=issue_id).first() if issue_id else None
    project = issue.project if issue else None
    if project_id:
        project = project or Project.objects.filter(pk=project_id).first()
    feature = None
    if feature_id:
        feature_lookup = Feature.objects.filter(feature_id=feature_id)
        if project:
            feature_lookup = feature_lookup.filter(project=project)
        feature = feature_lookup.first()
    task = None
    if task_id:
        task_lookup = Task.objects.filter(task_id=task_id)
        if project:
            task_lookup = task_lookup.filter(project=project)
        task = task_lookup.first()
    subtask = None
    if subtask_id:
        subtask = SubTask.objects.filter(pk=subtask_id).first()
        if subtask and not project:
            project = subtask.task.project
        if subtask and not task:
            task = subtask.task

    recent_duplicate = Notification.objects.filter(
        recipient=recipient,
        notification_type=ntype,
        title=title,
        message=message,
        issue=issue,
        project=project,
        feature=feature,
        task=task,
        subtask=subtask,
        created_at__gte=timezone.now() - timedelta(seconds=10),
    ).first()
    if recent_duplicate:
        return recent_duplicate

    notif = Notification.objects.create(
        recipient=recipient,
        notification_type=ntype,
        title=title,
        message=message,
        icon=icon,
        issue=issue,
        project=project,
        feature=feature,
        task=task,
        subtask=subtask,
        actor=actor,
    )
    if preference.in_app_enabled:
        send_ws(recipient.id, {
            'id':         notif.id,
            'title':      notif.title,
            'message':    notif.message,
            'icon':       '',
            'read':       notif.read,
            'created_at': notif.created_at.isoformat(),
            'type':       'direct',
            'issue_id':   issue_id,
            'project_id': project_id,
            'feature_id': feature_id,
            'task_id':    task_id,
            'subtask_id': subtask_id,
            'actor_name': (actor.get_full_name() or actor.username) if actor else None,
            'actor_role': actor.role if actor else None,
        } | build_notification_links(issue=issue, project=project, feature=feature, task=task, subtask=subtask))
    return notif


# ─── 1. Project Member Added ──────────────────────────────────────────────────

@receiver(post_save, sender=ProjectMember)
def on_project_member_added(sender, instance, created, **kwargs):
    if not created:
        return
    notify(
        instance.user, 'project_assigned',
        f'You are assigned to {instance.project.name}',
        f'You have been added as {instance.get_project_role_display()} on project '
        f'"{instance.project.name}" ({instance.project.project_key}).',
        '', project_id=instance.project.id,
    )


# ─── 2. Feature Assigned ──────────────────────────────────────────────────────

@receiver(pre_save, sender=Feature)
def track_feature_changes(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = Feature.objects.get(pk=instance.pk)
            if old.assignee_id != instance.assignee_id:
                instance._assignee_changed = True
        except Feature.DoesNotExist:
            pass


@receiver(post_save, sender=Feature)
def on_feature_saved(sender, instance, created, **kwargs):
    if not instance.assignee:
        return
    if created or getattr(instance, '_assignee_changed', False):
        notify(
            instance.assignee, 'feature_assigned',
            f'Feature assigned to you: {instance.feature_id}',
            f'Feature "{instance.title}" ({instance.feature_id}) has been assigned to you '
            f'in project "{instance.project.name}".',
            '', project_id=instance.project.id, feature_id=instance.feature_id,
            actor=instance.reporter,
        )


# ─── 3. Task Assigned / Status Changed ───────────────────────────────────────

@receiver(pre_save, sender=Task)
def track_task_changes(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = Task.objects.get(pk=instance.pk)
            if old.assignee_id != instance.assignee_id:
                instance._assignee_changed = True
            if old.status != instance.status:
                instance._status_changed = True
                instance._old_status = old.status
        except Task.DoesNotExist:
            pass


@receiver(post_save, sender=Task)
def on_task_saved(sender, instance, created, **kwargs):
    project = instance.project
    feature = instance.feature

    if created and instance.assignee:
        # Handle both direct tasks (no feature) and feature tasks
        if feature:
            feature_text = f'in feature "{feature.title}" of project "{project.name}"'
            feature_id = feature.feature_id
        else:
            feature_text = f'in project "{project.name}"'
            feature_id = None
            
        notify(
            instance.assignee, 'task_assigned',
            f'Task assigned to you: {instance.task_id}',
            f'Task "{instance.title}" ({instance.task_id}) has been assigned to you '
            f'{feature_text}. '
            f'Priority: {instance.priority.capitalize()}.'
            + (f' Due: {instance.due_date}' if instance.due_date else ''),
            '', project_id=project.id, feature_id=feature_id,
            task_id=instance.task_id, actor=instance.reporter,
        )
        return

    if not created:
        if getattr(instance, '_assignee_changed', False) and instance.assignee:
            feature_id = feature.feature_id if feature else None
            notify(
                instance.assignee, 'task_assigned',
                f'Task assigned to you: {instance.task_id}',
                f'Task "{instance.title}" ({instance.task_id}) has been assigned to you '
                f'in project "{project.name}".',
                '', project_id=project.id, feature_id=feature_id,
                task_id=instance.task_id, actor=instance.reporter,
            )

        if getattr(instance, '_status_changed', False):
            managers = project.team_members.filter(project_role='manager').select_related('user')
            admins = User.objects.filter(role='admin', workspace=project.workspace)
            recipients = set(list(admins) + [m.user for m in managers])
            actor_name = instance.assignee.username if instance.assignee else 'Someone'
            old_status = getattr(instance, '_old_status', 'Unknown')
            feature_id = feature.feature_id if feature else None

            if instance.status == 'In Progress' and old_status == 'To Do':
                title = f'Task Started: {instance.task_id}'
                message = f'{actor_name} started working on task "{instance.title}" in project "{project.name}".'
            elif instance.status == 'Testing' and old_status == 'In Progress':
                title = f'Task Ready for Testing: {instance.task_id}'
                message = f'{actor_name} completed task "{instance.title}" and moved it to testing in project "{project.name}".'
            elif instance.status == 'Done':
                title = f'Task Completed: {instance.task_id}'
                message = f'{actor_name} completed task "{instance.title}" in project "{project.name}".'
            else:
                title = f'Task Status Changed: {instance.task_id}'
                message = f'{actor_name} changed status of task "{instance.title}" from {old_status} to {instance.status}.'

            for user in recipients:
                notify(
                    user, 'task_status_changed', title, message, '',
                    project_id=project.id, feature_id=feature_id,
                    task_id=instance.task_id, actor=instance.assignee,
                )


# ─── 4. Issue Signals ─────────────────────────────────────────────────────────

@receiver(pre_save, sender=Issue)
def track_issue_changes(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = Issue.objects.get(pk=instance.pk)
            if old.status != instance.status:
                instance._status_changed = True
                instance._old_status = old.status
            if old.assignee != instance.assignee:
                instance._assignee_changed = True
        except Issue.DoesNotExist:
            pass


@receiver(post_save, sender=Issue)
def on_issue_saved(sender, instance, created, **kwargs):
    iid  = instance.id
    pid  = instance.project_id
    proj = instance.project

    admins   = list(User.objects.filter(role='admin', workspace=proj.workspace))
    managers = [m.user for m in proj.team_members.filter(project_role='manager').select_related('user')]
    testers  = [t.user for t in proj.team_members.filter(user__role='qa_tester').select_related('user')]
    update_recipients = set(admins + managers + testers)

    def broadcast_update():
        for u in update_recipients:
            send_data_update(u.id, 'issue', 'updated', {'issue_id': iid, 'project_id': pid})
        if instance.reported_by and instance.reported_by.role == 'client':
            send_data_update(instance.reported_by.id, 'issue', 'updated', {'issue_id': iid, 'project_id': pid})

    if created:
        for user in update_recipients:
            msg = (f'{instance.reported_by.username} reported: "{instance.title}" — Please verify and assign to a developer.'
                   if user.role == 'qa_tester'
                   else f'{instance.reported_by.username} reported: "{instance.title}"')
            notify(user, 'issue_created', 'New Issue Reported', msg, '',
                   issue_id=iid, project_id=pid, actor=instance.reported_by)
            send_data_update(user.id, 'issue', 'created', {'issue_id': iid, 'project_id': pid})
        return

    old_status = getattr(instance, '_old_status', None)
    mgr_set    = set(admins + managers)
    actor      = instance.assignee.username if instance.assignee else 'Someone'

    if getattr(instance, '_assignee_changed', False) and instance.assignee:
        notify(
            instance.assignee, 'issue_assigned',
            'Issue Assigned to You',
            f'Issue "{instance.title}" has been assigned to you in project {proj.name}. Priority: {instance.priority.capitalize()}.',
            '', issue_id=iid, project_id=pid, actor=instance.assignee,
        )
        update_recipients.add(instance.assignee)
        broadcast_update()

    if not getattr(instance, '_status_changed', False):
        return

    if instance.status == 'In Progress' and old_status != 'Testing':
        for user in mgr_set:
            notify(user, 'issue_status_changed', 'Issue In Progress',
                   f'{actor} started working on "{instance.title}".',
                   '', issue_id=iid, project_id=pid, actor=instance.assignee)
        broadcast_update()

    elif instance.status == 'Testing':
        for t in proj.team_members.filter(user__role='qa_tester').select_related('user'):
            notify(t.user, 'issue_status_changed', 'Issue Ready for Testing',
                   f'{actor} completed "{instance.title}" and moved it to testing.',
                   '', issue_id=iid, project_id=pid, actor=instance.assignee)
        for user in mgr_set:
            notify(user, 'issue_status_changed', 'Issue In Testing',
                   f'"{instance.title}" is ready for QA testing.',
                   '', issue_id=iid, project_id=pid, actor=instance.assignee)
        broadcast_update()

    elif instance.status == 'Done':
        if instance.assignee:
            notify(instance.assignee, 'issue_status_changed', 'Issue Approved',
                   f'Your work on "{instance.title}" has been approved and marked as Done.',
                   '', issue_id=iid, project_id=pid)
        if instance.reported_by and instance.reported_by.role == 'client':
            notify(instance.reported_by, 'issue_status_changed', 'Issue Resolved',
                   f'Your issue "{instance.title}" has been resolved successfully.',
                   '', issue_id=iid, project_id=pid)
        for user in mgr_set:
            notify(user, 'issue_status_changed', 'Issue Closed',
                   f'"{instance.title}" has been marked as Done.',
                   '', issue_id=iid, project_id=pid, actor=instance.assignee)
        broadcast_update()

    elif instance.status == 'In Progress' and old_status == 'Testing':
        if instance.assignee:
            notify(instance.assignee, 'issue_status_changed', 'Issue Rejected',
                   f'Your work on "{instance.title}" was rejected by QA. Check the comments for the reason.',
                   '', issue_id=iid, project_id=pid)
        for user in mgr_set:
            notify(user, 'issue_status_changed', 'Issue Rejected by QA',
                   f'"{instance.title}" was rejected and sent back to In Progress.',
                   '', issue_id=iid, project_id=pid)
        broadcast_update()


@receiver(post_save, sender=IssueComment)
def on_comment(sender, instance, created, **kwargs):
    if created and instance.issue.reported_by and instance.author != instance.issue.reported_by:
        notify(instance.issue.reported_by, 'issue_comment',
               'New Comment',
               f'{instance.author.username} commented on "{instance.issue.title}"',
               '', issue_id=instance.issue.id, actor=instance.author)


# ─── 5. SubTask Signals ──────────────────────────────────────────────────────

@receiver(pre_save, sender=SubTask)
def track_subtask_changes(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = SubTask.objects.get(pk=instance.pk)
            if old.assignee_id != instance.assignee_id:
                instance._assignee_changed = True
            if old.status != instance.status:
                instance._status_changed = True
                instance._old_status = old.status
        except SubTask.DoesNotExist:
            pass


@receiver(post_save, sender=SubTask)
def on_subtask_saved(sender, instance, created, **kwargs):
    project = instance.task.project
    task = instance.task

    if created and instance.assignee:
        notify(
            instance.assignee, 'subtask_assigned',
            f'Sub-task assigned to you: {instance.title}',
            f'Sub-task "{instance.title}" has been assigned to you '
            f'in task "{task.title}" ({task.task_id}) of project "{project.name}". '
            f'Priority: {instance.priority.capitalize()}.',
            '', project_id=project.id, task_id=task.id,
            subtask_id=instance.id, actor=instance.created_by,
        )
        return

    if not created:
        if getattr(instance, '_assignee_changed', False) and instance.assignee:
            notify(
                instance.assignee, 'subtask_assigned',
                f'Sub-task assigned to you: {instance.title}',
                f'Sub-task "{instance.title}" has been assigned to you '
                f'in task "{task.title}" ({task.task_id}).',
                '', project_id=project.id, task_id=task.id,
                subtask_id=instance.id, actor=instance.created_by,
            )

        if getattr(instance, '_status_changed', False):
            managers = project.team_members.filter(project_role='manager').select_related('user')
            admins = User.objects.filter(role='admin', workspace=project.workspace)
            recipients = set(list(admins) + [m.user for m in managers])
            if instance.assignee:
                recipients.add(instance.assignee)
            
            actor_name = instance.assignee.username if instance.assignee else 'Someone'
            old_status = getattr(instance, '_old_status', 'Unknown')

            if instance.status == 'In Progress' and old_status == 'To Do':
                title = f'Sub-task Started: {instance.title}'
                message = f'{actor_name} started working on sub-task "{instance.title}" in task "{task.title}".'
            elif instance.status == 'Testing' and old_status == 'In Progress':
                title = f'Sub-task Ready for Testing: {instance.title}'
                message = f'{actor_name} completed sub-task "{instance.title}" and moved it to testing.'
            elif instance.status == 'Done':
                title = f'Sub-task Completed: {instance.title}'
                message = f'{actor_name} completed sub-task "{instance.title}" in task "{task.title}".'
            else:
                title = f'Sub-task Status Changed: {instance.title}'
                message = f'{actor_name} changed status of sub-task "{instance.title}" from {old_status} to {instance.status}.'

            for user in recipients:
                notify(
                    user, 'subtask_status_changed', title, message, '',
                    project_id=project.id, task_id=task.id,
                    subtask_id=instance.id, actor=instance.assignee,
                )
                # Also send data_update to refresh the board/dashboard for admins and managers
                if user.role in ['admin', 'manager']:
                    send_data_update(user.id, 'subtask', 'status_changed', {
                        'subtask_id': instance.id,
                        'subtask_title': instance.title,
                        'task_id': task.id,
                        'task_title': task.title,
                        'project_id': project.id,
                        'old_status': old_status,
                        'new_status': instance.status,
                    })
