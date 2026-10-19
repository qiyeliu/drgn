#!/usr/bin/env drgn
# Iterate all pages, group by inode, output top N
import os
import sys
from collections import Counter
from typing import Any, Dict, Tuple

from drgn import FaultError, Object
from drgn.helpers.linux.fs import inode_path
from drgn.helpers.linux.mm import (
    PageCompound,
    PageSlab,
    PageTail,
    compound_nr,
    for_each_page,
)

PAGE_MAPPING_ANON = 0x1


def _sb_id(sb: Any) -> str:
    try:
        return os.fsdecode(sb.s_id.string_())
    except Exception:
        try:
            return str(sb.s_id.value_())
        except Exception:
            return hex(sb.value_())


def top_file_pages(limit: int = 10) -> None:
    counts: Counter = Counter()
    sample_obj: Dict[Tuple, Object] = {}

    for page in for_each_page():
        # Skip compound tail pages — their mapping is meaningless
        if PageTail(page):
            continue

        # Slab pages: mapping holds SLUB internal data, not file-backed
        if PageSlab(page):
            nr = compound_nr(page).value_() if PageCompound(page) else 1
            counts[("slab",)] += nr
            continue

        try:
            mapping = page.mapping
            mapping_val = mapping.value_()
        except (AttributeError, FaultError):
            continue
        if not mapping_val or (mapping_val & PAGE_MAPPING_ANON):
            continue

        # Count compound head by compound_nr, base page as 1
        nr = compound_nr(page).value_() if PageCompound(page) else 1

        try:
            inode = mapping.host
            inode_addr = int(inode.value_())
        except (AttributeError, FaultError):
            # mapping.host unreadable — group by mapping address
            counts[("mapping", mapping_val)] += nr
            continue

        try:
            ino = int(inode.i_ino.value_())
        except (AttributeError, FaultError):
            ino = 0

        try:
            sbid = _sb_id(inode.i_sb)
        except (AttributeError, FaultError):
            sbid = "<sb?>"

        key = ("inode", sbid, ino, inode_addr)
        counts[key] += nr
        sample_obj.setdefault(key, inode)

    print(f"Top {limit} file-backed page owners:")
    for i, (key, cnt) in enumerate(counts.most_common(limit), 1):
        if key[0] == "inode":
            _, sbid, ino, inode_addr = key
            inode_obj = sample_obj[key]
            path = ""
            try:
                p = inode_path(inode_obj)
                if p is not None:
                    path = os.fsdecode(p)
            except (AttributeError, FaultError):
                pass
            path_str = path or f"sb={sbid} ino={ino}"
            print(f"{i:2}. {cnt:8} pages  {path_str}  inode_addr={hex(inode_addr)}")
        elif key[0] == "slab":
            print(f"{i:2}. {cnt:8} pages  [slab]")
        else:
            _, addr = key
            print(f"{i:2}. {cnt:8} pages  mapping@{hex(addr)}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        prog = os.path.basename(sys.argv[0])
        print("Group file-backed pages by inode, output top N")
        print(f"Usage: drgn -s <vmlinux> {prog} [N]")
        print("  N   number of entries to show (default 10)")
        sys.exit(0)
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    top_file_pages(n)
