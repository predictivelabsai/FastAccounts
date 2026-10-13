"""Exact booked-base portions and balanced realised exchange differences."""
from decimal import Decimal

from core_utils import decimal, money
from exchange_rates import positive_rate
from ledger import PostingLine
from fx_settlement_repository import original_control, settled_control


def effective_rate(currency, base_currency, rate):
    return positive_rate(rate) if currency != base_currency else Decimal('1')


def booked_portion(tx, organisation_id, document, account_id, amount,
                   base_currency, *, total_key='total', paid=None):
    """Apportion actual control entries cumulatively, retaining their last cent.

    Original document batches are traceable. Cumulative portions avoid rounding
    each instalment independently and the final portion consumes the remainder.
    Legacy documents without entries fall back to their effective booking rate.
    """
    total = money(document[total_key])
    rate = effective_rate(document['currency'], base_currency, document['exchange_rate'])
    booked = original_control(tx, organisation_id, document['posting_batch_id'], account_id)
    if booked is None:
        booked = money(total * rate)
    paid = money(document['paid_total']) if paid is None else money(paid)
    if paid + amount == total:
        recorded_paid, relieved = settled_control(tx, organisation_id, document, account_id,
                                                  prepayment=total_key == 'amount')
        if paid > recorded_paid:
            relieved += money(booked * (paid - recorded_paid) / total)
        return booked - relieved
    return money(booked * (paid + amount) / total) - money(booked * paid / total)


def control_line(account_id, amount, *, debit, **kwargs):
    """A legacy over-relief can require a compensating control leg on settlement."""
    signed = amount if debit else -amount
    return PostingLine(account_id, debit=max(signed, Decimal('0')), credit=max(-signed, Decimal('0')), **kwargs)


def add_fx_line(tx, organisation_id, lines, *, memo=''):
    """Receipts at higher rates credit FX (gain); bill payments debit FX (loss)."""
    lines[:] = [line for line in lines if money(line.debit) or money(line.credit)]
    difference = sum((money(line.debit) - money(line.credit) for line in lines), Decimal('0'))
    if difference:
        account = tx.one('SELECT id FROM accounts WHERE organisation_id=? '
                         "AND system_role='FX_GAIN_LOSS' AND active=1", (organisation_id,))
        if not account:
            raise ValueError('Chart of accounts is missing FX_GAIN_LOSS')
        lines.append(PostingLine(account['id'], debit=-difference if difference < 0 else Decimal('0'),
                                 credit=difference if difference > 0 else Decimal('0'), memo=memo))
