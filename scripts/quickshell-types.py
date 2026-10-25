#!/usr/bin/env python3
"""Write Quickshell's QML type information to DEST/Quickshell, fixed for qmllint.

    scripts/quickshell-types.py DEST

scripts/lint.sh lints against this copy (`qmllint --bare -I DEST -I /usr/lib/qt6/qml`).
The installed files trip qmllint over Quickshell's packaging rather than over
anything in Jupiter-dotfiles, so every Quickshell type would otherwise go unchecked:

- property types name C++ classes without their namespace (`BluetoothAdapter`
  for `qs::bluetooth::BluetoothAdapter`) or by their QML name (`DBusMenuHandle`);
- submodules extend core types without declaring `depends Quickshell`, or name
  another submodule's types without depending on it (Hyprland's toplevels hand
  out Wayland's `Toplevel`), and the window types are an `optional import`; `prefer` points at resources only the
  running shell can read;
- core's value types (margins) do not resolve across its import cycle with the
  window module, nor do its enums where a copied core type names them
  (PopupAnchor's edges);
- since Qt 6.12, a module declares another module's types it uses as opaque
  stand-ins (`isTypeOpaque`), which hide the real declaration's members, so
  each is replaced by a copy of the real one;
- PanelWindow is declared uncreatable, though every panel creates one;
- Process.exited passes a QProcess::ExitStatus, which nothing declares, and
  Process.environment is a QVariantHash, which QML fills from a JS object;
- flag properties (PopupAnchor's edges) name a `Flags` type nothing declares
  either, where their enum is meant.
"""

import pathlib
import re
import sys


def first(pattern: str, text: str, flags: int = 0) -> str:
    """The first group of the match the installed files always have."""
    match = re.search(pattern, text, flags)
    if match is None:
        sys.exit(
            f"quickshell-types.py: no {pattern!r} in the qmltypes any more"
        )
    return match.group(1)


source = pathlib.Path("/usr/lib/qt6/qml/Quickshell")
target = pathlib.Path(sys.argv[1]) / "Quickshell"

types = {path: path.read_text() for path in source.rglob("*.qmltypes")}
real = {
    first(r'name: "([^"]+)"', block): block
    for text in types.values()
    for block in re.findall(
        r"^    Component \{\n.*?^    \}\n", text, re.S | re.M
    )
    if "isTypeOpaque: true" not in block
}


def unhide(stand_in: re.Match[str]) -> str:
    block = real.get(stand_in.group(1), stand_in.group(0))
    # A value type gets its copy below, with core's others.
    return (
        ""
        if 'accessSemantics: "value"' in block
        and block is not stand_in.group(0)
        else block
    )


types = {
    path: re.sub(
        r'^    Component \{\s*isTypeOpaque: true;?\s*name: "([^"]+)";?[^{}]*?\}\n',
        unhide,
        text,
        flags=re.M,
    )
    for path, text in types.items()
}
components = [
    (match.group(1), re.findall(r'"[\w.]+/(\w+) [\d.]+"', match.group(2)))
    for text in types.values()
    for match in re.finditer(
        r'Component \{[^{}]*?\bname: "([^"]+)"([^{}]*)', text, re.S
    )
]
declared = {name for name, _ in components}
aliases: dict[str, set[str]] = {}
for name, exports in components:
    for alias in {name.rsplit("::", 1)[-1], *exports}:
        aliases.setdefault(alias, set()).add(name)
modules = {
    path: first(r"^module (\S+)", (path.parent / "qmldir").read_text(), re.M)
    for path in types
}
module_of = {
    name: modules[path]
    for path, text in types.items()
    for name in re.findall(r'Component \{[^{}]*?\bname: "([^"]+)"', text, re.S)
}
core = types[source / "quickshell-core.qmltypes"]
value_types = {
    first(r'name: "([^"]+)"', block): block
    for block in re.findall(
        r"^    Component \{\n.*?^    \}\n", core, re.S | re.M
    )
    if 'accessSemantics: "value"' in block
}
enums = {
    first(r'name: "([^"]+)"', block): block
    for block in re.findall(
        r"^    Component \{\n.*?^    \}\n", core, re.S | re.M
    )
    if 'accessSemantics: "none"' in block and "Enum {" in block
}
exit_status = """    Component {
        name: "QProcess"
        accessSemantics: "reference"
        prototype: "QObject"
        Enum { name: "ExitStatus"; values: ["NormalExit", "CrashExit"] }
    }
"""


def resolve(name: str) -> str:
    if name in declared:
        return name
    candidates = aliases.get(name.rsplit("::", 1)[-1], set())
    return next(iter(candidates)) if len(candidates) == 1 else name


def reference(match: re.Match[str]) -> str:
    listed = re.fullmatch(r"QList<(.+)\*>", match.group(2))
    name = listed.group(1) if listed else match.group(2)
    enum = re.fullmatch(r"(.+)::(?:Enum|Flags)", name)
    name = resolve(enum.group(1)) + "::Enum" if enum else resolve(name)
    return f'{match.group(1)}: "{name}"' + ("; isList: true" if listed else "")


for path in source.rglob("*"):
    out = target / path.relative_to(source)
    if path.is_dir():
        out.mkdir(parents=True, exist_ok=True)
    elif path.suffix == ".qmltypes":
        text = re.sub(
            r'\b(type|prototype|extension|attachedType): "([^"]+)"',
            reference,
            types[path],
        )
        text = text.replace('"QVariantHash"', '"QVariantMap"')
        text = re.sub(
            r'(exports: \["Quickshell._Window/PanelWindow [\d.]+"\]\s*)isCreatable: false',
            r"\1isCreatable: true",
            text,
        )
        if path.parent != source:
            text = text.replace(
                "Module {\n",
                "Module {\n"
                + "".join(
                    block
                    for name, block in value_types.items()
                    if f'type: "{name}"' in text
                )
                + "".join(
                    block
                    for name, block in enums.items()
                    if f'"{name}::' in text
                ),
                1,
            )
        if "QProcess::ExitStatus" in text:
            text = text.replace("Module {\n", "Module {\n" + exit_status, 1)
        out.write_text(text)
    elif path.name == "qmldir":
        text = re.sub(
            r"^prefer .*\n", "", path.read_text(), flags=re.M
        ).replace("optional import ", "import ")
        if path.parent != source and "depends Quickshell\n" not in text:
            text += "depends Quickshell\n"
        own = [
            types_path
            for types_path in types
            if types_path.parent == path.parent
        ]
        used = {
            module_of[resolved]
            for types_path in own
            for name in re.findall(
                r'\b(?:type|prototype): "([^"]+)"', types[types_path]
            )
            if (resolved := resolve(name)) in module_of
        }
        for module in sorted(
            used - {"Quickshell", *(modules[types_path] for types_path in own)}
        ):
            if f"depends {module}\n" not in text:
                text += f"depends {module}\n"
        out.write_text(text)
    elif path.suffix == ".qml":
        out.write_text(path.read_text())
