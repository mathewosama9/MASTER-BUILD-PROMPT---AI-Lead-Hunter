"""Minimal bilingual strings (English / Arabic)."""

STRINGS: dict[str, dict[str, str]] = {
    "welcome": {"en": "👋 Welcome to AI Lead Hunter!\n\nWhat would you like to do?",
                "ar": "👋 أهلاً بك في AI Lead Hunter!\n\nماذا تريد أن تفعل؟"},
    "demo_banner": {"en": "🧪 DEMO MODE is enabled on this server: demo campaigns use fictional data.",
                    "ar": "🧪 وضع العرض التجريبي مفعّل: الحملات التجريبية تستخدم بيانات وهمية."},
    "not_linked": {"en": "🔒 This Telegram account is not linked.\n\nOpen the web dashboard → Settings → Telegram, "
                         "generate a code, then send:\n/link YOURCODE",
                   "ar": "🔒 حساب تيليجرام هذا غير مربوط.\n\nافتح لوحة التحكم ← الإعدادات ← تيليجرام، أنشئ رمزاً ثم أرسل:\n"
                         "/link الرمز"},
    "pending": {"en": "⏳ Your link request is waiting for administrator approval.",
                "ar": "⏳ طلب الربط بانتظار موافقة المسؤول."},
    "linked": {"en": "✅ Account linked. Send /start to begin.", "ar": "✅ تم ربط الحساب. أرسل /start للبدء."},
    "link_usage": {"en": "Usage: /link CODE", "ar": "الاستخدام: /link الرمز"},
    "btn_new": {"en": "🆕 New Campaign", "ar": "🆕 حملة جديدة"},
    "btn_mine": {"en": "📁 My Campaigns", "ar": "📁 حملاتي"},
    "btn_results": {"en": "🔎 Search Results", "ar": "🔎 نتائج البحث"},
    "btn_top": {"en": "🏆 Top Leads", "ar": "🏆 أفضل العملاء"},
    "btn_stats": {"en": "📊 Campaign Statistics", "ar": "📊 إحصائيات الحملات"},
    "btn_export": {"en": "📤 Export Leads", "ar": "📤 تصدير العملاء"},
    "btn_dashboard": {"en": "🌐 Open Web Dashboard", "ar": "🌐 فتح لوحة التحكم"},
    "btn_settings": {"en": "⚙️ Settings", "ar": "⚙️ الإعدادات"},
    "btn_help": {"en": "❓ Help", "ar": "❓ مساعدة"},
    "ask_country": {"en": "🌍 Select target country.", "ar": "🌍 اختر الدولة المستهدفة."},
    "ask_country_code": {"en": "Type the 2-letter country code (e.g. QA, KW, JO).",
                         "ar": "اكتب رمز الدولة المكوّن من حرفين (مثل QA أو KW)."},
    "ask_city": {"en": "🏙 Select a city (or Skip).", "ar": "🏙 اختر المدينة (أو تخطَّ)."},
    "ask_industry": {"en": "🏢 Select business industry.", "ar": "🏢 اختر مجال النشاط."},
    "ask_custom_industry": {"en": "Type the industry (e.g. 'veterinary clinics').",
                            "ar": "اكتب مجال النشاط (مثل: عيادات بيطرية)."},
    "ask_sources": {"en": "🔌 Select discovery sources, then press Done.\n✅ connected · ⛔ unavailable",
                    "ar": "🔌 اختر مصادر البحث ثم اضغط تم.\n✅ متصل · ⛔ غير متاح"},
    "ask_count": {"en": "🎯 How many companies should we target?", "ar": "🎯 كم عدد الشركات المستهدفة؟"},
    "ask_custom_count": {"en": "Type a number between 1 and 500.", "ar": "اكتب رقماً بين 1 و 500."},
    "ask_ai": {"en": "🤖 Enable AI Business Analysis?", "ar": "🤖 تفعيل تحليل الأعمال بالذكاء الاصطناعي؟"},
    "summary": {"en": "📋 Confirm your campaign", "ar": "📋 تأكيد الحملة"},
    "started": {"en": "🚀 Research started!", "ar": "🚀 بدأ البحث!"},
    "cancelled_wizard": {"en": "Campaign creation cancelled.", "ar": "تم إلغاء إنشاء الحملة."},
    "no_sources": {"en": "Select at least one available source.", "ar": "اختر مصدراً متاحاً واحداً على الأقل."},
    "no_campaigns": {"en": "You have no campaigns yet.", "ar": "لا توجد حملات بعد."},
    "no_leads": {"en": "No leads found yet.", "ar": "لا يوجد عملاء محتملون بعد."},
    "error": {"en": "⚠️ Something went wrong: {msg}", "ar": "⚠️ حدث خطأ: {msg}"},
    "help": {
        "en": "AI Lead Hunter finds businesses, enriches published business contacts, analyses opportunities "
              "with evidence and scores leads.\n\n/start – main menu\n/new – new campaign\n/campaigns – your "
              "campaigns\n/top – top leads\n/link CODE – link your account\n/lang – switch language\n/cancel – "
              "cancel the current wizard\n\nDrafts are for human review; nothing is sent to prospects "
              "automatically.",
        "ar": "يبحث AI Lead Hunter عن الشركات ويجمع بيانات التواصل المنشورة ويحلل الفرص بالأدلة ويقيّم العملاء.\n\n"
              "/start – القائمة الرئيسية\n/new – حملة جديدة\n/campaigns – حملاتك\n/top – أفضل العملاء\n"
              "/link الرمز – ربط الحساب\n/lang – تغيير اللغة\n/cancel – إلغاء المعالج\n\n"
              "الرسائل المقترحة للمراجعة البشرية فقط؛ لا يتم إرسال أي شيء تلقائياً.",
    },
    "yes": {"en": "✅ Yes", "ar": "✅ نعم"},
    "no": {"en": "❌ No", "ar": "❌ لا"},
    "skip": {"en": "Skip", "ar": "تخطَّ"},
    "done": {"en": "✔️ Done", "ar": "✔️ تم"},
    "other": {"en": "🌐 Other", "ar": "🌐 أخرى"},
    "custom": {"en": "✏️ Custom", "ar": "✏️ مخصص"},
    "start_research": {"en": "🚀 Start Research", "ar": "🚀 ابدأ البحث"},
    "edit": {"en": "✏️ Edit Settings", "ar": "✏️ تعديل"},
    "cancel": {"en": "✖ Cancel", "ar": "✖ إلغاء"},
    "back": {"en": "⬅️ Menu", "ar": "⬅️ القائمة"},
}


def t(key: str, lang: str = "en", **kw: object) -> str:
    entry = STRINGS.get(key, {})
    text = entry.get(lang) or entry.get("en") or key
    return text.format(**kw) if kw else text
