from django.urls import path
from .billing import CreateBillingPortalView, CreateCheckoutSessionView, StartWorkspaceTrialView, StripeWebhookView
from .views import LoginView, MeView, UserListCreateView, UserDetailView, UserProfileStatsView, ResendInviteView, ForgotPasswordView, ResetPasswordView, WorkspaceSettingsView, WorkspaceUsageView

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('me/', MeView.as_view(), name='me'),
    path('workspace/', WorkspaceSettingsView.as_view(), name='workspace-settings'),
    path('workspace/usage/', WorkspaceUsageView.as_view(), name='workspace-usage'),
    path('workspace/trial/', StartWorkspaceTrialView.as_view(), name='workspace-trial'),
    path('workspace/billing/checkout/', CreateCheckoutSessionView.as_view(), name='workspace-billing-checkout'),
    path('workspace/billing/portal/', CreateBillingPortalView.as_view(), name='workspace-billing-portal'),
    path('workspace/billing/webhook/', StripeWebhookView.as_view(), name='workspace-billing-webhook'),
    path('users/', UserListCreateView.as_view(), name='user-list-create'),
    path('users/<int:pk>/', UserDetailView.as_view(), name='user-detail'),
    path('users/<int:pk>/resend-invite/', ResendInviteView.as_view(), name='resend-invite'),
    path('users/<int:pk>/profile-stats/', UserProfileStatsView.as_view(), name='user-profile-stats'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('reset-password/', ResetPasswordView.as_view(), name='reset-password'),
]
