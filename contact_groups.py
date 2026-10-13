"""Contact and user groups: named tags with many-to-many membership.

Groups are labels, not security: user groups group memberships for
filtering and reporting, contact groups group clients and suppliers. Both
are organisation-scoped with unique names, audited writes under an
organisation lock, and cascade-deleted memberships.
"""
from __future__ import annotations

from core_utils import audit, new_id, utc_now
from database import get_database

KINDS = {
    "contact": ("contact_groups", "contact_group_members", "contact_id"),
    "user": ("user_groups", "user_group_members", "email"),
}


class GroupService:
    def __init__(self, db=None):
        self.db = db or get_database()

    # reads ----------------------------------------------------------------

    def list_groups(self, organisation_id, kind):
        table, member_table, member_column = KINDS[kind]
        return self.db.rows(
            f"SELECT g.id,g.name,g.created_at,"
            f"(SELECT COUNT(*) FROM {member_table} m WHERE m.group_id=g.id) members "
            f"FROM {table} g WHERE g.organisation_id=? ORDER BY g.name", (organisation_id,))

    def members(self, organisation_id, kind, group_id):
        table, member_table, member_column = KINDS[kind]
        group = self._group(organisation_id, kind, group_id)
        return {"group": {"id": group["id"], "name": group["name"]},
                "members": [row[member_column] for row in self.db.rows(
                    f"SELECT {member_column} FROM {member_table} WHERE organisation_id=? "
                    f"AND group_id=? ORDER BY created_at", (organisation_id, group_id))]}

    def contact_group_ids(self, organisation_id, contact_id):
        return [row["group_id"] for row in self.db.rows(
            "SELECT group_id FROM contact_group_members WHERE organisation_id=? AND contact_id=? "
            "ORDER BY created_at", (organisation_id, contact_id))]

    # writes ---------------------------------------------------------------

    def create_group(self, organisation_id, kind, name, *, actor):
        name = (name or "").strip()
        if not name or len(name) > 100:
            raise ValueError("A group name of up to 100 characters is required")
        table, _, _ = KINDS[kind]
        with self.db.transaction() as tx:
            locked = tx.execute("UPDATE organisations SET name=name WHERE id=?", (organisation_id,))
            if not locked.rowcount:
                raise KeyError("Organisation not found")
            existing = tx.one(f"SELECT id FROM {table} WHERE organisation_id=? AND name=?",
                              (organisation_id, name))
            if existing:
                raise ValueError("A group with this name already exists")
            group_id = new_id()
            tx.execute(f"INSERT INTO {table}(id,organisation_id,name,created_at) VALUES (?,?,?,?)",
                       (group_id, organisation_id, name, utc_now()))
            audit(tx, organisation_id, actor, f"group.{kind}_created", "group", group_id,
                  {"name": name})
        return self._group(organisation_id, kind, group_id)

    def delete_group(self, organisation_id, kind, group_id, *, actor):
        table, _, _ = KINDS[kind]
        with self.db.transaction() as tx:
            locked = tx.execute("UPDATE organisations SET name=name WHERE id=?", (organisation_id,))
            if not locked.rowcount:
                raise KeyError("Organisation not found")
            group = self._group(organisation_id, kind, group_id, tx=tx)
            tx.execute(f"DELETE FROM {table} WHERE id=?", (group_id,))
            audit(tx, organisation_id, actor, f"group.{kind}_deleted", "group", group_id,
                  {"name": group["name"]})

    def add_member(self, organisation_id, kind, group_id, member, *, actor):
        table, member_table, member_column = KINDS[kind]
        member = (member or "").strip()
        if not member:
            raise ValueError("A member is required")
        with self.db.transaction() as tx:
            self._group(organisation_id, kind, group_id, tx=tx)
            existing = tx.one(
                f"SELECT id FROM {member_table} WHERE organisation_id=? AND group_id=? AND {member_column}=?",
                (organisation_id, group_id, member))
            if existing:
                raise ValueError("The member is already in this group")
            if kind == "contact":
                contact = tx.one("SELECT id FROM contacts WHERE id=? AND organisation_id=?",
                                 (member, organisation_id))
                if not contact:
                    raise KeyError("Contact not found")
            tx.execute(
                f"INSERT INTO {member_table}(id,organisation_id,group_id,{member_column},created_at) "
                "VALUES (?,?,?,?,?)", (new_id(), organisation_id, group_id, member, utc_now()))
            audit(tx, organisation_id, actor, f"group.{kind}_member_added", "group", group_id,
                  {member_column: member})

    def remove_member(self, organisation_id, kind, group_id, member, *, actor):
        table, member_table, member_column = KINDS[kind]
        member = (member or "").strip()
        with self.db.transaction() as tx:
            self._group(organisation_id, kind, group_id, tx=tx)
            deleted = tx.execute(
                f"DELETE FROM {member_table} WHERE organisation_id=? AND group_id=? AND {member_column}=?",
                (organisation_id, group_id, member))
            if not deleted.rowcount:
                raise KeyError("Member not found")
            audit(tx, organisation_id, actor, f"group.{kind}_member_removed", "group", group_id,
                  {member_column: member})

    def _group(self, organisation_id, kind, group_id, tx=None):
        table, _, _ = KINDS[kind]
        runner = tx if tx is not None else self.db
        row = runner.one(f"SELECT * FROM {table} WHERE id=? AND organisation_id=?",
                         (group_id, organisation_id))
        if not row:
            raise KeyError("Group not found")
        return row