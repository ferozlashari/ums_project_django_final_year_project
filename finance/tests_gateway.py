"""Tests for the Safepay hosted-checkout integration: hidden until
configured, real redirect when configured, and webhook-only confirmation
(the browser return page never itself confirms a payment)."""
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlparse
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from academics.models import Department, Faculty, Program
from finance.models import Invoice, Payment
from registration.models import Student


class GatewayBase(TestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name='Faculty')
        dept = Department.objects.create(name='CS', faculty=faculty)
        program = Program.objects.create(name='BSCS', code='BSCS', department=dept)
        u = User.objects.create_user('payer1', password='pw')
        self.student = Student.objects.create(user=u, full_name='Payer One', admission_no='PAY-1', program=program)
        self.invoice = Invoice.objects.create(student=self.student, category='semester', amount=25000)
        self.client.force_login(u)


class NotConfiguredTests(GatewayBase):
    def test_pay_page_hides_online_button_when_not_configured(self):
        resp = self.client.get(reverse('pay-now', args=[self.invoice.pk]))
        self.assertNotContains(resp, 'Pay 25000')
        self.assertContains(resp, 'Not configured yet')

    def test_checkout_redirects_back_with_a_clear_message_when_not_configured(self):
        resp = self.client.get(reverse('gateway-checkout', args=[self.invoice.pk]), follow=True)
        self.assertContains(resp, 'not configured')


ENV = {'SAFEPAY_API_KEY': 'sec_test', 'SAFEPAY_V1_SECRET': 'shared_secret',
       'SAFEPAY_WEBHOOK_SECRET': 'whsec', 'SAFEPAY_ENVIRONMENT': 'sandbox'}


def _fake_tracker_response(token='track_123'):
    r = mock.Mock(status_code=200)
    r.json.return_value = {'data': {'token': token}}
    r.raise_for_status = mock.Mock()
    return r


@mock.patch.dict('os.environ', ENV)
class ConfiguredCheckoutTests(GatewayBase):
    def test_pay_page_shows_the_real_pay_button_when_configured(self):
        resp = self.client.get(reverse('pay-now', args=[self.invoice.pk]))
        self.assertContains(resp, reverse('gateway-checkout', args=[self.invoice.pk]))

    def test_init_request_matches_safepays_documented_contract(self):
        with mock.patch('requests.post', return_value=_fake_tracker_response()) as post:
            self.client.get(reverse('gateway-checkout', args=[self.invoice.pk]))
        args, kwargs = post.call_args
        self.assertEqual(args[0] if args else kwargs['url'] if 'url' in kwargs else post.call_args[0][0],
                         'https://sandbox.api.getsafepay.com/order/v1/init')
        self.assertEqual(kwargs['json'], {'client': 'sec_test', 'amount': 25000.0,
                                          'currency': 'PKR', 'environment': 'sandbox'})

    def test_checkout_redirects_to_safepays_hosted_checkout_and_stores_tracker(self):
        with mock.patch('requests.post', return_value=_fake_tracker_response('track_abc')):
            resp = self.client.get(reverse('gateway-checkout', args=[self.invoice.pk]))
        self.assertEqual(resp.status_code, 302)
        u = urlparse(resp.url)
        self.assertEqual(f'{u.scheme}://{u.netloc}{u.path}', 'https://sandbox.api.getsafepay.com/checkout/pay')
        q = parse_qs(u.query)
        self.assertEqual(q['beacon'], ['track_abc'])
        self.assertEqual(q['env'], ['sandbox'])
        payment = Payment.objects.get(invoice=self.invoice, method='safepay')
        self.assertEqual(q['order_id'], [f'UMS-{payment.pk}'])
        self.assertEqual(payment.status, 'pending')
        self.assertTrue(payment.transactions.filter(provider_reference='track_abc').exists())

    def test_gateway_failure_never_fakes_success(self):
        with mock.patch('requests.post', side_effect=RuntimeError('boom')):
            resp = self.client.get(reverse('gateway-checkout', args=[self.invoice.pk]), follow=True)
        self.assertContains(resp, 'Could not reach the Safepay')
        self.assertFalse(Payment.objects.filter(invoice=self.invoice, status='confirmed').exists())

    def test_other_students_challan_is_forbidden(self):
        other = User.objects.create_user('payer2', password='pw')
        self.client.force_login(other)
        resp = self.client.get(reverse('gateway-checkout', args=[self.invoice.pk]))
        self.assertEqual(resp.status_code, 403)


class ReturnAndWebhookTests(GatewayBase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict('os.environ', ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        with mock.patch('requests.post', return_value=_fake_tracker_response('track_777')):
            self.client.get(reverse('gateway-checkout', args=[self.invoice.pk]))
        self.payment = Payment.objects.get(invoice=self.invoice, method='safepay')

    def _wh_body(self, **note):
        n = {'tracker': 'track_777', 'state': 'PAID', 'amount': '25000.00', 'currency': 'PKR'}
        n.update(note)
        return {'token': 'x', 'type': 'payment:created', 'data': {'notification': n}}

    def _post_wh(self, body, sig=None):
        raw = json.dumps(body).encode()
        if sig is None:
            signed = json.dumps(body['data'], separators=(',', ':')).encode()
            sig = hmac.new(b'whsec', signed, hashlib.sha512).hexdigest()
        return self.client.post(reverse('gateway-webhook'), data=raw, content_type='application/json',
                                HTTP_X_SFPY_SIGNATURE=sig)

    # -- signed browser redirect (works on localhost) --------------------
    def test_return_with_valid_signature_confirms(self):
        sig = hmac.new(b'shared_secret', b'track_777', hashlib.sha256).hexdigest()
        self.client.get(reverse('gateway-return', args=[self.payment.pk]) + f'?tracker=track_777&sig={sig}')
        self.payment.refresh_from_db(); self.invoice.refresh_from_db()
        self.assertEqual(self.payment.status, 'confirmed')
        self.assertTrue(self.invoice.paid)

    def test_return_with_forged_signature_does_not_confirm(self):
        self.client.get(reverse('gateway-return', args=[self.payment.pk]) + '?tracker=track_777&sig=deadbeef')
        self.assertEqual(Payment.objects.get(pk=self.payment.pk).status, 'pending')

    def test_return_with_valid_sig_for_a_different_tracker_does_not_confirm(self):
        sig = hmac.new(b'shared_secret', b'track_OTHER', hashlib.sha256).hexdigest()
        self.client.get(reverse('gateway-return', args=[self.payment.pk]) + f'?tracker=track_OTHER&sig={sig}')
        self.assertEqual(Payment.objects.get(pk=self.payment.pk).status, 'pending')

    def test_plain_return_page_never_confirms(self):
        self.client.get(reverse('gateway-return', args=[self.payment.pk]))
        self.assertEqual(Payment.objects.get(pk=self.payment.pk).status, 'pending')

    # -- webhook ----------------------------------------------------------
    def test_unsigned_webhook_rejected(self):
        self.assertEqual(self._post_wh(self._wh_body(), sig='nope').status_code, 400)
        self.assertEqual(Payment.objects.get(pk=self.payment.pk).status, 'pending')

    def test_old_sha256_signature_scheme_is_rejected(self):
        body = self._wh_body()
        wrong = hmac.new(b'whsec', json.dumps(body).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(self._post_wh(body, sig=wrong).status_code, 400)

    def test_signed_paid_webhook_confirms_and_notifies_once(self):
        from core.models import Notification
        self.assertEqual(self._post_wh(self._wh_body()).status_code, 200)
        self.assertEqual(self._post_wh(self._wh_body()).status_code, 200)   # retry
        self.payment.refresh_from_db(); self.invoice.refresh_from_db()
        self.assertEqual(self.payment.status, 'confirmed')
        self.assertTrue(self.invoice.paid)
        self.assertEqual(Notification.objects.filter(title__startswith='Payment received').count(), 1)

    def test_non_paid_state_does_not_confirm(self):
        self.assertEqual(self._post_wh(self._wh_body(state='FAILED')).status_code, 200)
        self.assertEqual(Payment.objects.get(pk=self.payment.pk).status, 'pending')

    def test_amount_mismatch_is_not_confirmed_and_raises_an_exception(self):
        from core.models import ExceptionRecord
        self.assertEqual(self._post_wh(self._wh_body(amount='1.00')).status_code, 200)
        self.assertEqual(Payment.objects.get(pk=self.payment.pk).status, 'pending')
        self.assertTrue(ExceptionRecord.objects.filter(code='PAYMENT_AMOUNT_MISMATCH').exists())

    def test_unknown_tracker_is_acknowledged_and_ignored(self):
        self.assertEqual(self._post_wh(self._wh_body(tracker='track_unknown')).status_code, 200)
        self.assertEqual(Payment.objects.get(pk=self.payment.pk).status, 'pending')
