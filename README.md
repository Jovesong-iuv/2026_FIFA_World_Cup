# 2026 FIFA World Cup Predictor

2026 世界杯比分、胜平负、亚盘、大小球与价值赔率分析系统。

项目基于国际赛历史结果、Dixon-Coles 进球模型、Elo 强度修正和可选 LLM 理由生成，输出单场比赛的比分概率分布、各类盘口概率、公平赔率和中文分析说明。

> 定位：概率分析与决策参考，不是盈利保证。请理性使用，并遵守当地法律法规。

## 功能特性

- 2026 世界杯赛程驱动预测
- 自定义任意两队对阵预测
- Dixon-Coles + Elo 集成模型
- 比分概率热力图
- 胜平负概率与公平赔率
- 亚盘让球概率
- 大小球概率
- 最可能比分 Top 列表
- 历史交锋、近期状态、新闻与证据辅助
- 可选 LLM 生成中文分析理由
- The Odds API 赔率接入与价值盘扫描
- FastAPI 后端接口
- Streamlit 中文看板
- Docker Compose 一键启动

## 技术栈

- Python 3.11
- FastAPI
- Streamlit
- SQLite
- NumPy / SciPy / Pandas
- Plotly
- Docker / Docker Compose

## 项目结构

```text
.
├── wc2026/
│   ├── api/              # FastAPI 后端
│   ├── analysis/         # 证据、情境分析
│   ├── backtest/         # 世界杯历史回测
│   ├── data/             # 数据入库、数据源、球队名称映射
│   ├── features/         # 特征工程预留
│   ├── llm/              # LLM Provider 和理由生成
│   ├── markets/          # 比分矩阵转盘口概率
│   ├── models/           # Dixon-Coles / Elo / 集成预测器
│   └── config.py         # 环境变量与全局配置
├── web/
│   └── app.py            # Streamlit 看板
├── scripts/
│   ├── bootstrap.py      # 初始化数据库、训练模型、抓赛程
│   ├── update_data.py    # 更新国际赛历史数据
│   ├── smoke_test.py     # 模型冒烟测试
│   ├── backtest.py       # 回测入口
│   └── test_llm.py       # LLM 连通性测试
├── data/                 # 本地数据目录，数据库不进 Git
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## 快速开始

### 1. 克隆项目

```bash
git clone git@github.com:Jovesong-iuv/2026_FIFA_World_Cup.git
cd 2026_FIFA_World_Cup
```

如果服务器没有配置 SSH key，也可以用 HTTPS：

```bash
git clone https://github.com/Jovesong-iuv/2026_FIFA_World_Cup.git
cd 2026_FIFA_World_Cup
```

### 2. 准备环境变量

```bash
cp .env.example .env
```

最小可运行配置：

```env
DATABASE_URL=sqlite:///data/wc2026.db
LLM_ENABLED=false
```

需要 AI 理由或赔率扫描时，再填写 `LLM_API_KEY`、`LLM_BASE_URL`、`ODDS_API_KEY`。DeepSeek 可使用 `LLM_PROVIDER=openai`、`LLM_BASE_URL=https://api.deepseek.com`、`LLM_MODEL=deepseek-v4-flash`。

### 3. 本地 Python 启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/bootstrap.py
```

启动 API：

```bash
uvicorn wc2026.api.app:app --reload --host 0.0.0.0 --port 8000
```

启动看板：

```bash
streamlit run web/app.py
```

访问地址：

- API 文档：http://localhost:8000/docs
- Streamlit 看板：http://localhost:8501

## Docker Compose 启动

推荐服务器部署使用 Docker Compose。

```bash
cp .env.example .env
docker compose up --build -d
```

服务说明：

- `init`：初始化数据库、抓取历史数据、训练模型、抓取赛程，完成后退出
- `api`：FastAPI 后端，默认端口 `8000`
- `web`：Streamlit 看板，默认端口 `8501`

查看日志：

```bash
docker compose logs -f
```

停止服务：

```bash
docker compose down
```

重新初始化或更新镜像：

```bash
docker compose up --build -d
```

## API 示例

健康检查：

```bash
curl http://localhost:8000/health
```

查看球队：

```bash
curl http://localhost:8000/teams
```

查看可预测赛程：

```bash
curl "http://localhost:8000/fixtures?predictable_only=true"
```

预测一场比赛：

```bash
curl "http://localhost:8000/predict?home=Spain&away=Germany&neutral=true"
```

带情境调整预测：

```bash
curl "http://localhost:8000/predict?home=United%20States&away=Paraguay&neutral=false&use_context=true"
```

查看交锋证据：

```bash
curl "http://localhost:8000/evidence?home=Brazil&away=Argentina"
```

查看新闻：

```bash
curl "http://localhost:8000/news?home=France&away=Morocco&analyze=false"
```

全量刷新：

```bash
curl -X POST http://localhost:8000/refresh
```

价值盘扫描，需要配置 `ODDS_API_KEY`：

```bash
curl http://localhost:8000/value/scan
```

## 环境变量

| 变量 | 是否必填 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | 否 | 默认 `sqlite:///data/wc2026.db` |
| `INTL_RESULTS_BASE` | 否 | 国际赛历史数据源地址 |
| `LLM_ENABLED` | 否 | 是否启用 LLM 理由生成，默认 `true` |
| `LLM_PROVIDER` | 否 | `anthropic` 或 `openai` 兼容接口 |
| `LLM_BASE_URL` | 否 | LLM API 地址 |
| `LLM_API_KEY` | 否 | LLM API Key |
| `LLM_MODEL` | 否 | LLM 模型名称 |
| `LLM_ANTHROPIC_BETA` | 否 | Anthropic beta header，可留空 |
| `LLM_TIMEOUT` | 否 | LLM 请求超时时间 |
| `ODDS_API_KEY` | 否 | The Odds API key，用于赔率与价值盘扫描 |

## 数据与模型

项目使用本地 `data/` 目录保存运行数据：

- `data/wc2026.db`：SQLite 数据库，不提交到 Git
- `data/elo_model.json`：Elo 模型参数
- `data/dc_model.json`：Dixon-Coles 模型参数

初始化命令：

```bash
python scripts/bootstrap.py
```

只更新历史比赛数据：

```bash
python scripts/update_data.py
```

重新训练并做冒烟测试：

```bash
python scripts/smoke_test.py
```

世界杯历史回测：

```bash
python scripts/backtest.py
```

## 服务器部署建议

### 最小部署流程

```bash
git clone https://github.com/Jovesong-iuv/2026_FIFA_World_Cup.git
cd 2026_FIFA_World_Cup
cp .env.example .env
docker compose up --build -d
```

开放端口：

- `8000`：API
- `8501`：Web 看板

如果服务器只需要给自己访问，可以用防火墙限制端口，或通过 Nginx 反向代理到内网端口。

### Nginx 反向代理示例

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        proxy_pass http://127.0.0.1:8501/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## 安全说明

- 不要提交 `.env`
- 不要把真实 API Key 写进 README、代码或提交记录
- 服务器部署时建议只暴露必要端口
- 如使用私有 API Key，建议定期轮换
- 预测结果只做概率参考，不应作为唯一决策依据

## 常见问题

### 看板打不开

先确认容器是否启动：

```bash
docker compose ps
docker compose logs -f web
```

### API 返回球队不在训练集中

模型训练数据里没有该球队名称，优先使用英文标准名称，例如：

- `Spain`
- `Germany`
- `Brazil`
- `Argentina`
- `United States`

也可以在看板里从下拉框选择球队，避免拼写问题。

### LLM 没有生成 AI 理由

检查 `.env`：

```env
LLM_ENABLED=true
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=your-key
LLM_MODEL=deepseek-v4-flash
```

未配置 LLM 时，系统会自动降级为规则模板理由，核心预测不受影响。

### 赔率扫描不可用

`/value/scan` 需要配置：

```env
ODDS_API_KEY=your-odds-api-key
```

## License

如需开源使用，建议添加 MIT License；如果只是个人私有部署，可以暂不添加许可证文件。
