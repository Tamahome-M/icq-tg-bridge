#!/usr/bin/env python3
"""Build a separate MIDP probe with the cached TeleMotoMax build tools."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, required=True,
                        help="TeleMotoMax build directory containing jdk, wtk and proguard")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    chain = args.toolchain.resolve()
    output = args.output.resolve()
    compiler = chain / "jdk/bin/javac"
    java = chain / "jdk/bin/java"
    proguard = chain / "proguard/lib/proguard.jar"
    libraries = [chain / "wtk/lib/cldcapi11.jar", chain / "wtk/lib/midpapi20.jar"]
    for path in [compiler, java, proguard, *libraries]:
        if not path.is_file():
            parser.error(f"Missing {path}; first run telemotomax/build.sh with this toolchain directory")
    output.mkdir(parents=True, exist_ok=True)
    attributes = {
        "MIDlet-Name": "TMM Flip Probe",
        "MIDlet-Version": "0.1.0",
        "MIDlet-Vendor": "TeleMotoMax",
        "MIDlet-1": "TMM Flip Probe,,FlipProbe",
        "MicroEdition-Configuration": "CLDC-1.1",
        "MicroEdition-Profile": "MIDP-2.0",
        "Background": "True",
        "FlipInsensitive": "True",
    }
    manifest = "Manifest-Version: 1.0\r\n" + "".join(
        f"{name}: {value}\r\n" for name, value in attributes.items()) + "\r\n"
    with tempfile.TemporaryDirectory(prefix="tmm-flip-probe-") as directory:
        work = Path(directory)
        classes = work / "classes"
        classes.mkdir()
        source = Path(__file__).parent
        vendor_classes = work / "vendor-stubs"
        vendor_classes.mkdir()
        compile_args = [str(compiler), "-encoding", "UTF-8", "-source", "1.3", "-target", "1.1",
                        "-Xlint:-options", "-bootclasspath", ":".join(map(str, libraries))]
        subprocess.run([*compile_args, "-d", str(vendor_classes),
                        *map(str, sorted((source / "stubs").rglob("*.java")))], check=True)
        vendor = work / "vendor-stubs.jar"
        with zipfile.ZipFile(vendor, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(vendor_classes.rglob("*.class")):
                archive.write(path, path.relative_to(vendor_classes).as_posix())
        subprocess.run([*compile_args, "-classpath", str(vendor), "-d", str(classes),
                        *map(str, sorted(source.glob("*.java")))], check=True)
        raw = work / "raw.jar"
        with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("META-INF/MANIFEST.MF", manifest)
            for path in sorted(classes.rglob("*.class")):
                archive.write(path, path.relative_to(classes).as_posix())
        jar = output / "TmmFlipProbe.jar"
        config = work / "probe.pro"
        # Argument paths stay in argv; quote ProGuard's own file format separately.
        def quoted(path):
            value = str(path)
            if "'" in value or "\n" in value or "\r" in value:
                parser.error("ProGuard paths cannot contain quotes or newlines")
            return "'" + value + "'"
        config.write_text("\n".join([
            "-injars " + quoted(raw), "-outjars " + quoted(jar),
            *("-libraryjars " + quoted(path) for path in libraries),
            "-libraryjars " + quoted(vendor),
            "-microedition", "-dontshrink", "-dontoptimize", "-dontobfuscate",
            "-dontnote", "-keepattributes Exceptions,InnerClasses",
        ]) + "\n", encoding="utf-8")
        subprocess.run([str(java), "-cp", str(proguard), "proguard.ProGuard",
                        "@" + str(config)], check=True)
    jad = "".join(f"{name}: {value}\n" for name, value in attributes.items())
    jad += f"MIDlet-Jar-URL: {jar.name}\nMIDlet-Jar-Size: {jar.stat().st_size}\n"
    (output / "TmmFlipProbe.jad").write_text(jad, encoding="utf-8")
    print(f"{jar} ({jar.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
