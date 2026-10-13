"""Independent invoice deliveries through the established document sender."""
from contextlib import nullcontext

import automation
from database import get_database
from documents import DocumentService, InvoiceDeliveryFailed


MAX_BULK_INVOICES = 50


class BulkSendingService:
    def __init__(self, db=None):
        self.db = db or get_database()
        self.documents = DocumentService(self.db)

    def send(self, organisation_id, invoice_ids, *, actor, idempotency_key=None, client=None):
        if not 1 <= len(invoice_ids) <= MAX_BULK_INVOICES:
            raise ValueError(f'Select between 1 and {MAX_BULK_INVOICES} invoices')
        results, seen = [], set()
        for invoice_id in invoice_ids:
            result = dict(invoice_id=invoice_id, status='failed', reason=None,
                          delivery_id=None, attachment_id=None)
            if invoice_id in seen:
                result['reason'] = 'Duplicate invoice ID in this request'
                results.append(result)
                continue
            seen.add(invoice_id)
            try:
                # The shared sender validates eligibility and reserves its audit record
                # before HTTP. Each invoice commits independently of the others.
                with nullcontext(client) if client is not None else automation.HTTP_CLIENT_FACTORY() as http:
                    delivery = self.documents.send_invoice_email(
                        invoice_id, organisation_id=organisation_id, actor=actor, client=http,
                        bulk=True, idempotency_key=idempotency_key)
                result.update(status='sent', delivery_id=delivery['id'],
                              attachment_id=delivery['attachment_id'])
            except InvoiceDeliveryFailed as exc:
                result.update(reason=str(exc), delivery_id=exc.delivery['id'],
                              attachment_id=exc.delivery.get('attachment_id'))
            except (KeyError, ValueError, RuntimeError, OSError) as exc:
                result['reason'] = str(exc.args[0])
            results.append(result)
        return {'results': results}
