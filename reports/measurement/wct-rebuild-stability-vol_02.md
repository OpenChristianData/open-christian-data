# JE vol_02 WCT rebuild stability

- Pages compared: 34
- Old tokens: 44626
- New tokens: 44626
- Identical canonical-token anchors: 44626
- Rebound tokens: 0
- Orphaned tokens: 0
- Additions in r2: 0
- Identity rate: 100.000000%
- Acceptance threshold: 99.00%
- Acceptance result: PASS

## Design note

JE r2 pages use `edition_page_key = body_edition_key(page_num)` and `canonical_leaf_id = page_num`. The page number comes from the IA pages manifest SHA map; this keeps the 34 body-page oracle panel schema-valid without mutating the frozen vol_02 WCT evidence.

## Spot checks

- page_0010 vol_02:page_0010:body:c1:l000:p000: image_exists=True, bbox_within_image=True, text=in
- page_0011 vol_02:page_0011:body:c1:l000:p000: image_exists=True, bbox_within_image=True, text=espaiolaportuguey
- page_0013 vol_02:page_0013:body:c1:l000:p000: image_exists=True, bbox_within_image=True, text=to
- page_0014 vol_02:page_0014:body:c1:l000:p000: image_exists=True, bbox_within_image=True, text=observ
- page_0015 vol_02:page_0015:body:c1:l000:p000: image_exists=True, bbox_within_image=True, text=jews
- page_0016 vol_02:page_0016:body:c1:l000:p000: image_exists=True, bbox_within_image=True, text=influence
- page_0017 vol_02:page_0017:body:c1:l000:p000: image_exists=True, bbox_within_image=True, text=glaub
- page_0018 vol_02:page_0018:body:c1:l000:p000: image_exists=True, bbox_within_image=True, text=on
- page_0038 vol_02:page_0038:body:c1:l000:p000: image_exists=True, bbox_within_image=True, text=probably
- page_0039 vol_02:page_0039:body:c1:l000:p001: image_exists=True, bbox_within_image=True, text=ceed

## Exceptions

- None.
