"""Add PowerPoint animations and transitions to the deck that build_deck.js wrote.

pptxgenjs cannot write animations, so this post-processor injects them as OOXML:

* a ``<p:timing>`` main sequence per slide that starts by itself once the slide appears,
  with entrance effects (fade, float, zoom, wipe) on the shapes named in
  ``build/animations.json`` and staggered start times, so one click always means "next slide";
* a slide transition: fade, fade through black, or Morph (PowerPoint 2019 / Microsoft 365)
  with an automatic fade fallback for older viewers;
* the deck's theme colours and name (the same thing the pptx skill's apply_theme.js does),
  placeholder names (pptxgenjs ignores ``objectName`` on placeholders), and alt text that
  pptxgenjs fills with local file paths.

    python animate.py [deck.pptx]
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}
P = f"{{{NS['p']}}}"
XMLNS_P = f'xmlns:p="{NS["p"]}"'

TRANSITIONS = {
    "fade": '<p:transition {ns} spd="med"><p:fade/></p:transition>',
    "fadeBlack": '<p:transition {ns} spd="slow"><p:fade thruBlk="1"/></p:transition>',
    "morph": (
        '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" {ns}>'
        '<mc:Choice xmlns:p159="http://schemas.microsoft.com/office/powerpoint/2015/09/main" '
        'xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" Requires="p159">'
        '<p:transition spd="slow" p14:dur="1600"><p159:morph option="byObject"/></p:transition>'
        "</mc:Choice>"
        '<mc:Fallback><p:transition spd="slow"><p:fade/></p:transition></mc:Fallback>'
        "</mc:AlternateContent>"
    ),
}

# effect -> (presetID, presetSubtype)
PRESETS = {"fade": (10, 0), "float": (42, 0), "floatL": (42, 0), "zoom": (53, 16), "wipeL": (22, 8), "wipeU": (22, 4)}


class Ids:
    def __init__(self) -> None:
        self.n = 2  # 1 = timing root, 2 = main sequence

    def __call__(self) -> int:
        self.n += 1
        return self.n


def _target(spid: int) -> str:
    return f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'


def _set_visible(ids: Ids, spid: int) -> str:
    return (
        f'<p:set><p:cBhvr><p:cTn id="{ids()}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
        f"{_target(spid)}<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>"
        '<p:to><p:strVal val="visible"/></p:to></p:set>'
    )


def _filter(ids: Ids, spid: int, dur: int, name: str) -> str:
    return (
        f'<p:animEffect transition="in" filter="{name}"><p:cBhvr><p:cTn id="{ids()}" dur="{dur}"/>'
        f"{_target(spid)}</p:cBhvr></p:animEffect>"
    )


def _prop(ids: Ids, spid: int, dur: int, attr: str, start: str, end: str) -> str:
    def val(v: str) -> str:
        return f'<p:fltVal val="{v}"/>' if re.fullmatch(r"-?[0-9.]+", v) else f'<p:strVal val="{v}"/>'

    return (
        f'<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base">'
        f'<p:cTn id="{ids()}" dur="{dur}" decel="100000" fill="hold"/>{_target(spid)}'
        f"<p:attrNameLst><p:attrName>{attr}</p:attrName></p:attrNameLst></p:cBhvr>"
        f'<p:tavLst><p:tav tm="0"><p:val>{val(start)}</p:val></p:tav>'
        f'<p:tav tm="100000"><p:val>{val(end)}</p:val></p:tav></p:tavLst></p:anim>'
    )


def effect(ids: Ids, spid: int, kind: str, delay: int, dur: int) -> str:
    preset, subtype = PRESETS[kind]
    outer = ids()
    parts = [_set_visible(ids, spid)]
    if kind == "fade":
        parts.append(_filter(ids, spid, dur, "fade"))
    elif kind in ("float", "floatL"):
        parts.append(_filter(ids, spid, dur, "fade"))
        if kind == "float":
            parts.append(_prop(ids, spid, dur, "ppt_x", "#ppt_x", "#ppt_x"))
            parts.append(_prop(ids, spid, dur, "ppt_y", "#ppt_y+0.05", "#ppt_y"))
        else:
            parts.append(_prop(ids, spid, dur, "ppt_x", "#ppt_x-0.035", "#ppt_x"))
            parts.append(_prop(ids, spid, dur, "ppt_y", "#ppt_y", "#ppt_y"))
    elif kind == "zoom":
        parts.append(_prop(ids, spid, dur, "ppt_w", "#ppt_w*0.55", "#ppt_w"))
        parts.append(_prop(ids, spid, dur, "ppt_h", "#ppt_h*0.55", "#ppt_h"))
        parts.append(_filter(ids, spid, dur, "fade"))
    elif kind == "wipeL":
        parts.append(_filter(ids, spid, dur, "wipe(left)"))
    elif kind == "wipeU":
        parts.append(_filter(ids, spid, dur, "wipe(down)"))
    return (
        f'<p:par><p:cTn id="{outer}" presetID="{preset}" presetClass="entr" presetSubtype="{subtype}" '
        f'fill="hold" grpId="0" nodeType="withEffect"><p:stCondLst><p:cond delay="{delay}"/></p:stCondLst>'
        f"<p:childTnLst>{''.join(parts)}</p:childTnLst></p:cTn></p:par>"
    )


def media_nodes(ids: Ids, spid: int) -> str:
    """The media node and click-to-play trigger PowerPoint writes for an embedded video."""
    return (
        f'<p:video><p:cMediaNode vol="80000"><p:cTn id="{ids()}" fill="hold" display="0">'
        '<p:stCondLst><p:cond delay="indefinite"/></p:stCondLst></p:cTn>'
        f"{_target(spid)}</p:cMediaNode></p:video>"
        f'<p:seq concurrent="1" nextAc="seek"><p:cTn id="{ids()}" restart="whenNotActive" fill="hold" '
        'evtFilter="cancelBubble" nodeType="interactiveSeq">'
        f'<p:stCondLst><p:cond evt="onClick" delay="0">{_target(spid)}</p:cond></p:stCondLst>'
        '<p:endSync evt="end" delay="0"><p:rtn val="all"/></p:endSync><p:childTnLst>'
        f'<p:par><p:cTn id="{ids()}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
        f'<p:par><p:cTn id="{ids()}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
        f'<p:par><p:cTn id="{ids()}" presetID="2" presetClass="mediacall" presetSubtype="0" fill="hold" '
        'nodeType="clickEffect"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
        f'<p:cmd type="call" cmd="togglePause"><p:cBhvr><p:cTn id="{ids()}" dur="1" fill="hold"/>{_target(spid)}'
        "</p:cBhvr></p:cmd></p:childTnLst></p:cTn></p:par>"
        "</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>"
        "</p:childTnLst></p:cTn>"
        f'<p:nextCondLst><p:cond evt="onNext" delay="0">{_target(spid)}</p:cond></p:nextCondLst></p:seq>'
    )


def timing(effects: list[str], builds: list[str], extra: str = "") -> str:
    """One automatic step: every effect starts with the slide, at its own delay."""
    return (
        f"<p:timing {XMLNS_P}><p:tnLst><p:par>"
        '<p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
        '<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
        '<p:par><p:cTn id="{auto}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/>'
        '<p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond></p:stCondLst><p:childTnLst>'
        '<p:par><p:cTn id="{inner}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
        f"{''.join(effects)}"
        "</p:childTnLst></p:cTn></p:par>"
        "</p:childTnLst></p:cTn></p:par>"
        "</p:childTnLst></p:cTn>"
        '<p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
        '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst>'
        f"</p:seq>{extra}</p:childTnLst></p:cTn></p:par></p:tnLst>"
        f"<p:bldLst>{''.join(builds)}</p:bldLst></p:timing>"
    )


def scrub_alt_text(root: etree._Element) -> None:
    for el in root.iter(P + "cNvPr"):
        d = el.get("descr")
        if d and (d.startswith("/") or re.match(r"^[A-Za-z]:\\", d) or re.search(r"\.(png|gif|jpe?g)$", d, re.I)):
            el.set("descr", "FusionMap logo" if Path(d).name == "logo.png" else "")


def process_slide(xml: bytes, slide: dict) -> bytes:
    root = etree.fromstring(xml)
    scrub_alt_text(root)

    # name the placeholders in the order build_deck.js filled them
    phs = [
        sp for sp in root.iter(P + "sp")
        if (ph := sp.find("p:nvSpPr/p:nvPr/p:ph", NS)) is not None and ph.get("type") != "sldNum"
    ]
    if len(phs) != len(slide["ph"]):
        raise SystemExit(f"placeholder count mismatch: {len(phs)} in XML vs {slide['ph']}")
    for sp, name in zip(phs, slide["ph"]):
        sp.find("p:nvSpPr/p:cNvPr", NS).set("name", name)

    shapes: dict[str, tuple[int, str]] = {}
    for c in root.iter(P + "cNvPr"):
        kind = etree.QName(c.getparent().getparent()).localname  # sp | pic | graphicFrame | cxnSp
        name = c.get("name")
        if name in shapes and any(a["name"] == name for a in slide["anim"]):
            raise SystemExit(f"ambiguous shape name {name!r}")
        shapes[name] = (int(c.get("id")), kind)

    for old in root.findall("p:transition", NS) + root.findall("p:timing", NS) + root.findall("mc:AlternateContent", NS):
        root.remove(old)

    anchor = root.find("p:clrMapOvr", NS)
    if anchor is None:
        anchor = root.find("p:cSld", NS)
    pos = list(root).index(anchor) + 1
    root.insert(pos, etree.fromstring(TRANSITIONS[slide["transition"]].format(ns=XMLNS_P)))

    if slide["anim"]:
        ids = Ids()
        auto, inner = ids(), ids()
        effects, builds, built = [], [], set()
        for a in sorted(slide["anim"], key=lambda a: a["delay"]):
            if a["name"] not in shapes:
                raise SystemExit(f"no shape named {a['name']!r}")
            spid, kind = shapes[a["name"]]
            effects.append(effect(ids, spid, a["effect"], int(a["delay"]), int(a["dur"])))
            if spid in built:
                continue
            built.add(spid)
            if kind == "sp":
                builds.append(f'<p:bldP spid="{spid}" grpId="0" animBg="1"/>')
            elif kind == "graphicFrame":
                builds.append(f'<p:bldGraphic spid="{spid}" grpId="0"><p:bldAsOne/></p:bldGraphic>')
        videos = [
            int(pic.find("p:nvPicPr/p:cNvPr", NS).get("id"))
            for pic in root.iter(P + "pic")
            if pic.find("p:nvPicPr/p:nvPr/a:videoFile", NS) is not None
        ]
        extra = "".join(media_nodes(ids, v) for v in videos)
        xml_t = timing(effects, builds, extra).replace('id="{auto}"', f'id="{auto}"').replace('id="{inner}"', f'id="{inner}"')
        root.insert(pos + 1, etree.fromstring(xml_t))

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def theme_xml(xml: str, theme: dict) -> str:
    name = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", theme["name"])
    name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    slots = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink"]
    cols = theme["colors"]
    for k in slots:
        if not re.fullmatch(r"[0-9A-Fa-f]{6}", cols[k]):
            raise SystemExit(f"theme colour {k} must be six hex digits")
    scheme = f'<a:clrScheme name="{name}">' + "".join(f'<a:{k}><a:srgbClr val="{cols[k].upper()}"/></a:{k}>' for k in slots) + "</a:clrScheme>"
    xml = re.sub(r"<a:clrScheme\b[\s\S]*?</a:clrScheme>", lambda _: scheme, xml, count=1)
    return re.sub(r'(<a:(?:theme|fontScheme)\b[^>]*?\bname=")[^"]*"', lambda m: f'{m.group(1)}{name}"', xml)


def dedupe_media(parts: dict[str, bytes]) -> int:
    """pptxgenjs embeds a picture once per use; point every relationship at one copy."""
    keep: dict[str, str] = {}
    alias: dict[str, str] = {}
    for name in sorted(n for n in parts if n.startswith("ppt/media/")):
        digest = hashlib.sha256(parts[name]).hexdigest()
        if digest in keep:
            alias[Path(name).name] = Path(keep[digest]).name
        else:
            keep[digest] = name
    if not alias:
        return 0
    pattern = re.compile(r'Target="\.\./media/([^"]+)"')
    for name in [n for n in parts if n.endswith(".rels")]:
        xml = parts[name].decode("utf-8")
        new = pattern.sub(lambda m: f'Target="../media/{alias.get(m.group(1), m.group(1))}"', xml)
        if new != xml:
            parts[name] = new.encode("utf-8")
    saved = 0
    for dup in alias:
        saved += len(parts.pop(f"ppt/media/{dup}"))
    return saved


def main() -> None:
    deck = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "FusionMap_Pitch.pptx"
    spec = json.loads((HERE / "build" / "animations.json").read_text())
    src = zipfile.ZipFile(deck)
    out: dict[str, bytes] = {}
    n_eff = 0
    for info in src.infolist():
        data = src.read(info.filename)
        m = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", info.filename)
        if m:
            slide = spec["slides"][int(m.group(1)) - 1]
            data = process_slide(data, slide)
            n_eff += len(slide["anim"])
        elif re.fullmatch(r"ppt/(slideLayouts|slideMasters)/[^/]+\.xml", info.filename):
            root = etree.fromstring(data)
            scrub_alt_text(root)
            data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        elif info.filename == "ppt/theme/theme1.xml":
            data = theme_xml(data.decode("utf-8"), spec["theme"]).encode("utf-8")
        out[info.filename] = data
    src.close()
    saved = dedupe_media(out)
    tmp = deck.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in out.items():
            # GIFs and PNGs are already compressed
            z.writestr(name, data, compress_type=zipfile.ZIP_STORED if name.endswith((".gif", ".png")) else zipfile.ZIP_DEFLATED)
    tmp.replace(deck)
    morphs = sum(s["transition"] == "morph" for s in spec["slides"])
    print(f"animated {deck.name}: {len(spec['slides'])} slides, {n_eff} entrance effects, {morphs} Morph transitions; "
          f"de-duplicated media saved {saved / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
