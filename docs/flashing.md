# 烧录、救砖与排错

## 0. 准备工作

- USB-TTL 串口线（3.3V，**不要接 5V**），接板上的 UART：TX/RX/GND，115200 8N1
- 网线一根，PC 固定 IP `192.168.1.100/24`
- TFTP 服务（Windows 用 tftpd64，Linux 用 `tftpd-hpa`，都指向放 bin 的目录）
- 板上电前先按住复位键再上电，多数 MT7621 U-Boot 会停在命令行

串口应该看到类似：

```
U-Boot 1.1.3 (Nov 21 2023 - 10:22:31)
Board: MyCPE-5G
...
MT7621 # 
```

## 1. 首次烧录

### 1.1 推荐路径：TFTP 起 initramfs，再让 OpenWrt 自己写 NAND

并行 NAND（128MB 的片子出厂坏块 0–20 个很常见）**不能裸写**：U-Boot 的
`nand write` 遇到坏块会跳过并把后续数据前移，整个镜像偏移错位，结果就是
"写成功、不启动"。

所以先用 initramfs 在内存里跑起来：

```
setenv ipaddr 192.168.1.10
setenv serverip 192.168.1.100
ping 192.168.1.100

tftpboot 0x82000000 openwrt-23.05.5-ramips-mt7621-mycpe_5gcpe-initramfs-kernel.bin
bootm 0x82000000
```

确认 `Bytes transferred` 与文件大小一致后再 `bootm`。30–60 秒后系统跑在 RAM 里，
网口 `192.168.1.1` 可访问，此时 NAND 里除了 U-Boot 还是空的。

```bash
scp openwrt-*-squashfs-sysupgrade.bin root@192.168.1.1:/tmp/
ssh root@192.168.1.1 'sysupgrade -n /tmp/openwrt-*-squashfs-sysupgrade.bin'
```

`nand_do_upgrade` 会擦 kernel 分区、建 UBI 卷、自动跳过坏块。重启即正常系统。
这一步同时也验证了"你这块板子的 NAND 能被 mtd/ubi 正常读写"，比裸写更早暴露硬件问题。

### 1.2 量产路径：U-Boot 裸写（需要自己做 factory.bin）

如果产线要求"上电自动刷"，才需要裸写。前提有三个，缺一不可：

1. 自己做拼接镜像：`kernel + pad 到 6MB + ubi 镜像` → `factory.bin`
   （可在 `board/mt7621.mk.fragment` 里加
   `IMAGES += factory.bin` 和
   `IMAGE/factory.bin := append-kernel | pad-to $$$$(KERNEL_SIZE) | append-ubi | check-size`）
2. U-Boot 的 `nand write` 必须**不跳坏块**（部分 U-Boot 版本会跳，写完要校验）
3. 写之前先 `nand bad` 看一遍坏块分布，坏块落在 `0x0`–`0x140000` 内的话这板子直接报废

```
nand erase 0x140000 0x78C0000
nand write 0x82000000 0x140000 ${filesize}
nand dump 0x140000 0x200000 /dev/null          # 简单校验
reset
```

- `0x140000` = kernel 起始偏移（和 DTS `partition@140000` 一致）
- `0x78C0000` = kernel + ubi 总长度（0x8000000 − 0x140000），都是 128K 块对齐的
- 写完务必串口看一遍启动日志，确认 `ubi0: attached to mtd3` 正常

不要用 `nand erase.chip` 整片擦——会连 U-Boot 一起擦掉，除非你有 TSOP48 编程器。

## 2. 后续升级

LuCI 里「系统 → 备份/刷写固件」上传 `sysupgrade.bin`，或者：

```bash
scp openwrt-*-sysupgrade.bin root@192.168.1.1:/tmp/
ssh root@192.168.1.1 'sysupgrade -n /tmp/openwrt-*-sysupgrade.bin'
```

`nand_do_upgrade` 会写到 kernel 分区 + ubi 卷，保留 overlay 时不要加 `-n`。

## 3. 常见故障 → 病因对照

| 现象 | 最可能的原因 | 怎么改 |
|---|---|---|
| 串口无输出 | bootargs 波特率不对 | `mt7621.dtsi` 默认 57600，本 DTS 里写的是 115200；你的 U-Boot 用哪个就改成哪个 |
| 启动后 panic `Kernel bug` / 内存相关 | `memory` 节点写的比实际大 | 128MiB 板子写 `0x8000000`，别写 `0x10000000` |
| 启动到 `VFS: Cannot open root` | kernel 分区偏移和 U-Boot 不一致 / UBI 没写进去 | 核对 `nand read` 起始地址与 DTS `partition@140000`；确认串口有 `ubi0: attached to mtd3` |
| `UBI error: cannot attach mtd3`，满屏 bad eraseblock | `PAGESIZE`/`BLOCKSIZE` 和实际芯片不符 | 2K page 用 2048/128k，4K page 用 4096/256k，改 `board/mt7621.mk.fragment` |
| 裸写后不启动，U-Boot 能读但内核跑飞 | 写入过程跳过了坏块导致偏移错位 | 改用 1.1 的 initramfs + sysupgrade 路径 |
| `mt76` 认到设备但没信号 / 没网卡 | 两路 WiFi 的 PCIe 槽搞反了 | 交换 `pcie0/pcie1` 的 `mediatek,mtd-eeprom` 偏移 |
| `wlan0` 起来但 5G 扫不到 | EEPROM 偏移错，读到了 2.4G 的校准数据 | 5G 应在 `factory+0x8000`，确认 EEPROM 布局 |
| 找不到 `/dev/mtd*`，`dmesg` 里没有 nand | NFC 没使能 / 芯片 ID 不被识别 | 确认 DTS 有 `&nand { status = "okay"; }`；`dmesg | grep -i nand` 看是否报 unknown chip id |
| 5G 模组不识别 | USB3 没供电 / M.2 走的是 PCIe 模式 | 见 `docs/5g-modem.md` 的 USB 模式切换 |
| 复位键没反应 | GPIO 号错了 | 改 `keys/reset`，用 `cat /sys/kernel/debug/gpio` 逐个试 |

## 4. 救砖

**A. 还能进 U-Boot**：直接重复第 1 步。

**B. U-Boot 也进不去**：48 脚 TSOP 片子可以整片拆下来用 TSOP48 编程器（或免拆夹）
读写，把备份的整片 dump 写回去。所以**量产前一定要把原厂整片 NAND dump 存一份**，
这是唯一的硬救砖手段。

**C. 只是配置搞坏了**：如果还能进 failsafe（长按复位键上电，LED 快闪时松手），
`ssh root@192.168.1.1` 后 `firstboot && reboot`。

## 5. 出厂前的自检清单

```sh
# 硬件识别
dmesg | grep -iE 'mt76|nand|spi|xhci|cdc-wdm'
cat /proc/mtd

# 无线
iwinfo | head -20
iw dev

# 5G
ls /dev/cdc-wdm* /dev/ttyUSB*
5g-at info
ifstatus wwan
ping -c3 -I wwan 223.5.5.5

# 升级链路（务必测一次，别等客户手上再发现）
sysupgrade -n /tmp/same-firmware.bin
```
