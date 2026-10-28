package com.shema.app

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.SystemClock

/** Phone restarted / app updated: listening was stopped. Android 14+ forbids starting a microphone
 *  service from here, so ask the user with one tap (the tap opens the app, which starts it).
 *
 *  Play's Android 15 check resolves any lambda / Runnable / thread call reachable from here to every such function in
 *  the app (MainActivity's "start" included), so this file calls only Android's own APIs: the reminders are re-armed a
 *  minute later by ReminderReceiver (named by string, not ReminderReceiver::class), and Prefs is read directly.
 *  1.0.17-1.0.20 were flagged through Reminders.rearm (lambdas + a thread) and a MainActivity::class intent. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, i: Intent) {
        // alarms do not survive a restart / update: ReminderReceiver re-arms them
        val rearm = Intent(REARM).setComponent(ComponentName(c.packageName, "com.shema.app.ReminderReceiver"))
        c.getSystemService(AlarmManager::class.java).set(AlarmManager.ELAPSED_REALTIME, SystemClock.elapsedRealtime() + 60_000,
            PendingIntent.getBroadcast(c, 9, rearm, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
        if (!c.getSharedPreferences("home_pro", Context.MODE_PRIVATE).getBoolean("wanted", false)) return   // Prefs.wanted
        askToStart(c)
    }

    companion object {
        const val REARM = "com.shema.app.REARM"

        /** one tap opens the app, which starts listening (an activity may start a microphone service).
         *  The launcher intent, not MainActivity::class: Play's Android 15 check follows a class reference from boot
         *  code into MainActivity -> startForegroundService(ListenService) and flags it (1.0.17 / 1.0.18). */
        fun askToStart(c: Context, why: String = "הטלפון הופעל מחדש") {
            val nm = c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(NotificationChannel("restart", "הפעלה מחדש", NotificationManager.IMPORTANCE_HIGH))
            val launch = c.packageManager.getLaunchIntentForPackage(c.packageName) ?: return
            val open = PendingIntent.getActivity(c, 0, launch, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            nm.notify(2, Notification.Builder(c, "restart")
                .setSmallIcon(R.drawable.ic_stat)
                .setContentTitle("שמע Pro כבוי")
                .setContentText("$why. הקש כדי להתחיל להקשיב.")
                .setContentIntent(open).setAutoCancel(true).build())
        }
    }
}
