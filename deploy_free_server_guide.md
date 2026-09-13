# Free Cloud Server Deployment Guide (Multi-User Virtual Trading SaaS)

Yeh guide aapko batayegi ki kaise aap is webapp ko **bina 1 rupaye kharch kiye (100% Free)** internet par live kar sakte hain, taaki aapke demo users kisi bhi mobile ya computer se login karke trading kar sakein.

---

## Method 1: Render.com par Free Deploy (Sabse Aasan & Recommended ⭐)

Render.com 100% free web service hosting deta hai.

### Step 1: GitHub par Repository Banayein
1. Apne GitHub account par jayein aur **New Repository** banayein (e.g. `nifty-virtual-trading`).
2. Apne computer ke `virtual_trading_webapp` folder ke andar Git initialize karein:
   ```bash
   cd c:\AllProjects\nse_tool\virtual_trading_webapp
   git init
   git add .
   git commit -m "Initial commit for QuantGini Virtual Trading SaaS"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/nifty-virtual-trading.git
   git push -u origin main
   ```

### Step 2: Render.com par Web Service Banayein
1. [Render.com](https://render.com) par free account banayein (Sign in with GitHub).
2. Dashboard par **New +** button par click karke **Web Service** chunein.
3. Apni GitHub repository select karein (`nifty-virtual-trading`).
4. Render automatically `render.yaml` ya Python environment detect kar lega:
   - **Name**: `quantgini-trading-desk`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python server.py`
   - **Plan**: `Free` ($0/month)
5. **Deploy Web Service** par click karein.
6. 2-3 minute me aapki website live ho jayegi aur aapko ek free URL mil jayega, jaise:
   👉 `https://quantgini-trading-desk.onrender.com`

---

## Method 2: Cloudflare Tunnel se Apne PC ko Free Live Website Banayein (Instant 0 Cost ⭐⭐)

Agar aap chahte hain ki aapke computer par chal raha live Fyers data seedhe internet par users ko dikhe bina kisi cloud hosting ke:

1. Free tool **Cloudflared** download karein:
   [https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe](https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe)
2. Terminal me ek simple command run karein:
   ```cmd
   cloudflared-windows-amd64.exe tunnel --url http://localhost:8080
   ```
3. Cloudflare aapko turant ek free public HTTPS URL de dega (e.g. `https://random-words.trycloudflare.com`).
4. Is link ko aap kisi bhi user ko bhej sakte hain — wo apne mobile se login karke live virtual trades kar sakega!

---

## Method 3: Railway.app par Free Deploy
1. [Railway.app](https://railway.app) par login karein.
2. **Deploy from GitHub repo** par click karein.
3. Railway automatically `Procfile` aur `requirements.txt` se app ko start kar dega.
4. **Generate Domain** par click karte hi aapko public live link mil jayega.

---

## 🔑 Default Login Credentials:

| Role | Username | Password | Virtual Margin | URL Path |
|---|---|---|---|---|
| **Master Admin** | `admin` | `Admin@123` | ₹10,00,000 | `/admin` |
| **Demo Trader 1** | `demo_trader1` | `demo123` | ₹1,00,000 | `/trade` |
| **Demo Trader 2** | `demo_trader2` | `demo123` | ₹2,00,000 | `/trade` |

> 💡 **Admin Panel se Naye Users Banana**:
> Admin login karke `/admin` me "➕ Create Demo Account" button dabayein, username, password aur custom capital daalein — naya user turant ready ho jayega!
