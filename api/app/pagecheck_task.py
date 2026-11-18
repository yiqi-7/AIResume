"""One disposable task. Its entire process group is bounded by the worker deadline."""

import logging
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote

from defusedxml import ElementTree as SafeET
from pypdf import PdfReader

from .documents import W, parse_docx

PROFILE = '''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
 <item oor:path="/org.openoffice.Office.Common/Security/Scripting">
  <prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>
 </item>
 <item oor:path="/org.openoffice.Office.Writer/Content/Update">
  <prop oor:name="Link" oor:op="fuse"><value>0</value></prop>
 </item>
</oor:items>'''


def field_instructions(root) -> list[str]:
    instructions = [element.attrib.get(W + "instr", "")
                    for element in root.iter(W + "fldSimple")]
    stack = []
    for element in root.iter():
        if element.tag == W + "fldChar":
            kind = element.attrib.get(W + "fldCharType")
            if kind == "begin":
                stack.append("")
            elif stack and kind in {"separate", "end"}:
                instructions.append(stack[-1])
                if kind == "end":
                    stack.pop()
                else:
                    stack[-1] = ""
        elif element.tag == W + "instrText":
            if stack:
                # A single field command can be split across multiple runs.
                stack[-1] += element.text or ""
            else:
                instructions.append(element.text or "")
    return instructions + stack


def has_active_content(raw: bytes) -> bool:
    import io

    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        overrides, defaults = {}, {}
        if "[Content_Types].xml" in package.namelist():
            for part in SafeET.fromstring(package.read("[Content_Types].xml")):
                content_type = part.attrib.get("ContentType", "").casefold()
                if any(value in content_type for value in ("macroenabled", "vbaproject", "activex")):
                    return True
                if "PartName" in part.attrib:
                    overrides[unquote(part.attrib["PartName"]).lstrip("/")] = content_type
                elif "Extension" in part.attrib:
                    defaults[part.attrib["Extension"].casefold()] = content_type
        for name in package.namelist():
            lowered = name.casefold()
            if "vbaproject" in lowered or lowered.startswith("word/embeddings/"):
                return True
            if lowered.endswith(".rels"):
                for rel in SafeET.fromstring(package.read(name)):
                    relation_type = rel.attrib.get("Type", "").casefold()
                    if any(value in relation_type for value in ("vbaproject", "/oleobject", "/control")):
                        return True
                    if (rel.attrib.get("TargetMode", "").casefold() == "external"
                            and not rel.attrib.get("Type", "").endswith("/hyperlink")):
                        return True
            content_type = overrides.get(name, defaults.get(lowered.rsplit(".", 1)[-1], ""))
            if lowered.endswith(".xml") or content_type.endswith("xml"):
                root = SafeET.fromstring(package.read(name))
                if root.find(".//" + W + "object") is not None:
                    return True
                if any(re.search(r"\b(INCLUDETEXT|INCLUDEPICTURE|DDEAUTO|DDE|LINK|DATABASE)\b",
                                 instruction, re.IGNORECASE)
                       for instruction in field_instructions(root)):
                    return True
    return False


def run(directory: Path) -> int:
    raw = (directory / "source.docx").read_bytes()
    # Bound and validate the ZIP/XML before exposing it to the layout engine.
    parse_docx(raw)
    if has_active_content(raw):
        return 4
    profile = directory / "profile"
    profile.mkdir()
    (profile / "registrymodifications.xcu").write_text(PROFILE, encoding="utf-8")
    output = directory / "output"
    output.mkdir()
    result = subprocess.run(
        ["/usr/bin/libreoffice", "-env:UserInstallation=" + profile.as_uri(),
         "--headless", "--invisible", "--nologo", "--nodefault", "--nolockcheck", "--norestore",
         "--convert-to",
         'pdf:writer_pdf_Export:{"IsSkipEmptyPages":{"type":"boolean","value":"false"}}',
         "--outdir", str(output), str(directory / "source.docx")],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=False,
    )
    pdf = output / "source.pdf"
    if result.returncode or not pdf.is_file():
        return 3
    with pdf.open("rb") as file:
        pages = len(PdfReader(file, strict=True).pages)
    if pages < 1:
        return 3
    print(pages, flush=True)
    return 0


if __name__ == "__main__":
    # Library diagnostics must never contain document text in service logs.
    logging.disable(logging.CRITICAL)
    try:
        exit_code = run(Path(sys.argv[1]))
    except Exception:
        exit_code = 3
    raise SystemExit(exit_code)
