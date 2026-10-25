"""Copy the exact local imports of the retained vendored TEI schema into a test mirror."""
from hashlib import sha256
from pathlib import Path

SCHEMA_RELATIVE = Path("ocd_kernel/tei/vendor/xsd")
PINS = {
    "tei_all.xsd": "2d886fb9354567ab91d8a52286ef66276c6a932228ccbec04d7c4c9b6aa5a05f",
    "tei_all_teix.xsd": "51ab8c0071f2abc375090829acadf7cb57c707fe17a993cdb2213e84932a6fac",
    "tei_all_xml.xsd": "4f3a8348802f3bc968cbdd2a9d54a38a0549e5e4e7bc8d4338404f85f89568ba",
}


def copy_vendored_schema_imports(repository_root, mirror_root):
    """Keep local schema resolution complete, with no network or external fallback."""
    source = Path(repository_root) / SCHEMA_RELATIVE
    target = Path(mirror_root) / SCHEMA_RELATIVE
    main = target / "tei_all.xsd"
    assert sha256(main.read_bytes()).hexdigest() == PINS["tei_all.xsd"]
    payloads = {}
    for name in ("tei_all_teix.xsd", "tei_all_xml.xsd"):
        raw = (source / name).read_bytes()
        if sha256(raw).hexdigest() != PINS[name]:
            raise ValueError(f"Vendored schema import bytes differ: {name}")
        if (target / name).exists() and (target / name).read_bytes() != raw:
            raise ValueError(f"Existing mirrored schema import differs: {name}")
        payloads[name] = raw
    for name, raw in payloads.items():
        (target / name).write_bytes(raw)
