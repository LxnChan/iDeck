#!/usr/bin/env python3
"""Collect main-library or executable relink inputs from an Xcode build log.

This copies object code; keep the output private until source/license review.
Use only a trusted build log. No build or signing is executed by this tool.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import shutil


class RelinkError(ValueError):
    pass


RUNTIME_PREFIXES = ("@rpath/", "@loader_path/", "@executable_path/")
SYSTEM_LIBRARIES = {
    "System", "c", "c++", "objc", "z", "sqlite3", "lzma", "m", "dl", "pthread",
    "resolv", "bz2", "iconv", "xml2", "compression", "archive",
}
PRIVATE_SUFFIXES = {".mobileprovision", ".provisionprofile", ".p12", ".pfx", ".pem", ".key", ".cer", ".crt", ".log"}
PRIVATE_PARTS = {"private", ".ssh", "secrets", "credentials", "valve", "steamapps", "userdata"}
DISCARD_PATH_OPTIONS = {"-object_path_lto", "-dependency_info", "-add_ast_path", "-map", "-serialize-diagnostics"}
TEXT_INPUT_OPTIONS = {"-exported_symbols_list", "-unexported_symbols_list", "-order_file"}


def path_at(value, cwd):
    path = Path(value)
    return path if path.is_absolute() else cwd / path


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def response_tokens(values, cwd, stack=()):
    result = []
    for value in values:
        if value.startswith("@") and not value.startswith(RUNTIME_PREFIXES):
            path = path_at(value[1:], cwd).resolve()
            if path in stack:
                raise RelinkError(f"Recursive response file: {path.name}")
            if not path.is_file():
                raise RelinkError(f"Missing response file: {path}")
            result.extend(response_tokens(shlex.split(path.read_text(encoding="utf-8")), cwd, stack + (path,)))
        else:
            result.append(value)
    return result


def normalize_linker_arguments(values, cwd):
    """Keep driver and linker tokens distinct while expanding both response forms."""
    result = []
    i = 0
    while i < len(values):
        value = values[i]
        if value == "-Xlinker":
            if i + 1 == len(values):
                raise RelinkError("-Xlinker has no argument")
            result.extend((x, True) for x in response_tokens([values[i + 1]], cwd))
            i += 2
        elif value.startswith("-Wl,"):
            result.extend((x, True) for x in response_tokens(value[4:].split(","), cwd))
            i += 1
        elif value.startswith("@") and not value.startswith(RUNTIME_PREFIXES):
            result.extend(normalize_linker_arguments(response_tokens([value], cwd), cwd))
            i += 1
        else:
            result.append((value, False))
            i += 1
    return result


def select_link_command(log_path):
    cwd = log_path.resolve().parent
    candidates = []
    log = log_path.read_text(encoding="utf-8", errors="replace")
    for line in re.sub(r"\\\r?\n", " ", log).splitlines():
        line = line.strip()
        if line.startswith("cd "):
            parts = shlex.split(line)
            if len(parts) == 2:
                cwd = path_at(parts[1], cwd).resolve()
            continue
        if "clang" not in line:
            continue
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        driver_index = next((i for i, x in enumerate(parts) if Path(x).name in {"clang", "clang++"}), None)
        if driver_index is None:
            continue
        raw_args = parts[driver_index + 1:]
        if "-c" in raw_args:
            continue
        if "-o" in raw_args:
            output_index = raw_args.index("-o")
            if output_index + 1 < len(raw_args) and Path(raw_args[output_index + 1]).name not in {"Madeira", "Madeira.debug.dylib"}:
                continue
        args = normalize_linker_arguments(raw_args, cwd)
        if any(x == "-c" for x, _ in args):
            continue
        outputs = [args[i + 1][0] for i, (x, _) in enumerate(args[:-1]) if x == "-o"]
        if len(outputs) != 1 or Path(outputs[0]).name not in {"Madeira", "Madeira.debug.dylib"}:
            continue
        target = next((args[i + 1][0] for i, (x, _) in enumerate(args[:-1]) if x == "-target"), "")
        if target and ("apple-ios" not in target or "simulator" in target):
            continue
        candidates.append((parts[driver_index], args, cwd, Path(outputs[0]).name, target))
    debug = [x for x in candidates if x[3] == "Madeira.debug.dylib"]
    chosen = debug or candidates
    if len(chosen) != 1:
        raise RelinkError(f"Expected one main iOS link command; found {len(chosen)}")
    return chosen[0], log


def ensure_public_input(path):
    for candidate in (path, path.resolve()):
        parts = candidate.parts
        # macOS resolves ordinary temporary paths under these system roots.
        # Exempt their leading "private" only; inspect every later component.
        if parts[:3] in {("/", "private", "var"), ("/", "private", "tmp")}:
            parts = parts[2:]
        if candidate.suffix.lower() in PRIVATE_SUFFIXES or PRIVATE_PARTS.intersection(x.lower() for x in parts):
            raise RelinkError(f"Refusing credential, private log or third-party payload: {path.name}")
        if candidate.name.lower() in {"steamclient.dll", "steamclient64.dll", "steam.exe", "steamclient.o"}:
            raise RelinkError(f"Refusing Valve payload: {path.name}")


class Collector:
    def __init__(self, output, cwd, sdk, toolchain):
        self.output, self.cwd, self.sdk, self.toolchain = output, cwd, sdk, toolchain
        self.inputs = []
        self.staged = {}
        self.names = set()
        self.frameworks = {}

    def portable(self, value):
        if value.startswith(RUNTIME_PREFIXES):
            return value
        path = path_at(value, self.cwd).resolve()
        for base, placeholder in ((self.sdk, "@SDK@"), (self.toolchain, "@TOOLCHAIN@")):
            if base:
                try:
                    relative = path.relative_to(base.resolve())
                except ValueError:
                    continue
                return placeholder + "/" + relative.as_posix()
        if value.startswith("/usr/lib/"):
            return "@SDK@" + value
        return None

    def stage(self, value, kind="objects"):
        src = path_at(value, self.cwd).resolve()
        ensure_public_input(src)
        allowed = {".a", ".o", ".bc"} if kind != "metadata" else {".txt", ".exp", ".list", ".symbols", ""}
        if src.suffix.lower() not in allowed or not src.is_file():
            raise RelinkError(f"Unsupported or missing relink input: {src}")
        if src in self.staged:
            return self.staged[src]
        digest = sha256_file(src)
        relative = f"{kind}/{src.name}"
        if relative in self.names:
            relative = f"{kind}/{digest[:12]}-{src.name}"
        self.names.add(relative)
        dst = self.output / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        self.inputs.append({"path": relative, "sha256": digest, "size": dst.stat().st_size})
        result = "@ROOT@/" + relative
        self.staged[src] = result
        return result

    def framework(self, name, search):
        if not re.fullmatch(r"[A-Za-z0-9_]+", name):
            raise RelinkError(f"Invalid framework name: {name}")
        for directory in search:
            binary = directory / (name + ".framework") / name
            if binary.is_file():
                if self.portable(str(binary)):
                    return
                ensure_public_input(binary)
                self.frameworks[name] = {"name": name, "sha256": sha256_file(binary)}
                return
        if name == "StikJIT":
            self.frameworks.setdefault(name, {"name": name})

    def library(self, name, search):
        for directory in search:
            for extension in (".tbd", ".dylib", ".a"):
                candidate = directory / ("lib" + name + extension)
                if candidate.is_file():
                    if self.portable(str(candidate)):
                        return "-l" + name
                    if extension == ".a":
                        return self.stage(str(candidate), "libraries")
                    raise RelinkError(f"External dynamic library requires an explicit redistribution/relink recipe: {candidate.name}")
        if name in SYSTEM_LIBRARIES or name.startswith(("swift", "clang_rt.")):
            return "-l" + name
        raise RelinkError(f"Cannot resolve static library -l{name}")


def filelist_inputs(value, cwd):
    raw, separator, base = value.partition(",")
    path = path_at(raw, cwd)
    root = path_at(base, cwd) if separator else cwd
    if not path.is_file():
        raise RelinkError(f"Missing linker filelist: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        # Xcode filelists contain one path per line, including unquoted spaces.
        if line.startswith(('"', "'")):
            parts = shlex.split(line)
            if len(parts) != 1:
                raise RelinkError("Filelist entry must contain one path")
            line = parts[0]
        yield str(path_at(line, root))


def collect(log_path, output):
    (driver, args, cwd, output_name, target), _ = select_link_command(log_path)
    sdk_value = next((args[i + 1][0] for i, (x, _) in enumerate(args[:-1]) if x == "-isysroot"), None)
    if not sdk_value:
        raise RelinkError("Main link command has no -isysroot")
    sdk = path_at(sdk_value, cwd)
    toolchain = next((x for x in Path(driver).parents if x.suffix == ".xctoolchain"), None)
    search, framework_search = [], []
    for i, (value, _) in enumerate(args):
        for prefix, paths in (("-L", search), ("-F", framework_search)):
            if value == prefix and i + 1 < len(args):
                paths.append(path_at(args[i + 1][0], cwd))
            elif value.startswith(prefix) and len(value) > 2:
                paths.append(path_at(value[2:], cwd))
    output.mkdir(parents=True, exist_ok=False)
    collector = Collector(output, cwd, sdk, toolchain)
    result = []

    def emit(value, linker=False):
        if linker:
            result.extend(["-Xlinker", value])
        else:
            result.append(value)

    i = 0
    while i < len(args):
        value, linker = args[i]
        if value in DISCARD_PATH_OPTIONS:
            if i + 1 == len(args):
                raise RelinkError(f"{value} has no value")
            i += 2
            continue
        if value == "-l":
            if i + 1 == len(args):
                raise RelinkError("-l has no library name")
            emit(collector.library(args[i + 1][0], search), linker)
            i += 2
            continue
        if value in {"-L", "-F"} or (value.startswith(("-L", "-F")) and len(value) > 2):
            prefix = value[:2]
            source = args[i + 1][0] if value == prefix else value[2:]
            portable = collector.portable(source)
            if portable:
                emit(prefix + portable, linker)
            i += 2 if value == prefix else 1
            continue
        if value in {"-isysroot", "-syslibroot", "-o", "-filelist", "-force_load", "-framework", "-weak_framework"} | TEXT_INPUT_OPTIONS:
            if i + 1 == len(args):
                raise RelinkError(f"{value} has no value")
            argument = args[i + 1][0]
            if value == "-filelist":
                for obj in filelist_inputs(argument, cwd):
                    emit(collector.stage(obj), linker)
            else:
                emit(value, linker)
                if value in {"-isysroot", "-syslibroot"}:
                    replacement = "@SDK@"
                elif value == "-o":
                    replacement = "@ROOT@/" + output_name
                elif value == "-force_load":
                    replacement = collector.stage(argument, "libraries")
                elif value in TEXT_INPUT_OPTIONS:
                    replacement = collector.stage(argument, "metadata")
                else:
                    collector.framework(argument, framework_search)
                    replacement = argument
                emit(replacement, linker)
            i += 2
            continue
        if value.startswith("-l") and len(value) > 2 and value not in {"-ld_classic", "-ld_new", "-lto_library"}:
            emit(collector.library(value[2:], search), linker)
        elif not value.startswith("-") and Path(value).suffix.lower() in {".a", ".o", ".bc", ".dylib", ".tbd"}:
            portable = collector.portable(value)
            emit(portable or collector.stage(value, "libraries" if value.endswith(".a") else "objects"), linker)
        elif not value.startswith(("-",) + RUNTIME_PREFIXES) and ("/" in value or "\\" in value):
            portable = collector.portable(value)
            if not portable:
                raise RelinkError(f"Untranslated host path in link command: {value}")
            emit(portable, linker)
        else:
            emit(value, linker)
        i += 1
    if not collector.inputs:
        raise RelinkError("Main link command provided no object or archive inputs")
    metadata = {
        "driver": Path(driver).name, "output": output_name, "target": target,
        "sdk": sdk.name, "toolchain": toolchain.name if toolchain else None,
        "build_log_sha256": sha256_file(log_path),
        "external_frameworks": list(collector.frameworks.values()),
        "scope": "Exact link inputs only; source/license review and signing are separate.",
    }
    (output / "link-args.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (output / "INPUTS.json").write_text(json.dumps(collector.inputs, indent=2) + "\n", encoding="utf-8")
    (output / "BUILD.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (output / "relink.py").write_text(RELINK_SCRIPT, encoding="utf-8")
    return len(collector.inputs)


RELINK_SCRIPT = '''#!/usr/bin/env python3
"""Relink the collected main binary. This tool does not run codesign.

Libraries may be replaced to exercise relinking rights. --verify-inputs checks
the original input manifest and should be omitted when using modified inputs.
"""
from pathlib import Path
import argparse, hashlib, json, shlex, subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--framework-path', type=Path, action='append', default=[], help='Directory containing externally supplied frameworks; repeat as needed')
parser.add_argument('--output', type=Path)
parser.add_argument('--sdk', type=Path)
parser.add_argument('--compiler', type=Path)
parser.add_argument('--toolchain-root', type=Path)
parser.add_argument('--verify-inputs', action='store_true')
parser.add_argument('--dry-run', action='store_true')
options = parser.parse_args()
root = Path(__file__).resolve().parent
build = json.loads((root / 'BUILD.json').read_text(encoding='utf-8'))
def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()
if options.verify_inputs:
    for entry in json.loads((root / 'INPUTS.json').read_text(encoding='utf-8')):
        path = root / entry['path']
        if not path.is_file() or sha256_file(path) != entry['sha256']:
            parser.error('Original relink input hash mismatch: ' + entry['path'])
sdk = str(options.sdk.resolve()) if options.sdk else subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
compiler = str(options.compiler.resolve()) if options.compiler else subprocess.check_output(['xcrun', '--find', build['driver']], text=True).strip()
toolchain = options.toolchain_root or next((x for x in Path(compiler).parents if x.suffix == '.xctoolchain'), Path(compiler).parent.parent)
framework_paths = [x.resolve().parent if x.suffix == '.framework' else x.resolve() for x in options.framework_path]
for framework in build['external_frameworks']:
    name = framework['name']
    binary = next((x / (name + '.framework') / name for x in framework_paths if (x / (name + '.framework') / name).is_file()), None)
    if binary is None:
        parser.error('Supply --framework-path DIR containing ' + name + '.framework')
    if options.verify_inputs and 'sha256' in framework and sha256_file(binary) != framework['sha256']:
        parser.error('Original framework hash mismatch: ' + name)
output = options.output.resolve() if options.output else root / build['output']
args = []
for value in json.loads((root / 'link-args.json').read_text(encoding='utf-8')):
    if value == '@ROOT@/' + build['output']:
        value = str(output)
    else:
        value = value.replace('@ROOT@', str(root)).replace('@SDK@', sdk).replace('@TOOLCHAIN@', str(toolchain))
    args.append(value)
for path in framework_paths:
    args.append('-F' + str(path))
command = [compiler] + args
if options.dry_run:
    print(shlex.join(command))
else:
    subprocess.run(command, check=True)
    print('Relink complete: ' + str(output))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_log", type=Path)
    parser.add_argument("output", type=Path)
    options = parser.parse_args()
    try:
        count = collect(options.build_log, options.output.resolve())
    except (RelinkError, OSError, ValueError) as error:
        parser.exit(1, f"prepare-relink: {error}\n")
    print("Staged", count, "link inputs")


if __name__ == "__main__":
    main()
