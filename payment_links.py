"""Offline payment URLs from organisation-owned templates.

One configuration table and one link table keep provider choice independent of
HTTP adapters. Reads materialise links locally under an organisation lock, with
one stable random token per invoice and method. Template edits refresh the URL
without replacing that token. These tokens grant no access to FastAccounts.
"""
import re
import secrets
from string import Formatter
from urllib.parse import quote, urlsplit

from core_utils import audit, money, new_id
from database import get_database
from payment_links_repository import PaymentLinkRepository


class PaymentLinkService:
    FIELDS = {'invoice_total', 'invoice_due', 'invoice_number', 'invoice_id', 'token', 'currency'}

    def __init__(self, db=None):
        self.db = db or get_database()

    @staticmethod
    def _safe_url(url):
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme == 'https' and parsed.hostname and not parsed.username
                     and not parsed.password and parsed.port != 0)
        except ValueError:
            valid = False
        if not valid or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url) or '\\' in url:
            raise ValueError('Payment URL must be an absolute HTTPS URL without credentials or whitespace')

    @classmethod
    def _validate(cls, data):
        if data['provider'] not in {'everypay', 'linkpay', 'custom'}:
            raise ValueError('Unknown payment provider')
        data = dict(data, name=data['name'].strip(), url_template=data['url_template'].strip(), currency=data['currency'].strip().upper())
        if not data['name'] or len(data['name']) > 120 or not isinstance(data['enabled'], bool):
            raise ValueError('Payment method requires a name and an enabled boolean')
        if data['currency'] and not re.fullmatch('[A-Z]{3}', data['currency']):
            raise ValueError('Payment currency must be three letters or empty')
        template = data['url_template']
        if not template or len(template) > 2000:
            raise ValueError('Payment URL template must contain between 1 and 2000 characters')
        try:
            for _, field, spec, conversion in Formatter().parse(template):
                if field is not None and (field not in cls.FIELDS or spec or conversion):
                    raise ValueError('Unsupported payment URL placeholder')
            parsed = urlsplit(template)
            if '{' in parsed.netloc or '}' in parsed.netloc or '{' in parsed.scheme:
                raise ValueError('Payment URL placeholders must be in the path, query or fragment')
            cls._safe_url(template.format(**{key: 'sample' for key in cls.FIELDS}))
        except (KeyError, IndexError):
            raise ValueError('Unsupported payment URL placeholder') from None
        return data

    def list_configs(self, organisation_id):
        with self.db.transaction() as tx:
            return PaymentLinkRepository(tx, organisation_id).configs()

    def create_config(self, organisation_id, *, provider, name, url_template, actor, enabled=False, currency=''):
        data = self._validate(dict(provider=provider, name=name, url_template=url_template, enabled=enabled, currency=currency))
        with self.db.transaction() as tx:
            repo = PaymentLinkRepository(tx, organisation_id)
            repo.lock_organisation()
            method_id = new_id()
            row = repo.save_config(method_id, data)
            audit(tx, organisation_id, actor, 'payment_method.created', 'payment_link_config', method_id)
            return row

    def update_config(self, organisation_id, method_id, *, actor, **changes):
        if changes.keys() - {'provider', 'name', 'url_template', 'enabled', 'currency'} or any(v is None for v in changes.values()):
            raise ValueError('Invalid payment method fields')
        with self.db.transaction() as tx:
            repo = PaymentLinkRepository(tx, organisation_id)
            repo.lock_organisation()
            current = repo.config(method_id)
            current['enabled'] = bool(current['enabled'])
            data = self._validate(current | changes)
            row = repo.save_config(method_id, data, existing=True)
            audit(tx, organisation_id, actor, 'payment_method.updated', 'payment_link_config', method_id)
            return row

    @staticmethod
    def _payable(invoice):
        return (invoice['document_type'] == 'invoice' and invoice['status'] in {'Issued', 'Part Paid'}
                and money(invoice['total']) > money(invoice['paid_total']))

    def _generate(self, repo, invoice, config):
        if not config['enabled']:
            raise ValueError('Payment method is disabled')
        if not self._payable(invoice):
            raise ValueError('Payment links require an unpaid issued sales invoice')
        if config['currency'] and config['currency'] != invoice['currency']:
            raise ValueError('Payment method currency does not match the invoice')
        existing = repo.link(invoice['id'], config['id'])
        token = existing['token'] if existing else secrets.token_urlsafe(32)
        values = dict(invoice_total=format(money(invoice['total']), '.2f'),
                      invoice_due=format(money(invoice['total']) - money(invoice['paid_total']), '.2f'),
                      invoice_number=invoice['number'], invoice_id=invoice['id'], token=token, currency=invoice['currency'])
        url = config['url_template'].format(**{key: quote(str(value), safe='') for key, value in values.items()})
        self._safe_url(url)
        return repo.save_link(invoice['id'], config['id'], token, url, existing) | {'name': config['name'], 'provider': config['provider']}

    def generate(self, organisation_id, invoice_id, method_id):
        with self.db.transaction() as tx:
            repo = PaymentLinkRepository(tx, organisation_id)
            repo.lock_organisation()
            return self._generate(repo, repo.invoice(invoice_id), repo.config(method_id))

    def invoice_links(self, organisation_id, invoice_id):
        """Materialise eligible links; draft, paid and incompatible methods yield none."""
        with self.db.transaction() as tx:
            repo = PaymentLinkRepository(tx, organisation_id)
            repo.lock_organisation()
            invoice = repo.invoice(invoice_id)
            if not self._payable(invoice):
                return []
            return [self._generate(repo, invoice, config) for config in repo.configs()
                    if config['enabled'] and (not config['currency'] or config['currency'] == invoice['currency'])]

    def invoice_payload(self, organisation_id, invoice_id):
        from documents import DocumentService
        row = DocumentService(self.db).invoice(invoice_id, organisation_id)
        row['payment_links'] = self.invoice_links(organisation_id, invoice_id)
        row['deliveries'] = DocumentService(self.db).invoice_deliveries(organisation_id, invoice_id)
        return row
