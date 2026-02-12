import logging
import requests
import json
import ollama
from datetime import timedelta, datetime
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# ==========================================
# PART 1: AUTOCOUNT BRIDGE
# ==========================================
class AutoCountService:
    def __init__(self):
        self.base_url = "http://localhost:8015"
        self.user_id = "ADMIN"
        self.password = "ADMIN"
        self.token = "FK98DL-2AAAAA-AAAAAA-AAAAAA-ABLUB5-YR6ABK-DVAC8P-F5BQ7G"
        self.auth_key = None

    def login(self):
        """Authenticates and retrieves the JWT Token."""
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

    # --- FUNCTION 1: FINANCIALS (DEBTORS SUMMARY) ---
    def get_debtors(self):
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        payload = {"AccNo": []}  # Get All
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200: return r.json()
        except Exception as e:
            print(f"Error fetching debtors: {e}")
        return None

    # --- FUNCTION 1.5: DEBTOR DETAILS (NEW!) ---
    def get_debtor_details(self, keyword):
        """Finds a specific debtor and returns full profile."""
        all_debtors = self.get_debtors()
        if not all_debtors: return None

        keyword = keyword.lower()
        for d in all_debtors:
            # Search by Name or Account Number
            name = d.get('CompanyName', '').lower()
            acc = d.get('AccNo', '').lower()
            
            if keyword in name or keyword in acc:
                return d # Return the full dictionary for this debtor
        return None

# --- FUNCTION 2: SALES DASHBOARD (COMPLEX) ---
    def get_sales_dashboard(self):
        url = f"{self.base_url}/api/Invoice/GetInvoice"
        
        # 1. Define Dates
        now = datetime.now()
        today_str = now.strftime("%Y/%m/%d")
        yesterday_str = (now - timedelta(days=1)).strftime("%Y/%m/%d")
        
        # 2. Request Data for Yesterday AND Today
        payload = {"DateFrom": yesterday_str, "DateTo": today_str}
        
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=15)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                
                # Metrics
                stats = {
                    "today_sales": 0.0,
                    "yesterday_sales": 0.0,
                    "today_count": 0,
                    "top_product": "None",
                    "top_qty": 0,
                    "date": today_str
                }
                
                product_tally = {} # To count items sold today

                for inv in data:
                    # Skip cancelled
                    if inv.get("Cancelled") == "T": continue
                    
                    # Determine date (AutoCount returns "2024-08-07T00:00:00")
                    doc_date_raw = inv.get("DocDate", "")[:10] # Grab first 10 chars "2024-08-07"
                    # Normalize format to matches our request string (yyyy/mm/dd)
                    doc_date = doc_date_raw.replace("-", "/") 
                    
                    amount = float(inv.get("FinalTotal", inv.get("NetTotal", 0.0)))

                    if doc_date == today_str:
                        # TODAY'S DATA
                        stats["today_sales"] += amount
                        stats["today_count"] += 1
                        
                        # Tally Products (IVDTL)
                        if "IVDTL" in inv:
                            for item in inv["IVDTL"]:
                                code = item.get("ItemCode")
                                qty = item.get("Qty", 0)
                                desc = item.get("Description", code) # Fallback to code if desc missing
                                if code:
                                    # Create unique key
                                    product_tally[desc] = product_tally.get(desc, 0) + qty
                                    
                    elif doc_date == yesterday_str:
                        # YESTERDAY'S DATA
                        stats["yesterday_sales"] += amount

                # Find Top Product
                if product_tally:
                    best_seller = max(product_tally, key=product_tally.get)
                    stats["top_product"] = best_seller
                    stats["top_qty"] = product_tally[best_seller]

                return stats

        except Exception as e:
            print(f"Error fetching sales: {e}")
        return None

    # --- FUNCTION 3: STOCK CHECKER ---
    def check_stock(self, keyword):
        url = f"{self.base_url}/api/V2/Item/GetItem"
        payload = {"ItemCode": [], "IncludeBatchBal": True}
        
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                matches = []
                keyword = keyword.lower()
                for item in data:
                    code = item.get("ItemCode", "").lower()
                    desc = item.get("Description", "").lower()
                    if keyword in code or keyword in desc:
                        qty = 0
                        uom = "UNIT"
                        if "ItemDTL" in item and len(item["ItemDTL"]) > 0:
                            first_dtl = item["ItemDTL"][0]
                            qty = first_dtl.get("BalQty", first_dtl.get("Qty", 0))
                            uom = first_dtl.get("UOM", "UNIT")
                        matches.append({"code": item.get("ItemCode"), "desc": item.get("Description"), "qty": qty, "uom": uom})
                        if len(matches) >= 5: break 
                return matches
        except Exception as e:
            print(f"Error fetching stock: {e}")
        return None

ac_service = AutoCountService()

# ==========================================
# PART 2: AI BRAIN
# ==========================================
def ask_ai_intent(user_text):
    print(f"\n🧠 AI Processing: '{user_text}'...")
    system_prompt = """
    You are an API Router. Map requests to functions.
    
    Functions:
    - get_debtors: "Who owes money?", "List debtors", "Bad payers"
    - debtor_details: "Give me details for [Company]", "Address for [Name]", "Contact info for [Name]"
    - get_sales: "Sales today", "Daily revenue", "How much did we sell?", "Sales report"
    - check_stock: "Do we have [Item]?", "Check stock for [Item]"
    - none: Casual chat.

    RULES:
    1. If user asks about a SPECIFIC company/debtor, return: debtor_details: [Company Name]
    2. If user asks about STOCK items, return: check_stock: [Item Name]
    3. Otherwise return ONLY the function name.
    """

    try:
        response = ollama.chat(model="deepseek-r1:8b", messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_text},
        ])
        
        reply = response['message']['content'].split('</think>')[-1].strip()
        print(f"👉 Intent: {reply}")
        return reply
    except:
        return "error"

# ==========================================
# PART 3: HANDLERS
# ==========================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    response = ask_ai_intent(user_text)
    
    # --- ROUTING LOGIC ---
    
    # 1. DEBTOR DETAILS (NEW!)
    if "debtor_details" in response:
        keyword = response.split(":", 1)[-1].strip() if ":" in response else ""
        if not keyword:
            await update.message.reply_text("🏢 Which customer details do you need?")
            return

        await update.message.reply_text(f"📇 Pulling profile for '{keyword}'...")
        d = ac_service.get_debtor_details(keyword)
        
        if d:
            # Build a nice "Business Card"
            bal = float(d.get('Balance', d.get('Outstanding', 0.0)))
            msg = (
                f"🏢 **{d.get('CompanyName')}**\n"
                f"🆔 Acc: `{d.get('AccNo')}`\n"
                f"💰 **Outstanding: RM {bal:,.2f}**\n"
                f"────────────────\n"
                f"📞 Phone: {d.get('Phone1', 'N/A')}\n"
                f"📠 Fax: {d.get('Fax1', 'N/A')}\n"
                f"👤 Contact: {d.get('Attention', 'N/A')}\n"
                f"📍 Addr: {d.get('Address1', '')} {d.get('Address2', '')} {d.get('Address3', '')}\n"
                f"⏳ Terms: {d.get('DisplayTerm', 'N/A')}"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Could not find customer matching '{keyword}'.")

    # 2. DEBTORS LIST (SUMMARY)
    elif "get_debtors" in response:
        await update.message.reply_text("🔍 Checking outstanding balances...")
        data = ac_service.get_debtors()
        if data:
            msg = "📊 **Top Debtors**\n"
            for item in data[:8]:
                bal = float(item.get('Balance', item.get('Outstanding', 0.0)))
                if bal > 0:
                    msg += f"🔹 {item.get('CompanyName')}: RM {bal:,.2f}\n"
            msg += "\n💡 *Tip: Ask 'Get details for [Company]' to see address/phone.*"
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("✅ No outstanding debtors found.")

    # 3. SALES DASHBOARD (NEW FORMAT)
    elif "get_sales" in response:
        await update.message.reply_text("💰 Crunching the numbers...")
        data = ac_service.get_sales_dashboard()
        
        if data:
            # Calculate Comparison
            diff = data['today_sales'] - data['yesterday_sales']
            icon = "📈" if diff >= 0 else "📉"
            diff_str = f"{icon} RM {abs(diff):,.2f} vs Yesterday"
            
            # Format Top Product
            top_prod_str = "None"
            if data['top_product'] != "None":
                top_prod_str = f"{data['top_product']} ({data['top_qty']} units)"

            msg = (
                f"📅 **Sales Pulse: {data['date']}**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💵 **Revenue:** RM {data['today_sales']:,.2f}\n"
                f"   *({diff_str})*\n\n"
                f"🧾 **Invoices:** {data['today_count']}\n"
                f"🏆 **Top Seller:** {top_prod_str}"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Could not fetch sales data.")

    # 4. STOCK CHECK
    elif "check_stock" in response:
        keyword = response.split(":", 1)[-1].strip() if ":" in response else ""
        if not keyword:
            await update.message.reply_text("📦 What item should I look for?")
            return
        
        await update.message.reply_text(f"🔎 Searching inventory for '{keyword}'...")
        items = ac_service.check_stock(keyword)
        if items:
            msg = f"📦 **Stock Results for '{keyword}'**\n"
            for i in items:
                msg += f"🔹 `{i['code']}`: {i['desc']}\n   👉 **{i['qty']} {i['uom']}**\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ No items found matching '{keyword}'.")

    # 5. CASUAL
    else:
        await update.message.reply_text("🤖 I can help with:\n1. Sales Today\n2. Who owes money\n3. Stock Checks")

if __name__ == '__main__':
    TELEGRAM_TOKEN = "8274589592:AAHJgltCVJ_s4VwQoLRpFvsNJJc-M0ycs6k"
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🚀 AutoCount AI Agent is Running...")
    app.run_polling()