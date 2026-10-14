from django.urls import path
from .views import (
    NotificationListView, NotificationMarkReadView,
    NotificationMarkAllReadView, NotificationDeleteView,
    NotificationSummaryView, NotificationPreferenceView,
)

urlpatterns = [
    path('', NotificationListView.as_view(), name='notification-list'),
    path('summary/', NotificationSummaryView.as_view(), name='notification-summary'),
    path('preferences/', NotificationPreferenceView.as_view(), name='notification-preferences'),
    path('<int:pk>/read/', NotificationMarkReadView.as_view(), name='notification-mark-read'),
    path('mark-all-read/', NotificationMarkAllReadView.as_view(), name='notification-mark-all-read'),
    path('<int:pk>/delete/', NotificationDeleteView.as_view(), name='notification-delete'),
]
