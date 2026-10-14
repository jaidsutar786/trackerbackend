from rest_framework.permissions import BasePermission


class WorkspaceModuleAccess(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        module = getattr(view, 'workspace_module', None)
        return module is None or user.has_workspace_permission(module)