"""Bilingual strings (English / Arabic). Every user-facing text of the bot lives here."""

STRINGS: dict[str, dict[str, str]] = {
    # Welcome, linking, access ------------------------------------------------------------------------
    "welcome": {"en": "👋 Hi {name}!\n\n<b>Rasd</b> finds businesses that need what you sell, with their phone, "
                      "WhatsApp and email.\n\nWhat would you like to do?",
                "ar": "👋 أهلاً {name}!\n\n<b>رصد</b> بيلاقيلك الشركات اللي محتاجة خدمتك، بتليفوناتها وواتسابها "
                      "وإيميلاتها.\n\nتحب تعمل إيه؟"},
    "welcome_tip": {"en": "💡 Tip: just type what you are looking for, e.g. <i>dental clinics in Riyadh</i>.",
                    "ar": "💡 نصيحة: اكتب اللي بتدور عليه على طول، مثلاً <i>عيادات أسنان في الرياض</i>."},
    "demo_banner": {"en": "🧪 Demo mode is on: demo searches use fictional data.",
                    "ar": "🧪 الوضع التجريبي مفعّل: البحث التجريبي بيستخدم بيانات وهمية."},
    "not_linked": {
        "en": "👋 Welcome to <b>Rasd</b>!\n\nRasd finds ready clients for your business: companies that need "
              "your service, with their phone, WhatsApp and email.\n\n<b>Link your account in 3 steps:</b>\n"
              "1️⃣ Sign in to the dashboard (or create a free account).\n"
              "2️⃣ Open Settings → Telegram and press “Link Telegram”.\n"
              "3️⃣ Press “Open the bot” — or send the code here: <code>/link CODE</code>",
        "ar": "👋 أهلاً بيك في <b>رصد</b>!\n\nرصد بيجيبلك عملاء جاهزين: شركات محتاجة خدمتك، بتليفوناتها "
              "وواتسابها وإيميلاتها.\n\n<b>اربط حسابك في 3 خطوات:</b>\n"
              "1️⃣ ادخل لوحة التحكم (أو اعمل حساب مجاني).\n"
              "2️⃣ افتح الإعدادات ← تيليجرام واضغط «ربط تيليجرام».\n"
              "3️⃣ اضغط «افتح البوت» — أو ابعت الكود هنا: <code>/link الكود</code>"},
    "not_linked_short": {"en": "🔒 Link your account first: send /start for the steps.",
                         "ar": "🔒 اربط حسابك الأول: ابعت /start عشان تشوف الخطوات."},
    "pending": {"en": "⏳ Your link request was received and is waiting for your workspace admin to approve it.\n"
                      "You will be able to use the bot as soon as it is approved.",
                "ar": "⏳ طلب الربط وصل ومستني موافقة مسؤول مساحة العمل.\nهتقدر تستخدم البوت أول ما يتوافق عليه."},
    "linked": {"en": "✅ Your account is linked!", "ar": "✅ تم ربط حسابك!"},
    "link_usage": {"en": "Send the code from the dashboard like this: <code>/link CODE</code>",
                   "ar": "ابعت الكود اللي في لوحة التحكم كده: <code>/link الكود</code>"},
    "link_failed": {"en": "⚠️ This code did not work: {msg}\nGenerate a new code in Settings → Telegram.",
                    "ar": "⚠️ الكود ده مانفعش: {msg}\nاعمل كود جديد من الإعدادات ← تيليجرام."},
    "backend_down": {"en": "⚠️ Rasd is unavailable right now. Please try again in a minute.",
                     "ar": "⚠️ رصد مش متاح دلوقتي. جرّب تاني بعد دقيقة."},
    "error": {"en": "⚠️ Something went wrong: {msg}", "ar": "⚠️ حصلت مشكلة: {msg}"},
    "error_generic": {"en": "⚠️ Something went wrong. Please try again.", "ar": "⚠️ حصلت مشكلة. جرّب تاني."},
    "expired_button": {"en": "This button is no longer active. Send /start.",
                       "ar": "الزرار ده مابقاش شغال. ابعت /start."},
    "btn_register": {"en": "📝 Create a free account", "ar": "📝 اعمل حساب مجاني"},
    "btn_link_page": {"en": "🔗 Open Telegram settings", "ar": "🔗 افتح إعدادات تيليجرام"},

    # Main menu ---------------------------------------------------------------------------------------
    "btn_new": {"en": "🔎 New search", "ar": "🔎 بحث جديد"},
    "btn_mine": {"en": "📁 My searches", "ar": "📁 عمليات البحث"},
    "btn_top": {"en": "⭐ Best leads", "ar": "⭐ أفضل العملاء"},
    "btn_balance": {"en": "💳 My credits", "ar": "💳 رصيدي"},
    "btn_export": {"en": "📤 Export", "ar": "📤 تصدير"},
    "btn_settings": {"en": "⚙️ Settings", "ar": "⚙️ الإعدادات"},
    "btn_help": {"en": "❓ Help", "ar": "❓ مساعدة"},
    "btn_dashboard": {"en": "🌐 Open dashboard", "ar": "🌐 لوحة التحكم"},
    "menu": {"en": "🏠 Menu", "ar": "🏠 القائمة"},
    "back": {"en": "⬅️ Back", "ar": "⬅️ رجوع"},
    "cancel": {"en": "✖️ Cancel", "ar": "✖️ إلغاء"},
    "skip": {"en": "⏭ Skip", "ar": "⏭ تخطي"},
    # Telegram lays buttons out left-to-right in every language, so the arrows are not mirrored.
    "prev": {"en": "◀️", "ar": "◀️"},
    "next": {"en": "▶️", "ar": "▶️"},
    "on": {"en": "On", "ar": "مفعّل"},
    "off": {"en": "Off", "ar": "مقفول"},

    # Help & settings ---------------------------------------------------------------------------------
    "help": {
        "en": "❓ <b>How Rasd works</b>\n\n"
              "1️⃣ <b>Search</b>: type what you want (e.g. <i>restaurants in Dubai</i>) or press 🔎 New search.\n"
              "2️⃣ <b>Wait a few minutes</b>: we find businesses, collect their published contacts and analyse "
              "each one. You get a message when it is done.\n"
              "3️⃣ <b>Contact them</b>: open ⭐ Best leads, see why each one fits, and message them on WhatsApp "
              "with one tap.\n\n"
              "💳 1 credit = 1 new business with a phone, WhatsApp or email. Businesses you already have are "
              "free.\n\n"
              "<b>Commands</b>\n/start – menu\n/new – new search\n/campaigns – my searches\n/top – best leads\n"
              "/balance – my credits\n/lang – عربي / English\n/cancel – stop the current step\n\n"
              "Nothing is ever sent to businesses automatically.",
        "ar": "❓ <b>رصد بيشتغل إزاي</b>\n\n"
              "1️⃣ <b>ابحث</b>: اكتب اللي عايزه (مثلاً <i>مطاعم في دبي</i>) أو اضغط 🔎 بحث جديد.\n"
              "2️⃣ <b>استنى دقايق</b>: بنلاقي الشركات ونجمع بيانات التواصل المنشورة ونحلل كل شركة، "
              "وهيوصلك إشعار لما يخلص.\n"
              "3️⃣ <b>كلّمهم</b>: افتح ⭐ أفضل العملاء، شوف ليه كل واحد مناسب، وابعتله واتساب بضغطة.\n\n"
              "💳 1 كريدت = شركة جديدة واحدة ليها تليفون أو واتساب أو إيميل. الشركات اللي عندك قبل كده مجاناً.\n\n"
              "<b>الأوامر</b>\n/start – القائمة\n/new – بحث جديد\n/campaigns – عمليات البحث\n/top – أفضل العملاء\n"
              "/balance – رصيدي\n/lang – عربي / English\n/cancel – إلغاء الخطوة الحالية\n\n"
              "مفيش أي رسالة بتتبعت للشركات تلقائياً.",
    },
    "settings": {"en": "⚙️ <b>Settings</b>\n\n👤 Account: {user}\n🎖 Role: {role}\n🌐 Language: English\n\n"
                       "Your profile, team and Telegram links are managed in the dashboard.",
                 "ar": "⚙️ <b>الإعدادات</b>\n\n👤 الحساب: {user}\n🎖 الدور: {role}\n🌐 اللغة: العربية\n\n"
                       "ملفك وفريقك وربط تيليجرام بيتظبطوا من لوحة التحكم."},
    "btn_lang": {"en": "🌐 العربية", "ar": "🌐 English"},
    "lang_set": {"en": "✅ Language: English", "ar": "✅ اللغة: العربية"},

    # New search wizard -------------------------------------------------------------------------------
    "ask_mode": {"en": "🔎 <b>New search</b>\n\nHow would you like to describe it?",
                 "ar": "🔎 <b>بحث جديد</b>\n\nتحب توصف اللي عايزه إزاي؟"},
    "btn_free_text": {"en": "✍️ Type it in my words", "ar": "✍️ أكتبه بكلامي"},
    "btn_steps": {"en": "📋 Step by step", "ar": "📋 خطوة بخطوة"},
    "ask_free_text": {"en": "✍️ Describe the businesses you want in one message.\n\nExamples:\n"
                            "• <i>dental clinics in Riyadh</i>\n• <i>real estate agencies in Cairo, 50 companies</i>",
                      "ar": "✍️ اوصف الشركات اللي عايزها في رسالة واحدة.\n\nأمثلة:\n"
                            "• <i>عيادات أسنان في الرياض</i>\n• <i>شركات عقارات في القاهرة، 50 شركة</i>"},
    "parsing": {"en": "⏳ Understanding your request…", "ar": "⏳ بفهم طلبك…"},
    "step": {"en": "Step {n}/4", "ar": "خطوة {n}/4"},
    "ask_country": {"en": "🌍 Which country?", "ar": "🌍 في أنهي دولة؟"},
    "ask_country_code": {"en": "Type the 2-letter country code (e.g. QA, KW, JO).",
                         "ar": "اكتب كود الدولة من حرفين (مثلاً QA أو KW أو JO)."},
    "ask_city": {"en": "🏙 Which city in {country}?", "ar": "🏙 أنهي مدينة في {country}؟"},
    "ask_custom_city": {"en": "Type the city name.", "ar": "اكتب اسم المدينة."},
    "whole_country": {"en": "🌍 Whole country", "ar": "🌍 الدولة كلها"},
    "all_cities": {"en": "All cities", "ar": "كل المدن"},
    "other_city": {"en": "✏️ Another city", "ar": "✏️ مدينة تانية"},
    "other_country": {"en": "✏️ Another country", "ar": "✏️ دولة تانية"},
    "ask_industry": {"en": "🏢 What kind of businesses?", "ar": "🏢 نوع الشركات إيه؟"},
    "custom_industry": {"en": "✏️ Type it", "ar": "✏️ اكتبه"},
    "ask_custom_industry": {"en": "Type the type of business (e.g. <i>veterinary clinics</i>).",
                            "ar": "اكتب نوع النشاط (مثلاً <i>عيادات بيطرية</i>)."},
    "ask_count": {"en": "🎯 How many businesses should we look for?", "ar": "🎯 عايز كام شركة؟"},
    "custom": {"en": "✏️ Other", "ar": "✏️ رقم تاني"},
    "ask_custom_count": {"en": "Type a number between 1 and 500.", "ar": "اكتب رقم من 1 لـ 500."},
    "summary": {"en": "📋 <b>Review your search</b>", "ar": "📋 <b>راجع البحث</b>"},
    "f_country": {"en": "🌍 Country", "ar": "🌍 الدولة"},
    "f_city": {"en": "🏙 City", "ar": "🏙 المدينة"},
    "f_industry": {"en": "🏢 Businesses", "ar": "🏢 النشاط"},
    "f_count": {"en": "🎯 Target", "ar": "🎯 العدد"},
    "f_ai": {"en": "🤖 Smart analysis", "ar": "🤖 التحليل الذكي"},
    "f_keywords": {"en": "🔑 Keywords", "ar": "🔑 كلمات البحث"},
    "count_value": {"en": "{n} businesses", "ar": "{n} شركة"},
    "credits_line": {"en": "💳 Up to <b>{max}</b> credits · Your balance: <b>{balance}</b>",
                     "ar": "💳 حتى <b>{max}</b> كريدت · رصيدك: <b>{balance}</b>"},
    "credits_rule": {"en": "You pay only for new businesses with a phone, WhatsApp or email.",
                     "ar": "بتدفع بس على الشركات الجديدة اللي ليها تليفون أو واتساب أو إيميل."},
    "credits_low": {"en": "⚠️ Your balance is lower than the target: the search stops when credits run out.",
                    "ar": "⚠️ رصيدك أقل من العدد المطلوب: البحث هيقف لما الرصيد يخلص."},
    "credits_zero": {"en": "⛔ You have no credits. Top up to start this search.",
                     "ar": "⛔ مفيش رصيد. اشحن عشان تبدأ البحث ده."},
    "demo_search": {"en": "🧪 Demo search — fictional data, free.", "ar": "🧪 بحث تجريبي — بيانات وهمية ومجاناً."},
    "no_sources": {"en": "⛔ Search is temporarily unavailable. Please try again later.",
                   "ar": "⛔ البحث مش متاح دلوقتي. جرّب تاني بعد شوية."},
    "btn_start": {"en": "🚀 Start search", "ar": "🚀 ابدأ البحث"},
    "btn_toggle_ai": {"en": "🤖 Smart analysis: {v}", "ar": "🤖 التحليل الذكي: {v}"},
    "btn_edit_place": {"en": "📍 Change place", "ar": "📍 غيّر المكان"},
    "btn_edit_industry": {"en": "🏢 Change type", "ar": "🏢 غيّر النشاط"},
    "btn_edit_count": {"en": "🎯 Change number", "ar": "🎯 غيّر العدد"},
    "btn_topup": {"en": "💳 Top up credits", "ar": "💳 اشحن رصيد"},
    "started": {"en": "🚀 <b>Search started!</b> I will message you when it is done — usually a few minutes.",
                "ar": "🚀 <b>البحث بدأ!</b> هبعتلك أول ما يخلص — غالباً دقايق."},
    "cancelled_wizard": {"en": "Cancelled. Anything else?", "ar": "اتلغى. تحب تعمل حاجة تانية؟"},
    "need_credits": {"en": "💳 {msg}", "ar": "💳 {msg}"},
    "msg_no_credits": {"en": "You have no credits left. Top up to run a search.",
                       "ar": "رصيدك خلص. اشحن عشان تعمل بحث."},
    "msg_trial_expired": {"en": "Your free trial has ended. Top up to continue.",
                          "ar": "التجربة المجانية خلصت. اشحن عشان تكمل."},
    "msg_email_unverified": {"en": "Confirm your email (check your inbox) to activate your free credits.",
                             "ar": "أكّد إيميلك (شوف الرسايل) عشان الرصيد المجاني يتفعّل."},

    # Campaigns ---------------------------------------------------------------------------------------
    "campaigns_title": {"en": "📁 <b>My searches</b> ({total})", "ar": "📁 <b>عمليات البحث</b> ({total})"},
    "no_campaigns": {"en": "You have no searches yet. Press 🔎 New search or just type what you need.",
                     "ar": "لسه معملتش أي بحث. اضغط 🔎 بحث جديد أو اكتب اللي عايزه على طول."},
    "c_place": {"en": "📍 {place}", "ar": "📍 {place}"},
    "c_status": {"en": "Status: <b>{status}</b>", "ar": "الحالة: <b>{status}</b>"},
    "c_found": {"en": "🔎 Found: {found} · ✅ Qualified: {qualified}",
                "ar": "🔎 اتلقى: {found} · ✅ مناسبين: {qualified}"},
    "c_contacts": {"en": "📞 With contact info: {n} · 🔥 High priority: {h}",
                   "ar": "📞 ليهم بيانات تواصل: {n} · 🔥 أولوية عالية: {h}"},
    "c_target": {"en": "🎯 Target: {n}", "ar": "🎯 المطلوب: {n}"},
    "c_note_credits": {"en": "💳 Stopped early: your credits ran out.", "ar": "💳 وقف بدري: الرصيد خلص."},
    "c_note_time": {"en": "⏱ Stopped at the time limit.", "ar": "⏱ وقف عند الحد الأقصى للوقت."},
    "c_note_partial": {"en": "ℹ️ Some sources returned fewer results than usual.",
                       "ar": "ℹ️ بعض المصادر رجّعت نتايج أقل من المعتاد."},
    "c_note_failed": {"en": "⚠️ The search could not finish. Press 🔁 Retry or try another city.",
                      "ar": "⚠️ البحث ماكملش. اضغط 🔁 إعادة أو جرّب مدينة تانية."},
    "btn_progress": {"en": "🔄 Refresh", "ar": "🔄 تحديث"},
    "btn_pause": {"en": "⏸ Pause", "ar": "⏸ إيقاف مؤقت"},
    "btn_resume": {"en": "▶️ Resume", "ar": "▶️ استكمال"},
    "btn_stop": {"en": "⏹ Stop", "ar": "⏹ إيقاف"},
    "btn_results": {"en": "📋 All results", "ar": "📋 كل النتايج"},
    "btn_best": {"en": "⭐ Best leads", "ar": "⭐ أفضل العملاء"},
    "btn_csv": {"en": "📤 Excel / CSV", "ar": "📤 إكسيل / CSV"},
    "btn_retry": {"en": "🔁 Retry", "ar": "🔁 إعادة"},
    "btn_all_campaigns": {"en": "📁 All searches", "ar": "📁 كل عمليات البحث"},
    "done_action": {"en": "Done ✔", "ar": "تم ✔"},
    "updated": {"en": "Updated", "ar": "اتحدّث"},
    "export_caption": {"en": "📤 Your leads (opens in Excel)", "ar": "📤 عملاءك (بيفتح في إكسيل)"},

    # Leads -------------------------------------------------------------------------------------------
    "leads_top": {"en": "⭐ <b>Best leads</b>", "ar": "⭐ <b>أفضل العملاء</b>"},
    "leads_all": {"en": "📋 <b>Results</b>", "ar": "📋 <b>النتايج</b>"},
    "leads_range": {"en": "{a}–{b} of {total}", "ar": "{a}–{b} من {total}"},
    "leads_pick": {"en": "Tap a number to open the lead.", "ar": "اضغط على الرقم عشان تفتح العميل."},
    "no_leads": {"en": "No leads yet. Start a search and they will show up here.",
                 "ar": "مفيش عملاء لسه. ابدأ بحث وهيظهروا هنا."},
    "contacts_n": {"en": "📇 {n} contacts", "ar": "📇 {n} وسيلة تواصل"},
    "no_contact": {"en": "no contact yet", "ar": "مفيش تواصل لسه"},
    "verified": {"en": "verified", "ar": "موثّق"},
    "l_score": {"en": "📈 Score: <b>{score}/100</b> · {priority}", "ar": "📈 التقييم: <b>{score}/100</b> · {priority}"},
    "l_why": {"en": "💡 <b>Why it fits</b>", "ar": "💡 <b>ليه مناسب</b>"},
    "l_summary": {"en": "📝 <b>About</b>", "ar": "📝 <b>نبذة</b>"},
    "l_contacts": {"en": "📞 <b>Contacts</b>", "ar": "📞 <b>التواصل</b>"},
    "l_no_contacts": {"en": "No published contacts found yet.", "ar": "لسه ملقيناش بيانات تواصل منشورة."},
    "l_crm": {"en": "🏷 Status: <b>{status}</b>", "ar": "🏷 الحالة: <b>{status}</b>"},
    "l_note": {"en": "🗒 Last note: {note}", "ar": "🗒 آخر ملاحظة: {note}"},
    "l_suppressed": {"en": "🚫 On your do-not-contact list.", "ar": "🚫 في قايمة عدم التواصل."},
    "btn_whatsapp": {"en": "💬 WhatsApp", "ar": "💬 واتساب"},
    "btn_website": {"en": "🌐 Website", "ar": "🌐 الموقع"},
    "btn_status": {"en": "🏷 Change status", "ar": "🏷 غيّر الحالة"},
    "btn_note": {"en": "📝 Add note", "ar": "📝 أضف ملاحظة"},
    "btn_back_list": {"en": "⬅️ Back to list", "ar": "⬅️ رجوع للقايمة"},
    "pick_status": {"en": "🏷 Choose the new status for <b>{name}</b>:", "ar": "🏷 اختار الحالة الجديدة لـ <b>{name}</b>:"},
    "status_saved": {"en": "Status saved ✔", "ar": "الحالة اتحفظت ✔"},
    "ask_note": {"en": "📝 Send the note for <b>{name}</b>.", "ar": "📝 ابعت الملاحظة الخاصة بـ <b>{name}</b>."},
    "note_saved": {"en": "✅ Note saved.", "ar": "✅ الملاحظة اتحفظت."},
    "export_pick": {"en": "📤 What would you like to export?", "ar": "📤 تحب تصدّر إيه؟"},
    "btn_export_qualified": {"en": "⭐ Qualified leads", "ar": "⭐ العملاء المناسبين"},

    # Credits & top-up --------------------------------------------------------------------------------
    "bal_title": {"en": "💳 <b>My credits</b>", "ar": "💳 <b>رصيدي</b>"},
    "bal_value": {"en": "Balance: <b>{n}</b> credits", "ar": "الرصيد: <b>{n}</b> كريدت"},
    "bal_unlimited": {"en": "Balance: <b>unlimited</b>", "ar": "الرصيد: <b>مفتوح</b>"},
    "bal_trial": {"en": "🎁 Free trial: {days} days left", "ar": "🎁 التجربة المجانية: فاضل {days} يوم"},
    "bal_trial_expired": {"en": "⛔ Your free trial has ended.", "ar": "⛔ التجربة المجانية خلصت."},
    "bal_low": {"en": "⚠️ Your balance is running low.", "ar": "⚠️ رصيدك قرب يخلص."},
    "bal_pending": {"en": "⏳ Top-up requests under review: {n}", "ar": "⏳ طلبات شحن تحت المراجعة: {n}"},
    "bal_unverified": {"en": "📧 Confirm your email to activate your free credits.",
                       "ar": "📧 أكّد إيميلك عشان الرصيد المجاني يتفعّل."},
    "bal_rule": {"en": "1 credit = 1 new business with a phone, WhatsApp or email.",
                 "ar": "1 كريدت = شركة جديدة ليها تليفون أو واتساب أو إيميل."},
    "pick_package": {"en": "💳 <b>Choose a package</b>", "ar": "💳 <b>اختار الباقة</b>"},
    "package_btn": {"en": "{name} · {credits} credits · {price}",
                    "ar": "{name} · {credits} كريدت · {price}"},
    "pay_on_web": {"en": "💳 <b>{name}</b> — {credits} credits for <b>{price}</b>\n\n"
                         "Pay securely with PayPal (card or PayPal balance). The credits are added instantly.",
                   "ar": "💳 <b>{name}</b> — {credits} كريدت بـ <b>{price}</b>\n\n"
                         "ادفع بأمان عبر PayPal (بالكارت أو رصيد PayPal). الرصيد بيتضاف فوراً."},
    "pay_on_web_no_link": {"en": "Open 💳 Credits in the dashboard to pay.",
                           "ar": "افتح صفحة 💳 النقاط في لوحة التحكم عشان تدفع."},
    "btn_pay_paypal": {"en": "💳 Pay with PayPal", "ar": "💳 ادفع بـ PayPal"},
    "no_packages": {"en": "No packages are available right now. Contact support from the dashboard.",
                    "ar": "مفيش باقات متاحة دلوقتي. كلّم الدعم من لوحة التحكم."},
    "pick_method": {"en": "💳 <b>{name}</b> — {credits} credits for <b>{price} {currency}</b>\n\n"
                          "How will you pay?",
                    "ar": "💳 <b>{name}</b> — {credits} كريدت بـ <b>{price} {currency}</b>\n\nهتدفع إزاي؟"},
    "pay_instructions": {"en": "📌 <b>How to pay</b>\n{text}", "ar": "📌 <b>طريقة الدفع</b>\n{text}"},
    "ask_reference": {"en": "🔢 Send the transfer reference number (or press Skip).",
                      "ar": "🔢 ابعت الرقم المرجعي للتحويل (أو اضغط تخطي)."},
    "ask_receipt": {"en": "🧾 Now send a <b>photo or PDF of the receipt</b>.",
                    "ar": "🧾 ابعت دلوقتي <b>صورة أو PDF للإيصال</b>."},
    "receipt_invalid": {"en": "Please send the receipt as a photo, an image or a PDF (max 5 MB).",
                        "ar": "ابعت الإيصال صورة أو PDF (أقصى حجم 5 ميجا)."},
    "topup_sent": {"en": "✅ <b>Request sent!</b>\nWe will review your receipt and add the credits. "
                         "You can check the status in 💳 My credits.",
                   "ar": "✅ <b>الطلب اتبعت!</b>\nهنراجع الإيصال ونضيف الرصيد. تقدر تتابع من 💳 رصيدي."},
    "topup_admin_only": {"en": "Only workspace admins can request top-ups. Ask your admin.",
                         "ar": "مسؤول مساحة العمل بس اللي يقدر يطلب شحن. كلّمه."},
    "uploading": {"en": "⏳ Sending…", "ar": "⏳ جاري الإرسال…"},
}

STATUS = {
    "draft": ("📝", "Draft", "مسودة"),
    "queued": ("⏳", "Starting", "بيبدأ"),
    "discovering": ("🔍", "Finding businesses", "بيدور على الشركات"),
    "enriching": ("📇", "Collecting contacts", "بيجمع بيانات التواصل"),
    "analyzing": ("🤖", "Analysing", "بيحلل"),
    "completed": ("✅", "Completed", "خلص"),
    "partially_completed": ("☑️", "Completed (partial)", "خلص جزئياً"),
    "failed": ("❌", "Failed", "فشل"),
    "paused": ("⏸", "Paused", "متوقف مؤقتاً"),
    "cancelled": ("⏹", "Stopped", "اتوقف"),
}
RUNNING = ("queued", "discovering", "enriching", "analyzing")

CRM = {
    "new": ("🆕", "New", "جديد"),
    "reviewed": ("👀", "Reviewed", "اتراجع"),
    "qualified": ("✅", "Qualified", "مناسب"),
    "ready_for_outreach": ("📣", "Ready to contact", "جاهز للتواصل"),
    "contacted": ("📞", "Contacted", "اتكلمنا معاه"),
    "replied": ("💬", "Replied", "رد"),
    "meeting_scheduled": ("📅", "Meeting booked", "اتحدد ميعاد"),
    "won": ("🏆", "Won", "اتقفل"),
    "lost": ("➖", "Lost", "مانفعش"),
    "do_not_contact": ("🚫", "Do not contact", "عدم تواصل"),
}
PRIORITY = {"high": ("🔥", "High priority", "أولوية عالية"), "medium": ("🟡", "Medium priority", "أولوية متوسطة"),
            "low": ("⚪", "Low priority", "أولوية منخفضة")}
METHODS = {"instapay": ("⚡", "InstaPay", "إنستاباي"), "bank_transfer": ("🏦", "Bank transfer", "تحويل بنكي"),
           "vodafone_cash": ("📱", "Vodafone Cash", "فودافون كاش")}
ROLES = {"owner": ("Owner", "المالك"), "admin": ("Admin", "مسؤول"), "analyst": ("Analyst", "محلل"),
         "viewer": ("Viewer", "مشاهد")}


def t(key: str, lang: str = "en", **kw: object) -> str:
    entry = STRINGS.get(key, {})
    text = entry.get(lang) or entry.get("en") or key
    return text.format(**kw) if kw else text


def label(table: dict[str, tuple], value: str | None, lang: str, emoji: bool = True) -> str:
    """Translated label from one of the (emoji, en, ar) tables; unknown values are shown readable."""
    row = table.get(value or "")
    if row is None:
        return (value or "—").replace("_", " ")
    text = row[2] if lang == "ar" else row[1]
    return f"{row[0]} {text}" if emoji else text


def role_label(role: str | None, lang: str) -> str:
    row = ROLES.get(role or "")
    return (row[1] if lang == "ar" else row[0]) if row else (role or "—")


def num(n: object) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"
