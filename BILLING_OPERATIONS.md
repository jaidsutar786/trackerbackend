# Workspace Billing Operations

## Stripe Configuration

The application keeps paid billing disabled until all required values are configured in the backend environment:

```text
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_PAID=
FRONTEND_URL=https://your-frontend.example
```

Create a recurring Stripe Price for the paid plan and set its Price ID as `STRIPE_PRICE_PAID`. The API creates a Stripe customer per workspace, starts subscription Checkout, and opens the Stripe customer portal for billing management. Never put Stripe secrets in frontend variables or commit them to source control.

Configure a Stripe webhook to call:

```text
https://your-api.example/api/auth/workspace/billing/webhook/
```

Subscribe to `checkout.session.completed`, `customer.subscription.updated`, and `customer.subscription.deleted`. The endpoint validates the `Stripe-Signature` against `STRIPE_WEBHOOK_SECRET`; failed processing returns an error so Stripe can retry delivery.

## Plans and Limits

The application currently defines these server-side limits:

- Free: 5 active seats and 3 projects
- Trial: 10 active seats and 10 projects for 14 days
- Paid: 100 active seats and 100 projects

Trial expiry uses free-plan limits automatically. The limits are constants in `accounts.models.Workspace.PLAN_LIMITS` and should be aligned with the commercial offer before launch.

## Local Development

With Stripe settings absent, trial, usage, permissions, and free-plan caps continue to work. Checkout and billing portal return a service-unavailable response; no subscription is simulated. Use Stripe test-mode secret, price, and webhook signing secret to exercise payment flows before production.
