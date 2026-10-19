"""Provider-neutral payment gateway contracts.

Real merchant credentials are supplied only through environment variables.
No provider credential is hard-coded and no successful payment is trusted
until its signed/server-side callback is verified.
"""
import hashlib
import hmac
import os
from decimal import Decimal
from django.db import transaction
from .models import Payment, PaymentTransaction


class PaymentProvider:
    name = 'base'
    def initiate(self, payment, return_url):
        raise NotImplementedError
    def verify_callback(self, payload, signature):
        raise NotImplementedError


class ConfiguredHMACProvider(PaymentProvider):
    secret_env = ''
    name = 'generic'
    def __init__(self, name, secret_env):
        self.name, self.secret_env = name, secret_env
    @property
    def secret(self):
        return os.environ.get(self.secret_env, '')
    def initiate(self, payment, return_url):
        if not self.secret:
            raise RuntimeError(f'{self.name} payment provider is not configured.')
        return {'provider': self.name, 'payment_id': payment.pk, 'amount': str(payment.amount), 'return_url': return_url}
    def verify_callback(self, payload, signature):
        if not self.secret: return False
        message = '&'.join(f'{k}={payload[k]}' for k in sorted(payload))
        expected = hmac.new(self.secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature or '')


class SafepayProvider(PaymentProvider):
    """Real hosted checkout via Safepay (getsafepay.com).

    Contract taken from Safepay's own official SDK (safepay-python):
      * POST {api}/order/v1/init  {client, amount, currency, environment}
        -> data.token  (the "tracker")
      * Browser is sent to {checkout}/pay?beacon=<tracker>&order_id=..&
        redirect_url=..&cancel_url=..&env=..&source=..&webhooks=..
      * After a successful payment Safepay redirects the browser back with
        `tracker` and `sig`; sig = HMAC-SHA256(shared secret, tracker).
      * Server-to-server webhook: header `x-sfpy-signature` =
        HMAC-SHA512(webhook secret, compact-JSON(body["data"])).

    Credentials come only from environment variables:
      SAFEPAY_API_KEY         public/client key ("sec_..." in the dashboard)
      SAFEPAY_V1_SECRET       "Shared secret" (verifies the redirect `sig`)
      SAFEPAY_WEBHOOK_SECRET  webhook secret (verifies webhooks)
      SAFEPAY_ENVIRONMENT     sandbox | production
    SAFEPAY_SECRET_KEY is accepted as a legacy alias for SAFEPAY_V1_SECRET.
    """
    name = 'safepay'
    API_BASE = {
        'sandbox': 'https://sandbox.api.getsafepay.com',
        'production': 'https://api.getsafepay.com',
    }
    CHECKOUT_BASE = {
        'sandbox': 'https://sandbox.api.getsafepay.com/checkout/pay',
        'production': 'https://getsafepay.com/checkout/pay',
    }

    @property
    def api_key(self):
        return os.environ.get('SAFEPAY_API_KEY', '')

    @property
    def v1_secret(self):
        return os.environ.get('SAFEPAY_V1_SECRET', '') or os.environ.get('SAFEPAY_SECRET_KEY', '')

    @property
    def webhook_secret(self):
        return os.environ.get('SAFEPAY_WEBHOOK_SECRET', '')

    @property
    def environment(self):
        return 'production' if os.environ.get('SAFEPAY_ENVIRONMENT', 'sandbox').strip().lower() == 'production' else 'sandbox'

    def is_configured(self):
        return bool(self.api_key and self.v1_secret)

    def create_tracker(self, amount):
        """Ask Safepay for a payment tracker. Amount is in PKR (major units)."""
        import requests
        if not self.is_configured():
            raise RuntimeError('Safepay is not configured (SAFEPAY_API_KEY / SAFEPAY_V1_SECRET missing).')
        resp = requests.post(
            f'{self.API_BASE[self.environment]}/order/v1/init', timeout=20,
            json={'client': self.api_key, 'amount': float(Decimal(str(amount))),
                  'currency': 'PKR', 'environment': self.environment},
            headers={'Content-Type': 'application/json'},
        )
        resp.raise_for_status()
        try:
            return resp.json()['data']['token']
        except (KeyError, TypeError, ValueError):
            raise RuntimeError('Safepay returned an unexpected response while creating the payment.')

    def checkout_url(self, tracker, order_id, redirect_url, cancel_url):
        from urllib.parse import urlencode
        params = urlencode({
            'beacon': tracker, 'cancel_url': cancel_url, 'env': self.environment,
            'order_id': order_id, 'redirect_url': redirect_url,
            'source': 'custom', 'webhooks': 'true',
        })
        return f'{self.CHECKOUT_BASE[self.environment]}?{params}'

    def initiate(self, payment, return_url, cancel_url=None):
        """Create a tracker + build the official hosted-checkout URL. The
        tracker is stored on the PaymentTransaction so the redirect and the
        webhook can both find this payment later."""
        tracker = self.create_tracker(payment.amount)
        PaymentTransaction.objects.filter(payment=payment).update(
            provider_reference=tracker, status='pending',
        )
        return {
            'provider': self.name, 'payment_id': payment.pk, 'tracker_token': tracker,
            'checkout_url': self.checkout_url(tracker, f'UMS-{payment.pk}', return_url, cancel_url or return_url),
        }

    # -- verification ----------------------------------------------------
    def verify_redirect_signature(self, tracker, sig):
        if not (self.v1_secret and tracker and sig):
            return False
        expected = hmac.new(self.v1_secret.encode(), tracker.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)

    def verify_webhook(self, raw_body, signature):
        """Returns the parsed body dict when the signature is valid, else None."""
        import json
        if not (self.webhook_secret and signature):
            return None
        try:
            body = json.loads(raw_body)
        except (ValueError, TypeError):
            return None
        signed = body.get('data', body) if isinstance(body, dict) else body
        payload = json.dumps(signed, separators=(',', ':'))
        expected = hmac.new(self.webhook_secret.encode(), payload.encode(), hashlib.sha512).hexdigest()
        return body if hmac.compare_digest(expected, signature) else None


def provider_for(name):
    providers = {
        'jazzcash': ConfiguredHMACProvider('jazzcash', 'JAZZCASH_HASH_KEY'),
        'easypaisa': ConfiguredHMACProvider('easypaisa', 'EASYPAISA_HASH_KEY'),
        'bank': ConfiguredHMACProvider('bank', 'BANK_API_SECRET'),
        'card': ConfiguredHMACProvider('card', 'CARD_GATEWAY_SECRET'),
        'safepay': SafepayProvider(),
    }
    if name not in providers: raise ValueError('Unsupported payment provider.')
    return providers[name]


@transaction.atomic
def create_payment(invoice, amount, method, idempotency_key):
    amount = Decimal(str(amount))
    outstanding = invoice.amount - sum((p.amount for p in invoice.payments.filter(status='confirmed')), Decimal('0'))
    if amount <= 0 or amount > outstanding:
        raise ValueError('Payment amount must be greater than zero and cannot exceed the outstanding invoice balance.')
    payment, created = Payment.objects.get_or_create(invoice=invoice, transaction_id=idempotency_key, defaults={'amount': amount, 'method': method, 'status':'pending'})
    if not created and payment.amount != amount:
        raise ValueError('Idempotency key was already used with a different amount.')
    PaymentTransaction.objects.get_or_create(payment=payment, idempotency_key=idempotency_key, defaults={'provider': method, 'status':'initiated'})
    return payment
