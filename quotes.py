"""Sales offers remain outside the ledger until accepted and converted."""
from datetime import date
from decimal import InvalidOperation

from core_utils import audit, decimal, four_dp, new_id, today
from database import get_database
from documents import DocumentService
from quote_repository import QuoteRepository


class QuoteService:
    def __init__(self, db=None):
        self.db = db or get_database()
        self.documents = DocumentService(self.db)

    def list(self, organisation_id):
        with self.db.transaction() as tx:
            return QuoteRepository(tx, organisation_id).list()

    def get(self, organisation_id, quote_id):
        with self.db.transaction() as tx:
            return QuoteRepository(tx, organisation_id).get(quote_id)

    def _validate(self, tx, organisation, *, contact_id, quote_date, valid_until,
                  lines, currency=None, amount_type='exclusive', notes=''):
        start, end = date.fromisoformat(quote_date), date.fromisoformat(valid_until)
        if end < start:
            raise ValueError('Quote validity cannot precede the quote date')
        base = organisation['base_currency'] or ('GBP' if organisation['country_code'] == 'UK' else 'EUR')
        currency = (currency or base).upper()
        if currency != base:
            raise ValueError('Quotes require the organisation base currency')
        contact = QuoteRepository(tx, organisation['id']).customer(contact_id)
        if not contact or contact['contact_type'] not in {'customer', 'both'}:
            raise ValueError('A customer in this organisation is required')
        # Persist exactly the precision used during calculation and conversion.
        normalised = []
        for item in lines:
            item = dict(item)
            for key, default in (('quantity', 1), ('unit_price', 0)):
                try:
                    value = decimal(item.get(key, default))
                    if not value.is_finite() or abs(value) >= 10 ** 16 or value != four_dp(value):
                        raise ValueError('Quote line amounts must be finite with at most four decimal places')
                except InvalidOperation as exc:
                    raise ValueError('Invalid quote line amount') from exc
                item[key] = value
            normalised.append(item)
        try:
            calculated, subtotal, tax_total, total = self.documents._document_lines(tx, organisation['id'], normalised, amount_type)
        except InvalidOperation as exc:
            raise ValueError('Quote total exceeds the supported amount') from exc
        if total >= 10 ** 16:
            raise ValueError('Quote total exceeds the supported amount')
        return dict(contact_id=contact_id, quote_date=start.isoformat(), valid_until=end.isoformat(),
                    currency=currency, amount_type=amount_type, notes=notes.strip(),
                    subtotal=subtotal, tax_total=tax_total, total=total), calculated

    def create(self, organisation_id, *, actor, **data):
        with self.db.transaction() as tx:
            repo = QuoteRepository(tx, organisation_id)
            organisation = repo.lock_organisation()
            validated, lines = self._validate(tx, organisation, **data)
            quote_id = new_id()
            number = self.documents._next_number(tx, organisation_id, 'quote')
            repo.save(quote_id, validated, lines, number=number, actor=actor)
            audit(tx, organisation_id, actor, 'quote.created', 'quote', quote_id)
            return repo.get(quote_id)

    def update(self, organisation_id, quote_id, *, actor, **changes):
        with self.db.transaction() as tx:
            repo = QuoteRepository(tx, organisation_id)
            organisation = repo.lock_organisation()
            quote = repo.get(quote_id)
            if quote['status'] != 'Draft':
                raise ValueError('Only Draft quotes can be edited')
            data = {key: quote[key] for key in ('contact_id', 'quote_date', 'valid_until', 'currency', 'notes', 'lines')}
            data['amount_type'] = quote['line_amount_type']
            data.update(changes)
            validated, lines = self._validate(tx, organisation, **data)
            repo.save(quote_id, validated, lines)
            audit(tx, organisation_id, actor, 'quote.updated', 'quote', quote_id)
            return repo.get(quote_id)

    def _transition(self, organisation_id, quote_id, status, *, actor):
        with self.db.transaction() as tx:
            repo = QuoteRepository(tx, organisation_id)
            repo.lock_organisation()
            quote = repo.get(quote_id)
            allowed = {'Sent': {'Draft'}, 'Accepted': {'Sent'}, 'Declined': {'Sent'}, 'Expired': {'Draft', 'Sent'}}
            if quote['status'] not in allowed[status]:
                raise ValueError('Invalid quote status transition')
            if status in {'Sent', 'Accepted'} and quote['valid_until'] < today():
                raise ValueError('Quote has expired')
            if status == 'Expired' and quote['valid_until'] >= today():
                raise ValueError('Quote is still valid')
            repo.transition(quote_id, status, actor=actor)
            audit(tx, organisation_id, actor, 'quote.' + status.lower(), 'quote', quote_id)
            return repo.get(quote_id)

    def send(self, organisation_id, quote_id, *, actor):
        # TODO: wire quote delivery when a quote email template is available.
        return self._transition(organisation_id, quote_id, 'Sent', actor=actor)

    def accept(self, organisation_id, quote_id, *, actor):
        return self._transition(organisation_id, quote_id, 'Accepted', actor=actor)

    def decline(self, organisation_id, quote_id, *, actor):
        return self._transition(organisation_id, quote_id, 'Declined', actor=actor)

    def expire(self, organisation_id, quote_id, *, actor):
        return self._transition(organisation_id, quote_id, 'Expired', actor=actor)

    def expire_due(self, organisation_id, *, actor='automation'):
        """Daily worker entry point; the last valid day remains inclusive."""
        with self.db.transaction() as tx:
            repo = QuoteRepository(tx, organisation_id)
            repo.lock_organisation()
            due = repo.due(today())
            for quote in due:
                repo.transition(quote['id'], 'Expired')
                audit(tx, organisation_id, actor, 'quote.expired', 'quote', quote['id'])
            return {'expired': len(due)}

    def convert(self, organisation_id, quote_id, *, actor):
        with self.db.transaction() as tx:
            repo = QuoteRepository(tx, organisation_id)
            repo.lock_organisation()
            quote = repo.get(quote_id)
            if quote['converted_invoice_id']:
                return self.documents.issue_invoice(quote['converted_invoice_id'], actor=actor, tx=tx)
            if quote['status'] != 'Accepted':
                raise ValueError('Only Accepted quotes can be converted')
            invoice = self.documents.create_invoice(
                organisation_id, contact_id=quote['contact_id'], issue_date=quote['quote_date'],
                currency=quote['currency'], amount_type=quote['line_amount_type'], lines=quote['lines'],
                notes=quote['notes'], reference=quote['quote_number'], actor=actor, tx=tx)
            invoice = self.documents.issue_invoice(invoice['id'], actor=actor, tx=tx)
            repo.transition(quote_id, 'Converted', invoice_id=invoice['id'])
            audit(tx, organisation_id, actor, 'quote.converted', 'quote', quote_id, {'invoice_id': invoice['id']})
            return invoice
