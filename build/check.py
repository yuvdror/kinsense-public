#!/usr/bin/env python3
"""Validate the built site.

    python3 build/check.py

Checks what actually breaks on a static host and is invisible until someone reports
it: unbalanced markup, links that 404, hreflang sets that are not reciprocal (Google
silently ignores the whole cluster if they are not), and a sitemap listing URLs that
do not exist.

Link resolution mirrors vercel.json — a bare /privacy resolves through the rewrite —
so this fails if the routing config and the pages ever disagree.
"""
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).parent.parent
VOID = {"meta", "link", "br", "hr", "img", "input", "source", "area", "base", "col"}


class Doc(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.unbalanced = [], []
        self.ids, self.links, self.hreflangs = set(), [], []
        self.lang = self.dir = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "html":
            self.lang, self.dir = a.get("lang"), a.get("dir")
        if tag == "a" and "href" in a:
            self.links.append(a["href"])
        if tag == "link":
            if a.get("rel") == "alternate" and "hreflang" in a:
                self.hreflangs.append((a["hreflang"], a.get("href", "")))
            elif a.get("rel") == "stylesheet":
                self.links.append(a.get("href", ""))
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.unbalanced.append(tag)


def rewrites() -> dict[str, str]:
    cfg = json.loads((ROOT / "vercel.json").read_text())
    return {r["source"]: r["destination"] for r in cfg.get("rewrites", [])}


def apply_rewrites(path: str, rw: dict[str, str]) -> str:
    """Resolve a path through vercel.json's rewrites, including `:param` segments.

    Vercel matches `/:lang/delete-account` against any single first segment and
    substitutes it into the destination. Treating rewrite sources as literals would
    report every localised /de/delete-account link as a 404 that isn't one.
    """
    if path in rw:
        return rw[path]
    for source, destination in rw.items():
        if ":" not in source:
            continue
        src_parts, path_parts = source.strip("/").split("/"), path.strip("/").split("/")
        if len(src_parts) != len(path_parts):
            continue
        captured: dict[str, str] = {}
        for sp, pp in zip(src_parts, path_parts):
            if sp.startswith(":"):
                captured[sp[1:]] = pp
            elif sp != pp:
                break
        else:
            out = destination
            for name, value in captured.items():
                out = out.replace(f":{name}", value)
            return out
    return path


def resolve(href: str, rw: dict[str, str]) -> pathlib.Path | None:
    """Map a site-absolute href to the file a static host would serve, or None if
    the link is external / not a file reference."""
    if href.startswith(("http://", "https://", "mailto:", "#")):
        return None
    path = href.split("#")[0].split("?")[0]
    path = apply_rewrites(path, rw)
    if path == "":
        return None
    target = ROOT / path.lstrip("/").rstrip("/")
    # A bare directory path (/ar) is served as its index.html, the same way the host
    # resolves it. "/" lands here too and resolves to the root index.
    if target.is_dir():
        target = target / "index.html"
    return target


def main() -> int:
    errors: list[str] = []
    rw = rewrites()
    # Every page at the root and one level down (the locale directories). Globbing
    # only */index.html silently skipped the localised delete-account pages.
    pages = sorted(ROOT.glob("*.html")) + sorted(ROOT.glob("*/*.html"))
    pages = [p for p in pages if "build" not in p.parts]

    docs: dict[pathlib.Path, Doc] = {}
    for page in pages:
        d = Doc()
        d.feed(page.read_text(encoding="utf-8"))
        docs[page] = d
        rp = page.relative_to(ROOT)

        if d.stack:
            errors.append(f"{rp}: unclosed tags {d.stack}")
        if d.unbalanced:
            errors.append(f"{rp}: mismatched closing tags {d.unbalanced}")
        if not d.lang:
            errors.append(f"{rp}: <html> has no lang attribute")

        for href in d.links:
            if href.startswith("#"):
                if href[1:] not in d.ids:
                    errors.append(f"{rp}: broken anchor {href}")
                continue
            target = resolve(href, rw)
            if target is not None and not target.exists():
                errors.append(f"{rp}: broken link {href} -> {target.relative_to(ROOT)}")

    # hreflang must be reciprocal across the generated locale pages, and every
    # alternate must point at a page that exists.
    generated = {p: d for p, d in docs.items() if d.hreflangs}
    expected = None
    for page, d in generated.items():
        tags = {t for t, _ in d.hreflangs}
        if expected is None:
            expected = tags
        elif tags != expected:
            errors.append(
                f"{page.relative_to(ROOT)}: hreflang set differs "
                f"(missing {sorted(expected - tags)}, extra {sorted(tags - expected)})"
            )
        for _, href in d.hreflangs:
            target = resolve(re.sub(r"^https?://[^/]+", "", href), rw)
            if target is not None and not target.exists():
                errors.append(f"{page.relative_to(ROOT)}: hreflang points at missing {href}")

    # sitemap
    sm = ROOT / "sitemap.xml"
    if not sm.exists():
        errors.append("sitemap.xml missing")
    else:
        try:
            root = ET.fromstring(sm.read_text(encoding="utf-8"))
            ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            locs = [el.text for el in root.findall(".//s:loc", ns)]
            listed: set[pathlib.Path] = set()
            for loc in locs:
                target = resolve(re.sub(r"^https?://[^/]+", "", loc), rw)
                if target is None:
                    continue
                if not target.exists():
                    errors.append(f"sitemap.xml: {loc} does not exist")
                else:
                    listed.add(target)

            # Every page that should be indexed must be in the sitemap. Structural
            # rather than a count, so adding a page type can't silently pass.
            indexable = {
                p for p in pages
                if p.name != "auth-callback.html"  # Disallowed in robots.txt
            }
            for missing in sorted(indexable - listed):
                errors.append(f"sitemap.xml is missing {missing.relative_to(ROOT)}")
        except ET.ParseError as exc:
            errors.append(f"sitemap.xml is not valid XML: {exc}")

    if not (ROOT / "robots.txt").exists():
        errors.append("robots.txt missing")

    print(f"checked {len(pages)} page(s), {len(generated)} localised")
    for err in errors:
        print(f"  FAIL {err}")
    print(f"\n{len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
