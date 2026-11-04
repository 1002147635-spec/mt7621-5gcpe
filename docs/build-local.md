# 本地编译（不用 GitHub Actions）

云编译省事，但改 DTS 时来回推 commit 很慢。本地跑一遍只编译变动的部分，快得多。

## 方式一：Docker（Windows / macOS 推荐）

```bash
# 在仓库根目录（mt7621-5gcpe/ 的上层）执行
docker run --rm -it \
  -v "$PWD":/work -w /work \
  ubuntu:22.04 bash

# 容器内：
apt-get update && apt-get -y install \
  build-essential clang flex bison g++ gawk gcc-multilib g++-multilib \
  gettext git libncurses5-dev libncursesw5-dev libssl-dev python3-setuptools \
  rsync swig unzip zlib1g-dev file wget libelf-dev ecj fastjar \
  java-propose-classpath subversion device-tree-compiler ca-certificates

cd /work/mt7621-5gcpe
OWRT_VERSION=v23.05.5 bash scripts/local-build.sh
```

Windows 上把仓库放在 WSL 的文件系统里（`\\wsl$\...`）而不是 `/mnt/d/...`，
否则 OpenWrt 的 mksquashfs 会因为文件权限和大小写问题报错。

## 方式二：Linux 主机

```bash
sudo apt-get install -y build-essential clang flex bison g++ gawk \
  gcc-multilib g++-multilib gettext git libncurses5-dev libncursesw5-dev \
  libssl-dev python3-setuptools rsync swig unzip zlib1g-dev file wget \
  libelf-dev device-tree-compiler

OWRT_VERSION=v23.05.5 bash scripts/local-build.sh
```

## 增量迭代的姿势

改完 DTS 后不需要重新 clone、不需要重新 feeds，只要：

```bash
python3 scripts/apply-board.py openwrt          # 重新拷 DTS
cd openwrt
make target/linux/install V=s                   # 只重建内核 + DTB
make -j$(nproc) V=s                             # 重打镜像
```

DTS 语法错误会在 `make target/linux/install` 阶段由 dtc 直接报出来，带行号，
比在 CI 里等 30 分钟强。

## 检出配置对不对

```bash
cd openwrt
grep -E 'DEVICE_mycpe|mt76|qmi|mbim|qmodem' .config
./scripts/diffconfig.sh          # 看实际生效的配置和默认值差在哪
```

## 只验证 DTS（最快）

```bash
cd openwrt
make target/linux/prepare V=s
make target/linux/compile V=s    # 会调用 dtc 编译所有 mt7621 dts
```
