# 2026 世界杯 比分/赔率 预测系统

通过历史战绩、球队强度、情境因素，输出每场比赛的**比分概率分布**，并推导
胜平负 / 亚盘让球 / 大小球等各市场概率与公平赔率，附"为什么"的理由。
**定位：概率分析与决策参考，非盈利保证。** 请理性参与、遵守当地法规。

## 阶段
- **🅰 核心版（当前）**：免费历史数据 + Dixon-Coles 模型 → 三大市场概率 + 文字理由 + 手动刷新 + Streamlit 看板 + Docker 本地。
- **🅱 赛事期迭代**：价值&凯利、伤停/首发实时、LLM 再处理、ML 集成、回测校准。

## 目录
```
wc2026/
  config.py        全局配置（读 .env）
  data/            数据层：抓取 / 入库 / 数据源连接器
  features/        特征工程（预留）
  models/          预测模型：dixon_coles / elo
  markets/         比分矩阵 → 各市场概率换算
  llm/             LLM Provider 接口 + 理由生成（可降级）
  backtest/        回测框架（预留）
  api/             FastAPI 后端
web/               Streamlit 看板
scripts/           命令行脚本（数据更新等）
data/              SQLite 与缓存（不进版本库）
```

## 快速开始
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 按需填写
python scripts/update_data.py        # 抓取并入库历史数据
streamlit run web/app.py             # 打开看板
```

## 安全
- 密钥只放 `.env`（已被 `.gitignore` 排除），代码不硬编码。
- LLM 为可选增强：未配置或调用失败时自动降级为规则模板理由，核心预测不受影响。
