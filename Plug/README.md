# 🎙️ Voice AI Smart Relay Controller

نظام خلفي (Backend) متكامل واحترافي مبني بـ **FastAPI** للتحكم الذكي في 8 خانات (Relays) باستخدام الأوامر الصوتية باللغة العربية والإنجليزية، إضافة لدعم الأوامر النصية، والتحكم اليدوي المباشر. 

النظام يعتمد بشكل أساسي على **Whisper** لتحويل الصوت إلى نص، و **Gemini AI** لتحليل النوايا (Intent Classification). النظام مصمم ليكون سهل الربط جداً مع تطبيقات الهاتف (Flutter, Android, iOS).

---

## 🚀 دليل التشغيل السريع (Quick Start)

```bash
# 1. استنساخ المشروع والدخول للمجلد
cd plug

# 2. إنشاء بيئة وهمية (Virtual Environment)
python -m venv .venv
source .venv/bin/activate   # في الويندوز: .venv\Scripts\activate

# 3. تثبيت الحزم المطلوبة
pip install -r requirements.txt

# 4. نسخ ملف الإعدادات وإضافة المفاتيح
cp .env.example .env
# → قم بتعديل ملف .env وأضف مفاتيح HF_TOKEN و GEMINI_API_KEY الخاصة بك

# 5. تشغيل السيرفر (وضع التطوير)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

> **واجهة التوثيق التفاعلية (Swagger UI):** `http://localhost:8000/docs`

---

## 🔌 توثيق واجهة برمجة التطبيقات (API Reference)

### 1️⃣ `GET /status` (جلب حالة الخانات)
يُستخدم هذا المسار لمعرفة حالة الخانات الحالية (مطفية أم تعمل) لتحديث واجهة التطبيق بشكل لحظي.

* **Headers**: لا يوجد.

**📥 الرد المتوقع (200 OK):**
```json
{
  "relays": [true, false, false, true, false, false, false, false],
  "active_count": 2,
  "timestamp": "2026-04-16T00:00:00+00:00"
}
```

---

### 2️⃣ `POST /command` (إرسال الأوامر)
القلب النابض للنظام. يستقبل الأوامر بـ 3 طرق مختلفة. 
*(يجب أن يكون نوع الإرسال `multipart/form-data` كونه يدعم رفع الملفات الصوتية).*

#### الطريقة الأولى (voice): الأوامر الصوتية بالذكاء الاصطناعي 🎙️
المستخدم يسجل صوته، والـ API يتولى فهم الأمر.

| الحقل (Field) | القيمة (Value) | الوصف |
| --- | --- | --- |
| `type` | `"voice"` | إجباري |
| `language` | `"ar"` أو `"en"` | لغة الاستجابة |
| `audio` | ملف (UploadFile) | ملف الصوت (الصيغ المدعومة: `wav`, `webm`, `m4a`) |

#### الطريقة الثانية (text): الأوامر النصية بالذكاء الاصطناعي ⌨️
للتحكم عبر الشات أو الكتابة المباشرة.

| الحقل (Field) | القيمة (Value) | الوصف |
| --- | --- | --- |
| `type` | `"text"` | إجباري |
| `language` | `"ar"` أو `"en"` | لغة الاستجابة |
| `text` | نص (String) | مثال: `"شغل الخانة التالتة"` |

#### الطريقة الثالثة (manual): التحكم اليدوي المباشر 👆
للتحكم عن طريق الأزرار (Switches) في الواجهة الرسومية.

| الحقل (Field) | القيمة (Value) | الوصف |
| --- | --- | --- |
| `type` | `"manual"` | إجباري |
| `language` | `"ar"` أو `"en"` | لغة الاستجابة |
| `index` | رقم `0` إلى `7` | رقم الخانة (Index 0 يعني الخانة رقم 1) |
| `action` | `"on"`, `"off"`, `"toggle"` | الإجراء المطلوب تنفيذه |

#### 📥 شكل الرد النهائي (Response) - 200 OK
شكل الرد موحد لجميع الأنواع لتسهيل التعامل في واجهة برمجة التطبيقات:

**🟢 عند نجاح تنفيذ الأمر:**
```json
{
  "success": true,
  "message": "تم تشغيل الخانة رقم 3",
  "intent": "turn_on",
  "relay_index": 2,
  "already_in_state": false,
  "transcript": "شغل الخانة التالتة",
  "language": "ar",
  "request_id": "8ad23731-1f9e-4a6c-9ea6",
  "relays_snapshot": [false, false, true, false, false, false, false, false]
}
```

**🟡 عند عدم فهم الأمر أو النية المشوشة:**
لا يحدث Crash، بل يتم إرجاع نجاح مع توضيح رسالة الود للمستخدم.
```json
{
  "success": false,
  "message": "عذراً، لم أفهم الأمر أو الخانة بدقة. يرجى التوضيح.",
  "intent": "unknown",
  "relay_index": null,
  "already_in_state": false,
  "transcript": "ألو ألو",
  "language": "ar",
  "request_id": "8ad23731-1f9e-4a6c-9ea6",
  "relays_snapshot": [false, false, false, false, false, false, false, false]
}
```

---

### 3️⃣ `GET /health` (التحقق من صحة النظام)
يستخدم للـ Pinging والمراقبة للاطمئنان أن السيرفر يعمل.

**📥 الرد المتوقع:**
```json
{"status": "ok", "service": "relay-controller"}
```

---

## ⚠️ الأخطاء المرفوضة والمطالِبة بالتدخل (Errors)

كل الأخطاء الاستثنائية تأتي بتنسيق ذو شكل واحد لتسهيل التقاطهاใน التطبيق.

```json
{
  "error": "whisper_api_error",
  "message": "Whisper transcription service unavailable.",
  "request_id": "550e8400-e29b-41d4-a716",
  "detail": null
}
```

**قائمة أشهر الأخطاء ومسبباتها:**
| الرمز (Code) | HTTP | السبب |
| --- | --- | --- |
| `whisper_api_error` | 503 | خوادم HuggingFace معطلة أو لا تستجيب. |
| `gemini_api_error` | 503 | واجهة Google Gemini معطلة. |
| `invalid_relay_index` | 422 | تم إرسال Index خارج النطاق (أقل من 0 أو أكبر من 7). |
| `audio_too_large` | 413 | حجم المقطع الصوتي أكبر من المسموح (10 ميجابايت). |
| `invalid_audio_mime` | 415 | صيغة الملف المرفوع ليست ملفاً صوتياً. |
| `low_confidence` | 422 | ثقة تحليل النوايا في Gemini أقل من الحد المسموح به (< 0.6). |
| `gpio_error` | 500 | مشكلة في هاردوير الراسبري باي (Raspberry Pi GPIO). |
| `rate_limit_exceeded`| 429 | تجاوز الحد المسموح من الطلبات (أكثر من 30 طلب بالدقيقة). |

---

## 🛠️ أمثلة أكواد بلغة Dart (Flutter)

**إرسال أمر صوتي:**
```dart
import 'package:http/http.dart' as http;
import 'dart:io';

Future<void> sendVoiceCommand(File audioFile) async {
  var uri = Uri.parse('http://YOUR_SERVER_IP:8000/command');
  var request = http.MultipartRequest('POST', uri);
  
  request.fields['type'] = 'voice';
  request.fields['language'] = 'ar';
  
  // إرفاق الملف الصوتي
  request.files.add(
    await http.MultipartFile.fromPath('audio', audioFile.path)
  );

  var response = await request.send();
  if (response.statusCode == 200) {
    String responseBody = await response.stream.bytesToString();
    print('النتيجة: $responseBody');
  }
}
```

**التحكم اليدوي المباشر:**
```dart
Future<void> toggleRelay(int relayIndex) async {
  var uri = Uri.parse('http://YOUR_SERVER_IP:8000/command');
  var request = http.MultipartRequest('POST', uri);
  
  request.fields['type'] = 'manual';
  request.fields['index'] = relayIndex.toString(); // 0 to 7
  request.fields['action'] = 'toggle';
  request.fields['language'] = 'ar';

  var response = await request.send();
  if (response.statusCode == 200) {
    print('Command successful');
  }
}
```

---

## 💻 وضع المحاكاة (GPIO Simulation Mode)

في حال استخدامك لنظام التشغيل Windows أو Mac، لن يتم التعرف على مكتبة `RPi.GPIO` الخاصة بالراسبري باي.
السيرفر الخاص بنا لديه ميزة كشف ذلك تلقائياً وسيعمل في "وضع المحاكاة". 

سوف يظهر لك في اللوجز (Logs) الآتي:
`{"level": "WARNING", "message": "Running in SIMULATION mode."}`

للنشر والتشغيل الحقيقي على Raspberry Pi للتحكم في الخانات الفعليّة يجب تثبيت الباكيدج الخاصة بها:
```bash
pip install RPi.GPIO
```

---

## 📁 هيكل النظام (Project Directory)

```text
app/
├── main.py                  # ملف تشغيل FastAPI الأساسي والتعامل مع الأخطاء
├── config.py                # إعدادات النظام ومفاتيح الـ API
├── routes/
│   ├── command.py           # يحتوي على POST /command
│   └── status.py            # يحتوي على GET /status
├── services/
│   ├── whisper_service.py   # التكامل مع HuggingFace لتحويل الصوت لنص
│   ├── ai_service.py        # التكامل مع Gemini لفهم الأوامر
│   ├── relay_service.py     # التحكم في الخانات (GPIO / Simulation)
│   └── response_service.py  # بناء رسائل الرد العربية بطريقة ودية
├── models/
│   └── schemas.py           # هياكل البيانات (Pydantic Models) المدخلة والمخرجة
└── utils/
    ├── logger.py            # مسجل أحداث (Logger) يمرّر Request ID لكل ريكويست
    └── exceptions.py        # مكتبة إدارة الأخطاء الراجعة وتوحيد الـ Exception
```

---

## 📖 أمثلة للأوامر الصوتية المدعومة للغة العربية

| الأمر باللغة العربية (عامية أو فصحى) | الإجراء المفترض | النية |
|-----------------------------|----------------|-------------|
| ولّع الخانة الأولى           | تشغيل الخانة رقم 1 | `turn_on` |
| اطفي رقم تمانية              | إيقاف الخانة رقم 8 | `turn_off` |
| بدّل الخانة الثالثة          | تغيير حالة الخانة 3 | `toggle` |
| شغّل كل الخانات              | تشغيل جميع الخانات الـ 8 | `all_on` |
| وقّف كل شي                   | إيقاف جميع الخانات | `all_off` |
| بدّل كل اللمبات للوضع العكسي | إعطاء أمر Toggle للكل | `toggle_all`|
