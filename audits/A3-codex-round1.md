# A3 Codex Round 1 - Content Sampling Against Raw Sources

Scope: 5 deterministic samples per volume at 20/40/60/80/100% of `source/vol_NN.json:data[]`, per the session prompt. Reconciled `original/vol_NN.json` is used only for `source_pages`; definition text is checked from `source/vol_NN.json`.

## Verdict

- IA scan-image comparison is blocked in this checkout: `raw/internet-archive/schaff-herzog/scans/` is absent or empty. I did not re-download scans.
- Parser-to-raw sampling found mostly clean matches, but several sampled entries expose parser gaps/truncations against raw DjVu/ThML text. Treat these as content defects needing focused review, not as scan-level OCR judgements.
- IA `source_pages[].page_number` is partially null in current records; recovered DjVu marker pages exist for many sampled entries but are not reflected consistently in `original/vol_NN.json`.

## Page-Number Coverage Observed In `original/vol_NN.json`

| Vol | Blocks | Null page_numbers | Distinct numeric pages | Min | Max |
|---:|---:|---:|---:|---:|---:|
| 1 | 899 | 0 | 281 | 1 | 500 |
| 2 | 895 | 0 | 287 | 1 | 500 |
| 3 | 625 | 15 | 247 | 1 | 500 |
| 4 | 752 | 10 | 185 | 6 | 700 |
| 5 | 760 | 6 | 274 | 0 | 604 |
| 6 | 619 | 4 | 152 | 1 | 604 |
| 7 | 536 | 8 | 156 | 0 | 496 |
| 8 | 618 | 15 | 185 | 20 | 498 |
| 9 | 592 | 0 | 207 | 1 | 499 |
| 10 | 658 | 8 | 168 | 0 | 499 |
| 11 | 525 | 7 | 167 | 0 | 604 |
| 12 | 678 | 7 | 264 | 1 | 687 |

## Aggregate Parser Classes

| Vol | parser_clean | parser_truncated | parser_gap |
|---:|---:|---:|---:|
| 1 | 2 | 0 | 3 |
| 2 | 4 | 0 | 1 |
| 3 | 3 | 1 | 1 |
| 4 | 4 | 0 | 1 |
| 5 | 1 | 0 | 4 |
| 6 | 2 | 0 | 3 |
| 7 | 4 | 0 | 1 |
| 8 | 3 | 0 | 2 |
| 9 | 5 | 0 | 0 |
| 10 | 5 | 0 | 0 |
| 11 | 2 | 1 | 2 |
| 12 | 4 | 1 | 0 |

## Aggregate OCR / Scan Classes

| Vol | scan_unavailable | not_applicable | ocr_char | ocr_word | ocr_structural | scan_clean |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 5 | 0 | 0 | 0 | 0 |
| 2 | 0 | 5 | 0 | 0 | 0 | 0 |
| 3 | 5 | 0 | 0 | 0 | 0 | 0 |
| 4 | 5 | 0 | 0 | 0 | 0 | 0 |
| 5 | 5 | 0 | 0 | 0 | 0 | 0 |
| 6 | 5 | 0 | 0 | 0 | 0 | 0 |
| 7 | 5 | 0 | 0 | 0 | 0 | 0 |
| 8 | 5 | 0 | 0 | 0 | 0 | 0 |
| 9 | 0 | 5 | 0 | 0 | 0 | 0 |
| 10 | 5 | 0 | 0 | 0 | 0 | 0 |
| 11 | 5 | 0 | 0 | 0 | 0 | 0 |
| 12 | 5 | 0 | 0 | 0 | 0 | 0 |

## IA DjVu Page Marker Recovery

| Vol | Body start line | Article headings found | With recovered page |
|---:|---:|---:|---:|
| 3 | 2642 | 656 | 642 |
| 4 | 2797 | 790 | 781 |
| 5 | 3110 | 804 | 802 |
| 6 | 2987 | 645 | 642 |
| 7 | 3254 | 552 | 547 |
| 8 | 3395 | 651 | 640 |
| 10 | 3421 | 701 | 693 |
| 11 | 4185 | 561 | 556 |
| 12 | 4339 | 744 | 738 |

## Sample Notes

| Vol | Pos | Entry | Term | `definition_blocks[0][:200]` | Recorded page | Recovered DjVu page | Parser class | OCR/scan class | Note |
|---:|---:|---|---|---|---|---|---|---|---|
| 1 | 20% | `schaff-herzog.agnosticism` | Agnosticism | AGNOSTICISM: A philologically objectionable and philosophically unnecessary but very convenient term, invented toward the end of the nineteenth century (1869) as a designation of the skeptical habit o | [87] | None | parser_clean | not_applicable | parsed block found verbatim after whitespace normalisation; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 1 | 40% | `schaff-herzog.american-missionary-association` | American Missionary Association | AMERICAN MISSIONARY ASSOCIATION. See Congregationalists, I., 4, § 10. | [154] | None | parser_gap | not_applicable | parsed block not located in raw segment; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 1 | 60% | `schaff-herzog.apponius` | Apponius | APPONIUS, ap-pō´ni-Us: The author of an exposition of the Song of Solomon. He names himself in his preface, addressed to the presbyter Armenius, but neither the time nor the place of his activity can  | [250] | None | parser_clean | not_applicable | 4/5 parsed chunks found in raw segment; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 1 | 80% | `schaff-herzog.authorized-version-of-the-english-bible` | Authorized Version of the English Bible | AUTHORIZED VERSION OF THE ENGLISH BIBLE. See Bible Versions, B, IV, 6. | [384] | None | parser_gap | not_applicable | parsed block not located in raw segment; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 1 | 100% | `schaff-herzog.basilians` | Basilians | BASILIANS: Monks or nuns following the rule of St. Basil, who introduced the cenobitic life into Asia Minor, and is said to have founded the first monastery there. The rules which he gave this communi | [500] | None | parser_gap | not_applicable | parsed block not located in raw segment; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 2 | 20% | `schaff-herzog.bethsaida` | Bethsaida | BETHSAIDA. See Gaulanitis. | [75] | None | parser_gap | not_applicable | parsed block not located in raw segment; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 2 | 40% | `schaff-herzog.booth-tucker-frederick-st-george-de-lautour` | Booth Tucker, Frederick St. George de Lautour | BOOTH TUCKER, FREDERICK ST. GEORGE DE LAUTOUR: Secretary for Foreign Affairs of the Salvation Army; b. at Monghyr (80 m. e. of Patna), Bengal, Mar. 21, 1853. He was educated at Cheltenham College, Eng | [233] | None | parser_clean | not_applicable | 5/5 parsed chunks found in raw segment; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 2 | 60% | `schaff-herzog.bryant-jacob` | Bryant, Jacob | BRYANT, JACOB: English antiquarian; b. at Plymouth 1715; d. at Cypenham, in Farnham Royal (4 m. n. of Windsor), Nov. 14, 1804. He studied at King's College, Cambridge (B.A., 1740; M.A., 1744), and bec | [287] | None | parser_clean | not_applicable | 5/5 parsed chunks found in raw segment; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 2 | 80% | `schaff-herzog.camus-de-pont-carre-jean-pierre` | Camus (de Pont Carré), Jean Pierre | CAMUS, cɑ̄´´mū´, de Pont Carré, JEAN PIERRE: French prelate; b. in Paris Nov. 3, 1584; d. there Apr. 25, 1652. He became successively bishop of Belley 1609, abbot of Aulnay in Normandy 1629, but retir | [374] | None | parser_clean | not_applicable | 4/5 parsed chunks found in raw segment; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 2 | 100% | `schaff-herzog.chambers-talbot-wilson` | Chambers, Talbot Wilson | CHAMBERS, TALBOT WILSON: Reformed (Dutch); b. at Carlisle, Pa., Feb. 25, 1819; d.. in New York Feb. 3, 1896. He was graduated at Rutgers College, New Brunswick, N. J., 1834. He studied at New Brunswic | [500] | None | parser_clean | not_applicable | parsed block found verbatim after whitespace normalisation; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 3 | 20% | `schaff-herzog.clares` | CLARES | The founder of an order of women parallel to the Franciscans, and the order itself. Clara Scefi was born at Assisi, of a noble family, July 16, 1194. At the age of eighteen she was ex- pecting to be m | [125] | 125 | parser_clean | scan_unavailable | 5/5 parsed chunks found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 3 | 40% | `schaff-herzog.conscience` | CONSCIENCE | Origin of the Term (§ 1). | [242] | 242 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 3 | 60% | `schaff-herzog.crypt` | CRYPT | An architectural term most frequently used to denote a subterranean story or division of a church. The word was early applied to the sub- terranean cemeteries of the Christians, the so-called catacomb | [316] | 316 | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 3 | 80% | `schaff-herzog.de-put-william-harrison` | DE PUT, WILLIAM HARRISON | Methodist; b. at Penn Yan, N. Y., Oct. 31, 1821; d. at Canaan, Conn., Sept. 4, 1901. He was educated at Genesee College, Union University, and Mount Union Col- lege, and was professor of mathematics a | [407] | 407 | parser_truncated | scan_unavailable | parsed prefix found but parsed tail not found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 3 | 100% | `schaff-herzog.jcoes-wot-circulate` | JCOES WOT CIRCULATE | »SY5 | [500] | 500 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 4 | 20% | `schaff-herzog.elizabeth-queen-of-england-excom` | ELIZABETH, QUEEN OF ENGLAND, EXCOM- | MUNICATION OF. See Felton, John. | [110] | 110 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 4 | 40% | `schaff-herzog.bwald-hermaifn-august-paul` | BWALD (HERMAIfN AUGUST), PAUL | Ger- man Protestant; b. at Leipsic Jan. 13, 1857. He stadied in Eiiangen and Leipsic (Ph. D., 1881), and from 1880 to 1882 was a member of the clergy staff of St. Paul's, Leipsic. In 1883 he became pr | [282] | 282 | parser_clean | scan_unavailable | 5/5 parsed chunks found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 4 | 60% | `schaff-herzog.flaviall` | FLAVIAll | The name of two bishops of Antioch. | [337] | 337 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 4 | 80% | `schaff-herzog.gabriel-severus` | GABRIEL SEVERUS | Greek metropoh'tan and theologian; b. at Monemvasia (45 m. 8.e. of %>arta) 1541; d. at Venice Oct. 21, 1616. After ccanple- ting his education at Padua, he resided in Crete and at Venice, where the Gr | [416] | 416 | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 4 | 100% | `schaff-herzog.goa-archbishofric-of` | GOA, ARCHBISHOFRIC OF | A metropolitan see in Portuguese India, foimded in 1534 by Paul III. The first bishop was the Franciscan Jo&o Albuquerque, consecrated in 1537. After the ex- tension of Christianity by the labors of S | [500] | 500 | parser_clean | scan_unavailable | 5/5 parsed chunks found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 5 | 20% | `schaff-herzog.dinand` | DINAND | German Lutheran theologian; b. at Wettin (15 m. n.e. of Elberfeld) Feb. 25, 1803; d. Halle Feb. 4, 1878. He studied at the University of Halle and in recognition of his biography of August Hermann Fra | [2] | 2 | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 5 | 40% | `schaff-herzog.hart-samuel` | HART, SAMUEL | Protestant Episcopalian; b. at Saybrook, Conn., June 4, 1845. He was educated at Trinity College (B.A., 1866) and the Berkeley Divinity School, and was ordered deacon in 1869 and ordained priest in th | [161] | 161 | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 5 | 60% | `schaff-herzog.herrmann-johann-georg-wilhelm` | HERRMANN, JOHANN GEORG WILHELM | Ger- man Protestant; b. at Melkow, near Magdeburg, Dec. 6, 1846. He studied at the University of Halle 1866-70, and four years later, after serving in | [249] | 249 | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 5 | 80% | `schaff-herzog.horhe-george` | HORHE, GEORGE | Bishop of Norwich; b. at Otham, near Maidstone (8 m. s.s.e. of Rochester), Kent, Nov. 1, 1730; d. at Bath Jan. 17, 1792. He studied at University and Magdalen colleges, Oxford (B.A., 1749; M.A., 1752) | [366] | 366 | parser_clean | scan_unavailable | 4/5 parsed chunks found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 5 | 100% | `schaff-herzog.end-of-vol-v` | END OF VOL. V | -s vr | [508] | 508 | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 6 | 20% | `schaff-herzog.jesus-christ-pictures-and-images-of` | JESUS CHRIST, PICTURES AND IMAGES OF | I. The OldMt Viaws and Data on the Extcnial Appearanee of Jesus. | [168] | 168 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 6 | 40% | `schaff-herzog.linus-or-aquilius` | LINUS (or AQUILIUS) | Spanish presbyter and religious poet, in the reign of Ck>nstantine the Great, ^ whom he refers at the close of his principal poem. This is a rendering of the Gospels into Latin dac- tylic hexameters,  | [286] | 286 | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 6 | 60% | `schaff-herzog.knight-george-thomson` | KNIGHT, GEORGE THOMSON | Universalist; b. at Windham, Me., Oct. 29, 1850. He was edu- cated at Tufts Coll^ (B.A., 1872; M.A., 1875) and at the Tufts Divinity School (B.D., 1875), and has taught in the latter institution since | [356] | 356 | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 6 | 80% | `schaff-herzog.tholomasus-heihrici` | THOLOMASUS HEIHRICI) | Roman Catholic hu- | [420] | 420 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 6 | 100% | `schaff-herzog.liudger-saint` | LIUDGER, SAINT | Mis- sionary to the Frisians and first bishop of Mon- ster; b. in Frisia, probably between 740 and 750; d. at Billerbeck (15 m. w.n.w. of Munster) Mar. 26, 809. He was educated at Utrecht, and thence  | [604] | 604 | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 7 | 20% | `schaff-herzog.maccabees-books-of` | MACCABEES, BOOKS OF | See Apogbtfha, A, IV., 9-11. | [106] | 106 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 7 | 40% | `schaff-herzog.marcus-eremita` | MARCUS EREMITA | Identification and Early Citations (f 1). Ascetic and Polemic Treatises (f 2). Spurious Writings (f 3). DetaUs of His Life (f 4). His Theology (i 5). | [176] | 176 | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 7 | 60% | `schaff-herzog.mazarin-bible` | MAZARIN BIBLE | The first complete book printed in the West from movable type. It receives its name from the fact that " a copy in the library of Cardinal Mazarin first attracted the attention of bibliographers " in  | [264] | 264 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 7 | 80% | `schaff-herzog.midrash` | MIDRASH | Meaning and Emenoe of Midrash (f 1). | [364] | 364 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 7 | 100% | `schaff-herzog.moralists-british` | MORALISTS, BRITISH | Importance of Reformed Protestant | [496] | 496 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 8 | 20% | `schaff-herzog.oanisations` | OANISATIONS | 36,770 | [None] | None | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 8 | 40% | `schaff-herzog.iion-resideiice` | IION-RESIDEIICE | The term applied to the absenteeism of a cleric from his sphere of duty, while he enjoys the emoluments though his duties are per- formed by a deputy or substitute. In an early period the cause of non | [190] | 190 | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 8 | 60% | `schaff-herzog.oswt` | OSWT | King of Northumbrian 643-^1, im- portant in the history of the Ghriatianixation of was a younger son of the Northumbrian King Ethel- frid, and, by his mother, a nephew of Edwin. On his brother Oswald  | [283] | 283 | parser_clean | scan_unavailable | 4/5 parsed chunks found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 8 | 80% | `schaff-herzog.patriarch` | PATRIARCH | A title applied in the early Church to the chief bishops, having jurisdiction over met- ropolitans. The name occurs in the fourth century as applied to ordinary bishops; but by degrees, as and Jerusal | [381] | 381 | parser_clean | scan_unavailable | 5/5 parsed chunks found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 8 | 100% | `schaff-herzog.petersen-johann-wh-helm` | PETERSEN, JOHANN WH^HELM | German Lutheran, mystic, and chiliast; b. at OsnabrQck (74 m. w.s.w. of Hanover) J\me 1, 1649; d. near Zerbst (22 m. s.e. of Magdeburg) Jan. 31, 1727. He was educated at the universities of Giessen (1 | [409] | 409 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 9 | 20% | `schaff-herzog.placette-jean-la` | Placette, Jean La | PLACETTE, plā´´set´, JEAN LA: French Protestant theologian and moralist; b. at Pontacq (118 m. s.s.w. of Bordeaux) Jan. 19, 1639; d. at Utrecht Apr. 25, 1718. He studied theology at the Protestant aca | [85] | None | parser_clean | not_applicable | 3/5 parsed chunks found in raw segment; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 9 | 40% | `schaff-herzog.pratt-waldo-selden` | Pratt, Waldo Selden | PRATT, WALDO SELDEN: Congregational layman; b. at Philadelphia Nov. 10, 1857. He was educated at William College (A.B., 1878) and Johns Hopkins University (1878–80). He was assistant director of the M | [153] | None | parser_clean | not_applicable | parsed block found verbatim after whitespace normalisation; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 9 | 60% | `schaff-herzog.psychotherapy` | Psychotherapy | PSYCHOTHERAPY. | [351] | None | parser_clean | not_applicable | parsed block found verbatim after whitespace normalisation; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 9 | 80% | `schaff-herzog.raymond-miner` | Raymond, Miner | RAYMOND, MINER: Methodist Episcopal; b. at New York Aug. 29, 1811; d. at Evanston, Ill., Nov. 25, 1897. He was educated at the Wesleyan Academy, Wilbraham, Mass.; became teacher in the same, 1834, and | [408] | None | parser_clean | not_applicable | parsed block found verbatim after whitespace normalisation; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 9 | 100% | `schaff-herzog.reuchlin-johannes` | Reuchlin, Johannes | REUCHLIN, reiH´´lîn´ (CAPNION), JOHANNES: German humanist; b. at Pforzheim (24 m. n.w. of Stuttgart) Feb. 22, 1455; d. at Bad Liebenzell (20 m. w. of Stuttgart) June 30, 1522. After a brief course at  | [499] | None | parser_clean | not_applicable | 4/5 parsed chunks found in raw segment; CCEL ThML volume; no IA scan comparison required by this sample rule |
| 10 | 20% | `schaff-herzog.ross-johh` | ROSS, JOHH | Presbyterian missionary to China; b. at Easter Rarichie, Nigg (138 m. n. of Glasgow), Scotland, Aug. 6, 1842. He received his education at the village school at Nigg, through private in- struction, at | [9] | 9 | parser_clean | scan_unavailable | 5/5 parsed chunks found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 10 | 40% | `schaff-herzog.sarcbrius-erasmus` | SARCBRIUS, ERASMUS | German Lutheran; b. at Annaberg (18 m. s. of Chemnitz) probably Apr. 19, 1501; d. at Magde- burg Nov. 28, 1559. He was matriciilated at Leipsic in 1522, but in 1524 seems to have migrated to Wit- tenb | [200] | 200 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 10 | 60% | `schaff-herzog.science-christian` | SCIENCE, CHRISTIAN | (l«). n. Judicial Estimate of the System. | [284] | 284 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 10 | 80% | `schaff-herzog.shem-aiah` | SHEM AIAH | A nsme of frequent occurrence in the Old Testament The most important men who bore it were: | [389] | 389 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 10 | 100% | `schaff-herzog.end-of-volume-x` | END OF VOLUME X | 3 bios ooa Hm 3^^ | [499] | 499 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 11 | 20% | `schaff-herzog.stbarhsi-oakmaff-spra6ue` | STBARHSi OAKMAff SPRA6UE | American Baptist; b at Bath, Me., Oct. 20, 1817; d. in New- ton Centre, liass., Apr. 20, 1893. He was graduated from Waterville College, Me., 1840, and from New- ton Theological Institution, Mass., 18 | [78] | 78 | parser_truncated | scan_unavailable | parsed prefix found but parsed tail not found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 11 | 40% | `schaff-herzog.stumbling-block-stone-of-stumbling` | STUMBLING-BLOCK, STONE OF STUMBLING | brew miksholf makshdahj ebhen negheph, and the Greek proakomma, lithos ton proskornmatoe, shaiv- doUm, the fundamental idea of which is either an object in the way over which one may stumble or a weig | [119] | 119 | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 11 | 60% | `schaff-herzog.tausen-hans` | TAUSEN, HANS | Danish Reformer; b. in the village of Birkende on the island of Ftknen, 1404; d. at Ribe (154 m. w.8.w. of Copenhagen) Nov. 11, 1561 . He received his early education at the schools of Odense in FOnen | [278] | 278 | parser_clean | scan_unavailable | 5/5 parsed chunks found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 11 | 80% | `schaff-herzog.thibtlfas` | THIBTlfAS | Bishop of Meraeburg; b. July 25, 975; d. Dec. 1, 1018. He was a Qaxtm, son of Count Sigefrid of Walbeck, and related to the imperial family. He studied in the abbey of Quedlinburg and in Magdebui^, an | [416] | 416 | parser_clean | scan_unavailable | 4/5 parsed chunks found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 11 | 100% | `schaff-herzog.tremellius-emalfuel` | TREMELLIUS, EMAlfUEL | Hebrew scholar; b. at Ferrara, Italy, in 1510; d. at Sedan, France, Oct. 9, 1580. His parents being Jewish, Tremellius was thoroughly instructed in the He- brew language; after 1530 he was in contact  | [604] | 604 | parser_gap | scan_unavailable | parsed block not located in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 12 | 20% | `schaff-herzog.van-kirk-hiram` | VAN KIRK, HIRAM | Disciple of Christ; b. at Washington Court House, O., Feb. 13, 1868. He was educated at Hiram College, Hiram, O. (A.B., 1892), Yale Divinity School (B.D., 1895), and the University of Chicago (Ph.D.,  | [140] | 140 | parser_truncated | scan_unavailable | parsed prefix found but parsed tail not found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 12 | 40% | `schaff-herzog.wall-william` | WALL, WILLIAM | English divine; b. in the neighborhood of Sevenoaks (20 m. s.e. of London), Kent, Jan. 6, 1646-47; d. at Shoreham (17 m. s.e. of London) Jan. 13, 1727-28. He was educated at Queen's College, Oxford (B | [257] | 257 | parser_clean | scan_unavailable | 4/5 parsed chunks found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 12 | 60% | `schaff-herzog.whitefield-george` | WHITEFIELD, GEORGE | Calvinistic Methodist; b. in Gloucester, England, Dec. 27, 1714; d. in Newburyport, Mass., Sept. 30, 1770. He was the son of an innkeeper. At the age of twelve he was placed in the school of St. Mary  | [341] | 341 | parser_clean | scan_unavailable | 4/5 parsed chunks found in raw segment; local scan image not present; compared parser only against IA DjVu OCR text |
| 12 | 80% | `schaff-herzog.wortman-denis` | WORTMAN, DENIS | Dutch Reformed; b. at East Fiflhkill, N. Y., Apr. 30, 1835. He was gradu- ated from Amherst (B.A., 1857) and the Reformed Church Seminary, New Brunswick, N. J. (1860). He held pastorates at Brooklyn,  | [441] | 441 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
| 12 | 100% | `schaff-herzog.zoeckler` | ZOECKLER — | Zoeckleb — | [599] | 599 | parser_clean | scan_unavailable | parsed block found verbatim after whitespace normalisation; local scan image not present; compared parser only against IA DjVu OCR text |
