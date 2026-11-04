#!/usr/bin/env bash
#
# 本地编译（Linux / macOS / Docker 内）
# 用法：  OWRT_VERSION=v23.05.5 bash scripts/local-build.sh
#

set -euo pipefail

OWRT_VERSION="${OWRT_VERSION:-v23.05.5}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${SRC:-$REPO/openwrt}"

echo "== OpenWrt $OWRT_VERSION -> $SRC"

if [ ! -d "$SRC/target/linux/ramips" ]; then
	git clone --depth 1 -b "$OWRT_VERSION" \
		https://github.com/openwrt/openwrt.git "$SRC"
fi

python3 "$REPO/scripts/apply-board.py" "$SRC"

cd "$SRC"
cat "$REPO/configs/feeds.conf.append" >> feeds.conf.default
./scripts/feeds update -a
./scripts/feeds install -a || true

cat "$REPO/configs/seed.config" >> .config
make defconfig

grep -q 'CONFIG_TARGET_ramips_mt7621_DEVICE_mycpe_5gcpe=y' .config \
	|| { echo "设备没进 .config，板级注入失败"; exit 1; }

make download -j"$(nproc)" || true
make -j"$(nproc)" || make -j1 V=s

echo
echo "== 产物："
ls -lh bin/targets/ramips/mt7621/
