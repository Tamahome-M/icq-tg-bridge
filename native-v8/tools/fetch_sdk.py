"""Fetch the pinned public SDK; never execute an unverified download."""
import argparse
import hashlib
import copy
import os
from pathlib import Path
import tarfile
import tempfile
import urllib.request

COMMIT = "eadb88fdd471c5013b538166b692a0ddad9e5774"
URL = f"https://codeload.github.com/fillsa/motomagx-SDK-toolchain/tar.gz/{COMMIT}"
SHA256 = "9f7109079c23eed9b41293260f99b8f625303ad2c8ce0cf439c04b5f826ee288"


def sdk_filter(member, destination):
    # The original SDK assumes /arm-eabi. Relocate its internal absolute
    # links rather than creating anything outside the extraction directory.
    if (member.issym() or member.islnk()) and member.linkname.startswith("/arm-eabi/"):
        member = copy.copy(member)
        target = f"motomagx-SDK-toolchain-{COMMIT}/" + member.linkname[len("/arm-eabi/"):]
        member.linkname = os.path.relpath(target, os.path.dirname(member.name)) if member.issym() else target
    return tarfile.data_filter(member, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive", type=Path, help="Optional cached archive; SHA-256 is still verified")
    args = parser.parse_args()
    destination = args.output.resolve()
    if destination.exists():
        parser.error("output must not exist (use a dedicated build directory)")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".tmm-sdk-", dir=destination.parent) as temporary:
        archive = Path(temporary) / "sdk.tar.gz"
        digest = hashlib.sha256()
        response = args.archive.open("rb") if args.archive else urllib.request.urlopen(URL, timeout=120)
        with response, archive.open("wb") as output:
            size = 0
            while chunk := response.read(128 * 1024):
                size += len(chunk)
                if size > 256 * 1024 * 1024:
                    raise ValueError("SDK archive too large")
                digest.update(chunk); output.write(chunk)
        if digest.hexdigest() != SHA256:
            raise ValueError("SDK SHA-256 mismatch")
        unpacked = Path(temporary) / "unpacked"
        with tarfile.open(archive) as tar:
            tar.extractall(unpacked, filter=sdk_filter)
        (unpacked / f"motomagx-SDK-toolchain-{COMMIT}").rename(destination)
    print(destination)


if __name__ == "__main__":
    main()
