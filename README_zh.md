# pearl-miner-oss（珍珠币 PEARL 通用挖矿/提交工具）

BSC 上 PEARL（`PearlMiningV2`）的开源 GPU(CUDA)/CPU 挖矿与提交脚本。所有地址与个人参数均可配置，代码中不含任何个人信息。

## 原理
- `id = uint256(keccak256(handleOf(wallet)))`（注册表原始名称 UTF-8，不加 `.ai`）。
- `challenge(wallet,id)` 返回 `seed, target, reward, eligible, live, claims`。
- 寻找 nonce 使 `uint256(keccak256(abi.encode(bytes32 seed, uint256 nonce))) <= target`（以太坊 Keccak-256，非 SHA3-256），即合约 `proofDigest(wallet,nonce)`。
- 用 `mineBatch(id, nonces[], minTotalReward)` 提交，每笔最多 16 个，必须由同一钱包发送（答案绑定钱包）。

## 依赖
Python 3.9+，`pip install -r requirements.txt`；CPU 版需 gcc；GPU 版需 CUDA 工具链(nvcc)与 NVIDIA 显卡。

## 配置
```bash
cp config.example.yaml config.yaml   # 填写 wallet、rpc_urls、GPU 列表、提交参数
```
默认合约/注册表为 BSC 主网公开的 PEARL 地址，其他部署请自行修改。**私钥不要写进配置文件**。

## 运行
```bash
python3 fetch_challenge.py                 # 只读：校验代码哈希、解析 handle→id、读 seed/target → out/params.json
bash miner/run.sh                          # 编译+自检+每张卡后台挖（ARCH=sm_89 可指定架构）
CPU=1 bash miner/run.sh                    # CPU 兜底
python3 verify.py --params out/params.json --onchain 5 --out out/valid_nonces.txt out/nonces_*.txt
```

## 提交
```bash
python3 submit.py --dry-run --max-groups 3          # eth_call 模拟+估 gas，不发交易
export PRIVATE_KEY=0x...                            # 只从环境变量读取
python3 submit.py                                   # 需输入 YES 确认
python3 submit.py --wait-until <unix时间戳> --gas-limit 700000 --yes   # 提前签名，到点（每日开放）同时广播
```
- 每笔签名交易并发广播到所有 `rpc_urls`；本地管理交易 nonce，出现缺口自动重同步。
- 链上 `usedProofs` 去重；`out/submit_log.csv` 追加式断点日志，已提交/确认的 nonce 不会重发。
- `minTotalReward = 当前奖励 × 数量 × (1 − 滑点)`；暂停/未开放、当日额度不足、余额过低、连续失败时停止；难度变化时自动重新过滤。
- 每日窗口为自 `startsAt` 起每 86400 秒，下次开放 = `startsAt + (miningDay()+1)*86400`。

### 模式 B：托管钱包
如注册钱包是交易所 Web3 钱包/MPC/智能账户等无法导出私钥的钱包，请用 `verify.py` 与 `submit.py --dry-run` 准备数据，再用该钱包官方工具提交。本项目不含任何特定平台代码。

## 风险与免责
风险自负，无任何担保。存在智能合约风险（所有者可暂停、规则可能变化）；失败交易也消耗 gas；先到先得；代币价值无保证。
**妥善保管私钥**：使用余额少的专用热钱包，切勿提交 `.env`/`config.yaml`，不要把私钥贴到日志中。使用前请在 BscScan 核对合约。非投资建议。

许可证：MIT。
