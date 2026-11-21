import type { ReactNode } from 'react'
import {
  AudioWaveform, Users, ListChecks, Languages, Lock, Search, Smartphone, Laptop,
  Scissors, Ear, Sunset, Star, TrendingUp, CloudOff, KeyRound, type LucideIcon,
} from 'lucide-react'
import DownloadButtons, { useReleaseMeta } from './DownloadButtons'
import AudioDemo from './AudioDemo'
import { CLASSIC_URL, PRICE_YEAR, PRIVACY_URL, SITE_URL, SOURCE_URL, SUPPORT_URL, TRIAL_DAYS, GOOGLE_PLAY_URL } from '../config'

const ICON = { size: 26, strokeWidth: 1.25 } as const

function Tag({ children }: { children: ReactNode }) {
  return (
    <span className="hairline inline-flex items-center gap-2.5 rounded-full px-3.5 py-1 text-[12px] tracking-[.08em] text-mute">
      <span className="h-1 w-1 rounded-full bg-gold" />
      {children}
    </span>
  )
}

function H2({ a, b, className = '' }: { a: string; b: string; className?: string }) {
  return (
    <h2 className={`mt-6 font-display text-[clamp(34px,4.6vw,60px)] font-medium leading-[1.06] tracking-[-0.02em] text-bone ${className}`}>
      {a}<br /><span className="font-light text-bone/45">{b}</span>
    </h2>
  )
}

/** Bento cell: elevated surface, top-edge light, generous padding, a thin icon without a box. */
function Cell({ icon: Icon, title, children, className = '', accent = false }: {
  icon?: LucideIcon; title?: string; children?: ReactNode; className?: string; accent?: boolean
}) {
  return (
    <article data-reveal data-dense className={`surface flex flex-col rounded-[28px] p-7 md:p-9 ${className}`}>
      {Icon && <Icon {...ICON} className={accent ? 'text-gold' : 'text-bone/70'} aria-hidden="true" />}
      {title && <h3 className={`${Icon ? 'mt-6' : ''} font-display text-[21px] font-medium tracking-tight text-bone`}>{title}</h3>}
      {children}
    </article>
  )
}
const P = ({ children }: { children: ReactNode }) => <p className="mt-2.5 text-[15px] leading-relaxed text-mute">{children}</p>

// ---------------------------------------------------------------- 1. Hero
export function Hero() {
  const meta = useReleaseMeta()
  return (
    <section id="top" data-stage className="relative flex min-h-[100svh] items-end pb-16 pt-20 md:items-center md:pb-0">
      <div className="mx-auto grid w-full max-w-6xl px-4 md:grid-cols-[1.25fr_1fr] md:px-8">
        <div className="pt-[22vh] md:pt-0">
          <div data-hero><Tag>זיכרון קולי פרטי · תמלול עברית על המחשב שלך</Tag></div>
          <h1 className="mt-7 font-display text-[clamp(42px,6.6vw,86px)] leading-[1.02] tracking-[-0.03em] text-bone">
            <span data-hero className="block font-semibold">להקשיב לעומק.</span>
            <span data-hero className="block font-normal text-bone/70">לסכם בשנייה.</span>
            <span data-hero className="block font-light text-bone/45">לצמוח מכל שיחה.</span>
          </h1>
          <p data-hero className="mt-7 max-w-[34rem] text-[17px] leading-relaxed text-mute md:text-[18px]">
            שמע מקליט בטלפון, מתמלל בעברית ומסכם על המחשב שלכם, בלי ענן.
            פגישות עבודה הופכות להחלטות ומשימות. שיחות היום־יום הופכות לתובנות עליכם.
          </p>
          <div data-hero id="hero-cta" className="mt-9">
            <DownloadButtons />
            <p className="mt-4 text-[13px] text-mute">
              {meta && <>גרסה <bdi>{meta.ver}</bdi> · <bdi>{meta.mb}</bdi> · </>}{TRIAL_DAYS} ימי ניסיון חינם · אחר כך {PRICE_YEAR} לשנה
            </p>
          </div>
        </div>
      </div>
      <a href="#clarity" className="absolute bottom-7 left-1/2 hidden -translate-x-1/2 flex-col items-center gap-2 text-[11px] tracking-[.24em] text-mute md:flex" aria-label="גללו למטה">
        גללו
        <span className="h-10 w-px bg-gradient-to-b from-bone/40 to-transparent" />
      </a>
    </section>
  )
}

// ---------------------------------------------------------------- 2. Noise -> clarity (asymmetric bento)
export function Clarity() {
  return (
    <section id="clarity" data-stage className="relative px-4 py-28 md:px-8 md:py-44">
      <div className="mx-auto max-w-6xl">
        <div data-reveal data-dense className="max-w-xl max-md:surface max-md:rounded-[28px] max-md:p-6 md:pb-[22vh]">
          <Tag>מרעש לבהירות</Tag>
          <H2 a="דיבור חופשי נכנס." b="מבנה ברור יוצא." />
          <p className="mt-6 text-[17px] leading-relaxed text-mute">
            שיחה אמיתית היא בלגן: אנשים מדברים יחד, קופצים בין נושאים, וחצי מהחשוב נאמר בדרך אגב. שמע מסדר אותה.
          </p>
        </div>

        <div className="mt-[30vh] grid gap-4 md:mt-16 md:grid-cols-6">
          <Cell icon={AudioWaveform} title="תמלול עברית, על המחשב שלכם" className="md:col-span-4 md:row-span-2">
            <P>מודל מבוסס ivrit.ai שמותאם לעברית מדוברת רץ אצלכם. בלי חיוב לפי דקה, בלי שליחה החוצה.</P>
            <div className="mt-auto space-y-3 pt-10 text-[14px]">
              {[
                ['09:41', 'מיכל', 'בואו נעבור על הלו״ז של הרבעון'],
                ['09:41', 'אורי', 'הגרסה לבטא צריכה לצאת עד ה-15'],
                ['09:42', 'מיכל', 'אז ננעל פיצ׳רים ביום חמישי'],
              ].map(([tm, who, line]) => (
                <p key={line} className="flex items-baseline gap-4 border-t border-white/[.05] pt-3">
                  <span className="tabular-nums text-[12px] text-mute/70" dir="ltr">{tm}</span>
                  <span className="w-10 shrink-0 text-[12px] text-gold">{who}</span>
                  <span className="text-bone/80">{line}</span>
                </p>
              ))}
            </div>
          </Cell>
          <Cell icon={Users} title="מי אמר מה" className="md:col-span-2">
            <P>מלמדים את שמע קול פעם אחת, והוא משייך משפטים לאנשים בכל השיחות הבאות.</P>
          </Cell>
          <Cell icon={Ear} title="בלי רעש ושקט" className="md:col-span-2">
            <P>הטלפון מזהה דיבור בעצמו ומשמיט שתיקות, טלוויזיה ורעשי רקע לפני שהוא שולח משהו.</P>
          </Cell>
          <Cell icon={ListChecks} title="רק מה שחשוב" accent className="md:col-span-6">
            <div className="mt-3 grid gap-x-10 gap-y-2 text-[15px] text-mute md:grid-cols-[1fr_1fr_1fr]">
              <p>כותרת ועיקרי הדברים, בכמה שורות.</p>
              <p>מי התחייב למה, ועד מתי.</p>
              <p>משימות שאפשר לסמן כבוצעו.</p>
            </div>
          </Cell>
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- 3. Business + live demo (core on the right)
export function Business() {
  return (
    <section id="business" data-stage className="relative px-4 py-28 md:px-8 md:py-40">
      <div className="mx-auto grid max-w-6xl items-start gap-10 md:grid-cols-[1fr_1.2fr]">
        <div className="hidden md:block" />
        <div className="pt-[30vh] md:pt-0">
          <div data-reveal data-dense className="max-md:surface max-md:rounded-[28px] max-md:p-6">
            <Tag>עסקי ועבודה</Tag>
            <H2 a="הפגישה נגמרת." b="הסיכום כבר מוכן." />
            <p className="mt-6 max-w-xl text-[17px] leading-relaxed text-mute">
              לוחצים "הקלט פגישה" במחשב או בטלפון. בסוף מחכים לכם סיכום מנהלים, החלטות ומשימות עם שם של מי שאחראי.
              צריך רק חלק? בוחרים משפט פתיחה ומשפט סוף ומקבלים סיכום וקובץ שמע של הקטע הזה בלבד.
            </p>
          </div>
          <div data-reveal className="mt-10"><AudioDemo /></div>
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- 4. Personal growth (warm shift, core on the left)
const ME = [
  { label: 'הקשבה', value: '58%', note: 'מהזמן בשיחות הקשבתם', bar: 0.58 },
  { label: 'טון חיובי', value: '+12%', note: 'לעומת השבוע שעבר', bar: 0.72 },
  { label: 'מילים חדשות', value: '34', note: 'שלא אמרתם החודש', bar: 0.4 },
]

export function Personal() {
  return (
    <section id="personal" data-stage className="relative px-4 py-28 md:px-8 md:py-44">
      <div className="mx-auto grid max-w-6xl items-start gap-12 md:grid-cols-[1.15fr_1fr]">
        <div className="pt-[30vh] md:pt-0">
          <div data-reveal data-dense className="max-md:surface max-md:rounded-[28px] max-md:p-6">
            <Tag>אישי ושיפור אישי</Tag>
            <H2 a="לשמוע את עצמכם." b="ולצמוח מזה." />
            <p className="mt-6 max-w-xl text-[17px] leading-relaxed text-mute">
              בלשונית "אני" שמע מראה לכם איך אתם מדברים: כמה הקשבתם, באיזה טון, אילו מילים חוזרות,
              ועם מי השיחות שלכם הכי טובות. לפי יום, שבוע וחודש. בלי שיפוט, רק תמונה בהירה.
            </p>
          </div>

          <div className="mt-10 grid gap-4 sm:grid-cols-5">
            <Cell className="sm:col-span-3">
              <div className="flex items-baseline justify-between">
                <p className="font-display text-[19px] font-medium text-bone">השבוע שלי</p>
                <span className="text-[11px] text-mute/70">דוגמה להמחשה</span>
              </div>
              <div className="mt-7 space-y-6">
                {ME.map((m) => (
                  <div key={m.label}>
                    <div className="flex items-baseline justify-between">
                      <span className="text-[14px] text-mute">{m.label}</span>
                      <span className="font-display text-[22px] font-light tabular-nums text-bone" dir="ltr">{m.value}</span>
                    </div>
                    <div className="mt-2 h-px bg-white/10">
                      <div data-bar className="h-px origin-right bg-gold" style={{ width: `${m.bar * 100}%` }} />
                    </div>
                    <p className="mt-1.5 text-[12px] text-mute/70">{m.note}</p>
                  </div>
                ))}
              </div>
            </Cell>
            <div className="grid gap-4 sm:col-span-2">
              <Cell icon={Sunset} accent>
                <p className="mt-5 text-[15px] leading-relaxed text-bone/85">בשיחות ערב עם המשפחה הקשבתם יותר, והטון היה רך יותר מבבוקר.</p>
              </Cell>
              <Cell icon={TrendingUp}>
                <p className="mt-5 text-[15px] leading-relaxed text-mute">מגמות לאורך שבועות, ותמונה לפי כל אדם.</p>
              </Cell>
            </div>
          </div>
        </div>
        <div className="hidden md:block" />
      </div>
    </section>
  )
}

/** Phone -> home network (pairing key) -> PC, with the cloud crossed out above the path. */
function PrivacyFlow() {
  const node = (Icon: LucideIcon, label: string, sub: string, gold = false) => (
    <div className="flex flex-col items-center gap-3 text-center">
      <div className={`grid h-16 w-16 place-items-center rounded-full border ${gold ? 'border-gold/45' : 'border-white/[.14]'} bg-obsidian/60`}>
        <Icon size={24} strokeWidth={1.25} className={gold ? 'text-gold' : 'text-bone/80'} aria-hidden="true" />
      </div>
      <div>
        <p className="text-[13px] text-bone/90">{label}</p>
        <p className="mt-0.5 text-[11.5px] text-mute">{sub}</p>
      </div>
    </div>
  )
  const link = (
    <div className="relative mt-8 flex-1 border-t border-dashed border-gold/55">
      <span className="absolute left-0 top-1/2 h-1.5 w-1.5 -translate-y-1/2 rotate-45 border-b border-l border-gold/70" />
    </div>
  )
  return (
    <figure className="my-10 md:my-12" aria-label="ההקלטות עוברות מהטלפון למחשב שלכם ברשת הביתית, בלי ענן">
      <div className="mb-6 flex items-center justify-center gap-2 text-[12px] text-mute">
        <CloudOff size={16} strokeWidth={1.25} aria-hidden="true" />
        <span className="tracking-[.12em]">בלי ענן באמצע</span>
      </div>
      <div className="flex items-start justify-between gap-3">
        {node(Smartphone, 'טלפון', 'מקליט ומסנן')}
        {link}
        {node(KeyRound, 'רשת הבית', 'מפתח צימוד', true)}
        {link}
        {node(Laptop, 'המחשב שלכם', 'מתמלל ושומר')}
      </div>
    </figure>
  )
}

// ---------------------------------------------------------------- 5. Bento + final download
export function Features() {
  return (
    <section id="features" data-stage className="relative px-4 pb-10 pt-28 md:px-8 md:pt-44">
      <div className="mx-auto max-w-6xl">
        <div data-reveal className="max-w-xl">
          <Tag>הכל במקום אחד</Tag>
          <H2 a="בנוי לשקט נפשי." b="ולעבודה של כל יום." />
        </div>

        <div className="mt-14 grid gap-4 md:grid-cols-6">
          <Cell icon={Lock} accent title="פרטי מהיסוד. אפס ענן." className="md:col-span-4 md:row-span-2">
            <P>
              ההקלטות, התמלילים, חתימות הקול והסיכומים נשמרים רק במחשב שלכם. כל מודלי ה-AI רצים אצלכם.
              לשמע אין שרת ענן שמקבל את המידע שלכם.
            </P>
            <PrivacyFlow />
            <div className="mt-auto flex flex-wrap gap-2 pt-8 text-[13px] text-bone/70">
              {['פרטי לשעה', 'אזורים פרטיים', 'לא להקליט אדם מסוים', 'מחיקה בלחיצה'].map((p) => (
                <span key={p} className="hairline rounded-full px-3.5 py-1.5">{p}</span>
              ))}
            </div>
          </Cell>
          <Cell icon={Languages} title="עברית מדוברת" className="md:col-span-2">
            <P>תמלול שמותאם לעברית של היום־יום, עם דוברים וחותמות זמן. בלי הגבלת דקות.</P>
          </Cell>
          <Cell icon={Search} title="חפשו ושאלו" className="md:col-span-2">
            <div className="mt-5 space-y-2 text-[14px]">
              <p className="me-auto w-fit rounded-2xl bg-white/[.05] px-3.5 py-2 text-bone/85">מתי הבטחתי לשלוח את המסמך?</p>
              <p className="ms-auto w-fit rounded-2xl border border-gold/25 px-3.5 py-2 text-bone/85">ביום שלישי, בשיחה עם רון: "עד סוף השבוע".</p>
            </div>
          </Cell>
          <Cell className="md:col-span-3">
            <div className="flex items-center gap-3 text-bone/70">
              <Smartphone {...ICON} aria-hidden="true" />
              <span className="h-px w-8 bg-gradient-to-l from-gold/70 to-transparent" />
              <Laptop {...ICON} aria-hidden="true" />
            </div>
            <h3 className="mt-6 font-display text-[21px] font-medium tracking-tight text-bone">טלפון ומחשב, מחוברים</h3>
            <P>מחברים ב-QR ברשת הביתית. מחוץ לבית הטלפון שומר בתור ומעביר כשחוזרים, או מסנכרן דרך Tailscale.</P>
          </Cell>
          <Cell icon={Scissors} title="רק החלק שחשוב" className="md:col-span-3">
            <P>בוחרים קטע מתוך שיחה ומקבלים סיכום וקובץ שמע שלו. או משתפים משפט אחד.</P>
            <p className="mt-4 flex items-center gap-2 text-[13px] text-mute"><Star size={15} strokeWidth={1.25} className="text-gold" /> רגע שסימנתם נשמר לתמיד</p>
          </Cell>
          <Cell className="md:col-span-6 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="font-display text-[34px] font-light tracking-tight text-bone">{PRICE_YEAR} <span className="text-[16px] text-mute">לשנה</span></p>
              <p className="mt-1 text-[15px] text-mute">{TRIAL_DAYS} ימי ניסיון חינם מלאים. ניהול המנוי דרך Google Play, ביטול בכל רגע.</p>
            </div>
            <a href={GOOGLE_PLAY_URL} target="_blank" rel="noopener noreferrer" className="mt-6 w-fit rounded-full border border-gold/50 px-6 py-3 text-[15px] text-gold transition hover:bg-gold hover:text-obsidian md:mt-0">
              להתחיל ניסיון חינם
            </a>
          </Cell>
        </div>

        {/* final download hub */}
        <div id="download" className="relative mt-36 pb-24 text-center md:mt-56">
          <div data-reveal>
            <h2 className="mx-auto max-w-3xl font-display text-[clamp(40px,6.4vw,80px)] font-medium leading-[1.04] tracking-[-0.03em] text-bone">
              מוכנים לשמוע<br /><span className="font-light text-bone/45">את התמונה המלאה?</span>
            </h2>
            <p className="mx-auto mt-6 max-w-xl text-[17px] text-mute">שלושה צעדים: מתקינים במחשב, מתקינים בטלפון, וסורקים QR.</p>
            <DownloadButtons className="mt-10 justify-center" />
          </div>
        </div>
      </div>
    </section>
  )
}

export function Footer() {
  return (
    <footer className="relative border-t border-white/[.06] px-4 py-8 text-[13px] text-mute md:px-8">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 md:flex-row">
        <p>© 2026 שמע · <a href={SITE_URL} className="hover:text-bone" dir="ltr">shema.agmonp.com</a></p>
        <nav className="flex flex-wrap justify-center gap-x-6 gap-y-2">
          <a href={PRIVACY_URL} className="hover:text-bone">מדיניות פרטיות</a>
          <a href={CLASSIC_URL} className="hover:text-bone">שאלות נפוצות ופרטים</a>
          <a href={SUPPORT_URL} target="_blank" rel="noopener noreferrer" className="hover:text-bone">יצירת קשר ותמיכה</a>
          <a href={SOURCE_URL} target="_blank" rel="noopener noreferrer" className="hover:text-bone">קוד מקור</a>
        </nav>
      </div>
    </footer>
  )
}
