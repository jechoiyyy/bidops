# Synthetic SQLite migration fixture

`test_deep_review_migrations.py` builds a complete 13-table SQLite backup in a
temporary directory, then writes a matching `bidops.sqlite-file-manifest.v1`.
No operating database, attachment, credential, or real company snapshot is
stored in this fixture directory.
