import logging
import requests
import json
import ollama
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# ==========================================
# PART 1: AUTOCOUNT BRIDGE (Dynamic Date Support)
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

    # --- FUNCTION 1: FINANCIALS (DEBTORS) ---
    def get_debtors(self):
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        payload = {"AccNo": []}  # Get All
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200: return r.json()
        except Exception as e:
            print(f"Error fetching debtors: {e}")
        return None

    # --- FUNCTION 2: SALES DASHBOARD (ANY DATE) ---
    def get_sales_dashboard(self, target_date_str=None):
        url = f"{self.base_url}/api/Invoice/GetInvoice"
        
        # 1. Determine Target Date (Default to NOW if None)
        if target_date_str:
            try:
                target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
            except ValueError:
                print(f"⚠️ Date parse failed for {target_date_str}, defaulting to Today")
                target_date = datetime.now()
        else:
            target_date = datetime.now()

        # 2. Determine "Yesterday" relative to Target
        # If Target is Jan 29, Previous is Jan 28
        current_str = target_date.strftime("%Y/%m/%d")
        previous_date = target_date - timedelta(days=1)
        previous_str = previous_date.strftime("%Y/%m/%d")
        
        print(f"📊 Generating Report: {current_str} vs {previous_str}")

        # 3. Request Data for BOTH days
        payload = {"DateFrom": previous_str, "DateTo": current_str}
        
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
                    "date": current_str
                }
                
                product_tally = {} 

                for inv in data:
                    if inv.get("Cancelled") == "T": continue
                    
                    # Normalize Date
                    doc_date_raw = inv.get("DocDate", "")[:10] 
                    doc_date = doc_date_raw.replace("-", "/") 
                    
                    amount = float(inv.get("FinalTotal", inv.get("NetTotal", 0.0)))

                    if doc_date == current_str:
                        # TARGET DAY DATA
                        stats["today_sales"] += amount
                        stats["today_count"] += 1
                        
                        if "IVDTL" in inv:
                            for item in inv["IVDTL"]:
                                code = item.get("ItemCode")
                                qty = item.get("Qty", 0)
                                desc = item.get("Description", code) 
                                if code:
                                    product_tally[desc] = product_tally.get(desc, 0) + qty
                                    
                    elif doc_date == previous_str:
                        # PREVIOUS DAY DATA
                        stats["yesterday_sales"] += amount

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
                        
                        matches.append({
                            "code": item.get("ItemCode"),
                            "desc": item.get("Description"),
                            "qty": qty,
                            "uom": uom
                        })
                        if len(matches) >= 5: break
                return matches
        except Exception as e:
            print(f"Error fetching stock: {e}")
        return None

ac_service = AutoCountService()

# ==========================================
# PART 2: AI BRAIN (Updated for Dates)
# ==========================================
def ask_ai_intent(user_text):
    # Inject TODAY'S date so AI knows what "Yesterday" means
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    print(f"\n🧠 AI Processing: '{user_text}'...")
    system_prompt = f"""
    You are an API Router for AutoCount Accounting. Today is {today_str}.
    
    Map requests to functions:
    
    1. SALES / REVENUE:
       - If user asks for specific date (e.g., "Sales on 2026-01-29", "Sales yesterday"), output: get_sales: YYYY-MM-DD
       - If general ("How are sales?"), output: get_sales
       
    2. STOCK / INVENTORY:
       - Output: check_stock: [Item Name]
       
    3. DEBTORS / MONEY OWED:
       - Output: get_debtors
       
    4. CASUAL:
       - Output: none
       
    RULES:
    - ALWAYS format dates as YYYY-MM-DD.
    - Do NOT output reasoning or markdown.
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
    
    # 1. DEBTORS
    if "get_debtors" in response:
        await update.message.reply_text("🔍 Checking outstanding balances...")
        data = ac_service.get_debtors()
        if data:
            msg = "📊 **Debtor Aging Summary**\n"
            total_owed = 0.0
            for item in data[:10]:
                bal = float(item.get('Balance', item.get('Outstanding', 0.0)))
                if bal > 0:
                    msg += f"🔹 {item.get('CompanyName')}: RM {bal:,.2f}\n"
                    total_owed += bal
            msg += f"\n💰 **Total Visible: RM {total_owed:,.2f}**"
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("✅ No outstanding debtors found.")

    # 2. SALES DASHBOARD (Updated Logic)
    elif "get_sales" in response:
        # Check if AI extracted a date (e.g., "get_sales: 2026-01-29")
        target_date = None
        if ":" in response:
            target_date = response.split(":", 1)[-1].strip()
            await update.message.reply_text(f"📆 Fetching sales for **{target_date}**...", parse_mode='Markdown')
        else:
            await update.message.reply_text("💰 Calculating **Today's** revenue...", parse_mode='Markdown')

        data = ac_service.get_sales_dashboard(target_date)
        
        if data:
            diff = data['today_sales'] - data['yesterday_sales']
            icon = "📈" if diff >= 0 else "📉"
            diff_str = f"{icon} RM {abs(diff):,.2f} vs Prev Day"
            
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

    # 3. STOCK CHECK
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

    # 4. CASUAL
    else:
        await update.message.reply_text("🤖 I am ready. Ask me about Sales, Debtors, or Stock.")

if __name__ == '__main__':
    # REPLACE WITH YOUR TOKEN
    TELEGRAM_TOKEN = "8274589592:AAHJgltCVJ_s4VwQoLRpFvsNJJc-M0ycs6k"
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 AutoCount AI Agent is Running...")
    app.run_polling()