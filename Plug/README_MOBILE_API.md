# 📱 Voice AI Relay Controller - Mobile API Documentation

هذا الملف يحتوي على كل ما تحتاجه لربط التطبيق (Flutter, Android, iOS) مع الـ Backend.

الـ Backend بيقدم مسارين أساسيين: 
1. `GET /status`: لمعرفة حالة الخانات الحالية.
2. `POST /command`: لإرسال الأوامر (بالصوت 🎙️، بالنص ⌨️، أو بشكل يدوي 👆).

---

## 1️⃣ جلب حالة الخانات (Get Relay Status)

يُستخدم هذا الـ Endpoint عشان تعرض حالة الخانات (مطفية / شغالة) في واجهة التطبيق بشكل لحظي.

- **Endpoint**: `GET /status`
- **Method**: `GET`
- **Headers**: لا يوجد (فقط `Accept: application/json` اختياري)

### 📥 الرد المتوقع (Response - 200 OK):
```json
{
  "relays": [
    true,   // Relay 1 (Index 0) -> ON
    false,  // Relay 2 (Index 1) -> OFF
    false,  // Relay 3 (Index 2) -> OFF
    true,   // Relay 4 (Index 3) -> ON
    false,
    false,
    false,
    false
  ],
  "active_count": 2, // عدد الخانات الشغالة حالياً
  "timestamp": "2026-04-16T00:54:37+00:00"
}
```

---

## 2️⃣ إرسال أمر (Send Command)

- **Endpoint**: `POST /command`
- **Method**: `POST`
- **Content-Type**: `multipart/form-data`  **(مهم جداً جداً في Flutter تستخدم `MultipartRequest`)**

الـ API ده ذكي جداً وبيستقبل الأوامر بـ 3 طرق مختلفة (عن طريق تحديد قيمة حقل `type`):

### الطريقة الأولى: الأوامر الصوتية بالذكاء الاصطناعي 🎙️
المستخدم بيسجل صوته (عربي أو إنجليزي، فصحى أو عامية)، والـ API بيفهمه وينفذه.

**الحقول المطلوبة (Form Fields):**
- `type`: `"voice"`
- `language`: `"ar"` (للرد بالعربي) أو `"en"` (إنجليزي)
- `audio`: ملف الصوت الفعلي (File Upload - صيغ مدعومة: `wav`, `webm`, `m4a`).

> ⚠️ في فلاتر (Flutter)، استخدم الطريقة دي لرفع الصوت:
> `request.files.add(await http.MultipartFile.fromPath('audio', audioFilePath));`

### الطريقة الثانية: الأوامر النصية بالذكاء الاصطناعي ⌨️
لو هتعمل شات (Chatbot) أو زرار أرسل بـ Textbox بتكتب فيه الأمر.

**الحقول المطلوبة (Form Fields):**
- `type`: `"text"`
- `language`: `"ar"` أو `"en"`
- `text`: الأمر كنص (مثال: `"ولع الأنوار كلها"`, `"طفي الخانة التالتة"`).

### الطريقة الثالثة: التحكم اليدوي المباشر 👆
زي زراير الـ Switches الافتراضية في الواجهة للتحكم المباشر.

**الحقول المطلوبة (Form Fields):**
- `type`: `"manual"`
- `language`: `"ar"` أو `"en"`
- `index`: رقم الخانة برمجياً (من `0` إلى `7`).
  *(يعني لو في الـ UI زرار الخانة 1، هتبعت هنا 0)*.
- `action`: الحركة المطلوبة. تقبل 3 قيم فقط:
  - `"on"`: تشغيل.
  - `"off"`: إطفاء.
  - `"toggle"`: عكس الحالة الحالية.

---

### 📥 الرد النهائي لأي أمر (Command Response):

سواء بعتّ صوت أو نص أو تحكم يدوي، شكل الرد دايماً هيكون **موحد**:

#### 🟢 حالة النجاح (200 OK)
لو النية اتحددت صح، أو الأمر تنفذ:
```json
{
  "success": true,
  "message": "تم تشغيل الخانة رقم 3", // الرسالة الجاهزة لعرضها في التطبيق 
  "intent": "turn_on", // نوع النية (للاستخدام البرمجي في التطبيق)
  "relay_index": 2, // الخانة اللي اتأثرت (Index)
  "already_in_state": false, // لو كانت بالفعل شغالة هترجع true
  "transcript": "شغل الخانة التالتة", // (فقط مع الصوت) الكلام اللي اتفهم
  "language": "ar",
  "request_id": "8ad23731-...-3cafa4d3fff2",
  "relays_snapshot": [ // حالة جميع الخانات "بعد" تنفيذ الأمر مباشرة (مفيدة لتحديث الـ UI دون نداء جديد للـ status)
    false, false, true, false, false, false, false, false
  ]
}
```

#### 🟡 حالة عدم فهم الأمر (200 OK)
لو المستخدم قال أمر غير مفهوم أو ذبذبة صوتية (مش هيحصل Crash للـ API بفضل الـ Error Handling):
```json
{
  "success": false,
  "message": "عذراً، لم أفهم الأمر أو الخانة بدقة. يرجى التوضيح.",
  "intent": "unknown", // نية غير معروفة
  "relay_index": null,
  "already_in_state": false,
  "transcript": "ألو ألو",  // الكلام الغير مفهوم
  "language": "ar",
  "request_id": "8ad2...",
  "relays_snapshot": [ ... ] 
}
```
*💡 لاحظ: حالة الـ HTTP بيفضل 200، بس الـ JSON جواه `"success": false` و `"message"` ودية وتثقيفية عشان تعرضها لليوزر زي ما هي.*

#### 🔴 الأخطاء المرفوضة والمطالبة بتصحيح الكود (Errors 422 Unprocessable)
لو مبرمج التطبيق بعت داتا ناقصة أو غلط (مثلاً بعت حرف في الـ index أو محطش ملف):
```json
{
  "error": "validation_error",
  "message": "Request validation failed.",
  "detail": [
    {
      "loc": ["body", "audio"],
      "msg": "Value error, Expected UploadFile, received: <class 'str'>"
    }
  ]
}
```

---

## 🛠️ أمثلة أكواد بلغة Dart (Flutter) للتطبيق:

### 1- مثال التحكم المباشر (عند كبس الزرار):
```dart
import 'package:http/http.dart' as http;

Future<void> toggleRelay(int relayNumber) async {
  var uri = Uri.parse('http://YOUR_SERVER_IP:8000/command');
  var request = http.MultipartRequest('POST', uri);
  
  request.fields['type'] = 'manual';
  request.fields['index'] = (relayNumber - 1).toString(); // الخانة 1 يعني index 0
  request.fields['action'] = 'toggle';
  request.fields['language'] = 'ar'; // للرد بـ "تم تشغيل.." بدلاً من "Turned on.."

  var response = await request.send();
  if (response.statusCode == 200) {
    print('Command successful');
  }
}
```

### 2- مثال الأمر الصوتي المرفوع بالمايك:
```dart
import 'package:http/http.dart' as http;
import 'dart:io';

Future<void> sendVoiceCommand(File audioFile) async {
  var uri = Uri.parse('http://YOUR_SERVER_IP:8000/command');
  var request = http.MultipartRequest('POST', uri);
  
  request.fields['type'] = 'voice';
  request.fields['language'] = 'ar';
  
  // رفع الصوت
  request.files.add(
    await http.MultipartFile.fromPath('audio', audioFile.path)
  );

  var response = await request.send();
  if (response.statusCode == 200) {
    // اقرأ ملف الـ JSON عشان تطلع الـ message
    String responseBody = await response.stream.bytesToString();
    print('Response: \$responseBody');
  }
}
```
