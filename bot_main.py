import logging
import requests
import json
import ollama
import re
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# ==========================================
# PART 1: AUTOCOUNT BRIDGE (ENHANCED)
# ==========================================
class AutoCountService:
    def __init__(self):
        self.base_url = "http://localhost:8015"
        self.user_id = "ADMIN"
        self.password = "ADMIN"
        self.token = "FK98DL-2AAAAA-AAAAAA-AAAAAA-ABLUB5-YR6ABK-DVAC8P-F5BQ7G"
        self.auth_key = None

    def login(self):
        url = f"{self.base_url}/api/v3/Login"
        payload = {"UserID": self.user_id, "Password": self.password, "Token": self.token}
        try:
            r = requests.post(url, json=payload, timeout=5)
            if r.status_code == 200 and len(r.json()) > 0:
                self.auth_key = r.json()[0].get("JWTToken")
                print("✅ [AutoCount] Login Successful")
                return True
        except Exception as e:
            print(f"❌ [AutoCount] Connection Error: {e}")
        return False

    def _get_headers(self):
        if not self.auth_key: self.login()
        return {"Content-Type": "application/json", "Authorization": self.auth_key}

    # --- DEBTOR FUNCTIONS ---
    
    def get_debtor_list(self, limit=20):
        """Returns a simple directory of debtors"""
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        payload = {"AccNo": []} 
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                return r.json()[:limit] # Return first N results
        except: return None

    def get_debtor_outstanding(self, limit=5):
        """Returns debtors sorted by money owed"""
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        payload = {"AccNo": []} 
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json()
                # Filter > 0 and Sort by Balance Descending
                debtors = [d for d in data if float(d.get('Balance', d.get('Outstanding', 0.0))) > 0]
                sorted_data = sorted(debtors, key=lambda x: float(x.get('Balance', x.get('Outstanding', 0.0))), reverse=True)
                return sorted_data[:limit]
        except: return None

    def get_debtor_profile(self, keyword):
        """Deep search for a single debtor"""
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        payload = {"AccNo": []}
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json()
                keyword = keyword.lower()
                for item in data:
                    if keyword in item.get("CompanyName", "").lower() or keyword in item.get("AccNo", "").lower():
                        return item
        except: return None

    # --- STOCK FUNCTIONS ---

    def get_stock_list(self, limit=20):
        """Returns a simple directory of stock items"""
        url = f"{self.base_url}/api/V2/Item/GetItem"
        payload = {"ItemCode": []}
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                return r.json().get("ResultTable", [])[:limit]
        except: return None

    def get_stock_profile(self, keyword):
        """Deep search for a single item with FULL details"""
        url = f"{self.base_url}/api/V2/Item/GetItem"
        payload = {"ItemCode": [], "IncludeBatchBal": True}
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                keyword = keyword.lower()
                for item in data:
                    if keyword in item.get("ItemCode", "").lower() or keyword in item.get("Description", "").lower():
                        # Extract BalQty safely
                        qty = item.get("Qty", 0)
                        if "ItemDTL" in item and item["ItemDTL"]:
                            qty = item["ItemDTL"][0].get("BalQty", qty)
                        item["CalculatedQty"] = qty # Inject calculated qty
                        return item
        except: return None

    # --- SALES FUNCTION ---
    def get_sales_dashboard(self):
        url = f"{self.base_url}/api/Invoice/GetInvoice"
        now = datetime.now()
        today = now.strftime("%Y/%m/%d")
        yesterday = (now - timedelta(days=1)).strftime("%Y/%m/%d")
        payload = {"DateFrom": yesterday, "DateTo": today}
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=15)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                stats = {"sales": 0.0, "prev_sales": 0.0, "date": today}
                for inv in data:
                    if inv.get("Cancelled") == "T": continue
                    d = inv.get("DocDate", "")[:10].replace("-", "/")
                    amt = float(inv.get("FinalTotal", inv.get("NetTotal", 0.0)))
                    if d == today: stats["sales"] += amt
                    elif d == yesterday: stats["prev_sales"] += amt
                return stats
        except: return None

ac_service = AutoCountService()

# ==========================================
# PART 2: AI BRAIN (RE-TRAINED)
# ==========================================
def ask_ai_intent(user_text):
    print(f"\n🧠 AI Processing: '{user_text}'...")
    system_prompt = """
    You are an AutoCount API Assistant. Classify the user intent into these EXACT strings:
    
    1. DEBTORS:
    - "Who owes money?", "Top debtors" -> list_debtors_outstanding
    - "List all customers", "Show all debtors" -> list_all_debtors
    - "Info for Ali", "Check customer ABC" -> profile_debtor: [Keyword]
    
    2. STOCK:
    - "List all items", "Show all stock", "Inventory list" -> list_all_stock
    - "Check stock for iPhone", "Info for Item A" -> profile_stock: [Keyword]
    
    3. SALES:
    - "Sales today", "Daily sales" -> get_sales_dashboard
    
    RULES:
    - If specific Name/Item provided, use profile_... format.
    - If asking for a list/all, use list_... format.
    - Return ONLY the intent string. No markdown.
    """
    try:
        response = ollama.chat(model="deepseek-r1:8b", messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_text},
        ])
        reply = response['message']['content'].split('</think>')[-1].strip().replace("`", "")
        print(f"👉 Intent: {reply}")
        return reply
    except:
        return "error"

# ==========================================
# PART 3: HANDLERS
# ==========================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    intent = ask_ai_intent(user_text)
    
    # ---------------- DEBTOR HANDLERS ----------------
    if intent == "list_debtors_outstanding":
        await update.message.reply_text("📉 Fetching Top Outstanding Debtors...")
        data = ac_service.get_debtor_outstanding()
        msg = "🏆 **Top Debtors**\n" + "\n".join([f"• {d['CompanyName']}: RM {d.get('Balance',0):,.2f}" for d in data]) if data else "✅ No debt."
        await update.message.reply_text(msg, parse_mode='Markdown')

    elif intent == "list_all_debtors":
        await update.message.reply_text("📂 Fetching Customer Directory...")
        data = ac_service.get_debtor_list()
        msg = "📂 **Customer List**\n" + "\n".join([f"• `{d['AccNo']}` {d['CompanyName']}" for d in data]) if data else "❌ No customers."
        await update.message.reply_text(msg, parse_mode='Markdown')

    elif "profile_debtor" in intent:
        kw = intent.split(":", 1)[-1].strip()
        await update.message.reply_text(f"🔍 Searching customer '{kw}'...")
        d = ac_service.get_debtor_profile(kw)
        if d:
            addr = ", ".join(filter(None, [d.get(f'Address{i}') for i in range(1,5)] + [d.get('PostCode'), d.get('State')])) or "N/A"
            msg = (f"👤 **{d['CompanyName']}**\n🆔 `{d['AccNo']}`\n💰 Bal: RM {d.get('Balance',0):,.2f}\n"
                   f"📍 {addr}\n📞 {d.get('Phone1', 'N/A')} | 📠 {d.get('Fax1', 'N/A')}\n"
                   f"💳 Limit: RM {d.get('CreditLimit',0):,.2f} | 📅 Term: {d.get('DisplayTerm','N/A')}")
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Customer not found.")

    # ---------------- STOCK HANDLERS ----------------
    elif intent == "list_all_stock":
        await update.message.reply_text("📦 Fetching Item Catalog...")
        data = ac_service.get_stock_list()
        msg = "📦 **Item Catalog**\n" + "\n".join([f"• `{i['ItemCode']}` {i['Description']}" for i in data]) if data else "❌ No items."
        await update.message.reply_text(msg, parse_mode='Markdown')

    elif "profile_stock" in intent:
        kw = intent.split(":", 1)[-1].strip()
        await update.message.reply_text(f"🔎 Checking stock '{kw}'...")
        i = ac_service.get_stock_profile(kw)
        if i:
            # Using common AutoCount field names. Adjust if your DB uses different keys.
            msg = (
                f"📦 **{i['Description']}**\n"
                f"🔢 Code: `{i['ItemCode']}`\n"
                f"📊 **Stock: {i['CalculatedQty']} {i.get('UOM','UNIT')}**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💵 Price: RM {i.get('RefPrice', i.get('Price', 0.0)):,.2f}\n"
                f"🛠 Cost: RM {i.get('StdCost', 0.0):,.2f}\n"
                f"📂 Group: {i.get('ItemGroup', 'N/A')} | Type: {i.get('ItemType', 'N/A')}\n"
                f"⚖️ Tax: {i.get('TaxType', 'N/A')}"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Item not found.")

    # ---------------- SALES HANDLERS ----------------
    elif intent == "get_sales_dashboard":
        await update.message.reply_text("💰 Analysing sales...")
        s = ac_service.get_sales_dashboard()
        if s:
            icon = "📈" if s['sales'] >= s['prev_sales'] else "📉"
            await update.message.reply_text(f"📅 **Sales {s['date']}**\n💵 RM {s['sales']:,.2f}\n({icon} vs yesterday RM {s['prev_sales']:,.2f})", parse_mode='Markdown')

    else:
        await update.message.reply_text("🤖 I'm ready. Ask to list stocks, check prices, or find debtors.")

if __name__ == '__main__':
    TELEGRAM_TOKEN = "8274589592:AAHJgltCVJ_s4VwQoLRpFvsNJJc-M0ycs6k"
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🚀 AutoCount Agent Active...")
    app.run_polling()