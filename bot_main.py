import logging
import requests
import json
import ollama
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# ==========================================
# PART 1: AUTOCOUNT BRIDGE ( Unchanged )
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

    def _get_balance(self, item):
        for key in ['Balance', 'Outstanding', 'CurBalance', 'NetTotal']:
            if key in item and item[key] is not None: return float(item[key])
        return 0.0

    def _get_qty(self, item):
        total_qty = 0.0
        if 'BalQty' in item: total_qty = float(item['BalQty'])
        elif 'Qty' in item: total_qty = float(item['Qty'])
        if "ItemDTL" in item and isinstance(item["ItemDTL"], list):
            for dtl in item["ItemDTL"]: total_qty += float(dtl.get("BalQty", dtl.get("Qty", 0)))
        return total_qty

    # --- DEBTOR FUNCTIONS ---
    def get_debtor_list(self, limit=20):
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        try:
            r = requests.post(url, json={"AccNo": []}, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json()
                for d in data: d['show_bal'] = self._get_balance(d)
                return data[:limit]
        except: return None

    def get_debtor_outstanding(self, limit=5):
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        try:
            r = requests.post(url, json={"AccNo": []}, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json()
                for d in data: d['show_bal'] = self._get_balance(d)
                debtors = [d for d in data if d['show_bal'] > 0]
                return sorted(debtors, key=lambda x: x['show_bal'], reverse=True)[:limit]
        except: return None

    def get_debtor_profile(self, keyword):
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        try:
            r = requests.post(url, json={"AccNo": []}, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json()
                keyword = keyword.lower()
                for item in data:
                    if keyword in item.get("CompanyName", "").lower() or keyword in item.get("AccNo", "").lower():
                        item['show_bal'] = self._get_balance(item)
                        return item
        except: return None

    # --- STOCK FUNCTIONS ---
    def get_stock_list(self, limit=20):
        url = f"{self.base_url}/api/V2/Item/GetItem"
        try:
            r = requests.post(url, json={"ItemCode": [], "IncludeBatchBal": True}, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                for i in data: i['show_qty'] = self._get_qty(i)
                return data[:limit]
        except: return None

    def get_stock_profile(self, keyword):
        url = f"{self.base_url}/api/V2/Item/GetItem"
        try:
            r = requests.post(url, json={"ItemCode": [], "IncludeBatchBal": True}, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                keyword = keyword.lower()
                for item in data:
                    if keyword in item.get("ItemCode", "").lower() or keyword in item.get("Description", "").lower():
                        item['show_qty'] = self._get_qty(item)
                        return item
        except: return None

    # --- SALES FUNCTION ---
    def get_sales_dashboard(self, specific_date_str=None):
        url = f"{self.base_url}/api/Invoice/GetInvoice"
        
        # Date Logic: If user gave a date, use it. Otherwise default to "Today"
        if specific_date_str:
            try:
                target_dt = datetime.strptime(specific_date_str, "%Y/%m/%d")
            except:
                print(f"❌ Date Error: {specific_date_str}")
                return None
        else:
            target_dt = datetime.now()

        # Format for API: YYYY/MM/DD
        target_date = target_dt.strftime("%Y/%m/%d")
        prev_date = (target_dt - timedelta(days=1)).strftime("%Y/%m/%d")
        
        payload = {"DateFrom": prev_date, "DateTo": target_date}
        
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=15)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                stats = {"sales": 0.0, "prev_sales": 0.0, "count": 0, "date": target_date}
                
                for inv in data:
                    if inv.get("Cancelled") == "T": continue
                    # API returns date like "2026-01-29T00:00:00". Take first 10 chars and ensure YYYY/MM/DD
                    doc_date_raw = inv.get("DocDate", "")[:10].replace("-", "/")
                    
                    amount = float(inv.get("FinalTotal", inv.get("NetTotal", 0.0)))
                    
                    if doc_date_raw == target_date:
                        stats["sales"] += amount
                        stats["count"] += 1
                    elif doc_date_raw == prev_date:
                        stats["prev_sales"] += amount
                return stats
        except Exception as e:
            print(f"Sales API Error: {e}")
            return None

ac_service = AutoCountService()

# ==========================================
# PART 2: AI BRAIN ( Unchanged )
# ==========================================
def ask_ai_intent(user_text):
    print(f"\n🧠 AI Processing: '{user_text}'...")
    
    # We give the AI the context of "NOW" so it can calculate dates
    current_date = datetime.now().strftime("%Y/%m/%d")
    current_day = datetime.now().strftime("%A")

    system_prompt = f"""
    You are an AutoCount API Assistant. Today is {current_day}, {current_date}.
    
    Your job is to map User Requests to Functions.
    CRITICAL: You must convert ALL dates to "YYYY/MM/DD" format.
    
    1. SALES (Single Date):
    - "Sales today" -> get_sales: {current_date}
    - "Sales yesterday" -> get_sales: [Calculated YYYY/MM/DD]
    - "Sales for 29 Jan" -> get_sales: 2026/01/29 (Assume current year if not specified)
    - "Sales for 2025/08/12" -> get_sales: 2025/08/12
    
    2. SALES COMPARISON (Two Dates):
    - "Compare sales 29 Jan vs 12 Aug" -> compare_sales: 2026/01/29 | 2026/08/12
    - "How is today compared to last week?" -> compare_sales: {current_date} | [Calculated Date]
    
    3. DEBTORS:
    - "Top 3 debtors" -> list_debtors_outstanding: 3
    - "Who owes money" -> list_debtors_outstanding: 5
    - "List all customers" -> list_all_debtors
    - "Profile for Ali" -> profile_debtor: Ali
    
    4. STOCK:
    - "List all items" -> list_all_stock
    - "Check stock iPhone" -> profile_stock: iPhone
    
    Reply ONLY with the formatted string. No Markdown. No Quotes.
    """
    
    try:
        response = ollama.chat(model="deepseek-r1:8b", messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_text},
        ])
        # Clean <think> tags and quotes
        reply = response['message']['content'].split('</think>')[-1].strip()
        reply = reply.replace('"', '').replace("'", "").replace("`", "")
        print(f"👉 Intent: {reply}")
        return reply
    except:
        return "error"

# ==========================================
# PART 3: NEW UI DASHBOARD
# ==========================================
async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main menu with Inline Buttons."""
    
    keyboard = [
        [
            InlineKeyboardButton("📊 Today's Sales", callback_data='btn_sales_today'),
            InlineKeyboardButton("📉 Yesterday", callback_data='btn_sales_yesterday')
        ],
        [
            InlineKeyboardButton("🏆 Top Debtors", callback_data='btn_debtors_top'),
            InlineKeyboardButton("👥 Customer List", callback_data='btn_debtors_all')
        ],
        [
            InlineKeyboardButton("📦 Stock Catalog", callback_data='btn_stock_list'),
        ],
        [
             InlineKeyboardButton("🔍 Help / Search Tips", callback_data='btn_help')
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg_text = (
        "🤖 **AutoCount AI Dashboard**\n"
        "Select an option below or type your request naturally.\n"
        "*(e.g., 'Check price of iPhone', 'Compare sales today vs last Monday')*"
    )
    
    # Handle both new messages and callback edits
    if update.message:
        await update.message.reply_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        # If calling from a "Back" button, we edit the old message
        await update.callback_query.message.edit_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button clicks directly (No AI needed for these)."""
    query = update.callback_query
    await query.answer() # Acknowledge click to stop loading animation
    
    data = query.data
    
    if data == 'btn_sales_today':
        target_date = datetime.now().strftime("%Y/%m/%d")
        s = ac_service.get_sales_dashboard(target_date)
        if s:
            icon = "📈" if s['sales'] >= s['prev_sales'] else "📉"
            msg = (
                f"📊 **Sales Dashboard: Today**\n"
                f"💵 Revenue: RM {s['sales']:,.2f}\n"
                f"🧾 Invoices: {s['count']}\n"
                f"({icon} vs Prev Day: RM {s['prev_sales']:,.2f})"
            )
            await query.message.reply_text(msg, parse_mode='Markdown')
        else:
            await query.message.reply_text("❌ No data for today.")

    elif data == 'btn_sales_yesterday':
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y/%m/%d")
        s = ac_service.get_sales_dashboard(target_date)
        if s:
            msg = (f"📉 **Sales: Yesterday ({s['date']})**\n"
                   f"💵 Revenue: RM {s['sales']:,.2f}\n"
                   f"🧾 Invoices: {s['count']}")
            await query.message.reply_text(msg, parse_mode='Markdown')
        else:
             await query.message.reply_text("❌ No data for yesterday.")

    elif data == 'btn_debtors_top':
        data = ac_service.get_debtor_outstanding(5)
        msg = f"🏆 **Top 5 Debtors**\n" + "\n".join([f"• {d['CompanyName']}: RM {d['show_bal']:,.2f}" for d in data]) if data else "✅ No outstanding debt."
        await query.message.reply_text(msg, parse_mode='Markdown')

    elif data == 'btn_debtors_all':
        data = ac_service.get_debtor_list()
        msg = "👥 **Customer Directory**\n" + "\n".join([f"• `{d['AccNo']}` {d['CompanyName']}" for d in data]) if data else "❌ No customers found."
        await query.message.reply_text(msg, parse_mode='Markdown')

    elif data == 'btn_stock_list':
        data = ac_service.get_stock_list()
        msg = "📦 **Stock Catalog**\n" + "\n".join([f"• `{i['ItemCode']}` {i['Description']}: **{i['show_qty']}**" for i in data]) if data else "❌ No items found."
        await query.message.reply_text(msg, parse_mode='Markdown')
        
    elif data == 'btn_help':
        msg = (
            "💡 **How to use AutoCount AI**\n\n"
            "**1. Use the Buttons:** Click the menu options for quick reports.\n"
            "**2. Chat Naturally:**\n"
            "• 'Check stock for iPhone'\n"
            "• 'Who represents ABC Company?'\n"
            "• 'Sales for 25th Dec'\n"
            "• 'Compare sales today vs last week'"
        )
        await query.message.reply_text(msg, parse_mode='Markdown')

# ==========================================
# PART 4: TEXT HANDLER (AI & COMMANDS)
# ==========================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    
    # If user types /start or menu, show dashboard
    if user_text.lower() in ['/start', 'menu', 'help', 'hi', 'hello']:
        await show_dashboard(update, context)
        return

    # Otherwise, pass to AI
    intent = ask_ai_intent(user_text)
    
    # ---------------- SALES HANDLERS ----------------
    if "compare_sales" in intent:
        try:
            dates = intent.split(":", 1)[-1].split("|")
            date1, date2 = dates[0].strip(), dates[1].strip()
            
            await update.message.reply_text(f"📊 Comparing {date1} vs {date2}...")
            s1 = ac_service.get_sales_dashboard(date1)
            s2 = ac_service.get_sales_dashboard(date2)
            
            if s1 and s2:
                diff = s1['sales'] - s2['sales']
                icon = "🟢" if diff >= 0 else "🔴"
                msg = (
                    f"⚔️ **Sales Comparison**\n"
                    f"📅 **{s1['date']}**: RM {s1['sales']:,.2f}\n"
                    f"📅 **{s2['date']}**: RM {s2['sales']:,.2f}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"Difference: {icon} RM {abs(diff):,.2f}"
                )
                await update.message.reply_text(msg, parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Could not fetch data for one or both dates.")
        except:
             await update.message.reply_text("⚠️ Error parsing comparison dates.")

    elif "get_sales" in intent:
        target_date = intent.split(":", 1)[-1].strip()
        await update.message.reply_text(f"📆 Fetching sales for {target_date}...")
        
        s = ac_service.get_sales_dashboard(target_date)
        if s:
            icon = "📈" if s['sales'] >= s['prev_sales'] else "📉"
            await update.message.reply_text(
                f"📅 **Sales: {s['date']}**\n"
                f"💵 Revenue: RM {s['sales']:,.2f}\n"
                f"🧾 Invoices: {s['count']}\n"
                f"({icon} vs Prev Day: RM {s['prev_sales']:,.2f})", 
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ No sales data found for this date.")

    # ---------------- DEBTOR HANDLERS ----------------
    elif "list_debtors_outstanding" in intent:
        try:
            limit = int(re.search(r'\d+', intent).group())
        except:
            limit = 5
        await update.message.reply_text(f"📉 Fetching Top {limit} Debtors...")
        data = ac_service.get_debtor_outstanding(limit)
        msg = f"🏆 **Top {len(data)} Debtors**\n" + "\n".join([f"• {d['CompanyName']}: RM {d['show_bal']:,.2f}" for d in data]) if data else "✅ No debt."
        await update.message.reply_text(msg, parse_mode='Markdown')

    elif "list_all_debtors" in intent:
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
            msg = (f"👤 **{d['CompanyName']}**\n🆔 `{d['AccNo']}`\n💰 Bal: RM {d['show_bal']:,.2f}\n"
                   f"📍 {addr}\n📞 {d.get('Phone1', 'N/A')} | 📠 {d.get('Fax1', 'N/A')}\n"
                   f"💳 Limit: RM {d.get('CreditLimit',0):,.2f} | 📅 Term: {d.get('DisplayTerm','N/A')}")
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Customer not found.")

    # ---------------- STOCK HANDLERS ----------------
    elif "list_all_stock" in intent:
        await update.message.reply_text("📦 Fetching Item Catalog...")
        data = ac_service.get_stock_list()
        msg = "📦 **Item Catalog**\n" + "\n".join([f"• `{i['ItemCode']}` {i['Description']}: **{i['show_qty']}**" for i in data]) if data else "❌ No items."
        await update.message.reply_text(msg, parse_mode='Markdown')

    elif "profile_stock" in intent:
        kw = intent.split(":", 1)[-1].strip()
        await update.message.reply_text(f"🔎 Checking stock '{kw}'...")
        i = ac_service.get_stock_profile(kw)
        if i:
            msg = (
                f"📦 **{i['Description']}**\n"
                f"🔢 Code: `{i['ItemCode']}`\n"
                f"📊 **Stock: {i['show_qty']} {i.get('UOM','UNIT')}**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💵 Price: RM {i.get('RefPrice', i.get('Price', 0.0)):,.2f}\n"
                f"🛠 Cost: RM {i.get('StdCost', 0.0):,.2f}\n"
                f"📂 Group: {i.get('ItemGroup', 'N/A')} | Type: {i.get('ItemType', 'N/A')}\n"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Item not found.")

    else:
        # Fallback to Dashboard if AI is confused
        await show_dashboard(update, context)

if __name__ == '__main__':
    TELEGRAM_TOKEN = "8274589592:AAHJgltCVJ_s4VwQoLRpFvsNJJc-M0ycs6k"
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Add Handlers
    app.add_handler(CommandHandler("start", show_dashboard))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 AutoCount AI Agent is Running (With UI Dashboard)...")
    app.run_polling()