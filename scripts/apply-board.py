#!/usr/bin/env python3
"""
把本仓库的板级支持注入 OpenWrt 源码树。

用法：
    python3 scripts/apply-board.py ../openwrt

设计要点（都是踩过的坑）：
  * 02_network 里有两个 case（接口映射 / MAC 映射分属两个函数），
    platform.sh 里 platform_do_upgrade 内部也有两个 case。
    所以不能"插到最后一个 esac 前"，必须定位到正确的 case 块，
    并且插到该块的 *) 默认分支之前，否则会被默认分支吃掉、永不生效。
  * 幂等：重复执行不会重复插入。
  * 任何锚点找不到都直接报错退出，避免"编译成功但设备没进 .config"的假成功。
"""

import re
import shutil
import stat
import sys
from pathlib import Path

BOARD = "mycpe,5gcpe"
DTS_NAME = "mt7621_mycpe_5gcpe.dts"
REPO = Path(__file__).resolve().parent.parent

CASE_START = re.compile(r"^[ \t]*case\b.*?\bin[ \t]*$", re.M)
CASE_END = re.compile(r"^[ \t]*esac[ \t]*$", re.M)
DEFAULT_BRANCH = re.compile(r"^[ \t]*\*\)", re.M)


def die(msg: str) -> None:
    print(f"\n[apply-board] ERROR: {msg}\n", file=sys.stderr)
    sys.exit(1)


def info(msg: str) -> None:
    print(f"[apply-board] {msg}")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="surrogateescape")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", errors="surrogateescape")


def find_case_blocks(text: str, start: int):
    """返回 [start, end) 列表，每个元素是一个 case...esac 块的范围。"""
    blocks = []
    for m in CASE_START.finditer(text, start):
        cs = m.start()
        e = CASE_END.search(text, m.end())
        if not e:
            continue
        blocks.append((cs, e.start()))
    return blocks


def add_case_branch(path: Path, block: str, anchor: str = None, which: str = "last") -> None:
    text = read(path)
    if BOARD in text:
        info(f"已存在 {BOARD} 分支，跳过：{path.name}")
        return

    start = 0
    if anchor:
        idx = text.find(anchor)
        if idx < 0:
            die(f"{path.name} 里找不到锚点 {anchor!r}，OpenWrt 版本可能变了")
        start = idx

    blocks = find_case_blocks(text, start)
    if not blocks:
        die(f"{path.name}（锚点 {anchor}）里找不到 case 语句")

    cs, ce = blocks[-1] if which == "last" else blocks[0]
    seg = text[cs:ce]

    defaults = list(DEFAULT_BRANCH.finditer(seg))
    ins = cs + defaults[-1].start() if defaults else ce

    write(path, text[:ins] + block + text[ins:])
    info(f"已插入 {BOARD} 分支 -> {path.name}（case 块 {cs}-{ce}，"
         f"{'在 *) 之前' if defaults else '在 esac 之前'}）")


def main() -> None:
    if len(sys.argv) < 2:
        die("缺少 OpenWrt 源码目录参数，例如：python3 scripts/apply-board.py ../openwrt")

    root = Path(sys.argv[1]).resolve()
    if not (root / "target/linux/ramips").is_dir():
        die(f"{root} 看起来不是 OpenWrt 源码根目录（缺 target/linux/ramips）")

    ramips = root / "target/linux/ramips"
    mt7621 = ramips / "mt7621"

    # 1) DTS
    src_dts = REPO / "board" / DTS_NAME
    if not src_dts.is_file():
        die(f"找不到 {src_dts}")
    shutil.copyfile(src_dts, ramips / "dts" / DTS_NAME)
    info(f"DTS -> target/linux/ramips/dts/{DTS_NAME}")

    # 2) mt7621.mk 设备定义
    mk = ramips / "image" / "mt7621.mk"
    if not mk.is_file():
        die(f"找不到 {mk}")
    mk_text = read(mk)
    if "Device/mycpe_5gcpe" in mk_text:
        info("mt7621.mk 已包含设备定义，跳过")
    else:
        frag = read(REPO / "board" / "mt7621.mk.fragment")
        if not mk_text.endswith("\n"):
            mk_text += "\n"
        write(mk, mk_text + "\n" + frag)
        info("设备定义 -> target/linux/ramips/image/mt7621.mk")

    # 3) 01_leds：整文件只有一个顶层 case
    add_case_branch(
        mt7621 / "base-files" / "etc" / "board.d" / "01_leds",
        read(REPO / "board" / "01_leds.fragment"),
    )

    # 4) 02_network：必须落到 ramips_setup_interfaces 的那个 case，
    #    不能落到后面的 ramips_setup_macs
    add_case_branch(
        mt7621 / "base-files" / "etc" / "board.d" / "02_network",
        read(REPO / "board" / "02_network.fragment"),
        anchor="ramips_setup_interfaces",
        which="first",
    )

    # 5) platform.sh：platform_do_upgrade 里有两个 case，要的是第二个
    #    （里面有 nand_do_upgrade 那一堆设备列表 + *) 默认分支）
    add_case_branch(
        mt7621 / "base-files" / "lib" / "upgrade" / "platform.sh",
        read(REPO / "board" / "platform.sh.fragment"),
        anchor="platform_do_upgrade",
        which="last",
    )

    # 6) 自定义 rootfs 覆盖层
    src_files = REPO / "files"
    if src_files.is_dir():
        dst_files = root / "files"
        shutil.copytree(src_files, dst_files, dirs_exist_ok=True)
        for p in dst_files.rglob("*"):
            if p.is_file():
                p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        info(f"rootfs 覆盖层 -> {dst_files}")

    print(
        "\n[apply-board] 完成。下一步："
        "\n  cat ../configs/seed.config >> .config && make defconfig"
        "\n  确认 .config 里出现 CONFIG_TARGET_ramips_mt7621_DEVICE_mycpe_5gcpe=y\n"
    )


if __name__ == "__main__":
    main()
