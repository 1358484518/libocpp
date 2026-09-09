# C++ implementation of OCPP

![Github Actions](https://github.com/EVerest/libocpp/actions/workflows/build_and_test.yaml/badge.svg)

⚠️ **DEPRECATION NOTICE: This repository is now archived**. libocpp has been integrated into [EVerest](https://github.com/EVerest/EVerest).

All future development, updates, and issue tracking will continue within the [EVerest](https://github.com/EVerest/EVerest).
This standalone repository is now read-only and will no longer be maintained.

Please visit the [EVerest repository](https://github.com/EVerest/EVerest/tree/main/lib/everest/ocpp) to access the active codebase,
submit issues, or contribute.

## 本 fork：编译与测试（学习用）

工作都在分支 **`cursor/build-libocpp-sh-57cc`** 上，**不要合并进 `main`**。  
目标：在本机编出 libocpp 示例桩，连仓库里的 Python mock CSMS，跑通 OCPP **1.6** 和 **2.0.1**。

依赖：Linux（Debian/Ubuntu）、g++、CMake、Boost、OpenSSL 3、SQLite3、`python3-yaml`、`python3`。  
还需要 **everest-cmake**（默认放在 libocpp 的**上一级目录** `../everest-cmake`）。  
**不要** `pip install git+https://github.com/EVerest/EVerest.git`（会去克隆整个 EVerest 仓库）。本仓库用 `scripts/edm_minimal.py` 代替 edm。

### 编译

在仓库根目录：

```bash
git checkout cursor/build-libocpp-sh-57cc
chmod +x scripts/setup_and_build.sh
./scripts/setup_and_build.sh
```

GitHub 不通或代理 CONNECT 后 502 时：

```bash
GITHUB_MIRROR="https://ghproxy.net/" ./scripts/setup_and_build.sh
```

失败过 FetchContent 后必须清掉 build 再配一次：

```bash
rm -rf build
GITHUB_MIRROR="https://ghproxy.net/" ./scripts/setup_and_build.sh
```

脚本会：装 apt 依赖、克隆 `everest-cmake`（若还没有）、把 stub `edm` 放到 `~/everest/bin`、配置 CMake（`-DLIBOCPP16_BUILD_EXAMPLES=ON`）、编译 `ocpp`、`charge_point`、`charge_point_v2`。

也可以手写 CMake（`edm` 必须在 `PATH` 上，且已有 everest-cmake）：

```bash
export PATH="$HOME/everest/bin:$PATH"
cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -Deverest-cmake_DIR="$(cd ../everest-cmake && pwd)" \
  -DLIBOCPP16_BUILD_EXAMPLES=ON
cmake --build build -j"$(nproc)" --target charge_point charge_point_v2
```

产物：

- `build/src/charge_point` — OCPP 1.6 示例
- `build/src/charge_point_v2` — OCPP 2.0.1 示例

（若用别的 `BUILD_DIR`，例如 `/tmp/libocpp-build`，二进制在 `$BUILD_DIR/src/`。）

### 测试

先装 Python 依赖（仅 `websockets`）：

```bash
pip install -r scripts/ocpp_csms/requirements.txt
# 若环境不允许 pip：python3 -m pip install --user -r scripts/ocpp_csms/requirements.txt
```

**1. Python 假桩 ↔ Python CSMS**（不依赖 C++ 编译）：

```bash
python3 scripts/ocpp_csms/test_integration.py -v
```

应看到 5 个测试 OK（1.6 / 2.0.1 本地启停、远程停、GetVariables 等）。

**2. libocpp C++ 示例 ↔ 同一个 Python CSMS**（需要上面编好的二进制）：

```bash
export CHARGE_POINT_BIN="$(pwd)/build/src/charge_point"
export CHARGE_POINT_V2_BIN="$(pwd)/build/src/charge_point_v2"
python3 scripts/ocpp_csms/test_libocpp_csms.py -v
```

连本地 Python CSMS **不要开 HTTP/HTTPS 网络代理**（`http_proxy` / `https_proxy` / `HTTP_PROXY` / `HTTPS_PROXY`）。libwebsockets 会把 `ws://127.0.0.1:...` 也走代理，日志出现 `CLIENT_CONNECTION_ERROR: [http_proxy -> 502]`，BootNotification 超时。测完再开回代理即可。

测试会自己起 CSMS（随机端口），拉起 C++ `--auto-session`：

- 1.6：BootNotification → Authorize → StartTransaction → StopTransaction
- 2.0.1：BootNotification → Authorize → TransactionEvent

找不到二进制时这两个用例会 **skip**，不是失败。也可不设环境变量：脚本还会在 `/tmp/libocpp-build/src`、`/tmp/user-libocpp/build/src`、`build/src` 里找。

**3. 手动连（对照日志）**

终端 A：

```bash
python3 scripts/ocpp_csms/run_csms.py --port 9000
```

终端 B，OCPP 1.6：

```bash
./build/src/charge_point \
  --share-path "$(pwd)/config/v16" \
  --conf "$(pwd)/scripts/ocpp_csms/config-mock-v16.json" \
  --logconf "$(pwd)/config/logging.ini" \
  --auto-session
```

终端 B，OCPP 2.0.1（把 Device Model 里的 CSMS URL 改成实际端口，或先跑 `test_libocpp_csms.py` 看它如何改 `InternalCtrlr.json`）：

```bash
./build/src/charge_point_v2 \
  --config-dir "$(pwd)/config/v2/component_config" \
  --migrations "$(pwd)/config/v2/device_model_migrations" \
  --core-migrations "$(pwd)/config/v2/core_migrations" \
  --logconf "$(pwd)/config/logging.ini" \
  --auto-session
```

默认 Device Model 里 CSMS 是 `ws://localhost:9000`，桩 ID `cp001`。CSMS 交互命令：`list`、`remote_start <cpId>`、`remote_stop <cpId>`、`reset <cpId>`。

mock CSMS 是明文 WebSocket，只覆盖开机、授权、一笔交易和少量远程控制，不是完整平台。

### 调试（gdb / ddd）

用调试器跟 **一条 OCPP 报文对应的函数**，不要从 `main` 单步走进 Boost、nlohmann、libwebsockets。  
先看 CSMS 终端或 `/tmp/*.html` / `*.log` 里的 Action，再对那个函数下断点。WebSocket 在**别的线程**，Boot 的 CALLRESULT 往往不在你 `next` 的线程上。

必须 **Debug** 编译（带 `-g`，不要 `Release`），否则行号对不准：

```bash
export PATH="$HOME/everest/bin:$PATH"
cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Debug \
  -Deverest-cmake_DIR="$(cd ../everest-cmake && pwd)" \
  -DLIBOCPP16_BUILD_EXAMPLES=ON
cmake --build build -j"$(nproc)" --target charge_point
```

`./scripts/setup_and_build.sh` 默认 `BUILD_TYPE=Debug`。`file build/src/charge_point` 应显示 not stripped。

一键开 DDD（不要用 `ddd --gdb --args`，老 DDD 会只有版权横幅、没有窗口）。终端 A 先起 CSMS，终端 B：

```bash
chmod +x scripts/debug_charge_point_ddd.sh
./scripts/debug_charge_point_ddd.sh
```

窗口出来后 **Program → Run**（或下面敲 `run`），会停在 `src/charge_point.cpp` 的 `main`。参数已设好（share-path / mock 配置 / logging.ini）。

终端 A 先起 CSMS（**不要开 HTTP 代理**）：

```bash
python3 scripts/ocpp_csms/run_csms.py --port 9000
```

建议先学 **OCPP 1.6**，不要加 `--auto-session`（交互输入 `start_transaction` 时再停）。gdb：

```bash
gdb --args ./build/src/charge_point \
  --share-path "$(pwd)/config/v16" \
  --conf "$(pwd)/scripts/ocpp_csms/config-mock-v16.json" \
  --logconf "$(pwd)/config/logging.ini"
```

gdb 里：

```
break ocpp::v16::ChargePointImpl::boot_notification
break ocpp::v16::ChargePointImpl::authorize_id_token
break ocpp::v16::ChargePoint::on_transaction_started
break ocpp::v16::ChargePoint::on_transaction_stopped
run
```

连上后可用 `info threads`、`thread apply all bt`。一次只跟一个动作（例如只跟 Boot）。

OCPP 2.0.1 同样用 Debug 编 `charge_point_v2`，断点改到 `src/charge_point_v2.cpp` 的 `boot_notification_callback`、`validate_token`、`on_transaction_started`。

--------



This is a C++ library implementation of OCPP for version 1.6, 2.0.1 and 2.1.
(see [OCPP protocols at OCA website](https://openchargealliance.org/protocols/open-charge-point-protocol/)).
The OCPP2.0.1 implementation of libocpp has been certified by the OCA for multiple hardware platforms.

--------

Libocpp's approach to implementing the  OCPP protocol is to address as much functional requirements as possible as part of the library.
Since OCPP is a protocol that affects, controls, and monitors many areas of a charging station's operation this library needs to be
integrated with your charging station firmware.

## Integration with EVerest

This library is integrated within the [OCPP](https://github.com/EVerest/everest-core/tree/main/modules/OCPP) and [OCPP201](https://github.com/EVerest/everest-core/tree/main/modules/OCPP201)
module within [everest-core](https://github.com/EVerest/everest-core) - the complete software stack for your charging station. It is recommended to use EVerest together with this OCPP implementation.

## Getting Started

Check out the [Getting Started guide](doc/common/getting_started.md). It should be you starting point if you want to integrate this library with your charging station firmware.

## Get Involved

See the [COMMUNITY.md](https://github.com/EVerest/EVerest/blob/main/COMMUNITY.md) and [CONTRIBUTING.md](https://github.com/EVerest/EVerest/blob/main/CONTRIBUTING.md) of the EVerest project to get involved.

## OCPP1.6

### Supported Feature Profiles

OCPP1.6 is fully implemented.

| Feature Profile            | Supported                 |
| -------------------------- | ------------------------- |
| Core                       | ✅ yes    |
| Firmware Management        | ✅ yes    |
| Local Auth List Management | ✅ yes    |
| Reservation                | ✅ yes    |
| Smart Charging             | ✅ yes    |
| Remote Trigger             | ✅ yes    |

| Whitepapers & Application Notes                                                                                                                              | Supported              |
| ----------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| [OCPP 1.6 Security Whitepaper (3rd edition)](https://openchargealliance.org/wp-content/uploads/2023/11/OCPP-1.6-security-whitepaper-edition-3-2.zip) | ✅ yes |
| [Using ISO 15118 Plug & Charge with OCPP 1.6](https://openchargealliance.org/wp-content/uploads/2023/11/ocpp_1_6_ISO_15118_v10.pdf)                | ✅ yes                    |
| [OCPP & California Pricing Requirements](https://openchargealliance.org/wp-content/uploads/2024/09/ocpp_and_dms_evse_regulation-v3.1.pdf)          | ✅ yes |

### CSMS Compatibility

The EVerest implementation of OCPP 1.6 has been tested against the
OCPP Compliance Test Tool (OCTT) during the implementation.

The following table shows the known CSMS with which this library was tested.

- chargecloud
- chargeIQ
- Chargetic
- Compleo
- Current
- Daimler Truck
- ev.energy
- eDRV
- Fastned
- [Open Charging Cloud (GraphDefined)](https://github.com/OpenChargingCloud/WWCP_OCPP)
- Electrip Global
- EnergyStacks
- EV-Meter
- Fraunhofer IAO (ubstack CHARGE)
- Green Motion
- gridundco
- ihomer (Infuse CPMS)
- iLumen
- JibeCompany (CharlieV CMS and Chargebroker proxy)
- MSI
- PUMP (PUMP Connect)
- Scoptvision (Scopt Powerconnect)
- Siemens
- [SteVe](https://github.com/steve-community/steve)
- Syntech
- Trialog
- ubitricity
- Weev Energy

## OCPP2.0.1

### Supported Functional Blocks

| Feature Profile                      | Supported                 |
| -------------------------------------| ------------------------- |
| A. Security                          | ✅ yes  |
| B. Provisioning                      | ✅ yes  |
| C. Authorization                     | ✅ yes  |
| D. LocalAuthorizationList Management | ✅ yes  |
| E. Transactions                      | ✅ yes  |
| F. RemoteControl                     | ✅ yes  |
| G. Availability                      | ✅ yes  |
| H. Reservation                       | ✅ yes                      |
| I. TariffAndCost                     | ✅ yes  |
| J. MeterValues                       | ✅ yes  |
| K. SmartCharging                     | ✅ yes (except K11-K17)                       |
| L. FirmwareManagement                | ✅ yes  |
| M. ISO 15118 CertificateManagement   | ✅ yes  |
| N. Diagnostics                       | ✅ yes  |
| O. DisplayMessage                    | ✅ yes  |
| P. DataTransfer                      | ✅ yes  |

Check the [detailed current implementation status.](doc/v2/ocpp_2x_status.md).

| Whitepapers & Application Notes                                                                                                                              | Supported              |
| ----------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| [OCPP & California Pricing Requirements](https://openchargealliance.org/wp-content/uploads/2024/09/ocpp_and_dms_evse_regulation-v3.1.pdf)          | ✅ yes                  |

### CSMS Compatibility OCPP 2.0.1

The implementation of OCPP 2.0.1 has been tested against the following CSMS and is continuously tested against OCTT2.

Additionally, the implementation has been tested against these CSMS:

- ChargeLab
- Chargepoint
- [CitrineOS](https://lfenergy.org/projects/citrineos/)
- Current
- Ecoenergetyca
- einfochips
- evgateway
- ihomer (Infuse CPMS)
- Instituto Tecnológico de la Energía (ITE)
- [MaEVe (Thoughtworks)](https://github.com/thoughtworks/maeve-csms)
- [Monta](https://monta.com)
- Numocity
- [Open Charging Cloud (GraphDefined)](https://github.com/OpenChargingCloud/WWCP_OCPP)
- Switch EV
- SWTCH
- Relion
- Syntech
- Vector

## OCPP2.1

The implementation of OCPP2.1 is currently under development 🔧.

OCPP2.1 websocket connections and messages are supported by the library. Every functional block and use case supported in OCPP2.0.1 is also supported in OCPP2.1. Additional functional blocks and new requirements are currently
implemented.

The functional blocks we are targeting first are the extensions to SmartCharging and support for Bidirectional Power Transfer.

Check the [detailed current implementation status.](doc/v2/ocpp_2x_status.md).
