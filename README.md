# AI 每天学一点 · 自动日报

每天早上自动抓取 AI 领域的新模型、新工具、新玩法，精挑 6 条写成中文解读，
推送到飞书。每条固定三段：**讲了什么 / 为什么值得看 / 可以怎么用**，
最后附一个当天能动手做完的小任务。

🌐 **在线看**：<https://954545647.github.io/ai-daily/>（每天自动更新，手机可直接打开）

**零依赖**：只要有 Python 3.9+，不需要 pip install 任何东西，也不需要装 DSH。
Windows / macOS / Linux 都能跑。

---

## 在其他电脑上部署（3 步）

```bash
# 1. 解压（或用 git clone，见文末）
tar xzf ai-daily-YYYYMMDD.tar.gz && cd ai-daily

# 2. 填配置
cp .env.example .env
chmod 600 .env
vim .env          # 填 DEEPSEEK_API_KEY 和 FEISHU_WEBHOOK

# 3. 自检
python3 doctor.py # 全绿就装好了
```

然后 `./run.sh` 就能立刻出一份。想每天自动跑，见「定时运行」。

`.env` 是唯一需要手工配置的东西，不随包分发，也不会进 git。

---

## 它怎么工作

```
10 个公开源 ──→ fetch.py  → 候选池（45 条，已打分去重）
                                ↓
                summarize.py
                   ├─ 第一遍：模型精挑 6 条（只决定选哪些）
                   ├─ 抓原文：把 6 条网页正文抓下来
                   └─ 第二遍：只根据真实正文写中文沉淀
                                ↓
                 notify.py → 飞书卡片 → Webhook 推送
```

**为什么要抓原文**: 第一版是「把候选摘要喂给模型直接写」，结果它给一个仓库凭空
补了「使用 Gemma 4」——原文只说了 Gemma，版本号是模型自己加的。加了抓原文这一层后，
模型没有猜测空间，写出来的数字（31.1%、$1/$5、155 条响应）都能在原文里逐字对上。

代价是多一次模型调用 + 6 次网页抓取，整轮约 20 秒、成本仍是几分钱。

**为什么分三段**：抓取是确定性的（脚本干，稳、可调试、不花钱）；
判断和写作是模糊的（模型干，质量靠 prompt 约束）；渲染推送是纯执行。
分开之后，任何一段坏了都能单独定位、单独重跑，不会连锁失败。

## 文件说明

| 文件 | 作用 |
|---|---|
| `.env` | **唯一配置**：API key、Webhook |
| `config.py` | 调口味：兴趣关键词、源权重、每源配额、条数 |
| `fetch.py` | 抓取 + 去重 + 打分 → 候选池 |
| `summarize.py` | 两遍法：精挑 + 抓原文接地 + 写沉淀 |
| `notify.py` | 渲染飞书卡片 + Webhook 推送 |
| `render.py` | 把日报转成 Markdown 存档（`--dry-run` 预览） |
| `doctor.py` | 自检：环境、key、webhook、10 个源连通性 |
| `run.sh` | 一条命令跑完三段，日志落 `logs/` |
| `pack.sh` | 打包成可拷走的 tar.gz |

## 常用命令

```bash
./run.sh                          # 全流程
python3 fetch.py --verbose        # 只看抓取和排序
python3 summarize.py --dry-run    # 看 prompt，不花钱
python3 summarize.py --count 8    # 换成 8 条
python3 summarize.py --no-ground  # 跳过抓原文（快，但可能编造）
python3 notify.py --ping          # 只测推送链路
python3 render.py --dry-run       # 预览 Markdown 版
python3 doctor.py                 # 体检
```

同一天重复跑不会重复推送。

## 定时运行

### macOS（launchd，推荐）
```bash
cp com.aidaily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.aidaily.plist
```

### Linux（cron）
```bash
crontab -e
# 每天早上 8:00
0 8 * * * cd /path/to/ai-daily && ./run.sh >> logs/cron.log 2>&1
```

### Windows（任务计划程序）
新建任务 → 触发器每天 8:00 → 操作 `wsl ./run.sh` 或 `python run.bat`。

## 调教它

全在 `config.py`：

- **换口味**：`INTERESTS` 加关键词（比如开始关注多模态，加 `multimodal`、`video generation`）
- **嫌某家刷屏**：`SOURCE_CAP` 调小
- **嫌论文多**：把「论文研究」的 `weight` 降到 0.3
- **嫌噪音多**：`NEGATIVE_KEYWORDS` 加词

改完跑 `python3 fetch.py --verbose` 立刻看到排序变化。

## 关于 X（推特）

X 官方 API 个人用不起，所以没走。现在靠三路补：
官方博客 + Hacker News（推特吵起来的事半天内会上 HN）+ GitHub 日榜（工具类更快更准）。

以后买了 X API / Apify，在 `fetch.py` 的 `FETCHERS` 加一个函数、`SOURCES` 加一行即可，
打分去重配额逻辑全部自动复用。

## 已知限制

- **arXiv 直连不通**，论文用 HuggingFace 每日论文榜代替（社区投票筛过，质量更好）
- **官方源更新慢**，有时一天只有 1 条，「发布类」不是天天有
- **模型可能编造细节** → `summarize.py` 里做了 URL 白名单校验，编的链接会被打回重写
- **单次成本**约 5000 input token，DeepSeek 下一天不到一分钱

## 数据源

| 源 | 覆盖 | 频率 |
|---|---|---|
| OpenAI / Anthropic / Google AI / DeepMind | 官方发布 | 不定期 |
| Simon Willison | 深度解读、动手实验 | 高频 |
| Hacker News | 社区热度、踩坑 | 每小时 |
| GitHub Trending | 工具与开源项目 | 每日 |
| HuggingFace Papers | 论文精选 | 每日 |
| The Decoder / TechCrunch AI | 行业新闻 | 每日 |

## 用 git 管理（多机同步的更好方式）

```bash
cd ai-daily && git init && git add -A && git commit -m "init"
# 推到私有仓库后，任何新电脑：
git clone <你的私有仓库> && cd ai-daily
cp .env.example .env && vim .env
```

`.gitignore` 已经排除了 `.env`、日志和数据，密钥不会进仓库。
