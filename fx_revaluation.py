"""Atomic delta revaluation of current open foreign trade and advance balances."""
from datetime import date
from decimal import Decimal

from core_utils import audit, money, new_id
from database import get_database
from exchange_rates import booking_rate
from fx_revaluation_repository import FxRevaluationRepository
from fx_settlement import effective_rate, control_line, add_fx_line
from fx_settlement_repository import original_control, revaluation_control, settled_control
from ledger import LedgerService


class FxRevaluationService:
    def __init__(self, db=None):
        self.db = db or get_database()
        self.ledger = LedgerService(self.db)

    def list(self, organisation_id):
        with self.db.transaction() as tx:
            return FxRevaluationRepository(tx, organisation_id).list()

    def run(self, organisation_id, *, revaluation_date, actor):
        if not isinstance(revaluation_date, str) or date.fromisoformat(revaluation_date).isoformat() != revaluation_date:
            raise ValueError('Revaluation date must use YYYY-MM-DD')
        with self.db.transaction() as tx:
            repo = FxRevaluationRepository(tx, organisation_id)
            repo.lock()
            if repo.existing(revaluation_date):
                raise ValueError('A revaluation already exists for this date')
            self.ledger._validate_period(tx, organisation_id, revaluation_date)
            base, accounts = repo.base_currency(), repo.accounts()
            results, lines = [], []
            totals = dict(booked_base=Decimal('0'), target=Decimal('0'), delta=Decimal('0'), fx_gain_loss=Decimal('0'))
            for document in repo.documents(base):
                role = document['control_role']
                if role not in accounts:
                    raise ValueError(f'Chart of accounts is missing {role}')
                account = accounts[role]
                prepayment = document['document_type'] == 'prepayment'
                total = money(document['amount'] if prepayment else document['total'])
                paid = total - money(document['unallocated_balance']) if prepayment else money(document['paid_total'])
                portion = total - paid
                booked = original_control(tx, organisation_id, document['posting_batch_id'], account) or Decimal('0')
                _, relieved = settled_control(tx, organisation_id, document, account, prepayment=prepayment)
                booked += revaluation_control(tx, organisation_id, document, account, prepayment=prepayment) or Decimal('0')
                current = money(booked - relieved)
                if not current:
                    continue
                rate = effective_rate(document['currency'], base,
                                      booking_rate(tx, organisation_id, document['currency'], base, revaluation_date))
                target = money(portion * rate)
                delta = current - target
                result = dict(document_type=document['document_type'], document_id=document['id'],
                              document=document.get('number') or document.get('supplier_number') or
                              document.get('reference') or document['id'], currency=document['currency'],
                              portion=str(portion), booked_base=str(current), target=str(target), delta=str(delta), rate=str(rate))
                results.append(result)
                for key in ('booked_base', 'target', 'delta'):
                    totals[key] += {'booked_base': current, 'target': target, 'delta': delta}[key]
                if delta:
                    is_debit = document['side'] == 'supplier' if prepayment else document['document_type'] == 'invoice'
                    totals['fx_gain_loss'] += delta * (1 if is_debit else -1)
                    lines.append(control_line(account, -delta, debit=is_debit, contact_id=document['contact_id'],
                                              due_date=document.get('due_date'), memo=result['document'],
                                              source_line_type=document['document_type'], source_line_id=document['id']))
            if lines and 'FX_GAIN_LOSS' not in accounts:
                raise ValueError('Chart of accounts is missing FX_GAIN_LOSS')
            add_fx_line(tx, organisation_id, lines, memo='FX revaluation')
            run_id, batch_id = new_id(), None
            if lines:
                batch_id = self.ledger.post(organisation_id=organisation_id, voucher_type='fx_revaluation',
                    voucher_id=run_id, voucher_code=f'FX-{revaluation_date}', posting_date=revaluation_date,
                    lines=lines, actor=actor, currency=base, tx=tx)['id']
            payload = dict(documents=results, totals={key: str(value) for key, value in totals.items()}, base_currency=base)
            run = repo.create(run_id, revaluation_date, batch_id, actor)
            audit(tx, organisation_id, actor, 'fx_revaluation.posted', 'fx_revaluation', run_id,
                  dict(payload, posting_batch_id=batch_id))
            return dict(run, **payload)
