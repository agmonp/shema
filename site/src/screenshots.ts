// Real screenshots of Shema, served from the repo's docs/ folder (the same files the old page used).
const BASE = 'https://raw.githubusercontent.com/agmonp/shema/main/docs/'

export type Shot = { src: string; title: string; caption: string; w: number; h: number }

export const DESKTOP_SCREENSHOTS: Shot[] = [
  { src: BASE + 'pc-day.png', title: 'היום ושיחות', caption: 'סיכום יומי וציר זמן של כל השיחות, עם מי ומתי.', w: 1100, h: 1260 },
  { src: BASE + 'pc-conversation.png', title: 'שיחה אחת', caption: 'תמלול מלא עם שמות הדוברים, סיכום, החלטות ומשימות.', w: 1100, h: 1290 },
  { src: BASE + 'pc-search.png', title: 'חיפוש ומשימות', caption: 'חיפוש חופשי ושאלות על כל מה שנאמר, לפי תאריכים.', w: 1100, h: 1100 },
  { src: BASE + 'pc-teach.png', title: 'ללמד קולות', caption: 'משייכים משפט קצר לאדם, ושמע לומד לזהות את הקול.', w: 1100, h: 820 },
  { src: BASE + 'pc-people.png', title: 'אנשים', caption: 'זמני דיבור, שותפים לשיחה ומגמות לאורך זמן.', w: 1100, h: 800 },
  { src: BASE + 'pc-privacy.png', title: 'פרטיות', caption: 'מה נשמר, מה נמחק, ומי ביקש לא להיות מוקלט.', w: 1100, h: 1080 },
]

export const MOBILE_SCREENSHOTS: Shot[] = [
  { src: BASE + 'phone-segment-pick.png', title: 'בוחרים קטע', caption: 'משפט פתיחה ומשפט סוף, וכל גבול זז ב־5 שניות.', w: 540, h: 1110 },
  { src: BASE + 'phone-segment-summary.png', title: 'סיכום של הקטע', caption: 'סיכום רק של מה שנאמר בקטע, עם שמות הדוברים.', w: 540, h: 1110 },
  { src: BASE + 'phone-line-share.png', title: 'משפט אחד', caption: 'מתקנים מי אמר, או משתפים את הסאונד של השורה.', w: 540, h: 1110 },
]
