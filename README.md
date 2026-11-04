# MyCPE 5G —— MT7621A + MT7603E + MT7613BE + 128MiB 并行 NAND

一套可云编译（GitHub Actions）的 OpenWrt 23.05 板级工程，内置移远 5G 模组的管理能力。

**它解决什么**：MT7621 + MT7603E + MT7613BE 这个组合在 OpenWrt 主线里有现成的驱动支持
（MT7613 由 `mt7615e` 驱动 + `mt7663` 固件），但没有任何一块"自研 128MB NAND 板"的
DTS。本工程把 DTS / 镜像定义 / board.d / sysupgrade / 5G 拨号与管理全部补齐，做成一个
push 就能出固件的流水线。

---

## 1. 硬件假设

| 项目 | 取值 | 备注 |
|---|---|---|
| SoC | MT7621A（880MHz，2C4T，MIPS 1004Kc） | |
| RAM | 128MiB DDR3 | 256MiB 需改 DTS `memory` 节点 |
| Flash | **128MiB 并行 NAND**（48 脚 TSOP，8-bit） | 走 MT7621 内置 NFC，`&nand` 节点 |
| 2.4G | MT7603E（PCIe0） | EEPROM `factory+0x0` |
| 5G | MT7613BE（PCIe1） | EEPROM `factory+0x8000`，`mt7615e` 驱动 |
| 有线 | 4×LAN（MT7530 switch）+ 1×WAN（gmac1 + PHY4） | |
| 5G 模组 | 移远 M.2，**USB 3.0 模式**（RM500U-CN / RM520N-GL 等） | MT7621 原生 xHCI |
| 串口 | ttyS0 @115200 8N1 | 调试/救砖 |

NAND 分区表（并行 NAND，128MiB 全部用上）：

```
0x000000  512K     bootloader        (U-Boot, 只读)
0x080000  256K     bootloader-env    (环境变量, 只读)
0x0C0000  512K     factory           (WiFi 校准数据, 只读)
0x140000  6M       kernel
0x740000  126.75M  ubi               (rootfs + overlay)
```

`&nand` 里没有 `mediatek,nmbm`：并行 NAND 的坏块交给 UBI 层管理，分区偏移可以写死。
只有当你的 U-Boot 也按 nmbm 布局读写时才需要加，加了反而会和裸地址读写打架。

---

## 2. 开工前必须核对的地方

工程能编译，但**能不能在你的板子上跑起来，取决于这几个 GPIO**。全部集中在
`board/mt7621_mycpe_5gcpe.dts`，搜索 `[FILL]` 即可：

| DTS 位置 | 默认值 | 作用 |
|---|---|---|
| `keys/reset` | GPIO18 | 复位键（长按进 failsafe） |
| `keys/wps` | GPIO16 | WPS 键 |
| `leds/power` | GPIO4 | 电源灯 |
| `leds/wan` | GPIO5 | WAN 灯 |
| `leds/led_5g` | GPIO6 | 5G 状态灯（看门狗会驱动它） |
| `leds/wlan2g/wlan5g` | GPIO7/8 | 无线灯 |
| `reg_modem` | GPIO9 | M.2 供电使能，没这颗脚就保持 `status = "disabled"` |

另外几处按实际硬件确认：

- **NAND 页大小 / 块大小**：本工程在 `board/mt7621.mk.fragment` 里显式写死
  `BLOCKSIZE := 128k` / `PAGESIZE := 2048`（对应 2K page 的芯片，如 K9F1G08、
  TC58NVG0S3、MT29F1G08）。若你的片子是 4K page + 256K block（TC58NVG2S0、
  MT29F4G08），改成 `256k` / `4096`。写错的表现是镜像能编出来，但板上挂 ubi 报
  `UBI error: cannot attach mtd3`、满屏 bad eraseblock。

- **两路 WiFi 挂哪个 PCIe 槽**：默认 2.4G=pcie0、5G=pcie1。反了就交换两个
  `mediatek,mtd-eeprom` 偏移。实在拿不准就先按默认烧一版，`dmesg | grep mt76` 会告诉你
  哪个槽上认到了哪颗芯片。
- `&spi0` 这块要不要留：本板不用 SPI 控制器挂 Flash，保持 disabled 即可；
  若后续改版换成 8 脚 SPI-NAND，DTS 末尾有整段可切换的备选写法。


---

## 3. 云编译

本机不需要 Linux。把整个目录推到一个 GitHub 仓库即可。

```bash
cd mt7621-5gcpe
git init && git add -A
git commit -m "init: MT7621 5G CPE board support"
git remote add origin git@github.com:<你的账号>/<仓库名>.git
git push -u origin main
```

push 后自动触发 `.github/workflows/build.yml`：

1. 拉 OpenWrt `v23.05.5`（可在 Actions 页面手动改成别的 tag）
2. `scripts/apply-board.py` 注入 DTS + 镜像定义 + board.d + 升级脚本 + rootfs 覆盖层
3. 合并 `configs/seed.config`，`make defconfig`，**断言设备符号存在**（防止假成功）
4. 编译、打包、上传 artifact

一次全新编译在 2 核 runner 上约 **100–160 分钟**（含下载）。`dl/` 目录有缓存，第二次会快很多。
产物在 Actions 运行页底部 artifact `mycpe-5gcpe-ramips-mt7621`，主要文件：

```
openwrt-23.05.5-ramips-mt7621-mycpe_5gcpe-initramfs-kernel.bin     # 首次装机用这个
openwrt-23.05.5-ramips-mt7621-mycpe_5gcpe-squashfs-sysupgrade.bin  # 装完 / 后续升级
```

> 也可以在本地 Linux/Docker 里跑：`bash scripts/local-build.sh`（见 `docs/build-local.md`）。

---

## 4. 首次烧录（并行 NAND 别用裸写）

**为什么不能像 SPI-NAND 那样 `nand erase` + `nand write`**：U-Boot 的 `nand write`
遇到坏块会自动跳过、把后续数据往前挪，镜像就整体错位了；128MB 的片子出厂坏块
0–20 个是常态，裸写等于赌运气。

正确做法是 **RAM 里先跑起来，再让 OpenWrt 自己写 NAND**（坏块由 UBI 层接管）：

```
# 串口 115200 进 U-Boot 命令行
setenv ipaddr 192.168.1.10
setenv serverip 192.168.1.100
tftpboot 0x82000000 openwrt-23.05.5-ramips-mt7621-mycpe_5gcpe-initramfs-kernel.bin
bootm 0x82000000
```

等 30–60 秒，系统完全跑在内存里，网口 192.168.1.1 可访问（此时 NAND 还是空的）：

```bash
scp openwrt-*-squashfs-sysupgrade.bin root@192.168.1.1:/tmp/
ssh root@192.168.1.1 'sysupgrade -n /tmp/openwrt-*-squashfs-sysupgrade.bin'
```

`nand_do_upgrade` 会自动建 UBI 卷、跳坏块、写 kernel 分区。重启后就是正常系统。

后续升级同理：LuCI 上传 `sysupgrade.bin`，或 `sysupgrade -n`（`-n` 表示不保留配置）。

> 量产刷机想走 U-Boot 裸写的话，得自己做 `factory.bin`（kernel + pad + ubi 拼接），
> 并且用支持坏块跳过的写法规避错位——`docs/flashing.md` 里写了注意事项和验证方法。

详细步骤、救砖、常见启动失败现象见 `docs/flashing.md`。

---

## 5. 移远 5G 模组管理

固件里做了三层，互相不依赖，任何一层挂掉都不影响另一层：

**① 拨号（netifd + uqmi，主线自带，最稳）**
首次启动 `99-5gcpe` 自动建好 `wwan` 接口（proto=qmi，`/dev/cdc-wdm0`），
默认 APN `3gnet`，IPv4/IPv6 双栈，metric 10（有线 WAN 是 20，5G 优先）。
改 APN：LuCI → 网络 → 接口 → wwan，或者

```sh
uci set network.wwan.apn='cmnet'   # 移动 cmnet / 联通 3gnet / 电信 ctnet
uci commit network && ifup wwan
```

**② 图形化管理（luci-app-qmodem，来自 modem feed）**
模组信息、信号（RSRP/SINR/band）、拨号参数、锁频锁小区、AT 终端、短信收发、多 WAN。
如果 feed 拉取失败，这层会自动缺席，固件照常可用——这是刻意的降级设计。

**③ 看门狗 + AT 工具（本工程自带）**

```sh
logread -e 5g-watchdog        # 看链路掉线/重拨记录
5g-at info                    # 型号/注网/信号一次看全
5g-at 'AT+QENG="servingcell"' # 单条 AT
5g-at ports                   # 模组串口分布
```

看门狗默认每 20s 查一次 `wwan`：掉线 3 次 → `ifup`，9 次 → USB 重新授权（等效拔插模组），
同时驱动板上的 `green:5g` 灯。参数在 `/etc/config/5gcpe`。

更多 AT 指令、锁频、IMEI、USB 模式切换、RM500U 与 RM520N 的差异见 `docs/5g-modem.md`。

---

## 6. 目录结构

```
mt7621-5gcpe/
├── .github/workflows/build.yml   云编译流水线
├── board/
│   ├── mt7621_mycpe_5gcpe.dts    ← 核心：DTS，[FILL] 待填
│   ├── mt7621.mk.fragment        设备镜像定义（UBI + lzma-loader）
│   ├── 01_leds.fragment          LED 绑定
│   ├── 02_network.fragment       网口 → LAN/WAN 映射
│   └── platform.sh.fragment      sysupgrade 走 nand_do_upgrade
├── configs/
│   ├── seed.config               构建配置种子
│   └── feeds.conf.append         qmodem feed
├── files/                        rootfs 覆盖层（会原样进固件）
│   ├── etc/uci-defaults/99-5gcpe 首次启动初始化
│   ├── etc/config/5gcpe          看门狗参数
│   ├── etc/init.d/5g-watchdog
│   └── usr/sbin/{5g-watchdog,5g-at}
├── scripts/apply-board.py        把上面所有东西注入 OpenWrt 源码树
└── docs/{flashing.md,5g-modem.md,build-local.md}
```

---

## 7. 已知边界

- **并行 NAND 的坏块**：分区偏移写死的前提是 U-Boot 也只做裸地址读写（不加 nmbm）。
  如果你们的产线流程用 nmbm 布局，两边必须一致，否则 U-Boot 读到的 kernel 和
  OpenWrt 写的位置对不上，表现是"烧完不启动、串口停在 Starting kernel"。
- **不要指望单镜像能回滚**：本 DTS 是单镜像布局，没有 A/B 双分区。产品化想加回滚，
  得自己划 `alt_firmware` 并把 `platform.sh` 的升级逻辑换成双分区切换。
- **MT7613 的 5GHz 在部分板子上有 DFS 限制**：`ieee80211-freq-limit` 已放到
  4900–5925MHz，但 5.8G 频段是否可用取决于你板上的 FEM 和认证。
- **WiFi MAC 地址**：本模板没有从 factory 分区取 MAC（各厂偏移不一样，猜错会变砖级
  麻烦）。出厂前需要按你们的 EEPROM 格式补 `nvmem-cells`，否则 MAC 是随机生成的。
- **qmodem feed 是第三方**：版本会漂，已做"装不上就跳过"处理，但如果你要长期出货，
  建议 fork 一份固定 commit。
- **2 核 runner 编译时间偏长**：量大时换 larger runner 或自建 runner，配 ccache 更划算。
