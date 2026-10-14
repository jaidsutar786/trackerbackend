from django.contrib import admin
from .models import Client, Project, ProjectMember, Issue, IssueScreenshot, IssueComment, ActivityLog, Feature, Task, TaskCommentAttachment

admin.site.register(Client)
admin.site.register(Project)
admin.site.register(ProjectMember)
admin.site.register(Feature)
admin.site.register(Task)
admin.site.register(Issue)
admin.site.register(IssueScreenshot)
admin.site.register(IssueComment)
admin.site.register(TaskCommentAttachment)
admin.site.register(ActivityLog)
