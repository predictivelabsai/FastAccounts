from pathlib import Path
_MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "sqlite"
def catalogue() -> list[str]:
    """Return sorted SQLite migration stems for test expectations."""
    return sorted(path.stem for path in _MIGRATIONS.glob("*.sql"))
def catalogue_after(migration: str) -> list[str]:
    """Return migrations applied after an already applied migration."""
    items = catalogue()
    try:
        index = items.index(migration)
    except ValueError as exc:
        raise ValueError(f"Unknown migration: {migration}") from exc
    return items[index + 1:]
