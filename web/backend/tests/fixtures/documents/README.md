# Document processor fixtures

`section0.xml` is the deterministic OWPML section used by
`tests/test_document_mcp.py`.  The test packages it in memory as an HWPX ZIP
so no fixture extraction path is ever passed to the processor.  HWP/PDF/image
security cases are constructed from bytes in the test and are intentionally not
written to a user-visible location.
