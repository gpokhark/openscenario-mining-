"""OpenSCENARIO XSDs are ASAM-licensed, so they are fetched, never bundled.

Pinned to a commit of asam-ev/qc-openscenarioxml (ASAM's own checker); the
SHA-256 of each file is verified so every run validates against identical bytes.
"""
import hashlib
import urllib.request
from pathlib import Path

COMMIT = "d98bf3d116d4a1ce0198992c44da44efc7ea7700"
URL = ("https://raw.githubusercontent.com/asam-ev/qc-openscenarioxml/"
       + COMMIT + "/qc_openscenario/schema/{v}/OpenSCENARIO.xsd")
SHA256 = {
    "1.0.0": "ca8d8c4ed5ded079c24b40a4cf4256a4764ae13d0cb34a5115a0db1263958687",
    "1.1.0": "9a15e520830563f6040a1815363c804e610279ea4e84d1a3600c86187a0fd98f",
    "1.2.0": "2b6739357313039cc44cde4d2752ce1be40d8b07e61d9f45d7e598d9624d5389",
    "1.3.0": "f3f3df47c1187ca00bab95ad9653f1e2470b9b4ea8ffcc0b6498d3fa145d5773",
}
# declared revMinor -> XSD. 1.3.1 files declare revMinor 3 and use the 1.3 schema.
BY_MINOR = {0: "1.0.0", 1: "1.1.0", 2: "1.2.0", 3: "1.3.0"}


def path(directory, version):
    return Path(directory) / f"OpenSCENARIO-{version}.xsd"


def fetch(directory):
    Path(directory).mkdir(parents=True, exist_ok=True)
    for v, want in SHA256.items():
        dest = path(directory, v)
        if not dest.exists():
            dest.write_bytes(urllib.request.urlopen(URL.format(v=v), timeout=60).read())
        got = hashlib.sha256(dest.read_bytes()).hexdigest()
        if got != want:
            raise SystemExit(f"{dest}: sha256 {got} != pinned {want}")
        print(f"ok {dest}")
