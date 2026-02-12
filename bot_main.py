import logging
import requests
import json
import ollama
import re
from datetime import datetime, timedelta
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

    # --- FINANCIALS ---
    def get_debtors(self, limit=5):
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        payload = {"AccNo": []} 
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json()
                sorted_data = sorted(
                    data, 
                    key=lambda x: float(x.get('Balance', x.get('Outstanding', 0.0))), 
                    reverse=True
                )
                return sorted_data[:limit]
        except Exception as e:
            print(f"Error fetching debtors: {e}")
        return None

    def get_debtor_profile(self, keyword):
        url = f"{self.base_url}/api/Debtor/GetDebtor/"
        payload = {"AccNo": []}
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json()
                keyword = keyword.lower()
                for item in data:
                    name = item.get("CompanyName", "").lower()
                    code = item.get("AccNo", "").lower()
                    if keyword in name or keyword in code:
                        return item 
        except Exception as e:
            print(f"Error fetching profile: {e}")
        return None

    # --- SALES ---
    def get_sales_dashboard(self, specific_date=None):
        url = f"{self.base_url}/api/Invoice/GetInvoice"
        if specific_date:
            target_date_str = specific_date
            dt = datetime.strptime(specific_date, "%Y/%m/%d")
            prev_date_str = (dt - timedelta(days=1)).strftime("%Y/%m/%d")
        else:
            now = datetime.now()
            target_date_str = now.strftime("%Y/%m/%d")
            prev_date_str = (now - timedelta(days=1)).strftime("%Y/%m/%d")
        
        payload = {"DateFrom": prev_date_str, "DateTo": target_date_str}
        
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=15)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                stats = {"sales": 0.0, "prev_sales": 0.0, "count": 0, "date": target_date_str}
                for inv in data:
                    if inv.get("Cancelled") == "T": continue
                    doc_date = inv.get("DocDate", "")[:10].replace("-", "/")
                    amount = float(inv.get("FinalTotal", inv.get("NetTotal", 0.0)))
                    if doc_date == target_date_str:
                        stats["sales"] += amount
                        stats["count"] += 1
                    elif doc_date == prev_date_str:
                        stats["prev_sales"] += amount
                return stats
        except:
            return None

    # --- STOCK (NEW & IMPROVED) ---
    
    def get_all_stocks(self, limit=20):
        """Fetches ALL stocks without filter, limited to N items to prevent spam."""
        url = f"{self.base_url}/api/V2/Item/GetItem"
        # IncludeBatchBal=True ensures we get the ItemDTL for quantity
        payload = {"ItemCode": [], "IncludeBatchBal": True}
        
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                results = []
                for item in data[:limit]: # Slice list to limit
                    qty = 0.0
                    if "ItemDTL" in item and item["ItemDTL"]:
                        qty = item["ItemDTL"][0].get("BalQty", 0.0)
                    
                    results.append({
                        "code": item.get("ItemCode"),
                        "desc": item.get("Description"),
                        "qty": qty,
                        "uom": item.get("BaseUOM", "UNIT")
                    })
                return results
        except Exception as e:
            print(f"Error all stocks: {e}")
        return None

    def get_stock_detail(self, keyword):
        """Deep search for a single item to show FULL details."""
        url = f"{self.base_url}/api/V2/Item/GetItem"
        payload = {"ItemCode": [], "IncludeBatchBal": True}
        
        try:
            r = requests.post(url, json=payload, headers=self._get_headers(), timeout=10)
            if r.status_code == 200:
                data = r.json().get("ResultTable", [])
                keyword = keyword.lower()
                
                for item in data:
                    # Match against Code or Description
                    if keyword in item.get("ItemCode", "").lower() or keyword in item.get("Description", "").lower():
                        
                        # --- DATA EXTRACTION ---
                        # Extract UOM details (Cost/Price often hidden here)
                        uom_list = item.get("ItemUOM", [])
                        price = 0.0
                        cost = 0.0
                        
                        # Try to find Standard Cost/Price in UOM list
                        if uom_list:
                            first_uom = uom_list[0]
                            price = first_uom.get("Price", first_uom.get("StdSalePrice", 0.0))
                            cost = first_uom.get("Cost", first_uom.get("StdCost", 0.0))
                        
                        # Fallback to main item fields if UOM empty
                        if price == 0: price = item.get("RefPrice", 0.0)
                        if cost == 0: cost = item.get("RefCost", 0.0)

                        qty = 0.0
                        if "ItemDTL" in item and item["ItemDTL"]:
                            qty = item["ItemDTL"][0].get("BalQty", 0.0)

                        return {
                            "code": item.get("ItemCode"),
                            "desc": item.get("Description"),
                            "group": item.get("ItemGroup", "N/A"),
                            "type": item.get("ItemType", "N/A"),
                            "qty": qty,
                            "uom": item.get("BaseUOM", "UNIT"),
                            "price": price,
                            "cost": cost,
                            "active": item.get("IsActive", "T"),
                            "tax_type": item.get("SupplyTaxCode", "None")
                        }
        except Exception as e:
            print(f"Error detail stock: {e}")
        return None

ac_service = AutoCountService()

# ==========================================
# PART 2: AI BRAIN
# ==========================================
def ask_ai_intent(user_text):
    print(f"\n🧠 AI Processing: '{user_text}'...")
    system_prompt = """
    You are an AutoCount API Router. Map requests to these specific formats:
    
    1. DEBTORS:
       - "Who owes money?" -> get_debtors: 5
       - "Top 10 debtors" -> get_debtors: 10
       - "Info on Ali" -> get_debtor_profile: Ali
    
    2. SALES:
       - "Sales today" -> get_sales: latest
       - "Check sales for 2026-01-29" -> get_sales: 2026/01/29
    
    3. STOCK (NEW RULES):
       - "List all stocks", "Show me inventory", "Check all items" -> list_all_stocks
       - "Details for iPhone", "Full info on item A", "Give me information of stock A" -> stock_detail: A
       - "Check stock for iPhone" -> stock_detail: iPhone
       - "Do we have item X?" -> stock_detail: X
    
    4. CASUAL:
       - "Hi", "Thanks" -> none

    Reply ONLY with the formatted string. No JSON.
    """
    try:
        response = ollama.chat(model="deepseek-r1:8b", messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_text},
        ])
        reply = response['message']['content'].split('</think>')[-1].strip()
        reply = reply.replace("`", "").strip()
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
        try:
            limit = int(re.search(r'\d+', response).group())
        except:
            limit = 5
        await update.message.reply_text(f"📉 Listing Top {limit} Debtors...")
        data = ac_service.get_debtors(limit)
        if data:
            msg = f"🏆 **Top {len(data)} Debtors**\n━━━━━━━━━━\n"
            for item in data:
                bal = float(item.get('Balance', item.get('Outstanding', 0.0)))
                msg += f"🔹 {item.get('CompanyName')}: RM {bal:,.2f}\n"
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("✅ No data found.")

    elif "get_debtor_profile" in response:
        keyword = response.split(":", 1)[-1].strip()
        await update.message.reply_text(f"📇 Finding '{keyword}'...")
        item = ac_service.get_debtor_profile(keyword)
        if item:
            addr = f"{item.get('Address1', '')} {item.get('Address2', '')} {item.get('Address3', '')}"
            msg = (f"👤 **{item.get('CompanyName')}**\n"
                   f"🆔 {item.get('AccNo')}\n"
                   f"💰 Balance: RM {float(item.get('Balance',0)):,.2f}\n"
                   f"📍 {addr}")
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Not found.")

    # 2. SALES
    elif "get_sales" in response:
        date_param = response.split(":", 1)[-1].strip()
        date_arg = None if "latest" in date_param else date_param
        
        await update.message.reply_text("💰 Checking Sales...")
        data = ac_service.get_sales_dashboard(date_arg)
        if data:
            diff = data['sales'] - data['prev_sales']
            icon = "📈" if diff >= 0 else "📉"
            msg = (f"📅 **Sales: {data['date']}**\n"
                   f"💸 Rev: RM {data['sales']:,.2f}\n"
                   f"   ({icon} RM {abs(diff):,.2f} vs Prev)")
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ No data.")

    # 3. LIST ALL STOCKS (NEW)
    elif response == "list_all_stocks":
        await update.message.reply_text("📦 Fetching inventory list (Top 20)...")
        items = ac_service.get_all_stocks(limit=20)
        
        if items:
            msg = "📦 **Inventory Summary**\n━━━━━━━━━━━━━━━━━━\n"
            for i in items:
                status = "✅" if i['qty'] > 0 else "🔻"
                msg += f"{status} `{i['code']}`: {i['qty']} {i['uom']}\n"
            
            msg += "\n💡 *Tip: Ask 'Details for [item]' to see price & cost.*"
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ No items found in database.")

    # 4. STOCK DETAILS (NEW)
    elif "stock_detail" in response:
        keyword = response.split(":", 1)[-1].strip()
        if not keyword:
            await update.message.reply_text("📦 Which item?")
            return

        await update.message.reply_text(f"🔍 Pulling full specs for '{keyword}'...")
        i = ac_service.get_stock_detail(keyword)
        
        if i:
            active_icon = "🟢 Active" if i['active'] == "T" else "🔴 Inactive"
            msg = (
                f"📦 **Product Specification**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🏷 **{i['desc']}**\n"
                f"🔑 Code: `{i['code']}`\n"
                f"📂 Group: {i['group']} | Type: {i['type']}\n"
                f"📊 Status: {active_icon}\n\n"
                f"🔢 **Stock Level**\n"
                f"   👉 {i['qty']} {i['uom']}\n\n"
                f"💲 **Pricing**\n"
                f"   💵 Price: RM {i['price']:,.2f}\n"
                f"   🛠 Cost:  RM {i['cost']:,.2f}\n"
                f"   ⚖️ Tax:   {i['tax_type']}"
            )
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Item '{keyword}' not found.")
            
    else:
        await update.message.reply_text("🤖 Ready. Try 'List all stocks' or 'Details for [Item]'.")

if __name__ == '__main__':
    TELEGRAM_TOKEN = "8274589592:AAHJgltCVJ_s4VwQoLRpFvsNJJc-M0ycs6k"
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🚀 AutoCount AI Agent is Running...")
    app.run_polling()