# Subhash Bot — BTC Trading Agent

Delta Exchange India Testnet pe 24/7 chalne wala Bitcoin trading bot.

## Railway Deploy Steps

### Step 1: GitHub pe upload karo
1. GitHub.com pe jaao → New Repository banao (naam: `subhash-bot`)
2. Ye 3 files upload karo: `bot.py`, `requirements.txt`, `Procfile`

### Step 2: Railway connect karo
1. railway.app pe jaao → Login karo
2. "New Project" → "Deploy from GitHub repo" → `subhash-bot` select karo
3. Deploy hoga automatically

### Step 3: Environment Variables set karo
Railway dashboard mein → Variables tab → Add karo:

| Variable | Value |
|---|---|
| `DELTA_API_KEY` | Tera Delta Testnet API Key |
| `DELTA_API_SECRET` | Tera Delta Testnet API Secret |
| `TELEGRAM_TOKEN` | BotFather se mila token |
| `TELEGRAM_CHAT_ID` | Tera Telegram Chat ID |
| `CAPITAL` | 100 |

### Step 4: Deploy
Variables save karo → Bot automatically restart hoga → Telegram pe message aayega!

## Strategy (Subhash Method)
- Nearest 500-point round level dhundta hai
- 150 point buffer se entry leta hai  
- 250 point Stop Loss
- 1:3 minimum Risk:Reward
- Max 4 trades/day
- Max 5 SL attempts phir pause
- Trailing SL automatic
