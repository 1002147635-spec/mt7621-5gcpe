# 移远 5G 模组：驱动、拨号与调试

## 1. 先确认模组处在哪种"数据通道"模式

移远 5G 模组（RM500U / RM520N / RM500Q）出厂时可能配成三种模式，OpenWrt 里的处理方式完全不同：

| 模式 | 内核驱动 | 设备节点 | 拨号方式 |
|---|---|---|---|
| **QMI**（推荐） | `kmod-usb-net-qmi-wwan` | `/dev/cdc-wdm0` | `uqmi` / proto=qmi |
| **MBIM** | `kmod-usb-net-cdc-mbim` | `/dev/cdc-wdm0` | `umbim` / proto=mbim |
| **RNDIS/ECM**（网卡模式） | `kmod-usb-net-rndis` | `usb0` | 模组自己拨号，OpenWrt 当 DHCP 客户端 |

本固件默认按 QMI 配置。确认当前模式（AT 口一般是 `/dev/ttyUSB2`）：

```sh
5g-at 'AT+QCFG="usbnet"'
# 返回 +QCFG: "usbnet",5   → 5=QMI（好）
#      0=RNDIS  1=ECM  2=MBIM  3=...
```

切换成 QMI 并重启模组：

```sh
5g-at 'AT+QCFG="usbnet",5'
5g-at 'AT+CFUN=1,1'      # 重启模组
```

切换后 `/dev/cdc-wdm0` 应该在 10 秒内出现。

## 2. 拨号配置

```sh
# 运营商 APN
uci set network.wwan.apn='3gnet'      # 联通
# uci set network.wwan.apn='cmnet'    # 移动
# uci set network.wwan.apn='ctnet'    # 电信
uci commit network
ifup wwan
ifstatus wwan | grep -E 'up|address'
```

需要用户名密码的专网卡：

```sh
uci set network.wwan.auth='pap'
uci set network.wwan.username='xxx'
uci set network.wwan.password='yyy'
```

## 3. 常用 AT 指令速查

```sh
5g-at info                              # 下面这一串一次全打
5g-at 'ATI'                             # 型号/固件版本
5g-at 'AT+CPIN?'                        # SIM 是否就绪
5g-at 'AT+CSQ'                          # 信号强度（99 表示无信号）
5g-at 'AT+COPS?'                        # 当前运营商
5g-at 'AT+QNWINFO'                      # 注网制式 + 频段（LTE B3 / NR n78）
5g-at 'AT+QENG="servingcell"'           # 服务小区：RSRP / RSRQ / SINR / PCI
5g-at 'AT+QCAINFO'                      # 载波聚合明细
5g-at 'AT+QCCID'                        # ICCID
5g-at 'AT+CIMI'                         # IMSI
```

`AT+QENG="servingcell"` 的返回长这样（NR5G-SA 为例）：

```
+QENG: "servingcell", "NOCONN","NR5G-SA","TDD",460,00,1A2B3C4D,123,78,3,627264,
  -95,-11,-68,12,-
```

关键字段：`78` = n78 频段，`-95` = RSRP(dBm)，`-11` = RSRQ(dB)，`12` = SINR(dB)。

信号好坏参考：

| RSRP | 评价 | SINR | 评价 |
|---|---|---|---|
| > −85 dBm | 优秀 | > 20 dB | 优秀 |
| −85 ~ −100 | 良好 | 10 ~ 20 | 良好 |
| −100 ~ −110 | 一般 | 0 ~ 10 | 一般 |
| < −110 | 差，可能掉线 | < 0 | 差 |

## 4. 锁频 / 锁小区（现场优化必用）

```sh
# 只锁 n78 + B3
5g-at 'AT+QNWPREFCFG="nr5g_band",78'
5g-at 'AT+QNWPREFCFG="lte_band",3'

# 恢复全频段
5g-at 'AT+QNWPREFCFG="nr5g_band",0'
5g-at 'AT+QNWPREFCFG="lte_band",0'

# 锁定指定小区（PCI + 频点）
5g-at 'AT+QNWLOCK="common/5g",627264,123'
5g-at 'AT+QNWLOCK="common/5g",0'        # 解锁
```

**注意**：锁频参数在不同固件版本上语法有差异，RM500U（展锐平台）与 RM520N（高通 SDX62）
不是完全一套指令。发之前先 `5g-at 'AT+QNWPREFCFG=?'` 看模组自己支持什么。

## 5. 平台差异（踩坑重点）

| | RM500U-CN | RM520N-GL |
|---|---|---|
| 基带 | 展锐唐古拉 | 高通 SDX62 |
| AT 口 | `/dev/ttyUSB2`（通常 4 个口） | `/dev/ttyUSB2`（通常 4 个口） |
| QMI | 支持，但个别固件需要 `AT+QCFG="usbnet",5` 显式切 | 原生支持 |
| 5G SA | 需 `AT+QCFG="nr5g/band"` 或 QNWPREFCFG | 同 |
| 已知问题 | 某些固件 QMI 下 IPv6 前缀拿不到，建议 `pdptype='ipv4'` 先跑通 | PCIe/MHI 模式在 MT7621 上不稳，建议走 USB |

## 6. 排错路径

**模组完全不出现**（`lsusb` 里看不到 `2c7c:xxxx`）：

1. `dmesg | grep -i xhci` — USB3 控制器起来了吗
2. 量 M.2 的 3.3V/5V 和 `W_DISABLE#`（第 20 脚，拉高才会工作）
3. M.2 座的 USB3 TX/RX 差分对有没有走反（很常见）
4. 若模组被配成 PCIe 模式，USB 上不会枚举 → 必须先在别的机器上切回 USB 模式

**出现了 `/dev/ttyUSB*` 但没有 `/dev/cdc-wdm0`**：
模组在 RNDIS/MBIM 模式。按第 1 节切 `usbnet=5`。

**有 `/dev/cdc-wdm0` 但拨不上**：

```sh
uqmi -d /dev/cdc-wdm0 --get-capabilities      # 看模组支不支持
uqmi -d /dev/cdc-wdm0 --get-serving-system    # 注网状态
uqmi -d /dev/cdc-wdm0 --start-network --autoconnect
```

`--get-serving-system` 返回 `registered: true` 才说明注网成功；否则是 SIM / 天线 / 频段问题。

**能拨上但没网**：检查防火墙区域有没有把 `wwan` 加进 `wan` zone：

```sh
uci show firewall | grep -c wwan
```

**频繁掉线**：看 `logread -e 5g-watchdog`。如果是 USB 复位后才恢复，多半是供电不足
（5G 模组峰值电流 2A 以上，M.2 供电电容不够会导致 USB 掉设备），硬件上加大电容或
独立 3.8V DCDC，软件上看门狗的 `hard_fail` 就是给这种情况兜底的。
