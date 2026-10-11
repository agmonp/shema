# מדריך מילוי טופס בטיחות נתונים (Data Safety) ב-Google Play Console (מעודכן ונקי)

לפי הגדרות Google Play, **"Collected"** מוגדר כמידע שעוזב את מכשיר הטלפון.  
מאחר שנתוני המיקום והיומן נבדקים בזיכרון המכשיר בלבד לצורך השבתה מקומית ואינם נשלחים לשום מקום, אנו מסמנים אותם כ-**Not Collected**, מה שמשאיר את עמוד החנות נקי לחלוטין וללא תגיות מעקב!

---

## 1. סקירה כללית (Data collection and security)
1. **Does your app collect or share user data?**
   - בחר: **Yes**
2. **Is all user data encrypted in transit?**
   - בחר: **Yes** (העברת קבצי השמע מוצפנת ומאובטחת בטוקן מול המחשב שלך).
3. **Do you provide a way for users to request that their data is deleted?**
   - בחר: **Yes**
   - כתובת למחיקת נתונים:  
     `https://github.com/agmonp/shema/blob/main/commercial/compliance/privacy_policy.md#מחיקת-הקלטות`  
     *(או `https://agmonp.github.io/shema/privacy.html#מחיקת-הקלטות`)*

---

## 2. סוגי נתונים ספציפיים (Data types)

### א. נתוני שמע (Audio files) — הנתון היחיד שנאסף
- תחת **Audio files** ← סמן **Voice or sound recordings**:
  - **Collected?** סמן **Yes**.
  - **Shared?** סמן **No** (הנתונים נשלחים ישירות למחשב האישי של המשתמש בלבד).
  - **Ephemeral?** סמן **No** (השמע נשמר במחשב לפי מדיניות המשתמש).
  - **Required or Optional?** סמן **Data collection is required** (האזנה ותמלול הם הפיצ'ר המרכזי של האפליקציה).
  - **Purposes (מטרות):** סמן **App functionality** (פונקציונליות האפליקציה).

### ב. כל שאר הקטגוריות:
- **Location:** סמן **No** (מעובד On-device בלבד, אינו עוזב את הטלפון).
- **Calendar:** סמן **No** (מעובד On-device בלבד, אינו עוזב את הטלפון).
- **Personal info / Photos / Contacts / Files:** סמן **No**.
- **Financial info:** סמן **No** (הרכישות מטופלות ישירות על ידי Google Play Billing).
