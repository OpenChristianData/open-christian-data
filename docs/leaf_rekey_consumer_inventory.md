# NSH leaf-rekey consumer inventory

Generated for R0-1. Requested command was `rg -n "page_native_id" build/`; `rg`
was not available in this session, so the equivalent source-only fallback was:

```powershell
Get-ChildItem -Path build -Recurse -File -Include *.py |
  Where-Object { $_.FullName -notmatch '__pycache__' } |
  Select-String -Pattern 'page_native_id'
```

Raw fallback result: 267 source hits across 23 Python files. `__pycache__`
binary hits were excluded.

Legend: `read` consumes an existing `page_native_id`; `write` emits or stores
one; `derive` constructs one from a page number or image stem; `path` uses it
for artifact paths; `support` is a helper signature, call-through, regex, or
tracking set; `doc` is a docstring/comment hit.

## Accessor / support

- `build/lib/nsh_leaf_model.py`
  - support: 40, 265, 267, 279
- `build/lib/page_order.py`
  - doc: 90, 94, 138

## S1 emit

- `build/parsers/local_schaff_tesseract.py`
  - read: 436
  - write: 449
- `build/parsers/s1_abbyy_normalizer_je.py`
  - support: 59, 87, 96, 118, 126, 172
  - derive: 161, 291
  - path: 292
  - write: 69, 182, 301, 322, 336
  - log: 328
- `build/parsers/s1_abbyy_normalizer.py`
  - support: 130, 137, 155, 190, 218, 240, 253, 287, 407, 580, 591, 700, 733,
    759, 886, 924
  - read: 653, 958, 1005
  - derive: 138, 139, 140, 561
  - path: 563, 902
  - write: 168, 203, 271, 297, 432, 602, 712, 775, 810, 910, 931
  - tracking: 597, 939
  - doc: 823, 825, 859
- `build/parsers/s1_azure_normalizer_je.py`
  - read: 212, 218, 221
  - path: 165
  - write: 171, 181
  - support: 148
  - doc: 76
- `build/parsers/s1_azure_normalizer.py`
  - support: 101, 134, 148, 284, 317
  - read: 230, 349
  - path: 298
  - write: 113, 164, 198, 303, 322
  - tracking: 300, 310, 330, 332
  - doc: 215, 217
- `build/parsers/s1_calamari_runner.py`
  - support: 207, 298, 444, 454
  - derive: 418
  - tracking: 422, 462
  - write: 220, 312, 466
- `build/parsers/s1_kraken_greek_runner.py`
  - support: 111, 154, 274, 305, 371, 400, 497, 512, 522
  - read: 125
  - derive: 489
  - path: 155, 490, 491
  - write: 287, 320, 342, 393, 536
  - tracking: 532
- `build/parsers/s1_kraken_runner.py`
  - support: 121, 164, 285, 316, 382, 411, 707, 748, 758
  - read: 135
  - derive: 725
  - path: 165, 726, 727
  - write: 298, 331, 353, 404, 782
  - tracking: 730, 770, 800
- `build/parsers/s1_surya_runner.py`
  - support: 105, 148, 289, 320, 386, 415, 669, 679, 729, 757, 774, 784
  - read: 119, 628
  - derive: 749
  - path: 149, 750, 751
  - write: 302, 335, 357, 408, 620, 806
  - tracking: 689, 794
- `build/parsers/s1_tesseract_runner.py`
  - support: 107, 150, 255, 286, 352, 381, 560, 590, 600
  - read: 121
  - derive: 577
  - path: 151, 578, 579
  - write: 268, 301, 323, 374, 622
  - tracking: 582, 610, 640

## S2 render

- `build/tools/ocr_pipeline/render_s2.py`
  - support: 319, 437, 463, 473
  - read: 573, 687, 783, 871
  - write: 584
  - derive: 332

## WCT / reconciliation

- `build/tools/ocr_pipeline/align_ccel_to_wct.py`
  - read: 164, 198
  - diagnostic: 197
- `build/tools/ocr_pipeline/build_wct.py`
  - read: 63
- `build/tools/ocr_pipeline/drive_reconciliation_chain.py`
  - derive: 140, 228, 251, 285, 338, 449, 500
  - path: 233, 428, 786
  - diagnostic: 490
- `build/tools/ocr_pipeline/measure_reconciliation.py`
  - support: 27
  - derive: 306, 323
  - path: 561

## Normalizers / inventory / repair tools

- `build/tools/build_gold_sample.py`
  - read: 97
- `build/tools/ocr_pipeline/extract_ccel_page_gold.py`
  - write: 154, 192
  - doc: 126, 129
- `build/tools/ocr_pipeline/ocr_doctor.py`
  - read: 85
- `build/tools/ocr_pipeline/ocr_inventory.py`
  - support: 63
  - read: 205, 207, 210, 212
  - derive: 64, 70
  - tracking: 75, 81
- `build/tools/ocr_pipeline/reindex_manifest.py`
  - support: 50, 52, 70, 112, 125, 126, 127, 134, 155, 156, 157, 164, 255,
    265, 266, 267
  - read: 58, 124, 154, 264
  - write: 64, 80, 283
  - tracking: 142, 172, 277
  - diagnostic: 61

## Migration notes

- S1 emitters are the largest migration surface. They both derive IDs from
  image stems and write `"page_native_id"` into sidecar JSON.
- S2 and reconciliation mostly read page refs or derive filenames from the old
  page-key helper.
- `nsh_leaf_model.py` is the central place to add leaf-keyed resolution logic;
  new manifest-reading logic should stay there.
