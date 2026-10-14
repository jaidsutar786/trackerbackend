import logging
from datetime import datetime, timedelta, timezone as dt_timezone

import stripe
from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Workspace


logger = logging.getLogger(__name__)


def stripe_is_configured():
    return bool(settings.STRIPE_SECRET_KEY)


def _workspace_from_stripe_object(payload):
    metadata = payload.get('metadata') or {}
    workspace_id = metadata.get('workspace_id')
    if workspace_id:
        workspace = Workspace.objects.filter(pk=workspace_id).first()
        if workspace:
            return workspace
    customer_id = payload.get('customer')
    if customer_id:
        return Workspace.objects.filter(billing_customer_id=customer_id).first()
    return None


def handle_stripe_event(event):
    event_type = event.get('type')
    payload = event.get('data', {}).get('object', {})

    if event_type == 'checkout.session.completed':
        workspace = _workspace_from_stripe_object(payload)
        if not workspace:
            logger.error('Stripe checkout event has no matching workspace.')
            return
        workspace.billing_customer_id = payload.get('customer') or workspace.billing_customer_id
        workspace.billing_subscription_id = payload.get('subscription') or workspace.billing_subscription_id
        workspace.plan = 'paid'
        workspace.subscription_status = 'active'
        workspace.save(update_fields=[
            'billing_customer_id',
            'billing_subscription_id',
            'plan',
            'subscription_status',
            'updated_at',
        ])
        return

    if event_type not in ('customer.subscription.updated', 'customer.subscription.deleted'):
        return

    workspace = _workspace_from_stripe_object(payload)
    if not workspace:
        logger.error('Stripe subscription event has no matching workspace.')
        return

    status_map = {
        'active': 'active',
        'trialing': 'trialing',
        'past_due': 'past_due',
        'canceled': 'canceled',
        'unpaid': 'canceled',
        'incomplete': 'past_due',
        'incomplete_expired': 'canceled',
    }
    subscription_status = 'canceled' if event_type == 'customer.subscription.deleted' else status_map.get(
        payload.get('status'), 'canceled'
    )
    workspace.subscription_status = subscription_status
    workspace.plan = 'free' if subscription_status == 'canceled' else 'paid'
    workspace.billing_subscription_id = payload.get('id') or workspace.billing_subscription_id
    period_end = payload.get('current_period_end')
    workspace.current_period_end = datetime.fromtimestamp(
        period_end, tz=dt_timezone.utc
    ) if period_end else None
    workspace.save(update_fields=[
        'subscription_status',
        'plan',
        'billing_subscription_id',
        'current_period_end',
        'updated_at',
    ])


class StartWorkspaceTrialView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'admin' or not request.user.workspace_id:
            return Response({'error': 'Only a workspace admin can start a trial.'}, status=403)
        workspace = Workspace.objects.get(pk=request.user.workspace_id)
        if workspace.plan != 'free' or workspace.subscription_status != 'active':
            return Response({'error': 'A trial is only available to free workspaces.'}, status=409)
        workspace.plan = 'trial'
        workspace.subscription_status = 'trialing'
        workspace.trial_ends_at = timezone.now() + timedelta(days=14)
        workspace.save(update_fields=['plan', 'subscription_status', 'trial_ends_at', 'updated_at'])
        return Response({
            'plan': workspace.effective_plan,
            'subscription_status': workspace.subscription_status,
            'trial_ends_at': workspace.trial_ends_at,
            'seat_limit': workspace.seat_limit,
            'project_limit': workspace.project_limit,
        }, status=200)


class CreateCheckoutSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        workspace = request.user.workspace
        if request.user.role != 'admin' or not workspace:
            return Response({'error': 'Only a workspace admin can manage billing.'}, status=403)
        if not stripe_is_configured() or not settings.STRIPE_PRICE_PAID:
            return Response({'error': 'Paid billing is not configured for this environment.'}, status=503)

        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            if not workspace.billing_customer_id:
                customer = stripe.Customer.create(
                    email=workspace.billing_email or request.user.email,
                    name=workspace.name,
                    metadata={'workspace_id': str(workspace.pk)},
                )
                workspace.billing_customer_id = customer.id
                workspace.save(update_fields=['billing_customer_id', 'updated_at'])

            session = stripe.checkout.Session.create(
                mode='subscription',
                customer=workspace.billing_customer_id,
                line_items=[{'price': settings.STRIPE_PRICE_PAID, 'quantity': 1}],
                success_url=f'{settings.FRONTEND_URL.rstrip("/")}/settings?billing=success',
                cancel_url=f'{settings.FRONTEND_URL.rstrip("/")}/settings?billing=cancelled',
                metadata={'workspace_id': str(workspace.pk), 'plan': 'paid'},
                subscription_data={'metadata': {'workspace_id': str(workspace.pk), 'plan': 'paid'}},
            )
        except stripe.StripeError:
            logger.exception('Stripe checkout session creation failed for workspace %s.', workspace.pk)
            return Response({'error': 'Unable to start checkout. Please try again later.'}, status=502)
        return Response({'url': session.url})


class CreateBillingPortalView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        workspace = request.user.workspace
        if request.user.role != 'admin' or not workspace:
            return Response({'error': 'Only a workspace admin can manage billing.'}, status=403)
        if not stripe_is_configured():
            return Response({'error': 'Paid billing is not configured for this environment.'}, status=503)
        if not workspace.billing_customer_id:
            return Response({'error': 'This workspace has no billing customer yet.'}, status=409)

        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            session = stripe.billing_portal.Session.create(
                customer=workspace.billing_customer_id,
                return_url=f'{settings.FRONTEND_URL.rstrip("/")}/settings',
            )
        except stripe.StripeError:
            logger.exception('Stripe billing portal creation failed for workspace %s.', workspace.pk)
            return Response({'error': 'Unable to open billing management. Please try again later.'}, status=502)
        return Response({'url': session.url})


class StripeWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if not settings.STRIPE_WEBHOOK_SECRET:
            return Response({'error': 'Billing webhook is not configured.'}, status=503)
        signature = request.headers.get('Stripe-Signature', '')
        try:
            event = stripe.Webhook.construct_event(
                request.body,
                signature,
                settings.STRIPE_WEBHOOK_SECRET,
            )
        except (ValueError, stripe.SignatureVerificationError):
            return Response({'error': 'Invalid webhook signature or payload.'}, status=400)

        handle_stripe_event(event)
        return Response({'received': True})