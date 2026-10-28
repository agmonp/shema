# מדריך העלאה והגשה ב-Google Play Console עבור "שמע Pro"

מסמך זה מלווה אותך צעד-אחר-צעד במסכי ה-**Google Play Console** ([play.google.com/console](https://play.google.com/console)) כדי להעלות את האפליקציה, להגדיר את המנוי השנתי ולהגיש לבדיקה.

---

## 1. יצירת האפליקציה ב-Play Console (Create App)
1. היכנס ל-[Google Play Console](https://play.google.com/console).
2. לחץ על **Create app** (צור אפליקציה).
3. הזן את הפרטים:
   - **App name:** `שמע Pro` (או `Shema Pro`)
   - **Default language:** Hebrew (he)
   - **App or game:** App
   - **Free or paid:** Free (הורדה בחינם עם מנוי In-App Billing פנימי)
4. סמן את הצהרות המדיניות ולחץ על **Create app**.

---

## 2. הגדרת המנוי השנתי (In-App Subscriptions)
כדי שהרכישה הפנימית תפעל באפליקציה:
1. בתפריט הצד, גש אל: **Monetize** ← **Subscriptions** (מנויים).
2. לחץ על **Create subscription**.
3. הזן את המזהה שהוטמע בקוד:
   - **Product ID:** `shema_pro_yearly`
   - **Name:** `מנוי שמע Pro שנתי`
4. הוסף **Base plan** (תוכנית בסיס):
   - **Type:** Auto-renewing
   - **Billing period:** 1 Year (שנה אחת)
   - **Price:** ₪99.90 (או $29.99 בחנויות בינלאומיות)
   - **Grace period:** 16 days
5. הוסף **Offer** (תקופת ניסיון חינם):
   - **Offer type:** Free trial
   - **Duration:** 14 days
6. שמור והפעל (**Activate**).

---

## 3. מילוי הצהרות מדיניות ותוכן האפליקציה (App Content)
בסרגל הצד גש אל: **Policy and programs** ← **App content**:
1. **Privacy Policy (מדיניות פרטיות):**
   - הזן את הקישור למדיניות הפרטיות (מתוך `commercial/compliance/privacy_policy.md`).
2. **Data Safety (בטיחות נתונים):**
   - מלא את הטופס בדיוק לפי ההנחיות המוכנות בקובץ:
     `commercial/compliance/data_safety_answers.md`.
3. **App Access:**
   - בחר: **All functionality is available without special access** (האפליקציה אינה דורשת שם משתמש וסיסמה כדי להיכנס).
4. **Target Audience (קהל יעד):**
   - בחר: **18 and older** (או 13 ומעלה).
5. **Government apps / Financial features:**
   - בחר: **No**.

---

## 4. עמוד החנות (Store Listing)
בסרגל הצד גש אל: **Grow** ← **Store presence** ← **Main store listing**:
1. העתק את הטקסטים המוכנים מתוך `commercial/store_assets/listing_he.md`:
   - **App name:** `שמע Pro — זיכרון קולי פרטי`
   - **Short description:** `הקלטה, תמלול עברית וסיכומי שיחות בפרטיות מוחלטת אצלך בבית, ללא ענן.`
   - **Full description:** העתק את התיאור המלא מהקובץ.
2. העלה נכסים גרפיים:
   - **App icon:** 512x512 PNG
   - **Feature graphic:** 1024x500 PNG
   - **Screenshots:** צילומי מסך מהטלפון (לפחות 4 צילומים).

---

## 5. העלאת קובץ ה-AAB והגשה לבדיקה
1. בתפריט הצד, גש אל: **Release** ← **Testing** ← **Closed testing** (או Production בחשבונות ארגוניים).
2. לחץ על **Create new release**.
3. גרור והעלה את קובץ ה-Bundle החתום:
   `C:\Users\agmon\Desktop\projects ago46\shema\commercial\dist\shema-pro-v1.0.0.aab`
4. ב-**Release notes** כתוב: `גרסה ראשונה של שמע Pro`.
5. לחץ על **Save** ואז **Review release** ← **Start rollout**.

---

> [!TIP]
> קובץ ה-AAB חתום מראש במפתח ה-Keystore הרשמי שלך ומוכן ישירות להעלאה!

## Automatic upload (no Play Console clicks)

`scripts/build_aab.ps1 -VersionName 1.0.19 -VersionCode 116 -Upload [-Status draft|completed|inProgress] [-Fraction 0.2] [-Notes "..."]`
builds the bundle and uploads it through the Play Developer API (`scripts/play_upload.py`, standard library + cryptography).
Default `-Status draft`: the release waits in Play Console for "Send for review". `completed` sends it for review
(published to everyone once approved); `inProgress` = staged rollout to `-Fraction` of users.
An existing bundle: `python scripts/play_upload.py dist/shema-pro-v1.0.18.aab --notes "..."`.

One-time setup (the account owner does this; the key never goes into the repo):
1. https://console.cloud.google.com/projectcreate -> project `shema-play`.
2. https://console.cloud.google.com/apis/library/androidpublisher.googleapis.com -> Enable (project shema-play).
3. https://console.cloud.google.com/iam-admin/serviceaccounts/create -> name `play-publisher` -> no roles -> Done.
4. The service account -> Keys -> Add key -> JSON. Save it as `C:\Users\agmon\keys\play-publisher.json`
   (or point `SHEMA_PLAY_KEY` at it).
5. Play Console -> Users and permissions -> Invite new users -> the key's `client_email` -> App permissions:
   שמע Pro -> "Release to production, exclude devices, and use Play App Signing" + "Release apps to testing tracks".
   No account permissions. New permissions can take a few hours to reach the API.
