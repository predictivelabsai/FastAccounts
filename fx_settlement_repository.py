"""Tenant-scoped booked control amounts and immutable settlement history."""
from decimal import Decimal

from core_utils import decimal, money


def original_control(tx, organisation_id, batch_id, account_id):
    rows = tx.rows('SELECT debit,credit FROM gl_entries WHERE organisation_id=? '
                   'AND posting_batch_id=? AND account_id=?', (organisation_id, batch_id, account_id))
    return (abs(sum((decimal(r['debit']) - decimal(r['credit']) for r in rows), Decimal('0')))
            if rows else None)


def settled_control(tx, organisation_id, document, account_id, *, prepayment=False):
    """Return consumed currency units and the actual base relief of prior events."""
    paid, relieved = Decimal('0'), Decimal('0')
    if prepayment:
        events = tx.rows(
            'SELECT amount,posting_batch_id FROM prepayment_allocations WHERE organisation_id=? AND prepayment_id=? '
            'UNION ALL SELECT amount,posting_batch_id FROM prepayment_refunds WHERE organisation_id=? AND prepayment_id=?',
            (organisation_id, document['id'], organisation_id, document['id']))
    else:
        kind = document['document_type']
        events = tx.rows('SELECT amount,posting_batch_id FROM prepayment_allocations '
                         'WHERE organisation_id=? AND document_type=? AND document_id=?',
                         (organisation_id, kind, document['id']))
        allocations = tx.rows(
            'SELECT a.*,p.amount payment_amount,p.posting_batch_id FROM payment_allocations a '
            'JOIN payments p ON p.id=a.payment_id WHERE p.organisation_id=? '
            'AND a.document_type=? AND a.document_id=?', (organisation_id, kind, document['id']))
        for row in allocations:
            paid += decimal(row['amount'])
            if row['booked_base_amount'] is not None:
                relieved += decimal(row['booked_base_amount'])
                continue
            # Legacy aggregate legs have no document source. Apportion their
            # actual stored base amount by cumulative currency units, ordered
            # deterministically; unallocated units retain the final remainder.
            control = original_control(tx, organisation_id, row['posting_batch_id'], account_id)
            if control is None:
                continue
            cumulative = Decimal('0')
            for allocation in tx.rows('SELECT id,amount FROM payment_allocations WHERE payment_id=? ORDER BY id',
                                       (row['payment_id'],)):
                next_amount = cumulative + decimal(allocation['amount'])
                if allocation['id'] == row['id']:
                    relieved += money(control * next_amount / decimal(row['payment_amount'])) - money(
                        control * cumulative / decimal(row['payment_amount']))
                    break
                cumulative = next_amount
    for event in events:
        paid += decimal(event['amount'])
        rows = tx.rows('SELECT debit,credit FROM gl_entries WHERE organisation_id=? '
                       'AND posting_batch_id=? AND account_id=?',
                       (organisation_id, event['posting_batch_id'], account_id))
        original_is_debit = document.get('side') == 'supplier' if prepayment else document['document_type'] == 'invoice'
        relieved += sum(((decimal(r['credit']) - decimal(r['debit'])) * (1 if original_is_debit else -1)
                         for r in rows), Decimal('0'))
    return paid, relieved
