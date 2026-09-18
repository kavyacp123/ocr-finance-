# Mock finance dataset for demo testing

These files were created to exercise the app's main finance and analytics features quickly.

Files:
- mock_invoice_dataset.csv
- mock_po_dataset.csv
- mock_payment_dataset.csv

What this dataset triggers:
- duplicate invoices: INV-1006 appears twice
- unresolved PO link: INV-5001 uses LY
- missing PO: INV-3001 has no PO
- PO mismatch: INV-2003 references PO-999 while the PO total differs
- anomaly detection: INV-4001 is much larger than the usual vendor total
- zero/negative amount rule: INV-3001 total is 0
- overpayment detection: PMT-201 exceeds INV-2001 total

Suggested upload strategy:
1. Upload the invoice documents as PDFs or images in the UI.
2. Use the same vendors and invoice numbers as in the dataset.
3. For PO matching, add or seed a PO record with PO-101, PO-102, PO-201, PO-401, and PO-999.
4. After processing, the dashboard should show violations, anomalies, and duplicates.

This is intentionally crafted to maximize rule coverage without needing a large enterprise dataset.
