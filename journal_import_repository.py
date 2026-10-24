"""Tenant-scoped queries for reviewed workbook journal postings."""


class JournalImportRepository:
    def __init__(self, tx, organisation_id):
        self.tx, self.organisation_id = tx, organisation_id

    def lock(self):
        self.tx.execute("UPDATE organisations SET id=id WHERE id=?", (self.organisation_id,))

    def resolve_account(self, code):
        mapping = self.tx.one(
            "SELECT local_account_code,status FROM account_mappings WHERE organisation_id=? "
            "AND provider='file_import' AND external_account_code=?", (self.organisation_id, code))
        if mapping:
            if mapping["status"] != "Confirmed":
                return None
            code = mapping["local_account_code"]
        return self.tx.one("SELECT id,code FROM accounts WHERE organisation_id=? AND code=? AND active=1",
                           (self.organisation_id, code))

    def posted(self, external_id):
        return self.tx.one("SELECT id FROM posting_batches WHERE organisation_id=? AND voucher_type='file_journal' AND voucher_id=?",
                           (self.organisation_id, external_id))

    def staged(self, staged_id):
        return self.tx.one("SELECT status FROM import_staged_records WHERE organisation_id=? AND id=?",
                           (self.organisation_id, staged_id))

    def currency(self):
        return self.tx.scalar("SELECT base_currency FROM organisations WHERE id=?", (self.organisation_id,))
