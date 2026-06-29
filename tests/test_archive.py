def test_archive_dry_run_no_s3(client, monkeypatch, db):
    from app.config import settings
    monkeypatch.setattr(settings, "ARCHIVE_ENABLED", False)
    from app.archive import archive_old_ledger
    n = archive_old_ledger(db)
    assert n == 0
